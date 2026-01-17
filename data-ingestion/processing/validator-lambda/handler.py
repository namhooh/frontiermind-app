"""
FrontierMind Meter Data Validator Lambda

Triggered by S3 ObjectCreated events on raw/ prefix.
Validates, transforms, and loads meter data to Supabase PostgreSQL.

Flow:
1. Receive S3 event
2. Download file from S3
3. Validate against schema
4. Transform to canonical model
5. Load to meter_reading table
6. Move file to validated/ or quarantine/
7. Log to ingestion_log table
"""

import json
import logging
import os
import hashlib
from datetime import datetime
from typing import Optional
from urllib.parse import unquote_plus

import boto3

from schema_validator import SchemaValidator, ValidationResult
from transformer import Transformer
from loader import Loader

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')

# Environment variables
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'frontiermind-meter-data')


def get_secret(secret_name: str) -> str:
    """Retrieve secret from AWS Secrets Manager."""
    response = secrets_client.get_secret_value(SecretId=secret_name)
    return response['SecretString']


def get_database_url() -> str:
    """Get database URL from Secrets Manager."""
    return get_secret('frontiermind/supabase-url')


def parse_s3_key(key: str) -> dict:
    """
    Parse S3 key to extract metadata.

    Expected format: raw/{source}/{org_id}/{date}/{filename}
    Example: raw/solaredge/1/2026-01-16/site_abc_140000.json
    """
    parts = key.split('/')

    if len(parts) < 5:
        raise ValueError(f"Invalid S3 key format: {key}")

    return {
        'prefix': parts[0],  # 'raw'
        'source_type': parts[1],  # 'solaredge', 'manual', etc.
        'organization_id': int(parts[2]),
        'date': parts[3],
        'filename': '/'.join(parts[4:])
    }


def calculate_file_hash(content: bytes) -> str:
    """Calculate SHA256 hash of file content."""
    return hashlib.sha256(content).hexdigest()


def detect_file_format(key: str, content: bytes) -> str:
    """Detect file format from extension or content."""
    key_lower = key.lower()

    if key_lower.endswith('.json'):
        return 'json'
    elif key_lower.endswith('.csv'):
        return 'csv'
    elif key_lower.endswith('.parquet'):
        return 'parquet'
    elif key_lower.endswith('.xlsx'):
        return 'xlsx'

    # Try to detect from content
    try:
        json.loads(content)
        return 'json'
    except:
        pass

    if content.startswith(b'PAR1'):  # Parquet magic bytes
        return 'parquet'

    return 'unknown'


def move_file(bucket: str, source_key: str, destination_prefix: str) -> str:
    """Move file from source to destination prefix."""
    # Extract filename from key
    filename = source_key.split('/')[-1]
    date_str = datetime.utcnow().strftime('%Y-%m-%d')
    destination_key = f"{destination_prefix}/{date_str}/{filename}"

    # Copy to destination
    s3_client.copy_object(
        Bucket=bucket,
        CopySource={'Bucket': bucket, 'Key': source_key},
        Key=destination_key
    )

    # Delete original
    s3_client.delete_object(Bucket=bucket, Key=source_key)

    logger.info(f"Moved {source_key} to {destination_key}")
    return destination_key


def handler(event, context):
    """
    Lambda handler for S3 ObjectCreated events.

    Args:
        event: S3 event containing Records with bucket and object info
        context: Lambda context

    Returns:
        dict with statusCode and processing results
    """
    logger.info(f"Received event: {json.dumps(event)}")

    results = []

    for record in event.get('Records', []):
        result = process_record(record)
        results.append(result)

    # Return summary
    success_count = sum(1 for r in results if r['status'] == 'success')
    failed_count = len(results) - success_count

    return {
        'statusCode': 200,
        'body': {
            'processed': len(results),
            'success': success_count,
            'failed': failed_count,
            'results': results
        }
    }


def process_record(record: dict) -> dict:
    """
    Process a single S3 record.

    Args:
        record: S3 event record

    Returns:
        dict with processing results
    """
    bucket = record['s3']['bucket']['name']
    key = unquote_plus(record['s3']['object']['key'])
    size = record['s3']['object'].get('size', 0)

    logger.info(f"Processing file: s3://{bucket}/{key}")

    # Initialize components
    db_url = get_database_url()
    validator = SchemaValidator()
    transformer = Transformer()
    loader = Loader(db_url)

    ingestion_log_id = None

    try:
        # Parse S3 key for metadata
        metadata = parse_s3_key(key)
        source_type = metadata['source_type']
        org_id = metadata['organization_id']

        # Download file from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read()

        # Detect format and calculate hash
        file_format = detect_file_format(key, content)
        file_hash = calculate_file_hash(content)

        # Start ingestion log
        ingestion_log_id = loader.start_ingestion_log(
            organization_id=org_id,
            source_type=source_type,
            file_path=f"s3://{bucket}/{key}",
            file_size=size,
            file_format=file_format,
            file_hash=file_hash
        )

        # Check for duplicate
        if loader.is_duplicate_file(file_hash, org_id):
            logger.info(f"Duplicate file detected: {file_hash}")
            loader.complete_ingestion_log_skipped(ingestion_log_id, "Duplicate file")
            return {
                'key': key,
                'status': 'skipped',
                'reason': 'duplicate'
            }

        # Parse content based on format
        if file_format == 'json':
            data = json.loads(content)
        elif file_format == 'csv':
            import csv
            import io
            reader = csv.DictReader(io.StringIO(content.decode('utf-8')))
            data = list(reader)
        elif file_format == 'parquet':
            import pyarrow.parquet as pq
            import io
            table = pq.read_table(io.BytesIO(content))
            data = table.to_pylist()
        else:
            raise ValueError(f"Unsupported file format: {file_format}")

        # Validate
        validation_result = validator.validate(data, source_type)

        if not validation_result.is_valid:
            # Move to quarantine
            destination = move_file(bucket, key, 'quarantine')

            loader.complete_ingestion_log_quarantine(
                log_id=ingestion_log_id,
                validation_errors=validation_result.errors,
                error_message=validation_result.error_message,
                destination_path=destination
            )

            logger.warning(f"Validation failed for {key}: {validation_result.error_message}")

            return {
                'key': key,
                'status': 'quarantined',
                'errors': validation_result.errors[:5],  # Limit to first 5 errors
                'destination': destination
            }

        # Transform to canonical model
        canonical_records = transformer.transform(
            data=data,
            source_type=source_type,
            organization_id=org_id,
            metadata=metadata
        )

        # Load to database
        rows_loaded, data_start, data_end = loader.load_meter_readings(canonical_records)

        # Move to validated
        destination = move_file(bucket, key, 'validated')

        # Complete ingestion log
        loader.complete_ingestion_log_success(
            log_id=ingestion_log_id,
            rows_loaded=rows_loaded,
            data_start=data_start,
            data_end=data_end,
            destination_path=destination
        )

        logger.info(f"Successfully processed {key}: {rows_loaded} rows loaded")

        return {
            'key': key,
            'status': 'success',
            'rows_loaded': rows_loaded,
            'destination': destination
        }

    except Exception as e:
        logger.error(f"Error processing {key}: {str(e)}", exc_info=True)

        # Try to move to quarantine
        try:
            destination = move_file(bucket, key, 'quarantine')
        except:
            destination = None

        # Update ingestion log if we have one
        if ingestion_log_id:
            try:
                loader.complete_ingestion_log_error(
                    log_id=ingestion_log_id,
                    error_message=str(e),
                    destination_path=destination
                )
            except:
                pass

        return {
            'key': key,
            'status': 'error',
            'error': str(e),
            'destination': destination
        }
