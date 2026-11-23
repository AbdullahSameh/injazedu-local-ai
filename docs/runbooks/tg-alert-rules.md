# Alert rules: a guide for the operator (TG-M6)

This guide explains what an alert rule is, how to create one, what each of the five triggers watches, and
what every option on the form does. The binding rules are in `specs/013-tg-m6-alerts/contracts/alerting.md`
(§2 rules, §3 firing). The bot's exact Arabic wording is in `contracts/alert-messages.md`. Panel labels are
given in English and in the Arabic the panel shows.

---

## 1. What a rule is

A rule says: **"when this happens in the student groups, tell the moderators' group."**

- Rules are data that you create. Nothing alerts until a rule exists and is enabled. No threshold is
  built into the code.
- About every 30 seconds (`MODERATION_TICK_INTERVAL_S`), the system checks every enabled rule. Anything
  that newly qualifies gets **one** alert message in the alert group.
- An alert is sent once per rule and subject. A "subject" is one question, one incident or one group. The
  only further messages are the reminders you ask for (§5.4).
- When the subject ends, the bot **edits** the alert to say how it ended and removes its buttons. It
  does not send a new message.
- Alerts never change anything. Only a button press does, and a press is recorded exactly like the same
  act in the panel.

For a message to arrive, all four must hold:
1. a destination is designated;
2. the rule is enabled;
3. `ai-telegram` is running, because it drives the tick;
4. the moment the subject qualified is **after** the rule was switched on (§5.6).

## 2. Creating a rule

Panel → **Alert Rules** (قواعد التنبيه) → **New**. The form has three sections and a switch:

| Section | Fields | Shown for |
|---|---|---|
| **What it watches** (ما الذي تراقبه) | Trigger (المُشغِّل), Group (المجموعة), Threshold (الحدّ بالدقائق) | every trigger; Threshold only for three of them |
| **Which incidents** (أي المخالفات) | Lowest severity, Categories, Opened by | the two incident triggers only |
| **Repeats and quiet hours** (التكرار وساعات الهدوء) | Repeat every, Number of repeats, Quiet hours | every trigger |
| **Enabled** (مفعّلة) | on / off | every trigger |

Choose the trigger first, because the form shows only the fields that trigger accepts. **The trigger and
the group cannot be changed after the rule is created.** To change either, disable the rule and create a
new one.

## 3. The five triggers at a glance

| Trigger | Arabic in panel | Watches | Needs threshold | Filters | Buttons on the alert |
|---|---|---|---|---|---|
| Question waiting | سؤال ينتظر الرد | a student question nobody has answered | yes | no | 🙋 أتولّاه |
| Incident flagged | رُصدت مخالفة | a new possible violation | no | yes | ✅ تمت المعالجة · 🚫 ليست مخالفة |
| Incident unhandled | مخالفة لم تُعالَج | a violation still not handled after a while | yes | yes | ✅ تمت المعالجة · 🚫 ليست مخالفة |
| Group silent | مجموعة بلا نشاط | a group where nothing has been recorded for a while | yes | no | none |
| Bot not administrator | البوت ليس مسؤولاً | the bot losing administrator standing in a group | no | no | none |

When `MODERATION_PANEL_BASE_URL` is set, every alert also has a **فتح في اللوحة** button. It opens the
incident's page, the Live Attention Queue, or the group's page.

## 4. Each trigger in detail

### 4.1 Question waiting (سؤال ينتظر الرد): ⏳ سؤال ينتظر الرد

- **What it is for.** It stops a student's question from sitting unanswered. It is the alert version of the
  Live Attention Queue.
- **Watches.** Open items in the Live Attention Queue, which are the questions the rules opened in a
  measured group.
- **Fires when.** The question has waited at least the **threshold** and is still open: not answered, not
  dismissed and not expired.
- **The message.** The group, a short excerpt of the question (links, phones and @handles hidden), when it
  was asked and how long it had waited, the group's team (or who took it), and a link to the message.
- **🙋 أتولّاه.** It means "I'm on it". The question becomes yours, as if you had replied or reacted, but
  it stays open. The alert changes to `🙋 يتولّاه {name}` and the button stays.
  - A moderator who is not on that group's team is recorded but not assigned.
  - A second moderator after you is told who has it.
- **The alert ends** (it is edited and the buttons are removed) when someone answers, a panel user
  dismisses the question, or it expires.
- **Limit.** A question expires after `MODERATION_ITEM_MAX_AGE_S`, which is 24 hours today. A threshold of
  24 hours or more can therefore never fire.
- **Today.** The production attention queue is paused, so add question rules when it restarts.

### 4.2 Incident flagged (رُصدت مخالفة): 🚨 رُصدت مخالفة

- **What it is for.** Moderators hear about a possible violation **as soon as** it is flagged, without
  watching the panel.
- **Watches.** New incidents. An incident is a message flagged by the link rule, by the model or by a
  panel user.
- **Fires when.** On the next tick after the incident is flagged, if it is still open or only acknowledged
  and it matches the filters (§5.3). There is no threshold.
- **The message.** The group, the category and severity, an excerpt, who flagged it (قاعدة الروابط،
  النموذج، مشغّل اللوحة), when the message was posted and when it was flagged, the team, and the link.
- **✅ تمت المعالجة (Handled).** Resolves the incident under your name, exactly like **Resolve** in the
  panel. The incident page reads "Resolved (alert)".
- **🚫 ليست مخالفة (Not a violation).** Closes it as a false positive, exactly like the panel's **Not a
  violation**. Use it only when the flag was wrong: it is counted as a false positive in the incident and
  accuracy figures.
- **The alert ends** when the incident is resolved or closed by any route: these buttons, the panel, a
  👀 reaction, or a ban, restriction or removal in the group.

### 4.3 Incident unhandled (مخالفة لم تُعالَج): ⚠️ مخالفة لم تُعالَج بعد

- **What it is for.** Escalation. Nobody dealt with a flagged violation in time.
- **Fires when.** The incident has been flagged for at least the **threshold** and is still open or only
  **acknowledged**. "Acknowledged" means someone saw it (for example a reaction other than 👀, or the
  panel's Acknowledge) but did not resolve it, so it still counts as unhandled.
- **The message** is the same as 4.2, plus `مضى على رصدها {age} عند التنبيه`. The buttons and the ending are
  the same as 4.2.
- **Using 4.2 and 4.3 together.** "Flagged" tells the team at once and "unhandled" is the reminder. To
  have only the escalation, create "unhandled" alone.

### 4.4 Group silent (مجموعة بلا نشاط): 🔇 لا نشاط مسجَّل في مجموعة

- **What it is for.** It catches a group the system has **stopped seeing**: the bot removed, Telegram
  delivery broken, or the poller down for that group. A quiet group also looks like this.
- **Watches.** Each measured group's last recorded event of any kind: a message, an edit, a reaction or a
  join.
- **Fires when.** Nothing has been recorded for at least the **threshold**. It fires once per silence.
- **The alert ends** with `عاد النشاط الساعة {at}` as soon as anything is recorded again. A later silence
  is a new alert.
- **No buttons.** There is nothing to take or resolve. Check the group, or run `make tg-doctor`.
- **Choosing the threshold.** Groups are naturally quiet at night. Use a long threshold (hours), quiet
  hours, or both. After an outage of the system itself, this may fire for groups that were simply not
  observed (contract L2).

### 4.5 Bot not administrator (البوت ليس مسؤولاً): 🛑 البوت لم يعد مشرفاً في مجموعة

- **What it is for.** The bot needs administrator standing in a measured group to see every message
  (`tg-operator-prerequisites.md` §B). Without it, that group's figures quietly become incomplete.
- **Fires when.** The bot's recorded standing in a measured group changes to anything other than
  administrator: member, restricted, left or kicked. It fires once per change. "Unknown" never alerts.
- **The message.** The group and `حالة البوت: {status} منذ {time}`.
- **The alert ends** when the standing changes again: `تغيّرت حالة البوت الساعة {at}: مسؤول` once the bot
  is administrator again.
- **No threshold and no buttons.** Fix it by promoting the bot again in that group.

## 5. The options

### 5.1 Group (المجموعة): all groups or one group

- Leave it empty for **All groups** (كل المجموعات), or choose one **measured** group. Only monitored
  groups are offered, never the alert group.
- **A group's own rule replaces the all-groups rule for that group.** For example, an all-groups rule
  "Question waiting, 15 min" plus a rule for group X "Question waiting, 60 min" means X waits 60 minutes
  and every other group 15.
- **A disabled group rule mutes the trigger for that group.** To stop one group's alerts, create its own
  rule for that trigger and leave it disabled.
- There can be one all-groups rule per trigger and one rule per trigger per group. The form refuses a
  second one and asks you to edit the existing rule.

### 5.2 Threshold (الحدّ، بالدقائق)

- **Required** for Question waiting, Incident unhandled and Group silent. **Not accepted** for the other
  two, which fire on the event itself.
- It is entered in whole minutes, at least 1. The table shows it as "15 min" or "2 h".
- **What it measures:**
  - Question waiting: time since the question was asked.
  - Incident unhandled: time since it was flagged.
  - Group silent: time since the last recorded event.

### 5.3 Which incidents (the incident triggers only)

Leaving a filter empty means **any**. With several filters set, an incident must match all of them.

| Filter | Arabic | Values | Matches |
|---|---|---|---|
| Lowest severity | أدنى خطورة | Low · Medium · High | that severity **or higher**. "Medium" matches medium and high. |
| Categories | الفئات | Spam or ad (رسائل مزعجة أو إعلان) · Abuse (إساءة) · Other (أخرى) | any one of the ticked categories |
| Opened by | فُتح بواسطة | Link rule (قاعدة الروابط) · Model (النموذج) · Operator (مشغّل اللوحة) | incidents flagged by the ticked source |

Two examples:
- "Opened by: Link rule" alerts only on links posted by students and ignores the model's guesses.
- "Lowest severity: High" plus "Categories: Abuse" alerts only on serious abuse.

### 5.4 Repeats: Repeat every and Number of repeats (التكرار كل · عدد التكرارات)

- **Set both or neither.** With neither, there is one alert and no reminders.
- With both, a reminder goes out every *interval* after the first alert, up to *number* reminders, **only
  while the subject still qualifies**. The first answer or resolution stops them.
- Each reminder is a **new message** with its own buttons. Its header ends with ` · تذكير {k} من {max}`.
- **Example.** "Incident unhandled, 30 min" with "every 20 min, 2 repeats": the first alert at 30 min,
  reminder 1 at 50 min, reminder 2 at 70 min, then nothing more.
- A reminder that could not be sent at its time is **never sent late**. If the system was down, it skips
  to the current one and does not post a burst.
- Health triggers can repeat too, for example a reminder while a group stays silent.

### 5.5 Quiet hours (ساعات الهدوء)

- These are windows **in Riyadh time** (`HH:MM` to `HH:MM`) during which this rule sends nothing. Add one
  with **Add a quiet-hours window** (أضف فترة هدوء).
- A window whose end is before its start **crosses midnight**: `23:00 → 07:00` is the night. Start and
  end cannot be equal.
- **Suppressed means never sent, not delayed.** An alert due inside a window is recorded on the Alerts page
  as **مكتوم (ساعات الهدوء)** and is not posted when the window ends.
- **Reminders keep counting through quiet hours.** A reminder due after the window ends *is* sent. If
  you want a night-time question to reach the team in the morning, give the rule enough reminders to
  reach past the window.
  - Reminders are counted from the first alert's time. A first alert suppressed at 23:30 with "every
    60 min, 3 repeats" has reminders at 00:30, 01:30 and 02:30, all inside the window, so nothing arrives.
  - "Every 60 min, 9 repeats" would send the 07:30 reminder.
- Quiet hours belong to each rule. Different triggers can keep different hours.

### 5.6 Enabled (مفعّلة)

- **A rule alerts on what crosses its threshold after it is switched on.** Switching a rule on does
  **not** flood the group with the backlog: questions already past the threshold, or incidents flagged
  before, never alert under it.
- Each switch from off to on records a new **Enabled at** (فُعّلت في). Switching off and on again
  therefore also "forgets" whatever crossed while it was off.
- **Rules are never deleted, only disabled.** The alert history keeps pointing at the rule.

## 6. Editing a rule

- You can change the threshold, the filters, the repeats, the quiet hours and the switch. Changes take
  effect on the next tick, about 30 seconds later.
- A subject that **already alerted** under the rule is not alerted again after an edit. Each alert also
  records the values that were in force when it fired.

## 7. Who may press, and what a press does

- Only a **declared, active moderator** can press, and only one declared before the press. The moderator
  must be listed under Moderators and linked to their Telegram account. Anyone else is told `هذه الأزرار
  للمشرفين المعتمدين فقط` and nothing is recorded.
- A press is the same act as in the panel: same records, same figures. In "My work" it is counted as
  **via alert**. A mistaken press cannot be undone (contract L6).
- After every press the bot answers with a short toast, for example `تم: السؤال لك` or `تم: عولجت
  المخالفة`. If the item had already ended, the toast reads `انتهى هذا البند: …` and nothing is recorded.

## 8. Reading the Alerts page (التنبيهات)

Every alert is listed with its rule, trigger, group, subject link, repeat, status, times and presses. It is
read-only.

| Status | Meaning |
|---|---|
| أُرسل (Sent) | posted in the alert group |
| بانتظار الإرسال / قيد الإرسال (Pending / Sending) | about to be posted, normally for seconds |
| مكتوم (ساعات الهدوء) (Suppressed) | due inside quiet hours, never sent |
| لم يُرسل · لا توجد وجهة (Not sent · No destination) | no alert group was designated at the time |
| لم يُرسل · انتهى قبل الإرسال (Not sent · Ended before sending) | the question or incident ended before posting |
| فشل · {category} (Failed) | Telegram refused or could not be reached. Retried up to 5 times unless final; `destination_migrated` means designate the group's new row. |

## 9. A suggested starting set (to agree with management)

These are examples, not defaults. Nothing exists until you create it.

| Rule | Group | Threshold | Filters | Repeats | Quiet hours |
|---|---|---|---|---|---|
| Incident flagged | All groups | none | none | none | none, or the night |
| Incident unhandled | All groups | e.g. 30 min | none | e.g. every 30 min, 2 | none |
| Question waiting (when the queue restarts) | All groups | e.g. 15 min | n/a | e.g. every 30 min, 2 | e.g. 23:00 → 07:00 |
| Group silent | All groups | e.g. 6 h | n/a | none | e.g. 00:00 → 08:00 |
| Bot not administrator | All groups | none | n/a | none | none |

Start with the incident pair, since the team works incidents today. Watch the Alerts page for a week, then
tune the thresholds.
