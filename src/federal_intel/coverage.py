"""Coverage test scoreboard: resolve test-set companies against loaded data."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import psycopg

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

    @property
    def has_federal_signal(self) -> bool:
        return self.awards + self.patents + self.regulatory_events > 0


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
    total = len(results)

    lines: list[str] = []
    lines.append("=" * 100)
    lines.append("COVERAGE TEST SCOREBOARD")
    lines.append("=" * 100)
    header = (
        f"{'Query Name':<22} {'Resolved':<9} {'Confidence':<11} {'Rule':<16} "
        f"{'Awards':<7} {'Patents':<8} {'Reg':<5} Canonical / Match"
    )
    lines.append(header)
    lines.append("-" * 100)

    for row in results:
        conf = f"{row.confidence:.3f}" if row.confidence is not None else "-"
        rule = row.rule or "-"
        canonical = row.canonical_name or "-"
        if row.resolved and canonical != row.query_name:
            canonical = f"{canonical} (≠ query)"
        lines.append(
            f"{row.query_name:<22} "
            f"{'yes' if row.resolved else 'NO':<9} "
            f"{conf:<11} "
            f"{rule:<16} "
            f"{row.awards:<7} "
            f"{row.patents:<8} "
            f"{row.regulatory_events:<5} "
            f"{canonical}"
        )

    lines.append("-" * 100)
    lines.append(
        f"Summary: {resolved}/{total} resolved | "
        f"{with_signal}/{total} with federal signal (awards/patents/regulatory) | "
        f"v1 target: 17/20 resolved"
    )
    lines.append(
        f"Pass resolved: {'YES' if resolved >= 17 else 'NO'} | "
        f"Pass signal (Phase 1 SBIR only): {with_signal}/{total} with ≥1 award"
    )
    lines.append("=" * 100)
    return "\n".join(lines)
