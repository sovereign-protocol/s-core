# Node classes: decidable, observed, persisted

Status: proposed. No code has been written against this.

## 1. The problem

Every node in a shared topic is currently treated as though somebody might
disagree with it. Session compares both sides, stages a transition, and the
application offers a way to adopt or roll back. That is right for the
content people are actually agreeing about, and wrong for everything else -
and "everything else" is most of the nodes.

The cost is not theoretical:

- **S-Team's divergence list is unreadable.** It has no filter beyond stale
  in-flight, so role offers, role answers and seat records all appear in it.
  On a live two-client pair, client B's list holds A's *own acceptance of
  the Participant role* as `local_missing_node / awaiting_me`. B has no
  reason to ever act on it, adopting it would change nothing, and it will
  sit there for the life of the topic.

- **The rule already exists, written three times by hand.** S-Initiative
  keeps `DISPLAYED_DIVERGENCE_TYPES` separate from `OWNED_NODE_TYPES`; its
  auto-adopt callback carries a special case reading *"Comments are additive
  and author-stamped - always adopt one ... the way agenda items follow
  their author"*; S-Team excludes `agenda_item` from `REACTABLE`. Three
  expressions of one idea, none of them named, and S-Team is missing the
  half that matters most.

- **Core owns node types the applications re-declare.** `agenda_item` is
  created, deleted, prioritised and ordered entirely by `Session`;
  applications only expose routes to it. Both S-Team and S-Initiative list
  it in their own `OWNED_NODE_TYPES` anyway. A fact with two owners drifts.

- **A status line says the wrong thing.** When a trustee offers a role, the
  author sees `awaiting_peer` - "not yet adopted by them" - which reads as
  "they have not answered". They are different facts, and collapsing them
  made an offer that had never been shown to its recipient look like an
  offer awaiting their reply.

## 2. The distinction

> **Decidable** - a node I could agree or disagree with, where holding a
> different perspective means something. A clause in an agreement. A card on
> a board.
>
> **Observed** - a node that is part of my perspective as external
> information: a fact about somebody else that it makes no sense to
> question. Their identity. Their answer about a role they were offered.

The adoption mechanism exists only for decidable nodes. Observed nodes have
no proposal, no reaction, no divergence row, and no auto-adopt setting -
because there is no decision to automate.

This is deliberately **not** a claim of principle. Anyone is free to refuse
to see reality; that is their right as a sovereign actor. It is a complexity
reduction. The question the interface should ask is *what does it make sense
to decide on*, and everything that is clear per se should stay out of the
way.

Automating adoption and removing it are not the same answer. If the outcome
is always "adopt", keeping the machinery costs a proposal list, a reaction
button, a status line and a stage in the state machine to express a decision
nobody makes. Deleting the mechanism is strictly simpler than defaulting it.

## 3. The criterion

A node is decidable if **both** hold:

1. **More than one actor may write it** over its lifetime. A node with one
   possible author cannot diverge - there is one version, and a second copy
   of somebody's word adds nothing to it.

2. **Changing it materially changes what I hold.** A change that does not
   alter the meaning of the thing it hangs off is not worth anybody's
   decision, even where two people could both make it.

Either failing sends the node to observed.

### On the first axis

It is mechanical and it reproduces the split both applications already made
by feel. Every node type that exists today is classified correctly by it:
cards, columns, boards, clauses and sections are edited by anyone who holds
the topic; comments, attachments, agenda items, role offers, role answers
and seat records each have exactly one possible author, enforced by a guard
(`only the author can delete a comment`, `only the Identity holder can offer
a role`).

### On the second axis

It does no work that the first does not already do *for the types that exist
today* - which is worth stating plainly rather than overselling it. It earns
its place for two reasons.

First, it is the honest reason. An attachment on a card is not somebody's
private utterance the way a comment is; it is out of the adoption path
because adding a file does not change what the card means, while rewriting
its description does.

Second, it is the axis that survives finer-grained node types. As soon as an
aspect of a decidable node becomes a node of its own - a board's objective
beside its name, a card's labels beside its description - authorship cannot
discriminate, because both are writable by everyone. Significance can.

### It is already computed

S-Team hashes `agreement_reference_hash` over

```text
{agreement, agreement_section, agreement_clause}
  + {agreement_role, agreement_accountability, agreement_domain}
```

and an acceptance goes `outdated` when that hash changes. That set is, exactly,
"what materially changes what I hold" - already declared, already replicated,
already load-bearing. It is identical to the decidable set derived here.
Significance is not a new judgement being introduced; it is a boundary S-Team
has been relying on under another name. S-Initiative has no equivalent only
because it has no acceptance to invalidate.

### Declare it per type, never per reader

"Things I do not care about" is the right intuition at the wrong
granularity. `_offer_authority_guard` is built so that *"every side reaches
the same verdict, because it reads only replicated state"*. If significance
varied per user, two clients would disagree about whether a node was
adoptable at all, and convergence would depend on who was looking. Fixed at
design time it stays objective.

### Two questions that sound alike

`decidable` is *must this be consented to before it merges*.
The reference hash is *does this re-open consent already given*.

They are related but not equal, and trustee roles are what separate them: they
are decidable (see §5) but correctly absent from the reference hash, because a
change of trustee does not alter the text anybody agreed to.

## 4. Persistence is a separate question

Hiding inside "observed" is a second question that is not about consent at
all: **does my copy need to survive the author becoming unreachable, or can I
read it from them when I need it?**

- **Read through** - not stored locally. Read from the subject's replica on
  demand. When they are unreachable the fact is *unobservable*, and must be
  reported as such rather than guessed at. S-Team already does this for role
  answers, and already has the vocabulary: `unobserved` is deliberately not
  worded as `pending`, because "they have not answered" and "I cannot see
  whether they have" are different facts.

- **Persisted** - merged on receipt and kept. Needed where the fact must be
  usable while its subject is offline. `_offer_authority_guard` has to decide
  whether an incoming offer was authored by the trustee, and it must be able
  to do that without reaching them.

Both share everything that matters about being observed: no proposal, no
reaction, no divergence row, no auto-adopt setting. Persistence is a storage
property, not a third kind of consent.

### The invariant persistence requires

> **A persisted copy of somebody else's record is a fallback, never a source
> of truth. Where the subject's own replica is reachable, it wins.**

Without this, persistence reintroduces precisely the bug the hearsay rule was
written to prevent: A changes their answer, my stale copy still looks
authoritative, and I report a fact about A that A does not hold. S-Team's
`_observed_decisions` already states the rule for the read-through case - *"a
peer's copy of a third party's answer is hearsay, and nothing signs content,
so it is not counted"* - and it must hold identically for persisted records.

Corollary: a persisted record displayed while its subject is unreachable is
*last seen*, not *current*, and should say so.

## 5. Classification of every node type today

`M` = more than one writer. `S` = materially significant. Decidable requires
both.

### Core's own

| Node type | M | S | Class | Storage |
|---|---|---|---|---|
| `agenda_item` | no | - | observed | read through |
| `shared_user_profile` | no | - | observed | persisted |
| `folder`, `peer_cache_root` | - | - | structural, never shared | - |

An agenda item is one person's request to discuss something. It is read
through rather than persisted for the reason that settles it: there is no
point holding a discussion item belonging to somebody who is not there.

### S-Team

| Node type | M | S | Class | Storage |
|---|---|---|---|---|
| `agreement` | yes | yes | **decidable** | - |
| `agreement_section` | yes | yes | **decidable** | - |
| `agreement_clause` | yes | yes | **decidable** | - |
| `agreement_role` | yes | yes | **decidable** | - |
| `agreement_accountability` | yes | yes | **decidable** | - |
| `agreement_domain` | yes | yes | **decidable** | - |
| trustee roles (`agreement_identity`, …) | yes | yes | **decidable** | - |
| `agreement_role_offer` | no (trustee) | - | observed | persisted |
| `agreement_role_decision` | no (the actor) | - | observed | read through |
| `agreement_role_holding` | no (child's trustee) | - | observed | persisted |

### Trustee roles

Identity is not a special node. It is the first instance of a **trustee role**
(German *Treuhänder*): a role held on behalf of the team rather than for the
holder's own participation in it. There will be more, and they share a shape
ordinary roles do not:

- **Exactly one holder.** DESIGN_ROLES_AND_ACTORS.md §1.3 records this of
  Identity as being "shaped differently from other roles because of
  cardinality, not privilege". That is the trustee property, named there as an
  exception rather than as a class.
- **Held for the team.** An ordinary role is work somebody takes on. A
  trusteeship is an authority carried *for* the body - to speak for it, to
  commit it, to keep something of its on its behalf.
- **Encoded as one node whose holder field is rewritten**, not as an
  offer/answer pair. It needs no consent protocol layered on top, because the
  protocol's own semantics already express consent: a handover is a divergence,
  and adopting it is accepting (§2.2 there).
- **Vacated only by explicit resignation.** Expiry marks a norm; it does not
  release the seat.

Trustee roles are **decidable**, and that is a result rather than an oversight.
The node is genuinely multi-writer by design: the holder writes a handover,
*and a claimant writes a competing holder into the same node* - the warned
self-install of §2.2 is the whole resolution mechanism. Two writers, real
divergence, real conflict.

The consequence is that a trustee stepping out stays something the other side
adopts. That is not a gap to be closed by making it automatic; it is the same
consent path as every other change of trustee, and the fix for it not being
visible is presentational.

Everything above is a property of the class, not of Identity. A second
trusteeship inherits the classification, the guards and the resolution
mechanism without a new Core declaration - provided it is encoded as one, which
is what §7 asks.

### Seats are consented to by authorship, not by adoption

`agreement_role_offer`, `agreement_role_decision` and `agreement_role_holding`
are all observed, which raises the fair question of where a seat is consented
to at all. The answer is that nobody ever adopts anybody's holding:

- the offer is the trustee's own record, written by them;
- the decision is the actor's own record, written by them;
- and a holding is live only while both exist.

Consent is expressed by **authoring your own record**, and the holding is
exactly the overlap of the two. There is nothing for a third party to adopt,
which is why these sit outside the adoption path even though a seat is as
consequential as anything in the document.

`agreement_role_holding` is the child side of a cross-topic edge, and exists
only where the actor is a Team. An individual is not a topic: their decision
lives in the parent's topic and is readable by them there. A Team *is* a topic,
and the seat it holds is part of what that team *is* - the parent's agreement is
the basis its own agreement rests on.

A document has to state its own basis, in its own topic. Recording the seat
only in the parent would leave B's members reading a document whose founding
dependency is written down somewhere else, which they may not be holding at the
moment they need it. That is why the child keeps the record, and it is why the
record is the child trustee's to write.

Note this is *not* justified by B's members being able to avoid the parent.
**You are on a team only by holding a role on it, and that goes for every team
above it.** Being on B is being on A, so B's membership is contained in A's -
and in the membership of every parent B has, since a second parent is a second
commitment rather than a spare route around the first. The role above may be
the smallest "member" role there is; what matters is that it exists.

Three things follow, all of them now implemented in S-Team:

- A team may take a seat only if everybody already on it holds a role in the
  parent. Otherwise accepting the seat carries them into an agreement they
  never took a role in - and shuts the team for them, including for the
  trustee who accepted it.
- Losing a role above is losing the team below, for that person, derived and
  never recorded, so it reverses itself when the role above is taken up again.
- The roster has to say so. Invalidity above was derived only for whoever was
  reading, so everybody else went on being shown as accepted, and a team's own
  member list stated something untrue about them.

The containment is **observable, not enforceable**: a role held on a replica
this session cannot reach reads as unheld. The seat check therefore refuses
and names the people it cannot place, rather than guessing.

The difference from an individual's holding is therefore not that a Team needs
somebody to speak for it - that is carried by `decided_by` on the ordinary
decision node, and an individual's acceptance and a Team's acceptance are the
same node type in the same place. The difference is that one of the two parties
is a topic with a membership of its own.

### S-Initiative

| Node type | M | S | Class | Storage |
|---|---|---|---|---|
| `initiative`    | yes | yes | **decidable** | - |
| `kanban_column` | yes | yes | **decidable** | - |
| `kanban_card` | yes | yes | **decidable** | - |
| `card_comment` | no (author) | no | observed | persisted |
| `card_attachment` | no (author) | no | observed | persisted |

This reproduces `DISPLAYED_DIVERGENCE_TYPES` exactly, which is the point: the
classification is derived rather than chosen, and it agrees with the judgement
somebody already made.

## 6. The Core contract

The classification is declared once, at application registration, and Core
enforces it. `ApplicationRegistration` gains one field:

```python
@dataclass(frozen=True)
class NodeClass:
    decidable: bool
    persisted: bool = True   # ignored when decidable

@dataclass(frozen=True)
class ApplicationRegistration:
    ...
    node_classes: Mapping[str, NodeClass]
```

Core declares its own types (`agenda_item`, `shared_user_profile`) and
applications declare only theirs. An undeclared type is an error at
registration rather than a silent default, so a new node type cannot ship
unclassified.

### What Core enforces

1. **Transitions are computed and surfaced only for decidable nodes.** This
   replaces `DISPLAYED_DIVERGENCE_TYPES` in S-Initiative and supplies the
   filter S-Team never had.
2. **The reaction API refuses an observed node.** `accept_peer_node` and
   `rollback_peer_node` return an error rather than adopting one.
3. **Observed nodes never appear in a proposal list.** This replaces the
   `REACTABLE` check in `_proposed_nodes`.
4. **Persisted observed nodes merge on receipt**, without a decision and
   without an auto-adopt mode being consulted. This replaces the hand-written
   comment and agenda special cases in S-Initiative's `eligible()`.
5. **Read-through observed nodes are never merged.** They are read from the
   subject's replica, and their absence is reported as unobservable.
6. **Auto-adopt modes apply to decidable nodes only.** They are a policy about
   consent, and there is no consent to have a policy about elsewhere.

### What stays with the application

Which of its own types are which, and nothing else. The credibility rule -
that a record about an actor is authoritative only from that actor's replica
- is Core's, because it is the same rule for every application and is already
implemented twice.

## 7. What this does not settle

- **Retention.** Persisting observed records means holding data about people
  after they have gone. It is necessary - you cannot know who agreed to what
  otherwise - but it is a retention decision this document does not make.
- **Per-field significance.** The second axis is defined per node type. A
  decidable node whose *fields* differ in significance (a board's objective
  beside its name) is not addressed here, and would need either finer node
  types or a field-level declaration.
- **How a trusteeship is encoded.** Identity is `agreement_identity` today: one
  node type for one trusteeship. A second one added the same way needs a second
  node type, a second Core declaration and a second set of guards, and the
  class's shared semantics live only in whatever both copies happen to agree
  on. The recommendation is one node type - `agreement_trustee`, carrying
  `trust: "identity"` and a holder - so every future trusteeship inherits the
  classification, the resolution mechanism and the authority guard for free.
  That is a persisted node type, so it is a data migration on live instances,
  not a rename.

- **Whether the `agreement_` prefix should become `team_`.** The prefix names
  the topic type, not the actor, so it is not made wrong by Actors being
  Individuals or Teams. But if the topic itself is a Team in the vocabulary -
  which the interface now says - then `team`, `team_section`, `team_role`,
  `team_role_holding` follow, and the code stops using one word for the
  document and another for the body. Same cost: these strings are in persisted
  data on running instances, so it needs a migration or a read-compatibility
  shim, and it should be done in one pass with the trustee change rather than
  twice.
- **Signing.** None of this is a security boundary. Nothing in the protocol
  signs content, so "only the author may write this node" holds exactly as far
  as trusting the peers you chose to sync with - as recorded in
  DESIGN_ROLES_AND_ACTORS.md §2.1 and unchanged here.

## 8. Migration

1. Add `NodeClass` and `node_classes` to `ApplicationRegistration`; accept a
   missing declaration for one release so nothing breaks on upgrade.
2. Declare Core's own types. Remove `agenda_item` from both applications'
   `OWNED_NODE_TYPES`.
3. Move transition filtering into Session behind the declaration. Delete
   `DISPLAYED_DIVERGENCE_TYPES` and `_is_displayed_divergence` from
   S-Initiative; S-Team gains the behaviour it never had.
4. Enforce the reaction refusal and proposal exclusion in Session. Delete
   `REACTABLE` from S-Team.
5. Merge persisted observed nodes on receipt in Session. Delete the
   `card_comment` and agenda special cases from S-Initiative's `eligible()`.
6. Make the declaration required.

Steps 3 and 4 are what clears S-Team's divergence list. Step 5 is what makes
a peer's comment appear without anybody adopting it, which is already the
intended behaviour and is currently achieved by a comment in a callback.
