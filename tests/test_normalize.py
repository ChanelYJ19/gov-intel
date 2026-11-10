"""Tests for company-name normalization."""

from __future__ import annotations

import unittest

from federal_intel.normalize import normalize_company_name


class NormalizeCompanyNameTest(unittest.TestCase):
    def test_preserves_legal_words_inside_company_name(self) -> None:
        self.assertEqual(
            normalize_company_name("The Company Store Inc."),
            "the company store",
        )

    def test_keeps_legal_form_tokens_before_the_end(self) -> None:
        self.assertEqual(
            normalize_company_name("Acme Inc Holdings Inc."),
            "acme inc holdings",
        )

    def test_strips_dotted_legal_suffix_at_end(self) -> None:
        self.assertEqual(normalize_company_name("Acme L.L.C."), "acme")

    def test_strips_full_legal_suffix_at_end(self) -> None:
        self.assertEqual(
            normalize_company_name("Beta Technologies, Incorporated"),
            "beta technologies",
        )


if __name__ == "__main__":
    unittest.main()
