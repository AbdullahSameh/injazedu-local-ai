"""A moderator's 👀 reaction resolves an incident (TG-M4.1).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-21

`docs/plan/telegram/tg-eyes-reaction-resolution-plan.md` E1, amending
`specs/007-tg-m4-policy-incidents/contracts/incident-lifecycle.md` S4 and `data-model.md` §2.

- **`ck_actions_strength`**: a `reaction` row may now carry `confirmation` as well as
  `acknowledgement`. Every other kind keeps its one strength.
- **`ck_actions_reaction_confirmation`** (new): a confirming reaction row must have the standard
  👀 emoji among its added reactions, so a confirmation can never come from any other reaction.

The strength is decided at write time by `domain.incident.reaction_strength`; no existing row is
touched or reinterpreted, and neither view changes — the evidence view already passes each row's
own strength through and the state view already resolves on the earliest confirmation.

The downgrade restores the old constraint. It fails loudly while any confirming reaction exists,
rather than rewriting a recorded act.
"""

from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_OLD_STRENGTH = (
    "(action_type = 'reaction' AND action_strength = 'acknowledgement') OR "
    "(action_type IN ('ban', 'expulsion', 'restriction') "
    "AND action_strength = 'enforcement') OR "
    "(action_type = 'reversal' AND action_strength IS NULL) OR "
    "(action_type = 'panel_acknowledge' AND action_strength = 'acknowledgement') OR "
    "(action_type = 'panel_resolve' AND action_strength = 'confirmation') OR "
    "(action_type = 'panel_false_positive' AND action_strength IS NULL)"
)

_NEW_STRENGTH = (
    "(action_type = 'reaction' AND action_strength IN ('acknowledgement', 'confirmation')) OR "
    "(action_type IN ('ban', 'expulsion', 'restriction') "
    "AND action_strength = 'enforcement') OR "
    "(action_type = 'reversal' AND action_strength IS NULL) OR "
    "(action_type = 'panel_acknowledge' AND action_strength = 'acknowledgement') OR "
    "(action_type = 'panel_resolve' AND action_strength = 'confirmation') OR "
    "(action_type = 'panel_false_positive' AND action_strength IS NULL)"
)

_REACTION_CONFIRMATION = (
    "action_type <> 'reaction' OR action_strength <> 'confirmation' OR "
    "detail -> 'added' @> '[{\"type\": \"emoji\", \"emoji\": \"👀\"}]'::jsonb"
)


def upgrade() -> None:
    op.drop_constraint("ck_actions_strength", "moderation_actions", type_="check")
    op.create_check_constraint("ck_actions_strength", "moderation_actions", _NEW_STRENGTH)
    op.create_check_constraint(
        "ck_actions_reaction_confirmation", "moderation_actions", _REACTION_CONFIRMATION
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM moderation_actions
                       WHERE action_type = 'reaction' AND action_strength = 'confirmation') THEN
                RAISE EXCEPTION 'cannot downgrade 0012: a confirming (👀) reaction is recorded, '
                                'and a recorded act is never rewritten';
            END IF;
        END $$;
        """
    )
    op.drop_constraint("ck_actions_reaction_confirmation", "moderation_actions", type_="check")
    op.drop_constraint("ck_actions_strength", "moderation_actions", type_="check")
    op.create_check_constraint("ck_actions_strength", "moderation_actions", _OLD_STRENGTH)
