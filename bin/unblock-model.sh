#!/usr/bin/env bash
# Unblock a model in the registry after HR recovery, then refresh worker cache.
#
# Usage:
#   ./bin/unblock-model.sh MODEL_ID [--dry-run]
#
# When to use:
#   - Canary fires "Registry Blocked Models" or "Model Recovery Gap"
#   - After manually re-enabling a model that was blocked by decay detection
#   - After fleet reset where models were re-enabled but status stayed 'blocked'
#
# What it does:
#   1. Shows current registry state + recent performance for the model
#   2. Updates model_registry.status = 'active'
#   3. Refreshes worker model cache (new revision)
#   4. Verifies the change took effect
#
# Session 477: Standardizes the unblock procedure to prevent Error 001/003 recurrence.

set -euo pipefail

MODEL_ID="${1:-}"
DRY_RUN="${2:-}"
PROJECT_ID="nba-props-platform"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "$MODEL_ID" ]]; then
    echo "Usage: $0 MODEL_ID [--dry-run]"
    echo ""
    echo "Examples:"
    echo "  $0 catboost_v9_low_vegas_train0106_0205"
    echo "  $0 lgbm_v12_noveg_train0103_0227 --dry-run"
    echo ""
    echo "To find blocked models that need unblocking:"
    echo "  bq query --nouse_legacy_sql --project_id=$PROJECT_ID \\"
    echo "    \"SELECT model_id, status FROM nba_predictions.model_registry WHERE enabled=TRUE AND status='blocked'\""
    exit 1
fi

echo "=== Unblock Model: $MODEL_ID ==="
echo ""

# Step 1: Show current state
echo "--- Step 1: Current registry state ---"
bq query --nouse_legacy_sql --project_id="$PROJECT_ID" \
    "SELECT model_id, status, enabled, model_family, model_type
     FROM nba_predictions.model_registry
     WHERE model_id = '$MODEL_ID'"

# Step 2: Show recent performance
echo ""
echo "--- Step 2: Recent performance (last 7 days) ---"
bq query --nouse_legacy_sql --project_id="$PROJECT_ID" \
    "SELECT game_date, model_state,
       ROUND(rolling_hr_7d, 1) as hr_7d,
       ROUND(rolling_hr_14d, 1) as hr_14d,
       n_graded_7d
     FROM nba_predictions.model_performance_daily
     WHERE system_id = '$MODEL_ID'
       AND game_date >= CURRENT_DATE() - 7
     ORDER BY game_date DESC
     LIMIT 7"

if [[ "$DRY_RUN" == "--dry-run" ]]; then
    echo ""
    echo "[DRY RUN] Would UPDATE model_registry SET status='active' WHERE model_id='$MODEL_ID' AND enabled=TRUE"
    echo "[DRY RUN] Would run: ./bin/refresh-model-cache.sh --verify"
    echo ""
    echo "Run without --dry-run to execute."
    exit 0
fi

# Step 3: Unblock in registry
echo ""
echo "--- Step 3: Setting status='active' in registry ---"
bq query --nouse_legacy_sql --project_id="$PROJECT_ID" \
    "UPDATE nba_predictions.model_registry
     SET status = 'active'
     WHERE model_id = '$MODEL_ID' AND enabled = TRUE"

# Step 4: Verify registry update
echo ""
echo "--- Step 4: Verify registry update ---"
bq query --nouse_legacy_sql --project_id="$PROJECT_ID" \
    "SELECT model_id, status, enabled
     FROM nba_predictions.model_registry
     WHERE model_id = '$MODEL_ID'"

# Step 5: Refresh worker cache
echo ""
echo "--- Step 5: Refreshing worker model cache ---"
if [[ -f "$SCRIPT_DIR/refresh-model-cache.sh" ]]; then
    "$SCRIPT_DIR/refresh-model-cache.sh" --verify
else
    echo "WARNING: refresh-model-cache.sh not found. Refreshing manually..."
    gcloud run services update prediction-worker \
        --region=us-west2 \
        --project="$PROJECT_ID" \
        --update-env-vars="MODEL_CACHE_REFRESH=$(date +%Y%m%d_%H%M)"
    echo "Worker updated. New revision will serve within ~1 minute."
fi

echo ""
echo "=== Done: $MODEL_ID unblocked and worker cache refreshed ==="
echo ""
echo "Next steps:"
echo "  1. Verify model generates predictions for today:"
echo "     bq query --nouse_legacy_sql --project_id=$PROJECT_ID \\"
echo "       \"SELECT COUNT(*), ROUND(AVG(ABS(predicted_points-current_points_line)),2) as avg_abs_diff"
echo "        FROM nba_predictions.player_prop_predictions"
echo "        WHERE game_date = CURRENT_DATE() AND system_id = '$MODEL_ID'\""
echo ""
echo "  2. If BB pipeline hasn't run today, trigger it:"
echo "     gcloud pubsub topics publish nba-phase6-export-trigger \\"
echo "       --project=$PROJECT_ID \\"
echo "       --message='{\"export_types\": [\"signal-best-bets\"], \"target_date\": \"'\$(date +%Y-%m-%d)'\"}'"
