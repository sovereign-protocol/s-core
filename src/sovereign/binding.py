"""Capability-scoped access to Core-owned generic scalar bindings."""

from __future__ import annotations

import copy
import hmac
from dataclasses import dataclass
from typing import Any, Iterable

from .session import Session, SessionResult


@dataclass(frozen=True)
class BindingCapability:
    token: str
    origin: str
    topic_uuid: str
    node_uuid: str
    fields: frozenset[str]
    operations: frozenset[str]
    adoption: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BindingCapability":
        token = str(value.get("token") or "").strip()
        origin = str(value.get("origin") or "").strip().rstrip("/")
        topic_uuid = str(value.get("topic_uuid") or "").strip()
        node_uuid = str(value.get("node_uuid") or "").strip()
        fields = frozenset(str(item).strip() for item in value.get("fields") or [])
        operations = frozenset(
            str(item).strip() for item in value.get("operations") or ["read"]
        )
        adoption = str(value.get("adoption") or "hold").strip()
        if not token or not origin or not topic_uuid or not node_uuid or not fields:
            raise ValueError(
                "binding capability requires token, origin, topic_uuid, node_uuid, and fields"
            )
        if "type" in fields:
            raise ValueError("binding capability cannot expose the node type")
        if not operations <= {"read", "write", "react"}:
            raise ValueError("binding capability contains an unknown operation")
        if adoption not in {"auto", "hold"}:
            raise ValueError("binding adoption must be 'auto' or 'hold'")
        return cls(
            token, origin, topic_uuid, node_uuid, fields, operations, adoption,
        )


class GenericBindingService:
    """Read and mutate only nodes owned by Core's generic binding topic."""

    def __init__(self, session: Session, capabilities: Iterable[dict] = ()):
        self.session = session
        self._capabilities = tuple(
            BindingCapability.from_dict(dict(item)) for item in capabilities
        )
        self._adoption_by_target: dict[tuple[str, str], str] = {}
        for capability in self._capabilities:
            target = (capability.topic_uuid, capability.node_uuid)
            previous = self._adoption_by_target.get(target)
            if previous is not None and previous != capability.adoption:
                raise ValueError(
                    "binding capabilities for one node must use one adoption setting"
                )
            self._adoption_by_target[target] = capability.adoption
        self._configured_targets: set[tuple[str, str]] = set()
        for target in self._adoption_by_target:
            topic_uuid, node_uuid = target
            local_exists = bool(
                self.session.get_node(topic_uuid)
                or self.session.get_node(node_uuid)
            )
            if local_exists and not self.session.is_generic_binding_node(
                topic_uuid, node_uuid,
            ):
                raise ValueError("binding adoption target is not Core-owned")
            self._configure_adoption(target)

    def _configure_adoption(self, target: tuple[str, str]) -> bool:
        if target in self._configured_targets:
            return True
        topic_uuid, node_uuid = target
        owned = self.session.is_generic_binding_node(topic_uuid, node_uuid)
        if not owned:
            owned = any(
                self.session.is_generic_binding_node(
                    topic_uuid, node_uuid, peer_addr,
                )
                for peer_addr in self.session.peer_addresses(topic_uuid)
            )
        if not owned:
            return False
        result = self.session.set_adoption_metadata(
            node_uuid, adopt=self._adoption_by_target[target],
        )
        if result.status != "ok":
            raise ValueError(result.reason or "invalid binding adoption setting")
        self._configured_targets.add(target)
        return True

    def reconcile_adoption(self) -> bool:
        """Apply configured automatic decisions after a peer cache update."""
        changed = False
        topics = set()
        for target, adoption in self._adoption_by_target.items():
            if adoption == "auto" and self._configure_adoption(target):
                topics.add(target[0])
        for topic_uuid in sorted(topics):
            changed = self.session.reapply_adoption(topic_uuid) or changed
        return changed

    def capability_for(
        self,
        token: str,
        origin: str,
        topic_uuid: str,
        node_uuid: str,
        operation: str,
        field: str | None = None,
    ) -> BindingCapability | None:
        normalized_origin = str(origin or "").strip().rstrip("/")
        for capability in self._capabilities:
            if not hmac.compare_digest(capability.token, str(token or "")):
                continue
            if (
                capability.origin != normalized_origin
                or capability.topic_uuid != str(topic_uuid or "")
                or capability.node_uuid != str(node_uuid or "")
                or operation not in capability.operations
                or (field is not None and field not in capability.fields)
            ):
                continue
            return capability
        return None

    def origin_is_known(self, origin: str) -> bool:
        normalized = str(origin or "").strip().rstrip("/")
        return any(item.origin == normalized for item in self._capabilities)

    def view(self, topic_uuid: str, node_uuid: str, field: str) -> dict:
        peer_addresses = self.session.peer_addresses(topic_uuid)
        if not (
            self.session.is_generic_binding_node(topic_uuid, node_uuid)
            or any(
                self.session.is_generic_binding_node(topic_uuid, node_uuid, peer_addr)
                for peer_addr in peer_addresses
            )
        ):
            return {"status": "error", "reason": "binding target is not Core-owned"}
        node = self.session.get_node(node_uuid)
        events = []
        for peer_addr in peer_addresses:
            events.extend(
                event
                for event in self.session.analyze_peer_transitions(
                    peer_addr, topic_uuid,
                )
                if event.get("node_uuid") == node_uuid
            )
        transition = self.session.group_transition_events(events).get(node_uuid)
        perspectives = []
        for event in (transition or {}).get("events", []):
            peer_addr = event.get("peer_addr")
            peer = self.session.get_cached_peer_subtree(peer_addr, node_uuid)
            perspectives.append({
                "peer_addr": peer_addr,
                "value": copy.deepcopy(peer.data.get(field)) if peer else None,
                "absent": peer is None or peer.deleted,
            })
        return {
            "status": "ok",
            "topic_uuid": topic_uuid,
            "node_uuid": node_uuid,
            "field": field,
            "value": copy.deepcopy(node.data.get(field)) if node else None,
            "content_hash": node.content_hash if node else "",
            "transition": transition,
            # The effective, inherited policy is part of the projection. A
            # generic client should not have to reproduce Session's adoption
            # inheritance merely to explain how this field will behave.
            "adoption_policy": self.session.adoption_metadata(
                node_uuid,
            ).to_dict(),
            "perspectives": perspectives,
            "known_identities": self.session.known_identities(),
            "revision": self.session.current_view_revision(),
        }

    def write(
        self, topic_uuid: str, node_uuid: str, field: str, value: Any,
        expected_content_hash: str | None = None,
    ) -> SessionResult:
        if not self.session.is_generic_binding_node(topic_uuid, node_uuid):
            return SessionResult(
                "error", reason="binding target is not Core-owned",
            )
        if field == "type" or isinstance(value, (dict, list)):
            return SessionResult("error", reason="binding value must be scalar")
        node = self.session.get_node(node_uuid)
        if expected_content_hash and node.content_hash != expected_content_hash:
            return SessionResult("error", reason="binding changed before commit")
        return self.session.modify(
            node_uuid, {**node.data, field: copy.deepcopy(value)}, node.weights,
        )

    def react(
        self, topic_uuid: str, node_uuid: str, source_addr: str,
        reaction: str, absent: bool, allowed_fields: frozenset[str],
    ) -> SessionResult:
        if not self.session.is_generic_binding_node(
            topic_uuid, node_uuid, source_addr,
        ):
            return SessionResult(
                "error", reason="binding target is not Core-owned",
            )
        allowed_data = {"type", *allowed_fields}
        local = self.session.get_node(node_uuid)
        peer = self.session.get_cached_peer_subtree(source_addr, node_uuid)
        if any(
            node and not set(node.data) <= allowed_data
            for node in (local, peer)
        ):
            return SessionResult(
                "error", reason="reaction exceeds binding field capability",
            )
        events = [
            event
            for event in self.session.analyze_peer_transitions(
                source_addr, topic_uuid,
            )
            if event.get("node_uuid") == node_uuid
        ]
        matching = next((
            event for event in events
            if self.session.reaction_for_event(event) == reaction
            and (event.get("type") == "peer_missing_node") == bool(absent)
        ), None)
        if matching is None:
            return SessionResult("error", reason="reaction is not available")
        if reaction == "adopt":
            return self.session.accept_peer_node(source_addr, node_uuid, absent)
        if reaction == "rollback":
            return self.session.rollback_peer_node(source_addr, node_uuid, absent)
        return SessionResult("error", reason="unknown reaction")
