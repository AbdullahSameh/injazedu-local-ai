"""T052 — `classify_message` runs on its own queue, `moderation_classify`, consumed only by the
dedicated `ai-classifier` service (one process, one thread); every other moderation actor stays on
`default`, consumed by `ai-worker` (`contracts/classification-pipeline.md` §1 Q3, FR-022).

Amended by TG-M5.3 (T030, `specs/011-tg-m5-3-attention-judgement/contracts/attention-judgement.md`
§1 J2-J3, D-TG-187): `judge_attention` has its own queue, `moderation_attention`, consumed by the
same one-thread `ai-classifier`. Its lower priority number (0 against the classifier's 10) makes
Attention run first whenever both wait on that worker (research Finding 18). That ordering is the
current deployment policy, not a contract, so it is asserted here, beside the compose file that
carries it. Both model services receive `MODERATION_ATTENTION_PROMPT_VERSION`.

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
from app.workers.tasks.moderation.judge_attention import judge_attention

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


def test_judge_attention_is_on_its_own_queue() -> None:
    assert judge_attention.queue_name == "moderation_attention"


def test_attention_runs_before_a_waiting_classification() -> None:
    """Dramatiq runs a worker's fetched messages lowest priority number first (Finding 18)."""
    assert judge_attention.priority == 0
    assert classify_message.priority == 10
    assert judge_attention.priority < classify_message.priority


def test_every_other_moderation_actor_stays_on_default() -> None:
    actors = _every_moderation_actor()
    model_actors = {"classify_message", "judge_attention"}
    assert model_actors <= set(actors)
    others = {name: actor for name, actor in actors.items() if name not in model_actors}
    assert others, "expected at least one other moderation actor to compare against"
    for name, actor in others.items():
        assert actor.queue_name == "default", f"{name} is not on the default queue"


def _queues(command: list[str]) -> list[str]:
    """The queue names following `--queues`, up to the next flag."""
    queues: list[str] = []
    for arg in command[command.index("--queues") + 1 :]:
        if arg.startswith("--"):
            break
        queues.append(arg)
    return queues


def test_compose_runs_ai_worker_on_default_and_ai_classifier_on_both_model_queues() -> None:
    compose = yaml.safe_load(_COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose["services"]

    ai_worker_command = services["ai-worker"]["command"]
    assert "--queues" in ai_worker_command
    assert _queues(ai_worker_command) == ["default"]

    ai_classifier = services["ai-classifier"]
    classifier_command = ai_classifier["command"]
    assert "--queues" in classifier_command
    assert _queues(classifier_command) == ["moderation_attention", "moderation_classify"]
    assert "--processes" in classifier_command
    assert classifier_command[classifier_command.index("--processes") + 1] == "1"
    assert "--threads" in classifier_command
    assert classifier_command[classifier_command.index("--threads") + 1] == "1"


def test_both_model_services_receive_the_attention_instruction_setting() -> None:
    compose = yaml.safe_load(_COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose["services"]

    for service in ("ai-worker", "ai-classifier"):
        environment = services[service]["environment"]
        assert "MODERATION_ATTENTION_PROMPT_VERSION" in environment, service
        assert environment["MODERATION_ATTENTION_PROMPT_VERSION"] == (
            "${MODERATION_ATTENTION_PROMPT_VERSION:-}"
        ), service
