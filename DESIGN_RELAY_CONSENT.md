# Relay consent belongs to the session

Status: **built.** Agreed and implemented 2026-08-18.

There is no migration and no compatibility path. There are no productive
installations, so the move drops whatever consent sits in state files today;
a client re-accepts its tokens and re-shares its topics, once.

## 1. One file, two kinds of fact

`relay_state_{app}_{identity}_{fingerprint}.json` holds twelve keys, and they
divide cleanly by how they are recovered when lost:

| | keys | changes | recoverable |
|---|---|---|---|
| **Cache** | `published`, `published_observations`, `observed`, `observed_publications`, `peer_observed_publications`, `received_publications`, `publication_seq`, `ack_publication_seq` | every poll cycle | yes — from the relay |
| **Consent** | `desired`, `shared`, `identity_topics` | on a user action | **no** — only the user knows |
| **Neither** | `pair_all_topics` | when a link is paired | it is a property of the link, and lives in the target record (§8) |

A thirteenth key, `applied`, is deliberately never persisted
(`src/sovereign/relay_logic.py:2392`), because the in-memory cache it describes
does not survive a restart either. It is the precedent this note generalises:
the cache half of this file already has one member that is honest about being
a cache.

The two halves have nothing in common. One churns every three seconds and
costs a republish if lost; the other changes when someone accepts a token and
cannot be reconstructed at all. They share a file for no reason beyond history.

## 2. The move is already half made

The session's private relay namespace already persists the *targets* and the
*topic-to-target assignments* (`_persist_configuration`,
`src/sovereign/relay_logic.py:2561`):

```
relay_targets            target id -> backend, host, root, credentials
relay_topic_targets      topic uuid -> target id
```

And `_bootstrap_registry` seeds that second map **by reading `shared` and
`desired` out of the primary connection's state file**
(`src/sovereign/relay_logic.py:2613`), once, behind a
`relay_startup_target_migrated` flag. **That read is now deleted**; the flag
remains for the other thing it guards (§5.6).

So the session already owns *where* a topic syncs. The file still owns
*whether, and in which direction*: `desired` is "I accepted a token for this
topic", `shared` is "I offered this topic to someone". Two halves of one
relationship, in two stores, under two different keys, with two different
lifetimes — and a migration flag already standing between them.

This note is not a new refactor. It is finishing the one that flag records.

## 3. What the split cost

Written before the change and kept as argued. Line references are to the code
as it stands now; where the cost was a block of code, that block is gone and
the reference names the function it was in.

### 3.1 An edited target hand-carries its consent

`update_target` (`src/sovereign/relay_logic.py:2841`) **spent** roughly
forty-five lines moving `shared`, `desired` and `identity_topics` from the old connection
to the new one when a target's host or root changes — including a branch for
when another target still points at the old location, in which case only the
topics assigned to *this* target may move and the rest must stay behind.

Every line of it exists because consent is keyed by storage location. Keyed by
target id, editing a target's host is editing a record, and there is nothing
to migrate.

### 3.2 Pairing has an ordering constraint imposed by a filename

`accept_pairing_token` (`src/sovereign/relay_logic.py:3297`)
had to write `relay_paired_client_id` before any connection was constructed,
and said why: the state file is keyed by identity and location together, so
binding storage under the old identity ties this client's bookkeeping to a
slot it is about to leave.

A real constraint on call order in a security-relevant path, and its whole
cause is how a file is named.

**Relaxed, 2026-08-18** (`src/sovereign/relay_logic.py:3332`). Reading the
path closed the question: neither half of that reason survives. The state file
holds cache, and nothing in the pairing path consults the metadata for an
identity at all — `_adopt_pairing_channel` assigns `connection.identity`
outright, and every connection `RelayManager` builds is handed an explicit
`relay_identity`. What the write is really for is the *next* start, where
there is no token to read.

So it now runs after the channels are bound, which also fixes what the old
order cost: a token naming a relay the client cannot open used to leave the
session recording a pairing that reached no channel.

One thing did have to change to make that true rather than merely plausible.
`RelayManager` built its connections with `relay_identity` resolved as
"configured, else this session's uuid", skipping the paired client id that
`RelayLogic` itself honours. In the ordinary case the two agree, because
adopting a pairing identity replaces this session's profile uuid with the
sibling's. Where they disagree — an issuer whose relay identity was configured
rather than derived — a restart would have brought the target connections back
in a slot of their own beside their siblings. Both now resolve identity the
same way.

### 3.3 Moving a topic between targets writes to two stores

`accept_descriptor` (`src/sovereign/relay_logic.py:2937`) and
`assign_topic_target` (`src/sovereign/relay_logic.py:2999`) both reach into the
*previous* connection to `unmark_topics_shared` and `unmark_topics_desired` by
hand, because the assignment moved in the session while the consent stayed in
another connection's file. `RelayLogic.delete_topic`
(`src/sovereign/relay_logic.py:2346`) strips the same three keys again on its
own path.

One fact, three call sites keeping two representations of it aligned.

### 3.4 Session state is rebuilt from a cache file

`_activate_shared_topics` (`src/sovereign/relay_logic.py:771`) runs at
construction and calls `session.start_discussion` for every topic in `shared`.
The session's own notion of what is being discussed is restored from a
sidecar. The dependency points the wrong way.

### 3.5 The file is not safe to delete, and fails silently when it is

`has_active_relationship` (`src/sovereign/relay_logic.py:780`) is the relay
loop's gate, and it reads `shared` and `desired`. `poll_and_apply` grafts only
what is in `desired`.

Delete a live state file and both go empty: publishing stops because the gate
unarms, and inbound grafting stops because the consent gate refuses. The relay
stays reachable, presence keeps beating, the UI shows a healthy connection,
and the topic simply goes quiet. No error is raised anywhere.

This was reached in practice on 2026-08-18: forty-eight state files had
accumulated under `data/`, and answering "which of these can I delete?"
required opening each one. Forty-six were empty and safe; two were live and
would have silently unshared a working two-client session.

## 4. The model

Three rules.

1. **Consent is durable state of the session, keyed by target id.** Not by
   identity, not by storage location. A target keeps its id when its host,
   root, credentials or name are edited, which is exactly the invariance §3.1
   hand-codes.
2. **The state file holds cache only, and may be deleted at any time.** The
   worst consequence of deleting one is a republish and a refetch. This becomes
   a property anyone can rely on — a user, a cleanup script, an installer —
   rather than a question that needs the file read to answer.
3. **Memory is the read path; the session is the record.** Write-through:
   `RelayLogic._state` keeps consent in memory exactly as now, so
   `has_active_relationship` and `poll_and_apply` do not start taking the
   session lock on the poll hot path. Mutations write through to
   `session.update_component_metadata("relay", …)` instead of `_save_state`.

Where each key lands:

| key | home after the move |
|---|---|
| `desired`, `shared`, `identity_topics` | session, under `relay_consent[target_id]` |
| `pair_all_topics` | the target record, `relay_targets[target_id]` (§8) |
| everything else | state file, unchanged |

The lock order permits it as written: consent mutators are already
`@_relay_io_locked` and already reach the session (`_activate_shared_topics`),
and io → session is the sanctioned direction
(`DESIGN_LOCKING_AND_COMPOSITE_READS.md`).

## 5. What changes

1. `_persist_configuration` gains `relay_consent`, a `target_id -> {desired,
   shared, identity_topics}` map, loaded in `RelayManager`
   alongside `relay_targets` and `relay_topic_targets`.
2. The consent mutators (`mark_topics_desired`, `unmark_topics_desired`,
   `mark_topics_shared`, `unmark_topics_shared`, `pair_all_topics`,
   `src/sovereign/relay_logic.py:698-769`) write through to the session instead
   of calling `_save_state`.
3. `_load_state` and `_save_state` drop the four consent keys. `_load_state`'s
   defaults shrink to the cache set.
4. A connection learns its target id at construction, so it can address its own
   consent. `RelayManager` knows the id at every site that builds one.
5. `update_target`'s intent migration (§3.1) is **deleted**, not ported.
6. `_bootstrap_registry`'s intent-reading migration is **deleted** — the fact
   it migrated no longer lives in a file — along with the legacy `configured`
   key it stripped from older records. The `relay_startup_target_migrated`
   flag **stays**: it guards a second job, adopting a relay named in a config
   file as a target exactly once, and a target the user deleted must stay
   deleted however the config file still reads.
7. `_retire_connection` and `RelayManager.delete_target` drop consent from the
   session for that target id; `_delete_state_file` stays as it is.
8. `_activate_shared_topics` reads consent from the session.

Nothing in `poll_and_apply` or `publish_due_topics` changes. They read
`self._state` for consent today and still do.

## 6. Keying, and the one case that resists it

Target id is the key. The registry already assigns one to every target,
including the one adopted from a startup config
(`src/sovereign/relay_logic.py:2641`), and `connection_for_target` already
resolves in both directions.

The exception is the **unconfigured primary**: the implicit connection built
from a config file has no target id, and every test that constructs a
`RelayLogic` itself has none either. **Decided: reserve the key `"primary"`**,
fixed at construction and never re-keyed. Refusing consent without a target
was the cleaner rule and was rejected — it would have made "constructed by
`RelayManager`" a precondition of an object that is also constructed directly
throughout the suite.

Never re-keyed matters. When `_bootstrap_registry` adopts the config file's
relay as a target, the primary connection is handed that target id to *also*
answer for (`serve_target`), and goes on writing its own decisions to
`"primary"`. Moving the key instead would be the same hand-carry §3.1 deletes.

One consequence, accepted: if a relay reaches a client through a config file
and later only through an explicit target, consent recorded under `"primary"`
is read but never rewritten under the target id. It is the last place where
the old shape shows through.

A connection is a *location* and a target is a *link a user configured*, and
`create_target` does not dedup by location the way `register_descriptor` does.
So two targets can name one relay and share the one connection to it. A
connection therefore reads the **union** of consent across every target it
serves, and writes to the one it was built for.

This case previously *lost* the consent outright:
`_install_adopted_storage` re-keys `_state_path` and reloads
(`src/sovereign/relay_logic.py:473`), discarding whatever was marked before
adoption. It now survives, and `test_relay_consent.py` holds it to that.

## 7. Verification

`tests/test_relay_consent.py`, six tests, all of which fail against the shape
this note replaces:

- Deleting the state file loses nothing: consent and the publish gate both
  survive a rebuild (rule 2).
- No consent key ever appears in the written file.
- Consent marked before storage is adopted survives adoption (§6).
- Editing where a target points keeps its consent, with no code moving it
  (§3.1's replacement).
- Deleting a target drops its consent and no other target's.
- A second target naming one location shares the connection and reads the
  same consent (§6's union).

`tests/test_sibling_clients.py` gains one for §3.2's relaxation: a pairing
token whose relay cannot be opened records no client id. It fails against the
old ordering.

`tests/test_relay_state_files.py` still passes; its three placement and
lifetime tests now force a cache write directly, because consent no longer
writes that file at all. Three tests in
`s-initiative/tests/test_relay_logic.py` encoded the old shape and were
rewritten: two seeded the legacy `configured` key, and one asserted that
consent reloads from the state file into a *different* session — precisely
what this note ends.

Full suites green at the time of writing: s-core 504, s-initiative 264,
s-team 213, s-flow 33, s-cockpit 75.

## 8. Both follow-ons, built

Decided and implemented 2026-08-18.

### 8.1 `pair_all_topics` lives on the target

It is not consent: only pairing sets it, nothing clears it, and what it says
is that this *link* carries a sibling. It is a field of the target record now,
persisted with `relay_targets`, and a connection projects it for its three
readers — `relay_topic_uuids`, the poll's scope handling, and
`withdraw_topic_publication`'s refusal to interrupt a sibling relationship —
from every target it serves (`_project_pairing`,
`src/sovereign/relay_logic.py:628`). Projected, never written:
it is excluded from the state file by `PROJECTED_KEYS`, beside the consent
keys.

`update_target` rebuilds a record from a descriptor, and a descriptor
describes a location — so the pairing is carried across an edit explicitly. A
corrected host does not change whether the link carries a sibling.

A connection with no target record refuses to be paired rather than keeping
the flag where nothing reads it (`mark_target_pairs_all`,
`src/sovereign/relay_logic.py:3167`).

**The gap §6 predicted needed one more piece than expected.** The plan was to
adopt the storage onto primary and then register the descriptor, so that the
registration dedups to primary rather than building a second writer. It does
not, on its own: `connections` keys a connection by storage fingerprint, and
primary is filed under `"unconfigured"` while it has nothing — and nothing
re-filed it when it adopted. The registration would therefore have missed it
and built exactly the second connection the code takes care to avoid.
`_refile_primary` (`src/sovereign/relay_logic.py:3150`) closes
that, and is the symmetric counterpart of what `_retire_connection` already
did in the other direction.

One consequence worth naming: a re-filed primary is no longer skipped by
`refresh_scopes`. That only reaches the pairing path — an accepter with a
connect token gets a target-keyed connection, not primary — and a paired
connection carries every topic regardless of scope, which is what the flag
means.

Moving the mutator to the manager also surfaced a lock-order inversion:
`pair_all_topics` was `@_relay_io_locked` and the registry it now writes to is
the manager's, so it took I/O then manager, against `manager < relay I/O`.
The delegation is unlocked and the projection that follows takes the I/O lock
on its own.

### 8.2 The sequence counters resume from the relay

`_resume_publication_seq` (`src/sovereign/relay_logic.py:1454`)
reads back the counter from the head we ourselves published, so a start that
finds no state file does not begin again at zero and silence every peer's
acknowledgement.

Gated on the file having been absent and on the topic having no counter yet,
so an ordinary restart asks the relay nothing. A first start, or one after the
file was deleted, pays one read per topic it publishes and then never again —
a topic the relay has never held answers `None`, which is recorded as zero so
the question is not asked twice. An unreachable relay leaves the topic
unanswered rather than resuming from a guess.

With this, §4's rule 2 holds without an asterisk: the state file may be
deleted at any time, and the worst it costs is a republish and a refetch.

### Verification

`tests/test_relay_consent.py` gains three (pairing recorded on the target, an
edit that does not unpair, a targetless connection refusing), and
`tests/test_relay_authority.py` gains three for the counter, where the
principle already lives — the relay decides what the relay holds. The
resumption test fails without the resumption; the pairing tests fail without
the move.

Suites at the time of writing: s-core 511, s-initiative 264, s-team 213,
s-flow 33, s-cockpit 75.

### Still open

Nothing from this note. The nearest neighbour is `DESIGN_RELAY_EFFICIENCY.md`
step 7's successor question — whether the cache half is worth keeping on disk
at all, now that every part of it can be re-derived. Not asked here.
