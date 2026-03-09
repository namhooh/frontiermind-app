-- Migration 053: Organization-Scoped API Keys
--
-- Makes data_source_id nullable so credentials can be org-wide (not tied to a
-- specific inverter/source). Adds allowed_scopes for fine-grained permission
-- control and api_key_hash for O(1) key lookup.
--
-- Backward compatible: existing source-scoped keys continue to work unchanged.

BEGIN;

-- 1. Make data_source_id nullable (backward compatible)
ALTER TABLE integration_credential
  ALTER COLUMN data_source_id DROP NOT NULL;

-- 2. Add allowed_scopes as TEXT[] with CHECK constraint
-- NULL = all scopes allowed (org-wide key)
-- Non-null = restricted to listed scopes
ALTER TABLE integration_credential
  ADD COLUMN IF NOT EXISTS allowed_scopes TEXT[] DEFAULT NULL;

-- 3. Validate scope values
ALTER TABLE integration_credential
  ADD CONSTRAINT chk_allowed_scopes_valid CHECK (
    allowed_scopes IS NULL
    OR allowed_scopes <@ ARRAY['meter_data', 'fx_rates', 'billing_reads']::TEXT[]
  );

-- 4. Add api_key_hash for indexed lookup (avoid O(n) decrypt scan)
ALTER TABLE integration_credential
  ADD COLUMN IF NOT EXISTS api_key_hash VARCHAR(64) DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_credential_api_key_hash
  ON integration_credential(api_key_hash) WHERE api_key_hash IS NOT NULL;

COMMENT ON COLUMN integration_credential.data_source_id IS 'Optional FK. NULL = org-scoped key. Non-NULL = legacy source-scoped key.';
COMMENT ON COLUMN integration_credential.allowed_scopes IS 'Optional scope restriction. NULL = all scopes. E.g. {meter_data,fx_rates}.';
COMMENT ON COLUMN integration_credential.api_key_hash IS 'SHA-256 hash of plaintext API key for indexed lookup. Full key verified via hmac after hash match.';

COMMIT;
