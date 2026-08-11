"""Core-owned collaboration services.

Applications receive only :class:`ApplicationCollaborationView`.  Channel
registration, configuration, topic bindings, invitation negotiation and
effect delivery remain private to Core.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .channel import (
    ChannelManager, ChannelResult, ManagedChannel, PairingChannel,
)


@dataclass(frozen=True)
class ApplicationCollaborationView:
    """The deliberately small collaboration surface exposed to apps.

    The bridge operations name topics only. An application says "put this
    one where that one already is" and never learns which channel that is,
    what it costs, or who else is on it - the same rule the invitation
    operations follow.
    """

    _network_info: Callable[[str | None], dict]
    _peer_liveness: Callable[[str, str | None], dict | None]
    _compose_topic_invitation: Callable[[str], ChannelResult]
    _accept_topic_invitation_token: Callable[[dict], ChannelResult]
    _bridge_topic_like: Callable[[str, str], ChannelResult]
    _follow_bridged_topic: Callable[[str, str], ChannelResult]
    _join_bridged_topic: Callable[[str, str], ChannelResult]
    _unbridge_topic: Callable[[str], ChannelResult]
    _topics_share_a_bridge: Callable[[str, str], bool]

    def network_info(self, topic_uuid: str | None = None) -> dict:
        return self._network_info(topic_uuid)

    def peer_liveness_for_address(
        self, peer_addr: str, topic_uuid: str | None = None,
    ) -> dict | None:
        return self._peer_liveness(peer_addr, topic_uuid)

    def compose_topic_invitation(self, topic_uuid: str) -> ChannelResult:
        return self._compose_topic_invitation(topic_uuid)

    def accept_topic_invitation_token(self, token: dict) -> ChannelResult:
        return self._accept_topic_invitation_token(token)

    def bridge_topic_like(
        self, topic_uuid: str, like_topic_uuid: str,
    ) -> ChannelResult:
        """Publish one topic wherever another is already published."""
        return self._bridge_topic_like(topic_uuid, like_topic_uuid)

    def follow_bridged_topic(
        self, topic_uuid: str, like_topic_uuid: str,
    ) -> ChannelResult:
        """Consent to receive a topic over a channel already in use here."""
        return self._follow_bridged_topic(topic_uuid, like_topic_uuid)

    def join_bridged_topic(
        self, topic_uuid: str, like_topic_uuid: str,
    ) -> ChannelResult:
        """Receive a bridged topic and publish this replica back on it."""
        return self._join_bridged_topic(topic_uuid, like_topic_uuid)

    def unbridge_topic(self, topic_uuid: str) -> ChannelResult:
        """Stop publishing and receiving one topic. It becomes private."""
        return self._unbridge_topic(topic_uuid)

    def topics_share_a_bridge(
        self, topic_uuid: str, like_topic_uuid: str,
    ) -> bool:
        return self._topics_share_a_bridge(topic_uuid, like_topic_uuid)


class CollaborationService:
    """Session-level owner of channels, bindings and invitations."""

    RELEASE_TOPIC_EFFECT = "release_topic_channels"

    def __init__(self, session, channel_manager: ChannelManager):
        self.session = session
        self._channels = channel_manager
        self.application_view = ApplicationCollaborationView(
            self.network_info,
            self.peer_liveness_for_address,
            self.compose_topic_invitation,
            self.accept_topic_invitation_token,
            self.bridge_topic_like,
            self.follow_bridged_topic,
            self.join_bridged_topic,
            self.unbridge_topic,
            self.topics_share_a_bridge,
        )

    def network_info(self, topic_uuid: str | None = None) -> dict:
        return self._channels.network_info(topic_uuid)

    def peer_liveness_for_address(
        self, peer_addr: str, topic_uuid: str | None = None,
    ) -> dict | None:
        return self._channels.peer_liveness_for_address(peer_addr, topic_uuid)

    def execute_effects(self, effects: Iterable[Any]) -> list[Any]:
        """Execute application results without exposing channel machinery.

        One effect type reaches here, and it is a lifecycle signal rather
        than a message: releasing a topic's channels when its sharing ends.
        Nothing else is carried, because no channel sends anything on a
        caller's schedule any more - a mailbox publishes and polls on its
        own. Unknown effects are ignored rather than refused, so an
        application that grows one does not break on a Core that has not
        learned it yet.
        """
        deliveries = []
        for effect in effects:
            if getattr(effect, "type", "") != self.RELEASE_TOPIC_EFFECT:
                continue
            topic_uuid = str(
                (getattr(effect, "payload", {}) or {}).get("topic_uuid")
                or getattr(effect, "target", "")
                or ""
            ).strip()
            if not topic_uuid:
                continue
            released = self.release_topic(topic_uuid)
            if released.ok and released.value:
                deliveries.extend(released.value)
        return deliveries

    def release_topic(self, topic_uuid: str) -> ChannelResult:
        deliveries = []
        for channel in self._channels.channels():
            result = channel.detach_topics((topic_uuid,))
            if not result.ok:
                return result
            if isinstance(result.value, (list, tuple)):
                deliveries.extend(result.value)
        return ChannelResult.success(deliveries)

    def channels_payload(self) -> dict:
        channel_types = []
        instances = []
        identity_uuid = self.session.identity.uuid
        for channel in self._channels.channels():
            if not isinstance(channel, ManagedChannel):
                continue
            described = channel.management_descriptor()
            channel_types.extend(described.get("types") or [])
            for instance in described.get("instances") or []:
                assigned_topics = []
                for topic_uuid in instance.get("topic_uuids") or []:
                    topic_uuid = str(topic_uuid)
                    is_identity = topic_uuid == identity_uuid
                    node = self.session.get_node(topic_uuid)
                    data = node.data if node else {}
                    assigned_topics.append({
                        "uuid": topic_uuid,
                        "title": (
                            "My identity" if is_identity
                            else data.get("name") or data.get("title")
                            or topic_uuid
                        ),
                        "identity": is_identity,
                    })
                instances.append({
                    **instance,
                    "identity_home": any(
                        topic["identity"] for topic in assigned_topics
                    ),
                    "assigned_topics": assigned_topics,
                })
        identity_channel_ref = next((
            str(instance.get("ref") or "")
            for instance in instances
            if instance.get("identity_home")
        ), "")
        return {
            "status": "ok",
            "types": channel_types,
            "channels": instances,
            "identity_topic_uuid": identity_uuid,
            "identity_channel_ref": identity_channel_ref,
        }

    def topic_sharing_payload(self, topic_uuid: str) -> ChannelResult:
        topic = self.session.get_node(topic_uuid)
        if not topic or not self.session.supports_shared_topic(topic):
            return ChannelResult.error("application topic not found", 404)
        network = self.network_info(topic_uuid)
        peers = []
        identities = {}
        for item in self.session.known_identities():
            for address in item.get("addresses") or [item.get("address")]:
                if address:
                    identities[address] = item
        for peer_addr, info in sorted((network.get("peers") or {}).items()):
            if not self.session.peer_discusses_node(peer_addr, topic_uuid):
                continue
            identity = identities.get(peer_addr) or {}
            peers.append({
                "address": peer_addr,
                "name": identity.get("name") or peer_addr,
                "picture": identity.get("picture") or "",
                "identity_uuid": identity.get("uuid") or "",
                "channel": info.get("channel") or "",
                "status": info.get("status") or {},
                "channel_liveness": info.get("channel_liveness"),
            })

        bindings = []
        for channel in self._channels.channels():
            if isinstance(channel, ManagedChannel):
                bindings.extend(channel.topic_bindings(topic_uuid))
        return ChannelResult.success({
            "status": "ok",
            "topic_uuid": topic_uuid,
            "people": peers,
            "channels": bindings,
        })

    def configure_channel(self, values: dict) -> ChannelResult:
        channel = self._managed_channel(values.get("kind"))
        if not channel:
            return ChannelResult.error("unknown managed channel", 400)
        operation = (
            channel.update_instance
            if str(values.get("id") or "").strip()
            else channel.create_instance
        )
        return operation(values)

    def test_channel(self, values: dict) -> ChannelResult:
        channel = self._managed_channel(values.get("kind"))
        if not channel:
            return ChannelResult.error("unknown managed channel", 400)
        return channel.test_instance(values)

    def delete_channel(self, channel_ref: str) -> ChannelResult:
        """Remove a channel from this client, releasing whatever it carried.

        Deliberately unconditional. This used to refuse while any topic was
        still assigned to the channel, which turned the assignment - something
        the user never sees, and which nothing clears when the peers go away -
        into a lock on the channel list, reported as a bare topic uuid. A
        topic left with no channel is simply private again, and that is what
        deleting a channel means.
        """
        channel, instance_id = self._channel_instance(channel_ref)
        if not channel or not instance_id:
            return ChannelResult.error("channel not found", 404)
        return channel.delete_instance(instance_id)

    def set_topic_channel(
        self, topic_uuid: str, channel_ref: str, enabled: bool,
    ) -> ChannelResult:
        topic = self.session.get_node(topic_uuid)
        if not topic or not self.session.supports_shared_topic(topic):
            return ChannelResult.error("application topic not found", 404)
        channel, instance_id = self._channel_instance(channel_ref)
        if not channel:
            return ChannelResult.error("channel not found", 404)
        if enabled:
            options = {"instance_id": instance_id} if instance_id else {}
            return channel.attach_topics((topic_uuid,), options)
        if instance_id:
            if not isinstance(channel, ManagedChannel):
                return ChannelResult.error("channel instance cannot be detached", 400)
            return channel.detach_instance_topics((topic_uuid,), instance_id)
        return channel.detach_topics((topic_uuid,))

    def stop_channel(self, channel_ref: str) -> ChannelResult:
        """Detach every topic, including identity, while keeping the channel."""
        channel, instance_id = self._channel_instance(channel_ref)
        if not channel or not instance_id:
            return ChannelResult.error("channel not found", 404)
        if not isinstance(channel, ManagedChannel):
            return ChannelResult.error("channel instance cannot be detached", 400)
        instance = next((
            item for item in channel.management_descriptor().get("instances") or []
            if str(item.get("id") or "") == instance_id
        ), None)
        if instance is None:
            return ChannelResult.error("channel not found", 404)
        topic_uuids = tuple(str(item) for item in instance.get("topic_uuids") or [])
        if not topic_uuids:
            return ChannelResult.success()
        return channel.detach_instance_topics(topic_uuids, instance_id)

    def compose_invitation(
        self, topic_uuid: str, channel_ref: str,
    ) -> ChannelResult:
        if not str(topic_uuid or "").strip():
            return ChannelResult.error("select a topic first", 400)
        topic = self.session.get_node(topic_uuid)
        if not topic or not self.session.supports_shared_topic(topic):
            return ChannelResult.error("application topic not found", 404)
        channel, instance_id = self._channel_instance(channel_ref)
        if not channel:
            return ChannelResult.error("channel not found", 404)
        if not instance_id:
            return ChannelResult.error("channel instance is required", 400)
        topic_home = self._topic_home(topic_uuid)
        if (
            not topic_home
            or topic_home[0] is not channel
            or topic_home[1] != instance_id
        ):
            return ChannelResult.error(
                "use this channel for the topic before inviting anyone to it",
                409,
            )
        identity_uuid = self.session.identity.uuid
        identity_home = self._topic_home(identity_uuid)
        if not identity_home:
            return ChannelResult.error(
                "choose a home channel for your identity in Manage Channels"
                " before inviting",
                409,
            )
        identity_channel, identity_instance_id = identity_home
        return self._channels.compose_token(
            (topic_uuid,),
            {
                topic_uuid: {
                    "kind": channel.kind,
                    "target_id": instance_id,
                },
                identity_uuid: {
                    "kind": identity_channel.kind,
                    "target_id": identity_instance_id,
                },
            },
        )

    def compose_topic_invitation(self, topic_uuid: str) -> ChannelResult:
        """Compose an invitation using the topic's existing home channel.

        Applications need the resulting coordinates for scoped workflows such
        as onboarding, but never need channel inventories or implementation
        objects. The ordinary Share flow remains the place where a home is
        chosen.
        """
        topic_uuid = str(topic_uuid or "").strip()
        topic = self.session.get_node(topic_uuid)
        if not topic or not self.session.supports_shared_topic(topic):
            return ChannelResult.error("application topic not found", 404)
        topic_home = self._topic_home(topic_uuid)
        if not topic_home:
            return ChannelResult.error(
                "choose a home channel for this topic before admitting anyone",
                409,
            )
        identity_uuid = self.session.identity.uuid
        identity_home = self._topic_home(identity_uuid)
        if not identity_home:
            return ChannelResult.error(
                "choose a home channel for your identity before admitting anyone",
                409,
            )
        topic_channel, topic_instance_id = topic_home
        identity_channel, identity_instance_id = identity_home
        return self._channels.compose_token(
            (topic_uuid,),
            {
                topic_uuid: {
                    "kind": topic_channel.kind,
                    "target_id": topic_instance_id,
                },
                identity_uuid: {
                    "kind": identity_channel.kind,
                    "target_id": identity_instance_id,
                },
            },
        )

    # ---- bridges ---------------------------------------------------------
    #
    # A "bridge" is a topic's home channel, named by the topic that is on it
    # rather than by the channel itself. Applications create topics that
    # belong to other topics - an election belongs to the team that called
    # it, a board to the team that keeps it - and those have to travel the
    # same way as the thing they belong to, or they reach nobody. Without
    # this an application could compose an invitation to a topic but never
    # give one a home, which is the one thing needed before an invitation is
    # possible at all.
    #
    # Deliberately two-sided. Putting a topic on a bridge is the publisher
    # saying where it goes; following one is the receiver consenting to have
    # it. Core keeps those apart everywhere else (`shared` and `desired`),
    # and merging them here would let one client graft topics into another's
    # tree because they happen to share a relay root.

    def bridge_topic_like(
        self, topic_uuid: str, like_topic_uuid: str,
    ) -> ChannelResult:
        topic = self.session.get_node(topic_uuid)
        if not topic or not self.session.supports_shared_topic(topic):
            return ChannelResult.error("application topic not found", 404)
        home = self._topic_home(like_topic_uuid)
        if not home:
            return ChannelResult.error(
                "the topic to follow has no home channel", 409,
            )
        channel, instance_id = home
        return channel.attach_topics(
            (topic_uuid,), {"instance_id": instance_id},
        )

    def follow_bridged_topic(
        self, topic_uuid: str, like_topic_uuid: str,
    ) -> ChannelResult:
        """Consent to receive `topic_uuid` over `like_topic_uuid`'s channel.

        The counterpart of accepting an invitation, for a topic whose
        channel this client already uses: there is nothing to negotiate, so
        there is no token, but the consent step is the same one and is not
        skipped. The topic need not exist locally yet - that is the point.
        """
        home = self._topic_home(like_topic_uuid)
        if not home:
            return ChannelResult.error(
                "the topic to follow has no home channel", 409,
            )
        channel, instance_id = home
        follow = getattr(channel, "follow_topics", None)
        if not callable(follow):
            return ChannelResult.error(
                "this channel cannot be followed without an invitation", 400,
            )
        return follow((topic_uuid,), instance_id)

    def join_bridged_topic(
        self, topic_uuid: str, like_topic_uuid: str,
    ) -> ChannelResult:
        """Join both sides of a topic before its first local copy arrives."""
        home = self._topic_home(like_topic_uuid)
        if not home:
            return ChannelResult.error(
                "the topic to join has no home channel", 409,
            )
        channel, instance_id = home
        join = getattr(channel, "join_topics", None)
        if not callable(join):
            return ChannelResult.error(
                "this channel cannot be joined without an invitation", 400,
            )
        return join((topic_uuid,), instance_id)

    def unbridge_topic(self, topic_uuid: str) -> ChannelResult:
        return self.release_topic(topic_uuid)

    def topics_share_a_bridge(
        self, topic_uuid: str, like_topic_uuid: str,
    ) -> bool:
        home = self._topic_home(topic_uuid)
        other = self._topic_home(like_topic_uuid)
        return bool(home and other and home == other)

    def accept_invitation(self, token: dict) -> ChannelResult:
        return self._channels.accept_token(token)

    def accept_topic_invitation_token(self, token: dict) -> ChannelResult:
        """Application-facing name for accepting ordinary Core coordinates."""
        return self._channels.accept_token(token)

    # ---- pairing -------------------------------------------------------

    def compose_pairing_token(self, target_id: str = "") -> ChannelResult:
        channel = self._pairing_channel()
        if not channel:
            return ChannelResult.error("no mailbox channel", 404)
        return channel.compose_pairing_token(target_id)

    def accept_pairing_token(self, token: dict) -> ChannelResult:
        channel = self._pairing_channel()
        if not channel:
            return ChannelResult.error("no mailbox channel", 404)
        return channel.accept_pairing_token(token or {})

    # ---- sibling alarms ------------------------------------------------

    def _pairing_channel(self):
        channel = self._channels.channel("mailbox")
        return channel if isinstance(channel, PairingChannel) else None

    def sibling_alarms_payload(self) -> dict:
        """Topics where another client of this user published something that
        this client's own unpublished work was not built on.

        Session decides a topic is in this state; what to do about it is the
        application's to ask. The title is included because "one of your
        topics" is not something a person can act on.
        """
        channel = self._pairing_channel()
        alarms = channel.sibling_alarms() if channel else []
        described = []
        for alarm in alarms:
            node = self.session.get_node(alarm["topic_uuid"])
            data = node.data if node else {}
            described.append({
                **alarm,
                "title": data.get("name") or data.get("title") or "",
            })
        return {"status": "ok", "alarms": described}

    def resolve_sibling_alarm(self, topic_uuid: str,
                              decision: str) -> ChannelResult:
        channel = self._pairing_channel()
        if not channel:
            return ChannelResult.error("no mailbox channel", 404)
        return channel.resolve_sibling_alarm(topic_uuid, decision)

    def _managed_channel(self, kind: Any):
        channel = self._channels.channel(str(kind or "").strip())
        return channel if isinstance(channel, ManagedChannel) else None

    def _channel_instance(self, channel_ref: str):
        # Every channel is an instance of a managed kind now, so a bare kind
        # names nothing to publish into.
        kind, separator, instance_id = str(channel_ref or "").strip().partition(":")
        if not separator or not instance_id:
            return None, ""
        return self._managed_channel(kind), instance_id

    def _topic_home(self, topic_uuid: str):
        for channel in self._channels.channels():
            if not isinstance(channel, ManagedChannel):
                continue
            for binding in channel.topic_bindings(topic_uuid):
                if binding.get("in_use") and binding.get("id"):
                    return channel, str(binding["id"])
        return None
