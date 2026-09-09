# InjazEdu Local AI — Final Implementation Plan (v2)

> **Status:** approved plan — supersedes `injazedu-local-ai-code-agent-implementation-plan.md`.
> Every claim marked *verified* was checked against the real assets in this repository
> (textbooks, MySQL schema, the `injazedu/` Laravel app) or measured on this machine.
> `injazedu/` is read-only here; all InjazEdu-side changes described in §7 are work for the
> InjazEdu team, not this repository.

---

## 1. Context

InjazEdu sells Qiyas professional-licence, STEP and IELTS prep courses in Saudi Arabia across
**~40 categories, each with courses, each course with its own Arabic textbook** (DOCX/PDF, like the
two in `docs/textbooks/`). Trainers and the moderation team author every MCQ by hand. Producing
5 quizzes × 20–30 questions per day is the bottleneck.

The goal is a **local, self-hosted AI service** that turns those textbooks into
**reviewed-before-publish MCQ drafts**, then automates Telegram/WhatsApp workflows — running on a
MacBook Pro M1 Pro / 16 GB with Ollama, portable to vLLM, integrating with the production
Laravel 9 + MySQL app across a network boundary.

A first plan was drafted with GPT (`docs/plan/core/injazedu-local-ai-code-agent-implementation-plan.md`).
This document reviews it against the **actual** assets and replaces it.

---

## 2. Review of the existing plan

### 2.1 What is right and is kept

| Kept | Why |
|---|---|
| Separate AI service; MySQL stays the business source of truth | Correct blast-radius isolation |
| AI output is a **draft**; human approval mandatory before publish | Non-negotiable for exam content |
| Model Gateway abstraction over an OpenAI-compatible API | Verified: Ollama's `/v1/embeddings` and JSON-schema `format` both work here |
| Structure-aware chunking instead of fixed N-word splits | Essential for this book |
| Background jobs with an explicit state machine | Generation takes minutes on this hardware |
| Prompt/model versioning + reviewer-outcome evaluation | The only honest way to pick a prompt |
| Phased milestones, thin vertical slice first | Good discipline — kept, but re-ordered |
| Filament for the control panel | Fastest admin CRUD; team is a Laravel team |

### 2.2 What is wrong or missing — each point verified against the real files

**A. The generation model is too small — now with evidence.**
Measured this session on `gemma4:e2b-it-qat` (effective ~2 B): **69 tok/s generation, 5 schema-valid
Arabic MCQs in 29.8 s (~6 s/question)**. Plumbing is fine. Quality is not: the first stem it produced was

> «وفقًا للمعيار الأول (القيم والمسؤوليات المهنية)، **ما هو الدور الذي يضطلع به المعلم** فيما يتعلق بالقيم الإسلامية؟»

That is a *meta-question about the passage*, not a Qiyas **situational** item. Real book items look like

> «معلم طلب من طلابه تنظيف الحديقة والمسجد المجاورين للمدرسة، ما أفضل طريقة يتصرف بها المعلم؟»

Fixed in §16 (bigger model) + §11 (few-shot from the book's own items) + §12 (a validator that rejects
"وفقًا للنص"-style stems).

**B. The plan assumes the DOCX has heading structure. It does not.**
Unzipping `ملزمة الرخصة المهنية نوفمبر 2026.docx`: 9,988 paragraphs, 8,704 non-empty, **483,247 chars**,
73 tables, 183 drawings, 54 media files. Paragraph styles present: `(none)` ×7,502, `List Paragraph`
×2,393 — **zero `Heading 1..N` styles**. So `python-docx` + `paragraph.style.name` yields a flat wall of
text. Structure must be recovered from font size + bold + Arabic anchor vocabulary (§9.2).

**C. The book's MCQs put all four options on one tab-separated line.**
Verbatim from `أسئلة المعيار الأول`:
```
stem     مجموعة من المعارف والمهارات والقيم الواجب توافرها في المعلم …:
options  أ  القيم الاسلامية   ب  المهارات المهنية   ج  المعارف العلمية   د  المعايير المهنية
```
Sometimes 4 options span 2 paragraphs, sometimes 4. `python-docx` drops `<w:tab/>` and collapses them
into one unusable string. The parser must read `word/document.xml` directly (§9.3).

**D. The single biggest opportunity is missing.**
The textbook already contains **~800 Qiyas-style MCQs with no answer key** (1,201 paragraphs start with
`أ/ب/ج/د`; 814 start with `أ`; 11 exercise headings such as `أسئلة المعيار الأول`, `أسئلة (الدافعية للتعلم)`,
`أسئلة على الهمزة المتوسطة`). Numbering lives in Word auto-numbering (2,249 paragraphs carry `<w:numPr>`),
so the digits aren't even in the text.

This is *exactly* what you described — "create the tests with the questions but display the correct answer
as NULL; the moderation team then determines the correct answer with the trainer". Extracting those items
and having the AI **propose the answer with a cited passage** is far more accurate than free generation
(choose among 4 given options vs. invent them), immediately useful, and yields a **style corpus** and an
**evaluation set** for free. → **This is Milestone 1** (your decision confirms it).

**E. The STEP PDF will probably not extract as clean Arabic.**
`ملزمة ستيب 2026_.pdf`: PDF-1.7, 389 pages, 187 image XObjects, 731 `/Font` refs, 40 embedded font files,
but **only 21 `/ToUnicode` CMaps**; 267 content streams contain `Tj`/`TJ` so it is not a scan. Subset-embedded
Arabic fonts without ToUnicode maps extract as garbage glyphs. Needs an **extraction-quality gate + OCR
fallback** (§9.5). No PDF tooling is installed on this machine at all.

**F. Your explicit cross-server question is not actually answered.**
"API key now, HMAC later" ignores the real problem: the AI service runs on a **laptop behind NAT with no
public IP**, while InjazEdu is on a public server. Solved in §7.

**G. Publishing into the real schema is under-specified, and the schema has sharp edges.**
From the live code (`injazedu/database/migrations/*`, `app/Http/Controllers/Dashboard/Quiz/*`):
- Correctness is encoded **only** by `options.points > 0`. There is no `is_correct`; `Question::getCorrectOptionAttribute()` is literally `options()->where('points','>',0)->first()`.
- `options.name` is **VARCHAR(255)**; `questions.name` is LONGTEXT; `QuestionStoreRequest` caps the stem at **2000** chars.
- Questions hang off `sections.quiz_id`; **there is no `questions.quiz_id`**. Publish order is quiz → section → questions → options.
- Creating a quiz today is **three separate session-authenticated HTTP calls with no DB transaction**, and `QuestionController::store` **does not validate `options` at all** — it `json_decode`s a raw string and `createMany`s it.
- `QuestionController` and `SectionController` contain **no `authorize()` calls**, and `routes/admin.php` applies only `['auth','theme']`. Any logged-in user can POST `/admin/questions`. (Worth reporting to the InjazEdu team separately; not this project's job to fix, but do not build on it.)
- **No provenance, no idempotency key** on `questions`/`options` — no `uuid`, `external_id` or `source`. A retried publish silently duplicates a whole quiz.
- 21 tables use soft deletes; `sections/questions/options.order` is the MySQL reserved word `order`; `quizzes.sort_order` is spelled correctly while courses/books/categories use the typo `sorte_order`.
Solved in §7.3–§7.5.

**H. Arabic-specific processing is absent.** No normalisation (أ إ آ→ا, ة/ه, ى/ي, tatweel, tashkeel,
Arabic-Indic digits ٠-٩), no bidi handling, and no acknowledgement that the book's justification inserts
kashida so words arrive broken (`تـتكـون` appears verbatim in the file). Without normalisation, retrieval
and duplicate detection both collapse. §10.1.

**I. Retrieval is dense-only with no quality gate.** A 300 M embedder on Arabic needs lexical help.
§10.4 adds BM25 + Reciprocal Rank Fusion and a labelled retrieval set scored by recall@k / MRR.

**J. Embedding operational details missing.** Verified: `embeddinggemma:300m-qat-q4_0` returns **768 dims**
via `POST /v1/embeddings`; using the model's task prefixes widened the relevant-vs-irrelevant cosine margin
from **+0.4611 to +0.4867** on an Arabic probe. Throughput on real book chunks: **10.2 chunks/s at batch 32**
(7.1 at batch 8). Prefixes matter, the dimension must be pinned in `vector(768)`, and a re-embedding/backfill
path is required for the day the model changes. §10.2–§10.3, §16.5.

**K. Concurrency will break the machine.** Ollama serialises on one Metal context. Default Dramatiq worker
counts will queue-storm it and OOM 16 GB. A single-lane LLM semaphore is required. §16.4.

**L. No answer-verification strategy and no MCQ quality rules.** "Answer Check" is named, never defined.
Missing: independent verification, self-consistency, option-order shuffling to expose position bias,
option-length bias, `جميع ما سبق` overuse, Bloom level, scenario ratio. §12.

**M. Operational gaps:** no observability, no backups, no seeds, no test strategy that runs without a GPU
(a `FakeLLMProvider` is mandatory for deterministic CI), no re-ingest story for a new textbook edition,
no memory budget — **Docker Desktop currently claims 8 GB of your 16 GB**, which plus a 6 GB model leaves
nothing. §16.6, §19.

**N. Content locked in images is ignored.** 183 drawings, 54 media files, 2 SmartArt diagrams, 2 ink
annotations. Some standards content exists only as pictures. Must be an explicit v1 non-goal with a
`has_unextracted_media` flag, not silent data loss. §9.6.

**O. The plan is written for one book. You have ~40 categories' worth.** Layout heuristics tuned to the
الرخصة المهنية book will not transfer to STEP/IELTS/specialisation books. This needs
**parser profiles + a structure-review UI**, or ingestion will not scale past book #2. §9.1, §14.

---

## 3. Ground truth verified this session

### 3.1 Hardware / runtime
| Item | Value |
|---|---|
| Machine | MacBook Pro 18,1 — Apple M1 Pro, 10 cores, **16 GB RAM** |
| macOS | 26.6.2 · free disk 152 GB |
| Docker | running, **8 GB allocated**, 10 CPUs → must drop to ~5 GB |
| Ollama | up on `:11434`; `gemma4:e2b-it-qat` (4.3 GB), `embeddinggemma:300m-qat-q4_0` (238 MB) |
| Postgres client | `psql` present (Homebrew) |
| PDF tooling | **none** — `pdftotext`, `pypdf`, `pymupdf` all absent |

### 3.2 Measured performance (real calls, this session)
| Operation | Result |
|---|---|
| Embedding, batch 32, real 1.9 K-char book chunks | **10.2 chunks/s** |
| Embedding, batch 8 | 7.1 chunks/s |
| Generation `gemma4:e2b-it-qat`, 5 MCQs, JSON schema | 29.8 s total · 681 prompt tok @ 8,584 tok/s · 1,216 gen tok @ **69.1 tok/s** |

**Capacity implication.** One book ≈ 500 chunks → **~50 s to embed**. 40 books ≈ **~35 min**; 200 books ≈ ~2.8 h.
Embedding is *not* the bottleneck. An 8 B Q4 model runs ~3–4× slower than e2b → ~20–25 s per generated
question → a 25-question quiz in **8–12 min**, 5 quizzes/day in **~1 h of model time**. Comfortably feasible.

### 3.3 Textbook A — `ملزمة الرخصة المهنية نوفمبر 2026.docx` (15.6 MB)
483 K chars · 8,704 non-empty paragraphs · 73 tables · 183 drawings · 54 media (6 MB) · 2 SmartArt · 2 ink.
**No heading styles.** Hierarchy carried by vocabulary + font size + bold:
`القسم` (التربوي/اللغوي/الكمي) → `المجال` (الأول–الثالث) → `المعيار` (الأول–العاشر) → topic → knowledge block.
A `فهرس` (TOC) with page numbers exists and is usable as a section-boundary oracle.
11 exercise blocks hold **~800 answer-less MCQs**, situational in style.

**It is three sub-corpora, not one** (verified by re-parsing this session) — one parser profile cannot
cover all three:
| Part | Divider (size 60) | Parsing hazard |
|---|---|---|
| الجزء التربوي | `الرخصة المهنية عام / الجزء التربوي` | none — the baseline case |
| الجزء اللغوي | `… / الجزء اللغوي` | **165 of 559 parsed items have punctuation marks as option text** (`['،','؛',':','!']`) — breaks validators #3 and #10 |
| الجزء الكمي | `… / الجزء الكمي` | 384 paragraphs carry math symbols (`= √ × ÷ ≤ ≥ ± ∑`); table-heavy |

Option-line parse rate with marker-slicing (§9.4): **559 of 814** `أ`-lines yield a clean 4-option set on
a single line; the rest use the 2- or 4-paragraph layout. Zero Latin `A)`-style options in this book.

### 3.4 Textbook B — `ملزمة ستيب 2026_.pdf` (19 MB)
389 pages, unencrypted, not a scan, but poor font-mapping coverage → treat Arabic extraction as unreliable
until measured (§9.5).

### 3.5 InjazEdu app facts that constrain the design
| Fact | Source |
|---|---|
| Laravel **9.52.20**, PHP 8.2, Sanctum 2.15 (`expiration => null`), spatie/permission 5.11 | `composer.json` / `composer.lock` |
| **No Filament, no Livewire, no Horizon.** Blade + Vue 3 + Laravel Mix + yajra DataTables | `package.json`, `webpack.mix.js` |
| Roles seeded: `super_admin, admin, moderator, trainer, user` | `database/seeders/RolesPermissionsSeeder.php:21` |
| Queue driver `database`; `jobs` table exists | `.env`, `2025_03_05_045325_create_jobs_table.php` |
| **No service-to-service auth of any kind exists.** `ValidateSignature` registered but used on zero routes | `app/Http/Kernel.php:66` + grep |
| Public/general quiz = `course_id IS NULL AND lecture_id IS NULL AND status=1`, `category_id` required, and must actually have sections→questions→options | `AxiosController.php:242`, `Api/V2/CategoriesController.php:88` |
| Textbook file = `books.file` (`doc\|docx\|pdf`) at `storage/app/public/books/files/…` on the `local` disk; `spaces`/`google`/`s3` also configured | `BookStoreRequest.php`, `BookController.php:56,60` |
| `routes/admin-v3.php` imports `Dashboard\V3\Quiz\{QuizController, QuestionController, QuestionBankController}` — **classes do not exist**. An in-flight V3 quiz refactor, correctly middleware-gated (`['web','auth','admin','locale','theme']`) | `routes/admin-v3.php:4-6` |
| `QuizController@duplicatePost` already replicates a whole quiz→section→question→option tree — the pattern to copy for transactional creation | `QuizController.php:175-207` |
| App is Arabic-first RTL, `locale=ar`, `timezone=Asia/Riyadh`, separately compiled RTL stylesheets, Hijri dates common | `config/app.php:70,83`, `webpack.mix.js:18` |
| `courses.telegram_channel / telegram_group / telegram_private` already store Telegram targets | courses ALTER migrations 2022-04, 2022-08 |
| `owen-it/laravel-auditing` present; `User` is `Auditable`. Adding the trait to `Quiz`/`Question` gives a free audit trail for AI-published content | `app/Models/User.php:18` |

---

## 4. Decisions taken (confirmed with you)

| # | Decision |
|---|---|
| D1 | **Review happens in the Filament AI Control Center only** in v1. The AI box needs no inbound access. A trainer-facing screen inside InjazEdu is a later phase. |
| D2 | **The InjazEdu app may be modified**: a new internal API + a small migration are in scope for the InjazEdu team. |
| D3 | **Milestone 1 = answer the existing book questions**, not generate new ones. Generation follows. |
| D4 | **Larger local models are allowed**: an ~8 B generator plus a stronger embedder to benchmark. |
| D5 | Corpus scale target: **~40 categories → many courses → one textbook each**. Ingestion must be profile-driven and repeatable, not hand-tuned per book. |

**Assumptions I am proceeding on** (flag if wrong): the AI box has outbound internet; InjazEdu is
reachable over HTTPS; a service user can be created in InjazEdu; the moderation team can use a second
login; no student-facing AI feature in v1.

---

## 5. Target architecture

```
                        ┌──────────────────────────── Mac M1 Pro (local) ────────────────────────────┐
                        │                                                                             │
 InjazEdu (public)      │   ai-api (FastAPI)          ai-worker (Dramatiq)        ai-control          │
 Laravel 9 + MySQL      │   ├ /v1/documents           ├ ingest                    Laravel 11+Filament │
 ┌──────────────┐       │   ├ /v1/retrieval           ├ parse → chunk → embed     (reads Postgres)    │
 │ courses      │       │   ├ /v1/answer-jobs         ├ answer book questions     ─ review UI         │
 │ books.file   │◀──────┼── ├ /v1/generation-jobs     ├ generate MCQs             ─ structure editor  │
 │ quizzes      │  pull │   ├ /v1/drafts              ├ validate                  ─ retrieval tester  │
 │ sections     │       │   └ /v1/publish             └ publish → InjazEdu        ─ prompt/model mgmt │
 │ questions    │◀──────┼── push (HMAC + idempotency)                                                 │
 │ options      │       │        │                                                                    │
 └──────────────┘       │        ▼                                                                    │
                        │   Postgres 16 + pgvector      Redis        n8n                              │
                        │   (Alembic owns schema)       (queue)      (Telegram / WhatsApp / cron)     │
                        │        │                                                                    │
                        │        └────────────▶ Model Gateway ──▶ Ollama (host, native)               │
                        │                        (OpenAI-compatible)  └─▶ vLLM later, same interface  │
                        └─────────────────────────────────────────────────────────────────────────────┘
```

### 5.1 Architecture rules (non-negotiable)

1. InjazEdu MySQL is the business source of truth. **The AI service never holds MySQL credentials.**
2. All AI output is a draft. **Nothing reaches production without a recorded human decision.**
3. Every LLM/embedding call goes through the Model Gateway. **No `import ollama` outside `providers/`.**
4. **Alembic owns the Postgres schema.** Filament connects with a role that has DML but **no DDL**, and its `php artisan migrate` is never run against this database.
5. The AI service only ever makes **outbound** connections. No inbound port is required in v1.
6. Retrieval is always **scoped** by `document_version_id` (and usually by section/standard) — never a global search over 40 books.
7. n8n orchestrates; it never contains AI business logic or prompt text.
8. Every stored artefact records `prompt_version_id` + `model_profile_id` + `document_version_id`.

### 5.2 Component responsibilities

| Component | Owns | Never does |
|---|---|---|
| `ai-api` | HTTP contract, validation, job enqueue, draft CRUD | Long-running model calls in the request path |
| `ai-worker` | Ingestion, embedding, answering, generation, validation, publishing | Serving HTTP |
| `ai-control` (Filament) | All human UI: review, structure editing, prompts, metrics | Schema migrations; direct model calls |
| Model Gateway | Provider selection, retries, timeouts, token accounting, the single LLM lane | Business rules |
| n8n | Scheduling, Telegram/WhatsApp I/O, notifications | Prompting, chunking, validation |

---

## 6. Corpus model — scaling to ~40 categories

```
InjazEdu:  category (≈40) → course (many) → books.file (1 textbook)
AI:        source_document ──▶ document_version ──▶ document_node (tree)
                                              ├──▶ chunk ──▶ embedding
                                              └──▶ book_question (extracted MCQ)
```

- A `source_document` is keyed by `injaz_book_id` (+ `injaz_course_id`, `injaz_category_id`) so drafts, chunks and questions always trace back to a real course.
- A `document_version` is keyed by **SHA-256 of the file bytes**. Re-uploading the same file is a no-op; a new edition creates version *n+1*, leaving old chunks and approved drafts intact and marked `superseded`.
- **Sync job**: `POST /v1/sync/books` pulls the book inventory from InjazEdu (§7.2), diffs hashes, and enqueues ingestion for new/changed files. This is how 40 categories get ingested without manual uploads.
- Manual upload stays available in Filament for books not yet in InjazEdu.

**Ingestion budget** (measured): ~50 s embedding + ~1–3 min parsing per book → **~40 books in well under 2 hours**, re-runnable overnight via n8n.

---

## 7. InjazEdu ↔ AI integration (answers your cross-server question)

### 7.1 Network topology — the AI box initiates everything

The AI service runs on a laptop behind NAT. Therefore:

| Direction | Used for | Mechanism |
|---|---|---|
| **AI → InjazEdu** (outbound HTTPS) | pull categories/courses/books, download textbook files, **publish approved quizzes** | Always. No inbound port, no static IP, no tunnel needed. |
| InjazEdu → AI | *nothing in v1* | Not required, because review lives in Filament (D1). |

When phase 2 puts an "AI Drafts" screen inside InjazEdu, add **one** of:
- **Cloudflare Tunnel** (`cloudflared`) — free, outbound-only, gives a stable hostname + Cloudflare Access in front. **Recommended.**
- **Tailscale** — private mesh, best if only staff devices need it.
- Move `ai-api` to a small VPS and keep only Ollama local (or move the model to a GPU box).

Nothing in the design changes when that happens: it is a base-URL and an auth policy.

### 7.2 New InjazEdu internal API (InjazEdu-side work, D2)

New `routes/internal.php`, prefix `/internal/ai`, registered in `RouteServiceProvider`, middleware
`['api', 'internal.ai']`. Follows the `admin-v3` / `app/Domain/FileTransfer` DTO+Action pattern already in the codebase.

**Read endpoints (AI pulls):**
```
GET  /internal/ai/categories                      → id, name, parent_id
GET  /internal/ai/courses?category_id=&page=      → id, name, category_id, status
GET  /internal/ai/books?course_id=&page=          → id, title, course_id, category_id, type,
                                                     file, file_sha256, file_size, updated_at
GET  /internal/ai/books/{id}/download             → 302 to a short-lived signed URL (Storage::temporaryUrl)
GET  /internal/ai/quizzes/{id}                    → existing quiz tree (for duplicate detection)
GET  /internal/ai/questions?course_id=&since=     → existing questions+options (duplicate corpus)
```
`file_sha256` is the one genuinely new piece of data — add it as a nullable column on `books` and
backfill with a command, so the AI can diff without downloading 40 files every night.

**Write endpoint (AI pushes) — one transactional call:**
```
POST /internal/ai/quizzes
Headers: Authorization: Bearer <sanctum PAT>
         X-Injaz-Timestamp, X-Injaz-Nonce, X-Injaz-Signature, Idempotency-Key
```
```jsonc
{
  "quiz": {
    "name": "اختبار المعيار الأول — القيم والمسؤوليات المهنية",
    "category_id": 12, "course_id": 87, "lecture_id": null,
    "duration": 30, "status": 0,          // 0 = created hidden; a human flips it live
    "description": "...", "hint": null
  },
  "sections": [{
    "name": "القسم التربوي", "order": 1,
    "questions": [{
      "name": "معلم طلب من طلابه …",      // ≤ 2000 chars (QuestionStoreRequest)
      "description": null, "hint": "شرح الإجابة …", "order": 1,
      "options": [
        {"name": "…", "points": 1, "order": 1},   // exactly one option with points > 0
        {"name": "…", "points": 0, "order": 2},
        {"name": "…", "points": 0, "order": 3},
        {"name": "…", "points": 0, "order": 4}
      ]
    }]
  }]
}
```
Response `201 { quiz_id, section_ids[], question_ids[], idempotency_key, replayed: false }`.

**Server-side rules this endpoint must enforce** (the current `/admin/questions` path enforces none of them):
- Whole tree in **one `DB::transaction`**.
- `options`: 2–6 items, each `name` 1–255 chars, **exactly one** with `points > 0`, unique names.
- `questions.name` 3–2000 chars.
- `status` forced to `0` unless an explicit `publish_live: true` plus a permission check.
- `user_id` = the AI service user; `category_id` derived from `course_id` when a course is given (mirrors `QuizCourseController.php:17`).
- Idempotency: `Idempotency-Key` looked up in a new `ai_publications` table; a repeat returns the original `quiz_id` with `replayed: true`.

**New migration (small, D2):**
```php
Schema::create('ai_publications', function (Blueprint $t) {
    $t->id();
    $t->uuid('idempotency_key')->unique();
    $t->string('source')->default('injaz-ai');   // provenance
    $t->foreignId('quiz_id')->constrained()->cascadeOnDelete();
    $t->json('payload_digest')->nullable();      // sha256 + counts, for audit
    $t->timestamps();
});
Schema::table('books', fn (Blueprint $t) => $t->string('file_sha256', 64)->nullable()->index());
```
Optionally add `Auditable` to `Quiz`/`Question`/`Option` so AI-published content shows in `audits`.

### 7.3 Authentication (three layers, all cheap)

1. **Sanctum PAT** on a dedicated `ai-service` user (role `moderator` + a new `publish_ai_quizzes` permission). Sanctum already exists; `config/sanctum.php` has `expiration => null`, so set an explicit expiry for this token or rotate quarterly.
2. **HMAC-SHA256** over `METHOD\nPATH\nX-Injaz-Timestamp\nX-Injaz-Nonce\nsha256(body)` with a shared secret in `settings`/env. Reject if `|now − timestamp| > 300 s` or the nonce was seen (Redis/cache TTL 600 s). Laravel already ships `hash_hmac` usage in `StreamController`/`VapulusController` — same idiom.
3. **Idempotency-Key** as above. Retries are then safe, which matters because the AI box's connection is a home internet link.

IP allowlisting is deliberately **not** used — a home IP is dynamic. Cloudflare Access can replace it later.

### 7.4 Answer-key mapping (your NULL-answer requirement)

| Stage | AI Postgres | InjazEdu MySQL |
|---|---|---|
| Generated / extracted | `ai_suggested_key='ب'`, `final_key=NULL`, `status='ready_for_review'` | — |
| Human approves | `final_key='ب'`, `question_points=1`, `status='approved'`, `reviewed_by`, `reviewed_at` | — |
| Published | `status='published'`, `injaz_question_id` recorded | option ب → `points=1`; all others `points=0` |

`final_key` is **NOT NULL–enforced at publish time**: a draft with `final_key IS NULL` can never be
included in a publish payload. That is the technical expression of "no question is published without
human approval".

### 7.5 If D2 had been "no" — the fallback (documented for completeness)
Export approved quizzes as a JSON/CSV file matching the shape at `docs/_.json`, and have a human import
it. Since D2 = yes, this is only the disaster-recovery path.

---

## 8. AI service data model (Postgres 16 + pgvector)

Alembic-managed. Core tables (columns abbreviated to the load-bearing ones):

```
source_documents        id, injaz_book_id, injaz_course_id, injaz_category_id, title,
                        language, parser_profile_id, created_at
document_versions       id, source_document_id, version, source_filename, source_sha256 (unique),
                        mime, byte_size, original_path, processing_status, stats jsonb,
                        superseded_by_id, ingested_at
                        -- processing_status: pending|parsing|parsed|chunking|embedding|ready|failed

parser_profiles         id, name, doc_type (docx|pdf), config jsonb, is_default
                        -- config: level anchors, size/bold thresholds, option alphabet,
                        --         question-region regexes, arabic-ratio threshold

document_nodes          id, document_version_id, parent_id, node_type, level, ordinal,
                        title_path text[], original_text, normalized_text,
                        style_signals jsonb, page_hint, has_media bool, media_refs jsonb
                        -- node_type: section|domain|standard|topic|knowledge|table|
                        --            question_region|example_question|figure|other

chunks                  id, document_version_id, node_ids bigint[], title_path text[],
                        section, standard, topic, text, normalized_text, token_count,
                        char_count, checksum, tsv tsvector          -- GIN index
embeddings              id, chunk_id, model_profile_id, dim, vector vector(768)  -- HNSW cosine
                        -- one row per (chunk, model_profile) → model swaps are additive

book_questions          id, document_version_id, node_id, ordinal, stem, options jsonb,
                        title_path text[], extraction_confidence, extraction_warnings jsonb,
                        ai_suggested_key, ai_confidence, ai_evidence_quote, ai_evidence_chunk_id,
                        final_key, status, reviewed_by, reviewed_at
                        -- this table IS Milestone 1

question_drafts         id, generation_job_id, document_version_id, blueprint_slot_id,
                        stem, difficulty, bloom_level, question_style, source_chunk_ids bigint[],
                        ai_suggested_key, final_key, question_points, status,
                        prompt_version_id, model_profile_id, validation jsonb,
                        duplicate_of_id, similarity, reviewed_by, reviewed_at, review_notes
question_draft_options  id, question_draft_id, key, text, order, is_edited

quiz_drafts             id, name, injaz_category_id, injaz_course_id, injaz_lecture_id,
                        blueprint jsonb, duration_minutes, status, published_quiz_id,
                        idempotency_key uuid
quiz_draft_questions    quiz_draft_id, question_draft_id | book_question_id, section_name, order

generation_jobs         id, kind (ingest|answer|generate|publish), target_ref, params jsonb,
                        state, progress jsonb, error, started_at, finished_at
model_profiles          id, name, provider, base_url, model, role (llm|embedding),
                        params jsonb, dim, is_active
prompt_versions         id, name, role, template, variables jsonb, version, is_active, notes
model_runs              id, job_id, model_profile_id, prompt_version_id, operation,
                        prompt_tokens, completion_tokens, latency_ms, ok, error, request_digest
review_events           id, subject_type, subject_id, reviewer_id, action, before jsonb,
                        after jsonb, reason_code, created_at
                        -- reason_code: wrong_answer|bad_distractors|not_grounded|duplicate|
                        --              language|out_of_scope|other
retrieval_eval_sets / retrieval_eval_items / retrieval_eval_runs
```

Notes that matter:
- `embeddings` is a separate table keyed by `model_profile_id`, so switching from `embeddinggemma` (768) to `bge-m3` (1024) is an **additive backfill**, not a destructive migration. Two `vector` columns are impossible in one table with different dims — use one table per dim or a `dim`-discriminated partial-index scheme. **Recommended: `embeddings_768` and `embeddings_1024` tables** created by Alembic, selected by the active profile.
- `chunks.tsv` gives Postgres full-text search for the lexical half of hybrid retrieval.
- Every draft table carries `prompt_version_id` + `model_profile_id` → full reproducibility.

---

## 9. Document ingestion

### 9.1 Parser profiles (the answer to "40 categories")
A profile is a JSON config, not code. Shipped defaults:
- `qiyas-professional-license-docx-tarbawi` — الجزء التربوي. Anchors `الجزء|القسم|المجال|المعيار`, option alphabet `أ ب ج د`, question regions from `أسئلة|اسئلة|تدريبات|تمارين`.
- `qiyas-professional-license-docx-lughawi` — الجزء اللغوي. Same anchors, but **`symbol_answers: true`** (see §12): ~30 % of its items use punctuation marks as the option text.
- `qiyas-professional-license-docx-kammi` — الجزء الكمي. Same anchors, `math_content: true`, lower Arabic-ratio threshold, table-heavy.
- `step-ielts-mixed-docx` — bilingual, Latin option letters `A B C D` allowed, lower Arabic-ratio threshold.
- `generic-docx`, `generic-pdf`.

**A profile binds to a *part of a document*, not only to a whole document.** Verified (§3.3):
`ملزمة الرخصة المهنية` is three distinct sub-corpora in one file, and one profile cannot parse all three.
`document_versions` therefore carries a default profile, and any `document_node` subtree may override it.

**Auto-profiler**: on first ingest, sample the document, compute the font-size histogram, detect which
anchor vocabulary appears, and *propose* a profile. A human confirms/adjusts it in Filament once per book
family — then every sibling book reuses it.

### 9.2 Structure detection (DOCX, no heading styles)
Signals, combined into a score per paragraph:
1. **Part dividers first (strongest signal).** Full-page titles at **font size 60** mark the top level:
   `الرخصة المهنية عام / الجزء التربوي / د. مصطفى النمر`, then `… / الجزء اللغوي / …`, `… / الجزء الكمي / …`.
   ⚠ **The body says `الجزء`, not `القسم`.** `القسم` appears *only* inside the `فهرس` (TOC) — verified:
   zero body paragraphs begin with `القسم`, five begin with `الجزء`. Anchoring on `القسم` alone finds
   **no** top-level boundary in the body. Match `^\s*(الجزء|القسم)\s+(التربوي|اللغوي|الكمي)`.
   One divider reads `الاخــتبار العام` — kashida-broken, so anchors must run on `normalized_text` (§10.1),
   never on raw text.
2. **Sub-level anchor regex** — `^\s*(المجال|المعيار)\s+(الأول|…|العاشر)` → level 2 / level 3.
3. **Font size vs. document median** (median here is 16 half-points → sizes ≥ 20 are headings).
4. **Bold + short (< 90 chars) + no terminal punctuation.**
5. **Table-of-contents cross-check**: parse the `فهرس` entries (`title …… page`) — which *do* use `القسم` —
   and use them to confirm the size-60 boundaries and to fill `page_hint`. Treat a TOC/body mismatch
   (`القسم التربوي` vs `الجزء التربوي`) as the same node, not two.
6. **Numbering context** (`<w:numPr>`) → list item, never a heading.

Output is a **tree** in `document_nodes` with `title_path` like
`["الجزء التربوي","المجال الأول: القيم والمسؤوليات المهنية","المعيار الأول","وثيقة سياسة التعليم"]`.

### 9.3 DOCX reading — read the XML, not `python-docx`
Justified by §2.2-C. Use `lxml` over `word/document.xml` (+ `styles.xml`, `numbering.xml`) and walk
`w:body` children in order, emitting one record per `w:p` / `w:tbl` with:
`text` (with `<w:tab/>` preserved as `\t`), `pStyle`, first-run `w:sz`, `w:b`, `w:color`, `w:shd`,
`numPr` (list id + level), `w:drawing` count, and the run boundaries.
`python-docx` may still be used for convenience reads, but the structural pass must not depend on it.

### 9.4 Question extraction (Track A — the ~800 items)
```
1. Determine question regions: paragraphs matching the profile's region regex
   (^(أسئلة|اسئلة|تدريبات|التدريبات|تمارين)) up to the next heading-level node.
2. Walk paragraphs in order inside a region.
3. option_line?  →  normalise, then FIND ALL option markers and slice BETWEEN them:
                    marker = (?:(?<=^)|(?<=[\s\t]))([أ-د])[\s\t]*[\)\.\-]?[\s\t]+
                    option[i].text = line[ marker[i].end : marker[i+1].start ]
                    ⚠ Do NOT split the line on tab-runs or >=3 spaces first. The gap between a
                    marker and its own text is often 4+ spaces (`أ    18 حصة`), so pre-splitting
                    severs every marker from its text. Verified: marker-slicing parses
                    559 of 814 `أ`-lines into clean 4-option sets; pre-splitting parses 0.
4. Accumulate fragments across consecutive option lines until keys {أ,ب,ج,د} are complete
   (handles the 1-line, 2-line and 4-line layouts all present in this book).
5. Stem = the preceding non-option paragraph(s), joined while they wrap.
6. Also handle options inside w:tbl cells (73 tables exist; some hold options).
7. Emit book_question with extraction_confidence + warnings.
8. Reject/flag: <4 options, duplicate keys, empty option, stem <15 chars,
   stem lacking a question cue, option text >255 chars (InjazEdu limit).
9. The ~255 `أ`-lines that do not yield 4 options on one line are the 2-paragraph and 4-paragraph
   layouts — step 4 must close them. Track "single-line parse rate" as a per-profile ingestion
   metric, not a success condition.
```
Every rejection is **visible** in Filament as a "needs manual fix" row with the raw source text — never
silently dropped. Target: ≥90 % clean extraction on book #1, measured against a hand-labelled sample of 50.

### 9.5 PDF strategy (STEP book)
```
extract with PyMuPDF  →  quality gate:
      arabic_char_ratio ≥ 0.5  AND  replacement/unmapped-glyph ratio ≤ 0.02
      AND a dictionary spot-check of 20 common Arabic words
  pass → treat like DOCX (structure by font size/position instead of w:sz)
  fail → OCR fallback: render pages at 300 dpi, Tesseract `ara` (or a local VLM),
         mark document_version.stats.ocr = true and lower trust for generation
```
`pymupdf` and `pytesseract` are **not installed** — they are new dependencies. The quality gate result is
shown in Filament so nobody unknowingly generates questions from garbled text.
**Recommendation: ask the InjazEdu team for the DOCX source of the STEP book if it exists** — it removes this whole risk class.

### 9.6 Media — explicit v1 non-goal
183 drawings / 54 media / 2 SmartArt / 2 ink annotations. v1 records `has_media` + `media_refs` on the node
and sets `has_unextracted_media` on any chunk whose node contains a figure. Those chunks are usable for
retrieval but **flagged in the draft** so a reviewer knows a diagram was not read. VLM captioning
(`qwen2.5-vl` / `gemma3` vision) is a phase-3 option.

---

## 10. Normalisation, chunking, retrieval

### 10.1 Arabic normalisation (applied to `normalized_text`, never to `original_text`)
`أ إ آ ٱ → ا` · `ة → ه` (search only) · `ى → ي` · strip tashkeel `ً-ْٰ` · strip tatweel `ـ`
· Arabic-Indic digits `٠-٩` and `۰-۹` → ASCII · normalise `‏/‎/ ` and zero-width chars
· collapse whitespace · repair kashida-broken words (`تـتكـون` → `تتكون`) by removing `ـ` runs
· NFKC. Applied identically to documents and queries — a mismatch here silently halves retrieval quality.
Display always uses `original_text`.

### 10.2 Chunking
Structure-first, size-second:
```
knowledge node  →  if token_count ≤ 900        → one chunk
                   else split on paragraph/list boundaries into 500–900-token chunks
                   with 80-token overlap, never crossing a `المعيار` boundary
```
Every chunk keeps `title_path`, `section`, `standard`, `topic`, `node_ids` → full traceability back to the
exact source structure. Table nodes become one chunk each, serialised as markdown.
Token counting uses the active model's tokenizer via the gateway (fallback: chars/3.5 for Arabic).

### 10.3 Embeddings
- Model: `embeddinggemma:300m-qat-q4_0`, **768 dims**, via `POST /v1/embeddings` (verified).
- **Task prefixes are mandatory** (verified to widen the margin): documents `title: none | text: {chunk}`,
  queries `task: search result | query: {q}`. Encoded in the provider, not in business code.
- Batch size 32 (measured 10.2 chunks/s vs 7.1 at batch 8).
- Index: `CREATE INDEX ... USING hnsw (vector vector_cosine_ops) WITH (m=16, ef_construction=64)`; query `ef_search=64`.
- `bge-m3` (1024 dims) added as a second `model_profile` for A/B on the retrieval eval set (D4).

### 10.4 Hybrid retrieval + RRF
```
query → normalise → ┬─ dense: pgvector cosine top-50, filtered by document_version_id
                    │                              (+ standard/topic when the caller scopes it)
                    └─ lexical: ts_rank_cd over chunks.tsv ('simple' config on normalized_text) top-50
                    → Reciprocal Rank Fusion (k=60) → top-k (default 8)
                    → optional cross-encoder rerank later
```
**Structure filter before vector search**, always. Never search 40 books at once.

### 10.5 Retrieval quality gate — hard stop before generation
Build `retrieval_eval_set` with **50 hand-labelled Arabic queries → expected standard/topic** (30 for the
professional-licence book, 20 for STEP). Metrics: **recall@5, recall@10, MRR@10**.
**Gate: recall@5 ≥ 0.80 before any generation milestone starts.** If dense-only fails, hybrid usually fixes
it; if hybrid fails, switch embedder before touching prompts.

---

## 11. The two generation tracks

### Track A — answer the book's existing questions (Milestone 1, D3)
```
book_question
  → retrieve k=8 chunks scoped to (document_version, same standard first, then whole book)
  → prompt: "اختر الإجابة الصحيحة واقتبس الجملة التي تثبتها. إن لم يدعم النص أي خيار، أجب insufficient."
  → structured output { chosen_key, evidence_quote, evidence_chunk_id, confidence, rationale_ar }
  → run n=3 at temperature 0.6, each with a DIFFERENT random option order (mapped back)
  → majority vote; grounding check: normalized(evidence_quote) ⊂ normalized(chunk.text)
  → agreement 3/3 + grounded          → status ready_for_review, ai_confidence high
     agreement 2/3 or ungrounded      → status ready_for_review, ai_confidence low, flagged
     no majority / insufficient       → status needs_trainer_review, ai_suggested_key = NULL
  → final_key stays NULL until a human sets it
```
Option-order shuffling is the cheapest available defence against LLM position bias and costs nothing but
three calls (~15–25 s per question on an 8 B model → **~800 questions in 4–6 h**, run overnight).

**Why this is the right first milestone:** choosing among 4 given options is a far easier task than
inventing 4 plausible distractors; it produces immediately publishable quizzes; and once trainers confirm
the keys you own a gold set of ~800 Q&A pairs that becomes the few-shot corpus for Track B *and* the
regression suite for every future prompt/model change.

### Track B — generate new MCQs
```
blueprint (per quiz) → slots
for each slot:
   retrieve 2–4 knowledge chunks for the target standard/topic
 + retrieve 3 style exemplars from book_questions of the SAME standard   ← needs Track A
 + prompt_version (Qiyas style card: situational stem, 4 options, one unambiguously correct)
 → structured output, 1–2 questions per call (not 5 — better quality, cheaper retries)
 → validation battery (§12)
 → independent verification: run the Track A answerer on the new question WITHOUT the proposed key
      agree   → ready_for_review
      disagree→ needs_trainer_review, both keys shown to the reviewer
```
Blueprint example:
```json
{ "questions_count": 25, "sections": [{"standard": "المعيار الأول", "count": 10}, {"standard": "المعيار الثاني", "count": 15}],
  "difficulty": {"easy": 5, "medium": 15, "hard": 5},
  "style":      {"scenario": 15, "application": 6, "recall": 4},
  "bloom":      {"remember": 4, "understand": 6, "apply": 10, "analyze": 5} }
```

---

## 12. Validation battery (deterministic first, LLM second)

**Deterministic — no model call, runs in milliseconds:**

| # | Rule | Rationale |
|---|---|---|
| 1 | Valid against the JSON schema | Never parse free text |
| 2 | Exactly 4 options; keys are exactly {أ,ب,ج,د}, distinct | MCQ-only requirement |
| 3 | Each option 1–**255** chars, single line, no HTML | `options.name` VARCHAR(255) |
| 3b | **When the profile sets `symbol_answers: true`, exempt from #3's lower bound and skip #10** — a valid option may be a single punctuation mark (`،` `؛` `:` `!`). Verified: 165 of 559 parsed items in الجزء اللغوي are exactly this. Without the flag the validator auto-rejects all of them. | Language-section reality |
| 4 | Stem 15–**2000** chars | `QuestionStoreRequest: max:2000` |
| 5 | Option texts unique after Arabic normalisation | Catches "same answer twice" |
| 6 | Stem contains no meta-reference: `وفقًا للنص\|حسب النص\|في الفقرة السابقة\|من النص أعلاه` | The exact failure observed from e2b (§2.2-A) |
| 7 | `جميع ما سبق` / `لا شيء مما سبق` ≤ 1 per 10 questions, and correct ≤ 1 per 20 | Qiyas realism |
| 8 | Correct-key position distribution within ±40 % of uniform across a quiz | LLMs over-pick ب/ج |
| 9 | Correct option is the longest option in ≤ 35 % of questions | Classic length tell |
| 10 | Arabic-char ratio ≥ profile threshold (lower for STEP/IELTS; **skipped entirely for `symbol_answers` and `math_content` profiles**) | Language integrity |
| 11 | `source_chunk_ids` exist and belong to the target `document_version_id` | Traceability |
| 12 | Near-duplicate: max cosine vs. existing book/course questions < 0.92 | Else flag `duplicate_of_id` + score |
| 13 | Telegram-publishable check (only when a Telegram target is set): stem ≤ 300 chars, every option ≤ 100 chars, explanation ≤ 200 | Telegram quiz-poll hard limits |

**LLM-assisted — added only after the deterministic set is green:**
- **Grounding**: the cited evidence quote must appear in a retrieved chunk (string containment on normalised text — deterministic, cheap, do it first).
- **Answer verification**: independent answerer must agree (§11).
- **Distractor plausibility**: a light rubric pass scoring each distractor 1–3; any distractor scored 1 (obviously wrong / off-topic) flags the item.

Anything failing 1–5 or 11 is **rejected before review**. Anything failing 6–10, 12, 13 is **flagged, not
rejected** — the reviewer decides. Do not build a large evaluator framework up front.

---

## 13. Human review workflow

**States** (`book_questions` and `question_drafts` share them):
```
extracted|generated → validating → ready_for_review → { approved
                                                      | edited_and_approved
                                                      | needs_trainer_review
                                                      | rejected }
approved | edited_and_approved → queued_for_publish → published
failed_validation (terminal until edited)
```

**Reviewer actions:** Approve · Edit & Approve · Reject (with `reason_code`) · Send to Trainer · Mark duplicate.
**Editable:** stem, all four option texts, `final_key`, `question_points`, `hint` (explanation).
**Always retained** in `review_events`: the AI original, the AI suggested key, the human final key, the
reason code, who and when. This is what powers §17.

**Bulk review UX** is the single most important product decision: 800 questions cannot be reviewed
one-modal-at-a-time. The Filament screen must offer a **dense keyboard-driven table** — one row per
question, options inline, `1/2/3/4` sets the key, `A` approves, `R` rejects, `↓` next — with the evidence
quote in a side panel. Anything slower and the pipeline stalls at the human step.

---

## 14. AI Control Center — UI requirements (Filament)

Separate Laravel 11 + Filament app (`apps/ai-control`), Postgres connection, **no migrations**, own login,
`ar` locale + RTL. Pages, with what each must actually do:

| Page | Must support |
|---|---|
| **Dashboard** | Per-book ingestion status, drafts by state, today's approval/edit/rejection rates, model-time used, failed jobs |
| **Source Documents / Versions** | List by category→course→book, ingest status, SHA, "re-ingest", upload manual DOCX/PDF, extraction-quality badge (incl. PDF gate result) |
| **Parser Profiles** | Edit the JSON config, test it against a document, see the auto-profiler's proposal, clone a profile |
| **Structure Explorer** ★ | Tree of `document_nodes` with the source text; promote / demote / merge / split a node; re-run chunking for the affected subtree. **Without this, 40 books cannot be onboarded.** |
| **Chunk Explorer** | Filter by standard/topic, view text + token count + `has_unextracted_media`, see which drafts cite it |
| **Retrieval Tester** | Arabic query box, scope selector, side-by-side dense vs. lexical vs. RRF results with scores; save a query into the eval set |
| **Retrieval Eval** | Manage eval sets, run them, compare recall@k / MRR across `model_profile`s |
| **Book Questions** ★ | The Milestone-1 review queue. Dense keyboard-driven table, evidence side panel, bulk approve, filter by confidence/standard/status |
| **Generation Jobs** | Create from a blueprint, watch progress, per-slot failures, retry a slot |
| **Question Drafts** | Same dense review UX; shows AI key vs. verifier key, validation flags, duplicate candidates with scores |
| **Quiz Drafts** | Assemble approved questions into a quiz, set sections/duration/target course, preview, **Publish** |
| **Publications** | Every publish attempt, idempotency key, resulting InjazEdu `quiz_id`, deep link, replay status |
| **Prompt Versions** | Edit, version, diff, activate; per-prompt outcome stats |
| **Model Profiles** | Provider/base-URL/model/params, mark active, latency and token stats, "switch to vLLM" is editing a row here |
| **Evaluations** | Approval / edit / rejection / answer-correction rates sliced by prompt × model × standard |
| **Duplicate Candidates** | Pairs with similarity, merge/ignore |
| **Integrations & n8n** | Webhook targets, secrets, workflow status, last run — **not** a re-implementation of n8n's editor |
| **Jobs & Logs / Audit** | Job queue state, `model_runs` with token+latency, `review_events` audit |

**What needs *no* UI:** chunking, embedding, validation and publishing internals — they are jobs surfaced
through the pages above.

---

## 15. n8n workflows (after quality is proven)

*The parallel Moderation Intelligence track (`docs/plan/telegram/telegram-moderation-intelligence.md`)
keeps its own Telegram ingestion and alerting outside n8n; n8n's role there is limited to scheduled
digests and external glue — see that plan's §8.*

1. **Nightly book sync** — cron → `POST /v1/sync/books` → ingest new/changed textbooks → Telegram summary to the moderation channel.
2. **Nightly answer pass** — cron → `POST /v1/answer-jobs` for un-answered `book_questions` → notify moderators how many are ready.
3. **Quiz published → Telegram** — AI emits a webhook → n8n posts title, question count and the InjazEdu link to `courses.telegram_channel`.
4. **Telegram quiz polls** — for a published quiz, post each question as a native `sendPoll` with `type=quiz` and `correct_option_id`. **Hard limits: question ≤ 300 chars, each option ≤ 100 chars, explanation ≤ 200 chars** — enforced by validator #13 *before* offering the button, not after a failed API call.
5. **Scheduled draft generation** — cron → `POST /v1/generation-jobs` from a saved blueprint → **drafts only, never auto-publish**.
6. **Customer support (phase 4, separate feature)** —
   `inbound → n8n → identify user via /internal/ai/users/lookup → intent router → {FAQ | course | subscription | technical | complaint} → authorised RAG → confidence/policy gate → reply or human handoff`.
   **Authorisation before retrieval**: paid textbook content must never be retrieved before checking
   `User::hasCourse()`. FAQ/marketing content lives in a separate, public-safe index.
   **WhatsApp must use the official Meta Cloud API** (or a licensed BSP); unofficial libraries risk a
   permanent business-number ban. Telegram first, WhatsApp second.

---

## 16. Models, sizing and portability

### 16.1 Recommended roster (D4)
| Role | Model | Size | Why |
|---|---|---|---|
| Generator (primary) | `qwen3:8b` (Q4) | ~5.2 GB | Strong Arabic, reliable JSON-schema output, fits 16 GB alongside a 5 GB Docker cap |
| Generator (fast lane) | `gemma3:4b-it-qat` | ~3 GB | Bulk answering passes, cheap retries |
| Generator (current) | `gemma4:e2b-it-qat` | 4.3 GB | Keep as the speed baseline in the model-comparison harness |
| Embeddings (primary) | `embeddinggemma:300m-qat-q4_0` | 238 MB | Verified: 768 dims, 10.2 chunks/s, prefix-sensitive |
| Embeddings (challenger) | `bge-m3` | ~1.2 GB | 1024 dims, strong Arabic retrieval — A/B on the eval set |

Do **not** switch the generator on vibes. Add it as a `model_profile`, run the same 50-question answer set
and the retrieval eval, and compare on approval-without-edit rate.

### 16.2 Ollama settings
```
OLLAMA_NUM_PARALLEL=1          # do not let Ollama fan out on a laptop
OLLAMA_MAX_LOADED_MODELS=2     # generator + embedder resident, nothing else
OLLAMA_KEEP_ALIVE=30m
OLLAMA_FLASH_ATTENTION=1
num_ctx: 8192 for generation (4096 for answering), num_predict bounded per call
```
Run Ollama **natively on macOS**, never in Docker (no Metal access in a Linux container).

### 16.3 Model Gateway
```python
class LLMProvider(Protocol):
    async def generate_text(req: TextRequest) -> TextResponse
    async def generate_structured(req: StructuredRequest[T]) -> T   # JSON-schema constrained
class EmbeddingProvider(Protocol):
    async def embed(text: str, kind: Literal["query","document"]) -> list[float]
    async def embed_many(texts, kind, batch_size=32) -> list[list[float]]
```
Implementations: `OpenAICompatibleLLMProvider`, `OpenAICompatibleEmbeddingProvider`, plus
`FakeLLMProvider` / `FakeEmbeddingProvider` for tests. The task-prefix logic lives in the embedding
provider so business code never knows about it.

**Ollama → vLLM is a `model_profiles` row edit**: `base_url` `http://host.docker.internal:11434/v1` →
`http://gpu-host:8000/v1`, `model` → the HF id, `api_key` → whatever vLLM is configured with. One caveat to
encode now: Ollama takes a JSON schema in `format`, vLLM uses `guided_json` / `response_format`. The
provider must own that difference behind `generate_structured`.

### 16.4 Concurrency — the thing that will otherwise break the machine
A single **`llm` lane semaphore (concurrency 1)** in front of every generation call, and a separate
**`embed` lane (concurrency 1)**, both enforced in the gateway. Dramatiq worker processes: 2, threads 4,
but all model work funnels through the semaphores. Per-call timeout 180 s, 2 retries with jitter,
circuit-breaker after 5 consecutive failures.

### 16.5 Changing the embedding model
1. Add the new `model_profile` (with its `dim`). 2. Alembic creates `embeddings_<dim>` if absent.
3. Backfill job re-embeds all chunks (measured: ~35 min for 40 books). 4. Run the retrieval eval on both.
5. Flip `is_active` only if the challenger wins. Old vectors are kept, so rollback is instant.

### 16.6 Memory budget on 16 GB
```
Ollama (8B Q4 + 300M embedder, resident)   ~6.5 GB
Docker Desktop                              ~5.0 GB  ← reduce from the current 8 GB
  postgres 1.5 · redis 0.3 · ai-api 0.6 · ai-worker 0.8 · ai-control 0.5 · n8n 0.6
macOS + apps                                ~4.0 GB
```
n8n is **off by default** and started only when a workflow milestone is being worked on.

---

## 17. Evaluation — how you decide anything

**Primary product metric:** *what fraction of AI questions do trainers approve with no edit?*

| Metric | Source | Target by M6 |
|---|---|---|
| approved_without_edit | `review_events` | ≥ 50 % (Track B) |
| approved_with_edit | `review_events` | — |
| rejected + reason_code | `review_events` | ≤ 20 % |
| **answer_correction_rate** (human changed the AI key) | `ai_suggested_key ≠ final_key` | ≤ 15 % (Track A) |
| grounded_rate | validator | ≥ 95 % |
| duplicate_rate | validator | ≤ 5 % |
| recall@5 / MRR@10 | retrieval eval | ≥ 0.80 / ≥ 0.70 |
| minutes of model time per approved question | `model_runs` | tracked, not targeted |

Every metric is sliceable by `prompt_version` × `model_profile` × `standard`. A prompt or model change is
accepted only if it wins on the frozen eval set — that is what makes the `prompt_versions` /
`model_profiles` tables worth having.

---

## 18. Security, privacy, compliance

1. **Textbooks are paid IP.** The AI Postgres holds their full text — it gets the same protection as the production content: FileVault on, DB not exposed beyond localhost/Docker network, nightly `pg_dump` to an encrypted local volume, no cloud LLM calls ever (this is the strongest argument for the local-only design).
2. **No production MySQL credentials** on the AI box, at any point.
3. Secrets in `.env` files that are gitignored; the InjazEdu HMAC secret and the Sanctum PAT are rotated on a schedule and stored only on the AI box + InjazEdu `settings`.
4. **Authorisation before retrieval** for any future student- or customer-facing feature.
5. Publish endpoint creates quizzes with `status = 0` (hidden) by default; going live stays a human click in InjazEdu.
6. Log redaction: `model_runs` stores token counts, latency and a request digest — not full prompts by default (make full-prompt capture an opt-in debug flag, since prompts contain copyrighted book text).
7. Note for the InjazEdu team, out of scope here but found during review: `/admin/questions` and `/admin/sections` are reachable by **any authenticated user** (`routes/admin.php:6` applies only `['auth','theme']`; those controllers call no `authorize()`). Worth fixing independently.

---

## 19. Repository, tooling, testing

```
injazedu-local-ai/
├── apps/
│   ├── ai-api/                     # FastAPI + Dramatiq (one Python package, two entrypoints)
│   │   ├── app/
│   │   │   ├── api/v1/             # routers: documents, retrieval, answer_jobs,
│   │   │   │                       #          generation_jobs, drafts, publish, sync
│   │   │   ├── domain/             # pure models + rules: documents, questions, quizzes, reviews
│   │   │   ├── application/        # ingestion, retrieval, answering, generation,
│   │   │   │                       # validation, publishing, evaluation
│   │   │   ├── providers/
│   │   │   │   ├── llm/            # base.py, openai_compatible.py, fake.py
│   │   │   │   ├── embeddings/
│   │   │   │   ├── parsers/        # docx_ooxml.py, pdf_pymupdf.py, ocr.py, profiles.py
│   │   │   │   └── injazedu/       # the internal API client (HMAC + idempotency)
│   │   │   ├── infrastructure/     # db, queue, config, telemetry
│   │   │   ├── workers/
│   │   │   └── prompts/            # versioned templates, Arabic
│   │   ├── alembic/
│   │   └── tests/
│   └── ai-control/                 # Laravel 11 + Filament (no migrations against this DB)
├── infra/                          # docker-compose.yml, n8n workflow exports, init sql
├── docs/                           # this plan, schema notes, runbooks, eval sets
└── Makefile
```

**Tooling:** Python 3.12, `uv`, ruff, mypy (strict on `domain/` and `application/`), pytest,
`pytest-asyncio`, `testcontainers` (or a compose-provided Postgres) for pgvector tests.

**Testing strategy — this is what makes the plan executable by an agent:**
- **Golden-file parser tests.** Commit small anonymised DOCX fixtures (a question region, a table of options, a heading run) + expected node/question JSON. These are the highest-value tests in the project.
- **`FakeLLMProvider`** returns canned structured responses → all pipeline tests run in CI with **no model, no GPU**, deterministically.
- **Recorded-response tests** for one real Ollama round-trip per provider, marked `@pytest.mark.llm`, excluded from CI.
- **Contract tests** against a mocked InjazEdu internal API (schema + HMAC + idempotency-replay).
- **Retrieval eval** as a scored job, not a pass/fail test — tracked over time.

---

## 20. Milestones

Each milestone is done only when: implementation exists · tests exist and pass · docs/config updated ·
manual smoke test succeeds · no unrelated scope added · known limitations written down.

| M | Deliverable | Acceptance criteria | Est. |
|---|---|---|---|
| **M0** | Foundation | `docker compose up`; FastAPI `/health`; Postgres + pgvector + Alembic; Redis; Dramatiq worker; Filament logs in against Postgres; Docker capped at 5 GB; Ollama env set | 2–3 d |
| **M1** | Model Gateway | `generate_structured` + `embed_many` behind protocols; `FakeLLMProvider`; task prefixes; llm/embed semaphores; `model_profiles` seeded; **swapping base_url changes no business code** | 2 d |
| **M2** | Documents & OOXML parser | Upload/ingest the professional-licence DOCX; node tree browsable in Filament; SHA-based versioning; golden-file tests green | 4–5 d |
| **M3** | Parser profiles + Structure Explorer | Auto-profiler proposes a profile; a human can fix the tree in Filament and re-run chunking; **a book from a *different category* onboards without code changes** — another part of the same book does not count, it shares the authoring template; all three الرخصة المهنية part-profiles parse their own part | 5 d |
| **M4** | Chunking + hybrid retrieval | Arabic normalisation; 500–900-token structure-aware chunks; HNSW + tsvector; RRF; Retrieval Tester UI; **50-query eval set with recall@5 ≥ 0.80** ← hard gate | 4–5 d |
| **M5** ★ | **Book-question extraction + AI answering** | ≥ 90 % clean extraction on a 50-item hand-checked sample; all ~800 items answered with evidence + confidence; `final_key` NULL until human; dense keyboard review UI; **first 50 keys confirmed by a trainer** | 5–6 d |
| **M6** | Publish to InjazEdu | InjazEdu internal API + HMAC middleware + `ai_publications` migration (InjazEdu team); AI publishes a reviewed quiz; correct option gets `points=1`; retry is idempotent; quiz opens and is answerable in InjazEdu | 4 d (+2 d InjazEdu-side) |
| **M7** | MCQ generation (Track B) | 5 grounded MCQs from one standard, few-shot from M5's confirmed items; full validation battery; independent answer verification; source evidence shown | 5 d |
| **M8** | Quiz builder + duplicate detection | 25-question blueprint → drafts → review → publish; near-duplicate flagging with scores | 4 d |
| **M9** | Corpus scale-out | Nightly `sync/books`; ~40 categories' books ingested and answered; per-book dashboards; failure triage | 3–4 d |
| **M10** | Evaluation loop | Approval/edit/rejection + answer-correction rates by prompt × model; A/B a second generator and a second embedder; pick winners on evidence | 3 d |
| **M11** | n8n: Telegram | Publish → notification; per-question quiz polls with the Telegram length validator | 2–3 d |
| **M12** | n8n: scheduled drafts | Cron creates drafts only; moderators notified; never auto-publishes | 2 d |
| **M13** | Customer support (separate feature) | Telegram intent router, authorised RAG, confidence gate, human handoff; WhatsApp only via the official Cloud API | 8–10 d |

*A second, parallel bounded domain — Moderation Intelligence (TG-M0…TG-M10) — runs alongside this
table; see `docs/plan/telegram/telegram-moderation-intelligence.md` and
`specs/003-tg-m0-moderation-foundation/`. It does not replace or renumber any milestone above.*

**First real target (prove this before anything else):**
```
one DOCX → parsed tree → chunks → hybrid retrieval → extract its ~800 MCQs
        → AI proposes a key + evidence → moderator reviews 50 in Filament
        → publish one quiz into InjazEdu
```

---

## 21. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Structure heuristics don't transfer to other books | **High** | Parser profiles + Structure Explorer (M3) *before* scaling out |
| STEP PDF extracts as garbage Arabic | **High** | Quality gate + OCR fallback; ask for the DOCX source first |
| 8 B model still too weak for Qiyas-quality distractors | Medium | Track A first (easier task), few-shot from real items, verification pass, model A/B harness |
| Review becomes the bottleneck (800 items) | **High** | Dense keyboard-driven bulk review is a first-class requirement, not polish |
| Publish duplicates a quiz on retry | Medium | Idempotency-Key + `ai_publications` (M6) |
| 16 GB exhausted | Medium | Docker capped at 5 GB, single LLM lane, n8n off by default |
| Content trapped in images silently lost | Medium | `has_unextracted_media` flag surfaced in the draft |
| InjazEdu's unauthorised `/admin/questions` route abused | Low but real | Don't build on it; report separately |
| Scope creep into student-facing AI | Medium | Explicit non-goal until M13 |

---

## 22. Verification — how to prove each layer works end to end

```bash
# M0  infra
docker compose up -d && curl -s localhost:8000/health
psql "$DATABASE_URL" -c "select extversion from pg_extension where extname='vector';"

# M1  gateway portability
pytest apps/ai-api/tests/providers -q                 # runs with FakeLLMProvider, no model
LLM_BASE_URL=http://localhost:11434/v1 python -m app.scripts.smoke_llm   # real round-trip

# M2/M3  parser
pytest apps/ai-api/tests/parsers -q                   # golden files
python -m app.scripts.ingest --file "docs/textbooks/ملزمة الرخصة المهنية نوفمبر 2026.docx"
# then open Filament → Structure Explorer and confirm القسم/المجال/المعيار nesting

# M4  retrieval gate
python -m app.scripts.eval_retrieval --set qiyas-50   # must print recall@5 >= 0.80

# M5  extraction + answering
python -m app.scripts.extract_questions --version-id 1   # expect ~800, warnings listed
python -m app.scripts.answer_book_questions --version-id 1 --limit 50
# Filament → Book Questions: review 50, confirm keys, check answer_correction_rate

# M6  publish (staging InjazEdu first)
python -m app.scripts.publish_quiz --quiz-draft-id 1 --dry-run
python -m app.scripts.publish_quiz --quiz-draft-id 1
# repeat the same command → must return replayed:true and the SAME quiz_id
# open the quiz in InjazEdu, answer it, confirm the score is correct

# M7/M8  generation
python -m app.scripts.generate --standard "المعيار الأول" --count 5
pytest apps/ai-api/tests/validation -q                # the full battery
```

Run `make check` (ruff + mypy + pytest) before every milestone is called done.

---

## 23. Open questions for you

1. Is there a **DOCX original of the STEP book**? It removes the largest technical risk in the plan.
2. Is there a **staging copy of InjazEdu** to publish against for M6, or must the first publish target production (with `status=0`)?
3. Roughly how many textbooks in total across the ~40 categories — dozens, or a few hundred? It changes the ingestion schedule, not the design.
4. Should approved questions ever be **reusable across quizzes**? InjazEdu's schema forbids it (a question belongs to exactly one section of one quiz), so reuse means duplication — worth knowing before M8.
