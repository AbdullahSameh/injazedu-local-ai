# Contract: Alert Messages (TG-M6)

**Status**: durable from TG-M6. This is the wording of everything the bot says in the alert group:
- the alerts;
- their edits;
- the button labels;
- the answers to presses.

All of it is **Arabic only** (FR-533). One Python module renders it, `app/application/moderation/
alert_render.py`. Rendering is pure: a function of the alert row, the subject's derived state, names and
the held text. It takes no clock reading. The times shown come from the rows.

---

## §1 — Format

- HTML `parse_mode`. Every interpolated value is HTML-escaped: group titles, names, the excerpt.
- Times are shown in `Asia/Riyadh` as `HH:MM`. A time on a different calendar day from the alert's firing is
  shown as `YYYY-MM-DD HH:MM`. Digits are Western.
- A rendered message is at most 1,000 characters. The excerpt is the only variable-length part, and the group
  title is cut at 80 characters.
- Lines appear in the order given below. A line whose value is absent is omitted, never left blank.

## §2 — The excerpt (FR-531, D-TG-221)

1. Take the anchor's **first-posted** text from its captured event (`messages.extract_text`).
2. Apply `text.normalize`, then `text.redact`. `redact` is defined over normalised text
   (moderation-text contract §3), so the excerpt shows the folded letters the model also sees
   (for example ة as ه). Implementation note, 2026-11-14. Links, emails, @handles and runs of 7+ digits become `«رابط»`, `«بريد»`,
   `«مستخدم»` and `«رقم»`.
3. Collapse whitespace. Cut at the last space at or before 100 characters, and append `…` when cut. With no
   space in range, cut at 100.
4. Render it as `«{excerpt}»` on its own line.
5. When the text is not held (`text_purged_at`, `payload_purged_at`), or the message is at least
   `MODERATION_TEXT_RETENTION_DAYS` old, render `النص لم يعد محفوظاً` instead, with no guillemets.
6. Media with no text renders no excerpt line.

## §3 — Durations

The age frozen at firing is rendered with Arabic number agreement:

| Range | Form | Example |
|---|---|---|
| under 1 min | `أقل من دقيقة` (implementation note, 2026-11-14) | |
| under 60 min | 1 → `دقيقة`, 2 → `دقيقتين`, 3–10 → `n دقائق`, 11+ → `n دقيقة` | `12 دقيقة` |
| 1 h to under 24 h | hours by the same rule (`ساعة`, `ساعتين`, `n ساعات`, `n ساعة`), then `و` and the minutes when not 0 | `ساعتين و5 دقائق` |
| 24 h and over | days (`يوم`, `يومين`, `n أيام`, `n يوماً`), then `و` and the hours when not 0 | `يومين و3 ساعات` |

## §4 — Alerts

**The header line**, by trigger:

| Trigger | Header |
|---|---|
| `question_waiting` | `⏳ سؤال ينتظر الرد` |
| `incident_flagged` | `🚨 رُصدت مخالفة` |
| `incident_unhandled` | `⚠️ مخالفة لم تُعالَج بعد` |
| `group_silent` | `🔇 لا نشاط مسجَّل في مجموعة` |
| `bot_not_admin` | `🛑 البوت لم يعد مشرفاً في مجموعة` |

A repeat (index k ≥ 1) appends ` · تذكير {k} من {max}` to the header.

**The body**:

```
المجموعة: {title}
── question ──
«{excerpt}»
سُئل الساعة {opened_at} · انتظر {age} عند التنبيه
── incident ──
الفئة: {category} · الخطورة: {severity}
«{excerpt}»
فُتحت بواسطة: {opener} · نُشرت {posted_at} · رُصدت {detected_at}
مضى على رصدها {age} عند التنبيه          (incident_unhandled only)
── group_silent ──
آخر نشاط مسجَّل: {last_event_at} · منذ {age} عند التنبيه
── bot_not_admin ──
حالة البوت: {status} منذ {bot_status_at}
── all ──
{responsible}
{links}
{status line, §6, on edits}
```

**`{responsible}`** comes from the assignee views. There is none for health alerts.
- `المسؤول: {mention} · {via}` when assigned. The via labels:
  - `بالرد` (reply);
  - `بالاستبعاد من اللوحة` (dismissal);
  - `بالتفاعل` (reaction);
  - `من التنبيه` (alert);
  - for incidents, the panel's Arabic for the evidence kind.
- Otherwise `الفريق: {mention}، {mention}` (the panel's `Team: :names`), naming the source group's current
  team.
- Otherwise `بلا فريق`.

`{mention}` is `<a href="tg://user?id={tg_user_id}">{display_name}</a>` (D-TG-225).

**`{links}`**:
- `🔗 <a href="{message_link}">الرسالة</a>` when T7 allows a link.
- Otherwise `(لا يمكن الربط برسالة في مجموعة عادية)`.

**Glossary.** The category, severity, opener and status words are the panel's Arabic, keyed by the panel's
English key and asserted equal to `lang/ar.json`:

| Value | English key | Arabic |
|---|---|---|
| categories | the codes (`SPAM_OR_AD`, …) | e.g. `رسائل مزعجة أو إعلان` |
| severities | `low` · `medium` · `high` | `منخفضة` · `متوسطة` · `عالية` |
| openers | `Link rule` · `Model` · `Operator` | `قاعدة الروابط` · `النموذج` · `مشغّل اللوحة` |
| bot status | `member` · `left` · `kicked` · `restricted` · `administrator` | `عضو` · `غادر` · `طُرد` · `مقيّد` · `مسؤول` (the panel's existing entries) |
| responsibility | `Team: :names` · `No team` · `Not taken by the team` · `via reply` · `via dismissal` · `via reaction` · `via alert` · `via a ban or restriction` · `via panel acknowledge` · `via panel resolve` · `via Not a violation` | the panel's entries; `via alert` → `من التنبيه` is new |
| actors | `Operator` · `anonymous administrator` | `مشغّل اللوحة` · `مسؤول مجهول الهوية` |

> **Implementation note (2026-11-14, T511/T513).** The glossary test makes the panel's Arabic win
> wherever this contract's first draft differed: the bot standings read `طُرد`, `مقيّد` and `مسؤول`
> (not `مطرود`, `مقيَّد`, `مشرف`), the dismissal "via" word is `بالاستبعاد`, and an anonymous actor is
> `مسؤول مجهول الهوية`. An ended subject that nobody on the team took reads `لم يتولّه أحد من
> الفريق`, as the panel's Assigned column does.

## §5 — Buttons and answers

**Keyboard rows.**
- Incident: `[✅ تمت المعالجة] [🚫 ليست مخالفة]`.
- Question: `[🙋 أتولّاه]`.
- Every alert, when `MODERATION_PANEL_BASE_URL` is set: a second row `[فتح في اللوحة]`, a URL button. If
  probe P2 shows the URL refused, it becomes the text link `🖥 <a href="…">فتح في اللوحة</a>` in `{links}`.

The panel URL is the incident's page, the queue, or the group's page. Pinned from `php artisan
route:list` on 2026-11-14: `/admin/incidents/{id}`, `/admin/live-attention-queue` (the queue has no
URL filter, so it opens unfiltered) and `/admin/telegram-chats/{id}/edit`.

Once the subject has ended, the whole keyboard is removed, the panel row included (§6).

**`callback_data`**: `a:{alert_id}:h` (Handled), `a:{alert_id}:f` (Not a violation), `a:{alert_id}:t` (I'm on it).

**Answers** (`answerCallbackQuery`, at most 200 characters, no `show_alert`):

| Outcome | Answer |
|---|---|
| `recorded`, Handled | `تم: عولجت المخالفة` |
| `recorded`, Not a violation | `تم: أُغلقت كرصد خاطئ` |
| `recorded`, take | `تم: السؤال لك` |
| `recorded_not_team` | `سُجّل. لست في فريق هذه المجموعة، فلا يُسند إليك` |
| `already_taken` | `سُجّل. يتولّاه {name}` |
| `already_ended` | `انتهى هذا البند: {status}` |
| `not_a_moderator` | `هذه الأزرار للمشرفين المعتمدين فقط` |
| `invalid` | `هذا الزر لم يعد صالحاً` |

## §6 — Status lines (edits)

The keyboard is removed whenever the subject has ended.

| Subject end | Line |
|---|---|
| item answered by a moderator | `✅ أُجيب عنه — {name} الساعة {at}` |
| item answered by a member | `✅ أجاب عنه عضو الساعة {at}` |
| item dismissed | `استُبعد — {name, or مشغّل اللوحة} الساعة {at}` |
| item expired | `انتهت مهلته الساعة {at} دون رد` |
| item taken, still open | `🙋 يتولّاه {name}` (keyboard kept) |
| incident resolved | `✅ عولجت — {actor} · {how} الساعة {at}` |
| incident not a violation | `🚫 ليست مخالفة — {actor} الساعة {at}` |
| group resumed | `عاد النشاط الساعة {at}` |
| bot standing changed | `تغيّرت حالة البوت الساعة {at}: {status}` (`مسؤول` when administrator again) |

`{how}` is one of:
- `بحظر العضو` (ban);
- `بطرده` (expulsion);
- `بتقييده` (restriction);
- `بتفاعل 👀`;
- `من اللوحة`;
- `من التنبيه`.

`{actor}` is one of:
- the moderator's name;
- `مشغّل اللوحة` for an unlinked panel user;
- `مسؤول مجهول الهوية` for an anonymous administrator (the panel's word).
- `مسؤول` for a group administrator who is not a declared moderator, never named (W4; the panel's word).
  Implementation note, 2026-11-14: a ban or restriction by such an administrator resolves an incident.

## §7 — Never

- **W1.** No deletion or removal word: not `حذف`, `حُذفت`, `أزال` or `إزالة`. The bot cannot see deletions
  (TG-M4 D-TG-126). `test_alert_render.py` asserts this over every template and every outcome.
- **W2.** No confidence, no percentage, no probability word (TG-M5 W1).
- **W3.** "Flagged", never "confirmed": no template says a violation was proven.
- **W4.** No student name, username or Telegram id. Only moderators are mentioned.
