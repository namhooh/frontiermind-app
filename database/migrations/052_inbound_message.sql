-- Migration: 052_inbound_message.sql
-- Description: Unified inbound_message model (Combined Expand + Contract)
-- Version: v8.3
-- Date: 2026-03-04
-- Depends on: 051_org_email_address.sql, 032_email_notification_engine.sql
--
-- Strategy: Combined expand/contract migration in two transaction blocks.
-- Phase A: Create new tables, backfill from submission_response, add FKs, verify counts.
-- Phase B: Drop submission_response table, legacy columns, policies, and indexes.

BEGIN;

-- =============================================================================
-- SECTION 0: RENAME email_log → outbound_message
-- =============================================================================

ALTER TABLE email_log RENAME TO outbound_message;

-- Rename FK column on submission_token (created in migration 032)
ALTER TABLE submission_token RENAME COLUMN email_log_id TO outbound_message_id;

-- Rename indexes
ALTER INDEX idx_email_log_org_created RENAME TO idx_outbound_msg_org_created;
ALTER INDEX idx_email_log_schedule RENAME TO idx_outbound_msg_schedule;
ALTER INDEX idx_email_log_invoice RENAME TO idx_outbound_msg_invoice;
ALTER INDEX idx_email_log_status RENAME TO idx_outbound_msg_status;
ALTER INDEX idx_email_log_ses_message RENAME TO idx_outbound_msg_ses_message;

-- Rename RLS policies
ALTER POLICY email_log_select_policy ON outbound_message RENAME TO outbound_message_select_policy;
ALTER POLICY email_log_service_policy ON outbound_message RENAME TO outbound_message_service_policy;

-- =============================================================================
-- SECTION 1: ENUM TYPE + INBOUND_MESSAGE TABLE
-- =============================================================================

CREATE TYPE inbound_message_status AS ENUM (
    'received', 'pending_review', 'approved', 'rejected',
    'noise', 'auto_processed', 'failed'
);

CREATE TABLE inbound_message (
    id                  BIGSERIAL PRIMARY KEY,
    organization_id     BIGINT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,

    -- Channel discriminator
    channel             VARCHAR(20) NOT NULL,

    -- Email-specific fields
    subject             TEXT,
    body_text           TEXT,
    raw_headers         JSONB,
    ses_message_id      VARCHAR(255),
    in_reply_to         VARCHAR(255),
    references_chain    TEXT[],
    s3_raw_path         TEXT,

    -- Token-specific fields
    submission_token_id BIGINT REFERENCES submission_token(id),

    -- Common fields
    response_data       JSONB DEFAULT '{}',
    sender_email        VARCHAR(320),
    sender_name         VARCHAR(255),
    ip_address          INET,

    -- Linking
    invoice_header_id   BIGINT REFERENCES invoice_header(id) ON DELETE SET NULL,
    project_id          BIGINT REFERENCES project(id) ON DELETE SET NULL,
    counterparty_id     BIGINT REFERENCES counterparty(id) ON DELETE SET NULL,
    outbound_message_id BIGINT REFERENCES outbound_message(id),
    customer_contact_id BIGINT REFERENCES customer_contact(id),

    -- Attachment summary
    attachment_count    INTEGER DEFAULT 0,

    -- Processing state
    inbound_message_status inbound_message_status NOT NULL DEFAULT 'received',
    classification_reason VARCHAR(255),
    failed_reason       TEXT,
    reviewed_by         UUID REFERENCES auth.users(id),
    reviewed_at         TIMESTAMPTZ,

    -- Legacy backfill tracking (dropped in Phase B below)
    legacy_submission_response_id BIGINT UNIQUE,

    -- Audit
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_inbound_channel CHECK (channel IN ('email', 'token_form', 'token_upload')),
    CONSTRAINT chk_inbound_email_sender CHECK (channel != 'email' OR sender_email IS NOT NULL),
    CONSTRAINT chk_inbound_token_ref CHECK (
        channel NOT IN ('token_form', 'token_upload') OR submission_token_id IS NOT NULL
    )
);

COMMENT ON TABLE inbound_message IS
    'Unified model for all inbound counterparty communications: email replies, token form submissions, and token file uploads.';

COMMENT ON COLUMN inbound_message.channel IS
    'Discriminator: email, token_form, or token_upload.';

COMMENT ON COLUMN inbound_message.legacy_submission_response_id IS
    'Exact 1:1 mapping to submission_response.id for backfill verification. Dropped in Phase B below.';

-- =============================================================================
-- SECTION 2: INBOUND_ATTACHMENT TABLE
-- =============================================================================

CREATE TYPE attachment_processing_status AS ENUM (
    'pending', 'processing', 'extracted', 'failed', 'skipped'
);

CREATE TABLE inbound_attachment (
    id                  BIGSERIAL PRIMARY KEY,
    inbound_message_id  BIGINT NOT NULL REFERENCES inbound_message(id) ON DELETE CASCADE,
    filename            VARCHAR(500),
    content_type        VARCHAR(100),
    size_bytes          BIGINT,
    s3_path             TEXT NOT NULL,
    file_hash           VARCHAR(64),

    -- Processing state
    attachment_processing_status attachment_processing_status NOT NULL DEFAULT 'pending',
    extraction_result   JSONB,
    failed_reason       TEXT,
    reference_price_id  BIGINT REFERENCES reference_price(id),

    -- Audit
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE inbound_attachment IS
    'Per-file tracking for attachments on inbound messages. Links to reference_price when MRP is extracted.';

-- =============================================================================
-- SECTION 3: INDEXES
-- =============================================================================

-- inbound_message indexes
CREATE INDEX idx_inbound_msg_org_status ON inbound_message (organization_id, inbound_message_status);
CREATE INDEX idx_inbound_msg_channel ON inbound_message (channel);
CREATE INDEX idx_inbound_msg_sender ON inbound_message (sender_email);

CREATE UNIQUE INDEX ux_inbound_msg_s3_raw ON inbound_message (organization_id, s3_raw_path)
    WHERE channel = 'email';

CREATE UNIQUE INDEX ux_inbound_msg_ses_id ON inbound_message (organization_id, ses_message_id)
    WHERE channel = 'email' AND ses_message_id IS NOT NULL;

CREATE INDEX idx_inbound_msg_in_reply_to ON inbound_message (in_reply_to)
    WHERE in_reply_to IS NOT NULL;

CREATE INDEX idx_inbound_msg_pending ON inbound_message (organization_id, created_at DESC)
    WHERE inbound_message_status = 'pending_review';

-- inbound_attachment indexes
CREATE INDEX idx_inbound_att_message ON inbound_attachment (inbound_message_id);

CREATE INDEX idx_inbound_att_hash ON inbound_attachment (file_hash)
    WHERE file_hash IS NOT NULL;

CREATE INDEX idx_inbound_att_status ON inbound_attachment (attachment_processing_status)
    WHERE attachment_processing_status IN ('pending', 'processing');

-- =============================================================================
-- SECTION 4: FK ON REFERENCE_PRICE (expand phase — nullable)
-- =============================================================================

ALTER TABLE reference_price ADD COLUMN inbound_message_id BIGINT REFERENCES inbound_message(id);
ALTER TABLE reference_price ADD COLUMN inbound_attachment_id BIGINT REFERENCES inbound_attachment(id);

-- =============================================================================
-- SECTION 5: BACKFILL FROM SUBMISSION_RESPONSE
-- =============================================================================

-- Exact 1:1 mapping by submission_response.id
INSERT INTO inbound_message (
    organization_id, channel, submission_token_id,
    response_data, sender_email, ip_address,
    invoice_header_id, inbound_message_status,
    legacy_submission_response_id, created_at
)
SELECT
    sr.organization_id,
    CASE WHEN st.submission_type = 'mrp_upload' THEN 'token_upload' ELSE 'token_form' END,
    sr.submission_token_id,
    sr.response_data,
    sr.submitted_by_email,
    sr.ip_address,
    sr.invoice_header_id,
    'approved',
    sr.id,
    sr.created_at
FROM submission_response sr
LEFT JOIN submission_token st ON st.id = sr.submission_token_id;

-- Backfill reference_price FK via exact legacy_submission_response_id join
UPDATE reference_price rp
SET inbound_message_id = im.id
FROM inbound_message im
WHERE rp.submission_response_id = im.legacy_submission_response_id
  AND rp.submission_response_id IS NOT NULL;

-- =============================================================================
-- SECTION 6: RLS POLICIES
-- =============================================================================

ALTER TABLE inbound_message ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbound_attachment ENABLE ROW LEVEL SECURITY;

-- inbound_message: org members can read
CREATE POLICY inbound_message_select_policy ON inbound_message
    FOR SELECT TO authenticated
    USING (is_org_member(organization_id));

-- inbound_message: org admins can insert/update/delete
CREATE POLICY inbound_message_admin_policy ON inbound_message
    FOR ALL TO authenticated
    USING (is_org_admin(organization_id))
    WITH CHECK (is_org_admin(organization_id));

-- inbound_message: service_role bypass
CREATE POLICY inbound_message_service_policy ON inbound_message
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- inbound_attachment: org members can read (via parent message)
CREATE POLICY inbound_attachment_select_policy ON inbound_attachment
    FOR SELECT TO authenticated
    USING (
        inbound_message_id IN (
            SELECT im.id FROM inbound_message im
            WHERE is_org_member(im.organization_id)
        )
    );

-- inbound_attachment: org admins can manage (via parent message)
CREATE POLICY inbound_attachment_admin_policy ON inbound_attachment
    FOR ALL TO authenticated
    USING (
        inbound_message_id IN (
            SELECT im.id FROM inbound_message im
            WHERE is_org_admin(im.organization_id)
        )
    )
    WITH CHECK (
        inbound_message_id IN (
            SELECT im.id FROM inbound_message im
            WHERE is_org_admin(im.organization_id)
        )
    );

CREATE POLICY inbound_attachment_service_policy ON inbound_attachment
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- =============================================================================
-- SECTION 7: UPDATED_AT TRIGGERS
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_inbound_message_updated_at
    BEFORE UPDATE ON inbound_message
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_inbound_attachment_updated_at
    BEFORE UPDATE ON inbound_attachment
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- SECTION 8: VERIFICATION
-- =============================================================================

DO $$
DECLARE
    v_sr_count INTEGER;
    v_im_count INTEGER;
    v_rp_linked INTEGER;
    v_rp_migrated INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_sr_count FROM submission_response;
    SELECT COUNT(*) INTO v_im_count FROM inbound_message WHERE legacy_submission_response_id IS NOT NULL;
    IF v_sr_count != v_im_count THEN
        RAISE EXCEPTION 'Backfill mismatch: submission_response=%, inbound_message=%', v_sr_count, v_im_count;
    END IF;

    SELECT COUNT(*) INTO v_rp_linked FROM reference_price WHERE submission_response_id IS NOT NULL;
    SELECT COUNT(*) INTO v_rp_migrated FROM reference_price WHERE inbound_message_id IS NOT NULL;
    IF v_rp_linked != v_rp_migrated THEN
        RAISE EXCEPTION 'reference_price FK mismatch: old=%, new=%', v_rp_linked, v_rp_migrated;
    END IF;

    RAISE NOTICE 'Migration 052a: backfill verified (% rows, % FKs)', v_im_count, v_rp_migrated;
END $$;

COMMIT;

-- =============================================================================
-- PHASE B: Contract — drop submission_response and legacy columns
-- =============================================================================

BEGIN;

-- B1: Drop legacy column from inbound_message
ALTER TABLE inbound_message DROP COLUMN legacy_submission_response_id;

-- B2: Drop old FK from reference_price
ALTER TABLE reference_price DROP COLUMN submission_response_id;

-- B3: Drop RLS policies on submission_response
DROP POLICY IF EXISTS submission_response_select_policy ON submission_response;
DROP POLICY IF EXISTS submission_response_service_policy ON submission_response;

-- B4: Drop indexes on submission_response
DROP INDEX IF EXISTS idx_submission_response_token;
DROP INDEX IF EXISTS idx_submission_response_org;
DROP INDEX IF EXISTS idx_submission_response_invoice;

-- B5: Drop submission_response table
DROP TABLE submission_response;

-- B6: Verification
DO $$
BEGIN
    -- Verify submission_response is gone
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'submission_response') THEN
        RAISE EXCEPTION 'submission_response table still exists';
    END IF;
    -- Verify legacy column is gone from inbound_message
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'inbound_message' AND column_name = 'legacy_submission_response_id') THEN
        RAISE EXCEPTION 'legacy_submission_response_id still exists on inbound_message';
    END IF;
    -- Verify old FK column gone from reference_price
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'reference_price' AND column_name = 'submission_response_id') THEN
        RAISE EXCEPTION 'submission_response_id still exists on reference_price';
    END IF;
    RAISE NOTICE 'Migration 052b: contract phase verified — submission_response fully removed';
END $$;

COMMIT;
