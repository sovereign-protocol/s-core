"""A relationship read must never run with Session's lock already held.

`relationship_candidates` reaches into the channel manager
(`topics_share_a_bridge`), which locks itself for real once a topic has an
actual home on a real `RelayManager` - the test doubles the rest of
`test_relationships.py` uses never touch that lock at all, so they could not
have caught `api_core_relationships` wrapping the whole route in
`runtime.session.lock` (locking.py: manager < relay I/O < Session, and
Session's lock was already on the stack).
"""

import tempfile
import unittest
from pathlib import Path

from sovereign import ApplicationRegistration
from sovereign.blob_store import BlobStore
from sovereign.channel import ChannelManager
from sovereign.collaboration import CollaborationService
from sovereign.mailbox_channel import MailboxChannel
from sovereign.relay_logic import RelayManager
from sovereign.relationships import RelationshipService
from sovereign.session import Session, SessionResult


def register(session: Session, application_id: str, root_type: str,
             noun: str, topics: list) -> None:
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
    ))


def make_topic(session: Session, topics: list, root_type: str, name: str):
    topic = session.create_child(
        session.root_uuid(), {"type": root_type, "title": name}, {},
    ).value
    topics.append(topic)
    return SessionResult("ok", value=topic.uuid)


class RelationshipReadLockOrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session = Session("lock-order")
        self.teams: list = []
        register(self.session, "teams", "team", "Team", self.teams)
        blob_store = BlobStore(Path(self.tmp.name) / "blobs")
        self.relay_manager = RelayManager(self.session, {}, blob_store=blob_store)
        channel_manager = ChannelManager(self.session)
        mailbox = MailboxChannel(self.relay_manager)
        channel_manager.register(mailbox)
        self.collaboration = CollaborationService(self.session, channel_manager)
        self.service = RelationshipService(self.session, self.collaboration)
        created = self.relay_manager.create_target({
            "name": "relay", "backend": "local",
            "root": str(Path(self.tmp.name) / "relay"),
        })
        self.assertEqual(created.status, "ok", created.reason)
        self.team = self.session.get_node(
            make_topic(self.session, self.teams, "team", "Alpha").value,
        )
        attached = mailbox.attach_topics(
            [self.team.uuid], {"target_id": created.value},
        )
        self.assertTrue(attached.ok, attached.reason)
        # A second, unrelated topic: `relationship_candidates` only reaches
        # `topics_share_a_bridge` (and so the channel manager's lock) once
        # there is another held topic to check it against.
        self.other = self.session.get_node(
            make_topic(self.session, self.teams, "team", "Beta").value,
        )

    def test_reading_candidates_while_holding_the_session_lock_is_refused(self):
        # This is the mistake `api_core_relationships` made: wrapping the
        # whole route, including this read, in `with runtime.session.lock`.
        # Held here on purpose, to prove why that wrapping cannot come back.
        with self.session.lock:
            with self.assertRaises(RuntimeError):
                self.service.relationship_candidates(self.team.uuid)

    def test_reading_candidates_without_the_session_lock_held_works(self):
        candidates = self.service.relationship_candidates(self.team.uuid)
        self.assertEqual(
            [item["topic_uuid"] for item in candidates["own"]], [self.other.uuid],
        )


if __name__ == "__main__":
    unittest.main()
