#!/bin/bash
# bin/deploy_cloud_run.sh
# Deploy scrapers to Cloud Run (integrates with existing Terraform)

set -e

PROJECT_ID=${1:-$(gcloud config get-value project)}
REGION=${2:-"us-central1"}

echo "Deploying NBA Scrapers to Cloud Run..."
echo "Project: $PROJECT_ID"
echo "Region: $REGION"

# 1. Build and push images using Cloud Build
echo "Building container images..."
gcloud builds submit --config cloudbuild.yaml .

# 2. Apply Terraform changes (uses your existing infrastructure)
echo "Applying Terraform infrastructure..."
cd infra/
terraform plan -var="project_id=$PROJECT_ID"
terraform apply -var="project_id=$PROJECT_ID" -auto-approve
cd ..

# 3. Store the API key in Secret Manager (if not already done)
if [[ -n "$ODDS_API_KEY" ]]; then
    echo "Storing API key in Secret Manager..."
    echo -n "$ODDS_API_KEY" | gcloud secrets create odds-api-key --data-file=- --replication-policy=automatic || \
    echo -n "$ODDS_API_KEY" | gcloud secrets versions add odds-api-key --data-file=-
fi

# 4. Get service URLs
EVENTS_URL=$(gcloud run services describe nba-scraper-events --region=$REGION --format="value(status.url)")
ODDS_URL=$(gcloud run services describe nba-scraper-odds --region=$REGION --format="value(status.url)")

echo "✅ Deployment complete!"
echo "Events scraper: $EVENTS_URL"
echo "Odds scraper: $ODDS_URL"
echo ""
echo "Test with:"
echo "curl $EVENTS_URL/health"
echo "curl $ODDS_URL/health"

