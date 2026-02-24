#!/bin/bash
# Multi-Family Model Retraining Script
#
# Automates the weekly (7-day) retraining workflow for one or all model families.
# Model families are loaded from model_registry (BQ), not hardcoded.
# Session 284: Switched to 42-day rolling window (from fixed start) and 7-day cadence.
#
# Session 273: Model Management Overhaul — multi-family support, DB-driven families.
#
# Workflow per family:
# 1. Queries model_registry for family config (feature_set, loss_function, quantile_alpha)
# 2. Trains a new model via quick_retrain.py (auto-uploads to GCS, auto-registers)
# 3. Optionally promotes to production
#
# Usage:
#   ./bin/retrain.sh                              # Train default family (v9_mae)
#   ./bin/retrain.sh --family v9_q43              # Train just Q43
#   ./bin/retrain.sh --all                        # Train all enabled families
#   ./bin/retrain.sh --all --dry-run              # Show what would happen
#   ./bin/retrain.sh --family v12_noveg_q43 --enable  # Train new V12-Q43 and enable
#   ./bin/retrain.sh --promote                    # Train default and promote
#   ./bin/retrain.sh --train-end 2026-02-28       # Custom end date
#   ./bin/retrain.sh --eval-days 14               # Custom eval window
#
# See docs/08-projects/current/model-management/ for details

set -e

# Configuration
PROJECT="nba-props-platform"
REGION="us-west2"
GCS_BUCKET="gs://nba-props-platform-models"
ROLLING_WINDOW_DAYS=42  # Rolling training window (Session 284: +$5,370 P&L vs expanding)

# Parse arguments
DRY_RUN=false
PROMOTE=false
VALIDATE_FILTERS=false
FORCE_PROMOTE=false
TRAIN_END=""
CUSTOM_NAME=""
EVAL_DAYS=7
FAMILY=""
ALL_FAMILIES=false
ENABLE_AFTER=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --promote)
            PROMOTE=true
            shift
            ;;
        --train-end)
            TRAIN_END="$2"
            shift 2
            ;;
        --name)
            CUSTOM_NAME="$2"
            shift 2
            ;;
        --eval-days)
            EVAL_DAYS="$2"
            shift 2
            ;;
        --family)
            FAMILY="$2"
            shift 2
            ;;
        --all)
            ALL_FAMILIES=true
            shift
            ;;
        --enable)
            ENABLE_AFTER=true
            shift
            ;;
        --validate-filters)
            VALIDATE_FILTERS=true
            shift
            ;;
        --force-promote)
            FORCE_PROMOTE=true
            shift
            ;;
        -h|--help)
            echo "Multi-Family Model Retraining Script"
            echo ""
            echo "Usage:"
            echo "  ./bin/retrain.sh [options]"
            echo ""
            echo "Family Selection:"
            echo "  --family FAMILY    Train a specific family (e.g., v9_mae, v9_q43, v12_noveg_mae)"
            echo "  --all              Train all enabled families from model_registry"
            echo "  (no flag)          Train default family: v9_mae"
            echo ""
            echo "Options:"
            echo "  --dry-run            Show what would happen without executing"
            echo "  --promote            Automatically promote to production after training"
            echo "  --force-promote      Promote even if champion is HEALTHY/WATCH"
            echo "  --validate-filters   Run filter validation queries after training"
            echo "  --train-end DATE     Set training end date (default: yesterday)"
            echo "  --name NAME          Custom experiment name (default: auto-generated)"
            echo "  --eval-days N        Evaluation window in days (default: 7)"
            echo "  --enable             Set enabled=TRUE on the new model after training"
            echo "  -h, --help           Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./bin/retrain.sh --all --dry-run"
            echo "  ./bin/retrain.sh --family v9_q43 --train-end 2026-02-15"
            echo "  ./bin/retrain.sh --family v12_noveg_q43 --enable"
            echo "  ./bin/retrain.sh --promote --eval-days 14"
            echo ""
            echo "Model families are read from model_registry (BQ)."
            echo "Naming convention: {feature_set}_{loss} — e.g., v9_mae, v9_q43, v12_noveg_mae"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Calculate dates
TODAY=$(date +%Y-%m-%d)
MONTH_NAME=$(date +%b | tr '[:lower:]' '[:upper:]')

if [ -z "$TRAIN_END" ]; then
    TRAIN_END=$(date -d "yesterday" +%Y-%m-%d)
fi

# Rolling training window: TRAIN_END - ROLLING_WINDOW_DAYS
# Session 284: 42-day rolling beats expanding window by +$5,370 P&L
TRAINING_START=$(date -d "$TRAIN_END - $ROLLING_WINDOW_DAYS days" +%Y-%m-%d)

# ============================================================================
# Query model_registry for family configurations
# ============================================================================
get_families() {
    # Returns: model_family, feature_set, loss_function, quantile_alpha (tab-separated)
    bq query --use_legacy_sql=false --format=csv --quiet "
    SELECT DISTINCT
        model_family,
        feature_set,
        loss_function,
        CAST(quantile_alpha AS STRING) as quantile_alpha
    FROM \`${PROJECT}.nba_predictions.model_registry\`
    WHERE enabled = TRUE AND status IN ('active', 'production')
      AND model_family IS NOT NULL
    ORDER BY model_family
    " 2>/dev/null | tail -n +2  # Skip header
}

# Build the list of families to train
declare -a FAMILIES_TO_TRAIN
declare -A FAMILY_FEATURE_SET
declare -A FAMILY_LOSS_FUNCTION
declare -A FAMILY_QUANTILE_ALPHA

if [ "$ALL_FAMILIES" = true ]; then
    echo "Querying model_registry for enabled families..."
    while IFS=',' read -r fam fs lf qa; do
        if [ -n "$fam" ] && [ "$fam" != "model_family" ]; then
            FAMILIES_TO_TRAIN+=("$fam")
            FAMILY_FEATURE_SET["$fam"]="$fs"
            FAMILY_LOSS_FUNCTION["$fam"]="$lf"
            FAMILY_QUANTILE_ALPHA["$fam"]="$qa"
        fi
    done < <(get_families)

    if [ ${#FAMILIES_TO_TRAIN[@]} -eq 0 ]; then
        echo "ERROR: No enabled families found in model_registry."
        echo "Ensure model_family is populated. Run: bin/migrations/001_enrich_model_registry.sql"
        exit 1
    fi
    echo "Found ${#FAMILIES_TO_TRAIN[@]} families: ${FAMILIES_TO_TRAIN[*]}"
elif [ -n "$FAMILY" ]; then
    # Single family specified — look up its config
    echo "Querying model_registry for family '$FAMILY'..."
    FOUND=false
    while IFS=',' read -r fam fs lf qa; do
        if [ "$fam" = "$FAMILY" ]; then
            FAMILIES_TO_TRAIN+=("$fam")
            FAMILY_FEATURE_SET["$fam"]="$fs"
            FAMILY_LOSS_FUNCTION["$fam"]="$lf"
            FAMILY_QUANTILE_ALPHA["$fam"]="$qa"
            FOUND=true
        fi
    done < <(get_families)

    if [ "$FOUND" = false ]; then
        echo "WARNING: Family '$FAMILY' not found in registry. Using defaults."
        FAMILIES_TO_TRAIN+=("$FAMILY")
        # Parse family name to derive feature_set and loss
        if [[ "$FAMILY" == *"_q"* ]]; then
            # Extract quantile alpha from family name (e.g., v9_q43 -> 0.43)
            ALPHA_SHORT="${FAMILY##*_q}"
            ALPHA="0.${ALPHA_SHORT}"
            FS="${FAMILY%%_q*}"
            FAMILY_FEATURE_SET["$FAMILY"]="$FS"
            FAMILY_LOSS_FUNCTION["$FAMILY"]="Quantile:alpha=${ALPHA}"
            FAMILY_QUANTILE_ALPHA["$FAMILY"]="$ALPHA"
        else
            FS="${FAMILY%%_mae}"
            FS="${FS%%_rmse}"
            FAMILY_FEATURE_SET["$FAMILY"]="$FS"
            FAMILY_LOSS_FUNCTION["$FAMILY"]="MAE"
            FAMILY_QUANTILE_ALPHA["$FAMILY"]=""
        fi
    fi
else
    # Default: v9_mae
    FAMILIES_TO_TRAIN+=("v9_mae")
    FAMILY_FEATURE_SET["v9_mae"]="v9"
    FAMILY_LOSS_FUNCTION["v9_mae"]="MAE"
    FAMILY_QUANTILE_ALPHA["v9_mae"]=""
fi

echo ""
echo "=============================================="
echo "MULTI-FAMILY MODEL RETRAINING"
echo "=============================================="
echo "Families:        ${FAMILIES_TO_TRAIN[*]}"
echo "Training Range:  $TRAINING_START to $TRAIN_END"
echo "Eval Days:       $EVAL_DAYS"
echo "Promote:         $PROMOTE"
echo "Enable After:    $ENABLE_AFTER"
echo "=============================================="
echo ""

# ============================================================================
# Train each family
# ============================================================================
TRAINED_MODELS=()
FAILED_FAMILIES=()

for FAMILY_NAME in "${FAMILIES_TO_TRAIN[@]}"; do
    FS="${FAMILY_FEATURE_SET[$FAMILY_NAME]}"
    LF="${FAMILY_LOSS_FUNCTION[$FAMILY_NAME]}"
    QA="${FAMILY_QUANTILE_ALPHA[$FAMILY_NAME]}"

    # Derive quick_retrain.py arguments from family config
    RETRAIN_ARGS=""

    # Feature set (strip _noveg suffix — quick_retrain uses --no-vegas flag separately)
    BASE_FS="${FS%%_noveg}"
    RETRAIN_ARGS="$RETRAIN_ARGS --feature-set $BASE_FS"

    # No-vegas flag
    if [[ "$FS" == *"_noveg"* ]] || [[ "$FS" == *"noveg"* ]]; then
        RETRAIN_ARGS="$RETRAIN_ARGS --no-vegas"
    fi

    # Quantile alpha
    if [ -n "$QA" ] && [ "$QA" != "null" ] && [ "$QA" != "NULL" ]; then
        RETRAIN_ARGS="$RETRAIN_ARGS --quantile-alpha $QA"
    fi

    # Experiment name
    if [ -n "$CUSTOM_NAME" ]; then
        EXP_NAME="${CUSTOM_NAME}_${FAMILY_NAME}"
    else
        EXP_NAME="${FAMILY_NAME^^}_${MONTH_NAME}_RETRAIN"
    fi

    echo "----------------------------------------------"
    echo "FAMILY: $FAMILY_NAME"
    echo "  Feature Set:    $FS"
    echo "  Loss Function:  $LF"
    echo "  Quantile Alpha: ${QA:-N/A}"
    echo "  Experiment:     $EXP_NAME"
    echo "  Args:           $RETRAIN_ARGS"
    echo "----------------------------------------------"

    if [ "$DRY_RUN" = true ]; then
        echo "[DRY RUN] Would execute:"
        echo "  PYTHONPATH=. python ml/experiments/quick_retrain.py \\"
        echo "      --name \"$EXP_NAME\" \\"
        echo "      --train-start $TRAINING_START \\"
        echo "      --train-end $TRAIN_END \\"
        echo "      --eval-days $EVAL_DAYS \\"
        echo "      $RETRAIN_ARGS"
        echo ""
        continue
    fi

    # Train the model
    # Pass --enable to quick_retrain.py so it registers with enabled=TRUE directly
    # This avoids the BQ streaming buffer issue where UPDATE fails for ~30 min
    ENABLE_ARG=""
    if [ "$ENABLE_AFTER" = true ]; then
        ENABLE_ARG="--enable"
    fi

    echo ""
    echo "Training $FAMILY_NAME..."
    if PYTHONPATH=. python ml/experiments/quick_retrain.py \
        --name "$EXP_NAME" \
        --train-start "$TRAINING_START" \
        --train-end "$TRAIN_END" \
        --eval-days "$EVAL_DAYS" \
        --force \
        $ENABLE_ARG \
        $RETRAIN_ARGS; then

        echo "$FAMILY_NAME: Training complete"
        TRAINED_MODELS+=("$FAMILY_NAME")
    else
        echo "WARNING: $FAMILY_NAME training failed!"
        FAILED_FAMILIES+=("$FAMILY_NAME")
    fi

    echo ""
done

if [ "$DRY_RUN" = true ]; then
    echo "=============================================="
    echo "DRY RUN COMPLETE"
    echo "=============================================="
    exit 0
fi

# ============================================================================
# Update subset definitions (Session 311B)
# After training, update dynamic_subset_definitions to point to the new
# model's system_id. This prevents definition staleness at the source.
# The SubsetMaterializer also has runtime resolution as a safety net.
# ============================================================================
for FAMILY_NAME in "${TRAINED_MODELS[@]}"; do
    # Get the new model's system_id (= model_id in registry)
    NEW_SYSTEM_ID=$(bq query --use_legacy_sql=false --format=csv --quiet \
        --project_id="$PROJECT" "
    SELECT model_id FROM \`${PROJECT}.nba_predictions.model_registry\`
    WHERE model_family = '$FAMILY_NAME' AND status IN ('active', 'production')
    ORDER BY created_at DESC, model_id DESC LIMIT 1" | tail -1)

    if [ -z "$NEW_SYSTEM_ID" ] || [ "$NEW_SYSTEM_ID" = "model_id" ]; then
        echo "  Subset definitions: skipped for $FAMILY_NAME (no model_id found)"
        continue
    fi

    # Build the LIKE pattern for this family's old system_ids
    case "$FAMILY_NAME" in
        v9_mae)
            # Champion uses exact 'catboost_v9' — definitions don't go stale
            echo "  Subset definitions: skipped for v9_mae (champion uses fixed system_id)"
            continue
            ;;
        v9_q43)  PATTERN="catboost_v9_q43_%" ;;
        v9_q45)  PATTERN="catboost_v9_q45_%" ;;
        v9_low_vegas)  PATTERN="catboost_v9_low_vegas_%" ;;
        v12_mae|v12_noveg_mae)  PATTERN="catboost_v12_noveg_train%" ;;
        v12_q43|v12_noveg_q43)  PATTERN="catboost_v12_noveg_q43_%" ;;
        v12_q45|v12_noveg_q45)  PATTERN="catboost_v12_noveg_q45_%" ;;
        *)
            echo "  Subset definitions: skipped for $FAMILY_NAME (unknown pattern)"
            continue
            ;;
    esac

    # Count affected definitions
    AFFECTED=$(bq query --use_legacy_sql=false --format=csv --quiet \
        --project_id="$PROJECT" "
    SELECT COUNT(*) FROM \`${PROJECT}.nba_predictions.dynamic_subset_definitions\`
    WHERE system_id LIKE '$PATTERN' AND system_id != '$NEW_SYSTEM_ID' AND is_active = TRUE" | tail -1)

    if [ "$AFFECTED" = "0" ] || [ -z "$AFFECTED" ]; then
        echo "  Subset definitions: $FAMILY_NAME already up-to-date ($NEW_SYSTEM_ID)"
        continue
    fi

    # Update definitions
    bq query --use_legacy_sql=false --project_id="$PROJECT" "
    UPDATE \`${PROJECT}.nba_predictions.dynamic_subset_definitions\`
    SET system_id = '$NEW_SYSTEM_ID'
    WHERE system_id LIKE '$PATTERN' AND system_id != '$NEW_SYSTEM_ID' AND is_active = TRUE"

    echo "  Subset definitions: updated $AFFECTED rows for $FAMILY_NAME → $NEW_SYSTEM_ID"
done

# ============================================================================
# Post-Retrain Registry Validation (Session 335)
# Automatically checks registry consistency after training. Skips GCS checks
# (slow, and the model was just uploaded).
# ============================================================================
if [ ${#TRAINED_MODELS[@]} -gt 0 ]; then
    echo ""
    echo "=============================================="
    echo "POST-RETRAIN REGISTRY VALIDATION"
    echo "=============================================="
    python bin/validation/validate_model_registry.py --skip-gcs
    if [ $? -ne 0 ]; then
        echo "WARNING: Registry validation found issues. Review above output."
    fi
fi

# ============================================================================
# Filter Validation (Session 311)
# Checks model-specific negative filters against the new model's eval window.
# Filters are INHERITED — never auto-removed. Report flags issues for review.
# ============================================================================
if [ "$VALIDATE_FILTERS" = true ] && [ ${#TRAINED_MODELS[@]} -gt 0 ]; then
    echo ""
    echo "=============================================="
    echo "FILTER VALIDATION REPORT"
    echo "=============================================="

    EVAL_START=$(date -d "$TRAIN_END + 1 day" +%Y-%m-%d)
    EVAL_END=$(date -d "$TRAIN_END + $EVAL_DAYS days" +%Y-%m-%d)

    # Get the latest trained model's system_id
    FIRST_FAMILY="${TRAINED_MODELS[0]}"
    NEW_MODEL_ID=$(bq query --use_legacy_sql=false --format=csv --quiet \
        --project_id="$PROJECT" "
    SELECT model_id FROM \`${PROJECT}.nba_predictions.model_registry\`
    WHERE model_family = '$FIRST_FAMILY' AND status = 'active'
    ORDER BY created_at DESC, model_id DESC LIMIT 1" | tail -1)

    echo "Model:       $NEW_MODEL_ID"
    echo "Eval Window: $EVAL_START to $EVAL_END"
    echo "Breakeven:   52.4%"
    echo "----------------------------------------------"

    BREAKEVEN=52.4

    # Filter 1: UNDER edge 7+ block (MODEL-SPECIFIC)
    UNDER7_HR=$(bq query --use_legacy_sql=false --format=csv --quiet \
        --project_id="$PROJECT" "
    SELECT ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNT(*), 0), 1)
    FROM \`${PROJECT}.nba_predictions.prediction_accuracy\`
    WHERE system_id = '$NEW_MODEL_ID'
      AND recommendation = 'UNDER'
      AND ABS(predicted_points - line_value) >= 7
      AND game_date BETWEEN '$EVAL_START' AND '$EVAL_END'
      AND prediction_correct IS NOT NULL
      AND is_voided IS NOT TRUE" | tail -1)

    UNDER7_N=$(bq query --use_legacy_sql=false --format=csv --quiet \
        --project_id="$PROJECT" "
    SELECT COUNT(*)
    FROM \`${PROJECT}.nba_predictions.prediction_accuracy\`
    WHERE system_id = '$NEW_MODEL_ID'
      AND recommendation = 'UNDER'
      AND ABS(predicted_points - line_value) >= 7
      AND game_date BETWEEN '$EVAL_START' AND '$EVAL_END'
      AND prediction_correct IS NOT NULL
      AND is_voided IS NOT TRUE" | tail -1)

    if [ "$UNDER7_HR" = "null" ] || [ -z "$UNDER7_HR" ]; then
        echo "  UNDER edge 7+ block:    N/A (no data in eval window)"
    elif (( $(echo "$UNDER7_HR > $BREAKEVEN" | bc -l 2>/dev/null || echo 0) )); then
        echo "  UNDER edge 7+ block:    REVIEW_NEEDED — HR=${UNDER7_HR}% > ${BREAKEVEN}% (N=${UNDER7_N})"
    else
        echo "  UNDER edge 7+ block:    CONFIRMED — HR=${UNDER7_HR}% <= ${BREAKEVEN}% (N=${UNDER7_N})"
    fi

    # Filter 2: Feature quality floor (MODEL-SPECIFIC)
    LOWQ_HR=$(bq query --use_legacy_sql=false --format=csv --quiet \
        --project_id="$PROJECT" "
    SELECT ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNT(*), 0), 1)
    FROM \`${PROJECT}.nba_predictions.prediction_accuracy\` pa
    JOIN \`${PROJECT}.nba_predictions.player_prop_predictions\` pp
      ON pa.player_lookup = pp.player_lookup AND pa.game_id = pp.game_id
         AND pa.system_id = pp.system_id
    WHERE pa.system_id = '$NEW_MODEL_ID'
      AND COALESCE(pp.feature_quality_score, 0) < 85
      AND pa.game_date BETWEEN '$EVAL_START' AND '$EVAL_END'
      AND pa.prediction_correct IS NOT NULL
      AND pa.is_voided IS NOT TRUE" | tail -1)

    LOWQ_N=$(bq query --use_legacy_sql=false --format=csv --quiet \
        --project_id="$PROJECT" "
    SELECT COUNT(*)
    FROM \`${PROJECT}.nba_predictions.prediction_accuracy\` pa
    JOIN \`${PROJECT}.nba_predictions.player_prop_predictions\` pp
      ON pa.player_lookup = pp.player_lookup AND pa.game_id = pp.game_id
         AND pa.system_id = pp.system_id
    WHERE pa.system_id = '$NEW_MODEL_ID'
      AND COALESCE(pp.feature_quality_score, 0) < 85
      AND pa.game_date BETWEEN '$EVAL_START' AND '$EVAL_END'
      AND pa.prediction_correct IS NOT NULL
      AND pa.is_voided IS NOT TRUE" | tail -1)

    if [ "$LOWQ_HR" = "null" ] || [ -z "$LOWQ_HR" ]; then
        echo "  Quality < 85 block:     N/A (no data in eval window)"
    elif (( $(echo "$LOWQ_HR > $BREAKEVEN" | bc -l 2>/dev/null || echo 0) )); then
        echo "  Quality < 85 block:     REVIEW_NEEDED — HR=${LOWQ_HR}% > ${BREAKEVEN}% (N=${LOWQ_N})"
    else
        echo "  Quality < 85 block:     CONFIRMED — HR=${LOWQ_HR}% <= ${BREAKEVEN}% (N=${LOWQ_N})"
    fi

    # Market-structural filters (always inherit, no validation needed)
    echo ""
    echo "Market-structural filters (always inherited):"
    echo "  Edge floor (5.0):       INHERITED (market-structural)"
    echo "  Line movement blocks:   INHERITED (market-structural)"
    echo "  Bench UNDER block:      INHERITED (market-structural)"
    echo "  Avoid familiar (6+):    INHERITED (market-structural)"
    echo "  Player blacklist:       AUTO-RECOMPUTES (from grading data)"
    echo "----------------------------------------------"
    echo "NOTE: REVIEW_NEEDED does NOT mean remove the filter."
    echo "      It means the pattern may not hold for this model — investigate manually."
    echo ""
fi

# ============================================================================
# Promotion (only for single-family, non-quantile models)
# Session 311: Decay-gated promotion — checks champion's decay state before
# promoting. If champion is HEALTHY/WATCH, promotes immediately. If
# DEGRADING/BLOCKED, also promotes immediately (urgency). This ensures we
# never shadow when the current model is failing.
# ============================================================================
if [ "$PROMOTE" = true ] && [ ${#FAMILIES_TO_TRAIN[@]} -eq 1 ]; then
    FAMILY_NAME="${FAMILIES_TO_TRAIN[0]}"
    QA="${FAMILY_QUANTILE_ALPHA[$FAMILY_NAME]}"

    if [ -n "$QA" ] && [ "$QA" != "null" ]; then
        echo "Skipping promotion for quantile model (shadow-only)"
    else
        # Check champion's current decay state
        echo ""
        echo "Checking champion model decay state..."
        CHAMPION_STATE=$(bq query --use_legacy_sql=false --format=csv --quiet \
            --project_id="$PROJECT" "
        SELECT COALESCE(state, 'UNKNOWN')
        FROM \`${PROJECT}.nba_predictions.model_performance_daily\`
        WHERE game_date = (
            SELECT MAX(game_date) FROM \`${PROJECT}.nba_predictions.model_performance_daily\`
        )
        AND model_id = 'catboost_v9'
        LIMIT 1" | tail -1)

        CHAMPION_HR=$(bq query --use_legacy_sql=false --format=csv --quiet \
            --project_id="$PROJECT" "
        SELECT COALESCE(CAST(rolling_hr_7d AS STRING), 'N/A')
        FROM \`${PROJECT}.nba_predictions.model_performance_daily\`
        WHERE game_date = (
            SELECT MAX(game_date) FROM \`${PROJECT}.nba_predictions.model_performance_daily\`
        )
        AND model_id = 'catboost_v9'
        LIMIT 1" | tail -1)

        # Default to UNKNOWN if no data
        if [ -z "$CHAMPION_STATE" ] || [ "$CHAMPION_STATE" = "state" ]; then
            CHAMPION_STATE="UNKNOWN"
        fi

        echo "Champion state: $CHAMPION_STATE (7d HR: ${CHAMPION_HR}%)"

        PROCEED_WITH_PROMOTION=true
        case "$CHAMPION_STATE" in
            BLOCKED|DEGRADING)
                echo "Champion is $CHAMPION_STATE — URGENT promotion recommended"
                echo "Proceeding with immediate promotion..."
                ;;
            HEALTHY|WATCH)
                echo "Champion is $CHAMPION_STATE — standard promotion"
                ;;
            INSUFFICIENT_DATA|UNKNOWN)
                echo "Champion state unknown (insufficient data) — proceeding with promotion"
                ;;
            *)
                echo "WARNING: Unexpected champion state: $CHAMPION_STATE"
                echo "Proceeding with promotion..."
                ;;
        esac

        if [ "$PROCEED_WITH_PROMOTION" = true ]; then
            echo "Promoting latest $FAMILY_NAME model to production..."

            # Get the latest model_id for this family
            LATEST_MODEL=$(bq query --use_legacy_sql=false --format=csv --quiet \
                --project_id="$PROJECT" "
            SELECT model_id FROM \`${PROJECT}.nba_predictions.model_registry\`
            WHERE model_family = '$FAMILY_NAME' AND status = 'active'
            ORDER BY created_at DESC, model_id DESC LIMIT 1" | tail -1)

            LATEST_GCS=$(bq query --use_legacy_sql=false --format=csv --quiet \
                --project_id="$PROJECT" "
            SELECT gcs_path FROM \`${PROJECT}.nba_predictions.model_registry\`
            WHERE model_id = '$LATEST_MODEL'" | tail -1)

            if [ -n "$LATEST_MODEL" ] && [ "$LATEST_MODEL" != "model_id" ]; then
                # Deprecate current production
                CURRENT_PROD=$(bq query --use_legacy_sql=false --format=csv --quiet \
                    --project_id="$PROJECT" "
                SELECT model_id FROM \`${PROJECT}.nba_predictions.model_registry\`
                WHERE is_production = TRUE AND model_version = 'v9'
                LIMIT 1" | tail -1)

                if [ -n "$CURRENT_PROD" ] && [ "$CURRENT_PROD" != "model_id" ]; then
                    bq query --use_legacy_sql=false --project_id="$PROJECT" "
                    UPDATE \`${PROJECT}.nba_predictions.model_registry\`
                    SET is_production = FALSE, status = 'deprecated',
                        production_end_date = CURRENT_DATE()
                    WHERE model_id = '$CURRENT_PROD'"
                    echo "Deprecated: $CURRENT_PROD"
                fi

                # Promote new model
                bq query --use_legacy_sql=false --project_id="$PROJECT" "
                UPDATE \`${PROJECT}.nba_predictions.model_registry\`
                SET is_production = TRUE, enabled = TRUE,
                    production_start_date = CURRENT_DATE()
                WHERE model_id = '$LATEST_MODEL'"
                echo "Promoted: $LATEST_MODEL"

                # Update Cloud Run env var
                echo "Updating prediction-worker env var..."
                gcloud run services update prediction-worker \
                    --region="$REGION" \
                    --project="$PROJECT" \
                    --update-env-vars="CATBOOST_V9_MODEL_PATH=${LATEST_GCS}"
                echo "Model promoted to production!"
            else
                echo "ERROR: Could not find latest model for family $FAMILY_NAME"
            fi
        fi
    fi
elif [ "$PROMOTE" = true ]; then
    echo "Skipping promotion (--promote with --all not supported, promote one family at a time)"
fi

# ============================================================================
# Summary
# ============================================================================
echo ""
echo "=============================================="
echo "RETRAINING COMPLETE"
echo "=============================================="
echo "Trained:  ${TRAINED_MODELS[*]:-none}"
echo "Failed:   ${FAILED_FAMILIES[*]:-none}"
echo "=============================================="
echo ""
echo "Post-retrain verification:"
echo "  ./bin/model-registry.sh list                    # Verify registry"
echo "  ./bin/model-registry.sh validate                # Check GCS + SHA256"
echo "  ./bin/check-deployment-drift.sh --verbose       # Verify deployment"
echo ""
echo "To enable a newly trained model:"
echo "  bq query 'UPDATE nba_predictions.model_registry SET enabled=TRUE WHERE model_id=\"MODEL_ID\"'"
echo ""
