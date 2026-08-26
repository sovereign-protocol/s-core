import unittest

from sovereign.binding import GenericBindingService
from sovereign.protocol import ProtocolNode
from sovereign.session import (
    GENERIC_BINDING_NODE_TYPE,
    GENERIC_BINDING_TOPIC_TYPE,
    Session,
)


class GenericBindingTests(unittest.TestCase):
    def setUp(self):
        self.session = Session("http://binding")
        self.session.identity
        self.topic = self.session.create_child(
            self.session.protocol.root.uuid,
            {"type": GENERIC_BINDING_TOPIC_TYPE, "name": "Bound document"},
            {},
        ).value
        self.node = self.session.create_child(
            self.topic.uuid,
            {"type": GENERIC_BINDING_NODE_TYPE, "text": "confirmed"},
            {},
        ).value
        self.service = GenericBindingService(self.session, [{
            "token": "narrow-secret",
            "origin": "https://example.test",
            "topic_uuid": self.topic.uuid,
            "node_uuid": self.node.uuid,
            "fields": ["text"],
            "operations": ["read", "write", "react"],
            "adoption": "hold",
        }])

    def peer(self):
        peer = Session("http://peer")
        peer.identity
        self.session.identity
        peer.set_peer_identity_key(
            self.session.address, self.session.identity.data["identity_key"],
        )
        self.session.set_peer_identity_key(
            peer.address, peer.identity.data["identity_key"],
        )
        accepted = peer.accept_generic_binding_invitation(
            ProtocolNode.from_dict(
                self.session.protocol.index[self.topic.uuid].to_dict(),
            ),
        )
        self.assertEqual(accepted.status, "ok", accepted.reason)
        self.session.note_indirect_peer_topic(peer.address, self.topic.uuid)
        self.publish(peer)
        return peer

    def publish(self, peer):
        self.session.apply_peer_subtree(
            peer.address,
            ProtocolNode.from_dict(
                peer.protocol.index[self.topic.uuid].to_dict()
            ),
            self.session.protocol.root.uuid,
        )

    def test_capability_is_scoped_by_every_declared_dimension(self):
        allowed = self.service.capability_for(
            "narrow-secret", "https://example.test", self.topic.uuid,
            self.node.uuid, "write", "text",
        )
        refused = self.service.capability_for(
            "narrow-secret", "https://example.test", self.topic.uuid,
            self.node.uuid, "write", "title",
        )
        wrong_origin = self.service.capability_for(
            "narrow-secret", "https://other.test", self.topic.uuid,
            self.node.uuid, "write", "text",
        )

        self.assertIsNotNone(allowed)
        self.assertIsNone(refused)
        self.assertIsNone(wrong_origin)

    def test_write_preserves_node_shape_and_rejects_stale_confirmation(self):
        initial = self.service.view(self.topic.uuid, self.node.uuid, "text")
        self.assertEqual(initial["adoption_policy"]["adopt"], "hold")
        changed = self.service.write(
            self.topic.uuid, self.node.uuid, "text", "pending",
            initial["content_hash"],
        )
        stale = self.service.write(
            self.topic.uuid, self.node.uuid, "text", "lost update",
            initial["content_hash"],
        )

        self.assertEqual(changed.status, "ok", changed.reason)
        self.assertEqual(stale.status, "error")
        self.assertEqual(
            self.session.get_node(self.node.uuid).data,
            {"type": GENERIC_BINDING_NODE_TYPE, "text": "pending"},
        )

    def test_application_owned_node_cannot_be_mutated_as_a_binding(self):
        application_topic = self.session.create_child(
            self.session.protocol.root.uuid,
            {"type": "initiative", "name": "Application topic"},
            {},
        ).value
        application_node = self.session.create_child(
            application_topic.uuid,
            {"type": "kanban_card", "text": "domain data"},
            {},
        ).value

        result = self.service.write(
            application_topic.uuid, application_node.uuid, "text", "bypass",
        )

        self.assertEqual(result.status, "error")
        self.assertEqual(
            self.session.get_node(application_node.uuid).data["text"],
            "domain data",
        )
        with self.assertRaisesRegex(ValueError, "not Core-owned"):
            GenericBindingService(self.session, [{
                "token": "bypass-secret",
                "origin": "https://example.test",
                "topic_uuid": application_topic.uuid,
                "node_uuid": application_node.uuid,
                "fields": ["text"],
                "operations": ["read", "write", "react"],
                "adoption": "auto",
            }])

    def test_generic_binding_topic_is_a_core_registered_shared_topic(self):
        self.assertTrue(self.session.supports_shared_topic(self.topic))
        self.assertIn(
            self.topic.uuid,
            self.session.shared_topics.local_topic_uuids(None),
        )

    def test_held_peer_change_is_exposed_and_can_be_adopted(self):
        peer = self.peer()
        peer.modify(
            self.node.uuid,
            {"type": GENERIC_BINDING_NODE_TYPE, "text": "from peer"},
            {},
        )
        self.publish(peer)

        self.assertFalse(self.service.reconcile_adoption())
        view = self.service.view(self.topic.uuid, self.node.uuid, "text")
        choice = view["transition"]["events"][0]
        adopted = self.service.react(
            self.topic.uuid, self.node.uuid, peer.address,
            choice["reaction"], False, frozenset({"text"}),
        )

        self.assertEqual(adopted.status, "ok", adopted.reason)
        self.assertEqual(
            self.session.get_node(self.node.uuid).data["text"], "from peer",
        )

    def test_held_local_change_can_be_taken_back(self):
        peer = self.peer()
        self.session.modify(
            self.node.uuid,
            {"type": GENERIC_BINDING_NODE_TYPE, "text": "local draft"},
            {},
        )
        self.session.record_peer_observations(
            peer.address,
            self.session.node_revision_map(
                self.session.protocol.index[self.topic.uuid],
            ),
        )

        view = self.service.view(self.topic.uuid, self.node.uuid, "text")
        choice = view["transition"]["events"][0]
        self.assertEqual(choice["reaction"], "rollback")
        taken_back = self.service.react(
            self.topic.uuid, self.node.uuid, peer.address,
            "rollback", False, frozenset({"text"}),
        )

        self.assertEqual(taken_back.status, "ok", taken_back.reason)
        self.assertEqual(
            self.session.get_node(self.node.uuid).data["text"], "confirmed",
        )

    def test_auto_adoption_reconciles_the_generic_node(self):
        peer = self.peer()
        peer.modify(
            self.node.uuid,
            {"type": GENERIC_BINDING_NODE_TYPE, "text": "automatic"},
            {},
        )
        self.publish(peer)
        automatic = GenericBindingService(self.session, [{
            "token": "auto-secret",
            "origin": "https://example.test",
            "topic_uuid": self.topic.uuid,
            "node_uuid": self.node.uuid,
            "fields": ["text"],
            "operations": ["read", "write", "react"],
            "adoption": "auto",
        }])

        self.assertTrue(automatic.reconcile_adoption())
        self.assertEqual(
            self.session.get_node(self.node.uuid).data["text"], "automatic",
        )

    def test_one_node_cannot_have_conflicting_capability_adoption(self):
        common = {
            "origin": "https://example.test",
            "topic_uuid": self.topic.uuid,
            "node_uuid": self.node.uuid,
            "fields": ["text"],
            "operations": ["read"],
        }
        with self.assertRaisesRegex(ValueError, "one adoption setting"):
            GenericBindingService(self.session, [
                {**common, "token": "one", "adoption": "hold"},
                {**common, "token": "two", "adoption": "auto"},
            ])
