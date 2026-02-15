#!/bin/bash
#
# Deploy Python backend to AWS ECS Fargate
#
# Usage:
#   ./deploy-aws.sh                    # Uses config from aws/infrastructure-config.env
#   AWS_REGION=us-east-1 ./deploy-aws.sh  # Override region
#
# Prerequisites:
#   1. AWS CLI v2 installed: brew install awscli
#   2. Docker installed and running
#   3. Authenticated: aws configure
#   4. Infrastructure setup complete: ./aws/infrastructure-setup.sh
#   5. Secrets created in AWS Secrets Manager
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Load configuration from infrastructure setup (if exists)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/aws/infrastructure-config.env"

if [ -f "${CONFIG_FILE}" ]; then
    echo -e "${BLUE}Loading configuration from ${CONFIG_FILE}${NC}"
    source "${CONFIG_FILE}"
fi

# Configuration (can be overridden by environment variables)
AWS_REGION="${AWS_REGION:-us-east-1}"
PROJECT_NAME="frontiermind"
SERVICE_NAME="${PROJECT_NAME}-backend"
CLUSTER_NAME="${CLUSTER_NAME:-${PROJECT_NAME}-cluster}"

# Get account ID if not set
if [ -z "$ACCOUNT_ID" ]; then
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
fi

# ECR configuration
ECR_URI="${ECR_URI:-${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}-backend}"

# Get git commit hash for image tagging
GIT_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "latest")

echo -e "${GREEN}=== Deploying to AWS ECS Fargate ===${NC}"
echo "Account:  ${ACCOUNT_ID}"
echo "Region:   ${AWS_REGION}"
echo "Cluster:  ${CLUSTER_NAME}"
echo "Service:  ${SERVICE_NAME}"
echo "ECR URI:  ${ECR_URI}"
echo "Git Hash: ${GIT_HASH}"
echo ""

# Validate required variables
if [ -z "$ACCOUNT_ID" ]; then
    echo -e "${RED}Error: Could not determine AWS Account ID${NC}"
    exit 1
fi

# Check Docker is running
if ! docker info &> /dev/null; then
    echo -e "${RED}Error: Docker is not running${NC}"
    exit 1
fi

# Check AWS CLI authentication
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}Error: Not authenticated with AWS. Run: aws configure${NC}"
    exit 1
fi

# ============================================================================
# Step 1: Authenticate Docker to ECR
# ============================================================================
echo -e "${YELLOW}Step 1: Authenticating Docker to ECR...${NC}"
aws ecr get-login-password --region ${AWS_REGION} | \
    docker login --username AWS --password-stdin ${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com
echo -e "${GREEN}  Authenticated${NC}"

# ============================================================================
# Step 2: Build Docker Image
# ============================================================================
echo -e "${YELLOW}Step 2: Building Docker image...${NC}"

# Build from project root so Dockerfile can access both python-backend/ and data-ingestion/
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

docker build --platform linux/amd64 \
  -f "${SCRIPT_DIR}/Dockerfile" \
  -t ${SERVICE_NAME}:${GIT_HASH} \
  -t ${SERVICE_NAME}:latest \
  "${PROJECT_ROOT}"
echo -e "${GREEN}  Build complete${NC}"

# ============================================================================
# Step 3: Tag and Push to ECR
# ============================================================================
echo -e "${YELLOW}Step 3: Pushing to ECR...${NC}"

# Tag for ECR
docker tag ${SERVICE_NAME}:${GIT_HASH} ${ECR_URI}:${GIT_HASH}
docker tag ${SERVICE_NAME}:latest ${ECR_URI}:latest

# Push both tags
docker push ${ECR_URI}:${GIT_HASH}
docker push ${ECR_URI}:latest
echo -e "${GREEN}  Pushed ${ECR_URI}:${GIT_HASH}${NC}"
echo -e "${GREEN}  Pushed ${ECR_URI}:latest${NC}"

# ============================================================================
# Step 4: Update Task Definition
# ============================================================================
echo -e "${YELLOW}Step 4: Registering new task definition...${NC}"

# Read template and substitute placeholders
TASK_DEF_TEMPLATE="${SCRIPT_DIR}/aws/task-definition.json"

if [ ! -f "${TASK_DEF_TEMPLATE}" ]; then
    echo -e "${RED}Error: Task definition template not found at ${TASK_DEF_TEMPLATE}${NC}"
    exit 1
fi

# Replace placeholders in task definition and write to temp file
TASK_DEF_FILE="/tmp/frontiermind-task-def-$$.json"
cat ${TASK_DEF_TEMPLATE} | \
    sed "s/ACCOUNT_ID/${ACCOUNT_ID}/g" | \
    sed "s|${ECR_URI}:latest|${ECR_URI}:${GIT_HASH}|g" > ${TASK_DEF_FILE}

# Register new task definition
TASK_DEF_ARN=$(aws ecs register-task-definition \
    --cli-input-json file://${TASK_DEF_FILE} \
    --query 'taskDefinition.taskDefinitionArn' \
    --output text \
    --region ${AWS_REGION})

# Clean up temp file
rm -f ${TASK_DEF_FILE}

echo -e "${GREEN}  Registered: ${TASK_DEF_ARN}${NC}"

# ============================================================================
# Step 5: Check/Create ECS Service
# ============================================================================
echo -e "${YELLOW}Step 5: Updating ECS service...${NC}"

# Check if service exists
SERVICE_STATUS=$(aws ecs describe-services \
    --cluster ${CLUSTER_NAME} \
    --services ${SERVICE_NAME} \
    --query 'services[0].status' \
    --output text \
    --region ${AWS_REGION} 2>/dev/null || echo "MISSING")

if [ "$SERVICE_STATUS" == "ACTIVE" ]; then
    # Update existing service
    echo "  Updating existing service..."
    aws ecs update-service \
        --cluster ${CLUSTER_NAME} \
        --service ${SERVICE_NAME} \
        --task-definition ${TASK_DEF_ARN} \
        --force-new-deployment \
        --region ${AWS_REGION} > /dev/null

    echo -e "${GREEN}  Service updated${NC}"
else
    # Create new service
    echo "  Creating new service..."

    # Check required variables for service creation
    if [ -z "$SUBNET_IDS" ] || [ -z "$ECS_SG_ID" ] || [ -z "$TG_ARN" ]; then
        echo -e "${RED}Error: Missing required variables for service creation${NC}"
        echo "Please ensure infrastructure-config.env is loaded or set:"
        echo "  SUBNET_IDS, ECS_SG_ID, TG_ARN"
        exit 1
    fi

    # Convert comma-separated subnets to JSON array
    SUBNET_ARRAY=$(echo $SUBNET_IDS | tr ',' '\n' | awk '{print "\"" $1 "\""}' | paste -sd ',' -)

    aws ecs create-service \
        --cluster ${CLUSTER_NAME} \
        --service-name ${SERVICE_NAME} \
        --task-definition ${TASK_DEF_ARN} \
        --desired-count 1 \
        --launch-type FARGATE \
        --platform-version LATEST \
        --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_ARRAY}],securityGroups=[\"${ECS_SG_ID}\"],assignPublicIp=ENABLED}" \
        --load-balancers "targetGroupArn=${TG_ARN},containerName=${SERVICE_NAME},containerPort=8080" \
        --health-check-grace-period-seconds 120 \
        --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true},maximumPercent=200,minimumHealthyPercent=100" \
        --region ${AWS_REGION} > /dev/null

    echo -e "${GREEN}  Service created${NC}"

    # Set up auto-scaling
    echo "  Configuring auto-scaling..."

    # Register scalable target
    aws application-autoscaling register-scalable-target \
        --service-namespace ecs \
        --scalable-dimension ecs:service:DesiredCount \
        --resource-id service/${CLUSTER_NAME}/${SERVICE_NAME} \
        --min-capacity 0 \
        --max-capacity 10 \
        --region ${AWS_REGION} 2>/dev/null || true

    # CPU scaling policy
    aws application-autoscaling put-scaling-policy \
        --service-namespace ecs \
        --scalable-dimension ecs:service:DesiredCount \
        --resource-id service/${CLUSTER_NAME}/${SERVICE_NAME} \
        --policy-name ${SERVICE_NAME}-cpu-scaling \
        --policy-type TargetTrackingScaling \
        --target-tracking-scaling-policy-configuration "{
            \"TargetValue\": 70.0,
            \"PredefinedMetricSpecification\": {
                \"PredefinedMetricType\": \"ECSServiceAverageCPUUtilization\"
            },
            \"ScaleOutCooldown\": 60,
            \"ScaleInCooldown\": 300
        }" \
        --region ${AWS_REGION} 2>/dev/null || true

    # Memory scaling policy
    aws application-autoscaling put-scaling-policy \
        --service-namespace ecs \
        --scalable-dimension ecs:service:DesiredCount \
        --resource-id service/${CLUSTER_NAME}/${SERVICE_NAME} \
        --policy-name ${SERVICE_NAME}-memory-scaling \
        --policy-type TargetTrackingScaling \
        --target-tracking-scaling-policy-configuration "{
            \"TargetValue\": 80.0,
            \"PredefinedMetricSpecification\": {
                \"PredefinedMetricType\": \"ECSServiceAverageMemoryUtilization\"
            },
            \"ScaleOutCooldown\": 60,
            \"ScaleInCooldown\": 300
        }" \
        --region ${AWS_REGION} 2>/dev/null || true

    echo -e "${GREEN}  Auto-scaling configured (min: 0, max: 10)${NC}"
fi

# ============================================================================
# Step 6: Wait for Service Stability
# ============================================================================
echo -e "${YELLOW}Step 6: Waiting for service to stabilize...${NC}"
echo "  This may take 2-5 minutes..."

aws ecs wait services-stable \
    --cluster ${CLUSTER_NAME} \
    --services ${SERVICE_NAME} \
    --region ${AWS_REGION}

echo -e "${GREEN}  Service is stable${NC}"

# ============================================================================
# Get Service URL
# ============================================================================
if [ -n "$ALB_DNS" ]; then
    SERVICE_URL="http://${ALB_DNS}"
else
    # Try to get ALB DNS from infrastructure
    ALB_DNS=$(aws elbv2 describe-load-balancers \
        --names ${PROJECT_NAME}-alb \
        --query 'LoadBalancers[0].DNSName' \
        --output text \
        --region ${AWS_REGION} 2>/dev/null || echo "")

    if [ -n "$ALB_DNS" ] && [ "$ALB_DNS" != "None" ]; then
        SERVICE_URL="http://${ALB_DNS}"
    else
        SERVICE_URL="<ALB_DNS_NOT_FOUND>"
    fi
fi

# ============================================================================
# Summary
# ============================================================================
echo ""
echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo ""
echo "Task Definition: ${TASK_DEF_ARN}"
echo "Image:           ${ECR_URI}:${GIT_HASH}"
echo ""
echo "Service URL:     ${SERVICE_URL}"
echo "Health Check:    ${SERVICE_URL}/health"
echo "API Docs:        ${SERVICE_URL}/docs"
echo ""
echo -e "${YELLOW}Useful commands:${NC}"
echo "  # View logs"
echo "  aws logs tail /ecs/${SERVICE_NAME} --follow --region ${AWS_REGION}"
echo ""
echo "  # Scale down (costs drop to ~\$18/month)"
echo "  aws ecs update-service --cluster ${CLUSTER_NAME} --service ${SERVICE_NAME} --desired-count 0 --region ${AWS_REGION}"
echo ""
echo "  # Scale up (30-60 second cold start)"
echo "  aws ecs update-service --cluster ${CLUSTER_NAME} --service ${SERVICE_NAME} --desired-count 1 --region ${AWS_REGION}"
echo ""
echo "  # Rollback to previous task definition"
echo "  aws ecs update-service --cluster ${CLUSTER_NAME} --service ${SERVICE_NAME} --task-definition ${SERVICE_NAME}:PREVIOUS_REVISION --force-new-deployment --region ${AWS_REGION}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Test health: curl ${SERVICE_URL}/health"
echo "2. Update Vercel env: NEXT_PUBLIC_PYTHON_BACKEND_URL=${SERVICE_URL}"
echo "3. Monitor: aws ecs describe-services --cluster ${CLUSTER_NAME} --services ${SERVICE_NAME} --region ${AWS_REGION}"
