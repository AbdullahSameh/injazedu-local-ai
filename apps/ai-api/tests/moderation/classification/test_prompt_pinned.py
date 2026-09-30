"""`classify_v1.md` is pinned by its SHA-256 (T024, `contracts/classification-pipeline.md` §2,
D-TG-136): a new wording is a new file and a new version, never an edit.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "app" / "prompts" / "moderation" / "classify_v1.md"
)
_PINNED_SHA256 = "d16fbf312868524837787b587af53b382a78f8927252e3cb150d67bf32d9e348"


def test_classify_v1_matches_its_pinned_hash() -> None:
    digest = hashlib.sha256(_PROMPT_PATH.read_bytes()).hexdigest()
    assert digest == _PINNED_SHA256, (
        "classify_v1.md has changed — its wording is pinned. Create classify_v2.md instead of "
        "editing this file, and bump prompt_version wherever it is stored."
    )
