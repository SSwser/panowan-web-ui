import sys

import uvicorn

from .api import app
from .settings import settings


def main() -> None:
    print("=== PanoWan Local Service Starting ===", flush=True)
    print(f"Python version: {sys.version}", flush=True)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
