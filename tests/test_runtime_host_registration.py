import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from app.backends.spec import ResidentProviderSpec, load_backend_spec
from app.runtime_host_registration import build_provider_from_spec

_PROVIDER_MODULE_TEMPLATE = textwrap.dedent("""
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Identity:
        wan: str

    def load(identity):
        return {"identity": identity, "loaded": True}

    def execute(loaded, job, *, should_cancel=None):
        return {"status": "ok", "job": dict(job), "loaded": loaded}

    def teardown(loaded):
        loaded.clear()

    def identity_from_job(job):
        return _Identity(wan=job["wan"])

    def classify(exc):
        return isinstance(exc, MemoryError)
    """)


def _make_spec(
    module_name: str, *, with_default_identity: bool = False
) -> ResidentProviderSpec:
    return ResidentProviderSpec(
        enabled=True,
        provider_key="synthetic",
        entrypoint_module=module_name,
        load_attr="load",
        execute_attr="execute",
        teardown_attr="teardown",
        identity_attr="identity_from_job",
        failure_classifier_attr="classify",
    )


def _write_synthetic_backend(
    backend_root: Path,
    module_name: str,
    *,
    body: str = _PROVIDER_MODULE_TEMPLATE,
) -> None:
    backend_root.mkdir(parents=True, exist_ok=True)
    (backend_root / f"{module_name}.py").write_text(body, encoding="utf-8")


class BuildProviderFromSpecTests(unittest.TestCase):
    _counter = 0

    def _unique_module(self) -> str:
        BuildProviderFromSpecTests._counter += 1
        name = f"synthetic_provider_{BuildProviderFromSpecTests._counter}"
        self.addCleanup(lambda n=name: sys.modules.pop(n, None))
        return name

    def test_disabled_spec_raises(self) -> None:
        spec = ResidentProviderSpec(enabled=False)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "not enabled"):
                build_provider_from_spec(spec, backend_root=Path(tmp))

    def test_missing_required_attr_raises_listing_name(self) -> None:
        # provider_key is required when enabled=True.
        spec = ResidentProviderSpec(
            enabled=True,
            provider_key=None,
            entrypoint_module="x",
            load_attr="a",
            execute_attr="b",
            teardown_attr="c",
            identity_attr="d",
            failure_classifier_attr="e",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "provider_key"):
                build_provider_from_spec(spec, backend_root=Path(tmp))

    def test_successful_build_returns_provider_with_matching_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            module_name = self._unique_module()
            _write_synthetic_backend(Path(tmp), module_name)
            spec = _make_spec(module_name)
            provider = build_provider_from_spec(spec, backend_root=Path(tmp))
            self.assertEqual(provider.provider_key, "synthetic")

    def test_built_provider_delegates_to_module_functions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            module_name = self._unique_module()
            _write_synthetic_backend(Path(tmp), module_name)
            spec = _make_spec(module_name)
            provider = build_provider_from_spec(spec, backend_root=Path(tmp))

            identity = provider.runtime_identity_from_job({"wan": "/m"})
            self.assertEqual(identity.wan, "/m")

            loaded = provider.load(identity)
            self.assertEqual(loaded["identity"], identity)
            self.assertTrue(loaded["loaded"])

            result = provider.execute(loaded, {"wan": "/m", "k": 1})
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["job"], {"wan": "/m", "k": 1})

            self.assertTrue(provider.classify_failure(MemoryError("oom")))
            self.assertFalse(provider.classify_failure(ValueError("x")))

            provider.teardown(loaded)
            self.assertEqual(loaded, {})

    def test_default_identity_exposed_when_module_defines_it(self) -> None:
        body = _PROVIDER_MODULE_TEMPLATE + textwrap.dedent("""
            def default_identity():
                return _Identity(wan="default")
            """)
        with tempfile.TemporaryDirectory() as tmp:
            module_name = self._unique_module()
            _write_synthetic_backend(Path(tmp), module_name, body=body)
            spec = _make_spec(module_name)
            provider = build_provider_from_spec(spec, backend_root=Path(tmp))
            self.assertTrue(hasattr(provider, "default_identity"))
            self.assertEqual(provider.default_identity().wan, "default")

    def test_default_identity_absent_when_module_omits_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            module_name = self._unique_module()
            _write_synthetic_backend(Path(tmp), module_name)
            spec = _make_spec(module_name)
            provider = build_provider_from_spec(spec, backend_root=Path(tmp))
            self.assertFalse(hasattr(provider, "default_identity"))

    def test_sys_path_restored_after_successful_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            module_name = self._unique_module()
            _write_synthetic_backend(Path(tmp), module_name)
            spec = _make_spec(module_name)
            before = list(sys.path)
            build_provider_from_spec(spec, backend_root=Path(tmp))
            self.assertEqual(sys.path, before)

    def test_sys_path_restored_after_failed_import(self) -> None:
        # Module file does not exist — import will raise, sys.path must restore.
        with tempfile.TemporaryDirectory() as tmp:
            spec = _make_spec("does_not_exist_module")
            before = list(sys.path)
            with self.assertRaises(ModuleNotFoundError):
                build_provider_from_spec(spec, backend_root=Path(tmp))
            self.assertEqual(sys.path, before)


class EndToEndPanoWanWiringTests(unittest.TestCase):
    def test_real_panowan_backend_toml_wires_provider(self) -> None:
        spec_path = Path("third_party/PanoWan/backend.toml")
        backend_spec = load_backend_spec(spec_path)
        provider = build_provider_from_spec(
            backend_spec.resident_provider,
            backend_root=backend_spec.root,
        )
        self.assertEqual(provider.provider_key, "panowan")

        from third_party.PanoWan.sources import runtime_provider as rp

        # The bound load attr must be the same function object exposed by the
        # backend-root-loaded module (importlib caches it as ``sources.runtime_provider``
        # after build). This guards against accidental wrapping in the builder.
        # Note: this is a different sys.modules entry than the project-relative
        # ``third_party.PanoWan.sources.runtime_provider`` import — they're the
        # same source file evaluated under two import paths.
        backend_loaded = sys.modules["sources.runtime_provider"]
        self.assertIs(provider._load, backend_loaded.load_resident_runtime)
        # And the underlying behavior must match the project-relative module's
        # function: same qualified name and same source-defined symbol.
        self.assertEqual(
            provider._load.__qualname__, rp.load_resident_runtime.__qualname__
        )


if __name__ == "__main__":
    unittest.main()
