# PanoWan Backend Runtime Vendor Entry Design

> Final implementation target: convert `third_party/PanoWan/` from a project-managed engine source tree into a standard backend runtime that is invoked through backend-root integration code rather than through upstream CLI contracts.
>
> This design assumes the direction already agreed in discussion: PanoWan should target Strategy A (owned full source) because the repository already manages it as a Git submodule integrated into the local workflow. The design therefore focuses on the vendor entry contract and migration path, not on selective source trimming.

## Overview

PanoWan is already a first-class project dependency rather than an ad hoc external runtime. The repository owns its location, versioning model, and workflow integration through `third_party/PanoWan/`. That changes the migration question.

The primary problem is not how to shrink PanoWan into the smallest possible runtime subset. The primary problem is how this project should invoke PanoWan once it is treated as a standard backend runtime.

Per ADR 0003 and ADR 0006, the long-term invocation contract should not depend on upstream project entrypoints such as `panowan-test` or on unstable upstream CLI flags. The platform-facing entrypoint should be backend-root project integration code, specifically `runner.py`, which consumes a stable project-owned invocation contract and then delegates into the materialized backend runtime bundle under `vendor/`.

This design records a multi-phase migration plan that makes `runner.py` the canonical platform entrypoint, keeps `vendor/` as generated runtime output, and gradually removes direct worker dependence on `uv run panowan-test`.

## 1. Goal and Non-Goals

### Goal

Define the architecture and staged migration path for turning `third_party/PanoWan/` into a standard backend runtime with these properties:

- `third_party/PanoWan/runner.py` is the canonical platform entrypoint.
- `third_party/PanoWan/vendor/` is the generated runtime bundle consumed at runtime.
- `third_party/PanoWan/sources/` holds durable repo-owned runtime input files.
- worker/runtime code depends on a project-owned invocation contract rather than upstream CLI shape.
- future capabilities such as image-to-video extend the backend contract through the platform entrypoint rather than by exposing more upstream flags.

### Non-Goals

This design does not:

- finalize the exact first-version invocation payload field list,
- commit to a specific serialization format beyond requiring a project-owned structured runtime input,
- redesign PanoWan internal inference logic,
- require immediate removal of all transitional CLI compatibility in the first migration step,
- or define every future backend's invocation details in this document.

## 2. Current State

Today PanoWan is not yet a standard backend runtime.

### 2.1 What exists already

- The repository manages `third_party/PanoWan/` as a Git submodule.
- PanoWan model assets are already integrated into the product runtime setup flow.
- `PanoWanEngine` validates runtime asset existence before work is accepted.
- the broader backend architecture now has accepted ADR guidance for backend runtime contracts and backend-local input/output boundaries.

### 2.2 What is still non-standard

The current worker path still reaches through project-owned code directly into upstream invocation semantics.

Concretely:

- runtime execution depends on `cwd=settings.panowan_engine_dir`,
- worker code constructs a `uv run panowan-test ...` command directly,
- and the platform contract is therefore coupled to upstream CLI shape.

That coupling is exactly what the backend runtime architecture is supposed to remove.

## 3. Architectural Direction

### 3.1 Canonical runtime entrypoint

The platform should standardize on:

- backend-root `runner.py` as the canonical project integration entrypoint,
- not on upstream PanoWan entrypoints,
- and not on generated `vendor/` internals directly.

`runner.py` is part of the backend root integration layer defined by ADR 0006. It is project-owned code and therefore the correct place to define the stable invocation contract that this repository expects.

### 3.2 Runtime bundle ownership

`vendor/` remains generated runtime output.

It may contain:

- materialized PanoWan runtime code,
- generated wrappers or copied upstream execution files,
- and a provenance marker such as `.revision`.

It is not the durable editing target. Persistent fixes belong in backend-root integration code, backend metadata, or repo-owned runtime inputs under `sources/`.

### 3.3 Invocation layering

The long-term call chain should be:

```text
worker / engine code
  -> backend-root runner.py
  -> project-owned adapter layer
  -> vendor runtime bundle
  -> PanoWan inference internals
```

This layering matters because it keeps platform contract ownership in project code even if vendor bundle shape or upstream invocation details evolve.

## 4. Why Vendor Entry Design Matters More Than Runtime Trimming

For PanoWan, invocation design is the load-bearing decision.

Reasons:

1. The source tree is already intentionally preserved as an owned submodule.
2. The main architecture risk is contract drift between platform code and upstream CLI parameters.
3. Future capability growth, especially image-to-video, will force interface evolution regardless of whether the runtime bundle is trimmed aggressively.
4. If the platform first stabilizes entry semantics, later bundle-shape adjustments remain local implementation details.

Therefore this migration should begin by owning the invocation boundary rather than by optimizing the file subset.

## 5. Contract Shape: Platform Invocation vs Upstream Invocation

### 5.1 Platform invocation contract

The platform-owned contract is what worker code constructs and what `runner.py` consumes.

Its purpose is to express product/runtime intent in stable project vocabulary, for example:

- task or mode selection,
- prompt inputs,
- output target,
- model-path references,
- video or image generation parameters,
- and future mode-specific inputs such as image-to-video conditioning assets.

The contract should be structured, versionable, and independent of upstream CLI naming quirks.

### 5.2 Upstream invocation contract

The upstream invocation contract is whatever current PanoWan runtime code expects today:

- CLI flags,
- Python function signatures,
- working-directory assumptions,
- import path behavior,
- config file discovery,
- and any internal runtime conventions.

This contract is not the platform standard. It is an implementation detail that `runner.py` or adapter code may translate into.

### 5.3 Required separation

The platform should never again require worker code to know upstream invocation details such as `uv run panowan-test` or future equivalents.

That knowledge belongs behind the backend-root entrypoint.

## 6. Preferred Invocation Model

### 6.1 Long-term direction

Long-term, the backend should consume structured runtime input rather than a public CLI contract.

The design does not require immediate commitment to the exact transport form, but the semantics are:

- worker code provides one project-owned job or runtime specification,
- `runner.py` validates and normalizes it,
- `runner.py` dispatches to the correct PanoWan runtime path,
- and downstream runtime code never defines the public platform interface.

A file-backed payload such as `--job <path>` is one acceptable transitional transport because it keeps process boundaries simple while still shifting ownership of the contract away from upstream CLI flags.

### 6.2 Why not keep CLI as the standard

A stable platform contract should not be modeled as a growing list of passthrough CLI flags.

That would:

- freeze unstable upstream names into platform code,
- make image-to-video expansion awkward,
- encourage direct worker dependence on backend-specific flag logic,
- and repeat the coupling this architecture is trying to remove.

### 6.3 Why `runner.py` is the right place

`runner.py` is project-owned, durable, reviewable, and explicitly blessed by ADR 0006 as the backend-root integration entrypoint.

That makes it the correct place to:

- accept project-owned invocation input,
- validate platform-level invariants,
- translate into current runtime expectations,
- and insulate the rest of the platform from upstream churn.

## 7. Multi-Phase Migration Plan

### Phase 1: Introduce backend-root entrypoint without changing product semantics

Create canonical backend-root integration files for PanoWan:

```text
third_party/PanoWan/
  backend.toml
  runner.py
  sources/
  vendor/
```

Phase 1 responsibilities:

- add `runner.py` as the canonical project entrypoint,
- add backend metadata that expresses PanoWan as a backend runtime managed under ADR 0006,
- keep generated-vs-owned boundaries explicit,
- and preserve current runtime behavior even if `runner.py` still delegates to current PanoWan invocation mechanisms internally.

Success condition:

- project code can stop invoking `uv run panowan-test` directly and instead invoke `third_party/PanoWan/runner.py`.

### Phase 2: Introduce structured invocation contract at the runner boundary

Phase 2 changes the public shape of backend invocation without requiring immediate deep runtime refactors.

`runner.py` should:

- accept one structured project-owned runtime input,
- normalize or validate fields,
- map that input to current PanoWan execution semantics,
- and keep upstream CLI compatibility hidden behind the runner layer.

Optional transitional compatibility may remain for a short time, but it should be treated as migration aid, not as the long-term interface.

Success condition:

- worker/engine code depends on project invocation semantics rather than on upstream CLI parameters.

### Phase 3: Move dispatch logic behind stable adapter code

Once `runner.py` is the only public entrypoint, introduce project-owned adapter logic behind it.

Possible files include:

- `runner.py` for transport and bootstrap,
- `sources/runtime_adapter.py` or equivalent for mapping project invocation input to runtime operations,
- and stable helper code for task dispatch and parameter translation.

This phase keeps `runner.py` thin while still preserving a project-owned stable invocation layer.

Success condition:

- task dispatch, parameter normalization, and future capability branching live in project-owned adapter code rather than in worker call sites.

### Phase 4: Fold the existing I2V route into the same backend-root contract

The repository already has an earlier I2V implementation direction recorded in `docs/superpowers/plans/2026-04-23-i2v.md`.

That plan made one correct architectural observation: image-to-video should not be forced through the current `panowan-test` CLI because the needed `input_video` path is not exposed there. It therefore proposed a separate thin wrapper script such as `run_i2v.py` that calls the Python pipeline API directly.

This new backend-runtime direction keeps the useful part of that plan while moving ownership to the ADR 0006 boundary:

- the direct Python API path remains valid for I2V,
- but the project should not expose `run_i2v.py` as a second platform-facing runtime entrypoint,
- and worker code should not branch into a parallel backend command assembly path.

Instead, the old I2V route should be absorbed into `runner.py`.

The updated shape is:

```text
worker / engine code
  -> third_party/PanoWan/runner.py
  -> project-owned adapter logic
     -> t2v path
     -> i2v path
  -> vendor runtime bundle / direct runtime API
```

Concretely, the earlier `run_i2v.py` idea should be reinterpreted as one of two internal implementation options:

1. temporary internal helper code called only by `runner.py`, or
2. project-owned adapter logic moved under backend-owned integration files such as `sources/`.

It should not remain an alternate public contract that worker code targets directly.

That preserves the value of the earlier I2V design while preventing contract drift between text-to-video and image-to-video execution paths.

#### Phase 4.1: I2V compatibility during transition

During transition, `runner.py` may still delegate internally to a separate I2V helper path if that is the easiest way to bridge to the current PanoWan runtime.

However:

- that helper is internal implementation detail,
- `runner.py` remains the only canonical project entrypoint,
- and the project-owned invocation contract remains shared across t2v and i2v.

#### Phase 4.2: I2V contract extension

The platform-owned invocation contract should grow by extending task semantics rather than by introducing another command family.

The earlier I2V plan already established the intended runtime semantics:

- use the existing Wan2.1-T2V-1.3B + PanoWan LoRA path,
- encode the input image as a single-frame video,
- feed it through the video-to-video `input_video` path,
- and use `denoising_strength < 1.0` so output respects input composition.

Those semantics should now be represented as backend-root invocation contract fields handled by `runner.py`, not as a worker-owned special script contract.

#### Phase 4.3: Success condition

At the end of this phase:

- text-to-video and image-to-video share one backend-root invocation boundary,
- worker code does not know about `run_i2v.py`,
- worker code does not know about upstream `input_video` CLI gaps,
- and backend-root integration code owns mode dispatch and parameter translation.

### Phase 5: Reduce dependence on upstream CLI execution path

After the project-owned invocation contract is stable, reduce or remove dependence on `uv run panowan-test` itself.

This may evolve toward:

- direct import of stable runtime functions,
- a project-owned callable runner module within `vendor/`,
- or another runtime path that avoids upstream CLI coupling.

This phase is intentionally last. The public boundary must stabilize before the internal execution path is rewritten.

Success condition:

- the backend runtime can evolve internally without changing platform invocation semantics.

## 8. Backend Layout Target

The target backend root layout is:

```text
third_party/PanoWan/
  backend.toml
  runner.py
  sources/
    ... project-owned runtime inputs and adapter code ...
  vendor/
    ... generated runtime bundle ...
    .revision
  .tmp/
  build/
  ... existing owned source tree during migration ...
```

Important ownership rules:

- `runner.py` is durable project integration code.
- `sources/` is durable repo-owned runtime input.
- `vendor/` is generated runtime output.
- `.tmp/` and `build/` are disposable setup artifacts.
- direct edits in `vendor/` are disposable by contract.

## 9. Implications for `backend.toml`

PanoWan `backend.toml` should do more than describe source provenance.

It should declare:

- backend identity,
- source provenance and source-management assumptions,
- materialization target rules,
- expected generated runtime bundle shape,
- and runtime input participation from `sources/`.

Because PanoWan is Strategy A (owned full source), the source section may differ from transient-clone backends, but the runtime contract should still converge on the same backend-local vocabulary as other backends.

## 10. Testing and Verification Strategy

Testing should follow contract layers rather than only end-to-end success.

### 10.1 Contract-level verification

Verify that:

- backend metadata resolves correctly,
- `runner.py` exists at backend root,
- runtime input files under `sources/` participate in materialization as expected,
- generated `vendor/` bundle contains required runtime files,
- and `.revision` or equivalent provenance remains machine-checkable.

### 10.2 Invocation-boundary tests

Add tests that ensure:

- worker-side invocation targets `runner.py`,
- runner input validation rejects malformed project invocation payloads,
- stable project fields map correctly to current runtime semantics,
- and future task branching such as text-to-video vs image-to-video remains runner-owned.

### 10.3 Regression boundary

A regression is not only runtime failure. It is also any change that makes worker code depend again on upstream PanoWan entrypoints or flags.

That architectural regression should be treated as contract breakage.

## 11. Risks and Mitigations

### Risk 1: Contract drift between runner and runtime internals

Mitigation:

- keep worker-to-backend contract centralized in project-owned runner or adapter code,
- avoid direct worker passthrough of upstream flags,
- and test contract translation explicitly.

### Risk 2: Over-freezing too many platform fields too early

Mitigation:

- first standardize ownership and entrypoint,
- keep initial field set small,
- and add future capability fields only when product needs become clear.

### Risk 3: Confusing generated runtime output with durable source

Mitigation:

- keep `vendor/` ignored and disposable,
- keep persistent fixes in `runner.py`, `sources/`, or backend metadata,
- and test rebuild safety.

### Risk 4: Image-to-video grows a parallel invocation path

Mitigation:

- require new modes to extend the same backend-root invocation contract,
- not to create separate worker-owned command assembly logic.

## 12. Relationship to the Existing I2V Plan

The earlier document `docs/superpowers/plans/2026-04-23-i2v.md` should now be interpreted as an implementation-path precursor rather than as the final backend invocation architecture.

Its durable conclusions still stand:

- image-to-video should use the existing PanoWan/Wan video-to-video pathway rather than a separate Wan I2V model family,
- image input preparation may still require conversion into a single-frame video artifact,
- and image-to-video needs runtime parameters such as `input_video` and `denoising_strength` that are not exposed by the current upstream CLI.

What changes under this design is contract ownership.

The old plan proposed:

- worker-side branching in `generator.py`,
- direct generation and execution of `run_i2v.py`,
- and a backend-specific alternate command assembly path.

The new design keeps the same runtime capability direction but relocates ownership:

- worker code should construct one project-owned invocation payload,
- `runner.py` should own branching between t2v and i2v,
- any transitional I2V helper should sit behind `runner.py`,
- and backend runtime evolution should not require worker call-site rewrites.

That means the old I2V plan is not thrown away. It is subsumed into the backend-root runner architecture.

## 13. Recommended Next Discussion

The next design step should define the first stable project-owned invocation contract for `runner.py`.

That discussion should answer:

- what fields are part of version 1,
- which fields are intentionally not exposed yet,
- how task or mode selection is represented,
- and what transitional compatibility, if any, remains during migration.

That is the right next discussion because the platform boundary should be settled before implementation details such as exact internal transport helpers or deeper runtime refactors.
