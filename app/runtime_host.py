"""Worker-owned platform service for resident runtime providers.

This module is backend-agnostic. It defines the host state machine, the
``RuntimeProvider`` Protocol that backend adapters implement, and the
``ResidentRuntimeHost`` orchestrator that owns lifecycle (load, warm reuse,
identity-mismatch reload, eviction, failure classification, idle policy).

Backend-specific code lives in providers — never in the host. See
``docs/adr/0009-worker-owned-resident-runtime-host.md`` and
``docs/superpowers/specs/2026-04-30-platform-resident-runtime-host-design.md``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from app.cancellation import RuntimeCancellationProbe

logger = logging.getLogger(__name__)


class RuntimeState(str, Enum):
    COLD = "cold"
    LOADING = "loading"
    WARM = "warm"
    RUNNING = "running"
    EVICTING = "evicting"
    FAILED = "failed"


@runtime_checkable
class RuntimeProvider(Protocol):
    """Backend-specific adapter consumed by ``ResidentRuntimeHost``.

    The host never imports providers directly — they are registered at runtime
    so the platform layer stays free of backend imports.
    """

    provider_key: str

    def runtime_identity_from_job(self, job: Mapping[str, Any]) -> Hashable: ...
    def load(
        self,
        identity: Hashable,
        *,
        cancellation: RuntimeCancellationProbe | None = None,
    ) -> Any: ...
    def execute(
        self,
        loaded_runtime: Any,
        job: Mapping[str, Any],
        *,
        cancellation: RuntimeCancellationProbe | None = None,
    ) -> Mapping[str, Any]: ...
    def teardown(self, loaded_runtime: Any) -> None: ...
    def classify_failure(self, exc: BaseException) -> bool: ...


@dataclass
class RuntimeInstance:
    provider_key: str
    identity: Hashable | None
    state: RuntimeState
    loaded: Any = None
    last_used_at: float | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class RuntimeStatusSnapshot:
    provider_key: str
    state: RuntimeState
    identity: Hashable | None
    last_used_at: float | None
    last_error: str | None


class ResidentRuntimeHost:
    """Worker-owned host that manages backend-specific runtime providers.

    Concurrency model:
      * ``_state_lock`` guards the registry dicts (provider lookup,
        instance-state mutation snapshot reads).
      * Each provider has its own ``threading.Lock`` so that runs against
        different providers can proceed in parallel while runs against the
        same provider serialize.
      * Long-running provider calls (``load``/``execute``/``teardown``) are
        invoked WITHOUT holding ``_state_lock``; only the per-provider lock
        is held across them. This keeps ``status``/``status_all`` cheap and
        avoids cross-provider head-of-line blocking on lifecycle work.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._state_lock = threading.Lock()
        self._providers: dict[str, RuntimeProvider] = {}
        self._instances: dict[str, RuntimeInstance] = {}
        self._provider_locks: dict[str, threading.Lock] = {}

    # ---- registration -------------------------------------------------

    def register_provider(self, provider: RuntimeProvider) -> None:
        key = provider.provider_key
        with self._state_lock:
            if key in self._providers:
                raise ValueError(f"provider already registered: {key}")
            self._providers[key] = provider
            self._provider_locks[key] = threading.Lock()
            self._instances[key] = RuntimeInstance(
                provider_key=key,
                identity=None,
                state=RuntimeState.COLD,
            )

    def has_provider(self, provider_key: str) -> bool:
        with self._state_lock:
            return provider_key in self._providers

    # ---- internal helpers --------------------------------------------

    def _require(
        self, provider_key: str
    ) -> tuple[RuntimeProvider, RuntimeInstance, threading.Lock]:
        with self._state_lock:
            if provider_key not in self._providers:
                raise KeyError(provider_key)
            return (
                self._providers[provider_key],
                self._instances[provider_key],
                self._provider_locks[provider_key],
            )

    def _set_state(self, instance: RuntimeInstance, state: RuntimeState) -> None:
        with self._state_lock:
            instance.state = state

    def _safe_teardown(
        self, provider: RuntimeProvider, instance: RuntimeInstance
    ) -> None:
        """Tear down loaded runtime, swallowing errors.

        Teardown failures must not propagate to callers — the host's job is to
        return the slot to COLD so future loads can proceed. We log and force
        the slot back to a clean cold state.
        """
        loaded = instance.loaded
        if loaded is None:
            with self._state_lock:
                instance.state = RuntimeState.COLD
                instance.identity = None
            return
        try:
            provider.teardown(loaded)
        except BaseException:  # noqa: BLE001 — intentional swallow, see docstring
            logger.exception(
                "resident runtime host: teardown failed for provider %s",
                provider.provider_key,
            )
        finally:
            with self._state_lock:
                instance.loaded = None
                instance.identity = None
                instance.state = RuntimeState.COLD

    def _load(
        self,
        provider: RuntimeProvider,
        instance: RuntimeInstance,
        identity: Hashable,
        *,
        cancellation: RuntimeCancellationProbe | None = None,
    ) -> None:
        self._set_state(instance, RuntimeState.LOADING)
        try:
            loaded = provider.load(identity, cancellation=cancellation)
        except BaseException as exc:
            with self._state_lock:
                instance.state = RuntimeState.FAILED
                instance.last_error = str(exc)
                instance.loaded = None
                instance.identity = None
            raise
        with self._state_lock:
            instance.loaded = loaded
            instance.identity = identity
            instance.last_error = None
            instance.state = RuntimeState.WARM

    # ---- public lifecycle --------------------------------------------

    def prepare_runtime(
        self,
        provider_key: str,
        job: Mapping[str, Any],
        *,
        cancellation: RuntimeCancellationProbe | None = None,
    ) -> Any:
        provider, instance, lock = self._require(provider_key)
        with lock:
            # Preparation repairs a failed resident runtime before loading so a
            # previous corrupting execute failure cannot poison the next job.
            if instance.state == RuntimeState.FAILED:
                self._set_state(instance, RuntimeState.EVICTING)
                self._safe_teardown(provider, instance)

            identity = provider.runtime_identity_from_job(job)

            if instance.state == RuntimeState.WARM and instance.identity != identity:
                self._set_state(instance, RuntimeState.EVICTING)
                self._safe_teardown(provider, instance)

            if instance.state == RuntimeState.COLD:
                self._load(provider, instance, identity, cancellation=cancellation)

            return instance.loaded

    def execute_job(
        self,
        provider_key: str,
        loaded_runtime: Any,
        job: Mapping[str, Any],
        *,
        cancellation: RuntimeCancellationProbe | None = None,
    ) -> Mapping[str, Any]:
        provider, instance, lock = self._require(provider_key)
        with lock:
            self._set_state(instance, RuntimeState.RUNNING)
            try:
                result = provider.execute(
                    loaded_runtime, job, cancellation=cancellation
                )
            except BaseException as exc:
                corrupting = bool(provider.classify_failure(exc))
                if corrupting:
                    with self._state_lock:
                        instance.state = RuntimeState.FAILED
                        instance.last_error = str(exc)
                else:
                    with self._state_lock:
                        instance.state = RuntimeState.WARM
                        instance.last_used_at = self._clock()
                raise
            with self._state_lock:
                instance.last_used_at = self._clock()
                instance.state = RuntimeState.WARM
            return result

    def run_job(
        self,
        provider_key: str,
        job: Mapping[str, Any],
        *,
        cancellation: RuntimeCancellationProbe | None = None,
    ) -> Mapping[str, Any]:
        loaded_runtime = self.prepare_runtime(
            provider_key, job, cancellation=cancellation
        )
        return self.execute_job(
            provider_key,
            loaded_runtime,
            job,
            cancellation=cancellation,
        )

    def preload(self, provider_key: str, identity: Hashable | None = None) -> None:
        provider, instance, lock = self._require(provider_key)
        with lock:
            if identity is None:
                default_fn = getattr(provider, "default_identity", None)
                if default_fn is None:
                    raise ValueError(
                        f"provider {provider_key} has no default_identity(); "
                        "preload requires an explicit identity"
                    )
                identity = default_fn()
                if identity is None:
                    raise ValueError(
                        f"provider {provider_key}.default_identity() returned None"
                    )

            if instance.state == RuntimeState.FAILED:
                self._set_state(instance, RuntimeState.EVICTING)
                self._safe_teardown(provider, instance)

            if instance.state == RuntimeState.WARM:
                if instance.identity == identity:
                    return
                self._set_state(instance, RuntimeState.EVICTING)
                self._safe_teardown(provider, instance)

            if instance.state == RuntimeState.COLD:
                self._load(provider, instance, identity, cancellation=None)
                return

            raise RuntimeError(
                f"preload called in unexpected state {instance.state} for {provider_key}"
            )

    def evict(self, provider_key: str) -> None:
        provider, instance, lock = self._require(provider_key)
        with lock:
            if instance.state == RuntimeState.COLD and instance.loaded is None:
                return
            self._set_state(instance, RuntimeState.EVICTING)
            self._safe_teardown(provider, instance)

    def reset_failed(self, provider_key: str) -> None:
        provider, instance, lock = self._require(provider_key)
        with lock:
            if instance.state != RuntimeState.FAILED:
                return
            self._set_state(instance, RuntimeState.EVICTING)
            self._safe_teardown(provider, instance)
            with self._state_lock:
                instance.last_error = None

    def maybe_evict_idle(self, provider_key: str, idle_evict_seconds: float) -> bool:
        provider, instance, lock = self._require(provider_key)
        with lock:
            if instance.state != RuntimeState.WARM:
                return False
            last = instance.last_used_at
            if last is None:
                return False
            if self._clock() - last < idle_evict_seconds:
                return False
            self._set_state(instance, RuntimeState.EVICTING)
            self._safe_teardown(provider, instance)
            return True

    # ---- introspection -----------------------------------------------

    def status(self, provider_key: str) -> RuntimeStatusSnapshot | None:
        with self._state_lock:
            instance = self._instances.get(provider_key)
            if instance is None:
                return None
            return RuntimeStatusSnapshot(
                provider_key=instance.provider_key,
                state=instance.state,
                identity=instance.identity,
                last_used_at=instance.last_used_at,
                last_error=instance.last_error,
            )

    def status_all(self) -> Mapping[str, RuntimeStatusSnapshot]:
        with self._state_lock:
            return {
                key: RuntimeStatusSnapshot(
                    provider_key=inst.provider_key,
                    state=inst.state,
                    identity=inst.identity,
                    last_used_at=inst.last_used_at,
                    last_error=inst.last_error,
                )
                for key, inst in self._instances.items()
            }
