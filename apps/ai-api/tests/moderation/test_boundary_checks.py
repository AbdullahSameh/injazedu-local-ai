"""Planted-violation tests for the moderation domain boundary (contracts/domain-boundary.md).

Each test writes a real violation into a real file inside the scope the relevant
`scripts/check.sh` rule scans, runs the gate, and asserts it fails naming the file. The plant
is always removed in a `finally` — a test that leaves a violation behind poisons every later
run (FR-005, SC-002).
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
CHECK_SH = REPO_ROOT / "scripts" / "check.sh"

Plant = Callable[[str, str], Path]


def _run_check() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(CHECK_SH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def plant() -> Iterator[Plant]:
    """Writes one throwaway module at a repo-relative path; always removes it afterward."""
    written: list[Path] = []

    def _plant(rel_path: str, content: str) -> Path:
        full = REPO_ROOT / rel_path
        assert not full.exists(), f"refusing to overwrite an existing file: {full}"
        full.write_text(content)
        written.append(full)
        return full

    try:
        yield _plant
    finally:
        for full in written:
            full.unlink(missing_ok=True)


def test_forward_rule_rejects_moderation_importing_assessment(plant: Plant) -> None:
    probe = plant(
        "apps/ai-api/app/application/moderation/_boundary_probe_forward.py",
        "from app.application.health_service import run_health_check\n\n_ = run_health_check\n",
    )
    result = _run_check()
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert probe.name in output
    assert "Architecture violation" in output


def test_reverse_rule_rejects_assessment_importing_moderation(plant: Plant) -> None:
    probe = plant(
        "apps/ai-api/app/application/_boundary_probe_reverse.py",
        "from app.application.moderation.text import normalize\n\n_ = normalize\n",
    )
    result = _run_check()
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert probe.name in output
    assert "Architecture violation" in output


def test_telegram_sdk_rejected_outside_provider(plant: Plant) -> None:
    probe = plant(
        "apps/ai-api/app/domain/moderation/_boundary_probe_sdk.py",
        "import telegram\n\n_ = telegram\n",
    )
    result = _run_check()
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert probe.name in output
    assert "Architecture violation" in output
