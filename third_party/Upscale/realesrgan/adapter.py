#!/usr/bin/env python3
"""Deterministic entrypoint for the RealESRGAN backend.

`UpscaleEngine` invokes this adapter with the canonical RealESRGAN CLI
arguments. The adapter delegates to the vendored upstream runner under
``vendor/inference_realesrgan_video.py`` and never depends on environment
variables to locate the runner.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

_RUNNER = Path(__file__).resolve().parent / "vendor" / "inference_realesrgan_video.py"


def main() -> int:
    if not _RUNNER.is_file():
        sys.stderr.write(
            "RealESRGAN runner is missing. Expected vendored runner at "
            f"{_RUNNER}\n"
        )
        return 2

    original_argv = sys.argv[:]
    sys.argv = [str(_RUNNER), *original_argv[1:]]
    try:
        runpy.run_path(str(_RUNNER), run_name="__main__")
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return 1
    finally:
        sys.argv = original_argv
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
