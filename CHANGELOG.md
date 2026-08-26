# Changelog

## 0.1.9

- **The header's "Connected" dialog now covers connected work, not only
  local shortcuts.** A new Core-owned `sovereign_relationship` connects one
  topic to another the way S-Team's Work section always did — per-actor
  authored, live while any author's connection survives, and shared
  wherever the source topic already publishes
  (`bridge_topic_like`/`join_bridged_topic`) — but as one mechanism every
  application gets for free, at `/api/core/relationships/{topic_uuid}`,
  instead of three separately-built ones. The picker offers what's already
  on this relay, what's this client's own to share, and a "New `<kind>`"
  that creates and shares in one act. Applications with a domain rule Core
  cannot know — S-Initiative's "at most one team," S-Team remembering an
  election was actively declined rather than never taken up — register a
  `validate_relationship` or `on_relationship_removed` hook on their
  `ApplicationRegistration` instead of Core special-casing their vocabulary.
  Local navigation links are unchanged and sit in the same dialog for
  connections that are not work.

- **Reaction buttons stay short while their explanations stay precise.**
  Every direct control reads `Adopt` or `Take back`; its tooltip and accessible
  name identify the actor, object, and fields involved. Menus retain the full
  action sentence on each choice.

- **Shared selects and reorder handles now work across their whole face.** A
  page-level `max-width` could cap the transparent native select before the
  drawn chevron, and reorder items supplied through `getId` were not given the
  identity the nested-list guard requires. The chevron now opens the select,
  and both pointer and keyboard reordering reach application-owned lists.

- **A reaction to several field edits names the fields.** The explicit tooltip
  can now say `Take back my initiative name and intention changes` instead of
  the ambiguous `Take back my initiative modification`.

- **Held generic fields explain their policy with a quiet outline hand.** The
  effective inherited adoption policy now travels with binding views, and the
  shared decoration hides the hand whenever an actual transition is present.

- **Links below a topic title are local navigation metadata.** They are no
  longer protocol nodes, never publish or adopt, require both topics to be
  held, grant no access, and do not prevent a topic being dropped. Core owns
  their store, API, menu, and live route/title resolution.

- **The shell's agenda count follows the Cockpit's renamed tile family.** The
  optimistic update read `draft.boards`; that key is `draft.initiatives` now.
  Nothing else in Core named it, and the comments that described a topic as "a
  board" now say topic or initiative — Core does not own either noun.

- **An object is drawn from its kind, and from nothing else.**
  `ENTITY_GLYPHS` maps an entity kind to its paths; `entityBadge({kind})`
  reads the drawing from there, `SovereignUI.entityGlyph(kind)` exposes the
  same table to a surface that draws its own row, and `disclosure` takes a
  `glyph` kind so a section carries the mark of what it holds. `entityBadge`
  no longer takes an `icon`: S-Team was passing a key emoji for a
  trusteeship, an open diamond for a role and a filled one for a membership —
  three drawings chosen at three call sites, for objects Core already had
  names for, all three under one kind. See `DESIGN_UI_CONSISTENCY.md` U8.

- **A pairing is a property of the link, and a generation number is not guesswork.**
  `pair_all_topics` moved from the consent map to the target record, which is
  what it always described: only pairing sets it, nothing clears it, and it
  says that this link carries a sibling. It is projected onto the connection
  for its three readers and written nowhere else, and an edit to a target
  carries it across - a corrected host does not unpair a link.

  Giving a paired channel a target record to hold it needed `_refile_primary`:
  a connection is keyed by storage fingerprint, primary is filed as
  "unconfigured" while it has none, and nothing re-filed it when it adopted
  one - so registering the descriptor would have missed primary and built a
  second writer to the slot it had just taken.

  And `publish_due_topics` now recovers `publication_seq` from the head it
  published, when there was no state file to load. Starting again at zero left
  every peer holding a higher number ignoring the acknowledgement for good.
  Gated so an ordinary restart asks the relay nothing; a first start or a
  deleted file pays one read per topic, once. The state file may now be
  deleted at any time with no consequence beyond a republish and a refetch.

- **A paired client records the pairing once it has one.**
  `accept_pairing_token` wrote `relay_paired_client_id` before binding any
  channel, so a token naming a relay the client could not open left the session
  claiming a pairing that reached nothing. It is written after the channels
  now. The ordering was justified by the state file being keyed by identity,
  and by connections reading their identity from that metadata; neither holds -
  the file is cache, and `_adopt_pairing_channel` sets `connection.identity`
  outright. Every connection `RelayManager` builds now resolves its identity
  the way `RelayLogic` does, honouring the paired client id instead of falling
  through to this session's uuid, which is what made the second half true.

- **Where a topic syncs and whether it syncs are both the session's now.**
  `desired`, `shared`, `identity_topics` and `pair_all_topics` moved out of the
  relay state file into the session's private relay metadata, keyed by target
  id rather than by identity and storage location. The state file holds cache
  only and may be deleted at any time; the worst it costs is a republish and a
  refetch. Deleting one used to empty the consent it held, which unarmed
  publishing and stopped inbound grafting with no error anywhere and a
  perfectly healthy-looking connection.

  Three things went with it, none of them ported: `update_target`'s
  forty-five-line hand-carry of intent from the old connection to the new one,
  which existed only because consent was keyed by location; the one-time
  migration that read intent out of the state file to seed topic-to-target
  assignments; and the legacy `configured` key stripped from older target
  records. A connection reads the union of consent across every target it
  serves, since two targets may name one relay, and writes to the one it was
  built for. See `DESIGN_RELAY_CONSENT.md`.

- **A relay state file belongs to a connection, and does not outlive it.**
  `relay_state_directory` now places the file for every connection an instance
  makes, the implicit one built from the flat config included; it reached
  connections built from a target only, so an instance that set it went on
  writing into the shared `data/` beside its working directory anyway. A
  retired connection now deletes its state file rather than persisting an
  emptied copy of it, and a connection that re-keys to an adopted location
  deletes the file its boot-time path left behind - the reload after a re-key
  already discarded that file's contents, so keeping it only ever left
  residue. Found live: a `data/` holding 48 relay state files, 46 of them
  all-empty and none attributable to anything still configured - one per
  connection ever retired, per location ever abandoned.

- **An application says how its own topics are made, once.**
  `ApplicationRegistration` takes `topic_noun`, `template_required`,
  `list_templates` and `create_topic(title, template, snapshot)`; Core answers
  `Session.topic_kinds()` and `Session.create_application_topic(...)` from
  them. All three ways of starting are one call — from nothing, from a
  template the owning application listed, or from a snapshot document it
  exported — and Core reads neither the template id nor the document.

  This replaced a table in each of three applications: the Cockpit, S-Team and
  S-Initiative each carried a noun, a facade api version, a per-kind template
  lookup and a create path per kind, all restating what the owning application
  already knew. They had drifted, too — one could start a team from a file and
  another could not. An application that registers none of the four simply
  cannot have its topics made from elsewhere, which is the right answer for
  one that owns none.

- **The bar says what you are looking at and where else you can go.**
  `setTopicSelector` becomes `setTopicName` — a name, edited in place, with
  no list of the application's other topics beside it: reaching another topic
  goes through the Cockpit, which is the principle the shell already stated
  and the switcher predated. `setTopicLinks({links, make, link, onFollow,
  onRemove})` supplies what this topic references.
  `topicHref(applicationId, topicUuid)` composes any application's topic URL
  from `application_summaries()`, so no application knows another's route —
  every application now opens a topic through `?topic=<uuid>`.

  The bar is five objects on three regions — collaboration, navigation,
  connections. `[Agenda · N]` and `[Changes · N]` on the left, each counting
  only what it is named for. The topic centred in the middle under its
  application's mark, with a row of destinations beneath it: the topics this
  one names, then everything you hold. Who is here on the right. It had grown
  thirteen visual treatments across four border languages, three corner radii
  and five type sizes, with a grid that could not centre anything; the shape
  vocabulary is now two shapes, two type sizes, and no border at rest.
  `setAppActions` is gone with it — the bar holds nothing of an
  application's. See `DESIGN_UI_CONSISTENCY.md` U7.

- **One word per concept, decided before the pixels moved.** "Topic" was
  Core's protocol noun, an agenda field's placeholder and a word nobody
  applies to their own team; "Aligned" collided head-on with S-Team's
  Agreement, which is a document people accept; one sync state carried four
  surface words and people carried three. The user-facing vocabulary is now
  fixed — changes, needs your review, conflict, waiting on others, adopt,
  people — while every internal name is untouched, because they are precise
  and nobody reads them. There is deliberately no collective noun: where the
  shell must name an initiative, an organization and a flow at once it
  composes from `topic_noun` or avoids the noun. See `DESIGN_VOCABULARY.md`.

- **Icons have three classes and three construction rules.** An application
  mark depicts what the application holds and is built from whole shapes that
  survive 18px; an object glyph carries one idea in four strokes; an act uses
  the conventional drawing and is never invented. The three destructions stay
  visually apart, because conflating them once cost a list removal that
  called `delete_process` and destroyed the thing everywhere: a minus in a
  circle is off my side and reversible, a trash can is gone for everyone, and
  `×` is reserved for close so it can never be read as either. See
  `DESIGN_UI_CONSISTENCY.md` U8.

- **Third-party icon attribution.** `NOTICE` gains an MIT section for the
  Feather-derived paths and the Tabler-derived geometry, with `LICENSES/MIT.txt`
  beside it. It says which marks are original and is given as a precaution
  where a shape is merely the obvious drawing of its object.

- **A reference is removed by whoever wrote it.** `remove_topic_link` refuses
  a link this client did not author. A link is adopted same-origin, so a
  deletion written over somebody else's reference is one their peers refuse:
  locally gone, remotely standing, and back on the next sync. Saying so once
  beats leaving it to be discovered.

- **One dialog makes a topic, wherever it is made.**
  `SovereignShell.openNewTopicDialog({noun, templates, templateRequired,
  blankLabel, snapshotType, onCreate})` asks the three questions that making a
  topic always asks — what it is called, what it starts from, or a snapshot
  file instead of both — and hands the answers back. Core owns the shape, the
  wording built from the noun, and reading and refusing a snapshot file; the
  application owns what a template is and what creating actually calls. There
  were four copies of this form, three in the Cockpit and one in S-Team, and
  the S-Team one was the only place a snapshot could not be loaded — nobody
  decided that, it is what a copy costs. See `DESIGN_UI_CONSISTENCY.md` U5.

- **Topic links, and the three acts that are not the same act.** A `topic_link`
  node records that one node references a topic; applications own where links
  live, Core owns what one is and what following it does. Nothing keeps a table
  of them, because the links are the record: `links_to(topic_uuid)` walks this
  client's own tree. `remove_topic_link` deletes one reference and leaves the
  topic and every other reference to it, including other people's.
  `drop_topic` stops this client holding a topic — it ends sharing and removes
  the local subtree *without writing a tombstone*, so nothing is published and
  a peer sees only that this client stopped publishing; it refuses while any
  link here still points at the topic, and that count is a closed question
  about one tree rather than a claim about the network. `Session.delete` is
  neither of those and stays with the application that owns the topic, the only
  one that knows who may destroy it. `follow_topic_link` treats a link to a
  topic this client does not hold as an invitation rather than a broken
  reference, mounting it where a peer's perspective carries it and saying
  nobody is publishing it where none does — so a link names a topic and is
  never a key to it. See `DESIGN_TOPIC_LINKS.md` and `PUBLIC_API.md`.

  A duplicate is judged **per author**, not per parent: two actors referencing
  one topic from one parent is not a duplicate but the mechanism by which a
  team's list of what it runs is the union of its members' own references, and
  by which removing yours leaves everybody else's standing. `topic_links` and
  `links_to` take `authored_here` to tell the two apart, and `topic_links`
  takes a parent. An application wanting one reference whoever wrote it says
  so itself.

- **One palette for transition state, defined once.** A stage now has a colour
  token in `shared.css` — conflict, awaiting me, in transition — in two tones,
  because coloured text on a dark header and a filled dot cannot be the same
  hex and still read as the same colour. `@keyframes stage-pulse` moved here
  too: it was defined in one application's stylesheet, so the one surface that
  happened to own it was the only one that could use it.
- **The topic header reports every band, not only the worst.** One thing to
  review and one still travelling are two facts about two nodes, and an
  if/else chain showed the first and hid the second. Aligned now says nothing
  at all — the button's tooltip still says so on hover.
- Added `Session.ensure_container(parent_uuid, name, node_type)`: a named
  child an application uses to name a *place* rather than a type. It hands
  Core the container's uuid, so ordering, adoption declarations and hash
  scopes address somewhere in the tree instead of a string inside `data`.
  A new container takes a uuid derived from its parent's, which is what lets
  two clients arrive at the same one without either adopting it from the
  other: the data is identical and neither timestamps nor uuids enter the
  content hash, so the copies reconcile as agreement rather than as a change.
  A peer's child then finds its parent already present, which a container
  invented independently on each side would not.
- `Protocol.create_child` accepts a caller-supplied `node_uuid`. Neither hash
  covers the uuid, so it is assigned before the node is indexed and the
  signature is applied afterwards as usual. A uuid already in use is refused.
- Agenda items now hang off a container of their own rather than the topic
  root, and `project_nodes(topic_uuid, parent_uuid)` takes the container in
  place of a node type. The container carries the same derived uuid in every
  perspective, so a projection addresses a peer's agenda by *where it is*
  instead of matching a type string against everything in their tree. Core
  declares the container never-adoptable itself, which retires the rule every
  application previously had to remember to declare for `agenda_item`.
- `_ordered_children` and `next_child_order` take `node_type` as optional.
  A container holds one kind, so its uuid says what the type used to.

- Added `Session.reconsider_adoption(topic_uuid)`: an application says its own
  settings changed and Core re-decides everything the topic is holding back —
  dropping the classifier answers derived from those settings and re-asking the
  resolver for the nodes it holds. A declaration alone cannot be the trigger,
  because two application modes may declare identical handling and differ only
  in what their resolver answers. Without it a widened setting took effect only
  on whatever the peer sent next, and if they sent nothing, never. No peer is
  contacted: the snapshot each one last sent is enough to decide against.
- Declared adoption handling is now mandatory and complete: an undeclared topic
  holds everything, and no application supplies an eligibility callback any
  more. Two hooks replace them, each for a different question. A **classifier**
  is asked once, the first time Core meets a node it does not hold, for facts
  that do not move — its answer is stored. A **resolver** is asked every time
  Core meets a node it is holding, for verdicts derived from state that does —
  its answer is never stored, because a recorded verdict would go on being true
  after it stopped being true. The resolver answers `adopt`, `refuse` or
  `defer`; `refuse` outranks a user decision while `defer` yields to it, a
  distinction the old boolean callback could not express. Both run inside the
  session lock in the same pass that applies the result, so a decision and the
  adoption it permits cannot come apart, and an application fault leaves the
  conservative answer in force rather than propagating.
- `reconcile_peer_changes(..., deciding=True)` marks a pass the user asked for:
  it passes through `hold`, which means "wait for me to decide", but not
  `never`. `accept_peer_node` applies the same rule. One topic can therefore
  serve an automatic pass and a manual one without two sets of rules.
- Added per-node adoption metadata: applications record how incoming changes to
  a node are handled — `adopt`, `additions` and `author` — and Core executes the
  record without interpreting what the node means. Resolution cascades from the
  node to the nearest declared default above it, so a topic default plus its
  exceptions replaces an entry per node. Entries are local: not part of any
  node, not hashed, not published, never adopted from a peer, so a sender
  cannot set a recipient's handling. Persisted in the session envelope and
  inspectable through `Session.adoption_metadata_snapshot()`; entries for nodes
  no longer in the index are dropped on restore. Core enforces the record in
  `reconcile_peer_changes` for topics whose application has declared a default:
  an addition is adopted shallowly with parents processed first, so each level
  is a separate decision, and a deletion is refused whole while anything held
  sits beneath it. Bulk primitives cover the writes an application repeats —
  a subtree write optionally by node type, and swapping one `author` for
  another. Settling a timestamp-only difference bypasses the record, as it
  already bypasses application eligibility: converging two copies of the same
  value decides nothing. See `DESIGN_ADOPTION_METADATA.md`.

- **Fixed: an adoption could reach outside the topic it was authorised for.**
  Core classified transitions against a topic-scoped comparison and then
  resolved them against the global node index, so a peer placing a node in
  their copy of a shared topic could reuse the uuid of a node held in another
  topic — overwriting and relocating it — or name a `parent_uuid` in another
  topic and have a node created there. Neither required the target topic to be
  shared with that peer. Application eligibility callbacks did not prevent it;
  S-Initiative was exposed under `always`, its default. `accept_peer_node`,
  `rollback_peer_node` and `reconcile_peer_changes` now confine every adoption
  to the topic that authorises it, checking the destination — the local node
  changed and the local parent a new node attaches to — rather than the
  incoming node's type or the peer's account of where it lives. Refusals are
  traced as `session.confinement_refused`. See `DESIGN_TOPIC_CONFINEMENT.md`.

- Fixed identity/profile resolution across multiple addresses choosing the
  first cached copy. Agenda and other author avatars now use the highest
  verified revision; invalid higher-sequence copies cannot replace it.
- Identity lookup and read-only projections now share one revision-candidate
  resolver. Logical sequences are compared only within an origin; duplicate
  sources are merged and cross-origin conflicts remain explicit.
- Added application-declared `LastWriteWinsPolicy` reconciliation. Core now
  executes scoped timestamp comparison, stale-winner rejection, tie handling,
  and timestamp-only convergence without adding protocol data.
- The perspective staleness window now defaults to two hours in Core instead
  of being declared identically by every application. `max_age_seconds=None`
  projects every verified record regardless of age; an explicit value still
  overrides. The public export surface is unchanged.
- Added verified, read-only perspective projections with provenance,
  multi-address deduplication, and caller-supplied relative and absolute time
  thresholds. Core measures perspective age but assigns no domain freshness.
- Agenda views now project author-owned records across connected perspectives;
  only locally authored agenda records are persisted or mutable. Ordering uses
  wide fractional gaps and never rewrites a foreign perspective.
- Protocol schema 4 is a clean break; schema 3 sessions and wire envelopes are
  rejected without migration.

- Added an application-facing `join_bridged_topic` operation for taking up a
  shared topic bidirectionally. Mailbox channels persist both receive consent
  and the future topic assignment before the first local replica arrives.

- Applications can now compose or accept an ordinary topic invitation through
  the narrow collaboration view. Composition uses the topic's existing home
  channel; channel inventories and implementations remain private to Core.
  This supports admission workflows that publish connection coordinates only
  after an application-level decision.
- Relay presence now refreshes a peer's signed identity profile whenever its
  state hash changes. This fixes one-way name and avatar updates when a peer is
  visible on a shared topic but its identity-home topic is not subscribed.

- Protocol revisions now carry canonical Ed25519 authorship signatures. Core
  identities publish an append-only device-key chain; sibling clients receive
  distinct authorized keys, and invalid or unknown signatures remain visible
  for governance evaluation.
- Protocol schema 3, session envelope 2, connect token 3, and Core profile
  schema 2 are deliberate clean breaks; older stored sessions are rejected.
- Releasing a shared topic now withdraws its durable channel assignment even
  when the application has already removed the local topic node. This prevents
  an explicitly left topic from reappearing during the next relay poll.

0.1.8 was prepared but never published, so everything written for it is
released here. Both the public API and the wire formats changed since 0.1.7:
the release contract adds `LastWriteWinsPolicy`, `PerspectiveObservation`,
`PerspectiveSource` and `ProjectedNode`, and removes nothing, while protocol
schema 2 → 4, session envelope 1 → 2, connect token 2 → 3 and Core profile
schema 1 → 2 are clean breaks - sessions and envelopes written by 0.1.7 are
rejected rather than migrated.

## 0.1.7

- **Fixed: an application page without the confirm modal never rendered.**
  `shared.js` bound `confirmModalCancelBtn`'s handler at the top level, so a
  page lacking that markup threw partway through the file: `SovereignUI` was
  defined, `SovereignShell` was not, and any page calling into the shell
  failed with an empty console and no visible cause. The binding is now
  guarded, matching what `showToast` directly above it already did, and
  `confirmAction()` raises a named error instead of a null `TypeError` when a
  page asks to confirm without the markup to do it. Found in S-Flow, which
  uses no confirmations and had therefore never displayed a process at all.
  A test now fails on any top-level DOM access in `shared.js`, since carrying
  a given element is an application's choice and Core must not make one an
  unwritten requirement.
- The optimistic agenda path recognises the `team` application id, following
  S-Agreement's rename to S-Team.

No public API or wire-format change; the release contract differs from 0.1.6
only in its version.

## 0.1.6

- Add a deliberately small shared UI kit for disclosures, entity badges and
  avatars, semantic buttons, and inline add composers. Applications retain
  their own workflows while reusing the same visual and interaction rules.
- Bound every wait an SFTP relay can impose. Paramiko's connect timeout
  covers only the TCP handshake, so a connection that died once established
  left each later read waiting on a socket nobody would answer — stalling
  the poll cycle, and with it every request needing relay state, for as long
  as the OS kept the connection open. `banner_timeout` and `auth_timeout`
  now bound the rest of connecting, a channel timeout bounds each read, and
  keepalives make a silent peer fail rather than be waited on. Tunable with
  `relay_sftp_connect_timeout`, `relay_sftp_operation_timeout` and
  `relay_sftp_keepalive_seconds`; defaulted, because the stall must not
  depend on anybody having configured it.
- `RelayLogic.peer_liveness()` no longer takes the relay I/O lock. It reads
  only the heartbeat cache the poller has already filled, but sharing the
  poller's lock meant every request reporting who is reachable queued behind
  an SFTP round trip — so a relay whose connection had died stopped the
  client rather than only its sync. The two cached fields now have a
  dedicated leaf lock, which is what makes the cache's existing promise
  ("a UI request must never wait for SFTP") actually hold.
- Hosts can override the primary application's shared header name with
  `header_title` in the JSON configuration.
- Update the reviewed dependency inventory for `cryptography` 50.0.0. The
  licence expression is unchanged (`Apache-2.0 OR BSD-3-Clause`); paramiko
  requires only `cryptography>=3.3`, so CI resolves the newest release.

## 0.1.5

- Enforce the lock order `relay manager -> relay I/O -> Session` at runtime,
  including a rejection of two locks from the same layer: nothing orders one
  relay connection's I/O lock against another's.
- Deliver application effects only after relay and Session transactions end.
- Separate Core component metadata ownership from Session persistence.
- **`Session.application_metadata()` now requires the caller to hold
  `Session.lock`.** It returns the live namespace so applications can
  read-modify-write nested structures; an unlocked write could race
  persistence deep-copying the same dictionary. Core's response helpers hold
  the lock already, so only applications calling from outside a request need
  to open their own transaction.
- Add atomic snapshot-observe-merge responses for transport-decorated views.
- Remove the obsolete `PersistenceParticipant` lock-sharing contract.
- The channel poll tick now asserts that peer-update reconciliation runs
  inside the Session transaction, replacing a lock that could never be
  contended, and calls the runtime's persistence and effect delivery
  directly instead of probing for them.

## Unreleased

- Add `SovereignUI.reactionControl()`: one control for answering a divergence,
  shared by every application. A single available act reads as a button naming
  it ("Adopt accountability creation from Ana", "Take back my card creation");
  several become a "React" menu. The menu is Core's own element rather than
  markup each page must carry, and its choices are read from the transition's
  contributing events, so absence is decided by the event type rather than by
  whether a cached peer tree happens to have arrived. Three applications had
  copied the same menu, and a fourth had grown its own vocabulary for the same
  acts.
- The collaboration pane's divergence rows now carry that control beside
  "Show", so the list of what is unsettled is also where it is settled. Two new
  mount options: `reactNode(uuid, choice)` performs one, and `canReact(uuid)`
  lets an application that shows several topics offer it only where it has the
  routes to honour it.
- Fixed optimistic Session view confirmations that refreshed application data
  without notifying subscribers to redraw when pending state changed in the
  same batch.
- Core now provides an optimistic `SessionView`: confirmed snapshots remain
  separate from pending human intentions, mutations carry retry-safe IDs, and
  timeouts reconcile instead of rolling the visible state back. Session-owned
  view revisions make application snapshots atomic with their revision.
- **Fixed: changing a field back to an earlier value no longer creates a
  false divergence.** Relay observation now supplies the causal direction
  when current and base content hashes form a cycle.
- Browser liveness reads now use the channel poll's in-memory presence cache
  instead of performing relay/SFTP I/O, and Core exposes a lightweight local
  change revision for revision-gated application refreshes.

- **Fixed: stopping use of a relay channel now withdraws that client's
  publication.** The removal is serialized with publishing and leaves other
  clients' publications intact. Manage Channels now lists every assigned
  topic and can stop all use without deleting the channel.
- **Fixed: relay heartbeats now describe which topics they actually carry.**
  A client using the same relay for another board or only for identity traffic
  no longer appears online for a board it has moved elsewhere. Agenda rows
  also take their visible drop position before persistence and sync finish.
- **Fixed: relay presence and shutdown could remain stale or race.** The shell
  refreshes peer liveness without requiring a browser reload, and mailbox
  shutdown now waits for in-flight relay I/O before closing its storage.
- **Fixed: dragging an agenda item could show the drop position but leave the
  order unchanged in the desktop window.** The shared shell now uses one
  mouse-drag path instead of competing with WebView2's native HTML drag.
- **Fixed: shutting down a CLI host failed when a retired or unconfigured
  mailbox connection had no storage backend to close.** Mailbox shutdown now
  skips absent storage and is safe to repeat.
- **Fixed: the topic selector menu was centered on short titles and could open
  beyond the window's left edge.** It now aligns with the topic field's left
  edge.
- Core is now version `0.1.4`; Session registries are private, controller
  result handling is centralized, and pairing/storage capability contracts
  are explicit.
- Core `0.1.3` distinguished the connect-token v2 and public
  API changes from the published `0.1.2` contract. Release-contract snapshots
  now guard public exports and format versions.
- The shipped Notes example now uses the host's real asset routes, mounts the
  shared shell safely, and activates accepted topics.
- Removed the unused `requests` runtime dependency and its exclusive
  transitive dependencies from the reviewed inventory.
- Channel extensibility remains public through explicit management, liveness,
  blob, persistence, and polling capability protocols. Polling endpoints now
  own their complete cycle and diagnostics behind `poll_once`; the host only
  schedules them.
- **Every topic now has one visible home channel, including the Core
  identity.** The first channel created becomes the identity home
  automatically; Manage Channels shows it, lets the user move it, and warns
  that moving or deleting it breaks earlier invitations. Deleting a channel
  continues to remove every topic assigned to it.
  - Connect tokens are now version 2 and carry an explicit topic-to-channel
    mapping. An invitation can therefore route the identity and application
    topic through different relay targets without ambiguity; missing or
    incomplete mappings are rejected.
  - The profile handler is assignment-scoped like every application topic,
    and invitation composition no longer moves the identity as a hidden side
    effect.
  - Relay presence remains the one-time bootstrap by which an inviter learns
    who accepted. Once known, later profile changes are accepted only from the
    identity topic's home channel, so the heartbeat cannot bypass the home.
- **Several clients for one user, over one publication identity.** A pairing
  token carries the client id, one channel descriptor, every topic the account
  owns and its profile; a client that imports it becomes a copy of its
  siblings, and nobody outside can tell how many machines are behind one
  participant. Synchronisation between them is per topic rather than per node,
  from two local facts: if everything this client had was published, whatever
  a sibling wrote was written on top of it and is taken automatically; if this
  client holds unpublished work, nothing syncs and the person is asked. See
  `DESIGN_MULTI_CLIENT_PAIRING.md`.
  - The channel tick now polls before it publishes. Publishing first is
    harmless when each peer owns its own slot; with a shared one it writes
    over a sibling before comparing, and the sibling then correctly concludes
    the result is safe to adopt. Both clients follow the rule and the work is
    gone.
  - `Session.adopt_sibling_topic` takes a sibling's version of a topic whole,
    including nodes the sibling deleted. `reconcile_peer_changes` leaves those
    alone on purpose, because a *peer's* deletion is a separate decision; for
    one person's own clients the decision was already made, for the topic.
  - A sibling is never a peer: its version is cached under a `sibling:`
    address, so it reaches neither the participant lists nor the deletion
    quorum in `prune_deleted_nodes`.
  - The peer path refuses a pairing token explicitly. Admitted there it would
    register the user's own laptop as another person, and the reconnect-replace
    loop would then unbind the desktop from the very topics the token covers -
    a failure that presents as a working connection.
  - Content already identical on both sides is never an alarm, whatever the
    local record of publishing says. Both clients hold the account profile
    identically from the moment they pair, and a client that had not recorded
    publishing it would otherwise raise an alarm over content nothing had
    changed - and stop syncing that topic.
  - Pairing uses whichever connection actually has a relay, not just the
    implicit one. A relay added through Manage channels is a *target* with
    its own connection; the implicit connection holds storage only when the
    process was started with `relay_root` in a config file, which the
    packaged executable never is. Looking only at that one answered "no relay
    channel to pair over" to every user who had configured a relay the
    ordinary way.
  - A pairing token carries **every** relay this client has, not a chosen
    one. A sibling is a copy of this client, so whatever this one can reach
    it must reach too. Picking one refused with "several relays are
    configured - say which one to pair over" as soon as a second relay
    existed, which is the ordinary state for anyone using more than one.
    Accepting is additive: relays the client already has are re-keyed to the
    sibling identity and the rest are registered as ordinary targets, so
    generating a token again later *adds* the new channels instead of
    replacing what is there. Relays publishing under different identities are
    refused outright rather than silently covered by one of them, which would
    leave the sibling a *peer* of itself wherever the guess was wrong.
  - A **My other clients** section in the Manage channels dialog, beside the
    channel list, with a "Generate pairing token" button; and one paste field
    in the Sharing pane that takes either kind of token and routes by the
    marker the server sets. Pairing sits with the channels because that is
    what the token carries - this client's channels, not whichever board
    happens to be open - and is deliberately not a channel row action,
    because an invite token connects you to another person while a pairing
    token makes a second machine into you, and side by side as row actions
    those read as variations of one thing.
  - New: `POST /api/core/siblings/pairing`, `/pairing/accept`,
    `GET /api/core/siblings/alarms`, `POST /api/core/siblings/alarms/resolve`.
    The alarm names the storage file so the person can copy it before choosing;
    there is deliberately no export and no automatic merge.
  - Two clients on one machine must be given distinct `storage_file` **and**
    `relay_state_file` paths. The default state path is keyed by relay
    identity and storage location, both of which siblings share by design, so
    the default collides and the two would share the bookkeeping that tells
    them apart.
- **Fixed: a wiped relay stayed empty.** `publish_due_topics` skipped a topic
  whenever its locally persisted `published` record said that state was
  already on the server. Nothing ever falsified that record, so a relay that
  was wiped, rotated, moved, or restored from an older backup left every peer
  silently sitting on a stale flag, republishing nothing until its own content
  happened to change. The relay looked healthy - presence heartbeats are
  unconditional - while carrying no content at all, and anyone arriving
  afterwards synced nothing. The relay is now asked whether it still lists our
  publication before the skip is honoured; a listing that fails answers "yes",
  since an unreachable relay is not evidence of a missing publication.
- **A peer the relay no longer lists drops out of the connection view.** Its
  cached perspective for that topic is forgotten, so it leaves the network
  info the Sharing pane is built from, and it returns by itself once it
  publishes again. Deliberately narrow: `peer_topic_sets` is kept, so the
  peer keeps its vote in `prune_deleted_nodes` and a peer that is merely
  quiet cannot have its deletions pruned and then re-proposed on return.
  Content is untouched - cards keep naming the person as owner or member,
  because removing those references is a deliberate act, not something a
  missing directory should decide.
- `Session.forget_peer_topic_perspective(peer_addr, topic_uuid)` — drops a
  peer's cached content for one topic while keeping the relationship.
- **"Stop using" a relay channel now makes the topic private again.** The
  direct channel already did: its detach calls `Session.leave_topic`. The
  mailbox channel only cleared the topic's target assignment, so everyone it
  had been carrying stayed a member of the topic forever - the application
  went on listing them as people on the board, and could not tell "was here"
  from "is here". A mailbox detach now releases exactly the peers it was
  carrying, found through `peer_channel_for_topic`, so a topic also shared
  over a direct connection keeps those peers. This is the deliberate opposite
  of the entry above: a peer going quiet for a poll keeps the relationship;
  the user saying "stop using this channel here" ends it. Content is
  untouched either way - a card keeps naming the person, and taking them off
  it stays the user's own act.
- **Fixed: a channel could not be deleted while any topic was assigned to
  it.** `delete_channel` refused with `channel is still used by: <uuid>`. The
  assignment is invisible in the interface and nothing cleared it when the
  peers went away, so the refusal accumulated until a channel could not be
  removed at all - and explained itself with a bare uuid. Composing an invite
  token used to be enough to cause it - see the next entry. Deletion is now
  unconditional; `delete_target` already released the assignments, and the
  topics it held go back to private the same way "stop using" sends them.
- **Inviting someone to a channel no longer decides to publish there.**
  `MailboxChannel.offer_descriptor` assigned the topic to the target as a
  side effect of composing, so pressing "Get token" once - and never sending
  it - bound the board to that channel for good, with nothing on screen
  saying so and nothing ever clearing it. The order is now the other way
  round: "Use for this topic" is the decision, taken first and revocable from
  the same row, and composing refuses for a channel the topic is not on.
  "Get token" is renamed **Get invitation** and is only drawn for a channel
  in use, or for a direct connection, which has nothing to assign. The
  identity topic is the one exception - it is not a board, is never "used
  for" anything, and has to travel over whatever route the invitation takes
  or the invitee cannot see who invited them, so it follows the decision
  rather than needing one of its own. Polling follows use for the same
  reason: an outstanding invitation to a channel you have stopped using is an
  invitation to a channel you are no longer polling.
- **The direct HTTP channel is gone.** It needed a routable address between
  peers - port forwarding or a VPN - which for this project's users is
  effectively never, and the relay already covers both real cases: SFTP
  across the internet, a shared folder across a LAN. It was also the one
  channel that could not have a home for a topic: no assignment, no polling,
  no publication slot, so every rule in `DESIGN_TOPIC_HOME_CHANNELS.md` would
  have needed an "…except direct" exception. Two already existed. Deleted:
  `http_channel.py`, `transport.py`, the `/p2p/*` endpoints,
  `/api/join_discussion`, `/api/observe_topic`, `/api/unwatch_topic`,
  `/api/invite_discuss`, `/api/leave`, and the `relay_only` policy that
  existed only to switch direct HTTP off.
  - **Session no longer describes how anything moves.** The message handlers
    (`handle_join`, `handle_announce`, `handle_leave`, `handle_sync_status`,
    `handle_sync_response`), the sync-effect builders, the observation
    (`watch_topic`) surface, and the reachability bookkeeping
    (`members`, `peer_status`, `peer_sync_state`, `peer_fetch_topic_sets`,
    `peer_topics`) are all gone. What is left is the tree, the peer
    perspectives cached against it, and the reconciliation between them. A
    peer relationship is now one flat fact - `peer_topic_sets`: which topics
    we track it for.
  - **`SessionEffect` stays, carrying one type.** `release_topic_channels`
    is an application lifecycle signal, not a message, so `deliver_effects`
    and every application's `result.effects` contract are unchanged and no
    application repository needed a production change. `ChannelManager` no
    longer routes effects at all; `EffectDeliveryChannel` is withdrawn from
    the public API.
  - **Reachability is now the channel's answer, not the session's.**
    Session's network info carried a retry/failure record that only meant
    anything for a live connection. Whether a peer is reachable is now read
    from the heartbeat beside its publications, and added by
    `ChannelManager.network_info`.
  - **A peer is a publication identity, not a URL.** Peer addresses are
    `relay:<identity>` throughout. `advertise_host` survives only because
    the session address is built from it; nobody is told to connect to it.
  - The Protocol Explorer loses its address-based connect, watch and leave
    controls - it has no channel of its own to publish over, so it can only
    ever be an invitee.
- **Multi-client tests now run over a relay, not an in-process transport.**
  `MemoryHttpClient` answered a peer's message by calling the other runtime's
  handler directly. It was instant, and it exercised a route no user takes:
  direct HTTP needs a routable address between peers, which for this
  project's users means port forwarding or a VPN. The fixture it replaces
  (`s-initiative/tests/relay_clients.py`, and smaller equivalents in Core and
  S-Team) gives each client its own relay target on one shared folder
  and makes the test say when a cycle happens. This is the prerequisite for
  retiring the direct channel - see `DESIGN_TOPIC_HOME_CHANNELS.md` section
  3. Three tests changed what they assert, because "no implicit HTTP mesh"
  is a property of that transport and not of the design: everyone given a
  topic on a relay sees everyone else publishing it, and has to, or the board
  shows anonymous authors. What survives, and is now what they check, is that
  a board shared onward carries only that board.
- **Fixed: answering a sibling alarm only answered it on one relay.**
  `sibling_alarms` reports per (topic, relay), but the person is asked once,
  about their work. `resolve_sibling_alarm` stopped at the first connection
  holding the alarm, so with the topic on two relays - which is the ordinary
  state after pairing, since a pairing token carries every relay this client
  has and puts the whole account on each - the answer was carried out on one
  and the alarm came back on the next poll. It is now carried out on every
  connection holding it.
- **Fixed: a host with no topic could not be given one.** The shell disabled
  the connection button whenever no topic was selected, which on a first run
  is always - and the invite-token form lives behind that button. There was
  therefore no way to accept an invitation, so a fresh install could create
  topics but never join one. The button now always opens the pane, and with
  no topic the token form opens with it.

No wire or persistence-format change. `publish_due_topics` costs one extra
directory listing per published topic per poll, on the path that would
otherwise have skipped.

## 0.1.2 - 2026-07-26

- **Fixed: a windowed executable crashed on launch.** A frozen build with no
  console leaves `sys.stdout` and `sys.stderr` as `None`, and uvicorn's
  default log configuration asks `sys.stdout.isatty()` whether to colourise.
  That raised inside `logging.config.dictConfig` and surfaced as
  `ValueError: Unable to configure formatter 'default'`, with nothing in the
  message naming stdout. Every `console=False` build was affected, and it
  failed before the window appeared, so nothing was visible to the user
  except a traceback. `run_desktop` now gives the process discard streams
  when it has none.
- `desktop_main` accepts `--check`: it builds the runtime and the server,
  then returns without opening a window. A frozen build can run it on a
  machine with no desktop session, which is what lets CI prove the
  executable starts rather than only that it links.

No API removal, wire or persistence change. `run_desktop` gains an optional
`check_only` argument.

## 0.1.1 - 2026-07-26

- Blob transfer emits trace events. A blob cached, a referenced blob the
  relay does not hold, and a malformed identifier are now all recorded.
  Previously this path was silent, so an avatar reference that synced
  while its bytes did not left nothing in the logs to find.
- A publication held back because a referenced blob is missing locally is
  traced rather than only printed.

No API, wire or persistence change.

## 0.1.0 - 2026-07-26

- Initial public-alpha architecture.
- S-Protocol tree, Session perspectives, transitions, adopt and rollback.
- Direct HTTP and Local/SFTP mailbox channels.
- Generic application host, profile, protocol explorer, and blob storage.
