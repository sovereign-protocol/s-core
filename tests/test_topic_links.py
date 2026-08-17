"""Topic links, and the three acts that are not the same act.

`DESIGN_TOPIC_LINKS.md` exists because they were the same act once: removing
a flow from a team called the owning application's delete, so taking an item
off a list destroyed it for everybody who held it. What is checked here is
that removing a reference, dropping a topic and deleting it stay apart.
"""

import unittest

from sovereign import ApplicationRegistration
from sovereign.protocol import ProtocolNode
from sovereign.session import Session


def register_notes_app(session: Session) -> list[ProtocolNode]:
    topics: list[ProtocolNode] = []
    session.register_application(ApplicationRegistration(
        application_id="notes",
        root_types=frozenset({"notes"}),
        list_topics=lambda: list(topics),
        accept_invitation=session.accept_topic_invitation,
        assignment_scoped=True,
        mount_invitation=True,
    ))
    return topics


def notes_topics(session: Session) -> list[ProtocolNode]:
    """One registration per session, however many topics it makes."""
    topics = getattr(session, "_test_notes_topics", None)
    if topics is None:
        topics = register_notes_app(session)
        session._test_notes_topics = topics
    return topics


def make_topic(session: Session, name: str) -> ProtocolNode:
    topics = notes_topics(session)
    topic = session.create_child(
        session.root_uuid(), {"type": "notes", "name": name}, {},
    ).value
    topics.append(topic)
    session.start_discussion(topic.uuid)
    return topic


class TopicLinkTests(unittest.TestCase):
    def test_a_link_records_where_the_reference_is(self):
        session = Session("si-link")
        holder = make_topic(session, "Holder")
        referenced = make_topic(session, "Referenced")

        created = session.create_topic_link(
            holder.uuid, referenced.uuid, "notes", "Referenced",
        )

        self.assertEqual(created.status, "ok")
        links = session.links_to(referenced.uuid)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].data["topic_uuid"], referenced.uuid)
        self.assertEqual(links[0].data["application_id"], "notes")
        self.assertEqual(links[0].parent_uuid, holder.uuid)

    def test_one_author_does_not_record_the_same_reference_twice(self):
        session = Session("si-twice")
        holder = make_topic(session, "Holder")
        referenced = make_topic(session, "Referenced")
        session.create_topic_link(holder.uuid, referenced.uuid, "notes")

        again = session.create_topic_link(holder.uuid, referenced.uuid, "notes")

        self.assertEqual(again.status, "error")
        self.assertEqual(len(session.links_to(referenced.uuid)), 1)

    def test_two_actors_may_reference_one_topic_from_one_parent(self):
        """Not a duplicate - the mechanism.

        A team's list of what it runs is the union of its members' own
        references, and removing yours has to leave everybody else's
        standing. That needs each of them to be able to write their own.
        """
        author = Session("si-first")
        second = Session("si-second")
        author.identity
        second.identity
        holder = make_topic(author, "Holder")
        referenced = make_topic(author, "Referenced")
        author.create_topic_link(holder.uuid, referenced.uuid, "notes", "Ref")
        second.adopt_subtree(
            ProtocolNode.from_dict(
                author.protocol.index[holder.uuid].to_dict(),
            ),
            second.protocol.root.uuid,
        )
        self.assertEqual(len(second.links_to(referenced.uuid)), 1)
        self.assertEqual(second.links_to(referenced.uuid, authored_here=True), [])

        mine = second.create_topic_link(
            holder.uuid, referenced.uuid, "notes", "Ref",
        )

        self.assertEqual(mine.status, "ok")
        self.assertEqual(len(second.links_to(referenced.uuid)), 2)
        self.assertEqual(
            len(second.links_to(referenced.uuid, authored_here=True)), 1,
        )

    def test_links_can_be_read_under_one_parent(self):
        session = Session("si-under")
        holder = make_topic(session, "Holder")
        elsewhere = make_topic(session, "Elsewhere")
        referenced = make_topic(session, "Referenced")
        session.create_topic_link(holder.uuid, referenced.uuid, "notes")
        session.create_topic_link(elsewhere.uuid, referenced.uuid, "notes")

        self.assertEqual(len(session.topic_links()), 2)
        self.assertEqual(len(session.topic_links(holder.uuid)), 1)

    def test_a_topic_cannot_link_to_itself(self):
        session = Session("si-self")
        topic = make_topic(session, "Topic")
        inner = session.create_child(
            topic.uuid, {"type": "note", "name": "inner"}, {},
        ).value

        result = session.create_topic_link(inner.uuid, topic.uuid, "notes")

        self.assertEqual(result.status, "error")
        self.assertEqual(session.links_to(topic.uuid), [])

    def test_removing_a_link_leaves_the_topic_and_the_other_links(self):
        session = Session("si-remove")
        first = make_topic(session, "First")
        second = make_topic(session, "Second")
        referenced = make_topic(session, "Referenced")
        session.create_topic_link(first.uuid, referenced.uuid, "notes")
        session.create_topic_link(second.uuid, referenced.uuid, "notes")
        doomed = session.links_to(referenced.uuid)[0]

        removed = session.remove_topic_link(doomed.uuid)

        self.assertEqual(removed.status, "ok")
        self.assertIsNotNone(session.get_node(referenced.uuid))
        self.assertEqual(len(session.links_to(referenced.uuid)), 1)

    def test_a_drop_is_refused_while_a_link_still_points_at_it(self):
        session = Session("si-gated")
        holder = make_topic(session, "Holder")
        referenced = make_topic(session, "Referenced")
        session.create_topic_link(holder.uuid, referenced.uuid, "notes")

        dropped = session.drop_topic(referenced.uuid)

        self.assertEqual(dropped.status, "error")
        self.assertIn("still referenced", dropped.reason)
        self.assertIsNotNone(session.get_node(referenced.uuid))

    def test_a_drop_removes_the_subtree_without_writing_a_deletion(self):
        session = Session("si-drop")
        topic = make_topic(session, "Dropped")
        session.create_child(topic.uuid, {"type": "note", "name": "child"}, {})

        dropped = session.drop_topic(topic.uuid)

        self.assertEqual(dropped.status, "ok")
        self.assertIsNone(session.get_node(topic.uuid))
        # A tombstone would travel and peers would adopt it. Nothing is left
        # behind to travel: the node is gone from the tree, not marked dead
        # in it.
        self.assertNotIn(topic.uuid, session.protocol.index)
        self.assertIn(
            "release_topic_channels",
            [effect.type for effect in dropped.effects],
        )

    def test_a_drop_is_not_a_deletion(self):
        """The distinction the design note exists for.

        `delete` tombstones the node in place so the deletion can travel;
        `drop_topic` takes it out of this tree and says nothing to anybody.
        """
        session = Session("si-versus")
        deleted = make_topic(session, "Deleted")
        dropped = make_topic(session, "Dropped")
        # A peer on both, so the tombstone is not pruned the instant it is
        # written: with nobody to tell, a deletion is confirmed immediately.
        session.note_indirect_peer_topic("si-witness", deleted.uuid)
        session.note_indirect_peer_topic("si-witness", dropped.uuid)

        session.delete(deleted.uuid)
        session.drop_topic(dropped.uuid)

        remaining = session.protocol.index.get(deleted.uuid)
        self.assertIsNotNone(remaining)
        self.assertTrue(remaining.deleted)
        self.assertNotIn(dropped.uuid, session.protocol.index)

    def test_following_a_link_mounts_what_a_peer_publishes(self):
        author = Session("si-author")
        reader = Session("si-reader")
        author.identity
        reader.identity
        published = make_topic(author, "Published")
        holder = make_topic(reader, "Holder")
        reader.create_topic_link(
            holder.uuid, published.uuid, "notes", "Published",
        )
        link = reader.links_to(published.uuid)[0]
        self.assertIsNone(reader.get_node(published.uuid))

        reader.note_indirect_peer_topic(author.address, published.uuid)
        reader.apply_peer_subtree(
            author.address,
            ProtocolNode.from_dict(
                author.protocol.index[published.uuid].to_dict(),
            ),
            None,
        )
        followed = reader.follow_topic_link(link.uuid)

        self.assertEqual(followed.status, "ok")
        self.assertIsNotNone(reader.get_node(published.uuid))

    def test_following_a_link_nobody_publishes_says_so(self):
        """A link is a name for a topic and never a key to it."""
        reader = Session("si-alone")
        holder = make_topic(reader, "Holder")
        reader.create_topic_link(
            holder.uuid, "topic-nobody-has", "notes", "Elsewhere",
        )
        link = reader.links_to("topic-nobody-has")[0]

        followed = reader.follow_topic_link(link.uuid)

        self.assertEqual(followed.status, "error")
        self.assertIn("publishing", followed.reason)
        self.assertIsNone(reader.get_node("topic-nobody-has"))

    def test_a_dropped_topic_can_be_taken_back_from_a_peer(self):
        """The reverse of a drop, said out loud because "I removed it and it
        came back" is otherwise a bug report."""
        author = Session("si-keeper")
        reader = Session("si-returner")
        author.identity
        reader.identity
        topic = make_topic(author, "Shared")
        holder = make_topic(reader, "Holder")
        reader.note_indirect_peer_topic(author.address, topic.uuid)
        reader.apply_peer_subtree(
            author.address,
            ProtocolNode.from_dict(author.protocol.index[topic.uuid].to_dict()),
            None,
        )
        reader.create_topic_link(holder.uuid, topic.uuid, "notes", "Shared")
        link = reader.links_to(topic.uuid)[0]
        reader.follow_topic_link(link.uuid)
        reader.remove_topic_link(link.uuid)
        reader.drop_topic(topic.uuid)
        self.assertIsNone(reader.get_node(topic.uuid))

        # The drop stopped polling, so the peer's copy went with it. It comes
        # back the next time somebody who still publishes it is observed -
        # which is the whole of what "it remains available" means.
        reader.note_indirect_peer_topic(author.address, topic.uuid)
        reader.apply_peer_subtree(
            author.address,
            ProtocolNode.from_dict(author.protocol.index[topic.uuid].to_dict()),
            None,
        )
        reader.create_topic_link(holder.uuid, topic.uuid, "notes", "Shared")
        again = reader.links_to(topic.uuid)[0]
        followed = reader.follow_topic_link(again.uuid)

        self.assertEqual(followed.status, "ok")
        self.assertIsNotNone(reader.get_node(topic.uuid))

    def test_links_to_answers_about_this_tree_only(self):
        """A peer's references are theirs. The count gates a local drop, and
        nothing here lets one client speak for another's tree."""
        author = Session("si-theirs")
        reader = Session("si-mine")
        author.identity
        reader.identity
        referenced = make_topic(author, "Referenced")
        theirs = make_topic(author, "Theirs")
        author.create_topic_link(theirs.uuid, referenced.uuid, "notes")
        reader.note_indirect_peer_topic(author.address, theirs.uuid)
        reader.apply_peer_subtree(
            author.address,
            ProtocolNode.from_dict(author.protocol.index[theirs.uuid].to_dict()),
            None,
        )

        self.assertEqual(reader.links_to(referenced.uuid), [])


if __name__ == "__main__":
    unittest.main()
