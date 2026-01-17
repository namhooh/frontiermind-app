# Data Processing

AWS Lambda and infrastructure for validating and loading meter data from S3 to PostgreSQL.

## Overview

The Validator Lambda is triggered by S3 events when new files are uploaded to the `raw/` prefix. It validates, transforms, and loads the data into Supabase PostgreSQL.

```
┌─────────────────────────────────────────────────────────────────┐
│                    VALIDATOR LAMBDA FLOW                         │
└─────────────────────────────────────────────────────────────────┘

1. TRIGGER: S3 ObjectCreated event on raw/{source}/{org_id}/...
                │
                ▼
2. DOWNLOAD & PARSE:
   - Download file from S3
   - Parse JSON/CSV/Parquet
   - Extract metadata (source, org_id, site_id)
                │
                ▼
3. VALIDATE:
   - Check required fields exist
   - Validate data types
   - Check timestamps are reasonable
   - Validate values are within expected ranges
                │
                ▼
4. BRANCH:
   │
   ├── VALID:
   │   ├── Transform to canonical model
   │   ├── Load to meter_reading table (batch insert)
   │   ├── Move file to validated/
   │   └── Emit success metrics
   │
   └── INVALID:
       ├── Move file to quarantine/
       ├── Log validation errors
       └── Emit failure metrics
```

## File Structure

```
processing/
├── README.md                  # This file
│
├── validator-lambda/          # AWS Lambda function
│   ├── handler.py             # Lambda entry point
│   ├── schema_validator.py    # Schema validation logic
│   ├── transformer.py         # Transform to canonical model
│   ├── loader.py              # Load to Supabase PostgreSQL
│   ├── requirements.txt       # Python dependencies
│   └── template.yaml          # SAM deployment template
│
└── infrastructure/            # AWS infrastructure
    ├── setup.sh               # Setup script for S3/IAM
    ├── s3-lifecycle.json      # S3 lifecycle rules
    └── iam-lambda-role.json   # Lambda execution role policy
```

## Deployment

### Prerequisites

- AWS CLI configured with appropriate credentials
- AWS SAM CLI installed
- S3 bucket already created

### Deploy Lambda

```bash
cd validator-lambda

# Build
sam build

# Deploy (first time - guided)
sam deploy --guided

# Deploy (subsequent)
sam deploy
```

### Add S3 Trigger

After deploying the Lambda, add the S3 trigger:

```bash
aws s3api put-bucket-notification-configuration \
  --bucket frontiermind-meter-data \
  --notification-configuration '{
    "LambdaFunctionConfigurations": [{
      "LambdaFunctionArn": "arn:aws:lambda:us-east-1:ACCOUNT_ID:function:frontiermind-validator-production",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {
        "Key": {
          "FilterRules": [{"Name": "prefix", "Value": "raw/"}]
        }
      }
    }]
  }'
```

## S3 Bucket Structure

```
s3://frontiermind-meter-data/
├── raw/                          # Landing zone (source data)
│   ├── solaredge/{org_id}/{date}/
│   ├── enphase/{org_id}/{date}/
│   ├── snowflake/{org_id}/{date}/
│   └── manual/{org_id}/{date}/
│
├── validated/                    # Passed validation (30 day retention)
│   └── {date}/
│
├── quarantine/                   # Failed validation (14 day retention)
│   └── {date}/
│
└── archive/                      # Long-term evidence (Glacier)
    └── evidence/
```

## Configuration

### Lambda Environment Variables

| Variable | Description |
|----------|-------------|
| `BUCKET_NAME` | S3 bucket name |
| `ENVIRONMENT` | deployment environment |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service role key |

### Lambda Specs

| Setting | Value |
|---------|-------|
| Runtime | Python 3.11 |
| Memory | 1024 MB |
| Timeout | 5 minutes |
| Trigger | S3 ObjectCreated on `raw/` prefix |

## Infrastructure Setup

Run the setup script to create required AWS resources:

```bash
cd infrastructure
./setup.sh
```

This creates:
- S3 bucket with lifecycle rules
- IAM role for Lambda execution
- Required permissions
