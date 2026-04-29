import os

import uvicorn

from app.api import app
from app.settings import settings


def main() -> None:
    dev_mode = os.getenv("DEV_MODE", "0") == "1"
    uvicorn.run(
        "app.api:app" if dev_mode else app,
        host=settings.host,
        port=settings.port,
        reload=dev_mode,
    )


if __name__ == "__main__":
    main()
