"""Qualification, version 2 (`specs/011-tg-m5-3-attention-judgement/contracts/qualification.md`,
D-TG-194): a task-agnostic core (`core.py`) and one suite per task (`attention.py`,
`moderation.py`), run as `python -m app.scripts.qualification --task attention|moderation`.

A composition root, like the smokes it shares its per-fixture judgements with. It writes nothing
and never prints a fixture's text.
"""
