from typing import Mapping

from app.generator import build_runner_payload
from app.runtime_host import ResidentRuntimeHost

from .base import EngineResult


class PanoWanEngine:
    name = "panowan"
    capabilities = ("t2v", "i2v")
    provider_key = "panowan"

    def __init__(self, host: ResidentRuntimeHost) -> None:
        self._host = host

    def validate_runtime(self) -> None:
        # Engine no longer probes runtime files itself. Provider readiness is
        # the host's concern at preload time. Keep the method on the Protocol
        # surface but make it a no-op — runtime-availability errors will surface
        # the first time the host is asked to load the provider.
        return None

    def run(self, job: Mapping[str, object]) -> EngineResult:
        runner_payload = build_runner_payload(dict(job))
        result = self._host.run_job(self.provider_key, runner_payload)
        return EngineResult(output_path=result["output_path"], metadata={})
