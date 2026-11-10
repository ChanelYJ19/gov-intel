"""Tests for ambiguous normalized company names."""

from __future__ import annotations

import unittest
from collections.abc import Sequence

from federal_intel.resolution import CompanyResolver


class _Rows:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows

    def fetchone(self) -> tuple[object, ...] | None:
        return ("Acme Inc.",) if self._rows else None


class _Connection:
    def __init__(self, aliases: Sequence[tuple[object, ...]] | None = None) -> None:
        self.aliases = list(
            aliases
            if aliases is not None
            else [
                (1, "Acme Inc."),
                (2, "Acme LLC"),
            ]
        )

    def execute(self, query: str, params: object = None) -> _Rows:
        del params
        if "SELECT company_id, name" in query:
            return _Rows(self.aliases)
        if "SELECT canonical_name FROM company" in query:
            return _Rows([("Acme Inc.",)])
        if "INSERT INTO company_alias" in query:
            return _Rows([])
        raise AssertionError(f"Unexpected query: {query}")


class NormalizedCollisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = CompanyResolver.__new__(CompanyResolver)
        self.resolver.conn = _Connection()
        self.resolver._exact = {}
        self.resolver._normalized = {}
        self.resolver._load_cache()

    def test_resolve_rejects_normalized_name_shared_by_multiple_companies(self) -> None:
        with self.assertRaisesRegex(ValueError, r"ambiguous normalized name.*1, 2"):
            self.resolver.resolve("Acme Corporation", source="test")

    def test_lookup_does_not_pick_a_company_from_normalized_collision(self) -> None:
        self.assertIsNone(self.resolver.lookup("Acme Corporation"))

    def test_cache_recomputes_normalized_names_from_alias_text(self) -> None:
        resolver = CompanyResolver.__new__(CompanyResolver)
        resolver.conn = _Connection([(3, "The Company Store Inc.")])
        resolver._exact = {}
        resolver._normalized = {}
        resolver._load_cache()

        self.assertIn("the company store", resolver._normalized)
        self.assertNotIn("the store", resolver._normalized)


if __name__ == "__main__":
    unittest.main()
