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
            '<div id="root"></div><script type="module" src="/assets/index.js"></script><link rel="stylesheet" href="/assets/index.css">',
            encoding="utf-8",
        )
        assets_dir = self.frontend_dist / "assets"
        assets_dir.mkdir()
        (assets_dir / "index.js").write_text('document.querySelector("#root").textContent = "loaded";', encoding="utf-8")
        (assets_dir / "index.css").write_text("#root { color: black; }", encoding="utf-8")
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

    def test_react_assets_are_served_from_build_output(self) -> None:
        script_response = self.client.get("/assets/index.js")
        style_response = self.client.get("/assets/index.css")

        self.assertEqual(script_response.status_code, 200)
        self.assertIn("loaded", script_response.text)
        self.assertEqual(style_response.status_code, 200)
        self.assertIn("color: black", style_response.text)

    def test_asset_route_rejects_missing_files(self) -> None:
        response = self.client.get("/assets/missing.js")

        self.assertEqual(response.status_code, 404)

    def test_favicon_does_not_pollute_browser_console(self) -> None:
        response = self.client.get("/favicon.ico")

        self.assertEqual(response.status_code, 204)


if __name__ == "__main__":
    unittest.main()
