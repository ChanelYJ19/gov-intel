"""Regression tests for fuzzy company candidate ranking."""

from __future__ import annotations

import os
import unittest

import psycopg

from federal_intel.resolution import CompanyResolver


class FuzzyCandidateRankingTest(unittest.TestCase):
    def test_best_company_is_not_dropped_by_candidate_limit(self) -> None:
        database_url = os.environ.get("TEST_DATABASE_URL")
        if not database_url:
            self.skipTest("Set TEST_DATABASE_URL to run PostgreSQL integration tests")

        conn = psycopg.connect(database_url)
        self.addCleanup(conn.close)
        self.addCleanup(conn.rollback)
        conn.execute(
            """
            CREATE TEMP TABLE company (
                id BIGINT PRIMARY KEY,
                canonical_name TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TEMP TABLE company_alias (
                id BIGINT PRIMARY KEY,
                company_id BIGINT NOT NULL,
                name TEXT NOT NULL,
                name_normalized TEXT NOT NULL
            )
            """
        )

        query = "acme aerospace"
        for company_id in range(1, 11):
            alias = f"acme aerospace operations {company_id:02d}"
            conn.execute(
                "INSERT INTO company VALUES (%s, %s)",
                (company_id, alias),
            )
            conn.execute(
                "INSERT INTO company_alias VALUES (%s, %s, %s, %s)",
                (company_id, company_id, alias, alias),
            )

        # This is the strongest match, but its higher ID exposes a LIMIT applied
        # before global ranking.
        conn.execute("INSERT INTO company VALUES (11, 'Acme Aerospace')")
        conn.execute(
            "INSERT INTO company_alias VALUES (11, 11, 'Acme Aerospace', %s)",
            (query,),
        )

        resolver = CompanyResolver.__new__(CompanyResolver)
        resolver.conn = conn
        candidates = resolver._fuzzy_candidates(query)

        self.assertTrue(candidates)
        self.assertEqual(candidates[0][0], 11)


if __name__ == "__main__":
    unittest.main()
