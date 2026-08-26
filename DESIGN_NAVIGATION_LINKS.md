# Local navigation links

Status: built.

The links below a topic title are local shortcuts between topics this client
already holds. They are not protocol nodes and make no claim that the source
and destination are related.

Core stores `{uuid, parent_uuid, topic_uuid}` in the local session envelope.
Titles, application ids, and routes are resolved live from registered topics.
Consequently a shortcut:

- is not hashed, published, adopted, or counted as a change;
- cannot grant or invite access—the target must already be held to add it;
- does not prevent dropping a topic and is removed when either end is dropped;
- is managed uniformly by the shared shell and `/api/core/navigation/{topic}`.

Actual relationships belong to the application whose domain gives them
meaning. S-Initiative owns `initiative_relationship` in its Mandate, and S-Team
owns `team_item_relationship` in its Work section. Those nodes may travel and
diverge under their applications' rules; Core does not interpret them.
