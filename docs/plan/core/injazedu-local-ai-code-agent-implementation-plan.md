# InjazEdu Local AI — Implementation Plan for Codex & Claude Code

## 1. Goal

Build a Local AI platform for InjazEdu that can:

- Ingest DOCX course books.
- Parse and preserve document structure.
- Create embeddings and searchable chunks.
- Generate grounded MCQ drafts.
- Suggest the correct answer.
- Require trainer/moderator review before publishing.
- Build complete quiz drafts.
- Publish approved quizzes through the InjazEdu Laravel API.
- Later automate Telegram/WhatsApp workflows with n8n.
- Keep the inference layer portable from Ollama to vLLM through an OpenAI-compatible interface.

Final flow:

```text
DOCX
 → Parse
 → Structured chunks
 → Embeddings
 → Retrieval / RAG
 → MCQ generation
 → Validation
 → Human review
 → Quiz draft
 → InjazEdu API
 → MySQL
 → n8n integrations
```

---

## 2. Architecture

```text
InjazEdu Core
Laravel + MySQL
- Courses
- Books
- Users
- Quizzes
- Trainer/Moderator AI UI
        |
        | HTTPS Internal API
        v
Injaz AI Platform
- FastAPI
- PostgreSQL + pgvector
- Redis + Worker
- Document ingestion
- Retrieval / RAG
- Question generation
- Validation
- Duplicate detection
- AI draft storage
- Model Gateway
        |
        +--> Ollama now
        +--> vLLM later

AI Control Center
Laravel + Filament

n8n
- Telegram
- WhatsApp
- Notifications
- Scheduling
```

### Architecture rules

1. InjazEdu MySQL remains the business source of truth.
2. FastAPI never writes directly to production MySQL.
3. AI-generated questions are drafts until human approval.
4. Human review is mandatory before publish.
5. LLM access goes through a Model Gateway.
6. Prefer OpenAI-compatible APIs over Ollama-specific calls.
7. n8n handles automation, not core AI logic.
8. Preserve document structure before chunking.
9. Paid content authorization happens before retrieval when student-facing RAG is added.

---

## 3. Technology Stack

### AI backend

- Python 3.12
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- PostgreSQL
- pgvector
- Redis
- Dramatiq (preferred initially)

### Models

Generation:

```text
gemma4:e2b-it-qat
```

Embeddings:

```text
embeddinggemma:300m-qat-q4_0
```

### Local runtime

Run Ollama natively on macOS.

Docker Compose:

```text
ai-api
ai-worker
postgres
redis
ai-control
n8n
```

### AI Control Center

Use **Laravel + Filament**, not React.

Use it for:

- Documents
- Document versions
- Chunk explorer
- Retrieval testing
- Generation jobs
- Question drafts
- Models
- Prompt versions
- Evaluations
- Logs
- Integrations

The normal trainer/moderator workflow should remain inside the existing InjazEdu dashboard.

---

# Phase 0 — Foundation

## Goal

Create a stable local development environment.

## Build

Recommended repository layout:

```text
injaz-ai/
├── apps/
│   ├── ai-api/
│   └── ai-control/
├── infra/
├── docs/
└── docker-compose.yml
```

Environment:

```text
DATABASE_URL=
REDIS_URL=

LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=gemma4:e2b-it-qat

EMBEDDING_BASE_URL=http://host.docker.internal:11434/v1
EMBEDDING_MODEL=embeddinggemma:300m-qat-q4_0
```

## Acceptance Criteria

- FastAPI health endpoint works.
- PostgreSQL works.
- pgvector is enabled.
- Redis works.
- FastAPI can call Ollama.
- Embedding request works.
- Filament loads.

---

# Phase 1 — Model Gateway

## Goal

Keep the application independent from Ollama.

## Build

Interfaces:

```python
class LLMProvider:
    async def generate_text(...)
    async def generate_structured(...)

class EmbeddingProvider:
    async def embed(...)
    async def embed_many(...)
```

Implementation:

```text
OpenAICompatibleLLMProvider
OpenAICompatibleEmbeddingProvider
```

Business services must never call `ollama.chat()` directly.

## Acceptance Criteria

Changing `base_url` and model configuration does not require changing question-generation business code.

---

# Phase 2 — Document Storage

## Goal

Store imported books and versions before AI processing.

## Tables

```text
documents
document_versions
```

Suggested fields:

```text
documents
- id
- injaz_book_id nullable
- injaz_course_id nullable
- title

document_versions
- id
- document_id
- version
- source_filename
- source_hash
- original_path
- canonical_pdf_path nullable
- processing_status
```

## UI

Filament:

```text
Documents
Document Versions
Upload DOCX
```

## Acceptance Criteria

A DOCX can be uploaded, versioned, and identified by checksum.

---

# Phase 3 — DOCX Structural Parser

## Goal

Understand the book before chunking it.

## Parse

Detect:

```text
Heading
Paragraph
List
Table
Question Block
Answer Key
```

Store:

```text
document_nodes
```

Possible node types:

```text
section
standard
topic
knowledge
example_question
answer_key
other
```

Keep:

```text
original_text
normalized_text
title_path
position
parent_id
```

Do not split every N words.

## Acceptance Criteria

The uploaded book can be browsed as a hierarchy in Filament.

---

# Phase 4 — Structure-Aware Chunking

## Goal

Create meaningful retrieval units.

## Strategy

```text
Book
 → Section
 → Standard
 → Topic
 → Knowledge block
 → Size-based split only when needed
```

Initial target:

```text
500–900 tokens per chunk
```

Store metadata:

```text
document_id
document_version_id
section
standard
topic
source_node_ids
token_count
```

## Acceptance Criteria

Every chunk can be traced back to its exact source structure.

---

# Phase 5 — Embeddings + Retrieval

## Goal

Build the first RAG component.

## Build

Embed knowledge chunks using:

```text
embeddinggemma:300m-qat-q4_0
```

Store vectors in pgvector.

Endpoint:

```http
POST /v1/retrieval/search
```

Example:

```json
{
  "document_id": 1,
  "query": "التنمية المهنية للمعلم",
  "top_k": 5
}
```

Prefer:

```text
structure filter
 → vector search
```

over searching the entire knowledge base every time.

## Acceptance Criteria

Manual test queries consistently retrieve relevant source chunks.

Do not proceed to large-scale generation until retrieval quality is acceptable.

---

# Phase 6 — Generate 5 MCQs

## Goal

Generate five grounded MCQs from one selected topic.

## Input

```text
document
standard/topic
question_count
difficulty
question_style
```

## Flow

```text
Request
 → Retrieve knowledge
 → Retrieve optional style examples
 → Prompt
 → Structured LLM output
```

## Output schema

```json
{
  "stem": "...",
  "options": [
    {"key": "A", "text": "..."},
    {"key": "B", "text": "..."},
    {"key": "C", "text": "..."},
    {"key": "D", "text": "..."}
  ],
  "proposed_correct_key": "B",
  "difficulty": "medium",
  "question_style": "scenario",
  "source_chunk_ids": [12, 14]
}
```

Do not parse free-form LLM text.

## Acceptance Criteria

Exactly five schema-valid MCQs are produced with source references.

---

# Phase 7 — Jobs + Draft Storage

## Goal

Treat generation as a background job.

## Tables

```text
generation_jobs
question_drafts
question_draft_options
```

Job states:

```text
queued
retrieving
generating
validating
completed
failed
```

Question states:

```text
generated
ready_for_review
approved
edited_and_approved
rejected
needs_trainer_review
published
```

API:

```http
POST /v1/generation-jobs
GET  /v1/generation-jobs/{id}
```

## Acceptance Criteria

The API returns a job ID immediately and a worker completes generation asynchronously.

---

# Phase 8 — Validation

## Goal

Reject obvious bad outputs before human review.

## Deterministic validation

Check:

- Valid JSON.
- Exactly four options.
- No empty options.
- Unique option texts.
- Valid proposed correct key.
- Valid source chunk IDs.
- Non-empty question text.

Then add gradually:

```text
Grounding Check
Answer Check
Duplicate Check
```

Do not build a large evaluator system initially.

## Acceptance Criteria

Invalid generated questions are clearly flagged and cannot silently enter the review queue.

---

# Phase 9 — Human Review

## Goal

Make AI output safe enough for production.

## Reviewer actions

```text
Approve
Edit and Approve
Reject
Needs Trainer Review
```

Reviewer can edit:

```text
question
options
final_correct_option
question_points
```

Always retain:

```text
AI original draft
AI suggested answer
human final answer
review decision
```

## Correct-answer rule

In AI DB:

```text
ai_suggested_correct_option = B
final_correct_option = NULL
```

After review:

```text
final_correct_option = B
question_points = 5
```

Production mapping:

```text
A → 0
B → 5
C → 0
D → 0
```

The correct InjazEdu option is the option with `points > 0`.

## Acceptance Criteria

No question can be published without human approval.

---

# Phase 10 — Prompt + Model Versioning

## Goal

Make every generation reproducible and traceable.

## Tables

```text
prompt_versions
model_profiles
model_runs
```

Each generated question stores:

```text
prompt_version_id
model_profile_id
model_name
generation_parameters
```

## Acceptance Criteria

For any generated question, the system can identify exactly which model and prompt produced it.

---

# Phase 11 — InjazEdu Internal API

## Goal

Connect the AI platform to the real application safely.

## Rule

FastAPI must not use production MySQL credentials.

## Initial APIs

```http
GET /internal/ai/courses/{id}
GET /internal/ai/books/{id}
GET /internal/ai/quizzes/{id}
```

Publish API later:

```http
POST /internal/ai/quizzes
```

Development authentication:

```text
API key
```

Production hardening later:

```text
HTTPS
API key
HMAC signature
timestamp
idempotency key
```

## Acceptance Criteria

AI can obtain required course/book information without direct MySQL access.

---

# Phase 12 — Publish to InjazEdu

## Goal

Convert approved AI drafts into the current InjazEdu quiz model.

## Flow

```text
Approved Quiz Draft
 → InjazEdu Internal API
 → Laravel validation
 → MySQL transaction
 → Quiz
 → Sections
 → Questions
 → Options
```

Mapping:

```text
final_correct_option → points = question_points
all other options    → points = 0
```

Laravel owns final production business rules.

## Acceptance Criteria

A reviewed AI quiz can be published and used normally inside InjazEdu.

---

# Phase 13 — Quiz Builder

## Goal

Move from five questions to complete quizzes.

Build:

```text
quiz_drafts
quiz_draft_questions
```

Initial controls:

```text
20–30 questions
topic/standard distribution
difficulty distribution
question-style distribution
```

Generate in small batches:

```text
5 + 5 + 5 + 5 + 5
```

Example blueprint:

```json
{
  "questions_count": 25,
  "difficulty": {
    "easy": 5,
    "medium": 15,
    "hard": 5
  }
}
```

## Acceptance Criteria

One complete 25-question quiz can be generated, reviewed, and published.

---

# Phase 14 — Duplicate Detection

## Goal

Reduce repeated questions.

Compare against:

```text
existing InjazEdu questions
book example questions
previous AI-generated questions
questions in the same generation job
```

Start with embedding similarity.

Flag possible duplicates for review.

Do not auto-delete or auto-reject initially.

## Acceptance Criteria

Reviewer can see likely duplicate candidates and similarity scores.

---

# Phase 15 — Evaluation

## Goal

Choose prompts and models using real reviewer data.

Track:

```text
approved_without_edit
approved_with_edit
rejected
wrong_answer
bad_distractors
not_grounded
duplicate
language_problem
```

Important metrics:

```text
approval rate
edit rate
rejection rate
answer correction rate
average generation time
```

Primary product metric:

```text
How many AI questions can trainers approve
without editing or with only minor editing?
```

## Acceptance Criteria

Prompt/model versions can be compared using human-review outcomes.

---

# Phase 16 — n8n + Telegram

## Goal

Automate only after generation and publishing are stable.

First workflow:

```text
Quiz Published
 → Webhook
 → n8n
 → Telegram notification
```

Start with:

```text
quiz title
question count
InjazEdu link
```

Do not begin by publishing all questions as Telegram polls.

## Acceptance Criteria

Publishing a quiz can automatically trigger a Telegram notification.

---

# Phase 17 — Scheduled Draft Generation

Only after generation quality is proven.

```text
n8n Schedule
 → POST /generation-jobs
 → AI creates drafts
 → Notify moderators
```

Important:

```text
Automation creates drafts only.
Never auto-publish AI-generated quizzes.
```

---

# Phase 18 — WhatsApp / Telegram Customer Support

Treat this as a later independent feature.

```text
Incoming message
 → n8n
 → Identify customer
 → Intent router
 → FAQ / Course / Subscription / Technical / Complaint
 → Injaz API or authorized RAG
 → Confidence/policy check
 → AI reply OR human handoff
```

Security rule:

```text
Authorization before retrieval
```

Paid course content must not be retrieved before checking user access.

---

# AI Control Center Pages

Use Filament for:

```text
Dashboard

Documents
Document Versions
Document Structure
Chunk Explorer

Retrieval Tester

Generation Jobs
Question Drafts

Models
Model Profiles
Prompt Versions

Evaluations
Duplicate Candidates

Integrations
n8n Status

Logs
Audit
Metrics
```

Do not rebuild the n8n visual editor inside Filament.

---

# Recommended FastAPI Structure

```text
app/
├── api/
├── domain/
│   ├── documents/
│   ├── generation/
│   ├── questions/
│   ├── quizzes/
│   └── reviews/
├── application/
│   ├── ingestion/
│   ├── retrieval/
│   ├── generation/
│   ├── validation/
│   └── publishing/
├── providers/
│   ├── llm/
│   │   ├── base.py
│   │   └── openai_compatible.py
│   ├── embeddings/
│   ├── document_parser/
│   └── storage/
├── infrastructure/
│   ├── database/
│   ├── queue/
│   └── config/
├── workers/
├── prompts/
└── tests/
```

Critical rule:

```text
Domain/application code must not import Ollama directly.
```

---

# How to Use Codex and Claude Code

Give agents **one bounded phase at a time**.

Do not say:

```text
Build the whole AI platform.
```

Say:

```text
Implement Phase 5 only.
```

Every agent task should contain:

```text
Context
Goal
Allowed scope
Non-goals
Requirements
Tests
Acceptance criteria
```

## Agent Step 1 — Inspect

Use:

```text
Inspect the repository for Phase X.

Do not modify files.

Return:
1. Relevant current architecture.
2. Files that need changes.
3. Risks/conflicts.
4. Proposed implementation.
5. Tests to add.

Stay strictly within Phase X.
```

## Agent Step 2 — Review the design

Before implementation verify:

- Scope was not widened.
- No direct Ollama coupling was added.
- No direct production MySQL write was introduced.
- Human review boundaries remain intact.
- Existing architecture is reused where sensible.

## Agent Step 3 — Implement

Use:

```text
Implement the approved Phase X design.

Requirements:
- Work test-first where practical.
- Keep changes bounded to Phase X.
- Do not add unrelated abstractions.
- Add/update tests.
- Run relevant tests.
- Report changed files, tests, and unresolved issues.
```

## Agent Step 4 — Independent review

Use the second agent:

```text
Review the Phase X implementation as a senior AI application engineer.

Focus on:
- correctness
- architecture boundaries
- security
- data integrity
- test coverage
- unnecessary complexity

Do not modify files.
```

Example workflow:

```text
Codex → implementation
Claude Code → review
```

or the reverse.

---

# Definition of Done Per Phase

A phase is complete only when:

- Implementation exists.
- Tests exist.
- Tests pass.
- Relevant configuration/docs are updated.
- No unrelated scope was added.
- Manual smoke test succeeds.
- Known limitations are documented.

Do not move forward merely because the code compiles.

---

# Learning Order

Learn concepts when the project needs them:

```text
Phase 1  → LLM APIs / OpenAI-compatible
Phase 3  → DOCX parsing
Phase 4  → Chunking
Phase 5  → Embeddings / pgvector / RAG
Phase 6  → Prompting / Structured Outputs
Phase 7  → Queues / AI jobs
Phase 8  → Grounding / Validation
Phase 9  → Human-in-the-loop
Phase 14 → Semantic similarity
Phase 15 → AI evaluation
Phase 16 → n8n automation
```

The project itself becomes the AI Application Engineering learning path.

---

# Milestones

```text
M1  Local infrastructure + Model Gateway
M2  DOCX → structure → chunks
M3  Embeddings + retrieval
M4  5 grounded MCQs from one topic
M5  Validation + human review
M6  25-question quiz draft
M7  Publish to InjazEdu
M8  Prompt/model evaluation
M9  Duplicate detection
M10 Telegram automation
M11 Scheduled draft generation
M12 Customer-support AI
```

Do not skip milestones.

---

# First Real Target

The first valuable working version is only:

```text
Upload one DOCX
 → Parse one standard/topic
 → Index the knowledge
 → Retrieve relevant chunks
 → Generate 5 MCQs
 → Show source evidence
 → Review them in Filament
```

Do not start with five quizzes per day, WhatsApp, agents, fine-tuning, or advanced automation.

Prove this vertical slice first.
