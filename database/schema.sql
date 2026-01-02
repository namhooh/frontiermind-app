-- =========================
-- SECTION 1: TABLES
-- =========================

CREATE TABLE organization (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  address VARCHAR,
  country VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE role (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT REFERENCES organization(id),
  name VARCHAR NOT NULL,
  email VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE project (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT REFERENCES organization(id), -- N:M
  name VARCHAR NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE contractor_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE contractor (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT REFERENCES project(id), -- N:M
  contractor_type_id BIGINT REFERENCES contractor_type(id),
  name VARCHAR NOT NULL,
  email VARCHAR,
  address VARCHAR,
  country VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE contract_counterparty (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  address VARCHAR,
  country VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE contract_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE contract_status (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE contract (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT REFERENCES project(id),
  organization_id BIGINT REFERENCES organization(id), -- N:M
  contract_counterparty_id BIGINT REFERENCES contract_counterparty(id), -- N:M
  contract_type_id BIGINT REFERENCES contract_type(id),
  contract_status_id BIGINT REFERENCES contract_status(id), -- N:M
  name VARCHAR NOT NULL,
  description VARCHAR,
  effective_date DATE,
  end_date DATE,
  file_location VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by VARCHAR, 
  version INTEGER
);

CREATE TABLE clause_responsibleparty (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  address VARCHAR,
  country VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE clause_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE clause_category (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE clause (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT REFERENCES project(id),
  contract_id BIGINT REFERENCES contract(id),
  clause_responsibleparty_id BIGINT REFERENCES clause_responsibleparty(id), -- N:M
  clause_type_id BIGINT REFERENCES clause_type(id), 
  clause_category_id BIGINT REFERENCES clause_category(id), 
  name VARCHAR NOT NULL,
  section_ref VARCHAR,
  raw_text VARCHAR,
  normalized_payload JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by VARCHAR, 
  version INTEGER
);

CREATE TYPE updated_frequency AS ENUM ('daily', 'hourly', '15min', 'min', 'sec', 'millisec');
CREATE TABLE data_source (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  description VARCHAR,
  updated_frequency updated_frequency NOT NULL DEFAULT 'daily',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE vendor (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  address VARCHAR,
  country VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE asset_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE asset (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT REFERENCES project(id),
  asset_type_id BIGINT REFERENCES asset_type(id),
  vendor_id BIGINT REFERENCES vendor(id), -- N:M
  name VARCHAR NOT NULL,
  description VARCHAR,
  model VARCHAR,
  serial_code VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE meter_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE meter (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT REFERENCES project(id),
  asset_id BIGINT REFERENCES asset(id),
  vendor_id BIGINT REFERENCES vendor(id), -- N:M
  meter_type_id BIGINT REFERENCES meter_type(id),
  model VARCHAR,
  unit VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE meter_reading (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT REFERENCES project(id),
  meter_id BIGINT REFERENCES meter(id),
  meter_type_id BIGINT REFERENCES meter_type(id),
  value DECIMAL,
  reading_timestamp TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE event_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TYPE status AS ENUM ('open', 'closed');
CREATE TABLE event (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT REFERENCES project(id),
  organization_id BIGINT REFERENCES organization(id), -- N:M
  data_source_id BIGINT REFERENCES data_source(id), -- N:M
  event_type_id BIGINT REFERENCES event_type(id),
  description VARCHAR,
  raw_data JSONB,
  metric_outcome JSONB,
  time_start TIMESTAMPTZ,
  time_acknowledged TIMESTAMPTZ,
  time_fixed TIMESTAMPTZ,
  time_end TIMESTAMPTZ,
  status status NOT NULL DEFAULT 'open',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ,
  created_by VARCHAR,
  updated_by VARCHAR
);

CREATE TABLE default_event_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE default_event (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT REFERENCES project(id),
  organization_id BIGINT REFERENCES organization(id), -- N:M
  contract_id BIGINT REFERENCES contract(id), -- N:M
  event_id BIGINT REFERENCES event(id), -- N:M
  default_event_type_id BIGINT REFERENCES default_event_type(id),
  description VARCHAR,
  metadata_detail JSONB,
  cure_deadline TIMESTAMPTZ,
  time_start TIMESTAMPTZ,
  time_acknowledged TIMESTAMPTZ,
  time_cured TIMESTAMPTZ,
  status status NOT NULL DEFAULT 'open',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ,
  created_by VARCHAR,
  updated_by VARCHAR
);

CREATE TABLE rule_output_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE currency (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL UNIQUE   -- USD, EUR, ZAR, etc.
);

CREATE TABLE rule_output (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT REFERENCES project(id),
  default_event_id BIGINT REFERENCES default_event(id), 
  clause_id BIGINT REFERENCES clause(id), -- N:M
  rule_output_type_id BIGINT REFERENCES rule_output_type(id),
  currency_id BIGINT REFERENCES currency(id),
  description VARCHAR,
  metadata_detail JSONB,
  ld_amount DECIMAL,
  invoice_adjustment DECIMAL,
  breach BOOLEAN NOT NULL DEFAULT true,
  excuse BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ,
  created_by VARCHAR,
  updated_by VARCHAR
);

CREATE TABLE notification_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE notification (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT REFERENCES organization(id), -- N:M
  project_id BIGINT REFERENCES project(id),
  default_event_id BIGINT REFERENCES default_event(id), 
  rule_output_id BIGINT REFERENCES rule_output(id), 
  notification_type_id BIGINT REFERENCES notification_type(id),
  description VARCHAR,
  metadata_detail JSONB,
  time_notified TIMESTAMPTZ,
  time_due TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);


  


-- =========================
-- SECTION 2: RELATIONSHIPS
-- =========================

-- ALTER TABLE project
-- ADD CONSTRAINT fk_project_organization
-- FOREIGN KEY (organization_id)
-- REFERENCES organization(id);

-- =========================
-- SECTION 3: INDEXES
-- =========================

-- CREATE INDEX idx_project_organization_id
-- ON project(organization_id);
