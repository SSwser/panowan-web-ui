# Setup Backends Design

Date: 2026-04-26
Status: Draft

## Problem

Backend vendor trees are manually maintained with no declarative acquisition contract, no incremental sync, and no automated verification. Model provisioning lives in `app/models/` as a separate concern from backend code acquisition, forcing developers to touch multiple files and follow different workflows when adding or updating a backend.

## Decision

Replace `app/models/` with `app/backends/`, a unified setup tool that exposes a single CLI while keeping backend acquisition and model provisioning as separate internal subflows. Backend acquisition is driven by `backend.toml` declarations in each backend directory.

## backend.toml Format

Each backend directory contains a `backend.toml` that declares its upstream source and filtering rules. This file is the acquisition and filtering contract per ADR 0005.

```toml
[backend]
name = "realesrgan"
display_name = "Real-ESRGAN"

[source]
type = "git"
url = "https://github.com/xinntao/Real-ESRGAN.git"
revision = "v0.3.0"

[filter]
include = [
    "inference/inference_realesrgan_video.py",
    "realesrgan/**",
]
exclude = [
    "realesrgan/**/test*",
    "**/*.md",
]

[output]
target = "vendor"
```

Fields:

- `source.type` — only `"git"` supported initially; extensible to `"archive"` etc.
- `source.revision` — tag, branch, or commit hash
- `filter.include` — glob whitelist relative to repo root; empty = include all
- `filter.exclude` — glob blacklist applied after include
- `output.target` — vendor generation target directory name, defaults to `"vendor"`

## Backend Directory Layout

```
third_party/Upscale/realesrgan/
  backend.toml          # acquisition + filtering contract
  .gitignore            # ignores vendor/ and __pycache__/
  vendor/               # generated, untracked
    .revision           # records current materialized revision
    __main__.py
    inference_realesrgan_video.py
    realesrgan/
      ...
  requirements.txt      # backend Python dependencies
```

Each backend owns its own `.gitignore` that ignores its `vendor/` directory. The project root `.gitignore` does not manage backend-level generated boundaries.

## Python Module Structure

```
app/backends/
  __init__.py           # re-exports BackendSpec, BackendManager, ModelSpec
  __main__.py           # CLI: python -m app.backends install|verify|rebuild|list
  cli.py                # argparse subcommand definitions
  registry.py           # discover(): scans BACKEND_ROOT for backend.toml files
  spec.py               # BackendSpec, SourceSpec, FilterSpec, OutputSpec
  acquire.py            # git sparse-checkout clone
  filter.py             # include/exclude glob matching
  materialize.py        # writes vendor/ + .revision
  verify.py             # revision + file-set consistency checks
  model_spec.py         # FileCheck, ModelSpec (migrated from app/models/registry.py)
  model_specs.py        # load_model_specs() (migrated from app/models/specs.py)
  model_manager.py      # ModelManager (migrated from app/models/manager.py)
  providers.py          # HuggingFaceProvider, HttpProvider, SubmoduleProvider
```

Module responsibilities:

Backend acquisition and model provisioning are separate subdomains under the same CLI. The first group owns backend vendor materialization; the second group owns model artifact provisioning.

| Module | Input | Output | Responsibility |
|--------|-------|--------|----------------|
| `registry` | BACKEND_ROOT path | `list[BackendSpec]` | discover all directories with backend.toml |
| `spec` | backend.toml file | `BackendSpec` | TOML parsing + validation |
| `acquire` | `SourceSpec` + temp dir | cloned repo in temp dir | git clone + sparse-checkout |
| `filter` | file list + `FilterSpec` | filtered file list | glob matching |
| `materialize` | filtered files + `OutputSpec` | vendor/ dir + .revision | copy files + write revision marker |
| `verify` | `BackendSpec` + vendor/ path | verification result | revision match + file existence |
| `model_spec` | — | `FileCheck`, `ModelSpec` | data classes |
| `model_specs` | `Settings` | `list[ModelSpec]` | declarative model spec registry |
| `model_manager` | `ModelSpec` list | downloaded model files | dispatch to providers |
| `providers` | `ModelSpec` | download/verify | HuggingFace, HTTP, Submodule |

## CLI Commands

```
python -m app.backends install     # fetch missing/stale backends + download models
python -m app.backends verify      # read-only consistency check
python -m app.backends rebuild     # force rebuild all vendor/ directories
python -m app.backends list        # show backend + model status
```

### install

Idempotent initialization and incremental sync. Executed on the host machine.

Pipeline per backend:

1. **discover** — `registry.discover()` returns all `BackendSpec` instances
2. **check** — read `vendor/.revision`, compare with `backend.toml` declared revision
   - not found or mismatch → needs install
   - match → skip
3. **acquire** — git sparse-checkout into temp directory:
   ```
   git clone --no-checkout --depth 1 --branch <revision> <url> <tmpdir>
   cd <tmpdir>
   git sparse-checkout init --cone
   git sparse-checkout set <top-level dirs from include>
   git checkout
   ```
4. **filter** — apply `filter.include` and `filter.exclude` globs to the cloned file list
5. **materialize** — remove old `vendor/`, copy filtered files, write `.revision`

Then run the model subflow separately:

1. **check** — verify file existence + SHA-256 if declared
2. **install** — dispatch to the appropriate provider (HuggingFace / HTTP / Submodule)

Single backend failure does not block others. Errors are caught and reported; processing continues.

### verify

Read-only. Checks:

- Backend: `vendor/.revision` matches declared revision + expected files exist
- Model: files exist + SHA-256 matches if declared

Output statuses use a single lowercase enum: `ok` / `mismatch` / `missing`.

### rebuild

Forces a full backend rebuild by deleting all backend `vendor/` directories, then re-running acquire → filter → materialize for every backend. This ignores existing `.revision` values but still follows each `backend.toml`. It does not rebuild model weights (too large; use `install` for that).

### list

Prints each backend's name, current revision, target revision, and status (`ok` / `mismatch` / `missing`). Prints each model's name and status using the same lowercase enum.

## Incremental Sync

`vendor/.revision` is a plain-text file containing the materialized revision string (e.g., `v0.3.0`). When a new backend directory is added with its own `backend.toml`, running `install` again will:

1. Discover the new backend
2. Find no `vendor/.revision`
3. Acquire, filter, and materialize only the new backend
4. Skip existing backends whose `.revision` matches

When an upstream revision changes in `backend.toml`, running `install` will rebuild only the affected backend.

## Host Execution

All commands run on the host machine, not inside Docker. This is required because:

- `vendor/` must exist before `docker build` (Dockerfile `COPY third_party/Upscale /engines/upscale`)
- Model downloads only need `huggingface_hub` (optional dependency), no GPU or torch
- `git sparse-checkout` requires git on the host

Python dependency for model downloads:

```toml
[project.optional-dependencies]
setup = ["huggingface_hub"]
```

## Makefile Integration

```makefile
init: setup-submodules setup-backends

setup-submodules:
	git submodule update --init --recursive

setup-backends:
	python -m app.backends install
```

No shell script wrappers. No Docker compose profiles for setup. `make init` is the single entry point.

## Migration from app/models/

### Delete

- `app/models/` — remove once no remaining runtime import depends on it
- `scripts/model-setup.sh` — replace with `make init`
- `docker-compose.yml` — remove the `model-setup` service and profile once nothing else references them
- `Makefile` — remove the `setup-models` target

### Preserve and update

- `scripts/check-runtime.sh` — kept; internal call changed to `python -m app.backends verify`
- `scripts/start-worker.sh` — no change (calls `check-runtime.sh`, not `app.models` directly)
- `Dockerfile` — expected to remain unchanged unless the backend vendor layout forces a minimal COPY adjustment later on

Deletion assumes these paths only serve the old setup flow and are not required by any remaining runtime path.

### Import path changes

All references to `app.models` are updated to `app.backends`:

- `app/models/registry.py` → `app/backends/model_spec.py`
- `app/models/specs.py` → `app/backends/model_specs.py`
- `app/models/manager.py` → `app/backends/model_manager.py`
- `app/models/providers.py` → `app/backends/providers.py`

No backward-compatibility shims. No re-exports from `app.models`.

## Docker Integration

No Dockerfile changes required. The existing `COPY third_party/Upscale /engines/upscale` naturally includes `vendor/` after `setup-backends install` populates it on the host. The `.dockerignore` does not exclude `vendor/`.

Model weights are downloaded to `data/models/` on the host and mounted into containers via Docker volumes, unchanged.

## Error Handling

- Single backend failure does not block others
- Acquire failure (network/git error) → report and skip that backend
- Filter/materialize failure (IO error) → report and skip
- All failures are summarized at the end with non-zero exit code if any backend or model failed

## .revision File

Located at `vendor/.revision`. Contains a single line: the revision string from `backend.toml`.

Deleted when `vendor/` is deleted. Recreated when `materialize` runs. Not tracked by git.

## Related Documents

- [ADR 0003: Backend Runtime Contracts](../../adr/0003-backend-runtime-contract.md)
- [ADR 0005: Backend Acquisition and Setup](../../adr/0005-backend-acquisition-and-setup.md)
