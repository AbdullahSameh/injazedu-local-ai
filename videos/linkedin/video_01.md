
##  المشكلة الأصلية


```text
Problem 1
Assessment Content

Books → Questions → Review → Quizzes
```


```text
Problem 2
Telegram Moderation

Messages → Response → Follow-up → Measurement
```

---

# Main Plan

1. Main Plan:
   - `final-injazedu-local-ai-code-agent-implementation-plan.md`
   - وده خاص بالكتب، الـ questions، الـ retrieval، الـ AI-assisted answering والج eneration، وبعد كده review و publish.

2. Telegram plan:
   - `telegram-moderation-intelligence.md`
   - وده خاص بمتابعة Telegram: الرسائل، الردود، مين المسؤول عن الـ group، الـ response time، الـ incidents، والـ alerts.


# Main Diagram

استخدم هذه كـvisual الرئيسي في الفيديو.

```text
                          Injaz AI Platform
                                   │
             ┌─────────────────────┴─────────────────────┐
             │                                           │
             │                                           │
   Assessment Intelligence                    Moderation Intelligence
      (Local AI for content)                   (Telegram Moderation)
             │                                           │
   ┌─────────┼─────────┐                     ┌───────────┼───────────┐
   │         │         │                     │           │           │
 M0        M1       Next مراحل             TG-M0      TG-M1       TG-M2
Foundation Gateway  Parser/Retrieval     Foundation   Event Ingestion   Groups/Owners
   ✅          ✅                                 │           │           │
                                                  └──────→ TG-M3
                                                         Response Tracking
                                                         ★ First usable slice
                                                              │
                                                              ├── TG-M4 Policy Incidents
                                                              ├── TG-M5 AI Classification
                                                              ├── TG-M6 Alerts
                                                              ├── TG-M7 Dashboard
                                                              ├── TG-M8 Review/Reprocess
                                                              ├── TG-M9 n8n Digests
                                                              └── TG-M10 Hardening
```

---

##  Shared Infrastructure، لكن Domain مختلف



```text
apps/ai-api/
apps/ai-control/
infra/
```

### This Means

المسارين مستقلين في الـbusiness logic، لكنهم بيستخدموا نفس الـinfrastructure الأساسية.

عندي FastAPI، PostgreSQL، Redis، Dramatiq، Laravel مع Filament، والـModel Gateway.

الفكرة هنا مش إني أعمل مشروع جديد لكل مشكلة.

لكن في نفس الوقت مش عايز Assessment code يبدأ يدخل في Moderation code والعكس.

فالـinfrastructure مشتركة، والـdomain boundaries واضحة.

### Structure

```text
Shared:
FastAPI
PostgreSQL
Redis
Dramatiq
Filament
Model Gateway

Separate:
Assessment Domain
Moderation Domain
```

---

## What have done

Assessment:

`final-injazedu-local-ai-code-agent-implementation-plan.md`


```text
M0 Foundation
M1 Model Gateway
```

## Foundation

### runbooks

[ Terminal ]

`docs/runbooks/m0-foundation.md`

مثال:

```bash
make up
```

ثم:

[containers وهي Running]

ثم:

[ Filament AI Control Center في Browser]

### الكلام

الـFoundation عندي فيها FastAPI للـAI services، PostgreSQL ومعاه pgvector، Redis، worker، وLaravel + Filament كـControl Center.

وOllama شغال Local على الجهاز.

## Model Gateway:


بعد كده M1 كان الـModel Gateway.

أنا شغال دلوقتي بـOllama.

لكن مش عايز الـbusiness logic يبقى مكتوب على أساس إن Ollama هو الشيء الوحيد اللي هيعيش مع المشروع للأبد.

فباقي السيستم بيتعامل مع interface واحدة.

دلوقتي وراها Ollama.

لو بعدين نقلت لـvLLM أو provider متوافق مع OpenAI API، المفروض التغيير يحصل في الـprovider layer، مش في كل الـapplication.

### Model Provider

```text
Business Logic
      ↓
 Model Gateway
      ↓
OpenAI-Compatible Provider
      ↓
    Ollama

Later:

      ↓
     vLLM
```


---

## Telegram business problem

example:

```text
10:03
Student:
"الكتاب مش ظاهر عندي"

        ↓

10:11
Moderator:
"تم، جرّب دلوقتي"
```

### الكلام

السؤال اللي خلاني أبدأ المسار ده بسيط جدًا.

لو طالب كتب الساعة 10:03:

"الكتاب مش ظاهر عندي"

والـmoderator رد عليه الساعة 10:11...

هل أقدر أقول بثقة إن الـFirst Response Time كان 8 دقايق؟

طيب مين كان الـmoderator المسؤول عن الـgroup وقت الرسالة؟

وإيه الرسائل اللي أصلًا كان المفروض حد يرد عليها وماحدش رد؟

دلوقتي ما عنديش system يجاوب الأسئلة دي بشكل reliable.

---

##  لماذا Telegram يبدأ بدون AI؟


والحاجة اللي يمكن تبدو غريبة إن أول جزء من Telegram Moderation **مش محتاج AI أصلًا**.

أنا محتاج أعرف:

مين أرسل الرسالة.

إمتى اتبعتت.

مين رد.

الرد حصل بعد كام دقيقة.

ومين كان مسؤول في الوقت ده.

دي كلها deterministic facts.

لو دخلت LLM من أول خطوة، هبقى بحاول أعمل debug system deterministic و system probabilistic في نفس الوقت.

وده بالنسبة لي تعقيد من غير قيمة.

### flow

```text
First prove:

Capture
→ Attribution
→ Correlation
→ Response Time

Then add AI.
```

---

## Telegram Roadmap 


[ Main Diagram]

- will use Telegram Bot


فالتركيز الحالي عندي هو أول vertical slice فقط.

**TG-M0:** أعمل Foundation.

**TG-M1:** أخلي Telegram updates تدخل وتتخزن (Event Ingestion).

**TG-M2:** أحول الـraw events لـmessages وأحدد الـgroups والـmoderators ومين مسؤول عن إيه وفي أي وقت.

وبعدين **TG-M3**، ودي أول نقطة أعتبر عندها إن فيه Feature حقيقية usable.

رسالة محتاجة رد تدخل.

تتحول لـattention item.

الـmoderator يرد.

والسيستم يحسب الـFirst Response Time ويعرضه في Filament.

### Message Flow

```text
Telegram Group
      ↓
Event Ingestion
      ↓
Message
      ↓
Responsible Moderator
      ↓
Attention Item
      ↓
Moderator Response
      ↓
First Response Time
```

---

##  أين يدخل الـAI فعلًا؟

### الصورة



```text
TG-M5 AI Classification
```

### الكلام

بعد ما أثبت إن الـmeasurement نفسه صح، ساعتها الـAI يبدأ يبقى له معنى.

مثلًا:

هل الرسالة دي Question؟

Complaint؟

Spam أو Ad؟

هل محتاجة Response؟

هل محتاجة Moderation؟

هنا الـmodel عنده قيمة فعلية، لأننا دخلنا في فهم معنى الرسالة، مش مجرد حساب timestamps.

### على الشاشة

```text
Deterministic first
        ↓
Reliable baseline
        ↓
TG-M5
AI Classification
```

---

##  كيف يتم تنفيذ كل Milestone؟


[ Spec-Kit folder أو specs folder]

لو عندك الملفات:

```text
spec.md
plan.md
tasks.md
```

اعرض أسماء الملفات أولًا، ثم افتح جزء ص

وأنا مش ببني الـmilestones دي بأنّي أفتح AI coding agent وأقوله:

"ابني Telegram Moderation System."

كل Milestone بتحول عندي لـSpec منفصل باستخدام Spec-Kit.

بحدد الـscope، الـnon-goals، الـrequirements، الاختبارات والـacceptance criteria.

وبراجع الـspec الأول.

### Spec Flow

```text
Milestone
   ↓
Spec
   ↓
Review
   ↓
Tasks
   ↓
Implementation
   ↓
Independent Review
   ↓
Smoke Test
```

---

## next steps


ودلوقتي تركيزي هو إني أوصل من TG-M0 لـTG-M3.

ليه اخترت Long Polling بدل Webhook؟

إزاي أتأكد إني ما بضيعش Telegram updates؟

ليه مسؤولية الـmoderator لازم تتخزن بتاريخها؟

وإزاي أحسب First Response Time بشكل أقدر أثق فيه فعلًا؟

---

## Tell me your opinion.