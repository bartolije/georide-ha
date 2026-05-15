"""Smoke test: every translations/<lang>.json mirrors en.json exactly.

Catches the case where a new label is added in en.json but a translation
file is forgotten. Languages that are intentionally untranslated should
copy the en.json keys with the English text (or be removed from the
directory).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_TRANSLATIONS = (
    Path(__file__).parent.parent / "custom_components" / "georide" / "translations"
)


def _flatten(d, prefix=""):
    out: set[str] = set()
    for key, value in d.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out |= _flatten(value, path)
        else:
            out.add(path)
    return out


@pytest.fixture(scope="module")
def reference_keys() -> set[str]:
    with (_TRANSLATIONS / "en.json").open() as f:
        return _flatten(json.load(f))


@pytest.mark.parametrize(
    "lang",
    [p.stem for p in sorted(_TRANSLATIONS.glob("*.json")) if p.stem != "en"],
)
def test_translation_matches_en_keys(reference_keys: set[str], lang: str):
    with (_TRANSLATIONS / f"{lang}.json").open() as f:
        keys = _flatten(json.load(f))
    missing = reference_keys - keys
    extra = keys - reference_keys
    assert not missing, f"{lang}.json is missing keys: {sorted(missing)}"
    assert not extra, f"{lang}.json has extra keys not in en: {sorted(extra)}"
