"""T052 — `classify_message` runs on its own queue, `moderation_classify`, consumed only by the
dedicated `ai-classifier` service (one process, one thread); every other moderation actor stays on
`default`, consumed by `ai-worker` (`contracts/classification-pipeline.md` §1 Q3, FR-022).

⚠ Finding 4: every functional test passes with every actor sharing one queue while a busy model
stalls message processing — only the stack's own configuration shows the isolation is real.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import app.workers.tasks.moderation as moderation_tasks
import dramatiq
import yaml
from app.workers.tasks.moderation.classify_message import classify_message

_REPO_ROOT = Path(__file__).resolve().parents[5]
_COMPOSE_PATH = _REPO_ROOT / "infra" / "docker-compose.yml"


def _every_moderation_actor() -> dict[str, dramatiq.Actor]:
    """Every `dramatiq.Actor` module attribute across `app.workers.tasks.moderation`'s own
    submodules — imported by name rather than relying on `app.workers.main`'s side-effecting
    imports, so this test does not depend on import order elsewhere."""
    actors: dict[str, dramatiq.Actor] = {}
    for module_info in pkgutil.iter_modules(moderation_tasks.__path__):
        module = importlib.import_module(f"{moderation_tasks.__name__}.{module_info.name}")
        for name, value in vars(module).items():
            if isinstance(value, dramatiq.Actor):
                actors[name] = value
    return actors


def test_classify_message_is_on_its_own_queue() -> None:
    assert classify_message.queue_name == "moderation_classify"


def test_every_other_moderation_actor_stays_on_default() -> None:
    actors = _every_moderation_actor()
    assert "classify_message" in actors
    others = {name: actor for name, actor in actors.items() if name != "classify_message"}
    assert others, "expected at least one other moderation actor to compare against"
    for name, actor in others.items():
        assert actor.queue_name == "default", f"{name} is not on the default queue"


def test_compose_runs_ai_worker_on_default_and_ai_classifier_on_moderation_classify() -> None:
    compose = yaml.safe_load(_COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose["services"]

    ai_worker_command = services["ai-worker"]["command"]
    assert "--queues" in ai_worker_command
    assert ai_worker_command[ai_worker_command.index("--queues") + 1] == "default"

    ai_classifier = services["ai-classifier"]
    classifier_command = ai_classifier["command"]
    assert "--queues" in classifier_command
    assert (
        classifier_command[classifier_command.index("--queues") + 1] == "moderation_classify"
    )
    assert "--processes" in classifier_command
    assert classifier_command[classifier_command.index("--processes") + 1] == "1"
    assert "--threads" in classifier_command
    assert classifier_command[classifier_command.index("--threads") + 1] == "1"
