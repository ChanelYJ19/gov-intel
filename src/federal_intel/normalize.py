"""Company name normalization for entity resolution."""

from __future__ import annotations

import re

_SUFFIXES = (
    r"\bincorporated\b",
    r"\binc\.?\b",
    r"\bllc\.?\b",
    r"\bl\.?l\.?c\.?\b",
    r"\bcorp\.?\b",
    r"\bcorporation\b",
    r"\bco\.?\b",
    r"\bcompany\b",
    r"\bltd\.?\b",
    r"\blimited\b",
    r"\bplc\.?\b",
    r"\blp\.?\b",
    r"\bllp\.?\b",
    r"\bpllc\.?\b",
    r"\bpc\.?\b",
    r"\bpa\.?\b",
)

_SUFFIX_PATTERN = re.compile("|".join(_SUFFIXES), re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_MULTI_SPACE = re.compile(r"\s+")


def normalize_company_name(name: str) -> str:
    """Lowercase, strip legal suffixes and punctuation, collapse whitespace."""
    cleaned = name.strip().lower()
    cleaned = _NON_ALNUM.sub(" ", cleaned)
    cleaned = _SUFFIX_PATTERN.sub(" ", cleaned)
    cleaned = _MULTI_SPACE.sub(" ", cleaned).strip()
    return cleaned


def parse_amount(raw: str | None) -> float | None:
    if not raw:
        return None
    digits = raw.replace(",", "").replace("$", "").strip().strip("'\"")
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def parse_date(raw: str | None) -> str | None:
    """Return ISO date string YYYY-MM-DD or None."""
    if not raw or not raw.strip():
        return None
    value = raw.strip()
    # SBIR bulk file uses MM/DD/YYYY
    parts = value.split("/")
    if len(parts) == 3:
        month, day, year = parts
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return None
