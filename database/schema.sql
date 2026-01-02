-- =========================
-- SECTION 1: TABLES
-- =========================

CREATE TABLE organization (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  address VARCHAR NOT NULL,
  country VARCHAR NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE role (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGSERIAL REFERENCES organization(id),
  name VARCHAR NOT NULL,
  email VARCHAR NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE contractor (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGSERIAL REFERENCES project(id), -- N:M
  contractor_type_id BIGSERIAL REFERENCES contractor_type(id),
  name VARCHAR NOT NULL,
  email VARCHAR NOT NULL,
  address VARCHAR NOT NULL,
  country VARCHAR NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE contractor_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE project (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGSERIAL REFERENCES organization(id), -- N:M
  name VARCHAR NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE contract (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGSERIAL REFERENCES project(id),
  organization_id BIGSERIAL REFERENCES organization(id), -- N:M
  contract_counterparty_id BIGSERIAL REFERENCES contract_counterparty(id), -- N:M
  contract_type_id BIGSERIAL REFERENCES contract_type(id),
  contract_status_id BIGSERIAL REFERENCES contract_status(id), -- N:M
  name VARCHAR NOT NULL,
  description VARCHAR,
  effective_date DATE,
  end_date DATE,
  file_location URL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by VARCHAR, 
  version INTEGER
);

CREATE TABLE contract_counterparty (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  address VARCHAR NOT NULL,
  country VARCHAR NOT NULL,
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

CREATE TABLE clause (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGSERIAL REFERENCES project(id),
  contract_id BIGSERIAL REFERENCES contract(id),
  clause_responsibleparty_id BIGSERIAL REFERENCES clause_responsibleparty(id), -- N:M
  clause_type_id BIGSERIAL REFERENCES clause_type(id), 
  clause_category_id BIGSERIAL REFERENCES clause_category(id), 
  name VARCHAR NOT NULL,
  section_ref VARCHAR,
  raw_text VARCHAR,
  normalized_payload JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by VARCHAR, 
  version INTEGER
);

CREATE TABLE clause_responsibleparty (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  address VARCHAR NOT NULL,
  country VARCHAR NOT NULL,
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

CREATE TABLE meter (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGSERIAL REFERENCES project(id),
  asset_id BIGSERIAL REFERENCES asset(id),
  vendor_id BIGSERIAL REFERENCES vendor(id), -- N:M
  meter_type_id BIGSERIAL REFERENCES meter_type(id),
  model VARCHAR NOT NULL,
  unit VARCHAR NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE meter_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE vendor (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  address VARCHAR NOT NULL,
  country VARCHAR NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TYPE updated_frequency AS ENUM ('daily', 'hourly', '15min', 'min', 'sec', 'millisec');
CREATE TABLE data_source (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  description VARCHAR NOT NULL,
  updated_frequency updated_frequency NOT NULL DEFAULT 'daily',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TYPE status AS ENUM ('open', 'closed');
CREATE TABLE event (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGSERIAL REFERENCES project(id),
  organization_id BIGSERIAL REFERENCES organization(id), -- N:M
  data_source_id BIGSERIAL REFERENCES data_source(id), -- N:M
  event_type_id BIGSERIAL REFERENCES event_type(id),
  description VARCHAR NOT NULL,
  raw_data JSONB,
  metric_outcome JSONB,
  time_start TIMESTAMPTZ NOT NULL DEFAULT,
  time_acknowledged TIMESTAMPTZ NOT NULL DEFAULT,
  time_fixed TIMESTAMPTZ NOT NULL DEFAULT,
  time_end TIMESTAMPTZ NOT NULL DEFAULT,
  status status NOT NULL DEFAULT 'open',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by VARCHAR,
  updated_by VARCHAR, 
);

CREATE TABLE event_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE default_event (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGSERIAL REFERENCES project(id),
  organization_id BIGSERIAL REFERENCES organization(id), -- N:M
  contract_id BIGSERIAL REFERENCES contract(id), -- N:M
  event_id BIGSERIAL REFERENCES event(id), -- N:M
  default_event_type_id BIGSERIAL REFERENCES default_event_type(id),
  description VARCHAR NOT NULL,
  metadata_detail JSONB,
  cure_deadline DATETIME,
  time_start TIMESTAMPTZ NOT NULL DEFAULT,
  time_acknowledged TIMESTAMPTZ NOT NULL DEFAULT,
  time_cured TIMESTAMPTZ NOT NULL DEFAULT,
  status status NOT NULL DEFAULT 'open',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by VARCHAR,
  updated_by VARCHAR, 
);

CREATE TABLE default_event_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE rule_output (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGSERIAL REFERENCES project(id),
  default_event_id BIGSERIAL REFERENCES default_event(id), 
  clause_id BIGSERIAL REFERENCES clause(id), -- N:M
  rule_output_type_id BIGSERIAL REFERENCES rule_output_type(id),
  currency_id BIGSERIAL REFERENCES currency(id),
  description VARCHAR NOT NULL,
  metadata_detail JSONB,
  ld_amount DECIMAL,
  invoice_adjustment DECIMAL,
  breach BOOLEAN NOT NULL DEFAULT true,
  excuse BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by VARCHAR,
  updated_by VARCHAR, 
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

CREATE TABLE notification (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGSERIAL REFERENCES organization(id), -- N:M
  project_id BIGSERIAL REFERENCES project(id),
  default_event_id BIGSERIAL REFERENCES default_event(id), 
  rule_output_id BIGSERIAL REFERENCES rule_output(id), 
  notification_type_id BIGSERIAL REFERENCES notification_type(id),
  description VARCHAR NOT NULL,
  metadata_detail JSONB,
  time_notified DATETIME,
  time_due DATETIME,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE notification_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE asset (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGSERIAL REFERENCES project(id),
  asset_type_id BIGSERIAL REFERENCES asset_type(id),
  vendor_id BIGSERIAL REFERENCES vendor(id), -- N:M
  name VARCHAR NOT NULL,
  description VARCHAR,
  model VARCHAR,
  serial_code VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE asset_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE meter_reading (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGSERIAL REFERENCES project(id),
  meter_id BIGSERIAL REFERENCES meter(id),
  meter_type_id BIGSERIAL REFERENCES meter_type(id),
  value NUMBER NOT NULL,
  reading_timestamp NOT NULL DATETIME,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

  


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
