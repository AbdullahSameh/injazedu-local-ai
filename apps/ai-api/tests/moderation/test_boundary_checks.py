"""Planted-violation tests for the moderation domain boundary (contracts/domain-boundary.md).

Each test writes a real violation into a real file inside the scope the relevant
`scripts/check.sh` rule scans, runs the gate, and asserts it fails naming the file. The plant
is always removed in a `finally` — a test that leaves a violation behind poisons every later
run (FR-005, SC-002).
"""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
CHECK_SH = REPO_ROOT / "scripts" / "check.sh"
DOMAIN_ATTENTION = REPO_ROOT / "apps" / "ai-api" / "app" / "domain" / "moderation" / "attention.py"

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


def test_forward_rule_rejects_a_new_worker_actor_importing_assessment(plant: Plant) -> None:
    """TG-M3's new `_MOD_DIRS` entry (`app/workers/tasks/moderation/`) is exercised by the same
    check 1 the other moderation directories already are (FR-002, FR-003)."""
    probe = plant(
        "apps/ai-api/app/workers/tasks/moderation/_boundary_probe_forward.py",
        "from app.application.health_service import run_health_check\n\n_ = run_health_check\n",
    )
    result = _run_check()
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert probe.name in output
    assert "Architecture violation" in output


def test_check4_rejects_message_text_on_a_new_actors_logging_call(plant: Plant) -> None:
    """Check 4 (`contracts/domain-boundary.md` §5, FR-030, D-TG-28) had no test at all before this
    milestone — exercised here against one of TG-M3's own new actor directories, never previously
    covered by a planted violation."""
    probe = plant(
        "apps/ai-api/app/workers/tasks/moderation/_boundary_probe_logging.py",
        'import logging\n\nlogger = logging.getLogger(__name__)\noriginal_text = "sample"\n'
        'logger.info("opened %s", original_text)\n',
    )
    result = _run_check()
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert probe.name in output
    assert "Architecture violation" in output


def test_domain_attention_imports_nothing_but_the_standard_library() -> None:
    """`app/domain/moderation/attention.py`'s own docstring: no I/O, no clock, no session, no
    import outside the standard library (`plan.md`'s domain-purity rule, FR-073). Check 1's
    forward allowlist permits this file to import from six other `app.*` prefixes — it is a
    stricter rule than check.sh enforces mechanically, so it needs its own test rather than a
    planted `check.sh` violation."""
    tree = ast.parse(DOMAIN_ATTENTION.read_text(encoding="utf-8"), filename=str(DOMAIN_ATTENTION))
    stdlib_names = sys.stdlib_module_names

    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders.extend(
                alias.name for alias in node.names if alias.name.split(".")[0] not in stdlib_names
            )
        elif isinstance(node, ast.ImportFrom):
            if node.module is None or node.module.split(".")[0] not in stdlib_names:
                offenders.append(node.module or "<relative import>")

    assert offenders == [], f"non-stdlib import(s) in {DOMAIN_ATTENTION}: {offenders}"
