#!/bin/bash
# Force predictions for a specific date - bypasses all dependency checks
# Usage: ./bin/pipeline/force_predictions.sh 2025-12-28 [dataset_prefix]
#
# This script is the "nuclear option" - use when the normal pipeline fails.
# It clears stuck state and runs all phases with skip_dependency_check=true.
#
# dataset_prefix: Optional prefix for test datasets (e.g., "test" -> test_nba_analytics)

set -euo pipefail

DATE=${1:-$(TZ=America/New_York date -d "tomorrow" +%Y-%m-%d)}
DATASET_PREFIX=${2:-""}
REGION="us-west2"

echo "================================================"
echo "FORCE PREDICTIONS FOR: $DATE"
if [ -n "$DATASET_PREFIX" ]; then
  echo "DATASET PREFIX: ${DATASET_PREFIX}_"
fi
echo "================================================"
echo ""

# Get auth token
TOKEN=$(gcloud auth print-identity-token)

# Step 1: Clear any stuck run_history for this date
echo "[1/5] Clearing stuck run_history entries..."
python3 -c "
from google.cloud import firestore
from datetime import datetime, timedelta, timezone

db = firestore.Client()
date = '$DATE'
now = datetime.now(timezone.utc)

# Find and delete stuck entries
docs = db.collection('run_history').where('status', '==', 'running').stream()
cleared = 0
for doc in docs:
    data = doc.to_dict()
    started = data.get('started_at')
    # Clear if stuck (>4 hours) or if it's for our target date
    if started and started < now - timedelta(hours=4):
        doc.reference.delete()
        cleared += 1
        print(f'  Cleared: {doc.id}')

# Also clear any failed entries for this date to allow retry
failed_docs = db.collection('run_history').where('data_date', '==', date).where('status', '==', 'failed').stream()
for doc in failed_docs:
    doc.reference.delete()
    cleared += 1
    print(f'  Cleared failed: {doc.id}')

print(f'Cleared {cleared} entries')
" 2>/dev/null || echo "  No entries to clear"

# Step 2: Run Phase 3 Analytics in backfill mode
echo ""
echo "[2/5] Running Phase 3 Analytics (backfill_mode=true)..."
YESTERDAY=$(TZ=America/New_York date -d "$DATE - 1 day" +%Y-%m-%d)

# Build request payload with optional dataset_prefix
PHASE3_PAYLOAD=$(cat <<EOF
{
  "start_date": "$YESTERDAY",
  "end_date": "$YESTERDAY",
  "processors": ["PlayerGameSummaryProcessor", "UpcomingPlayerGameContextProcessor"],
  "backfill_mode": true$([ -n "$DATASET_PREFIX" ] && echo ",
  \"dataset_prefix\": \"$DATASET_PREFIX\"" || echo "")
}
EOF
)

curl -s -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$PHASE3_PAYLOAD" | jq -r '.message // .error // .'

# Step 3: Run Phase 4 with skip_dependency_check
echo ""
echo "[3/5] Running Phase 4 ML Feature Store (skip_dependency_check=true)..."

# Build request payload with optional dataset_prefix
PHASE4_PAYLOAD=$(cat <<EOF
{
  "analysis_date": "$DATE",
  "processors": ["MLFeatureStoreProcessor"],
  "strict_mode": false,
  "skip_dependency_check": true$([ -n "$DATASET_PREFIX" ] && echo ",
  \"dataset_prefix\": \"$DATASET_PREFIX\"" || echo "")
}
EOF
)

curl -s -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$PHASE4_PAYLOAD" | jq -r '.message // .error // .'

# Step 4: Wait a moment for features to populate
echo ""
echo "[4/5] Waiting 10s for feature store to populate..."
sleep 10

# Step 5: Run Prediction Coordinator
echo ""
echo "[5/5] Running Prediction Coordinator..."

# Build request payload with optional dataset_prefix
PHASE5_PAYLOAD=$(cat <<EOF
{
  "game_date": "$DATE"$([ -n "$DATASET_PREFIX" ] && echo ",
  \"dataset_prefix\": \"$DATASET_PREFIX\"" || echo "")
}
EOF
)

curl -s -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$PHASE5_PAYLOAD" | jq -r '.message // .error // .'

# Verify results
echo ""
echo "================================================"
echo "VERIFICATION"
echo "================================================"
sleep 5

# Use prefixed dataset if specified
PREDICTIONS_DATASET="nba_predictions"
if [ -n "$DATASET_PREFIX" ]; then
  PREDICTIONS_DATASET="${DATASET_PREFIX}_nba_predictions"
fi

bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as players,
  ROUND(AVG(estimated_line_value), 2) as avg_line_value
FROM ${PREDICTIONS_DATASET}.player_prop_predictions
WHERE game_date = '$DATE' AND is_active = TRUE
GROUP BY game_date"

echo ""
echo "Done! Check above for prediction counts."
