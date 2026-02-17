-- Migration: 032_email_notification_engine.sql
-- Description: Email notification engine with scheduling, templates, and submission tokens
-- Version: v8.0
-- Date: 2026-02-15
-- Depends on: 031_generated_report_invoice_direction.sql, 028_customer_contact.sql

-- =============================================================================
-- SECTION 1: ENUMS
-- =============================================================================

-- Email schedule types
CREATE TYPE email_schedule_type AS ENUM (
    'invoice_reminder',
    'invoice_initial',
    'invoice_escalation',
    'compliance_alert',
    'meter_data_missing',
    'report_ready',
    'custom'
);

-- Email delivery status
CREATE TYPE email_status AS ENUM (
    'pending',
    'sending',
    'delivered',
    'bounced',
    'failed',
    'suppressed'
);

-- Submission token lifecycle
CREATE TYPE submission_token_status AS ENUM (
    'active',
    'used',
    'expired',
    'revoked'
);

-- Extend audit_action_type with notification events
ALTER TYPE audit_action_type ADD VALUE IF NOT EXISTS 'EMAIL_SENT';
ALTER TYPE audit_action_type ADD VALUE IF NOT EXISTS 'EMAIL_FAILED';
ALTER TYPE audit_action_type ADD VALUE IF NOT EXISTS 'SUBMISSION_RECEIVED';
ALTER TYPE audit_action_type ADD VALUE IF NOT EXISTS 'SUBMISSION_TOKEN_CREATED';

-- =============================================================================
-- SECTION 2: EMAIL TEMPLATE TABLE
-- =============================================================================

CREATE TABLE email_template (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,

    email_schedule_type email_schedule_type NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,

    -- Jinja2 template content
    subject_template VARCHAR(500) NOT NULL,
    body_html TEXT NOT NULL,
    body_text TEXT,

    -- Variables available for template rendering
    available_variables JSONB NOT NULL DEFAULT '[]',

    -- System templates cannot be deleted by users
    is_system BOOLEAN NOT NULL DEFAULT false,
    is_active BOOLEAN NOT NULL DEFAULT true,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID REFERENCES auth.users(id),
    updated_by UUID REFERENCES auth.users(id)
);

-- Unique template name per org
CREATE UNIQUE INDEX ux_email_template_org_name
    ON email_template (organization_id, name);

CREATE INDEX idx_email_template_org_active
    ON email_template(organization_id, is_active);
CREATE INDEX idx_email_template_schedule_type
    ON email_template(email_schedule_type);

-- =============================================================================
-- SECTION 3: EMAIL NOTIFICATION SCHEDULE TABLE
-- =============================================================================

CREATE TABLE email_notification_schedule (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    email_template_id BIGINT NOT NULL REFERENCES email_template(id) ON DELETE CASCADE,

    name VARCHAR(255) NOT NULL,
    email_schedule_type email_schedule_type NOT NULL,

    -- Reuse report_frequency enum from migration 018
    report_frequency report_frequency NOT NULL,
    day_of_month INTEGER,
    time_of_day TIME NOT NULL DEFAULT '09:00:00',
    timezone VARCHAR(50) NOT NULL DEFAULT 'UTC',

    -- Conditions for matching invoices/entities (evaluated at runtime)
    conditions JSONB NOT NULL DEFAULT '{}',

    -- Reminder controls
    max_reminders INTEGER DEFAULT 3,
    escalation_after INTEGER DEFAULT 1,

    -- Submission link configuration
    include_submission_link BOOLEAN NOT NULL DEFAULT false,
    submission_fields JSONB DEFAULT '[]',

    -- Schedule state
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_run_at TIMESTAMPTZ,
    last_run_status VARCHAR(20),
    last_run_error TEXT,
    next_run_at TIMESTAMPTZ,

    -- Scoping (optional narrowing)
    project_id BIGINT REFERENCES project(id),
    contract_id BIGINT REFERENCES contract(id),
    counterparty_id BIGINT REFERENCES counterparty(id),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID REFERENCES auth.users(id),

    -- Constraints
    CONSTRAINT chk_email_day_of_month_range
        CHECK (day_of_month IS NULL OR (day_of_month BETWEEN 1 AND 28)),
    CONSTRAINT chk_email_frequency_requires_day
        CHECK (
            report_frequency = 'on_demand'
            OR (report_frequency IN ('monthly', 'quarterly', 'annual') AND day_of_month IS NOT NULL)
        ),
    CONSTRAINT chk_email_max_reminders_positive
        CHECK (max_reminders IS NULL OR max_reminders > 0),
    CONSTRAINT chk_email_escalation_after_positive
        CHECK (escalation_after IS NULL OR escalation_after > 0)
);

-- Scheduler lookup index (same pattern as scheduled_report)
CREATE INDEX idx_email_schedule_scheduler
    ON email_notification_schedule (is_active, next_run_at, organization_id)
    WHERE is_active = true;
CREATE INDEX idx_email_schedule_template
    ON email_notification_schedule(email_template_id);
CREATE INDEX idx_email_schedule_org
    ON email_notification_schedule(organization_id);

-- =============================================================================
-- SECTION 4: EMAIL LOG TABLE
-- =============================================================================

CREATE TABLE email_log (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,

    email_notification_schedule_id BIGINT REFERENCES email_notification_schedule(id) ON DELETE SET NULL,
    email_template_id BIGINT REFERENCES email_template(id) ON DELETE SET NULL,

    recipient_email VARCHAR(255) NOT NULL,
    recipient_name VARCHAR(255),
    subject VARCHAR(500) NOT NULL,
    email_status email_status NOT NULL DEFAULT 'pending',

    -- SES tracking
    ses_message_id VARCHAR(255),

    -- Context
    reminder_count INTEGER DEFAULT 0,
    invoice_header_id BIGINT REFERENCES invoice_header(id) ON DELETE SET NULL,
    submission_token_id BIGINT,  -- FK added after submission_token table creation

    -- Error tracking
    error_message TEXT,
    bounce_type VARCHAR(50),

    sent_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    bounced_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_email_log_org_created
    ON email_log(organization_id, created_at DESC);
CREATE INDEX idx_email_log_schedule
    ON email_log(email_notification_schedule_id)
    WHERE email_notification_schedule_id IS NOT NULL;
CREATE INDEX idx_email_log_invoice
    ON email_log(invoice_header_id)
    WHERE invoice_header_id IS NOT NULL;
CREATE INDEX idx_email_log_status
    ON email_log(email_status);
CREATE INDEX idx_email_log_ses_message
    ON email_log(ses_message_id)
    WHERE ses_message_id IS NOT NULL;

-- =============================================================================
-- SECTION 5: SUBMISSION TOKEN TABLE
-- =============================================================================

CREATE TABLE submission_token (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,

    -- Token stored as SHA-256 hash (raw token never persisted)
    token_hash VARCHAR(64) NOT NULL,

    -- What data to collect
    submission_fields JSONB NOT NULL DEFAULT '[]',
    submission_token_status submission_token_status NOT NULL DEFAULT 'active',

    -- Usage limits
    max_uses INTEGER NOT NULL DEFAULT 1,
    use_count INTEGER NOT NULL DEFAULT 0,
    expires_at TIMESTAMPTZ NOT NULL,

    -- Linked entity
    invoice_header_id BIGINT REFERENCES invoice_header(id) ON DELETE SET NULL,
    counterparty_id BIGINT REFERENCES counterparty(id) ON DELETE SET NULL,
    email_log_id BIGINT REFERENCES email_log(id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_token_max_uses_positive
        CHECK (max_uses > 0),
    CONSTRAINT chk_token_use_count_valid
        CHECK (use_count >= 0 AND use_count <= max_uses)
);

CREATE UNIQUE INDEX ux_submission_token_hash
    ON submission_token(token_hash);
CREATE INDEX idx_submission_token_org
    ON submission_token(organization_id);
CREATE INDEX idx_submission_token_status
    ON submission_token(submission_token_status)
    WHERE submission_token_status = 'active';
CREATE INDEX idx_submission_token_expires
    ON submission_token(expires_at)
    WHERE submission_token_status = 'active';

-- Now add FK from email_log to submission_token
ALTER TABLE email_log
    ADD CONSTRAINT fk_email_log_submission_token
    FOREIGN KEY (submission_token_id) REFERENCES submission_token(id) ON DELETE SET NULL;

-- =============================================================================
-- SECTION 6: SUBMISSION RESPONSE TABLE
-- =============================================================================

CREATE TABLE submission_response (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    submission_token_id BIGINT NOT NULL REFERENCES submission_token(id) ON DELETE CASCADE,

    -- Response data
    response_data JSONB NOT NULL DEFAULT '{}',
    submitted_by_email VARCHAR(255),
    ip_address INET,

    -- Linked invoice (denormalized from token for query convenience)
    invoice_header_id BIGINT REFERENCES invoice_header(id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_submission_response_token
    ON submission_response(submission_token_id);
CREATE INDEX idx_submission_response_org
    ON submission_response(organization_id, created_at DESC);
CREATE INDEX idx_submission_response_invoice
    ON submission_response(invoice_header_id)
    WHERE invoice_header_id IS NOT NULL;

-- =============================================================================
-- SECTION 7: ROW LEVEL SECURITY
-- =============================================================================

ALTER TABLE email_template ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_notification_schedule ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE submission_token ENABLE ROW LEVEL SECURITY;
ALTER TABLE submission_response ENABLE ROW LEVEL SECURITY;

-- Email template policies
DROP POLICY IF EXISTS email_template_select_policy ON email_template;
CREATE POLICY email_template_select_policy ON email_template
    FOR SELECT TO authenticated
    USING (is_org_member(organization_id));

DROP POLICY IF EXISTS email_template_admin_policy ON email_template;
CREATE POLICY email_template_admin_policy ON email_template
    FOR ALL TO authenticated
    USING (is_org_admin(organization_id))
    WITH CHECK (is_org_admin(organization_id));

DROP POLICY IF EXISTS email_template_service_policy ON email_template;
CREATE POLICY email_template_service_policy ON email_template
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- Email notification schedule policies
DROP POLICY IF EXISTS email_schedule_select_policy ON email_notification_schedule;
CREATE POLICY email_schedule_select_policy ON email_notification_schedule
    FOR SELECT TO authenticated
    USING (is_org_member(organization_id));

DROP POLICY IF EXISTS email_schedule_admin_policy ON email_notification_schedule;
CREATE POLICY email_schedule_admin_policy ON email_notification_schedule
    FOR ALL TO authenticated
    USING (is_org_admin(organization_id))
    WITH CHECK (is_org_admin(organization_id));

DROP POLICY IF EXISTS email_schedule_service_policy ON email_notification_schedule;
CREATE POLICY email_schedule_service_policy ON email_notification_schedule
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- Email log policies
DROP POLICY IF EXISTS email_log_select_policy ON email_log;
CREATE POLICY email_log_select_policy ON email_log
    FOR SELECT TO authenticated
    USING (is_org_member(organization_id));

DROP POLICY IF EXISTS email_log_service_policy ON email_log;
CREATE POLICY email_log_service_policy ON email_log
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- Submission token policies
DROP POLICY IF EXISTS submission_token_select_policy ON submission_token;
CREATE POLICY submission_token_select_policy ON submission_token
    FOR SELECT TO authenticated
    USING (is_org_member(organization_id));

DROP POLICY IF EXISTS submission_token_service_policy ON submission_token;
CREATE POLICY submission_token_service_policy ON submission_token
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- Submission response policies
DROP POLICY IF EXISTS submission_response_select_policy ON submission_response;
CREATE POLICY submission_response_select_policy ON submission_response
    FOR SELECT TO authenticated
    USING (is_org_member(organization_id));

DROP POLICY IF EXISTS submission_response_service_policy ON submission_response;
CREATE POLICY submission_response_service_policy ON submission_response
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- =============================================================================
-- SECTION 8: TRIGGERS
-- =============================================================================

-- Timestamp trigger for email_template
CREATE OR REPLACE FUNCTION update_email_template_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        NEW.updated_at = now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS email_template_updated_at ON email_template;
CREATE TRIGGER email_template_updated_at
    BEFORE INSERT OR UPDATE ON email_template
    FOR EACH ROW
    EXECUTE FUNCTION update_email_template_timestamp();

-- Trigger to calculate next_run_at for email schedules
-- Reuses calculate_next_run_time() from migration 018
CREATE OR REPLACE FUNCTION update_email_schedule_next_run()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.is_active AND NEW.report_frequency != 'on_demand' THEN
        NEW.next_run_at := calculate_next_run_time(
            NEW.report_frequency,
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

DROP TRIGGER IF EXISTS email_schedule_next_run ON email_notification_schedule;
CREATE TRIGGER email_schedule_next_run
    BEFORE INSERT OR UPDATE ON email_notification_schedule
    FOR EACH ROW
    EXECUTE FUNCTION update_email_schedule_next_run();

-- =============================================================================
-- SECTION 9: SEED SYSTEM EMAIL TEMPLATES
-- =============================================================================

INSERT INTO email_template (
    organization_id, email_schedule_type, name, description,
    subject_template, body_html, body_text,
    available_variables, is_system
)
SELECT
    o.id,
    template.email_schedule_type::email_schedule_type,
    template.name,
    template.description,
    template.subject_template,
    template.body_html,
    template.body_text,
    template.available_variables::JSONB,
    true
FROM organization o
CROSS JOIN (VALUES
    (
        'invoice_initial',
        'Invoice Delivery',
        'Initial invoice delivery to counterparty',
        'Invoice {{ invoice_number }} - {{ counterparty_name }}',
        '<p>Dear {{ counterparty_name }},</p><p>Please find attached invoice <strong>{{ invoice_number }}</strong> for the period {{ period_start }} to {{ period_end }}.</p><p>Amount due: <strong>{{ total_amount | format_currency }}</strong></p><p>Due date: <strong>{{ due_date | format_date }}</strong></p>{% if submission_url %}<p><a href="{{ submission_url }}">Submit PO Number / Confirm Receipt</a></p>{% endif %}<p>Regards,<br/>{{ sender_name }}</p>',
        'Invoice {{ invoice_number }} for {{ counterparty_name }}. Amount: {{ total_amount }}. Due: {{ due_date }}.{% if submission_url %} Submit response: {{ submission_url }}{% endif %}',
        '["invoice_number", "counterparty_name", "total_amount", "due_date", "period_start", "period_end", "submission_url", "sender_name"]'
    ),
    (
        'invoice_reminder',
        'Payment Reminder',
        'Payment reminder for overdue invoices',
        'Payment Reminder: Invoice {{ invoice_number }} - {{ days_overdue }} days overdue',
        '<p>Dear {{ counterparty_name }},</p><p>This is a friendly reminder that invoice <strong>{{ invoice_number }}</strong> is now <strong>{{ days_overdue }} days overdue</strong>.</p><p>Amount due: <strong>{{ total_amount | format_currency }}</strong></p><p>Original due date: <strong>{{ due_date | format_date }}</strong></p><p>This is reminder {{ reminder_count }} of {{ max_reminders }}.</p>{% if submission_url %}<p><a href="{{ submission_url }}">Confirm Payment / Provide Update</a></p>{% endif %}<p>Regards,<br/>{{ sender_name }}</p>',
        'Payment reminder for invoice {{ invoice_number }}. {{ days_overdue }} days overdue. Amount: {{ total_amount }}. Reminder {{ reminder_count }} of {{ max_reminders }}.{% if submission_url %} Respond: {{ submission_url }}{% endif %}',
        '["invoice_number", "counterparty_name", "total_amount", "due_date", "days_overdue", "reminder_count", "max_reminders", "submission_url", "sender_name"]'
    ),
    (
        'invoice_escalation',
        'Invoice Escalation',
        'Escalation notice for significantly overdue invoices',
        'ESCALATION: Invoice {{ invoice_number }} - {{ days_overdue }} days overdue',
        '<p>Dear {{ counterparty_name }},</p><p>This is an escalation notice regarding invoice <strong>{{ invoice_number }}</strong>, which is now <strong>{{ days_overdue }} days overdue</strong>.</p><p>Amount due: <strong>{{ total_amount | format_currency }}</strong></p><p>Previous reminders have been sent without response. Please address this matter urgently.</p>{% if submission_url %}<p><a href="{{ submission_url }}">Provide Payment Update</a></p>{% endif %}<p>Regards,<br/>{{ sender_name }}</p>',
        'ESCALATION: Invoice {{ invoice_number }} is {{ days_overdue }} days overdue. Amount: {{ total_amount }}. Immediate attention required.{% if submission_url %} Respond: {{ submission_url }}{% endif %}',
        '["invoice_number", "counterparty_name", "total_amount", "due_date", "days_overdue", "submission_url", "sender_name"]'
    ),
    (
        'compliance_alert',
        'Compliance Alert',
        'Contract compliance breach notification',
        'Compliance Alert: {{ contract_name }} - {{ alert_type }}',
        '<p>Dear {{ counterparty_name }},</p><p>A compliance issue has been detected for contract <strong>{{ contract_name }}</strong>.</p><p>Alert type: <strong>{{ alert_type }}</strong></p><p>Details: {{ alert_details }}</p><p>Please review and take appropriate action.</p><p>Regards,<br/>{{ sender_name }}</p>',
        'Compliance alert for {{ contract_name }}: {{ alert_type }}. {{ alert_details }}',
        '["contract_name", "counterparty_name", "alert_type", "alert_details", "sender_name"]'
    )
) AS template(email_schedule_type, name, description, subject_template, body_html, body_text, available_variables)
WHERE NOT EXISTS (
    SELECT 1 FROM email_template et
    WHERE et.organization_id = o.id
      AND et.name = template.name
);

-- =============================================================================
-- SECTION 10: GRANT PERMISSIONS
-- =============================================================================

REVOKE EXECUTE ON FUNCTION update_email_template_timestamp FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION update_email_schedule_next_run FROM PUBLIC;

GRANT EXECUTE ON FUNCTION update_email_template_timestamp TO service_role;
GRANT EXECUTE ON FUNCTION update_email_schedule_next_run TO service_role;

-- =============================================================================
-- SECTION 11: VERIFICATION
-- =============================================================================

DO $$
DECLARE
    v_count INTEGER;
BEGIN
    -- Check tables exist
    SELECT COUNT(*) INTO v_count
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name IN (
          'email_template',
          'email_notification_schedule',
          'email_log',
          'submission_token',
          'submission_response'
      );

    IF v_count < 5 THEN
        RAISE EXCEPTION 'Not all tables were created. Expected 5, found %', v_count;
    END IF;

    -- Check enums exist
    PERFORM 1 FROM pg_type WHERE typname = 'email_schedule_type';
    IF NOT FOUND THEN RAISE EXCEPTION 'email_schedule_type enum not found'; END IF;

    PERFORM 1 FROM pg_type WHERE typname = 'email_status';
    IF NOT FOUND THEN RAISE EXCEPTION 'email_status enum not found'; END IF;

    PERFORM 1 FROM pg_type WHERE typname = 'submission_token_status';
    IF NOT FOUND THEN RAISE EXCEPTION 'submission_token_status enum not found'; END IF;

    RAISE NOTICE 'Migration 032_email_notification_engine (v8.0) completed successfully';
END $$;
