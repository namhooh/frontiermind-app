#!/bin/bash
# =====================================================
# AWS Infrastructure Setup for FrontierMind Data Ingestion
# =====================================================
# This script sets up:
# 1. S3 bucket with lifecycle policies
# 2. IAM role for Validator Lambda
# 3. Secrets in AWS Secrets Manager
#
# Prerequisites:
# - AWS CLI configured with appropriate credentials
# - jq installed for JSON parsing
# =====================================================

set -e

# Configuration
BUCKET_NAME="frontiermind-meter-data"
REGION="${AWS_REGION:-us-east-1}"
LAMBDA_ROLE_NAME="frontiermind-validator-lambda-role"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "================================================"
echo "FrontierMind AWS Infrastructure Setup"
echo "================================================"
echo "Region: $REGION"
echo "Bucket: $BUCKET_NAME"
echo ""

# =====================================================
# Step 1: Create S3 Bucket
# =====================================================
echo "Step 1: Creating S3 bucket..."

if aws s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
    echo "  Bucket $BUCKET_NAME already exists"
else
    aws s3api create-bucket \
        --bucket "$BUCKET_NAME" \
        --region "$REGION" \
        $([ "$REGION" != "us-east-1" ] && echo "--create-bucket-configuration LocationConstraint=$REGION")
    echo "  Created bucket: $BUCKET_NAME"
fi

# Apply lifecycle configuration
echo "  Applying lifecycle configuration..."
aws s3api put-bucket-lifecycle-configuration \
    --bucket "$BUCKET_NAME" \
    --lifecycle-configuration "file://$SCRIPT_DIR/s3-lifecycle.json"
echo "  Lifecycle configuration applied"

# Block public access
echo "  Blocking public access..."
aws s3api put-public-access-block \
    --bucket "$BUCKET_NAME" \
    --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
echo "  Public access blocked"

# Enable versioning (optional, for audit trail)
echo "  Enabling versioning..."
aws s3api put-bucket-versioning \
    --bucket "$BUCKET_NAME" \
    --versioning-configuration Status=Enabled
echo "  Versioning enabled"

# =====================================================
# Step 2: Create IAM Role for Lambda
# =====================================================
echo ""
echo "Step 2: Creating IAM role for Lambda..."

# Trust policy for Lambda
TRUST_POLICY='{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "lambda.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}'

# Check if role exists
if aws iam get-role --role-name "$LAMBDA_ROLE_NAME" 2>/dev/null; then
    echo "  Role $LAMBDA_ROLE_NAME already exists"
else
    aws iam create-role \
        --role-name "$LAMBDA_ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY" \
        --description "Role for FrontierMind Validator Lambda"
    echo "  Created role: $LAMBDA_ROLE_NAME"
fi

# Attach custom policy
echo "  Attaching custom policy..."
aws iam put-role-policy \
    --role-name "$LAMBDA_ROLE_NAME" \
    --policy-name "frontiermind-validator-policy" \
    --policy-document "file://$SCRIPT_DIR/iam-lambda-role.json"
echo "  Custom policy attached"

# Attach managed policy for basic Lambda execution
aws iam attach-role-policy \
    --role-name "$LAMBDA_ROLE_NAME" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" \
    2>/dev/null || true
echo "  Basic execution policy attached"

# =====================================================
# Step 3: Create Secrets (if not exist)
# =====================================================
echo ""
echo "Step 3: Creating secrets in Secrets Manager..."

create_secret_if_not_exists() {
    local secret_name=$1
    local description=$2
    local placeholder_value=$3

    if aws secretsmanager describe-secret --secret-id "$secret_name" 2>/dev/null; then
        echo "  Secret $secret_name already exists"
    else
        aws secretsmanager create-secret \
            --name "$secret_name" \
            --description "$description" \
            --secret-string "$placeholder_value"
        echo "  Created secret: $secret_name (UPDATE WITH REAL VALUE!)"
    fi
}

create_secret_if_not_exists \
    "frontiermind/supabase-url" \
    "Supabase PostgreSQL connection URL" \
    "postgresql://user:pass@host:5432/db"

create_secret_if_not_exists \
    "frontiermind/supabase-service-key" \
    "Supabase service role key for backend operations" \
    "eyJ..."

create_secret_if_not_exists \
    "frontiermind/encryption-key" \
    "Fernet encryption key for credential storage" \
    "base64-encoded-32-byte-key"

# =====================================================
# Step 4: Create S3 bucket notification for Lambda (placeholder)
# =====================================================
echo ""
echo "Step 4: S3 event notification setup..."
echo "  NOTE: Lambda notification will be configured during SAM deployment"
echo "  Run 'cd lambdas/validator && sam deploy' to complete setup"

# =====================================================
# Summary
# =====================================================
echo ""
echo "================================================"
echo "Setup Complete!"
echo "================================================"
echo ""
echo "Resources created:"
echo "  - S3 Bucket: $BUCKET_NAME"
echo "  - IAM Role: $LAMBDA_ROLE_NAME"
echo "  - Secrets: frontiermind/supabase-url, frontiermind/supabase-service-key, frontiermind/encryption-key"
echo ""
echo "Next steps:"
echo "  1. Update secrets with real values in AWS Secrets Manager"
echo "  2. Deploy Validator Lambda: cd lambdas/validator && sam build && sam deploy --guided"
echo "  3. Run database migrations: psql \$DATABASE_URL -f database/migrations/006_meter_reading_v2.sql"
echo ""
echo "Bucket structure:"
echo "  s3://$BUCKET_NAME/"
echo "  ├── raw/{source}/{org_id}/{date}/   # Landing zone"
echo "  ├── validated/{date}/                # 30-day retention"
echo "  ├── quarantine/{date}/               # 14-day retention"
echo "  └── archive/                         # Glacier (long-term)"
echo ""
