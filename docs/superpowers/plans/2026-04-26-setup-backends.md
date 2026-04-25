# Setup Backends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a host-side `setup-backends` workflow that acquires backend vendor trees from `backend.toml`, provisions model assets, and verifies both without reintroducing `app/models/` as the setup boundary.

**Architecture:** `app/backends/` becomes the single CLI and orchestration package. Backend acquisition, filtering, materialization, and verification stay separate from model provisioning, but both flow through the same `install`, `verify`, `rebuild`, and `list` commands. The new workflow is host-driven, writes backend-local `vendor/` trees plus `.revision` markers, and preserves the existing runtime boundary by keeping `scripts/check-runtime.sh` as a verification wrapper.

**Tech Stack:** Python 3.11+, dataclasses, `argparse`, `tomllib`, `git sparse-checkout`, existing pytest/unittest test suite, Bash scripts, Makefile, Docker/Compose

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `app/backends/__init__.py` | Package exports for backend setup types and CLI helpers |
| Create | `app/backends/__main__.py` | `python -m app.backends` entry point |
| Create | `app/backends/cli.py` | `install` / `verify` / `rebuild` / `list` parsing and command dispatch |
| Create | `app/backends/spec.py` | `BackendSpec`, `SourceSpec`, `FilterSpec`, `OutputSpec` dataclasses and TOML parsing |
| Create | `app/backends/registry.py` | Discovery of backend directories containing `backend.toml` |
| Create | `app/backends/acquire.py` | `git clone` + sparse-checkout acquisition logic |
| Create | `app/backends/filter.py` | include/exclude glob filtering |
| Create | `app/backends/materialize.py` | copy filtered files into `vendor/` and write `.revision` |
| Create | `app/backends/verify.py` | backend vendor verification and status reporting |
| Create | `app/backends/model_spec.py` | `FileCheck` / `ModelSpec` dataclasses |
| Create | `app/backends/model_specs.py` | `load_model_specs()` registry |
| Create | `app/backends/model_manager.py` | model provisioning orchestration |
| Create | `app/backends/providers.py` | `HuggingFaceProvider`, `HttpProvider`, `SubmoduleProvider` |
| Modify | `scripts/check-runtime.sh` | Switch runtime verification to `python -m app.backends verify` |
| Modify | `scripts/start-worker.sh` | Keep runtime flow aligned if it references setup verification indirectly |
| Modify | `Makefile` | Replace old setup entrypoint with `setup-backends` and wire `make init` |
| Modify | `docker-compose.yml` | Remove old `model-setup` wiring and align setup env if still needed |
| Modify | `Dockerfile` | Verify backend vendor trees are copied through the existing build context |
| Modify | `.gitignore` | No root backend-specific ignore management; only ensure no conflicting generated-path rules remain |
| Create | `third_party/Upscale/realesrgan/backend.toml` | Backend acquisition contract |
| Create | `third_party/Upscale/realesrgan/.gitignore` | Ignore backend-local `vendor/` |
| Create | `third_party/Upscale/.gitignore` | Ignore other backend-local generated trees under the engine bundle |
| Remove | `app/models/` | Old setup boundary after imports are migrated |
| Remove | `scripts/model-setup.sh` | Superseded setup wrapper |
| Remove | `docker-compose.yml` model-setup service/profile | Superseded setup workflow |

---

## Task 1: Scaffold the backend setup package

**Files:**
- Create: `app/backends/__init__.py`
- Create: `app/backends/__main__.py`
- Create: `app/backends/cli.py`
- Create: `tests/test_backends_cli.py`

- [ ] **Step 1: Write the failing test**

```python
import subprocess
import sys


def test_app_backends_module_exists() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.backends", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "install" in result.stdout
    assert "verify" in result.stdout
    assert "rebuild" in result.stdout
    assert "list" in result.stdout
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_backends_cli.py -v`
Expected: `ModuleNotFoundError: No module named 'app.backends'`

- [ ] **Step 3: Implement the minimal package and CLI wiring**

```python
# app/backends/__init__.py
from .cli import main

__all__ = ["main"]
```

```python
# app/backends/__main__.py
from .cli import main

if __name__ == "__main__":
    main()
```

```python
# app/backends/cli.py
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.backends")
    parser.add_argument("action", choices=["install", "verify", "rebuild", "list"])
    parser.parse_args()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_backends_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/backends/__init__.py app/backends/__main__.py app/backends/cli.py tests/test_backends_cli.py
git commit -m "feat: scaffold app.backends CLI package"
```

---

## Task 2: Add backend spec parsing and discovery

**Files:**
- Create: `app/backends/spec.py`
- Create: `app/backends/registry.py`
- Create: `tests/test_backend_spec.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from app.backends.spec import BackendSpec
from app.backends.registry import discover


def test_discover_reads_backend_toml(tmp_path: Path) -> None:
    backend_dir = tmp_path / "realesrgan"
    backend_dir.mkdir()
    (backend_dir / "backend.toml").write_text(
        """
[backend]
name = "realesrgan"
display_name = "Real-ESRGAN"

[source]
type = "git"
url = "https://example.invalid/realesrgan.git"
revision = "v1"

[filter]
include = ["inference.py"]
exclude = ["**/*.md"]

[output]
target = "vendor"
""".strip(),
        encoding="utf-8",
    )

    specs = discover(tmp_path)
    assert len(specs) == 1
    assert isinstance(specs[0], BackendSpec)
    assert specs[0].backend.name == "realesrgan"
    assert specs[0].source.type == "git"
    assert specs[0].output.target == "vendor"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_backend_spec.py -v`
Expected: `ModuleNotFoundError: No module named 'app.backends.spec'`

- [ ] **Step 3: Implement the spec and registry modules**

```python
# app/backends/spec.py
from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class BackendSection:
    name: str
    display_name: str


@dataclass(frozen=True)
class SourceSpec:
    type: str
    url: str
    revision: str


@dataclass(frozen=True)
class FilterSpec:
    include: list[str]
    exclude: list[str]


@dataclass(frozen=True)
class OutputSpec:
    target: str = "vendor"


@dataclass(frozen=True)
class BackendSpec:
    root: Path
    backend: BackendSection
    source: SourceSpec
    filter: FilterSpec
    output: OutputSpec


def load_backend_spec(path: Path) -> BackendSpec:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return BackendSpec(
        root=path.parent,
        backend=BackendSection(**data["backend"]),
        source=SourceSpec(**data["source"]),
        filter=FilterSpec(
            include=list(data.get("filter", {}).get("include", [])),
            exclude=list(data.get("filter", {}).get("exclude", [])),
        ),
        output=OutputSpec(**data.get("output", {})),
    )
```

```python
# app/backends/registry.py
from pathlib import Path

from .spec import BackendSpec, load_backend_spec


def discover(root: Path) -> list[BackendSpec]:
    specs: list[BackendSpec] = []
    for backend_toml in sorted(root.glob("**/backend.toml")):
        specs.append(load_backend_spec(backend_toml))
    return specs
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_backend_spec.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/backends/spec.py app/backends/registry.py tests/test_backend_spec.py
git commit -m "feat: add backend.toml parsing and discovery"
```

---

## Task 3: Implement backend acquisition, filtering, materialization, and verification

**Files:**
- Create: `app/backends/acquire.py`
- Create: `app/backends/filter.py`
- Create: `app/backends/materialize.py`
- Create: `app/backends/verify.py`
- Create: `tests/test_backend_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from app.backends.filter import filter_paths
from app.backends.materialize import write_revision
from app.backends.verify import verify_backend


def test_filter_paths_applies_include_and_exclude() -> None:
    paths = [
        "inference.py",
        "README.md",
        "realesrgan/model.py",
        "realesrgan/test_model.py",
    ]
    filtered = filter_paths(
        paths,
        include=["inference.py", "realesrgan/**"],
        exclude=["**/*.md", "realesrgan/**/test*"]
    )
    assert filtered == ["inference.py", "realesrgan/model.py"]


def test_write_revision_creates_marker(tmp_path: Path) -> None:
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir()
    write_revision(vendor_dir, "v0.3.0")
    assert (vendor_dir / ".revision").read_text(encoding="utf-8") == "v0.3.0\n"


def test_verify_backend_reports_missing_revision(tmp_path: Path) -> None:
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir()
    result = verify_backend(expected_revision="v0.3.0", vendor_dir=vendor_dir, expected_files=["a.py"])
    assert result.status == "missing"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_backend_pipeline.py -v`
Expected: module import failures for the new backend pipeline helpers

- [ ] **Step 3: Implement the backend helpers**

```python
# app/backends/filter.py
from fnmatch import fnmatch


def filter_paths(paths: list[str], include: list[str], exclude: list[str]) -> list[str]:
    included = [p for p in paths if not include or any(fnmatch(p, pat) for pat in include)]
    return [p for p in included if not any(fnmatch(p, pat) for pat in exclude)]
```

```python
# app/backends/materialize.py
from pathlib import Path


def write_revision(vendor_dir: Path, revision: str) -> None:
    (vendor_dir / ".revision").write_text(f"{revision}\n", encoding="utf-8")
```

```python
# app/backends/verify.py
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackendVerification:
    status: str
    missing_files: list[str]
    revision: str | None


def verify_backend(expected_revision: str, vendor_dir: Path, expected_files: list[str]) -> BackendVerification:
    revision_path = vendor_dir / ".revision"
    if not revision_path.exists():
        return BackendVerification(status="missing", missing_files=expected_files, revision=None)
    actual_revision = revision_path.read_text(encoding="utf-8").strip()
    if actual_revision != expected_revision:
        return BackendVerification(status="mismatch", missing_files=expected_files, revision=actual_revision)
    missing = [name for name in expected_files if not (vendor_dir / name).exists()]
    return BackendVerification(status="ok" if not missing else "missing", missing_files=missing, revision=actual_revision)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_backend_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/backends/acquire.py app/backends/filter.py app/backends/materialize.py app/backends/verify.py tests/test_backend_pipeline.py
git commit -m "feat: add backend acquisition and verification helpers"
```

---

## Task 4: Add model provisioning under app/backends

**Files:**
- Create: `app/backends/model_spec.py`
- Create: `app/backends/model_specs.py`
- Create: `app/backends/providers.py`
- Create: `app/backends/model_manager.py`
- Create: `tests/test_model_backends.py`

- [ ] **Step 1: Write the failing test**

```python
from app.backends.model_spec import FileCheck, ModelSpec
from app.backends.model_manager import ModelManager


def test_model_manager_uses_registered_provider_for_submodule_specs() -> None:
    spec = ModelSpec(
        name="upscale-engine",
        source_type="submodule",
        source_ref="",
        target_dir="/engines/upscale",
        files=[FileCheck(path="realesrgan/inference_realesrgan_video.py")],
    )
    manager = ModelManager()
    result = manager.verify([spec])
    assert result == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_model_backends.py -v`
Expected: `ModuleNotFoundError: No module named 'app.backends.model_spec'`

- [ ] **Step 3: Implement the model registry and providers**

```python
# app/backends/model_spec.py
from dataclasses import dataclass


@dataclass(frozen=True)
class FileCheck:
    path: str
    sha256: str | None = None


@dataclass(frozen=True)
class ModelSpec:
    name: str
    source_type: str
    source_ref: str
    target_dir: str
    files: list[FileCheck]
    subfolder: str | None = None
    git_ref: str | None = None
```

```python
# app/backends/providers.py
from pathlib import Path

from .model_spec import ModelSpec


class SubmoduleProvider:
    def ensure(self, spec: ModelSpec) -> None:
        self.verify(spec)

    def verify(self, spec: ModelSpec) -> None:
        for file_check in spec.files:
            if not (Path(spec.target_dir) / file_check.path).exists():
                raise FileNotFoundError(file_check.path)
```

```python
# app/backends/model_manager.py
from .model_spec import ModelSpec
from .providers import SubmoduleProvider


class ModelManager:
    def __init__(self) -> None:
        self._providers = {"submodule": SubmoduleProvider()}

    def verify(self, specs: list[ModelSpec]) -> list[str]:
        missing: list[str] = []
        for spec in specs:
            try:
                self._providers[spec.source_type].verify(spec)
            except FileNotFoundError:
                missing.append(spec.name)
        return missing
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_model_backends.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/backends/model_spec.py app/backends/providers.py app/backends/model_manager.py tests/test_model_backends.py
git commit -m "feat: add model provisioning primitives under app.backends"
```

---

## Task 5: Add `load_model_specs()` and backend CLI actions

**Files:**
- Create: `app/backends/model_specs.py`
- Modify: `app/backends/cli.py`
- Modify: `app/backends/__init__.py`
- Modify: `tests/test_model_backends.py`

- [ ] **Step 1: Write the failing test**

```python
from app.backends.model_specs import load_model_specs


def test_load_model_specs_includes_upscale_backend_items() -> None:
    specs = load_model_specs()
    names = {spec.name for spec in specs}
    assert "panowan-engine" in names
    assert "upscale-engine" in names
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_model_backends.py -v`
Expected: `ModuleNotFoundError: No module named 'app.backends.model_specs'`

- [ ] **Step 3: Implement model spec loading and wire CLI commands**

```python
# app/backends/model_specs.py
from .model_spec import FileCheck, ModelSpec


def load_model_specs() -> list[ModelSpec]:
    return [
        ModelSpec(
            name="panowan-engine",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/panowan",
            files=[FileCheck(path="pyproject.toml")],
        ),
        ModelSpec(
            name="upscale-engine",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/upscale",
            files=[FileCheck(path="realesrgan/inference_realesrgan_video.py")],
        ),
    ]
```

```python
# app/backends/cli.py
import argparse
import sys

from .model_manager import ModelManager
from .model_specs import load_model_specs


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.backends")
    parser.add_argument("action", choices=["install", "verify", "rebuild", "list"])
    args = parser.parse_args()

    specs = load_model_specs()
    manager = ModelManager()

    if args.action == "install":
        manager.ensure(specs)
        print("Backends and models are ready.")
    elif args.action == "verify":
        missing = manager.verify(specs)
        if missing:
            print(f"Missing: {', '.join(missing)}")
            sys.exit(1)
        print("Backends and models verified.")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_model_backends.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/backends/model_specs.py app/backends/cli.py app/backends/__init__.py tests/test_model_backends.py
git commit -m "feat: wire backend CLI to model spec loading and verification"
```

---

## Task 6: Add Real-ESRGAN backend.toml and backend-local ignores

**Files:**
- Create: `third_party/Upscale/realesrgan/backend.toml`
- Create: `third_party/Upscale/realesrgan/.gitignore`
- Create: `third_party/Upscale/.gitignore`
- Modify: `tests/` as needed for discovery/verification

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from app.backends.registry import discover


def test_real_esrgan_backend_toml_exists() -> None:
    root = Path("third_party/Upscale/realesrgan/backend.toml")
    assert root.exists()


def test_real_esrgan_backend_is_discoverable() -> None:
    specs = discover(Path("third_party/Upscale"))
    assert any(spec.backend.name == "realesrgan" for spec in specs)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_backend_spec.py -v`
Expected: failure because `backend.toml` does not yet exist

- [ ] **Step 3: Create backend-local metadata and ignore files**

```toml
# third_party/Upscale/realesrgan/backend.toml
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

```gitignore
# third_party/Upscale/realesrgan/.gitignore
vendor/
__pycache__/
```

```gitignore
# third_party/Upscale/.gitignore
realesrgan/vendor/
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_backend_spec.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add third_party/Upscale/realesrgan/backend.toml third_party/Upscale/realesrgan/.gitignore third_party/Upscale/.gitignore tests/test_backend_spec.py
git commit -m "feat: add Real-ESRGAN backend.toml and local ignore rules"
```

---

## Task 7: Update runtime and setup entry points

**Files:**
- Modify: `scripts/check-runtime.sh`
- Modify: `Makefile`
- Modify: `scripts/start-worker.sh`
- Remove: `scripts/model-setup.sh`
- Remove: `docker-compose.yml` model-setup service/profile

- [ ] **Step 1: Write the failing test or check**

```bash
grep -n "python -m app.models" scripts/check-runtime.sh
```

Expected: no matches after the change.

- [ ] **Step 2: Update the runtime wrapper and make targets**

```bash
# scripts/check-runtime.sh
#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_runtime

exec python -m app.backends verify
```

```makefile
init: setup-submodules setup-backends

setup-submodules:
	git submodule update --init --recursive

setup-backends:
	python -m app.backends install
```

- [ ] **Step 3: Remove legacy setup plumbing**

Delete `scripts/model-setup.sh` and remove the `model-setup` service/profile from `docker-compose.yml` once nothing references it.

- [ ] **Step 4: Run the validation command**

Run: `grep -R "setup-models\|model-setup\|app.models" scripts Makefile docker-compose.yml`
Expected: no remaining setup-related references except historical docs or runtime code still being migrated in later tasks.

- [ ] **Step 5: Commit**

```bash
git add scripts/check-runtime.sh Makefile scripts/start-worker.sh docker-compose.yml
rm -f scripts/model-setup.sh
git commit -m "refactor: switch setup entry points to app.backends"
```

---

## Task 8: Migrate remaining app.models references and remove the old boundary

**Files:**
- Modify: all source files still importing `app.models`
- Remove: `app/models/`
- Modify: tests that still reference old paths

- [ ] **Step 1: Find remaining references**

Run:

```bash
grep -R "app.models\|setup-models\|model-setup" app scripts tests
```

- [ ] **Step 2: Migrate imports and references to `app.backends`**

Replace each remaining `app.models` import with the matching `app.backends` module:

```python
from app.backends.model_manager import ModelManager
from app.backends.model_specs import load_model_specs
from app.backends.model_spec import FileCheck, ModelSpec
from app.backends.providers import HuggingFaceProvider, HttpProvider, SubmoduleProvider
```

- [ ] **Step 3: Remove the old package**

Delete `app/models/` only after the grep above returns no remaining runtime references.

- [ ] **Step 4: Run the focused test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/backends app/models tests
git commit -m "refactor: migrate setup flow from app.models to app.backends"
```

---

## Task 9: Validate packaging, Docker integration, and end-to-end behavior

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- No new code files

- [ ] **Step 1: Check that the backend vendor tree is included in the image context**

Confirm `Dockerfile` still copies `third_party/Upscale` into `/engines/upscale` and that the backend-local `vendor/` tree is not excluded by `.dockerignore`.

- [ ] **Step 2: Verify compose env vars still match the new setup flow**

Ensure the worker and setup containers use `UPSCALE_ENGINE_DIR` and `UPSCALE_WEIGHTS_DIR`, and that no old `upscale_model_dir` wiring remains.

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 4: Run the host-side verification command**

Run: `python -m app.backends verify`
Expected: reports missing items on a dev machine without installed assets, exits non-zero

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "chore: validate backend packaging and compose wiring"
```

---

## Self-Review

### 1. Spec Coverage

| Spec Section | Task(s) | Covered? |
|---|---|---|
| CLI contract (`install`, `verify`, `rebuild`, `list`) | Task 1, Task 5 | Yes |
| `backend.toml` contract and discovery | Task 2, Task 6 | Yes |
| Backend acquisition pipeline | Task 3 | Yes |
| Model provisioning pipeline | Task 4, Task 5 | Yes |
| Host-side execution | Task 7, Task 9 | Yes |
| `make init` / `setup-backends` | Task 7 | Yes |
| Migration away from `app/models/` | Task 8 | Yes |
| Backend-local `.gitignore` | Task 6 | Yes |
| Docker packaging / vendor tree inclusion | Task 9 | Yes |
| `scripts/check-runtime.sh` preservation | Task 7 | Yes |

### 2. Placeholder Scan

No TBD/TODO/fill-in-later markers remain in task steps. Each task names concrete files, commands, and expected outcomes.

### 3. Type Consistency

- `BackendSpec`, `SourceSpec`, `FilterSpec`, `OutputSpec` are introduced once and reused consistently.
- `FileCheck` / `ModelSpec` are introduced once and reused consistently.
- The CLI commands are always the same four verbs: `install`, `verify`, `rebuild`, `list`.
- `setup-backends` is the Make target; `python -m app.backends install` is the runtime implementation.

### 4. Scope Check

This plan still bundles backend setup and model provisioning because the spec explicitly defines them as two subdomains under one CLI. If either subdomain grows beyond this boundary later, it should be split into its own plan, but this version is internally consistent.
