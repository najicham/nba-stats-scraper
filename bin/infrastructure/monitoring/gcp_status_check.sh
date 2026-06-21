#!/bin/bash
set -euo pipefail
# File: bin/monitoring/gcp_status_check.sh
# Purpose: Quick status check of GCP infrastructure for NBA gamebook backfill

echo "=== NBA Gamebook Backfill Status Check ==="
echo "Date: $(date)"
echo

# Check if authenticated
echo "🔐 Authentication Status:"
gcloud auth list --filter="status:ACTIVE" --format="table(account,status)" 2>/dev/null || echo "❌ Not authenticated"
echo

# Check current project
echo "📋 Current Project:"
gcloud config get-value project 2>/dev/null || echo "❌ No project set"
echo

# Check existing Cloud Run job
echo "🏃 Existing Cloud Run Job:"
gcloud run jobs describe nba-gamebook-backfill \
  --region=us-west2 \
  --format="table(metadata.name,status.conditions[0].type,spec.template.spec.template.spec.containers[0].image)" \
  2>/dev/null || echo "❌ Job doesn't exist yet"
echo

# Check scraper service status
echo "🕷️  Scraper Service Status:"
gcloud run services describe nba-scrapers \
  --region=us-west2 \
  --format="table(metadata.name,status.url,status.conditions[0].type)" \
  2>/dev/null || echo "❌ Service not found"
echo

# Check container image exists
echo "🐳 Container Image Status:"
gcloud container images list-tags gcr.io/nba-props-platform/nba-gamebook-backfill \
  --format="table(tags,timestamp)" \
  --limit=3 2>/dev/null || echo "❌ No images found"
echo

# Check GCS bucket access
echo "☁️  GCS Bucket Access:"
gsutil ls gs://nba-scraped-data/nba-com/ 2>/dev/null | head -5 || echo "❌ Can't access bucket"
echo

# Check recent schedule data
echo "📅 Recent Schedule Data:"
gsutil ls gs://nba-scraped-data/nba-com/schedule/ 2>/dev/null || echo "❌ No schedule data"
echo

echo "=== Status Check Complete ==="
