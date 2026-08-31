# Connected: navigation links and connected work

Status: built.

The row below a topic title, and the dialog behind its chevron, answer one
question — "where else does this connect?" — with two different kinds of
fact, both Core-owned, both reached through the same UI.

## Local navigation links

A plain shortcut between two topics this client already holds. Not a
protocol node, and no claim that the source and destination are related.

Core stores `{uuid, parent_uuid, topic_uuid}` in the local session envelope.
Titles, application ids, and routes are resolved live from registered
topics. Consequently a shortcut:

- is not hashed, published, adopted, or counted as a change;
- cannot grant or invite access — the target must already be held to add one;
- does not prevent dropping a topic, and is removed when either end is dropped;
- is managed through `/api/core/navigation/{topic}`.

Use this when a connection is worth remembering but sharing it is not the
point — a team linking to an unrelated reference topic, say.

## Connected work

`sovereign_relationship` (`src/sovereign/relationships.py`) is different on
every count above: it *is* a protocol node, a direct child of the topic it
connects from, and creating or connecting one also publishes the target
wherever the source already publishes
(`CollaborationService.bridge_topic_like` / `join_bridged_topic`) — "this
team runs that initiative" is a claim other people on the same relay should
see, not a private bookmark.

Several actors may each write their own statement about the same target.
The connection reads as live while any of them survives
(`RelationshipService.relationships`), and drops only when the last author
removes their own — the union that makes "the team's work" a fact several
members can independently vouch for, not one person's private note.
Adoption is `auto`/`never`, same-origin: it is evidence of who said so, not
something negotiated.

`RelationshipService.relationship_candidates` offers exactly what the
picker shows:

- **already here** — topics that already share this one's bridge
  (`topics_share_a_bridge`) and are not yet connected;
- **your other items** — this client's other held topics of a registered
  kind that do not share this bridge yet; connecting one bridges it as part
  of the same act;
- **new** — `topic_kinds()`, reused as-is, for making one from nothing.

Both candidate groups, and the row-level create/connect calls, restrict
themselves to topics whose `application_id` is one `topic_kinds()` actually
offers to create — Core's own bootstrap topics (the identity profile and
the like) have no `topic_noun` and are not "work" in any application's
sense, so they never appear as a candidate either.

**This was previously three separate implementations.** S-Team's
`team_item_relationship` had this same union/bridging behavior; S-Initiative's
`initiative_relationship`, built the same session, copied its shape but not
its bridging call, so a team or flow named from an initiative was never
actually shared with anyone; S-Flow had nothing. All three are retired in
favor of this one mechanism.

### Application-specific rules, without Core knowing application vocabulary

An application that needs a constraint Core cannot express generically —
S-Initiative's "at most one team" — registers `validate_relationship(parent,
target) -> SessionResult | None` on its `ApplicationRegistration`
(`topic_registry.py`). `None`, or an "ok" result, allows the connection; any
other result is the refusal reason, checked before Core writes the node.
Most applications register nothing here.

`/api/core/relationships/{topic_uuid}` (`app_server.py`) is the single
route: `GET` for the current connections and both candidate groups, `POST`
with `action` one of `add` (an already-held topic), `create` (new, shared),
`connect` (pull in what somebody else already shared), `remove` (this
actor's own connection only).
