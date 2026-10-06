"""TG-M5.2's benchmark fixture lines (`specs/010-tg-m5-2-classify-v3/data-model.md` §1, D-TG-177)
and the one per-fixture judgement the smokes and the qualification share (D-TG-178).

Two optional keys ride on a fixture line: `label_class` (`clear` by default, or `ambiguous`;
attention sets only) and `tracked` (`no-link-rule` or `label-review`; any set). Anything else is
refused, and the refusal names the set and the line, never the text. Lines are numbered as the
smokes number them: blank lines skipped, from 1.

The per-fixture judgement is the smokes' own path, extracted unchanged — normalise, the rule set,
eligibility, the model, `route_prediction` (live), `proposes_attention` — with the model replaced
by a stub here. Pure: no model runtime, no database, no network.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.application.gateway import GatewayError, ModelTimeoutError
from app.application.moderation.classification import (
    MessageClassificationResult,
    build_model_input,
)
from app.application.moderation.text import normalize
from app.scripts import smoke_attention, smoke_moderation
from app.scripts.qualify_moderation import (
    LABEL_CLASSES,
    TRACKED_DISPOSITIONS,
    TRACKED_LIMIT,
    FixtureError,
    SetSpec,
    _parse_args,
    discover_sets,
    judge_sets,
    load_fixture_lines,
    load_sets,
)

_SENTINEL = "SENTINEL-fixture-text-never-printed"
_SCRIPTS = Path(smoke_attention.__file__).resolve().parent
_FLOOR = Decimal("0.600")
_THRESHOLD = Decimal("0.850")


def _attention(**extra: Any) -> dict[str, Any]:
    return {"text": _SENTINEL, "needs_response": True, "category": "QUESTION_COURSE", **extra}


def _moderation(**extra: Any) -> dict[str, Any]:
    return {"text": _SENTINEL, "category": "SPAM_OR_AD", "needs_moderation": True, **extra}


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

    with pytest.raises(FixtureError) as caught:
        load_fixture_lines(path, "attention")

    message = str(caught.value)
    assert "real-attention.jsonl" in message
    assert "#2" in message
    assert "label_class" in message
    assert _SENTINEL not in message


def test_label_class_on_a_moderation_fixture_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "real-moderation.jsonl", [_moderation(label_class="clear")])

    with pytest.raises(FixtureError) as caught:
        load_fixture_lines(path, "moderation")

    message = str(caught.value)
    assert "real-moderation.jsonl" in message
    assert "#1" in message
    assert "label_class" in message
    assert _SENTINEL not in message


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

    with pytest.raises(FixtureError) as caught:
        load_fixture_lines(path, kind)

    message = str(caught.value)
    assert "shipped.jsonl" in message
    assert "#3" in message
    assert "tracked" in message
    assert _SENTINEL not in message


def test_an_untracked_line_carries_no_tracked_key(tmp_path: Path) -> None:
    path = _write(tmp_path, "set.jsonl", [_moderation()])

    [(_, fixture)] = load_fixture_lines(path, "moderation")

    assert "tracked" not in fixture


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

    with pytest.raises(FixtureError) as caught:
        load_fixture_lines(path, "attention")

    message = str(caught.value)
    assert "set.jsonl" in message
    assert "#2" in message
    assert _SENTINEL not in message


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

    with pytest.raises(FixtureError) as caught:
        load_fixture_lines(path, kind)

    assert "#1" in str(caught.value)
    assert _SENTINEL not in str(caught.value)


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


# --- the sets the qualification reads (data-model §2, contract §2) ----------------------------


def _touch(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("", encoding="utf-8")


def _shape(specs: list[SetSpec]) -> list[tuple[str, str, str, bool]]:
    return [(spec.name, spec.role, spec.kind, spec.path is not None) for spec in specs]


def test_every_set_is_found_in_reading_order(tmp_path: Path) -> None:
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
    _touch(
        shipped,
        "attention_smoke_fixtures.jsonl",
        "attention_smoke_heldout_fixtures.jsonl",
        "moderation_smoke_fixtures.jsonl",
        "moderation_smoke_policy_fixtures.jsonl",
    )

    specs = discover_sets(fixtures, shipped_dir=shipped)

    assert _shape(specs) == [
        ("real-attention-extra.jsonl", "tuning", "attention", True),
        ("real-attention.jsonl", "tuning", "attention", True),
        ("attention_smoke_fixtures.jsonl", "tuning", "attention", True),
        ("attention_smoke_heldout_fixtures.jsonl", "heldout", "attention", True),
        ("fresh-attention.jsonl", "fresh", "attention", True),
        ("real-moderation.jsonl", "moderation-real", "moderation", True),
        ("moderation_smoke_fixtures.jsonl", "moderation-shipped", "moderation", True),
        ("moderation_smoke_policy_fixtures.jsonl", "moderation-policy", "moderation", True),
    ]
    assert specs[0].path == fixtures / "real-attention-extra.jsonl"
    assert specs[2].path == shipped / "attention_smoke_fixtures.jsonl"


def test_a_missing_set_is_listed_without_a_path(tmp_path: Path) -> None:
    fixtures, shipped = tmp_path / "fixtures", tmp_path / "shipped"
    fixtures.mkdir()
    _touch(
        shipped,
        "attention_smoke_fixtures.jsonl",
        "moderation_smoke_fixtures.jsonl",
        "moderation_smoke_policy_fixtures.jsonl",
    )

    specs = discover_sets(fixtures, shipped_dir=shipped)

    assert _shape(specs) == [
        ("real-attention*.jsonl", "tuning", "attention", False),
        ("attention_smoke_fixtures.jsonl", "tuning", "attention", True),
        ("attention_smoke_heldout_fixtures.jsonl", "heldout", "attention", False),
        ("fresh-attention.jsonl", "fresh", "attention", False),
        ("real-moderation.jsonl", "moderation-real", "moderation", False),
        ("moderation_smoke_fixtures.jsonl", "moderation-shipped", "moderation", True),
        ("moderation_smoke_policy_fixtures.jsonl", "moderation-policy", "moderation", True),
    ]


def test_the_shipped_sets_default_to_the_scripts_directory(tmp_path: Path) -> None:
    specs = discover_sets(tmp_path)

    shipped = {spec.name: spec.path for spec in specs if spec.role != "heldout"}
    assert shipped["attention_smoke_fixtures.jsonl"] == _SCRIPTS / "attention_smoke_fixtures.jsonl"
    assert shipped["moderation_smoke_policy_fixtures.jsonl"] == (
        _SCRIPTS / "moderation_smoke_policy_fixtures.jsonl"
    )


# --- the per-fixture judgement (D-TG-178) -----------------------------------------------------


class _StubGateway:
    """Stands in for `Gateway`: records each structured request and its role, then answers with
    `answer` or raises `fail_with`. The judgement only ever calls `generate_structured`."""

    def __init__(
        self,
        answer: MessageClassificationResult | None = None,
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


async def _judge_attention(
    gateway: _StubGateway, fixture: dict[str, Any], *, line: int = 1, **kwargs: Any
) -> tuple[smoke_attention.AttentionRow, int | None]:
    return await smoke_attention.judge_attention_fixture(
        gateway,  # type: ignore[arg-type]
        fixture,
        line=line,
        prompt_version="classify_v2",
        floor=_FLOOR,
        threshold=_THRESHOLD,
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


async def test_attention_sends_the_named_instruction_on_the_moderation_role() -> None:
    gateway = _StubGateway(_answer())
    text = "  المحتوى ناقص عندي  "

    await _judge_attention(gateway, {"text": text, "needs_response": True})

    [(request, role)] = gateway.calls
    assert role == "moderation"
    assert request.messages == build_model_input(normalize(text), prompt_version="classify_v2")
    assert request.schema_model is MessageClassificationResult


async def test_attention_the_rule_set_has_the_first_word() -> None:
    gateway = _StubGateway(_answer(needs_response=False, category="OTHER"))

    row, latency_ms = await _judge_attention(
        gateway, {"text": "متى الاختبار؟", "needs_response": True}, line=3
    )

    assert row.line == 3
    assert row.rule_opens is True
    assert row.opener == "rule"
    assert row.predicted_needs_response is False
    assert latency_ms is not None


async def test_attention_the_model_proposes_when_the_rules_decline() -> None:
    gateway = _StubGateway(_answer("QUESTION_ACCESS", confidence=0.9))

    row, latency_ms = await _judge_attention(
        gateway,
        {"text": "المحتوى ناقص عندي", "needs_response": True, "category": "QUESTION_ACCESS"},
        line=2,
    )

    assert row.rule_opens is False
    assert row.model_proposes is True
    assert row.opener == "model"
    assert row.predicted_category == "QUESTION_ACCESS"
    assert row.predicted_needs_moderation is False
    assert row.confidence == 0.9
    assert row.route == "none"
    assert row.matched
    assert isinstance(latency_ms, int) and latency_ms >= 0


async def test_attention_an_acknowledgement_never_reaches_the_model() -> None:
    gateway = _StubGateway(_answer())

    row, latency_ms = await _judge_attention(gateway, {"text": "شكرا", "needs_response": False})

    assert gateway.calls == []
    assert row.excluded == "acknowledgement"
    assert row.opener == "excluded"
    assert latency_ms is None


async def test_attention_a_gateway_errors_detail_goes_only_to_the_reporter() -> None:
    reported: list[tuple[int, str]] = []
    gateway = _StubGateway(fail_with=ModelTimeoutError)

    row, latency_ms = await _judge_attention(
        gateway,
        {"text": "المحتوى ناقص عندي", "needs_response": True},
        line=5,
        report_error=lambda line, detail: reported.append((line, detail)),
    )

    assert row.error == "ModelTimeoutError"
    assert row.predicted_needs_response is None
    assert row.opener == "error"
    assert latency_ms is None
    assert reported == [(5, f"ModelTimeoutError: raw model output {_SENTINEL}")]
    assert _SENTINEL not in repr(row)


async def test_attention_an_out_of_range_confidence_is_an_error_never_a_prediction() -> None:
    reported: list[tuple[int, str]] = []
    gateway = _StubGateway(_answer(confidence=1.5))

    row, _ = await _judge_attention(
        gateway,
        {"text": "المحتوى ناقص عندي", "needs_response": True},
        report_error=lambda line, detail: reported.append((line, detail)),
    )

    assert row.error == "confidence_out_of_range"
    assert row.predicted_needs_response is None
    assert reported == [(1, "confidence_out_of_range")]


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


# --- the per-line format, the smokes' own (pinned so the extraction changes no byte) ----------


def test_the_attention_line_format_is_the_smokes() -> None:
    scored = smoke_attention.AttentionRow(
        line=3,
        expected_needs_response=False,
        expected_category=None,
        rule_opens=False,
        predicted_needs_response=True,
        predicted_category="QUESTION_COURSE",
        predicted_needs_moderation=False,
        confidence=0.95,
        route="none",
        model_proposes=True,
    )
    excluded = smoke_attention.AttentionRow(
        line=6,
        expected_needs_response=False,
        expected_category=None,
        rule_opens=False,
        excluded="acknowledgement",
    )

    assert smoke_attention.format_row(scored, 12) == (
        "[FP] #3 expected=False predicted=True category=QUESTION_COURSE confidence=0.95 "
        "route=none rule=declines opener=model latency_ms=12"
    )
    assert smoke_attention.format_row(excluded, None) == (
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


# --- the command: its arguments and its judging loop (contract §1 C1-C5) ------------------------


def test_the_profile_is_required() -> None:
    with pytest.raises(SystemExit) as caught:
        _parse_args(["--fixtures-dir", "/fixtures"])

    assert caught.value.code == 2


def test_the_prompt_must_be_in_the_allowlist() -> None:
    with pytest.raises(SystemExit) as caught:
        _parse_args(["--profile", "p", "--fixtures-dir", "/f", "--prompt", "classify_v9"])

    assert caught.value.code == 2


@pytest.mark.parametrize("repeat", ["0", "-1", "two"])
def test_repeat_must_be_a_positive_whole_number(repeat: str) -> None:
    with pytest.raises(SystemExit) as caught:
        _parse_args(["--profile", "p", "--fixtures-dir", "/f", "--repeat", repeat])

    assert caught.value.code == 2


def test_the_defaults() -> None:
    args = _parse_args(["--profile", "p", "--fixtures-dir", "/f"])

    assert (args.profile, args.fixtures_dir, args.prompt, args.repeat) == ("p", "/f", None, 2)


class _ScriptedByText(_StubGateway):
    """Answers every call, except that a message carrying `FAIL` times out — with the model's raw
    output, text included, in the exception's message."""

    async def generate_structured(self, request: Any, *, role: str) -> Any:
        self.calls.append((request, role))
        if "FAIL" in request.messages[-1].content:
            raise ModelTimeoutError(f"raw model output {_SENTINEL}", profile_name="stub")
        return SimpleNamespace(value=self.answer)


def _sets(tmp_path: Path) -> list[SetSpec]:
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
            }
        ],
    )
    shipped = tmp_path / "shipped"
    shipped.mkdir()
    return discover_sets(fixtures, shipped_dir=shipped)


def test_a_bad_line_is_refused_before_any_call(tmp_path: Path) -> None:
    specs = _sets(tmp_path)
    _write(tmp_path / "fixtures", "real-attention.jsonl", [_attention(label_class="unsure")])

    with pytest.raises(FixtureError):
        load_sets(specs)


async def test_every_present_set_is_judged_repeat_times_and_nothing_printed_carries_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    specs = _sets(tmp_path)
    gateway = _ScriptedByText(_answer("QUESTION_ACCESS"))

    results = await judge_sets(
        gateway,  # type: ignore[arg-type]
        specs,
        load_sets(specs),
        prompt_version="classify_v2",
        floor=_FLOOR,
        threshold=_THRESHOLD,
        repeat=2,
    )
    out, err = capsys.readouterr()

    by_name = {result.spec.name: result for result in results}
    attention = by_name["real-attention.jsonl"]
    assert [spec.name for spec in specs] == [result.spec.name for result in results]
    assert len(attention.runs) == 2
    assert [row.line for row in attention.runs[1]] == [1, 2, 3]
    assert attention.runs[0][1].error == "ModelTimeoutError"
    assert attention.runs[0][2].excluded == "acknowledgement"
    assert len(attention.latencies_ms) == 2  # one answered call per run; no ack, no failure
    assert attention.label_classes == {1: "clear", 2: "clear", 3: "clear"}
    assert by_name["real-moderation.jsonl"].tracked == {1: "no-link-rule"}
    assert not by_name["fresh-attention.jsonl"].ran
    assert not by_name["attention_smoke_fixtures.jsonl"].ran
    assert len(gateway.calls) == 2 * 3  # two attention calls and one moderation call, twice

    assert _SENTINEL not in out
    assert _SENTINEL not in err
    assert "== real-attention.jsonl (tuning) run 1 of 2 ==" in out
    assert "[OK] #1 expected=True predicted=True category=QUESTION_ACCESS" in out
    assert "  ERROR #2: ModelTimeoutError" in err.splitlines()
    # The per-line detail is the first run's only.
    assert out.count("#1 expected=True") == 1
