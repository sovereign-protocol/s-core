"""Local navigation links are conveniences, never protocol semantics."""

import unittest

from sovereign import ApplicationRegistration
from sovereign.session import Session


def register_notes_app(session: Session) -> list:
    topics = []
    session.register_application(ApplicationRegistration(
        application_id="notes",
        root_types=frozenset({"notes"}),
        list_topics=lambda: list(topics),
        accept_invitation=session.accept_topic_invitation,
        assignment_scoped=True,
        mount_invitation=True,
        topic_noun="Note",
    ))
    return topics


def make_topic(session: Session, topics: list, name: str):
    topic = session.create_child(
        session.root_uuid(), {"type": "notes", "name": name}, {},
    ).value
    topics.append(topic)
    session.start_discussion(topic.uuid)
    return topic


class NavigationLinkTests(unittest.TestCase):
    def setUp(self):
        self.session = Session("si-navigation")
        self.topics = register_notes_app(self.session)
        self.holder = make_topic(self.session, self.topics, "Holder")
        self.target = make_topic(self.session, self.topics, "Target")

    def test_link_is_local_metadata_and_not_a_protocol_node(self):
        before = set(self.session.protocol.index)
        created = self.session.create_navigation_link(
            self.holder.uuid, self.target.uuid,
        )

        self.assertEqual(created.status, "ok", created.reason)
        self.assertEqual(set(self.session.protocol.index), before)
        self.assertEqual(self.session.navigation_links(self.holder.uuid), [{
            "uuid": created.value,
            "topic_uuid": self.target.uuid,
            "application_id": "notes",
            "label": "Note",
            "title": "Target",
        }])
        self.assertIn("navigation_links", self.session.app_metadata)

    def test_link_requires_two_held_registered_topics(self):
        missing = self.session.create_navigation_link(
            self.holder.uuid, "not-held",
        )
        self_link = self.session.create_navigation_link(
            self.holder.uuid, self.holder.uuid,
        )

        self.assertEqual(missing.status, "error")
        self.assertEqual(self_link.status, "error")
        self.assertEqual(self.session.navigation_links(self.holder.uuid), [])

    def test_duplicate_is_refused_and_remove_keeps_both_topics(self):
        created = self.session.create_navigation_link(
            self.holder.uuid, self.target.uuid,
        )
        duplicate = self.session.create_navigation_link(
            self.holder.uuid, self.target.uuid,
        )
        removed = self.session.remove_navigation_link(
            self.holder.uuid, created.value,
        )

        self.assertEqual(duplicate.status, "error")
        self.assertEqual(removed.status, "ok")
        self.assertIsNotNone(self.session.get_node(self.holder.uuid))
        self.assertIsNotNone(self.session.get_node(self.target.uuid))
        self.assertEqual(self.session.navigation_links(self.holder.uuid), [])

    def test_candidates_are_other_unlinked_held_topics(self):
        third = make_topic(self.session, self.topics, "Another")
        self.session.create_navigation_link(self.holder.uuid, self.target.uuid)

        candidates = self.session.navigation_candidates(self.holder.uuid)

        self.assertEqual(
            [item["topic_uuid"] for item in candidates], [third.uuid],
        )

    def test_candidates_may_live_below_an_application_container(self):
        container = self.session.create_child(
            self.session.root_uuid(), {"type": "folder", "name": "Notes app"}, {},
        ).value
        nested = self.session.create_child(
            container.uuid, {"type": "notes", "name": "Nested"}, {},
        ).value
        self.topics.append(nested)

        candidates = self.session.navigation_candidates(self.holder.uuid)

        self.assertIn(nested.uuid, [item["topic_uuid"] for item in candidates])

    def test_drop_is_not_blocked_and_clears_local_shortcuts(self):
        self.session.create_navigation_link(self.holder.uuid, self.target.uuid)

        dropped = self.session.drop_topic(self.target.uuid)

        self.assertEqual(dropped.status, "ok", dropped.reason)
        self.assertEqual(self.session.navigation_links(self.holder.uuid), [])

    def test_navigation_metadata_round_trips_in_session_envelope(self):
        created = self.session.create_navigation_link(
            self.holder.uuid, self.target.uuid,
        )
        metadata = self.session.persistence_metadata()
        restored = Session("si-restored")
        register_notes_app(restored)
        restored.adopt_subtree(self.session.get_node(self.holder.uuid), restored.root_uuid())
        restored.adopt_subtree(self.session.get_node(self.target.uuid), restored.root_uuid())
        restored.restore_persistence_metadata(metadata)

        self.assertEqual(
            restored.navigation_links(self.holder.uuid)[0]["uuid"], created.value,
        )


if __name__ == "__main__":
    unittest.main()
