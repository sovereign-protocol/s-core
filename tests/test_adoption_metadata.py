"""Declared per-node handling: Core executes the record, never interprets it.

See DESIGN_ADOPTION_METADATA.md.
"""

import unittest

from sovereign.adoption import (
    ADOPT_AUTO, ADOPT_HOLD, ADOPT_NEVER, AUTHOR_ANY, AUTHOR_SAME_ORIGIN,
    RESOLVE_ADOPT, RESOLVE_DEFER, RESOLVE_REFUSE, AdoptionEntry,
)
from sovereign.reconciliation import LastWriteWinsPolicy
from sovereign.protocol import ProtocolNode
from sovereign.session import Session


class AdoptionMetadataTests(unittest.TestCase):
    def pair(self):
        """A peer owning a board, and a local client holding a copy of it."""
        peer = Session("si-peer")
        peer.identity
        board = peer.create_child(
            peer.protocol.root.uuid, {"type": "board", "name": "b"}, {},
        ).value
        column = peer.create_child(
            board.uuid, {"type": "column", "name": "todo"}, {},
        ).value
        local = Session("si-local")
        local.identity
        local.adopt_subtree(
            ProtocolNode.from_dict(peer.protocol.index[board.uuid].to_dict()),
            local.protocol.root.uuid,
        )
        return local, peer, board, column

    def sync(self, local, peer, board):
        local.apply_peer_subtree(
            "si-peer",
            ProtocolNode.from_dict(peer.protocol.index[board.uuid].to_dict()),
            local.protocol.root.uuid,
        )

    # ---- resolution ----

    def test_absent_entry_resolves_to_the_conservative_root_default(self):
        local, _peer, board, _column = self.pair()
        resolved = local.adoption_metadata(board.uuid)
        self.assertEqual(resolved.adopt, ADOPT_HOLD)
        self.assertEqual(resolved.additions, ADOPT_HOLD)
        self.assertEqual(resolved.author, AUTHOR_ANY)

    def test_node_entry_overrides_the_topic_default(self):
        local, _peer, board, column = self.pair()
        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_AUTO)
        local.set_adoption_metadata(column.uuid, adopt=ADOPT_HOLD)

        self.assertEqual(local.adoption_metadata(board.uuid).adopt, ADOPT_AUTO)
        self.assertEqual(local.adoption_metadata(column.uuid).adopt, ADOPT_HOLD)

    def test_unset_fields_inherit_rather_than_reset(self):
        local, _peer, board, column = self.pair()
        local.set_topic_adoption_default(
            board.uuid, adopt=ADOPT_AUTO, additions=ADOPT_AUTO,
        )
        local.set_adoption_metadata(column.uuid, adopt=ADOPT_HOLD)

        resolved = local.adoption_metadata(column.uuid)
        self.assertEqual(resolved.adopt, ADOPT_HOLD)
        self.assertEqual(resolved.additions, ADOPT_AUTO)

    def test_an_invalid_value_is_refused(self):
        local, _peer, board, _column = self.pair()
        result = local.set_adoption_metadata(board.uuid, adopt="sometimes")
        self.assertEqual(result.status, "error")

    # ---- enforcement ----

    def test_an_undeclared_topic_holds_everything(self):
        """Declaration is mandatory: silence is not consent to adopt."""
        local, peer, board, column = self.pair()
        peer.modify(column.uuid, {"type": "column", "name": "doing"}, {})
        self.sync(local, peer, board)

        self.assertFalse(local.reconcile_peer_changes("si-peer", board.uuid))
        self.assertEqual(local.protocol.index[column.uuid].data["name"], "todo")

    def test_a_user_decision_passes_through_hold(self):
        """`hold` means "wait for me to decide" - this is that decision."""
        local, peer, board, column = self.pair()
        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_HOLD)
        peer.modify(column.uuid, {"type": "column", "name": "doing"}, {})
        self.sync(local, peer, board)

        self.assertFalse(local.reconcile_peer_changes("si-peer", board.uuid))
        self.assertTrue(
            local.reconcile_peer_changes("si-peer", board.uuid, deciding=True),
        )
        self.assertEqual(
            local.protocol.index[column.uuid].data["name"], "doing",
        )

    def test_a_user_decision_does_not_pass_through_never(self):
        local, peer, board, column = self.pair()
        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_NEVER)
        peer.modify(column.uuid, {"type": "column", "name": "doing"}, {})
        self.sync(local, peer, board)

        self.assertFalse(
            local.reconcile_peer_changes("si-peer", board.uuid, deciding=True),
        )
        self.assertEqual(local.protocol.index[column.uuid].data["name"], "todo")

    def test_a_classifier_answers_once_for_a_node_not_yet_held(self):
        local, peer, board, column = self.pair()
        local.set_topic_adoption_default(
            board.uuid, adopt=ADOPT_AUTO, additions=ADOPT_AUTO,
        )
        asked = []

        def classify(node, default):
            asked.append(node.uuid)
            if node.data.get("type") == "secret":
                return {"adopt": ADOPT_NEVER, "additions": ADOPT_NEVER}
            return None

        local.set_adoption_classifier(board.uuid, classify)
        secret = peer.create_child(
            column.uuid, {"type": "secret", "name": "s"}, {},
        ).value
        ordinary = peer.create_child(
            column.uuid, {"type": "card", "name": "c"}, {},
        ).value
        self.sync(local, peer, board)

        local.reconcile_peer_changes("si-peer", board.uuid)

        self.assertNotIn(secret.uuid, local.protocol.index)
        self.assertIn(ordinary.uuid, local.protocol.index)
        # Asked once, then remembered: a second pass reads the table.
        before = len(asked)
        local.reconcile_peer_changes("si-peer", board.uuid)
        self.assertNotIn(secret.uuid, local.protocol.index)
        self.assertEqual(asked.count(secret.uuid), asked[:before].count(secret.uuid))

    def test_a_classifier_that_raises_leaves_the_default_in_force(self):
        local, peer, board, column = self.pair()
        local.set_topic_adoption_default(
            board.uuid, adopt=ADOPT_AUTO, additions=ADOPT_AUTO,
        )

        def classify(node, default):
            raise RuntimeError("application fault")

        local.set_adoption_classifier(board.uuid, classify)
        card = peer.create_child(
            column.uuid, {"type": "card", "name": "c"}, {},
        ).value
        self.sync(local, peer, board)

        local.reconcile_peer_changes("si-peer", board.uuid)

        self.assertIn(card.uuid, local.protocol.index)

    def test_redeclaring_a_topic_default_re_asks_the_classifier(self):
        """A classifier answer derived under the old declaration is stale."""
        local, peer, board, column = self.pair()
        local.set_topic_adoption_default(
            board.uuid, adopt=ADOPT_AUTO, additions=ADOPT_AUTO,
        )
        local.set_adoption_classifier(
            board.uuid, lambda node, default: {"adopt": ADOPT_HOLD},
        )
        card = peer.create_child(
            column.uuid, {"type": "card", "name": "c"}, {},
        ).value
        self.sync(local, peer, board)
        local.reconcile_peer_changes("si-peer", board.uuid)
        self.assertIn(card.uuid, local._adoption_by_node)

        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_AUTO)

        self.assertNotIn(card.uuid, local._adoption_by_node)

    # ---- Core reacts to a changed declaration ----

    def test_declaring_adoption_applies_it_to_what_is_already_waiting(self):
        """Otherwise turning adoption on does nothing until fresh traffic."""
        local, peer, board, column = self.pair()
        peer.modify(column.uuid, {"type": "column", "name": "doing"}, {})
        self.sync(local, peer, board)
        local.note_indirect_peer_topic("si-peer", board.uuid)
        self.assertEqual(local.protocol.index[column.uuid].data["name"], "todo")

        local.set_topic_adoption_default(
            board.uuid, adopt=ADOPT_AUTO, additions=ADOPT_AUTO,
        )

        self.assertEqual(
            local.protocol.index[column.uuid].data["name"], "doing",
        )

    def test_reconsidering_settles_what_the_old_answer_held(self):
        """A setting Core cannot see changed, so the answers from it are stale.

        Two of an application's modes can declare the same handling here and
        differ only in what their resolver says, which is why redeclaring
        cannot be the trigger.
        """
        local, peer, board, column = self.pair()
        local.note_indirect_peer_topic("si-peer", board.uuid)
        local.set_topic_adoption_default(
            board.uuid, adopt=ADOPT_HOLD, additions=ADOPT_HOLD,
        )
        verdict = [RESOLVE_DEFER]
        local.set_adoption_resolver(
            board.uuid,
            lambda peer_node, local_node, peer_addr: verdict[0],
        )
        peer.modify(column.uuid, {"type": "column", "name": "doing"}, {})
        self.sync(local, peer, board)
        self.assertEqual(local.protocol.index[column.uuid].data["name"], "todo")

        verdict[0] = RESOLVE_ADOPT

        self.assertTrue(local.reconsider_adoption(board.uuid))
        self.assertEqual(
            local.protocol.index[column.uuid].data["name"], "doing",
        )

    def test_reconsidering_re_asks_the_classifier(self):
        """What it said about an unheld node was derived from the same setting."""
        local, peer, board, column = self.pair()
        local.note_indirect_peer_topic("si-peer", board.uuid)
        local.set_topic_adoption_default(
            board.uuid, adopt=ADOPT_AUTO, additions=ADOPT_AUTO,
        )
        refusing = [True]
        local.set_adoption_classifier(
            board.uuid,
            lambda node, default: (
                {"adopt": ADOPT_NEVER, "additions": ADOPT_NEVER}
                if refusing[0] else None
            ),
        )
        card = peer.create_child(
            column.uuid, {"type": "card", "name": "c"}, {},
        ).value
        self.sync(local, peer, board)
        local.reconcile_peer_changes("si-peer", board.uuid)
        self.assertNotIn(card.uuid, local.protocol.index)

        refusing[0] = False

        local.reconsider_adoption(board.uuid)
        self.assertIn(card.uuid, local.protocol.index)

    def test_reconsidering_leaves_a_decision_the_user_made(self):
        """Only answers derived from the setting are dropped, not held nodes."""
        local, _peer, board, column = self.pair()
        local.note_indirect_peer_topic("si-peer", board.uuid)
        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_AUTO)
        local.set_adoption_metadata(column.uuid, adopt=ADOPT_NEVER)

        local.reconsider_adoption(board.uuid)

        self.assertEqual(
            local.adoption_metadata(column.uuid).adopt, ADOPT_NEVER,
        )

    def test_republishing_the_same_declaration_decides_nothing(self):
        local, peer, board, column = self.pair()
        local.note_indirect_peer_topic("si-peer", board.uuid)
        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_HOLD)
        peer.modify(column.uuid, {"type": "column", "name": "doing"}, {})
        self.sync(local, peer, board)

        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_HOLD)

        self.assertEqual(local.protocol.index[column.uuid].data["name"], "todo")

    def test_declaring_during_a_pass_cannot_recurse(self):
        """The publisher writes the declaration at the start of every pass.

        Loop safety must not depend on it writing identical values - that is
        an application's choice, and a wrong one would be an infinite
        reconciliation. Core refuses to re-apply a topic it is already
        reconciling, whatever the values.
        """
        local, peer, board, column = self.pair()
        local.note_indirect_peer_topic("si-peer", board.uuid)
        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_HOLD)
        peer.modify(column.uuid, {"type": "column", "name": "doing"}, {})
        self.sync(local, peer, board)

        depth = []

        def resolve(peer_node, local_node, peer_addr):
            depth.append(1)
            # A declaration written from inside the pass, with a new value.
            local.set_topic_adoption_default(
                board.uuid,
                adopt=ADOPT_AUTO if len(depth) % 2 else ADOPT_HOLD,
            )
            return RESOLVE_DEFER

        local.set_adoption_resolver(board.uuid, resolve)
        local.reconcile_peer_changes("si-peer", board.uuid)

        self.assertLessEqual(len(depth), 4)

    def test_reconciliation_policies_are_declared_not_passed(self):
        """Core must reach the application's result when it runs the pass."""
        local, peer, board, column = self.pair()
        local.note_indirect_peer_topic("si-peer", board.uuid)
        local.set_topic_adoption_default(
            board.uuid, adopt=ADOPT_AUTO, additions=ADOPT_AUTO,
        )
        declared = local.set_topic_reconciliation_policies(
            board.uuid,
            (LastWriteWinsPolicy(
                node_type="column", timestamp_field="moved_at",
                data_fields=("name",),
            ),),
        )

        self.assertEqual(declared.status, "ok")
        self.assertEqual(declared.value, 1)

    # ---- resolving a held node ----

    def held_pair(self, verdict):
        """A board holding everything, with a resolver giving one verdict."""
        local, peer, board, column = self.pair()
        local.set_topic_adoption_default(
            board.uuid, adopt=ADOPT_HOLD, additions=ADOPT_HOLD,
        )
        asked = []

        def resolve(peer_node, local_node, peer_addr):
            asked.append(peer_node.uuid)
            return verdict

        local.set_adoption_resolver(board.uuid, resolve)
        peer.modify(column.uuid, {"type": "column", "name": "doing"}, {})
        self.sync(local, peer, board)
        return local, peer, board, column, asked

    def test_the_application_can_settle_a_held_node_itself(self):
        local, _peer, board, column, asked = self.held_pair(RESOLVE_ADOPT)

        self.assertTrue(local.reconcile_peer_changes("si-peer", board.uuid))

        self.assertEqual(
            local.protocol.index[column.uuid].data["name"], "doing",
        )
        self.assertIn(column.uuid, asked)

    def test_a_refusal_outranks_a_user_decision(self):
        """"My rule says no" is not the same as "nobody has decided yet"."""
        local, _peer, board, column, _asked = self.held_pair(RESOLVE_REFUSE)

        self.assertFalse(
            local.reconcile_peer_changes("si-peer", board.uuid, deciding=True),
        )
        self.assertEqual(local.protocol.index[column.uuid].data["name"], "todo")

    def test_deferring_leaves_it_to_the_user(self):
        local, _peer, board, column, _asked = self.held_pair(RESOLVE_DEFER)

        self.assertFalse(local.reconcile_peer_changes("si-peer", board.uuid))
        self.assertEqual(local.protocol.index[column.uuid].data["name"], "todo")

        self.assertTrue(
            local.reconcile_peer_changes("si-peer", board.uuid, deciding=True),
        )
        self.assertEqual(
            local.protocol.index[column.uuid].data["name"], "doing",
        )

    def test_no_resolver_means_defer(self):
        local, peer, board, column = self.pair()
        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_HOLD)
        peer.modify(column.uuid, {"type": "column", "name": "doing"}, {})
        self.sync(local, peer, board)

        self.assertFalse(local.reconcile_peer_changes("si-peer", board.uuid))
        self.assertTrue(
            local.reconcile_peer_changes("si-peer", board.uuid, deciding=True),
        )

    def test_a_resolver_that_raises_means_defer(self):
        local, peer, board, column = self.pair()
        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_HOLD)

        def resolve(peer_node, local_node, peer_addr):
            raise RuntimeError("application fault")

        local.set_adoption_resolver(board.uuid, resolve)
        peer.modify(column.uuid, {"type": "column", "name": "doing"}, {})
        self.sync(local, peer, board)

        self.assertFalse(local.reconcile_peer_changes("si-peer", board.uuid))
        self.assertEqual(local.protocol.index[column.uuid].data["name"], "todo")

    def test_a_resolver_is_asked_every_time_never_stored(self):
        """Its answer derives from state that moves, so it is not cached."""
        local, peer, board, column, asked = self.held_pair(RESOLVE_DEFER)

        local.reconcile_peer_changes("si-peer", board.uuid)
        first = len(asked)
        local.reconcile_peer_changes("si-peer", board.uuid)

        self.assertGreater(len(asked), first)
        self.assertEqual(local.adoption_metadata_snapshot()["nodes"], {})

    def test_auto_and_never_never_reach_the_resolver(self):
        """Only `hold` is undecided; the other two are already settled."""
        local, peer, board, column = self.pair()
        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_AUTO)
        asked = []
        local.set_adoption_resolver(
            board.uuid,
            lambda peer_node, local_node, peer_addr: asked.append(1),
        )
        peer.modify(column.uuid, {"type": "column", "name": "doing"}, {})
        self.sync(local, peer, board)

        local.reconcile_peer_changes("si-peer", board.uuid)

        self.assertEqual(asked, [])

    def test_hold_keeps_a_change_out(self):
        local, peer, board, column = self.pair()
        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_AUTO)
        local.set_adoption_metadata(column.uuid, adopt=ADOPT_HOLD)
        peer.modify(column.uuid, {"type": "column", "name": "doing"}, {})
        self.sync(local, peer, board)

        local.reconcile_peer_changes("si-peer", board.uuid)

        self.assertEqual(local.protocol.index[column.uuid].data["name"], "todo")

    def test_auto_lets_a_change_in(self):
        local, peer, board, column = self.pair()
        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_AUTO)
        peer.modify(column.uuid, {"type": "column", "name": "doing"}, {})
        self.sync(local, peer, board)

        local.reconcile_peer_changes("si-peer", board.uuid)

        self.assertEqual(
            local.protocol.index[column.uuid].data["name"], "doing",
        )

    def test_additions_are_governed_by_the_parent(self):
        local, peer, board, column = self.pair()
        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_AUTO)
        local.set_adoption_metadata(column.uuid, additions=ADOPT_HOLD)
        card = peer.create_child(
            column.uuid, {"type": "card", "name": "new"}, {},
        ).value
        self.sync(local, peer, board)

        local.reconcile_peer_changes("si-peer", board.uuid)

        self.assertNotIn(card.uuid, local.protocol.index)

    def test_an_addition_arrives_without_its_descendants(self):
        """Each level is a separate decision under its own parent's entry."""
        local, peer, board, column = self.pair()
        local.set_topic_adoption_default(
            board.uuid, adopt=ADOPT_AUTO, additions=ADOPT_AUTO,
        )
        card = peer.create_child(
            column.uuid, {"type": "card", "name": "card"}, {},
        ).value
        comment = peer.create_child(
            card.uuid, {"type": "comment", "text": "hi"}, {},
        ).value
        # The card admits nothing: its comment must not ride in on the graft.
        local.set_adoption_metadata(card.uuid, additions=ADOPT_HOLD)
        self.sync(local, peer, board)

        local.reconcile_peer_changes("si-peer", board.uuid)

        self.assertIn(card.uuid, local.protocol.index)
        self.assertNotIn(comment.uuid, local.protocol.index)

    def test_a_deletion_is_refused_while_it_would_take_a_held_node(self):
        local, peer, board, column = self.pair()
        card = peer.create_child(
            column.uuid, {"type": "card", "name": "card"}, {},
        ).value
        self.sync(local, peer, board)
        local.set_topic_adoption_default(
            board.uuid, adopt=ADOPT_AUTO, additions=ADOPT_AUTO,
        )
        local.reconcile_peer_changes("si-peer", board.uuid)
        self.assertIn(card.uuid, local.protocol.index)

        # Now the card is held, and the peer deletes the column above it.
        local.set_adoption_metadata(card.uuid, adopt=ADOPT_HOLD)
        peer.delete(column.uuid)
        self.sync(local, peer, board)

        local.reconcile_peer_changes("si-peer", board.uuid)

        self.assertFalse(local.protocol.index[column.uuid].deleted)
        self.assertIn(card.uuid, local.protocol.index)

    def test_a_declared_author_excludes_other_origins(self):
        local, peer, board, column = self.pair()
        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_AUTO)
        local.set_adoption_metadata(column.uuid, author="somebody-else")
        peer.modify(column.uuid, {"type": "column", "name": "doing"}, {})
        self.sync(local, peer, board)

        local.reconcile_peer_changes("si-peer", board.uuid)

        self.assertEqual(local.protocol.index[column.uuid].data["name"], "todo")

    def test_the_peers_own_key_satisfies_a_declared_author(self):
        local, peer, board, column = self.pair()
        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_AUTO)
        author = peer.protocol.index[column.uuid].revision_origin
        local.set_adoption_metadata(column.uuid, author=author)
        peer.modify(column.uuid, {"type": "column", "name": "doing"}, {})
        self.sync(local, peer, board)

        local.reconcile_peer_changes("si-peer", board.uuid)

        self.assertEqual(
            local.protocol.index[column.uuid].data["name"], "doing",
        )

    # ---- bulk primitives ----

    def test_a_subtree_write_can_target_one_node_type(self):
        local, _peer, board, column = self.pair()
        local.set_adoption_metadata_for_subtree(
            board.uuid, adopt=ADOPT_HOLD, node_type="column",
        )
        self.assertEqual(local.adoption_metadata(column.uuid).adopt, ADOPT_HOLD)
        self.assertIsNone(local._adoption_by_node.get(board.uuid))

    def test_replacing_an_author_leaves_other_entries_alone(self):
        local, _peer, board, column = self.pair()
        local.set_adoption_metadata(column.uuid, author="old-trustee")
        local.set_adoption_metadata(board.uuid, author="someone-else")

        swapped = local.replace_adoption_author(
            board.uuid, "old-trustee", "new-trustee",
        )

        self.assertEqual(swapped.value, 1)
        self.assertEqual(
            local.adoption_metadata(column.uuid).author, "new-trustee",
        )
        self.assertEqual(
            local.adoption_metadata(board.uuid).author, "someone-else",
        )

    # ---- persistence ----

    def test_the_table_survives_a_round_trip_and_is_inspectable(self):
        local, _peer, board, column = self.pair()
        local.set_topic_adoption_default(board.uuid, adopt=ADOPT_AUTO)
        local.set_adoption_metadata(column.uuid, adopt=ADOPT_NEVER)

        stored = local.persistence_metadata()["adoption_metadata"]
        self.assertEqual(stored["topics"][board.uuid], {"adopt": ADOPT_AUTO})
        self.assertEqual(stored["nodes"][column.uuid], {"adopt": ADOPT_NEVER})

    def test_restoring_drops_entries_for_nodes_that_are_gone(self):
        local, _peer, board, column = self.pair()
        local.set_adoption_metadata(column.uuid, adopt=ADOPT_AUTO)
        metadata = local.persistence_metadata()
        metadata["adoption_metadata"]["nodes"]["not-a-node"] = {
            "adopt": ADOPT_AUTO,
        }

        local.restore_persistence_metadata(metadata)

        self.assertIn(column.uuid, local._adoption_by_node)
        self.assertNotIn("not-a-node", local._adoption_by_node)

    def test_an_unreadable_entry_is_dropped_rather_than_raised_on(self):
        self.assertIsNone(AdoptionEntry.from_dict({"adopt": "nonsense"}))
        self.assertIsNone(AdoptionEntry.from_dict("not a dict"))
        self.assertIsNone(AdoptionEntry.from_dict({}))


if __name__ == "__main__":
    unittest.main()
