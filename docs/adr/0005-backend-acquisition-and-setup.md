# ADR 0005: Backend Acquisition and Setup

Date: 2026-04-25
Status: Proposed

## Context

The project now treats backend implementation as a broader parent concept than individual model providers. The current backend work shows three recurring needs:

- source acquisition for upstream backend code,
- filtering that source into a minimal runtime subset,
- and a repeatable setup flow that materializes backend dependencies into a backend-local vendor tree.

The existing model setup flow is useful, but its scope is too narrow for backend acquisition. A backend may include runtime code, wrappers, filters, and backend-specific assets in addition to model files. Treating this as only a model problem fragments setup logic and encourages backend-specific exceptions.

The project also wants each backend to own its generated dependency boundary. A backend-local `.gitignore` should ignore that backend's `vendor/` directory, and the generated vendor tree should behave like a Python analogue of `node_modules`: regenerated from declared upstream metadata, not committed as project-owned source.

## Decision

Introduce a unified backend setup concept and use `setup-backends` as the canonical setup workflow.

1. **Backends are the parent abstraction**
   - Model provisioning remains part of backend setup, but it is only one subset of backend work.
   - The setup workflow should cover backend code acquisition, filtering, runtime dependency materialization, and model asset checks.

2. **Backend-local ignore rules own generated vendor trees**
   - Each backend directory owns its own `.gitignore`.
   - The backend-local `.gitignore` ignores `vendor/` for that backend.
   - The project root `.gitignore` should not be the mechanism that defines backend-specific generated boundaries.

3. **`backend.toml` is the acquisition and filtering contract**
   - Each backend root declares its upstream source, revision or equivalent provenance, include/exclude filters, and backend setup metadata in `backend.toml`.
   - `backend.toml` is the durable source of truth for how a backend's runtime subset is produced.
   - The legacy `UPSTREAM.lock` concept is not part of the current design.

4. **`vendor/` is a regenerated dependency tree**
   - The backend's `vendor/` directory is populated by setup tooling.
   - It should not be treated as project-owned inference source.
   - The generated tree must remain reproducible from `backend.toml` and the setup tool's filtering rules.

5. **`setup-modules` is superseded by `setup-backends`**
   - The previous module-oriented setup concept is too narrow for the current backend architecture.
   - `setup-backends` becomes the canonical entrypoint for setup and verification.
   - No backwards-compatibility shim is required for the superseded setup name.

6. **Compatibility shims are not retained**
   - The new setup architecture should be adopted directly.
   - Old patch-on-patch flows should not be preserved once they are superseded by the new backend-oriented setup path.

## Consequences

### Positive

- Backend acquisition, filtering, and setup share one explicit contract.
- Each backend owns its generated boundary and can evolve independently.
- Model setup becomes a subset of backend setup instead of a separate special case.
- The generated vendor tree can be regenerated and verified from declarative metadata.
- Future backends can use the same setup flow without inventing new scripts.

### Negative

- The old module-oriented setup path is formally replaced.
- Each backend must carry its own ignore rules and setup metadata.
- Setup tooling becomes responsible for cloning/fetching and filtering upstream sources.

## Alternatives Considered

1. **Keep `setup-models` as the top-level name** — rejected: the abstraction is too small for backend acquisition and filtering.
2. **Use the project root `.gitignore` for all vendor trees** — rejected: backend boundaries should be explicit and local.
3. **Keep committed backend source under `vendor/`** — rejected: this makes upstream code look like project-owned source and weakens the acquisition contract.
4. **Add compatibility wrappers for old setup flows** — rejected: this would preserve a weaker contract and slow the move to the new design.

## Supersedes

This ADR supersedes the narrow setup interpretation currently implied by ADR 0002's model-download-manager framing and adds the backend-oriented setup boundary that ADR 0003 leaves open.

## Related Documents

- [ADR 0001: Engine-oriented Product Runtime](0001-engine-oriented-product-runtime.md)
- [ADR 0002: Unified Model Download Manager](0002-model-download-manager.md)
- [ADR 0003: Backend Runtime Contracts](0003-backend-runtime-contract.md)
- [ADR 0004: Worker Registry and Communication Boundary](0004-worker-registry-and-communication-boundary.md)
