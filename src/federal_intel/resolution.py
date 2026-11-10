"""Company name resolution: exact, normalized, then fuzzy."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import psycopg
from rapidfuzz import fuzz

from federal_intel.normalize import normalize_company_name

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 92
REJECT_LOG_THRESHOLD = 85
NORMALIZED_CONFIDENCE = 0.95
EXACT_CONFIDENCE = 1.0


@dataclass(frozen=True)
class ResolutionResult:
    company_id: int
    confidence: float
    rule: str
    is_new: bool


@dataclass(frozen=True)
class LookupResult:
    company_id: int
    canonical_name: str
    confidence: float
    rule: str


class AmbiguousCompanyNameError(ValueError):
    """Raised when a name key points to more than one canonical company."""

    def __init__(self, name: str, rule: str, company_ids: set[int]) -> None:
        ids = sorted(company_ids)
        self.company_ids = tuple(ids)
        super().__init__(
            f"ambiguous {rule} for {name!r}; candidate company IDs: "
            + ", ".join(str(company_id) for company_id in ids)
        )


class CompanyResolver:
    """Resolve company names against existing aliases with tiered matching."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn
        self._exact: dict[str, set[int]] = {}
        self._normalized: dict[str, set[int]] = {}
        self._load_cache()
        self._ensure_fuzzy_index()

    def _ensure_fuzzy_index(self) -> None:
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_company_alias_norm_trgm
            ON company_alias USING gin (name_normalized gin_trgm_ops)
            """
        )

    def _load_cache(self) -> None:
        rows = self.conn.execute(
            """
            SELECT company_id, name
            FROM company_alias
            """
        ).fetchall()
        for company_id, name in rows:
            key_exact = name.strip().lower()
            normalized = normalize_company_name(name)
            self._exact.setdefault(key_exact, set()).add(company_id)
            self._normalized.setdefault(normalized, set()).add(company_id)

    def _log_resolution(
        self,
        *,
        source: str,
        source_key: str | None,
        raw_name: str,
        action: str,
        company_id: int | None,
        confidence: float | None,
        rule: str | None,
        detail: dict | None = None,
    ) -> None:
        import json

        self.conn.execute(
            """
            INSERT INTO resolution_log
                (source, source_key, raw_name, action, company_id, confidence, rule, detail)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                source,
                source_key,
                raw_name,
                action,
                company_id,
                confidence,
                rule,
                json.dumps(detail) if detail else None,
            ),
        )

    def _create_company(self, raw_name: str, source: str, source_key: str | None) -> int:
        canonical = raw_name.strip()
        row = self.conn.execute(
            """
            INSERT INTO company (canonical_name)
            VALUES (%s)
            RETURNING id
            """,
            (canonical,),
        ).fetchone()
        assert row is not None
        company_id = row[0]
        normalized = normalize_company_name(canonical)
        self.conn.execute(
            """
            INSERT INTO company_alias
                (company_id, name, name_normalized, source, confidence, rule)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (company_id, name_normalized, source) DO NOTHING
            """,
            (company_id, canonical, normalized, source, EXACT_CONFIDENCE, "new_company"),
        )
        self._exact.setdefault(canonical.lower(), set()).add(company_id)
        self._normalized.setdefault(normalized, set()).add(company_id)

        self._log_resolution(
            source=source,
            source_key=source_key,
            raw_name=raw_name,
            action="created_company",
            company_id=company_id,
            confidence=EXACT_CONFIDENCE,
            rule="new_company",
        )
        return company_id

    def _add_alias(
        self,
        company_id: int,
        raw_name: str,
        source: str,
        confidence: float,
        rule: str,
    ) -> None:
        normalized = normalize_company_name(raw_name)
        self.conn.execute(
            """
            INSERT INTO company_alias
                (company_id, name, name_normalized, source, confidence, rule)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (company_id, name_normalized, source) DO NOTHING
            """,
            (company_id, raw_name.strip(), normalized, source, confidence, rule),
        )
        key_exact = raw_name.strip().lower()
        self._exact.setdefault(key_exact, set()).add(company_id)
        self._normalized.setdefault(normalized, set()).add(company_id)

    def _fuzzy_candidates(self, normalized: str) -> list[tuple[int, str, str]]:
        """Return (company_id, alias_name, canonical_name) candidates via pg_trgm."""
        rows = self.conn.execute(
            """
            WITH ranked_aliases AS (
                SELECT
                    ca.company_id,
                    ca.name,
                    c.canonical_name,
                    GREATEST(
                        similarity(ca.name_normalized, %(q)s),
                        similarity(ca.name, %(q)s)
                    ) AS sim,
                    ROW_NUMBER() OVER (
                        PARTITION BY ca.company_id
                        ORDER BY GREATEST(
                            similarity(ca.name_normalized, %(q)s),
                            similarity(ca.name, %(q)s)
                        ) DESC, ca.id
                    ) AS alias_rank
                FROM company_alias ca
                JOIN company c ON c.id = ca.company_id
                WHERE ca.name_normalized %% %(q)s
                   OR ca.name %% %(q)s
            )
            SELECT company_id, name, canonical_name, sim
            FROM ranked_aliases
            WHERE alias_rank = 1
            ORDER BY sim DESC, company_id
            LIMIT 10
            """,
            {"q": normalized},
        ).fetchall()
        scored: list[tuple[int, str, str, float]] = []
        for company_id, alias_name, canonical_name, _sim in rows:
            score = fuzz.token_sort_ratio(normalized, normalize_company_name(alias_name))
            scored.append((company_id, alias_name, canonical_name, score))
        scored.sort(key=lambda item: item[3], reverse=True)
        return [(cid, alias, canonical) for cid, alias, canonical, _ in scored[:5]]

    def resolve(self, raw_name: str, *, source: str, source_key: str | None = None) -> ResolutionResult:
        name = raw_name.strip()
        if not name:
            raise ValueError("Cannot resolve empty company name")

        exact_key = name.lower()
        exact_ids = self._exact.get(exact_key, set())
        if len(exact_ids) > 1:
            raise AmbiguousCompanyNameError(name, "exact name", exact_ids)
        if exact_ids:
            company_id = next(iter(exact_ids))
            self._add_alias(company_id, name, source, EXACT_CONFIDENCE, "exact_name")
            return ResolutionResult(company_id, EXACT_CONFIDENCE, "exact_name", is_new=False)

        normalized = normalize_company_name(name)
        normalized_ids = self._normalized.get(normalized, set())
        if len(normalized_ids) > 1:
            raise AmbiguousCompanyNameError(name, "normalized name", normalized_ids)
        if normalized_ids:
            company_id = next(iter(normalized_ids))
            self._add_alias(company_id, name, source, NORMALIZED_CONFIDENCE, "normalized_name")
            return ResolutionResult(
                company_id, NORMALIZED_CONFIDENCE, "normalized_name", is_new=False
            )

        candidates = self._fuzzy_candidates(normalized)
        if candidates:
            best_id, best_alias, best_canonical = candidates[0]
            best_score = fuzz.token_sort_ratio(
                normalized, normalize_company_name(best_alias)
            )
            if best_score >= FUZZY_THRESHOLD:
                confidence = round(best_score / 100.0, 3)
                rule = "fuzzy_name"
                self._add_alias(best_id, name, source, confidence, rule)
                if confidence < NORMALIZED_CONFIDENCE:
                    self._log_resolution(
                        source=source,
                        source_key=source_key,
                        raw_name=name,
                        action="fuzzy_match",
                        company_id=best_id,
                        confidence=confidence,
                        rule=rule,
                        detail={"matched_canonical": best_canonical, "score": best_score},
                    )
                return ResolutionResult(best_id, confidence, rule, is_new=False)

            if best_score >= REJECT_LOG_THRESHOLD:
                self._log_resolution(
                    source=source,
                    source_key=source_key,
                    raw_name=name,
                    action="fuzzy_rejected",
                    company_id=None,
                    confidence=round(best_score / 100.0, 3),
                    rule="fuzzy_below_threshold",
                    detail={
                        "best_match": best_canonical,
                        "score": best_score,
                        "threshold": FUZZY_THRESHOLD,
                    },
                )

        company_id = self._create_company(name, source, source_key)
        return ResolutionResult(company_id, EXACT_CONFIDENCE, "new_company", is_new=True)

    def lookup(self, raw_name: str) -> LookupResult | None:
        """Read-only resolution for coverage queries; never creates companies."""
        name = raw_name.strip()
        if not name:
            return None

        exact_key = name.lower()
        exact_ids = self._exact.get(exact_key, set())
        if len(exact_ids) > 1:
            return None
        if exact_ids:
            return self._lookup_meta(next(iter(exact_ids)), EXACT_CONFIDENCE, "exact_name")

        normalized = normalize_company_name(name)
        normalized_ids = self._normalized.get(normalized, set())
        if len(normalized_ids) > 1:
            return None
        if normalized_ids:
            return self._lookup_meta(
                next(iter(normalized_ids)), NORMALIZED_CONFIDENCE, "normalized_name"
            )

        candidates = self._fuzzy_candidates(normalized)
        if candidates:
            best_id, best_alias, _best_canonical = candidates[0]
            best_score = fuzz.token_sort_ratio(
                normalized, normalize_company_name(best_alias)
            )
            if best_score >= FUZZY_THRESHOLD:
                confidence = round(best_score / 100.0, 3)
                return self._lookup_meta(best_id, confidence, "fuzzy_name")

        return None

    def _lookup_meta(self, company_id: int, confidence: float, rule: str) -> LookupResult:
        row = self.conn.execute(
            "SELECT canonical_name FROM company WHERE id = %s",
            (company_id,),
        ).fetchone()
        assert row is not None
        return LookupResult(company_id, row[0], confidence, rule)


def award_kind_from_program(program: str | None) -> str:
    if not program:
        return "sbir"
    upper = program.strip().upper()
    if upper == "STTR":
        return "sttr"
    return "sbir"
