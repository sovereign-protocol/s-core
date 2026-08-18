# Topic links

A topic is referenced from somewhere else: a team lists the flows it runs, a
card names the process it waits on, a cockpit holds everything this client has
made. Three applications answer that need three ways, none of which the others
understand, and one of them answered it so badly that removing a flow from a
team destroyed it for everybody who held it.

This proposes one shape for a reference, kept by Core, and two acts on it that
are not the same act.

## What already exists

Core has more of this than the applications use.

- **`leave_topic`** (`session.py:1251`) stops sharing a topic and says nothing
  to anybody: *"No message goes out. A relay peer is told by absence: this
  client stops publishing into the slot, and stops polling theirs."*
  `end_topic_sharing` adds releasing the channels.
- **`session.delete`** writes a tombstone. It travels, and peers adopt it.
  This is the one the applications reach for, including where they meant the
  first one.
- **`pending_topic_invitations` + `mount_cached_topics`** (`session.py:776`)
  find topics a peer holds that this client does not, match them against the
  owning application's registered root types, and hand them to that
  application to accept.

So "stop holding this quietly" and "a peer's reference is an invitation" are
both already here. What is missing is a way for an application to *say* that
one node references a topic, in a form another application can read.

## The model

A **link** is a node that references a topic. It says where the reference is
and nothing about what the topic contains.

- Applications own **where links live** — a link is an ordinary child of
  whatever refers to the topic, so a card's link hangs off the card and a
  team's off the team. Core does not keep a table of them.
- Core owns **what a link is**: the node type, the field naming the topic, and
  what following one does.
- Bookkeeping is **derived**. "Where do I reference this topic from" is a walk
  of this client's own tree. Nothing is stored, because nothing needs to be:
  the links are the record.

### Vocabulary

| Field | Meaning |
|---|---|
| `topic_uuid` | the topic referred to |
| `application_id` | which application owns that topic, for routing and for a label |
| `title` | what to show before the topic is held, when its own name cannot be read |

`title` is a convenience copy and may be stale. It is what a link says when
the thing it points at is not here yet; once the topic is held, its own name
wins.

## Two acts, and a third that stays where it is

**Remove** deletes the link. One reference, gone. The topic is untouched, and
so is every other reference to it — including other people's.

**Drop** stops this client holding the topic at all: `end_topic_sharing`, then
remove the subtree from the local tree. Offered only when Core reports no
remaining link from this client. Nothing is published, because nothing was
deleted — a peer sees this client stop publishing, which is what it also sees
when somebody closes their laptop.

**Delete** is not either of these and does not move. It stays with the
application that owns the topic, which is the only one that knows who may
destroy it. That rule is unrelated to how many links exist.

The distinction is the whole point of the note. Removing a flow from a team
called `delete_process`, so taking it off a list destroyed it everywhere and a
member who had not created it could not take it off at all.

### The count is about this client only

"No other link" means no other link *here*. It is a closed question about one
tree, not a claim about the network, and it gates only a local drop. Nothing
in this design lets one client destroy a topic another peer publishes, and the
protocol should not allow it: a deletion is authored by whoever owns the
topic, and adopting one is the recipient's decision.

## Following a link you do not hold

A link to a topic this client does not have is not broken. It is an
invitation, and the path already exists: `note_pending_topic_invitation`, then
`mount_cached_topics` for the owning application, which mounts it if a peer's
perspective carries it.

That makes the reverse of a drop explicit. After dropping a topic, a peer who
still publishes it offers it back as an invitation. Intended: nothing was
destroyed, this client stopped keeping it, and it remains available. Worth
saying out loud, because "I removed it and it came back" is otherwise a bug
report.

## Consequences

**S-Team's item lists collapse into links.** `team_item_list` is a chain of
per-actor snapshots, each carrying a *list field* of items — the one list
field in the codebase, safe only because a single author replaces their own
list wholesale. With links, each member's reference is its own node: the
team's list is the union of them, removing yours leaves everybody else's
standing, and the list field goes.

**The withdrawal set disappears.** Offering an item currently means being
computed into a derived list, so declining to offer it needs a stored
exception (`withdrawn_items`) — a decision that nothing else records. With an
explicit link, offering *is* creating a node and removing *is* deleting one.
The decision becomes the record, and the exception set is not needed.

Which also decides how a link is declared for adoption: `auto` and
`same-origin` once held, so its author's removal travels as their offer did
and nobody else may write it. Not `never` as a governance record is — a record
is appended and stands for good, while a reference is put up and taken down,
and freezing one would need a second record saying it had been withdrawn,
which is the shape the exception set had.

**Initiatives and flows get references for free.** Neither has any today. A
card naming the process it waits on is the same node type as a team naming a
flow it runs.

## Open

- **Whether a link is adoptable.** Settled for an initiative's links and only
  those: they are ordinary children of the topic, so they replicate and appear
  in the divergence list like anything else there. Two clients disagreeing
  about which team an initiative belongs to is worth a human seeing, and since
  a link's data never changes once written — a reference is replaced, not
  edited — the only divergence it can produce is present-on-one-side, which is
  exactly the decision worth showing. A card's link to a private topic is the
  case still open: a reference to something the reader cannot reach, where a
  permanent invitation may be noise rather than information.

  **Where it renders is settled** (`DESIGN_UI_CONSISTENCY.md` U6): a link on
  the topic itself is drawn by Core in the bar, beside the topic's name; a
  link on a node inside the topic is drawn beside that node. Beside the card
  an unreachable reference is information; in the topbar it would be noise.
  Same-origin also answers who may remove one, and it is not a rule any
  application sets: `remove_topic_link` refuses a link this client did not
  author, because a deletion written over somebody else's reference is one
  their peers refuse and the next sync brings back.
- **What a drop leaves behind.** Links elsewhere in this client's tree that
  pointed at a dropped topic become unheld references. They should render as
  invitations rather than as errors, but nothing prunes them.
- **`prune_deleted_nodes` is not this.** It removes tombstoned subtrees once
  every peer has confirmed the deletion. A drop needs removal of a subtree
  that was never deleted, which no public method offers yet.

## Sequencing

1. **Built.** The link node type and `links_to(topic_uuid)` in Core, plus a
   local drop that removes a subtree without writing a deletion. Also
   `create_topic_link`, `remove_topic_link`, `topic_links`, `topic_link` and
   `follow_topic_link`; the contract is in `PUBLIC_API.md`.
2. **Built.** The Cockpit offers "Stop holding it" beside Delete on an
   initiative and on a team, over `/api/cockpit/topics/drop`. Remove is not
   there and does not belong there: the Cockpit holds no links, so a reference
   is removed where it lives, which is the page that made it.
3. **Built.** S-Team writes links instead of item lists; `team_item_list` and
   `withdrawn_items` are gone, along with the record's schema check, its
   assessor and its container. Each member writes their own reference, the
   team's list is the union of those authored by current members, and the
   membership test moved from the moment a record arrived to every read — so
   somebody leaving stops naming items at once, with nothing to rewrite.

   Two things it turned up that this note had not:

   - **A duplicate is per author, not per parent.** Two members referencing
     one topic from one team is not a duplicate, it is the mechanism. Core's
     guard now refuses only what the same client already wrote, and an
     application that wants one reference whoever wrote it — an initiative
     naming its team — says so itself.
   - **A reference is not a claim to hold a copy.** A list said "I hold this"
     and had to be recomputed when that stopped being true, which is why
     declining to offer needed a stored exception. A reference says the team's
     work includes this; whether a copy is held here is read from the tree as
     `active`. Deleting your copy therefore leaves the item on the team,
     shown as not held, instead of quietly taking it off. That is a change of
     meaning, and it is what lets the exception set go.

   One thing still remembers a refusal: an election is the only item taken up
   without being asked, so removing one is recorded locally as declined. That
   is not the withdrawal set returning — that one stopped a derived list from
   resurrecting a decision, and there is no derived list now; this stops an
   automatic adopter, which is still there.
4. **Built for S-Initiative.** An initiative names the team it belongs to (at
   most one, which is this application's rule and not Core's) and the flows it
   runs, as direct children of the initiative topic. S-Flow writes no links
   yet; a card naming the process it waits on is the obvious next one and is
   the same node type in a different place.

### And one thing that turned out to be here already

S-Flow's `leave_process` — "this removes the shared flow from your Cockpit,
the creator keeps it" — took the creator's own path: end sharing, then write a
deletion. That was correct only by arithmetic. The tombstone did not travel
because the peer set had just been emptied, and it was pruned locally for the
same reason; nothing about the intent said so, and releasing the channels is
an effect the runtime delivers *afterwards*, so a poll landing in between had
a tombstone to publish. It is `drop_topic` now, which writes no deletion to
get the ordering right about.
