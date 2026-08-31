import shutil
import subprocess
import unittest
from pathlib import Path


class ReactionPresentationTests(unittest.TestCase):
    def test_density_action_and_choice_combinations(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not installed")
        script = Path(__file__).with_name("reaction_presentation_test.js")

        completed = subprocess.run(
            [node, str(script)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
