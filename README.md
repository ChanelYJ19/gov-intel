# Federal & Regulatory Intelligence Graph

Entity-resolution graph joining public federal funding, contract, IP, and regulatory records to private companies. Exposed as an MCP server (Phase 4) for investor AI assistants.

**Phase 1 (current):** SBIR/STTR bulk awards only.

## Design principles

- **Raw vs resolved:** `source_record` rows are immutable provenance; resolution lives in separate tables.
- **Non-destructive merges:** ambiguous matches become edges with confidence + rule, never overwrites.
- **Idempotent ingestion:** re-running loaders does not create duplicates.
- **Explicit SQL:** no ORM; boring SQL you can audit.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/) for dependency management
- PostgreSQL 16 with `pg_trgm` extension

## GitHub sync

If your GitHub clone is missing files (e.g. `coverage_test.py`), pull latest `main` from Cursor Origin and push to GitHub:

```bash
origin auth login
./scripts/sync_github.sh
uv sync
```

## Setup

```bash
# Create database (adjust credentials as needed)
sudo -u postgres psql -c "CREATE USER fedintel WITH PASSWORD 'fedintel' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE federal_intel OWNER fedintel;"

cp .env.example .env

uv sync
uv run init-db
```

## Phase 1: Load SBIR/STTR awards

Download the full bulk file (~290MB with abstracts) from sbir.gov and load into `source_record`:

```bash
uv run load-sbir
```

Options:

- `--force-download` — re-fetch the CSV even if cached in `data/`
- `--limit N` — process only the first N rows (for testing)

Then resolve companies and create award edges:

```bash
uv run resolve-sbir
```

Resolution order:

1. **Exact name** match (confidence 1.0)
2. **Normalized name** match — lowercase, strip Inc/LLC/Corp/punctuation (confidence 0.95)
3. **Fuzzy name** match via RapidFuzz, threshold 92 (confidence = score/100)
4. **New company** if no match; ambiguous near-misses are logged to `resolution_log`

## Schema

See `sql/001_schema.sql`. Core Phase 1 tables:

| Table | Purpose |
|-------|---------|
| `source_record` | Immutable raw JSON from each data source |
| `company` | Resolved canonical entities |
| `company_alias` | Name variants linked to companies |
| `company_identifier` | DUNS, UEI, domain, etc. |
| `award` | SBIR/STTR/grant/contract edges |
| `resolution_log` | Audit trail for ambiguous matches |

## Data source

SBIR bulk CSV: https://data.www.sbir.gov/awarddatapublic/award_data.csv

Do **not** use the web export (10,000 record cap) or the intermittently-down API.

## Phase 3: Coverage test scoreboard

Run weekly against the seeded test set (`fixtures/coverage_test_set.csv` — 20 companies):

```bash
uv run coverage-test
# or: uv run coverage_test.py
```

Custom CSV (columns: `name`, optional `domain`, optional `notes`):

```bash
uv run coverage-test --csv path/to/companies.csv
```

Reports per company: resolved or not, match confidence and rule, counts of awards/patents/regulatory events, and canonical name. Domain column uses `company_identifier` when present. v1 target: **17/20 resolved**.

## Roadmap

- **Phase 2:** USASpending + UEI resolution
- **Phase 4:** MCP server with seven query tools
- **Phase 5+:** NIH RePORTER, NSF, PatentsView, openFDA, ClinicalTrials.gov, SEC Form D
