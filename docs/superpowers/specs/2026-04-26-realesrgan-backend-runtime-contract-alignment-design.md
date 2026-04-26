# RealESRGAN Backend Runtime Contract Alignment Design

> Final implementation target (Phase 1): align the `third_party/Upscale/realesrgan/` backend with ADR 0006 by replacing historical `overlay` terminology with backend-local runtime contract terms.
>
> This design is intentionally narrower than the earlier model-download-manager draft. It focuses on the first concrete backend migration to the ADR 0006 contract and leaves broader multi-backend acquisition generalization for a later phase.

## Overview

Align the RealESRGAN backend under `third_party/Upscale/realesrgan/` with ADR 0006's backend-local runtime input/output contract. The backend root will explicitly separate project-owned integration code, repo-owned runtime inputs, generated runtime bundle output, and ephemeral setup artifacts.

This phase does not attempt to design a full backend-generic acquisition framework for every future backend. It finishes one concrete backend migration so that later generalization can build on stable vocabulary, stable deletion semantics, and a stable install/verify/rebuild contract.

## 1. Goal and Non-Goals

### Goal

Make the RealESRGAN backend conform to ADR 0006 so that its ownership rules and rebuild behavior are obvious from the directory layout and `backend.toml` alone.

At the end of this phase:

- `third_party/Upscale/realesrgan/runner.py` is the backend-root project integration entrypoint.
- `third_party/Upscale/realesrgan/sources/` is the repo-owned runtime input layer.
- `third_party/Upscale/realesrgan/vendor/` remains the generated runtime bundle layer.
- temporary acquisition and setup trees remain disposable and ignored.
- `backend.toml` no longer uses historical sections such as `[overlay]` or `[legacy_materialized]`.
- backend setup code and tests use the same contract vocabulary as ADR 0006.

### Non-Goals

This phase does not:

- define the final acquisition implementation for every future backend,
- require large upstream repositories to be committed into this repository,
- refactor all backend helpers into a maximally generic framework,
- or migrate other upscale backends such as SeedVR in the same change.

## 2. Target RealESRGAN Backend Layout

The RealESRGAN backend root follows the four ADR 0006 layers.

```text
third_party/Upscale/realesrgan/
  backend.toml
  runner.py
  requirements.txt
  .gitignore
  sources/
    ... repo-owned runtime input files ...
  vendor/
    ... generated runtime bundle ...
    .revision
  .tmp/
  build/
```

### 2.1 Project integration layer

Files at the backend root such as `runner.py` are project-owned integration code.

- They define how this project invokes the backend runtime.
- They are not generated output.
- They are not upstream-acquired source snapshots.
- They must survive rebuild.

`runner.py` is the canonical project entrypoint for this backend. Runtime callers should target the backend-root integration entrypoint rather than reaching into upstream project entrypoints directly.

### 2.2 Repo-owned runtime input layer

`sources/` holds durable project-owned runtime input files.

These files participate in runtime bundle materialization, but they are not disposable generated output. They are committed to this repository and are part of the backend-local source of truth.

For RealESRGAN, `sources/` replaces the old conceptual role previously described as `overlay/`. The new name matters because these files are not merely ad hoc post-processing patches. They are explicit runtime inputs owned by this repository.

### 2.3 Generated runtime bundle layer

`vendor/` remains the materialized runtime bundle.

- It is produced by setup tooling.
- It is consumed by runtime code.
- It is safe to delete and rebuild.
- It must not be treated as durable maintained source.

### 2.4 Ephemeral setup layer

Temporary acquisition trees and one-shot build artifacts belong under directories such as `.tmp/` or `build/`.

These directories exist only to support setup work. They must not contain durable project-owned inputs or unique runtime knowledge.

## 3. Persistence and Rebuild Boundary

The backend contract must make it obvious which files belong in this repository and which files are disposable rebuild output.

### 3.1 Files that stay in Git

The following categories are backend-local source of truth and remain committed:

- `backend.toml`,
- `runner.py` and other backend-root integration files,
- `sources/**`,
- backend-root metadata such as `requirements.txt`,
- and any additional durable project-owned backend metadata.

### 3.2 Files that stay ignored and disposable

The following categories are regenerated or ephemeral and remain ignored:

- `vendor/**`,
- `vendor/.revision`,
- `.tmp/**`,
- `build/**`,
- and temporary acquisition trees used during install or rebuild.

### 3.3 Deletion rule

A file or directory is disposable only if install or rebuild can recreate it from the declared backend-local source of truth plus the declared upstream source.

That rule means:

- `vendor/` is disposable,
- temporary setup directories are disposable,
- `sources/` is not disposable,
- and backend-root integration files such as `runner.py` are not disposable.

## 4. `backend.toml` Contract Changes

`backend.toml` remains the durable backend-local contract surface, but its vocabulary changes to match ADR 0006.

### 4.1 Sections that remain

The following contract areas remain:

- `[backend]` for backend identity,
- `[source]` for upstream provenance,
- `[filter]` for upstream source selection,
- `[output]` for runtime bundle target rules and expected bundle shape.

### 4.2 Historical sections removed

The following historical sections are removed from the long-term contract:

- `[overlay]`
- `[legacy_materialized]`

These names describe migration history rather than durable architecture vocabulary.

### 4.3 Runtime input participation becomes explicit

The contract must explicitly express that repo-owned runtime inputs from `sources/` participate in materialization.

The exact TOML field shape can remain modest in Phase 1, but the semantics must be clear:

- upstream acquisition is one input,
- repo-owned runtime files under `sources/` are another input,
- `vendor/` is the output,
- and `expected_files` defines the verification target shape.

### 4.4 Verification meaning

`output.expected_files` represents the runtime bundle contract that verification checks after materialization. It is not a historical snapshot list and not a second editable source of truth.

## 5. Install / Materialize / Verify Flow

Phase 1 keeps the flow concrete and RealESRGAN-focused.

### 5.1 Install / ensure

Install ensures that the backend is ready for runtime use.

For RealESRGAN, that means:

1. acquire upstream source for the declared revision,
2. filter that source to the declared runtime subset,
3. merge repo-owned runtime inputs from `sources/`,
4. materialize the final bundle under `vendor/`,
5. write `.revision`,
6. verify the expected runtime bundle files exist.

### 5.2 Verify

Verify is read-only.

It checks the generated runtime bundle contract without mutating state:

- `vendor/` exists,
- `.revision` matches declared provenance,
- expected runtime bundle files are present.

### 5.3 Rebuild

Rebuild forces regeneration of `vendor/` from declared inputs.

It is valid to delete `vendor/` before rebuild because generated runtime output is disposable by contract.

### 5.4 Runtime responsibility boundary

Runtime execution consumes already-materialized files. Runtime code must not re-acquire upstream source, reconstruct filtering decisions, or regenerate missing setup output during a user job.

## 6. Acquisition Strategy Model Beyond RealESRGAN

Phase 1 only implements the RealESRGAN migration, but the contract should document the intended strategy taxonomy for future backends.

### 6.1 Strategy A: owned full source

Use this when the project intentionally owns or co-maintains the full source tree.

Example: `third_party/PanoWan/` as a project-maintained engine source managed via git submodule.

Characteristics:

- full checkout is acceptable,
- the source tree is intentionally preserved,
- and the repository accepts long-lived ownership of that tree.

### 6.2 Strategy B: selective transient acquisition

Use this when the upstream repository is large or contains substantial material outside runtime needs.

Examples include backends such as SeedVR with training code, datasets, notebooks, or large non-runtime trees.

Characteristics:

- upstream source is acquired transiently during install or rebuild,
- shallow clone, sparse checkout, or equivalent narrowing is preferred when useful,
- filter rules select the runtime subset,
- repo-owned runtime inputs still live under `sources/`,
- and only the final runtime bundle is materialized under `vendor/`.

Large upstream repositories must not be committed into this repository merely to support backend materialization.

### 6.3 RealESRGAN in Phase 1

RealESRGAN is the first backend migrated to this contract. It acts as the proving ground for:

- the rename from historical `overlay` terminology to `sources/`,
- the split between backend-root integration code and generated runtime output,
- the rule that repo-owned runtime inputs stay committed while `vendor/` stays ignored,
- and the install/verify/rebuild semantics that later backends should reuse.

## 7. File Change Summary for Phase 1

| File / area | Change |
|---|---|
| `docs/adr/0006-backend-runtime-input-and-output-contract.md` | Already defines contract vocabulary; no further scope change in this phase |
| `docs/backend-runtime-bundle-guide.md` | New maintainer guide for persistence, rebuild, and acquisition strategy rules |
| `third_party/Upscale/realesrgan/backend.toml` | Remove historical sections and express `sources/` participation in materialization |
| `third_party/Upscale/realesrgan/overlay/` | Rename or replace with `sources/` |
| `third_party/Upscale/realesrgan/runner.py` | Backend-root integration entrypoint |
| `third_party/Upscale/realesrgan/.gitignore` | Keep `vendor/` and ephemeral setup dirs ignored, do not ignore `sources/` |
| `app/backends/spec.py` | Replace overlay-oriented spec model with runtime-input-oriented model |
| `app/backends/materialize.py` | Merge repo-owned `sources/` into generated `vendor/` bundle |
| `app/backends/verify.py` | Continue verifying the runtime bundle contract defined by `backend.toml` |
| `app/upscale_contract.py` and related callers | Align path assumptions with backend-root `runner.py` and generated `vendor/` semantics |
| backend tests | Update to contract-first vocabulary and rebuild semantics |

## 8. Future Work

After Phase 1 stabilizes RealESRGAN, later work may:

- generalize acquisition helpers across backend families,
- support multiple acquisition modes in a more explicit API,
- add further backend examples such as SeedVR,
- and refine backend metadata shapes once more than one migrated backend exercises the same contract.

Those follow-up changes should not reopen the core Phase 1 ownership semantics.

A later roadmap item should promote backend contract metadata into a clearer platform manifest abstraction once more than one backend has converged on the same runtime contract shape.

That future abstraction should:

- define backend-generic semantic fields for runtime entrypoints, runtime dependencies, weight artifacts, acquisition strategy, and materialization outputs,
- let application code consume a platform-level manifest model instead of reaching into backend-specific contract details,
- and reduce app-to-`third_party` coupling by making backend-local TOML parse into a stable platform-owned schema.

That work is intentionally deferred in Phase 1 because only RealESRGAN currently exercises this richer runtime metadata shape. Before introducing a broader manifest layer, the project should first accumulate at least one more migrated backend with comparable runtime contract structure so that shared fields are discovered from stable commonality rather than guessed too early.
