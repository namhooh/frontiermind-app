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

CREATE TABLE counterparty_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  code VARCHAR NOT NULL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE counterparty (
  id BIGSERIAL PRIMARY KEY,
  counterparty_type_id BIGINT REFERENCES counterparty_type(id), 
  name VARCHAR NOT NULL,
  email VARCHAR,
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
  counterparty_id BIGINT REFERENCES counterparty(id), -- N:M
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

-- V1.1

CREATE TABLE tariff_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,  -- Flat, Time of Use, Tiered, Indexed
  code VARCHAR NOT NULL,
  description VARCHAR, 
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE clause_tariff (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT REFERENCES project(id),
  contract_id BIGINT REFERENCES contract(id),
  tariff_type_id BIGINT REFERENCES tariff_type(id),
  currency_id BIGINT REFERENCES currency(id),
  name VARCHAR NOT NULL,
  valid_from DATE,
  valid_to DATE,
  base_rate DECIMAL,
  unit VARCHAR,
  logic_parameters JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE billing_period (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,  
  start_date DATE,
  end_date DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE meter_aggregate (
  id BIGSERIAL PRIMARY KEY,
  billing_period_id BIGINT REFERENCES billing_period(id), -- 1:1
  meter_id BIGINT REFERENCES meter(id),
  data_source_id BIGINT REFERENCES data_source(id),
  total_production DECIMAL,
  total_consumption DECIMAL,
  peak DECIMAL,
  off_peak DECIMAL,
  unit VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TYPE invoice_status AS ENUM ('draft', 'verified', 'sent', 'disputed', 'paid');
CREATE TABLE invoice_header (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT REFERENCES project(id),
  contract_id BIGINT REFERENCES contract(id),
  billing_period_id BIGINT REFERENCES billing_period(id), -- 1:1
  counterparty_id BIGINT REFERENCES counterparty(id),
  currency_id BIGINT REFERENCES currency(id),
  invoice_number VARCHAR,
  invoice_date DATE,
  due_date DATE,
  total_amount DECIMAL,
  status invoice_status NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE invoice_line_item_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL, 
  code VARCHAR NOT NULL,
  description VARCHAR, 
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE invoice_line_item (
  id BIGSERIAL PRIMARY KEY,
  invoice_header_id BIGINT REFERENCES invoice_header(id),
  rule_output_id BIGINT REFERENCES rule_output(id), -- 1:1
  clause_tariff_id BIGINT REFERENCES clause_tariff(id),
  meter_aggregate_id BIGINT REFERENCES meter_aggregate(id),
  invoice_line_item_type_id BIGINT REFERENCES invoice_line_item_type(id),
  description VARCHAR,
  quantity DECIMAL,
  line_unit_price DECIMAL,
  line_total_amount DECIMAL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE expected_invoice_header (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT REFERENCES project(id),
  contract_id BIGINT REFERENCES contract(id),
  billing_period_id BIGINT REFERENCES billing_period(id), -- 1:1
  counterparty_id BIGINT REFERENCES counterparty(id),
  currency_id BIGINT REFERENCES currency(id),
  total_amount DECIMAL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE expected_invoice_line_item (
  id BIGSERIAL PRIMARY KEY,
  expected_invoice_header_id BIGINT REFERENCES expected_invoice_header(id),
  invoice_line_item_type_id BIGINT REFERENCES invoice_line_item_type(id),
  description VARCHAR,
  line_total_amount DECIMAL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE received_invoice_header (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT REFERENCES project(id),
  contract_id BIGINT REFERENCES contract(id),
  billing_period_id BIGINT REFERENCES billing_period(id), -- 1:1
  counterparty_id BIGINT REFERENCES counterparty(id),
  currency_id BIGINT REFERENCES currency(id),
  invoice_number VARCHAR,
  invoice_date DATE,
  due_date DATE,
  total_amount DECIMAL,
  status invoice_status NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE received_invoice_line_item (
  id BIGSERIAL PRIMARY KEY,
  received_invoice_header_id BIGINT REFERENCES received_invoice_header(id),
  invoice_line_item_type_id BIGINT REFERENCES invoice_line_item_type(id),
  description VARCHAR,
  line_total_amount DECIMAL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TYPE invoice_comparison_status AS ENUM ('unchecked', 'matched', 'underbilled', 'overbilled');
CREATE TABLE invoice_comparison (
  id BIGSERIAL PRIMARY KEY,
  expected_invoice_header_id BIGINT REFERENCES expected_invoice_header(id),
  received_invoice_header_id BIGINT REFERENCES received_invoice_header(id),
  variance_amount DECIMAL,
  status invoice_comparison_status NOT NULL DEFAULT 'unchecked',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE invoice_comparison_line_item (
  id BIGSERIAL PRIMARY KEY,
  invoice_comparison_id BIGINT REFERENCES invoice_comparison(id), -- 1:1
  expected_invoice_line_item_id BIGINT REFERENCES expected_invoice_line_item(id), -- 1:1
  received_invoice_line_item_id BIGINT REFERENCES received_invoice_line_item(id), -- 1:1
  variance_amount DECIMAL,
  description VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
); 

CREATE TABLE grid_event_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,  
  code VARCHAR NOT NULL,
  description VARCHAR, 
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE grid_operator (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  address VARCHAR,
  country VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE grid_event (
  id BIGSERIAL PRIMARY KEY,
  grid_event_type_id BIGINT REFERENCES grid_event_type(id),
  grid_operator_id BIGINT REFERENCES grid_operator(id),
  country VARCHAR,
  region VARCHAR,
  source VARCHAR,
  metadata_detail JSONB,
  time_start TIMESTAMPTZ,
  time_end TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE weather_data_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,  
  code VARCHAR NOT NULL,
  description VARCHAR, 
  updated_frequency updated_frequency NOT NULL DEFAULT 'daily',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE weather_data (
  id BIGSERIAL PRIMARY KEY,
  weather_data_type_id BIGINT REFERENCES weather_data_type(id),
  country VARCHAR,
  region VARCHAR,
  source VARCHAR,
  unit VARCHAR,
  unit_value DECIMAL,
  reading_timestamp TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE regulatory_fee_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,  
  code VARCHAR NOT NULL,
  description VARCHAR, 
  updated_frequency updated_frequency NOT NULL DEFAULT 'daily',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE regulatory_fee (
  id BIGSERIAL PRIMARY KEY,
  regulatory_fee_type_id BIGINT REFERENCES regulatory_fee_type(id),
  country VARCHAR,
  region VARCHAR,
  source VARCHAR,
  unit VARCHAR,
  unit_value DECIMAL,
  reading_timestamp TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

CREATE TABLE market_price_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,  
  code VARCHAR NOT NULL,
  description VARCHAR, 
  updated_frequency updated_frequency NOT NULL DEFAULT 'daily',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE market_price (
  id BIGSERIAL PRIMARY KEY,
  market_price_type_id BIGINT REFERENCES market_price_type(id),
  country VARCHAR,
  region VARCHAR,
  source VARCHAR,
  unit VARCHAR,
  unit_value DECIMAL,
  reading_timestamp TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

CREATE TABLE contractor_report (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT REFERENCES project(id),
  counterparty_id BIGINT REFERENCES counterparty(id),
  raw_text VARCHAR,
  metadata_detail JSONB,
  file_location VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE fault_type (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,  
  code VARCHAR NOT NULL,
  description VARCHAR, 
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TYPE severity AS ENUM ('high', 'medium', 'low');
CREATE TABLE fault (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGINT REFERENCES project(id),
  asset_id BIGINT REFERENCES asset(id),
  data_source_id BIGINT REFERENCES data_source(id),
  fault_type_id BIGINT REFERENCES fault_type(id),
  description VARCHAR,
  severity severity NOT NULL DEFAULT 'high',
  time_start TIMESTAMPTZ,
  time_end TIMESTAMPTZ,
  metadata_detail JSONB,
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
