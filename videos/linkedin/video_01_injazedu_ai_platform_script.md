# Video 01 — أنا ببني إيه بالضبط في InjazEdu؟

> **نوع الفيديو:** Build in Public / Project Introduction  
> **الهدف:** تعريف الناس بالمشروع الكبير، المسارين الرئيسيين، ما تم بناؤه بالفعل، ولماذا Telegram Moderation هو الأولوية الحالية.  
> **المدة المستهدفة:** 5:30 – 6:30 دقائق  
> **Format:** Face Camera + Screen Recording + Markdown Diagram + Project/Plan snippets  
> **مهم:** هذا ليس Tutorial في Ollama أو FastAPI أو Telegram Bot. الفكرة الأساسية هي **كيف تحولت مشكلة Business حقيقية إلى Platform لها مساران واضحان**.

---

# قبل التصوير — جهّز هذه الأشياء

لا تبدأ التسجيل قبل تجهيز هذه الـtabs/windows:

1. VS Code مفتوح على هذا الملف.
2. VS Code مفتوح على ملف الـMain Plan:
   - `final-injazedu-local-ai-code-agent-implementation-plan.md`
3. VS Code مفتوح على Telegram plan:
   - `telegram-moderation-intelligence.md`
4. Project repo مفتوح في VS Code.
5. Terminal جاهز لتنفيذ:
   - `make up`
   - أو command يوضح الـrunning containers بدون كشف أي credentials.
6. Browser مفتوح على:
   - Filament AI Control Center.
7. [ضع هنا Screenshot أو Screen Recording قصير للـInjazEdu dashboard أو صفحة Courses/Quizzes، بدون أي بيانات خاصة بالطلاب]
8. [ضع هنا Diagram المشروع الموجودة في قسم "Main Diagram" أدناه داخل ملف Markdown مستقل إذا أردت عرضها Full Screen]
9. تأكد أن أي:
   - API keys
   - tokens
   - customer/student data
   - `.env`
   - private Telegram group names
   غير ظاهرة في التسجيل.

---

# Main Diagram

استخدم هذه كـvisual الرئيسي في الفيديو.

```text
                          InjazEdu AI Platform
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
Foundation Gateway  Parser/Retrieval       Boundary   Ingestion   Groups/Owners
   ✅          ✅                                 │           │           │
                                                  └──────→ TG-M3
                                                         Response Tracking
                                                         ★ First usable slice
                                                              │
                                                              ├── TG-M4 Incidents
                                                              ├── TG-M5 AI Classification
                                                              ├── TG-M6 Alerts
                                                              ├── TG-M7 Dashboard
                                                              ├── TG-M8 Review/Reprocess
                                                              ├── TG-M9 n8n Digests
                                                              └── TG-M10 Hardening
```

> **ملاحظة أثناء التصوير:** لا تشرح كل Milestone هنا. استخدم الـDiagram كخريطة، وZoom على الجزء الذي تتكلم عنه فقط.

---

# السكربت الكامل

---

## 00:00 – 00:15 — Hook

### الصورة
**Face Camera — Full Screen**

### الكلام

أنا الفترة دي شغال على مشروع كنت في البداية بسميه **Local AI Lab لـInjazEdu**.

لكن وأنا براجع المشاكل الفعلية في المنصة، المشروع بدأ يتحول لحاجة أكبر شوية.

مش مجرد إنّي أشغّل Model Local وأوصله بالـplatform.

أنا فعليًا ببني Platform فيها أكتر من مسار، وكل مسار بيحل مشكلة Business مختلفة.

### على الشاشة

لا تعرض أي code حتى الآن.

ضع Text بسيط:

```text
Local AI Lab
↓
became
↓
InjazEdu AI Platform
```

---

## 00:15 – 00:38 — المشكلة الأصلية

### الصورة

[اعرض InjazEdu dashboard أو جزء عام من المنصة]

ثم:

[اعرض صفحة Quizzes أو Courses بدون بيانات مستخدمين حساسة]

### الكلام

InjazEdu منصة تعليمية شغالة بالفعل، وعندنا شغل حقيقي بيحصل يوميًا.

جزء من الشغل متعلق بالمحتوى والاختبارات.

عندنا كتب ومحتوى تدريبي، والأسئلة والـquizzes في أجزاء كبيرة منها بتحتاج شغل يدوي من الـtrainers والـmoderation team.

وفي نفس الوقت عندنا Telegram groups للطلاب، وفريق بيرد ويتابع المشاكل والأسئلة هناك.

فأنا قدامي مشكلتين مختلفتين تمامًا.

### On Screen

اعرض:

```text
Problem 1
Assessment Content

Books → Questions → Review → Quizzes
```

ثم:

```text
Problem 2
Telegram Moderation

Messages → Response → Follow-up → Measurement
```

---

## 00:38 – 01:05 — لماذا المشروع اتقسم لمسارين؟

### الصورة

[اعرض Main Diagram Full Screen]

### الكلام

وعشان كده قررت ما أحاولش أحشر كل حاجة تحت Feature واحدة اسمها AI.

قسمت المشروع لمسارين مستقلين.

الأول اسمه **Assessment Intelligence**.

وده خاص بالكتب، الـquestions، الـretrieval، الـAI-assisted answering والجeneration، وبعد كده review وpublish.

والمسار الثاني اسمه **Moderation Intelligence**.

وده خاص بمتابعة Telegram: الرسائل، الردود، مين المسؤول عن الـgroup، الـresponse time، الـincidents، والـalerts.

### الحركة على الشاشة

ابدأ بالـDiagram كاملة.

ثم Zoom على:

```text
Assessment Intelligence
```

ثم Zoom على:

```text
Moderation Intelligence
```

---

## 01:05 – 01:35 — نقطة مهمة: Shared Infrastructure، لكن Domain مختلف

### الصورة

[اعرض جزء من Folder Structure في VS Code]

ابحث وأظهر فقط بشكل واضح:

```text
apps/ai-api/
apps/ai-control/
infra/
```

ولو الـmoderation directories موجودة بالفعل وقت التصوير:

[اعرض `app/domain/moderation/` و `app/application/moderation/`]

ولو لم تُنفّذ بعد:

[اعرض Telegram plan section الخاص بالـBounded Context بدلًا من code]

### الكلام

المسارين مستقلين في الـbusiness logic، لكنهم بيستخدموا نفس الـinfrastructure الأساسية.

عندي FastAPI، PostgreSQL، Redis، Dramatiq، Laravel مع Filament، والـModel Gateway.

الفكرة هنا مش إني أعمل مشروع جديد لكل مشكلة.

لكن في نفس الوقت مش عايز Assessment code يبدأ يدخل في Moderation code والعكس.

فالـinfrastructure مشتركة، والـdomain boundaries واضحة.

### على الشاشة

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

## 01:35 – 02:05 — ماذا أنجزت في Local AI حتى الآن؟

### الصورة

[اعرض الـMain Plan عند Milestones M0 وM1]

ابحث داخل:

`final-injazedu-local-ai-code-agent-implementation-plan.md`

واعرض فقط الصفوف أو الجزء الخاص بـ:

```text
M0 Foundation
M1 Model Gateway
```

### الكلام

في مسار الـAssessment، أنا خلصت لحد دلوقتي أول Milestoneين.

**M0 كان Foundation.**

يعني قبل ما أعمل أي RAG أو generation، جهزت البيئة اللي باقي النظام هيعتمد عليها.

وبعده **M1 كان Model Gateway**.

وده بالنسبة لي كان قرار مهم جدًا من البداية.

### Screen instruction

[Zoom على M0]

ثم:

[Zoom على M1]

---

## 02:05 – 02:40 — Show the Foundation

### الصورة

[اعرض Terminal]

شغّل الأمر الذي تستخدمه فعليًا لتشغيل المشروع.

مثال:

```bash
make up
```

ثم:

[اعرض الـcontainers وهي Running]

ثم:

[افتح Filament AI Control Center في Browser]

### الكلام

الـFoundation عندي فيها FastAPI للـAI services، PostgreSQL ومعاه pgvector، Redis، worker، وLaravel + Filament كـControl Center.

وOllama شغال Local على الجهاز.

لكن بالنسبة لي النقطة المهمة هنا مش أسماء الـtools.

النقطة إن كل حاجة لها responsibility واضحة، عشان لما أبدأ أضيف Features بعد كده ما يبقاش عندي script كبير مربوط ببعضه.

### Important

لا تدخل في شرح:
- Docker installation.
- ما هو Redis.
- ما هو pgvector.

هذه Topics لفيديوهات أخرى عند الحاجة.

---

## 02:40 – 03:12 — M1: لماذا Model Gateway؟

### الصورة

[اعرض الـMain Plan عند M1 أو الكود الفعلي للـModel Gateway]

إذا كان مناسبًا:

[اعرض interface/protocol مثل `LLMProvider` أو `EmbeddingProvider`]

ثم:

[اعرض `OpenAICompatible...Provider` بدون الدخول في implementation details]

### الكلام

بعد كده M1 كان الـModel Gateway.

أنا شغال دلوقتي بـOllama.

لكن مش عايز الـbusiness logic يبقى مكتوب على أساس إن Ollama هو الشيء الوحيد اللي هيعيش مع المشروع للأبد.

فباقي السيستم بيتعامل مع interface واحدة.

دلوقتي وراها Ollama.

لو بعدين نقلت لـvLLM أو provider متوافق مع OpenAI API، المفروض التغيير يحصل في الـprovider layer، مش في كل الـapplication.

### على الشاشة

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

## 03:12 – 03:30 — لماذا لم أكمل Assessment الآن؟

### الصورة

ارجع إلى الـMain Diagram.

Dim أو تجاهل Assessment milestones بعد M1.

Highlight:

```text
Moderation Intelligence
```

### الكلام

المفروض طبيعي بعد M1 أبدأ M2 في الـAssessment: documents والـparser.

لكن هنا الأولوية عندي اتغيرت مؤقتًا.

لأن مشكلة Telegram دلوقتي أهم تشغيليًا بالنسبة لي، وعايز أوصل منها لأول usable version قبل ما أرجع أكمل الـAssessment track.

---

## 03:30 – 04:00 — Telegram business problem

### الصورة

**Face bubble + Markdown scenario Full Screen**

اعرض:

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

## 04:00 – 04:35 — لماذا Telegram يبدأ بدون AI؟

### الصورة

[اعرض Telegram plan عند First Vertical Slice]

افتح:

`telegram-moderation-intelligence.md`

واعرض الجزء:

```text
TG-M0 → TG-M1 → TG-M2 → TG-M3
```

ثم الجزء الذي يوضح:

```text
AI-free
```

### الكلام

والحاجة اللي يمكن تبدو غريبة إن أول جزء من Telegram Moderation **مش محتاج AI أصلًا**.

أنا محتاج أعرف:

مين أرسل الرسالة.

إمتى اتبعتت.

مين رد.

الرد حصل بعد كام دقيقة.

ومين كان مسؤول في الوقت ده.

دي كلها deterministic facts.

لو دخلت LLM من أول خطوة، هبقى بحاول أdebug system deterministic وsystem probabilistic في نفس الوقت.

وده بالنسبة لي تعقيد من غير قيمة.

### On Screen

```text
First prove:

Capture
→ Attribution
→ Correlation
→ Response Time

Then add AI.
```

---

## 04:35 – 05:10 — Telegram Roadmap الحالية

### الصورة

[اعرض Main Diagram]

Highlight بالترتيب أثناء الكلام:

```text
TG-M0
TG-M1
TG-M2
TG-M3
```

### الكلام

فالتركيز الحالي عندي هو أول vertical slice فقط.

**TG-M0:** أعمل Domain Boundary والـguardrails.

**TG-M1:** أخلي Telegram updates تدخل وتتخزن reliably.

**TG-M2:** أحول الـraw events لـmessages وأحدد الـgroups والـmoderators ومين مسؤول عن إيه وفي أي وقت.

وبعدين **TG-M3**، ودي أول نقطة أعتبر عندها إن فيه Feature حقيقية usable.

رسالة محتاجة رد تدخل.

تتحول لـattention item.

الـmoderator يرد.

والسيستم يحسب الـFirst Response Time ويعرضه في Filament.

### على الشاشة

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

## 05:10 – 05:32 — أين يدخل الـAI فعلًا؟

### الصورة

Highlight:

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

## 05:32 – 05:55 — كيف يتم تنفيذ كل Milestone؟

### الصورة

[اعرض Spec-Kit folder أو specs folder]

[اعرض spec حقيقي لـTG-M0 أو الـmilestone الحالي]

لو عندك الملفات:

```text
spec.md
plan.md
tasks.md
```

اعرض أسماء الملفات أولًا، ثم افتح جزء صغير من `spec.md`.

### الكلام

وأنا مش ببني الـmilestones دي بأنّي أفتح AI coding agent وأقوله:

"ابني Telegram Moderation System."

كل Milestone بتحول عندي لـSpec منفصل باستخدام Spec-Kit.

بحدد الـscope، الـnon-goals، الـrequirements، الاختبارات والـacceptance criteria.

وبراجع الـspec الأول.

بعدها التنفيذ.

وبعد التنفيذ فيه review وsmoke test قبل ما أعتبر الـmilestone خلص.

### On Screen

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

## 05:55 – 06:15 — ماذا سنرى في الفيديوهات القادمة؟

### الصورة

Face Camera أو Face Bubble مع Main Diagram.

### الكلام

فالفيديوهات الجاية مش هتكون كورس FastAPI أو Telegram Bot tutorial.

هحاول أخلي كل فيديو حوالين قرار أو مشكلة حقيقية وأنا ببني المشروع.

زي:

ليه اخترت Long Polling بدل Webhook؟

إزاي أتأكد إني ما بضيعش Telegram updates؟

ليه مسؤولية الـmoderator لازم تتخزن بتاريخها؟

وإزاي أحسب First Response Time بشكل أقدر أثق فيه فعلًا؟

---

## 06:15 – 06:28 — Ending

### الصورة

**Face Camera**

### الكلام

ودلوقتي تركيزي هو إني أوصل من TG-M0 لـTG-M3.

أول ما الـvertical slice دي تشتغل end-to-end، هتبقى أول نتيجة حقيقية في Telegram track.

ومن هنا هنبدأ نشوف هل الـAI فعلًا هيحسن السيستم، ولا لأ.

---

# نهاية الفيديو

لا تستخدم CTA من نوع:

> اعمل Follow عشان تشوف الجزء الجاي.

إذا أردت CTA، استخدم CTA هادئًا مثل:

> لو بتبني system مشابه وواجهت مشكلة في قياس response time أو Telegram events، مهتم أعرف إنت حليتها إزاي.

أو لا تستخدم CTA نهائيًا في الفيديو الأول.

---

# B-Roll / Screen Recording Checklist

سجل هذه المقاطع منفصلة قبل أو بعد تصوير الكلام:

- [ ] InjazEdu dashboard — لقطة عامة آمنة.
- [ ] Page of Quizzes أو Courses.
- [ ] Main Diagram كاملة.
- [ ] Main Diagram مع Highlight على Assessment.
- [ ] Main Diagram مع Highlight على Moderation.
- [ ] Main Plan → M0 / M1.
- [ ] Terminal → `make up`.
- [ ] Running services/containers.
- [ ] Filament AI Control Center.
- [ ] Model Gateway interface/protocol.
- [ ] Telegram Plan → First Vertical Slice.
- [ ] Telegram Plan → TG-M0…TG-M3.
- [ ] Telegram Plan → TG-M5 AI Classification.
- [ ] Spec-Kit folder.
- [ ] spec.md / plan.md / tasks.md.
- [ ] أي smoke test موجود بالفعل ومرتبط بما تم تنفيذه فقط.

---

# أماكن تحتاج Content منك قبل التصوير

هذه الأشياء لا أريد افتراضها، لذلك أكملها أنت قبل التسجيل:

## 1. لقطة InjazEdu

[ضع هنا اسم الصفحة الآمنة التي ستعرضها من InjazEdu]

مثال:

```text
Courses index
```

أو:

```text
Quiz dashboard
```

---

## 2. Current Telegram Milestone

[ضع هنا الـMilestone الذي وصلت إليه يوم التصوير فعلًا]

```text
Current: TG-M?
Status:
```

**مهم:** لو وقت التصوير أصبحت مثلًا في TG-M1، عدل جملة "تركيزي هو TG-M0 → TG-M3" إلى:

> "أنا حاليًا في TG-M1، والهدف القريب هو الوصول لـTG-M3."

---

## 3. Spec الذي ستعرضه

[ضع هنا path للـSpec الحقيقي الذي ستفتحه أثناء الفيديو]

```text
specs/_______________________/
```

واعرض فقط:
- Goal
- Scope
- Acceptance Criteria
- Non-goals

لا تعرض الملف بالكامل.

---

## 4. Code Snippet للـModel Gateway

[ضع هنا path لأفضل ملف صغير يوضح الـinterface بدون تفاصيل كثيرة]

```text
apps/ai-api/_______________________
```

يفضل أن يحتوي على شيء شبيه بـ:

```python
class LLMProvider(...):
    ...

class EmbeddingProvider(...):
    ...
```

---

## 5. Filament Screen

[ضع هنا اسم الصفحة التي ستعرضها]

```text
AI Control Center → __________________
```

إذا لم توجد Dashboard مفيدة حاليًا، افتح `Model Profiles` بدل اختراع UI غير موجودة.

---

# ممنوع إظهاره أثناء التسجيل

- `.env`
- Telegram bot tokens
- API keys
- الطلاب أو أرقامهم أو usernames الحقيقية
- private group links
- customer/student messages الحقيقية بدون anonymization
- production DB credentials
- internal security findings
- أي code أو configuration يكشف secrets
- unreleased sensitive business data

---

# Editing Notes

## Style

الفيديو يجب أن يشعر كأن المشاهد **يمشي معك داخل المشروع**، وليس كأنه يشاهد Lecture.

استخدم:
- Cuts بسيطة.
- Zoom عند السطر الذي تتكلم عنه.
- Highlight محدود.
- Text labels قليلة.
- لا تملأ الشاشة بـanimations.

## Face Bubble

استخدم Face Bubble أثناء:
- Architecture.
- Plans/specs.
- Browser demos.

اخفِها مؤقتًا إذا كانت تغطي code أو diagram مهمة.

## Code

لا تعرض أكثر من 8–15 سطرًا في نفس اللحظة.

إذا كان الملف كبيرًا:
- Zoom.
- Collapse unrelated code.
- Highlight الجزء المقصود.

---

# الرسالة الأساسية التي يجب أن يخرج بها المشاهد

إذا شاهد شخص الفيديو ونسي كل التفاصيل، أريده أن يتذكر هذا:

> أنا لا أبني AI demo.
>
> عندي منصة حقيقية ومشكلتان حقيقيتان.
>
> بنيت Foundation وModel Gateway أولًا.
>
> الآن الأولوية هي Telegram Moderation.
>
> وسأثبت الـdeterministic system أولًا قبل إدخال AI في المكان الذي يحتاج فعلًا إلى فهم semantics.

---

# مواضيع الفيديوهات التي يفتحها هذا الفيديو طبيعيًا

لا تقلها كلها كـCTA؛ هذه فقط continuity للسلسلة:

1. لماذا الـLocal AI project بدأ بـFoundation بدل RAG؟
2. لماذا لا يتعامل الـbusiness code مع Ollama مباشرة؟
3. لماذا Telegram Moderation يبدأ بدون AI؟
4. Spec-Kit: كيف أقسم Feature كبيرة إلى Milestones قابلة للمراجعة؟
5. لماذا Long Polling بدل Webhook؟
6. كيف أمنع Telegram update من أن يتسجل مرتين؟
7. لماذا أحتاج Dev Bot وLive Bot؟
8. كيف أخزن من كان مسؤولًا عن Group في وقت سابق؟
9. كيف تتحول رسالة إلى Attention Item؟
10. كيف أقيس First Response Time؟
11. متى يدخل AI Classification؟
