"""CLI: download and load SBIR bulk awards into source_record."""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Load SBIR.gov bulk award CSV into source_record")
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Directory for downloaded CSV (default: data/)",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download the bulk file even if cached",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N rows (for testing)",
    )
    args = parser.parse_args()

    from pathlib import Path

    from federal_intel.loaders.sbir import run_load

    try:
        stats = run_load(
            data_dir=Path(args.data_dir),
            force_download=args.force_download,
            limit=args.limit,
        )
    except Exception as exc:
        logging.error("%s", exc)
        sys.exit(1)

    print("SBIR load complete:")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
