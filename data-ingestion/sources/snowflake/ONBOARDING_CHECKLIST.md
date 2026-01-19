# Snowflake Integration Onboarding Checklist

This checklist outlines the steps required to onboard a new client for Snowflake data warehouse integration.

---

## How It Works (Conceptual Overview)

Before diving into the steps, here's how the trust relationship between FrontierMind, Snowflake, and the client works:

### What Each Party Has

| Party | What They Have |
|-------|----------------|
| **FrontierMind** | AWS account with S3 bucket (`frontiermind-meter-data`) and IAM roles |
| **Client** | Snowflake account with data to export |
| **Snowflake** | Managed AWS infrastructure that executes COPY INTO commands |

### Trust Relationship Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           TRUST CHAIN                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────────┐         ┌──────────────┐         ┌──────────────┐       │
│   │   Client's   │         │  Snowflake   │         │ FrontierMind │       │
│   │   Snowflake  │────────▶│  Managed AWS │────────▶│   S3 Bucket  │       │
│   │   Account    │         │  IAM User    │         │              │       │
│   └──────────────┘         └──────────────┘         └──────────────┘       │
│         │                        │                         ▲               │
│         │                        │                         │               │
│         │   Storage Integration  │   AssumeRole with       │               │
│         │   (authorizes          │   External ID           │               │
│         │    Snowflake to        │   validation            │               │
│         │    use its IAM user)   │                         │               │
│         │                        └─────────────────────────┘               │
│         │                                                                   │
│         └── Client runs COPY INTO ──▶ Data flows to S3                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Step-by-Step Explanation

1. **FrontierMind creates an IAM role** in our AWS account specifically for this client
2. **Client creates a Storage Integration** in Snowflake, which tells Snowflake "use your managed IAM user to access FrontierMind's S3"
3. **Snowflake generates IAM credentials** (an IAM user ARN and External ID) that it will use when connecting
4. **Client sends these credentials to FrontierMind**, who updates the IAM role's trust policy to allow Snowflake's IAM user to assume it
5. **When the client runs COPY INTO**, Snowflake's managed IAM user assumes FrontierMind's IAM role and writes to S3

### Why Two External IDs?

There are **two different External IDs** involved for security:

| External ID | Created By | Purpose |
|-------------|------------|---------|
| **FrontierMind External ID** | FrontierMind | Included in the Storage Integration config. Prevents unauthorized integrations from connecting to our S3. |
| **Snowflake External ID** | Snowflake | Auto-generated when client creates Storage Integration. Sent back to FrontierMind to add to trust policy. Prevents confused deputy attacks. |

Both External IDs must match for the connection to work. This dual-verification ensures:
- Only authorized Storage Integrations can access FrontierMind's bucket
- Snowflake's IAM user can only assume the role when properly configured
- No other AWS account can impersonate the connection

### Summary

The client's Snowflake account → delegates to Snowflake's managed AWS → which assumes FrontierMind's IAM role → to write to FrontierMind's S3 bucket. Each hop requires explicit authorization with External ID verification.

---

## Phase 1: FrontierMind Setup

### 1.1 Create Organization (FrontierMind Team)

- [ ] Create organization record in database
- [ ] Note the assigned `organization_id`
- [ ] Create admin user account for client
- [ ] Generate API key for status endpoint access

### 1.2 Create IAM Role (FrontierMind Team)

- [ ] Apply Terraform to create IAM role for this client
  ```bash
  cd infrastructure/terraform
  terraform apply -target=aws_iam_role.snowflake_access_org_${ORG_ID}
  ```
- [ ] Note the IAM Role ARN
- [ ] Generate unique External ID: `fm_org_${ORG_ID}_snowflake`
- [ ] Verify S3 bucket policy allows the new role

### 1.3 Provide Credentials to Client

Send the following to the client:

| Item | Value |
|------|-------|
| Organization ID | `___` |
| IAM Role ARN | `arn:aws:iam::___:role/frontiermind-snowflake-org-___` |
| External ID | `fm_org_____snowflake` |
| S3 Bucket | `frontiermind-meter-data` |
| S3 Path Prefix | `raw/snowflake/___/` |
| API Endpoint | `https://api.frontiermind.com` |
| API Key | `___` |

---

## Phase 2: Client Setup

### 2.1 Create Storage Integration (Client Team)

- [ ] Run `CREATE STORAGE INTEGRATION` in Snowflake (as ACCOUNTADMIN)
- [ ] Replace placeholders with provided values
- [ ] Note the `STORAGE_AWS_IAM_USER_ARN` from DESC output
- [ ] Note the `STORAGE_AWS_EXTERNAL_ID` from DESC output

**Send back to FrontierMind:**
- Snowflake IAM User ARN: `arn:aws:iam::___:user/___`
- Snowflake External ID: `___`

### 2.2 Update IAM Trust Policy (FrontierMind Team)

After receiving Snowflake IAM details:

- [ ] Update IAM role trust policy with Snowflake principal
- [ ] Add Snowflake External ID to condition
- [ ] Apply changes:
  ```bash
  terraform apply -target=aws_iam_role.snowflake_access_org_${ORG_ID}
  ```

### 2.3 Create Stage and File Format (Client Team)

- [ ] Create external stage pointing to S3 path
- [ ] Create Parquet file format
- [ ] Test stage access: `LIST @frontiermind_stage;`

---

## Phase 3: Test Integration

### 3.1 Upload Test File (Client Team)

- [ ] Prepare test data (10-100 records recommended)
- [ ] Execute COPY INTO command
- [ ] Note the file path and size

### 3.2 Verify Processing (Both Teams)

- [ ] Check S3 for file arrival (FrontierMind)
  ```bash
  aws s3 ls s3://frontiermind-meter-data/raw/snowflake/${ORG_ID}/ --recursive
  ```

- [ ] Check Lambda CloudWatch logs (FrontierMind)
  ```bash
  aws logs tail /aws/lambda/frontiermind-validator --follow
  ```

- [ ] Query status API (Client)
  ```bash
  curl "https://api.frontiermind.com/api/ingest/status/by-hash/{hash}?organization_id=${ORG_ID}"
  ```

- [ ] Verify data in `meter_reading` table (FrontierMind)
  ```sql
  SELECT COUNT(*), MIN(reading_timestamp), MAX(reading_timestamp)
  FROM meter_reading
  WHERE organization_id = ${ORG_ID}
    AND source_system = 'snowflake';
  ```

### 3.3 Verify Full Round Trip

- [ ] Confirm status API returns `success`
- [ ] Confirm `rows_loaded` matches source count
- [ ] Confirm no validation errors
- [ ] Confirm processing time is acceptable

---

## Phase 4: Production Setup

### 4.1 Configure Automated Export (Client Team)

- [ ] Create Snowflake Task for scheduled exports
- [ ] Configure appropriate schedule (daily recommended)
- [ ] Set up alerting for failed exports (optional)
- [ ] Resume the task

### 4.2 Set Up Monitoring (Both Teams)

**FrontierMind:**
- [ ] Add client to ingestion monitoring dashboard
- [ ] Configure alerts for missing files
- [ ] Configure alerts for validation failures

**Client:**
- [ ] Monitor Snowflake Task execution history
- [ ] Set up alerts for COPY INTO failures
- [ ] Optionally poll status API after exports

### 4.3 Documentation

- [ ] Client received SNOWFLAKE_INTEGRATION.md
- [ ] Client received FILE_FORMAT_SPEC.md
- [ ] Client has API key documentation
- [ ] Client has support contact information

---

## Sign-Off

### FrontierMind Team

| Task | Completed | Date | By |
|------|-----------|------|-----|
| Organization created | [ ] | | |
| IAM role deployed | [ ] | | |
| Trust policy updated | [ ] | | |
| Test data verified | [ ] | | |
| Monitoring configured | [ ] | | |

### Client Team

| Task | Completed | Date | By |
|------|-----------|------|-----|
| Storage integration created | [ ] | | |
| Stage and format created | [ ] | | |
| Test export successful | [ ] | | |
| Automated task configured | [ ] | | |
| Production data flowing | [ ] | | |

---

## Rollback Procedure

If integration needs to be disabled:

### FrontierMind

```bash
# Disable IAM role
terraform destroy -target=aws_iam_role.snowflake_access_org_${ORG_ID}

# Archive existing data (optional)
aws s3 mv s3://frontiermind-meter-data/raw/snowflake/${ORG_ID}/ \
          s3://frontiermind-meter-data/archive/snowflake/${ORG_ID}/ --recursive
```

### Client

```sql
-- Suspend task
ALTER TASK frontiermind_daily_export SUSPEND;

-- Drop integration (optional)
DROP STORAGE INTEGRATION frontiermind_integration;
```

---

## Support Contacts

**FrontierMind:**
- Integrations Team: integrations@frontiermind.com
- On-Call: support@frontiermind.com

**Escalation Path:**
1. Integration issues → integrations@frontiermind.com
2. Data quality issues → data-engineering@frontiermind.com
3. Urgent/production issues → support@frontiermind.com
