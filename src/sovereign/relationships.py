"""Core-owned connections between topics: browse, create, and share.

A `sovereign_relationship` says one actor's own topic connects to another -
"this team runs that initiative," "this initiative belongs to that team" -
and is a direct child of the topic it connects *from*. Several actors may
each write their own statement about the same target: the connection reads
as live while any of them survives, and drops only when the last author
removes their own. That union is what makes "the team's work" a fact
several members can independently vouch for rather than one person's private
note, the same property S-Team's own `team_item_relationship` had before
this replaced it.

Creating or connecting a relationship also publishes the target wherever the
source is already published (`CollaborationService.bridge_topic_like` /
`join_bridged_topic`), so "connect this" and "share this with the same
people" are one act rather than two. A plain, unshared shortcut between
topics that are not work - the kind Core already offered - remains
`Session`'s local `navigation_links`, untouched by any of this.
"""

from __future__ import annotations

from typing import Any

from .protocol import ProtocolNode
from .session import Session, SessionResult

RELATIONSHIP_TYPE = "sovereign_relationship"


class RelationshipService:
    """Session-level connections that also know how to share a channel."""

    def __init__(self, session: Session, collaboration):
        self.session = session
        self.collaboration = collaboration

    def _topic(self, topic_uuid: str) -> tuple[ProtocolNode, Any] | None:
        node = self.session.get_node(str(topic_uuid or ""))
        if node is None or node.deleted:
            return None
        handler = self.session.shared_topic_handler_for(node)
        if handler is None:
            return None
        return node, handler

    @staticmethod
    def _view(topic: ProtocolNode, handler: Any) -> dict[str, str]:
        return {
            "topic_uuid": topic.uuid,
            "application_id": handler.application_id,
            "label": handler.topic_noun or "Topic",
            "title": str(
                topic.data.get("title") or topic.data.get("name") or "Untitled",
            ),
        }

    def create_relationship(
        self, parent_uuid: str, topic_uuid: str,
    ) -> SessionResult:
        parent = self._topic(parent_uuid)
        if parent is None:
            return SessionResult("error", reason="relationship source is not held")
        target = self._topic(topic_uuid)
        if target is None:
            return SessionResult("error", reason="relationship target is not held")
        parent_node, parent_handler = parent
        target_node, target_handler = target
        if parent_node.uuid == target_node.uuid:
            return SessionResult("error", reason="a topic cannot connect to itself")
        actor = self.session.identity.uuid
        if any(
            child.data.get("type") == RELATIONSHIP_TYPE
            and child.data.get("topic_uuid") == target_node.uuid
            and child.data.get("actor_uuid") == actor
            for child in parent_node.children
            if not child.deleted
        ):
            return SessionResult("error", reason="that connection already exists")
        if parent_handler.validate_relationship is not None:
            problem = parent_handler.validate_relationship(parent_node, target_node)
            if problem is not None and getattr(problem, "status", "ok") != "ok":
                return problem
        created = self.session.create_child(parent_node.uuid, {
            "type": RELATIONSHIP_TYPE,
            "topic_uuid": target_node.uuid,
            "application_id": target_handler.application_id,
            "title": self._view(target_node, target_handler)["title"],
            "actor_uuid": actor,
        }, {})
        if created.status != "ok":
            return created
        self.session.set_adoption_metadata(
            created.value.uuid, adopt="auto", additions="never",
            author="same-origin",
        )
        return created

    def remove_relationship(
        self, parent_uuid: str, relationship_uuid: str,
    ) -> SessionResult:
        parent = self._topic(parent_uuid)
        if parent is None:
            return SessionResult("error", reason="relationship source is not held")
        parent_node, parent_handler = parent
        node = self.session.get_node(str(relationship_uuid or ""))
        actor = self.session.identity.uuid
        if (
            node is None or node.deleted
            or node.data.get("type") != RELATIONSHIP_TYPE
            or node.parent_uuid != parent_node.uuid
            or node.data.get("actor_uuid") != actor
        ):
            return SessionResult(
                "error", reason="you are not offering that connection",
            )
        target_uuid = str(node.data.get("topic_uuid") or "")
        result = self.session.delete(node.uuid)
        if result.status == "ok" and parent_handler.on_relationship_removed:
            parent_handler.on_relationship_removed(parent_node, target_uuid)
        return result

    def relationships(self, parent_uuid: str) -> list[dict]:
        """The union view: one row per target, live while anyone offers it."""
        parent = self._topic(parent_uuid)
        if parent is None:
            return []
        parent_node, _ = parent
        actor = self.session.identity.uuid
        by_target: dict[str, dict] = {}
        for child in parent_node.children:
            if child.deleted or child.data.get("type") != RELATIONSHIP_TYPE:
                continue
            target_uuid = str(child.data.get("topic_uuid") or "")
            if not target_uuid:
                continue
            entry = by_target.setdefault(target_uuid, {
                "topic_uuid": target_uuid, "uuid": "", "mine": False,
                "application_id": "", "title": "",
            })
            # A cached fallback for a target this client does not hold; the
            # live resolution below overrides it whenever the target *is*
            # held, the same rule S-Initiative's relationships already used.
            entry["application_id"] = str(
                child.data.get("application_id") or entry["application_id"],
            )
            entry["title"] = str(child.data.get("title") or entry["title"] or "Untitled")
            if child.data.get("actor_uuid") == actor:
                entry["mine"] = True
                entry["uuid"] = child.uuid
            elif not entry["uuid"]:
                entry["uuid"] = child.uuid
        out = []
        for target_uuid, entry in by_target.items():
            target = self._topic(target_uuid)
            if target is not None:
                target_node, target_handler = target
                entry.update(self._view(target_node, target_handler))
                entry["held"] = True
            else:
                entry["label"] = "Topic"
                entry["held"] = False
            out.append(entry)
        return sorted(out, key=lambda item: (item["label"], item["title"].lower()))

    def connect_relationship(
        self, parent_uuid: str, topic_uuid: str,
    ) -> SessionResult:
        """Pull in what somebody else already connected, and add my own say."""
        parent = self._topic(parent_uuid)
        if parent is None:
            return SessionResult("error", reason="relationship source is not held")
        parent_node, _ = parent
        normalized = str(topic_uuid or "").strip()
        joined = self.collaboration.join_bridged_topic(normalized, parent_node.uuid)
        if not getattr(joined, "ok", False):
            return SessionResult(
                "error",
                reason=getattr(joined, "reason", "could not connect to it") or "",
            )
        return self.create_relationship(parent_node.uuid, normalized)

    def create_and_share_topic(
        self, parent_uuid: str, application_id: str, title: str,
        template: str = "", snapshot: dict | None = None,
    ) -> SessionResult:
        """Make a new topic and connect it, shared wherever this one is."""
        parent = self._topic(parent_uuid)
        if parent is None:
            return SessionResult("error", reason="relationship source is not held")
        parent_node, _ = parent
        created = self.session.create_application_topic(
            application_id, title, template, snapshot,
        )
        if created.status != "ok":
            return created
        topic_uuid = str(created.value or "")
        # Connected - and so validated - before anything is shared: an
        # application's `validate_relationship` (e.g. S-Initiative's "at
        # most one team") must have the last word before a peer ever sees
        # this topic. A refusal deletes the local draft rather than leaving
        # an orphan behind.
        related = self.create_relationship(parent_node.uuid, topic_uuid)
        if related.status != "ok":
            self.session.delete(topic_uuid)
            return related
        # Publishing is attempted, not required: a source with no channel of
        # its own has nowhere to put it yet, and the connection still stands
        # locally - the same "stays private until there is somewhere"
        # behavior S-Team's item creation already had.
        self.collaboration.bridge_topic_like(topic_uuid, parent_node.uuid)
        return SessionResult(
            "ok", value=topic_uuid,
            effects=[*created.effects, *related.effects],
        )

    def relationship_candidates(self, parent_uuid: str) -> dict[str, list[dict]]:
        """What could be connected next, in the two groups the picker shows.

        `shared` already publishes wherever this topic does - connecting one
        reaches the same people without any new sharing act. `own` is
        everything else this client holds: private, or shared somewhere
        else. Connecting one of those bridges it as part of the same act.
        """
        parent = self._topic(parent_uuid)
        if parent is None:
            return {"shared": [], "own": []}
        parent_node, _ = parent
        related = {item["topic_uuid"] for item in self.relationships(parent_node.uuid)}
        # Restricted to the same kinds `topic_kinds()` already offers to
        # create - Core's own bootstrap topics (the identity profile and the
        # like) have no `topic_noun` and are not "work" in any application's
        # sense, so they are not candidates to connect either.
        kinds = {kind["application_id"] for kind in self.session.topic_kinds()}
        shared: list[dict] = []
        own: list[dict] = []
        for topic_uuid in self.session.shared_topic_uuids():
            if topic_uuid == parent_node.uuid or topic_uuid in related:
                continue
            target = self._topic(topic_uuid)
            if target is None:
                continue
            target_node, target_handler = target
            if target_handler.application_id not in kinds:
                continue
            view = self._view(target_node, target_handler)
            if self.collaboration.topics_share_a_bridge(parent_node.uuid, topic_uuid):
                shared.append(view)
            else:
                own.append(view)
        key = lambda item: (item["label"].lower(), item["title"].lower())
        return {"shared": sorted(shared, key=key), "own": sorted(own, key=key)}
