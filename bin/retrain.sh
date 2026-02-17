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
            echo "  --dry-run          Show what would happen without executing"
            echo "  --promote          Automatically promote to production after training"
            echo "  --train-end DATE   Set training end date (default: yesterday)"
            echo "  --name NAME        Custom experiment name (default: auto-generated)"
            echo "  --eval-days N      Evaluation window in days (default: 7)"
            echo "  --enable           Set enabled=TRUE on the new model after training"
            echo "  -h, --help         Show this help message"
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
# Promotion (only for single-family, non-quantile models)
# ============================================================================
if [ "$PROMOTE" = true ] && [ ${#FAMILIES_TO_TRAIN[@]} -eq 1 ]; then
    FAMILY_NAME="${FAMILIES_TO_TRAIN[0]}"
    QA="${FAMILY_QUANTILE_ALPHA[$FAMILY_NAME]}"

    if [ -n "$QA" ] && [ "$QA" != "null" ]; then
        echo "Skipping promotion for quantile model (shadow-only)"
    else
        echo "Promoting latest $FAMILY_NAME model to production..."

        # Get the latest model_id for this family
        LATEST_MODEL=$(bq query --use_legacy_sql=false --format=csv --quiet "
        SELECT model_id FROM \`${PROJECT}.nba_predictions.model_registry\`
        WHERE model_family = '$FAMILY_NAME' AND status = 'active'
        ORDER BY created_at DESC LIMIT 1" | tail -1)

        LATEST_GCS=$(bq query --use_legacy_sql=false --format=csv --quiet "
        SELECT gcs_path FROM \`${PROJECT}.nba_predictions.model_registry\`
        WHERE model_id = '$LATEST_MODEL'" | tail -1)

        if [ -n "$LATEST_MODEL" ] && [ "$LATEST_MODEL" != "model_id" ]; then
            # Deprecate current production
            CURRENT_PROD=$(bq query --use_legacy_sql=false --format=csv --quiet "
            SELECT model_id FROM \`${PROJECT}.nba_predictions.model_registry\`
            WHERE is_production = TRUE AND model_version = 'v9'
            LIMIT 1" | tail -1)

            if [ -n "$CURRENT_PROD" ] && [ "$CURRENT_PROD" != "model_id" ]; then
                bq query --use_legacy_sql=false "
                UPDATE \`${PROJECT}.nba_predictions.model_registry\`
                SET is_production = FALSE, status = 'deprecated',
                    production_end_date = CURRENT_DATE()
                WHERE model_id = '$CURRENT_PROD'"
                echo "Deprecated: $CURRENT_PROD"
            fi

            # Promote new model
            bq query --use_legacy_sql=false "
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
