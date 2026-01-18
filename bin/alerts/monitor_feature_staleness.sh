#!/bin/bash

# NBA Prediction Platform - Feature Pipeline Staleness Monitor
# Checks ml_feature_store_v2 freshness and logs to Cloud Logging
# Designed to run via Cloud Scheduler every hour
# Usage: ./bin/alerts/monitor_feature_staleness.sh

set -euo pipefail

PROJECT="nba-props-platform"
THRESHOLD_HOURS=4

# Check feature freshness
RESULT=$(bq query --use_legacy_sql=false --project_id="$PROJECT" --format=json '
SELECT
  MAX(created_at) as last_feature_update,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as hours_ago,
  COUNT(DISTINCT player_lookup) as players_with_features
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE()
' 2>/dev/null)

HOURS_AGO=$(echo "$RESULT" | jq -r '.[0].hours_ago // "null"')
PLAYER_COUNT=$(echo "$RESULT" | jq -r '.[0].players_with_features // "0"')
LAST_UPDATE=$(echo "$RESULT" | jq -r '.[0].last_feature_update // "never"')

# Log to Cloud Logging (structured logging for metric creation)
if [ "$HOURS_AGO" == "null" ]; then
    # CRITICAL: No features at all
    echo "{\"severity\":\"ERROR\",\"message\":\"NBA_FEATURE_PIPELINE_STALE\",\"hours_ago\":999,\"player_count\":0,\"status\":\"CRITICAL\",\"reason\":\"No features found for current/upcoming games\"}" | \
        gcloud logging write nba-feature-staleness-monitor --severity=ERROR --project="$PROJECT" -
elif [ "$HOURS_AGO" -ge "$THRESHOLD_HOURS" ]; then
    # WARNING: Features are stale
    echo "{\"severity\":\"WARNING\",\"message\":\"NBA_FEATURE_PIPELINE_STALE\",\"hours_ago\":$HOURS_AGO,\"player_count\":$PLAYER_COUNT,\"status\":\"WARNING\",\"reason\":\"Features are ${HOURS_AGO} hours old (threshold: ${THRESHOLD_HOURS} hours)\",\"last_update\":\"$LAST_UPDATE\"}" | \
        gcloud logging write nba-feature-staleness-monitor --severity=WARNING --project="$PROJECT" -
    echo "WARNING: Features are $HOURS_AGO hours old (threshold: $THRESHOLD_HOURS hours)"
    exit 1
else
    # OK: Features are fresh
    echo "{\"severity\":\"INFO\",\"message\":\"NBA_FEATURE_PIPELINE_HEALTHY\",\"hours_ago\":$HOURS_AGO,\"player_count\":$PLAYER_COUNT,\"status\":\"OK\",\"last_update\":\"$LAST_UPDATE\"}" | \
        gcloud logging write nba-feature-staleness-monitor --severity=INFO --project="$PROJECT" -
    echo "OK: Features are fresh ($HOURS_AGO hours old, $PLAYER_COUNT players)"
fi

exit 0
