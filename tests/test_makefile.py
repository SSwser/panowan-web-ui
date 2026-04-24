from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MakefileTests(unittest.TestCase):
    def setUp(self):
        self.makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    def test_explicit_role_commands_exist(self):
        for target in ["build-dev", "setup-models", "up-dev", "down-dev", "logs-dev"]:
            self.assertRegex(self.makefile, rf"(^|\n){target}:")

    def test_no_dev_mode_compose_file_switch(self):
        self.assertNotIn("ifeq ($(DEV),1)", self.makefile)
        self.assertNotIn("COMPOSE_FILE := docker-compose-dev.yml", self.makefile)
