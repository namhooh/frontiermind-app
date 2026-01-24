# Export & Report Generation Implementation Guide

## For Energy Contract Compliance Platform

---

## 1. Overview

**Goal:** Provide a comprehensive export and report generation framework for the contract compliance system, supporting data exports, scheduled reports, and template-based reporting.

**Schema Version:** v5.0
**Migration:** `database/migrations/018_export_and_reports_schema.sql`
**Related:** `SCHEMA_CHANGES.md` v5.0 section

---

## 2. Core Tables

```
┌─────────────────────┐
│   organization      │
└─────────┬───────────┘
          │ 1:N
          ▼
┌─────────────────────┐         ┌─────────────────────┐
│  report_template    │◄────────│  scheduled_report   │
│  (reusable config)  │ 1:N     │  (when to run)      │
└─────────┬───────────┘         └─────────┬───────────┘
          │ 1:N (optional)                │ 1:N
          ▼                               ▼
┌─────────────────────┐         ┌─────────────────────┐
│  generated_report   │◄────────│  generated_report   │
│  (from template)    │         │  (from schedule)    │
└─────────────────────┘         └─────────────────────┘

┌─────────────────────┐
│  export_request     │──────► ┌─────────────────────┐
│  (user-initiated)   │  1:1   │  generated_report   │
└─────────────────────┘        │  (from export)      │
                               └─────────────────────┘
```

### Table Purposes

| Table | Purpose |
|-------|---------|
| `export_request` | Tracks ad-hoc data export requests with approval workflow |
| `report_template` | Reusable report configurations with branding and default filters |
| `scheduled_report` | Automated report scheduling (daily, weekly, monthly, etc.) |
| `generated_report` | Historical archive of all generated reports |

---

## 3. Report Generation Workflows

### Workflow 1: Template-based (On-demand)

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ User selects │────▶│ Template provides │────▶│ Create report    │
│ template     │     │ default config    │     │ (generated_report)│
└──────────────┘     └──────────────────┘     └──────────────────┘
                            │
                            ▼
                     User can override:
                     • Contract filter
                     • Date range
                     • File format
```

**Flow:**
1. User selects a `report_template` (e.g., "Monthly Settlement Report")
2. Template provides default configuration (filters, format, branding)
3. User can override defaults at generation time
4. System creates `generated_report` with `report_template_id` set

**Use Cases:**
- One-time financial summary
- Ad-hoc compliance review
- Custom date range analysis

---

### Workflow 2: Schedule-based (Automated)

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ scheduled_report │────▶│ Background job   │────▶│ generated_report │
│ (config + when)  │     │ runs at time     │     │ + email/S3       │
└──────────────────┘     └──────────────────┘     └──────────────────┘
        │                                                │
        ▼                                                ▼
  References template                            Delivered to:
  for base config                                • Email recipients
                                                 • S3 bucket
```

**Flow:**
1. Admin creates `scheduled_report` linked to a `report_template`
2. Can override template defaults (project_id, contract_id, date_range)
3. Trigger auto-calculates `next_run_at` based on frequency
4. Background job generates report at scheduled time
5. Creates `generated_report` with both `report_template_id` and `scheduled_report_id` set
6. Delivers via email and/or S3

**Use Cases:**
- Monthly settlement reports to stakeholders
- Weekly compliance status to management
- Daily meter data summaries

---

### Workflow 3: Export-based (Ad-hoc Data)

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ User requests    │────▶│ Approval check   │────▶│ Process export   │
│ data export      │     │ (bulk threshold) │     │                  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
                                │                         │
                                ▼                         ▼
                         If >20 records:           generated_report
                         requires admin            with export_request_id
                         approval
```

**Flow:**
1. User creates `export_request` specifying data type, format, and filters
2. System checks if approval required (bulk threshold >20 records)
3. If required, admin approves/rejects
4. Export processed and file generated
5. Creates `generated_report` with `export_request_id` set

**Approval Logic:**
```sql
SELECT check_export_requires_approval('contract'::export_data_type, 25);
-- Returns: true (exceeds bulk threshold of 20)
```

---

## 4. Schema Details

### Enums

| Enum | Values | Purpose |
|------|--------|---------|
| `export_request_status` | pending, approved, processing, completed, failed, expired, cancelled | Export lifecycle |
| `export_data_type` | contract, clause, invoice_generated, invoice_received, expense, meter_data, financial_report, compliance_report, settlement_report, custom | What data to export |
| `export_file_format` | csv, xlsx, json, pdf | Output format |
| `report_frequency` | daily, weekly, monthly, quarterly, annual, on_demand | Schedule frequency |
| `report_type` | settlement, compliance, financial_summary, invoice_aging, expense_by_category, generation_summary, ld_summary, custom | Report category |

### Report Template Scoping

Templates support two visibility levels:

| `project_id` Value | Visibility | Use Case |
|--------------------|------------|----------|
| `NULL` | Org-wide | All organization members can see and use |
| Set to project ID | Project-specific | Only project members can see and use |

**Unique Constraint:**
- `(organization_id, project_id, name)` with `NULLS NOT DISTINCT`
- Allows same template name in different projects
- Prevents duplicate names within same scope

### Default Filters

Templates can define default filters that pre-fill when generating reports:

| Field | Purpose | Default |
|-------|---------|---------|
| `default_contract_id` | Pre-select a specific contract | NULL (user must select) |
| `default_date_range_days` | Pre-select date range in days | 30 |

Users can override these defaults at generation time.

---

## 5. Pre-seeded Templates

The migration automatically creates 6 org-wide templates for each organization:

| Template Name | Type | Format | Config |
|---------------|------|--------|--------|
| Monthly Settlement Report | settlement | PDF | meter_data, pricing, adjustments |
| Compliance Status Report | compliance | PDF | breaches, cured, upcoming |
| Financial Summary | financial_summary | XLSX | revenue, expenses |
| Invoice Aging Report | invoice_aging | PDF | 30/60/90/120 day buckets |
| Expense by Category | expense_by_category | XLSX | trends, variance |
| LD Summary Report | ld_summary | PDF | cured events |

---

## 6. Helper Functions

### `check_export_requires_approval()`

Determines if an export needs dual approval:

```sql
SELECT check_export_requires_approval(
    'contract'::export_data_type,
    25,  -- estimated records
    20   -- bulk threshold (default)
);
-- Returns: true
```

Rules:
- Bulk exports (>20 records) require approval
- PII-containing types (contract, invoice) require approval if >10 records

### `calculate_next_run_time()`

Computes next scheduled run based on frequency:

```sql
SELECT calculate_next_run_time(
    'weekly'::report_frequency,
    1,           -- day_of_week (Monday)
    NULL,        -- day_of_month (not used for weekly)
    '06:00:00',  -- time_of_day
    'America/New_York',
    now()
);
```

### `get_export_statistics()`

Returns export metrics for an organization:

```sql
SELECT * FROM get_export_statistics(1, 30);
-- Returns: total_exports, completed_exports, failed_exports,
--          pending_approval, total_records_exported, avg_processing_time_ms
```

---

## 7. Security & RLS

All tables have Row Level Security enabled:

| Table | SELECT | INSERT | UPDATE | Service Role |
|-------|--------|--------|--------|--------------|
| export_request | org member | org member + own request | org admin | full access |
| report_template | org member | org admin | org admin | full access |
| scheduled_report | org member | org admin | org admin | full access |
| generated_report | org member | org member | - | full access |

### Export Request Lifecycle

```
pending ──┬──▶ approved ──▶ processing ──┬──▶ completed ──▶ expired
          │                              │
          └──▶ cancelled                 └──▶ failed
```

---

## 8. API Endpoints (Planned)

The following API endpoints will be implemented in `python-backend/api/exports.py`:

### Export Requests

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/exports/request` | Create new export request |
| GET | `/api/exports/request/{id}` | Get export request status |
| GET | `/api/exports/request` | List user's export requests |
| POST | `/api/exports/request/{id}/approve` | Approve export (admin) |
| POST | `/api/exports/request/{id}/reject` | Reject export (admin) |
| GET | `/api/exports/request/{id}/download` | Download completed export |

### Report Templates

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/reports/templates` | List available templates |
| POST | `/api/reports/templates` | Create custom template (admin) |
| GET | `/api/reports/templates/{id}` | Get template details |
| PUT | `/api/reports/templates/{id}` | Update template (admin) |
| DELETE | `/api/reports/templates/{id}` | Deactivate template (admin) |

### Report Generation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/reports/generate` | Generate report from template |
| GET | `/api/reports/generated` | List generated reports |
| GET | `/api/reports/generated/{id}` | Get report details |
| GET | `/api/reports/generated/{id}/download` | Download report |

### Scheduled Reports

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/reports/scheduled` | List scheduled reports |
| POST | `/api/reports/scheduled` | Create schedule (admin) |
| PUT | `/api/reports/scheduled/{id}` | Update schedule (admin) |
| DELETE | `/api/reports/scheduled/{id}` | Disable schedule (admin) |

---

## 9. File Storage

### S3 Structure

```
frontiermind-reports/
├── exports/
│   └── {org_id}/
│       └── {export_request_id}/
│           └── export_{timestamp}.{format}
├── reports/
│   └── {org_id}/
│       └── {year}/
│           └── {month}/
│               └── {report_name}_{timestamp}.{format}
└── archive/
    └── {org_id}/
        └── {year}/
            └── *.glacier
```

### Retention Policy

| Category | Retention | Storage Class |
|----------|-----------|---------------|
| Export files | 7 days | S3 Standard |
| Generated reports | 90 days | S3 Standard |
| Archived reports | 7 years | S3 Glacier |

---

## 10. Verification

After applying the migration, verify the schema:

```sql
-- Check tables exist
SELECT table_name FROM information_schema.tables
WHERE table_name IN ('export_request', 'report_template', 'scheduled_report', 'generated_report');

-- Check enums
SELECT enum_range(NULL::export_request_status);
SELECT enum_range(NULL::report_type);

-- Check pre-seeded templates
SELECT organization_id, name, report_type FROM report_template;

-- Test helper functions
SELECT check_export_requires_approval('contract', 25);
SELECT calculate_next_run_time('weekly', 1, NULL, '06:00', 'UTC', now());
```

---

## 11. Future Enhancements

- [ ] Dashboard widget for report generation status
- [ ] Email notifications for scheduled report delivery
- [ ] Bulk report generation for multiple projects
- [ ] Report comparison (period-over-period)
- [ ] Custom report builder UI
- [ ] Report sharing with external stakeholders
- [ ] Webhook notifications for export completion

---

## Related Documentation

- **Schema Changes:** `database/SCHEMA_CHANGES.md` (v5.0 section)
- **Migration:** `database/migrations/018_export_and_reports_schema.sql`
- **Security Assessment:** `SECURITY_PRIVACY_ASSESSMENT.md` (export controls)
- **Database Guide:** `database/DATABASE_GUIDE.md`
