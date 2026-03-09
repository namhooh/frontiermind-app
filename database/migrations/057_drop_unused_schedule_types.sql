-- Migration 057: Remove unused email_schedule_type enum values
-- Drops: invoice_escalation, meter_data_missing, report_ready
-- Remaining: invoice_reminder, invoice_initial, compliance_alert, custom

-- PostgreSQL doesn't support ALTER TYPE ... DROP VALUE directly.
-- Must recreate the enum type.

BEGIN;

-- 1. Remove any schedules using the deprecated types (safety net)
DELETE FROM email_notification_schedule
WHERE email_schedule_type IN ('invoice_escalation', 'meter_data_missing', 'report_ready');

DELETE FROM email_template
WHERE email_schedule_type IN ('invoice_escalation', 'meter_data_missing', 'report_ready');

-- 2. Recreate enum without the removed values
ALTER TYPE email_schedule_type RENAME TO email_schedule_type_old;

CREATE TYPE email_schedule_type AS ENUM (
    'invoice_reminder',
    'invoice_initial',
    'compliance_alert',
    'custom'
);

-- 3. Migrate columns that use this enum
ALTER TABLE email_notification_schedule
    ALTER COLUMN email_schedule_type TYPE email_schedule_type
    USING email_schedule_type::text::email_schedule_type;

ALTER TABLE email_template
    ALTER COLUMN email_schedule_type TYPE email_schedule_type
    USING email_schedule_type::text::email_schedule_type;

-- 4. Drop the old enum type
DROP TYPE email_schedule_type_old;

COMMIT;

-- 5. Add 'daily' to report_frequency enum
-- ADD VALUE cannot run inside a transaction block, so it runs between commits
ALTER TYPE report_frequency ADD VALUE IF NOT EXISTS 'daily';

BEGIN;

-- 6. Update calculate_next_run_time() to handle 'daily' frequency
CREATE OR REPLACE FUNCTION calculate_next_run_time(
    p_frequency report_frequency,
    p_day_of_month INTEGER,
    p_time_of_day TIME,
    p_timezone TEXT DEFAULT 'UTC'
) RETURNS TIMESTAMPTZ AS $$
DECLARE
    v_next TIMESTAMPTZ;
    v_now TIMESTAMPTZ := NOW();
    v_today DATE := (v_now AT TIME ZONE p_timezone)::DATE;
    v_time TIME := COALESCE(p_time_of_day, '09:00:00'::TIME);
BEGIN
    CASE p_frequency
        WHEN 'daily' THEN
            -- Next day at the specified time
            v_next := ((v_today + INTERVAL '1 day') + v_time) AT TIME ZONE p_timezone;
            -- If we somehow computed a time in the past, add another day
            IF v_next <= v_now THEN
                v_next := v_next + INTERVAL '1 day';
            END IF;

        WHEN 'monthly' THEN
            v_next := (DATE_TRUNC('month', v_today) + ((COALESCE(p_day_of_month, 1) - 1) || ' days')::INTERVAL + v_time) AT TIME ZONE p_timezone;
            IF v_next <= v_now THEN
                v_next := (DATE_TRUNC('month', v_today + INTERVAL '1 month') + ((COALESCE(p_day_of_month, 1) - 1) || ' days')::INTERVAL + v_time) AT TIME ZONE p_timezone;
            END IF;

        WHEN 'quarterly' THEN
            v_next := (DATE_TRUNC('quarter', v_today) + ((COALESCE(p_day_of_month, 1) - 1) || ' days')::INTERVAL + v_time) AT TIME ZONE p_timezone;
            IF v_next <= v_now THEN
                v_next := (DATE_TRUNC('quarter', v_today + INTERVAL '3 months') + ((COALESCE(p_day_of_month, 1) - 1) || ' days')::INTERVAL + v_time) AT TIME ZONE p_timezone;
            END IF;

        WHEN 'annual' THEN
            v_next := (DATE_TRUNC('year', v_today) + ((COALESCE(p_day_of_month, 1) - 1) || ' days')::INTERVAL + v_time) AT TIME ZONE p_timezone;
            IF v_next <= v_now THEN
                v_next := (DATE_TRUNC('year', v_today + INTERVAL '1 year') + ((COALESCE(p_day_of_month, 1) - 1) || ' days')::INTERVAL + v_time) AT TIME ZONE p_timezone;
            END IF;

        ELSE
            -- on_demand or unknown: no automatic next run
            RETURN NULL;
    END CASE;

    RETURN v_next;
END;
$$ LANGUAGE plpgsql;

-- 7. Relax chk_email_frequency_requires_day to allow daily without day_of_month
ALTER TABLE email_notification_schedule DROP CONSTRAINT IF EXISTS chk_email_frequency_requires_day;
ALTER TABLE email_notification_schedule ADD CONSTRAINT chk_email_frequency_requires_day
    CHECK (
        report_frequency IN ('on_demand', 'daily')
        OR day_of_month IS NOT NULL
    );

COMMIT;

