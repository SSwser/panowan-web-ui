"""PanoWan resident runtime provider — backend-root entrypoint.

Per spec §9: this module shares the same backend-root validation/dispatch
semantics as ``runner.py`` so CLI and resident execution cannot diverge.
``validate_job`` and the runtime identity / failure classification helpers
are imported from ``sources.runtime_adapter`` (single source of truth).

Phase C ships the resident-host contract surface only. Real model
construction lives behind a TODO and will land in the migration roadmap
(see docs/superpowers/specs/2026-04-30-platform-resident-runtime-host-design.md).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

# Import path note: runner.py invokes this module with ``cwd=backend_root`` so
# the ``sources`` package sits at the top level. The platform builder also
# inserts ``backend_root`` into ``sys.path`` before importing
# ``sources.runtime_provider``. In both cases an absolute ``sources.*`` import
# would work — but tests and project-level tooling import this file via the
# fully qualified ``third_party.PanoWan.sources`` path, where ``sources`` is
# not a top-level package. A relative import resolves correctly in all three
# contexts and keeps the single-source-of-truth re-export contract intact.
from .runtime_adapter import (
    InvalidRunnerJob,
    PanoWanRuntimeIdentity,
    classify_runtime_failure as _classify_runtime_failure,
    runtime_identity_from_job as _runtime_identity_from_job,
    validate_job,
)

# Re-export so the platform builder resolves the SAME object as the adapter
# module (single source of truth for identity and failure classification).
runtime_identity_from_job = _runtime_identity_from_job
classify_runtime_failure = _classify_runtime_failure


def load_resident_runtime(identity: PanoWanRuntimeIdentity) -> dict[str, Any]:
    # TODO(phase-D+): construct the actual Wan2.1 + LoRA pipeline here. Phase C
    # only ships the resident-host contract surface; the pipeline is a stub
    # mirroring runner.py's Phase 1 semantics.
    pipeline = {
        "wan_model_path": identity.wan_model_path,
        "lora_checkpoint_path": identity.lora_checkpoint_path,
    }
    return {"identity": identity, "pipeline": pipeline}


def run_job_inprocess(
    loaded: dict[str, Any], job: Mapping[str, Any]
) -> dict[str, Any]:
    # Mirror runner.py: validate_job enforces the runner contract identically
    # whether we're in-process (resident) or subprocess (CLI/debug).
    payload = validate_job(dict(job))
    output_path = payload["output_path"]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).touch()
    return {"status": "ok", "output_path": output_path}


def teardown_resident_runtime(loaded: dict[str, Any]) -> None:
    # Best-effort: drop references so GC can reclaim the loaded pipeline. Must
    # not raise on already-empty dicts — the host calls teardown defensively
    # during eviction and failure recovery.
    if not loaded:
        return
    loaded.clear()


__all__ = [
    "load_resident_runtime",
    "run_job_inprocess",
    "teardown_resident_runtime",
    "runtime_identity_from_job",
    "classify_runtime_failure",
    "InvalidRunnerJob",
    "PanoWanRuntimeIdentity",
]
