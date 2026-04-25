#!/usr/bin/env python3
"""Deterministic entrypoint for the RealESRGAN backend.

`UpscaleEngine` invokes this adapter with the canonical RealESRGAN CLI
arguments. The adapter delegates to the vendored upstream runner under
``vendor/Real-ESRGAN/inference_realesrgan_video.py`` and never depends on
environment variables to locate the runner.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

_VENDOR_ROOT = Path(__file__).resolve().parent / "vendor" / "Real-ESRGAN"
_RUNNER = _VENDOR_ROOT / "inference_realesrgan_video.py"


def main() -> int:
    if not _RUNNER.is_file():
        sys.stderr.write(
            "RealESRGAN runner is missing. Expected vendored runner at " f"{_RUNNER}\n"
        )
        return 2

    original_argv = sys.argv[:]
    original_path = sys.path[:]
    sys.argv = [str(_RUNNER), *original_argv[1:]]
    sys.path.insert(0, str(_VENDOR_ROOT))
    try:
        runpy.run_path(str(_RUNNER), run_name="__main__")
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return 1
    finally:
        sys.argv = original_argv
        sys.path[:] = original_path
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
