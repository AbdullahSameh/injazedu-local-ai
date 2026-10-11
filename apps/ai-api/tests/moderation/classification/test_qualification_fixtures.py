"""The qualification's benchmark fixture lines (`specs/011-tg-m5-3-attention-judgement/contracts/
qualification.md` version 2 §3, data-model §8, D-TG-193; version 1's keys from
`specs/010-tg-m5-2-classify-v3/data-model.md` §1, D-TG-177), the sets each suite reads (§2), the
per-fixture judgements the smokes and the qualification share (C4, D-TG-178, D-TG-195), and the
command's arguments (§1).

- Version 1's keys: `label_class` (`clear` by default, or `ambiguous`; attention sets only) and
  `tracked` (`no-link-rule` or `label-review`; any set).
- Version 2's: `intent` (one of six, `asking` exactly when `needs_response`), `peer` (`true`
  only), and, in the burst set only, `burst` (2-5 texts, replacing `text`) with a required
  `expected_opener` (`rule` | `model` | `none`).

Anything else is refused, and the refusal names the set and the line, never the text. Lines are
numbered as the smokes number them: blank lines skipped, from 1. The attention judgement is the
live path — the rule set first (no call when it opens), eligibility, the model on
`role="attention"` — with the model replaced by a stub here. Pure: no model runtime, no database,
no network.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.application.gateway import GatewayError, ModelTimeoutError, StructuredOutputInvalidError
from app.application.moderation.attention_judgement import (
    AttentionJudgementResult,
    build_attention_input,
)
from app.application.moderation.classification import (
    MessageClassificationResult,
    build_model_input,
)
from app.application.moderation.text import normalize
from app.scripts import smoke_moderation
from app.scripts.qualification import attention as attention_suite
from app.scripts.qualification import moderation as moderation_suite
from app.scripts.qualification.__main__ import _parse_args
from app.scripts.qualification.core import (
    LABEL_CLASSES,
    SHIPPED_DIR,
    TRACKED_DISPOSITIONS,
    TRACKED_LIMIT,
    FixtureError,
    SetSpec,
    judge_sets,
    load_fixture_lines,
    load_sets,
)

_SENTINEL = "SENTINEL-fixture-text-never-printed"
_SCRIPTS = Path(smoke_moderation.__file__).resolve().parent
_FLOOR = Decimal("0.600")
_THRESHOLD = Decimal("0.850")
_INSTRUCTION = "TEST ATTENTION INSTRUCTION"


def _attention(**extra: Any) -> dict[str, Any]:
    return {"text": _SENTINEL, "needs_response": True, "category": "QUESTION_COURSE", **extra}


def _moderation(**extra: Any) -> dict[str, Any]:
    return {"text": _SENTINEL, "category": "SPAM_OR_AD", "needs_moderation": True, **extra}


def _burst(**extra: Any) -> dict[str, Any]:
    return {
        "burst": [_SENTINEL, _SENTINEL],
        "needs_response": True,
        "expected_opener": "model",
        **extra,
    }


def _write(tmp_path: Path, name: str, lines: list[dict[str, Any] | str]) -> Path:
    path = tmp_path / name
    path.write_text(
        "\n".join(
            line if isinstance(line, str) else json.dumps(line, ensure_ascii=False)
            for line in lines
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _refused(path: Path, kind: str, *, line: int, names: str) -> None:
    """The line is refused, naming the set, the line and the key — never the text."""
    with pytest.raises(FixtureError) as caught:
        load_fixture_lines(path, kind)
    message = str(caught.value)
    assert path.name in message
    assert f"#{line}" in message
    assert names in message
    assert _SENTINEL not in message


# --- the closed vocabularies -------------------------------------------------------------------


def test_the_vocabularies_are_closed_and_the_tracked_limit_is_two() -> None:
    assert LABEL_CLASSES == ("clear", "ambiguous")
    assert TRACKED_DISPOSITIONS == ("no-link-rule", "label-review")
    assert TRACKED_LIMIT == 2


# --- label_class -------------------------------------------------------------------------------


def test_a_missing_label_class_defaults_to_clear(tmp_path: Path) -> None:
    path = _write(tmp_path, "set.jsonl", [_attention()])

    [(line, fixture)] = load_fixture_lines(path, "attention")

    assert line == 1
    assert fixture["label_class"] == "clear"


def test_ambiguous_is_accepted(tmp_path: Path) -> None:
    path = _write(tmp_path, "set.jsonl", [_attention(label_class="ambiguous")])

    [(_, fixture)] = load_fixture_lines(path, "attention")

    assert fixture["label_class"] == "ambiguous"


def test_an_unknown_label_class_is_refused_naming_the_set_and_line_never_the_text(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "real-attention.jsonl", [_attention(), _attention(label_class="maybe")])

    _refused(path, "attention", line=2, names="label_class")


def test_label_class_on_a_moderation_fixture_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "real-moderation.jsonl", [_moderation(label_class="clear")])

    _refused(path, "moderation", line=1, names="label_class")


# --- tracked -----------------------------------------------------------------------------------


@pytest.mark.parametrize("disposition", ["no-link-rule", "label-review"])
@pytest.mark.parametrize("kind", ["attention", "moderation"])
def test_each_tracked_disposition_is_accepted_on_any_set(
    tmp_path: Path, kind: str, disposition: str
) -> None:
    fixture = (_attention if kind == "attention" else _moderation)(tracked=disposition)
    path = _write(tmp_path, "set.jsonl", [fixture])

    [(_, loaded)] = load_fixture_lines(path, kind)

    assert loaded["tracked"] == disposition


@pytest.mark.parametrize("kind", ["attention", "moderation"])
def test_an_unknown_tracked_value_is_refused_naming_the_set_and_line_never_the_text(
    tmp_path: Path, kind: str
) -> None:
    good = _attention if kind == "attention" else _moderation
    path = _write(tmp_path, "shipped.jsonl", [good(), good(), good(tracked="later")])

    _refused(path, kind, line=3, names="tracked")


def test_an_untracked_line_carries_no_tracked_key(tmp_path: Path) -> None:
    path = _write(tmp_path, "set.jsonl", [_moderation()])

    [(_, fixture)] = load_fixture_lines(path, "moderation")

    assert "tracked" not in fixture


# --- intent (V1) --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("intent", "needs_response"),
    [
        ("asking", True),
        ("discussion", False),
        ("informing", False),
        ("social", False),
        ("offering", False),
        ("other", False),
    ],
)
def test_each_intent_is_accepted_with_its_label(
    tmp_path: Path, intent: str, needs_response: bool
) -> None:
    path = _write(tmp_path, "set.jsonl", [_attention(intent=intent, needs_response=needs_response)])

    [(_, fixture)] = load_fixture_lines(path, "attention")

    assert fixture["intent"] == intent


@pytest.mark.parametrize("intent", ["question", "ASKING", "", 1, None])
def test_an_intent_outside_the_six_is_refused(tmp_path: Path, intent: Any) -> None:
    path = _write(tmp_path, "attention_validation_fixtures.jsonl", [_attention(intent=intent)])

    _refused(path, "attention", line=1, names="intent")


@pytest.mark.parametrize(
    ("intent", "needs_response"), [("asking", False), ("discussion", True), ("social", True)]
)
def test_an_intent_that_disagrees_with_needs_response_is_refused(
    tmp_path: Path, intent: str, needs_response: bool
) -> None:
    path = _write(
        tmp_path,
        "attention_validation_fixtures.jsonl",
        [_attention(), _attention(intent=intent, needs_response=needs_response)],
    )

    _refused(path, "attention", line=2, names="needs_response")


@pytest.mark.parametrize("name", ["intent", "peer"])
def test_attention_keys_on_a_moderation_fixture_are_refused(tmp_path: Path, name: str) -> None:
    path = _write(tmp_path, "real-moderation.jsonl", [_moderation(**{name: True})])

    _refused(path, "moderation", line=1, names=name)


# --- peer (V2) ----------------------------------------------------------------------------------


def test_peer_true_is_accepted(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "set.jsonl",
        [_attention(intent="discussion", needs_response=False, peer=True)],
    )

    [(_, fixture)] = load_fixture_lines(path, "attention")

    assert fixture["peer"] is True


@pytest.mark.parametrize("value", [False, "true", 1, None])
def test_peer_is_accepted_only_as_true(tmp_path: Path, value: Any) -> None:
    path = _write(tmp_path, "set.jsonl", [_attention(peer=value)])

    _refused(path, "attention", line=1, names="peer")


# --- burst and expected_opener (V3) -------------------------------------------------------------


@pytest.mark.parametrize("opener", ["rule", "model", "none"])
@pytest.mark.parametrize("size", [2, 5])
def test_a_burst_line_is_accepted_in_the_burst_set(tmp_path: Path, opener: str, size: int) -> None:
    path = _write(
        tmp_path,
        "attention_burst_fixtures.jsonl",
        [_burst(burst=[_SENTINEL] * size, expected_opener=opener)],
    )

    [(_, fixture)] = load_fixture_lines(path, "burst")

    assert len(fixture["burst"]) == size
    assert fixture["expected_opener"] == opener
    assert fixture["label_class"] == "clear"


@pytest.mark.parametrize(
    "members", [[_SENTINEL], [_SENTINEL] * 6, [], _SENTINEL, [_SENTINEL, 1], None]
)
def test_a_burst_must_be_two_to_five_texts(tmp_path: Path, members: Any) -> None:
    path = _write(tmp_path, "attention_burst_fixtures.jsonl", [_burst(burst=members)])

    _refused(path, "burst", line=1, names="burst")


def test_a_burst_line_carries_no_text(tmp_path: Path) -> None:
    path = _write(tmp_path, "attention_burst_fixtures.jsonl", [_burst(text=_SENTINEL)])

    _refused(path, "burst", line=1, names="text")


@pytest.mark.parametrize("missing", ["burst", "needs_response", "expected_opener"])
def test_the_burst_sets_label_keys_are_required(tmp_path: Path, missing: str) -> None:
    fixture = _burst()
    del fixture[missing]
    path = _write(tmp_path, "attention_burst_fixtures.jsonl", [fixture])

    _refused(path, "burst", line=1, names=missing)


@pytest.mark.parametrize("opener", ["excluded", "error", "Rule", ""])
def test_an_unknown_expected_opener_is_refused(tmp_path: Path, opener: str) -> None:
    path = _write(tmp_path, "attention_burst_fixtures.jsonl", [_burst(expected_opener=opener)])

    _refused(path, "burst", line=1, names="expected_opener")


@pytest.mark.parametrize(
    ("kind", "fixture", "name"),
    [
        ("attention", _attention(burst=[_SENTINEL, _SENTINEL]), "burst"),
        ("attention", _attention(expected_opener="none"), "expected_opener"),
        ("moderation", _moderation(burst=[_SENTINEL, _SENTINEL]), "burst"),
        ("moderation", _moderation(expected_opener="rule"), "expected_opener"),
    ],
)
def test_burst_keys_outside_the_burst_set_are_refused(
    tmp_path: Path, kind: str, fixture: dict[str, Any], name: str
) -> None:
    path = _write(tmp_path, "attention_validation_fixtures.jsonl", [fixture])

    _refused(path, kind, line=1, names=name)


def test_an_intent_on_a_burst_line_must_agree_with_its_label(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "attention_burst_fixtures.jsonl",
        [_burst(intent="asking"), _burst(intent="social")],
    )

    _refused(path, "burst", line=2, names="needs_response")


# --- the line itself ---------------------------------------------------------------------------


def test_blank_lines_are_skipped_and_numbering_matches_the_smokes(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "set.jsonl",
        [_attention(category="A"), "", "   ", _attention(category="B"), _attention(category="C")],
    )
    # The smokes' own numbering: `enumerate(<non-blank lines>, start=1)`.
    smoke_numbering = [
        (n, json.loads(raw)["category"])
        for n, raw in enumerate(
            (raw for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip()),
            start=1,
        )
    ]

    loaded = [(n, fixture["category"]) for n, fixture in load_fixture_lines(path, "attention")]

    assert loaded == smoke_numbering == [(1, "A"), (2, "B"), (3, "C")]


def test_a_line_that_is_not_json_is_refused_naming_the_set_and_line(tmp_path: Path) -> None:
    path = _write(tmp_path, "set.jsonl", [_attention(), f'{{"text": "{_SENTINEL}", '])

    _refused(path, "attention", line=2, names="JSON")


@pytest.mark.parametrize(
    ("kind", "fixture"),
    [
        ("attention", {"text": _SENTINEL}),
        ("attention", {"needs_response": True}),
        ("moderation", {"text": _SENTINEL, "category": "SPAM_OR_AD"}),
        ("moderation", {"text": _SENTINEL, "needs_moderation": True}),
    ],
)
def test_a_missing_label_key_is_refused(tmp_path: Path, kind: str, fixture: dict[str, Any]) -> None:
    path = _write(tmp_path, "set.jsonl", [fixture])

    _refused(path, kind, line=1, names="missing")


# --- the shipped synthetic sets (data-model §1: keys added, never a label changed) --------------


def test_the_shipped_attention_set_marks_lines_4_to_6_ambiguous_and_nothing_else() -> None:
    loaded = load_fixture_lines(_SCRIPTS / "attention_smoke_fixtures.jsonl", "attention")

    assert len(loaded) == 15
    assert [n for n, fixture in loaded if fixture["label_class"] == "ambiguous"] == [4, 5, 6]
    assert not [n for n, fixture in loaded if "tracked" in fixture]
    # Bare declaratives under Policy S — labelled true, and the label stays true.
    assert all(fixture["needs_response"] for n, fixture in loaded if n in (4, 5, 6))


def test_the_shipped_moderation_set_tracks_line_11_for_label_review_only() -> None:
    loaded = load_fixture_lines(_SCRIPTS / "moderation_smoke_fixtures.jsonl", "moderation")

    assert len(loaded) == 12
    assert [(n, fixture["tracked"]) for n, fixture in loaded if "tracked" in fixture] == [
        (11, "label-review")
    ]
    [(_, accusation)] = [(n, fixture) for n, fixture in loaded if n == 11]
    assert (accusation["category"], accusation["needs_moderation"]) == ("ABUSE", True)


def test_the_shipped_policy_set_loads_untracked() -> None:
    loaded = load_fixture_lines(_SCRIPTS / "moderation_smoke_policy_fixtures.jsonl", "moderation")

    assert len(loaded) == 64
    assert not [n for n, fixture in loaded if "tracked" in fixture]


# --- the sets each suite reads (contract §2) ---------------------------------------------------


def _touch(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("", encoding="utf-8")


def _shape(specs: list[SetSpec]) -> list[tuple[str, str, str, bool]]:
    return [(spec.name, spec.role, spec.kind, spec.path is not None) for spec in specs]


_ALL_SHIPPED = (
    "attention_smoke_fixtures.jsonl",
    "attention_validation_fixtures.jsonl",
    "attention_validation_scope_fixtures.jsonl",
    "attention_heldout_v1_fixtures.jsonl",
    "attention_heldout_fixtures.jsonl",
    "attention_burst_fixtures.jsonl",
    "moderation_smoke_fixtures.jsonl",
    "moderation_smoke_policy_fixtures.jsonl",
)


def test_every_attention_set_is_found_in_reading_order(tmp_path: Path) -> None:
    fixtures, shipped = tmp_path / "fixtures", tmp_path / "shipped"
    _touch(
        fixtures,
        "real-attention.jsonl",
        "real-attention-extra.jsonl",
        "fresh-attention.jsonl",
        "real-moderation.jsonl",
        "real_messages.md",
    )
    (fixtures / "real-attention-extra.jsonl_files").mkdir()  # not a set
    _touch(shipped, *_ALL_SHIPPED)

    specs = attention_suite.discover_attention_sets(fixtures, shipped_dir=shipped)

    assert _shape(specs) == [
        ("real-attention-extra.jsonl", "tuning", "attention", True),
        ("real-attention.jsonl", "tuning", "attention", True),
        ("attention_smoke_fixtures.jsonl", "tuning", "attention", True),
        ("attention_validation_fixtures.jsonl", "validation", "attention", True),
        ("attention_validation_scope_fixtures.jsonl", "validation", "attention", True),
        ("attention_heldout_v1_fixtures.jsonl", "validation", "attention", True),
        ("attention_heldout_fixtures.jsonl", "heldout", "attention", True),
        ("fresh-attention.jsonl", "fresh", "attention", True),
        ("attention_burst_fixtures.jsonl", "burst", "burst", True),
        ("real-moderation.jsonl", "a6-source", "moderation", True),
        ("moderation_smoke_fixtures.jsonl", "a6-source", "moderation", True),
        ("moderation_smoke_policy_fixtures.jsonl", "a6-source", "moderation", True),
    ]
    assert specs[0].path == fixtures / "real-attention-extra.jsonl"
    assert specs[2].path == shipped / "attention_smoke_fixtures.jsonl"


def test_candidate_mode_withholds_the_held_out_and_fresh_sets(tmp_path: Path) -> None:
    fixtures, shipped = tmp_path / "fixtures", tmp_path / "shipped"
    _touch(fixtures, "real-attention.jsonl", "fresh-attention.jsonl", "real-moderation.jsonl")
    _touch(shipped, *_ALL_SHIPPED)

    specs = attention_suite.discover_attention_sets(fixtures, shipped_dir=shipped, candidate=True)

    withheld = {spec.name: spec for spec in specs if spec.path is None}
    assert set(withheld) == {"attention_heldout_fixtures.jsonl", "fresh-attention.jsonl"}
    assert all(spec.withheld for spec in withheld.values())
    assert {spec.missing_reason for spec in withheld.values()} == {"withheld in candidate mode"}
    # The first cycle's held-out set is seen: in the second cycle it is validation, read in
    # candidate mode like the other two (T086, D-TG-200).
    assert [spec.name for spec in specs if spec.role == "validation" and spec.path] == [
        "attention_validation_fixtures.jsonl",
        "attention_validation_scope_fixtures.jsonl",
        "attention_heldout_v1_fixtures.jsonl",
    ]


def test_every_moderation_set_is_found_in_reading_order(tmp_path: Path) -> None:
    fixtures, shipped = tmp_path / "fixtures", tmp_path / "shipped"
    _touch(fixtures, "real-moderation.jsonl", "real-attention.jsonl")
    _touch(shipped, *_ALL_SHIPPED)

    specs = moderation_suite.discover_moderation_sets(fixtures, shipped_dir=shipped)

    assert _shape(specs) == [
        ("real-moderation.jsonl", "moderation-real", "moderation", True),
        ("moderation_smoke_fixtures.jsonl", "moderation-shipped", "moderation", True),
        ("moderation_smoke_policy_fixtures.jsonl", "moderation-policy", "moderation", True),
    ]


def test_a_missing_set_is_listed_without_a_path(tmp_path: Path) -> None:
    fixtures, shipped = tmp_path / "fixtures", tmp_path / "shipped"
    fixtures.mkdir()
    _touch(
        shipped,
        "attention_smoke_fixtures.jsonl",
        "moderation_smoke_fixtures.jsonl",
        "moderation_smoke_policy_fixtures.jsonl",
    )

    attention = attention_suite.discover_attention_sets(fixtures, shipped_dir=shipped)
    moderation = moderation_suite.discover_moderation_sets(fixtures, shipped_dir=shipped)

    assert _shape(attention) == [
        ("real-attention*.jsonl", "tuning", "attention", False),
        ("attention_smoke_fixtures.jsonl", "tuning", "attention", True),
        ("attention_validation_fixtures.jsonl", "validation", "attention", False),
        ("attention_validation_scope_fixtures.jsonl", "validation", "attention", False),
        ("attention_heldout_v1_fixtures.jsonl", "validation", "attention", False),
        ("attention_heldout_fixtures.jsonl", "heldout", "attention", False),
        ("fresh-attention.jsonl", "fresh", "attention", False),
        ("attention_burst_fixtures.jsonl", "burst", "burst", False),
        ("real-moderation.jsonl", "a6-source", "moderation", False),
        ("moderation_smoke_fixtures.jsonl", "a6-source", "moderation", True),
        ("moderation_smoke_policy_fixtures.jsonl", "a6-source", "moderation", True),
    ]
    assert _shape(moderation) == [
        ("real-moderation.jsonl", "moderation-real", "moderation", False),
        ("moderation_smoke_fixtures.jsonl", "moderation-shipped", "moderation", True),
        ("moderation_smoke_policy_fixtures.jsonl", "moderation-policy", "moderation", True),
    ]
    assert {spec.missing_reason for spec in attention if spec.path is None} == {"missing"}


def test_the_shipped_sets_default_to_the_scripts_directory(tmp_path: Path) -> None:
    attention = {s.name: s.path for s in attention_suite.discover_attention_sets(tmp_path)}
    moderation = {s.name: s.path for s in moderation_suite.discover_moderation_sets(tmp_path)}

    assert SHIPPED_DIR == _SCRIPTS
    assert (
        attention["attention_smoke_fixtures.jsonl"] == _SCRIPTS / "attention_smoke_fixtures.jsonl"
    )
    assert moderation["moderation_smoke_policy_fixtures.jsonl"] == (
        _SCRIPTS / "moderation_smoke_policy_fixtures.jsonl"
    )


# --- the per-fixture judgements (C4, D-TG-195) --------------------------------------------------


class _StubGateway:
    """Stands in for `Gateway`: records each structured request and its role, then answers with
    `answer` or raises `fail_with`. The judgements only ever call `generate_structured`."""

    def __init__(
        self,
        answer: Any = None,
        fail_with: type[GatewayError] | None = None,
    ) -> None:
        self.answer = answer
        self.fail_with = fail_with
        self.calls: list[tuple[Any, str]] = []

    async def generate_structured(self, request: Any, *, role: str) -> Any:
        self.calls.append((request, role))
        if self.fail_with is not None:
            raise self.fail_with(f"raw model output {_SENTINEL}", profile_name="stub")
        return SimpleNamespace(value=self.answer)


def _intent(intent: str) -> AttentionJudgementResult:
    return AttentionJudgementResult.model_validate({"intent": intent})


def _answer(
    category: str = "QUESTION_COURSE",
    *,
    needs_response: bool = True,
    needs_moderation: bool = False,
    severity: str = "none",
    confidence: float = 0.95,
) -> MessageClassificationResult:
    return MessageClassificationResult.model_validate(
        {
            "category": category,
            "needs_response": needs_response,
            "needs_moderation": needs_moderation,
            "severity": severity,
            "confidence": confidence,
        }
    )


async def _judge_line(
    gateway: _StubGateway, fixture: dict[str, Any], *, line: int = 1, **kwargs: Any
) -> tuple[attention_suite.AttentionRow, int | None]:
    return await attention_suite.judge_attention_line(
        gateway,  # type: ignore[arg-type]
        fixture,
        line=line,
        instruction=_INSTRUCTION,
        **kwargs,
    )


async def _judge_moderation(
    gateway: _StubGateway, fixture: dict[str, Any], *, line: int = 1, **kwargs: Any
) -> tuple[smoke_moderation.SmokeRow, int | None]:
    return await smoke_moderation.judge_moderation_fixture(
        gateway,  # type: ignore[arg-type]
        fixture,
        line=line,
        prompt_version="classify_v2",
        floor=_FLOOR,
        threshold=_THRESHOLD,
        **kwargs,
    )


async def test_attention_sends_the_instruction_and_redacted_words_on_the_attention_role() -> None:
    gateway = _StubGateway(_intent("asking"))
    text = "  المحتوى ناقص عندي https://example.com/x  "

    await _judge_line(gateway, {"text": text, "needs_response": True})

    [(request, role)] = gateway.calls
    assert role == "attention"
    assert request.messages == build_attention_input(normalize(text), instruction=_INSTRUCTION)
    assert request.messages[0].content == _INSTRUCTION
    assert "https://" not in request.messages[1].content  # redacted, as the live request is
    assert request.schema_model is AttentionJudgementResult


async def test_attention_the_rule_set_has_the_first_word_and_no_call_is_made() -> None:
    gateway = _StubGateway(_intent("social"))

    row, latency_ms = await _judge_line(
        gateway, {"text": "متى الاختبار؟", "needs_response": True}, line=3
    )

    assert gateway.calls == []  # AE2: no call
    assert row.line == 3
    assert row.rule_opens is True
    assert row.opener == "rule"
    assert row.intent is None
    assert latency_ms is None


@pytest.mark.parametrize(
    ("intent", "opener"),
    [
        ("asking", "model"),
        ("discussion", "none"),
        ("informing", "none"),
        ("social", "none"),
        ("offering", "none"),
        ("other", "none"),
    ],
)
async def test_attention_the_model_opens_only_on_asking(intent: str, opener: str) -> None:
    gateway = _StubGateway(_intent(intent))

    row, latency_ms = await _judge_line(
        gateway,
        {"text": "المحتوى ناقص عندي", "needs_response": True, "intent": "asking", "peer": True},
        line=2,
    )

    assert row.rule_opens is False
    assert row.intent == intent
    assert row.expected_intent == "asking"
    assert row.peer is True
    assert row.opener == opener
    assert row.predicted_needs_response is (intent == "asking")
    assert isinstance(latency_ms, int) and latency_ms >= 0


async def test_attention_an_acknowledgement_never_reaches_the_model() -> None:
    gateway = _StubGateway(_intent("asking"))

    row, latency_ms = await _judge_line(gateway, {"text": "شكرا", "needs_response": False})

    assert gateway.calls == []
    assert row.excluded == "acknowledgement"
    assert row.opener == "excluded"
    assert latency_ms is None


@pytest.mark.parametrize("error", [ModelTimeoutError, StructuredOutputInvalidError])
async def test_attention_a_gateway_errors_detail_goes_only_to_the_reporter(
    error: type[GatewayError],
) -> None:
    reported: list[tuple[int, str]] = []
    gateway = _StubGateway(fail_with=error)

    row, latency_ms = await _judge_line(
        gateway,
        {"text": "المحتوى ناقص عندي", "needs_response": True},
        line=5,
        report_error=lambda line, detail: reported.append((line, detail)),
    )

    assert row.error == error.__name__
    assert row.intent is None
    assert row.opener == "error"
    assert latency_ms is None
    assert reported == [(5, f"{error.__name__}: raw model output {_SENTINEL}")]
    assert _SENTINEL not in repr(row)


async def test_moderation_routes_live_at_the_given_thresholds() -> None:
    gateway = _StubGateway(
        _answer(
            "SPAM_OR_AD",
            needs_response=False,
            needs_moderation=True,
            severity="medium",
            confidence=0.95,
        )
    )
    text = "  عرض خاص تواصل خاص  "

    row, latency_ms = await _judge_moderation(
        gateway, {"text": text, "category": "SPAM_OR_AD", "needs_moderation": True}, line=9
    )

    [(request, role)] = gateway.calls
    assert role == "moderation"
    assert request.messages == build_model_input(normalize(text), prompt_version="classify_v2")
    assert row.line == 9
    assert row.route == "incident"
    assert row.predicted_category == "SPAM_OR_AD"
    assert row.predicted_needs_moderation is True
    assert row.predicted_needs_response is False
    assert row.confidence == 0.95
    assert row.matched
    assert isinstance(latency_ms, int)


async def test_moderation_keeps_the_route_reason() -> None:
    gateway = _StubGateway(_answer("SPAM_OR_AD", needs_response=False, needs_moderation=False))

    row, _ = await _judge_moderation(
        gateway, {"text": "عرض", "category": "SPAM_OR_AD", "needs_moderation": True}
    )

    assert row.route == "possible_violation/inconsistent"


async def test_moderation_a_gateway_error_is_an_error_row() -> None:
    reported: list[tuple[int, str]] = []
    gateway = _StubGateway(fail_with=ModelTimeoutError)

    row, latency_ms = await _judge_moderation(
        gateway,
        {"text": "عرض", "category": "SPAM_OR_AD", "needs_moderation": True},
        line=4,
        report_error=lambda line, detail: reported.append((line, detail)),
    )

    assert row.error == "ModelTimeoutError"
    assert row.route is None
    assert latency_ms is None
    assert reported == [(4, f"ModelTimeoutError: raw model output {_SENTINEL}")]


async def test_moderation_an_out_of_range_confidence_is_an_error() -> None:
    row, _ = await _judge_moderation(
        _StubGateway(_answer(confidence=-0.1)),
        {"text": "عرض", "category": "SPAM_OR_AD", "needs_moderation": True},
    )

    assert row.error == "confidence_out_of_range"
    assert row.predicted_category is None


# --- the per-line format (moderation pinned so the move changes no byte) -----------------------


def test_the_attention_line_format() -> None:
    judged = attention_suite.AttentionRow(
        line=3,
        expected_needs_response=False,
        expected_intent="discussion",
        peer=True,
        rule_opens=False,
        intent="asking",
    )
    ruled = attention_suite.AttentionRow(line=4, expected_needs_response=True, rule_opens=True)
    excluded = attention_suite.AttentionRow(
        line=6, expected_needs_response=False, rule_opens=False, excluded="acknowledgement"
    )

    assert attention_suite.format_row(judged, 12) == (
        "[FP] #3 expected=False label=discussion peer intent=asking rule=declines opener=model "
        "latency_ms=12"
    )
    assert attention_suite.format_row(ruled, None) == "[OK] #4 expected=True rule=opens opener=rule"
    assert attention_suite.format_row(excluded, None) == (
        "[OK] #6 expected=False excluded=acknowledgement rule=declines opener=excluded"
    )


def test_the_moderation_line_format_is_the_smokes() -> None:
    row = smoke_moderation.SmokeRow(
        line=2,
        expected_category="ABUSE",
        expected_needs_moderation=True,
        predicted_category="COMPLAINT",
        predicted_needs_moderation=True,
        predicted_needs_response=True,
        confidence=0.9,
        route="incident",
    )

    assert smoke_moderation.format_row(row, 7) == (
        "[MISMATCH] #2 expected=ABUSE/True predicted=COMPLAINT/True confidence=0.9 "
        "route=incident latency_ms=7"
    )
    assert moderation_suite.moderation_detail(
        SetSpec("s", "moderation-real", "moderation"), row, (7,)
    ) == smoke_moderation.format_row(row, 7)


# --- the command: its arguments (contract §1 C1, C5, C6) ----------------------------------------


def _args(*extra: str, task: str = "moderation") -> list[str]:
    return ["--task", task, "--profile", "p", "--fixtures-dir", "/f", *extra]


def test_the_task_and_the_profile_are_required() -> None:
    for argv in (
        ["--profile", "p", "--fixtures-dir", "/fixtures"],
        ["--task", "moderation", "--fixtures-dir", "/fixtures"],
        ["--task", "both", "--profile", "p", "--fixtures-dir", "/fixtures"],
    ):
        with pytest.raises(SystemExit) as caught:
            _parse_args(argv)
        assert caught.value.code == 2


def test_the_prompt_must_be_in_the_tasks_allowlist() -> None:
    for argv in (
        _args("--prompt", "classify_v9"),
        _args("--prompt", "classify_v2", task="attention"),  # the moderation allowlist's
        _args("--prompt", "attention_v1"),  # the attention allowlist's
        _args("--prompt", "attention_v2", task="attention"),  # not frozen
    ):
        with pytest.raises(SystemExit) as caught:
            _parse_args(argv)
        assert caught.value.code == 2

    assert _parse_args(_args("--prompt", "classify_v2")).prompt == "classify_v2"
    # T074: the frozen attention instruction.
    assert _parse_args(_args("--prompt", "attention_v1", task="attention")).prompt == "attention_v1"


def test_an_attention_prompt_is_accepted_once_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.scripts.qualification import __main__ as command

    monkeypatch.setattr(command, "ATTENTION_PROMPT_VERSIONS", ("attention_test",))

    args = _parse_args(_args("--prompt", "attention_test", task="attention"))

    assert args.prompt == "attention_test"


@pytest.mark.parametrize("repeat", ["0", "-1", "two"])
def test_repeat_must_be_a_positive_whole_number(repeat: str) -> None:
    with pytest.raises(SystemExit) as caught:
        _parse_args(_args("--repeat", repeat))

    assert caught.value.code == 2


def test_the_defaults() -> None:
    args = _parse_args(_args())

    assert (args.task, args.profile, args.fixtures_dir, args.prompt, args.repeat) == (
        "moderation",
        "p",
        "/f",
        None,
        2,
    )
    assert (args.candidate_file, args.moderation_p95_ms, args.serving) == (None, None, "single")


def test_a_candidate_file_is_for_attention_only_and_under_the_fixtures_dir() -> None:
    accepted = _parse_args(_args("--candidate-file", "/f/candidate-w1.md", task="attention"))
    assert accepted.candidate_file == "/f/candidate-w1.md"

    for argv in (
        _args("--candidate-file", "/f/candidate-w1.md"),  # moderation
        _args("--candidate-file", "/elsewhere/candidate-w1.md", task="attention"),
        _args("--candidate-file", "/f/../candidate-w1.md", task="attention"),
        _args("--candidate-file", "/f/c.md", "--prompt", "classify_v2", task="attention"),
    ):
        with pytest.raises(SystemExit) as caught:
            _parse_args(argv)
        assert caught.value.code == 2


def test_serving_is_single_or_concurrent() -> None:
    assert _parse_args(_args("--serving", "concurrent", task="attention")).serving == "concurrent"
    with pytest.raises(SystemExit):
        _parse_args(_args("--serving", "parallel", task="attention"))


# --- the judging loop (S5, C3) ------------------------------------------------------------------


class _ScriptedByText(_StubGateway):
    """Answers every call, except that a message carrying `FAIL` times out — with the model's raw
    output, text included, in the exception's message."""

    async def generate_structured(self, request: Any, *, role: str) -> Any:
        self.calls.append((request, role))
        if "FAIL" in request.messages[-1].content:
            raise ModelTimeoutError(f"raw model output {_SENTINEL}", profile_name="stub")
        return SimpleNamespace(value=self.answer)


def _attention_sets(tmp_path: Path) -> list[SetSpec]:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    _write(
        fixtures,
        "real-attention.jsonl",
        [
            {"text": f"{_SENTINEL} المحتوى ناقص عندي", "needs_response": True},
            {"text": f"{_SENTINEL} FAIL", "needs_response": False},
            "",
            {"text": "شكرا", "needs_response": False, "label_class": "clear"},
            {"text": f"{_SENTINEL} متى الاختبار؟", "needs_response": True},
        ],
    )
    _write(
        fixtures,
        "real-moderation.jsonl",
        [
            {
                "text": _SENTINEL,
                "category": "SPAM_OR_AD",
                "needs_moderation": True,
                "tracked": "no-link-rule",
            },
            {"text": _SENTINEL, "category": "CHITCHAT", "needs_moderation": False},
        ],
    )
    shipped = tmp_path / "shipped"
    shipped.mkdir()
    _write(
        shipped,
        "attention_burst_fixtures.jsonl",
        [
            {
                "burst": [f"{_SENTINEL} السلام عليكم", f"{_SENTINEL} بس الرابط بايظ"],
                "needs_response": True,
                "expected_opener": "model",
            }
        ],
    )
    return attention_suite.discover_attention_sets(fixtures, shipped_dir=shipped)


def test_a_bad_line_is_refused_before_any_call(tmp_path: Path) -> None:
    specs = _attention_sets(tmp_path)
    _write(tmp_path / "fixtures", "real-attention.jsonl", [_attention(intent="unsure")])

    with pytest.raises(FixtureError):
        load_sets(specs)


async def test_every_read_set_is_judged_repeat_times_and_nothing_printed_carries_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    specs = _attention_sets(tmp_path)
    gateway = _ScriptedByText(_intent("asking"))

    results = await judge_sets(
        specs,
        load_sets(specs),
        repeat=2,
        judge=attention_suite.attention_judge(
            gateway,  # type: ignore[arg-type]
            instruction=_INSTRUCTION,
        ),
        detail=attention_suite.attention_detail,
    )
    out, err = capsys.readouterr()

    by_name = {result.spec.name: result for result in results}
    attention = by_name["real-attention.jsonl"]
    assert [spec.name for spec in specs] == [result.spec.name for result in results]
    assert len(attention.runs) == 2
    assert [row.line for row in attention.runs[1]] == [1, 2, 3, 4]
    assert attention.runs[0][1].error == "ModelTimeoutError"
    assert attention.runs[0][2].excluded == "acknowledgement"
    assert attention.runs[0][3].opener == "rule"
    assert len(attention.latencies_ms) == 2  # one answered call per run; no ack, rule or failure
    assert attention.label_classes == {1: "clear", 2: "clear", 3: "clear", 4: "clear"}
    a6 = by_name["real-moderation.jsonl"]
    assert a6.tracked == {1: "no-link-rule"}
    assert [row.violation for row in a6.first] == [True, False]
    assert a6.first[0].answered_asking
    burst = by_name["attention_burst_fixtures.jsonl"].first[0]
    assert (burst.opener, burst.opening_member) == ("model", 1)
    assert not by_name["fresh-attention.jsonl"].ran
    assert not by_name["attention_smoke_fixtures.jsonl"].ran
    # Per run: two attention calls (one fails), one A6 call, two burst members.
    assert len(gateway.calls) == 2 * 5
    assert {role for _, role in gateway.calls} == {"attention"}

    assert _SENTINEL not in out
    assert _SENTINEL not in err
    assert "== real-attention.jsonl (tuning) run 1 of 2 ==" in out
    assert "[OK] #1 expected=True intent=asking rule=declines opener=model" in out
    assert "[OK] #4 expected=True rule=opens opener=rule" in out
    assert "  ERROR #2: ModelTimeoutError" in err.splitlines()
    # The per-line detail is the first run's only.
    assert out.count("#1 expected=True intent=asking") == 1


async def test_the_moderation_suite_judges_through_the_smokes_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    _write(fixtures, "real-moderation.jsonl", [_moderation(), _moderation(text="FAIL")])
    specs = moderation_suite.discover_moderation_sets(fixtures, shipped_dir=tmp_path / "none")
    gateway = _ScriptedByText(
        _answer("SPAM_OR_AD", needs_response=False, needs_moderation=True, severity="medium")
    )

    results = await judge_sets(
        specs,
        load_sets(specs),
        repeat=1,
        judge=moderation_suite.moderation_judge(
            gateway,  # type: ignore[arg-type]
            prompt_version="classify_v2",
            floor=_FLOOR,
            threshold=_THRESHOLD,
        ),
        detail=moderation_suite.moderation_detail,
    )
    out, err = capsys.readouterr()

    [real, shipped, policy] = results
    assert [row.route for row in real.first] == ["incident", None]
    assert not shipped.ran and not policy.ran
    assert {role for _, role in gateway.calls} == {"moderation"}
    assert "[OK] #1 expected=SPAM_OR_AD/True predicted=SPAM_OR_AD/True" in out
    assert "  ERROR #2: ModelTimeoutError" in err.splitlines()
    assert _SENTINEL not in out + err
