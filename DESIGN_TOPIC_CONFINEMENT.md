# Topic confinement

An adoption authorised for one topic must not touch any local node outside it.
Enforced by Core, for every application, with nothing declared.

Supersedes the type-membership guard previously drafted as
`DESIGN_APPLICATION_NODE_SCOPING.md`. That draft checked the incoming node's
type and the peer's claim about where it lives — both attacker-supplied. It did
not check where the change would actually land, and so did not close the hole
it was written for.

## The invariant

> **An adoption reconciling topic T may create, modify or delete local nodes
> inside T, and nothing else.**

The check is on the **destination** — the local node being changed and the
local parent a new node will attach to — never on the incoming node's declared
type or on the peer's account of where it sits.

## Why it is needed

Core classifies transitions against a **topic-scoped** comparison and then
resolves them against the **global** index.

`analyze_peer_transitions` flattens the local topic and the peer's copy of that
topic (`session.py:1514`), so a uuid absent from the local topic is reported
`local_missing_node`. But `reconcile_peer_changes` then looks the node up with
`self._protocol.index.get(...)`, and `accept_peer_node` does the same
(`session.py:1772`) and resolves the peer-supplied `parent_uuid` the same way
(`session.py:1797`). Core says "you do not have this node" and then edits the
node you do have, in another topic.

Three probes against current `main`, all on the ordinary receive path
(`apply_peer_subtree` then `reconcile_peer_changes`, exactly what a relay poll
performs):

1. **Cross-topic overwrite and move.** A peer places a node in their copy of a
   shared board reusing the uuid of a node in a topic never shared with them.
   Result: the node is moved out of the private topic into the board, its
   content replaced, the private topic left empty.
2. **Application callbacks do not stop it.** Replaying S-Initiative's real
   `source_eligible`, the node is taken under `always` — the default. It is
   blocked under the three other modes only by `local_missing_node → mode ==
   "always"` (`logic.py:872`), a line written for the shallow-container problem
   and unrelated to confinement. That accidental protection is scheduled for
   deletion by the pre-adoption change.
3. **Creation into an unshared topic.** A new node in the peer's copy of the
   shared board, carrying `parent_uuid` pointing into a private topic, is
   created inside that private topic.

Probe 3 is what defeats a type-based guard: naming a plausible topic and node
type, with valid hashes, is the entire cost of bypassing it. Type membership
describes the node; confinement describes the effect.

## The rule

For an adoption of node `N` offered by peer `P`:

1. **Establish T, the topic the adoption is authorised for.**
   - `reconcile_peer_changes` already has it as an argument.
   - For a direct `accept_peer_node` / `rollback_peer_node`, T is the topic of
     `P`'s cache that contains `N` (`peer_topics_for_node`). Ambiguous or
     absent — refuse.
2. **Every local node the operation touches must resolve to T**, via
   `_topic_for_node`:
   - an existing local `N` — for a content adoption, a rollback, or a deletion
     through `adopt_absence`;
   - the destination parent — for a graft of a missing node, and for the move
     leg of `adopt_own_fields`.
3. Anything else is refused, and nothing is mutated.

Deriving T from the peer's own cache in step 1 is safe precisely because it is
then checked against the local resolution in step 2. A peer claiming a node
belongs to the shared board while the local destination sits in another topic
fails the comparison — which is the case a peer-side check alone cannot catch.

## Universal, and not declared

This is not an application capability. It takes no registration, no node-type
declaration and no opt-in, and there is no way for an application to weaken or
skip it. Every application on the session gets the same invariant because it is
a property of what a shared topic *is*, not of what any application means by
its own nodes.

Consequently it is enforced **inside** Core's peer entry points rather than
offered as a helper for applications to call:

| Entry point | On refusal |
|---|---|
| `accept_peer_node`, including `adopt_absence` | `SessionResult("error", ...)` |
| `rollback_peer_node`, including `rollback_absence` | `SessionResult("error", ...)` |
| `reconcile_peer_changes` | skip the node, trace, continue |

An application that forgets to guard cannot be wrong, because there is nothing
for it to remember.

## What this does not cover

**The local request surface.** Confinement constrains adoptions from peers. It
says nothing about an application's own HTTP route being handed a uuid from
another application: `Session.modify` and `Session.delete` resolve globally
(`session.py:1602`, `session.py:1649`), so `/api/initiative/...` given a Team
node uuid still acts on it. That is what `InitiativeLogic.owns_node` and
`TeamLogic.owns_node` guard today, and they remain necessary — the duplication
between them is a separate problem with a separate answer. Do not read this
document as retiring them.

**The Protocol Explorer**, which implements its own `accept_peer_node` against
session primitives (`protocol_explorer.py:52`) and is a raw-tree tool by
design. Confirm during implementation that it does not reach the enforced path
indirectly.

**Signature validity.** Probe 1's planted node carried a signature that no
longer matched its content and was adopted regardless: verification runs on
projections (`revision_verification`) but does not gate adoption. Separate
issue, separate fix.

## Tests

- Each probe above, as a regression test asserting refusal and an unmutated
  tree.
- A tombstoned local node is still a local node: deleted-but-unpruned uuids are
  in the index (`protocol.py:512` marks, `prune_deleted_nodes` removes later),
  so an adoption naming one must be confined the same way.
- `adopt_sibling_topic` (`session.py:2054`) loops `accept_peer_node` over a
  whole topic; confirm a legitimate sibling take is unaffected, since one
  refusal would silently reduce it to a partial adoption.
- Ordinary multi-topic operation: two topics shared with the same peer, changes
  flowing in both, neither reaching the other.

## Sequencing

This lands **first**, before the declared-adoption-policy work. Two reasons:
the hole is live on the default setting today, and the pre-adoption change in
`DESIGN_DECLARED_ADOPTION_POLICY.md` deletes the line currently providing
accidental protection under the restricted modes.

It is also independent: it needs no application change, so it can ship without
waiting for any declaration work.
