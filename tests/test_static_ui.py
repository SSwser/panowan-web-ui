import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import api


class ReactStaticUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.frontend_dist = Path(self.temp_dir.name) / "frontend" / "dist"
        self.frontend_dist.mkdir(parents=True)
        (self.frontend_dist / "index.html").write_text(
            '<div id="root"></div><script type="module" src="/assets/index.js"></script>',
            encoding="utf-8",
        )
        patched_settings = replace(api.settings, frontend_dist_dir=str(self.frontend_dist))
        self.settings_patch = patch("app.api.settings", patched_settings)
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.client = TestClient(api.app)

    def test_root_serves_react_build_index(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('<div id="root"></div>', response.text)
        self.assertIn('/assets/index.js', response.text)

    def test_root_reports_missing_build_clearly(self) -> None:
        os.remove(self.frontend_dist / "index.html")

        response = self.client.get("/")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Frontend build not found. Run npm --prefix frontend run build.")


if __name__ == "__main__":
    unittest.main()
