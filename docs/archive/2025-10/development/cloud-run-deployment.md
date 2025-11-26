# Cloud Run Deployment Guide

## Overview

This guide covers deploying the NBA analytics platform to Google Cloud Run, including infrastructure setup, service deployment, and operational procedures.

## Prerequisites

### 📋 **Required Tools**
```bash
# Verify you have these installed
gcloud --version        # Google Cloud CLI
docker --version        # Docker
terraform --version     # Infrastructure as Code
```

### 🔐 **Authentication Setup**
```bash
# Login to Google Cloud
gcloud auth login

# Set default project
gcloud config set project YOUR_PROJECT_ID

# Configure Docker for Container Registry
gcloud auth configure-docker
```

### ☁️ **Required APIs**
```bash
# Enable necessary Google Cloud APIs
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable secretmanager.googleapis.com
gcloud services enable workflows.googleapis.com
gcloud services enable pubsub.googleapis.com
```

## Infrastructure Setup

### 🏗️ **Terraform Infrastructure**
```bash
# Navigate to infrastructure directory
cd infra/

# Initialize Terraform
terraform init

# Review planned changes
terraform plan -var="project_id=YOUR_PROJECT_ID"

# Apply infrastructure
terraform apply -var="project_id=YOUR_PROJECT_ID"
```

### 🔐 **Secret Management**
```bash
# Store API keys in Secret Manager
echo -n "$ODDS_API_KEY" | gcloud secrets create odds-api-key --data-file=-
echo -n "$BDL_API_KEY" | gcloud secrets create ball-dont-lie-api-key --data-file=-

# Verify secrets
gcloud secrets list
```

## Build and Deploy

### 🚀 **Quick Deployment**
```bash
# Deploy everything with one command
./bin/deploy_all_services.sh YOUR_PROJECT_ID us-central1 true

# This will:
# 1. Build all container images
# 2. Push to Container Registry  
# 3. Deploy to Cloud Run
# 4. Update Terraform infrastructure
```

### 🔧 **Manual Step-by-Step**

#### Step 1: Build Images
```bash
# Build all images using Cloud Build
gcloud builds submit --config docker/cloudbuild.yaml .

# Verify images are built
gcloud container images list --repository=gcr.io/YOUR_PROJECT_ID
```

#### Step 2: Deploy Individual Services
```bash
# Deploy Events Scraper
gcloud run deploy nba-scraper-events \
  --image gcr.io/YOUR_PROJECT_ID/nba-scrapers:latest \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --max-instances 10 \
  --set-env-vars PROJECT_ID=YOUR_PROJECT_ID \
  --service-account nba-scraper-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --args="events,--serve"

# Deploy Odds Scraper  
gcloud run deploy nba-scraper-odds \
  --image gcr.io/YOUR_PROJECT_ID/nba-scrapers:latest \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --max-instances 10 \
  --set-env-vars PROJECT_ID=YOUR_PROJECT_ID \
  --service-account nba-scraper-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --args="odds,--serve"

# Deploy Event Processor
gcloud run deploy nba-processor-events \
  --image gcr.io/YOUR_PROJECT_ID/nba-processors:latest \
  --region us-central1 \
  --platform managed \
  --no-allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 600 \
  --max-instances 5 \
  --set-env-vars PROJECT_ID=YOUR_PROJECT_ID \
  --service-account nba-processor-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --args="events,--serve"
```

## Service Configuration

### 🎛️ **Environment Variables**
```bash
# Common environment variables for all services
PROJECT_ID=your-gcp-project
REGION=us-central1
ENVIRONMENT=production

# Scraper-specific
ODDS_API_KEY=secret://odds-api-key
BDL_API_KEY=secret://ball-dont-lie-api-key

# Processor-specific  
DATABASE_URL=secret://database-url
BIGQUERY_DATASET=nba_analytics

# Report generator-specific
REPORT_STORAGE_BUCKET=nba-reports-bucket
EMAIL_API_KEY=secret://sendgrid-api-key
```

### 🔒 **Service Account Permissions**
```bash
# Scraper service account needs:
- roles/storage.objectAdmin        # Write to GCS
- roles/secretmanager.secretAccessor  # Read API keys
- roles/pubsub.publisher          # Trigger processing

# Processor service account needs:
- roles/storage.objectAdmin        # Read/write GCS
- roles/bigquery.dataEditor       # Write to BigQuery
- roles/pubsub.subscriber         # Listen to messages

# Report generator service account needs:  
- roles/bigquery.dataViewer       # Read processed data
- roles/storage.objectAdmin        # Store reports
```

## Testing Deployment

### 🏥 **Health Checks**
```bash
# Get service URLs
EVENTS_URL=$(gcloud run services describe nba-scraper-events \
  --region=us-central1 --format="value(status.url)")

ODDS_URL=$(gcloud run services describe nba-scraper-odds \
  --region=us-central1 --format="value(status.url)")

# Test health endpoints
curl "$EVENTS_URL/health"
curl "$ODDS_URL/health"

# Expected response:
# {"status": "healthy", "scraper": "odds_api_historical_events"}
```

### 🧪 **Functional Tests**
```bash
# Test events scraper
curl -X POST "$EVENTS_URL/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "basketball_nba",
    "date": "2024-12-15T00:00:00Z",
    "group": "dev",
    "debug": true
  }'

# Test odds scraper
curl -X POST "$ODDS_URL/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "basketball_nba", 
    "eventId": "sample_event_id",
    "date": "2024-12-15T00:00:00Z",
    "regions": "us",
    "markets": "player_points"
  }'
```

## Workflow Deployment

### 🔄 **Deploy NBA Scraper Workflow**
```bash
# Deploy the workflow
gcloud workflows deploy nba-scraper-workflow \
  --source=workflows/nba_scraper_cloud_run.yaml \
  --location=us-central1

# Execute workflow manually
gcloud workflows run nba-scraper-workflow \
  --data='{"date": "2024-12-15T00:00:00Z", "sport": "basketball_nba"}'

# Check execution status
gcloud workflows executions list --workflow=nba-scraper-workflow
```

### ⏰ **Schedule Execution**
```bash
# Create daily scheduler job
gcloud scheduler jobs create http nba-scraper-daily \
  --schedule="0 8 * * *" \
  --uri="https://workflowexecutions.googleapis.com/v1/projects/YOUR_PROJECT_ID/locations/us-central1/workflows/nba-scraper-workflow/executions" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"argument": {"date": "2025-01-15T00:00:00Z", "debug": false}}' \
  --oidc-service-account-email="nba-scraper-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com"
```

## Monitoring and Observability

### 📊 **Cloud Monitoring Dashboard**
```bash
# Import monitoring dashboard
gcloud monitoring dashboards create --config-from-file=monitoring/dashboards/nba_scrapers_dashboard.json
```

### 🚨 **Alert Policies**
```bash
# Create alert for failed scrapers
gcloud alpha monitoring policies create --policy-from-file=monitoring/alerts.yaml
```

### 📝 **Log Queries**
```bash
# View scraper logs
gcloud logs read "resource.type=cloud_run_revision AND resource.labels.service_name=nba-scraper-events" --limit=50

# View error logs
gcloud logs read "resource.type=cloud_run_revision AND severity=ERROR" --limit=20

# View scraper stats
gcloud logs read "jsonPayload.message=~\"SCRAPER_STATS.*\"" --limit=10
```

## Scaling Configuration

### 📈 **Auto-scaling Settings**
```bash
# Update scraper scaling (if needed)
gcloud run services update nba-scraper-events \
  --min-instances=0 \
  --max-instances=20 \
  --cpu-throttling \
  --region=us-central1

# Update processor scaling
gcloud run services update nba-processor-events \
  --min-instances=0 \
  --max-instances=10 \
  --no-cpu-throttling \
  --region=us-central1
```

### 💰 **Cost Optimization**
```bash
# Set up budget alerts
gcloud billing budgets create \
  --billing-account=YOUR_BILLING_ACCOUNT \
  --display-name="NBA Platform Budget" \
  --budget-amount=100USD \
  --threshold-rule=percent=80,basis=CURRENT_SPEND
```

## Troubleshooting

### 🔍 **Common Issues**

#### Service Won't Start
```bash
# Check service logs
gcloud logs read "resource.type=cloud_run_revision" --limit=50

# Check service configuration
gcloud run services describe nba-scraper-events --region=us-central1
```

#### API Key Issues
```bash
# Verify secret exists
gcloud secrets describe odds-api-key

# Check service account permissions
gcloud projects get-iam-policy YOUR_PROJECT_ID \
  --filter="bindings.members:nba-scraper-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com"
```

#### Container Build Failures
```bash
# Check build logs
gcloud builds log BUILD_ID

# Verify base image exists
gcloud container images list --repository=gcr.io/YOUR_PROJECT_ID/nba-base
```

### 🚑 **Emergency Procedures**

#### Rollback Deployment
```bash
# Get previous revision
gcloud run revisions list --service=nba-scraper-events --region=us-central1

# Rollback to previous revision
gcloud run services update-traffic nba-scraper-events \
  --to-revisions=REVISION_NAME=100 \
  --region=us-central1
```

#### Stop All Services
```bash
# Emergency stop (set traffic to 0)
for service in nba-scraper-events nba-scraper-odds nba-processor-events; do
  gcloud run services update-traffic $service \
    --to-revisions=CURRENT=0 \
    --region=us-central1
done
```

## Maintenance

### 🔄 **Regular Updates**
```bash
# Weekly: Update base images
./bin/update_base_images.sh

# Monthly: Review and update dependencies  
./bin/update_dependencies.sh

# As needed: Scale services based on usage
./bin/optimize_scaling.sh
```

### 📊 **Performance Review**
- Review Cloud Monitoring dashboards weekly
- Analyze cost reports monthly
- Update scaling parameters based on usage patterns
- Review logs for errors and optimization opportunities

---

**Next Steps:**
1. Set up [Development Workflow](development-workflow.md)
2. Configure [Monitoring and Alerts](monitoring-setup.md)
3. Review [Troubleshooting Guide](troubleshooting.md)

