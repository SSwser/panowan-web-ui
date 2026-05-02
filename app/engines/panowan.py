from typing import Mapping

from app.cancellation import RuntimeCancellationProbe
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

    def _build_runner_payload(self, job: Mapping[str, object]) -> dict:
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
        return build_runner_payload(api_payload)

    def prepare(self, job: Mapping[str, object]) -> object:
        raw = dict(job)
        runner_payload = self._build_runner_payload(raw)
        cancellation = raw.get("_cancellation_probe")
        if not isinstance(cancellation, RuntimeCancellationProbe):
            cancellation = None
        return self._host.prepare_runtime(
            self.provider_key,
            runner_payload,
            cancellation=cancellation,
        )

    def execute(self, job: Mapping[str, object]) -> EngineResult:
        raw = dict(job)
        runner_payload = self._build_runner_payload(raw)
        prepared = raw["_prepared_runtime"]
        cancellation = raw.get("_cancellation_probe")
        if not isinstance(cancellation, RuntimeCancellationProbe):
            cancellation = None
        result = self._host.execute_job(
            self.provider_key,
            prepared,
            runner_payload,
            cancellation=cancellation,
        )
        return EngineResult(output_path=result["output_path"], metadata={})

    def run(self, job: Mapping[str, object]) -> EngineResult:
        prepared = self.prepare(job)
        return self.execute({**dict(job), "_prepared_runtime": prepared})
