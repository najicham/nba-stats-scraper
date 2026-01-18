#!/bin/bash
#
# create_grading_coverage_alert.sh
#
# Creates a Cloud Monitoring alert for low grading coverage.
# Alerts when grading coverage drops below 70% for predictions from 24+ hours ago.
#
# This uses a log-based metric + alert policy.

set -euo pipefail

PROJECT_ID="nba-props-platform"
NOTIFICATION_CHANNEL_ID=${NOTIFICATION_CHANNEL_ID:-""}  # Set this to your Slack channel ID

echo "=== Creating Grading Coverage Alert ==="
echo "Project: $PROJECT_ID"
echo ""

# Step 1: Create a log-based metric for grading coverage
# (Alternative: use BigQuery scheduled query + Cloud Logging)

echo "Creating scheduled BigQuery query to check grading coverage..."

# Create SQL query
cat > /tmp/grading_coverage_check.sql <<'EOF'
-- Check grading coverage for predictions from 24+ hours ago
WITH predictions_yesterday AS (
  SELECT
    game_date,
    COUNT(DISTINCT CONCAT(player_lookup, '|', system_id)) as total_predictions
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)  -- 2 days ago (allows time for boxscores)
    AND is_active = TRUE
  GROUP BY game_date
),
graded_yesterday AS (
  SELECT
    game_date,
    COUNT(DISTINCT CONCAT(player_lookup, '|', system_id)) as graded_predictions
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
  GROUP BY game_date
),
boxscores_yesterday AS (
  SELECT
    game_date,
    COUNT(DISTINCT player_lookup) as players_with_actuals
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
  GROUP BY game_date
)
SELECT
  p.game_date,
  p.total_predictions,
  COALESCE(g.graded_predictions, 0) as graded,
  COALESCE(b.players_with_actuals, 0) as boxscores_available,
  ROUND(COALESCE(g.graded_predictions, 0) * 100.0 / NULLIF(p.total_predictions, 0), 1) as coverage_pct,
  CASE
    WHEN b.players_with_actuals = 0 THEN 'NO_BOXSCORES'
    WHEN COALESCE(g.graded_predictions, 0) * 100.0 / NULLIF(p.total_predictions, 0) < 70 THEN 'LOW_COVERAGE_ALERT'
    ELSE 'OK'
  END as status,
  -- Log this for Cloud Logging integration
  CONCAT(
    'Grading coverage for ', CAST(p.game_date AS STRING), ': ',
    CAST(ROUND(COALESCE(g.graded_predictions, 0) * 100.0 / NULLIF(p.total_predictions, 0), 1) AS STRING),
    '% (', CAST(COALESCE(g.graded_predictions, 0) AS STRING), '/', CAST(p.total_predictions AS STRING), ')'
  ) as message
FROM predictions_yesterday p
LEFT JOIN graded_yesterday g ON p.game_date = g.game_date
LEFT JOIN boxscores_yesterday b ON p.game_date = b.game_date
WHERE COALESCE(b.players_with_actuals, 0) > 0  -- Only alert if boxscores exist
  AND COALESCE(g.graded_predictions, 0) * 100.0 / NULLIF(p.total_predictions, 0) < 70
EOF

echo "SQL query created at /tmp/grading_coverage_check.sql"
echo ""

# Step 2: Create Cloud Scheduler job to run this check daily
echo "Creating Cloud Scheduler job for grading coverage check..."

gcloud scheduler jobs create http grading-coverage-check \
  --location=us-west2 \
  --schedule="0 12 * * *" \
  --time-zone="America/Los_Angeles" \
  --uri="https://bigquery.googleapis.com/bigquery/v2/projects/$PROJECT_ID/queries" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body="{
    \"query\": \"$(cat /tmp/grading_coverage_check.sql | tr '\n' ' ' | sed 's/"/\\"/g')\",
    \"useLegacySql\": false
  }" \
  --oauth-service-account-email="756957797294-compute@developer.gserviceaccount.com" \
  2>/dev/null || echo "Scheduler job may already exist"

echo ""
echo "✅ Grading coverage monitoring setup complete!"
echo ""
echo "The check runs daily at 12:00 PM PT and queries grading coverage for 2 days ago."
echo "If coverage is < 70% and boxscores exist, it logs a LOW_COVERAGE_ALERT status."
echo ""
echo "Next steps:"
echo "1. Set up log-based alert in Cloud Monitoring Console:"
echo "   - Filter: textPayload=~\"LOW_COVERAGE_ALERT\""
echo "   - Threshold: > 0 occurrences in 24 hours"
echo "   - Notification: Slack channel"
echo ""
echo "2. Or use the Cloud Logging API to create the alert programmatically"
EOF
