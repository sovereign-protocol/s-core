import unittest

from sovereign.protocol import ProtocolNode
from sovereign.topic_registry import (
    ApplicationRegistration, SharedTopicRegistry,
)


class SharedTopicRegistryTests(unittest.TestCase):
    def test_enumerates_topics_and_routes_invitation_by_root_type(self):
        registry = SharedTopicRegistry()
        topic = ProtocolNode({"type": "agreement", "title": "Terms"})
        accepted = []
        registry.register(
            "S-Team",
            {"agreement"},
            lambda: [topic],
            lambda tree: accepted.append(tree.uuid),
        )

        self.assertEqual(registry.local_topic_uuids(), [topic.uuid])
        self.assertTrue(registry.supports(topic))
        registry.accept_invited_topic(topic)
        self.assertEqual(accepted, [topic.uuid])

    def test_root_type_can_only_belong_to_one_application(self):
        registry = SharedTopicRegistry()
        registry.register("first", {"agreement"}, lambda: [], lambda tree: None)

        with self.assertRaisesRegex(ValueError, "already handled"):
            registry.register("second", {"agreement"}, lambda: [], lambda tree: None)

    def test_reregistering_owner_replaces_its_types_and_unregister_removes_it(self):
        registry = SharedTopicRegistry()
        registry.register("app", {"old"}, lambda: [], lambda tree: None)
        registry.register("app", {"new"}, lambda: [], lambda tree: None)

        self.assertFalse(registry.supports(ProtocolNode({"type": "old"})))
        self.assertTrue(registry.supports(ProtocolNode({"type": "new"})))
        registry.unregister("app")
        self.assertFalse(registry.supports(ProtocolNode({"type": "new"})))

    def test_core_topic_respects_the_same_assignment_filter_as_app_topics(self):
        registry = SharedTopicRegistry()
        profile = ProtocolNode({"type": "profile"})
        board = ProtocolNode({"type": "board"})
        registry.register(
            "core", {"profile"}, lambda: [profile], lambda tree: None,
            mount_invitation=False,
        )
        registry.register(
            "app", {"board"}, lambda: [board], lambda tree: None,
        )

        self.assertEqual(registry.local_topic_uuids(()), [])
        self.assertEqual(
            registry.local_topic_uuids({board.uuid}),
            [board.uuid],
        )
        self.assertEqual(
            set(registry.local_topic_uuids({profile.uuid, board.uuid})),
            {profile.uuid, board.uuid},
        )
        self.assertFalse(registry.invitation_requires_mount(profile))
        self.assertTrue(registry.invitation_requires_mount(board))

    def test_only_an_application_that_said_how_offers_a_kind_to_make(self):
        """Making one is the owning application's, and it says so once.

        Three applications had each grown a table of how to create another
        application's topics - a noun, an api version, a template lookup and
        a create call per kind - and every one of them was restating what
        the owning application already knew.
        """
        registry = SharedTopicRegistry()
        made = []
        registry.register_application(ApplicationRegistration(
            "flow", frozenset({"process"}), lambda: [], lambda tree: None,
            True, True,
            topic_noun="Flow",
            template_required=True,
            list_templates=lambda: [{"value": "election", "name": "Election"}],
            create_topic=lambda title, template, snapshot: made.append(
                (title, template, snapshot),
            ),
        ))
        # Registered, and read from, but nothing here can be made.
        registry.register_application(ApplicationRegistration(
            "reader", frozenset({"note"}), lambda: [], lambda tree: None,
            True, True,
        ))

        kinds = registry.topic_kinds()

        self.assertEqual([kind["application_id"] for kind in kinds], ["flow"])
        self.assertTrue(kinds[0]["template_required"])
        self.assertEqual(
            kinds[0]["templates"],
            [{"value": "election", "name": "Election", "description": ""}],
        )
        registry.make_topic("flow", "Choosing", "election")
        self.assertEqual(made, [("Choosing", "election", None)])
        # An application that is not here answers nothing rather than
        # raising, so the caller can say so in its own words.
        self.assertIsNone(registry.make_topic("absent", "Anything"))
        self.assertIsNone(registry.make_topic("reader", "Anything"))


if __name__ == "__main__":
    unittest.main()
