"""A state file belongs to a connection, and does not outlive it.

Relay bookkeeping is written per connection, named for the identity and the
storage location it belongs to. Nothing ever reads one back under a different
name, so every connection that ends without taking its file with it leaves an
orphan - found live as a data/ directory holding dozens of all-empty state
files, none attributable to anything still configured.

Two ways a connection ends that way, plus the setting that decides where the
files live at all: it was retired, or it re-keyed to another location.
"""

import tempfile
import unittest
from pathlib import Path

from sovereign.relay_logic import RelayLogic, RelayManager
from sovereign.session import Session


class StateFilePlacementTests(unittest.TestCase):
    def test_the_implicit_connection_honours_the_state_directory(self):
        # The setting used to reach connections built from a target only.
        # An instance that set it still had its implicit connection writing
        # into the shared data/ beside the working directory, so the one
        # setting that is supposed to isolate an instance did not.
        with tempfile.TemporaryDirectory() as relay_root, \
                tempfile.TemporaryDirectory() as state_dir:
            session = Session("addr-a")
            relay = RelayLogic(session, {
                "relay_backend": "local", "relay_root": relay_root,
                "relay_state_directory": state_dir,
            })
            relay._save_state()  # cache, the only thing this file holds

            path = Path(relay._state_path)
            self.assertEqual(path.parent, Path(state_dir))
            self.assertTrue(path.is_file())

    def test_both_kinds_of_connection_are_named_the_same_way(self):
        # One directory holds both, so they have to agree on how a location
        # is named - otherwise the same relay is bookkept twice under two
        # spellings of the same fact.
        with tempfile.TemporaryDirectory() as relay_root, \
                tempfile.TemporaryDirectory() as state_dir:
            implicit = RelayLogic(Session("addr-a"), {
                "relay_backend": "local", "relay_root": relay_root,
                "relay_state_directory": state_dir,
            })
            manager = RelayManager(Session("addr-b"), {
                "relay_state_directory": state_dir,
            })
            target_id = manager.create_target({
                "name": "T", "backend": "local", "root": relay_root,
            }, verify=False).value

            from_target = manager.connection_for_target(target_id)

            self.assertEqual(
                Path(from_target._state_path).name,
                Path(implicit._state_path).name,
            )


class StateFileLifetimeTests(unittest.TestCase):
    def test_retiring_a_connection_takes_its_state_file_with_it(self):
        # Retiring used to blank shared/desired/identity_topics and save the
        # emptied state, which is what produced the all-empty orphans: the
        # file survived every connection that ever ended.
        with tempfile.TemporaryDirectory() as relay_root, \
                tempfile.TemporaryDirectory() as state_dir:
            session = Session("addr-a")
            manager = RelayManager(session, {
                "relay_state_directory": state_dir,
            })
            target_id = manager.create_target({
                "name": "T", "backend": "local", "root": relay_root,
            }, verify=False).value
            connection = manager.connection_for_target(target_id)
            connection._save_state()
            state_path = Path(connection._state_path)
            self.assertTrue(state_path.is_file())

            manager.delete_target(target_id)

            self.assertFalse(state_path.is_file())

    def test_adopting_a_location_removes_the_file_it_leaves_behind(self):
        # A token-provisioned client boots with no storage, so its first
        # state path is fingerprinted from a location it never talks to.
        # Adoption re-keys the path and reloads - discarding that file's
        # contents either way, so leaving the file is pure residue.
        with tempfile.TemporaryDirectory() as relay_root, \
                tempfile.TemporaryDirectory() as state_dir:
            session = Session("addr-a")
            relay = RelayLogic(session, {"relay_state_directory": state_dir})
            relay._save_state()
            boot_path = Path(relay._state_path)
            self.assertTrue(boot_path.is_file())

            relay.adopt_storage_from_descriptor({
                "type": "relay", "root": relay_root,
            })

            self.assertNotEqual(Path(relay._state_path), boot_path)
            self.assertFalse(boot_path.is_file())


if __name__ == "__main__":
    unittest.main()
