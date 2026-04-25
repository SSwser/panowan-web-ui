#!/usr/bin/env python3
"""Launcher placeholder for the project-owned Upscale engine bundle.

This file preserves the final engine layout:
    third_party/Upscale/realesrgan/inference_realesrgan_video.py

Vendor or replace this launcher with the actual RealESRGAN runner before
executing upscale jobs in production.
"""

from __future__ import annotations

import sys


def main() -> int:
    sys.stderr.write(
        "UpscaleEngine found the project-owned RealESRGAN launcher stub, but the "
        "actual backend runner has not been vendored yet.\n"
        "Provide the RealESRGAN implementation under third_party/Upscale/realesrgan/ "
        "before executing upscale jobs.\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
