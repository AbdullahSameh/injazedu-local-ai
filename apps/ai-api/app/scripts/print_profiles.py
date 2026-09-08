"""Print the model roster: name, role, model, endpoint, dim, active (FR-049).

The read-only answer to "what will the next call use?" Exempt from testing — pretty-printer,
not a safety mechanism (plan.md's Constitution Check).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import create_engine

from app.infrastructure.config import load_settings

_QUERY = text(
    "SELECT name, role, provider, model, base_url, dim, is_active "
    "FROM model_profiles ORDER BY role, name"
)

_COLUMNS = ("name", "role", "provider", "model", "endpoint", "dim", "active")


def _rows() -> list[tuple[str, ...]]:
    settings = load_settings()
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(_QUERY)
            return [
                (
                    row.name,
                    row.role,
                    row.provider,
                    row.model,
                    row.base_url or "—",
                    str(row.dim) if row.dim is not None else "—",
                    "yes" if row.is_active else "no",
                )
                for row in result
            ]
    finally:
        engine.dispose()


def _print_table(rows: list[tuple[str, ...]]) -> None:
    widths = [
        max(len(_COLUMNS[i]), *(len(row[i]) for row in rows)) if rows else len(_COLUMNS[i])
        for i in range(len(_COLUMNS))
    ]
    header = "  ".join(col.ljust(widths[i]) for i, col in enumerate(_COLUMNS))
    print(header)
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


def main() -> None:
    rows = _rows()
    if not rows:
        print("no model profiles — run `make seed-profiles`")
        return
    _print_table(rows)


if __name__ == "__main__":
    main()
