"""Tests for the Telegram-token secret-scan rule (contracts/domain-boundary.md §7, D-TG-25).

Builds any sample token at runtime — a full-length literal in a tracked test file would fail the
very rule it tests. `scan_secrets.sh` only scans `git ls-files` output, which lists a tracked
file regardless of uncommitted working-tree edits, so a plant lands directly in a real tracked
file's *working-tree* content — no `git add`, no staging, nothing for the operator to do
(Constitution Principle IV). The original content is always restored in a `finally`.

FR-013, FR-014, SC-006.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCAN_SH = REPO_ROOT / "scripts" / "scan_secrets.sh"
PLANT_FILE = REPO_ROOT / "README.md"

PlantLine = Callable[[str], None]


def _run_scan() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCAN_SH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _sample_token() -> str:
    # Built, never a literal: 8-10 digits, ":", 35 characters — the shape the rule matches.
    return "8123456789:" + "A" * 35


@pytest.fixture
def planted_line() -> Iterator[PlantLine]:
    original = PLANT_FILE.read_text()

    def _plant(line: str) -> None:
        PLANT_FILE.write_text(original + "\n" + line + "\n")

    try:
        yield _plant
    finally:
        PLANT_FILE.write_text(original)


def test_token_shaped_value_in_tracked_md_is_reported(planted_line: PlantLine) -> None:
    planted_line(f"the token looks like {_sample_token()}")
    result = _run_scan()
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "README.md" in output
    assert "Telegram bot token" in output


def test_change_me_placeholder_is_not_flagged(planted_line: PlantLine) -> None:
    planted_line("TELEGRAM_BOT_TOKEN=CHANGE_ME_TELEGRAM_BOT_TOKEN")
    result = _run_scan()
    assert result.returncode == 0


def test_empty_assignment_is_not_flagged(planted_line: PlantLine) -> None:
    planted_line("TELEGRAM_BOT_TOKEN=")
    result = _run_scan()
    assert result.returncode == 0


def test_timestamp_is_not_flagged(planted_line: PlantLine) -> None:
    planted_line("the deploy finished at 12:34:56")
    result = _run_scan()
    assert result.returncode == 0


def test_the_regex_does_not_match_its_own_printed_form(planted_line: PlantLine) -> None:
    # contracts/domain-boundary.md §7: the rule's own regex, written out in prose, is safe to
    # document — checked, not assumed.
    planted_line(r"the shape is \d{8,10}:[A-Za-z0-9_-]{35}")
    result = _run_scan()
    assert result.returncode == 0
