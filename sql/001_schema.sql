-- Phase 1 schema: source records + company resolution + awards
-- Raw and resolved layers are strictly separate.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Immutable provenance layer
CREATE TABLE source_record (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL,
    source_key  TEXT NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    url         TEXT,
    raw         JSONB NOT NULL,
    UNIQUE (source, source_key)
);

CREATE INDEX idx_source_record_source ON source_record (source);

-- Resolved entity layer
CREATE TABLE company (
    id              BIGSERIAL PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE company_alias (
    id              BIGSERIAL PRIMARY KEY,
    company_id      BIGINT NOT NULL REFERENCES company (id),
    name            TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    source          TEXT NOT NULL,
    confidence      REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    rule            TEXT NOT NULL,
    UNIQUE (company_id, name_normalized, source)
);

CREATE INDEX idx_company_alias_normalized ON company_alias (name_normalized);
CREATE INDEX idx_company_alias_name_trgm ON company_alias USING gin (name gin_trgm_ops);

CREATE TABLE company_identifier (
    id          BIGSERIAL PRIMARY KEY,
    company_id  BIGINT NOT NULL REFERENCES company (id),
    kind        TEXT NOT NULL CHECK (kind IN ('uei', 'cage', 'ein', 'domain', 'ticker', 'duns')),
    value       TEXT NOT NULL,
    confidence  REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    rule        TEXT NOT NULL,
    source      TEXT,
    UNIQUE (kind, value)
);

CREATE INDEX idx_company_identifier_company ON company_identifier (company_id);

-- Award edges (Phase 1: SBIR/STTR only)
CREATE TABLE award (
    id               BIGSERIAL PRIMARY KEY,
    company_id       BIGINT NOT NULL REFERENCES company (id),
    kind             TEXT NOT NULL CHECK (kind IN ('sbir', 'sttr', 'grant', 'contract')),
    agency           TEXT,
    program          TEXT,
    phase            TEXT,
    amount           NUMERIC,
    start_date       DATE,
    end_date         DATE,
    source_record_id BIGINT NOT NULL UNIQUE REFERENCES source_record (id),
    confidence       REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    rule             TEXT NOT NULL
);

CREATE INDEX idx_award_company ON award (company_id);
CREATE INDEX idx_award_kind ON award (kind);

-- Reserved for later phases (empty shells keep migration path clear)
CREATE TABLE patent (
    id               BIGSERIAL PRIMARY KEY,
    company_id       BIGINT NOT NULL REFERENCES company (id),
    patent_number    TEXT NOT NULL,
    title            TEXT,
    filed_date       DATE,
    published_date   DATE,
    assignee_raw     TEXT,
    source_record_id BIGINT REFERENCES source_record (id),
    confidence       REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    rule             TEXT NOT NULL,
    UNIQUE (patent_number)
);

CREATE TABLE regulatory_event (
    id               BIGSERIAL PRIMARY KEY,
    company_id       BIGINT NOT NULL REFERENCES company (id),
    kind             TEXT NOT NULL,
    identifier       TEXT NOT NULL,
    event_date       DATE,
    detail           JSONB,
    source_record_id BIGINT REFERENCES source_record (id),
    confidence       REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    rule             TEXT NOT NULL,
    UNIQUE (kind, identifier)
);

CREATE TABLE person (
    id   BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    UNIQUE (name)
);

CREATE TABLE person_company (
    id          BIGSERIAL PRIMARY KEY,
    person_id   BIGINT NOT NULL REFERENCES person (id),
    company_id  BIGINT NOT NULL REFERENCES company (id),
    role        TEXT NOT NULL CHECK (role IN ('founder', 'pi', 'inventor', 'other')),
    confidence  REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    rule        TEXT NOT NULL,
    source      TEXT,
    UNIQUE (person_id, company_id, role)
);

-- Audit trail for ambiguous resolution decisions
CREATE TABLE resolution_log (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    source      TEXT NOT NULL,
    source_key  TEXT,
    raw_name    TEXT NOT NULL,
    action      TEXT NOT NULL,
    company_id  BIGINT REFERENCES company (id),
    confidence  REAL,
    rule        TEXT,
    detail      JSONB
);

CREATE INDEX idx_resolution_log_created ON resolution_log (created_at DESC);
