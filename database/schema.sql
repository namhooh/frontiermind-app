-- =========================
-- SECTION 1: TABLES
-- =========================

CREATE TABLE organization (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE project (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT,
  name TEXT NOT NULL,
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
