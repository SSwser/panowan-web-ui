import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ViteConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")

    def test_dev_server_uses_container_friendly_port(self):
        self.assertIn("host: '0.0.0.0'", self.config)
        self.assertIn("port: 5173", self.config)
        self.assertIn("strictPort: true", self.config)

    def test_dev_server_proxy_uses_environment_target(self):
        self.assertIn("process.env.VITE_API_PROXY_TARGET", self.config)
        self.assertIn("http://127.0.0.1:8000", self.config)
        for route in ["/api", "/jobs", "/generate", "/upscale", "/health"]:
            self.assertIn(f"'{route}'", self.config)

    def test_dev_server_supports_polling_for_docker_desktop(self):
        self.assertIn("CHOKIDAR_USEPOLLING", self.config)
        self.assertIn("usePolling", self.config)


if __name__ == "__main__":
    unittest.main()
