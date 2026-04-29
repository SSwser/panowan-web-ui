# PanoWan Web UI — AI Agent Guide

## Project Overview

FastAPI + worker service for AI video generation (T2V/I2V via PanoWan) and upscaling. Three isolated roles: **api**, **worker**, **model-setup**. See [docs/runtime-architecture.md](docs/runtime-architecture.md) and [ADR 0001](docs/adr/0001-engine-oriented-product-runtime.md).

## Commands

```bash
# Host Python / dependencies (requires Python 3.13 exactly — not 3.12 or 3.14)
uv sync --group dev

# Tests
uv run python -m unittest discover -s tests   # canonical
uv run pytest tests/                          # also works

# Run locally on the host
DEV_MODE=1 uv run python -m app.api_service   # API with hot-reload
uv run python -m app.worker_service           # Worker

# Docker
make build          # checks uv.lock, then compose build
make up             # production
make up DEV=1       # dev (mounts source)
make doctor         # diagnose GPU/Docker/models
make setup-backends # download model weights and verify backends (required before first run)
```

> Host-side Python is managed via `uv`. Prefer `uv run ...` over calling the system `python` directly so commands always use the project's pinned Python 3.13 environment.
>
> Host-side Docker usage should follow the existing wrappers in `Makefile` and `scripts/docker-proxy.sh` instead of ad-hoc `docker compose ...` commands. Those entry points preserve this repo's host/WSL environment propagation and compose interpolation contract.
>
> If you need a direct Docker command, copy the calling pattern from `Makefile` or route it through `scripts/docker-proxy.sh` rather than inventing a new shell wrapper.
>
> After changing `pyproject.toml`, run `uv lock` before `make build` — the build will fail otherwise.
>
> `make` targets that execute host-side Python (`make test`, `make setup-backends`, `make init`) are expected to run through `uv` when available.

### Host Python Rule

- Use `uv sync --group dev` to provision the host environment.
- Use `uv run ...` for host-side Python entry points.
- Do **not** assume the shell's `python` version is correct.
- Container-internal commands may still use plain `python`; the `uv` rule is for host execution.

Why: this repo pins Python `>=3.13,<3.14`, but many developer machines still have 3.12 on `PATH`. Using `uv` avoids subtle runtime differences like missing stdlib APIs or mismatched dependency resolution.

### Makefile Host Runner Convention

The Makefile uses a `PYTHON_RUN` wrapper that resolves to `uv run` when `uv` is installed, and falls back to `python` otherwise. New host-side Python targets should use `$(PYTHON_RUN) -m ...` instead of calling `python` directly.

Examples:

- Good: `$(PYTHON_RUN) -m app.backends install`
- Good: `$(PYTHON_RUN) -m unittest discover -s tests`
- Avoid for host targets: `python -m ...`
- Fine in containers: `python -m ...`

Short version: **host = `uv run`; container = plain `python`**.

### Backend Vendor Maintenance

Backend `vendor/` trees are generated runtime output, not hand-maintained source. If a backend declares `sources/` as authoritative runtime input, make persistent changes under `sources/` and sync `vendor/` through the built-in install flow (`uv run -m app.backends install` or `make setup-backends`) rather than editing generated files in place.

When the current verification path is blocked by directory `stat` limitations, the fastest safe recovery is to delete that backend's `vendor/` directory and rerun the install flow so it is rebuilt from declared inputs. Treat this as a rebuild workaround, not as permission to maintain `vendor/` manually.

Why: the backend runtime contract is file-list based and rebuild-oriented. Manual edits inside `vendor/` drift from `backend.toml` and `sources/`, while delete-and-rebuild keeps runtime state aligned with the declared backend spec.

## Architecture

```
Client → app/api.py (FastAPI)
       → LocalJobBackend  (data/runtime/jobs.json, file-locked, atomic writes)
       ← Worker polls → claim_next_job()
                      → EngineRegistry → engine.run(job) → EngineResult
                      → backend.complete_job() / fail_job()
       → SSE push (app/sse.py)
```

**Job type → engine mapping** (in `app/worker_service.py`):

- `"generate"` → `PanoWanEngine` (t2v, i2v)
- `"upscale"` → `UpscaleEngine` (multi-backend)

## Adding a New Engine

Implement the `EngineAdapter` Protocol from [app/engines/base.py](app/engines/base.py): define `name`, `capabilities`, `validate_runtime()` (raise `FileNotFoundError` if deps missing), and `run(job) -> EngineResult`. The `job` dict includes `_should_cancel: Callable[[], bool]` — poll it in long tasks.

Then register in `app/engines/registry.py` and add a `JOB_TYPE_TO_ENGINE` entry in `app/worker_service.py`.

## Key Conventions

**Settings** (`app/settings.py`): `frozen=True` dataclass read from env vars. Use `dataclasses.replace(settings, ...)` to create modified copies (tests use `patch("app.api.settings", ...)`).

**Concurrency**: `LocalJobBackend` and `LocalWorkerRegistry` use `threading.Lock` + `.lock` sidecar files + `os.replace()` atomic writes. Never write JSON directly.

**Upscale backends** each have an isolated venv: `/opt/venvs/upscale-realesrgan`, `upscale-realbasicvsr`, `upscale-seedvr2` — do **not** import their packages from the main `/opt/venv`.

**Model weights** live under `/models/<MODEL_FAMILY>/` (e.g., `/models/Real-ESRGAN/`), not `/models/upscale/`. `UPSCALE_WEIGHTS_DIR` defaults to `MODEL_ROOT`.

**Worker ID**: defaults to `hostname:pid`, overridable via `WORKER_ID` env var.

## Design System Guidance

This project follows the design system direction in `DESIGN.md`:

- Keep the interface **grayscale and minimal**: color is for links, states, and product screenshots only.
- Use **Cal Sans** for headings and display typography, **Inter** for body copy.
- Prefer **subtle layered shadows** over borders; the system relies on ring-shadow + soft shadow + contact shadow for elevation.
- Keep layouts clean with **generous spacing** and a white canvas; the visual weight should come from structure and content, not decoration.
- Avoid decorative graphics, brand colors, or gradients; the product UI itself is the primary visual focus.

See [DESIGN.md](DESIGN.md) for the full visual and component system guidance.

## Environment Variables

Full list in [ENVIRONMENT.md](ENVIRONMENT.md) and [app/settings.py](app/settings.py).

## Docs & ADRs

See [docs/](docs/) for architecture docs and ADRs.

## Documentation Lifecycle

**ADRs** (`docs/adr/`): Immutable after commit. Never edit an existing ADR — deprecate it and supersede with a new one.

**Plans** (`docs/superpowers/plans/`): Temporary. Delete after the plan is implemented and code review passes — they contain implementation details that become stale and pollute context quickly.

**Specs** (`docs/superpowers/specs/`): Longer-lived than plans, but delete immediately if they conflict with current ADRs or design direction.

## Code Comments

Document the *why*, not the *what*. When implementing behavior driven by a non-obvious constraint, add one or two lines explaining why — safety constraint, compatibility decision, design-doc rule. Don't restate what the code does or cite design-doc sections verbatim.

## File and Module Naming

Never use vague names like `helpers`, `utils`, `common`, or `misc` for files or modules. Name files after the concrete domain concept they contain (e.g., `process_runner.py`, `upscale_contract.py`). If you reach for `helpers`, the file likely has multiple responsibilities and should be split.
