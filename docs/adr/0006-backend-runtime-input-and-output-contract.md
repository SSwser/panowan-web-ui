# ADR 0006: Backend Runtime Input and Output Contract

Date: 2026-04-26
Status: Proposed

## Context

ADR 0003 defines backend runtime policy and ADR 0005 defines backend acquisition/setup policy, but the project still lacks one durable record for the backend-local runtime input/output contract.

That missing contract now matters because backend setup is no longer only about model files. A backend runtime may depend on an acquired upstream source subset, repo-owned runtime input files, generated runtime bundle files, provenance markers, and explicit verification rules. Without a backend-local contract, different backends can drift into different directory semantics, different rebuild assumptions, and different verification behavior.

The project also wants additional backends such as Panowan to converge on the same backend architecture rather than repeating implementation-specific directory choices. The missing piece is not another backend-specific integration plan. The missing piece is one backend-generic contract for what a backend root contains, what setup produces, what runtime consumes, what verification checks, and what is always safe to delete and rebuild.

## Decision

Define one backend-local runtime input/output contract that all backends under this project should follow.

### 1. Backend roots use four stable layers

Each backend root is divided into four semantic layers:

1. **Project integration layer**
   - Holds project-owned integration code such as `runner.py`.
   - Defines how this project invokes the backend runtime.
   - Is not generated output and is not upstream-acquired source.

2. **Repo-owned runtime input layer**
   - Holds durable project-owned files that must participate in runtime bundle materialization.
   - Uses `sources/` as the canonical directory name.
   - Stores concrete maintained files rather than relying only on transformation rules.

3. **Generated runtime bundle layer**
   - Holds the materialized runtime bundle under `vendor/`.
   - Contains setup output that runtime code consumes directly.
   - Is regenerated, disposable output rather than project-owned source.

4. **Ephemeral build/setup layer**
   - Holds temporary acquisition trees, intermediate transforms, and one-shot install artifacts.
   - Uses directories such as `.tmp/` or `build/`.
   - Must not carry durable project knowledge.

### 2. `runner.py` is part of the contract

`runner.py` is the canonical project integration entrypoint for a backend.

- It lives at the backend root.
- It represents project-owned invocation logic.
- It should consume the materialized runtime bundle contract rather than re-implement acquisition or filtering logic.
- Backend execution contracts should standardize around backend-root integration files such as `runner.py`, not around upstream project entrypoints.

A backend may contain more integration files than `runner.py`, but they belong to the same project integration layer and follow the same ownership rule.

### 3. Runtime bundles are materialized, not edited in place

A backend runtime bundle is produced by materialization.

Materialization combines:

- the declared upstream-acquired source subset,
- the backend's repo-owned runtime input files,
- and the backend's declared output path rules.

`vendor/` is the result of that materialization step.

Therefore:

- `vendor/` is not the source of truth for backend-owned runtime code.
- setup tooling may replace the whole generated tree during rebuild.
- runtime bundle generation should be deterministic from declared backend metadata plus repo-owned runtime inputs.

### 4. Provenance is part of the runtime contract

A generated runtime bundle must be traceable to declared setup inputs.

At minimum:

- the upstream revision or equivalent provenance must be recorded,
- the generated bundle must preserve a machine-checkable marker such as `.revision`,
- and rebuild must be able to recreate the runtime bundle from declared inputs without depending on manual repair inside `vendor/`.

Provenance markers exist to support verification and reproducibility, not as human-only documentation.

### 5. Verification checks the runtime bundle contract

Backend verification is not a loose filesystem smoke test. It validates the runtime bundle contract.

At minimum, backend verification should check:

- that the generated runtime bundle exists,
- that its provenance marker matches the declared revision or equivalent source identity,
- and that the expected runtime files declared by the backend contract are present.

Command semantics are:

- **install** ensures required backend runtime bundles and model assets are present,
- **verify** validates contract state without mutating it,
- **rebuild** forces regeneration of the runtime bundle from declared inputs.

A backend is not considered ready only because source directories exist. It is ready when its runtime contract verifies successfully.

### 6. Ownership boundaries are explicit

The backend-local source of truth is limited to:

- `backend.toml` and other backend metadata files,
- backend-root project integration files such as `runner.py`,
- and repo-owned runtime input files under `sources/`.

Generated runtime output under `vendor/` is not a durable editing target.

Therefore:

- direct edits inside `vendor/` are disposable,
- fixes that must survive rebuild belong in `sources/`, backend metadata, or backend-root integration code,
- and setup tooling must not depend on unique manual edits living only in generated output.

### 7. `backend.toml` is both setup metadata and bundle-shape contract

`backend.toml` remains the durable backend-local contract surface.

It should describe, in backend-generic terms:

- source provenance,
- source selection and filtering rules,
- output target rules,
- expected runtime bundle shape for verification,
- and repo-owned runtime input participation in materialization.

This means `backend.toml` is not only an acquisition descriptor. It also participates in defining the shape of the generated runtime bundle that verification expects.

### 8. Setup-time and runtime-time responsibilities do not mix

Setup-time responsibilities include:

- acquiring upstream backend source,
- filtering source into the runtime subset,
- merging repo-owned runtime inputs,
- writing provenance markers,
- and materializing the final runtime bundle.

Runtime-time responsibilities include:

- consuming the generated runtime bundle,
- invoking backend execution through project integration code,
- and relying on already-installed dependencies and already-materialized files.

Runtime execution must not dynamically reconstruct acquisition state, recompute filtering decisions, or install missing dependencies during a user job.

### 9. Deletion safety is part of the contract

Deletion safety rules are explicit:

- deleting `vendor/` must always be safe because it is regenerated output,
- deleting `.tmp/` or `build/` must always be safe because they are ephemeral layers,
- deleting `sources/` is not safe because it destroys durable project-owned runtime inputs,
- and backend setup must never require preserving unique runtime knowledge only inside generated output.

These rules exist so that clean rebuild is a supported workflow rather than a recovery accident.

### 10. The contract is backend-generic

This contract applies to all backend families managed under this project.

Backends may differ in:

- interpreter/runtime boundary,
- upstream source layout,
- model assets,
- verification details,
- and execution logic.

Backends should not differ in:

- ownership semantics,
- generated-vs-source boundary,
- deletion safety assumptions,
- or the distinction between setup-time inputs and runtime-time outputs.

New backends such as Panowan should converge on this contract rather than define parallel backend-local layout rules.

### 11. Migration follows contract language, not historical naming

Existing backend directories may carry transitional layout or metadata names during migration.

However:

- historical implementation names do not define long-term architecture vocabulary,
- new backend work should target the canonical contract terms directly,
- and migration should remove temporary or legacy naming once backend directories conform to the declared contract.

The contract language is the long-lived architecture. Migration names are temporary implementation details.

## Consequences

### Positive

- Backend-local runtime contracts become readable without reverse-engineering implementation history.
- Future backends can reuse one ownership, verification, and rebuild model.
- Backend setup and runtime responsibilities stay separate.
- Rebuild behavior becomes safer because deletion rules are explicit.
- Backend metadata and verification can evolve around one stable contract language.

### Negative

- Existing backends may need migration work to converge on canonical names and boundaries.
- Setup tooling and tests must enforce stricter ownership rules than before.
- Some backend-local files may need to move out of generated output and into declared runtime input locations.

## Alternatives Considered

1. **Keep backend-local layout implicit in code and tests** — rejected: too easy for new backends to drift into incompatible boundaries.
2. **Treat generated runtime bundles as editable maintained source** — rejected: breaks rebuild safety and weakens provenance.
3. **Store repo-owned runtime participation only as transformation rules** — rejected: concrete maintained files are easier to review, test, and reproduce.
4. **Let runtime code reconstruct missing setup state dynamically** — rejected: mixes setup with execution and violates backend readiness rules from ADR 0003.
5. **Write backend-specific layout rules separately for each engine family** — rejected: Panowan and future backends should converge on one backend-generic contract.

## Supersedes

This ADR supersedes the previously undefined backend-local runtime input/output boundary that ADR 0003 and ADR 0005 left implicit. ADR 0003 remains the runtime-policy record. ADR 0005 remains the acquisition/setup policy record. This ADR defines the backend-local runtime contract needed to make those policies concrete.

## Related Documents

- [ADR 0001: Engine-oriented Product Runtime](0001-engine-oriented-product-runtime.md)
- [ADR 0003: Backend Runtime Contracts](0003-backend-runtime-contract.md)
- [ADR 0005: Backend Acquisition and Setup](0005-backend-acquisition-and-setup.md)
- [Upscale Backend Integration Design](../superpowers/specs/2026-04-25-upscale-backend-integration-design.md)
