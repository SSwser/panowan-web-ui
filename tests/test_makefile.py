import unittest
from pathlib import Path

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

    def test_makefile_selects_shell_from_current_platform(self):
        self.assertIn("ifeq ($(OS),Windows_NT)", self.makefile)
        self.assertIn("BASH ?= sh", self.makefile)
        self.assertIn("else\nBASH ?= bash\nendif", self.makefile)
        self.assertIn("DOCKER ?= $(BASH) scripts/docker-proxy.sh", self.makefile)
        self.assertIn("DATA_SYNC ?= $(BASH) scripts/data-sync.sh", self.makefile)
        self.assertIn("NORMALIZE_BIND_PATH ?= $(BASH) scripts/lib/path.sh", self.makefile)
        self.assertNotIn("GIT_BASH ?=", self.makefile)
        self.assertNotIn("C:/Program Files/Git/bin/bash.exe", self.makefile)
        self.assertNotIn("DOCKER ?= bash scripts/docker-proxy.sh", self.makefile)
        self.assertNotIn("DATA_SYNC ?= bash scripts/data-sync.sh", self.makefile)
        self.assertNotIn("NORMALIZE_BIND_PATH ?= bash scripts/lib/path.sh", self.makefile)

    def test_dev_exports_frontend_port_for_compose(self):
        self.assertIn("FRONTEND_PORT ?= 5173", self.makefile)
        self.assertIn("export FRONTEND_PORT", self.makefile)

    def test_up_removes_orphans_by_default(self):
        self.assertIn("UP_FLAGS ?= --remove-orphans", self.makefile)
        self.assertIn("$(COMPOSE) up -d $(UP_FLAGS)", self.makefile)

    def test_setup_bootstrap_creates_checkout_local_venv(self):
        self.assertRegex(self.makefile, r"\nsetup-bootstrap:\n")
        self.assertIn("VENV_DIR ?= .venv", self.makefile)
        self.assertIn("HOST_PYTHON ?= py -3.12", self.makefile)
        self.assertIn("VENV_PYTHON ?= $(VENV_DIR)/Scripts/python.exe", self.makefile)
        self.assertIn("PYTHON_RUN := $(VENV_PYTHON)", self.makefile)
        self.assertIn('if [ ! -x "$(VENV_PYTHON)" ]; then', self.makefile)
        self.assertIn("$(HOST_PYTHON) -m venv $(VENV_DIR)", self.makefile)
        self.assertIn("import pip, sys", self.makefile)
        self.assertIn("sys.version_info[:2] == (3, 12)", self.makefile)
        self.assertIn("rm -rf $(VENV_DIR)", self.makefile)
        self.assertIn("$(PYTHON_RUN) -m ensurepip --upgrade", self.makefile)
        self.assertIn('$(PYTHON_RUN) -m pip install -e ".[host-runtime]"', self.makefile)
        self.assertIn("git submodule update --init --recursive", self.makefile)
        self.assertNotIn("uv sync --group dev", self.makefile)
        self.assertNotIn("$(PYTHON_RUN) -m pip install -e .", self.makefile)
        self.assertNotIn("python -m venv $(VENV_DIR)", self.makefile)

    def test_setup_uses_install_bootstrap(self):
        self.assertRegex(self.makefile, r"\nsetup-bootstrap-main: setup-bootstrap\n")
        self.assertIn("$(PYTHON_RUN) -m app.backends install", self.makefile)
        self.assertRegex(self.makefile, r"\nsetup: setup-bootstrap-main\n")

    def test_setup_worktree_uses_verify_bootstrap(self):
        self.assertRegex(self.makefile, r"\nsetup-bootstrap-worktree: setup-bootstrap\n")
        self.assertIn("$(PYTHON_RUN) -m app.backends verify", self.makefile)
        self.assertRegex(self.makefile, r"\nsetup-worktree:\n")
        self.assertIn("$(DATA_SYNC) link $(if $(WITH_RUNTIME),--runtime)", self.makefile)
        self.assertIn("@$(MAKE) setup-bootstrap-worktree", self.makefile)
        self.assertNotIn("@$(MAKE) setup-bootstrap-main", self.makefile)
        self.assertIn("setup-bootstrap-worktree: setup-bootstrap", self.makefile)

    def test_verify_runs_test_then_doctor(self):
        self.assertRegex(self.makefile, r"\nverify:\n")
        self.assertIn("@$(MAKE) test", self.makefile)
        self.assertIn("$(BASH) scripts/doctor.sh", self.makefile)
        self.assertRegex(self.makefile, r"\nlogs:\n")

    def test_test_target_uses_checkout_local_pythonpath(self):
        self.assertIn("CURDIR", self.makefile)
        self.assertIn("PYTHONPATH=$(CURDIR) $(PYTHON_RUN) -m unittest discover -s tests", self.makefile)
        self.assertNotIn("python -m unittest discover -s tests", self.makefile)

    def test_build_runs_prune_by_default_and_can_disable_it(self):
        self.assertIn("AUTO_PRUNE ?= 1", self.makefile)
        self.assertIn("PRUNE_CMD := $(DOCKER) image prune -f", self.makefile)
        self.assertIn("ifeq ($(AUTO_PRUNE),0)", self.makefile)
        self.assertIn("BUILD_PRUNE_STEP := @:", self.makefile)
        self.assertIn("$(BUILD_PRUNE_STEP)", self.makefile)
        self.assertRegex(self.makefile, r"\nprune:\n")
        self.assertIn("$(PRUNE_CMD)", self.makefile)

    def test_makefile_adds_stage_announcements(self):
        self.assertIn("define announce", self.makefile)
        self.assertIn("==> %s", self.makefile)
        self.assertIn("$(call announce,Link shared worktree data)", self.makefile)
        self.assertIn("$(call announce,Validate uv lockfile)", self.makefile)
        self.assertIn("$(call announce,Build compose images)", self.makefile)
        self.assertIn("$(call announce,Prune dangling Docker images)", self.makefile)

    def test_legacy_make_targets_are_removed(self):
        for target in [
            "init",
            "env",
            "setup-python",
            "setup-submodules",
            "setup-backends",
            "doctor",
            "health",
            "data-link",
            "data-unlink",
            "data-status",
            "init-worktree",
            "docker-env",
        ]:
            self.assertNotRegex(self.makefile, rf"(^|\n){target}:")
        for target in ["up", "down", "logs"]:
            self.assertEqual(self.makefile.count(f"\n{target}:\n"), 1)
        self.assertEqual(self.makefile.count("\nprune:\n"), 1)
        self.assertEqual(self.makefile.count("\nbuild:\n"), 1)
        self.assertNotIn("GIT_BASH ?=", self.makefile)
        self.assertNotIn("C:/Program Files/Git/bin/bash.exe", self.makefile)

    def test_data_sync_guides_users_on_local_directory_conflicts(self):
        data_sync = (ROOT / "scripts" / "data-sync.sh").read_text(encoding="utf-8")
        self.assertIn("refusing to replace real directory", data_sync)
        self.assertIn("Move or remove that worktree-local directory first", data_sync)
        self.assertIn("Expected shared source: $expected_target", data_sync)
        self.assertIn("must run from a Windows POSIX shell such as Git Bash", data_sync)
        self.assertNotIn("not WSL bash", data_sync)
        self.assertNotIn("This script supports Git Bash on Windows only.", data_sync)

    def test_makefile_uses_backend_verify_command_in_scripts(self):
        self.assertIn(
            "python -m app.backends verify",
            (ROOT / "scripts" / "check-runtime.sh").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
