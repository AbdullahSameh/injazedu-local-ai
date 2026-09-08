# Contract: Operator Command Surface — M1 delta

**Serves**: FR-010, FR-026, FR-028, FR-049 · **Rationale**: research
[D-36](../research.md), [D-40](../research.md)

A delta on M0's [`make-targets.md`](../../001-m0-foundation/contracts/make-targets.md). Every M0
target keeps its name and meaning.

---

## New targets

| Target | Does | Serves |
|---|---|---|
| `make seed-profiles` | Seeds the §16.1 model roster into `model_profiles`, `ON CONFLICT (name) DO NOTHING`. **Idempotent, and never overwrites an operator edit** — re-running after you have re-pointed a profile's `base_url` changes nothing | FR-010, SC-013 |
| `make profiles` | Prints the roster as a table: name, role, model, endpoint, dim, active. The read-only answer to "what will the next call use?" | FR-049 |
| `make smoke-llm` | One **real** round-trip against the local runtime: a structured generation and an embedding. Prints the returned shape, token counts and latency. Requires Ollama; the only operator command that does | FR-028, SC-015 |
| `make test-llm` | Runs **only** the `@pytest.mark.llm` tests — the ones `make check` excludes. Deliberate, never automatic | FR-027 |

## Changed targets

| Target | Change | Serves |
|---|---|---|
| `make check` | Gains an **architecture check**: greps for `httpx` / `ollama` / `openai` imports outside `app/providers/` and fails the gate on a hit. Joins the existing secret scan. Still offline, still model-free | FR-002, SC-001 |
| `make migrate` | Unchanged in form; now applies revision `0002_model_gateway` (`model_profiles`, `model_runs`) | FR-047 |
| `make doctor` | Additionally reports which profiles are active and whether their models are actually present in the runtime — the check that would have caught `qwen3:8b` not being pulled | FR-049 |

## Behavioural requirements

- **`make check` must pass with Ollama quit.** This is the gate M0 established and M1 must not
  weaken. `addopts = -m 'not llm'` lives in `pyproject.toml`, not in `check.sh`, so a bare
  `uv run pytest` is equally safe (D-40).
- **`make seed-profiles` is separate from `make migrate`.** A migration re-run on a fresh database
  must not resurrect a profile the operator deliberately deleted (D-36).
- **`make smoke-llm` is the only target that requires a model**, and it says so when the runtime is
  unreachable rather than hanging for the full 180 s deadline.
- **Order for a first run**: `make up` → `make migrate` → `make seed-profiles` → `make smoke-llm`.
  `quickstart.md` walks it.
