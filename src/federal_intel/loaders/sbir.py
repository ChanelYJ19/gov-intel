"""SBIR.gov bulk award file loader."""

from __future__ import annotations

import csv
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.request import urlretrieve

import psycopg

logger = logging.getLogger(__name__)

SBIR_BULK_URL = "https://data.www.sbir.gov/awarddatapublic/award_data.csv"
SBIR_SOURCE = "sbir_gov_bulk"
DEFAULT_DATA_DIR = Path("data")


def sbir_record_url(agency_tracking_number: str) -> str:
    """Construct a stable reference URL for an individual award."""
    slug = agency_tracking_number.strip().replace(" ", "%20")
    return f"https://www.sbir.gov/sbirsearch/detail/{slug}"


def sbir_source_key(row: dict[str, Any]) -> str | None:
    """Derive a stable idempotency key from SBIR row fields."""
    tracking = (row.get("Agency Tracking Number") or "").strip()
    if tracking:
        return tracking
    contract = (row.get("Contract") or "").strip()
    company = (row.get("Company") or "").strip()
    award_date = (row.get("Proposal Award Date") or "").strip()
    if contract:
        return f"{contract}|{company}|{award_date}"
    return None


def row_to_json(row: dict[str, str]) -> dict[str, Any]:
    return {k: (v if v != "" else None) for k, v in row.items()}


def iter_sbir_rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield row


def download_sbir_bulk(dest: Path, force: bool = False) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        logger.info("Using cached SBIR bulk file at %s", dest)
        return dest
    logger.info("Downloading SBIR bulk file (~290MB) from %s", SBIR_BULK_URL)
    urlretrieve(SBIR_BULK_URL, dest)
    logger.info("Download complete: %s", dest)
    return dest


def insert_source_record(
    conn: psycopg.Connection,
    *,
    source_key: str,
    url: str,
    raw: dict[str, Any],
    fetched_at: datetime,
) -> int | None:
    row = conn.execute(
        """
        INSERT INTO source_record (source, source_key, fetched_at, url, raw)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (source, source_key) DO NOTHING
        RETURNING id
        """,
        (SBIR_SOURCE, source_key, fetched_at, url, json.dumps(raw)),
    ).fetchone()
    return row[0] if row else None


def load_sbir_csv(
    conn: psycopg.Connection,
    csv_path: Path,
    *,
    limit: int | None = None,
) -> dict[str, int]:
    fetched_at = datetime.now(UTC)
    stats = {"rows_read": 0, "inserted": 0, "skipped_no_key": 0, "skipped_duplicate": 0}

    for row in iter_sbir_rows(csv_path):
        stats["rows_read"] += 1
        if limit is not None and stats["rows_read"] > limit:
            stats["rows_read"] -= 1
            break

        source_key = sbir_source_key(row)
        if not source_key:
            stats["skipped_no_key"] += 1
            logger.warning("Skipping row without source key: %s", row.get("Company"))
            continue

        raw = row_to_json(row)
        url = sbir_record_url(source_key)
        record_id = insert_source_record(
            conn,
            source_key=source_key,
            url=url,
            raw=raw,
            fetched_at=fetched_at,
        )
        if record_id is None:
            stats["skipped_duplicate"] += 1
        else:
            stats["inserted"] += 1

        if stats["rows_read"] % 10000 == 0:
            conn.commit()
            logger.info("Processed %d rows (%d inserted)", stats["rows_read"], stats["inserted"])

    conn.commit()
    return stats


def run_load(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    force_download: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    from federal_intel.db import apply_schema, connect

    csv_path = data_dir / "award_data.csv"
    download_sbir_bulk(csv_path, force=force_download)

    with connect() as conn:
        apply_schema(conn)
        return load_sbir_csv(conn, csv_path, limit=limit)
