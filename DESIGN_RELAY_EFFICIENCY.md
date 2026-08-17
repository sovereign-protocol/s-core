# Relay efficiency

A poll cycle must spend its round trips on questions it has not already
answered. Today roughly half of them are spent re-asking.

This plan is written from one live two-client session (A on 8501, B on 8502,
both against the same SFTP relay, traced at `timing` level for 22 minutes on
2026-08-16). Every number below is measured, not estimated, and every
redundancy named here is reproduced by a test in
`tests/test_relay_efficiency.py`.

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

## Step 4 — One round trip per file read

`read_head_with_mtime` and `read_presence_with_mtime` each issue a `_read_json`
followed by a separate `_stat_mtime` (`relay_storage.py:601`, `:672`). Paramiko
returns both from one visit: `sftp.open(...)` then `SFTPFile.stat()` on the open
handle. This is the same saving `write_presence` already documents and takes at
`relay_storage.py:648` — "one round trip fewer than write-then-stat" — applied
to the read side.

Cheap on its own (~65 ms per cycle at three topics) and it is a precondition for
step 5, which needs the mtime to be free.

**Acceptance.** SFTP-level, so not covered by the logical-operation budget:
assert against a fake paramiko SFTP client that one `read_head_with_mtime`
issues one `open` and no `stat`.

## Step 5 — Skip heads that cannot have changed

`_list_dir` calls `listdir_attr` and throws away everything except the directory
names (`relay_storage.py:867`). It already has each peer directory's
`st_mtime` in hand, and a `posix_rename` of `head.json` into that directory
bumps it. **The information needed to skip an unchanged head read is already
being downloaded and discarded.**

**Change.** Return `(name, mtime)` pairs from the peer listing, keep the
previous cycle's mtimes beside `_relay_listed_peers`, and read a head only when
its directory mtime has moved. First sight of a peer always reads.

**Acceptance.** A new budget test: a second idle cycle over an unchanged relay
costs `2 + 2 × topics` — 8 operations at three topics, down from 14. Correctness
is guarded by the existing suite plus one test that a head written between
cycles is still picked up.

## Step 6 — An acknowledgement should not rewrite a subtree

Seven of A's sixteen board publications carried no content change
(`ack_requested: false`) — pure "I saw your seq N" bookkeeping. Each one still
pays the whole `write_snapshot` path: read head, write the entire subtree, write
head, gc listing (`relay_storage.py:402`) — four operations where two would do.

The obstacle is that the head's metadata is smuggled through the snapshot
payload. `_relay_observed`, `_relay_observed_publications`,
`_relay_ack_publication_seq` and `_relay_ack_requested` are written into every
snapshot **solely so `write_snapshot` can copy them into `head.json`**
(`relay_storage.py:408-425`). The only field ever read back out of a downloaded
snapshot is `_relay_publication_seq`, at `relay_logic.py:1729`.

**Change, in two parts.**

1. Pass head metadata to `write_snapshot` as arguments instead of stuffing it
   into the payload. Every snapshot on every relay gets smaller and the head
   stops being a derived copy of something it should have owned outright.
2. Add `write_head(topic_uuid, peer_id, ...)` for a publication whose hash is
   unchanged, and route observation-only publications to it.

**One trap to close with it.** The snapshot-race check at
`relay_logic.py:1731` refuses a payload whose `_relay_publication_seq` differs
from the head's. Once a head can advance without its snapshot, a first-time
reader would meet head seq 16 against snapshot seq 15 and skip the topic
indefinitely. The check must become `payload_seq > publication_seq`: a snapshot
from a *newer* generation is the real race, while an older one carrying the
head's hash is content-identical by definition. Do not land part 2 without this.

**Acceptance.** `test_an_acknowledgement_does_not_rewrite_the_subtree`, plus a
regression test that a peer arriving after an observation-only publication still
receives the topic.

## Step 7 — Presence as a manifest

The structural fix, and the only one that changes the shape of the cost rather
than its constant.

Every client already writes `identities/<peer>/presence.json` once per cycle,
unconditionally, and every peer already reads it once per cycle
(`relay_logic.py:1495` caches it across topics for exactly this reason). Give it
`topic_heads: {topic_uuid: {hash, publication_seq, ack_publication_seq}}` and an
idle poll needs **no per-topic head reads at all**: one presence read per peer
answers "has anything changed anywhere", and a head is read only where the hash
differs.

Idle cost goes from `2 + 4 × topics` to roughly `2 + topics` (the peer listing
that discovers newcomers), and stops growing with peers × topics.

**The ordering caveat.** Presence is written *before* publish inside a cycle
(`relay_logic.py:789`), so a change published in cycle N would not reach the
manifest until cycle N+1 — up to 3 s added to the 1.5–2.9 s propagation this
plan must not regress. `publish_once` must therefore refresh presence after a
publication: one extra operation, only when something actually changed.

Presence is per identity and reachability is per topic — the same tension
`relay_logic.py:657` already resolves by putting `topic_uuids` in the payload.
This step extends that list rather than introducing a new concept.

**Acceptance.** Idle budget `2 + topics`; end-to-end propagation test still
within one poll interval; existing `test_relay_authority` suite unchanged.

## Sequencing

Steps 1, 2 and 3 have landed together. 4 precedes 5. 6 precedes 7, because 7
makes head writes frequent and 6 makes them cheap. 7 is the only step that
changes the relay's on-disk contract and should land alone.

| step | idle ops (3 topics) | of a 3 s cycle |
|---|---|---|
| before | 14 | ~1.35 s |
| after 2 (**done**) | 11 | ~1.05 s |
| after 5 | 8 | ~0.75 s |
| after 7 | 5 | ~0.45 s |

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
