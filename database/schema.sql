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
  organization_id BIGSERIAL,
  name VARCHAR NOT NULL,
  email VARCHAR NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE contractor (
  id BIGSERIAL PRIMARY KEY,
  project_id BIGSERIAL,
  contractor_type_id BIGSERIAL,
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
  organization_id BIGSERIAL,
  name VARCHAR NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE contract (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGSERIAL,
  project_id BIGSERIAL,
  name VARCHAR NOT NULL,
  description VARCHAR,
  contract_counterparty_id BIGSERIAL,
  contract_type_id BIGSERIAL,
  contract_status_id BIGSERIAL,
  effective_date DATE,
  end_date DATE,
  file_location URL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
  updated_by_id BIGSERIAL, 
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
  contract_id BIGSERIAL,
  project_id BIGSERIAL,
  name VARCHAR NOT NULL,
  clause_type_id BIGSERIAL,
  clause_category_id BIGSERIAL,
  section_ref VARCHAR,
  raw_text VARCHAR,
  clause_responsibleparty_id BIGSERIAL,
  normalized_payload JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
  updated_by_id BIGSERIAL, 
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
  project_id BIGSERIAL,
  meter_type_id BIGSERIAL,
  meter_vendor_id BIGSERIAL,
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

CREATE TABLE meter_vendor (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR NOT NULL,
  address VARCHAR NOT NULL,
  country VARCHAR NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);




-- =========================
-- SECTION 2: RELATIONSHIPS
-- =========================

ALTER TABLE project
ADD CONSTRAINT fk_project_organization
FOREIGN KEY (organization_id)
REFERENCES organization(id);

-- =========================
-- SECTION 3: INDEXES
-- =========================

CREATE INDEX idx_project_organization_id
ON project(organization_id);
