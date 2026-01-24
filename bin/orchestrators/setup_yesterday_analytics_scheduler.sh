#!/bin/bash
# Setup scheduler for yesterday's analytics
# Runs backward-looking Phase 3 processors for YESTERDAY's completed games
#
# This addresses the gap where same-day-phase3 only runs forward-looking processors
# (UpcomingPlayerGameContext) but doesn't run backward-looking processors
# (PlayerGameSummary, TeamDefenseGameSummary, TeamOffenseGameSummary) for yesterday.
#
# Without this scheduler, grading fails because player_game_summary has no data
# for yesterday's games.
#
# Timeline (all times ET):
#   6:30 AM - daily-yesterday-analytics: Backward-looking Phase 3 for YESTERDAY
#   7:00 AM - phase6-daily-results: Grading (existing) - needs player_game_summary
#
# Created: 2025-12-30 (after Dec 29 grading incident)

set -euo pipefail

PROJECT_ID=${PROJECT_ID:-nba-props-platform}
REGION=${REGION:-us-west2}

echo "=== Setting up daily-yesterday-analytics scheduler ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Phase 3 endpoint
PHASE3_URL="https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range"

# Get service account for Cloud Run invocation
SERVICE_ACCOUNT="756957797294-compute@developer.gserviceaccount.com"

echo "Creating daily-yesterday-analytics scheduler (6:30 AM ET)..."

# Delete existing job if present (idempotent)
gcloud scheduler jobs delete daily-yesterday-analytics --location=$REGION --quiet 2>/dev/null || true

# Create the scheduler job
# Runs at 6:30 AM ET to allow time before grading (typically 7 AM)
# Processors:
#   - PlayerGameSummaryProcessor: Player stats for completed games (critical for grading)
#   - TeamDefenseGameSummaryProcessor: Team defensive metrics
#   - TeamOffenseGameSummaryProcessor: Team offensive metrics
# Note: UpcomingPlayerGameContext and UpcomingTeamGameContext are NOT included
#       as they are forward-looking and handled by same-day-phase3 for TODAY
gcloud scheduler jobs create http daily-yesterday-analytics \
  --location=$REGION \
  --schedule="30 6 * * *" \
  --time-zone="America/New_York" \
  --uri="$PHASE3_URL" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"start_date": "YESTERDAY", "end_date": "YESTERDAY", "processors": ["PlayerGameSummaryProcessor", "TeamDefenseGameSummaryProcessor", "TeamOffenseGameSummaryProcessor"], "backfill_mode": true}' \
  --oidc-service-account-email="$SERVICE_ACCOUNT" \
  --attempt-deadline="600s" \
  --description="Morning Phase 3 analytics for yesterday's completed games (supports grading)"

echo ""
echo "=== Scheduler created successfully ==="
echo ""
echo "Schedule: 6:30 AM ET daily"
echo "Target date: YESTERDAY"
echo "Processors:"
echo "  - PlayerGameSummaryProcessor (critical for grading)"
echo "  - TeamDefenseGameSummaryProcessor"
echo "  - TeamOffenseGameSummaryProcessor"
echo ""
echo "This ensures player_game_summary has data for yesterday before grading runs."
echo ""
echo "To verify:"
echo "  gcloud scheduler jobs list --location=$REGION | grep yesterday"
echo "  gcloud scheduler jobs describe daily-yesterday-analytics --location=$REGION"
echo ""
echo "To run immediately for testing:"
echo "  gcloud scheduler jobs run daily-yesterday-analytics --location=$REGION"
echo ""
echo "Timeline reminder (all times ET):"
echo "  6:30 AM - daily-yesterday-analytics: Phase 3 backward-looking"
echo "  7:00 AM - phase6-daily-results: Grading (requires player_game_summary)"
echo "  10:30 AM - same-day-phase3: Phase 3 forward-looking (today)"
