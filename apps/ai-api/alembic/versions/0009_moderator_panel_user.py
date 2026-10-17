"""Moderator panel account: moderators.user_id and its one-account-per-moderator constraint.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-17

`docs/plan/side/panel-users-and-sorting-plan.md` §4. A moderator may optionally name the panel
account its person signs in with — a plain reference, nullable, set and cleared only from the
panel's Moderators form. **No FK to `users`**, matching D-TG-102 (`opened_by_user_id`) and TG-M3's
`closed_by_user_id`; panel accounts are never deleted from the panel, access is withdrawn with
`is_panel_operator`. `uq_moderators_user_id` keeps one account to at most one moderator (NULLs do
not collide). Linking grants and removes no access, and no Python path reads the column. Takes the
next free number, as D-TG-192 moved the roadmap's reservation on. No `GRANT` — table-level
privileges already cover a new column. Additive: no existing row is touched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("moderators", sa.Column("user_id", sa.BigInteger(), nullable=True))
    op.create_unique_constraint("uq_moderators_user_id", "moderators", ["user_id"])


def downgrade() -> None:
    op.drop_constraint("uq_moderators_user_id", "moderators", type_="unique")
    op.drop_column("moderators", "user_id")
