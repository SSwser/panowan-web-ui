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

    def test_init_bootstraps_python_before_setup_backends(self):
        self.assertRegex(
            self.makefile,
            r"\ninit: env setup-python setup-submodules setup-backends doctor\n",
        )

    def test_setup_python_uses_uv_or_pip_fallback(self):
        self.assertRegex(self.makefile, r"\nsetup-python:\n")
        self.assertIn("uv sync --group dev", self.makefile)
        self.assertIn("python -m pip install -e .", self.makefile)

    def test_setup_backends_depends_on_setup_python(self):
        self.assertRegex(self.makefile, r"\nsetup-backends: setup-python\n")
