# Relay efficiency

A poll cycle must spend its round trips on questions it has not already
answered. When this was written, roughly half of them were spent re-asking.

The plan is written from one live two-client session (A on 8501, B on 8502,
both against the same SFTP relay, traced at `timing` level for 22 minutes on
2026-08-16). Every number is measured, not estimated, and every redundancy named
here is reproduced by a test in `tests/test_relay_efficiency.py`.

**All seven steps have landed.** An idle cycle went from `2 + 4 × topics`
logical relay operations to `2 + topics` — 14 to 5 at three topics — and an
acknowledgement from four operations rewriting the whole subtree to one head
write. On the link this was written from, that is 17 SFTP operations per quiet
cycle down to 6, and 56 % of wall clock inside SFTP down to about a fifth
(*Measured afterwards*, under Sequencing). The sections below are kept as they
were argued, each with what it actually cost and what it turned up; step 7
records why the mechanism it specified was dropped in favour of one that was
already there.

## What the session cost

The link's single round trip is **22 ms** (a bare `stat`). Every logical relay
operation is a multiple of it: `_read_json` and `_list_dir` ~90 ms, `_write_json`
and `write_presence` ~140–200 ms.

| | A8501 | B8502 |
|---|---|---|
| poll cycles traced | 423 | 62 (then blind, see step 1) |
| SFTP operations per cycle | 16.5 | 14.8 |
| wall-clock time inside SFTP | **56 %** | **59 %** |

An idle cycle carrying three topics and one peer is 17 SFTP operations and
1.35 s of a 3 s budget, with nothing to say and nothing to hear.

Expressed in backend-independent terms — what `tests/test_relay_efficiency.py`
counts — an idle cycle costs:

> **2 + 4 × topics** logical relay operations per peer.

per topic: two `list_peers` (one of them redundant), one `read_head` for our own
slot, and one `read_head_with_mtime` per peer. This is linear in
topics × peers with no index anywhere in it. Ten topics and five peers would
need ~75 operations ≈ 6.8 s, and the client would never hold a 3 s cadence
again.

## What already works

Nothing below should be read as "sync is broken". The session shows the
protocol doing exactly what it is designed to do:

- Four card moves propagated end to end in **1.5 s, 2.0 s, 2.9 s** (the fourth
  was held for a decision, correctly — see below). `publish_once` got each edit
  off the machine in 0.69–1.0 s without waiting for an inbound poll.
- Poll preceded publish in every one of 423 cycles; the sibling check ran
  before every `publish_once`.
- Zero `ok=False`, zero reconnects, zero snapshot races, zero deferred
  publications, zero sibling alarms, zero missing blobs.
- The one held adoption was `not_member` refusing a card its user participates
  in (`s-initiative/src/s_initiative/logic.py:982`), adopted by hand 14 s later.
  Declared handling working as specified.
- The acknowledgement protocol terminates: `ack_requested` is false for
  observation-only heads (`relay_logic.py:1322`), so there is no ack-of-ack
  loop. A single change settles and then costs nothing.

The work below is about cost, not correctness — with one exception, which is
first because it is the one that hides everything else.

## Step 1 — Transport reporting must survive a storage swap — **done**

**B stopped emitting every transport event at 22:08:17 and never resumed.**
Cycles continued normally for another 203 iterations, phases still showed
~1.3 s of I/O each, and not one `relay.sftp_operation` line was written.

`_report_transport_events()` (`relay_logic.py:331`) is called from exactly one
place: `RelayLogic.__init__`. Two paths install a *different* storage object and
never re-wire it:

- `relay_logic.py:2216` — `ensure_connection`, existing-connection branch:
  `existing.storage = storage`, where `storage` is a freshly built
  `SftpRelayStorage` whose `on_event` is `None`.
- `relay_logic.py:414` — `_install_adopted_storage`, when reached from
  `adopt_storage_from_descriptor`, which builds a new storage at
  `relay_logic.py:407`.

Reproduced directly: construct a `RelayManager` whose flat config names the same
relay as a registered target, and `primary.storage.on_event` is already `None`
before the first poll — `RelayManager.__init__` bootstraps its registry and then
calls `ensure_connection` for every target (`relay_logic.py:2058`), which finds
the primary by fingerprint and swaps its storage out. In the live session A
survived because its flat config named no relay, so its target got a brand-new
`RelayLogic` (constructor path, callback wired); B lost the callback when
joining the board re-ensured an existing connection.

This is not only a tracing loss. `relay.sftp_reconnect` (`relay_storage.py:820`)
travels through the same callback and is an **events-level, always-on**
diagnostic. Every client that has ever accepted a token or re-keyed a target is
permanently blind to dropped SSH connections — precisely the clients most in
need of diagnosis. Any conclusion drawn from a trace missing this callback is
unsound, which is why this step comes before the measurement work.

**Change.** One assignment point for storage: `_set_storage(storage)`, ending in
`self._report_transport_events()`, called from `__init__`,
`_install_adopted_storage`, `ensure_connection`'s existing branch, and
`_retire_connection`. `MailboxChannel.close` still assigns directly and should:
it marks a closed resource rather than installing a backend, and it works on a
duck-typed connection that should not have to be a `RelayLogic`.

**Result.** All three swap paths report; before the change none of them did,
including a `RelayManager` at boot whose flat config names a registered target.

## Step 2 — List a topic's peers once per cycle — **done**

`poll_and_apply` lists `topics/<t>/peers` at `relay_logic.py:1525`.
`publish_due_topics` → `_relay_holds_our_publication` lists the *same* directory
again at `relay_logic.py:1234`, in the same cycle, to compute
`self.identity in listed_peer_ids` — a value the first listing already returned.

Three topics, three duplicate listings, ~280 ms per cycle: **20 % of the cycle
spent re-reading a directory nothing has written to in the meantime.**

`_relay_holds_our_publication` exists for a real reason (`relay_logic.py:1211`
documents the wiped-relay case) and that reason survives intact: the answer is
still taken from the relay, just from the listing this cycle already performed.

**Change.** `poll_once` owns a `peer_listings` dict for the duration of one
cycle and hands it to `poll_and_apply`, which fills it, and to
`publish_due_topics`, which passes it down to `_relay_holds_our_publication`. A
local rather than a field on purpose: `publish_once` and a UI request can run
their own publication concurrently with a cycle, and they must ask the relay
themselves rather than inherit an answer from whatever cycle is in flight. A
topic the poll did not visit falls back to a fresh listing, so the guarantee is
unchanged.

**Result.** Idle cycle 14 → **11** operations at three topics, as measured by
`test_an_idle_cycle_costs_a_fixed_amount_plus_a_charge_per_topic`.

## Step 3 — Never fetch a snapshot of our own state — **done**

**Eleven of A's twelve snapshot downloads were of a state hash A had published
itself.** When B adopts A's change, B's content hash becomes A's hash and B
republishes it as new content; A then downloads a full board snapshot that is
byte-identical to what it already holds, deep-copies it, applies it, and runs a
reconcile pass over it.

The guard at `relay_logic.py:1696` compares the peer's head against
`applied[topic][peer]` — what we last took *from that peer* — and never against
our own `node_state_hash(topic_uuid)`. But the hash **is** content identity:
equal hash means there is nothing to fetch and nothing to apply.

**Change.** Where the snapshot was fetched, the payload is instead taken from
`session.get_subtree(topic_uuid)` when the head names our own hash. Everything
downstream is untouched — same envelope shape, same `apply_peer_subtree`, same
observation recording, same `applied` bookkeeping, same `after_apply` — so the
peer cache ends up holding exactly what a fetch would have produced, which the
test asserts by hash rather than by inspection.

Only when the peer is already cached. The envelope also says *where* the peer
keeps this topic, and our own copy can only answer that for a peer whose mount
point we have already seen; first contact still fetches. On the traced session
that leaves ten of twelve snapshot reads removed, one per card move per side,
along with the deep copy and reconcile pass each carried.

**Note for step 6.** The snapshot-race check is now reached only on the fetch
path, which is the only path that can race. That is the correct home for it, and
it is where the `payload_seq > publication_seq` relaxation described in step 6
will have to go.

**Result.** `test_a_peer_head_matching_our_own_state_costs_no_snapshot_read`
green: the echo round trip costs zero snapshot reads and both sides still
converge. One test in `s-initiative` had to change with it — see below.

## Step 4 — One round trip per file read — **done**

`read_head_with_mtime` and `read_presence_with_mtime` each issued a `_read_json`
followed by a separate `_stat_mtime`. Paramiko returns both from one visit:
`sftp.open(...)` then `SFTPFile.stat()` on the open handle. This is the same
saving `write_presence` already documents and takes — "one round trip fewer than
write-then-stat" — applied to the read side.

Both backends now have `_read_json_with_mtime`, and the two callers go through
it. Beyond the round trip, it is the only way the pair is coherent: a separate
stat can describe a version the read did not see, and this mtime decides both
how stale a peer's perspective looks and — after step 5 — whether its head is
read again at all.

**Acceptance.** `OneVisitPerFileTests`, against a recording SFTP client: a head
read and a heartbeat read each issue one `open` and one `fstat` on the handle,
no path `stat`; a missing file answers without a second lookup.

## Step 5 — Skip heads that cannot have changed — **done**

`_list_dir` called `listdir_attr` and threw away everything except the directory
names. It already had each peer directory's `st_mtime` in hand, and a
`posix_rename` of `head.json` into that directory bumps it. **The information
needed to skip an unchanged head read was already being downloaded and
discarded.**

`list_peers_with_mtimes` keeps it. `poll_and_apply` records, per topic and peer,
the slot mtime whose head it has taken; an unchanged mtime next cycle means an
unchanged head, and the head is not read. A peer's head is no longer read on an
idle cycle at all: **`2 + 2 × topics`, measured — 8 operations at three topics,
down from 14.**

Two things had to be got right, and both are the kind that fail silently.

**The clock's resolution is part of the inference.** SFTP reports mtimes in
whole seconds (`mtime_resolution_seconds = 1.0`), so a write landing in the same
second as the one just observed leaves the slot looking untouched — and the
peer's change would be dropped, and keep being dropped until something else
wrote into that slot. So a slot may only be settled once its timestamp is
already older than the resolution, at which point any further write must land in
a later second and must therefore show. Before the server clock is calibrated,
nothing settles and every head is read, which is merely the old cost.

**An unchanged slot is not the same as nothing left to do.** A topic that
arrived before this client could mount it is parked as a pending invitation and
has to be offered again on the next poll — which is why the unchanged-hash
short-circuit has always been conditioned on `not wants_graft`. Settling the
slot bypassed that test one level higher up, and a subteam admitted later never
appeared; s-team caught it. A slot with a graft still pending is never settled.

Freshness still moves while a slot is quiet: `source_age_seconds` is derived
from the settled head's mtime, so a silent peer goes stale on schedule without
being asked again.

**Acceptance.** `SilenceIsOnlyTrustedWhenItIsProofTests` — a head written
between cycles is still read; a backend whose clock cannot resolve the interval
never settles anything; a returning peer whose slot reappears is read again; a
topic waiting to be grafted keeps being offered. Plus the budget test.

## Step 6 — An acknowledgement should not rewrite a subtree — **done**

Seven of A's sixteen board publications carried no content change
(`ack_requested: false`) — pure "I saw your seq N" bookkeeping. Each one still
pays the whole `write_snapshot` path: read head, write the entire subtree, write
head, gc listing (`relay_storage.py:402`) — four operations where two would do.

**And the cost is the smaller half of it.** Rewriting the subtree makes a
snapshot file *mutable under a fixed hash*, and that is the only thing that
makes `relay.publication_snapshot_race` reachable at all. The session run after
steps 1-3 landed caught it twice, on B's first cycle after a restart:

```
A  05:48:44.844  publication_published  board  seq 27  ack_requested=False  hash 4f89d90282
B  05:48:44.905  publication_snapshot_race     head_seq 26  snapshot_seq 27  hash 4f89d90282
```

B read the head at generation 26, A's acknowledgement rewrote the *same-hash*
snapshot 61 ms later, and B's snapshot read landed on generation 27. The team
topic repeated it 20 ms apart in the same cycle. Nothing was lost - the guard
skipped, and the next cycle cached both (`seq 27` at 05:48:46.954, `seq 34` at
05:48:47.491, about two seconds) - but a client that has just started is
precisely the one doing the most fetching, and it is the one that meets this.

A content-addressed file should never change. Once the head can advance without
the snapshot, `snapshots/<hash>.json` is immutable by construction and this race
cannot arise from an acknowledgement at all. That is the real argument for this
step; the four saved operations are a bonus.

The obstacle was that the head's metadata was smuggled through the snapshot
payload. `_relay_observed`, `_relay_observed_publications`,
`_relay_ack_publication_seq` and `_relay_ack_requested` were written into every
snapshot **solely so `write_snapshot` could copy them into `head.json`**. The
only field ever read back out of a downloaded snapshot was
`_relay_publication_seq`, and the only thing reading it was the race check that
existed because of it.

**What changed.** `head_document()` builds the head from a `publication`
argument, and both backends take it. `write_head()` writes that head without the
subtree, and `publish_due_topics` routes to it when the content has not changed.
A snapshot is now a pure function of the hash it is named after.

**The race check is gone rather than relaxed.** The plan called for weakening it
to `payload_seq > publication_seq`. That was the right fix for a mutable
snapshot; with an immutable one there is nothing left to check. `snapshots/<hash>.json`
is written once and never rewritten, so the file a head names either holds that
hash's content or is not there — and "not there" was already handled on the next
line. Keeping a check that can no longer fire would have left the reason for it
unrecorded and the code lying about the risk.

**One thing the routing has to get right, found by the tests.** "Content did not
change" is not the same as "the snapshot is on the relay". After a wipe, or a
withdrawn publication, local bookkeeping still says the content is published
while the relay holds neither head nor snapshot — and a head-only write would
name a snapshot that is not there. So the head-only path is taken only when the
relay was confirmed to still hold our slot this cycle, which
`_relay_holds_our_publication` already establishes for the skip decision just
above. `test_relay_authority` caught both cases.

**Acceptance.** `test_an_acknowledgement_does_not_rewrite_the_subtree` (no
longer `expectedFailure`); `test_one_change_costs_one_subtree_write_and_one_acknowledgement`
— the author writes its subtree once and the peer answers with a head and
nothing else; `test_a_peer_arriving_after_an_acknowledgement_still_gets_the_topic`
— the head an acknowledgement leaves behind still names a snapshot that is
there. Confirmed live: no `relay.publication_snapshot_race` in a traced restart,
where two had fired before this step (see *Measured afterwards*).

## Step 7 — The last head read — **done, by other means**

This step was written as "presence as a manifest": give
`identities/<peer>/presence.json` a `topic_heads` map so one presence read
answers "has anything changed anywhere" and no head is read on an idle cycle.
Target, `2 + topics`.

**The target is met. The manifest is not what met it, and should not be built.**

Step 5 had already removed every peer head read, using the slot mtime the peer
listing carries. What remained at `2 + 2 × topics` was one listing and *our own*
slot's head per topic — the sibling rule's read, deliberately left alone then.
It is now skipped on exactly the same evidence: a sibling writes into that slot
the way anyone writes theirs, so the listing shows it. That is the whole of this
step, and it lands the budget at **`2 + topics` — 5 operations at three topics,
measured, down from 14.**

Three reasons the manifest was dropped rather than deferred:

1. **It cannot safely skip a read.** Presence is written before publish within a
   cycle, so a peer that publishes after writing presence leaves a manifest that
   is a generation stale. Refreshing presence after publication narrows the
   window but cannot close it — a crash between the two leaves a manifest that
   is permanently wrong. A stale manifest may therefore only ever *add* a reason
   to read, never justify skipping one, so it cannot replace the slot mtime.
   Which makes it cost without benefit.
2. **It re-creates what step 6 just removed.** Step 6's finding was that head
   metadata smuggled through another file makes that file mutable and its
   authority unclear. Copying head hashes into presence is the same move, into a
   file rewritten every cycle by every client.
3. **Siblings share a presence file.** Two clients of one person write
   `identities/<identity>/presence.json` in turn, so a manifest there is
   whichever sibling wrote last — the one place the answer must be exact.

**What is left, and why it stays.** One `list_peers_with_mtimes` per topic. It
cannot come from presence, because presence means *alive* and a mailbox has to
stay readable when its publisher is not: a client that published and then went
offline must still be found. Removing it would trade a round trip for the
property that makes this a relay rather than a session. The remaining fixed cost
is the heartbeat write and one heartbeat read per peer.

**Acceptance.** Idle budget `2 + topics`, asserted per topic count;
`test_a_sibling_writing_into_our_own_slot_is_still_seen` — the slot is read
again as soon as a sibling writes to it, and the sibling rule runs on what it
finds.

## Sequencing

All seven have landed: 1–3 together, then 4 and 5 (4 first, because 5 needs the
mtime to be free), then 6 and 7 (6 first, so that the head writes 7 leans on are
already cheap).

| step | idle ops (3 topics) | of a 3 s cycle |
|---|---|---|
| before | 14 | ~1.35 s |
| after 2 | 11 | ~1.05 s |
| after 5 | 8 | ~0.75 s |
| after 7 | **5** | ~0.45 s |

An idle cycle is now a heartbeat write, a heartbeat read per peer, and one
listing per topic. Every one of those answers a question nothing else in the
cycle has answered: whether we are still alive, whether the peer is, and who is
in the topic. Nothing further can come out without giving something up — which
is the point at which a cost plan should stop.

The write side is bounded too: one subtree write per change by its author, and a
head and nothing more from everyone acknowledging it.

### Measured afterwards, on the link it was written from

Same two clients, same SFTP relay, traced at `timing` for five minutes on
2026-08-17 after all seven had landed.

| A8501, quiet cycle | before | after |
|---|---|---|
| SFTP operations | 17 | **6** |
| cycle duration (p50) | 1467 ms | **608 ms** |
| `publish_after_poll` | 386 ms | **26 ms** |
| operations per cycle (mean) | 16.5 | **6.3** |

A peer's head was read **8 times in 105 cycles**, against once per peer per
topic per cycle before. Of nine publications, six were acknowledgements costing
two operations rather than four; only three `_gc_snapshots` appear in the whole
trace, which is the count of publications that actually carried content.

Both predictions the plan made about failure held. **No
`relay.publication_snapshot_race`** — including through both clients' cold
start, which is exactly where it fired twice before step 6, and which is the
live proof that section asked for. **No `relay.sftp_reconnect`** either, and
that is now a statement rather than an absence of evidence: step 1 is what makes
the difference between a link that did not fault and a client that could not say.

Propagation is unchanged, which was the constraint on all of this: a card moved
on B was published in 1.08 s and seen by A in 2.95 s, inside one poll interval.

Two things in the trace that are not regressions. The first cycle after start-up
takes about nine seconds on both clients - a cold connect and a first read of
everything - after which no cycle exceeds 1.5 s. And a slow `_list_dir` at
1.5 s or a `_read_json` at 1.85 s is a slow answer, not a dropped connection;
telling those two apart is the whole point of step 1.

### What step 3 cost elsewhere

`s-initiative`'s `test_peer_observation_waits_for_matching_changed_snapshot`
guards a real invariant — an acknowledgement must not be exposed before the peer
content it accompanies has been applied — by sabotaging `read_snapshot` and
checking the observation is withheld. Its scenario had the peer adopt the local
change and republish it, so after step 3 there is no snapshot read left to
sabotage and the acknowledgement is exposed alongside content that is correct by
construction. The invariant holds; the test was reaching it through a mechanism
that no longer applies to that case.

The test now gives the peer an edit of its own before it republishes, so its
publication is genuinely content this client does not hold, the fetch is
required again, and the assertion means what it was written to mean. A test that
asserts a mechanism rather than the invariant behind it is worth noticing when
it breaks: this one was one edit away from asserting the invariant directly.

## Housekeeping — relay state files

`default_relay_state_file` (`relay_logic.py:130`) hardcodes
`Path.cwd() / "data"`, so bookkeeping lands in whatever directory the process
was launched from, one file per (identity × relay location). Nothing ever
removes one: `_retire_connection` (`relay_logic.py:2625`) blanks
`shared`/`desired`/`identity_topics` and then **saves the file again**. There is
no `unlink` of a state path anywhere in the codebase.

They accumulate because the identity is fresh every time. Measured on a clean
tree: **one run of `pytest tests/` leaves 7 new files under `s-core/data`**, six
of them from `test_sibling_clients.py`, and the next run leaves 7 more rather
than overwriting them. Before the working tree was last cleaned it held 770 —
600 under `s-initiative/data` across 504 distinct identities, 140 under
`s-core/data`, 4 under `s-cockpit/dist/data`. Roughly a fifth of identities had
two files each: a client that re-keyed its state path when it adopted a
descriptor, leaving the first orphaned.

Three changes, smallest first:

1. `_retire_connection` and `delete_target` delete the file rather than
   rewriting an empty one.
2. Every test that builds a `RelayLogic` or `RelayManager` pins
   `relay_state_file`/`relay_state_directory` into its temp directory — the
   plumbing exists (`_configured_state_file`, `relay_state_directory`) and
   `test_relay_efficiency.py` uses it; `test_sibling_clients.py` and part of
   `test_relay_authority.py` and `test_app_server.py` do not.
3. Derive the default directory from the application's data location instead of
   `Path.cwd()`, so a client started from a different folder does not silently
   begin with empty bookkeeping.

Only the two files under `data/` belong to a live client; anything under a
repository's own `data/` is test residue and can be deleted.

## What this does not cover

- The `session.reconcile_skip` churn (A ran 294 team-topic reconcile passes
  after 22:11, all `hashes_equal`, against B's 14). Local CPU, no relay cost,
  driven by the open UI — worth a look, not part of this plan.
- Blob transfer. One avatar moved in the whole session; `has_blob` already
  guards the presence path (`relay_logic.py:643`).
- Content encryption, unchanged MVP scope (`relay_storage.py:67`).

## Tests

`tests/test_relay_efficiency.py` counts **logical relay operations** through a
counting proxy around `LocalFolderRelayStorage`, so the budgets are
transport-independent and stable. Tests encoding behaviour a step has not landed
yet carry `@unittest.expectedFailure` and name their step; unittest reports an
unexpected success as a failure, so each one announces itself the moment its fix
lands and the marker must be removed. One remains, for step 6.

`IDLE_FIXED_OPERATIONS` and `IDLE_OPERATIONS_PER_TOPIC` at the top of that file
are the budget. Steps 5 and 7 lower the per-topic charge; nothing else may
raise either without saying why.
