# Upscale Engine Bundle

`third_party/Upscale` is the repository-managed engine bundle for `UpscaleEngine`.
Each backend owns a stable subdirectory under this bundle:

- `realesrgan/` — RealESRGAN adapter and vendored runner files
- `realbasicvsr/` — reserved for RealBasicVSR adapter/config/vendor files
- `seedvr2/` — reserved for SeedVR2 adapter/vendor files

At runtime the bundle is copied to `/engines/upscale`, while backend weights live under `/models/upscale/<backend>`.

Unlike `third_party/PanoWan`, this bundle is maintained inside the repository so the engine-level layout stays aligned with `UpscaleEngine` rather than any single upstream project name.

## Backend availability contract

A backend is **registered** in `app.upscaler.UPSCALE_BACKENDS` purely by its Python class. A backend is **available** at runtime only when every file it declares in `UpscaleBackendAssets` exists under `/engines/upscale` (engine files) and `/models/upscale` (weight files), every required external command (e.g. `torchrun`) is on `PATH`, and any declared backend runtime Python can import its required modules.

`app.api` rejects upscale jobs for registered-but-unavailable models, and `UpscaleEngine.validate_runtime()` refuses to start the worker when no backend is available.

## RealESRGAN

`realesrgan/adapter.py` is the stable entrypoint invoked by `app.upscaler.RealESRGANBackend`. It deterministically delegates to `realesrgan/vendor/Real-ESRGAN/inference_realesrgan_video.py`, prepends the vendored snapshot root to `sys.path`, and runs with the exact CLI arguments forwarded by the engine — no environment variables, no fallbacks.

A RealESRGAN backend is available only when the adapter, vendored snapshot files, backend-local runtime Python, and `realesrgan/realesr-animevideov3.pth` all exist, and `/opt/venvs/upscale-realesrgan/bin/python` can import `cv2`, `ffmpeg`, and `tqdm`. `make setup-models` provisions the weight via the `upscale-realesrgan-weights` ModelSpec (direct download from the official Real-ESRGAN GitHub release, sha256-verified).

The vendored runtime intentionally keeps only the inference surface the worker actually uses:

- `inference_realesrgan_video.py`
- `realesrgan/__init__.py`
- `realesrgan/utils.py`
- `realesrgan/archs/__init__.py`
- `realesrgan/archs/srvgg_arch.py`

The vendored `__init__.py` files are slimmed down so importing `realesrgan` does not pull training/data/version modules.

## Backend runtime dependencies

Each upscale backend may declare backend-local Python dependencies in its own `requirements.txt`.
Dependencies are installed during Docker build into backend-specific virtual environments under `/opt/venvs/<backend>`, not into the running container at job time.

RealESRGAN uses `/opt/venvs/upscale-realesrgan/bin/python` and requires:

- `ffmpeg` system command
- `cv2` Python module
- `ffmpeg` Python module from `ffmpeg-python`
- `tqdm` Python module
- vendored `realesrgan` package files from `realesrgan/vendor/Real-ESRGAN`

The RealESRGAN adapter prepends `realesrgan/vendor/Real-ESRGAN` to `sys.path` before running the upstream video inference script. The vendored runtime requires an explicit `--model_path` and supports only `realesr-animevideov3`; missing dependencies should be fixed in Docker build dependencies rather than by runtime installs.
