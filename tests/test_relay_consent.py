"""What a client accepted and offered is the session's, not a file's.

Consent - `desired`, `shared`, `identity_topics` - is the one part of relay
bookkeeping no relay can re-answer, so it lives with the session and is keyed
by target. Everything else in the state file is cache.

`pair_all_topics` was consent once and is not: only pairing sets it, nothing
clears it, and what it says is that the *link* carries a sibling. It lives in
the target record, and the last class here holds it to that.

Two properties follow, and both are asserted here: the state file may be
deleted at any time without losing anything, and a target that changes where
it points keeps the consent recorded against it, with no code moving it.

See DESIGN_RELAY_CONSENT.md.
"""

import tempfile
import unittest
from pathlib import Path

from sovereign.relay_logic import RelayLogic, RelayManager
from sovereign.session import Session


class ConsentOutlivesTheStateFileTests(unittest.TestCase):
    def test_deleting_the_state_file_loses_nothing_that_matters(self):
        # The property the split buys. Before it, deleting this file emptied
        # `desired` and `shared`, so the gate unarmed and grafting stopped -
        # silently, with the relay still reachable and presence still beating.
        with tempfile.TemporaryDirectory() as relay_root, \
                tempfile.TemporaryDirectory() as state_dir:
            session = Session("addr-a")
            config = {
                "relay_backend": "local", "relay_root": relay_root,
                "relay_state_directory": state_dir,
            }
            relay = RelayLogic(session, config)
            relay.mark_topics_shared(["board-1"])
            relay.mark_topics_desired(["board-2"])
            relay._save_state()
            Path(relay._state_path).unlink()

            rebuilt = RelayLogic(session, config)

            self.assertEqual(rebuilt._state["shared"], ["board-1"])
            self.assertEqual(rebuilt._state["desired"], ["board-2"])
            self.assertTrue(rebuilt.has_active_relationship())

    def test_consent_never_reaches_the_state_file(self):
        with tempfile.TemporaryDirectory() as relay_root, \
                tempfile.TemporaryDirectory() as state_dir:
            relay = RelayLogic(Session("addr-a"), {
                "relay_backend": "local", "relay_root": relay_root,
                "relay_state_directory": state_dir,
            })
            relay.mark_topics_shared(["board-1"])
            relay._save_state()

            written = Path(relay._state_path).read_text(encoding="utf-8")

            for key in ("desired", "shared", "identity_topics", "pair_all_topics"):
                self.assertNotIn(key, written)

    def test_adopting_a_location_keeps_consent_marked_before_it(self):
        # A token-provisioned client can accept topics before it has storage.
        # Adoption reloads the state file under a new name, which used to
        # take the consent with it.
        with tempfile.TemporaryDirectory() as relay_root, \
                tempfile.TemporaryDirectory() as state_dir:
            session = Session("addr-a")
            relay = RelayLogic(session, {"relay_state_directory": state_dir})
            relay.mark_topics_desired(["board-1"])

            relay.adopt_storage_from_descriptor({
                "type": "relay", "root": relay_root,
            })

            self.assertEqual(relay._state["desired"], ["board-1"])


class ConsentFollowsTheTargetTests(unittest.TestCase):
    def manager(self, state_dir: str) -> RelayManager:
        return RelayManager(Session("addr-a"), {
            "relay_state_directory": state_dir,
        })

    def test_editing_where_a_target_points_keeps_its_consent(self):
        # update_target used to hand-carry shared/desired/identity_topics
        # from the old connection to the new one, because consent was keyed
        # by storage location. Keyed by target id, an edit moves nothing.
        with tempfile.TemporaryDirectory() as first_root, \
                tempfile.TemporaryDirectory() as second_root, \
                tempfile.TemporaryDirectory() as state_dir:
            manager = self.manager(state_dir)
            target_id = manager.create_target({
                "name": "T", "backend": "local", "root": first_root,
            }, verify=False).value
            manager.connection_for_target(target_id).mark_topics_desired(
                ["board-1"],
            )

            updated = manager.update_target(target_id, {
                "name": "T", "backend": "local", "root": second_root,
            }, verify=False)

            self.assertEqual(updated.status, "ok", updated.reason)
            moved = manager.connection_for_target(target_id)
            self.assertEqual(moved._state["desired"], ["board-1"])
            self.assertEqual(str(moved.storage.root), str(Path(second_root)))

    def test_deleting_a_target_drops_its_consent_and_no_one_else_s(self):
        with tempfile.TemporaryDirectory() as first_root, \
                tempfile.TemporaryDirectory() as second_root, \
                tempfile.TemporaryDirectory() as state_dir:
            manager = self.manager(state_dir)
            doomed = manager.create_target({
                "name": "A", "backend": "local", "root": first_root,
            }, verify=False).value
            kept = manager.create_target({
                "name": "B", "backend": "local", "root": second_root,
            }, verify=False).value
            manager.connection_for_target(doomed).mark_topics_desired(["board-1"])
            manager.connection_for_target(kept).mark_topics_desired(["board-2"])

            manager.delete_target(doomed)

            stored = manager.session.component_metadata("relay")["relay_consent"]
            self.assertNotIn(doomed, stored)
            self.assertEqual(stored[kept]["desired"], ["board-2"])
            self.assertEqual(
                manager.connection_for_target(kept)._state["desired"], ["board-2"],
            )

    def test_a_second_target_on_one_location_reads_the_same_consent(self):
        # create_target does not dedup by location the way register_descriptor
        # does, so two targets can name one relay - and they share the single
        # connection to it. It answers for both.
        with tempfile.TemporaryDirectory() as relay_root, \
                tempfile.TemporaryDirectory() as state_dir:
            manager = self.manager(state_dir)
            first = manager.create_target({
                "name": "A", "backend": "local", "root": relay_root,
            }, verify=False).value
            manager.connection_for_target(first).mark_topics_desired(["board-1"])

            second = manager.create_target({
                "name": "B", "backend": "local", "root": relay_root,
            }, verify=False).value

            self.assertIs(
                manager.connection_for_target(second),
                manager.connection_for_target(first),
            )
            self.assertEqual(
                manager.connection_for_target(second)._state["desired"],
                ["board-1"],
            )


class PairingIsAPropertyOfTheLinkTests(unittest.TestCase):
    def manager(self, state_dir: str) -> RelayManager:
        return RelayManager(Session("addr-a"), {
            "relay_state_directory": state_dir,
        })

    def test_pairing_a_connection_records_it_on_the_target(self):
        with tempfile.TemporaryDirectory() as relay_root, \
                tempfile.TemporaryDirectory() as state_dir:
            manager = self.manager(state_dir)
            target_id = manager.create_target({
                "name": "T", "backend": "local", "root": relay_root,
            }, verify=False).value
            connection = manager.connection_for_target(target_id)

            self.assertEqual(connection.pair_all_topics().status, "ok")

            record = manager.session.component_metadata(
                "relay",
            )["relay_targets"][target_id]
            self.assertTrue(record["pair_all_topics"])
            self.assertTrue(connection._state["pair_all_topics"])

    def test_editing_a_target_does_not_unpair_it(self):
        # update_target rebuilds the record from a descriptor, and a
        # descriptor describes a location. Whether the link carries a sibling
        # is not something a corrected host can answer.
        with tempfile.TemporaryDirectory() as first_root, \
                tempfile.TemporaryDirectory() as second_root, \
                tempfile.TemporaryDirectory() as state_dir:
            manager = self.manager(state_dir)
            target_id = manager.create_target({
                "name": "T", "backend": "local", "root": first_root,
            }, verify=False).value
            manager.connection_for_target(target_id).pair_all_topics()

            manager.update_target(target_id, {
                "name": "T", "backend": "local", "root": second_root,
            }, verify=False)

            self.assertTrue(
                manager.connection_for_target(target_id)._state["pair_all_topics"],
            )

    def test_a_connection_with_no_target_cannot_be_paired(self):
        # Pairing is recorded on the link. A connection built straight from a
        # config file has no target record to record it on, and says so
        # rather than keeping it somewhere nothing reads.
        with tempfile.TemporaryDirectory() as relay_root, \
                tempfile.TemporaryDirectory() as state_dir:
            relay = RelayLogic(Session("addr-a"), {
                "relay_backend": "local", "relay_root": relay_root,
                "relay_state_directory": state_dir,
            })

            paired = relay.pair_all_topics()

            self.assertEqual(paired.status, "error")
            self.assertFalse(relay._state["pair_all_topics"])


if __name__ == "__main__":
    unittest.main()
