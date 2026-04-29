"""Deterministic entrypoint for generated RealESRGAN runtime bundle.

Invoked as `python /engines/upscale/realesrgan/vendor/__main__.py ...`.

The generated runtime bundle lives flat under this directory:
    realesrgan/vendor/
    ├── __main__.py                   ← this file
    ├── inference_realesrgan_video.py ← trimmed video runner
    └── realesrgan/                   ← trimmed runtime package

This entrypoint prepends generated runtime root to ``sys.path`` so trimmed
``realesrgan`` package resolves before any system-installed copy, then calls
``inference_realesrgan_video.main()`` with forwarded CLI args. No environment
variables or fallback discovery is involved.
"""

from __future__ import annotations

import sys
from pathlib import Path

_RUNTIME_ROOT = Path(__file__).resolve().parent


def main() -> int:
    if str(_RUNTIME_ROOT) not in sys.path:
        sys.path.insert(0, str(_RUNTIME_ROOT))

    # Import after sys.path is set so the vendored ``realesrgan`` package wins.
    import inference_realesrgan_video  # noqa: E402  (import after sys.path setup)

    try:
        inference_realesrgan_video.main()
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
