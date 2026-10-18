"""The link rule's incident source, and the advert guard's route reason.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-18

`docs/plan/telegram/tg-day-one-investigation-and-link-rule-plan.md` Step 1.

- `moderation_incidents.source` gains `'rule'`. A regular member's link opens an incident with no
  model and no operator.
- `moderation_incidents.rule_version` is set exactly on a rule incident
  (`ck_incident_rule_version`), as `attention_items.rule_version` is on a rule item. A new reading
  of the rule is a new version, so figures never pool two readings.
- `message_classifications.route_reason` gains `'no_contact_signal'` (R4b). A SPAM_OR_AD
  prediction with no link, phone, mention, forward or redacted contact is listed, not opened.

No `GRANT`: table-level privileges already cover a new column. Additive: no existing row is
touched, and every row already written satisfies the widened constraints.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_ROUTE_REASON_0007 = (
    "(route = 'possible_violation') = (route_reason IS NOT NULL) "
    "AND (route_reason IS NULL OR route_reason IN ('uncertain', 'inconsistent'))"
)
_ROUTE_REASON_0010 = (
    "(route = 'possible_violation') = (route_reason IS NOT NULL) "
    "AND (route_reason IS NULL OR route_reason IN "
    "('uncertain', 'inconsistent', 'no_contact_signal'))"
)


def upgrade() -> None:
    op.drop_constraint("ck_incident_source", "moderation_incidents", type_="check")
    op.create_check_constraint(
        "ck_incident_source", "moderation_incidents", "source IN ('operator', 'ai', 'rule')"
    )
    op.add_column(
        "moderation_incidents", sa.Column("rule_version", sa.SmallInteger(), nullable=True)
    )
    op.create_check_constraint(
        "ck_incident_rule_version",
        "moderation_incidents",
        "(source = 'rule') = (rule_version IS NOT NULL)",
    )

    op.drop_constraint(
        "ck_classification_route_reason", "message_classifications", type_="check"
    )
    op.create_check_constraint(
        "ck_classification_route_reason", "message_classifications", _ROUTE_REASON_0010
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_classification_route_reason", "message_classifications", type_="check"
    )
    op.create_check_constraint(
        "ck_classification_route_reason", "message_classifications", _ROUTE_REASON_0007
    )

    op.drop_constraint("ck_incident_rule_version", "moderation_incidents", type_="check")
    op.drop_column("moderation_incidents", "rule_version")
    op.drop_constraint("ck_incident_source", "moderation_incidents", type_="check")
    op.create_check_constraint(
        "ck_incident_source", "moderation_incidents", "source IN ('operator', 'ai')"
    )
