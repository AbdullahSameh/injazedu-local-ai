"""Every moderation instruction is pinned by its SHA-256 (T024, `contracts/classification-
pipeline.md` §2 and §2a, D-TG-136, D-TG-163): a new wording is a new file and a new version, never
an edit. The selectable versions, the files on disk and the pinned hashes are one and the same set
— no instruction can be sent that is not pinned, and no file can sit beside them unpinned.

TG-M5.3 (D-TG-189, research Finding 17) adds a second family. `app/prompts/moderation/` holds the
classification instructions (`classify_*`, allowlist `PROMPT_VERSIONS`, pins `_PINNED_SHA256`) and
the attention instructions (allowlist `ATTENTION_PROMPT_VERSIONS`, pins
`_PINNED_ATTENTION_SHA256`). Every file is in exactly one allowlist, and each allowlist equals its
pinned set. `attention_v1` was frozen on 2026-10-07 (T074).

Every classification instruction also ends its needs_response line with the sentence TG-M5.1's G4
rests on (TG-M5.2, `specs/010-tg-m5-2-classify-v3/contracts/classify-v3.md` V4): a future
instruction that drops it fails here. That test reads the `classify_*` files only.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from app.application.moderation.classification import PROMPT_VERSIONS
from app.infrastructure.config import ATTENTION_PROMPT_VERSIONS

_PROMPT_DIR = Path(__file__).resolve().parents[3] / "app" / "prompts" / "moderation"
_PINNED_SHA256 = {
    "classify_v1": "d16fbf312868524837787b587af53b382a78f8927252e3cb150d67bf32d9e348",
    "classify_v2": "bf5ec2ce00ee0f01204515fd073ebbddcd17f190f33300569be2872a1e63aab0",
}
# The frozen `attention_v1.md`, its allowlist entry and its pin landed in one change (D-TG-189,
# T074, 2026-10-07). A new wording is a new file and a new version, never an edit of this one.
_PINNED_ATTENTION_SHA256: dict[str, str] = {
    "attention_v1": "a55308ca8cd1b3371c607120d5a076db6956eb315bd6a1c0b065396ee578748a",
}

_G4_SENTENCE = "Always false for SPAM_OR_AD, ABUSE and CHITCHAT."


@pytest.mark.parametrize("version", sorted(_PINNED_SHA256))
def test_each_instruction_matches_its_pinned_hash(version: str) -> None:
    digest = hashlib.sha256((_PROMPT_DIR / f"{version}.md").read_bytes()).hexdigest()
    assert digest == _PINNED_SHA256[version], (
        f"{version}.md has changed — its wording is pinned. Create the next classify_vN.md "
        "instead of editing this file, and add it to ModerationPromptVersion."
    )


@pytest.mark.parametrize("version", sorted(_PINNED_ATTENTION_SHA256))
def test_each_attention_instruction_matches_its_pinned_hash(version: str) -> None:
    digest = hashlib.sha256((_PROMPT_DIR / f"{version}.md").read_bytes()).hexdigest()
    assert digest == _PINNED_ATTENTION_SHA256[version], (
        f"{version}.md has changed — its wording is pinned. Create the next attention_vN.md "
        "instead of editing this file, and add it to ATTENTION_PROMPT_VERSIONS."
    )


def test_selectable_versions_files_and_pins_are_one_set() -> None:
    files = {path.stem for path in _PROMPT_DIR.glob("*.md")}

    for stem in sorted(files):
        families = (stem in PROMPT_VERSIONS) + (stem in ATTENTION_PROMPT_VERSIONS)
        assert families == 1, (
            f"{stem}.md must be in exactly one of PROMPT_VERSIONS and ATTENTION_PROMPT_VERSIONS"
        )
    assert set(PROMPT_VERSIONS) == set(_PINNED_SHA256)
    assert set(ATTENTION_PROMPT_VERSIONS) == set(_PINNED_ATTENTION_SHA256)
    assert files == set(_PINNED_SHA256) | set(_PINNED_ATTENTION_SHA256)


@pytest.mark.parametrize("version", sorted(_PINNED_SHA256))
def test_every_instruction_ends_its_needs_response_line_with_the_g4_sentence(
    version: str,
) -> None:
    text = (_PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")
    (needs_response_line,) = [
        line for line in text.splitlines() if line.startswith("- needs_response:")
    ]

    assert needs_response_line.endswith(" " + _G4_SENTENCE)
