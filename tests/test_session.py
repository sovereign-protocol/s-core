import unittest

from sovereign import LastWriteWinsPolicy
from sovereign.protocol import ProtocolNode
from sovereign.session import Session
from sovereign.signing import sign_revision


class SessionTests(unittest.TestCase):
    @staticmethod
    def perspective_pair():
        author = Session("si-author")
        observer = Session("si-observer")
        author.identity
        observer.identity
        topic = author.create_child(
            author.protocol.root.uuid, {"type": "note", "name": "Topic"}, {},
        ).value
        observer.adopt_subtree(
            ProtocolNode.from_dict(author.protocol.index[topic.uuid].to_dict()),
            observer.protocol.root.uuid,
        )
        observer.note_indirect_peer_topic(author.address, topic.uuid)
        observer.apply_peer_subtree(
            author.address, ProtocolNode.from_dict(author.identity.to_dict()), None,
        )
        return author, observer, topic

    def test_start_discussion_tracks_topic_and_members(self):
        session = Session("si-a")
        topic = session.create_child(
            session.protocol.root.uuid,
            {"name": "topic"},
            {},
        ).value

        result = session.start_discussion(topic.uuid)

        self.assertEqual(result.status, "ok")
        self.assertEqual(session.active_topic_uuid, topic.uuid)

    def test_internal_network_and_active_topic_readers_take_the_session_lock(self):
        # Both walk Session internals directly, so losing the decorator would
        # let a UI request iterate _peer_perspectives while the poller
        # inserts into it. Callers hold nothing; the readers lock themselves.
        self.assertTrue(hasattr(Session.get_network_info, "__wrapped__"))
        self.assertTrue(hasattr(Session.active_topic_uuid.fget, "__wrapped__"))

        session = Session("si-a")

        self.assertEqual(session.get_network_info()["peers"], {})
        self.assertIsNone(session.active_topic_uuid)


    def test_start_discussion_allows_multiple_topics(self):
        session = Session("si-a")
        first = session.create_child(
            session.protocol.root.uuid,
            {"name": "first"},
            {},
        ).value
        second = session.create_child(
            session.protocol.root.uuid,
            {"name": "second"},
            {},
        ).value
        session.start_discussion(first.uuid)

        result = session.start_discussion(second.uuid)

        self.assertEqual(result.status, "ok")
        self.assertEqual(session.active_topic_uuids, {first.uuid, second.uuid})

    def test_peer_registry_views_are_detached_snapshots(self):
        session = Session("si-a")
        peer_tree = ProtocolNode({"name": "peer topic"})
        session.note_indirect_peer_topic("relay:B", peer_tree.uuid)
        session.apply_peer_subtree("relay:B", peer_tree, None)

        topics = session.peer_topic_sets
        perspectives = session.peer_perspectives
        topics["relay:B"] = frozenset()
        perspectives["relay:B"].data["name"] = "changed"

        self.assertEqual(
            session.peer_topic_uuids("relay:B"), (peer_tree.uuid,),
        )
        self.assertEqual(
            session.get_cached_peer_subtree(
                "relay:B", peer_tree.uuid,
            ).data["name"],
            "peer topic",
        )

    def test_application_metadata_is_namespaced(self):
        session = Session("si-a")
        with session.lock:
            session.application_metadata("one")["selected"] = "a"

            self.assertEqual(
                session.application_metadata("one"), {"selected": "a"},
            )
            self.assertEqual(session.application_metadata("two"), {})

    def test_application_metadata_requires_the_session_lock(self):
        # The namespace is live, so an unlocked write could race
        # persistence_metadata() deep-copying the same dictionary.
        session = Session("si-a")

        with self.assertRaisesRegex(RuntimeError, "must be held"):
            session.application_metadata("one")

    def test_component_metadata_is_detached_and_updates_atomically(self):
        session = Session("si-a")
        session.update_component_metadata("relay", {
            "relay_targets": {"one": {"name": "First"}},
        })

        detached = session.component_metadata("relay")
        detached["relay_targets"]["one"]["name"] = "Changed outside Session"

        self.assertEqual(
            session.component_metadata("relay")["relay_targets"]["one"]["name"],
            "First",
        )
        updated = session.update_component_metadata("relay", {
            "relay_topic_targets": {"topic": "one"},
        })
        self.assertEqual(updated["relay_topic_targets"], {"topic": "one"})
        self.assertEqual(updated["relay_targets"]["one"]["name"], "First")

    def test_node_revision_changes_when_node_moves(self):
        session = Session("si-a")
        first = session.create_child(
            session.protocol.root.uuid, {"name": "first"}, {},
        ).value
        second = session.create_child(
            session.protocol.root.uuid, {"name": "second"}, {},
        ).value
        child = session.create_child(first.uuid, {"name": "card"}, {}).value
        child = session.protocol.index[child.uuid]
        before = session.node_revision(child)

        session.move_child(child.uuid, second.uuid)

        moved = session.protocol.index[child.uuid]
        self.assertNotEqual(before, session.node_revision(moved))

    def test_accept_topic_invitation_attaches_topic_under_other_perspectives(self):
        inviter = Session("si-a")
        topic = inviter.create_child(
            inviter.protocol.root.uuid,
            {"name": "topic"},
            {},
        ).value

        invited = Session("si-b")
        result = invited.accept_topic_invitation(ProtocolNode.from_dict(topic.to_dict()))

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.value, topic.uuid)
        self.assertEqual(invited.active_topic_uuid, topic.uuid)
        self.assertIn(topic.uuid, invited.protocol.index)
        parent = invited.protocol.index[invited.protocol.index[topic.uuid].parent_uuid]
        self.assertEqual(parent.data, {
            "type": "folder",
            "name": "other_perspectives",
        })

    def test_apply_peer_subtree_updates_peer_cache_without_http(self):
        session = Session("si-a")
        topic = ProtocolNode({"name": "topic"})
        child = ProtocolNode({"name": "child"}, parent_uuid=topic.uuid)
        topic.children.append(child)
        topic.refresh_hashes()

        session.apply_peer_subtree("si-b", topic, None)

        cached = session.get_cached_peer_subtree("si-b", child.uuid)
        self.assertIsNotNone(cached)
        self.assertEqual(cached.data["name"], "child")

    def test_analyze_peer_transition_detects_peer_made_changes(self):
        local = Session("si-a")
        peer = Session("si-b")
        topic = local.create_child(local.protocol.root.uuid, {"name": "topic"}, {}).value
        peer.accept_topic_invitation(ProtocolNode.from_dict(topic.to_dict()))
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )
        peer.modify(topic.uuid, {"name": "peer-topic"}, {})
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        events = local.analyze_peer_transitions("si-b", topic.uuid)

        self.assertEqual(events[0]["type"], "peer_made_changes")
        self.assertEqual(events[0]["node_uuid"], topic.uuid)

    def test_analyze_peer_transition_detects_in_agreement(self):
        local = Session("si-a")
        peer = Session("si-b")
        topic = local.create_child(local.protocol.root.uuid, {"name": "topic"}, {}).value
        local.modify(topic.uuid, {"name": "new-topic"}, {})
        peer.accept_topic_invitation(ProtocolNode.from_dict(
            local.protocol.index[topic.uuid].to_dict()
        ))
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        events = local.analyze_peer_transitions("si-b", topic.uuid)

        self.assertEqual(events[0]["type"], "in_agreement")

    def test_analyze_peer_transition_detects_divergence(self):
        local = Session("si-a")
        peer = Session("si-b")
        local_identity = local.identity.data["identity_key"]
        peer_identity = peer.identity.data["identity_key"]
        local.set_peer_identity_key("si-b", peer_identity)
        peer.set_peer_identity_key("si-a", local_identity)
        topic = local.create_child(local.protocol.root.uuid, {"name": "topic"}, {}).value
        peer.accept_topic_invitation(ProtocolNode.from_dict(topic.to_dict()))
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )
        local.modify(topic.uuid, {"name": "local"}, {})
        peer.modify(topic.uuid, {"name": "peer"}, {})
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        events = local.analyze_peer_transitions("si-b", topic.uuid)

        self.assertEqual(events[0]["type"], "divergence")

    def test_analyze_peer_transition_detects_local_missing_node(self):
        local = Session("si-a")
        peer = Session("si-b")
        topic = local.create_child(local.protocol.root.uuid, {"name": "topic"}, {}).value
        peer.accept_topic_invitation(ProtocolNode.from_dict(topic.to_dict()))
        child = peer.create_child(topic.uuid, {"name": "peer child"}, {}).value
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        events = local.analyze_peer_transitions("si-b", child.uuid)

        self.assertEqual(events[0]["type"], "local_missing_node")

    def test_analyze_peer_transition_detects_peer_missing_node(self):
        local = Session("si-a")
        peer = Session("si-b")
        topic = local.create_child(local.protocol.root.uuid, {"name": "topic"}, {}).value
        peer.accept_topic_invitation(ProtocolNode.from_dict(topic.to_dict()))
        child = local.create_child(topic.uuid, {"name": "local child"}, {}).value
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        events = local.analyze_peer_transitions("si-b", child.uuid)

        self.assertEqual(events[0]["type"], "peer_missing_node")
        self.assertEqual(events[0]["stage"], "in_flight")

    def test_analyze_peer_transition_compounds_multiple_unsynced_edits(self):
        local = Session("si-a")
        peer = Session("si-c")
        topic = local.create_child(local.protocol.root.uuid, {"name": "topic"}, {}).value
        peer.accept_topic_invitation(ProtocolNode.from_dict(topic.to_dict()))
        local.apply_peer_subtree(
            "si-c",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        peer.modify(topic.uuid, {"name": "peer-first"}, {})
        peer.modify(topic.uuid, {"name": "peer-second"}, {})
        local.apply_peer_subtree(
            "si-c",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        events = local.analyze_peer_transitions("si-c", topic.uuid)

        self.assertEqual(events[0]["type"], "peer_made_changes")

    def test_observed_peer_revert_to_an_earlier_value_is_a_newer_change(self):
        local = Session("si-a")
        peer = Session("si-b")
        local.identity
        peer.identity
        topic = local.create_child(
            local.protocol.root.uuid, {"name": "topic"}, {},
        ).value
        child = local.create_child(
            topic.uuid, {"name": "Doing"}, {},
        ).value
        peer.accept_topic_invitation(ProtocolNode.from_dict(topic.to_dict()))

        local.modify(child.uuid, {"name": "Doings"}, {})
        peer.apply_peer_subtree(
            "si-a",
            ProtocolNode.from_dict(local.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )
        peer.set_topic_adoption_default(
            topic.uuid, adopt="auto", additions="auto",
        )
        self.assertTrue(peer.reconcile_peer_changes("si-a", topic.uuid))
        peer.modify(child.uuid, {"name": "Doing"}, {})

        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )
        local.record_peer_observations("si-b", {
            child.uuid: Session.node_revision(local.protocol.index[child.uuid]),
        })

        events = local.analyze_peer_transitions("si-b", topic.uuid)
        child_event = next(
            event for event in events if event["node_uuid"] == child.uuid
        )

        self.assertEqual(child_event["type"], "peer_made_changes")
        local.set_topic_adoption_default(
            topic.uuid, adopt="auto", additions="auto",
        )
        self.assertTrue(local.reconcile_peer_changes("si-b", topic.uuid))
        self.assertEqual(
            local.protocol.index[child.uuid].data["name"], "Doing",
        )

    @staticmethod
    def _node(state_hash, base_hash, parent_uuid, base_parent_uuid,
              origin=None, revision_seq=0):
        node = ProtocolNode({"name": "x"})
        node.state_hash = state_hash
        node.base_hash = base_hash
        node.parent_uuid = parent_uuid
        node.base_parent_uuid = base_parent_uuid
        node.revision_origin = origin
        node.revision_seq = revision_seq
        return node

    def test_opposing_moves_are_divergence(self):
        local_node = self._node("h0", "h0", "doing", "todo")
        peer_node = self._node("h0", "h0", "todo", "doing")
        local_node.updated_at = "2026-01-01T00:00:00.000+00:00"
        peer_node.updated_at = "2026-01-01T00:00:00.000+00:00"

        self.assertEqual(Session._classify_move(local_node, peer_node), "divergence")
        self.assertEqual(Session._classify_node(local_node, peer_node), "divergence")

    def test_opposing_moves_use_newer_timestamp_as_clean_move(self):
        local_node = self._node("h0", "h0", "todo", "doing")
        peer_node = self._node("h0", "h0", "doing", "todo")
        local_node.updated_at = "2026-01-01T00:00:00.000+00:00"
        peer_node.updated_at = "2026-01-01T00:00:01.000+00:00"

        self.assertEqual(Session._classify_move(local_node, peer_node), "peer_made_changes")

    def test_move_direction_disambiguates_content_hash_cycle(self):
        local_node = self._node(
            "local-content", "peer-content", "todo", "backlog",
            "identity-a", 19,
        )
        peer_node = self._node(
            "peer-content", "local-content", "doing", "todo",
            "identity-c", 46,
        )
        local_node.content_hash = "local-content"
        peer_node.content_hash = "peer-content"

        self.assertEqual(
            Session._classify_content(local_node, peer_node),
            "local_made_changes",
        )
        self.assertEqual(
            Session._classify_move(local_node, peer_node),
            "peer_made_changes",
        )
        self.assertEqual(
            Session._classify_node(local_node, peer_node),
            "peer_made_changes",
        )

    def test_content_direction_disambiguates_parent_cycle(self):
        local_node = self._node(
            "local-content", "base-content", "todo", "doing",
            "identity-a", 19,
        )
        peer_node = self._node(
            "peer-content", "local-content", "doing", "todo",
            "identity-c", 46,
        )
        local_node.content_hash = "local-content"
        peer_node.content_hash = "peer-content"
        local_node.updated_at = "2026-01-01T00:00:01.000+00:00"
        peer_node.updated_at = "2026-01-01T00:00:00.000+00:00"

        self.assertEqual(
            Session._classify_content(local_node, peer_node),
            "peer_made_changes",
        )
        self.assertEqual(
            Session._classify_move(local_node, peer_node),
            "local_made_changes",
        )
        self.assertEqual(
            Session._classify_node(local_node, peer_node),
            "peer_made_changes",
        )

    def test_same_origin_sequence_orders_content_without_clock_comparison(self):
        local_node = self._node(
            "local", "base", "doing", "done", "origin-b", 10,
        )
        peer_node = self._node(
            "peer", "base", "doing", "done", "origin-b", 11,
        )
        local_node.content_hash = "local"
        peer_node.content_hash = "peer"
        local_node.updated_at = "2026-01-01T00:00:10.000+00:00"
        peer_node.updated_at = "2026-01-01T00:00:00.000+00:00"

        self.assertEqual(
            Session._classify_content(local_node, peer_node),
            "peer_made_changes",
        )

    def test_same_origin_sequence_orders_repeated_move_without_clock_comparison(self):
        local_node = self._node(
            "h0", "h0", "doing", "done", "origin-b", 10,
        )
        peer_node = self._node(
            "h0", "h0", "todo", "done", "origin-b", 11,
        )
        local_node.updated_at = "2026-01-01T00:00:10.000+00:00"
        peer_node.updated_at = "2026-01-01T00:00:00.000+00:00"

        self.assertEqual(
            Session._classify_move(local_node, peer_node),
            "peer_made_changes",
        )

    def test_transition_staging_waits_for_peer_observation(self):
        event = {
            "type": "local_made_changes",
            "node_uuid": "n1",
            "peer_observed_local_revision": False,
        }

        waiting = Session._stage_transition_event(event)
        confirmed = Session._stage_transition_event({
            **event, "peer_observed_local_revision": True,
        })

        # The relation is the same either way - it is my change in both. Only
        # how far it has travelled differs, and neither is a conflict.
        self.assertEqual(waiting["type"], "local_made_changes")
        self.assertEqual(waiting["stage"], "in_flight")
        self.assertEqual(confirmed["type"], "local_made_changes")
        self.assertEqual(confirmed["stage"], "awaiting_peer")

    def test_competing_origins_confirm_divergence_immediately(self):
        event = {
            "type": "divergence",
            "node_uuid": "n1",
            "local_revision_origin": "identity-a",
            "peer_revision_origin": "identity-b",
            "peer_observed_local_revision": False,
        }

        self.assertEqual(
            Session._stage_transition_event(event)["type"], "divergence",
        )

    def test_peer_change_is_actionable_without_debounce(self):
        event = {
            "type": "peer_made_changes",
            "node_uuid": "n1",
            "peer_observed_local_revision": False,
        }

        self.assertEqual(
            Session._stage_transition_event(event)["type"], "peer_made_changes",
        )


    def test_apply_peer_subtree_update_propagates_deleted_flag_and_history(self):
        local = Session("si-a")
        peer = Session("si-b")
        topic = peer.create_child(peer.protocol.root.uuid, {"name": "topic"}, {}).value
        child = peer.create_child(topic.uuid, {"name": "child"}, {}).value
        peer.start_discussion(topic.uuid)
        peer.note_indirect_peer_topic("si-a", topic.uuid)
        local.note_indirect_peer_topic("si-b", topic.uuid)
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            peer.protocol.root.uuid,
        )

        peer.modify(child.uuid, {"name": "renamed"}, {})
        peer.delete(child.uuid)
        # Pull just the changed node, hitting the update-in-place merge path.
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[child.uuid].to_dict()),
            topic.uuid,
        )

        cached_child = local.get_cached_peer_subtree("si-b", child.uuid)
        peer_child = peer.protocol.index[child.uuid]
        self.assertTrue(cached_child.deleted)
        self.assertEqual(cached_child.base_hash, peer_child.base_hash)
        # If the merge left a stale deleted flag, the cache's recomputed
        # topic hash would never match what the peer reports, causing an
        # endless re-pull loop.
        self.assertEqual(
            local.get_cached_peer_subtree("si-b", topic.uuid).state_hash,
            peer.protocol.index[topic.uuid].state_hash,
        )

    def test_delete_flags_node_and_waits_for_peer_confirmation_before_pruning(self):
        local = Session("si-a")
        topic = local.create_child(local.protocol.root.uuid, {"name": "topic"}, {}).value
        child = local.create_child(topic.uuid, {"name": "child"}, {}).value
        stale_topic = ProtocolNode.from_dict(local.protocol.index[topic.uuid].to_dict())
        local.start_discussion(topic.uuid)
        local.note_indirect_peer_topic("si-b", topic.uuid)

        result = local.delete(child.uuid)

        self.assertEqual(result.status, "ok")
        self.assertIn(child.uuid, local.protocol.index)
        self.assertTrue(local.protocol.index[child.uuid].deleted)

        # Peer's cache still shows the pre-delete state - not confirmed yet,
        # so the flagged node must stay in the tree.
        local.apply_peer_subtree("si-b", stale_topic, local.protocol.root.uuid)
        self.assertIn(child.uuid, local.protocol.index)

        # Once the peer's cache also shows the node deleted, it can be pruned.
        current_topic = ProtocolNode.from_dict(local.protocol.index[topic.uuid].to_dict())
        local.apply_peer_subtree("si-b", current_topic, local.protocol.root.uuid)

        self.assertNotIn(child.uuid, local.protocol.index)

    def test_delete_without_topic_peers_prunes_immediately(self):
        local = Session("si-a")
        topic = local.create_child(local.protocol.root.uuid, {"name": "topic"}, {}).value
        child = local.create_child(topic.uuid, {"name": "child"}, {}).value
        local.start_discussion(topic.uuid)

        result = local.delete(child.uuid)

        self.assertEqual(result.status, "ok")
        self.assertNotIn(child.uuid, local.protocol.index)


    def test_leave_topic_removes_only_that_topic(self):
        # Nothing is sent. A peer on a relay learns this side has gone by
        # its slot going quiet, not by being told.
        session = Session("si-a")
        session.note_indirect_peer_topic("relay:B", "topic-1")
        session.note_indirect_peer_topic("relay:B", "topic-2")
        session.note_indirect_peer_topic("relay:C", "topic-1")
        session.bind_peer_topics_channel(
            "relay:B", {"topic-1", "topic-2"}, "mailbox",
        )
        session.bind_peer_topic_channel("relay:C", "topic-1", "mailbox")

        result = session.leave_topic("topic-1")

        self.assertEqual(result.effects, [])
        self.assertEqual(session.peer_topic_sets["relay:B"], {"topic-2"})
        self.assertNotIn("relay:C", session.peer_topic_sets)
        self.assertIsNone(
            session.peer_channel_for_topic("relay:B", "topic-1"),
        )

    def test_remove_peer_clears_only_that_peer(self):
        session = Session("si-a")
        session.note_indirect_peer_topic("relay:B", "topic-1")
        session.note_indirect_peer_topic("relay:B", "topic-2")
        session.note_indirect_peer_topic("relay:C", "topic-1")
        bob_session = Session("si-b")
        bob_session.set_identity("Bob")
        session.apply_peer_identity_snapshot("relay:B", bob_session.identity.to_dict())
        session.bind_peer_topics_channel(
            "relay:B", {"topic-1", "topic-2"}, "mailbox",
        )

        session.remove_peer("relay:B")

        self.assertNotIn("relay:B", session.peer_topic_sets)
        self.assertNotIn("relay:B", session.peer_perspectives)
        self.assertNotIn("relay:B", session.peer_topic_channel)
        # Unrelated peer untouched.
        self.assertEqual(session.peer_topic_sets["relay:C"], {"topic-1"})

    def test_remove_peer_on_unknown_address_is_a_no_op(self):
        session = Session("si-a")
        session.note_indirect_peer_topic("relay:B", "topic-1")

        session.remove_peer("si-nobody")

        self.assertIn("relay:B", session.peer_topic_sets)

    def test_identity_is_lazily_created_and_stable(self):
        # No InitiativeLogic/app involved at all - identity is a Session-owned
        # meta-topic, so any app (or none) gets it for free.
        session = Session("si-a")

        profile = session.identity

        self.assertEqual(profile.data["type"], "shared_user_profile")
        self.assertEqual(profile.data["profile_schema_version"], 2)
        self.assertEqual(len(profile.data["signing_key_events"]), 1)
        self.assertEqual(session.revision_verification(profile), "valid")
        self.assertTrue(profile.data["identity_key"])
        self.assertNotIn("email", profile.data)
        self.assertEqual(profile.data["display_name"], "")
        self.assertEqual(session.identity.uuid, profile.uuid)
        self.assertEqual(
            session.identity.data["identity_key"], profile.data["identity_key"],
        )

    def test_signed_revision_verifies_and_forged_content_does_not(self):
        alice = Session("si-a")
        alice.identity
        revision = alice.create_child(
            alice.protocol.root.uuid, {"type": "note", "text": "Original"}, {},
        ).value
        bob = Session("si-b")
        bob.apply_peer_identity_snapshot("si-a", alice.identity.to_dict())

        self.assertEqual(bob.revision_verification(revision), "valid")

        payload = revision.to_dict()
        payload["data"]["text"] = "Forged"
        forged = ProtocolNode.from_dict(payload, repair_hashes=True)
        self.assertEqual(bob.revision_verification(forged), "invalid")
        bob.apply_peer_subtree("si-a-data", forged, None)
        observed = bob.get_cached_peer_subtree("si-a-data", forged.uuid)
        self.assertEqual(observed.data["text"], "Forged")
        self.assertEqual(bob.revision_verification(observed), "invalid")
        unknown_key = ProtocolNode.from_dict(revision.to_dict())
        unknown_key.revision_key_id = "ed25519:" + "0" * 64
        self.assertEqual(bob.revision_verification(unknown_key), "unknown")
        self.assertEqual(Session("si-c").revision_verification(revision), "unknown")
        self.assertEqual(
            bob.revision_verification(ProtocolNode({"type": "note"})), "invalid",
        )

    def test_every_local_mutation_shape_refreshes_its_signature(self):
        session = Session("si-a")
        session.identity
        first = session.create_child(
            session.protocol.root.uuid, {"type": "folder", "name": "First"}, {},
        ).value
        second = session.create_child(
            session.protocol.root.uuid, {"type": "folder", "name": "Second"}, {},
        ).value
        child = session.create_child(
            first.uuid, {"type": "note", "text": "Initial"}, {},
        ).value

        session.modify(child.uuid, {**child.data, "text": "Changed"}, child.weights)
        self.assertEqual(
            session.revision_verification(session.protocol.index[child.uuid]), "valid",
        )
        session.move(child.uuid, second.uuid)
        moved = session.protocol.index[child.uuid]
        moved_topic = session.protocol.index[second.uuid]
        self.assertEqual(moved.revision_parent_uuid, second.uuid)
        self.assertEqual(session.revision_verification(moved), "valid")

        copied = session.copy(child.uuid, first.uuid).value
        self.assertEqual(session.revision_verification(copied), "valid")

        session.note_indirect_peer_topic("si-peer", second.uuid)
        session.apply_peer_subtree("si-peer", moved_topic, None)
        session.delete(child.uuid)
        deleted = session.protocol.index.get(child.uuid)
        self.assertIsNotNone(deleted)
        self.assertTrue(deleted.deleted)
        self.assertEqual(session.revision_verification(deleted), "valid")

    def test_rotation_and_sibling_revocation_follow_the_identity_key_chain(self):
        alice = Session("si-a")
        alice.identity
        old_key_id = alice.signing_key_id
        old_revision = alice.create_child(
            alice.protocol.root.uuid, {"type": "note", "text": "Old"}, {},
        ).value

        rotated = alice.rotate_signing_key()
        self.assertEqual(rotated.status, "ok")
        self.assertNotEqual(alice.signing_key_id, old_key_id)
        new_revision = alice.create_child(
            alice.protocol.root.uuid, {"type": "note", "text": "New"}, {},
        ).value
        observer = Session("si-observer")
        observer.apply_peer_identity_snapshot("si-a", alice.identity.to_dict())
        self.assertEqual(observer.revision_verification(old_revision), "valid")
        self.assertEqual(observer.revision_verification(new_revision), "valid")

        pre_revocation_profile = alice.identity
        revoked = alice.revoke_signing_key(old_key_id)
        self.assertEqual(revoked.status, "ok")
        observer.apply_peer_identity_snapshot("si-a", alice.identity.to_dict())
        self.assertEqual(observer.revision_verification(old_revision), "invalid")
        self.assertEqual(observer.revision_verification(new_revision), "valid")
        observer.apply_peer_identity_snapshot(
            "si-a", pre_revocation_profile.to_dict(),
        )
        self.assertEqual(observer.revision_verification(old_revision), "invalid")
        self.assertEqual(
            alice.revoke_signing_key(alice.signing_key_id).status, "error",
        )
        profile = alice.identity
        data = dict(profile.data)
        data["signing_key_events"] = data["signing_key_events"][1:]
        self.assertEqual(
            alice.modify(profile.uuid, data, profile.weights).status, "error",
        )

    def test_pairing_authorizes_a_distinct_device_signer(self):
        desktop = Session("si-desktop")
        desktop.identity
        issued = desktop.issue_sibling_signing_key()
        self.assertEqual(issued.status, "ok")
        laptop = Session("si-laptop")
        self.assertEqual(
            laptop.adopt_pairing_identity(desktop.identity.to_dict()).status, "ok",
        )
        self.assertEqual(
            laptop.install_sibling_signing_key(issued.value).status, "ok",
        )
        self.assertNotEqual(laptop.signing_key_id, desktop.signing_key_id)
        revision = laptop.create_child(
            laptop.protocol.root.uuid, {"type": "note", "text": "Laptop"}, {},
        ).value
        observer = Session("si-observer")
        observer.apply_peer_identity_snapshot(
            "si-desktop", desktop.identity.to_dict(),
        )
        self.assertEqual(observer.revision_verification(revision), "valid")

    def test_set_identity_updates_display_fields(self):
        session = Session("si-a")

        result = session.set_identity("Alice", "https://example.test/a.png")

        self.assertEqual(result.status, "ok")
        profile = session.identity
        self.assertEqual(profile.data["display_name"], "Alice")
        self.assertEqual(profile.data["picture"], "https://example.test/a.png")

    def test_core_identity_excludes_contact_information(self):
        session = Session("si-a")
        identity_key = session.identity.data["identity_key"]

        session.set_identity("Alice")

        profile = session.identity
        self.assertNotIn("email", profile.data)
        self.assertEqual(profile.data["identity_key"], identity_key)

    def test_core_identity_rejects_contact_fields(self):
        session = Session("si-a")
        profile = session.identity
        data = dict(profile.data)
        data["email"] = "alice@example.test"

        result = session.modify(profile.uuid, data, profile.weights)

        self.assertEqual(result.status, "error")
        self.assertIn("email", result.reason)
        self.assertNotIn("email", session.identity.data)

    def test_find_peer_identity_searches_cached_peer_perspectives(self):
        session = Session("si-a")
        peer_profile = ProtocolNode({
            "type": "shared_user_profile",
            "name": "public_profile",
            "profile_schema_version": 1,
            "identity_key": "key-b",
            "display_name": "Bob",
            "picture": "",
        })
        peer_profile.refresh_hashes()
        session.apply_peer_subtree("si-b", peer_profile, None)

        found = session.find_peer_identity("key-b")

        self.assertIsNotNone(found)
        self.assertEqual(found.data["display_name"], "Bob")
        self.assertIsNone(session.find_peer_identity("key-c"))

    def test_find_peer_identity_survives_address_change(self):
        # The whole point of keying identity lookup by identity_key instead
        # of address: the same identity, cached under two different
        # peer_perspectives dict keys (simulating Bob reconnecting from a
        # new address), must still resolve to one identity.
        session = Session("si-a")
        bob_v1 = ProtocolNode({
            "type": "shared_user_profile", "name": "public_profile",
            "profile_schema_version": 1, "identity_key": "key-bob",
            "display_name": "Bob", "picture": "",
        })
        bob_v1.refresh_hashes()
        session.apply_peer_subtree("old-address", bob_v1, None)
        bob_v2 = ProtocolNode({
            "type": "shared_user_profile", "name": "public_profile",
            "profile_schema_version": 1, "identity_key": "key-bob",
            "display_name": "Bob", "picture": "",
        })
        bob_v2.refresh_hashes()
        session.apply_peer_subtree("new-address", bob_v2, None)

        found = session.find_peer_identity("key-bob")

        self.assertIsNotNone(found)
        self.assertEqual(found.data["display_name"], "Bob")

    def test_known_identity_uses_newest_verified_avatar_across_addresses(self):
        bob = Session("bob")
        bob.set_identity("Bob", picture="old-avatar")
        old_profile = ProtocolNode.from_dict(bob.identity.to_dict())
        bob.set_identity("Bob", picture="new-avatar")
        new_profile = ProtocolNode.from_dict(bob.identity.to_dict())

        observer = Session("observer")
        observer.identity
        # The stale address sorts first, reproducing Agenda's former
        # first-address-wins lookup. The newest profile is cached elsewhere.
        observer.apply_peer_subtree("a-stale", old_profile, None)
        observer.apply_peer_subtree("z-current", new_profile, None)

        resolved = observer.find_peer_identity(
            bob.identity.data["identity_key"],
        )
        known = next(
            item for item in observer.known_identities()
            if item["uuid"] == bob.identity.uuid
        )

        self.assertEqual(resolved.data["picture"], "new-avatar")
        self.assertEqual(
            observer.peer_identity("a-stale").data["picture"], "new-avatar",
        )
        self.assertEqual(known["picture"], "new-avatar")
        self.assertEqual(known["addresses"], ["a-stale", "z-current"])

    def test_invalid_high_sequence_profile_cannot_replace_verified_avatar(self):
        bob = Session("bob")
        bob.set_identity("Bob", picture="current-avatar")
        current = ProtocolNode.from_dict(bob.identity.to_dict())
        forged = ProtocolNode.from_dict(current.to_dict())
        forged.data["picture"] = "forged-avatar"
        forged.revision_seq += 1000
        forged.updated_at = "2099-01-01T00:00:00+00:00"
        forged.refresh_hashes()

        observer = Session("observer")
        observer.identity
        observer.apply_peer_subtree("a-forged", forged, None)
        observer.apply_peer_subtree("z-valid", current, None)

        resolved = observer.find_peer_identity(
            bob.identity.data["identity_key"],
        )

        self.assertEqual(resolved.data["picture"], "current-avatar")
        self.assertEqual(
            observer.known_identities()[1]["picture"], "current-avatar",
        )

    def test_competing_self_signed_identity_chain_cannot_replace_trusted_avatar(self):
        bob = Session("bob")
        bob.set_identity("Bob", picture="trusted-avatar")
        trusted = ProtocolNode.from_dict(bob.identity.to_dict())

        attacker = Session("attacker")
        forged = ProtocolNode.from_dict(attacker.identity.to_dict())
        forged.uuid = trusted.uuid
        forged.data["identity_key"] = trusted.data["identity_key"]
        forged.data["display_name"] = "Not Bob"
        forged.data["picture"] = "forged-avatar"
        forged.revision_origin = trusted.revision_origin
        forged.revision_seq = trusted.revision_seq + 1000
        forged.updated_at = "2099-01-01T00:00:00+00:00"
        forged.refresh_hashes()
        sign_revision(forged, attacker._signing_keypair)

        observer = Session("observer")
        observer.identity
        observer.apply_peer_subtree("z-trusted", trusted, None)
        observer.apply_peer_subtree("a-forged", forged, None)

        resolved = observer.find_peer_identity(
            trusted.data["identity_key"],
        )

        self.assertEqual(resolved.data["picture"], "trusted-avatar")
        self.assertEqual(resolved.data["display_name"], "Bob")

    def test_set_peer_identity_key_records_and_overwrites(self):
        session = Session("si-a")

        session.set_peer_identity_key("relay:B", "key-bob")
        self.assertEqual(session.peer_identity_key["relay:B"], "key-bob")

        session.set_peer_identity_key("relay:B", "key-other")
        self.assertEqual(session.peer_identity_key["relay:B"], "key-other")

        # Blank inputs are ignored, never stored.
        session.set_peer_identity_key("", "key-x")
        session.set_peer_identity_key("addr-x", "")
        self.assertNotIn("", session.peer_identity_key)
        self.assertNotIn("addr-x", session.peer_identity_key)

    def test_addresses_for_identity_returns_all_matches_sorted(self):
        session = Session("si-a")
        session.set_peer_identity_key("relay:B", "key-bob")
        session.set_peer_identity_key("http://addr-b", "key-bob")
        session.set_peer_identity_key("http://addr-c", "key-carol")

        self.assertEqual(
            session.addresses_for_identity("key-bob"),
            ["http://addr-b", "relay:B"],
        )
        self.assertEqual(session.addresses_for_identity("key-nobody"), [])

    def test_actor_uuid_resolves_to_the_verified_identity_key_namespace(self):
        alice = Session("si-a")
        bob = Session("si-b")
        alice.apply_peer_identity_snapshot("si-b", bob.identity.to_dict())

        self.assertEqual(
            alice.identity_key_for_actor(alice.identity.uuid),
            alice.identity.data["identity_key"],
        )
        self.assertEqual(
            alice.identity_key_for_actor(bob.identity.uuid),
            bob.identity.data["identity_key"],
        )
        self.assertIsNone(alice.identity_key_for_actor("unknown-actor"))

    def test_known_identity_resolves_profile_across_transport_addresses(self):
        session = Session("si-a")
        bob = ProtocolNode({
            "type": "shared_user_profile", "name": "public_profile",
            "profile_schema_version": 1, "identity_key": "key-bob",
            "display_name": "Bob", "picture": "",
        })
        bob.refresh_hashes()
        session.apply_peer_subtree("relay:identity-home", bob, None)
        session.set_peer_identity_key("relay:board-home", "key-bob")
        session.note_indirect_peer_topic("relay:board-home", "board")

        identities = session.known_identities()
        remote = next(item for item in identities if item["uuid"] == bob.uuid)

        self.assertEqual(remote["name"], "Bob")
        self.assertEqual(
            remote["addresses"],
            ["relay:board-home", "relay:identity-home"],
        )

    def test_forget_peer_address_removes_a_new_own_publication_slot(self):
        session = Session("si-a")
        session.note_indirect_peer_topic("relay:paired", "board")
        session.set_peer_identity_key("relay:paired", "old-peer-key")
        session.peer_observed_node_revisions["relay:paired"] = {"node": "rev"}

        session.forget_peer_address("relay:paired")

        self.assertNotIn("relay:paired", session.peer_topic_sets)
        self.assertNotIn("relay:paired", session.peer_identity_key)
        self.assertNotIn(
            "relay:paired", session.peer_observed_node_revisions,
        )

    def test_apply_peer_subtree_records_identity_key_for_profile_roots(self):
        session = Session("si-a")
        bob = ProtocolNode({
            "type": "shared_user_profile", "name": "public_profile",
            "profile_schema_version": 1, "identity_key": "key-bob",
            "display_name": "Bob", "picture": "",
        })
        bob.refresh_hashes()

        session.apply_peer_subtree("relay:B", bob, None)

        self.assertEqual(session.peer_identity_key.get("relay:B"), "key-bob")

    def test_apply_peer_subtree_ignores_non_identity_roots(self):
        session = Session("si-a")
        board = ProtocolNode({"type": "kanban_board", "name": "Board"})
        board.refresh_hashes()

        session.apply_peer_subtree("http://addr-b", board, None)

        self.assertEqual(session.peer_identity_key, {})

    def test_remove_peer_keeps_the_identity_registry_entry(self):
        # Knowledge, not registration: tearing down a peer's registration
        # must not erase the fact that its address belongs to an identity -
        # It stays true after the teardown, and could not be re-learned
        # from content once forgotten.
        session = Session("si-a")
        session.note_indirect_peer_topic("relay:B", "topic-1")
        session.set_peer_identity_key("relay:B", "key-bob")

        session.remove_peer("relay:B")

        self.assertNotIn("relay:B", session.peer_topic_sets)
        self.assertEqual(session.peer_identity_key.get("relay:B"), "key-bob")

    def test_peer_identity_scoped_to_one_address(self):
        session = Session("si-a")
        bob = ProtocolNode({
            "type": "shared_user_profile", "name": "public_profile",
            "profile_schema_version": 1, "identity_key": "key-bob",
            "display_name": "Bob", "picture": "",
        })
        bob.refresh_hashes()
        session.apply_peer_subtree("addr-bob", bob, None)

        self.assertEqual(session.peer_identity("addr-bob").data["display_name"], "Bob")
        self.assertIsNone(session.peer_identity("addr-nobody"))

    def test_apply_peer_identity_snapshot_caches_unconditionally(self):
        session = Session("si-a")
        bob_session = Session("si-b")
        bob_session.set_identity("Bob")
        payload = bob_session.identity.to_dict()

        session.apply_peer_identity_snapshot("si-b", payload)

        cached = session.find_peer_identity(payload["data"]["identity_key"])
        self.assertIsNotNone(cached)
        self.assertEqual(cached.data["display_name"], "Bob")
        self.assertEqual(
            session.peer_identity_key.get("si-b"),
            payload["data"]["identity_key"],
        )

    def test_apply_peer_identity_snapshot_ignores_unrecognized_version(self):
        session = Session("si-a")
        bob_session = Session("si-b")
        bob_session.set_identity("Bob")
        payload = bob_session.identity.to_dict()
        payload["data"]["profile_schema_version"] = 99

        session.apply_peer_identity_snapshot("si-b", payload)

        self.assertEqual(session.peer_perspectives, {})

    def test_apply_peer_identity_snapshot_ignores_malformed_input(self):
        session = Session("si-a")

        session.apply_peer_identity_snapshot("si-b", {"not": "a real node"})
        session.apply_peer_identity_snapshot("si-c", "not even a dict")

        self.assertEqual(session.peer_perspectives, {})

    def test_is_identity_node(self):
        session = Session("si-a")

        self.assertTrue(session.is_identity_node(session.identity))
        other = session.create_child(
            session.protocol.root.uuid, {"type": "folder", "name": "x"}, {},
        ).value
        self.assertFalse(session.is_identity_node(other))
        self.assertFalse(session.is_identity_node(None))

    # reconcile_peer_changes / accept_peer_node / peer_discusses_node -
    # generic peer-content reconciliation, generalized out of
    # kanban_logic.py's adopt_incoming_changes. Deliberately exercised here
    # with non-kanban node types ("note"/"note_item"/"leaf") to prove the
    # mechanism carries no kanban-specific assumptions.

    def test_peer_discusses_node(self):
        session = Session("si-a")
        topic = session.create_child(
            session.protocol.root.uuid, {"type": "note", "name": "t"}, {},
        ).value
        child = session.create_child(topic.uuid, {"type": "note_item"}, {}).value
        session.note_indirect_peer_topic("si-b", topic.uuid)

        self.assertTrue(session.peer_discusses_node("si-b", child.uuid))
        self.assertFalse(session.peer_discusses_node("si-b", "no-such-uuid"))
        self.assertFalse(session.peer_discusses_node("si-c", child.uuid))

    def test_accept_peer_node_adopts_and_deletes_on_absence(self):
        peer = Session("si-b")
        topic = peer.create_child(
            peer.protocol.root.uuid, {"type": "note", "name": "t"}, {},
        ).value
        local = Session("si-a")
        local.adopt_subtree(
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )
        child = peer.create_child(topic.uuid, {"type": "note_item", "text": "x"}, {}).value
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        result = local.accept_peer_node("si-b", child.uuid)
        self.assertEqual(result.status, "ok")
        self.assertIn(child.uuid, local.protocol.index)
        self.assertEqual(local.protocol.index[child.uuid].data["text"], "x")

        result = local.accept_peer_node("si-b", child.uuid, adopt_absence=True)
        self.assertEqual(result.status, "ok")
        self.assertNotIn(child.uuid, local.protocol.index)

    def test_rollback_restores_my_exact_revision_still_held_by_peer(self):
        local = Session("si-a")
        local_identity = local.identity.data["identity_key"]
        topic = local.create_child(
            local.protocol.root.uuid, {"type": "note", "name": "t"}, {},
        ).value
        child = local.create_child(
            topic.uuid, {"type": "note_item", "text": "original"}, {},
        ).value
        peer_copy = ProtocolNode.from_dict(
            local.protocol.index[topic.uuid].to_dict(),
        )
        local.apply_peer_subtree("si-b", peer_copy, local.protocol.root.uuid)
        peer_child = local.get_cached_peer_subtree("si-b", child.uuid)

        local.modify(child.uuid, {"type": "note_item", "text": "first"}, {})
        local.modify(child.uuid, {"type": "note_item", "text": "second"}, {})
        changed = local.protocol.index[child.uuid]
        self.assertEqual(changed.revision_origin, local_identity)
        self.assertEqual(changed.base_hash, peer_child.base_hash)

        result = local.rollback_peer_node("si-b", child.uuid)

        self.assertEqual(result.status, "ok")
        rolled_back = local.protocol.index[child.uuid]
        self.assertEqual(rolled_back.data["text"], "original")
        self.assertEqual(rolled_back.state_hash, peer_child.state_hash)
        self.assertEqual(rolled_back.base_hash, peer_child.base_hash)
        self.assertEqual(rolled_back.revision_origin, local_identity)

    def test_rollback_rejects_another_origins_revision(self):
        peer = Session("si-b")
        peer.identity
        topic = peer.create_child(
            peer.protocol.root.uuid, {"type": "note", "name": "t"}, {},
        ).value
        local = Session("si-a")
        local.identity
        local.adopt_subtree(
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )
        local.apply_peer_subtree(
            "si-b", ProtocolNode.from_dict(topic.to_dict()), local.protocol.root.uuid,
        )

        result = local.rollback_peer_node("si-b", topic.uuid)

        self.assertEqual(result.status, "error")
        self.assertIn("not mine", result.reason)

    def test_reconcile_peer_changes_no_cached_subtree_is_a_no_op(self):
        session = Session("si-a")
        self.assertFalse(session.reconcile_peer_changes("si-b", "no-such-topic"))

    def test_reconcile_peer_changes_adopts_eligible_change_by_default(self):
        peer = Session("si-b")
        topic = peer.create_child(
            peer.protocol.root.uuid, {"type": "note", "name": "t"}, {},
        ).value
        child = peer.create_child(topic.uuid, {"type": "note_item", "text": "original"}, {}).value
        local = Session("si-a")
        local.adopt_subtree(
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        peer.modify(child.uuid, {"type": "note_item", "text": "updated"}, {})
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        local.set_topic_adoption_default(
            topic.uuid, adopt="auto", additions="auto",
        )
        changed = local.reconcile_peer_changes("si-b", topic.uuid)

        self.assertTrue(changed)
        self.assertEqual(local.protocol.index[child.uuid].data["text"], "updated")

    def test_reconcile_peer_changes_respects_node_is_eligible(self):
        peer = Session("si-b")
        topic = peer.create_child(
            peer.protocol.root.uuid, {"type": "note", "name": "t"}, {},
        ).value
        child = peer.create_child(topic.uuid, {"type": "note_item", "text": "original"}, {}).value
        local = Session("si-a")
        local.adopt_subtree(
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        peer.modify(child.uuid, {"type": "note_item", "text": "updated"}, {})
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        local.set_topic_adoption_default(
            topic.uuid, adopt="auto", additions="auto",
        )
        changed = local.reconcile_peer_changes(
            "si-b", topic.uuid, node_is_eligible=lambda node, event_type: False,
        )

        self.assertFalse(changed)
        self.assertEqual(local.protocol.index[child.uuid].data["text"], "original")

    @staticmethod
    def _lww_position_pair():
        peer = Session("si-b")
        topic = peer.create_child(
            peer.protocol.root.uuid, {"type": "board", "name": "t"}, {},
        ).value
        first = peer.create_child(
            topic.uuid, {"type": "column", "name": "first"}, {},
        ).value
        second = peer.create_child(
            topic.uuid, {"type": "column", "name": "second"}, {},
        ).value
        third = peer.create_child(
            topic.uuid, {"type": "column", "name": "third"}, {},
        ).value
        card = peer.create_child(first.uuid, {
            "type": "card", "text": "same", "order": 0.0,
            "position_at": "2026-01-01T00:00:00+00:00",
        }, {}).value
        local = Session("si-a")
        local.adopt_subtree(
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )
        return peer, local, topic, second, third, card

    def test_lww_policy_adopts_newer_declared_position_conflict(self):
        peer, local, topic, second, third, card = self._lww_position_pair()
        local.move(card.uuid, second.uuid)
        local_card = local.protocol.index[card.uuid]
        local.modify(card.uuid, {
            **local_card.data,
            "order": 1.0,
            "position_at": "2026-01-01T00:00:01+00:00",
        }, local_card.weights)
        peer.move(card.uuid, third.uuid)
        peer_card = peer.protocol.index[card.uuid]
        peer.modify(card.uuid, {
            **peer_card.data,
            "order": 2.0,
            "position_at": "2026-01-01T00:00:02+00:00",
        }, peer_card.weights)
        local.apply_peer_subtree(
            peer.address,
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        local.set_topic_adoption_default(
            topic.uuid, adopt="auto", additions="auto",
        )
        local.set_topic_reconciliation_policies(
            topic.uuid, (LastWriteWinsPolicy(
                node_type="card",
                timestamp_field="position_at",
                data_fields=("order",),
                include_parent=True,
            ),),
        )
        changed = local.reconcile_peer_changes(
            peer.address,
            topic.uuid,
        )

        self.assertTrue(changed)
        adopted = local.protocol.index[card.uuid]
        self.assertEqual(adopted.parent_uuid, third.uuid)
        self.assertEqual(adopted.data["order"], 2.0)

    def test_lww_policy_keeps_newer_local_position(self):
        peer, local, topic, second, third, card = self._lww_position_pair()
        local.move(card.uuid, second.uuid)
        local_card = local.protocol.index[card.uuid]
        local.modify(card.uuid, {
            **local_card.data,
            "position_at": "2026-01-01T00:00:03+00:00",
        }, local_card.weights)
        peer.move(card.uuid, third.uuid)
        peer_card = peer.protocol.index[card.uuid]
        peer.modify(card.uuid, {
            **peer_card.data,
            "position_at": "2026-01-01T00:00:02+00:00",
        }, peer_card.weights)
        local.apply_peer_subtree(
            peer.address,
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        local.set_topic_adoption_default(
            topic.uuid, adopt="auto", additions="auto",
        )
        local.set_topic_reconciliation_policies(
            topic.uuid, (LastWriteWinsPolicy(
                node_type="card",
                timestamp_field="position_at",
                data_fields=("order",),
                include_parent=True,
            ),),
        )
        changed = local.reconcile_peer_changes(
            peer.address,
            topic.uuid,
        )

        self.assertFalse(changed)
        self.assertEqual(local.protocol.index[card.uuid].parent_uuid, second.uuid)

    def test_lww_policy_does_not_hide_other_semantic_conflicts(self):
        peer, local, topic, second, third, card = self._lww_position_pair()
        local.move(card.uuid, second.uuid)
        local_card = local.protocol.index[card.uuid]
        local.modify(card.uuid, {
            **local_card.data,
            "text": "local text",
            "position_at": "2026-01-01T00:00:01+00:00",
        }, local_card.weights)
        peer.move(card.uuid, third.uuid)
        peer_card = peer.protocol.index[card.uuid]
        peer.modify(card.uuid, {
            **peer_card.data,
            "text": "peer text",
            "position_at": "2026-01-01T00:00:02+00:00",
        }, peer_card.weights)
        local.apply_peer_subtree(
            peer.address,
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        local.set_topic_adoption_default(
            topic.uuid, adopt="auto", additions="auto",
        )
        local.set_topic_reconciliation_policies(
            topic.uuid, (LastWriteWinsPolicy(
                node_type="card",
                timestamp_field="position_at",
                data_fields=("order",),
                include_parent=True,
            ),),
        )
        changed = local.reconcile_peer_changes(
            peer.address,
            topic.uuid,
        )

        self.assertFalse(changed)
        self.assertEqual(local.protocol.index[card.uuid].data["text"], "local text")

    def test_lww_policy_settles_timestamp_only_difference_without_adoption(self):
        peer, local, topic, _second, _third, card = self._lww_position_pair()
        local_card = local.protocol.index[card.uuid]
        local.modify(card.uuid, {
            **local_card.data,
            "position_at": "2026-01-01T00:00:01+00:00",
        }, local_card.weights)
        peer_card = peer.protocol.index[card.uuid]
        peer.modify(card.uuid, {
            **peer_card.data,
            "position_at": "2026-01-01T00:00:02+00:00",
        }, peer_card.weights)
        local.apply_peer_subtree(
            peer.address,
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        local.set_topic_adoption_default(
            topic.uuid, adopt="auto", additions="auto",
        )
        local.set_topic_reconciliation_policies(
            topic.uuid, (LastWriteWinsPolicy(
                node_type="card",
                timestamp_field="position_at",
                data_fields=("order",),
                include_parent=True,
            ),),
        )
        changed = local.reconcile_peer_changes(
            peer.address,
            topic.uuid,
            node_is_eligible=lambda node, event_type: False,
        )

        self.assertTrue(changed)
        self.assertEqual(
            local.protocol.index[card.uuid].data["position_at"],
            "2026-01-01T00:00:02+00:00",
        )

    def test_reconcile_adopts_an_existing_nodes_own_fields_only(self):
        # Adopting an existing node updates its own fields only (never grafts
        # its whole subtree) - now the default in accept_peer_node, so no
        # adopt-mode hint is passed. The deeper "doesn't smuggle a
        # simultaneously-added child" property is covered end-to-end by the
        # kanban auto-adopt tests in test_kanban_new_logic.py.
        peer = Session("si-b")
        topic = peer.create_child(
            peer.protocol.root.uuid, {"type": "note", "name": "t"}, {},
        ).value
        folder = peer.create_child(topic.uuid, {"type": "folder", "text": "orig"}, {}).value
        local = Session("si-a")
        local.adopt_subtree(
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        peer.modify(folder.uuid, {"type": "folder", "text": "new"}, {})
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        local.set_topic_adoption_default(
            topic.uuid, adopt="auto", additions="auto",
        )
        changed = local.reconcile_peer_changes("si-b", topic.uuid)

        self.assertTrue(changed)
        self.assertEqual(local.protocol.index[folder.uuid].data["text"], "new")

    def test_shallow_peer_adoption_preserves_the_remote_revision_origin(self):
        peer = Session("si-b")
        peer_identity_key = peer.identity.data["identity_key"]
        topic = peer.create_child(
            peer.protocol.root.uuid, {"type": "note", "name": "t"}, {},
        ).value
        folder = peer.create_child(
            topic.uuid, {"type": "folder", "text": "orig"}, {},
        ).value
        local = Session("si-a")
        local.identity
        local.adopt_subtree(
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        peer.modify(folder.uuid, {"type": "folder", "text": "new"}, {})
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )
        local.set_topic_adoption_default(
            topic.uuid, adopt="auto", additions="auto",
        )
        local.reconcile_peer_changes("si-b", topic.uuid)

        adopted = local.protocol.index[folder.uuid]
        self.assertEqual(adopted.data["text"], "new")
        self.assertEqual(
            adopted.revision_origin, peer_identity_key,
        )

    def test_reconcile_peer_changes_filters_ineligible_new_nodes(self):
        # A brand-new peer node (never seen locally) is always classified
        # "local_missing_node" regardless of hop count - independent
        # coverage of node_is_eligible for that event type specifically,
        # since test_reconcile_peer_changes_respects_node_is_eligible above
        # only covers "peer_made_changes".
        peer = Session("si-b")
        topic = peer.create_child(
            peer.protocol.root.uuid, {"type": "note", "name": "t"}, {},
        ).value
        local = Session("si-a")
        local.adopt_subtree(
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        leaf = peer.create_child(topic.uuid, {"type": "leaf", "text": "new"}, {}).value
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )

        # With the node_hash/subtree_hash split the topic root's own event is
        # "in_agreement" (its own fields didn't change; only its subtree hash
        # cascaded from gaining the leaf), and adoption of any existing node is
        # shallow by default - so neither can drag the filtered leaf in. The
        # leaf itself is local_missing_node and blocked by node_is_eligible.
        local.set_topic_adoption_default(
            topic.uuid, adopt="auto", additions="auto",
        )
        local.reconcile_peer_changes(
            "si-b", topic.uuid,
            node_is_eligible=lambda node, event_type: node.data.get("type") != "leaf",
        )

        self.assertNotIn(leaf.uuid, local.protocol.index)

    def test_accept_missing_peer_node_can_adopt_container_without_descendants(self):
        peer = Session("si-b")
        topic = peer.create_child(
            peer.protocol.root.uuid, {"type": "note", "name": "t"}, {},
        ).value
        local = Session("si-a")
        local.adopt_subtree(
            ProtocolNode.from_dict(topic.to_dict()),
            local.protocol.root.uuid,
        )
        folder = peer.create_child(
            topic.uuid, {"type": "folder", "name": "new"}, {},
        ).value
        leaf = peer.create_child(
            folder.uuid, {"type": "leaf", "text": "protected"}, {},
        ).value
        local.apply_peer_subtree(
            "si-b",
            ProtocolNode.from_dict(
                peer.protocol.index[topic.uuid].to_dict(),
            ),
            local.protocol.root.uuid,
        )

        result = local.accept_peer_node(
            "si-b", folder.uuid, adopt_descendants=False,
        )

        self.assertEqual(result.status, "ok")
        adopted = local.protocol.index[folder.uuid]
        self.assertEqual(adopted.content_hash, folder.content_hash)
        self.assertEqual(adopted.revision_origin, folder.revision_origin)
        self.assertEqual(adopted.revision_seq, folder.revision_seq)
        self.assertEqual(adopted.children, [])
        self.assertNotIn(leaf.uuid, local.protocol.index)

    def test_only_an_agenda_item_author_can_update_its_text(self):
        author = Session("si-author")
        topic = author.create_child(
            author.protocol.root.uuid, {"type": "note", "name": "Topic"}, {},
        ).value
        item = author.create_agenda_item(topic.uuid, "Original").value

        updated = author.update_agenda_item_text(item.uuid, "  Revised  ")

        self.assertEqual(updated.status, "ok")
        self.assertEqual(author.protocol.index[item.uuid].data["text"], "Revised")

        peer = Session("si-peer")
        peer.adopt_subtree(
            ProtocolNode.from_dict(author.protocol.index[topic.uuid].to_dict()),
            peer.protocol.root.uuid,
        )
        refused = peer.update_agenda_item_text(item.uuid, "Hijacked")
        self.assertEqual(refused.status, "error")
        self.assertIn("originator", refused.reason)

    def test_agenda_projection_reads_peer_item_without_adopting_it(self):
        author, observer, topic = self.perspective_pair()
        item = author.create_agenda_item(topic.uuid, "Observed").value
        observer.apply_peer_subtree(
            author.address,
            ProtocolNode.from_dict(author.protocol.index[topic.uuid].to_dict()),
            observer.protocol.root.uuid,
        )

        projected = observer.agenda_projection(topic.uuid)

        self.assertEqual([entry.uuid for entry in projected], [item.uuid])
        self.assertFalse(projected[0].perspective.local)
        self.assertEqual(
            projected[0].perspective.identity_uuid, author.identity.uuid,
        )
        self.assertNotIn(item.uuid, observer.protocol.index)

    def test_projection_deduplicates_same_identity_across_addresses(self):
        author, observer, topic = self.perspective_pair()
        item = author.create_agenda_item(topic.uuid, "One identity").value
        topic_copy = ProtocolNode.from_dict(
            author.protocol.index[topic.uuid].to_dict(),
        )
        observer.apply_peer_subtree(
            author.address, ProtocolNode.from_dict(topic_copy.to_dict()),
            observer.protocol.root.uuid,
        )
        second_address = "relay:author-second-device"
        observer.note_indirect_peer_topic(second_address, topic.uuid)
        observer.apply_peer_subtree(
            second_address, ProtocolNode.from_dict(author.identity.to_dict()), None,
        )
        observer.apply_peer_subtree(
            second_address, ProtocolNode.from_dict(topic_copy.to_dict()),
            observer.protocol.root.uuid,
        )

        projected = observer.agenda_projection(topic.uuid)

        self.assertEqual([entry.uuid for entry in projected], [item.uuid])
        self.assertEqual(
            set(projected[0].perspective.addresses),
            {author.address, second_address},
        )

    def test_agenda_projection_rejects_author_field_owner_mismatch(self):
        author, observer, topic = self.perspective_pair()
        item = author.create_agenda_item(topic.uuid, "Mislabeled").value
        node = author.protocol.index[item.uuid]
        changed = author.modify(
            node.uuid,
            {**node.data, "author": observer.identity.uuid},
            node.weights,
        )
        self.assertEqual(changed.status, "ok")
        observer.apply_peer_subtree(
            author.address,
            ProtocolNode.from_dict(author.protocol.index[topic.uuid].to_dict()),
            observer.protocol.root.uuid,
        )

        self.assertEqual(observer.agenda_projection(topic.uuid), [])

    def test_perspective_projection_accepts_relative_and_absolute_thresholds(self):
        author, observer, topic = self.perspective_pair()
        item = author.create_agenda_item(topic.uuid, "Time-bound").value
        observer.apply_peer_subtree(
            author.address,
            ProtocolNode.from_dict(author.protocol.index[topic.uuid].to_dict()),
            observer.protocol.root.uuid,
        )
        observer.observe_peer_perspective(
            author.address,
            topic.uuid,
            source_age_seconds=10,
            source_timestamp=1_000,
            channel_kind="test",
        )

        self.assertEqual(
            observer.agenda_projection(topic.uuid, max_age_seconds=5), [],
        )
        self.assertEqual(
            [entry.uuid for entry in observer.agenda_projection(
                topic.uuid, max_age_seconds=20,
            )],
            [item.uuid],
        )
        self.assertEqual(
            observer.agenda_projection(topic.uuid, not_before=1_001), [],
        )
        self.assertEqual(
            [entry.uuid for entry in observer.agenda_projection(
                topic.uuid, not_before=999,
            )],
            [item.uuid],
        )

    def test_authoritative_peer_deletion_removes_projected_agenda_item(self):
        author, observer, topic = self.perspective_pair()
        item = author.create_agenda_item(topic.uuid, "Temporary").value
        observer.apply_peer_subtree(
            author.address,
            ProtocolNode.from_dict(author.protocol.index[topic.uuid].to_dict()),
            observer.protocol.root.uuid,
        )
        self.assertEqual(
            [entry.uuid for entry in observer.agenda_projection(topic.uuid)],
            [item.uuid],
        )

        author.delete_agenda_item(item.uuid)
        observer.apply_peer_subtree(
            author.address,
            ProtocolNode.from_dict(author.protocol.index[topic.uuid].to_dict()),
            observer.protocol.root.uuid,
        )

        self.assertEqual(observer.agenda_projection(topic.uuid), [])

    def test_persistence_projection_drops_foreign_agenda_nodes(self):
        """Grafting a topic brings the inviter's agenda; persisting drops it."""
        author = Session("si-author")
        observer = Session("si-observer")
        author.identity
        observer.identity
        topic = author.create_child(
            author.protocol.root.uuid, {"type": "note", "name": "Topic"}, {},
        ).value
        item = author.create_agenda_item(topic.uuid, "Foreign").value
        observer.adopt_subtree(
            ProtocolNode.from_dict(author.protocol.index[topic.uuid].to_dict()),
            observer.protocol.root.uuid,
        )
        self.assertIn(item.uuid, observer.protocol.index)

        persisted = ProtocolNode.from_dict(
            observer.export_persistence_protocol_root(),
        )

        self.assertNotIn(item.uuid, Session._flatten_by_uuid(persisted))
        # The container survives: it is the place, not the foreign content.
        self.assertIn(
            Session.agenda_container_uuid(topic.uuid),
            Session._flatten_by_uuid(persisted),
        )

    def test_a_peer_agenda_item_is_never_adoptable(self):
        """Core declares the rule on its own container, not every application."""
        author, observer, topic = self.perspective_pair()
        item = author.create_agenda_item(topic.uuid, "Foreign").value
        observer.apply_peer_subtree(
            author.address,
            ProtocolNode.from_dict(author.protocol.index[topic.uuid].to_dict()),
            observer.protocol.root.uuid,
        )

        adopted = observer.accept_peer_node(author.address, item.uuid)

        self.assertEqual(adopted.status, "error")
        self.assertNotIn(item.uuid, observer.protocol.index)

    def test_agenda_move_never_rewrites_an_observed_item(self):
        local = Session("si-local")
        peer = Session("si-peer")
        local.identity
        peer.identity
        topic = local.create_child(
            local.protocol.root.uuid, {"type": "note", "name": "Topic"}, {},
        ).value
        first = local.create_agenda_item(topic.uuid, "First").value
        peer.adopt_subtree(
            ProtocolNode.from_dict(local.protocol.index[topic.uuid].to_dict()),
            peer.protocol.root.uuid,
        )
        foreign = peer.create_agenda_item(topic.uuid, "Foreign").value
        local.note_indirect_peer_topic(peer.address, topic.uuid)
        local.apply_peer_subtree(
            peer.address, ProtocolNode.from_dict(peer.identity.to_dict()), None,
        )
        local.apply_peer_subtree(
            peer.address,
            ProtocolNode.from_dict(peer.protocol.index[topic.uuid].to_dict()),
            local.protocol.root.uuid,
        )
        before = local.get_cached_peer_subtree(peer.address, foreign.uuid).data["order"]

        result = local.move_agenda_item(first.uuid, 1)

        self.assertEqual(result.status, "ok", result.reason)
        self.assertEqual(
            local.get_cached_peer_subtree(peer.address, foreign.uuid).data["order"],
            before,
        )
        self.assertEqual(
            local.move_agenda_item(foreign.uuid, 0).status, "error",
        )

    def test_agenda_containers_agree_without_being_adopted(self):
        """Both sides derive the same container, so neither adopts the other's.

        This is what lets a projection address a peer's agenda by uuid. The
        two copies are authored independently and carry different timestamps
        and signatures, but neither enters the content hash, so reconciliation
        sees agreement rather than a change to decide about.
        """
        author, observer, topic = self.perspective_pair()
        mine = observer.create_agenda_item(topic.uuid, "Mine").value
        theirs = author.create_agenda_item(topic.uuid, "Theirs").value
        container_uuid = Session.agenda_container_uuid(topic.uuid)

        local_container = observer.protocol.index[container_uuid]
        peer_container = author.protocol.index[container_uuid]
        self.assertEqual(
            local_container.content_hash, peer_container.content_hash,
        )
        self.assertNotEqual(
            local_container.revision_signature,
            peer_container.revision_signature,
        )
        self.assertEqual(
            Session._classify_content(local_container, peer_container),
            "in_agreement",
        )

        observer.apply_peer_subtree(
            author.address,
            ProtocolNode.from_dict(author.protocol.index[topic.uuid].to_dict()),
            observer.protocol.root.uuid,
        )
        projected = observer.agenda_projection(topic.uuid, max_age_seconds=None)

        self.assertEqual(
            {item.uuid for item in projected}, {mine.uuid, theirs.uuid},
        )

    def test_ensure_container_is_idempotent_by_name(self):
        session = Session("si-container")
        session.identity
        topic = session.create_child(
            session.protocol.root.uuid, {"type": "note", "name": "Topic"}, {},
        ).value

        first = session.ensure_container(topic.uuid, "comments")
        second = session.ensure_container(topic.uuid, "comments")
        other = session.ensure_container(topic.uuid, "attachments")

        self.assertEqual(first.status, "ok", first.reason)
        self.assertEqual(first.value.uuid, second.value.uuid)
        self.assertNotEqual(first.value.uuid, other.value.uuid)
        self.assertEqual(
            session.ensure_container("missing-uuid", "comments").status, "error",
        )

    def test_container_children_are_ordered_without_naming_a_type(self):
        """A container holds one kind, so its uuid says what the type used to."""
        session = Session("si-ordering")
        session.identity
        topic = session.create_child(
            session.protocol.root.uuid, {"type": "note", "name": "Topic"}, {},
        ).value
        container = session.ensure_container(topic.uuid, "comments").value
        for text in ("first", "second"):
            session.create_child(
                container.uuid,
                {
                    "type": "comment",
                    "text": text,
                    "order": session.next_child_order(container.uuid),
                },
                {},
            )

        self.assertEqual(session.next_child_order(container.uuid), 2.0)
        # The topic root still holds mixed kinds, so naming one still narrows.
        self.assertEqual(session.next_child_order(topic.uuid), 1.0)
        self.assertEqual(session.next_child_order(topic.uuid, "comment"), 0.0)


if __name__ == "__main__":
    unittest.main()
