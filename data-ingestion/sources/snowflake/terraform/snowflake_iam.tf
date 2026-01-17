# =============================================================================
# Snowflake Cross-Account IAM Access
# =============================================================================
#
# This Terraform configuration creates IAM roles that allow Snowflake to push
# meter data directly to FrontierMind's S3 bucket using COPY INTO commands.
#
# Each client organization gets a dedicated IAM role with:
# - s3:PutObject permission for their specific path prefix
# - s3:ListBucket permission with path prefix condition
# - Trust policy allowing their Snowflake AWS account to assume the role
#
# Usage:
#   terraform apply -var="org_id=42" -var="snowflake_iam_user_arn=arn:aws:iam::..." -var="snowflake_external_id=..."
#
# =============================================================================

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# =============================================================================
# Variables
# =============================================================================

variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "meter_data_bucket" {
  description = "S3 bucket for meter data"
  type        = string
  default     = "frontiermind-meter-data"
}

variable "org_id" {
  description = "FrontierMind organization ID for this Snowflake integration"
  type        = number
}

variable "snowflake_iam_user_arn" {
  description = "The IAM user ARN from Snowflake's storage integration (STORAGE_AWS_IAM_USER_ARN)"
  type        = string
}

variable "snowflake_external_id" {
  description = "The external ID from Snowflake's storage integration (STORAGE_AWS_EXTERNAL_ID)"
  type        = string
}

# =============================================================================
# Provider
# =============================================================================

provider "aws" {
  region = var.aws_region
}

# =============================================================================
# IAM Role for Snowflake Cross-Account Access
# =============================================================================

resource "aws_iam_role" "snowflake_access" {
  name        = "frontiermind-snowflake-org-${var.org_id}"
  description = "Allows Snowflake to write meter data to S3 for organization ${var.org_id}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowSnowflakeAssumeRole"
        Effect = "Allow"
        Principal = {
          AWS = var.snowflake_iam_user_arn
        }
        Action = "sts:AssumeRole"
        Condition = {
          StringEquals = {
            "sts:ExternalId" = var.snowflake_external_id
          }
        }
      }
    ]
  })

  tags = {
    Name         = "frontiermind-snowflake-org-${var.org_id}"
    Environment  = "production"
    Service      = "data-ingestion"
    Integration  = "snowflake"
    Organization = var.org_id
  }
}

# =============================================================================
# IAM Policy for S3 Access
# =============================================================================

resource "aws_iam_role_policy" "snowflake_s3_access" {
  name = "snowflake-s3-write-org-${var.org_id}"
  role = aws_iam_role.snowflake_access.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowPutObject"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:PutObjectAcl"
        ]
        Resource = [
          "arn:aws:s3:::${var.meter_data_bucket}/raw/snowflake/${var.org_id}/*"
        ]
      },
      {
        Sid    = "AllowListBucket"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          "arn:aws:s3:::${var.meter_data_bucket}"
        ]
        Condition = {
          StringLike = {
            "s3:prefix" = [
              "raw/snowflake/${var.org_id}/*"
            ]
          }
        }
      }
    ]
  })
}

# =============================================================================
# Outputs
# =============================================================================

output "role_arn" {
  description = "The ARN of the IAM role for Snowflake to assume"
  value       = aws_iam_role.snowflake_access.arn
}

output "role_name" {
  description = "The name of the IAM role"
  value       = aws_iam_role.snowflake_access.name
}

output "s3_path_prefix" {
  description = "The S3 path prefix this role can write to"
  value       = "s3://${var.meter_data_bucket}/raw/snowflake/${var.org_id}/"
}

output "external_id" {
  description = "The external ID configured for this role"
  value       = var.snowflake_external_id
  sensitive   = true
}

output "snowflake_storage_integration_config" {
  description = "Configuration snippet for Snowflake STORAGE INTEGRATION"
  value       = <<-EOT
    -- Run in Snowflake as ACCOUNTADMIN
    CREATE STORAGE INTEGRATION frontiermind_integration
      TYPE = EXTERNAL_STAGE
      STORAGE_PROVIDER = 'S3'
      ENABLED = TRUE
      STORAGE_AWS_ROLE_ARN = '${aws_iam_role.snowflake_access.arn}'
      STORAGE_ALLOWED_LOCATIONS = ('s3://${var.meter_data_bucket}/raw/snowflake/${var.org_id}/');
  EOT
}
