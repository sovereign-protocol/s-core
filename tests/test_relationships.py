"""Core-owned connections: union authorship, bridging, and candidates."""

import unittest

from sovereign import ApplicationRegistration
from sovereign.channel import ChannelManager
from sovereign.collaboration import CollaborationService
from sovereign.relationships import RELATIONSHIP_TYPE, RelationshipService
from sovereign.session import Session, SessionResult

from tests.test_channel_manager import _BridgingChannel


def register(session: Session, application_id: str, root_type: str,
             noun: str, topics: list, validate_relationship=None,
             on_relationship_removed=None):
    session.register_application(ApplicationRegistration(
        application_id=application_id,
        root_types=frozenset({root_type}),
        list_topics=lambda: list(topics),
        accept_invitation=session.accept_topic_invitation,
        assignment_scoped=True,
        mount_invitation=True,
        topic_noun=noun,
        create_topic=lambda title, template, snapshot: make_topic(
            session, topics, root_type, title,
        ),
        validate_relationship=validate_relationship,
        on_relationship_removed=on_relationship_removed,
    ))


def make_topic(session: Session, topics: list, root_type: str, name: str):
    topic = session.create_child(
        session.root_uuid(), {"type": root_type, "title": name}, {},
    ).value
    topics.append(topic)
    return SessionResult("ok", value=topic.uuid)


class RelationshipMechanicsTests(unittest.TestCase):
    def setUp(self):
        self.session = Session("rel-a")
        self.teams: list = []
        self.flows: list = []
        register(self.session, "teams", "team", "Team", self.teams)
        register(self.session, "flows", "flow", "Flow", self.flows)
        self.manager = ChannelManager(self.session)
        self.channel = _BridgingChannel()
        self.manager.register(self.channel)
        self.collaboration = CollaborationService(self.session, self.manager)
        self.service = RelationshipService(self.session, self.collaboration)
        self.team = make_topic(self.session, self.teams, "team", "Alpha").value
        self.team = self.session.get_node(self.team)
        self.flow = make_topic(self.session, self.flows, "flow", "Onboarding").value
        self.flow = self.session.get_node(self.flow)

    def test_create_relationship_writes_a_core_owned_child(self):
        created = self.service.create_relationship(self.team.uuid, self.flow.uuid)

        self.assertEqual(created.status, "ok", created.reason)
        node = self.session.get_node(created.value.uuid)
        self.assertEqual(node.parent_uuid, self.team.uuid)
        self.assertEqual(node.data["type"], RELATIONSHIP_TYPE)
        self.assertEqual(node.data["topic_uuid"], self.flow.uuid)
        self.assertEqual(node.data["application_id"], "flows")
        self.assertEqual(node.data["actor_uuid"], self.session.identity.uuid)

    def test_self_link_and_unheld_target_are_refused(self):
        self_link = self.service.create_relationship(self.team.uuid, self.team.uuid)
        missing = self.service.create_relationship(self.team.uuid, "not-a-topic")

        self.assertEqual(self_link.status, "error")
        self.assertEqual(missing.status, "error")

    def test_a_second_relationship_from_the_same_actor_is_refused(self):
        first = self.service.create_relationship(self.team.uuid, self.flow.uuid)
        duplicate = self.service.create_relationship(self.team.uuid, self.flow.uuid)

        self.assertEqual(first.status, "ok")
        self.assertEqual(duplicate.status, "error")

    def test_connection_reads_as_live_while_any_authors_survive(self):
        mine = self.service.create_relationship(self.team.uuid, self.flow.uuid).value
        # A peer's own statement about the same target, written directly the
        # way S-Team's tests simulate a replicated answer.
        theirs = self.session.create_child(self.team.uuid, {
            "type": RELATIONSHIP_TYPE,
            "topic_uuid": self.flow.uuid,
            "application_id": "flows",
            "title": "Onboarding",
            "actor_uuid": "peer-actor",
        }, {}).value

        rows = self.service.relationships(self.team.uuid)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["mine"])
        self.assertTrue(rows[0]["held"])

        removed = self.service.remove_relationship(self.team.uuid, mine.uuid)
        self.assertEqual(removed.status, "ok")
        rows = self.service.relationships(self.team.uuid)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["mine"])
        self.assertEqual(rows[0]["uuid"], theirs.uuid)

        removed_theirs = self.service.remove_relationship(self.team.uuid, theirs.uuid)
        self.assertEqual(removed_theirs.status, "error")

    def test_remove_refuses_a_relationship_this_actor_did_not_author(self):
        theirs = self.session.create_child(self.team.uuid, {
            "type": RELATIONSHIP_TYPE,
            "topic_uuid": self.flow.uuid,
            "application_id": "flows",
            "title": "Onboarding",
            "actor_uuid": "peer-actor",
        }, {}).value

        result = self.service.remove_relationship(self.team.uuid, theirs.uuid)

        self.assertEqual(result.status, "error")
        self.assertIsNotNone(self.session.get_node(theirs.uuid))

    def test_a_registered_hook_is_told_after_this_actors_own_removal(self):
        removed_calls = []

        def remember_removal(parent, topic_uuid):
            removed_calls.append((parent.uuid, topic_uuid))

        session = Session("rel-d")
        teams: list = []
        flows: list = []
        register(
            session, "teams", "team", "Team", teams,
            on_relationship_removed=remember_removal,
        )
        register(session, "flows", "flow", "Flow", flows)
        manager = ChannelManager(session)
        channel = _BridgingChannel()
        manager.register(channel)
        collaboration = CollaborationService(session, manager)
        service = RelationshipService(session, collaboration)
        team = session.get_node(make_topic(session, teams, "team", "Alpha").value)
        flow = session.get_node(make_topic(session, flows, "flow", "Onboarding").value)
        created = service.create_relationship(team.uuid, flow.uuid)

        removed = service.remove_relationship(team.uuid, created.value.uuid)

        self.assertEqual(removed.status, "ok")
        self.assertEqual(removed_calls, [(team.uuid, flow.uuid)])

    def test_the_hook_is_not_called_when_removal_is_refused(self):
        calls = []
        session = Session("rel-e")
        teams: list = []
        flows: list = []
        register(
            session, "teams", "team", "Team", teams,
            on_relationship_removed=lambda parent, topic_uuid: calls.append(1),
        )
        register(session, "flows", "flow", "Flow", flows)
        manager = ChannelManager(session)
        channel = _BridgingChannel()
        manager.register(channel)
        collaboration = CollaborationService(session, manager)
        service = RelationshipService(session, collaboration)
        team = session.get_node(make_topic(session, teams, "team", "Alpha").value)
        theirs = session.create_child(team.uuid, {
            "type": RELATIONSHIP_TYPE,
            "topic_uuid": "elsewhere",
            "application_id": "flows",
            "title": "Not mine",
            "actor_uuid": "peer-actor",
        }, {}).value

        refused = service.remove_relationship(team.uuid, theirs.uuid)

        self.assertEqual(refused.status, "error")
        self.assertEqual(calls, [])

    def test_an_unheld_target_falls_back_to_the_cached_title(self):
        node = self.session.create_child(self.team.uuid, {
            "type": RELATIONSHIP_TYPE,
            "topic_uuid": "gone-elsewhere",
            "application_id": "flows",
            "title": "Cached name",
            "actor_uuid": "peer-actor",
        }, {}).value

        rows = self.service.relationships(self.team.uuid)

        self.assertEqual(rows, [{
            "topic_uuid": "gone-elsewhere", "uuid": node.uuid, "mine": False,
            "application_id": "flows", "title": "Cached name",
            "label": "Topic", "held": False,
        }])


class RelationshipBridgingTests(unittest.TestCase):
    def setUp(self):
        self.session = Session("rel-b")
        self.teams: list = []
        self.flows: list = []
        register(self.session, "teams", "team", "Team", self.teams)
        register(self.session, "flows", "flow", "Flow", self.flows)
        self.manager = ChannelManager(self.session)
        self.channel = _BridgingChannel()
        self.manager.register(self.channel)
        self.collaboration = CollaborationService(self.session, self.manager)
        self.service = RelationshipService(self.session, self.collaboration)
        self.team = self.session.get_node(
            make_topic(self.session, self.teams, "team", "Alpha").value,
        )
        self.channel.homes[self.team.uuid] = "relay-1"

    def test_create_and_share_bridges_the_new_topic(self):
        created = self.service.create_and_share_topic(
            self.team.uuid, "flows", "Onboarding",
        )

        self.assertEqual(created.status, "ok", created.reason)
        self.assertTrue(
            self.collaboration.topics_share_a_bridge(self.team.uuid, created.value),
        )
        rows = self.service.relationships(self.team.uuid)
        self.assertEqual([row["topic_uuid"] for row in rows], [created.value])

    def test_connect_relationship_joins_and_adds_this_actors_own_say(self):
        process = make_topic(self.session, self.flows, "flow", "Elsewhere").value
        process = self.session.get_node(process)
        self.channel.homes[process.uuid] = "relay-2"

        connected = self.service.connect_relationship(self.team.uuid, process.uuid)

        self.assertEqual(connected.status, "ok", connected.reason)
        rows = self.service.relationships(self.team.uuid)
        self.assertEqual([row["topic_uuid"] for row in rows], [process.uuid])
        self.assertTrue(rows[0]["mine"])

    def test_candidates_split_by_whether_they_already_share_this_bridge(self):
        bridged = self.session.get_node(
            make_topic(self.session, self.flows, "flow", "Bridged").value,
        )
        self.channel.homes[bridged.uuid] = "relay-1"
        private = self.session.get_node(
            make_topic(self.session, self.flows, "flow", "Private").value,
        )

        candidates = self.service.relationship_candidates(self.team.uuid)

        self.assertEqual(
            [item["topic_uuid"] for item in candidates["shared"]], [bridged.uuid],
        )
        self.assertEqual(
            [item["topic_uuid"] for item in candidates["own"]], [private.uuid],
        )

    def test_a_registered_validation_hook_can_refuse_a_connection(self):
        def refuse_second_flow(parent, target):
            existing = [
                child for child in parent.children
                if not child.deleted
                and child.data.get("type") == RELATIONSHIP_TYPE
                and child.data.get("application_id") == "flows"
            ]
            if existing:
                return SessionResult("error", reason="only one flow allowed")
            return None

        session = Session("rel-c")
        teams: list = []
        flows: list = []
        register(
            session, "teams", "team", "Team", teams,
            validate_relationship=refuse_second_flow,
        )
        register(session, "flows", "flow", "Flow", flows)
        manager = ChannelManager(session)
        channel = _BridgingChannel()
        manager.register(channel)
        collaboration = CollaborationService(session, manager)
        service = RelationshipService(session, collaboration)
        team = session.get_node(make_topic(session, teams, "team", "Alpha").value)
        first = session.get_node(make_topic(session, flows, "flow", "First").value)
        second = session.get_node(make_topic(session, flows, "flow", "Second").value)

        allowed = service.create_relationship(team.uuid, first.uuid)
        refused = service.create_relationship(team.uuid, second.uuid)

        self.assertEqual(allowed.status, "ok")
        self.assertEqual(refused.status, "error")
        self.assertEqual(refused.reason, "only one flow allowed")


if __name__ == "__main__":
    unittest.main()
