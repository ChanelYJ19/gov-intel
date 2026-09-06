"""Resolve SBIR source records into company + award edges."""

from __future__ import annotations

import logging

import psycopg

from federal_intel.loaders.sbir import SBIR_SOURCE
from federal_intel.normalize import parse_amount, parse_date
from federal_intel.resolution import CompanyResolver, award_kind_from_program

logger = logging.getLogger(__name__)


def _upsert_duns(
    conn: psycopg.Connection,
    company_id: int,
    duns: str | None,
    source: str,
) -> None:
    if not duns:
        return
    cleaned = duns.strip().strip("'\"")
    if not cleaned or cleaned.lower() in ("n/a", "none"):
        return
    conn.execute(
        """
        INSERT INTO company_identifier (company_id, kind, value, confidence, rule, source)
        VALUES (%s, 'duns', %s, 0.9, 'sbir_source_field', %s)
        ON CONFLICT (kind, value) DO NOTHING
        """,
        (company_id, cleaned, source),
    )


def _upsert_domain(
    conn: psycopg.Connection,
    company_id: int,
    website: str | None,
    source: str,
) -> None:
    if not website:
        return
    domain = website.strip().lower()
    for prefix in ("https://", "http://", "www."):
        if domain.startswith(prefix):
            domain = domain[len(prefix) :]
    domain = domain.split("/")[0]
    if not domain or "." not in domain:
        return
    conn.execute(
        """
        INSERT INTO company_identifier (company_id, kind, value, confidence, rule, source)
        VALUES (%s, 'domain', %s, 0.85, 'sbir_website_field', %s)
        ON CONFLICT (kind, value) DO NOTHING
        """,
        (company_id, domain, source),
    )


def resolve_pending_sbir_records(
    conn: psycopg.Connection,
    *,
    limit: int | None = None,
) -> dict[str, int]:
    resolver = CompanyResolver(conn)
    stats = {
        "records_processed": 0,
        "awards_created": 0,
        "companies_created": 0,
        "skipped_no_company": 0,
    }

    query = """
        SELECT sr.id, sr.source_key, sr.raw
        FROM source_record sr
        LEFT JOIN award a ON a.source_record_id = sr.id
        WHERE sr.source = %s AND a.id IS NULL
        ORDER BY sr.id
    """
    params: list = [SBIR_SOURCE]
    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)

    rows = conn.execute(query, params).fetchall()

    for record_id, source_key, raw in rows:
        stats["records_processed"] += 1
        company_name = (raw.get("Company") or "").strip()
        if not company_name:
            stats["skipped_no_company"] += 1
            continue

        result = resolver.resolve(
            company_name,
            source=SBIR_SOURCE,
            source_key=source_key,
        )
        if result.is_new:
            stats["companies_created"] += 1

        _upsert_duns(conn, result.company_id, raw.get("Duns"), SBIR_SOURCE)
        _upsert_domain(conn, result.company_id, raw.get("Company Website"), SBIR_SOURCE)

        conn.execute(
            """
            INSERT INTO award (
                company_id, kind, agency, program, phase, amount,
                start_date, end_date, source_record_id, confidence, rule
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_record_id) DO NOTHING
            """,
            (
                result.company_id,
                award_kind_from_program(raw.get("Program")),
                raw.get("Agency"),
                raw.get("Program"),
                raw.get("Phase"),
                parse_amount(raw.get("Award Amount")),
                parse_date(raw.get("Proposal Award Date")),
                parse_date(raw.get("Contract End Date")),
                record_id,
                result.confidence,
                result.rule,
            ),
        )
        stats["awards_created"] += 1

        if stats["records_processed"] % 5000 == 0:
            conn.commit()
            logger.info("Resolved %d records", stats["records_processed"])

    conn.commit()
    return stats


def run_resolve(*, limit: int | None = None) -> dict[str, int]:
    from federal_intel.db import connect

    with connect() as conn:
        return resolve_pending_sbir_records(conn, limit=limit)
