from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MakefileTests(unittest.TestCase):
    def setUp(self):
        self.makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    def test_dev_variable_controls_compose_files(self):
        self.assertIn("DEV ?=", self.makefile)
        self.assertIn("docker-compose-dev.yml", self.makefile)
        self.assertIn("$(DEV)", self.makefile)

    def test_no_dev_target_duplicates(self):
        for target in ["build-dev", "up-dev", "down-dev", "logs-dev"]:
            self.assertNotRegex(self.makefile, rf"(^|\n){target}:")

    def test_compose_uses_dev_variable(self):
        self.assertIn("COMPOSE_FILES", self.makefile)
        self.assertRegex(self.makefile, r"COMPOSE \?.*=.*\$\(DOCKER\)")
