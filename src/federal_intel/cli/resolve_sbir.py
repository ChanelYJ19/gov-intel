"""CLI: resolve SBIR source records into companies and awards."""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Resolve SBIR source_record rows into company + award edges"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Resolve only the first N pending records (for testing)",
    )
    args = parser.parse_args()

    from federal_intel.pipeline.resolve_sbir import run_resolve

    try:
        stats = run_resolve(limit=args.limit)
    except Exception as exc:
        logging.error("%s", exc)
        sys.exit(1)

    print("SBIR resolution complete:")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
