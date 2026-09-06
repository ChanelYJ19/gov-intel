"""CLI: apply database schema."""

from __future__ import annotations

import sys


def main() -> None:
    from federal_intel.db import apply_schema, connect

    try:
        with connect() as conn:
            apply_schema(conn)
        print("Schema ready.")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
