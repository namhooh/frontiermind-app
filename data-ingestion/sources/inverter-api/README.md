# Inverter API Fetchers

Fetcher workers that pull data from solar inverter manufacturer APIs and upload to S3 for processing.

## Supported Manufacturers

| Manufacturer | Auth Type | Fetcher | GitHub Workflow |
|--------------|-----------|---------|-----------------|
| SolarEdge | API Key | `solaredge/fetcher.py` | `.github/workflows/fetcher-solaredge.yml` |
| GoodWe | API Key | `goodwe/fetcher.py` | `.github/workflows/fetcher-goodwe.yml` |
| Enphase | OAuth 2.0 | `enphase/fetcher.py` | `.github/workflows/fetcher-enphase.yml` |
| SMA | OAuth 2.0 | `sma/fetcher.py` | `.github/workflows/fetcher-sma.yml` |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    FETCHER WORKER EXECUTION                      │
└─────────────────────────────────────────────────────────────────┘

1. TRIGGER: GitHub Actions cron schedule (hourly)
                │
                ▼
2. QUERY CREDENTIALS:
   - Fetch active credentials from Supabase
   - Decrypt credentials using Fernet
                │
                ▼
3. FOR EACH CREDENTIAL:
   │
   ├── If OAuth: Check token expiry
   │   └── If expired: Refresh token, update in DB
   │
   └── FOR EACH SITE:
       │
       ├── Call inverter API (last 2 hours of data)
       │
       └── Upload to S3: raw/{source}/{org_id}/{date}/site_{id}_{time}.json
                │
                ▼
4. EXIT (ephemeral - no persistent process)
```

## File Structure

```
inverter-api/
├── __init__.py              # Package exports
├── base_fetcher.py          # Abstract base class with common logic
├── config.py                # Configuration management
├── requirements.txt         # Python dependencies
│
├── solaredge/
│   └── fetcher.py           # SolarEdge API implementation
│
├── enphase/
│   └── fetcher.py           # Enphase OAuth API implementation
│
├── goodwe/
│   └── fetcher.py           # GoodWe API implementation
│
└── sma/
    └── fetcher.py           # SMA OAuth API implementation
```

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_SERVICE_KEY="your-service-key"
export ENCRYPTION_KEY="your-fernet-key"
export AWS_REGION="us-east-1"

# Run a fetcher (dry run mode)
python -m data-ingestion.sources.inverter-api.solaredge.fetcher --dry-run --verbose

# Run with custom lookback period
python -m data-ingestion.sources.inverter-api.solaredge.fetcher --lookback 4
```

## Adding a New Fetcher

1. Create a new folder under `inverter-api/` (e.g., `fronius/`)
2. Create `fetcher.py` that extends `BaseFetcher`
3. Implement required methods:
   - `fetch_site_data()` - Fetch data for a single site
   - `fetch_sites_list()` - List available sites
4. Add GitHub workflow in `.github/workflows/fetcher-{name}.yml`
5. Add manufacturer config to `config.py`

## Base Fetcher Features

The `BaseFetcher` class provides:

- **Credential Management**: Fetch and decrypt credentials from Supabase
- **OAuth Token Refresh**: Automatic token refresh for OAuth providers
- **S3 Upload**: Upload data with proper path structure
- **Status Tracking**: Update sync status in database
- **Error Handling**: Record errors for troubleshooting

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SUPABASE_URL` | Supabase project URL | Yes |
| `SUPABASE_SERVICE_KEY` | Supabase service role key | Yes |
| `ENCRYPTION_KEY` | Fernet key for credential encryption | Yes |
| `AWS_REGION` | AWS region for S3 | Yes |
| `METER_DATA_BUCKET` | S3 bucket name | No (default: frontiermind-meter-data) |
| `ENPHASE_CLIENT_ID` | Enphase OAuth client ID | For Enphase |
| `ENPHASE_CLIENT_SECRET` | Enphase OAuth client secret | For Enphase |
| `SMA_CLIENT_ID` | SMA OAuth client ID | For SMA |
| `SMA_CLIENT_SECRET` | SMA OAuth client secret | For SMA |
