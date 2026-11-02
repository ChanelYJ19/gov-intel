#!/usr/bin/env python3
"""Weekly coverage scoreboard for the test-set companies."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report resolution coverage for a CSV of company names"
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Path to test-set CSV (default: fixtures/coverage_test_set.csv)",
    )
    args = parser.parse_args()

    from federal_intel.coverage import DEFAULT_TEST_SET, format_scoreboard, run_coverage

    path = args.csv or DEFAULT_TEST_SET
    if not path.exists():
        print(f"Test set not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        results = run_coverage(path)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(format_scoreboard(results))


if __name__ == "__main__":
    main()
