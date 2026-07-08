-- SarEmi DB Schema
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS institutions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    contact_name    TEXT,
    phone           TEXT,
    plan            TEXT NOT NULL DEFAULT 'basic',
    active          BOOLEAN NOT NULL DEFAULT true,
    baas_entity_id  TEXT,
    -- Entitlements del token: protocolos permitidos, blockchain on/off, tipos de documento
    config          JSONB NOT NULL DEFAULT '{"allowed_protocols": ["rest", "soap"], "blockchain_enabled": true, "allowed_document_types": ["*"]}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Migración para DBs existentes (idempotente)
ALTER TABLE institutions ADD COLUMN IF NOT EXISTS config JSONB NOT NULL
    DEFAULT '{"allowed_protocols": ["rest", "soap"], "blockchain_enabled": true, "allowed_document_types": ["*"]}';

CREATE TABLE IF NOT EXISTS api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id  UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
    key_hash        TEXT NOT NULL UNIQUE,
    key_prefix      TEXT NOT NULL,
    label           TEXT,
    active          BOOLEAN NOT NULL DEFAULT true,
    last_used_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    usage_count     BIGINT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS verification_logs (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_id       UUID REFERENCES institutions(id) ON DELETE SET NULL,
    document_type        TEXT NOT NULL DEFAULT 'document',
    status               TEXT NOT NULL DEFAULT 'processing',
    confidence_score     NUMERIC(5,3) NOT NULL DEFAULT 0,
    extracted_data       JSONB NOT NULL DEFAULT '{}',
    checks               JSONB NOT NULL DEFAULT '[]',
    conclusion           TEXT,
    warnings             JSONB NOT NULL DEFAULT '[]',
    processing_time_ms   INTEGER NOT NULL DEFAULT 0,
    document_hash        TEXT NOT NULL DEFAULT '',
    ip_address           TEXT,
    file_path            TEXT,
    original_filename    TEXT,
    client_reference_id  TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vl_institution ON verification_logs(institution_id);
CREATE INDEX IF NOT EXISTS idx_vl_status      ON verification_logs(status);
CREATE INDEX IF NOT EXISTS idx_vl_created_at  ON verification_logs(created_at DESC);

CREATE TABLE IF NOT EXISTS manual_reviews (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    verification_id  UUID NOT NULL REFERENCES verification_logs(id) ON DELETE CASCADE,
    decision         TEXT,
    notes            TEXT,
    assigned_to      TEXT,
    resolved_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_manual_review_verification UNIQUE (verification_id)
);

CREATE TABLE IF NOT EXISTS person_groups (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    notes           TEXT,
    institution_id  UUID REFERENCES institutions(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS person_group_members (
    group_id         UUID NOT NULL REFERENCES person_groups(id) ON DELETE CASCADE,
    verification_id  UUID NOT NULL REFERENCES verification_logs(id) ON DELETE CASCADE,
    PRIMARY KEY (group_id, verification_id)
);
