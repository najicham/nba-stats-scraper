#!/bin/bash
# deploy_bluesky_listener.sh
#
# Deploy the Bluesky NBA beat-writer listener as a Cloud Run Job.
# Runs as a long-lived WebSocket listener (8h) for injury/status posts
# from ~10 NBA beat writers. Triggers daily at noon ET on game days.
#
# Architecture:
#   Cloud Scheduler (noon ET) → Cloud Run Jobs API → bluesky-nba-listener job
#   Job runs bluesky_nba_news.py for 8 hours (noon–8 PM ET)
#   Flushes posts to GCS + BQ every 5 minutes
#
# Usage:
#   ./bin/deploy/deploy_bluesky_listener.sh
#   ./bin/deploy/deploy_bluesky_listener.sh --dry-run
#   ./bin/deploy/deploy_bluesky_listener.sh --scheduler-only
#   ./bin/deploy/deploy_bluesky_listener.sh --job-only

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
IMAGE="us-west2-docker.pkg.dev/${PROJECT_ID}/nba-props/nba-scrapers:latest"
JOB_NAME="bluesky-nba-listener"
SCHEDULER_JOB="nba-bluesky-listener-daily"
SA_EMAIL="756957797294-compute@developer.gserviceaccount.com"
TIMEZONE="America/New_York"

DRY_RUN="false"
SCHEDULER_ONLY="false"
JOB_ONLY="false"

for arg in "${@}"; do
    case "$arg" in
        --dry-run)        DRY_RUN="true" ;;
        --scheduler-only) SCHEDULER_ONLY="true" ;;
        --job-only)       JOB_ONLY="true" ;;
    esac
done

[[ "$DRY_RUN" == "true" ]] && echo "[DRY RUN] No resources will be created."

echo "========================================"
echo "Bluesky NBA Listener — Cloud Run Job"
echo "========================================"
echo "Project:  $PROJECT_ID"
echo "Region:   $REGION"
echo "Job:      $JOB_NAME"
echo "Image:    $IMAGE"
echo "Schedule: 0 12 * * * (noon ET, year-round; off-season listener opens + finds 0 posts)"
echo ""

# ── 1. Cloud Run Job ──────────────────────────────────────────────────────────

if [[ "$SCHEDULER_ONLY" != "true" ]]; then
    echo "--- Creating Cloud Run Job: $JOB_NAME ---"

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[DRY RUN] Would create/update Cloud Run Job: $JOB_NAME"
    else
        # Delete existing job (ignore if not found)
        gcloud run jobs delete "$JOB_NAME" \
            --region="$REGION" --project="$PROJECT_ID" --quiet 2>/dev/null || true

        gcloud run jobs create "$JOB_NAME" \
            --image="$IMAGE" \
            --region="$REGION" \
            --project="$PROJECT_ID" \
            --service-account="$SA_EMAIL" \
            --max-retries=0 \
            --task-timeout=28800 \
            --memory=512Mi \
            --cpu=1 \
            --command="python" \
            --args="-m,scrapers.external.bluesky_nba_news,--duration,480,--group,prod" \
            --description="Bluesky NBA beat-writer WebSocket listener (noon–8 PM ET game days)"

        # Env vars: use update-env-vars (safe: additive, never wipes existing vars)
        gcloud run jobs update "$JOB_NAME" \
            --region="$REGION" \
            --project="$PROJECT_ID" \
            --update-env-vars="GCP_PROJECT=${PROJECT_ID},GCS_BUCKET_RAW=nba-scraped-data"

        echo "Cloud Run Job created: $JOB_NAME"
    fi
    echo ""
fi

# ── 2. Cloud Scheduler trigger ────────────────────────────────────────────────

if [[ "$JOB_ONLY" != "true" ]]; then
    echo "--- Creating Cloud Scheduler: $SCHEDULER_JOB ---"

    # Jobs API URI for triggering a Cloud Run Job
    JOB_RUN_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[DRY RUN] Would create/update scheduler: $SCHEDULER_JOB"
        echo "  URI: $JOB_RUN_URI"
    else
        # Delete existing scheduler if present
        gcloud scheduler jobs delete "$SCHEDULER_JOB" \
            --location="$REGION" --project="$PROJECT_ID" --quiet 2>/dev/null || true

        # NBA season is Oct–Apr; run daily at noon ET
        # Cron months don't wrap, so use two separate patterns handled by one job
        # running year-round (off-season the listener opens and finds 0 posts — fine)
        gcloud scheduler jobs create http "$SCHEDULER_JOB" \
            --schedule="0 12 * * *" \
            --time-zone="$TIMEZONE" \
            --uri="$JOB_RUN_URI" \
            --http-method=POST \
            --location="$REGION" \
            --project="$PROJECT_ID" \
            --description="Trigger Bluesky NBA listener daily at noon ET (runs 8h, game days)" \
            --oauth-service-account-email="$SA_EMAIL" \
            --attempt-deadline=30s

        echo "Cloud Scheduler created: $SCHEDULER_JOB"
    fi
    echo ""
fi

echo "========================================"
echo "Done."
echo ""
echo "Verify job:"
echo "  gcloud run jobs describe $JOB_NAME --region=$REGION --project=$PROJECT_ID"
echo ""
echo "Manual trigger:"
echo "  gcloud run jobs execute $JOB_NAME --region=$REGION --project=$PROJECT_ID"
echo ""
echo "View logs:"
echo "  gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME' --limit=50"
echo ""
echo "Verify scheduler:"
echo "  gcloud scheduler jobs list --location=$REGION --project=$PROJECT_ID | grep bluesky"
