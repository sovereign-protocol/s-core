"""Public protocol Session facade.

Session owns local mutations, peer snapshots, topic membership, reconciliation,
ordering, agenda policy, application metadata namespaces, and its persisted
registries. It never sends data: channels publish and poll independently.
Public peer/topic views are detached snapshots; mutable registries stay private.
"""

from __future__ import annotations

import copy
import time
import threading
import uuid as uuid_mod
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

from .adoption import (
    ADOPT_AUTO, ADOPT_HOLD, ADOPT_NEVER, AUTHOR_ANY, AUTHOR_SAME_ORIGIN,
    RESOLVE_ADOPT, RESOLVE_DEFER, RESOLVE_REFUSE, RESOLVE_VALUES,
    ROOT_DEFAULT, AdoptionEntry,
)
from .blob_store import avatar_attachment
from .locking import OrderedRLock, SESSION_LOCK_ORDER
from .protocol import (
    ProtocolNode, ProtocolState, collect_subtree_uuids,
    protocol_tree_envelope, stable_hash,
)
from .perspective import (
    PerspectiveObservation, PerspectiveSource, ProjectedNode,
    _RevisionCandidate, _resolve_revision_candidates,
)
from .reconciliation import LastWriteWinsPolicy
from .signing import (
    activation_event, generate_keypair, key_id_for_public_key,
    public_key_for_private_key,
    resolve_key_events, revocation_event, sign_revision, verify_revision,
)
from .topic_registry import ApplicationRegistration, SharedTopicRegistry
from .trace_log import TraceLogger
from .versions import CORE_PROFILE_SCHEMA_VERSION


_LOCAL_REVISION_ORIGIN = object()

# How stale a peer's perspective may be before its agenda records stop
# counting as current. Core measures perspective age and assigns no domain
# meaning to it, but a projection has to answer the question one way or the
# other, so the safer answer is the default: an unobserved or long-silent
# perspective is not projected. Callers wanting every verified record
# regardless of age pass max_age_seconds=None explicitly.
DEFAULT_AGENDA_PERSPECTIVE_MAX_AGE_SECONDS = 2 * 60 * 60

_CORE_PROFILE_FIELDS = frozenset({
    "type", "name", "profile_schema_version", "identity_key",
    "display_name", "picture", "attachments", "signing_key_events",
})


def _core_profile_schema_error(data: dict) -> str | None:
    if data.get("type") != "shared_user_profile":
        return "Core profile type must be 'shared_user_profile'"
    version = data.get("profile_schema_version")
    if version != CORE_PROFILE_SCHEMA_VERSION:
        return (
            f"unsupported Core profile schema version {version!r}; "
            f"expected {CORE_PROFILE_SCHEMA_VERSION}"
        )
    extra = sorted(set(data) - _CORE_PROFILE_FIELDS)
    if extra:
        return f"unsupported Core profile fields: {', '.join(extra)}"
    if data.get("name") != "public_profile":
        return "Core profile name must be 'public_profile'"
    if not isinstance(data.get("identity_key"), str) or not data["identity_key"]:
        return "Core profile identity_key is required"
    if not isinstance(data.get("display_name"), str):
        return "Core profile display_name must be a string"
    if not isinstance(data.get("picture"), str):
        return "Core profile picture must be a string"
    if not isinstance(data.get("attachments"), list):
        return "Core profile attachments must be a list"
    _known, active, signing_error = resolve_key_events(
        data.get("signing_key_events"),
    )
    if signing_error:
        return signing_error
    if not active:
        return "Core profile must retain an active signing key"
    return None


def _session_locked(method):
    """Serialize access to Session's mutable protocol and peer state."""
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return locked


@dataclass(frozen=True)
class SessionEffect:
    type: str
    target: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    channel_kind: str | None = None


@dataclass
class SessionResult:
    status: str
    value: Any = None
    reason: str | None = None
    effects: list[SessionEffect] = field(default_factory=list)


class ReadOnlyProtocolIndex:
    def __init__(self, protocol: ProtocolState, lock: threading.RLock):
        self._protocol = protocol
        self._lock = lock

    def __contains__(self, node_uuid: str) -> bool:
        with self._lock:
            return node_uuid in self._protocol.index

    def __iter__(self):
        with self._lock:
            return iter(tuple(self._protocol.index))

    def __len__(self) -> int:
        with self._lock:
            return len(self._protocol.index)

    def get(self, node_uuid: str, default=None) -> ProtocolNode | None:
        with self._lock:
            node = self._protocol.index.get(node_uuid)
            return Session._snapshot_node(node) if node else default

    def __getitem__(self, node_uuid: str) -> ProtocolNode:
        with self._lock:
            node = self._protocol.index[node_uuid]
            return Session._snapshot_node(node)

    def keys(self):
        with self._lock:
            return tuple(self._protocol.index)

    def values(self):
        with self._lock:
            return tuple(
                Session._snapshot_node(node)
                for node in self._protocol.index.values()
            )

    def items(self):
        with self._lock:
            return tuple(
                (node_uuid, Session._snapshot_node(node))
                for node_uuid, node in self._protocol.index.items()
            )


class ReadOnlyProtocolView:
    def __init__(self, protocol: ProtocolState, lock: threading.RLock):
        self._protocol = protocol
        self._lock = lock
        self.index = ReadOnlyProtocolIndex(protocol, lock)

    @property
    def root(self) -> ProtocolNode:
        with self._lock:
            return Session._snapshot_node(self._protocol.root)

    @property
    def author(self) -> str:
        with self._lock:
            return self._protocol.author


class Session:
    ORDER_GAP_EPSILON = 1e-9
    AGENDA_ORDER_STRIDE = 1024.0
    MUTATION_HISTORY_LIMIT = 512
    # Another client of this same user caches its version of a topic under an
    # address with this prefix. It is not a peer address and must never be
    # treated as one: a sibling has no place in the participant lists, and no
    # vote in prune_deleted_nodes - it is this user, not another party.
    SIBLING_ADDRESS_PREFIX = "sibling:"

    @classmethod
    def is_sibling_address(cls, peer_addr: str | None) -> bool:
        return str(peer_addr or "").startswith(cls.SIBLING_ADDRESS_PREFIX)

    def __init__(self, address: str, trace: TraceLogger | None = None):
        self.lock = OrderedRLock(SESSION_LOCK_ORDER, "Session.lock")
        self.address = address
        self.trace = trace or TraceLogger.disabled()
        self._protocol = ProtocolState(author=address)
        self.protocol = ReadOnlyProtocolView(self._protocol, self.lock)
        self._signing_keypair = generate_keypair()
        self._creating_identity = False
        # Identity -> last verified append-only public-key chain. Peer profile
        # snapshots remain observable even when they branch, but a branch can
        # never roll back a key activation or revocation already trusted here.
        self._trusted_signing_key_events: dict[str, list[dict]] = {}
        # Persisted origin-local logical clock. Every local protocol mutation
        # receives a larger value; adopted/forwarded revisions preserve the
        # originator's value instead of consuming this counter.
        self.local_revision_seq = 0
        # Runtime revision of the complete confirmed Session view. Unlike a
        # protocol node revision, this also covers peer perspectives and
        # application metadata. It is intentionally not persisted: after a
        # restart browsers fetch a fresh snapshot before comparing revisions.
        self._view_revision = 0
        # Bounded runtime ledger for idempotent browser mutations. A retry with
        # the same client-generated ID observes the original result instead of
        # applying a human intention twice.
        self._mutation_results: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._peer_topic_sets: dict[str, set[str]] = {}
        self._peer_perspectives: dict[str, ProtocolNode] = {}
        # Runtime-only observation facts. Channels report age; applications
        # decide what age is acceptable for each use of a perspective.
        self._perspective_observations: dict[
            tuple[str, str], PerspectiveObservation
        ] = {}
        # Which channel type last successfully delivered to/from a peer
        # address - purely informational (the only transport-shaped thing
        # an app is allowed to surface to its UI, per the connect-channel
        # design), never read by any sync/reconciliation logic itself.
        # Explicit delivery route per peer and topic. A peer relationship
        # without an entry is intentionally unrouted; no transport may infer
        # HTTP merely because the address happens to look like a URL.
        self.peer_topic_channel: dict[str, dict[str, str]] = {}
        # Canonical addr -> identity_key registry. Knowledge, not
        # registration: an entry records "this address belongs to this
        # identity", a fact that stays true even after the peer's
        # registration (peer_topic_sets/...) is torn down - so remove_peer
        # deliberately leaves it alone. Written the instant any channel
        # learns the fact (set_peer_identity_key), never re-derived from
        # cached content on demand.
        self._peer_identity_key: dict[str, str] = {}
        # Exact local node revisions each peer has confirmed fetching,
        # rebuilt from durable relay heads after restart.
        self.peer_observed_node_revisions: dict[str, dict[str, str]] = {}
        self._active_topic_uuids: set[str] = set()
        # Runtime-only consent markers for invited application topics that
        # arrived while their application was inactive. Passive relay cache
        # entries are deliberately absent and must never be grafted merely
        # because an application is activated later.
        self.pending_topic_invitations: set[str] = set()
        self._app_metadata: dict[str, Any] = {}
        # How incoming changes are handled, per node and per topic. Written by
        # applications, read and executed by Core, never interpreted by it.
        # Local: not part of any node, not hashed, not published, never adopted
        # from a peer. See DESIGN_ADOPTION_METADATA.md.
        self._adoption_by_node: dict[str, AdoptionEntry] = {}
        self._adoption_by_topic: dict[str, AdoptionEntry] = {}
        # Runtime-only: how a topic classifies a node it does not yet hold.
        # Asked once per node, at first sight, and the answer is persisted.
        self._adoption_classifiers: dict[
            str, Callable[[ProtocolNode, AdoptionEntry], AdoptionEntry | None]
        ] = {}
        # Runtime-only: how a topic resolves a node it is holding. Asked every
        # time, never stored, because the rules it answers from move.
        self._adoption_resolvers: dict[
            str, Callable[[ProtocolNode, ProtocolNode | None, str], str | None]
        ] = {}
        self._reconciliation_by_topic: dict[
            str, tuple[LastWriteWinsPolicy, ...]
        ] = {}
        # Topics with a reconciliation pass in progress. Re-applying a changed
        # declaration must not recurse into the pass that is applying it.
        self._reconciling_topics: set[str] = set()
        # Runtime-only application hooks used by channels to enumerate and
        # mount shared topic roots without importing application modules.
        self.shared_topics = SharedTopicRegistry()
        self.shared_topics.register(
            "Sovereign Core profile",
            {"shared_user_profile"},
            lambda: [self.identity],
            self.accept_profile_invitation,
            mount_invitation=False,
        )

    @_session_locked
    def current_view_revision(self) -> int:
        """Revision identifying the current confirmed browser-visible state."""
        return self._view_revision

    @_session_locked
    def advance_view_revision(self) -> int:
        """Commit a new confirmed browser-visible Session revision."""
        self._view_revision += 1
        return self._view_revision

    @_session_locked
    def read_snapshot(self, builder: Callable[[], Any]) -> tuple[int, Any]:
        """Build one application view atomically with its Session revision."""
        return self._view_revision, builder()

    @_session_locked
    def mutation_result(self, mutation_id: str) -> dict[str, Any] | None:
        """Return a detached prior result and refresh its bounded LRU entry."""
        if not mutation_id:
            return None
        stored = self._mutation_results.get(mutation_id)
        if stored is None:
            return None
        self._mutation_results.move_to_end(mutation_id)
        return copy.deepcopy(stored)

    @_session_locked
    def remember_mutation_result(
        self, mutation_id: str, payload: dict[str, Any],
    ) -> None:
        """Remember a definitive mutation outcome for safe request retries."""
        if not mutation_id:
            return
        self._mutation_results[mutation_id] = copy.deepcopy(payload)
        self._mutation_results.move_to_end(mutation_id)
        while len(self._mutation_results) > self.MUTATION_HISTORY_LIMIT:
            self._mutation_results.popitem(last=False)

    @property
    @_session_locked
    def active_topic_uuid(self) -> str | None:
        return sorted(self._active_topic_uuids)[0] if self._active_topic_uuids else None

    @property
    @_session_locked
    def active_topic_uuids(self) -> frozenset[str]:
        return frozenset(self._active_topic_uuids)

    @property
    @_session_locked
    def peer_topic_sets(self) -> dict[str, frozenset[str]]:
        return {
            address: frozenset(topics)
            for address, topics in self._peer_topic_sets.items()
        }

    @property
    @_session_locked
    def peer_perspectives(self) -> dict[str, ProtocolNode]:
        return self.peer_perspectives_for_topic()

    @property
    @_session_locked
    def peer_identity_key(self) -> dict[str, str]:
        return dict(self._peer_identity_key)

    @property
    @_session_locked
    def app_metadata(self) -> dict[str, Any]:
        return copy.deepcopy(self._app_metadata)

    @_session_locked
    def active_topic_ids(self) -> tuple[str, ...]:
        """Return a stable snapshot of locally active topic identifiers."""
        return tuple(sorted(self._active_topic_uuids))

    @_session_locked
    def active_topics(self) -> tuple[ProtocolNode, ...]:
        """Return detached snapshots of all locally active topic roots."""
        topics = []
        for topic_uuid in sorted(self._active_topic_uuids):
            node = self._protocol.index.get(topic_uuid)
            if node is not None:
                topics.append(ProtocolNode.from_dict(node.to_dict()))
        return tuple(topics)

    @_session_locked
    def is_node_in_active_topic(self, node_uuid: str) -> bool:
        """Whether *node_uuid* is contained by any locally active topic."""
        return any(
            self._is_descendant_or_self(topic_uuid, node_uuid)
            for topic_uuid in self._active_topic_uuids
        )

    @_session_locked
    def peer_addresses(self, topic_uuid: str | None = None) -> tuple[str, ...]:
        """Return known peer addresses, optionally filtered by topic."""
        if topic_uuid is None:
            addresses = set(self._peer_topic_sets) | set(self._peer_perspectives)
        else:
            addresses = {
                address
                for address, topics in self._peer_topic_sets.items()
                if topic_uuid in topics
            }
        return tuple(sorted(addresses))

    @_session_locked
    def peer_topic_uuids(self, peer_addr: str) -> tuple[str, ...]:
        """Return a snapshot of topics registered for one peer."""
        return tuple(sorted(self._peer_topic_sets.get(peer_addr, ())))

    @_session_locked
    def peer_perspectives_for_topic(
        self, topic_uuid: str | None = None,
    ) -> dict[str, ProtocolNode]:
        """Return detached peer-tree snapshots, optionally filtered by topic."""
        addresses = (
            self.peer_addresses(topic_uuid)
            if topic_uuid is not None
            else tuple(sorted(self._peer_perspectives))
        )
        return {
            address: ProtocolNode.from_dict(tree.to_dict())
            for address in addresses
            if (tree := self._peer_perspectives.get(address)) is not None
        }

    @_session_locked
    def observe_peer_perspective(
        self,
        peer_addr: str,
        topic_uuid: str,
        *,
        source_age_seconds: float | None = None,
        source_timestamp: float | None = None,
        channel_kind: str | None = None,
    ) -> None:
        """Record runtime facts without assigning domain meaning to age."""
        if not peer_addr or not topic_uuid:
            return
        normalized_age = (
            max(0.0, float(source_age_seconds))
            if source_age_seconds is not None else None
        )
        normalized_timestamp = (
            float(source_timestamp) if source_timestamp is not None else None
        )
        self._perspective_observations[(peer_addr, topic_uuid)] = (
            PerspectiveObservation(
                address=peer_addr,
                topic_uuid=topic_uuid,
                observed_monotonic=time.monotonic(),
                observed_at=datetime.now(timezone.utc).isoformat(
                    timespec="milliseconds",
                ),
                source_age_seconds=normalized_age,
                source_timestamp=normalized_timestamp,
                channel_kind=channel_kind,
            )
        )

    @_session_locked
    def perspective_observation(
        self, peer_addr: str, topic_uuid: str,
    ) -> PerspectiveObservation | None:
        return self._perspective_observations.get((peer_addr, topic_uuid))

    @_session_locked
    def peer_identity_key_for_address(self, peer_addr: str) -> str | None:
        return self._peer_identity_key.get(peer_addr)

    def application_metadata(self, application_id: str) -> dict[str, Any]:
        """Return one application's live metadata namespace.

        Deliberately not detached: applications read and modify nested
        structures here, which a snapshot-and-replace API cannot express
        without copying whole subtrees. The caller must therefore already
        hold Session.lock, so a write can never race persistence_metadata()
        deep-copying the same dictionary. Acquiring the lock here instead
        would only make each single access atomic, not the read-modify-write
        the callers actually perform.
        """
        self.lock.assert_owned()
        apps = self._app_metadata.setdefault("apps", {})
        if not isinstance(apps, dict):
            apps = {}
            self._app_metadata["apps"] = apps
        namespace = apps.setdefault(application_id, {})
        if not isinstance(namespace, dict):
            namespace = {}
            apps[application_id] = namespace
        return namespace

    @_session_locked
    def component_metadata(self, component_id: str) -> dict[str, Any]:
        """Return a detached private Core-component metadata snapshot."""
        return copy.deepcopy(self._component_metadata_namespace(component_id))

    @_session_locked
    def update_component_metadata(
        self, component_id: str, values: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically replace selected keys in a component namespace."""
        if not isinstance(values, dict):
            raise TypeError("component metadata update must be a dictionary")
        namespace = self._component_metadata_namespace(component_id)
        for key, value in values.items():
            namespace[str(key)] = copy.deepcopy(value)
        return copy.deepcopy(namespace)

    def _component_metadata_namespace(
        self, component_id: str,
    ) -> dict[str, Any]:
        components = self._app_metadata.setdefault("core_components", {})
        if not isinstance(components, dict):
            components = {}
            self._app_metadata["core_components"] = components
        namespace = components.setdefault(component_id, {})
        if not isinstance(namespace, dict):
            namespace = {}
            components[component_id] = namespace
        if component_id == "relay":
            for key in list(self._app_metadata):
                if key.startswith("relay_"):
                    namespace.setdefault(key, self._app_metadata.pop(key))
        return namespace

    @_session_locked
    def persistence_metadata(self) -> dict[str, Any]:
        """Return the Session-owned persistence fields as a detached value."""
        return {
            "local_revision_seq": self.local_revision_seq,
            "active_topic_uuids": sorted(self._active_topic_uuids),
            "peer_topic_sets": {
                addr: sorted(topics)
                for addr, topics in sorted(self._peer_topic_sets.items())
            },
            "peer_identity_key": dict(sorted(self._peer_identity_key.items())),
            "peer_topic_channel": {
                addr: dict(sorted(bindings.items()))
                for addr, bindings in sorted(self.peer_topic_channel.items())
            },
            "app_metadata": copy.deepcopy(self._app_metadata),
            "adoption_metadata": self.adoption_metadata_snapshot(),
            "signing_key": copy.deepcopy(self._signing_keypair),
        }

    @_session_locked
    def restore_persistence_metadata(self, metadata: dict[str, Any]) -> None:
        """Restore Session-owned registries while validating stored values."""
        stored_revision_seq = metadata.get("local_revision_seq", 0)
        self.local_revision_seq = (
            stored_revision_seq
            if isinstance(stored_revision_seq, int)
            and not isinstance(stored_revision_seq, bool)
            and stored_revision_seq >= 0
            else 0
        )
        stored_signing_key = metadata.get("signing_key")
        if not isinstance(stored_signing_key, dict):
            raise ValueError("session signing key is required")
        try:
            public_key = public_key_for_private_key(
                stored_signing_key["private_key"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("session signing key is invalid") from exc
        if (
            stored_signing_key.get("public_key") != public_key
            or stored_signing_key.get("key_id")
            != key_id_for_public_key(public_key)
        ):
            raise ValueError("session signing key does not match its public key")
        self._signing_keypair = copy.deepcopy(stored_signing_key)
        self._active_topic_uuids = {
            uuid for uuid in metadata.get("active_topic_uuids", [])
            if self._protocol.index.get(uuid) is not None
        }
        self._peer_topic_sets.clear()
        self.peer_topic_channel.clear()
        self._app_metadata = copy.deepcopy(
            dict(metadata.get("app_metadata") or {}),
        )
        self._restore_adoption_metadata(metadata.get("adoption_metadata"))
        self._peer_identity_key = {
            addr: key
            for addr, key in (metadata.get("peer_identity_key") or {}).items()
            if isinstance(addr, str) and isinstance(key, str) and addr and key
        }
        self.peer_topic_channel = {
            addr: {
                topic_uuid: channel_kind
                for topic_uuid, channel_kind in bindings.items()
                if (
                    isinstance(topic_uuid, str)
                    and topic_uuid
                    and isinstance(channel_kind, str)
                    and channel_kind
                )
            }
            for addr, bindings in (
                metadata.get("peer_topic_channel") or {}
            ).items()
            if isinstance(addr, str) and addr and isinstance(bindings, dict)
        }
        for peer, stored_topics in sorted(
            (metadata.get("peer_topic_sets") or {}).items(),
        ):
            topics = {
                topic for topic in stored_topics
                if (
                    self._protocol.index.get(topic) is not None
                    or self.peer_channel_for_topic(peer, topic)
                )
            }
            if topics:
                self._peer_topic_sets[peer] = topics
        self.peer_topic_channel = {
            addr: bindings
            for addr, bindings in self.peer_topic_channel.items()
            if addr in self._peer_topic_sets and bindings
        }
        profile = self._find_identity_in_tree(self._protocol.root)
        if profile is not None:
            known, active, error = resolve_key_events(
                profile.data.get("signing_key_events"),
            )
            key_id = self._signing_keypair["key_id"]
            if (
                error
                or key_id not in active
                or known.get(key_id) != self._signing_keypair["public_key"]
            ):
                raise ValueError("session signing key is not active for its identity")
            if not self._observe_identity_signing_keys(profile):
                raise ValueError("identity signing-key chain is invalid")

    # Identity - a session-owned meta-topic. Any app gets "who am I"/"who is
    # this peer" for free through these, instead of reimplementing its own
    # profile node and lookup logic.

    def _folder(self, parent: ProtocolNode, name: str,
               node_type: str = "folder") -> ProtocolNode:
        for child in parent.children:
            if child.data.get("name") == name and child.data.get("type") in ("folder", node_type):
                return child
        return self.create_child(parent.uuid, {"type": node_type, "name": name}, {}).value

    @property
    @_session_locked
    def identity(self) -> ProtocolNode:
        # The shared_user_data folder only ever holds this session's own
        # identity node - no address match needed to find "mine" among
        # others, unlike the old address-keyed lookup this replaced.
        self._creating_identity = True
        try:
            container = self._folder(self.protocol.root, "shared_user_data")
            for child in container.children:
                if child.data.get("type") == "shared_user_profile":
                    return self._validated_identity(child)
            return self.create_child(
                container.uuid,
                {
                    "type": "shared_user_profile",
                    "name": "public_profile",
                    "profile_schema_version": CORE_PROFILE_SCHEMA_VERSION,
                    "identity_key": str(uuid_mod.uuid4()),
                    "display_name": "",
                    "picture": "",
                    "attachments": [],
                    "signing_key_events": [activation_event(self._signing_keypair)],
                },
                {},
            ).value
        finally:
            self._creating_identity = False

    def _validated_identity(self, node: ProtocolNode) -> ProtocolNode:
        data = dict(node.data)
        error = _core_profile_schema_error(data)
        if error:
            raise ValueError(error)
        return node

    @staticmethod
    def validate_core_tree(root: ProtocolNode) -> str | None:
        stack = [root]
        while stack:
            node = stack.pop()
            if node.data.get("type") == "shared_user_profile":
                error = _core_profile_schema_error(node.data)
                if error:
                    return f"node {node.uuid}: {error}"
            stack.extend(node.children)
        return None

    @_session_locked
    def set_identity(self, display_name: str,
                     picture: str | None = None) -> SessionResult:
        profile = self.identity
        data = dict(profile.data)
        data.update({
            "type": "shared_user_profile",
            "name": "public_profile",
            "display_name": display_name or "",
        })
        if picture is not None:
            data["picture"] = picture or ""
        return self.modify(profile.uuid, data, profile.weights)

    @_session_locked
    def adopt_pairing_identity(self, profile: dict) -> SessionResult:
        """Become the identity in a pairing token, replacing our own.

        Unlike accept_profile_invitation, which validates a *peer's* profile
        and leaves ours alone, this replaces the local profile node outright
        - uuid included. That is the point: siblings must present one face,
        so third parties see one participant rather than one per machine.

        `local_revision_seq` is deliberately untouched. It is this client's
        own counter and stays client-local; copying it would give two clients
        one origin *and* one counter, which is the collision the sequence
        comparator cannot detect.
        """
        error = _core_profile_schema_error(dict(profile.get("data") or {}))
        if error:
            return SessionResult("error", reason=error)
        incoming = ProtocolNode.from_dict(profile)
        if incoming.children:
            return SessionResult("error", reason="Core profile cannot have children")
        container = self._folder(self.protocol.root, "shared_user_data")
        current = next(
            (
                child for child in container.children
                if child.data.get("type") == "shared_user_profile"
            ),
            None,
        )
        if current is not None:
            if current.uuid == incoming.uuid:
                refreshed = self._protocol.adopt_own_fields(
                    current.uuid, incoming, adopt_move=False,
                )
                if not refreshed.ok:
                    return SessionResult("error", reason=refreshed.reason)
                self._observe_identity_signing_keys(incoming)
                return SessionResult("ok", value=current.uuid)
            self._protocol.remove_subtree_uuids(
                self._protocol.root.uuid, {current.uuid},
            )
        adopted = self.adopt_subtree(incoming, container.uuid)
        if adopted.status != "ok":
            return adopted
        self._observe_identity_signing_keys(incoming)
        self.trace_event(
            "session.pairing_identity_adopted",
            identity_uuid=incoming.uuid,
        )
        return SessionResult("ok", value=incoming.uuid)

    def accept_profile_invitation(self, tree: ProtocolNode) -> SessionResult:
        """Validate a peer profile without grafting it into our sovereign tree.

        The channel stores the peer's version in ``peer_perspectives`` after
        this handler succeeds. Our local profile remains the only profile under
        ``shared_user_data``.
        """
        error = _core_profile_schema_error(tree.data)
        if error:
            return SessionResult("error", reason=error)
        if tree.children:
            return SessionResult("error", reason="Core profile cannot have children")
        return SessionResult("ok", value=tree.uuid)

    # Application registration. Callbacks are runtime-only and are never
    # persisted. Session owns invocation so channels do not touch registry
    # locks or mutable protocol state directly.

    @_session_locked
    def register_application(self, registration: ApplicationRegistration) -> None:
        self.shared_topics.register_application(registration)

    @_session_locked
    def unregister_application(self, application_id: str) -> None:
        if application_id == "Sovereign Core profile":
            raise ValueError("the Core profile registration cannot be removed")
        self.shared_topics.unregister(application_id)

    @_session_locked
    def mount_cached_topics(self, application_id: str) -> list[str]:
        registration = next((
            item for item in self.shared_topics.registrations()
            if item.application_id == application_id
        ), None)
        if not registration or not registration.mount_invitation:
            return []
        mounted = []
        seen = set()
        stack = list(self._peer_perspectives.values())
        while stack:
            node = stack.pop()
            if node.uuid in seen:
                continue
            seen.add(node.uuid)
            if (
                node.uuid in self.pending_topic_invitations
                and
                node.data.get("type") in registration.root_types
                and node.uuid not in self._protocol.index
            ):
                result = registration.accept_invitation(copy.deepcopy(node))
                if getattr(result, "status", None) == "ok":
                    mounted.append(node.uuid)
                    self.pending_topic_invitations.discard(node.uuid)
                    continue
            stack.extend(node.children)
        return sorted(mounted)

    @_session_locked
    def shared_topic_uuids(
        self,
        assigned_topic_uuids: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> list[str]:
        return self.shared_topics.local_topic_uuids(assigned_topic_uuids)

    @_session_locked
    def shared_topic_handler_for(self, tree: ProtocolNode | None):
        return self.shared_topics.handler_for(tree)

    @_session_locked
    def supports_shared_topic(self, tree: ProtocolNode | None) -> bool:
        return self.shared_topics.supports(tree)

    @_session_locked
    def accept_shared_topic_invitation(self, tree: ProtocolNode):
        result = self.shared_topics.accept_invited_topic(tree)
        if getattr(result, "status", None) == "ok":
            self.pending_topic_invitations.discard(tree.uuid)
        return result

    @_session_locked
    def note_pending_topic_invitation(self, topic_uuid: str) -> None:
        if topic_uuid:
            self.pending_topic_invitations.add(str(topic_uuid))

    @_session_locked
    def shared_topic_invitation_requires_mount(
        self, tree: ProtocolNode | None,
    ) -> bool:
        return self.shared_topics.invitation_requires_mount(tree)

    def find_peer_identity(self, identity_key: str) -> ProtocolNode | None:
        """Return the newest authenticated profile across all addresses.

        One identity may be visible through several relays or devices. Cache
        insertion/address order is not revision order, so selecting the first
        copy can indefinitely retain an old name or avatar.
        """
        candidates = [
            _RevisionCandidate(
                found,
                address,
                self._identity_profile_is_self_verified(found),
            )
            for address, tree in self._peer_perspectives.items()
            if (found := self._find_identity_in_tree(tree, identity_key))
        ]
        # Unsigned profiles can exist in an in-memory cache created by an
        # older embedding or test double. They remain readable only when no
        # authenticated candidate exists; they can never outrank one.
        resolved = _resolve_revision_candidates(
            candidates, allow_unverified_fallback=True,
        )
        return resolved.node if resolved else None

    def _identity_profile_is_self_verified(self, profile: ProtocolNode) -> bool:
        identity_key = profile.data.get("identity_key")
        if (
            not isinstance(identity_key, str)
            or not identity_key
            or profile.revision_origin != identity_key
            or _core_profile_schema_error(dict(profile.data))
        ):
            return False
        known, active, error = resolve_key_events(
            profile.data.get("signing_key_events"),
        )
        if error or profile.revision_key_id not in active:
            return False
        public_key = known.get(profile.revision_key_id)
        if public_key is None or not verify_revision(profile, public_key):
            return False
        events = profile.data.get("signing_key_events")
        trusted = self._trusted_signing_key_events.get(identity_key)
        if trusted is None:
            return True
        # Stale and newer profiles may carry a prefix or extension of the
        # trusted chain. A competing self-signed chain using the same public
        # identity key is not an authenticated revision of that identity.
        return (
            events == trusted
            or (
                len(events) < len(trusted)
                and events == trusted[:len(events)]
            )
            or (
                len(trusted) < len(events)
                and trusted == events[:len(trusted)]
            )
        )

    def peer_identity(self, peer_addr: str) -> ProtocolNode | None:
        # The address bootstraps identity-key discovery. Once known, resolve
        # across every alias/device so all routes expose the same newest
        # authenticated profile instead of their independently cached copy.
        identity_key = self._peer_identity_key.get(peer_addr)
        if identity_key:
            resolved = self.find_peer_identity(identity_key)
            if resolved is not None:
                return resolved
        tree = self._peer_perspectives.get(peer_addr)
        return self._find_identity_in_tree(tree) if tree else None

    def set_peer_identity_key(self, peer_addr: str, identity_key: str) -> None:
        # The single writer for the addr -> identity_key registry - every
        # code path that learns an address's identity (connect-token
        # snapshot, direct profile pull, relay discovery) funnels through
        # here, so the fact is recorded once, immediately, decoupled from
        # whether/when full content has been cached.
        if not peer_addr or not identity_key:
            return
        if self._peer_identity_key.get(peer_addr) == identity_key:
            return
        self._peer_identity_key[peer_addr] = identity_key
        self.trace_event(
            "session.set_peer_identity_key",
            peer_addr=peer_addr,
            identity_key=identity_key,
        )

    def addresses_for_identity(self, identity_key: str) -> list[str]:
        return sorted(
            addr for addr, key in self._peer_identity_key.items()
            if key == identity_key
        )

    def _local_revision_origin(self, data: dict | None = None) -> str | None:
        # Do not use the identity property here: identity creation itself
        # goes through create_child and would recurse. Search only what
        # already exists, with the new profile's key as bootstrap fallback.
        profile = self._find_identity_in_tree(self._protocol.root)
        if profile and profile.data.get("identity_key"):
            return profile.data["identity_key"]
        if (data or {}).get("type") == "shared_user_profile":
            return (data or {}).get("identity_key")
        return None

    def _next_local_revision_seq(self, origin: str | None) -> int:
        if not origin:
            return 0
        self.local_revision_seq += 1
        return self.local_revision_seq

    def _sign_local_revision(
        self, node: ProtocolNode | None, origin: str | None, revision_seq: int,
    ) -> None:
        if (
            node is not None
            and origin
            and node.revision_origin == origin
            and node.revision_seq == revision_seq
        ):
            node.revision_parent_uuid = node.parent_uuid
            sign_revision(node, self._signing_keypair)
            if self.is_identity_node(node):
                self._observe_identity_signing_keys(node)

    def _observe_identity_signing_keys(self, profile: ProtocolNode) -> bool:
        identity_key = profile.data.get("identity_key")
        events = profile.data.get("signing_key_events")
        if not isinstance(identity_key, str) or not identity_key:
            return False
        known, active, error = resolve_key_events(events)
        if error or profile.revision_key_id not in active:
            return False
        public_key = known.get(profile.revision_key_id)
        if public_key is None or not verify_revision(profile, public_key):
            return False
        detached = copy.deepcopy(events)
        trusted = self._trusted_signing_key_events.get(identity_key)
        if trusted is None:
            self._trusted_signing_key_events[identity_key] = detached
            return True
        if detached == trusted:
            return True
        if len(detached) >= len(trusted) and detached[:len(trusted)] == trusted:
            self._trusted_signing_key_events[identity_key] = detached
            return True
        # Stale and competing branches stay in peer observations, while the
        # last verified chain remains the source of verification authority.
        return False

    @property
    @_session_locked
    def signing_key_id(self) -> str:
        return self._signing_keypair["key_id"]

    @_session_locked
    def revision_verification(self, node: ProtocolNode) -> str:
        """Verify authorship without deciding whether the author had authority."""
        if not node.revision_origin or not node.revision_key_id or not node.revision_signature:
            return "invalid"
        profile = self._find_identity_in_tree(
            self._protocol.root, node.revision_origin,
        ) or self.find_peer_identity(node.revision_origin)
        if profile is not None:
            self._observe_identity_signing_keys(profile)
        trusted_events = self._trusted_signing_key_events.get(
            node.revision_origin,
        )
        if trusted_events is None:
            return "unknown"
        known, active, error = resolve_key_events(
            trusted_events,
        )
        if error:
            return "invalid"
        public_key = known.get(node.revision_key_id)
        if public_key is None:
            return "unknown"
        if node.revision_key_id not in active:
            return "invalid"
        if (
            self.is_identity_node(node)
            and node.data.get("signing_key_events") != trusted_events
        ):
            return "invalid"
        return "valid" if verify_revision(node, public_key) else "invalid"

    @_session_locked
    def issue_sibling_signing_key(self) -> SessionResult:
        """Authorize a distinct device key and return its private pairing bundle."""
        profile = self.identity
        new_key = generate_keypair()
        data = dict(profile.data)
        events = copy.deepcopy(data["signing_key_events"])
        events.append(activation_event(new_key, self._signing_keypair))
        data["signing_key_events"] = events
        updated = self.modify(profile.uuid, data, profile.weights)
        if updated.status != "ok":
            return updated
        return SessionResult("ok", value=new_key)

    @_session_locked
    def install_sibling_signing_key(self, keypair: dict) -> SessionResult:
        """Install only a private key already authorized by the paired identity."""
        try:
            public_key = public_key_for_private_key(keypair["private_key"])
            key_id = key_id_for_public_key(public_key)
        except (KeyError, TypeError, ValueError):
            return SessionResult("error", reason="pairing signing key is invalid")
        if keypair.get("public_key") != public_key or keypair.get("key_id") != key_id:
            return SessionResult("error", reason="pairing signing key does not match")
        known, active, error = resolve_key_events(
            self.identity.data.get("signing_key_events"),
        )
        if error or known.get(key_id) != public_key or key_id not in active:
            return SessionResult("error", reason="pairing signing key is not authorized")
        self._signing_keypair = copy.deepcopy(keypair)
        return SessionResult("ok", value=key_id)

    @_session_locked
    def rotate_signing_key(self) -> SessionResult:
        """Add a new active key and make it this device's signer."""
        issued = self.issue_sibling_signing_key()
        if issued.status != "ok":
            return issued
        return self.install_sibling_signing_key(issued.value)

    @_session_locked
    def revoke_signing_key(self, key_id: str) -> SessionResult:
        """Revoke another active key; self-revocation is deliberately forbidden."""
        if key_id == self._signing_keypair["key_id"]:
            return SessionResult(
                "error", reason="an active sibling key must revoke this device key",
            )
        profile = self.identity
        known, active, error = resolve_key_events(
            profile.data.get("signing_key_events"),
        )
        if error or key_id not in active or key_id not in known:
            return SessionResult("error", reason="signing key is not active")
        data = dict(profile.data)
        events = copy.deepcopy(data["signing_key_events"])
        events.append(revocation_event(key_id, self._signing_keypair))
        data["signing_key_events"] = events
        return self.modify(profile.uuid, data, profile.weights)

    def apply_peer_identity_snapshot(self, peer_addr: str, identity: dict) -> None:
        # A connect token carries the sender's identity inline so it's
        # visible immediately, without waiting on whichever channel(s) end
        # up actually usable to fetch it - deliberately unconditional
        # (never goes through collaborative revision reconciliation):
        # an identity assertion isn't collaborative content with divergence
        # to resolve, it's just "the latest thing this peer said about
        # themselves." Degrades gracefully (no-op) on anything it doesn't
        # recognize, rather than raising - a peer running a newer identity
        # version should never be able to break an older one's connect flow.
        data = identity.get("data", {}) if isinstance(identity, dict) else {}
        schema_error = (
            _core_profile_schema_error(data)
            if data.get("type") == "shared_user_profile"
            else "identity snapshot is not a Core profile"
        )
        if schema_error:
            self.trace_event(
                "session.reject_peer_identity_schema",
                peer_addr=peer_addr,
                received_version=data.get("profile_schema_version"),
                expected_version=CORE_PROFILE_SCHEMA_VERSION,
                reason=schema_error,
            )
            return
        try:
            node = ProtocolNode.from_dict(identity)
        except (ValueError, KeyError):
            return
        self.apply_peer_subtree(peer_addr, node, None)

    @staticmethod
    def _find_identity_in_tree(node: ProtocolNode | None,
                               identity_key: str | None = None) -> ProtocolNode | None:
        if not node:
            return None
        if (node.data.get("type") == "shared_user_profile"
                and (identity_key is None or node.data.get("identity_key") == identity_key)):
            return node
        for child in node.children:
            found = Session._find_identity_in_tree(child, identity_key)
            if found:
                return found
        return None

    @staticmethod
    def is_identity_node(node: ProtocolNode | None) -> bool:
        if not node:
            return False
        return node.data.get("type") == "shared_user_profile"

    # Read-only protocol access / persistence

    @_session_locked
    def load_protocol_root(self, root: ProtocolNode) -> None:
        self._protocol.root = root
        self._protocol.index = {}
        self._protocol.index_subtree(root)
        self.protocol = ReadOnlyProtocolView(self._protocol, self.lock)

    @_session_locked
    def export_protocol_root(self) -> dict:
        return self._protocol.root.to_dict()

    @_session_locked
    def export_persistence_protocol_root(self) -> dict:
        """Persist this client's agenda, never cached/adopted peer agendas."""
        identity = self.identity
        root = ProtocolNode.from_dict(self._protocol.root.to_dict())
        identity_key = str(identity.data.get("identity_key") or "")

        def retain(node: ProtocolNode) -> None:
            kept = []
            for child in node.children:
                if child.data.get("type") == "agenda_item" and not (
                    child.data.get("author") == identity.uuid
                    and child.revision_origin == identity_key
                ):
                    continue
                retain(child)
                kept.append(child)
            node.children = kept

        retain(root)
        root.refresh_hashes_deep()
        return root.to_dict()

    def root_uuid(self) -> str:
        return self._protocol.root.uuid

    def has_node(self, node_uuid: str | None) -> bool:
        return bool(node_uuid and node_uuid in self._protocol.index)

    @_session_locked
    def node_state_hash(self, node_uuid: str) -> str | None:
        node = self._protocol.index.get(node_uuid)
        return node.state_hash if node else None

    # Discussion/session state

    @_session_locked
    def start_discussion(self, topic_uuid: str) -> SessionResult:
        if topic_uuid not in self._protocol.index:
            return SessionResult("error", reason="topic not found")
        self._active_topic_uuids.add(topic_uuid)
        return SessionResult("ok", value=topic_uuid)

    @_session_locked
    def note_indirect_peer_topic(self, peer_addr: str, topic_uuid: str) -> None:
        # The one way a peer relationship is recorded. Application auto-adopt
        # policies gate candidates on peer_topic_sets (_peer_discusses_node)
        # to know a cached peer perspective actually applies to a given
        # topic - without this, a relay-sourced cache update would be
        # silently invisible to auto-adopt even though the data arrived
        # correctly.
        self._peer_topic_sets.setdefault(peer_addr, set()).add(topic_uuid)

    def bind_peer_topic_channel(
        self, peer_addr: str, topic_uuid: str, channel_kind: str,
    ) -> None:
        peer_addr = str(peer_addr or "").strip()
        topic_uuid = str(topic_uuid or "").strip()
        channel_kind = str(channel_kind or "").strip()
        if not peer_addr or not topic_uuid or not channel_kind:
            raise ValueError("peer, topic and channel are required")
        self.peer_topic_channel.setdefault(peer_addr, {})[topic_uuid] = channel_kind

    def bind_peer_topics_channel(
        self, peer_addr: str, topic_uuids: list[str] | set[str] | tuple[str, ...],
        channel_kind: str,
    ) -> None:
        for topic_uuid in sorted(set(topic_uuids)):
            self.bind_peer_topic_channel(peer_addr, topic_uuid, channel_kind)

    def peer_channel_for_topic(
        self, peer_addr: str, topic_uuid: str,
    ) -> str | None:
        return self.peer_topic_channel.get(peer_addr, {}).get(topic_uuid)

    def unbind_peer_topic_channel(self, peer_addr: str, topic_uuid: str) -> None:
        bindings = self.peer_topic_channel.get(peer_addr)
        if not bindings:
            return
        bindings.pop(topic_uuid, None)
        if not bindings:
            self.peer_topic_channel.pop(peer_addr, None)

    def peers_for_topic(self, topic_uuid: str) -> list[str]:
        return sorted(
            peer for peer, topics in self._peer_topic_sets.items()
            if topic_uuid in topics
        )

    @_session_locked
    def accept_topic_invitation(self, tree: ProtocolNode,
                                parent_uuid: str | None = None) -> SessionResult:
        result = self._protocol.attach_topic(
            tree,
            parent_uuid or self._other_perspectives_uuid(),
        )
        if not result.ok:
            return SessionResult("error", reason=result.reason)
        self._active_topic_uuids.add(result.value)
        return SessionResult("ok", value=result.value)

    def leave_topic(self, topic_uuid: str) -> SessionResult:
        # No message goes out. A relay peer is told by absence: this client
        # stops publishing into the slot, and stops polling theirs.
        tracked_peers = sorted(
            peer for peer, topics in self._peer_topic_sets.items()
            if topic_uuid in topics
        )
        self._active_topic_uuids.discard(topic_uuid)
        for peer in tracked_peers:
            self._remove_peer_topic(peer, topic_uuid)
        return SessionResult("ok")

    def end_topic_sharing(self, topic_uuid: str) -> SessionResult:
        """End the Session relationship and ask Core to release all channels.

        Session deliberately knows only the lifecycle effect, never the
        channel implementations that will execute it.
        """
        result = self.leave_topic(topic_uuid)
        if result.status == "ok":
            result.effects.append(SessionEffect(
                "release_topic_channels",
                topic_uuid,
                {"topic_uuid": topic_uuid},
            ))
        return result


    @staticmethod
    def node_revision(node: ProtocolNode) -> str:
        # content_hash is this node's OWN version (no descendants), so a
        # descendant change never re-revisions an ancestor - observation stays
        # aligned with classification (both key on content_hash). parent_uuid
        # makes moves independently acknowledgeable; origin and sequence
        # distinguish independently authored and successive revisions.
        return (
            f"{node.content_hash}@{node.parent_uuid or ''}"
            f"@{node.revision_origin or ''}@{node.revision_seq}"
        )

    @classmethod
    def node_revision_map(cls, root: ProtocolNode) -> dict[str, str]:
        revisions = {root.uuid: cls.node_revision(root)}
        for child in root.children:
            revisions.update(cls.node_revision_map(child))
        return revisions

    @_session_locked
    def record_peer_observations(self, peer_addr: str,
                                 revisions: dict[str, str]) -> bool:
        if not peer_addr or not isinstance(revisions, dict):
            return False
        known = self.peer_observed_node_revisions.setdefault(peer_addr, {})
        changed = False
        for node_uuid, revision in revisions.items():
            if not node_uuid or not isinstance(revision, str):
                continue
            if known.get(node_uuid) != revision:
                known[node_uuid] = revision
                changed = True
        return changed

    def peer_observed_node(self, peer_addr: str, node: ProtocolNode) -> bool:
        return (
            self.peer_observed_node_revisions.get(peer_addr, {}).get(node.uuid)
            == self.node_revision(node)
        )

    # Peer cache

    @_session_locked
    def apply_peer_subtree(self, peer_addr: str,
                           subtree: ProtocolNode,
                           parent_uuid: str | None) -> None:
        for topic_uuid in self._peer_topic_sets.get(peer_addr, set()):
            if subtree.uuid == topic_uuid or self._find_in_tree(subtree, topic_uuid):
                self.observe_peer_perspective(peer_addr, topic_uuid)
        # Identity topics are always applied with the profile node as the
        # subtree root (connect-token snapshot, direct profile pull, relay
        # poll alike), so a root-only check is enough to make this the one
        # choke point where every channel's identity discovery lands in
        # the addr -> identity_key registry.
        if self.is_identity_node(subtree) and subtree.data.get("identity_key"):
            self.set_peer_identity_key(peer_addr, subtree.data["identity_key"])
            self._observe_identity_signing_keys(subtree)
        cached = self._peer_perspectives.get(peer_addr)
        if cached is None:
            self._peer_perspectives[peer_addr] = subtree
            self.trace_event(
                "session.apply_peer_subtree",
                peer_addr=peer_addr,
                node_uuid=subtree.uuid,
                parent_uuid=parent_uuid,
                state_hash=subtree.state_hash,
                action="new_cache",
            )
            self.prune_deleted_nodes()
            return

        subtree_uuids = collect_subtree_uuids(subtree)
        target = self._find_in_tree(cached, subtree.uuid)
        if target is None:
            for uuid in subtree_uuids:
                self._remove_uuid_from_tree(cached, uuid)
            parent = self._find_in_tree(cached, parent_uuid) if parent_uuid else None
            if parent:
                subtree.parent_uuid = parent.uuid
                parent.children = [
                    child for child in parent.children
                    if child.uuid != subtree.uuid
                ]
                parent.children.append(subtree)
                self._refresh_tree_hashes(cached)
                self.trace_event(
                    "session.apply_peer_subtree",
                    peer_addr=peer_addr,
                    node_uuid=subtree.uuid,
                    parent_uuid=parent_uuid,
                    state_hash=subtree.state_hash,
                    action="append_to_parent",
                )
                self.prune_deleted_nodes()
                return
            if cached.data.get("type") == "peer_cache_root":
                subtree.parent_uuid = cached.uuid
                cached.children = [
                    child for child in cached.children
                    if child.uuid != subtree.uuid
                ]
                cached.children.append(subtree)
                self._refresh_tree_hashes(cached)
                self.trace_event(
                    "session.apply_peer_subtree",
                    peer_addr=peer_addr,
                    node_uuid=subtree.uuid,
                    parent_uuid=parent_uuid,
                    state_hash=subtree.state_hash,
                    action="append_to_cache_root",
                )
                self.prune_deleted_nodes()
                return
            if cached.uuid != subtree.uuid:
                aggregate = self._peer_cache_root(peer_addr)
                existing = cached
                existing.parent_uuid = aggregate.uuid
                subtree.parent_uuid = aggregate.uuid
                aggregate.children = [existing, subtree]
                aggregate.refresh_hashes_deep()
                self._peer_perspectives[peer_addr] = aggregate
                self.trace_event(
                    "session.apply_peer_subtree",
                    peer_addr=peer_addr,
                    node_uuid=subtree.uuid,
                    parent_uuid=parent_uuid,
                    state_hash=subtree.state_hash,
                    action="create_cache_root",
                )
                self.prune_deleted_nodes()
                return
            self._peer_perspectives[peer_addr] = subtree
            self.trace_event(
                "session.apply_peer_subtree",
                peer_addr=peer_addr,
                node_uuid=subtree.uuid,
                parent_uuid=parent_uuid,
                state_hash=subtree.state_hash,
                action="replace_cache",
            )
            self.prune_deleted_nodes()
            return

        old_state_hash = target.state_hash
        self._remove_duplicate_subtree_uuids(cached, subtree_uuids, subtree.uuid)
        target.created_at = subtree.created_at
        target.updated_at = subtree.updated_at
        target.content_hash = subtree.content_hash
        target.state_hash = subtree.state_hash
        target.base_hash = subtree.base_hash
        target.base_parent_uuid = subtree.base_parent_uuid
        target.deleted = subtree.deleted
        target.revision_origin = subtree.revision_origin
        target.revision_seq = subtree.revision_seq
        target.revision_parent_uuid = subtree.revision_parent_uuid
        target.revision_key_id = subtree.revision_key_id
        target.revision_signature = subtree.revision_signature
        target.weights = subtree.weights
        target.data = subtree.data
        target.children = subtree.children
        if parent_uuid and target.parent_uuid != parent_uuid:
            old_parent = self._find_in_tree(cached, target.parent_uuid)
            new_parent = self._find_in_tree(cached, parent_uuid)
            if old_parent and new_parent:
                old_parent.children = [
                    child for child in old_parent.children
                    if child.uuid != target.uuid
                ]
                target.parent_uuid = new_parent.uuid
                new_parent.children = [
                    child for child in new_parent.children
                    if child.uuid != target.uuid
                ]
                new_parent.children.append(target)
        self._refresh_tree_hashes(cached)
        self.trace_event(
            "session.apply_peer_subtree",
            peer_addr=peer_addr,
            node_uuid=subtree.uuid,
            parent_uuid=parent_uuid,
            old_state_hash=old_state_hash,
            state_hash=subtree.state_hash,
            action="update_existing",
        )
        self.prune_deleted_nodes()

    def get_cached_peer_subtree(self, peer_addr: str, node_uuid: str) -> ProtocolNode | None:
        tree = self._peer_perspectives.get(peer_addr)
        if not tree:
            return None
        node = self._find_in_tree(tree, node_uuid)
        return ProtocolNode.from_dict(node.to_dict()) if node else None

    def peer_discusses_node(self, peer_addr: str, node_uuid: str) -> bool:
        return any(
            self._is_descendant_or_self(topic_uuid, node_uuid)
            for topic_uuid in self._peer_topic_sets.get(peer_addr, set())
        )

    def peer_topics_for_node(
        self, peer_addr: str, node_uuid: str,
    ) -> list[str]:
        tree = self._peer_perspectives.get(peer_addr)
        if not tree:
            return []
        return [
            topic_uuid
            for topic_uuid in sorted(
                self._peer_topic_sets.get(peer_addr, set()),
            )
            if (
                (topic := self._find_in_tree(tree, topic_uuid))
                and self._find_in_tree(topic, node_uuid)
            )
        ]

    @_session_locked
    def forget_peer_topic_perspective(self, peer_addr: str,
                                      topic_uuid: str) -> bool:
        """Drop a peer's cached content for one topic, keep the relationship.

        Deliberately narrower than remove_peer. The cache is a view of what
        a peer is currently publishing, so it may follow what the channel
        can presently see. peer_topic_sets is the relationship, and dropping
        that would also drop the peer's vote in prune_deleted_nodes - which
        is how a peer that merely went quiet could have its deletions pruned
        and then re-proposed as new nodes when it came back.

        Losing the cache makes _peer_topic_confirms_deletion answer False
        for this peer, so pruning becomes more conservative here, never
        less.
        """
        tree = self._peer_perspectives.get(peer_addr)
        self._perspective_observations.pop((peer_addr, topic_uuid), None)
        if not tree:
            return False
        if tree.uuid == topic_uuid:
            # The cache root is the topic itself, so there is nothing left
            # to keep - same case handle_leave has to make.
            self._peer_perspectives.pop(peer_addr, None)
            return True
        if not self._find_in_tree(tree, topic_uuid):
            return False
        self._remove_uuid_from_tree(tree, topic_uuid)
        self._refresh_tree_hashes(tree)
        return True

    def analyze_peer_transitions(self, peer_addr: str,
                                 node_uuid: str | None = None) -> list[dict]:
        peer_root = self._peer_perspectives.get(peer_addr)
        if not peer_root:
            return []
        compare_uuid = node_uuid or peer_root.uuid
        peer_node = self._find_in_tree(peer_root, compare_uuid)
        local_node = self._protocol.index.get(compare_uuid)
        if not local_node and not peer_node:
            return []
        # Nodes are matched by uuid across the whole subtree, not by
        # structural position, so a node that moved to a different parent
        # on one side is still compared against its own counterpart (and
        # its move is attributable via base_parent_uuid) instead of
        # showing up as an unrelated local_missing/peer_missing pair.
        local_by_uuid = self._flatten_by_uuid(local_node) if local_node else {}
        peer_by_uuid = self._flatten_by_uuid(peer_node) if peer_node else {}
        other_uuids = sorted((set(local_by_uuid) | set(peer_by_uuid)) - {compare_uuid})
        events = []
        for uuid in [compare_uuid, *other_uuids]:
            local = local_by_uuid.get(uuid)
            peer = peer_by_uuid.get(uuid)
            is_compare_root = uuid == compare_uuid
            event = self._analyze_transition_node(
                peer_addr,
                local,
                peer,
                is_topic_root=is_compare_root,
            )
            observed = bool(
                local and self.peer_observed_node(peer_addr, local)
            )
            event["peer_observed_local_revision"] = observed
            # Returning a field to an earlier value crosses both content/base
            # relations. Relay observation supplies the causal direction that
            # hashes alone cannot: this peer built its new revision on ours.
            if (
                observed
                and local is not None
                and peer is not None
                and event["type"] == "local_made_changes"
                and peer.content_hash == local.base_hash
                and local.content_hash == peer.base_hash
                and (
                    is_compare_root
                    or local.parent_uuid == peer.parent_uuid
                )
            ):
                event["type"] = "peer_made_changes"
            events.append(self._stage_transition_event(event))
        return events

    @staticmethod
    def _flatten_by_uuid(node: ProtocolNode) -> dict[str, ProtocolNode]:
        out = {node.uuid: node}
        for child in node.children:
            out.update(Session._flatten_by_uuid(child))
        return out

    # App-facing protocol wrappers

    @_session_locked
    def create_child(self, parent_uuid: str, data: dict,
                     weights: dict[str, float] | None = None) -> SessionResult:
        if (
            not self._creating_identity
            and not (
                data.get("type") == "folder"
                and data.get("name") == "shared_user_data"
            )
            and self._find_identity_in_tree(self._protocol.root) is None
        ):
            # Authorship must exist before the first application mutation.
            # Identity's own bootstrap folder uses the guarded recursive path.
            self.identity
        if data.get("type") == "shared_user_profile":
            profile_error = _core_profile_schema_error(data)
            if profile_error:
                return SessionResult("error", reason=profile_error)
        revision_origin = self._local_revision_origin(data)
        revision_seq = self._next_local_revision_seq(revision_origin)
        result = self._protocol.create_child(
            parent_uuid, data, weights, revision_origin, revision_seq,
        )
        if not result.ok:
            return SessionResult("error", reason=result.reason)
        child = result.value
        self._sign_local_revision(child, revision_origin, revision_seq)
        self.trace_event(
            "protocol.create_child",
            parent_uuid=parent_uuid,
            node_uuid=child.uuid,
            node_type=child.data.get("type"),
            state_hash=child.state_hash,
            revision_origin=child.revision_origin,
            revision_seq=child.revision_seq,
        )
        return SessionResult("ok", value=self._snapshot_node(child))

    @_session_locked
    def modify(self, node_uuid: str, data: dict,
               weights: dict[str, float] | None = None,
               revision_origin: str | None | object = _LOCAL_REVISION_ORIGIN) -> SessionResult:
        before = self._protocol.index.get(node_uuid)
        if (data.get("type") == "shared_user_profile"
                or (before and before.data.get("type") == "shared_user_profile")):
            profile_error = _core_profile_schema_error(data)
            if profile_error:
                return SessionResult("error", reason=profile_error)
            if before:
                old_events = before.data.get("signing_key_events")
                new_events = data.get("signing_key_events")
                if (
                    not isinstance(old_events, list)
                    or not isinstance(new_events, list)
                    or len(new_events) < len(old_events)
                    or new_events[:len(old_events)] != old_events
                ):
                    return SessionResult(
                        "error", reason="signing key events are append-only",
                    )
        old_state_hash = before.state_hash if before else None
        origin = (
            self._local_revision_origin(data)
            if revision_origin is _LOCAL_REVISION_ORIGIN
            else revision_origin
        )
        revision_seq = self._next_local_revision_seq(origin)
        result = self._protocol.modify(
            node_uuid, data, weights, origin, revision_seq,
        )
        after = self._protocol.index.get(node_uuid)
        if result.ok:
            self._sign_local_revision(after, origin, revision_seq)
        self.trace_event(
            "protocol.modify",
            node_uuid=node_uuid,
            old_state_hash=old_state_hash,
            state_hash=after.state_hash if after else None,
            revision_origin=(
                after.revision_origin if after else None
            ),
            revision_seq=after.revision_seq if after else None,
            ok=result.ok,
            reason=result.reason,
        )
        return self._operation_result(result, node_uuid)

    @_session_locked
    def delete(self, node_uuid: str) -> SessionResult:
        node = self._protocol.index.get(node_uuid)
        changed_nodes = [
            item for item in self._flatten_by_uuid(node).values()
            if not item.deleted
        ] if node else []
        parent_uuid = node.parent_uuid if node else None
        old_state_hash = node.state_hash if node else None
        origin = self._local_revision_origin()
        revision_seq = self._next_local_revision_seq(origin)
        result = self._protocol.delete(node_uuid, origin, revision_seq)
        if result.ok:
            for changed in changed_nodes:
                self._sign_local_revision(changed, origin, revision_seq)
            self.prune_deleted_nodes()
        self.trace_event(
            "protocol.delete",
            node_uuid=node_uuid,
            parent_uuid=parent_uuid,
            old_state_hash=old_state_hash,
            ok=result.ok,
            reason=result.reason,
        )
        return self._operation_result(result, parent_uuid or node_uuid)

    @_session_locked
    def copy(self, source_uuid: str, destination_uuid: str) -> SessionResult:
        origin = self._local_revision_origin()
        revision_seq = self._next_local_revision_seq(origin)
        result = self._protocol.copy(
            source_uuid, destination_uuid, origin, revision_seq,
        )
        if not result.ok:
            return SessionResult("error", reason=result.reason)
        clone = result.value
        for changed in self._flatten_by_uuid(clone).values():
            self._sign_local_revision(changed, origin, revision_seq)
        return SessionResult("ok", value=self._snapshot_node(clone))

    @_session_locked
    def move(self, source_uuid: str, destination_uuid: str) -> SessionResult:
        origin = self._local_revision_origin()
        revision_seq = self._next_local_revision_seq(origin)
        result = self._protocol.move(
            source_uuid, destination_uuid, origin, revision_seq,
        )
        if result.ok:
            self._sign_local_revision(
                self._protocol.index.get(source_uuid), origin, revision_seq,
            )
        return self._operation_result(result, source_uuid)

    @_session_locked
    def move_child(self, source_uuid: str, destination_uuid: str,
                   index: int | None = None) -> SessionResult:
        node = self._protocol.index.get(source_uuid)
        old_parent_uuid = node.parent_uuid if node else None
        old_state_hash = node.state_hash if node else None
        origin = self._local_revision_origin()
        revision_seq = self._next_local_revision_seq(origin)
        result = self._protocol.move_child(
            source_uuid, destination_uuid, index,
            origin, revision_seq,
        )
        moved = self._protocol.index.get(source_uuid)
        if result.ok:
            self._sign_local_revision(moved, origin, revision_seq)
        self.trace_event(
            "protocol.move_child",
            node_uuid=source_uuid,
            old_parent_uuid=old_parent_uuid,
            destination_uuid=destination_uuid,
            index=index,
            old_state_hash=old_state_hash,
            state_hash=moved.state_hash if moved else None,
            revision_origin=moved.revision_origin if moved else None,
            revision_seq=moved.revision_seq if moved else None,
            ok=result.ok,
            reason=result.reason,
        )
        return self._operation_result(result, source_uuid)

    @_session_locked
    def adopt_subtree(self, tree: ProtocolNode, parent_uuid: str,
                      remove_descendant_duplicates: bool = False) -> SessionResult:
        result = self._protocol.adopt_subtree(
            tree,
            parent_uuid,
            remove_descendant_duplicates=remove_descendant_duplicates,
        )
        if not result.ok:
            self.trace_event(
                "protocol.adopt_subtree",
                node_uuid=tree.uuid,
                parent_uuid=parent_uuid,
                state_hash=tree.state_hash,
                ok=False,
                reason=result.reason,
            )
            return SessionResult("error", reason=result.reason)
        adopted = result.value
        self.trace_event(
            "protocol.adopt_subtree",
            node_uuid=adopted.uuid,
            parent_uuid=parent_uuid,
            state_hash=adopted.state_hash,
            ok=True,
            remove_descendant_duplicates=remove_descendant_duplicates,
        )
        return SessionResult("ok", value=self._snapshot_node(adopted))

    # ---- adoption metadata ------------------------------------------------
    # Applications record how incoming changes are handled; Core executes the
    # record. Resolution cascades node -> topic -> ROOT_DEFAULT, so the table
    # stays small: a topic default plus the exceptions, rather than an entry
    # per node.

    def _restore_adoption_metadata(self, stored: Any) -> None:
        """Restore the table, dropping entries for nodes that are gone.

        This is the table's garbage collection, and it matches how
        active_topic_uuids is already treated: a uuid no longer in the index
        cannot be adopted into, so its entry is dead weight. An unreadable
        entry is dropped rather than raised on - the conservative root default
        then applies, which is safe, where refusing to open the session is not.
        """
        self._adoption_by_node.clear()
        self._adoption_by_topic.clear()
        if not isinstance(stored, dict):
            return
        for key, target in (
            ("nodes", self._adoption_by_node),
            ("topics", self._adoption_by_topic),
        ):
            values = stored.get(key)
            if not isinstance(values, dict):
                continue
            for node_uuid, value in values.items():
                if (
                    not isinstance(node_uuid, str)
                    or self._protocol.index.get(node_uuid) is None
                ):
                    continue
                entry = AdoptionEntry.from_dict(value)
                if entry is not None:
                    target[node_uuid] = entry

    @_session_locked
    def set_adoption_metadata(
        self,
        node_uuid: str,
        *,
        adopt: str | None = None,
        additions: str | None = None,
        author: str | None = None,
    ) -> SessionResult:
        """Record how changes to one node are handled."""
        try:
            entry = AdoptionEntry(adopt=adopt, additions=additions, author=author)
        except ValueError as error:
            return SessionResult("error", reason=str(error))
        if not entry.to_dict():
            self._adoption_by_node.pop(node_uuid, None)
            return SessionResult("ok", value=None)
        self._adoption_by_node[node_uuid] = entry
        return SessionResult("ok", value=entry.to_dict())

    @_session_locked
    def set_topic_adoption_default(
        self,
        topic_uuid: str,
        *,
        adopt: str | None = None,
        additions: str | None = None,
        author: str | None = None,
    ) -> SessionResult:
        """Record the default for every node in one topic."""
        try:
            entry = AdoptionEntry(adopt=adopt, additions=additions, author=author)
        except ValueError as error:
            return SessionResult("error", reason=str(error))
        previous = self._adoption_by_topic.get(topic_uuid)
        if not entry.to_dict():
            self._adoption_by_topic.pop(topic_uuid, None)
        else:
            self._adoption_by_topic[topic_uuid] = entry
        if previous == entry:
            # Republishing what is already declared decides nothing new.
            return SessionResult("ok", value=entry.to_dict() or None)
        # Classifier answers were derived under the declaration that just
        # changed, so they are stale.
        self._forget_unheld_adoption_answers()
        # A declaration that only takes effect on the next peer update looks
        # broken: turn adoption on while looking at a divergence and nothing
        # happens, and if the peer has nothing further to send, nothing ever
        # will. Core applies it now, for whichever application declared it.
        self.reapply_adoption(topic_uuid)
        return SessionResult("ok", value=entry.to_dict() or None)

    @_session_locked
    def set_topic_reconciliation_policies(
        self, topic_uuid: str,
        policies: tuple[LastWriteWinsPolicy, ...] = (),
    ) -> SessionResult:
        """Declare the structured conflict rules for one topic.

        Held with the topic rather than passed per call so that Core can run a
        pass on an application's behalf and reach the same result the
        application would have.
        """
        if policies:
            self._reconciliation_by_topic[topic_uuid] = tuple(policies)
        else:
            self._reconciliation_by_topic.pop(topic_uuid, None)
        return SessionResult("ok", value=len(policies))

    def _forget_unheld_adoption_answers(self) -> None:
        """Drop what the classifier said about nodes this client does not hold.

        Those answers only ever cover unheld nodes - a held node's entry is
        written by its application - so dropping exactly those re-asks the
        question on the next pass without touching a decision anyone made.
        """
        for node_uuid in list(self._adoption_by_node):
            if self._protocol.index.get(node_uuid) is None:
                self._adoption_by_node.pop(node_uuid, None)

    @_session_locked
    def reconsider_adoption(self, topic_uuid: str) -> bool:
        """Re-ask every decision this topic is currently holding back.

        An application's handling is not only what it declares here: a mode
        that admits some cards and holds others is read by its own resolver at
        the moment of decision, and Core cannot see it change. When it does,
        every answer derived from it is stale in exactly the way a changed
        declaration makes them stale, and is cleared the same way - so an
        application says so once and Core does the rest.

        Without this, a setting only takes effect on whatever the peer sends
        next: widen the mode while looking at a held card and nothing happens,
        and if the peer has nothing further to send, nothing ever will. No peer
        is contacted - the snapshot each one last sent is enough to decide
        against.
        """
        self._forget_unheld_adoption_answers()
        return self.reapply_adoption(topic_uuid)

    @_session_locked
    def reapply_adoption(self, topic_uuid: str) -> bool:
        """Reconcile this topic with every peer that shares it.

        Core's own driver: the declaration is Core's, so acting on a change to
        it is Core's too, and every application gets the same behaviour without
        remembering to ask.
        """
        if topic_uuid in self._reconciling_topics:
            return False
        if self._protocol.index.get(topic_uuid) is None:
            return False
        changed = False
        for peer_addr in self.peer_addresses(topic_uuid):
            if not self.peer_discusses_node(peer_addr, topic_uuid):
                continue
            changed = self.reconcile_peer_changes(
                peer_addr, topic_uuid,
            ) or changed
        return changed

    @_session_locked
    def clear_adoption_metadata(self, node_uuid: str) -> SessionResult:
        self._adoption_by_node.pop(node_uuid, None)
        return SessionResult("ok", value=None)

    def adoption_metadata(self, node_uuid: str) -> AdoptionEntry:
        """The effective handling of one node, after inheritance."""
        entry = self._adoption_by_node.get(node_uuid, AdoptionEntry())
        return entry.inherit(
            self._inherited_adoption_default(node_uuid),
        ).inherit(ROOT_DEFAULT)

    def _inherited_adoption_default(self, node_uuid: str) -> AdoptionEntry:
        """The nearest declared default at or above this node.

        Walked structurally rather than resolved through the topic registry: a
        default declared on a topic root governs its subtree, and which entry
        applies must not depend on whether a topic was registered.
        """
        seen: set[str] = set()
        current = self._protocol.index.get(node_uuid)
        while current is not None and current.uuid not in seen:
            seen.add(current.uuid)
            declared = self._adoption_by_topic.get(current.uuid)
            if declared is not None:
                return declared
            current = self._protocol.index.get(current.parent_uuid or "")
        return AdoptionEntry()

    def adoption_metadata_for_addition(self, parent_uuid: str) -> AdoptionEntry:
        """How a child not yet held is handled: the parent's `additions`.

        A node that does not exist locally cannot carry an entry, so its
        parent - which the recipient does hold - answers for it. The parent's
        `author` carries over, so "only the trustee may add here" is one
        statement rather than one per child.
        """
        parent = self.adoption_metadata(parent_uuid)
        return AdoptionEntry(
            adopt=parent.additions,
            additions=parent.additions,
            author=parent.author,
        )

    @_session_locked
    def set_adoption_metadata_for_subtree(
        self,
        root_uuid: str,
        *,
        adopt: str | None = None,
        additions: str | None = None,
        author: str | None = None,
        node_type: str | None = None,
    ) -> SessionResult:
        """Apply one entry across a subtree, optionally by node type.

        Offered by Core so applications do not each write the same walk when
        circumstances change - an ownership change, a mode change, a new
        trustee.
        """
        root = self._protocol.index.get(root_uuid)
        if root is None:
            return SessionResult("error", reason="node not found")
        written = 0
        for node in self._flatten_by_uuid(root).values():
            if node_type is not None and node.data.get("type") != node_type:
                continue
            result = self.set_adoption_metadata(
                node.uuid, adopt=adopt, additions=additions, author=author,
            )
            if result.status != "ok":
                return result
            written += 1
        return SessionResult("ok", value=written)

    @_session_locked
    def replace_adoption_author(
        self, root_uuid: str, previous_author: str, author: str,
    ) -> SessionResult:
        """Swap one authority for another throughout a subtree.

        The trustee change: authority moved, so every entry naming the old
        holder now names the new one. Entries with a different author, or none,
        are left alone.
        """
        root = self._protocol.index.get(root_uuid)
        if root is None:
            return SessionResult("error", reason="node not found")
        if not isinstance(author, str) or not author.strip():
            return SessionResult("error", reason="author must be a non-empty string")
        swapped = 0
        for node_uuid in self._flatten_by_uuid(root):
            entry = self._adoption_by_node.get(node_uuid)
            if entry is None or entry.author != previous_author:
                continue
            self._adoption_by_node[node_uuid] = entry.with_author(author)
            swapped += 1
        for topic_uuid, entry in list(self._adoption_by_topic.items()):
            if topic_uuid == root_uuid and entry.author == previous_author:
                self._adoption_by_topic[topic_uuid] = entry.with_author(author)
                swapped += 1
        return SessionResult("ok", value=swapped)

    @_session_locked
    def set_adoption_classifier(
        self,
        topic_uuid: str,
        classifier: Callable[[ProtocolNode, AdoptionEntry], AdoptionEntry | None]
        | None,
    ) -> SessionResult:
        """Register how this topic classifies a node it does not yet hold.

        A node that does not exist locally carries no entry, and its parent's
        `additions` cannot tell one kind of incoming node from another. So Core
        asks the application to classify it **once**, at first sight, and
        persists the answer; every decision after that is a table read.

        The distinction that matters: this classifies a node, it does not
        decide an adoption. A hook consulted per decision would be
        node_is_eligible under another name - application logic back on the
        adoption path, and decisions that cannot be reproduced from stored
        state.

        It runs inside the session lock during reconciliation, so it must be
        read-only on Session and must not perform I/O. Core never blocks on it:
        no classifier, a classifier returning None, or one that raises, all
        leave the inherited default in force.
        """
        if classifier is None:
            self._adoption_classifiers.pop(topic_uuid, None)
        else:
            self._adoption_classifiers[topic_uuid] = classifier
        return SessionResult("ok", value=None)

    def _classify_unheld_node(
        self, topic_uuid: str, node_uuid: str, peer_node: ProtocolNode,
    ) -> None:
        """Ask once, and remember, before the entry is read."""
        if node_uuid in self._adoption_by_node:
            return
        classifier = self._adoption_classifiers.get(topic_uuid)
        if classifier is None:
            return
        parent_uuid = peer_node.parent_uuid or ""
        default = (
            self.adoption_metadata_for_addition(parent_uuid)
            if self._protocol.index.get(parent_uuid) is not None
            else ROOT_DEFAULT
        )
        try:
            # A detached copy: classifying must not be a way to edit the tree.
            entry = classifier(self._snapshot_node(peer_node), default)
        except Exception as error:  # an application fault is not Core's crash
            self.trace_event(
                "session.adoption_classifier_failed",
                topic_uuid=topic_uuid,
                node_uuid=node_uuid,
                reason=repr(error),
            )
            return
        if entry is None:
            return
        if not isinstance(entry, AdoptionEntry):
            # A plain mapping is accepted so an application needs no import to
            # answer: {"adopt": "never"} says as much as the dataclass does.
            entry = AdoptionEntry.from_dict(entry)
        if entry is None or not entry.to_dict():
            return
        self._adoption_by_node[node_uuid] = entry
        self.trace_event(
            "session.adoption_classified",
            topic_uuid=topic_uuid,
            node_uuid=node_uuid,
            node_type=peer_node.data.get("type"),
            entry=entry.to_dict(),
        )

    @_session_locked
    def set_adoption_resolver(
        self,
        topic_uuid: str,
        resolver: Callable[[ProtocolNode, ProtocolNode | None, str], str | None]
        | None,
    ) -> SessionResult:
        """Register how this topic resolves a node it is holding.

        `hold` records that nothing has decided yet. It ends in one of three
        ways, and the application says which: `adopt` (its own rule settles
        it), `refuse` (its rule says no, and no user decision overrides that),
        or `defer` (nobody has decided; the user's decision governs).

        Asked at the moment of decision and never stored, unlike a classifier's
        answer, because the rules it answers from - membership, roles, what
        somebody holds today - move. Storing the verdict would be a cache of
        exactly the state that changes underneath it.

        It runs inside the session lock, so it must be read-only on Session and
        must not block. Reaching back into relay I/O or the channel manager
        raises rather than deadlocks: Session is the innermost lock layer and
        OrderedRLock rejects reverse acquisition. No resolver, a resolver
        returning nothing, or one that raises, all mean `defer`.
        """
        if resolver is None:
            self._adoption_resolvers.pop(topic_uuid, None)
        else:
            self._adoption_resolvers[topic_uuid] = resolver
        return SessionResult("ok", value=None)

    def _resolve_held_node(
        self,
        topic_uuid: str,
        peer_node: ProtocolNode,
        local_node: ProtocolNode | None,
        peer_addr: str,
    ) -> str:
        resolver = self._adoption_resolvers.get(topic_uuid)
        if resolver is None:
            return RESOLVE_DEFER
        try:
            # Detached copies: resolving must not be a way to edit the tree.
            verdict = resolver(
                self._snapshot_node(peer_node),
                self._snapshot_node(local_node) if local_node else None,
                peer_addr,
            )
        except Exception as error:  # an application fault is not Core's crash
            self.trace_event(
                "session.adoption_resolver_failed",
                topic_uuid=topic_uuid,
                node_uuid=peer_node.uuid,
                reason=repr(error),
            )
            return RESOLVE_DEFER
        if verdict not in RESOLVE_VALUES:
            return RESOLVE_DEFER
        return verdict

    def _adoption_author_permits(
        self, entry: AdoptionEntry, peer_node: ProtocolNode,
        reference: ProtocolNode | None,
    ) -> bool:
        """Whether this revision's origin may write here.

        `author` is matched against `revision_origin`, which carries an
        identity key - not a profile uuid. An application naming a concrete
        authority resolves the holder's identity key and writes that.
        """
        author = entry.author or AUTHOR_ANY
        if author == AUTHOR_ANY:
            return True
        origin = str(peer_node.revision_origin or "")
        if author == AUTHOR_SAME_ORIGIN:
            # For a change, the origin that already authored the node; for an
            # addition, the origin that authored the parent.
            expected = str(reference.revision_origin or "") if reference else ""
            return bool(expected) and origin == expected
        return origin == author

    def _adoption_allows_deletion(self, node_uuid: str) -> bool:
        """Whether adopting a deletion of this node is permitted throughout.

        The protocol has no partial deletion - _delete_impl cascades to the
        whole subtree - so a deletion may only be adopted when nothing beneath
        it is being held. Anything held below refuses the deletion whole; the
        container stays as a divergence, and unheld nodes beneath it still
        delete through their own per-node events.
        """
        node = self._protocol.index.get(node_uuid)
        if node is None:
            return True
        if self.adoption_metadata(node_uuid).adopt != ADOPT_AUTO:
            return False
        return all(
            self._adoption_allows_deletion(child.uuid)
            for child in node.children
            if not child.deleted
        )

    def _adoption_refusal(
        self,
        topic_uuid: str,
        event_type: str,
        node_uuid: str,
        peer_node: ProtocolNode | None,
        local_node: ProtocolNode | None,
        deciding: bool = False,
        peer_addr: str = "",
    ) -> str | None:
        """Why the declared handling holds this change back, or None.

        `deciding` marks a pass the user asked for. `hold` means "wait for me
        to decide", so it does not block the decision itself; `never` still
        does, because such a node is not offered at all.
        """
        if peer_node is None:
            return None
        if local_node is None:
            # A node not yet held carries no entry of its own. The application
            # is asked to classify it, once; failing that its parent - which
            # this client does hold - answers for it.
            self._classify_unheld_node(topic_uuid, node_uuid, peer_node)
            classified = self._adoption_by_node.get(node_uuid)
            parent = self._protocol.index.get(peer_node.parent_uuid or "")
            if parent is None:
                return "parent not held locally"
            entry = self.adoption_metadata_for_addition(parent.uuid)
            if classified is not None:
                entry = classified.inherit(entry)
            reference = parent
        else:
            entry = self.adoption_metadata(node_uuid)
            reference = local_node
        if entry.adopt == ADOPT_NEVER:
            return "declared never adoptable"
        if entry.adopt != ADOPT_AUTO:
            # Held: nothing has decided yet. Ask the application, inside this
            # same atomic step, so its answer and the adoption it permits
            # cannot come apart.
            verdict = self._resolve_held_node(
                topic_uuid, peer_node, local_node, peer_addr,
            )
            if verdict == RESOLVE_REFUSE:
                return "refused by the application's rule"
            if verdict != RESOLVE_ADOPT and not deciding:
                return "held for a decision"
        if not self._adoption_author_permits(entry, peer_node, reference):
            return "revision origin is not the declared author"
        if (
            local_node is not None
            and peer_node.deleted
            and not local_node.deleted
            and not self._adoption_allows_deletion(node_uuid)
        ):
            return "deletion would remove a node being held"
        return None

    def adoption_metadata_snapshot(self) -> dict[str, Any]:
        """The whole table, for inspection and maintenance."""
        return {
            "nodes": {
                node_uuid: entry.to_dict()
                for node_uuid, entry in sorted(self._adoption_by_node.items())
            },
            "topics": {
                topic_uuid: entry.to_dict()
                for topic_uuid, entry in sorted(self._adoption_by_topic.items())
            },
        }

    # Topic confinement. An adoption authorised for one topic may create,
    # modify or delete local nodes inside that topic and nothing else.
    #
    # It is needed because Core classifies transitions against a topic-scoped
    # comparison (analyze_peer_transitions flattens one topic on each side) and
    # then resolves them against the global index. Without this, a peer placing
    # a node in their copy of a shared topic - reusing the uuid of a node the
    # recipient holds elsewhere, or naming a parent_uuid in another topic -
    # reaches nodes that were never shared with them. See
    # DESIGN_TOPIC_CONFINEMENT.md.
    #
    # The check is on the destination: the local node being changed and the
    # local parent a new node attaches to. Never on the incoming node's type or
    # on the peer's account of where it lives, both of which the peer chooses.

    def _authorised_topic(self, peer_addr: str, node_uuid: str) -> str | None:
        """The topic an adoption of this node is authorised for.

        Read structurally from the peer's cached perspective - the topic
        subtree their copy of this node actually arrived in - rather than from
        a registry, so it is defined for every peer whose data we hold. It is
        safe to take from the peer only because _confined_to_topic then checks
        it against where the destination sits *locally*: a peer claiming their
        node belongs to a shared topic while the local destination lies in
        another one fails that comparison, and that mismatch is exactly what a
        peer-side check alone cannot catch.
        """
        topics = self._peer_topic_roots(peer_addr)
        for topic in topics:
            if self._find_in_tree(topic, node_uuid):
                return topic.uuid
        # Adopting an absence is the case the peer's own copy cannot answer:
        # the node is local and the peer's not having it is the whole point. So
        # fall back to the shared topic that contains it locally - still one
        # the peer demonstrably holds, never an unshared one.
        for topic in topics:
            if self._is_descendant_or_self(topic.uuid, node_uuid):
                return topic.uuid
        return None

    def _peer_topic_roots(self, peer_addr: str) -> list[ProtocolNode]:
        cache = self._peer_perspectives.get(peer_addr)
        if cache is None:
            return []
        if cache.data.get("type") == "peer_cache_root":
            return list(cache.children)
        return [cache]

    def _confined_to_topic(self, topic_uuid: str | None,
                           node_uuid: str) -> bool:
        # Structural containment in the local tree, not a registry lookup: the
        # question is where the write would land, and the answer must not
        # depend on whether a topic was registered.
        return bool(topic_uuid) and self._is_descendant_or_self(
            topic_uuid, node_uuid,
        )

    def _confinement_refusal(
        self,
        peer_addr: str,
        topic_uuid: str | None,
        node_uuid: str,
        peer: ProtocolNode | None,
        local: ProtocolNode | None,
    ) -> str | None:
        """Why this adoption would leave `topic_uuid`, or None if it stays."""
        if not topic_uuid:
            return "no single shared topic authorises this node"
        if local is not None:
            if not self._confined_to_topic(topic_uuid, node_uuid):
                return "node belongs to another topic"
            # A topic root is attached under each session's own local
            # container, so its parent is deliberately not inside the topic and
            # its move is never adopted (see accept_peer_node).
            if node_uuid == topic_uuid:
                return None
            destination = peer.parent_uuid if peer is not None else None
            if (
                destination
                and destination != local.parent_uuid
                and not self._confined_to_topic(topic_uuid, destination)
            ):
                return "move leaves the topic"
            return None
        destination = peer.parent_uuid if peer is not None else None
        if destination and not self._confined_to_topic(topic_uuid, destination):
            return "destination parent belongs to another topic"
        return None

    def _refuse_unconfined(
        self,
        peer_addr: str,
        topic_uuid: str | None,
        node_uuid: str,
        peer: ProtocolNode | None,
        local: ProtocolNode | None,
    ) -> str | None:
        reason = self._confinement_refusal(
            peer_addr, topic_uuid, node_uuid, peer, local,
        )
        if reason is not None:
            self.trace_event(
                "session.confinement_refused",
                peer_addr=peer_addr,
                topic_uuid=topic_uuid,
                node_uuid=node_uuid,
                local_topic_uuid=self._topic_for_node(node_uuid),
                reason=reason,
            )
        return reason

    @_session_locked
    def accept_peer_node(
        self,
        peer_addr: str,
        node_uuid: str,
        adopt_absence: bool = False,
        adopt_descendants: bool = True,
        topic_uuid: str | None = None,
    ) -> SessionResult:
        authorised = topic_uuid or self._authorised_topic(peer_addr, node_uuid)
        if adopt_absence:
            refusal = self._refuse_unconfined(
                peer_addr, authorised, node_uuid, None,
                self._protocol.index.get(node_uuid),
            )
            if refusal:
                return SessionResult("error", reason=refusal)
            return self.delete(node_uuid)
        peer = self.get_cached_peer_subtree(peer_addr, node_uuid)
        if not peer:
            return SessionResult("error", reason="peer node not found")
        local = self._protocol.index.get(node_uuid)
        refusal = self._refuse_unconfined(
            peer_addr, authorised, node_uuid, peer, local,
        )
        if refusal:
            return SessionResult("error", reason=refusal)
        # `hold` is deliberately not enforced here: holding a change means
        # waiting for the user to decide, and this is that decision. `never`
        # is, because a node nobody may adopt is not offered at all.
        if (
            local is not None
            and self.adoption_metadata(node_uuid).adopt == ADOPT_NEVER
        ):
            return SessionResult("error", reason="declared never adoptable")
        if local is not None:
            # The node already exists locally: adopt its OWN fields only (a
            # field-level, base-preserving update). Descendants are separate
            # per-node decisions, so a container adopt never clobbers a card
            # the recipient is keeping. Applies uniformly to cards (leaves)
            # and containers - see ProtocolState.adopt_own_fields. A topic
            # root's parent differs only because each session attaches it under
            # its own local container, so its move must not be adopted.
            is_topic_root = self._topic_for_node(node_uuid) == node_uuid
            result = self._protocol.adopt_own_fields(
                node_uuid, peer, adopt_move=not is_topic_root,
            )
            self.trace_event(
                "protocol.adopt_own_fields",
                node_uuid=node_uuid,
                state_hash=peer.state_hash,
                ok=result.ok,
                reason=result.reason,
            )
            return self._operation_result(result, node_uuid)
        # Brand-new node the peer has and we don't: normally graft the whole
        # subtree. Applications with descendant-specific policy may first
        # adopt only the missing container, then reconcile its children as
        # independent decisions.
        parent_uuid = peer.parent_uuid if peer.parent_uuid in self._protocol.index else None
        if not parent_uuid or parent_uuid not in self._protocol.index:
            return SessionResult("error", reason="local parent not found")
        adopted = peer
        if not adopt_descendants:
            adopted = copy.deepcopy(peer)
            adopted.children = []
            adopted.refresh_hashes()
        return self.adopt_subtree(
            adopted, parent_uuid, remove_descendant_duplicates=True,
        )

    def validate_rollback_target(self, peer_addr: str,
                                 node_uuid: str,
                                 rollback_absence: bool = False) -> SessionResult:
        local = self._protocol.index.get(node_uuid)
        peer = self.get_cached_peer_subtree(peer_addr, node_uuid)
        if not local:
            return SessionResult("error", reason="rollback version not found")
        local_identity = self._local_revision_origin()
        if not local_identity or local.revision_origin != local_identity:
            return SessionResult("error", reason="local version is not mine to roll back")
        if rollback_absence and not peer:
            return SessionResult("ok", value=None)
        if not peer:
            return SessionResult("error", reason="rollback version not found")
        if peer.revision_origin != local_identity:
            return SessionResult("error", reason="target is another client's revision")
        if peer.base_hash != local.base_hash:
            return SessionResult("error", reason="target is not from the same revision wave")
        return SessionResult("ok", value=peer)

    @_session_locked
    def rollback_peer_node(self, peer_addr: str,
                           node_uuid: str,
                           rollback_absence: bool = False) -> SessionResult:
        target = self.validate_rollback_target(
            peer_addr, node_uuid, rollback_absence,
        )
        if target.status != "ok":
            return target
        if rollback_absence:
            refusal = self._refuse_unconfined(
                peer_addr,
                self._authorised_topic(peer_addr, node_uuid),
                node_uuid,
                None,
                self._protocol.index.get(node_uuid),
            )
            if refusal:
                return SessionResult("error", reason=refusal)
            return self.delete(node_uuid)
        return self.accept_peer_node(peer_addr, node_uuid)

    @classmethod
    def _last_write_wins_resolution(
        cls,
        local_node: ProtocolNode | None,
        peer_node: ProtocolNode | None,
        policies: tuple[LastWriteWinsPolicy, ...],
    ) -> tuple[LastWriteWinsPolicy, bool, int | None] | None:
        """Return policy, timestamp-only flag, and peer timestamp ordering.

        Ordering is ``1`` when the peer is newer, ``-1`` when local is newer,
        ``0`` for an exact tie, and ``None`` when a declared timestamp cannot
        be interpreted. An applicable but unordered policy deliberately
        blocks the generic classifier: malformed clocks must not silently
        become last-write-wins through some unrelated fallback.
        """

        if local_node is None or peer_node is None:
            return None
        for policy in policies:
            if (
                local_node.data.get("type") != policy.node_type
                or peer_node.data.get("type") != policy.node_type
                or local_node.deleted != peer_node.deleted
                or local_node.weights != peer_node.weights
            ):
                continue
            if (
                not policy.include_parent
                and local_node.parent_uuid != peer_node.parent_uuid
            ):
                continue

            local_data = dict(local_node.data)
            peer_data = dict(peer_node.data)
            local_timestamp = local_data.pop(policy.timestamp_field, None)
            peer_timestamp = peer_data.pop(policy.timestamp_field, None)
            semantic_difference = (
                policy.include_parent
                and local_node.parent_uuid != peer_node.parent_uuid
            )
            for field_name in policy.data_fields:
                local_value = local_data.pop(field_name, None)
                peer_value = peer_data.pop(field_name, None)
                semantic_difference = (
                    semantic_difference or local_value != peer_value
                )
            if local_data != peer_data:
                continue

            timestamp_only = not semantic_difference
            if timestamp_only and not policy.settle_timestamp_only:
                continue
            if local_timestamp in (None, "") and policy.fallback_to_updated_at:
                local_timestamp = local_node.updated_at
            if peer_timestamp in (None, "") and policy.fallback_to_updated_at:
                peer_timestamp = peer_node.updated_at
            try:
                local_clock = cls._absolute_threshold(local_timestamp)
                peer_clock = cls._absolute_threshold(peer_timestamp)
            except (TypeError, ValueError):
                return policy, timestamp_only, None
            if local_clock is None or peer_clock is None:
                return policy, timestamp_only, None
            order = 1 if peer_clock > local_clock else -1 if local_clock > peer_clock else 0
            return policy, timestamp_only, order
        return None

    @_session_locked
    def reconcile_peer_changes(
        self,
        peer_addr: str,
        topic_uuid: str,
        node_is_eligible: Callable[[ProtocolNode, str], bool] | None = None,
        deciding: bool = False,
    ) -> bool:
        # Generic "adopt incoming changes" walk - every app on this protocol
        # wants the same thing (adopt whatever a peer changed for one topic).
        # Applications declare eligibility and optional structured conflict
        # policies. Core owns their execution, stale-winner rejection and
        # adoption; shallow-vs-graft is decided by accept_peer_node.
        node_is_eligible = node_is_eligible or (lambda node, event_type: True)

        peer_topic = self.get_cached_peer_subtree(peer_addr, topic_uuid)
        if not peer_topic:
            self.trace_event("session.reconcile_skip", reason="no_cached_subtree",
                              peer_addr=peer_addr, topic_uuid=topic_uuid)
            return False
        local_topic = self._protocol.index.get(topic_uuid)
        if not local_topic:
            self.trace_event("session.reconcile_skip", reason="no_local_topic",
                              peer_addr=peer_addr, topic_uuid=topic_uuid)
            return False
        if peer_topic.state_hash == local_topic.state_hash:
            self.trace_event("session.reconcile_skip", reason="hashes_equal",
                              peer_addr=peer_addr, topic_uuid=topic_uuid)
            return False

        peer_events = self.analyze_peer_transitions(peer_addr, topic_uuid)
        self.trace_event(
            "session.reconcile_peer_events",
            peer_addr=peer_addr,
            topic_uuid=topic_uuid,
            events=[{"type": e["type"], "node_uuid": e.get("node_uuid")} for e in peer_events],
        )
        if not any(event["type"] != "in_agreement" for event in peer_events):
            self.trace_event("session.reconcile_skip", reason="all_in_agreement",
                              peer_addr=peer_addr, topic_uuid=topic_uuid)
            return False

        self.trace_event(
            "session.reconcile_start",
            peer_addr=peer_addr,
            topic_uuid=topic_uuid,
            local_state_hash=local_topic.state_hash,
        )

        reconciliation_policies = self._reconciliation_by_topic.get(
            topic_uuid, (),
        )
        # Reconciliation is always per node. There is deliberately no
        # wholesale-subtree replace: with node_hash classification the topic
        # root's own event reflects only its own fields, so it can't safely
        # decide to overwrite an unrelated local descendant change.
        # Parents before children. An addition is adopted shallowly, so each
        # level is judged by its own parent's entry - which only works if the
        # parent exists by the time its children are considered.
        # analyze_peer_transitions returns events uuid-sorted, so impose the
        # order here rather than relying on a wholesale graft to carry
        # descendants in.
        depth = {
            node.uuid: index
            for index, node in enumerate(self._breadth_first(peer_topic))
        }
        peer_events = sorted(
            peer_events,
            key=lambda event: depth.get(event["node_uuid"], len(depth)),
        )
        changed = False
        self._reconciling_topics.add(topic_uuid)
        try:
            for event in peer_events:
                peer_node = self.get_cached_peer_subtree(peer_addr, event["node_uuid"])
                local_node = self._protocol.index.get(event["node_uuid"])
                reference_node = local_node or peer_node
                if not reference_node:
                    continue
                settling_only = False
                lww = self._last_write_wins_resolution(
                    local_node, peer_node, reconciliation_policies,
                )
                if lww is not None:
                    policy, timestamp_only, peer_order = lww
                    self.trace_event(
                        "session.reconcile_policy",
                        peer_addr=peer_addr,
                        topic_uuid=topic_uuid,
                        node_uuid=event["node_uuid"],
                        event_type=event["type"],
                        policy=policy.to_dict(),
                        timestamp_only=timestamp_only,
                        winner=(
                            "peer" if peer_order == 1
                            else "local" if peer_order == -1
                            else "tie" if peer_order == 0
                            else "unresolved"
                        ),
                    )
                    # Timestamp-only differences carry no application meaning.
                    # Settling them is normalization, not adoption policy. A real
                    # semantic difference still passes through the application's
                    # explicit eligibility decision - and through declared
                    # handling, which settling likewise bypasses: converging two
                    # copies of the same value decides nothing to hold back.
                    settling_only = timestamp_only
                    if peer_order != 1 or (
                        not timestamp_only
                        and not node_is_eligible(reference_node, event["type"])
                    ):
                        continue
                else:
                    if event["type"] not in (
                        "peer_made_changes", "local_missing_node",
                    ):
                        continue
                    if not node_is_eligible(reference_node, event["type"]):
                        continue
                if not settling_only:
                    refusal = self._adoption_refusal(
                        topic_uuid, event["type"], event["node_uuid"],
                        peer_node, local_node, deciding=deciding,
                        peer_addr=peer_addr,
                    )
                    if refusal:
                        self.trace_event(
                            "session.adoption_held",
                            peer_addr=peer_addr,
                            topic_uuid=topic_uuid,
                            node_uuid=event["node_uuid"],
                            event_type=event["type"],
                            reason=refusal,
                        )
                        continue
                self.trace_event(
                    "session.reconcile_node",
                    peer_addr=peer_addr,
                    topic_uuid=topic_uuid,
                    node_uuid=event["node_uuid"],
                    event_type=event["type"],
                    peer_state_hash=event.get("peer_state_hash"),
                )
                # accept_peer_node adopts an existing node's own fields (shallow,
                # so a container change never drags in a filtered-out descendant)
                # and grafts a brand-new node's whole subtree - the event type
                # already tells the two apart. An addition is always shallow:
                # each descendant is a separate decision under its own parent's
                # entry, so grafting the subtree would decide them all at once.
                result = self.accept_peer_node(
                    peer_addr, event["node_uuid"], topic_uuid=topic_uuid,
                    adopt_descendants=False,
                )
                changed = changed or result.status == "ok"
        finally:
            self._reconciling_topics.discard(topic_uuid)
        self.trace_event("session.reconcile_done", peer_addr=peer_addr,
                          topic_uuid=topic_uuid, changed=changed)
        return changed

    @_session_locked
    def adopt_sibling_topic(self, peer_addr: str,
                            topic_uuid: str) -> SessionResult:
        """Take another client of this same user's version of one topic, whole.

        Deliberately unlike reconcile_peer_changes, which is per node because
        peer reconciliation is *selective* - one adopts a peer's card and
        declines their column deletion, so every node needs its own verdict.
        Between one person's own clients there is nothing to select: the
        decision was made once, for the topic, by the person who was asked
        (DESIGN_MULTI_CLIENT_PAIRING.md 4.3). So every difference resolves the
        same way, including the two reconcile_peer_changes leaves alone -
        nodes only this side still has, and nodes this side changed.

        Nodes the sibling no longer has are deleted here. Leaving them would
        produce a state that is *nearly* the sibling's, which is worse than
        either version: nobody chose it and nobody can reason about it.
        """
        peer_topic = self.get_cached_peer_subtree(peer_addr, topic_uuid)
        if not peer_topic:
            return SessionResult("error", reason="no sibling version cached")
        local_topic = self._protocol.index.get(topic_uuid)
        if not local_topic:
            return SessionResult("error", reason="topic not found")
        if peer_topic.state_hash == local_topic.state_hash:
            return SessionResult("ok", value=False)

        changed = False
        # Parents before children: a node the sibling has and this client does
        # not can only be created once its parent exists.
        for node in self._breadth_first(peer_topic):
            result = self.accept_peer_node(
                peer_addr,
                node.uuid,
                adopt_descendants=node.uuid not in self._protocol.index,
                topic_uuid=topic_uuid,
            )
            changed = changed or result.status == "ok"

        peer_uuids = {node.uuid for node in self._breadth_first(peer_topic)}
        # Shallowest first, and skipping anything already removed: deleting a
        # node takes its descendants with it, so the deeper entries of a
        # removed subtree are gone before the loop reaches them.
        for node in self._breadth_first(local_topic):
            if node.uuid in peer_uuids or node.uuid == topic_uuid:
                continue
            if node.uuid not in self._protocol.index:
                continue
            result = self.delete(node.uuid)
            changed = changed or result.status == "ok"

        self.trace_event(
            "session.sibling_topic_adopted",
            peer_addr=peer_addr,
            topic_uuid=topic_uuid,
            changed=changed,
        )
        return SessionResult(
            "ok",
            value=changed,
        )

    @staticmethod
    def _breadth_first(root: ProtocolNode) -> list[ProtocolNode]:
        ordered = []
        pending = [root]
        while pending:
            node = pending.pop(0)
            ordered.append(node)
            pending.extend(node.children)
        return ordered

    @_session_locked
    def remove_subtree_uuids(self, root_uuid: str, uuids: set[str]) -> SessionResult:
        result = self._protocol.remove_subtree_uuids(root_uuid, uuids)
        return self._operation_result(result, root_uuid)

    @_session_locked
    def prune_deleted_nodes(self) -> None:
        deleted_uuids = self._collect_deleted_uuids(self._protocol.root)
        if not deleted_uuids:
            return
        resolved = set()
        for node_uuid in sorted(deleted_uuids):
            topic_uuid = self._topic_for_node(node_uuid)
            peers = self.peers_for_topic(topic_uuid) if topic_uuid else []
            if all(
                self._peer_topic_confirms_deletion(peer, topic_uuid, node_uuid)
                for peer in peers
            ):
                resolved.add(node_uuid)
        if not resolved:
            return
        self._protocol.remove_subtree_uuids(self._protocol.root.uuid, resolved)
        for node_uuid in resolved:
            self.trace_event(
                "session.deleted_node_pruned",
                node_uuid=node_uuid,
            )

    @staticmethod
    def _collect_deleted_uuids(node: ProtocolNode) -> set[str]:
        out = set()
        if node.deleted:
            out.add(node.uuid)
        for child in node.children:
            out.update(Session._collect_deleted_uuids(child))
        return out

    @_session_locked
    def get_node(self, node_uuid: str) -> ProtocolNode | None:
        node = self._protocol.index.get(node_uuid)
        return self._snapshot_node(node) if node else None

    @_session_locked
    def get_subtree(self, node_uuid: str) -> dict | None:
        node = self._protocol.index.get(node_uuid)
        if not node:
            return None
        return protocol_tree_envelope(node)

    @_session_locked
    def get_network_info(self) -> dict:
        # No health or retry state here any more. Reachability was a fact
        # about a direct connection; a channel that publishes into a slot
        # and reads back has nothing of the kind to report, and the one
        # thing there is to say - whether a peer's heartbeat is recent -
        # belongs to the channel and is added by ChannelManager.network_info.
        return {
            "address": self.address,
            "root_uuid": self._protocol.root.uuid,
            "root_content_hash": self._protocol.root.content_hash,
            "root_state_hash": self._protocol.root.state_hash,
            # Siblings are excluded throughout: this view is "who else is on
            # this topic", and another client of mine is not someone else.
            "peer_addresses": sorted(
                addr for addr in self._peer_perspectives
                if not self.is_sibling_address(addr)
            ),
            "topic_uuid": self.active_topic_uuid,
            "topic_uuids": sorted(self._active_topic_uuids),
            "peers": {
                addr: {
                    "content_hash": tree.content_hash,
                    "state_hash": tree.state_hash,
                    "root_uuid": tree.uuid,
                    "topic_uuids": sorted(self._peer_topic_sets.get(addr) or []),
                    "topic_channels": dict(sorted(
                        self.peer_topic_channel.get(addr, {}).items()
                    )),
                }
                for addr, tree in self._peer_perspectives.items()
                if not self.is_sibling_address(addr)
            },
        }

    # Internals

    def _operation_result(self, result, changed_uuid: str | None) -> SessionResult:
        if not result.ok:
            return SessionResult("error", reason=result.reason)
        return SessionResult("ok", value=True)

    def trace_event(self, kind: str, *, trace_level: str = "events",
                    **fields: Any) -> None:
        self.trace.event(
            kind, required_level=trace_level, **fields,
        )

    def _topic_for_node(self, node_uuid: str) -> str | None:
        topic_uuids = set(self._active_topic_uuids)
        for topics in self._peer_topic_sets.values():
            topic_uuids.update(topics)
        for topic_uuid in sorted(topic_uuids):
            if self._is_descendant_or_self(topic_uuid, node_uuid):
                return topic_uuid
        return None

    def _peer_topic_confirms_deletion(self, peer_addr: str,
                                      topic_uuid: str,
                                      node_uuid: str) -> bool:
        cache = self._peer_perspectives.get(peer_addr)
        if not cache:
            return False
        topic = self._find_in_tree(cache, topic_uuid)
        if not topic:
            return False
        node = self._find_in_tree(topic, node_uuid)
        if node is None:
            return True
        return bool(node.deleted)

    def _is_descendant_or_self(self, root_uuid: str, node_uuid: str) -> bool:
        root = self._protocol.index.get(root_uuid)
        return bool(root and self._find_in_tree(root, node_uuid))

    def _remove_peer_topic(self, peer_addr: str | None, topic_uuid: str) -> None:
        if not peer_addr:
            return
        topics = self._peer_topic_sets.get(peer_addr)
        if topics is not None:
            topics.discard(topic_uuid)
            if not topics:
                self._peer_topic_sets.pop(peer_addr, None)
        self.unbind_peer_topic_channel(peer_addr, topic_uuid)
        if not self._peer_topic_sets.get(peer_addr):
            # Last topic gone - nothing left to track this peer for.
            self.remove_peer(peer_addr)

    @_session_locked
    def remove_peer(self, peer_addr: str) -> None:
        # The single per-peer teardown: every path that stops tracking a
        # peer (reconnect superseding an old address, the last-topic case
        # above) goes through here. They used to each pop their own subset,
        # and the subsets had drifted apart - which is how stale routing
        # entries survived a departure.
        #
        # peer_identity_key is deliberately NOT cleared: it's knowledge
        # ("this address belongs to identity X"), not registration, and it
        # stays true after teardown.
        self._peer_topic_sets.pop(peer_addr, None)
        self._peer_perspectives.pop(peer_addr, None)
        for key in tuple(self._perspective_observations):
            if key[0] == peer_addr:
                self._perspective_observations.pop(key, None)
        self.peer_topic_channel.pop(peer_addr, None)

    @_session_locked
    def forget_peer_address(self, peer_addr: str) -> None:
        """Remove an address that this client now publishes as itself.

        Ordinary peer teardown keeps the identity registry because the fact
        remains useful. Pairing is different: once a relay address becomes
        our own publication slot, retaining its former peer identity makes
        Core resolve our own slot as another person forever.
        """
        self.remove_peer(peer_addr)
        self._peer_identity_key.pop(peer_addr, None)
        self.peer_observed_node_revisions.pop(peer_addr, None)

    def remove_peer_topics(
        self, peer_addr: str, topic_uuids: list[str] | set[str] | tuple[str, ...],
    ) -> None:
        """Remove only the named peer/topic relationships."""
        for topic_uuid in sorted(set(topic_uuids)):
            self._remove_peer_topic(peer_addr, topic_uuid)

    @staticmethod
    def _snapshot_node(node: ProtocolNode) -> ProtocolNode:
        return ProtocolNode.from_dict(node.to_dict())


    @staticmethod
    def _peer_cache_root(peer_addr: str) -> ProtocolNode:
        root = ProtocolNode({"type": "peer_cache_root", "label": peer_addr})
        root.uuid = f"peer-cache:{peer_addr}"
        root.refresh_hashes()
        return root

    def _other_perspectives_uuid(self) -> str:
        for child in self._protocol.root.children:
            if (child.data.get("type") == "folder"
                    and child.data.get("name") == "other_perspectives"):
                return child.uuid
        created = self._protocol.create_child(
            self._protocol.root.uuid,
            {"type": "folder", "name": "other_perspectives"},
            {},
        )
        return created.value.uuid

    def _analyze_transition_node(self, peer_addr: str,
                                 local_node: ProtocolNode | None,
                                 peer_node: ProtocolNode | None,
                                 is_topic_root: bool = False) -> dict:
        if not local_node:
            # A node that only the peer still has, and only as a tombstone,
            # isn't something to adopt - both sides already agree there's
            # nothing live here. Without this, a deleted node that has been
            # pruned locally keeps reappearing as "missing" every time the
            # peer's cache is compared, so auto-adopt re-materializes the
            # tombstone only for the next prune pass to remove it again -
            # an endless adopt/prune churn.
            if peer_node.deleted:
                return self._transition_event("in_agreement", peer_addr, None, peer_node)
            return self._transition_event("local_missing_node", peer_addr, None, peer_node)
        if not peer_node:
            if local_node.deleted:
                return self._transition_event("in_agreement", peer_addr, local_node, None)
            return self._transition_event("peer_missing_node", peer_addr, local_node, None)

        # A topic's own root node is grafted at a different parent in every
        # peer's local tree (see attach_topic) - that's an artifact of how
        # topics are shared, not a move either peer made, so only content is
        # comparable at that level.
        local_identity = self._local_revision_origin()
        peer_identity = self._peer_identity_key.get(peer_addr)
        if is_topic_root:
            event_type = self._classify_content(
                local_node, peer_node, local_identity, peer_identity,
            )
        else:
            event_type = self._classify_node(
                local_node, peer_node, local_identity, peer_identity,
            )
        return self._transition_event(event_type, peer_addr, local_node, peer_node)

    # How much sovereignty to exercise on a topic: adopt a peer's changes
    # automatically, or hold them for a decision. Every application needs the
    # choice, so the policy and its storage are Session's.
    #
    # Only "always" and "never" are universal. An application may offer more
    # by passing its own allowed set - modes judged against an ownership or
    # membership model Core has no concept of. Core stores the string and
    # never interprets an application's extra modes.
    AUTO_ADOPT_MODES = ("always", "never")

    def auto_adopt_mode(self, topic_uuid: str, default: str = "always") -> str:
        stored = self._app_metadata.get("auto_adopt_by_topic", {})
        value = stored.get(topic_uuid) if isinstance(stored, dict) else None
        return value if isinstance(value, str) and value else default

    def set_auto_adopt_mode(self, topic_uuid: str, mode: str,
                            allowed: tuple[str, ...] | None = None) -> SessionResult:
        permitted = allowed or self.AUTO_ADOPT_MODES
        if mode not in permitted:
            return SessionResult("error", reason=f"unknown auto-adopt mode: {mode}")
        stored = self._app_metadata.setdefault("auto_adopt_by_topic", {})
        if not isinstance(stored, dict):
            stored = {}
            self._app_metadata["auto_adopt_by_topic"] = stored
        stored[topic_uuid] = mode
        return SessionResult("ok", value=mode)

    # An agenda is what a topic's participants want to talk about, merged
    # across everyone discussing it. That is a collaboration primitive, not a
    # property of boards, and it needs no new storage: an agenda item is
    # already a child of the topic root, and every application's topic is a
    # root. Only the originator may edit or remove their own item; everyone
    # sees the merged list.
    AGENDA_PRIORITIES = ("high", "medium", "low")
    # Fractional-order reordering, generic over node type. A moved node gets an
    # "order" value midway between its new neighbours, so a single sibling
    # moves without renumbering the rest. Nodes without an explicit order fall
    # back to their creation position, so the scheme works before anything has
    # ever been moved. Agenda items, agreement sections, and agreement clauses
    # all share this.
    def _ordered_children(self, parent_uuid: str, node_type: str) -> list[ProtocolNode]:
        parent = self._protocol.index.get(parent_uuid)
        if parent is None:
            return []
        items = sorted(
            [
                child for child in parent.live_children()
                if child.data.get("type") == node_type
            ],
            key=lambda node: node.created_at,
        )
        creation_index = {node.uuid: index for index, node in enumerate(items)}
        return sorted(
            items,
            key=lambda node: (
                self._child_order(node, creation_index[node.uuid]),
                node.created_at,
            ),
        )

    @staticmethod
    def _child_order(node: ProtocolNode, fallback: float) -> float:
        value = node.data.get("order")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return fallback

    def next_child_order(self, parent_uuid: str, node_type: str) -> float:
        """The order value that appends a new child after every existing one."""
        existing = self._ordered_children(parent_uuid, node_type)
        if not existing:
            return 0.0
        return max(
            self._child_order(node, index)
            for index, node in enumerate(existing)
        ) + 1.0

    def move_child_to_index(self, node_uuid: str, index: int) -> SessionResult:
        node = self._protocol.index.get(node_uuid)
        if node is None:
            return SessionResult("error", reason="node not found")
        ordered = self._ordered_children(
            node.parent_uuid, node.data.get("type"),
        )
        effective_order = {
            item.uuid: self._child_order(item, position)
            for position, item in enumerate(ordered)
        }
        siblings = [item for item in ordered if item.uuid != node.uuid]
        bounded = max(0, min(int(index), len(siblings)))
        low = effective_order[siblings[bounded - 1].uuid] if bounded > 0 else None
        high = effective_order[siblings[bounded].uuid] if bounded < len(siblings) else None
        if low is None and high is None:
            order = 0.0
        elif low is None:
            order = high - 1.0
        elif high is None:
            order = low + 1.0
        elif high - low >= self.ORDER_GAP_EPSILON:
            order = (low + high) / 2.0
        else:
            # Two peers appending concurrently each pick max+1, so equal
            # neighbouring orders are normal rather than corrupt. No value
            # sorts strictly between them, and the created_at tiebreak would
            # then silently place the node somewhere else while still
            # reporting success - so state the whole arrangement instead.
            return self._renumber_children(siblings, bounded, node)
        data = dict(node.data)
        data["order"] = order
        return self.modify(node.uuid, data, node.weights)

    @_session_locked
    def move_child_to_parent_index(
        self, node_uuid: str, parent_uuid: str, index: int,
    ) -> SessionResult:
        """Move a child between parents and place it in fractional order."""
        node = self._protocol.index.get(node_uuid)
        parent = self._protocol.index.get(parent_uuid)
        if node is None:
            return SessionResult("error", reason="node not found")
        if parent is None:
            return SessionResult("error", reason="destination not found")
        effects = []
        if node.parent_uuid != parent_uuid:
            moved = self.move_child(node_uuid, parent_uuid)
            if moved.status != "ok":
                return moved
            effects.extend(moved.effects)
        placed = self.move_child_to_index(node_uuid, index)
        if placed.status != "ok":
            return placed
        effects.extend(placed.effects)
        return SessionResult("ok", value=node_uuid, effects=effects)

    def _renumber_children(self, siblings: list[ProtocolNode], index: int,
                           node: ProtocolNode) -> SessionResult:
        """Write the requested arrangement out as explicit sequential orders."""
        arranged = [*siblings[:index], node, *siblings[index:]]
        effects = []
        for position, item in enumerate(arranged):
            if item.data.get("order") == float(position):
                continue
            data = dict(item.data)
            data["order"] = float(position)
            result = self.modify(item.uuid, data, item.weights)
            if result.status != "ok":
                return result
            effects.extend(result.effects)
        return SessionResult("ok", value=node.uuid, effects=effects)

    def agenda_items(self, topic_uuid: str) -> list[ProtocolNode]:
        """Agenda records stored in this client's own perspective."""
        identity = self.identity
        identity_key = str(identity.data.get("identity_key") or "")
        return [
            item for item in self._ordered_children(topic_uuid, "agenda_item")
            if (
                item.data.get("author") == identity.uuid
                and item.revision_origin == identity_key
            )
        ]

    @_session_locked
    def project_nodes(
        self,
        topic_uuid: str,
        node_type: str,
        *,
        included_addresses: set[str] | None = None,
        max_age_seconds: float | None = (
            DEFAULT_AGENDA_PERSPECTIVE_MAX_AGE_SECONDS
        ),
        not_before: str | float | datetime | None = None,
    ) -> list[ProjectedNode]:
        """Project verified records without adopting them.

        Core reports and filters factual time information supplied by the
        caller. It assigns no universal meaning to "current" beyond the
        default staleness window, which an explicit ``None`` removes.
        """
        threshold = self._absolute_threshold(not_before)
        local_identity = self.identity
        local_key = str(local_identity.data.get("identity_key") or "")
        candidates: dict[str, list[tuple[ProtocolNode, PerspectiveSource]]] = {}

        local_topic = self._protocol.index.get(topic_uuid)
        if local_topic is not None:
            source = PerspectiveSource(
                identity_uuid=local_identity.uuid,
                identity_key=local_key,
                addresses=(self.address,),
                local=True,
                age_seconds=0.0,
                observed_at=None,
                source_timestamp=None,
                channel_kind=None,
            )
            self._collect_projected_candidates(
                local_topic, node_type, source, candidates,
            )

        permitted = included_addresses
        for address in self.peer_addresses(topic_uuid):
            if permitted is not None and address not in permitted:
                continue
            tree = self._peer_perspectives.get(address)
            topic = self._find_in_tree(tree, topic_uuid) if tree else None
            if topic is None:
                continue
            identity_key = str(self._peer_identity_key.get(address) or "")
            identity = (
                self.find_peer_identity(identity_key) if identity_key else None
            ) or self.peer_identity(address)
            if identity is None:
                continue
            identity_key = str(identity.data.get("identity_key") or identity_key)
            if not identity_key:
                continue
            observation = self._perspective_observations.get(
                (address, topic_uuid),
            )
            age = self._perspective_age(observation)
            if max_age_seconds is not None and (
                age is None or age > max(0.0, float(max_age_seconds))
            ):
                continue
            reference_time = self._perspective_reference_time(observation)
            if threshold is not None and (
                reference_time is None or reference_time < threshold
            ):
                continue
            source = PerspectiveSource(
                identity_uuid=identity.uuid,
                identity_key=identity_key,
                addresses=(address,),
                local=False,
                age_seconds=age,
                observed_at=observation.observed_at if observation else None,
                source_timestamp=(
                    observation.source_timestamp if observation else None
                ),
                channel_kind=observation.channel_kind if observation else None,
            )
            self._collect_projected_candidates(
                topic, node_type, source, candidates,
            )

        resolved = [
            self._projected_node_from_candidates(values)
            for _uuid, values in sorted(candidates.items())
        ]
        return [item for item in resolved if not item.node.deleted]

    def agenda_projection(
        self,
        topic_uuid: str,
        *,
        included_addresses: set[str] | None = None,
        max_age_seconds: float | None = (
            DEFAULT_AGENDA_PERSPECTIVE_MAX_AGE_SECONDS
        ),
        not_before: str | float | datetime | None = None,
    ) -> list[ProjectedNode]:
        items = [
            item for item in self.project_nodes(
                topic_uuid,
                "agenda_item",
                included_addresses=included_addresses,
                max_age_seconds=max_age_seconds,
                not_before=not_before,
            )
            if (
                item.data.get("author") == item.perspective.identity_uuid
                and item.node.parent_uuid == topic_uuid
            )
        ]
        return sorted(
            items,
            key=lambda item: (
                self._child_order(item.node, 0.0),
                item.perspective.identity_key,
                item.created_at,
                item.uuid,
            ),
        )

    def _collect_projected_candidates(
        self,
        topic: ProtocolNode,
        node_type: str,
        source: PerspectiveSource,
        candidates: dict[str, list[tuple[ProtocolNode, PerspectiveSource]]],
    ) -> None:
        for node in self._flatten_by_uuid(topic).values():
            if (
                node.data.get("type") != node_type
                or node.revision_origin != source.identity_key
                or self.revision_verification(node) != "valid"
            ):
                continue
            candidates.setdefault(node.uuid, []).append((node, source))

    def _projected_node_from_candidates(
        self, values: list[tuple[ProtocolNode, PerspectiveSource]],
    ) -> ProjectedNode:
        resolved = _resolve_revision_candidates([
            _RevisionCandidate(node, source, True)
            for node, source in values
        ])
        if resolved is None:  # all collected projection candidates are valid
            raise ValueError("projection has no verified revision candidate")
        node = resolved.node
        matching = list(resolved.sources)
        selected = matching[0]
        addresses = tuple(sorted({
            address for source in matching for address in source.addresses
        }))
        source = PerspectiveSource(
            identity_uuid=selected.identity_uuid,
            identity_key=selected.identity_key,
            addresses=addresses,
            local=any(item.local for item in matching),
            age_seconds=min(
                (item.age_seconds for item in matching if item.age_seconds is not None),
                default=None,
            ),
            observed_at=max(
                (item.observed_at for item in matching if item.observed_at),
                default=None,
            ),
            source_timestamp=max(
                (
                    item.source_timestamp for item in matching
                    if item.source_timestamp is not None
                ),
                default=None,
            ),
            channel_kind=next(
                (item.channel_kind for item in matching if item.channel_kind),
                None,
            ),
        )
        return ProjectedNode(
            self._snapshot_node(node), source, resolved.conflict,
        )

    @staticmethod
    def _perspective_age(
        observation: PerspectiveObservation | None,
    ) -> float | None:
        if observation is None:
            return None
        elapsed = max(0.0, time.monotonic() - observation.observed_monotonic)
        return (observation.source_age_seconds or 0.0) + elapsed

    @staticmethod
    def _perspective_reference_time(
        observation: PerspectiveObservation | None,
    ) -> float | None:
        if observation is None:
            return None
        if observation.source_timestamp is not None:
            return observation.source_timestamp
        try:
            return datetime.fromisoformat(observation.observed_at).timestamp()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _absolute_threshold(
        value: str | float | datetime | None,
    ) -> float | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            normalized = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        elif isinstance(value, str):
            normalized = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise ValueError("not_before must be an ISO timestamp or epoch seconds")
        if normalized.tzinfo is None:
            normalized = normalized.replace(tzinfo=timezone.utc)
        return normalized.timestamp()

    def create_agenda_item(
        self,
        topic_uuid: str,
        text: str,
        priority: str | None = None,
        *,
        max_age_seconds: float | None = (
            DEFAULT_AGENDA_PERSPECTIVE_MAX_AGE_SECONDS
        ),
        not_before: str | float | datetime | None = None,
    ) -> SessionResult:
        if self._protocol.index.get(topic_uuid) is None:
            return SessionResult("error", reason="topic not found")
        normalized = str(text or "").strip()
        if not normalized:
            return SessionResult("error", reason="discussion topic text is required")
        return self.create_child(
            topic_uuid,
            {
                "type": "agenda_item",
                "text": normalized,
                "priority": priority if priority in self.AGENDA_PRIORITIES else None,
                "author": self.identity.uuid,
                "order": self._next_agenda_order(
                    topic_uuid,
                    max_age_seconds=max_age_seconds,
                    not_before=not_before,
                ),
            },
            {},
        )

    def delete_agenda_item(self, item_uuid: str) -> SessionResult:
        item = self._agenda_item(item_uuid)
        if item is None:
            return SessionResult("error", reason="agenda item not found")
        if not self._is_local_agenda_item(item):
            return SessionResult(
                "error", reason="only the topic originator can delete it",
            )
        return self.delete(item.uuid)

    def update_agenda_item_text(
        self, item_uuid: str, text: str,
    ) -> SessionResult:
        item = self._agenda_item(item_uuid)
        if item is None:
            return SessionResult("error", reason="agenda item not found")
        if not self._is_local_agenda_item(item):
            return SessionResult(
                "error", reason="only the topic originator can edit it",
            )
        normalized = str(text or "").strip()
        if not normalized:
            return SessionResult("error", reason="agenda text is required")
        data = dict(item.data)
        data["text"] = normalized
        return self.modify(item.uuid, data, item.weights)

    def set_agenda_item_priority(self, item_uuid: str,
                                 priority: str | None) -> SessionResult:
        item = self._agenda_item(item_uuid)
        if item is None:
            return SessionResult("error", reason="agenda item not found")
        if not self._is_local_agenda_item(item):
            return SessionResult(
                "error", reason="only the topic originator can set its priority",
            )
        data = dict(item.data)
        data["priority"] = priority if priority in self.AGENDA_PRIORITIES else None
        return self.modify(item.uuid, data, item.weights)

    def move_agenda_item(
        self,
        item_uuid: str,
        index: int,
        *,
        max_age_seconds: float | None = (
            DEFAULT_AGENDA_PERSPECTIVE_MAX_AGE_SECONDS
        ),
        not_before: str | float | datetime | None = None,
    ) -> SessionResult:
        item = self._agenda_item(item_uuid)
        if item is None:
            return SessionResult("error", reason="agenda item not found")
        if not self._is_local_agenda_item(item):
            return SessionResult(
                "error", reason="only locally authored agenda items can be moved",
            )
        projected = self.agenda_projection(
            item.parent_uuid,
            max_age_seconds=max_age_seconds,
            not_before=not_before,
        )
        siblings = [entry for entry in projected if entry.uuid != item_uuid]
        bounded = max(0, min(int(index), len(siblings)))
        left = bounded
        while left > 0 and siblings[left - 1].perspective.local:
            left -= 1
        right = bounded
        while right < len(siblings) and siblings[right].perspective.local:
            right += 1
        arranged = [
            *siblings[left:bounded],
            ProjectedNode(
                self._snapshot_node(item),
                PerspectiveSource(
                    self.identity.uuid,
                    str(self.identity.data.get("identity_key") or ""),
                    (self.address,), True, 0.0, None, None, None,
                ),
            ),
            *siblings[bounded:right],
        ]
        low = (
            self._child_order(siblings[left - 1].node, 0.0)
            if left > 0 else None
        )
        high = (
            self._child_order(siblings[right].node, 0.0)
            if right < len(siblings) else None
        )
        orders = self._spread_agenda_orders(len(arranged), low, high)
        if orders is None:
            return SessionResult(
                "error", reason="no representable order between surrounding agenda items",
            )
        effects: list[SessionEffect] = []
        for projected_item, order in zip(arranged, orders):
            local = self._protocol.index.get(projected_item.uuid)
            if local is None or not self._is_local_agenda_item(local):
                continue
            data = dict(local.data)
            data["order"] = order
            changed = self.modify(local.uuid, data, local.weights)
            if changed.status != "ok":
                return changed
            effects.extend(changed.effects)
        return SessionResult("ok", value=item_uuid, effects=effects)

    def _next_agenda_order(
        self,
        topic_uuid: str,
        *,
        max_age_seconds: float | None = (
            DEFAULT_AGENDA_PERSPECTIVE_MAX_AGE_SECONDS
        ),
        not_before: str | float | datetime | None = None,
    ) -> float:
        projected = self.agenda_projection(
            topic_uuid,
            max_age_seconds=max_age_seconds,
            not_before=not_before,
        )
        if not projected:
            return 0.0
        return max(
            self._child_order(item.node, index)
            for index, item in enumerate(projected)
        ) + self.AGENDA_ORDER_STRIDE

    def _spread_agenda_orders(
        self, count: int, low: float | None, high: float | None,
    ) -> list[float] | None:
        if count <= 0:
            return []
        if low is None and high is None:
            return [self.AGENDA_ORDER_STRIDE * index for index in range(count)]
        if low is None:
            return [
                high - self.AGENDA_ORDER_STRIDE * (count - index)
                for index in range(count)
            ]
        if high is None:
            return [
                low + self.AGENDA_ORDER_STRIDE * (index + 1)
                for index in range(count)
            ]
        gap = (high - low) / (count + 1)
        if gap <= self.ORDER_GAP_EPSILON:
            return None
        orders = [low + gap * (index + 1) for index in range(count)]
        if not all(low < order < high for order in orders):
            return None
        if len(set(orders)) != len(orders):
            return None
        return orders

    def _is_local_agenda_item(self, item: ProtocolNode) -> bool:
        identity = self.identity
        return (
            item.data.get("type") == "agenda_item"
            and item.data.get("author") == identity.uuid
            and item.revision_origin == identity.data.get("identity_key")
        )

    def _agenda_item(self, item_uuid: str) -> ProtocolNode | None:
        node = self._protocol.index.get(item_uuid)
        if node is None or node.data.get("type") != "agenda_item":
            return None
        return node

    def known_identities(self) -> list[dict]:
        """Every identity this session can currently put a name and picture to.

        Agenda authorship, and anything else that names a participant by
        identity uuid rather than peer address, needs this to render
        generically - identity is Core's, not an application's, and an
        application without a richer user model of its own still needs to
        show *some* name for "who wrote this".
        """
        def describe(
            uuid: str, data: dict, address: str, addresses: list[str],
        ) -> dict:
            attachment = avatar_attachment(data)
            return {
                "uuid": uuid,
                "identity_key": data.get("identity_key") or "",
                "address": address,
                "addresses": addresses,
                "name": data.get("display_name") or "",
                "picture": (
                    f"/api/blob/{attachment['blob_id']}" if attachment
                    else data.get("picture") or ""
                ),
            }

        out = [describe(
            self.identity.uuid, self.identity.data, self.address, [self.address],
        )]
        seen = {self.identity.uuid}
        addrs = (
            set(self._peer_perspectives) | set(self._peer_topic_sets)
        ) - {self.address}
        for addr in sorted(addr for addr in addrs
                           if not self.is_sibling_address(addr)):
            identity_key = self._peer_identity_key.get(addr)
            profile = (
                self.peer_identity(addr)
                or (self.find_peer_identity(identity_key) if identity_key else None)
            )
            if not profile or profile.uuid in seen:
                continue
            seen.add(profile.uuid)
            aliases = (
                [
                    candidate for candidate in sorted(addrs)
                    if self._peer_identity_key.get(candidate) == identity_key
                ]
                if identity_key else [addr]
            )
            out.append(describe(
                profile.uuid, profile.data, addr, aliases or [addr],
            ))
        return out

    @_session_locked
    def identity_key_for_actor(self, actor_uuid: str) -> str | None:
        """Resolve a public-profile Actor UUID to its signing identity key."""
        normalized = str(actor_uuid or "").strip()
        if not normalized:
            return None
        local = self._find_identity_in_tree(self._protocol.root)
        if local is not None and local.uuid == normalized:
            return str(local.data.get("identity_key") or "") or None
        for tree in self._peer_perspectives.values():
            candidate = self._find_in_tree(tree, normalized)
            if self.is_identity_node(candidate):
                return str(candidate.data.get("identity_key") or "") or None
        return None

    def reaction_for_event(self, event: dict) -> str:
        """Which reaction resolves this transition: "adopt" or "rollback".

        Reacting is how a divergence is left behind, so every application
        needs it and none should decide it. The answer is drawn entirely from
        Core vocabulary - revision origins and base hashes - so it belongs
        here rather than being re-derived per application.

        "rollback" when the local side authored the revision the peer is
        answering, so the peer's copy is the stale one; "adopt" otherwise.
        """
        local_identity = self._local_revision_origin()
        local_origin = event.get("local_revision_origin")
        peer_origin = event.get("peer_revision_origin")
        same_local_wave = (
            peer_origin == local_identity
            and event.get("local_base_hash") == event.get("peer_base_hash")
        )
        if (local_identity and local_origin == local_identity
                and (same_local_wave
                     or event.get("type") == "peer_missing_node")):
            return "rollback"
        return "adopt"

    # How loudly each transition should speak when one node carries several.
    # Session decides what the words mean, so Session ranks them; applications
    # that grouped events per node had each copied this table, and the copies
    # had already drifted apart on divergence.
    TRANSITION_PRIORITY = {
        "divergence": 6,
        "peer_made_changes": 4,
        "local_missing_node": 4,
        "local_made_changes": 3,
        "peer_missing_node": 3,
        "in_agreement": 0,
    }

    # Two events can share a relation and differ only in how far each has
    # travelled - one peer has observed my revision, another has not yet.
    # Ranking the stage as well keeps the peer who is actually holding a
    # decision as the node's headline instead of whichever arrived first.
    STAGE_PRIORITY = {
        "conflict": 4,
        "awaiting_me": 3,
        "awaiting_peer": 2,
        "in_flight": 1,
        "settled": 0,
    }

    @classmethod
    def transition_rank(cls, event: dict) -> tuple[int, int]:
        """How loudly one transition speaks, relation first, then stage."""
        return (
            cls.TRANSITION_PRIORITY.get(event.get("type"), 0),
            cls.STAGE_PRIORITY.get(event.get("stage"), 0),
        )

    @staticmethod
    def _same_origin_sequence_order(local_node: ProtocolNode,
                                    peer_node: ProtocolNode) -> str | None:
        """Order two different revisions authored by the same identity.

        Positive logical sequences are authoritative. Sequence zero is the
        migration value for protocol-v1 nodes, so callers may continue into
        the legacy base/timestamp classifier only for that case.
        """
        origin = local_node.revision_origin
        if not origin or origin != peer_node.revision_origin:
            return None
        if local_node.revision_seq > peer_node.revision_seq:
            return "local_made_changes"
        if peer_node.revision_seq > local_node.revision_seq:
            return "peer_made_changes"
        if local_node.revision_seq > 0:
            # One origin/sequence cannot legitimately describe two different
            # semantic revisions.
            return "divergence"
        return None

    @staticmethod
    def _classify_content(local_node: ProtocolNode, peer_node: ProtocolNode,
                          local_identity: str | None = None,
                          peer_identity: str | None = None) -> str:
        if local_node.content_hash == peer_node.content_hash:
            return "in_agreement"
        sequence_order = Session._same_origin_sequence_order(
            local_node, peer_node,
        )
        if sequence_order:
            return sequence_order
        if peer_node.content_hash == local_node.base_hash:
            return "local_made_changes"
        if local_node.content_hash == peer_node.base_hash:
            return "peer_made_changes"
        if (local_node.base_hash == peer_node.base_hash
                and local_node.revision_origin
                == peer_node.revision_origin):
            origin = local_node.revision_origin
            # An unset origin must not classify by identity: `None == None`
            # would otherwise pick a definite side instead of falling through
            # to the recency tiebreak / divergence.
            if origin and origin == local_identity:
                return "local_made_changes"
            if origin and origin == peer_identity:
                return "peer_made_changes"
            if local_node.updated_at > peer_node.updated_at:
                return "local_made_changes"
            if peer_node.updated_at > local_node.updated_at:
                return "peer_made_changes"
        return "divergence"

    @staticmethod
    def _classify_move(local_node: ProtocolNode, peer_node: ProtocolNode,
                       local_identity: str | None = None,
                       peer_identity: str | None = None) -> str:
        if local_node.parent_uuid == peer_node.parent_uuid:
            return "in_agreement"
        sequence_order = Session._same_origin_sequence_order(
            local_node, peer_node,
        )
        if sequence_order:
            return sequence_order
        peer_moved_from_local = local_node.parent_uuid == peer_node.base_parent_uuid
        local_moved_from_peer = peer_node.parent_uuid == local_node.base_parent_uuid
        if peer_moved_from_local and local_moved_from_peer:
            if (local_node.base_parent_uuid == peer_node.base_parent_uuid
                    and local_node.revision_origin
                    == peer_node.revision_origin):
                origin = local_node.revision_origin
                # See _classify_content: an unset origin must not match a
                # None identity and short-circuit the recency tiebreak.
                if origin and origin == local_identity:
                    return "local_made_changes"
                if origin and origin == peer_identity:
                    return "peer_made_changes"
            if peer_node.updated_at > local_node.updated_at:
                return "peer_made_changes"
            if local_node.updated_at > peer_node.updated_at:
                return "local_made_changes"
            return "divergence"
        if peer_moved_from_local:
            return "peer_made_changes"
        if local_moved_from_peer:
            return "local_made_changes"
        return "divergence"

    @staticmethod
    def _classify_node(local_node: ProtocolNode, peer_node: ProtocolNode,
                       local_identity: str | None = None,
                       peer_identity: str | None = None) -> str:
        content = Session._classify_content(
            local_node, peer_node, local_identity, peer_identity,
        )
        move = Session._classify_move(
            local_node, peer_node, local_identity, peer_identity,
        )
        if content == "divergence" or move == "divergence":
            return "divergence"
        if content == move:
            return content
        if content == "in_agreement":
            return move
        if move == "in_agreement":
            return content
        # A semantic state may legitimately return to an earlier hash. In
        # that case both base relations are true and the first matching
        # relation in the per-dimension classifier points the wrong way.
        # Use the other, non-cyclic dimension to order the whole node
        # revision. This is common when a card move also restores an earlier
        # fractional order value.
        content_cycle = (
            peer_node.content_hash == local_node.base_hash
            and local_node.content_hash == peer_node.base_hash
        )
        move_cycle = (
            peer_node.parent_uuid == local_node.base_parent_uuid
            and local_node.parent_uuid == peer_node.base_parent_uuid
        )
        if content_cycle and not move_cycle:
            return move
        if move_cycle and not content_cycle:
            return content
        return "divergence"

    @staticmethod
    def _transition_event(event_type: str, peer_addr: str,
                          local_node: ProtocolNode | None,
                          peer_node: ProtocolNode | None) -> dict:
        node = local_node or peer_node
        local_origin = (
            local_node.revision_origin if local_node else None
        )
        peer_origin = peer_node.revision_origin if peer_node else None
        if event_type in (
            "peer_made_changes", "local_missing_node", "divergence",
        ):
            origin = peer_origin
        elif event_type in ("local_made_changes", "peer_missing_node"):
            origin = local_origin
        else:
            origin = peer_origin or local_origin
        return {
            "type": event_type,
            "peer_addr": peer_addr,
            "node_uuid": node.uuid if node else None,
            "local_state_hash": local_node.state_hash if local_node else None,
            "peer_state_hash": peer_node.state_hash if peer_node else None,
            "local_base_hash": local_node.base_hash if local_node else None,
            "peer_base_hash": peer_node.base_hash if peer_node else None,
            "local_revision_seq": (
                local_node.revision_seq if local_node else None
            ),
            "peer_revision_seq": (
                peer_node.revision_seq if peer_node else None
            ),
            "local_revision": (
                Session.node_revision(local_node) if local_node else None
            ),
            "peer_revision": (
                Session.node_revision(peer_node) if peer_node else None
            ),
            "origin_identity": origin,
            "local_revision_origin": local_origin,
            "peer_revision_origin": peer_origin,
        }

    @staticmethod
    def _stage_transition_event(event: dict) -> dict:
        """Say how far a difference has travelled without changing what it is.

        `type` is the relation between the two versions; `stage` is whose
        turn it is. These used to share one field, which is why the author
        of an uncontested edit saw "divergence" as soon as the peer merely
        observed it, while the peer - the side that actually had a decision
        to make - saw the milder "in transition" for the same fact.
        """
        event_type = event["type"]
        observed = event.get("peer_observed_local_revision") is True
        local_origin = event.get("local_revision_origin")
        peer_origin = event.get("peer_revision_origin")
        competing_origins = bool(
            local_origin and peer_origin and local_origin != peer_origin
        )
        if event_type == "in_agreement":
            stage = "settled"
        elif event_type in ("peer_made_changes", "local_missing_node"):
            stage = "awaiting_me"
        elif event_type in ("local_made_changes", "peer_missing_node"):
            # A peer that has observed this revision and still publishes its
            # own is answering rather than lagging - but it is answering me,
            # so this is my change awaiting a decision, not a conflict.
            stage = "awaiting_peer" if observed else "in_flight"
        elif competing_origins or observed:
            stage = "conflict"
        else:
            # Hashes disagree, but nothing yet says the peer has seen my side.
            stage = "in_flight"
        return {**event, "stage": stage}

    @staticmethod
    def _remove_uuid_from_tree(root: ProtocolNode, uuid: str) -> bool:
        original_len = len(root.children)
        root.children = [child for child in root.children if child.uuid != uuid]
        removed = len(root.children) != original_len
        for child in root.children:
            removed = Session._remove_uuid_from_tree(child, uuid) or removed
        return removed

    @staticmethod
    def _remove_duplicate_subtree_uuids(root: ProtocolNode,
                                        subtree_uuids: set[str],
                                        keep_uuid: str) -> None:
        for uuid in subtree_uuids:
            if uuid != keep_uuid:
                Session._remove_uuid_from_tree(root, uuid)

    @staticmethod
    def _find_in_tree(root: ProtocolNode, uuid: str | None) -> ProtocolNode | None:
        if uuid is None:
            return None
        if root.uuid == uuid:
            return root
        for child in root.children:
            found = Session._find_in_tree(child, uuid)
            if found:
                return found
        return None

    @staticmethod
    def _refresh_tree_hashes(node: ProtocolNode) -> None:
        for child in node.children:
            Session._refresh_tree_hashes(child)
        node.refresh_hashes()
