"""Spec-driven builder that produces ``RuntimeProvider`` adapters.

Kept separate from ``app/runtime_host.py`` so the host module stays focused on
the state machine and Protocol surface, with no dependency on backend.toml
parsing. This module wires ``ResidentProviderSpec`` (declarative) to the
runtime ``RuntimeProvider`` Protocol consumed by ``ResidentRuntimeHost``.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from collections.abc import Hashable, Mapping
from pathlib import Path
from typing import Any

from app.backends.spec import ResidentProviderSpec
from app.cancellation import RuntimeCancellationProbe
from app.runtime_host import RuntimeProvider

_REQUIRED_ATTRS = (
    "provider_key",
    "entrypoint_module",
    "load_attr",
    "execute_attr",
    "teardown_attr",
    "identity_attr",
    "failure_classifier_attr",
)


class _SpecBoundProvider:
    """Adapter that satisfies ``RuntimeProvider`` by delegating to module funcs.

    Resolved attrs are cached in ``__init__`` so per-call indirection cost is
    constant — no repeated ``getattr`` on every job.
    """

    def __init__(
        self, *, provider_key: str, module: Any, spec: ResidentProviderSpec
    ) -> None:
        # getattr without a default — surface AttributeError from the original
        # module so the operator sees which attribute is missing in which file.
        self.provider_key = provider_key
        self._load = getattr(module, spec.load_attr)
        self._execute = getattr(module, spec.execute_attr)
        self._teardown = getattr(module, spec.teardown_attr)
        self._identity = getattr(module, spec.identity_attr)
        self._classify = getattr(module, spec.failure_classifier_attr)
        # Inspect ``execute`` once so dispatch is signature-driven instead of
        # relying on a TypeError catch — that catch could swallow legitimate
        # TypeErrors from inside the provider and silently re-invoke it.
        try:
            params = inspect.signature(self._execute).parameters
        except (TypeError, ValueError):
            params = {}
        self._execute_supports_cancellation = "cancellation" in params
        if not self._execute_supports_cancellation:
            raise TypeError(
                f"Resident provider {provider_key} execute() must accept a cancellation keyword"
            )
        # default_identity is an optional Protocol member — only expose it when
        # the entrypoint module actually defines it.
        default_identity = getattr(module, "default_identity", None)
        if default_identity is not None:
            self.default_identity = default_identity

    def runtime_identity_from_job(self, job: Mapping[str, Any]) -> Hashable:
        return self._identity(job)

    def load(self, identity: Hashable) -> Any:
        return self._load(identity)

    def execute(
        self,
        loaded_runtime: Any,
        job: Mapping[str, Any],
        *,
        cancellation: RuntimeCancellationProbe | None = None,
    ) -> Mapping[str, Any]:
        return self._execute(loaded_runtime, job, cancellation=cancellation)

    def teardown(self, loaded_runtime: Any) -> None:
        self._teardown(loaded_runtime)

    def classify_failure(self, exc: BaseException) -> bool:
        return self._classify(exc)


def build_provider_from_spec(
    spec: ResidentProviderSpec,
    *,
    backend_root: Path,
) -> RuntimeProvider:
    """Build a RuntimeProvider from a backend.toml [resident_provider] section.

    Imports the entrypoint module declared in ``entrypoint_module``, resolves
    the five attributes, and returns an adapter satisfying ``RuntimeProvider``.
    ``backend_root`` is added to ``sys.path`` for the duration of the import so
    that backend-local modules like ``sources.runtime_provider`` resolve
    relative to the backend's own source tree (matching how runner.py is
    invoked with ``cwd=backend_root``).
    """
    if not spec.enabled:
        raise ValueError("Resident provider not enabled")

    missing = [name for name in _REQUIRED_ATTRS if getattr(spec, name) is None]
    if missing:
        raise ValueError(
            f"Resident provider spec missing required attrs: {', '.join(missing)}"
        )

    root_str = str(backend_root)
    sys.path.insert(0, root_str)
    try:
        module = importlib.import_module(spec.entrypoint_module)
    finally:
        # Restore sys.path whether the import succeeds or fails — mirrors the
        # try/finally contract of subprocess cwd scoping in runner.py.
        try:
            sys.path.remove(root_str)
        except ValueError:
            pass

    return _SpecBoundProvider(
        provider_key=spec.provider_key,
        module=module,
        spec=spec,
    )


__all__ = ["build_provider_from_spec"]
