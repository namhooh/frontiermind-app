-- Migration: 002_add_contract_pii_mapping.sql
-- Description: Add contract PII mapping table with encrypted storage
-- Author: Phase 2 - Database Integration
-- Date: 2026-01-11

-- ==============================================================================
-- UP Migration
-- ==============================================================================

-- Enable pgcrypto extension for encryption (if not already enabled)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Create contract_pii_mapping table for encrypted PII storage
-- This table stores PII mappings separately from contracts for enhanced security
CREATE TABLE contract_pii_mapping (
  id BIGSERIAL PRIMARY KEY,
  contract_id BIGINT NOT NULL REFERENCES contract(id) ON DELETE CASCADE,

  -- Encrypted PII mapping (JSON encrypted with AES-256)
  -- Structure: {"<PERSON_1>": "John Smith", "<EMAIL_1>": "john@example.com", ...}
  encrypted_mapping BYTEA NOT NULL,

  -- Metadata
  pii_entities_count INTEGER NOT NULL DEFAULT 0,
  encryption_method VARCHAR(50) NOT NULL DEFAULT 'aes-256-gcm',

  -- Audit trail
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by UUID REFERENCES auth.users(id),
  accessed_at TIMESTAMPTZ,
  accessed_by UUID REFERENCES auth.users(id),
  access_count INTEGER NOT NULL DEFAULT 0,

  -- Constraints
  CONSTRAINT pii_entities_count_positive CHECK (pii_entities_count >= 0),
  CONSTRAINT access_count_non_negative CHECK (access_count >= 0)
);

-- Create indexes for performance
CREATE INDEX idx_contract_pii_mapping_contract_id ON contract_pii_mapping(contract_id);
CREATE INDEX idx_contract_pii_mapping_created_at ON contract_pii_mapping(created_at);
CREATE INDEX idx_contract_pii_mapping_accessed_at ON contract_pii_mapping(accessed_at);

-- Add comments explaining encryption approach
COMMENT ON TABLE contract_pii_mapping IS
'Stores encrypted PII mappings for contracts. PII is detected locally (Presidio),
anonymized before sending to external AI services, and stored encrypted using
application-level encryption keys. Access is logged and restricted to admin users.';

COMMENT ON COLUMN contract_pii_mapping.encrypted_mapping IS
'AES-256-GCM encrypted JSON mapping of placeholder tokens to original PII values.
Encryption key is stored in application secrets (not in database).
Format: {"<PERSON_1>": "John Smith", "<EMAIL_1>": "john@example.com"}';

COMMENT ON COLUMN contract_pii_mapping.pii_entities_count IS
'Number of PII entities detected and anonymized. Used for auditing and metrics.';

-- Enable Row Level Security (RLS)
ALTER TABLE contract_pii_mapping ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Only admins can SELECT PII mappings
CREATE POLICY contract_pii_mapping_select_policy ON contract_pii_mapping
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM auth.users u
      JOIN role r ON r.user_id = u.id
      WHERE u.id = auth.uid()
      AND r.role_type = 'admin'
      AND r.is_active = TRUE
    )
  );

-- RLS Policy: System can INSERT (application service account)
-- Note: In production, use a specific service account role
CREATE POLICY contract_pii_mapping_insert_policy ON contract_pii_mapping
  FOR INSERT
  WITH CHECK (TRUE);  -- Application handles authorization

-- RLS Policy: Admins can UPDATE to track access
CREATE POLICY contract_pii_mapping_update_policy ON contract_pii_mapping
  FOR UPDATE
  USING (
    EXISTS (
      SELECT 1 FROM auth.users u
      JOIN role r ON r.user_id = u.id
      WHERE u.id = auth.uid()
      AND r.role_type = 'admin'
      AND r.is_active = TRUE
    )
  );

-- Helper function: Log PII access
CREATE OR REPLACE FUNCTION log_pii_access(
  p_contract_id BIGINT
) RETURNS VOID AS $$
BEGIN
  -- Update access tracking
  UPDATE contract_pii_mapping
  SET
    accessed_at = NOW(),
    accessed_by = auth.uid(),
    access_count = access_count + 1
  WHERE contract_id = p_contract_id;

  -- Log to audit trail (if audit table exists)
  -- INSERT INTO audit_log (table_name, record_id, action, user_id, timestamp)
  -- VALUES ('contract_pii_mapping', p_contract_id, 'PII_ACCESS', auth.uid(), NOW());
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION log_pii_access IS
'Logs access to contract PII mapping. Called whenever PII is decrypted.
Creates audit trail for compliance and security monitoring.';

-- Helper function: Get PII entity count for a contract
CREATE OR REPLACE FUNCTION get_contract_pii_count(
  p_contract_id BIGINT
) RETURNS INTEGER AS $$
DECLARE
  v_count INTEGER;
BEGIN
  SELECT pii_entities_count INTO v_count
  FROM contract_pii_mapping
  WHERE contract_id = p_contract_id;

  RETURN COALESCE(v_count, 0);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION get_contract_pii_count IS
'Returns the number of PII entities detected in a contract.
Returns 0 if no PII mapping exists for the contract.';

