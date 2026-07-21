-- Synapse Phase 1 — Initial Database Schema
-- PostgreSQL 16 + pgvector
--
-- Run order:
--   1. Create database: CREATE DATABASE synapse;
--   2. psql -d synapse -f 001_initial_schema.sql
--
-- Django Phase 3 will generate equivalent migrations from django_models.py.
-- This file is the canonical SQL reference and can be used for local dev bootstrap.

BEGIN;

-- ─── Extensions ──────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "vector";     -- pgvector
CREATE EXTENSION IF NOT EXISTS "btree_gist"; -- appointment exclusion constraint

-- ─── Clinic Management ───────────────────────────────────────────────────────

CREATE TABLE clinics (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                VARCHAR(64)  NOT NULL UNIQUE,
    name                VARCHAR(255) NOT NULL,
    email               VARCHAR(255) NOT NULL,
    phone               VARCHAR(20),
    address             JSONB        NOT NULL DEFAULT '{}',
    timezone            VARCHAR(50)  NOT NULL DEFAULT 'America/New_York',
    status              VARCHAR(20)  NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'suspended', 'onboarding')),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_clinics_status ON clinics (status);

CREATE TABLE widget_settings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(), 
    clinic_id       UUID NOT NULL UNIQUE REFERENCES clinics (id) ON DELETE CASCADE,
    configuration   JSONB NOT NULL DEFAULT '{}',
    -- Expected keys: widget, ai, booking, feature_flags
    -- Example:
    -- {
    --   "widget": {"primary_color": "#2563EB", "position": "bottom-right", "greeting": "...", "logo_url": "...", "allowed_origins": []},
    --   "ai": {"model": "gpt-4o-mini", "temperature": 0.3, "system_prompt_override": null},
    --   "booking": {"require_auth": true, "slot_duration_min": 30, "buffer_min": 5},
    --   "feature_flags": {"booking": true, "insurance": true, "rag": true, "doctor_search": true}
    -- }
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE clinic_business_hours (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id       UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    day_of_week     SMALLINT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6), -- 0=Monday
    open_time       TIME,
    close_time      TIME,
    is_closed       BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_clinic_business_hours_day UNIQUE (clinic_id, day_of_week),
    CONSTRAINT chk_clinic_hours_times CHECK (
        is_closed = true
        OR (open_time IS NOT NULL AND close_time IS NOT NULL AND close_time > open_time)
    )
);

CREATE INDEX idx_clinic_business_hours_clinic ON clinic_business_hours (clinic_id);

-- ─── Medical Information ─────────────────────────────────────────────────────

CREATE TABLE specialties (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id   UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    name        VARCHAR(100) NOT NULL,
    slug        VARCHAR(100) NOT NULL,
    description TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    is_deleted  BOOLEAN NOT NULL DEFAULT false,
    deleted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_specialty_clinic_slug UNIQUE (clinic_id, slug)
);

CREATE INDEX idx_specialties_clinic_active ON specialties (clinic_id, is_active)
    WHERE is_deleted = false;

CREATE TABLE doctors (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id               UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    full_name               VARCHAR(255) NOT NULL,
    title                   VARCHAR(50),
    bio                     TEXT,
    photo_url               VARCHAR(500),
    languages               VARCHAR[] NOT NULL DEFAULT '{en}',
    is_active               BOOLEAN NOT NULL DEFAULT true,
    is_accepting_patients   BOOLEAN NOT NULL DEFAULT true,
    metadata                JSONB NOT NULL DEFAULT '{}',
    is_deleted              BOOLEAN NOT NULL DEFAULT false,
    deleted_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_doctors_clinic_active ON doctors (clinic_id, is_active)
    WHERE is_deleted = false;
CREATE INDEX idx_doctors_clinic_accepting ON doctors (clinic_id, is_accepting_patients)
    WHERE is_active = true AND is_deleted = false;

CREATE TABLE doctor_specialties (
    doctor_id    UUID NOT NULL REFERENCES doctors (id) ON DELETE CASCADE,
    specialty_id UUID NOT NULL REFERENCES specialties (id) ON DELETE CASCADE,
    clinic_id    UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    PRIMARY KEY (doctor_id, specialty_id)
);

CREATE INDEX idx_doctor_specialties_clinic_specialty ON doctor_specialties (clinic_id, specialty_id);
CREATE INDEX idx_doctor_specialties_clinic_doctor ON doctor_specialties (clinic_id, doctor_id);

CREATE TABLE services (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id       UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    duration_min    SMALLINT NOT NULL DEFAULT 30,
    price_cents     INTEGER,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    is_deleted      BOOLEAN NOT NULL DEFAULT false,
    deleted_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_services_clinic_active ON services (clinic_id, is_active)
    WHERE is_deleted = false;

CREATE TABLE doctor_services (
    doctor_id   UUID NOT NULL REFERENCES doctors (id) ON DELETE CASCADE,
    service_id  UUID NOT NULL REFERENCES services (id) ON DELETE CASCADE,
    clinic_id   UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    PRIMARY KEY (doctor_id, service_id)
);

CREATE INDEX idx_doctor_services_clinic_service ON doctor_services (clinic_id, service_id);
CREATE INDEX idx_doctor_services_clinic_doctor ON doctor_services (clinic_id, doctor_id);

CREATE TABLE insurance_plans (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id       UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    provider_name   VARCHAR(255) NOT NULL,
    plan_name       VARCHAR(255),
    plan_type       VARCHAR(50),
    is_accepted     BOOLEAN NOT NULL DEFAULT true,
    notes           TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    is_deleted      BOOLEAN NOT NULL DEFAULT false,
    deleted_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_insurance_plans_clinic_accepted ON insurance_plans (clinic_id, is_accepted)
    WHERE is_deleted = false;

CREATE TABLE doctor_insurance (
    doctor_id           UUID NOT NULL REFERENCES doctors (id) ON DELETE CASCADE,
    insurance_plan_id   UUID NOT NULL REFERENCES insurance_plans (id) ON DELETE CASCADE,
    clinic_id           UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    PRIMARY KEY (doctor_id, insurance_plan_id)
);

CREATE INDEX idx_doctor_insurance_clinic_plan ON doctor_insurance (clinic_id, insurance_plan_id);
CREATE INDEX idx_doctor_insurance_clinic_doctor ON doctor_insurance (clinic_id, doctor_id);

CREATE TABLE doctor_schedules (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id           UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    doctor_id           UUID NOT NULL REFERENCES doctors (id) ON DELETE CASCADE,
    day_of_week         SMALLINT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    start_time          TIME NOT NULL,
    end_time            TIME NOT NULL CHECK (end_time > start_time),
    slot_duration_min   SMALLINT NOT NULL DEFAULT 30,
    is_active           BOOLEAN NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_doctor_schedules_lookup ON doctor_schedules (clinic_id, doctor_id, day_of_week);
CREATE INDEX idx_doctor_schedules_active ON doctor_schedules (clinic_id, doctor_id, is_active);

CREATE TABLE doctor_leaves (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id   UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    doctor_id   UUID NOT NULL REFERENCES doctors (id) ON DELETE CASCADE,
    start_at    TIMESTAMPTZ NOT NULL,
    end_at      TIMESTAMPTZ NOT NULL CHECK (end_at > start_at),
    reason      VARCHAR(255),
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_doctor_leaves_lookup ON doctor_leaves (clinic_id, doctor_id, start_at, end_at);
CREATE INDEX idx_doctor_leaves_active ON doctor_leaves (clinic_id, doctor_id, is_active);

-- ─── Patient System ──────────────────────────────────────────────────────────

CREATE TABLE patients (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id           UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    phone               VARCHAR(20) NOT NULL,
    email               VARCHAR(255),
    first_name          VARCHAR(100) NOT NULL,
    last_name           VARCHAR(100) NOT NULL,
    date_of_birth       DATE,
    preferred_language  VARCHAR(10) NOT NULL DEFAULT 'en',
    is_verified         BOOLEAN NOT NULL DEFAULT false,
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_patients_clinic_phone UNIQUE (clinic_id, phone)
);

CREATE UNIQUE INDEX uq_patients_clinic_email ON patients (clinic_id, email)
    WHERE email IS NOT NULL AND email <> '';

CREATE INDEX idx_patients_clinic_first_name ON patients (clinic_id, first_name);
CREATE INDEX idx_patients_clinic_last_name ON patients (clinic_id, last_name);

CREATE TABLE appointments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id           UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    doctor_id           UUID NOT NULL REFERENCES doctors (id) ON DELETE RESTRICT,
    patient_id          UUID NOT NULL REFERENCES patients (id) ON DELETE RESTRICT,
    service_id          UUID REFERENCES services (id) ON DELETE SET NULL,
    insurance_plan_id   UUID REFERENCES insurance_plans (id) ON DELETE SET NULL,
    start_time          TIMESTAMPTZ NOT NULL,
    end_time            TIMESTAMPTZ NOT NULL CHECK (end_time > start_time),
    status              VARCHAR(20) NOT NULL DEFAULT 'pending'
                            CHECK (status IN (
                                'pending', 'confirmed', 'cancelled',
                                'completed', 'no_show', 'rescheduled'
                            )),
    confirmation_code   VARCHAR(10) NOT NULL UNIQUE,
    notes               TEXT,
    source              VARCHAR(20) NOT NULL DEFAULT 'chatbot'
                            CHECK (source IN (
                                'chatbot', 'admin', 'phone', 'walk_in', 'import'
                            )),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_appointments_clinic_doctor_time ON appointments (clinic_id, doctor_id, start_time);
CREATE INDEX idx_appointments_clinic_patient ON appointments (clinic_id, patient_id);
CREATE INDEX idx_appointments_clinic_status_time ON appointments (clinic_id, status, start_time);

-- Prevent double-booking: overlapping slots blocked except cancelled/rescheduled
ALTER TABLE appointments ADD CONSTRAINT excl_appointments_no_overlap
    EXCLUDE USING gist (
        doctor_id WITH =,
        tstzrange(start_time, end_time) WITH &&
    )
    WHERE (status NOT IN ('cancelled', 'rescheduled'));

-- ─── AI Knowledge ────────────────────────────────────────────────────────────

CREATE TABLE documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id       UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    title           VARCHAR(255) NOT NULL,
    file_name       VARCHAR(255) NOT NULL,
    file_type       VARCHAR(50) NOT NULL,
    storage_path    VARCHAR(500) NOT NULL,
    file_size_bytes INTEGER,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'processing', 'indexed', 'failed')),
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    -- uploaded_by: nullable UUID until clinic admin users exist (Phase 4/8)
    uploaded_by     UUID,
    metadata        JSONB NOT NULL DEFAULT '{}',
    error_message   TEXT,
    is_deleted      BOOLEAN NOT NULL DEFAULT false,
    deleted_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_documents_clinic_status ON documents (clinic_id, status)
    WHERE is_deleted = false;
CREATE INDEX idx_documents_clinic_created ON documents (clinic_id, created_at)
    WHERE is_deleted = false;

CREATE TABLE knowledge_chunks (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id           UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    document_id         UUID NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    chunk_number        INTEGER NOT NULL,
    page_number         INTEGER,
    content             TEXT NOT NULL,
    token_count         INTEGER,
    embedding           vector(1536),
    embedding_model     VARCHAR(50) NOT NULL DEFAULT 'text-embedding-3-small',
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_chunk_document_number UNIQUE (document_id, chunk_number)
);

CREATE INDEX idx_knowledge_chunks_clinic_document ON knowledge_chunks (clinic_id, document_id);
CREATE INDEX idx_knowledge_chunks_document_page ON knowledge_chunks (document_id, page_number)
    WHERE page_number IS NOT NULL;

-- HNSW index for cosine similarity search
CREATE INDEX idx_knowledge_chunks_embedding_hnsw
    ON knowledge_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Full-text search for hybrid retrieval
CREATE INDEX idx_knowledge_chunks_content_fts
    ON knowledge_chunks
    USING gin (to_tsvector('english', content));

-- ─── Chat System ─────────────────────────────────────────────────────────────

CREATE TABLE chat_sessions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id               UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    patient_id              UUID REFERENCES patients (id) ON DELETE SET NULL,
    session_token           VARCHAR(64) NOT NULL UNIQUE,
    ip_hash                 VARCHAR(64),
    user_agent              VARCHAR(500),
    locale                  VARCHAR(10) NOT NULL DEFAULT 'en',
    conversation_context    JSONB NOT NULL DEFAULT '{}',
    is_authenticated        BOOLEAN NOT NULL DEFAULT false,
    status                  VARCHAR(20) NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'closed', 'escalated')),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at               TIMESTAMPTZ
);

CREATE INDEX idx_chat_sessions_clinic_status ON chat_sessions (clinic_id, status);
CREATE INDEX idx_chat_sessions_clinic_last_active ON chat_sessions (clinic_id, last_active_at);
CREATE INDEX idx_chat_sessions_clinic_patient ON chat_sessions (clinic_id, patient_id)
    WHERE patient_id IS NOT NULL;

CREATE TABLE chat_messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id           UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    session_id          UUID NOT NULL REFERENCES chat_sessions (id) ON DELETE CASCADE,
    role                VARCHAR(20) NOT NULL
                            CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    message_type        VARCHAR(20) NOT NULL DEFAULT 'text'
                            CHECK (message_type IN (
                                'text', 'tool_call', 'tool_result', 'system', 'error'
                            )),
    content             TEXT NOT NULL,
    -- metadata shape:
    -- {
    --   "intent": "BOOK_APPOINTMENT",
    --   "entities": {"doctor": "Rajat", "date": "Tomorrow"},
    --   "latency": 310,
    --   "tool_called": "check_availability"
    -- }
    metadata            JSONB NOT NULL DEFAULT '{}',
    token_count         INTEGER,
    sequence_number     INTEGER NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_message_session_sequence UNIQUE (session_id, sequence_number)
);

CREATE INDEX idx_chat_messages_session_created ON chat_messages (session_id, created_at);
CREATE INDEX idx_chat_messages_clinic_created ON chat_messages (clinic_id, created_at);
CREATE INDEX idx_chat_messages_session_type ON chat_messages (session_id, message_type);

-- ─── Authentication ──────────────────────────────────────────────────────────

CREATE TABLE otp_verifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id       UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    session_id      UUID NOT NULL REFERENCES chat_sessions (id) ON DELETE CASCADE,
    patient_id      UUID REFERENCES patients (id) ON DELETE SET NULL,
    phone           VARCHAR(20) NOT NULL,
    code_hash       VARCHAR(128) NOT NULL,
    attempts        SMALLINT NOT NULL DEFAULT 0,
    max_attempts    SMALLINT NOT NULL DEFAULT 3,
    expires_at      TIMESTAMPTZ NOT NULL,
    verified_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_otp_session_created ON otp_verifications (session_id, created_at);
CREATE INDEX idx_otp_clinic_phone_expires ON otp_verifications (clinic_id, phone, expires_at);

-- ─── Analytics ───────────────────────────────────────────────────────────────

CREATE TABLE ai_usage_logs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id           UUID NOT NULL REFERENCES clinics (id) ON DELETE CASCADE,
    session_id          UUID REFERENCES chat_sessions (id) ON DELETE SET NULL,
    message_id          UUID REFERENCES chat_messages (id) ON DELETE SET NULL,
    provider            VARCHAR(50) NOT NULL DEFAULT 'openai'
                            CHECK (provider IN ('openai', 'anthropic', 'gemini', 'cache')),
    operation           VARCHAR(50) NOT NULL,
    model               VARCHAR(50) NOT NULL,
    prompt_tokens       INTEGER NOT NULL DEFAULT 0,
    completion_tokens   INTEGER NOT NULL DEFAULT 0,
    total_tokens        INTEGER NOT NULL DEFAULT 0,
    latency_ms          INTEGER NOT NULL DEFAULT 0,
    cost_microcents     BIGINT NOT NULL DEFAULT 0,
    cached_response     BOOLEAN NOT NULL DEFAULT false,
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ai_usage_clinic_created ON ai_usage_logs (clinic_id, created_at);
CREATE INDEX idx_ai_usage_clinic_operation_created ON ai_usage_logs (clinic_id, operation, created_at);
CREATE INDEX idx_ai_usage_clinic_cached ON ai_usage_logs (clinic_id, cached_response, created_at);
CREATE INDEX idx_ai_usage_session_created ON ai_usage_logs (session_id, created_at)
    WHERE session_id IS NOT NULL;

-- ─── Updated_at Trigger ──────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_clinics_updated_at
    BEFORE UPDATE ON clinics FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_widget_settings_updated_at
    BEFORE UPDATE ON widget_settings FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_clinic_business_hours_updated_at
    BEFORE UPDATE ON clinic_business_hours FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_specialties_updated_at
    BEFORE UPDATE ON specialties FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_doctors_updated_at
    BEFORE UPDATE ON doctors FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_services_updated_at
    BEFORE UPDATE ON services FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_insurance_plans_updated_at
    BEFORE UPDATE ON insurance_plans FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_doctor_schedules_updated_at
    BEFORE UPDATE ON doctor_schedules FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_doctor_leaves_updated_at
    BEFORE UPDATE ON doctor_leaves FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_patients_updated_at
    BEFORE UPDATE ON patients FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_appointments_updated_at
    BEFORE UPDATE ON appointments FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_documents_updated_at
    BEFORE UPDATE ON documents FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
