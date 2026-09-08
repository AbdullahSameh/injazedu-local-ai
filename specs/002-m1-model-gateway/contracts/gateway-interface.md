# Contract: The Model Gateway interface

**Feature**: `specs/002-m1-model-gateway/` · **Date**: 2026-09-03

This is M1's primary contract. It is not an HTTP surface — M1 adds no endpoint — it is the **in-process
interface every later milestone codes against**. M2…M13 depend on the shapes below; changing one after
M1 ships is a breaking change to twelve milestones.

Import boundary: callers import from `app.application.gateway`. **Nothing outside `app/providers/`
may import `httpx`, `ollama` or `openai`** — asserted by `make check` (SC-001).

---

## 1. Protocols

```python
# app/providers/llm/base.py
class LLMProvider(Protocol):
    async def generate_text(self, req: TextRequest) -> TextResponse: ...
    async def generate_structured(self, req: StructuredRequest[T]) -> StructuredResponse[T]: ...

# app/providers/embeddings/base.py
class EmbeddingProvider(Protocol):
    async def embed(self, text: str, kind: TextKind) -> EmbeddingResult: ...
    async def embed_many(self, texts: Sequence[str], kind: TextKind,
                         batch_size: int | None = None) -> BatchEmbeddingResult: ...
```

`§16.3`'s shapes, with return types widened from bare values to results carrying `usage`, because
FR-037 must record token counts and the provider is the only layer that sees them.

Implementations: `OpenAICompatibleLLMProvider`, `OpenAICompatibleEmbeddingProvider` (both parameterised
by profile — one class serves Ollama and vLLM, D-24), `FakeLLMProvider`, `FakeEmbeddingProvider`.

---

## 2. Request and response models

```python
TextKind = Literal["document", "query"]

class TextRequest(BaseModel):
    messages: list[Message]                  # role: system | user | assistant
    max_output_tokens: int | None = None     # overrides the profile's num_predict
    temperature: float | None = None
    context_tokens: int | None = None        # overrides the profile's num_ctx

class StructuredRequest(BaseModel, Generic[T]):
    messages: list[Message]
    schema_model: type[T]                    # a Pydantic model — D-25
    max_output_tokens: int | None = None
    temperature: float | None = None
    context_tokens: int | None = None

class Usage(BaseModel):
    prompt_tokens: int | None
    completion_tokens: int | None            # always None for embeddings (probe 6)

class TextResponse(BaseModel):
    text: str
    usage: Usage
    latency_ms: int
    profile_name: str

class StructuredResponse(BaseModel, Generic[T]):
    value: T                                 # already validated — see §3
    usage: Usage
    latency_ms: int
    profile_name: str

class EmbeddingResult(BaseModel):
    vector: list[float]                      # len == profile.dim, guaranteed
    usage: Usage
    profile_name: str

class BatchEmbeddingResult(BaseModel):
    vectors: list[list[float]]               # len == len(texts), input order — FR-020
    usage: Usage
    profile_name: str
```

`profile_name` is on every response so a caller can record *which* model produced an artefact
(§5.1 rule 8) without a second lookup.

---

## 3. Structured-output guarantees

`generate_structured` returns `StructuredResponse[T]` where `value` is an **instance of the caller's
model**. Getting there, in order — every step can fail, none can be skipped:

1. `schema_model.model_json_schema()` → sent as `response_format.json_schema.schema`, `strict: true`.
   `$defs`/`$ref` are sent verbatim; measured to work (D-25).
2. **`finish_reason` must be `"stop"`.** Anything else → `ModelTruncatedError`. ⚠ This check is not
   optional: a truncated call returns HTTP 200 with `content: ""` (D-26, probe 3). Without it the
   caller sees a JSON parse error and debugs the wrong thing.
3. `json.loads(content)` → `StructuredOutputInvalidError` on failure.
4. `schema_model.model_validate(...)` → `StructuredOutputInvalidError` on failure.

**A caller never receives a partial object.** Steps 2–4 raise; they never return a half-built value
(FR-004, SC-003).

---

## 4. Embedding guarantees

| Guarantee | Mechanism | Requirement |
|---|---|---|
| Prefix applied by kind | `params.prefix_document` / `prefix_query`, `{text}` substituted in the provider | FR-018 |
| Caller never writes a prefix | Templates live on the profile, not in call sites | FR-018, SC-005 |
| One vector per input, input order | Response reordered by `index`, never by arrival | FR-020 |
| Fixed width | Every vector length-checked against `profile.dim`; mismatch → `EmbeddingDimensionMismatchError`, nothing returned | FR-021, SC-004 |
| Oversized batches split internally | Chunked at `params.batch_size` (default 32) and reassembled | FR-019 |
| Empty input rejected | Whitespace-only text → `ProviderRejectedError` naming the index | FR-022 |

⚠ On the last row: Ollama returns a **full 768-dim vector for an empty string** (probe 6). The runtime
will not object, so the gateway must — an empty-text vector is meaningless but indistinguishable from a
real one once it is in M4's index.

---

## 5. Error contract

All inherit `GatewayError`, which carries `retryable: bool`, `profile_name: str` and
`category: str`. **Retry logic branches on `retryable`, never on message text** (FR-032).

| Error | Condition | `retryable` | Caller's fix |
|---|---|---|---|
| `ProviderUnreachableError` | connect/read failure, refused | ✅ | start the runtime |
| `ModelNotAvailableError` | HTTP 404 `not_found_error` | ❌ | pull the model, or fix the profile |
| `ProviderRejectedError` | HTTP 400/422; empty embedding input | ❌ | fix the request |
| `ProviderAuthError` | HTTP 401/403 | ❌ | fix `api_key_env` |
| `ModelTruncatedError` | `finish_reason != "stop"` | ✅ | raise `max_output_tokens` |
| `StructuredOutputInvalidError` | parse or validation failure | ✅ | change the prompt or the model |
| `EmbeddingDimensionMismatchError` | width ≠ `profile.dim` | ❌ | fix the profile's `dim` |
| `ModelTimeoutError` | 180 s deadline exceeded | ✅ | raise the deadline, or use a smaller model |
| `CircuitOpenError` | breaker open (D-32) | ❌ | wait; recovery is automatic |
| `NoActiveProfileError` | no active profile for the role | ❌ | activate one in the Control Center |

`ModelTruncatedError` and `StructuredOutputInvalidError` deserve separate identities even though both
mean "unusable output": the fixes are opposite (a bigger ceiling vs. a different prompt), and M5 will
branch on exactly this.

---

## 6. Execution semantics

Every call, in order:

```
resolve active profile (30 s TTL cache, D-37)   → NoActiveProfileError
check circuit breaker for that profile          → CircuitOpenError (fails in < 1 s, SC-009)
acquire lane  (llm | embed, machine-wide FIFO)  → blocks; ModelTimeoutError on deadline
  ├ attempt 1 ─ on retryable error: backoff 0.5·2ⁿ s, full jitter
  ├ attempt 2
  └ attempt 3                                    (retries = 2, D-31)
release lane  (always — success, failure, timeout, cancellation; FR-034)
record model_runs row                            (failure logged and swallowed, FR-040)
```

**The 180 s deadline covers the whole call including retries and lane wait**, not each attempt — it is
a bound on the caller's wait (D-31).

**The lane is machine-wide.** ⚠ Measured: Ollama does *not* serialise (probe 5 — two simultaneous
generations overlapped, 3.5 s wall against 5.3 s of work), and M0 runs two worker processes plus the
API process. An in-process semaphore would admit three concurrent generations on a 16 GB machine. The
lane is a Redis lease with a watchdog, so a process killed mid-call frees it within 30 s (D-33,
FR-029, FR-034).

---

## 7. Fake providers

```python
FakeLLMProvider(
    responses: list[Any] | None = None,   # scripted queue; else synthesised from schema_model
    fail_with: type[GatewayError] | None = None,
    latency_ms: int = 0,
)
FakeEmbeddingProvider(dim: int = 768, fail_with: type[GatewayError] | None = None)
```

- **Determinism** (FR-024, SC-011): with no script, a structured call synthesises a schema-valid
  instance from the caller's own model, so a fake cannot go stale when a schema changes. Embedding
  vectors are a deterministic hash of the normalised text — same text, same vector; different text,
  different vector — which gives M4's retrieval tests real structure with no model.
- **Failure injection** (FR-025): `fail_with` raises any category in §5, so every branch of §6 is
  testable offline.
- Fakes satisfy the same Protocols and go through the same gateway, so tests exercise the real lane,
  retry, breaker and accounting paths — not a bypass.

---

## 8. Health report delta (M0 `contracts/openapi.yaml`)

`GET /health` gains one field on the existing `model_runtime` component, satisfying FR-039's
requirement that debug capture's state be *visible*:

```json
"model_runtime": {
  "status": "ok", "required": false, "latency_ms": 12,
  "detail": "Ollama 0.33.2",
  "gateway": { "llm_profile": "ollama-gemma4-e2b",
               "embedding_profile": "ollama-embeddinggemma-300m",
               "capture_payloads": false }
}
```

Still **informational** — M0's FR-008 stands: an unreachable model runtime does not fail the overall
verdict, and M1 does not change that. `capture_payloads: true` is the operator's visible reminder that
copyrighted prompt text is being written to the database.
