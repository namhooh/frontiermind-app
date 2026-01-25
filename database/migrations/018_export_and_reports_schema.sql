-- Migration: 018_export_and_reports_schema.sql
-- Description: Adds simplified report generation schema (invoice-focused)
-- Version: v5.1
-- Date: 2026-01-24
-- Depends on: 017_core_table_rls.sql
-- Updated: 2026-01-24 - Code review: RLS policies with TO role, iterative scheduler, index consolidation, COALESCE fix
-- Updated: 2026-01-25 - Simplified enum names (report_type, file_format, delivery_method) for consistency

-- =============================================================================
-- SECTION 1: ENUMS
-- =============================================================================

-- Report types (invoice-focused)
CREATE TYPE report_type AS ENUM (
    'invoice_to_client',      -- Generated invoice to issue to paying client (invoice_header, invoice_line_item)
    'invoice_expected',       -- Expected invoice from contractor (expected_invoice_header)
    'invoice_received',       -- Received invoice from contractor (received_invoice_header)
    'invoice_comparison'      -- Variance analysis (invoice_comparison, invoice_comparison_line_item)
);

-- File formats for export
CREATE TYPE file_format AS ENUM (
    'csv',
    'xlsx',
    'json',
    'pdf'
);

-- Report frequency (aligned with billing periods)
CREATE TYPE report_frequency AS ENUM (
    'monthly',
    'quarterly',
    'annual',
    'on_demand'
);

-- Simplified report status lifecycle (no approval workflow)
CREATE TYPE report_status AS ENUM (
    'pending',      -- Queued for processing
    'processing',   -- Currently generating
    'completed',    -- Successfully generated
    'failed'        -- Generation failed
);

-- Generation source for audit trail
CREATE TYPE generation_source AS ENUM (
    'on_demand',    -- User-initiated via UI/API
    'scheduled'     -- Scheduler-initiated
);

-- Delivery method for scheduled reports
CREATE TYPE delivery_method AS ENUM (
    'email',
    's3',
    'both'
);

-- =============================================================================
-- SECTION 2: REPORT TEMPLATE TABLE
-- =============================================================================

CREATE TABLE report_template (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,

    -- Template ownership/visibility scope
    -- NULL = org-wide template (visible to all org members)
    -- Set = project-specific template (visible only to project members)
    -- NOTE: ON DELETE CASCADE removes templates when project is deleted. If audit retention
    -- is required, consider ON DELETE SET NULL instead.
    project_id BIGINT REFERENCES project(id) ON DELETE CASCADE,

    name VARCHAR(255) NOT NULL,
    description TEXT,
    report_type report_type NOT NULL,
    file_format file_format NOT NULL DEFAULT 'pdf',

    -- Template configuration
    template_config JSONB NOT NULL DEFAULT '{}',
    include_charts BOOLEAN DEFAULT true,
    include_summary BOOLEAN DEFAULT true,
    include_line_items BOOLEAN DEFAULT true,

    -- Default scope (user can override at generation time)
    default_contract_id BIGINT REFERENCES contract(id),

    -- Branding
    logo_path TEXT,
    header_text TEXT,
    footer_text TEXT,

    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID REFERENCES auth.users(id),
    updated_by UUID REFERENCES auth.users(id)
);

-- Unique template name per scope (PG14 compatible partial indexes)
CREATE UNIQUE INDEX ux_report_template_org_name
    ON report_template (organization_id, name)
    WHERE project_id IS NULL;

CREATE UNIQUE INDEX ux_report_template_project_name
    ON report_template (organization_id, project_id, name)
    WHERE project_id IS NOT NULL;

-- Primary lookup indexes
CREATE INDEX idx_report_template_org_active ON report_template(organization_id, is_active);
CREATE INDEX idx_report_template_type ON report_template(report_type);
CREATE INDEX idx_report_template_project ON report_template(project_id)
    WHERE project_id IS NOT NULL;
CREATE INDEX idx_report_template_config ON report_template USING GIN (template_config);

-- =============================================================================
-- SECTION 3: SCHEDULED REPORT TABLE
-- =============================================================================

CREATE TABLE scheduled_report (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    report_template_id BIGINT NOT NULL REFERENCES report_template(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,

    -- Schedule configuration
    frequency report_frequency NOT NULL,
    day_of_month INTEGER,         -- 1-28 (for monthly/quarterly/annual)
    time_of_day TIME NOT NULL DEFAULT '06:00:00',
    timezone VARCHAR(50) NOT NULL DEFAULT 'UTC',

    -- Scope overrides (if different from template defaults)
    project_id BIGINT REFERENCES project(id),
    contract_id BIGINT REFERENCES contract(id),

    -- Billing period selection
    -- NULL = auto-select most recent completed billing period at run time
    -- Set = always use this specific billing period (for historical reruns)
    billing_period_id BIGINT REFERENCES billing_period(id),

    -- Delivery configuration
    -- recipients: Array of objects with email addresses
    -- Expected format: [{"email": "user@example.com", "name": "User Name"}, ...]
    -- Note: Contains PII - ensure proper access controls
    recipients JSONB NOT NULL DEFAULT '[]',
    delivery_method delivery_method NOT NULL DEFAULT 'email',
    s3_destination TEXT,

    -- Status tracking
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_run_at TIMESTAMPTZ,
    last_run_status report_status,
    last_run_error TEXT,
    next_run_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID REFERENCES auth.users(id),

    -- Constraints
    CONSTRAINT chk_day_of_month_range
        CHECK (day_of_month IS NULL OR (day_of_month BETWEEN 1 AND 28)),
    -- Validate recipients is a JSONB array with valid email objects
    CONSTRAINT chk_recipients_valid
        CHECK (
            jsonb_typeof(recipients) = 'array'
            AND NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(recipients) elem
                WHERE jsonb_typeof(elem) <> 'object'
                   OR (elem->>'email') IS NULL
                   OR (elem->>'email') = ''
            )
        ),
    CONSTRAINT chk_frequency_requires_day
        CHECK (
            frequency = 'on_demand'
            OR (frequency IN ('monthly', 'quarterly', 'annual') AND day_of_month IS NOT NULL)
        )
);

-- Consolidated index for scheduler queries (covers active + next_run lookups)
CREATE INDEX idx_scheduled_report_scheduler
    ON scheduled_report (is_active, next_run_at, organization_id)
    WHERE is_active = true;
CREATE INDEX idx_scheduled_report_template ON scheduled_report(report_template_id);

-- =============================================================================
-- SECTION 4: GENERATED REPORT TABLE
-- =============================================================================

CREATE TABLE generated_report (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,

    -- Traceability
    report_template_id BIGINT REFERENCES report_template(id),
    scheduled_report_id BIGINT REFERENCES scheduled_report(id),
    generation_source generation_source NOT NULL,

    -- Report details
    report_type report_type NOT NULL,
    name VARCHAR(255) NOT NULL,
    status report_status NOT NULL DEFAULT 'pending',

    -- Scope
    project_id BIGINT REFERENCES project(id),
    contract_id BIGINT REFERENCES contract(id),
    billing_period_id BIGINT REFERENCES billing_period(id),

    -- File details
    file_format file_format NOT NULL,
    file_path TEXT,                 -- S3 path (NULL until completed)
    file_size_bytes BIGINT,
    file_hash VARCHAR(64),          -- SHA-256 hex (64 chars)

    -- Processing details
    requested_by UUID REFERENCES auth.users(id),
    processing_started_at TIMESTAMPTZ,
    processing_completed_at TIMESTAMPTZ,
    processing_error TEXT,
    processing_time_ms INTEGER,

    -- Record counts
    record_count INTEGER,

    -- Summary data (for quick display without re-downloading)
    summary_data JSONB,

    -- Download tracking (use atomic UPDATE ... SET download_count = download_count + 1)
    download_count INTEGER NOT NULL DEFAULT 0,
    expires_at TIMESTAMPTZ DEFAULT (now() + INTERVAL '90 days'),

    -- Archival
    archived_at TIMESTAMPTZ,
    archived_path TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Consolidated indexes (removed redundant org-only index)
CREATE INDEX idx_generated_report_org_created ON generated_report(organization_id, created_at DESC);
CREATE INDEX idx_generated_report_type ON generated_report(report_type);
CREATE INDEX idx_generated_report_status ON generated_report(status);
CREATE INDEX idx_generated_report_billing_period ON generated_report(billing_period_id);
CREATE INDEX idx_generated_report_template ON generated_report(report_template_id);
CREATE INDEX idx_generated_report_schedule ON generated_report(scheduled_report_id);
CREATE INDEX idx_generated_report_pending ON generated_report(status, created_at)
    WHERE status IN ('pending', 'processing');
CREATE INDEX idx_generated_report_expires ON generated_report(expires_at)
    WHERE expires_at IS NOT NULL AND archived_at IS NULL;

-- =============================================================================
-- SECTION 5: HELPER FUNCTIONS
-- =============================================================================

-- Get the most recent completed billing period
-- Returns: billing_period.id or NULL if no completed periods exist
CREATE OR REPLACE FUNCTION get_latest_completed_billing_period()
RETURNS BIGINT AS $$
DECLARE
    v_result BIGINT;
BEGIN
    SELECT id INTO v_result
    FROM billing_period
    WHERE end_date < CURRENT_DATE
    ORDER BY end_date DESC
    LIMIT 1;

    -- Returns NULL if no completed billing period found
    RETURN v_result;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_latest_completed_billing_period() IS
    'Returns the ID of the most recent billing period where end_date < CURRENT_DATE. Returns NULL if none found.';

-- Calculate next run time for scheduled report (iterative, not recursive)
CREATE OR REPLACE FUNCTION calculate_next_run_time(
    p_frequency report_frequency,
    p_day_of_month INTEGER,
    p_time_of_day TIME,
    p_timezone VARCHAR,
    p_from_time TIMESTAMPTZ DEFAULT now()
)
RETURNS TIMESTAMPTZ AS $$
DECLARE
    v_local_from TIMESTAMP;
    v_candidate TIMESTAMP;
    v_next TIMESTAMPTZ;
    v_time_interval INTERVAL;
    v_iteration INTEGER := 0;
    v_max_iterations INTEGER := 12;  -- Safety limit
BEGIN
    -- Validate parameters
    IF p_frequency IN ('monthly', 'quarterly', 'annual') AND p_day_of_month IS NULL THEN
        RAISE EXCEPTION 'calculate_next_run_time: day_of_month required for % frequency', p_frequency;
    END IF;

    -- on_demand reports have no scheduled runs
    IF p_frequency = 'on_demand' THEN
        RETURN NULL;
    END IF;

    -- Convert TIME to INTERVAL explicitly
    v_time_interval := p_time_of_day::INTERVAL;

    -- Convert to local time (strip timezone for arithmetic)
    v_local_from := (p_from_time AT TIME ZONE p_timezone)::TIMESTAMP;

    -- Iterative approach: find next valid candidate
    LOOP
        v_iteration := v_iteration + 1;
        IF v_iteration > v_max_iterations THEN
            RAISE EXCEPTION 'calculate_next_run_time: iteration limit exceeded';
        END IF;

        -- Calculate candidate for current or next period
        CASE p_frequency
            WHEN 'monthly' THEN
                -- Try current month first, then next
                IF v_iteration = 1 THEN
                    v_candidate := DATE_TRUNC('month', v_local_from)::TIMESTAMP
                                 + (LEAST(p_day_of_month, 28) - 1) * INTERVAL '1 day'
                                 + v_time_interval;
                ELSE
                    v_candidate := v_candidate + INTERVAL '1 month';
                END IF;

            WHEN 'quarterly' THEN
                IF v_iteration = 1 THEN
                    v_candidate := DATE_TRUNC('quarter', v_local_from)::TIMESTAMP
                                 + (LEAST(p_day_of_month, 28) - 1) * INTERVAL '1 day'
                                 + v_time_interval;
                ELSE
                    v_candidate := v_candidate + INTERVAL '3 months';
                END IF;

            WHEN 'annual' THEN
                IF v_iteration = 1 THEN
                    v_candidate := DATE_TRUNC('year', v_local_from)::TIMESTAMP
                                 + (LEAST(p_day_of_month, 28) - 1) * INTERVAL '1 day'
                                 + v_time_interval;
                ELSE
                    v_candidate := v_candidate + INTERVAL '1 year';
                END IF;
        END CASE;

        -- Convert back to timestamptz
        v_next := v_candidate AT TIME ZONE p_timezone;

        -- If candidate is in the future, we're done
        IF v_next > p_from_time THEN
            RETURN v_next;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION calculate_next_run_time(report_frequency, INTEGER, TIME, VARCHAR, TIMESTAMPTZ) IS
    'Computes next scheduled run time for monthly/quarterly/annual frequencies. Returns NULL for on_demand.';

-- Get report statistics for an organization
CREATE OR REPLACE FUNCTION get_report_statistics(
    p_organization_id BIGINT,
    p_days INTEGER DEFAULT 30
)
RETURNS TABLE(
    total_reports BIGINT,
    completed_reports BIGINT,
    failed_reports BIGINT,
    pending_reports BIGINT,
    total_records_exported BIGINT,
    avg_processing_time_ms DOUBLE PRECISION
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(*)::BIGINT,
        COUNT(*) FILTER (WHERE gr.status = 'completed')::BIGINT,
        COUNT(*) FILTER (WHERE gr.status = 'failed')::BIGINT,
        COUNT(*) FILTER (WHERE gr.status IN ('pending', 'processing'))::BIGINT,
        COALESCE(SUM(gr.record_count) FILTER (WHERE gr.status = 'completed'), 0)::BIGINT,
        COALESCE(AVG(gr.processing_time_ms) FILTER (WHERE gr.status = 'completed'), 0.0)::DOUBLE PRECISION
    FROM generated_report gr
    WHERE gr.organization_id = p_organization_id
      AND gr.created_at >= now() - (p_days || ' days')::INTERVAL;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- =============================================================================
-- SECTION 6: ROW LEVEL SECURITY
-- =============================================================================

ALTER TABLE report_template ENABLE ROW LEVEL SECURITY;
ALTER TABLE scheduled_report ENABLE ROW LEVEL SECURITY;
ALTER TABLE generated_report ENABLE ROW LEVEL SECURITY;

-- Report template policies
-- SELECT: Org members can see org-wide templates; project members can see project-specific
DROP POLICY IF EXISTS report_template_select_policy ON report_template;
CREATE POLICY report_template_select_policy ON report_template
    FOR SELECT TO authenticated
    USING (
        (project_id IS NULL AND is_org_member(organization_id))
        OR (project_id IS NOT NULL AND is_project_member(project_id))
    );

-- INSERT/UPDATE/DELETE: Org admins only
DROP POLICY IF EXISTS report_template_admin_policy ON report_template;
CREATE POLICY report_template_admin_policy ON report_template
    FOR ALL TO authenticated
    USING (is_org_admin(organization_id))
    WITH CHECK (is_org_admin(organization_id));

-- Service role: full access (bypasses RLS by default, but explicit for clarity)
DROP POLICY IF EXISTS report_template_service_policy ON report_template;
CREATE POLICY report_template_service_policy ON report_template
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- Scheduled report policies
-- SELECT: Org members can see org-wide schedules; project members can see project-specific
DROP POLICY IF EXISTS scheduled_report_select_policy ON scheduled_report;
CREATE POLICY scheduled_report_select_policy ON scheduled_report
    FOR SELECT TO authenticated
    USING (
        (project_id IS NULL AND is_org_member(organization_id))
        OR (project_id IS NOT NULL AND is_project_member(project_id))
    );

-- INSERT/UPDATE/DELETE: Org admins only
DROP POLICY IF EXISTS scheduled_report_admin_policy ON scheduled_report;
CREATE POLICY scheduled_report_admin_policy ON scheduled_report
    FOR ALL TO authenticated
    USING (is_org_admin(organization_id))
    WITH CHECK (is_org_admin(organization_id));

-- Service role: full access
DROP POLICY IF EXISTS scheduled_report_service_policy ON scheduled_report;
CREATE POLICY scheduled_report_service_policy ON scheduled_report
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- Generated report policies
-- SELECT: Org members can view
DROP POLICY IF EXISTS generated_report_select_policy ON generated_report;
CREATE POLICY generated_report_select_policy ON generated_report
    FOR SELECT TO authenticated
    USING (is_org_member(organization_id));

-- INSERT: Org members can create
DROP POLICY IF EXISTS generated_report_insert_policy ON generated_report;
CREATE POLICY generated_report_insert_policy ON generated_report
    FOR INSERT TO authenticated
    WITH CHECK (is_org_member(organization_id));

-- UPDATE: Admins or the requester can update
DROP POLICY IF EXISTS generated_report_update_policy ON generated_report;
CREATE POLICY generated_report_update_policy ON generated_report
    FOR UPDATE TO authenticated
    USING (is_org_admin(organization_id) OR requested_by = (SELECT auth.uid()));

-- Service role: full access
DROP POLICY IF EXISTS generated_report_service_policy ON generated_report;
CREATE POLICY generated_report_service_policy ON generated_report
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- =============================================================================
-- SECTION 7: TRIGGERS
-- =============================================================================

-- Update timestamp trigger for report_template (handles both INSERT and UPDATE)
CREATE OR REPLACE FUNCTION update_report_template_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        NEW.updated_at = now();
    END IF;
    -- On INSERT, updated_at uses DEFAULT now() which is already set
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS report_template_updated_at ON report_template;
CREATE TRIGGER report_template_updated_at
    BEFORE INSERT OR UPDATE ON report_template
    FOR EACH ROW
    EXECUTE FUNCTION update_report_template_timestamp();

-- Trigger to calculate next run time when scheduled report is created/updated
CREATE OR REPLACE FUNCTION update_scheduled_report_next_run()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.is_active AND NEW.frequency != 'on_demand' THEN
        NEW.next_run_at := calculate_next_run_time(
            NEW.frequency,
            NEW.day_of_month,
            NEW.time_of_day,
            NEW.timezone,
            COALESCE(NEW.last_run_at, now())
        );
    ELSE
        NEW.next_run_at := NULL;
    END IF;

    IF TG_OP = 'UPDATE' THEN
        NEW.updated_at := now();
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS scheduled_report_next_run ON scheduled_report;
CREATE TRIGGER scheduled_report_next_run
    BEFORE INSERT OR UPDATE ON scheduled_report
    FOR EACH ROW
    EXECUTE FUNCTION update_scheduled_report_next_run();

-- Trigger to update processing timestamps on status change
CREATE OR REPLACE FUNCTION update_generated_report_timestamps()
RETURNS TRIGGER AS $$
DECLARE
    v_start_time TIMESTAMPTZ;
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- Set processing_started_at if inserting with status 'processing'
        IF NEW.status = 'processing' AND NEW.processing_started_at IS NULL THEN
            NEW.processing_started_at = now();
        END IF;
    ELSIF TG_OP = 'UPDATE' THEN
        -- Transition to processing
        IF NEW.status = 'processing' AND COALESCE(OLD.status, 'pending') = 'pending' THEN
            NEW.processing_started_at = now();
        -- Transition to completed/failed
        ELSIF NEW.status IN ('completed', 'failed') AND COALESCE(OLD.status, 'pending') = 'processing' THEN
            NEW.processing_completed_at = now();
            -- Use COALESCE to handle case where NEW doesn't include start time
            v_start_time := COALESCE(NEW.processing_started_at, OLD.processing_started_at);
            IF v_start_time IS NOT NULL THEN
                NEW.processing_time_ms = ROUND(
                    EXTRACT(EPOCH FROM (NEW.processing_completed_at - v_start_time)) * 1000
                )::INTEGER;
            END IF;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS generated_report_timestamps ON generated_report;
CREATE TRIGGER generated_report_timestamps
    BEFORE INSERT OR UPDATE ON generated_report
    FOR EACH ROW
    EXECUTE FUNCTION update_generated_report_timestamps();

-- =============================================================================
-- SECTION 8: SEED DEFAULT REPORT TEMPLATES
-- =============================================================================

-- Seed invoice-focused report templates for each organization
INSERT INTO report_template (
    organization_id, project_id, name, description, report_type, file_format, template_config
)
SELECT
    o.id,
    NULL,  -- org-wide template
    template.name,
    template.description,
    template.report_type::report_type,
    template.file_format::file_format,
    template.config::JSONB
FROM organization o
CROSS JOIN (VALUES
    (
        'Invoice to Client Report',
        'Generated invoice ready to issue to paying client for a billing period',
        'invoice_to_client',
        'pdf',
        '{"include_line_items": true, "include_meter_summary": true, "include_adjustments": true}'
    ),
    (
        'Expected Invoice Report',
        'Expected invoice from contractor based on contract terms and meter data',
        'invoice_expected',
        'pdf',
        '{"include_line_items": true, "include_calculation_details": true}'
    ),
    (
        'Received Invoice Report',
        'Received invoice from contractor for review and comparison',
        'invoice_received',
        'pdf',
        '{"include_line_items": true, "include_scanned_document": false}'
    ),
    (
        'Invoice Comparison Report',
        'Variance analysis between expected and received invoices',
        'invoice_comparison',
        'pdf',
        '{"include_variance_breakdown": true, "include_line_item_matching": true, "highlight_discrepancies": true}'
    )
) AS template(name, description, report_type, file_format, config)
WHERE NOT EXISTS (
    SELECT 1 FROM report_template rt
    WHERE rt.organization_id = o.id
      AND rt.project_id IS NULL
      AND rt.name = template.name
);

-- =============================================================================
-- SECTION 9: GRANT PERMISSIONS
-- =============================================================================

-- Revoke default public access from all functions
REVOKE EXECUTE ON FUNCTION get_latest_completed_billing_period FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION calculate_next_run_time FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION get_report_statistics FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION update_report_template_timestamp FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION update_scheduled_report_next_run FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION update_generated_report_timestamps FROM PUBLIC;

-- Grant to specific roles
GRANT EXECUTE ON FUNCTION get_latest_completed_billing_period TO authenticated;
GRANT EXECUTE ON FUNCTION get_latest_completed_billing_period TO service_role;

GRANT EXECUTE ON FUNCTION calculate_next_run_time TO authenticated;
GRANT EXECUTE ON FUNCTION calculate_next_run_time TO service_role;

GRANT EXECUTE ON FUNCTION get_report_statistics TO authenticated;
GRANT EXECUTE ON FUNCTION get_report_statistics TO service_role;

-- Trigger functions only need service_role (called internally by trigger)
GRANT EXECUTE ON FUNCTION update_report_template_timestamp TO service_role;
GRANT EXECUTE ON FUNCTION update_scheduled_report_next_run TO service_role;
GRANT EXECUTE ON FUNCTION update_generated_report_timestamps TO service_role;

-- =============================================================================
-- SECTION 10: HELPER FUNCTION FOR PROJECT MEMBER CHECK
-- =============================================================================

-- Add is_project_member function if it doesn't exist (required for RLS policies)
-- This checks if the current user is a member of the project's organization
-- IMPORTANT: Relies on is_org_member() which must be:
--   - SECURITY DEFINER
--   - STABLE
--   - Use (SELECT auth.uid()) pattern internally
--   - REVOKE EXECUTE FROM PUBLIC with grants to authenticated/service_role
-- Verify these properties exist from migration 017_core_table_rls.sql
CREATE OR REPLACE FUNCTION is_project_member(p_project_id BIGINT)
RETURNS BOOLEAN AS $$
DECLARE
    v_org_id BIGINT;
BEGIN
    -- Use SELECT to help query planner
    SELECT organization_id INTO v_org_id
    FROM project
    WHERE id = p_project_id;

    IF v_org_id IS NULL THEN
        RETURN false;
    END IF;

    RETURN is_org_member(v_org_id);
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

REVOKE EXECUTE ON FUNCTION is_project_member FROM PUBLIC;
GRANT EXECUTE ON FUNCTION is_project_member TO authenticated;
GRANT EXECUTE ON FUNCTION is_project_member TO service_role;

-- =============================================================================
-- VERIFICATION
-- =============================================================================

DO $$
DECLARE
    v_count INTEGER;
BEGIN
    -- Check tables exist
    SELECT COUNT(*) INTO v_count
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name IN ('report_template', 'scheduled_report', 'generated_report');

    IF v_count < 3 THEN
        RAISE EXCEPTION 'Not all tables were created. Expected 3, found %', v_count;
    END IF;

    -- Check all enums exist
    PERFORM 1 FROM pg_type WHERE typname = 'report_type';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'report_type enum not found';
    END IF;

    PERFORM 1 FROM pg_type WHERE typname = 'file_format';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'file_format enum not found';
    END IF;

    PERFORM 1 FROM pg_type WHERE typname = 'report_frequency';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'report_frequency enum not found';
    END IF;

    PERFORM 1 FROM pg_type WHERE typname = 'report_status';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'report_status enum not found';
    END IF;

    PERFORM 1 FROM pg_type WHERE typname = 'generation_source';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'generation_source enum not found';
    END IF;

    PERFORM 1 FROM pg_type WHERE typname = 'delivery_method';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'delivery_method enum not found';
    END IF;

    RAISE NOTICE 'Migration 018_export_and_reports_schema (v5.1 simplified) completed successfully';
END $$;
