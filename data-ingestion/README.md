# Data Ingestion

This folder contains all data ingestion components for the FrontierMind platform. All three data sources feed into a shared S3 processing pipeline (Validator Lambda).

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         DATA SOURCES                             │
└─────────────────────────────────────────────────────────────────┘
        │                      │                      │
        ▼                      ▼                      ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│ INVERTER APIs │      │  SNOWFLAKE    │      │  FILE UPLOAD  │
│               │      │               │      │               │
│ sources/      │      │ sources/      │      │ sources/      │
│ inverter-api/ │      │ snowflake/    │      │ file-upload/  │
└───────┬───────┘      └───────┬───────┘      └───────┬───────┘
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               │
                               ▼
                ┌─────────────────────────┐
                │        S3 BUCKET        │
                │       (Lake-House)      │
                │                         │
                │  raw/{source}/{org}/    │
                └────────────┬────────────┘
                             │
                        S3 Event
                             │
                             ▼
                ┌─────────────────────────┐
                │   VALIDATOR LAMBDA      │
                │                         │
                │   processing/           │
                │   validator-lambda/     │
                └────────────┬────────────┘
                             │
                             ▼
                ┌─────────────────────────┐
                │   SUPABASE POSTGRES     │
                └─────────────────────────┘
```

## Folder Structure

```
data-ingestion/
├── README.md                          # This file
│
├── sources/                           # Data source integrations
│   ├── file-upload/                   # Manual CSV/Parquet uploads
│   │   └── README.md                  # File format specification
│   │
│   ├── inverter-api/                  # Manufacturer API fetchers
│   │   ├── README.md                  # Fetcher overview
│   │   ├── base_fetcher.py            # Base class with common logic
│   │   ├── config.py                  # Configuration management
│   │   ├── requirements.txt           # Python dependencies
│   │   ├── solaredge/fetcher.py       # SolarEdge API fetcher
│   │   ├── enphase/fetcher.py         # Enphase API fetcher (OAuth)
│   │   ├── goodwe/fetcher.py          # GoodWe API fetcher
│   │   └── sma/fetcher.py             # SMA API fetcher (OAuth)
│   │
│   └── snowflake/                     # Client Snowflake integration
│       ├── README.md                  # Integration guide
│       ├── ONBOARDING_CHECKLIST.md    # Client onboarding steps
│       └── terraform/                 # IAM resources for cross-account access
│
├── processing/                        # S3 event processing
│   ├── README.md                      # Processing overview
│   ├── validator-lambda/              # AWS Lambda for validation & loading
│   │   ├── handler.py                 # Lambda entry point
│   │   ├── schema_validator.py        # Schema validation logic
│   │   ├── transformer.py             # Transform to canonical model
│   │   ├── loader.py                  # Load to Supabase
│   │   ├── requirements.txt           # Python dependencies
│   │   └── template.yaml              # SAM deployment template
│   └── infrastructure/                # AWS infrastructure configs
│       ├── setup.sh                   # Infrastructure setup script
│       ├── s3-lifecycle.json          # S3 lifecycle rules
│       └── iam-lambda-role.json       # Lambda IAM role policy
│
└── oauth/                             # OAuth callback handling
    └── supabase-callback/             # Supabase Edge Function
        ├── index.ts                   # OAuth callback handler
        └── _shared/cors.ts            # CORS utilities
```

## Quick Links

- **File Upload**: [sources/file-upload/README.md](sources/file-upload/README.md) - Format specification for manual uploads
- **Inverter APIs**: [sources/inverter-api/README.md](sources/inverter-api/README.md) - Fetcher implementation guide
- **Snowflake**: [sources/snowflake/README.md](sources/snowflake/README.md) - Client integration instructions
- **Processing**: [processing/README.md](processing/README.md) - Lambda validator documentation

## Related Files

- **Architecture Doc**: [docs/IMPLEMENTATION_GUIDE_ARCHITECTURE.md](docs/IMPLEMENTATION_GUIDE_ARCHITECTURE.md) - Full system design
- **GitHub Workflows**: [../.github/workflows/](../.github/workflows/) - Fetcher scheduled workflows
- **Database Migrations**: [../database/migrations/](../database/migrations/) - Schema migrations
