"""Application-neutral registry for shared protocol topic roots.

Applications register the root node types they own, how to enumerate their
local topics, and how an invited topic is mounted into the local tree. Channel
implementations consume only this contract and never import an application.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .protocol import ProtocolNode


@dataclass(frozen=True)
class ApplicationRegistration:
    """What an application says about the topics it owns.

    The last three fields are how one of its topics is *made*. They are
    optional, and an application that leaves them out simply cannot have one
    made from anywhere else - which is the honest answer for an aggregate
    that owns no topics of its own.

    They are here because three applications had each grown a table of how
    to create another application's topics, differing in what they could
    make and in what they let you start from. Every one of those tables was
    restating what the owning application already knew.

    `topic_noun`      what one of these is called to a person: "Initiative"
    `template_required` a process with no workflow is not a process
    `list_templates`  what a new one can start from, as {value, name} and an
                      optional `description`
    `create_topic`    (title, template, snapshot) -> SessionResult naming the
                      new topic. All three ways of starting are its own: from
                      nothing, from a template it listed, or from a snapshot
                      document it exported.
    """

    application_id: str
    root_types: frozenset[str]
    list_topics: Callable[[], Iterable[str | ProtocolNode]]
    accept_invitation: Callable[[ProtocolNode], Any]
    assignment_scoped: bool
    mount_invitation: bool
    on_peer_update: Callable[[], Any] | None = None
    topic_noun: str = ""
    template_required: bool = False
    list_templates: Callable[[], Iterable[dict]] | None = None
    create_topic: Callable[[str, str, dict | None], Any] | None = None


SharedTopicHandler = ApplicationRegistration


class SharedTopicRegistry:
    """Runtime-only application topic handlers for one Session."""

    def __init__(self):
        self._lock = threading.RLock()
        self._handlers_by_owner: dict[str, ApplicationRegistration] = {}
        self._owner_by_root_type: dict[str, str] = {}

    def register(
        self,
        owner: str,
        root_types: Iterable[str],
        list_topics: Callable[[], Iterable[str | ProtocolNode]],
        accept_invitation: Callable[[ProtocolNode], Any],
        *,
        assignment_scoped: bool = True,
        mount_invitation: bool = True,
    ) -> None:
        owner = str(owner or "").strip()
        normalized_types = frozenset(
            str(value).strip() for value in root_types if str(value).strip()
        )
        if not owner or not normalized_types:
            raise ValueError("shared topic handler requires owner and root types")
        with self._lock:
            conflicts = {
                root_type: current_owner
                for root_type in normalized_types
                if (current_owner := self._owner_by_root_type.get(root_type))
                and current_owner != owner
            }
            if conflicts:
                root_type, current_owner = next(iter(conflicts.items()))
                raise ValueError(
                    f"topic type {root_type!r} is already handled by {current_owner!r}"
                )
            self.unregister(owner)
            handler = ApplicationRegistration(
                owner, normalized_types, list_topics, accept_invitation,
                assignment_scoped, mount_invitation,
            )
            self._handlers_by_owner[owner] = handler
            for root_type in normalized_types:
                self._owner_by_root_type[root_type] = owner

    def unregister(self, owner: str) -> None:
        with self._lock:
            handler = self._handlers_by_owner.pop(owner, None)
            if not handler:
                return
            for root_type in handler.root_types:
                if self._owner_by_root_type.get(root_type) == owner:
                    self._owner_by_root_type.pop(root_type, None)

    def register_application(self, registration: ApplicationRegistration) -> None:
        with self._lock:
            if registration.application_id in self._handlers_by_owner:
                raise ValueError(
                    f"application {registration.application_id!r} is already registered"
                )
            self.register(
                registration.application_id,
                registration.root_types,
                registration.list_topics,
                registration.accept_invitation,
                assignment_scoped=registration.assignment_scoped,
                mount_invitation=registration.mount_invitation,
            )
            self._handlers_by_owner[registration.application_id] = registration

    def registrations(self) -> tuple[ApplicationRegistration, ...]:
        with self._lock:
            return tuple(self._handlers_by_owner.values())

    def handler_for(self, node: ProtocolNode | None) -> SharedTopicHandler | None:
        root_type = str((node.data if node else {}).get("type") or "")
        with self._lock:
            owner = self._owner_by_root_type.get(root_type)
            return self._handlers_by_owner.get(owner) if owner else None

    def supports(self, node: ProtocolNode | None) -> bool:
        return self.handler_for(node) is not None

    def local_topic_uuids(
        self,
        assigned_topic_uuids: Iterable[str] | None = None,
    ) -> list[str]:
        """Return publishable topics, applying home-channel scope in one place."""
        with self._lock:
            handlers = list(self._handlers_by_owner.values())
        assigned = (
            {str(value) for value in assigned_topic_uuids if str(value)}
            if assigned_topic_uuids is not None else None
        )
        found = set()
        for handler in handlers:
            for item in handler.list_topics() or []:
                topic_uuid = item.uuid if isinstance(item, ProtocolNode) else str(item or "")
                if (topic_uuid and (
                    assigned is None
                    or not handler.assignment_scoped
                    or topic_uuid in assigned
                )):
                    found.add(topic_uuid)
        return sorted(found)

    def accept_invited_topic(self, tree: ProtocolNode):
        handler = self.handler_for(tree)
        return handler.accept_invitation(tree) if handler else None

    def invitation_requires_mount(self, tree: ProtocolNode | None) -> bool:
        """Whether a recognized topic is expected to exist in the local tree."""
        handler = self.handler_for(tree)
        return handler.mount_invitation if handler else True

    def topic_kinds(self) -> list[dict]:
        """What can be made here, and what each one starts from.

        Only applications actually running on this client, and only those
        that said how one of their topics is made. A kind that is not here
        is not offered rather than offered and then refused.
        """
        out = []
        for handler in self.registrations():
            if handler.create_topic is None or not handler.topic_noun:
                continue
            templates = handler.list_templates
            out.append({
                "application_id": handler.application_id,
                "noun": handler.topic_noun,
                "template_required": handler.template_required,
                "templates": [
                    {
                        "value": str(item.get("value") or ""),
                        "name": str(item.get("name") or item.get("value") or ""),
                        "description": str(item.get("description") or ""),
                    }
                    for item in (templates() if templates else [])
                ],
            })
        return sorted(out, key=lambda kind: kind["noun"].lower())

    def make_topic(
        self, application_id: str, title: str, template: str = "",
        snapshot: dict | None = None,
    ):
        """Ask the application that owns a kind to make one.

        Returns its own result. Nothing here reads a template id or a
        snapshot document: what a valid one contains is the owning
        application's answer, and the caller's business is only the uuid
        that comes back.
        """
        with self._lock:
            handler = self._handlers_by_owner.get(str(application_id or "").strip())
        if handler is None or handler.create_topic is None:
            return None
        return handler.create_topic(str(title or ""), str(template or ""), snapshot)

    def has_assignment_scoped_handlers(self) -> bool:
        with self._lock:
            return any(
                handler.assignment_scoped
                for handler in self._handlers_by_owner.values()
            )
