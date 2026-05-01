from typing import Mapping

from app.cancellation import (
    CallbackCancellationProbe,
    CancellationContext,
    RuntimeCancellationProbe,
)
from app.generator import build_runner_payload
from app.runtime_host import ResidentRuntimeHost

from .base import EngineResult


def _legacy_probe_from(job: Mapping[str, object]) -> RuntimeCancellationProbe | None:
    # Worker injection of ``_cancellation_probe`` lands in a follow-up task;
    # until then, fall back to the legacy ``_should_cancel`` callable so
    # cancellation continues to reach the host without behavioural change.
    legacy = job.get("_should_cancel")
    if not callable(legacy):
        return None
    job_id = str(job.get("job_id") or job.get("id") or "")
    worker_id = str(job.get("worker_id") or "")
    return CallbackCancellationProbe(
        context=CancellationContext(
            job_id=job_id,
            worker_id=worker_id,
            mode="soft",
            requested_at="",
            deadline_at="",
            attempt=0,
        ),
        _stop_check=legacy,
    )


class PanoWanEngine:
    name = "panowan"
    capabilities = ("t2v", "i2v")
    provider_key = "panowan"
    i2v_not_implemented_message = (
        "task='i2v' is reserved in the runner contract but is not implemented yet"
    )

    def __init__(self, host: ResidentRuntimeHost) -> None:
        self._host = host

    def validate_runtime(self) -> None:
        # Engine no longer probes runtime files itself. Provider readiness is
        # the host's concern at preload time. Keep the method on the Protocol
        # surface but make it a no-op — runtime-availability errors will surface
        # the first time the host is asked to load the provider.
        return None

    def run(self, job: Mapping[str, object]) -> EngineResult:
        # Worker passes the full job record (status, params, payload, …);
        # build_runner_payload expects the API-originated payload dict.
        raw = dict(job)
        api_payload = raw.get("payload")
        if isinstance(api_payload, dict):
            # Carry job-level fields that build_runner_payload also reads.
            api_payload = {
                "id": raw.get("id") or raw.get("job_id"),
                "output_path": raw.get("output_path"),
                **api_payload,
            }
        else:
            api_payload = raw
        task = api_payload.get("task") or api_payload.get("mode") or "t2v"
        # Keep i2v visible in the public contract so the API/worker boundary is
        # already shaped for the upcoming implementation, but fail here with a
        # stable error instead of letting the request reach deeper runtime code.
        if task == "i2v":
            raise NotImplementedError(self.i2v_not_implemented_message)
        runner_payload = build_runner_payload(api_payload)
        cancellation = raw.get("_cancellation_probe")
        if not isinstance(cancellation, RuntimeCancellationProbe):
            cancellation = _legacy_probe_from(raw)
        result = self._host.run_job(
            self.provider_key,
            runner_payload,
            cancellation=cancellation,
        )
        return EngineResult(output_path=result["output_path"], metadata={})
