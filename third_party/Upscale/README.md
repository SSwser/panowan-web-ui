# Upscale Engine Bundle

`third_party/Upscale` is the repository-managed engine bundle for `UpscaleEngine`.
Each backend owns a stable subdirectory under this bundle:

- `realesrgan/` — RealESRGAN backend root with repo-owned runtime sources and generated runtime bundle
- `realbasicvsr/` — reserved for RealBasicVSR vendor files
- `seedvr2/` — reserved for SeedVR2 vendor files

At runtime the bundle is copied to `/engines/upscale`. Backend weights live under `/models/<MODEL_FAMILY>/` (the `MODEL_ROOT`-rooted layout shared with all other models per ADR 0003), e.g. `/models/Real-ESRGAN/realesr-animevideov3.pth`.

Unlike `third_party/PanoWan`, this bundle is maintained inside the repository so the engine-level layout stays aligned with `UpscaleEngine` rather than any single upstream project name.

## Backend availability contract

A backend is **registered** in `app.upscaler.UPSCALE_BACKENDS` purely by its Python class. A backend is **available** at runtime only when every file it declares in `UpscaleBackendAssets` exists under `/engines/upscale` (engine files) and `UPSCALE_WEIGHTS_DIR` (weight files; equals `MODEL_ROOT` per ADR 0003), every required external command (e.g. `ffmpeg`) is on `PATH`, and any declared backend runtime Python can import its required modules.

`app.api` rejects upscale jobs for registered-but-unavailable models, and `UpscaleEngine.validate_runtime()` refuses to start the worker when no backend is available.

## RealESRGAN

`realesrgan/runner.py` is the stable backend-root entrypoint invoked by `app.upscaler.RealESRGANBackend`. It delegates into generated `vendor/__main__.py`, while repo-owned runtime source of truth lives under `realesrgan/sources/`.

A RealESRGAN backend is available only when the backend-root runner, generated runtime bundle files, backend-local runtime Python, and `/models/Real-ESRGAN/realesr-animevideov3.pth` all exist, and `/opt/venvs/upscale-realesrgan/bin/python` can import `cv2`, `ffmpeg`, and `tqdm`. `make setup-models` provisions the weight via the `upscale-realesrgan-weights` ModelSpec (direct download from the official Real-ESRGAN GitHub release, sha256-verified).

The repo-owned runtime sources intentionally keep only the inference surface the worker actually uses under `realesrgan/sources/`:

- `__main__.py`
- `inference_realesrgan_video.py`
- `realesrgan/__init__.py`
- `realesrgan/utils.py`
- `realesrgan/srvgg_arch.py`

`vendor/` is disposable generated output rebuilt from those sources, not committed source of truth. The slimmed-down `__init__.py` files ensure importing `realesrgan` does not pull training/data/version modules.

## Backend runtime dependencies

Each upscale backend may declare backend-local Python dependencies in its own `requirements.txt`.
Dependencies are installed during Docker build into backend-specific virtual environments under `/opt/venvs/<backend>`, not into the running container at job time.

RealESRGAN uses `/opt/venvs/upscale-realesrgan/bin/python` and requires:

- `ffmpeg` system command
- `cv2` Python module
- `ffmpeg` Python module from `ffmpeg-python`
- `tqdm` Python module
- generated `realesrgan/vendor/` runtime bundle rebuilt from `realesrgan/sources/`

The generated `vendor/__main__.py` inserts its own directory at the front of `sys.path` before importing `inference_realesrgan_video`, and `runner.py` delegates into that generated entrypoint. The trimmed runtime requires an explicit `--model_path` and supports only `realesr-animevideov3`; missing dependencies should be fixed in Docker build dependencies rather than by runtime installs.
