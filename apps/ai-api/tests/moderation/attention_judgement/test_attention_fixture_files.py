"""T063, T065, T086, T087 — the in-repository attention fixture files
(`specs/011-tg-m5-3-attention-judgement/contracts/qualification.md` version 2 §2-§3, data-model §8,
plan §3a, §8.3-§8.4; D-TG-193, D-TG-200).

What a run cannot check, a test does:
- **They load.** Every in-repo attention file goes through the qualification's own
  `load_fixture_lines` (V1-V4) with no `FixtureError`. The held-out set is checked once it exists:
  it is written only after the freeze (W-5).
- **Peer lines are rule-declined** (V2). A `peer` line the rules open never reaches the model, so it
  tests nothing: `evaluate([normalize(text)])` must be false (research Finding 14's `من` trap).
- **The validation set's minimums** (spec FR-331, plan §8.3): Policy D's peer lines — D3
  `discussion` negatives, D2/D5 peer-addressed `asking` positives, D6 unaddressed course-content
  lines marked ambiguous — and its size. No line carries a held-out topic word (plan §9, FR-333):
  the held-out topics are fixed now, and the validation set stays outside them.
- **The first cycle's held-out set is kept exactly** (T086, D-TG-200): `attention_v1` ran it once,
  so it is seen. Renamed `attention_heldout_v1_fixtures.jsonl` and read as a validation set in the
  second cycle, its bytes are pinned by SHA-256 — never edited, never relabelled.
- **The scope validation set's minimums** (T087; Policy D′, addendum §6.2), written before any v2
  candidate. It holds outside-institution negatives (`discussion` or `informing`), own-service
  positives on the same surface words, and D7 and exam-content lines, ambiguous. Every line reaches
  the model: rule-declined and no acknowledgement. No line names an institution a tuning set
  names, and no line labelled clear `asking` names an outside institution (D0).
- **The second cycle's held-out topics** (addendum §6.6, FR-333) are fixed before any v2
  candidate: no in-repo validation or tuning file carries one.
- **The held-out set's minimums** (T075, spec FR-331, plan §9), once it exists: at least 10
  rule-declined clear positives, at least 80% of lines without a question mark, at least 3
  rule-declined peer-discussion negatives and 2 peer-addressed positives.
- **The burst set's shape** (plan §3a, §8.4): each `rule` line opens by `evaluate` over all its
  members; each `model` and `none` line is declined as a whole burst and member by member; the
  L-B1 lines and the model-opened variants are there.

Pure: no model runtime, no database, no network. Nothing here prints a fixture's text — a failure
names the file and the line number only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from app.application.moderation.text import normalize
from app.domain.moderation.attention import evaluate, is_acknowledgement
from app.scripts.qualification.core import (
    KIND_ATTENTION,
    KIND_BURST,
    SHIPPED_DIR,
    load_fixture_lines,
)

_VALIDATION = SHIPPED_DIR / "attention_validation_fixtures.jsonl"
_HELDOUT = SHIPPED_DIR / "attention_heldout_fixtures.jsonl"
_HELDOUT_V1 = SHIPPED_DIR / "attention_heldout_v1_fixtures.jsonl"
_SCOPE = SHIPPED_DIR / "attention_validation_scope_fixtures.jsonl"
_BURST = SHIPPED_DIR / "attention_burst_fixtures.jsonl"
_SMOKE = SHIPPED_DIR / "attention_smoke_fixtures.jsonl"

# The first cycle's held-out set, as `attention_v1`'s T076 run read it (55 lines, 8,355 bytes).
_HELDOUT_V1_SHA256 = "0178e64e09b99f4f1c017aaa92b7bc6b867a1ab17089a042d21016bf261ae820"

# The files a peer line may sit in, and must be rule-declined in (V2). The held-out set joins once
# it is written (T075, T093).
_PEER_FILES: tuple[Path, ...] = (_VALIDATION, _SCOPE, _HELDOUT_V1, _HELDOUT)

# The in-repo validation and tuning files (the second cycle's, addendum §6.1).
_VALIDATION_AND_TUNING_FILES: tuple[Path, ...] = (_SMOKE, _VALIDATION, _SCOPE, _HELDOUT_V1)

# Plan §9's held-out topics, the first cycle's, as words already normalised (certificate, grades,
# homework submission, receipt, group link, exam hall, meeting app, timetable).
_HELDOUT_TOPIC_WORDS: tuple[str, ...] = (
    "شهاده",
    "درجات",
    "تسليم الواجب",
    "ايصال",
    "رابط الجروب",
    "قاعه",
    "زوم",
    "جدول",
)

# Addendum §6.6: the second cycle's held-out topics, fixed before any v2 candidate — embassy, visa,
# degree equivalency, the labour office, civil service; subscription, discount code, question
# bank, simulated test. Normalised before use.
_HELDOUT_V2_TOPIC_WORDS: tuple[str, ...] = (
    "سفارة",
    "تأشيرة",
    "معادلة",
    "مكتب العمل",
    "الخدمة المدنية",
    "اشتراك",
    "كود",
    "بنك الأسئلة",
    "محاكي",
)

# Addendum §6.2: the scope set's outside institutions — Jadarah, scholarships, university
# placement, unified admission — none of them named by a tuning set; and the outside institutions
# the real tuning sets do name, which the scope set stays off. Normalised before use.
_SCOPE_OUTSIDE_WORDS: tuple[str, ...] = ("جدارة", "ابتعاث", "تنسيق", "القبول الموحد")
_TUNING_OUTSIDE_WORDS: tuple[str, ...] = ("قياس", "جامعة", "رخصة", "ماجستير")

# Addendum §6.2: the scope set's size and minimums.
_SCOPE_MIN_LINES = 15
_SCOPE_MAX_LINES = 22
_SCOPE_MIN_OUTSIDE_NEGATIVES = 6
_SCOPE_MIN_OWN_POSITIVES = 4
_SCOPE_MIN_OWN_PEER_POSITIVES = 2
_SCOPE_MIN_AMBIGUOUS = 3  # at least 2 D7 lines and 1 exam-content line

# FR-331 / plan §8.3: the validation set's minimums.
_VALIDATION_MIN_LINES = 35
_VALIDATION_MAX_LINES = 45
_VALIDATION_MIN_PEER_DISCUSSION = 6
_VALIDATION_MIN_PEER_ASKING = 4
_VALIDATION_MIN_AMBIGUOUS_UNADDRESSED = 2

# FR-331 / plan §9: the held-out set's minimums.
_HELDOUT_MIN_RULE_DECLINED_POSITIVES = 10
_HELDOUT_MAX_QUESTION_MARK_SHARE = 0.20
_HELDOUT_MIN_PEER_DISCUSSION = 3
_HELDOUT_MIN_PEER_ASKING = 2

# Plan §8.4: the burst set's size and its two documented outcomes.
_BURST_MIN_LINES = 6
_BURST_MAX_LINES = 10
_BURST_MIN_L_B1 = 2
_BURST_MIN_MODEL = 3

# Keys every line written for TG-M5.3 carries (T064, data-model §8).
_VALIDATION_KEYS: tuple[str, ...] = ("text", "needs_response", "intent", "label_class")
_BURST_KEYS: tuple[str, ...] = ("burst", "needs_response", "intent", "expected_opener")


def _attention_lines(path: Path) -> list[tuple[int, dict[str, Any]]]:
    return load_fixture_lines(path, KIND_ATTENTION)


def _burst_lines() -> list[tuple[int, dict[str, Any]]]:
    return load_fixture_lines(_BURST, KIND_BURST)


def _raw_lines(path: Path) -> list[tuple[int, dict[str, Any]]]:
    """The lines as written, before `load_fixture_lines` defaults `label_class`."""
    raw = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [(n, json.loads(line)) for n, line in enumerate(raw, start=1)]


def _opens(texts: list[str]) -> bool:
    return evaluate([normalize(text) for text in texts])


# --- every in-repo file loads -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        pytest.param(_VALIDATION, KIND_ATTENTION, id="validation"),
        pytest.param(_SCOPE, KIND_ATTENTION, id="scope"),
        pytest.param(_HELDOUT_V1, KIND_ATTENTION, id="heldout-v1"),
        pytest.param(_BURST, KIND_BURST, id="burst"),
        pytest.param(_HELDOUT, KIND_ATTENTION, id="heldout"),
    ],
)
def test_every_in_repo_attention_file_loads_with_no_fixture_error(path: Path, kind: str) -> None:
    if path == _HELDOUT and not path.is_file():
        pytest.skip("the held-out set is written only after the freeze (W-5)")
    assert load_fixture_lines(path, kind)


@pytest.mark.parametrize(
    ("path", "keys"),
    [
        pytest.param(_VALIDATION, _VALIDATION_KEYS, id="validation"),
        pytest.param(_SCOPE, _VALIDATION_KEYS, id="scope"),
        pytest.param(_HELDOUT_V1, _VALIDATION_KEYS, id="heldout-v1"),
        pytest.param(_HELDOUT, _VALIDATION_KEYS, id="heldout"),
        pytest.param(_BURST, _BURST_KEYS, id="burst"),
    ],
)
def test_every_line_written_for_tg_m5_3_carries_its_keys(
    path: Path, keys: tuple[str, ...]
) -> None:
    if not path.is_file():
        pytest.skip(f"{path.name} is not written yet")
    missing = [(n, key) for n, fixture in _raw_lines(path) for key in keys if key not in fixture]
    assert missing == [], f"{path.name}: lines missing keys {missing}"


# --- peer lines are rule-declined (V2) ----------------------------------------------------------


@pytest.mark.parametrize("path", _PEER_FILES, ids=["validation", "scope", "heldout-v1", "heldout"])
def test_every_peer_line_is_rule_declined(path: Path) -> None:
    if not path.is_file():
        pytest.skip(f"{path.name} is not written yet")
    rule_opened = [
        n
        for n, fixture in _attention_lines(path)
        if fixture.get("peer") and _opens([fixture["text"]])
    ]
    assert rule_opened == [], f"{path.name}: peer lines the rules open: {rule_opened}"


# --- the first cycle's held-out set, kept exactly (T086, D-TG-200) ------------------------------


def test_the_first_cycles_held_out_set_is_kept_byte_identical() -> None:
    """Seen by `attention_v1`'s one run, it is a validation set now — the same bytes, or it is not
    the same evidence."""
    assert hashlib.sha256(_HELDOUT_V1.read_bytes()).hexdigest() == _HELDOUT_V1_SHA256


# --- the validation set's minimums (FR-331, plan §8.3) ------------------------------------------


def test_the_validation_set_has_its_size() -> None:
    count = len(_attention_lines(_VALIDATION))
    assert _VALIDATION_MIN_LINES <= count <= _VALIDATION_MAX_LINES


def test_the_validation_set_has_its_peer_discussion_negatives() -> None:
    """D3: peer questions about the members' own experience, work, answers or opinions — clear
    negatives, so they count under A3."""
    lines = [
        n
        for n, f in _attention_lines(_VALIDATION)
        if f.get("peer") and f["intent"] == "discussion" and f["label_class"] == "clear"
    ]
    assert len(lines) >= _VALIDATION_MIN_PEER_DISCUSSION


def test_the_validation_set_has_its_peer_addressed_positives() -> None:
    """D2 + D5: a peer-addressed service question or problem check is the team's."""
    lines = [
        n for n, f in _attention_lines(_VALIDATION) if f.get("peer") and f["intent"] == "asking"
    ]
    assert len(lines) >= _VALIDATION_MIN_PEER_ASKING


def test_the_validation_set_has_its_unaddressed_course_content_lines() -> None:
    """D6: `asking`, marked ambiguous, with no addressee — reported, never gated."""
    lines = [
        n
        for n, f in _attention_lines(_VALIDATION)
        if f["label_class"] == "ambiguous" and not f.get("peer")
    ]
    assert len(lines) >= _VALIDATION_MIN_AMBIGUOUS_UNADDRESSED


def test_no_validation_line_carries_a_held_out_topic_word() -> None:
    """FR-333: the first cycle's held-out topics were fixed in plan §9, and the first cycle's
    validation set stays outside them — checked on the normalised text, as a substring."""
    words = [normalize(word) for word in _HELDOUT_TOPIC_WORDS]
    carrying = [
        n
        for n, fixture in _attention_lines(_VALIDATION)
        if any(word in normalize(fixture["text"]) for word in words)
    ]
    assert carrying == [], f"validation lines carrying a held-out topic word: {carrying}"


# --- the second cycle: the scope set (T087) and the v2 held-out topics (addendum §6.2, §6.6) -----


def _carries(text: str, words: tuple[str, ...]) -> bool:
    normalised = normalize(text)
    return any(normalize(word) in normalised for word in words)


def _scope_lines() -> list[tuple[int, dict[str, Any]]]:
    return _attention_lines(_SCOPE)


def test_no_validation_or_tuning_line_carries_a_second_cycle_held_out_topic_word() -> None:
    carrying = [
        (path.name, n)
        for path in _VALIDATION_AND_TUNING_FILES
        for n, fixture in _attention_lines(path)
        if _carries(fixture["text"], _HELDOUT_V2_TOPIC_WORDS)
    ]
    assert carrying == [], f"lines carrying a v2 held-out topic word: {carrying}"


def test_the_scope_set_has_its_size() -> None:
    assert _SCOPE_MIN_LINES <= len(_scope_lines()) <= _SCOPE_MAX_LINES


def test_every_scope_line_reaches_the_model() -> None:
    """Rule-declined (AE2) and no acknowledgement (E8): a line that never reaches the model tests
    nothing about the wording."""
    stopped = [
        n
        for n, f in _scope_lines()
        if _opens([f["text"]]) or is_acknowledgement(normalize(f["text"]))
    ]
    assert stopped == [], f"scope lines the rules or E8 stop: {stopped}"


def test_the_scope_set_has_its_outside_institution_negatives() -> None:
    """D0, D3 and Policy S's scope: an outside institution's question or complaint, never the
    team's."""
    lines = [
        n
        for n, f in _scope_lines()
        if _carries(f["text"], _SCOPE_OUTSIDE_WORDS)
        and f["label_class"] == "clear"
        and f["intent"] in ("discussion", "informing")
    ]
    assert len(lines) >= _SCOPE_MIN_OUTSIDE_NEGATIVES


def test_no_clear_asking_scope_line_names_an_outside_institution() -> None:
    """D0: a line naming an outside institution is not the team's. Unclear lines are D7's, and
    ambiguous."""
    named = [
        n
        for n, f in _scope_lines()
        if f["label_class"] == "clear"
        and f["intent"] == "asking"
        and _carries(f["text"], _SCOPE_OUTSIDE_WORDS)
    ]
    assert named == []


def test_the_scope_set_has_its_own_service_positives() -> None:
    """D2 and D5: the course's own service, on the same surface words, some peer-addressed."""
    lines = [
        (n, f.get("peer") is True)
        for n, f in _scope_lines()
        if f["label_class"] == "clear" and f["intent"] == "asking"
    ]
    assert len(lines) >= _SCOPE_MIN_OWN_POSITIVES
    assert sum(peer for _, peer in lines) >= _SCOPE_MIN_OWN_PEER_POSITIVES


def test_the_scope_set_has_its_d7_and_exam_content_lines() -> None:
    """Unclear whose service (D7), and the content of the exam the course prepares for (D0, D6):
    `asking`, ambiguous — reported, never gated."""
    lines = [
        n
        for n, f in _scope_lines()
        if f["label_class"] == "ambiguous" and f["intent"] == "asking"
    ]
    assert len(lines) >= _SCOPE_MIN_AMBIGUOUS


def test_the_scope_set_stays_off_the_tuning_sets_institutions() -> None:
    """FR-331: validation topics are outside the tuning vocabulary — the institutions the real
    tuning sets name are not the scope set's."""
    carrying = [n for n, f in _scope_lines() if _carries(f["text"], _TUNING_OUTSIDE_WORDS)]
    assert carrying == []


# --- the held-out set's minimums (FR-331, plan §9) ----------------------------------------------


def _heldout_lines() -> list[tuple[int, dict[str, Any]]]:
    if not _HELDOUT.is_file():
        pytest.skip("the held-out set is written only after the freeze (W-5)")
    return _attention_lines(_HELDOUT)


def test_the_held_out_set_has_its_rule_declined_clear_positives() -> None:
    """A4 needs at least 10: a thinner set cannot show a miss rate."""
    lines = [
        n
        for n, f in _heldout_lines()
        if f["needs_response"] and f["label_class"] == "clear" and not _opens([f["text"]])
    ]
    assert len(lines) >= _HELDOUT_MIN_RULE_DECLINED_POSITIVES


def test_most_held_out_lines_carry_no_question_mark() -> None:
    lines = _heldout_lines()
    marked = [n for n, f in lines if "?" in f["text"] or "\u061f" in f["text"]]
    assert len(marked) <= _HELDOUT_MAX_QUESTION_MARK_SHARE * len(lines)


def test_the_held_out_set_has_its_peer_lines() -> None:
    """D3 negatives and D2/D5 positives, all rule-declined (checked above)."""
    lines = _heldout_lines()
    discussion = [
        n
        for n, f in lines
        if f.get("peer") and f["intent"] == "discussion" and f["label_class"] == "clear"
    ]
    asking = [n for n, f in lines if f.get("peer") and f["intent"] == "asking"]
    assert len(discussion) >= _HELDOUT_MIN_PEER_DISCUSSION
    assert len(asking) >= _HELDOUT_MIN_PEER_ASKING


# --- the burst set (plan §3a, §8.4) -------------------------------------------------------------


def test_the_burst_set_has_its_size() -> None:
    count = len(_burst_lines())
    assert _BURST_MIN_LINES <= count <= _BURST_MAX_LINES


def test_every_rule_burst_opens_by_the_rules_over_all_its_members() -> None:
    declined = [
        n
        for n, f in _burst_lines()
        if f["expected_opener"] == "rule" and not _opens(f["burst"])
    ]
    assert declined == [], f"rule bursts the rules decline: {declined}"


def test_every_model_and_none_burst_is_rule_declined_whole_and_member_by_member() -> None:
    """A burst the rules open never reaches the model; nor does a member whose own words open them
    (AE2). Both are checked so a `model` or `none` line tests the model."""
    rule_opened = [
        n
        for n, f in _burst_lines()
        if f["expected_opener"] in ("model", "none")
        and (_opens(f["burst"]) or any(_opens([member]) for member in f["burst"]))
    ]
    assert rule_opened == [], f"model/none bursts the rules open: {rule_opened}"


def test_the_burst_set_documents_l_b1_and_the_model_opened_variants() -> None:
    lines = _burst_lines()
    l_b1 = [n for n, f in lines if f["needs_response"] and f["expected_opener"] == "none"]
    model = [n for n, f in lines if f["expected_opener"] == "model"]
    assert len(l_b1) >= _BURST_MIN_L_B1
    assert len(model) >= _BURST_MIN_MODEL
