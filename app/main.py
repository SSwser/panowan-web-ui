import os
import sys

import uvicorn

from .api import app
from .settings import settings


def main() -> None:
    dev_mode = os.getenv("DEV_MODE", "0") == "1"
    vmtouch = os.getenv("VMTOUCH_MODELS", "0") == "1"

    print("=== PanoWan Local Service Starting ===", flush=True)
    print(f"  Python   : {sys.version.split()[0]}", flush=True)
    print(f"  Listen   : {settings.host}:{settings.port}", flush=True)
    print(f"  Timeout  : {settings.generation_timeout_seconds}s", flush=True)
    print(
        f"  DEV_MODE : {'on  (uvicorn --reload, uv sync on start)' if dev_mode else 'off'}",
        flush=True,
    )
    print(
        f"  VMTOUCH  : {'on  (model weights pre-loaded into pagecache)' if vmtouch else 'off'}",
        flush=True,
    )

    if dev_mode:
        uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
    else:
        uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
