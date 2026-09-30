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
DOMAIN_INCIDENT = REPO_ROOT / "apps" / "ai-api" / "app" / "domain" / "moderation" / "incident.py"
DOMAIN_CLASSIFICATION = (
    REPO_ROOT / "apps" / "ai-api" / "app" / "domain" / "moderation" / "classification.py"
)
EVIDENCE_MODULE = (
    REPO_ROOT / "apps" / "ai-api" / "app" / "application" / "moderation" / "evidence.py"
)
INCIDENTS_MODULE = (
    REPO_ROOT / "apps" / "ai-api" / "app" / "application" / "moderation" / "incidents.py"
)
METRICS_MODULE = REPO_ROOT / "apps" / "ai-api" / "app" / "application" / "moderation" / "metrics.py"
_MOD_DIRS = (
    REPO_ROOT / "apps" / "ai-api" / "app" / "domain" / "moderation",
    REPO_ROOT / "apps" / "ai-api" / "app" / "application" / "moderation",
    REPO_ROOT / "apps" / "ai-api" / "app" / "providers" / "telegram",
    REPO_ROOT / "apps" / "ai-api" / "app" / "workers" / "tasks" / "moderation",
)

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


def _non_stdlib_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
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
    return offenders


def test_domain_incident_imports_nothing_but_the_standard_library() -> None:
    """T067 (FR-080): `app/domain/moderation/incident.py`'s own docstring — no I/O, no clock, no
    session, no import outside the standard library, exactly as `attention.py`'s own rule. Check
    1's forward allowlist is looser than this, so it needs its own test rather than a planted
    `check.sh` violation."""
    offenders = _non_stdlib_imports(DOMAIN_INCIDENT)
    assert offenders == [], f"non-stdlib import(s) in {DOMAIN_INCIDENT}: {offenders}"


def test_evidence_incidents_and_metrics_import_no_telegram_client_or_model_gateway() -> None:
    """T067 (FR-080): TG-M4 records what moderators observably did with **zero AI** — `evidence.py`,
    `incidents.py` and `metrics.py` (which also carries TG-M3's own figures) never import the
    Telegram client the ingestion actor calls, nor any model/LLM gateway, even though check 1's
    allowlist would otherwise permit a moderation module to import `app.providers.telegram`. A
    stricter rule than check.sh enforces mechanically, so it needs its own test."""
    forbidden_prefixes = (
        "app.providers.telegram",
        "app.application.gateway",
        "app.domain.model_profile",
        "httpx",
        "ollama",
        "openai",
    )
    for module_path in (EVIDENCE_MODULE, INCIDENTS_MODULE, METRICS_MODULE):
        offenders = [
            name
            for name in _non_stdlib_imports(module_path)
            if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden_prefixes)
        ]
        assert offenders == [], f"forbidden import(s) in {module_path}: {offenders}"


def test_no_moderation_module_imports_the_model_runtime_directly() -> None:
    """T048 (pipeline N10, research Finding 3): every `.py` under the four moderation directories
    reaches a model only through `app.application.gateway` — never `app.providers.llm`, `ollama` or
    `openai` directly, and never `httpx` for anything but the Telegram Bot API (`app/providers/
    telegram/` is itself a provider, exactly as `scripts/check.sh`'s own httpx/ollama/openai check
    exempts all of `app/providers/`). `test_boundary_checks.py`'s own planted-violation tests
    already prove `scripts/check.sh` catches one file at a time; this test proves the rule holds
    across the whole tree as it stands today, not just against a single probe."""
    always_forbidden = ("app.providers.llm", "ollama", "openai")
    telegram_provider_dir = REPO_ROOT / "apps" / "ai-api" / "app" / "providers" / "telegram"
    offenders: dict[str, list[str]] = {}
    for mod_dir in _MOD_DIRS:
        for module_path in mod_dir.rglob("*.py"):
            forbidden_prefixes = always_forbidden
            if telegram_provider_dir not in module_path.parents:
                forbidden_prefixes = (*always_forbidden, "httpx")
            bad = [
                name
                for name in _non_stdlib_imports(module_path)
                if any(
                    name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden_prefixes
                )
            ]
            if bad:
                offenders[str(module_path.relative_to(REPO_ROOT))] = bad
    assert offenders == {}, f"forbidden model-runtime import(s): {offenders}"


def test_domain_classification_imports_nothing_but_the_standard_library_and_attention() -> None:
    """T048: `app/domain/moderation/classification.py`'s own docstring — pure, no I/O, no clock, no
    session, no import outside the standard library and `app.domain.moderation` (for the shared
    acknowledgement matcher, E8). This is the only definition of eligibility and routing (pipeline
    N7); a second, looser import surface would let it quietly grow a dependency check.sh's forward
    allowlist would otherwise permit but the module's own contract forbids."""
    offenders = [
        name
        for name in _non_stdlib_imports(DOMAIN_CLASSIFICATION)
        if not (name == "app.domain.moderation" or name.startswith("app.domain.moderation."))
    ]
    assert offenders == [], (
        f"non-stdlib, non-domain-moderation import(s) in {DOMAIN_CLASSIFICATION}: {offenders}"
    )
