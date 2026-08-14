# Adoption metadata

Each application records, per node, how incoming changes to that node are to be
handled. Core reads the record and executes it. Core never interprets what the
node means.

Supersedes the rule-based draft (`DESIGN_DECLARED_ADOPTION_POLICY.md`), which
had applications declare per-type predicates — identity-bearing fields, scalar
versus list, protect-when-present — that Core then evaluated. That put a small
semantic vocabulary in Core which would have grown with every application need.
A table Core reads and never interprets has no such failure mode.

Assumes `DESIGN_TOPIC_CONFINEMENT.md` has landed: this document decides which
changes are *accepted*, which is only meaningful once which changes can
*reach* you is settled.

## The model

- The application writes an entry for a node when it creates one, and when its
  own circumstances change what should happen to it.
- Core reads entries during reconciliation and acts on them.
- Entries are **local**. They are not part of the node, not hashed, not
  published, and never adopted from a peer. A peer's opinion about how their
  change should be treated is not an input to how the recipient treats it.

## Vocabulary

Three fields per node:

| Field | Values | Governs |
|---|---|---|
| `adopt` | `auto` \| `hold` \| `never` | a change to *this* node |
| `additions` | `auto` \| `hold` \| `never` | children not yet held locally |
| `author` | `any` \| `<identity_uuid>` \| `same-origin` | whose revision is acceptable at all |

**`hold` and `never` are different.** `hold` means "present it as a divergence,
I will decide". `never` means "do not offer it at all" — Core's own
`agenda_item`, which is projected by author authority and never adopted. That
second value also governs whether the node appears in the divergence list,
which is where `DISPLAYED_DIVERGENCE_TYPES` goes: the same judgement, currently
written a second time for display.

**`author` stays mechanical.** `same-origin` means "only revisions carrying the
origin that already authored this node" — Core compares `revision_origin` and
needs no application semantics. On `adopt` it covers comments, role decisions
and profiles; on `additions` it means only the parent's author may add
children. A concrete identity uuid covers the trustee case.

Core must never learn set-valued authority ("any current member"). The
application resolves membership to concrete uuids and writes them; otherwise
membership semantics leak into Core through the back door.

## Where entries live

A Core-side table keyed by node uuid, persisted with the session.

Not in `node.data`. Anything in `data` is in the content hash, so it would be
published, revised, and adopted — and an adopted entry would mean the sender
setting the recipient's policy, which is the one inversion this design exists
to avoid.

Being local, entries are per client, exactly as `auto_adopt_by_topic` already
is (`session.py:2340`). Paired sibling clients each hold their own. That is not
a change from today.

### Persistence

The table is persisted in the session envelope, beside the application metadata
that already holds `auto_adopt_by_topic` — `persistence_metadata()` /
`restore_persistence_metadata()` (`session.py:491`). Restore validates stored
values and drops entries whose uuid is no longer in the index, which is the
same treatment `active_topic_uuids` already receives and is the table's
garbage collection.

Two kinds of entry sit in it, and only one strictly requires persisting:

- **derived** — "hold the cards I own" is recomputable from the tree and the
  stored mode. Persisting it is a cache, with a cache's hazard: it drifts if an
  application misses a write path.
- **decided** — the result of the classification hook, or an `author` uuid the
  application resolved from membership at a particular moment. Nothing can
  recompute these.

Because the second kind exists, the table persists. Because the first kind
exists, an application must be able to rebuild a topic's entries on demand, so
that a drifted cache is recoverable rather than permanent. That rebuild is the
same path a mode change already takes.

No envelope version change is required: an absent table inherits topic
defaults, and an absent topic default is `hold`. That is safe but not silent —
a session upgrading would find everything waiting for review. The answer is not
migration code. The application already persists the chosen mode, so its
ordinary "translate the mode into table writes" path runs once at startup and
populates the defaults.

## Defaults cascade

An absent entry inherits the topic default, which the application sets. An
absent topic default is `hold` — the conservative answer, chosen so that a
missing entry can never widen what is accepted.

Cascading is what keeps the table small and the writes bounded. S-Initiative's
`not_owner` becomes "topic default `auto`, with `hold` on the cards I own",
rather than an entry per card, and switching to `not_member` rewrites the
exception set rather than the board.

## Classification of a node not yet held

Parent marking answers most of it: a new child is governed by its parent's
`additions`, and the parent is something the recipient already holds.

It does not answer all of it. Under `not_owner`, a peer creates a card naming
**me** as its owner. The column says `additions: auto`, and no entry can exist
for a node that does not exist — so it would be accepted, where today the
incoming card's `owner` field is inspected and the card is held
(`logic.py:863`, which passes the peer's node when there is no local one).

So Core offers a **one-shot classification hook**:

- called at most once per node uuid, the first time Core meets a node with no
  entry;
- receives the incoming node (detached) and the inherited default;
- returns an entry, a plain mapping such as `{"adopt": "never"}`, or nothing to
  accept the default;
- the answer is **persisted**, and every subsequent decision about that node is
  a table read.

Only facts that do not move belong here, precisely because the answer is
stored. Anything derived from state that changes - membership, roles, what
somebody owns today - is a question for the resolver below, asked when it is
actually being answered.

Redeclaring a topic default drops the answers for nodes not held, since they
were derived under the declaration that just changed. Restart does the same,
because restore keeps only entries whose node is in the index. Both re-ask.

The distinction that matters: Core asks the application to *classify a node
once*, never to *decide an adoption*. A hook consulted per decision would be
`node_is_eligible` under a new name — application logic back on the adoption
path, alongside a table, and decisions that cannot be reproduced from stored
state.

Two constraints follow from where it runs. It executes inside the session lock
during reconciliation, so it must be read-only on Session and must not perform
I/O — see `DESIGN_LOCKING_AND_COMPOSITE_READS.md`. And Core must never block on
it: an application that supplies no hook gets the inherited default and
reconciliation proceeds.

## Consequences

Three things previously scoped as separate work fall out of this model rather
than being built beside it.

**Additions are shallow, and processed parents-first.** If a missing container
is accepted because its parent says `additions: auto`, grafting its subtree
wholesale would import children that are separate decisions under their own
parent's entry. So every addition is created empty and each level is judged by
its own parent. This generalises the shallow pre-adoption previously scoped for
S-Initiative's columns, and it requires the parent-ordered walk noted there:
`analyze_peer_transitions` returns events uuid-sorted (`session.py:1516`), and
today's application pre-pass only avoids failing because it creates nothing
deeper than a column hanging off the topic root.

**Deletion is checked over the subtree.** The protocol has no partial deletion:
`_delete_impl` cascades to the whole subtree (`protocol.py:501`). So adopting a
deletion of `N` requires `N` and every live descendant to be `auto`. Anything
`hold` below refuses the deletion whole — the container remains as a divergence,
and unprotected nodes beneath it still delete through their own events. Without
this the table's promise fails in exactly the case where losing content is
irreversible.

**Divergence display follows `never`.** A node nobody may adopt has no business
in a list of things to decide about.

## Lifecycle

| Event | Table |
|---|---|
| application creates a node | entry written by the application |
| Core first meets an unheld node | hook, or inherited default; result persisted |
| node pruned | entry removed |
| topic default changed | one write; entries unaffected |
| circumstances change (ownership, mode, trustee) | application rewrites the affected entries |

Core offers the bulk primitives so each application does not write the same
loop: set a topic default, set an entry across a subtree, and replace one
`author` uuid with another throughout a topic — the trustee swap.

No migration path is needed. A node with no entry inherits the topic default,
so existing sessions behave as though the table had always been there and
empty.

## What the applications delete

S-Initiative: `_auto_adopt_allows_node`, `_has_protected_descendant`,
`_adopt_missing_columns_shallowly`, both eligibility closures in
`adopt_incoming_changes`, `DISPLAYED_DIVERGENCE_TYPES`, and the browser copy of
the predicate (`initiative.html:116`) — the payload carries the verdict
instead. Roughly 120 lines, plus the drift hazard between the Python and
JavaScript copies.

What remains is the four-position dial and its labels: the user's chosen mode
stays application vocabulary, and the application translates a mode change into
table writes.

Note this leaves `session.py:2329` correct as written. Core stores an
application's mode string and still never interprets it — the earlier draft
would have reversed that; this one does not.

## Open

- Write amplification on a mode change is bounded by the exception set but is
  still proportional to topic size. Acceptable at board scale; worth measuring
  before assuming it holds for a large team topic.
- Whether `additions` needs a depth notion, or whether one level plus
  inheritance is sufficient. Nothing today needs more.

## Declaration is mandatory

Every topic is governed. There is no fallback to an application callback:
`node_is_eligible` remains on `reconcile_peer_changes` for callers with a rule
Core has no way to store, but no application uses it, and an undeclared topic
holds everything. Silence is not consent to adopt.

### What each application declares

| Application | Topic default | Written per node | Classified at first sight |
|---|---|---|---|
| S-Initiative | from the board's mode: `auto` unless `never` | `hold` on cards the mode protects, which still admit comments through `additions`; `never` on any held agenda item | an agenda item (`never`); a card arriving already marked as the reader's (`hold`) |
| S-Flow | `auto` | the owner's key as `author` on every held process, assignment and runtime-state node; `never` on agenda items | a response (anyone's), a process/assignment/runtime-state node (the owner's), anything else (`never`) |
| S-Team | `hold` — agreement content is what members negotiate | `never` plus `same-origin` on every held governance record; `never` on agenda items | an agenda item (`never`) |

S-Team is the one whose verdict cannot be declared at all: whether an incoming
record was authored by the actor entitled to author it is computed from
membership and role state, both of which move. So it is not classified but
**resolved** — assessed at the moment of decision, answering `adopt` when
authority holds and `refuse` when it does not, since no member's decision makes
an unauthorized record authorized. Everything else defers, which is what makes
one topic serve both its automatic governance pass and its manual adopt button.

Entries are rebuilt rather than updated incrementally - each application's
`publish_adoption_metadata` runs before its adoption pass - so a missed write
path cannot leave a stale entry behind. That rebuild is the safety valve the
persistence section requires.

## Resolving a held node

`hold` does not mean "refuse". It means **nothing has decided yet**, and that
ends in one of three ways. When Core meets a held node it asks the topic's
resolver, which answers:

| Verdict | Meaning | Automatic pass | `deciding=True` |
|---|---|---|---|
| `adopt` | the application's own rule settles it | adopted | adopted |
| `refuse` | its rule says no | skipped | **still skipped** |
| `defer` | nobody has decided; the user's call | skipped | adopted |

`defer` is the answer when no resolver is registered, when one returns nothing,
and when one raises. Core never blocks on an application fault.

The `refuse`/`defer` distinction is the one the old boolean callback could not
make: it collapsed "my rule says no" and "nobody has decided yet" into the same
`False`, so an application had no way to say that a user's decision should not
override its rule.

Unlike a classifier's answer, a resolver's is **never stored**. It is derived
from state that moves, so a recorded verdict would go on being true after it
stopped being true - the same cache-drift that makes the classifier wrong for
these questions.

### Why this keeps adoption atomic

The resolver runs inside the session lock, in the same pass that applies the
result, so the answer and the adoption it permits cannot come apart. Nothing
mutates the session in between: `reconcile_peer_changes`, `accept_peer_node`,
`adopt_subtree`, `modify`, `delete` and `apply_peer_subtree` all take that one
re-entrant lock, so a channel poll delivering a new snapshot mid-pass cannot
happen. Per-node adoption is itself atomic - `adopt_own_fields` defers the
whole adoption rather than applying content without an inapplicable move
(`protocol.py:364`).

Two limits worth stating. A pass is not transactional *across* nodes: a refusal
at node three leaves nodes one and two adopted, which is intended, since
reconciliation is per node. And a resolver must not block: reaching back into
relay I/O or the channel manager raises rather than deadlocks, because Session
is the innermost lock layer and `OrderedRLock` rejects reverse acquisition -
but those checks are `if __debug__`, and blocking on something outside the lock
hierarchy is caught by nothing.

## A decision the user is making now

`hold` means "wait for me to decide". A pass the user asked for *is* that
decision, so `reconcile_peer_changes(..., deciding=True)` passes through
`hold` - and only `hold`. `never` still refuses, because such a node is not
offered at all, and `Session.accept_peer_node` applies the same rule.

This is what lets one topic serve both an automatic pass and a manual one
without two sets of rules. S-Team relies on it directly: its team topic
defaults to `hold`, so governance facts arrive on their own while agreement
content waits for a member to adopt it.

## Sequencing

1. Table, vocabulary, cascade and bulk primitives. Unused; no behaviour change.
2. Core reads the table in `reconcile_peer_changes` — including shallow
   parent-ordered additions and the subtree deletion check — behind the
   applications' existing callbacks, so both must agree. Prove equivalence
   against the existing adoption tests.
3. S-Initiative writes entries and its callbacks are deleted.
4. The classification hook, once a case needs it — `not_owner` with an incoming
   card naming the recipient as owner is that case.
5. Divergence display switches to `never`.
