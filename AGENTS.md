<!-- SPECKIT START -->
Active feature: **M1 — Model Gateway** (`specs/002-m1-model-gateway/`)

Read before working on this feature:

- `specs/002-m1-model-gateway/plan.md` — implementation plan, Constitution Check, project structure
- `specs/002-m1-model-gateway/spec.md` — requirements (FR-001…FR-051) and success criteria
- `specs/002-m1-model-gateway/research.md` — 18 decisions (D-23…D-40) with rationale and rejected alternatives
- `specs/002-m1-model-gateway/data-model.md` — `model_profiles`, `model_runs`, the gateway Redis keyspace
- `specs/002-m1-model-gateway/contracts/gateway-interface.md` — **the** M1 contract: protocols, models, error taxonomy
- `specs/002-m1-model-gateway/quickstart.md` — operator walkthrough and known limitations

Two measured facts that drive this design (see research.md §0):

1. A truncated structured call returns **HTTP 200 with empty content** (`finish_reason: "length"`).
   Always check `finish_reason` before parsing — D-26.
2. **Ollama does not serialise** concurrent generations. The lane must be machine-wide (Redis lease),
   not an in-process semaphore — D-33. This corrects the source plan's §16.4 premise.

Architecture rule, mechanically enforced by `make check`: **no `httpx` / `ollama` / `openai` import
outside `app/providers/`.**

Previous milestone (still current infrastructure): `specs/001-m0-foundation/`.

Project-wide, always: `.specify/memory/constitution.md`. Its non-negotiables in one line —
`injazedu/` is read-only, Git actions belong to the operator, and no test may touch a database
whose name lacks `_test`.

Broader context: `docs/plan/core/final-injazedu-local-ai-code-agent-implementation-plan.md`.
<!-- SPECKIT END -->
