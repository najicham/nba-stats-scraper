#!/usr/bin/env bash
# refresh-model-cache.sh
#
# Force prediction-worker to reload the BQ model registry on its next request.
# Use this after enabling or disabling models in nba_predictions.model_registry.
#
# The worker loads models once at startup (singleton). Changing MODEL_CACHE_REFRESH
# triggers a new Cloud Run revision, which cold-starts with a fresh registry read.
#
# Note: With Session 474's TTL-based refresh (default 4h), this is only needed for
# same-day immediate effect. Overnight cold-starts pick up registry changes automatically.
#
# Usage:
#   ./bin/refresh-model-cache.sh              # refresh worker only
#   ./bin/refresh-model-cache.sh --verify     # refresh + verify new models in predictions

set -euo pipefail

PROJECT="nba-props-platform"
REGION="us-west2"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "=== Refreshing prediction-worker model cache ==="
echo "Timestamp: $TIMESTAMP"
echo ""

gcloud run services update prediction-worker \
  --region="$REGION" \
  --project="$PROJECT" \
  --update-env-vars="MODEL_CACHE_REFRESH=$TIMESTAMP"

echo ""
echo "Worker updated. New revision is serving."
echo ""

if [[ "${1:-}" == "--verify" ]]; then
  echo "=== Verifying models loaded (waiting 10s for cold start) ==="
  sleep 10

  echo "Models currently generating predictions today:"
  bq query --use_legacy_sql=false --format=pretty --project_id="$PROJECT" \
    "SELECT system_id, COUNT(*) as n_preds,
       ROUND(AVG(ABS(predicted_points - current_points_line)),2) as avg_abs_diff
     FROM nba_predictions.player_prop_predictions
     WHERE game_date = CURRENT_DATE() AND is_active = TRUE AND current_points_line IS NOT NULL
     GROUP BY 1 ORDER BY 2 DESC"

  echo ""
  echo "Enabled models in registry:"
  bq query --use_legacy_sql=false --format=pretty --project_id="$PROJECT" \
    "SELECT model_id, enabled FROM nba_predictions.model_registry WHERE enabled = TRUE ORDER BY model_id"
fi

echo ""
echo "Done. Registry changes will be picked up on the next prediction request."
echo "If models still missing after verification, check:"
echo "  1. Is the model path in GCS? (bin/model-registry.sh validate)"
echo "  2. Is is_active=TRUE in model_registry? (enabled AND is_active both required)"
