# RealESRGAN Backend Runtime Contract Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the `third_party/Upscale/realesrgan/` backend with ADR 0006 by replacing historical `overlay` contract terms with backend-local runtime input terminology and a backend-root `runner.py` entrypoint.

**Architecture:** Keep the Phase 1 migration narrow and RealESRGAN-specific. First replace the backend spec vocabulary so `backend.toml`, code, and tests talk about repo-owned runtime inputs under `sources/` instead of `overlay`; then update materialization so it merges `sources/` into the generated `vendor/` bundle and keeps verification read-only; finally switch runtime callers and fixtures from `vendor/__main__.py` to backend-root `runner.py` while preserving the existing generated `vendor/` bundle contract.

**Tech Stack:** Python 3.13, `uv`, `unittest`, TOML backend metadata, git sparse checkout for transient upstream acquisition

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Modify | `third_party/Upscale/realesrgan/backend.toml` | Remove historical `[overlay]` and `[legacy_materialized]` sections; declare `sources/` runtime-input participation using Phase 1 contract vocabulary |
| Create | `third_party/Upscale/realesrgan/runner.py` | Stable backend-root runtime entrypoint that survives rebuild and delegates into generated `vendor/` runtime files |
| Rename | `third_party/Upscale/realesrgan/overlay/**` → `third_party/Upscale/realesrgan/sources/**` | Durable repo-owned runtime input files merged into `vendor/` during materialization |
| Modify | `third_party/Upscale/realesrgan/.gitignore` | Keep `vendor/`, `.tmp/`, `build/`, and `__pycache__/` ignored while leaving `sources/` tracked |
| Modify | `app/backends/spec.py` | Replace overlay-oriented datamodel with runtime-input-oriented spec model and TOML loader |
| Modify | `app/backends/materialize.py` | Merge repo-owned `sources/` files into the generated `vendor/` bundle |
| Modify | `app/backends/verify.py` | Keep verify/ensure semantics aligned with `output.expected_files` and new spec model |
| Modify | `app/upscale_contract.py` | Point RealESRGAN engine contract at backend-root `runner.py` while keeping generated bundle files explicit |
| Modify | `app/upscaler.py` | Build RealESRGAN runtime command through backend-root `runner.py` instead of `vendor/__main__.py` |
| Modify | `tests/test_backend_spec.py` | Assert new TOML parsing and runtime-input contract vocabulary |
| Modify | `tests/test_model_providers.py` | Assert rebuild merges `sources/` inputs into `vendor/` and preserve verification semantics |
| Modify | `tests/test_scripts.py` | Assert Git boundary, `runner.py` role, and `sources/` ownership semantics |
| Modify | `tests/test_upscaler.py` | Assert RealESRGAN command path uses backend-root `runner.py` |
| Modify | `docs/guide/backend-runtime-bundle.md` | Keep maintainer guide wording consistent with shipped file names and runtime entrypoint |

---

## Task 1: Backend spec model — replace `overlay` vocabulary with runtime inputs

**Files:**
- Modify: `app/backends/spec.py:6-74`
- Modify: `tests/test_backend_spec.py:7-69`
- Modify: `third_party/Upscale/realesrgan/backend.toml:1-48`

- [ ] **Step 1: Write the failing test**

Update `tests/test_backend_spec.py` so the fixture TOML and RealESRGAN assertions use runtime-input fields instead of `overlay`:

```python
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

[runtime_inputs]
root = "sources"
files = ["runner_patch.py"]
""".strip(),
        encoding="utf-8",
    )

    specs = discover(tmp_path)
    assert len(specs) == 1
    assert isinstance(specs[0], BackendSpec)
    assert specs[0].runtime_inputs.root == "sources"
    assert specs[0].runtime_inputs.files == ["runner_patch.py"]


def test_real_esrgan_backend_is_discoverable() -> None:
    specs = discover(Path("third_party/Upscale"))
    realesrgan = next(spec for spec in specs if spec.backend.name == "realesrgan")
    assert realesrgan.output.target == "vendor"
    assert realesrgan.runtime_inputs.root == "sources"
    assert realesrgan.runtime_inputs.files == [
        "__main__.py",
        "inference_realesrgan_video.py",
        "realesrgan/__init__.py",
        "realesrgan/utils.py",
        "realesrgan/archs/__init__.py",
        "realesrgan/archs/srvgg_arch.py",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run python -m pytest tests/test_backend_spec.py -v`
Expected: FAIL with `AttributeError: 'BackendSpec' object has no attribute 'runtime_inputs'` or TOML parsing error for `[runtime_inputs]`

- [ ] **Step 3: Write minimal implementation**

Replace the overlay dataclass in `app/backends/spec.py` with a runtime-input-oriented dataclass and loader:

```python
@dataclass(frozen=True)
class RuntimeInputsSpec:
    root: str = "sources"
    files: list[str] | None = None


@dataclass(frozen=True)
class BackendSpec:
    root: Path
    backend: BackendSection
    source: SourceSpec
    filter: FilterSpec
    output: OutputSpec
    runtime_inputs: RuntimeInputsSpec = field(default_factory=RuntimeInputsSpec)

    # Backend specs in tests often only care about the acquisition/materialization
    # contract, so runtime-input metadata should stay optional unless a test exercises it.


def load_backend_spec(path: Path) -> BackendSpec:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    output_data = dict(data.get("output", {}))
    strip_prefixes = output_data.get("strip_prefixes")
    if strip_prefixes is not None:
        output_data["strip_prefixes"] = list(strip_prefixes)
    expected_files = output_data.get("expected_files")
    if expected_files is not None:
        output_data["expected_files"] = list(expected_files)
    runtime_inputs_data = dict(data.get("runtime_inputs", {}))
    runtime_input_files = runtime_inputs_data.get("files")
    if runtime_input_files is not None:
        runtime_inputs_data["files"] = list(runtime_input_files)
    return BackendSpec(
        root=path.parent,
        backend=BackendSection(**data["backend"]),
        source=SourceSpec(**data["source"]),
        filter=FilterSpec(
            include=list(data.get("filter", {}).get("include", [])),
            exclude=list(data.get("filter", {}).get("exclude", [])),
        ),
        output=OutputSpec(**output_data),
        runtime_inputs=RuntimeInputsSpec(**runtime_inputs_data),
    )
```

Update `third_party/Upscale/realesrgan/backend.toml` to remove the historical sections and declare runtime input participation explicitly:

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
  "inference/Real-ESRGAN/inference_realesrgan_video.py",
  "realesrgan/Real-ESRGAN/realesrgan/**",
]
exclude = ["realesrgan/**/test*", "**/*.md"]

[output]
target = "vendor"
strip_prefixes = ["inference/Real-ESRGAN/", "realesrgan/Real-ESRGAN/"]
expected_files = [
  "__main__.py",
  "inference_realesrgan_video.py",
  "realesrgan/__init__.py",
  "realesrgan/utils.py",
  "realesrgan/archs/__init__.py",
  "realesrgan/archs/srvgg_arch.py",
]

[runtime_inputs]
root = "sources"
files = [
  "__main__.py",
  "inference_realesrgan_video.py",
  "realesrgan/__init__.py",
  "realesrgan/utils.py",
  "realesrgan/archs/__init__.py",
  "realesrgan/archs/srvgg_arch.py",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk uv run python -m pytest tests/test_backend_spec.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/backends/spec.py tests/test_backend_spec.py third_party/Upscale/realesrgan/backend.toml
rtk git commit -m "refactor: align backend spec runtime input vocabulary"
```

---

## Task 2: Materialization flow — merge `sources/` into generated `vendor/`

**Files:**
- Modify: `app/backends/materialize.py:24-45`
- Modify: `app/backends/verify.py:53-79`
- Modify: `tests/test_model_providers.py:537-615`

- [ ] **Step 1: Write the failing test**

Update `tests/test_model_providers.py` to construct `sources/` instead of `overlay/` and to build `BackendSpec` with `runtime_inputs`:

```python
def test_ensure_backend_rebuilds_with_runtime_input_files(self) -> None:
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as src:
        root = Path(td)
        runtime_input_root = root / "sources" / "realesrgan"
        runtime_input_root.mkdir(parents=True)
        (root / "sources" / "__main__.py").write_text("entry", encoding="utf-8")
        (runtime_input_root / "__init__.py").write_text("pkg", encoding="utf-8")

        src_root = Path(src)
        (src_root / "inference" / "Real-ESRGAN").mkdir(parents=True)
        (
            src_root
            / "inference"
            / "Real-ESRGAN"
            / "inference_realesrgan_video.py"
        ).write_text("runner", encoding="utf-8")

        spec = BackendSpec(
            root=root,
            backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
            source=SourceSpec(
                type="git",
                url="https://example.invalid/realesrgan.git",
                revision="v1",
            ),
            filter=FilterSpec(
                include=["inference/Real-ESRGAN/inference_realesrgan_video.py"],
                exclude=[],
            ),
            output=OutputSpec(
                target="vendor",
                strip_prefixes=["inference/Real-ESRGAN/"],
                expected_files=[
                    "__main__.py",
                    "inference_realesrgan_video.py",
                    "realesrgan/__init__.py",
                ],
            ),
            runtime_inputs=RuntimeInputsSpec(
                root="sources",
                files=["__main__.py", "realesrgan/__init__.py"],
            ),
        )

        class TempDirStub:
            def __init__(self, name: str) -> None:
                self.name = name

            def cleanup(self) -> None:
                return None

        with patch(
            "app.backends.verify.acquire_backend_source",
            return_value=TempDirStub(src),
        ):
            status = ensure_backend(spec)

        self.assertEqual(status, "rebuilt")
        self.assertEqual(
            (root / "vendor" / ".revision").read_text(encoding="utf-8").strip(),
            "v1",
        )
        self.assertEqual(
            (root / "vendor" / "inference_realesrgan_video.py").read_text(
                encoding="utf-8"
            ),
            "runner",
        )
        self.assertEqual(
            (root / "vendor" / "__main__.py").read_text(encoding="utf-8"),
            "entry",
        )
        self.assertEqual(
            (root / "vendor" / "realesrgan" / "__init__.py").read_text(
                encoding="utf-8"
            ),
            "pkg",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run python -m pytest tests/test_model_providers.py -k runtime_input_files -v`
Expected: FAIL with `NameError: name 'RuntimeInputsSpec' is not defined` or materialization still reading `spec.overlay`

- [ ] **Step 3: Write minimal implementation**

Update `app/backends/materialize.py` to merge repo-owned runtime inputs from the configured root:

```python
def materialize_backend(
    spec: BackendSpec, source_root: Path, relative_paths: list[str]
) -> Path:
    vendor_dir = spec.root / spec.output.target
    if vendor_dir.exists():
        shutil.rmtree(vendor_dir)
    vendor_dir.mkdir(parents=True, exist_ok=True)

    for relative_path in relative_paths:
        source_path = source_root / relative_path
        target_relative = _rewrite_relative_path(
            relative_path, spec.output.strip_prefixes
        )
        _copy_file(source_path, vendor_dir / target_relative)

    if spec.runtime_inputs.files:
        runtime_inputs_root = spec.root / spec.runtime_inputs.root
        for relative_path in spec.runtime_inputs.files:
            _copy_file(runtime_inputs_root / relative_path, vendor_dir / relative_path)

    write_revision(vendor_dir, spec.source.revision)
    return vendor_dir
```

Keep `app/backends/verify.py` contract-first and update the local comments/variable naming so ensure logic talks about runtime inputs, not overlay history:

```python
def ensure_backend(spec: BackendSpec, *, force: bool = False) -> str:
    if spec.source.type != "git":
        raise RuntimeError(
            f"Unsupported backend source type for materialization: {spec.source.type}"
        )

    vendor_dir = spec.root / spec.output.target
    expected_files = expected_backend_files(spec)
    verification = verify_backend(spec.source.revision, vendor_dir, expected_files)
    if verification.status == "ok" and not force:
        return "ok"

    temp_dir = acquire_backend_source(spec)
    try:
        source_root = Path(temp_dir.name)
        all_files = [
            # backend.toml filter patterns are rooted at the transient upstream tree,
            # while runtime inputs live under the backend root. Keeping those inputs
            # separate prevents rebuild from depending on generated vendor state.
            path.relative_to(source_root).as_posix()
            for path in source_root.rglob("*")
            if path.is_file()
        ]
        filtered = filter_paths(all_files, spec.filter.include, spec.filter.exclude)
        materialize_backend(spec, source_root, filtered)
        return "rebuilt"
    finally:
        temp_dir.cleanup()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk uv run python -m pytest tests/test_model_providers.py -k runtime_input_files -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/backends/materialize.py app/backends/verify.py tests/test_model_providers.py
rtk git commit -m "refactor: materialize backend runtime inputs from sources"
```

---

## Task 3: Backend layout — move durable inputs to `sources/` and add backend-root `runner.py`

**Files:**
- Rename: `third_party/Upscale/realesrgan/overlay/__main__.py` → `third_party/Upscale/realesrgan/sources/__main__.py`
- Rename: `third_party/Upscale/realesrgan/overlay/inference_realesrgan_video.py` → `third_party/Upscale/realesrgan/sources/inference_realesrgan_video.py`
- Rename: `third_party/Upscale/realesrgan/overlay/realesrgan/**` → `third_party/Upscale/realesrgan/sources/realesrgan/**`
- Create: `third_party/Upscale/realesrgan/runner.py`
- Modify: `third_party/Upscale/realesrgan/.gitignore:1-2`
- Modify: `tests/test_scripts.py:29-68`

- [ ] **Step 1: Write the failing test**

Update `tests/test_scripts.py` so it asserts `sources/` ownership and a backend-root `runner.py` entrypoint:

```python
def test_realesrgan_sources_own_generated_vendor_boundary(self):
    backend_root = ROOT / "third_party" / "Upscale" / "realesrgan"
    self.assertFalse((ROOT / "third_party" / "Upscale" / ".gitignore").exists())
    backend_gitignore = (backend_root / ".gitignore").read_text(encoding="utf-8")
    self.assertIn("vendor/", backend_gitignore)
    self.assertIn(".tmp/", backend_gitignore)
    self.assertIn("build/", backend_gitignore)
    self.assertIn("__pycache__/", backend_gitignore)

    sources_root = backend_root / "sources"
    self.assertTrue((sources_root / "__main__.py").exists())
    self.assertTrue((sources_root / "inference_realesrgan_video.py").exists())
    self.assertTrue((sources_root / "realesrgan" / "utils.py").exists())
    self.assertFalse((backend_root / "overlay").exists())


def test_realesrgan_runner_delegates_to_materialized_vendor_entrypoint(self):
    runner = (
        ROOT / "third_party" / "Upscale" / "realesrgan" / "runner.py"
    ).read_text(encoding="utf-8")
    self.assertIn('vendor_main = backend_root / "vendor" / "__main__.py"', runner)
    self.assertIn("runpy.run_path", runner)
    self.assertIn("sys.argv", runner)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run python -m pytest tests/test_scripts.py -k realesrgan -v`
Expected: FAIL because `sources/` and `runner.py` do not exist yet and `.gitignore` lacks `.tmp/` / `build/`

- [ ] **Step 3: Write minimal implementation**

Move the durable runtime input files from `overlay/` to `sources/`, then create `third_party/Upscale/realesrgan/runner.py` as the stable backend-root entrypoint:

```python
from pathlib import Path
import runpy
import sys


def main() -> None:
    backend_root = Path(__file__).resolve().parent
    vendor_main = backend_root / "vendor" / "__main__.py"
    if not vendor_main.exists():
        raise FileNotFoundError(
            f"RealESRGAN runtime bundle is missing: {vendor_main}"
        )
    sys.argv[0] = str(vendor_main)
    runpy.run_path(str(vendor_main), run_name="__main__")


if __name__ == "__main__":
    main()
```

Update `third_party/Upscale/realesrgan/.gitignore` to keep only disposable setup output ignored:

```gitignore
vendor/
.tmp/
build/
__pycache__/
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk uv run python -m pytest tests/test_scripts.py -k realesrgan -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add third_party/Upscale/realesrgan/.gitignore third_party/Upscale/realesrgan/runner.py third_party/Upscale/realesrgan/sources tests/test_scripts.py
rtk git commit -m "refactor: move realesrgan runtime inputs under sources"
```

---

## Task 4: Runtime contract — switch callers from `vendor/__main__.py` to backend-root `runner.py`

**Files:**
- Modify: `app/upscale_contract.py:1-50`
- Modify: `app/upscaler.py:92-113`
- Modify: `tests/test_model_providers.py:467-474`
- Modify: `tests/test_upscaler.py:258-258`

- [ ] **Step 1: Write the failing test**

Update the RealESRGAN contract assertions to expect backend-root `runner.py` in the engine file set and command string:

```python
def test_realesrgan_engine_files_point_to_backend_root_runner(self) -> None:
    self.assertIn("realesrgan/runner.py", REALESRGAN_ENGINE_FILES)
    self.assertIn("realesrgan/vendor/inference_realesrgan_video.py", REALESRGAN_ENGINE_FILES)
    self.assertTrue(all(path.startswith("realesrgan/") for path in REALESRGAN_ENGINE_FILES))
```

And update the command-path assertion in `tests/test_upscaler.py`:

```python
self.assertIn("/engines/upscale/realesrgan/runner.py", cmd_str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run python -m pytest tests/test_model_providers.py tests/test_upscaler.py -k realesrgan -v`
Expected: FAIL because the command and engine-file contract still target `realesrgan/vendor/__main__.py`

- [ ] **Step 3: Write minimal implementation**

Update `app/upscale_contract.py` so the durable backend-root runner is part of the required engine files:

```python
REALESRGAN_ENGINE_FILES: tuple[str, ...] = (
    "realesrgan/runner.py",
    "realesrgan/vendor/__main__.py",
    "realesrgan/vendor/inference_realesrgan_video.py",
    "realesrgan/vendor/realesrgan/__init__.py",
    "realesrgan/vendor/realesrgan/utils.py",
    "realesrgan/vendor/realesrgan/archs/__init__.py",
    "realesrgan/vendor/realesrgan/archs/srvgg_arch.py",
)
```

Update `app/upscaler.py` so the runtime command uses the backend-root entrypoint:

```python
def build_command(
    self,
    input_path: str,
    output_dir: str,
    engine_dir: str,
    weights_dir: str,
    scale: int,
    target_width: int | None = None,
    target_height: int | None = None,
) -> list[str]:
    # Runtime jobs must enter through the backend root so rebuild-safe project
    # integration code stays stable even if the generated vendor bundle is refreshed.
    script = container_join(engine_dir, "realesrgan", "runner.py")
    model_path = container_join(
        weights_dir, REALESRGAN_WEIGHT_FAMILY, REALESRGAN_WEIGHT_FILENAME
    )
    return [
        self.assets.runtime_python or sys.executable,
        script,
        "-i",
        input_path,
        "-o",
        output_dir,
        "-n",
        "realesr-animevideov3",
        "--model_path",
        model_path,
        "-s",
        str(scale),
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk uv run python -m pytest tests/test_model_providers.py tests/test_upscaler.py -k realesrgan -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/upscale_contract.py app/upscaler.py tests/test_model_providers.py tests/test_upscaler.py
rtk git commit -m "refactor: route realesrgan runtime through backend runner"
```

---

## Task 5: Maintainer docs — match shipped backend names and rebuild semantics

**Files:**
- Modify: `docs/guide/backend-runtime-bundle.md`
- Test: `tests/test_backend_spec.py`
- Test: `tests/test_scripts.py`

- [ ] **Step 1: Write the failing doc-oriented assertions**

Add one concrete assertion to `tests/test_scripts.py` that proves the shipped backend layout exists, so doc updates cannot drift silently:

```python
def test_realesrgan_backend_root_contains_runner_and_sources_contract(self):
    backend_root = ROOT / "third_party" / "Upscale" / "realesrgan"
    self.assertTrue((backend_root / "runner.py").exists())
    self.assertTrue((backend_root / "sources").is_dir())
    self.assertTrue((backend_root / "backend.toml").exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk uv run python -m pytest tests/test_scripts.py -k runner_and_sources_contract -v`
Expected: FAIL until `runner.py` and `sources/` are present

- [ ] **Step 3: Update maintainer guide wording**

Edit `docs/guide/backend-runtime-bundle.md` so its RealESRGAN examples describe the shipped Phase 1 layout and runtime boundary explicitly:

```markdown
third_party/Upscale/realesrgan/
  backend.toml
  runner.py
  sources/
  vendor/
  .tmp/
  build/
```

And in the flow section, use this exact sequence:

```markdown
1. acquire upstream source for the declared revision,
2. filter that source to the declared runtime subset,
3. merge repo-owned runtime inputs from `sources/`,
4. materialize the final bundle under `vendor/`,
5. write `.revision`,
6. verify the expected runtime bundle files exist.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk uv run python -m pytest tests/test_scripts.py -k runner_and_sources_contract -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add docs/guide/backend-runtime-bundle.md tests/test_scripts.py
rtk git commit -m "docs: align backend runtime bundle guide with realesrgan layout"
```

---

## Self-Review

### Spec coverage
- Goal state covered: backend-root `runner.py`, committed `sources/`, disposable `vendor/`, and removal of `[overlay]` / `[legacy_materialized]` are implemented across Tasks 1, 3, and 4.
- Install / materialize / verify flow covered: Task 2 keeps verify read-only and rebuilds `vendor/` from transient upstream + committed runtime inputs.
- Persistence and rebuild boundary covered: Task 3 updates `.gitignore`, file layout, and script assertions so `sources/` stays committed while `vendor/`, `.tmp/`, and `build/` stay disposable.
- Maintainer-facing documentation covered: Task 5 aligns the shipped guide with the resulting file layout and rebuild semantics.
- No uncovered spec section remains for Phase 1 scope.

### Placeholder scan
- No `TODO`, `TBD`, “appropriate error handling”, or cross-task shorthand remains.
- Every code-changing step includes concrete code blocks.
- Every verification step includes exact commands and expected outcomes.

### Type consistency
- Plan consistently uses `RuntimeInputsSpec`, `runtime_inputs.root`, and `runtime_inputs.files`.
- RealESRGAN runtime entrypoint is consistently `third_party/Upscale/realesrgan/runner.py` for durable integration and `vendor/__main__.py` for generated bundle execution.
- Runtime bundle output remains `vendor/` in all tasks and tests.
