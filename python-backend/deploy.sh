#!/bin/bash
#
# Deploy Python backend to Google Cloud Run
#
# Usage:
#   ./deploy.sh                    # Uses default project from gcloud config
#   GCP_PROJECT_ID=myproject ./deploy.sh  # Override project ID
#
# Prerequisites:
#   1. gcloud CLI installed: brew install google-cloud-sdk
#   2. Authenticated: gcloud auth login
#   3. APIs enabled:
#      gcloud services enable cloudbuild.googleapis.com run.googleapis.com
#   4. Secrets created in Secret Manager (see README)
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="frontiermind-backend"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo -e "${GREEN}=== Deploying to Google Cloud Run ===${NC}"
echo "Project:  ${PROJECT_ID}"
echo "Region:   ${REGION}"
echo "Service:  ${SERVICE_NAME}"
echo "Image:    ${IMAGE_NAME}"
echo ""

# Validate project ID
if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}Error: No project ID set.${NC}"
    echo "Set with: gcloud config set project YOUR_PROJECT_ID"
    echo "Or: GCP_PROJECT_ID=your-project ./deploy.sh"
    exit 1
fi

# Check if gcloud is authenticated
if ! gcloud auth print-access-token &>/dev/null; then
    echo -e "${RED}Error: Not authenticated with gcloud.${NC}"
    echo "Run: gcloud auth login"
    exit 1
fi

# Set project
echo -e "${YELLOW}Setting project...${NC}"
gcloud config set project ${PROJECT_ID}

# Check if required APIs are enabled
echo -e "${YELLOW}Checking required APIs...${NC}"
REQUIRED_APIS="cloudbuild.googleapis.com run.googleapis.com secretmanager.googleapis.com"
for api in $REQUIRED_APIS; do
    if ! gcloud services list --enabled --filter="name:$api" --format="value(name)" | grep -q "$api"; then
        echo "Enabling $api..."
        gcloud services enable $api
    fi
done

# Build image using Cloud Build
echo -e "${YELLOW}Building Docker image with Cloud Build...${NC}"
echo "This may take 5-10 minutes on first build..."
gcloud builds submit --tag ${IMAGE_NAME} .

# Deploy to Cloud Run
echo -e "${YELLOW}Deploying to Cloud Run...${NC}"
gcloud run deploy ${SERVICE_NAME} \
    --image ${IMAGE_NAME} \
    --platform managed \
    --region ${REGION} \
    --memory 4Gi \
    --cpu 2 \
    --timeout 300s \
    --concurrency 80 \
    --max-instances 10 \
    --min-instances 0 \
    --port 8080 \
    --allow-unauthenticated \
    --set-env-vars "ENVIRONMENT=production,LOG_LEVEL=INFO" \
    --set-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest" \
    --set-secrets "LLAMA_CLOUD_API_KEY=llama-api-key:latest" \
    --set-secrets "DATABASE_URL=database-url:latest" \
    --set-secrets "SUPABASE_DB_URL=database-url:latest" \
    --set-secrets "ENCRYPTION_KEY=encryption-key:latest"

# Get service URL
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region ${REGION} --format 'value(status.url)')

echo ""
echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo ""
echo "Service URL:   ${SERVICE_URL}"
echo "Health Check:  ${SERVICE_URL}/health"
echo "API Docs:      ${SERVICE_URL}/docs"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Test health: curl ${SERVICE_URL}/health"
echo "2. Update Vercel env: NEXT_PUBLIC_PYTHON_BACKEND_URL=${SERVICE_URL}"
echo "3. View logs: gcloud run logs read --service=${SERVICE_NAME} --region=${REGION}"
