"""Database connection and migration helpers."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "sql" / "001_schema.sql"


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and configure Postgres."
        )
    return url


def connect() -> psycopg.Connection:
    return psycopg.connect(get_database_url())


def apply_schema(conn: psycopg.Connection | None = None) -> None:
    own_conn = conn is None
    if own_conn:
        conn = connect()
    try:
        exists = conn.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'source_record'
            )
            """
        ).fetchone()[0]
        if exists:
            return
        sql = SCHEMA_PATH.read_text()
        conn.execute(sql)
        conn.commit()
    finally:
        if own_conn and conn is not None:
            conn.close()
