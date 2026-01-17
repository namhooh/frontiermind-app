"""
Fetcher Configuration

Environment variables and constants for fetcher workers.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """Configuration for fetcher workers."""

    # AWS
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    s3_bucket: str = os.getenv("METER_DATA_BUCKET", "frontiermind-meter-data")

    # Supabase
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_key: str = os.getenv("SUPABASE_SERVICE_KEY", "")

    # Encryption
    encryption_key: str = os.getenv("ENCRYPTION_KEY", "")

    # API Endpoints
    solaredge_api_base: str = "https://monitoringapi.solaredge.com"
    goodwe_api_base: str = "https://openapi.semsportal.com/api"
    enphase_api_base: str = "https://api.enphaseenergy.com/api/v4"
    sma_api_base: str = "https://async-auth.sma.de/monitoring/v1"

    # OAuth Client IDs/Secrets (from environment/AWS Secrets)
    enphase_client_id: str = os.getenv("ENPHASE_CLIENT_ID", "")
    enphase_client_secret: str = os.getenv("ENPHASE_CLIENT_SECRET", "")
    sma_client_id: str = os.getenv("SMA_CLIENT_ID", "")
    sma_client_secret: str = os.getenv("SMA_CLIENT_SECRET", "")

    # Rate limits (requests per minute)
    solaredge_rate_limit: int = 300
    goodwe_rate_limit: int = 60
    enphase_rate_limit: int = 10  # Enphase is more restrictive
    sma_rate_limit: int = 60

    # Fetch window (hours to look back)
    default_lookback_hours: int = 2

    @classmethod
    def from_env(cls) -> "Config":
        """Create config from environment variables."""
        return cls()

    @classmethod
    def from_aws_secrets(cls) -> "Config":
        """Create config by fetching secrets from AWS Secrets Manager."""
        import boto3

        secrets = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))

        def get_secret(secret_id: str) -> str:
            try:
                response = secrets.get_secret_value(SecretId=secret_id)
                return response["SecretString"]
            except Exception as e:
                print(f"Warning: Could not fetch secret {secret_id}: {e}")
                return ""

        return cls(
            supabase_url=get_secret("frontiermind/supabase-url"),
            supabase_service_key=get_secret("frontiermind/supabase-service-key"),
            encryption_key=get_secret("frontiermind/encryption-key"),
            enphase_client_id=get_secret("frontiermind/enphase-client-id"),
            enphase_client_secret=get_secret("frontiermind/enphase-client-secret"),
            sma_client_id=get_secret("frontiermind/sma-client-id"),
            sma_client_secret=get_secret("frontiermind/sma-client-secret"),
        )


# Data source IDs (must match data_source table)
# These should be fetched from DB, but hardcoded for now
SOURCE_TYPE_IDS = {
    "solaredge": 1,  # Update with actual ID from data_source table
    "goodwe": 2,
    "enphase": 3,
    "sma": 4,
    "snowflake": 5,
    "manual": 6,
}
