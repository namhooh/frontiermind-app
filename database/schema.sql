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
