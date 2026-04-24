import importlib
import sys
import unittest
from unittest import mock


class ApiServiceTests(unittest.TestCase):
    def test_api_service_does_not_import_worker_or_engines_at_startup(self):
        # Snapshot modules we're about to pop so we can restore them and
        # avoid contaminating sibling test files that already imported
        # symbols from these modules (e.g. tests/test_engines.py's
        # PanoWanEngine reference is bound to the original module object;
        # if we leave a fresh re-imported module in sys.modules,
        # mock.patch will patch the wrong instance).
        prefixes = ("app.api_service", "app.worker_service", "app.engines")
        snapshot = {
            name: sys.modules[name]
            for name in list(sys.modules)
            if any(name == p or name.startswith(p + ".") for p in prefixes)
        }
        for name in snapshot:
            sys.modules.pop(name, None)

        def _restore() -> None:
            # Drop anything imported during the test, then put the original
            # modules back exactly as they were.
            for name in list(sys.modules):
                if any(name == p or name.startswith(p + ".") for p in prefixes):
                    sys.modules.pop(name, None)
            sys.modules.update(snapshot)

        self.addCleanup(_restore)

        for module_name in list(sys.modules):
            if module_name.startswith("app.api_service") or module_name.startswith("app.worker_service") or module_name.startswith("app.engines"):
                sys.modules.pop(module_name, None)

        importlib.import_module("app.api_service")

        self.assertNotIn("app.worker_service", sys.modules)
        self.assertNotIn("app.engines.panowan", sys.modules)

    @mock.patch("app.api_service.uvicorn.run")
    def test_main_uses_reload_only_in_dev_mode(self, run):
        module = importlib.import_module("app.api_service")
        with mock.patch.dict("os.environ", {"DEV_MODE": "1"}):
            module.main()
        self.assertTrue(run.call_args.kwargs["reload"])
