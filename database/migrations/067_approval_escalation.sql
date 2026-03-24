-- Migration 067: Multi-approver escalation system
--
-- Adds:
--   1. approval_chain_type table — defines approval workflow steps
--   2. approval_escalation_rule table — threshold-based conditions that select a chain
--   3. New columns on change_request for multi-step tracking
--   4. Renames change_request.policy_key → change_type
--
-- Backward compatible: existing change_requests with NULL approval_chain_type
-- continue to use the legacy single-approver flow.

-- ============================================================================
-- 1. Rename policy_key → change_type on change_request
-- ============================================================================

ALTER TABLE change_request RENAME COLUMN policy_key TO change_type;

-- ============================================================================
-- 2. approval_chain_type — each row is one step in an approval chain
-- ============================================================================

CREATE TABLE IF NOT EXISTS approval_chain (
    id                    BIGSERIAL PRIMARY KEY,
    organization_id       BIGINT NOT NULL REFERENCES organization(id),

    -- Chain identity (rows with same org + approval_chain_type form a chain)
    approval_chain_type   TEXT NOT NULL,

    -- Step definition
    step_order            INT NOT NULL,
    step_name             TEXT,

    -- WHO must approve (at least one must be set)
    assigned_approver_id  UUID,
    approver_role_type    TEXT,
    approver_department   TEXT,

    -- Per-step four-eyes
    allow_self_approve    BOOLEAN NOT NULL DEFAULT false,

    is_active             BOOLEAN NOT NULL DEFAULT true,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Each chain+step combination is unique per org
    UNIQUE (organization_id, approval_chain_type, step_order),

    -- At least one approver specification must be set
    CONSTRAINT valid_approver_spec CHECK (
        assigned_approver_id IS NOT NULL OR
        approver_role_type IS NOT NULL OR
        approver_department IS NOT NULL
    )
);

CREATE INDEX idx_approval_chain_lookup
    ON approval_chain (organization_id, approval_chain_type)
    WHERE is_active = true;

-- ============================================================================
-- 3. approval_escalation_rule — threshold conditions that select a chain
-- ============================================================================

CREATE TABLE IF NOT EXISTS approval_escalation_rule (
    id                    BIGSERIAL PRIMARY KEY,
    organization_id       BIGINT NOT NULL REFERENCES organization(id),

    -- Which change type this rule applies to (e.g., 'billing_entry')
    change_type           TEXT NOT NULL,

    -- Human-readable rule name
    name                  TEXT NOT NULL,

    -- Evaluation order (lower = evaluated first, first match wins)
    priority              INT NOT NULL DEFAULT 100,

    -- Condition definition
    condition_type        TEXT NOT NULL,
    condition_field       TEXT,
    condition_operator    TEXT NOT NULL,
    condition_value       JSONB NOT NULL,

    -- Which approval chain to use when this rule matches
    approval_chain_type   TEXT NOT NULL,

    is_active             BOOLEAN NOT NULL DEFAULT true,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_condition_type CHECK (
        condition_type IN ('absolute_value', 'pct_change', 'value_threshold')
    ),
    CONSTRAINT valid_condition_operator CHECK (
        condition_operator IN ('gt', 'gte', 'lt', 'lte', 'eq', 'neq')
    )
);

CREATE INDEX idx_approval_escalation_rule_lookup
    ON approval_escalation_rule (organization_id, change_type, priority)
    WHERE is_active = true;

-- ============================================================================
-- 4. Add multi-step columns to change_request
-- ============================================================================

ALTER TABLE change_request
    ADD COLUMN IF NOT EXISTS approval_chain_type TEXT,
    ADD COLUMN IF NOT EXISTS current_step_order INT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS total_steps INT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS approval_steps JSONB;

COMMENT ON COLUMN change_request.approval_chain_type IS 'NULL = legacy single-approver flow. Set = multi-step via approval_steps JSONB.';
COMMENT ON COLUMN change_request.current_step_order IS 'Which step is currently active (1-indexed). Advances on each step approval.';
COMMENT ON COLUMN change_request.total_steps IS 'Total number of approval steps. 1 for legacy flow.';
COMMENT ON COLUMN change_request.approval_steps IS 'JSONB array of step states: [{step_order, step_name, step_status, approved_by, approved_at, approval_note}]';
