"""Coverage test scoreboard: resolve test-set companies against loaded data."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import psycopg

from federal_intel.loaders.sbir import SBIR_SOURCE
from federal_intel.resolution import CompanyResolver

DEFAULT_TEST_SET = Path(__file__).resolve().parents[2] / "fixtures" / "coverage_test_set.csv"


@dataclass
class CompanyCoverage:
    query_name: str
    domain: str | None
    notes: str | None
    resolved: bool
    company_id: int | None
    canonical_name: str | None
    confidence: float | None
    rule: str | None
    awards: int
    patents: int
    regulatory_events: int
    sbir_corpus_rows: int
    sbir_name_hint: str | None

    @property
    def has_federal_signal(self) -> bool:
        return self.awards + self.patents + self.regulatory_events > 0

    @property
    def diagnosis(self) -> str:
        if self.resolved:
            return "ok"
        if self.sbir_corpus_rows == 0:
            return "absent_from_sbir"
        return "in_sbir_unresolved"


def _normalize_domain(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    domain = raw.strip().lower()
    for prefix in ("https://", "http://", "www."):
        if domain.startswith(prefix):
            domain = domain[len(prefix) :]
    domain = domain.split("/")[0]
    return domain if domain and "." in domain else None


def _lookup_by_domain(conn: psycopg.Connection, domain: str) -> tuple[int, str, float, str] | None:
    row = conn.execute(
        """
        SELECT c.id, c.canonical_name, ci.confidence, ci.rule
        FROM company_identifier ci
        JOIN company c ON c.id = ci.company_id
        WHERE ci.kind = 'domain' AND ci.value = %s
        ORDER BY ci.confidence DESC
        LIMIT 1
        """,
        (domain,),
    ).fetchone()
    if not row:
        return None
    return row[0], row[1], float(row[2]), row[3]


def _edge_counts(conn: psycopg.Connection, company_id: int) -> tuple[int, int, int]:
    awards = conn.execute(
        "SELECT COUNT(*) FROM award WHERE company_id = %s",
        (company_id,),
    ).fetchone()[0]
    patents = conn.execute(
        "SELECT COUNT(*) FROM patent WHERE company_id = %s",
        (company_id,),
    ).fetchone()[0]
    events = conn.execute(
        "SELECT COUNT(*) FROM regulatory_event WHERE company_id = %s",
        (company_id,),
    ).fetchone()[0]
    return int(awards), int(patents), int(events)


def _sbir_corpus_stats(
    conn: psycopg.Connection,
    *,
    name: str,
    domain: str | None,
) -> tuple[int, str | None]:
    """Count SBIR rows matching company name or website; return top name hint."""
    normalized_domain = _normalize_domain(domain)
    params: list = [SBIR_SOURCE, f"%{name}%"]
    sql = f"""
        SELECT COUNT(*) FROM source_record
        WHERE source = %s AND (
            raw->>'Company' ILIKE %s
            {" OR raw->>'Company Website' ILIKE %s" if normalized_domain else ""}
        )
    """
    count_row = conn.execute(sql, tuple(params)).fetchone()
    count = int(count_row[0]) if count_row else 0

    hint_row = conn.execute(
        """
        SELECT raw->>'Company' AS company, COUNT(*) AS n
        FROM source_record
        WHERE source = %s AND raw->>'Company' ILIKE %s
        GROUP BY 1
        ORDER BY n DESC
        LIMIT 1
        """,
        (SBIR_SOURCE, f"%{name}%"),
    ).fetchone()
    hint = hint_row[0] if hint_row else None
    return count, hint


def load_test_set(path: Path) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(
                {
                    "name": (row.get("name") or "").strip(),
                    "domain": (row.get("domain") or "").strip() or None,
                    "notes": (row.get("notes") or "").strip() or None,
                }
            )
    return [r for r in rows if r["name"]]


def evaluate_company(
    conn: psycopg.Connection,
    resolver: CompanyResolver,
    *,
    name: str,
    domain: str | None,
    notes: str | None,
) -> CompanyCoverage:
    sbir_rows, sbir_hint = _sbir_corpus_stats(conn, name=name, domain=domain)

    company_id: int | None = None
    canonical: str | None = None
    confidence: float | None = None
    rule: str | None = None

    normalized_domain = _normalize_domain(domain)
    if normalized_domain:
        hit = _lookup_by_domain(conn, normalized_domain)
        if hit:
            company_id, canonical, confidence, rule = hit
            rule = f"domain:{rule or 'identifier'}"

    if company_id is None:
        hit = resolver.lookup(name)
        if hit:
            company_id = hit.company_id
            canonical = hit.canonical_name
            confidence = hit.confidence
            rule = hit.rule

    if company_id is None:
        return CompanyCoverage(
            query_name=name,
            domain=domain,
            notes=notes,
            resolved=False,
            company_id=None,
            canonical_name=None,
            confidence=None,
            rule=None,
            awards=0,
            patents=0,
            regulatory_events=0,
            sbir_corpus_rows=sbir_rows,
            sbir_name_hint=sbir_hint,
        )

    awards, patents, events = _edge_counts(conn, company_id)
    return CompanyCoverage(
        query_name=name,
        domain=domain,
        notes=notes,
        resolved=True,
        company_id=company_id,
        canonical_name=canonical,
        confidence=confidence,
        rule=rule,
        awards=awards,
        patents=patents,
        regulatory_events=events,
        sbir_corpus_rows=sbir_rows,
        sbir_name_hint=sbir_hint,
    )


def run_coverage(test_set_path: Path = DEFAULT_TEST_SET) -> list[CompanyCoverage]:
    from federal_intel.db import connect

    with connect() as conn:
        resolver = CompanyResolver(conn)
        results: list[CompanyCoverage] = []
        for row in load_test_set(test_set_path):
            results.append(
                evaluate_company(
                    conn,
                    resolver,
                    name=row["name"],  # type: ignore[arg-type]
                    domain=row["domain"],  # type: ignore[arg-type]
                    notes=row["notes"],  # type: ignore[arg-type]
                )
            )
        return results


def format_scoreboard(results: list[CompanyCoverage]) -> str:
    resolved = sum(1 for r in results if r.resolved)
    with_signal = sum(1 for r in results if r.has_federal_signal)
    absent = sum(1 for r in results if r.diagnosis == "absent_from_sbir")
    unresolved_in_sbir = sum(1 for r in results if r.diagnosis == "in_sbir_unresolved")
    total = len(results)

    lines: list[str] = []
    lines.append("=" * 110)
    lines.append("COVERAGE TEST SCOREBOARD (Phase 1: SBIR/STTR only)")
    lines.append("=" * 110)
    header = (
        f"{'Query Name':<20} {'Resolved':<9} {'Conf':<6} {'Rule':<18} "
        f"{'Awd':<5} {'SBIR':<5} {'Diag':<18} Match / hint"
    )
    lines.append(header)
    lines.append("-" * 110)

    for row in results:
        conf = f"{row.confidence:.2f}" if row.confidence is not None else "-"
        rule = (row.rule or "-")[:17]
        if row.resolved:
            match = row.canonical_name or "-"
            if match != row.query_name:
                match = f"{match} (≠ query)"
        elif row.sbir_name_hint and row.sbir_corpus_rows > 0:
            match = f"SBIR name: {row.sbir_name_hint[:40]}"
        else:
            match = "no SBIR row for name/domain"

        lines.append(
            f"{row.query_name:<20} "
            f"{'yes' if row.resolved else 'NO':<9} "
            f"{conf:<6} "
            f"{rule:<18} "
            f"{row.awards:<5} "
            f"{row.sbir_corpus_rows:<5} "
            f"{row.diagnosis:<18} "
            f"{match}"
        )

    lines.append("-" * 110)
    lines.append(
        f"Summary: {resolved}/{total} resolved | {with_signal}/{total} with ≥1 award | "
        f"{absent}/{total} absent from SBIR corpus | {unresolved_in_sbir}/{total} in SBIR but not linked"
    )
    lines.append(
        "Note: 17/20 resolved is a multi-source v1 target. On SBIR-only data, portfolio companies "
        "with no SBIR awards will stay unresolved until Phase 2 (USASpending) or other sources."
    )
    lines.append(
        f"Pass resolved (SBIR-only realistic): {'YES' if resolved >= 10 else 'NO'} at {resolved}/20 | "
        f"Full v1 target: {'YES' if resolved >= 17 else 'NO'}"
    )
    lines.append("=" * 110)
    return "\n".join(lines)
