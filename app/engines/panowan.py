from typing import Mapping

from app.cancellation import RuntimeCancellationProbe, legacy_probe_from_job
from app.generator import build_runner_payload
from app.runtime_host import ResidentRuntimeHost

from .base import EngineResult


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
        # The worker injects ``_cancellation_probe`` directly. Fall back to
        # wrapping a legacy ``_should_cancel`` callable for tests or external
        # embeddings that don't go through the worker loop.
        cancellation = raw.get("_cancellation_probe")
        if not isinstance(cancellation, RuntimeCancellationProbe):
            cancellation = legacy_probe_from_job(raw)
        result = self._host.run_job(
            self.provider_key,
            runner_payload,
            cancellation=cancellation,
        )
        return EngineResult(output_path=result["output_path"], metadata={})
