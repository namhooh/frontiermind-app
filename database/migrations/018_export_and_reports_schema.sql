-- Migration: 018_export_and_reports_schema.sql
-- Description: Adds data export tracking and report generation schema
-- Version: v5.0
-- Date: 2026-01-22
-- Depends on: 017_core_table_rls.sql
-- Updated: 2026-01-23 - Fixed PG14 compatibility, added performance indexes
-- Updated: 2026-01-23 - Added null validation, timezone fixes, recipients CHECK, REVOKE FROM PUBLIC

-- =============================================================================
-- SECTION 1: ENUMS
-- =============================================================================

-- Export request status
CREATE TYPE export_request_status AS ENUM (
    'pending',         -- Request submitted, awaiting approval (for bulk)
    'approved',        -- Approved, ready to process
    'processing',      -- Export in progress
    'completed',       -- Export completed, ready for download
    'failed',          -- Export failed
    'expired',         -- Download link expired
    'cancelled'        -- Cancelled by user or admin
);

-- Export data types
CREATE TYPE export_data_type AS ENUM (
    'contract',
    'clause',
    'invoice_generated',
    'invoice_received',
    'expense',
    'meter_data',
    'financial_report',
    'compliance_report',
    'settlement_report',
    'custom'
);

-- Export file formats
CREATE TYPE export_file_format AS ENUM (
    'csv',
    'xlsx',
    'json',
    'pdf'
);

-- Report frequency
CREATE TYPE report_frequency AS ENUM (
    'daily',
    'weekly',
    'monthly',
    'quarterly',
    'annual',
    'on_demand'
);

-- Report types
CREATE TYPE report_type AS ENUM (
    'settlement',          -- Monthly settlement calculation
    'compliance',          -- Compliance status report
    'financial_summary',   -- Revenue/expense summary
    'invoice_aging',       -- Invoice aging report
    'expense_by_category', -- Expense breakdown
    'generation_summary',  -- Generation data summary
    'ld_summary',          -- Liquidated damages summary
    'custom'               -- Custom report template
);

-- =============================================================================
-- SECTION 2: EXPORT REQUEST TABLE
-- =============================================================================

CREATE TABLE export_request (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES public.organization(id) ON DELETE CASCADE,
    requested_by UUID NOT NULL REFERENCES auth.users(id),
    data_type export_data_type NOT NULL,
    file_format export_file_format NOT NULL,
    status export_request_status NOT NULL DEFAULT 'pending',

    -- Filters and scope
    project_id BIGINT REFERENCES public.project(id),
    contract_id BIGINT REFERENCES public.contract(id),
    date_from DATE,
    date_to DATE,
    filters JSONB,  -- Additional filters as key-value pairs

    -- Record counts and approval
    estimated_record_count INTEGER,
    actual_record_count INTEGER,
    requires_approval BOOLEAN NOT NULL DEFAULT false,
    approved_by UUID REFERENCES auth.users(id),
    approved_at TIMESTAMPTZ,
    rejection_reason TEXT,

    -- File details
    file_path TEXT,  -- S3 path (no length limit)
    file_size_bytes BIGINT,
    file_hash VARCHAR(64),   -- SHA-256 for integrity
    watermarked BOOLEAN DEFAULT false,
    download_count INTEGER DEFAULT 0,
    max_downloads INTEGER DEFAULT 5,
    expires_at TIMESTAMPTZ,

    -- Processing details
    processing_started_at TIMESTAMPTZ,
    processing_completed_at TIMESTAMPTZ,
    processing_error TEXT,
    processing_time_ms INTEGER,

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX idx_export_request_org ON export_request(organization_id);
CREATE INDEX idx_export_request_status ON export_request(status);
CREATE INDEX idx_export_request_user ON export_request(requested_by);
CREATE INDEX idx_export_request_data_type ON export_request(data_type);
CREATE INDEX idx_export_request_pending_approval ON export_request(organization_id, status)
    WHERE status = 'pending' AND requires_approval = true;

-- Performance: Composite index for common queries
CREATE INDEX idx_export_request_composite
    ON export_request (requested_by, status, organization_id, created_at DESC);

-- Performance: GIN index for JSONB filters
CREATE INDEX idx_export_request_filters ON export_request USING GIN (filters);

-- =============================================================================
-- SECTION 3: REPORT TEMPLATE TABLE
-- =============================================================================

CREATE TABLE report_template (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES public.organization(id) ON DELETE CASCADE,

    -- Template ownership/visibility scope
    -- NULL = org-wide template (visible to all org members)
    -- Set = project-specific template (visible only to project members)
    project_id BIGINT REFERENCES public.project(id) ON DELETE CASCADE,

    name VARCHAR(255) NOT NULL,
    description TEXT,
    report_type report_type NOT NULL,
    file_format export_file_format NOT NULL DEFAULT 'pdf',

    -- Template configuration
    template_config JSONB NOT NULL DEFAULT '{}',  -- Report-specific settings
    include_charts BOOLEAN DEFAULT true,
    include_tables BOOLEAN DEFAULT true,
    include_summary BOOLEAN DEFAULT true,

    -- Default filters: Pre-fill values when generating reports (user can override)
    -- NULL = no default, user must select
    default_contract_id BIGINT REFERENCES public.contract(id),  -- Pre-select this contract
    default_date_range_days INTEGER DEFAULT 30,          -- Pre-select this date range (days)

    -- Branding
    logo_path TEXT,  -- S3 path (no length limit)
    header_text TEXT,
    footer_text TEXT,

    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID REFERENCES auth.users(id),
    updated_by UUID REFERENCES auth.users(id)

    -- NOTE: Unique constraint handled via partial indexes below (PG14 compatible)
);

-- Unique template name per scope using partial indexes (PG14 compatible)
-- Replaces: CONSTRAINT report_template_scope_name_unique UNIQUE NULLS NOT DISTINCT (organization_id, project_id, name)
-- which requires PG15+

-- Org-wide templates (project_id IS NULL): unique (organization_id, name)
CREATE UNIQUE INDEX ux_report_template_org_name
    ON report_template (organization_id, name)
    WHERE project_id IS NULL;

-- Project-specific templates (project_id IS NOT NULL): unique (organization_id, project_id, name)
CREATE UNIQUE INDEX ux_report_template_project_name
    ON report_template (organization_id, project_id, name)
    WHERE project_id IS NOT NULL;

CREATE INDEX idx_report_template_org ON report_template(organization_id, is_active);
CREATE INDEX idx_report_template_type ON report_template(report_type);
CREATE INDEX idx_report_template_project ON report_template(project_id) WHERE project_id IS NOT NULL;

-- Performance: GIN index for JSONB template_config
CREATE INDEX idx_report_template_config ON report_template USING GIN (template_config);

-- =============================================================================
-- SECTION 4: SCHEDULED REPORT TABLE
-- =============================================================================

CREATE TABLE scheduled_report (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES public.organization(id) ON DELETE CASCADE,
    report_template_id BIGINT NOT NULL REFERENCES public.report_template(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,

    -- Schedule configuration
    frequency report_frequency NOT NULL,
    day_of_week INTEGER,  -- 0=Sunday, 6=Saturday (for weekly)
    day_of_month INTEGER, -- 1-28 (for monthly/quarterly/annual)
    time_of_day TIME NOT NULL DEFAULT '06:00:00',
    timezone VARCHAR(50) NOT NULL DEFAULT 'UTC',

    -- Filters override (if different from template)
    project_id BIGINT REFERENCES public.project(id),
    contract_id BIGINT REFERENCES public.contract(id),
    date_range_days INTEGER,

    -- Delivery
    -- recipients: Array of objects with email addresses
    -- Expected format: [{"email": "user@example.com", "name": "User Name"}, ...]
    recipients JSONB NOT NULL DEFAULT '[]',
    delivery_method VARCHAR(20) NOT NULL DEFAULT 'email',  -- 'email', 's3', 'both'
    s3_destination TEXT,  -- S3 prefix for automated storage (no length limit)

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_run_at TIMESTAMPTZ,
    last_run_status VARCHAR(50),
    last_run_error TEXT,
    next_run_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID REFERENCES auth.users(id),

    -- CHECK constraints for schedule fields
    CONSTRAINT chk_day_of_week_range
        CHECK (day_of_week IS NULL OR (day_of_week BETWEEN 0 AND 6)),
    CONSTRAINT chk_day_of_month_range
        CHECK (day_of_month IS NULL OR (day_of_month BETWEEN 1 AND 28)),
    -- Validate recipients is a JSONB array
    CONSTRAINT chk_recipients_is_array
        CHECK (jsonb_typeof(recipients) = 'array')
);

CREATE INDEX idx_scheduled_report_org ON scheduled_report(organization_id, is_active);
CREATE INDEX idx_scheduled_report_next_run ON scheduled_report(next_run_at)
    WHERE is_active = true;

-- Performance: Composite index for scheduler queries
CREATE INDEX idx_scheduled_report_active_next_run
    ON scheduled_report (is_active, next_run_at)
    WHERE is_active = true;

-- =============================================================================
-- SECTION 5: GENERATED REPORT TABLE
-- =============================================================================

CREATE TABLE generated_report (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES public.organization(id) ON DELETE CASCADE,
    report_template_id BIGINT REFERENCES public.report_template(id),
    scheduled_report_id BIGINT REFERENCES public.scheduled_report(id),
    export_request_id BIGINT REFERENCES public.export_request(id),

    report_type report_type NOT NULL,
    name VARCHAR(255) NOT NULL,

    -- Scope
    project_id BIGINT REFERENCES public.project(id),
    contract_id BIGINT REFERENCES public.contract(id),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,

    -- File details
    file_format export_file_format NOT NULL,
    file_path TEXT NOT NULL,  -- S3 path (no length limit)
    file_size_bytes BIGINT,

    -- Generation details
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    generated_by UUID REFERENCES auth.users(id),
    generation_time_ms INTEGER,

    -- Summary data (for quick display)
    summary_data JSONB,  -- Key metrics from the report

    -- Retention
    expires_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,
    archived_path TEXT,  -- Glacier path (no length limit)

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_generated_report_org ON generated_report(organization_id);
CREATE INDEX idx_generated_report_type ON generated_report(report_type);
CREATE INDEX idx_generated_report_period ON generated_report(period_start, period_end);
CREATE INDEX idx_generated_report_template ON generated_report(report_template_id);

-- =============================================================================
-- SECTION 6: HELPER FUNCTIONS
-- =============================================================================

-- Function to check if export requires approval (bulk export threshold)
-- IMMUTABLE: Pure function of inputs only, no database access or now() calls
CREATE OR REPLACE FUNCTION check_export_requires_approval(
    p_data_type export_data_type,
    p_estimated_count INTEGER,
    p_bulk_threshold INTEGER DEFAULT 20
)
RETURNS BOOLEAN AS $$
BEGIN
    -- Handle null count explicitly - unknown count doesn't require approval
    IF p_estimated_count IS NULL THEN
        RETURN false;
    END IF;

    -- Bulk exports require dual approval
    IF p_estimated_count > p_bulk_threshold THEN
        RETURN true;
    END IF;

    -- PII-containing data types always require approval
    IF p_data_type IN ('contract', 'invoice_generated', 'invoice_received', 'expense') THEN
        RETURN p_estimated_count > 10;
    END IF;

    RETURN false;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function to calculate next run time for scheduled report
-- STABLE: Uses now() default, reads timezone data (not IMMUTABLE)
CREATE OR REPLACE FUNCTION calculate_next_run_time(
    p_frequency report_frequency,
    p_day_of_week INTEGER,
    p_day_of_month INTEGER,
    p_time_of_day TIME,
    p_timezone VARCHAR,
    p_from_time TIMESTAMPTZ DEFAULT now(),
    p_depth INTEGER DEFAULT 0  -- Recursion guard
)
RETURNS TIMESTAMPTZ AS $$
DECLARE
    v_local_from TIMESTAMP;  -- local timestamp (no tz)
    v_local_next TIMESTAMP;  -- computed local next run
    v_next TIMESTAMPTZ;
BEGIN
    -- Guard against infinite recursion (max 12 iterations covers all edge cases)
    IF p_depth > 12 THEN
        RAISE EXCEPTION 'calculate_next_run_time: recursion limit exceeded';
    END IF;

    -- Validate required parameters based on frequency
    CASE p_frequency
        WHEN 'weekly' THEN
            IF p_day_of_week IS NULL THEN
                RAISE EXCEPTION 'calculate_next_run_time: day_of_week required for weekly frequency';
            END IF;
        WHEN 'monthly', 'quarterly', 'annual' THEN
            IF p_day_of_month IS NULL THEN
                RAISE EXCEPTION 'calculate_next_run_time: day_of_month required for % frequency', p_frequency;
            END IF;
        ELSE
            NULL;  -- daily and on_demand don't need these
    END CASE;

    -- Convert to local time explicitly (avoids DST edge cases in arithmetic)
    v_local_from := (p_from_time AT TIME ZONE p_timezone);

    -- All arithmetic in local time
    CASE p_frequency
        WHEN 'daily' THEN
            v_local_next := date_trunc('day', v_local_from) + INTERVAL '1 day' + p_time_of_day;

        WHEN 'weekly' THEN
            -- Find next occurrence of day_of_week
            v_local_next := date_trunc('day', v_local_from) + ((7 + p_day_of_week - EXTRACT(DOW FROM v_local_from)::INTEGER) % 7 + 1) * INTERVAL '1 day' + p_time_of_day;

        WHEN 'monthly' THEN
            -- Use day_of_month, capped at 28 for safety
            v_local_next := DATE_TRUNC('month', v_local_from) + INTERVAL '1 month' + (LEAST(p_day_of_month, 28) - 1) * INTERVAL '1 day' + p_time_of_day;

        WHEN 'quarterly' THEN
            -- First day of next quarter + day_of_month
            v_local_next := DATE_TRUNC('quarter', v_local_from) + INTERVAL '3 months' + (LEAST(p_day_of_month, 28) - 1) * INTERVAL '1 day' + p_time_of_day;

        WHEN 'annual' THEN
            -- First day of next year + day_of_month (as day of January)
            v_local_next := DATE_TRUNC('year', v_local_from) + INTERVAL '1 year' + (LEAST(p_day_of_month, 28) - 1) * INTERVAL '1 day' + p_time_of_day;

        ELSE
            RETURN NULL;  -- on_demand reports don't have scheduled runs
    END CASE;

    -- Convert back to timestamptz at the end
    v_next := v_local_next AT TIME ZONE p_timezone;

    -- If calculated time is in the past, advance by one period
    IF v_next <= p_from_time THEN
        RETURN calculate_next_run_time(p_frequency, p_day_of_week, p_day_of_month, p_time_of_day, p_timezone, v_next, p_depth + 1);
    END IF;

    RETURN v_next;
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to get export statistics
-- STABLE SECURITY DEFINER: Reads from tables, requires elevated access for RLS bypass
CREATE OR REPLACE FUNCTION get_export_statistics(
    p_organization_id BIGINT,
    p_days INTEGER DEFAULT 30
)
RETURNS TABLE(
    total_exports BIGINT,
    completed_exports BIGINT,
    failed_exports BIGINT,
    pending_approval BIGINT,
    total_records_exported BIGINT,
    avg_processing_time_ms NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(*)::BIGINT,
        COUNT(*) FILTER (WHERE status = 'completed')::BIGINT,
        COUNT(*) FILTER (WHERE status = 'failed')::BIGINT,
        COUNT(*) FILTER (WHERE status = 'pending' AND requires_approval)::BIGINT,
        COALESCE(SUM(actual_record_count) FILTER (WHERE status = 'completed'), 0)::BIGINT,
        AVG(processing_time_ms) FILTER (WHERE status = 'completed')
    FROM public.export_request
    WHERE organization_id = p_organization_id
      AND created_at >= now() - (p_days || ' days')::INTERVAL;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- =============================================================================
-- SECTION 7: ROW LEVEL SECURITY
-- =============================================================================

ALTER TABLE export_request ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_template ENABLE ROW LEVEL SECURITY;
ALTER TABLE scheduled_report ENABLE ROW LEVEL SECURITY;
ALTER TABLE generated_report ENABLE ROW LEVEL SECURITY;

-- Export request policies
DROP POLICY IF EXISTS export_request_org_policy ON export_request;
CREATE POLICY export_request_org_policy ON export_request
    FOR SELECT USING (is_org_member(organization_id));

DROP POLICY IF EXISTS export_request_user_insert_policy ON export_request;
CREATE POLICY export_request_user_insert_policy ON export_request
    FOR INSERT WITH CHECK (is_org_member(organization_id) AND requested_by = auth.uid());

DROP POLICY IF EXISTS export_request_admin_modify_policy ON export_request;
CREATE POLICY export_request_admin_modify_policy ON export_request
    FOR UPDATE USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS export_request_service_policy ON export_request;
CREATE POLICY export_request_service_policy ON export_request
    FOR ALL USING (auth.role() = 'service_role');

-- Report template policies
DROP POLICY IF EXISTS report_template_org_policy ON report_template;
CREATE POLICY report_template_org_policy ON report_template
    FOR SELECT USING (is_org_member(organization_id));

DROP POLICY IF EXISTS report_template_admin_modify_policy ON report_template;
CREATE POLICY report_template_admin_modify_policy ON report_template
    FOR ALL USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS report_template_service_policy ON report_template;
CREATE POLICY report_template_service_policy ON report_template
    FOR ALL USING (auth.role() = 'service_role');

-- Scheduled report policies
DROP POLICY IF EXISTS scheduled_report_org_policy ON scheduled_report;
CREATE POLICY scheduled_report_org_policy ON scheduled_report
    FOR SELECT USING (is_org_member(organization_id));

DROP POLICY IF EXISTS scheduled_report_admin_modify_policy ON scheduled_report;
CREATE POLICY scheduled_report_admin_modify_policy ON scheduled_report
    FOR ALL USING (is_org_admin(organization_id));

DROP POLICY IF EXISTS scheduled_report_service_policy ON scheduled_report;
CREATE POLICY scheduled_report_service_policy ON scheduled_report
    FOR ALL USING (auth.role() = 'service_role');

-- Generated report policies
DROP POLICY IF EXISTS generated_report_org_policy ON generated_report;
CREATE POLICY generated_report_org_policy ON generated_report
    FOR SELECT USING (is_org_member(organization_id));

DROP POLICY IF EXISTS generated_report_insert_policy ON generated_report;
CREATE POLICY generated_report_insert_policy ON generated_report
    FOR INSERT WITH CHECK (is_org_member(organization_id));

DROP POLICY IF EXISTS generated_report_service_policy ON generated_report;
CREATE POLICY generated_report_service_policy ON generated_report
    FOR ALL USING (auth.role() = 'service_role');

-- =============================================================================
-- SECTION 8: TRIGGERS
-- =============================================================================

-- Update timestamp trigger for export_request
CREATE OR REPLACE FUNCTION update_export_request_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS export_request_updated_at ON export_request;
CREATE TRIGGER export_request_updated_at
    BEFORE UPDATE ON export_request
    FOR EACH ROW
    EXECUTE FUNCTION update_export_request_timestamp();

-- Trigger to calculate next run time when scheduled report is created/updated
CREATE OR REPLACE FUNCTION update_scheduled_report_next_run()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.is_active THEN
        NEW.next_run_at := calculate_next_run_time(
            NEW.frequency,
            NEW.day_of_week,
            NEW.day_of_month,
            NEW.time_of_day,
            NEW.timezone,
            COALESCE(NEW.last_run_at, now())
        );
    ELSE
        NEW.next_run_at := NULL;
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS scheduled_report_next_run ON scheduled_report;
CREATE TRIGGER scheduled_report_next_run
    BEFORE INSERT OR UPDATE ON scheduled_report
    FOR EACH ROW
    EXECUTE FUNCTION update_scheduled_report_next_run();

-- =============================================================================
-- SECTION 9: SEED DEFAULT REPORT TEMPLATES
-- =============================================================================

-- Seed default report templates for each organization (org-wide templates with project_id = NULL)
-- Using WHERE NOT EXISTS instead of ON CONFLICT due to partial unique indexes
INSERT INTO public.report_template (organization_id, project_id, name, description, report_type, file_format, template_config)
SELECT
    o.id,
    NULL,  -- org-wide template
    template.name,
    template.description,
    template.report_type::report_type,
    template.file_format::export_file_format,
    template.config::JSONB
FROM public.organization o
CROSS JOIN (VALUES
    ('Monthly Settlement Report', 'Calculates monthly settlement based on meter data and contract terms', 'settlement', 'pdf',
     '{"include_meter_data": true, "include_pricing": true, "include_adjustments": true}'),
    ('Compliance Status Report', 'Shows compliance status against all contract obligations', 'compliance', 'pdf',
     '{"include_breaches": true, "include_cured": true, "include_upcoming": true}'),
    ('Financial Summary', 'Revenue and expense summary for the period', 'financial_summary', 'xlsx',
     '{"include_revenue": true, "include_expenses": true, "include_projections": false}'),
    ('Invoice Aging Report', 'Outstanding invoices by age bucket', 'invoice_aging', 'pdf',
     '{"buckets": [30, 60, 90, 120], "include_details": true}'),
    ('Expense by Category', 'O&M expense breakdown by category', 'expense_by_category', 'xlsx',
     '{"include_trends": true, "include_variance": true}'),
    ('LD Summary Report', 'Liquidated damages summary and trends', 'ld_summary', 'pdf',
     '{"include_cured": true, "include_projections": false}')
) AS template(name, description, report_type, file_format, config)
WHERE NOT EXISTS (
    SELECT 1 FROM public.report_template rt
    WHERE rt.organization_id = o.id
      AND rt.project_id IS NULL
      AND rt.name = template.name
);

-- =============================================================================
-- SECTION 10: GRANT PERMISSIONS
-- =============================================================================

-- Revoke default public access (follows pattern from migration 017)
REVOKE EXECUTE ON FUNCTION check_export_requires_approval FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION calculate_next_run_time FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION get_export_statistics FROM PUBLIC;

-- Grant to specific roles
GRANT EXECUTE ON FUNCTION check_export_requires_approval TO authenticated;
GRANT EXECUTE ON FUNCTION check_export_requires_approval TO service_role;

GRANT EXECUTE ON FUNCTION calculate_next_run_time TO authenticated;
GRANT EXECUTE ON FUNCTION calculate_next_run_time TO service_role;

GRANT EXECUTE ON FUNCTION get_export_statistics TO authenticated;
GRANT EXECUTE ON FUNCTION get_export_statistics TO service_role;

-- =============================================================================
-- VERIFICATION
-- =============================================================================

DO $$
DECLARE
    v_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM information_schema.tables
    WHERE table_name IN ('export_request', 'report_template', 'scheduled_report', 'generated_report');

    IF v_count < 4 THEN
        RAISE EXCEPTION 'Not all tables were created. Expected 4, found %', v_count;
    END IF;

    RAISE NOTICE 'Migration 018_export_and_reports_schema completed successfully';
END $$;
