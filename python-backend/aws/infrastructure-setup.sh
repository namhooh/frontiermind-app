#!/bin/bash
#
# One-time AWS Infrastructure Setup for ECS Fargate
#
# This script creates all necessary AWS resources:
# - ECR repository
# - Secrets in Secrets Manager
# - IAM roles (task execution + task role)
# - VPC with public subnets
# - Security groups
# - Application Load Balancer
# - ECS cluster
# - CloudWatch log group
#
# Prerequisites:
#   1. AWS CLI v2 installed: brew install awscli
#   2. Configured: aws configure
#   3. Sufficient IAM permissions
#
# Usage:
#   ./infrastructure-setup.sh
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
AWS_REGION="${AWS_REGION:-us-east-1}"
PROJECT_NAME="frontiermind"
SERVICE_NAME="${PROJECT_NAME}-backend"
CLUSTER_NAME="${PROJECT_NAME}-cluster"
ECR_REPO_NAME="${PROJECT_NAME}-backend"
LOG_GROUP_NAME="/ecs/${SERVICE_NAME}"

# VPC Configuration
VPC_CIDR="10.0.0.0/16"
SUBNET_A_CIDR="10.0.1.0/24"
SUBNET_B_CIDR="10.0.2.0/24"

echo -e "${GREEN}=== AWS ECS Fargate Infrastructure Setup ===${NC}"
echo "Region:  ${AWS_REGION}"
echo "Project: ${PROJECT_NAME}"
echo ""

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI not found. Install with: brew install awscli${NC}"
    exit 1
fi

# Check authentication
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}Error: Not authenticated with AWS. Run: aws configure${NC}"
    exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "AWS Account: ${ACCOUNT_ID}"
echo ""

# ============================================================================
# Step 1: Create ECR Repository
# ============================================================================
echo -e "${YELLOW}Step 1: Creating ECR Repository...${NC}"

if aws ecr describe-repositories --repository-names ${ECR_REPO_NAME} --region ${AWS_REGION} &> /dev/null; then
    echo "  ECR repository already exists"
else
    aws ecr create-repository \
        --repository-name ${ECR_REPO_NAME} \
        --image-scanning-configuration scanOnPush=true \
        --region ${AWS_REGION}
    echo -e "  ${GREEN}ECR repository created${NC}"
fi

ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"
echo "  ECR URI: ${ECR_URI}"

# ============================================================================
# Step 2: Create Secrets in Secrets Manager
# ============================================================================
echo -e "${YELLOW}Step 2: Setting up Secrets Manager...${NC}"
echo -e "${BLUE}  NOTE: Secrets must be created manually with actual values:${NC}"
echo ""
echo "  aws secretsmanager create-secret --name ${PROJECT_NAME}/backend/anthropic-api-key --secret-string 'YOUR_KEY' --region ${AWS_REGION}"
echo "  aws secretsmanager create-secret --name ${PROJECT_NAME}/backend/llama-api-key --secret-string 'YOUR_KEY' --region ${AWS_REGION}"
echo "  aws secretsmanager create-secret --name ${PROJECT_NAME}/backend/database-url --secret-string 'YOUR_URL' --region ${AWS_REGION}"
echo "  aws secretsmanager create-secret --name ${PROJECT_NAME}/backend/encryption-key --secret-string 'YOUR_KEY' --region ${AWS_REGION}"
echo ""

# Check if secrets exist
SECRETS=("anthropic-api-key" "llama-api-key" "database-url" "encryption-key")
for secret in "${SECRETS[@]}"; do
    SECRET_NAME="${PROJECT_NAME}/backend/${secret}"
    if aws secretsmanager describe-secret --secret-id ${SECRET_NAME} --region ${AWS_REGION} &> /dev/null; then
        echo -e "  ${GREEN}Secret ${secret} exists${NC}"
    else
        echo -e "  ${RED}Secret ${secret} NOT FOUND - create it before deploying${NC}"
    fi
done

# ============================================================================
# Step 3: Create VPC and Networking
# ============================================================================
echo -e "${YELLOW}Step 3: Creating VPC and Networking...${NC}"

# Check for existing VPC with our tag
EXISTING_VPC=$(aws ec2 describe-vpcs \
    --filters "Name=tag:Name,Values=${PROJECT_NAME}-vpc" \
    --query 'Vpcs[0].VpcId' \
    --output text \
    --region ${AWS_REGION} 2>/dev/null || echo "None")

if [ "$EXISTING_VPC" != "None" ] && [ -n "$EXISTING_VPC" ]; then
    echo "  Using existing VPC: ${EXISTING_VPC}"
    VPC_ID=$EXISTING_VPC
else
    # Create VPC
    VPC_ID=$(aws ec2 create-vpc \
        --cidr-block ${VPC_CIDR} \
        --query 'Vpc.VpcId' \
        --output text \
        --region ${AWS_REGION})

    aws ec2 create-tags --resources ${VPC_ID} --tags Key=Name,Value=${PROJECT_NAME}-vpc --region ${AWS_REGION}
    aws ec2 modify-vpc-attribute --vpc-id ${VPC_ID} --enable-dns-hostnames --region ${AWS_REGION}
    aws ec2 modify-vpc-attribute --vpc-id ${VPC_ID} --enable-dns-support --region ${AWS_REGION}
    echo -e "  ${GREEN}VPC created: ${VPC_ID}${NC}"
fi

# Create Internet Gateway
EXISTING_IGW=$(aws ec2 describe-internet-gateways \
    --filters "Name=attachment.vpc-id,Values=${VPC_ID}" \
    --query 'InternetGateways[0].InternetGatewayId' \
    --output text \
    --region ${AWS_REGION} 2>/dev/null || echo "None")

if [ "$EXISTING_IGW" != "None" ] && [ -n "$EXISTING_IGW" ]; then
    IGW_ID=$EXISTING_IGW
    echo "  Using existing Internet Gateway: ${IGW_ID}"
else
    IGW_ID=$(aws ec2 create-internet-gateway \
        --query 'InternetGateway.InternetGatewayId' \
        --output text \
        --region ${AWS_REGION})

    aws ec2 attach-internet-gateway --internet-gateway-id ${IGW_ID} --vpc-id ${VPC_ID} --region ${AWS_REGION}
    aws ec2 create-tags --resources ${IGW_ID} --tags Key=Name,Value=${PROJECT_NAME}-igw --region ${AWS_REGION}
    echo -e "  ${GREEN}Internet Gateway created: ${IGW_ID}${NC}"
fi

# Get availability zones
AZ_A=$(aws ec2 describe-availability-zones \
    --query 'AvailabilityZones[0].ZoneName' \
    --output text \
    --region ${AWS_REGION})
AZ_B=$(aws ec2 describe-availability-zones \
    --query 'AvailabilityZones[1].ZoneName' \
    --output text \
    --region ${AWS_REGION})

# Create Subnet A
EXISTING_SUBNET_A=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=${VPC_ID}" "Name=tag:Name,Values=${PROJECT_NAME}-subnet-a" \
    --query 'Subnets[0].SubnetId' \
    --output text \
    --region ${AWS_REGION} 2>/dev/null || echo "None")

if [ "$EXISTING_SUBNET_A" != "None" ] && [ -n "$EXISTING_SUBNET_A" ]; then
    SUBNET_A_ID=$EXISTING_SUBNET_A
    echo "  Using existing Subnet A: ${SUBNET_A_ID}"
else
    SUBNET_A_ID=$(aws ec2 create-subnet \
        --vpc-id ${VPC_ID} \
        --cidr-block ${SUBNET_A_CIDR} \
        --availability-zone ${AZ_A} \
        --query 'Subnet.SubnetId' \
        --output text \
        --region ${AWS_REGION})

    aws ec2 create-tags --resources ${SUBNET_A_ID} --tags Key=Name,Value=${PROJECT_NAME}-subnet-a --region ${AWS_REGION}
    aws ec2 modify-subnet-attribute --subnet-id ${SUBNET_A_ID} --map-public-ip-on-launch --region ${AWS_REGION}
    echo -e "  ${GREEN}Subnet A created: ${SUBNET_A_ID} (${AZ_A})${NC}"
fi

# Create Subnet B
EXISTING_SUBNET_B=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=${VPC_ID}" "Name=tag:Name,Values=${PROJECT_NAME}-subnet-b" \
    --query 'Subnets[0].SubnetId' \
    --output text \
    --region ${AWS_REGION} 2>/dev/null || echo "None")

if [ "$EXISTING_SUBNET_B" != "None" ] && [ -n "$EXISTING_SUBNET_B" ]; then
    SUBNET_B_ID=$EXISTING_SUBNET_B
    echo "  Using existing Subnet B: ${SUBNET_B_ID}"
else
    SUBNET_B_ID=$(aws ec2 create-subnet \
        --vpc-id ${VPC_ID} \
        --cidr-block ${SUBNET_B_CIDR} \
        --availability-zone ${AZ_B} \
        --query 'Subnet.SubnetId' \
        --output text \
        --region ${AWS_REGION})

    aws ec2 create-tags --resources ${SUBNET_B_ID} --tags Key=Name,Value=${PROJECT_NAME}-subnet-b --region ${AWS_REGION}
    aws ec2 modify-subnet-attribute --subnet-id ${SUBNET_B_ID} --map-public-ip-on-launch --region ${AWS_REGION}
    echo -e "  ${GREEN}Subnet B created: ${SUBNET_B_ID} (${AZ_B})${NC}"
fi

# Create Route Table
EXISTING_RT=$(aws ec2 describe-route-tables \
    --filters "Name=vpc-id,Values=${VPC_ID}" "Name=tag:Name,Values=${PROJECT_NAME}-rt" \
    --query 'RouteTables[0].RouteTableId' \
    --output text \
    --region ${AWS_REGION} 2>/dev/null || echo "None")

if [ "$EXISTING_RT" != "None" ] && [ -n "$EXISTING_RT" ]; then
    RT_ID=$EXISTING_RT
    echo "  Using existing Route Table: ${RT_ID}"
else
    RT_ID=$(aws ec2 create-route-table \
        --vpc-id ${VPC_ID} \
        --query 'RouteTable.RouteTableId' \
        --output text \
        --region ${AWS_REGION})

    aws ec2 create-tags --resources ${RT_ID} --tags Key=Name,Value=${PROJECT_NAME}-rt --region ${AWS_REGION}
    aws ec2 create-route --route-table-id ${RT_ID} --destination-cidr-block 0.0.0.0/0 --gateway-id ${IGW_ID} --region ${AWS_REGION}
    aws ec2 associate-route-table --route-table-id ${RT_ID} --subnet-id ${SUBNET_A_ID} --region ${AWS_REGION}
    aws ec2 associate-route-table --route-table-id ${RT_ID} --subnet-id ${SUBNET_B_ID} --region ${AWS_REGION}
    echo -e "  ${GREEN}Route Table created: ${RT_ID}${NC}"
fi

# ============================================================================
# Step 4: Create Security Groups
# ============================================================================
echo -e "${YELLOW}Step 4: Creating Security Groups...${NC}"

# ALB Security Group
EXISTING_ALB_SG=$(aws ec2 describe-security-groups \
    --filters "Name=vpc-id,Values=${VPC_ID}" "Name=group-name,Values=${PROJECT_NAME}-alb-sg" \
    --query 'SecurityGroups[0].GroupId' \
    --output text \
    --region ${AWS_REGION} 2>/dev/null || echo "None")

if [ "$EXISTING_ALB_SG" != "None" ] && [ -n "$EXISTING_ALB_SG" ]; then
    ALB_SG_ID=$EXISTING_ALB_SG
    echo "  Using existing ALB Security Group: ${ALB_SG_ID}"
else
    ALB_SG_ID=$(aws ec2 create-security-group \
        --group-name ${PROJECT_NAME}-alb-sg \
        --description "ALB security group for ${PROJECT_NAME}" \
        --vpc-id ${VPC_ID} \
        --query 'GroupId' \
        --output text \
        --region ${AWS_REGION})

    aws ec2 create-tags --resources ${ALB_SG_ID} --tags Key=Name,Value=${PROJECT_NAME}-alb-sg --region ${AWS_REGION}

    # Allow HTTP from anywhere
    aws ec2 authorize-security-group-ingress \
        --group-id ${ALB_SG_ID} \
        --protocol tcp \
        --port 80 \
        --cidr 0.0.0.0/0 \
        --region ${AWS_REGION}

    # Allow HTTPS from anywhere
    aws ec2 authorize-security-group-ingress \
        --group-id ${ALB_SG_ID} \
        --protocol tcp \
        --port 443 \
        --cidr 0.0.0.0/0 \
        --region ${AWS_REGION}

    echo -e "  ${GREEN}ALB Security Group created: ${ALB_SG_ID}${NC}"
fi

# ECS Security Group
EXISTING_ECS_SG=$(aws ec2 describe-security-groups \
    --filters "Name=vpc-id,Values=${VPC_ID}" "Name=group-name,Values=${PROJECT_NAME}-ecs-sg" \
    --query 'SecurityGroups[0].GroupId' \
    --output text \
    --region ${AWS_REGION} 2>/dev/null || echo "None")

if [ "$EXISTING_ECS_SG" != "None" ] && [ -n "$EXISTING_ECS_SG" ]; then
    ECS_SG_ID=$EXISTING_ECS_SG
    echo "  Using existing ECS Security Group: ${ECS_SG_ID}"
else
    ECS_SG_ID=$(aws ec2 create-security-group \
        --group-name ${PROJECT_NAME}-ecs-sg \
        --description "ECS tasks security group for ${PROJECT_NAME}" \
        --vpc-id ${VPC_ID} \
        --query 'GroupId' \
        --output text \
        --region ${AWS_REGION})

    aws ec2 create-tags --resources ${ECS_SG_ID} --tags Key=Name,Value=${PROJECT_NAME}-ecs-sg --region ${AWS_REGION}

    # Allow port 8080 from ALB only
    aws ec2 authorize-security-group-ingress \
        --group-id ${ECS_SG_ID} \
        --protocol tcp \
        --port 8080 \
        --source-group ${ALB_SG_ID} \
        --region ${AWS_REGION}

    echo -e "  ${GREEN}ECS Security Group created: ${ECS_SG_ID}${NC}"
fi

# ============================================================================
# Step 5: Create IAM Roles
# ============================================================================
echo -e "${YELLOW}Step 5: Creating IAM Roles...${NC}"

# Task Execution Role
EXEC_ROLE_NAME="${PROJECT_NAME}-ecs-execution-role"
if aws iam get-role --role-name ${EXEC_ROLE_NAME} &> /dev/null; then
    echo "  Using existing Task Execution Role: ${EXEC_ROLE_NAME}"
else
    cat > /tmp/ecs-trust-policy.json << 'EOF'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "ecs-tasks.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}
EOF

    aws iam create-role \
        --role-name ${EXEC_ROLE_NAME} \
        --assume-role-policy-document file:///tmp/ecs-trust-policy.json

    # Attach managed policy
    aws iam attach-role-policy \
        --role-name ${EXEC_ROLE_NAME} \
        --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

    # Create secrets access policy
    cat > /tmp/secrets-policy.json << EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue"
            ],
            "Resource": "arn:aws:secretsmanager:${AWS_REGION}:${ACCOUNT_ID}:secret:${PROJECT_NAME}/backend/*"
        }
    ]
}
EOF

    aws iam put-role-policy \
        --role-name ${EXEC_ROLE_NAME} \
        --policy-name SecretsAccessPolicy \
        --policy-document file:///tmp/secrets-policy.json

    echo -e "  ${GREEN}Task Execution Role created: ${EXEC_ROLE_NAME}${NC}"
fi

EXEC_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${EXEC_ROLE_NAME}"

# Task Role (for S3 access)
TASK_ROLE_NAME="${PROJECT_NAME}-ecs-task-role"
if aws iam get-role --role-name ${TASK_ROLE_NAME} &> /dev/null; then
    echo "  Using existing Task Role: ${TASK_ROLE_NAME}"
else
    aws iam create-role \
        --role-name ${TASK_ROLE_NAME} \
        --assume-role-policy-document file:///tmp/ecs-trust-policy.json

    # Create S3 access policy
    cat > /tmp/s3-policy.json << EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::frontiermind-meter-data",
                "arn:aws:s3:::frontiermind-meter-data/*"
            ]
        }
    ]
}
EOF

    aws iam put-role-policy \
        --role-name ${TASK_ROLE_NAME} \
        --policy-name S3AccessPolicy \
        --policy-document file:///tmp/s3-policy.json

    echo -e "  ${GREEN}Task Role created: ${TASK_ROLE_NAME}${NC}"
fi

TASK_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${TASK_ROLE_NAME}"

# ============================================================================
# Step 6: Create Application Load Balancer
# ============================================================================
echo -e "${YELLOW}Step 6: Creating Application Load Balancer...${NC}"

# Check for existing ALB
EXISTING_ALB=$(aws elbv2 describe-load-balancers \
    --names ${PROJECT_NAME}-alb \
    --query 'LoadBalancers[0].LoadBalancerArn' \
    --output text \
    --region ${AWS_REGION} 2>/dev/null || echo "None")

if [ "$EXISTING_ALB" != "None" ] && [ -n "$EXISTING_ALB" ]; then
    ALB_ARN=$EXISTING_ALB
    ALB_DNS=$(aws elbv2 describe-load-balancers \
        --load-balancer-arns ${ALB_ARN} \
        --query 'LoadBalancers[0].DNSName' \
        --output text \
        --region ${AWS_REGION})
    echo "  Using existing ALB: ${ALB_DNS}"
else
    ALB_ARN=$(aws elbv2 create-load-balancer \
        --name ${PROJECT_NAME}-alb \
        --type application \
        --scheme internet-facing \
        --subnets ${SUBNET_A_ID} ${SUBNET_B_ID} \
        --security-groups ${ALB_SG_ID} \
        --query 'LoadBalancers[0].LoadBalancerArn' \
        --output text \
        --region ${AWS_REGION})

    ALB_DNS=$(aws elbv2 describe-load-balancers \
        --load-balancer-arns ${ALB_ARN} \
        --query 'LoadBalancers[0].DNSName' \
        --output text \
        --region ${AWS_REGION})

    echo -e "  ${GREEN}ALB created: ${ALB_DNS}${NC}"
fi

# Create Target Group
EXISTING_TG=$(aws elbv2 describe-target-groups \
    --names ${PROJECT_NAME}-tg \
    --query 'TargetGroups[0].TargetGroupArn' \
    --output text \
    --region ${AWS_REGION} 2>/dev/null || echo "None")

if [ "$EXISTING_TG" != "None" ] && [ -n "$EXISTING_TG" ]; then
    TG_ARN=$EXISTING_TG
    echo "  Using existing Target Group"
else
    TG_ARN=$(aws elbv2 create-target-group \
        --name ${PROJECT_NAME}-tg \
        --protocol HTTP \
        --port 8080 \
        --vpc-id ${VPC_ID} \
        --target-type ip \
        --health-check-protocol HTTP \
        --health-check-path /health \
        --health-check-interval-seconds 30 \
        --health-check-timeout-seconds 10 \
        --healthy-threshold-count 2 \
        --unhealthy-threshold-count 3 \
        --query 'TargetGroups[0].TargetGroupArn' \
        --output text \
        --region ${AWS_REGION})

    echo -e "  ${GREEN}Target Group created${NC}"
fi

# Create HTTP Listener
EXISTING_LISTENER=$(aws elbv2 describe-listeners \
    --load-balancer-arn ${ALB_ARN} \
    --query 'Listeners[?Port==`80`].ListenerArn' \
    --output text \
    --region ${AWS_REGION} 2>/dev/null || echo "")

if [ -n "$EXISTING_LISTENER" ]; then
    echo "  Using existing HTTP Listener"
else
    aws elbv2 create-listener \
        --load-balancer-arn ${ALB_ARN} \
        --protocol HTTP \
        --port 80 \
        --default-actions Type=forward,TargetGroupArn=${TG_ARN} \
        --region ${AWS_REGION} > /dev/null

    echo -e "  ${GREEN}HTTP Listener created${NC}"
fi

# ============================================================================
# Step 6.5: Create ECS Service-Linked Role (required for Fargate)
# ============================================================================
echo -e "${YELLOW}Step 6.5: Creating ECS Service-Linked Role...${NC}"

if aws iam get-role --role-name AWSServiceRoleForECS &> /dev/null; then
    echo "  ECS service-linked role already exists"
else
    aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com 2>/dev/null || true
    echo -e "  ${GREEN}ECS service-linked role created${NC}"
    # Wait a moment for the role to propagate
    sleep 5
fi

# ============================================================================
# Step 7: Create ECS Cluster
# ============================================================================
echo -e "${YELLOW}Step 7: Creating ECS Cluster...${NC}"

if aws ecs describe-clusters --clusters ${CLUSTER_NAME} --region ${AWS_REGION} --query 'clusters[0].status' --output text 2>/dev/null | grep -q "ACTIVE"; then
    echo "  Using existing ECS cluster: ${CLUSTER_NAME}"
else
    aws ecs create-cluster \
        --cluster-name ${CLUSTER_NAME} \
        --capacity-providers FARGATE \
        --default-capacity-provider-strategy capacityProvider=FARGATE,weight=1 \
        --setting name=containerInsights,value=enabled \
        --region ${AWS_REGION} > /dev/null

    echo -e "  ${GREEN}ECS Cluster created: ${CLUSTER_NAME}${NC}"
fi

# ============================================================================
# Step 8: Create CloudWatch Log Group
# ============================================================================
echo -e "${YELLOW}Step 8: Creating CloudWatch Log Group...${NC}"

if aws logs describe-log-groups --log-group-name-prefix ${LOG_GROUP_NAME} --region ${AWS_REGION} --query 'logGroups[0].logGroupName' --output text 2>/dev/null | grep -q "${LOG_GROUP_NAME}"; then
    echo "  Using existing log group: ${LOG_GROUP_NAME}"
else
    aws logs create-log-group \
        --log-group-name ${LOG_GROUP_NAME} \
        --region ${AWS_REGION}

    aws logs put-retention-policy \
        --log-group-name ${LOG_GROUP_NAME} \
        --retention-in-days 30 \
        --region ${AWS_REGION}

    echo -e "  ${GREEN}CloudWatch Log Group created: ${LOG_GROUP_NAME}${NC}"
fi

# ============================================================================
# Summary
# ============================================================================
echo ""
echo -e "${GREEN}=== Infrastructure Setup Complete ===${NC}"
echo ""
echo "Resources created:"
echo "  ECR Repository:   ${ECR_URI}"
echo "  VPC:              ${VPC_ID}"
echo "  Subnets:          ${SUBNET_A_ID}, ${SUBNET_B_ID}"
echo "  ALB:              ${ALB_DNS}"
echo "  Target Group:     ${TG_ARN}"
echo "  ALB Security Group: ${ALB_SG_ID}"
echo "  ECS Security Group: ${ECS_SG_ID}"
echo "  Execution Role:   ${EXEC_ROLE_ARN}"
echo "  Task Role:        ${TASK_ROLE_ARN}"
echo "  ECS Cluster:      ${CLUSTER_NAME}"
echo "  Log Group:        ${LOG_GROUP_NAME}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Create secrets (if not done):"
echo "   aws secretsmanager create-secret --name ${PROJECT_NAME}/backend/anthropic-api-key --secret-string 'YOUR_KEY' --region ${AWS_REGION}"
echo ""
echo "2. Update python-backend/aws/task-definition.json with:"
echo "   - executionRoleArn: ${EXEC_ROLE_ARN}"
echo "   - taskRoleArn: ${TASK_ROLE_ARN}"
echo "   - Replace ACCOUNT_ID with: ${ACCOUNT_ID}"
echo ""
echo "3. Run deployment:"
echo "   cd python-backend && ./deploy-aws.sh"
echo ""
echo -e "${BLUE}Environment variables for deploy-aws.sh:${NC}"
echo "  export AWS_REGION=${AWS_REGION}"
echo "  export VPC_ID=${VPC_ID}"
echo "  export SUBNET_IDS=\"${SUBNET_A_ID},${SUBNET_B_ID}\""
echo "  export ECS_SG_ID=${ECS_SG_ID}"
echo "  export TG_ARN=${TG_ARN}"
echo "  export ECR_URI=${ECR_URI}"
echo ""

# Save configuration to file
CONFIG_FILE="$(dirname $0)/infrastructure-config.env"
cat > ${CONFIG_FILE} << EOF
# AWS Infrastructure Configuration
# Generated by infrastructure-setup.sh on $(date)
# Source this file before running deploy-aws.sh

export AWS_REGION=${AWS_REGION}
export ACCOUNT_ID=${ACCOUNT_ID}
export VPC_ID=${VPC_ID}
export SUBNET_A_ID=${SUBNET_A_ID}
export SUBNET_B_ID=${SUBNET_B_ID}
export SUBNET_IDS="${SUBNET_A_ID},${SUBNET_B_ID}"
export ALB_SG_ID=${ALB_SG_ID}
export ECS_SG_ID=${ECS_SG_ID}
export ALB_ARN=${ALB_ARN}
export ALB_DNS=${ALB_DNS}
export TG_ARN=${TG_ARN}
export ECR_URI=${ECR_URI}
export EXEC_ROLE_ARN=${EXEC_ROLE_ARN}
export TASK_ROLE_ARN=${TASK_ROLE_ARN}
export CLUSTER_NAME=${CLUSTER_NAME}
export LOG_GROUP_NAME=${LOG_GROUP_NAME}
EOF

echo -e "${GREEN}Configuration saved to: ${CONFIG_FILE}${NC}"
echo "Run: source ${CONFIG_FILE}"
