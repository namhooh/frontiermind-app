# Email & Notification Engine - Implementation Guide

**Version:** 1.0
**Date:** 2026-02-15
**Migration:** `database/migrations/032_email_notification_engine.sql`

---

## Overview

Automated email notification system for sending invoice reminders, compliance alerts, and other notifications to external counterparties. Includes a secure token-based submission system for collecting responses (PO numbers, payment confirmations) without requiring counterparties to have FrontierMind accounts.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Supabase PostgreSQL                                            │
│  ┌──────────────┐ ┌──────────────────┐ ┌──────────────────────┐ │
│  │email_template│ │email_notification │ │email_log             │ │
│  │              │ │_schedule          │ │                      │ │
│  └──────────────┘ └──────────────────┘ └──────────────────────┘ │
│  ┌──────────────┐ ┌──────────────────┐ ┌──────────────────────┐ │
│  │submission    │ │submission        │ │customer_contact      │ │
│  │_token        │ │_response         │ │(migration 028)       │ │
│  └──────────────┘ └──────────────────┘ └──────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
          │                │                       │
          ▼                ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│  ECS Python Backend (FastAPI)                                   │
│                                                                 │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────┐ │
│  │APScheduler     │  │NotificationService│  │TokenService     │ │
│  │(in-process)    │──│(orchestrator)     │──│(SHA-256 tokens) │ │
│  │• 5-min poll    │  │• Immediate send   │  │• Generate       │ │
│  │• Token expiry  │  │• Scheduled send   │  │• Validate       │ │
│  └────────────────┘  └──────────────────┘  │• Use + record   │ │
│                             │               └─────────────────┘ │
│                    ┌────────┴────────┐                          │
│                    │                 │                           │
│            ┌───────▼──────┐  ┌──────▼──────┐                   │
│            │SESClient     │  │Template     │                    │
│            │(boto3)       │  │Renderer     │                    │
│            │              │  │(Jinja2)     │                    │
│            └──────────────┘  └─────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
          │                                        │
          ▼                                        ▼
┌──────────────────┐              ┌────────────────────────────┐
│  AWS SES         │              │  Next.js Frontend          │
│  • Email delivery│              │  /notifications  (admin)   │
│  • Bounce/bounce │              │  /submit/[token] (public)  │
│    tracking      │              └────────────────────────────┘
└──────────────────┘
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Scheduler | APScheduler in-process | Schedule state in PostgreSQL; APScheduler only runs the poll loop. Emails only send when ECS desired-count >= 1 |
| Email delivery | AWS SES | Already in AWS ecosystem, boto3 already a dependency |
| Templates | Jinja2 | Same engine as existing PDF report templates |
| Token storage | SHA-256 hash | Raw token never persisted; hash lookup on validation |
| Recipient resolution | `customer_contact` table | Reuses migration 028 with `include_in_invoice_email` / `escalation_only` flags |
| Schedule timing | `calculate_next_run_time()` | Reuses function from migration 018 (report scheduling) |
| Shared scheduler | Report schedule job also hosted here | The `services/email/scheduler.py` APScheduler instance hosts a third job (`process_due_report_schedules`) that processes `scheduled_report` rows — see `services/reports/scheduler.py` |

---

## Database Schema

### New Tables

#### `email_template`
Jinja2 email templates stored per organization. System templates are seeded automatically and cannot be deleted.

| Column | Type | Description |
|--------|------|-------------|
| `email_schedule_type` | `email_schedule_type` | Template category |
| `subject_template` | VARCHAR(500) | Jinja2 subject line |
| `body_html` | TEXT | Jinja2 HTML body |
| `body_text` | TEXT | Plain text fallback |
| `available_variables` | JSONB | List of template variables |
| `is_system` | BOOLEAN | Protected system templates |

#### `email_notification_schedule`
Defines when, what, and who to email. Conditions filter which invoices trigger notifications.

| Column | Type | Description |
|--------|------|-------------|
| `report_frequency` | `report_frequency` | Reuses enum from migration 018 |
| `conditions` | JSONB | Runtime filter criteria (see below) |
| `max_reminders` | INTEGER | Cap per invoice |
| `escalation_after` | INTEGER | Include escalation contacts after N reminders |
| `include_submission_link` | BOOLEAN | Attach token-based form link |
| `submission_fields` | JSONB | Fields to collect |
| `next_run_at` | TIMESTAMPTZ | Calculated by trigger |

**Conditions JSONB format:**
```json
{
  "invoice_status": ["sent", "verified"],
  "days_overdue_min": 7,
  "days_overdue_max": 60,
  "min_amount": 1000,
  "max_amount": 500000
}
```

#### `email_log`
Every email sent, with SES tracking.

| Column | Type | Description |
|--------|------|-------------|
| `email_status` | `email_status` | Lifecycle: pending → sending → delivered/bounced/failed |
| `ses_message_id` | VARCHAR | SES tracking ID |
| `reminder_count` | INTEGER | Which reminder number this was |
| `invoice_header_id` | BIGINT | Linked invoice |
| `submission_token_id` | BIGINT | Linked submission token |

#### `submission_token`
Secure tokens for external data collection. Raw token never stored — only the SHA-256 hash.

| Column | Type | Description |
|--------|------|-------------|
| `token_hash` | VARCHAR(64) | SHA-256 of URL-safe token (unique indexed) |
| `submission_fields` | JSONB | What data to collect |
| `max_uses` | INTEGER | Usage limit (default 1) |
| `expires_at` | TIMESTAMPTZ | Token expiry (default 7 days) |

#### `submission_response`
Data submitted by counterparties via token links.

| Column | Type | Description |
|--------|------|-------------|
| `response_data` | JSONB | Submitted form data |
| `submitted_by_email` | VARCHAR | Optional email of submitter |
| `ip_address` | INET | Client IP for audit |

### New Enums

| Enum | Values |
|------|--------|
| `email_schedule_type` | `invoice_reminder`, `invoice_initial`, `invoice_escalation`, `compliance_alert`, `meter_data_missing`, `report_ready`, `custom` |
| `email_status` | `pending`, `sending`, `delivered`, `bounced`, `failed`, `suppressed` |
| `submission_token_status` | `active`, `used`, `expired`, `revoked` |

### Seed Data

4 system templates seeded per organization:
1. **Invoice Delivery** (`invoice_initial`) — Initial invoice notification
2. **Payment Reminder** (`invoice_reminder`) — Overdue payment reminder
3. **Invoice Escalation** (`invoice_escalation`) — Escalation to senior contacts
4. **Compliance Alert** (`compliance_alert`) — Contract compliance breach

---

## Backend Components

### File Map

```
python-backend/
├── api/
│   ├── notifications.py          # /api/notifications/* (authenticated)
│   └── submissions.py            # /api/submit/*        (public, no auth)
├── db/
│   └── notification_repository.py # All DB operations
├── models/
│   └── notifications.py          # Pydantic models
├── services/
│   ├── email/
│   │   ├── __init__.py
│   │   ├── ses_client.py          # AWS SES wrapper
│   │   ├── template_renderer.py   # Jinja2 rendering
│   │   ├── notification_service.py# Core orchestrator
│   │   ├── condition_evaluator.py # Schedule condition matching
│   │   ├── scheduler.py          # APScheduler integration (also hosts report schedule job)
│   │   ├── token_service.py      # Submission token management
│   │   └── templates/            # HTML email templates
│   │       ├── base_email.html
│   │       ├── invoice_initial.html
│   │       ├── invoice_reminder.html
│   │       ├── invoice_escalation.html
│   │       ├── compliance_alert.html
│   │       └── report_ready.html  # Scheduled report delivery notification
```

### API Endpoints

#### Authenticated Endpoints (`/api/notifications`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/notifications/send` | Send email immediately |
| `GET` | `/api/notifications/templates` | List email templates |
| `GET` | `/api/notifications/templates/{id}` | Get template |
| `POST` | `/api/notifications/templates` | Create template |
| `PUT` | `/api/notifications/templates/{id}` | Update template |
| `DELETE` | `/api/notifications/templates/{id}` | Deactivate template |
| `GET` | `/api/notifications/schedules` | List schedules |
| `GET` | `/api/notifications/schedules/{id}` | Get schedule |
| `POST` | `/api/notifications/schedules` | Create schedule |
| `PUT` | `/api/notifications/schedules/{id}` | Update schedule |
| `DELETE` | `/api/notifications/schedules/{id}` | Deactivate schedule |
| `POST` | `/api/notifications/schedules/{id}/trigger` | Manual trigger |
| `GET` | `/api/notifications/email-log` | Paginated email history |
| `GET` | `/api/notifications/submissions` | List submission responses |

#### Public Endpoints (`/api/submit`) — No Authentication, Rate Limited (10/min per IP)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/submit/{token}` | Validate token, return form config |
| `POST` | `/api/submit/{token}` | Submit data against token (409 on concurrent duplicate) |

### Notification Service Pipeline

#### Immediate Send (`POST /api/notifications/send`)

```
1. Load email_template by ID
2. Query invoice_header for template context (amounts, dates, counterparty)
3. If include_submission_link:
   a. Generate 64-byte URL-safe token (secrets.token_urlsafe)
   b. Store SHA-256 hash in submission_token table
   c. Add submission_url to template context
4. Render Jinja2 template (subject + HTML + text)
5. For each recipient:
   a. Create email_log record (status=sending)
   b. Call SES send_email()
   c. Update email_log with SES message ID + status
6. Return email_log_ids + submission_token_id
```

#### Scheduled Processing (APScheduler, every 5 minutes)

```
1. Query email_notification_schedule WHERE is_active AND next_run_at <= NOW()
2. For each due schedule:
   a. Query invoice_header matching schedule conditions
   b. For each matching invoice:
      i.  Count existing reminders (email_log) — skip if >= max_reminders
      ii. Resolve recipients from customer_contact WHERE include_in_invoice_email=true
      iii.If reminder_count >= escalation_after: include escalation_only contacts
      iv. Build template context from invoice data
      v.  Generate submission token if schedule.include_submission_link=true
      vi. Render template, send to each contact, log
   c. Update schedule last_run_at (trigger recalculates next_run_at)
```

### Submission Token Flow

```
Generate:
  raw_token = secrets.token_urlsafe(64)   →  86-char URL-safe string
  token_hash = SHA-256(raw_token)          →  64-char hex stored in DB
  Expiry: 7 days default

Validate (GET /api/submit/{token}):
  hash = SHA-256(token_from_url)
  Lookup by hash → check status=active, expires_at > now(), use_count < max_uses

Use (POST /api/submit/{token}):
  Atomic UPDATE ... WHERE status='active' RETURNING id  →  only one concurrent request wins
  If UPDATE returns no rows → 409 Conflict (token already used)
  Store submission_response (response_data JSONB, email, IP)
  Increment use_count → set status=used if max_uses reached
```

### Scheduler Lifecycle

```python
# main.py lifespan handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    email_scheduler.start()    # Start APScheduler
    yield
    email_scheduler.shutdown()  # Clean shutdown

# Three recurring jobs registered:
# 1. process_due_schedules          — every 5 minutes (email notifications)
# 2. expire_stale_tokens            — every hour
# 3. process_due_report_schedules   — every 5 minutes (scheduled report generation)
```

**Important constraint:** Emails only send when ECS `desired-count >= 1`. When scaled to zero, the scheduler is not running. This is a documented operational constraint, not a bug.

---

## Frontend Components

### File Map

```
app/
├── notifications/
│   └── page.tsx              # Admin dashboard (4 tabs)
└── submit/
    └── [token]/
        └── page.tsx          # Public submission form (no auth)

lib/api/
└── notificationsClient.ts    # API client (follows reportsClient.ts pattern)
```

### Notifications Page (`/notifications`)

Four-tab dashboard:

| Tab | Content |
|-----|---------|
| **Schedules** | List active/inactive schedules with pause/resume/trigger controls |
| **Email History** | Paginated table of sent emails with status badges (delivered/bounced/failed) |
| **Templates** | View system and custom email templates |
| **Submissions** | View data submitted by counterparties via token links |

### Public Submission Page (`/submit/[token]`)

- No authentication required
- SSR token validation via `GET /api/submit/{token}`
- Dynamic form rendered from `submission_fields` config
- Invoice summary display (number, amount, due date)
- Success/error states with clear messaging
- Minimal UI — no dashboard navigation

---

## Environment Variables

### Backend (ECS / .env)

| Variable | Required | Description |
|----------|----------|-------------|
| `SES_SENDER_EMAIL` | Yes | Verified SES sender email |
| `SES_SENDER_NAME` | No | Display name (default: "FrontierMind") |
| `SES_CONFIGURATION_SET` | No | SES configuration set for tracking |
| `APP_BASE_URL` | Yes | Base URL for submission links (set in ECS `task-definition.json`; default: `http://localhost:3000`) |

### AWS Secrets Manager

| Secret | Path |
|--------|------|
| SES sender email | `frontiermind/backend/ses-sender-email` |

### AWS IAM (ECS Task Role)

Required SES permissions:
```json
{
  "Effect": "Allow",
  "Action": ["ses:SendEmail", "ses:SendRawEmail", "ses:GetSendQuota"],
  "Resource": "*"
}
```

### SES Domain Verification

Before sending emails, the sender domain must be verified in SES:
1. Add and verify domain in AWS SES console
2. Add DKIM DNS records
3. If in SES sandbox: also verify recipient emails (or request production access)

---

## Operational Guide

### Manual Email Send

```bash
curl -X POST http://localhost:8000/api/notifications/send \
  -H "Content-Type: application/json" \
  -H "X-Organization-ID: 1" \
  -d '{
    "template_id": 1,
    "invoice_header_id": 42,
    "recipient_emails": ["finance@counterparty.com"],
    "include_submission_link": true,
    "submission_fields": ["po_number", "payment_date"]
  }'
```

### Create a Schedule

```bash
curl -X POST http://localhost:8000/api/notifications/schedules \
  -H "Content-Type: application/json" \
  -H "X-Organization-ID: 1" \
  -d '{
    "name": "Monthly Overdue Reminders",
    "email_template_id": 2,
    "email_schedule_type": "invoice_reminder",
    "report_frequency": "monthly",
    "day_of_month": 15,
    "time_of_day": "09:00:00",
    "timezone": "Africa/Johannesburg",
    "conditions": {
      "invoice_status": ["sent", "verified"],
      "days_overdue_min": 7
    },
    "max_reminders": 3,
    "escalation_after": 2,
    "include_submission_link": true,
    "submission_fields": ["po_number", "expected_payment_date", "notes"]
  }'
```

### Manually Trigger a Schedule

```bash
curl -X POST http://localhost:8000/api/notifications/schedules/1/trigger \
  -H "X-Organization-ID: 1"
```

### View Email History

```bash
curl "http://localhost:8000/api/notifications/email-log?limit=20" \
  -H "X-Organization-ID: 1"
```

### Check SES Sending Quota

Via SESClient directly (useful for monitoring):
```python
from services.email.ses_client import SESClient
client = SESClient()
quota = client.check_sending_quota()
# {'max_24h_send': 50000, 'sent_last_24h': 127, 'max_send_rate': 14.0}
```

---

## Verification Checklist

1. **Schema:** Run migration 032 → verify 5 tables, 3 enums, indexes, RLS policies
2. **Seed data:** Verify 4 system templates created per organization
3. **Immediate send:** `POST /api/notifications/send` → email arrives, `email_log` record created
4. **Scheduling:** Create schedule with `frequency=monthly` → verify `next_run_at` set by trigger → manual trigger sends emails
5. **Conditions:** Create schedule with `conditions: {"days_overdue_min": 7}` → only overdue invoices get emails
6. **Submission tokens:** Send with `include_submission_link=true` → visit URL → submit PO number → verify `submission_response` record
7. **Escalation:** Set `max_reminders=2, escalation_after=1` → verify escalation contacts included after first reminder
8. **Token expiry:** Verify hourly job sets expired tokens to `status=expired`
9. **Frontend:** Navigate to `/notifications` → view all 4 tabs
10. **Public form:** Navigate to `/submit/{token}` → submit form → see success confirmation

---

## Dependencies

### Existing (already in requirements.txt)
- `boto3` — AWS SES client
- `jinja2` — Template rendering
- `apscheduler` — In-process scheduling
- `psycopg2` — PostgreSQL driver

### Existing Database Dependencies
- `calculate_next_run_time()` — Function from migration 018
- `report_frequency` enum — From migration 018
- `customer_contact` table — From migration 028
- `invoice_header` table — Core schema
- `counterparty` table — Core schema
- `audit_action_type` enum — From migration 016

---

## Known Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| **Auth model: header-only `X-Organization-ID`** | All notification endpoints rely on a client-supplied header with no server-side ownership check. A user with a valid JWT could pass any org ID. | Systemic issue shared with all routers (reports, contracts, etc.). Fix globally when RLS-backed org scoping is added to the API layer. |
| **Non-invoice schedule types not implemented** | `compliance_alert`, `meter_data_missing`, `report_ready`, and `custom` schedule types are defined in the enum but `_process_single_schedule()` only handles invoice types (`invoice_reminder`, `invoice_initial`, `invoice_escalation`). Unsupported types are silently skipped with a debug log. | Extend `_process_single_schedule()` with type-specific handlers when these features are needed. |
| **No test coverage** | No unit or integration tests for the notification system. | Add tests as a separate PR. |
| **`invoice_direction` now in report GET responses** | Fixed — `invoice_direction` is now returned in `GET /api/reports/generated` and `GET /api/reports/generated/{id}` responses. | Fixed (Round 2 remediation) |
| **Report-ready emails logged to `email_log`** | Report delivery emails sent via `ReportDeliveryService` are now recorded in `email_log` for audit trail, providing visibility in the notification email history tab. | Fixed (Round 2 remediation) |
| **Event loop blocking resolved** | All three scheduler jobs (`_process_due_schedules`, `_expire_stale_tokens`, `_process_due_report_schedules`) now offload sync calls via `asyncio.to_thread()`, preventing event loop blocking during DB queries, PDF rendering, S3 uploads, and SES sends. | Fixed (Round 2 remediation) |
| **Single-instance deployment assumption** | The scheduler uses `FOR UPDATE SKIP LOCKED` to guard against double-processing, but the overall design assumes `desired-count=0` or `1`. Multi-instance deployments may produce unexpected behavior in edge cases (e.g., token expiry job running on multiple instances simultaneously). | Keep `desired-count <= 1` or add distributed locking (Redis/DynamoDB) for multi-instance. |

---

## Future Enhancements (Phase 6)

- **SES bounce/complaint handling:** SNS webhook → update `email_log.email_status` on bounces
- **Organization-level daily email quota:** Prevent runaway sends
- **Email attachment support:** Attach invoice PDFs via SES raw email
- **Template preview endpoint:** Render template with sample data without sending
- **Comprehensive test suite:** Unit tests for notification_service, condition_evaluator, token_service
