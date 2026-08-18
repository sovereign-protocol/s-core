# Sovereign Core public API (`0.x`)

This document defines the supported Python import surface for application and
channel authors. Before `1.0`, breaking changes remain possible and increment
the owning version; compatibility is never inferred from package version alone.

## Core application API

The names exported by `sovereign.__all__` are public. Applications should import
these contracts from `sovereign`, not from host, controller, transport, relay,
or persistence modules. All other Python modules and names are implementation
details unless this document explicitly says otherwise.

The current exports are: `ApplicationFacade`, `ApplicationFacadeLookup`,
`ApplicationInstance`, `ApplicationManifest`, `ApplicationRegistration`,
`ApplicationResultView`, `ApplicationServices`, `ApplicationSpec`,
`BlobChannel`, `Channel`, `ChannelAcceptance`, `ChannelResult`,
`IncompatibleApplicationFacade`, `Invitation`, `LastWriteWinsPolicy`, `LivenessChannel`,
`ManagedChannel`, `PairingChannel`, `PerspectiveObservation`,
`PerspectiveSource`, `ProjectedNode`, `PollCycleResult`,
`PollingChannel`, `PollingEndpoint`, `ProtocolNode`, `ProtocolResult`,
`ProtocolState`, `RelayStorage`, `Session`, `SessionEffect`, `SessionResult`,
`UnsupportedProtocolVersion`, `application_json_response`,
`application_result_view`, `avatar_attachment`, `canonical_attachments`,
`desktop_main`, `json_value`,
`protocol_node_from_envelope`, `protocol_tree_envelope`, and `run_desktop`.

An application module exports:

- `APPLICATION_MANIFEST: ApplicationManifest`
- `create_application(services: ApplicationServices) -> ApplicationInstance`

Applications may register shared topic roots through `ApplicationRegistration`.
They return domain mutations as `SessionResult`. A `SessionEffect` is a
lifecycle signal Core carries out - today only the release of a topic's
channels when its sharing ends - and never a message to a peer: a channel
publishes and polls on its own schedule, not on a caller's.

`ApplicationServices` deliberately exposes no channel manager. Applications
receive a read-only collaboration view and an effect-delivery callable; channel
configuration and the channel inventory are Core-only.

The collaboration view names **topics, never channels**. Besides composing and
accepting a topic invitation it can put one topic where another already is —
`bridge_topic_like(topic, like_topic)` — consent to receive one that is already
there, `follow_bridged_topic(topic, like_topic)`, stop both with
`unbridge_topic(topic)`, and ask `topics_share_a_bridge(topic, like_topic)`.
Applications create topics that belong to other topics — an election belongs to
the team that called it, a board to the team that keeps it — and those have to
travel the same way as the thing they belong to or they reach nobody. Which
channel that is, what it costs and who else is on it stay Core's.

Publishing and receiving stay **two acts**, as they are everywhere else in
Core (`shared` and `desired`). Bridging a topic is the publisher saying where
it goes; following one is the receiver consenting to have it. Merging them
would let one client graft topics into another's tree because the two happen to
share a relay root, which is exactly what the consent gate exists to prevent.
Its `snapshot_response(builder)` binds an application view to one confirmed
Session revision. `composite_response(snapshot_builder, observer, merger)`
extends that contract for views decorated with live transport information:
Session state is snapshotted first, observation and detached merging happen
after its lock is released. `mutation_response(operation, mutation_id=...,
invalidates=...)`
commits a retry-safe human intention; applications pass an unevaluated callback
so mutation, persistence, and revision confirmation share one boundary.

## Attachments

Core owns blob storage, transfer and collection; applications own what an
attachment *means*. `canonical_attachments` validates and normalizes a list of
attachment references, and `avatar_attachment` selects the `avatar` role from
one. Any node whose `data["attachments"]` holds canonical references is found by
Core's publication, peer-fetch and garbage-collection walkers, so an application
adds a new kind of attachment - a card's file, a document's exhibit - without
any Core change. Bytes are uploaded to Core's `/api/blob` endpoint, which owns
the size limit and content addressing; only the reference reaches the
application.

## Desktop window

Serving a host into its own window is Core's work, not an application's: it
owns the runtime, the server and the shutdown. `run_desktop` starts the host
on loopback and shows the window until it is closed; `desktop_main` wraps it
as a command line. An application supplies only what is its own - which module
to start and what to title the window - and declares the `pywebview`
dependency itself, so a headless install stays headless.

Because the port is chosen at start-up, the session file is not derived from
it and is not placed under the working directory. It goes to a per-user
application directory, so state survives a different port or launch location.
An explicit `storage_file` still wins.

## Optional application facades

Cross-application dependencies are optional and late-bound. A producer may put
one `ApplicationFacade` on its `ApplicationInstance`. Its
`facade_api_version` is owned by that producer and is independent from its data
schema and distribution versions.

A consumer calls `services.facades.find(application_id, expected_version)` at
use time. The result is:

- the producer's public API object when active and version-compatible;
- `None` when the producer is inactive;
- `IncompatibleApplicationFacade` when the producer is active with another API
  version.

Consumers must remain usable when an optional producer is absent. They must not
import the producer's logic, controller, or persistence modules. In `0.x`, a
producer exposes at most one facade version at a time; compatibility adapters
belong on the consumer side.

S-Initiative's current facade is `s_initiative.InitiativeFacade`, API version `1`. It
exposes detached query snapshots plus explicit board, card, agenda, reaction,
and policy commands. S-Cockpit consumes it without declaring S-Initiative
as a package dependency.

## Making a topic

An application says how one of its own topics is made, once, on its
`ApplicationRegistration`: `topic_noun` (what one is called to a person),
`template_required`, `list_templates()` returning `{value, name, description}`,
and `create_topic(title, template, snapshot)` returning a `SessionResult`
naming the new topic. All three ways of starting are its own — from nothing,
from a template it listed, or from a snapshot document it exported. An
application that leaves these out cannot have one of its topics made from
anywhere else, which is the right answer for one that owns none.

Anybody offering to make another application's topic reads that:

- `Session.topic_kinds()` — `[{application_id, noun, template_required,
  templates}]` for the applications running here that said how. A kind that is
  not present is not offered, rather than offered and then refused.
- `Session.create_application_topic(application_id, title, template="",
  snapshot=None)` — makes one and returns its uuid. Core reads neither the
  template id nor the snapshot document; what a valid one contains is the
  owning application's answer.

This replaced a table in each of three applications — a noun, a facade api
version, a per-kind template lookup and a create path per kind — all of them
restating what the owning application already knew, and drifting: one could
start a team from a file and another could not.

## Topic links

A `topic_link` node records that one node references a topic. Applications own
where links live — a link is an ordinary child of whatever refers to the topic,
so a card's link hangs off the card and a team's off the team. Core owns what a
link is: `topic_uuid`, `application_id`, and a `title` that is a convenience
copy for use before the topic is held. Once it is held, its own name wins.

`Session.create_topic_link(parent_uuid, topic_uuid, application_id, title)`
writes one, refusing a topic that would link to itself and a duplicate **this
client has already written** under that parent. Two actors referencing one
topic from the same parent is not a duplicate: it is how a team's list of what
it runs is the union of its members' own references, and how removing yours
leaves everybody else's standing.

`topic_links(parent_uuid=None, authored_here=False)` and
`links_to(topic_uuid, authored_here=False)` walk this client's own tree;
nothing is stored about where links are, because the links are the record.
`authored_here` narrows to the ones this client signed — a replicated link is
somebody else's statement, and which of the two it is decides who may remove
it. `topic_link(link_uuid)` returns one as a detached snapshot.

Three acts, and they are not the same act:

- `remove_topic_link(link_uuid)` deletes one reference. The topic is untouched,
  and so is every other reference to it, including other people's. It refuses a
  link this client did not author: a link is adopted same-origin, so a deletion
  written over somebody else's reference is one their peers refuse, and it
  returns on the next sync.
- `drop_topic(topic_uuid)` stops this client holding the topic: it ends sharing
  and removes the local subtree without writing a tombstone, so nothing is
  published and a peer sees only that this client stopped publishing. It
  refuses while any link here still points at the topic. That count is a closed
  question about one tree and never a claim about the network.
- `Session.delete` is neither, and stays with the application that owns the
  topic — the only one that knows who may destroy it.

`follow_topic_link(link_uuid)` holds what a link points at. A link to a topic
this client does not have is not broken, it is an invitation: the call notes a
pending invitation and mounts the topic if a peer's perspective carries it, and
reports that nobody is publishing it when none does. The uuid alone grants
nothing, so a link names a topic and is never a key to it. A peer who still
publishes a dropped topic offers it back the same way.

## Channel extension API

`Channel` is the required extension contract. A channel opts into independent
capabilities by also satisfying:

- `ManagedChannel`: named instance configuration, topic bindings, and
  instance-scoped detach;
- `LivenessChannel`: routed peer reachability;
- `BlobChannel`: remote blob reads through an explicit peer/topic route;
- `PairingChannel`: sibling-client pairing and conflict resolution;
- `PollingChannel`: discovery of independently scheduled `PollingEndpoint`
  objects.

A `PollingEndpoint` provides `poll_interval_seconds`,
`has_active_relationship()`, `polling_diagnostics()`, and one complete
`poll_once(after_apply)` operation. The endpoint owns transport ordering,
timing calibration, response publication, failure handling, and diagnostic
tracing. It calls `after_apply` after applying remote state and before
publishing its response. `poll_once` returns `PollCycleResult`; Core schedules
the endpoint and advances the fixed cadence but does not inspect transport
implementation fields. Standard diagnostic keys are `identity`, `backend`,
`state_file`, and `poll_interval_seconds`; extensions may add keys.

Core owns registration, descriptor negotiation, invitation composition, and
poll scheduling. Concrete mailbox, relay-manager, storage backend, Starlette
controller, and server modules are Core implementation details in `0.x`.
`RelayStorage` is the backend contract used by polling endpoints; it includes
explicit connection closure.

## Protocol and session API

`ProtocolNode`, `ProtocolState`, their envelope helpers, `Session`,
`SessionResult`, and `SessionEffect` are public. The hash and wire semantics are
normative in `SPECIFICATION_S_PROTOCOL.md`; direct mutation of internal indexes,
peer caches, locks, or application registries is unsupported.
Session peer/topic properties are detached snapshots. Applications store local
state only through `application_metadata(application_id)`, which returns the
live namespace and requires the caller to hold `Session.lock`. Core's response
helpers (`mutation_response`, `snapshot_response`, `composite_response`) hold it
already; an application calling from anywhere else opens its own transaction
with `with session.lock:`. See `DESIGN_LOCKING_AND_COMPOSITE_READS.md`.

`Session.project_nodes()` derives a read-only view across local and explicitly
connected peer perspectives without adopting their records. `ProjectedNode`
preserves the detached `ProtocolNode` and adds a verified `PerspectiveSource`;
`PerspectiveObservation` contains runtime-only timing facts. Callers may supply
a relative maximum age, an absolute lower timestamp, both, or neither. Core
measures and filters these facts but does not define domain-level freshness.

A projection still has to answer "is this current?" one way or the other, so
the relative maximum age carries a default of two hours rather than leaving
every caller to declare the same number. An explicit `max_age_seconds=None`
removes the window and projects every verified record regardless of age; an
explicit value replaces it. The absolute lower timestamp has no default,
because no timestamp is a defensible one.

`LastWriteWinsPolicy` lets an application declare a narrowly scoped timestamp
rule for one node type. The declaration names the timestamp field and the data
and parent fields that constitute the reconciled value. Passing declarations
to `Session.reconcile_peer_changes(..., reconciliation_policies=...)` makes
Core reject stale candidates, resolve a newer eligible candidate, and normalize
timestamp-only differences. Other field differences remain ordinary
transitions; applications still decide which semantic changes may be adopted.
