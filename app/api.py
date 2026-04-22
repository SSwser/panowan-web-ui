import os
import traceback

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse

from .generator import generate_video, log_startup_diagnostics
from .settings import settings


app = FastAPI(
    title=settings.service_title,
    description="Run PanoWan video generation inside a local Docker container.",
    version=settings.service_version,
)


def _path_has_content(path: str) -> bool:
    if os.path.isdir(path):
        return any(os.scandir(path))
    return os.path.exists(path)


@app.on_event("startup")
def on_startup() -> None:
    log_startup_diagnostics()


@app.get("/")
def root() -> dict:
    return {
        "service": "panowan-local",
        "status": "ok",
        "generate_endpoint": "/generate",
    }


@app.get("/health")
def healthcheck() -> dict:
    panowan_dir_exists = os.path.exists(settings.panowan_dir)
    wan_model_ready = _path_has_content(settings.wan_model_absolute_path)
    lora_exists = os.path.exists(settings.lora_absolute_path)
    model_ready = wan_model_ready and lora_exists

    return {
        "status": "ready" if model_ready else "starting",
        "service_started": True,
        "model_ready": model_ready,
        "panowan_dir_exists": panowan_dir_exists,
        "wan_model_exists": wan_model_ready,
        "lora_exists": lora_exists,
    }


@app.post("/generate")
def generate(payload: dict, background_tasks: BackgroundTasks) -> FileResponse:
    try:
        result = generate_video(payload)
        output_path = result["output_path"]
        background_tasks.add_task(os.remove, output_path)
        return FileResponse(
            output_path,
            media_type="video/mp4",
            filename=f"{result['id']}.mp4",
            background=background_tasks,
            headers={"X-Job-Id": result["id"]},
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        print(f"ERROR: {exc}", flush=True)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
