-- =====================================================
-- Migration 065: Change Request Workflow
-- =====================================================
-- Adds a change_request table for two-step edit/approval
-- workflow on financially sensitive fields. Editors propose,
-- approvers review and apply.
-- =====================================================

-- Audit action types (must run outside transaction)
ALTER TYPE audit_action_type ADD VALUE IF NOT EXISTS 'CHANGE_REQUESTED';
ALTER TYPE audit_action_type ADD VALUE IF NOT EXISTS 'CHANGE_APPROVED';
ALTER TYPE audit_action_type ADD VALUE IF NOT EXISTS 'CHANGE_REJECTED';

BEGIN;

-- 1. Status enum
DO $$ BEGIN
  CREATE TYPE change_request_status AS ENUM (
      'pending',
      'conflicted',
      'approved',
      'rejected',
      'cancelled',
      'superseded'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 2. Change request table
CREATE TABLE IF NOT EXISTS change_request (
    id                    BIGSERIAL PRIMARY KEY,
    organization_id       BIGINT NOT NULL REFERENCES organization(id),
    project_id            BIGINT NOT NULL REFERENCES project(id),

    -- What changed
    target_table          TEXT NOT NULL,
    target_id             BIGINT NOT NULL,
    field_name            TEXT NOT NULL,
    old_value             JSONB,
    new_value             JSONB NOT NULL,
    display_label         TEXT,
    policy_key            TEXT NOT NULL,

    -- Workflow
    change_request_status change_request_status NOT NULL DEFAULT 'pending',
    auto_approved         BOOLEAN NOT NULL DEFAULT false,

    -- Requester
    requested_by          UUID NOT NULL,
    requested_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    request_note          TEXT,

    -- Assignment (set at submission from project.default_approver_id or org fallback)
    assigned_approver_id  UUID,

    -- Review
    reviewed_by           UUID,
    reviewed_at           TIMESTAMPTZ,
    review_note           TEXT,

    -- Conflict detection
    base_updated_at       TIMESTAMPTZ,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Indexes
-- Fast lookup: pending requests for a project (dashboard badge)
CREATE INDEX IF NOT EXISTS idx_cr_pending_project
    ON change_request (organization_id, project_id)
    WHERE change_request_status = 'pending';

-- Prevent duplicate pending requests for the same field on the same row
CREATE UNIQUE INDEX IF NOT EXISTS idx_cr_unique_pending
    ON change_request (target_table, target_id, field_name)
    WHERE change_request_status = 'pending';

-- Approver's queue
CREATE INDEX IF NOT EXISTS idx_cr_approver
    ON change_request (assigned_approver_id)
    WHERE change_request_status = 'pending';

-- 4. Immutability trigger for terminal states
CREATE OR REPLACE FUNCTION prevent_cr_mutation()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.change_request_status IN ('approved', 'rejected', 'cancelled', 'superseded') THEN
        RAISE EXCEPTION 'Cannot modify a resolved change request';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cr_immutable ON change_request;
CREATE TRIGGER trg_cr_immutable
    BEFORE UPDATE ON change_request
    FOR EACH ROW EXECUTE FUNCTION prevent_cr_mutation();

-- 5. Add default_approver_id to project table
ALTER TABLE project ADD COLUMN IF NOT EXISTS default_approver_id UUID;

COMMIT;
