# ADR 0008: Unified Runtime Artifact Layout and Profiled Packaging

Date: 2026-04-27
Status: Proposed

> ADR 0003 remains the durable backend runtime isolation policy record. ADR 0005 remains the acquisition/setup policy record. ADR 0006 remains the backend-local runtime input/output contract record. This ADR defines the shared runtime artifact naming and packaging contract that those ADRs leave implicit.

## Context

ADR 0003 allows backend-specific runtime isolation so optional backend dependencies do not pollute the main worker runtime. ADR 0005 defines backend acquisition and setup as the canonical workflow. ADR 0006 defines backend-local ownership and runtime-bundle boundaries.

Those ADRs define policy and backend-local structure, but they do not yet define one durable project-wide contract for how application and backend runtimes are named, materialized, packaged, and consumed.

That gap now matters for three reasons:

1. **The current runtime naming is inconsistent**
   - The main application runtime still behaves like a historical special case under `/opt/venv`.
   - Backend-specific runtimes use backend-local names such as `/opt/venvs/upscale-realesrgan`.
   - This makes the application runtime look architecturally different from backend runtimes even though both are runtime artifacts with explicit ownership.

2. **Container build behavior has drifted into implicit runtime ownership**
   - Historical Docker stage structure has allowed one stage to rely on another stage's side effects such as a runtime path being created indirectly.
   - That weakens the explicit-runtime model from ADR 0003 and makes stage refactors fragile.
   - The project needs runtime ownership to be readable without reverse-engineering Docker topology.

3. **Future backend growth and release variation need a lighter packaging model**
   - The project expects more backend families over time.
   - Workers should be publishable in different capability profiles instead of forcing one monolithic runtime image.
   - Development environments may need direct source or artifact mounting, while release packaging should remain deterministic.

The missing decision is not another backend-specific integration detail. The missing decision is one project-wide contract for runtime artifact layout and how those artifacts are packaged for development and release.

## Decision

Define one unified runtime artifact layout and one explicit packaging contract for both application and backend runtimes.

### 1. All Python runtimes use one canonical namespace under `/opt/venvs/`

Every project-owned Python runtime artifact lives under `/opt/venvs/<runtime-id>`.

Canonical names are:

- `/opt/venvs/app` for the main application runtime
- `/opt/venvs/<backend-id>` for backend-specific runtimes

Examples:

- `/opt/venvs/app`
- `/opt/venvs/upscale-realesrgan`

`/opt/venv` is retired as historical naming and is not part of the long-term architecture vocabulary.

This rule exists so that the application runtime is treated as a first-class runtime artifact rather than as a special case outside the backend-oriented runtime taxonomy.

### 2. Runtime artifacts are materialized before packaging

The architecture does not require `docker build` to resolve and materialize runtime dependencies as the primary workflow.

Instead:

- the application runtime is materialized by the application setup/build workflow,
- each backend runtime is materialized by that backend's setup/build workflow,
- and packaging consumes those prepared runtime artifacts.

Container packaging remains allowed, but it is a consumer of prepared runtime artifacts rather than the source of truth for how those artifacts come into existence.

This keeps runtime construction explicit and prevents container topology from silently becoming the dependency contract.

### 3. Runtime ownership is explicit and single-owner

Each runtime artifact has one explicit owner:

- the application setup/build flow owns `/opt/venvs/app`,
- each backend setup/build flow owns `/opt/venvs/<backend-id>`,
- and final packaging layers only consume those artifacts.

Therefore:

- a backend runtime must not depend on the application runtime being implicitly present,
- the application runtime must not absorb backend-specific dependencies,
- and packaging must not rely on one artifact existing only because another packaging step happened to create it.

This preserves ADR 0003's isolation rule while making ownership legible at the artifact level.

### 4. Development and release packaging contracts are distinct

Development workflows may prioritize iteration speed and direct inspection.

Development environments may therefore bind-mount:

- project source trees,
- configuration files,
- model directories,
- backend source or generated runtime-bundle directories when appropriate,
- and prebuilt runtime artifact directories when they are platform-compatible with the target runtime.

However, arbitrary host-created virtual environments are not the project's portable cross-platform development contract.

Reasons:

- host operating systems may differ from target runtime operating systems,
- host Python ABI details may differ from the target runtime,
- and a mount-based workflow must not redefine the durable release contract.

Release packaging has the stricter rule:

- release images consume only declared, already-materialized runtime artifacts,
- release packaging does not depend on ad hoc host environment shape,
- and release images should be reproducible from declared setup inputs plus prepared runtime artifacts.

### 5. Packaging profiles are explicit composition choices

Packaging profiles define which runtime artifacts are assembled together for a given worker image or runtime bundle.

Examples include:

- `app-only`
- `app + one backend`
- `app + multiple backends`

Profiles are composition choices, not ownership changes.

That means:

- adding a backend to a profile does not change who owns that backend runtime,
- removing a backend from a profile does not redefine backend readiness or setup,
- and profiles should compose prepared artifacts rather than introduce profile-specific dependency resolution logic.

### 6. Thin packaging is preferred over build-time hidden inheritance

When container images are used, they should act as thin packaging layers around prepared runtime artifacts.

Thin packaging means:

- the image assembly step copies or otherwise includes declared runtime artifacts,
- the image assembly step does not depend on hidden stage side effects to make paths exist,
- and packaging structure should remain understandable even if internal build topology changes.

This does not ban multi-stage container builds. It bans using multi-stage topology as an implicit runtime contract.

### 7. No backward-compatibility shim is retained for legacy runtime naming

Migration to `/opt/venvs/app` is direct.

The project does not retain:

- `/opt/venv` aliases,
- fallback search paths that preserve historical naming,
- or compatibility wrappers whose only purpose is to keep old runtime layout alive.

The runtime artifact contract should be adopted directly once migrated.

## Consequences

### Positive

- The application runtime and backend runtimes now share one explicit naming model.
- Runtime ownership becomes readable without reverse-engineering Docker stages.
- Backend growth becomes easier because new backends add new runtime artifacts rather than mutate the application runtime contract.
- Release packaging can vary by profile without redefining dependency ownership.
- Development workflows can use direct mounts where appropriate without confusing dev convenience with release architecture.
- Container packaging becomes lighter because runtime materialization is defined outside packaging topology.

### Negative

- Existing code, scripts, tests, and packaging paths that assume `/opt/venv` must migrate.
- CI or setup workflows must take clearer responsibility for producing runtime artifacts before release packaging.
- Developers must distinguish more carefully between platform-compatible dev mounts and portable release artifacts.
- Teams used to container-only dependency materialization will need a more explicit artifact workflow.

## Alternatives Considered

1. **Keep `/opt/venv` for the application runtime and `/opt/venvs/<backend>` for backend runtimes** — rejected: preserves a historical special case and weakens a unified runtime taxonomy.
2. **Install backend-specific dependencies into the main application runtime** — rejected: conflicts with ADR 0003 and makes optional backend dependencies mandatory for all workers.
3. **Keep using Docker multi-stage build inheritance as the primary runtime contract** — rejected: too fragile, too implicit, and too easy to break during refactors.
4. **Treat arbitrary host-created virtual environments as the default development contract** — rejected: too platform-specific and too easy to confuse with the durable release contract.
5. **Define packaging profiles as dependency-resolution variants instead of artifact-composition variants** — rejected: mixes release composition with dependency ownership and makes profiles harder to reason about.

## Supersedes

This ADR supersedes the previously implicit project-wide runtime artifact layout and packaging boundary that ADR 0003, ADR 0005, and ADR 0006 left open.

- ADR 0003 remains the backend runtime isolation and readiness policy record.
- ADR 0005 remains the backend acquisition/setup policy record.
- ADR 0006 remains the backend-local input/output and ownership record.
- This ADR adds the shared application-plus-backend runtime naming and packaging contract needed to make those decisions operationally consistent.

## Related Documents

- [ADR 0001: Engine-oriented Product Runtime](0001-engine-oriented-product-runtime.md)
- [ADR 0003: Backend Runtime Contracts](0003-backend-runtime-contract.md)
- [ADR 0005: Backend Acquisition and Setup](0005-backend-acquisition-and-setup.md)
- [ADR 0006: Backend Runtime Input and Output Contract](0006-backend-runtime-input-and-output-contract.md)
- [ADR 0007: GPU-Resident Worker Runtime for PanoWan](0007-gpu-resident-worker-runtime.md)
