"""D-TG-222: every word an alert shares with the panel is the panel's own Arabic.

`alert_render.GLOSSARY` is keyed by the panel's English string; each value must equal
`apps/ai-control/lang/ar.json[key]`, so an alert and the panel cannot drift. The second test pins
that every category, severity, opener and bot standing the renderer can meet has a glossary entry.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.application.moderation.alert_render import _OPENER_KEY, _VIA_KEY, GLOSSARY

_AR_JSON = Path(__file__).resolve().parents[5] / "apps" / "ai-control" / "lang" / "ar.json"


def test_every_glossary_word_equals_the_panels_arabic() -> None:
    panel = json.loads(_AR_JSON.read_text(encoding="utf-8"))

    mismatched = {
        key: (value, panel.get(key)) for key, value in GLOSSARY.items() if panel.get(key) != value
    }

    assert mismatched == {}, f"alert glossary differs from lang/ar.json: {mismatched}"


def test_every_value_the_renderer_meets_has_a_glossary_entry() -> None:
    categories = {"SPAM_OR_AD", "ABUSE", "OTHER"}  # ck_incident_category
    severities = {"low", "medium", "high"}  # ck_incident_severity
    standings = {"member", "administrator", "left", "kicked", "restricted"}
    expected = categories | severities | standings | set(_OPENER_KEY.values()) | set(
        _VIA_KEY.values()
    )

    assert expected - set(GLOSSARY) == set()
    assert set(_OPENER_KEY) == {"rule", "ai", "operator"}  # ck_incident_source
