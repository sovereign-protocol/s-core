"""An adoption authorised for one topic must not touch anything outside it.

Core classifies transitions against a topic-scoped comparison and then resolves
them against the global index. These are the three ways a peer could exploit
that gap before confinement was enforced - see DESIGN_TOPIC_CONFINEMENT.md.
"""

import unittest
import uuid as uuid_mod

from sovereign.protocol import ProtocolNode
from sovereign.session import Session


class TopicConfinementTests(unittest.TestCase):
    def scenario(self):
        """A shared board, and a private topic the peer was never given."""
        victim = Session("si-victim")
        peer = Session("si-peer")
        victim.identity
        peer.identity

        root = victim.protocol.root.uuid
        board = victim.create_child(
            root, {"type": "initiative", "name": "Initiative"}, {},
        ).value
        private = victim.create_child(
            root, {"type": "team", "name": "Private"}, {},
        ).value
        secret = victim.create_child(
            private.uuid, {"type": "team_clause", "text": "Original"}, {},
        ).value

        victim.note_indirect_peer_topic(peer.address, board.uuid)
        victim.apply_peer_subtree(
            peer.address, ProtocolNode.from_dict(peer.identity.to_dict()), None,
        )
        return victim, peer, board, private, secret

    def apply_peer_board(self, victim, peer, board, planted):
        board_dict = victim.protocol.index[board.uuid].to_dict()
        board_dict["children"] = [planted]
        # A real peer computes valid hashes over its own tree.
        peer_board = ProtocolNode.from_dict(board_dict, repair_hashes=True)
        peer_board.refresh_hashes_deep()
        victim.apply_peer_subtree(
            peer.address, peer_board, victim.protocol.root.uuid,
        )

    def test_peer_cannot_overwrite_a_node_held_in_another_topic(self):
        victim, peer, board, private, secret = self.scenario()
        planted = victim.protocol.index[secret.uuid].to_dict()
        planted["data"] = {"type": "kanban_card", "name": "PLANTED"}
        planted["parent_uuid"] = board.uuid
        planted["children"] = []
        self.apply_peer_board(victim, peer, board, planted)

        changed = victim.reconcile_peer_changes(peer.address, board.uuid)

        self.assertFalse(changed)
        held = victim.protocol.index[secret.uuid]
        self.assertEqual(held.parent_uuid, private.uuid)
        self.assertEqual(held.data["text"], "Original")

    def test_peer_cannot_create_a_node_under_a_parent_in_another_topic(self):
        victim, peer, board, private, secret = self.scenario()
        planted = victim.protocol.index[secret.uuid].to_dict()
        planted["uuid"] = str(uuid_mod.uuid4())
        planted["data"] = {"type": "kanban_card", "name": "PLANTED"}
        planted["parent_uuid"] = secret.uuid          # inside the private topic
        planted["children"] = []
        self.apply_peer_board(victim, peer, board, planted)

        victim.reconcile_peer_changes(peer.address, board.uuid)

        self.assertNotIn(planted["uuid"], victim.protocol.index)
        self.assertEqual(victim.protocol.index[secret.uuid].children, [])

    def test_manual_accept_is_confined_too(self):
        """The gap is in Core, so the guard cannot live only in reconcile."""
        victim, peer, board, private, secret = self.scenario()
        planted = victim.protocol.index[secret.uuid].to_dict()
        planted["data"] = {"type": "kanban_card", "name": "PLANTED"}
        planted["parent_uuid"] = board.uuid
        planted["children"] = []
        self.apply_peer_board(victim, peer, board, planted)

        result = victim.accept_peer_node(peer.address, secret.uuid)

        self.assertEqual(result.status, "error")
        self.assertEqual(
            victim.protocol.index[secret.uuid].data["text"], "Original",
        )

    def test_a_tombstoned_local_node_is_still_a_local_node(self):
        """Deleted-but-unpruned uuids stay indexed, so they stay confined.

        A deletion is pruned only once the topic's peers have confirmed it, so
        the private topic needs a peer of its own for a tombstone to persist -
        which is the realistic shape anyway: one topic shared with a colleague,
        another shared with the peer doing the planting.
        """
        victim, peer, board, private, secret = self.scenario()
        colleague = Session("si-colleague")
        colleague.identity
        victim.note_indirect_peer_topic(colleague.address, private.uuid)
        victim.apply_peer_subtree(
            colleague.address,
            ProtocolNode.from_dict(victim.protocol.index[private.uuid].to_dict()),
            victim.protocol.root.uuid,
        )

        planted = victim.protocol.index[secret.uuid].to_dict()
        victim.delete(secret.uuid)
        tombstone = victim.protocol.index.get(secret.uuid)
        self.assertIsNotNone(tombstone, "the deletion should not be pruned yet")

        planted["data"] = {"type": "kanban_card", "name": "REVIVED"}
        planted["parent_uuid"] = board.uuid
        planted["children"] = []
        self.apply_peer_board(victim, peer, board, planted)

        victim.reconcile_peer_changes(peer.address, board.uuid)

        held = victim.protocol.index[secret.uuid]
        self.assertNotEqual(held.parent_uuid, board.uuid)
        self.assertNotEqual(held.data.get("name"), "REVIVED")

    def test_ordinary_changes_inside_the_shared_topic_still_flow(self):
        """Confinement must not cost the normal case anything."""
        peer = Session("si-b")
        topic = peer.create_child(
            peer.protocol.root.uuid, {"type": "initiative", "name": "b"}, {},
        ).value
        card = peer.create_child(
            topic.uuid, {"type": "kanban_card", "name": "original"}, {},
        ).value
        local = Session("si-a")
        local.adopt_subtree(
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )
        local.set_topic_adoption_default(
            topic.uuid, adopt="auto", additions="auto",
        )

        peer.modify(card.uuid, {"type": "kanban_card", "name": "edited"}, {})
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        changed = local.reconcile_peer_changes("si-b", topic.uuid)

        self.assertTrue(changed)
        self.assertEqual(local.protocol.index[card.uuid].data["name"], "edited")


if __name__ == "__main__":
    unittest.main()
