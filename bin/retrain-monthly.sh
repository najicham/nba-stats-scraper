#!/bin/bash
# Monthly Model Retraining Script
#
# Automates the monthly retraining workflow:
# 1. Trains a new model on recent data
# 2. Uploads to GCS with consistent naming
# 3. Registers in model_registry table
# 4. Optionally promotes to production
#
# Usage:
#   ./bin/retrain-monthly.sh                    # Train with defaults (last 90 days)
#   ./bin/retrain-monthly.sh --promote          # Train and promote to production
#   ./bin/retrain-monthly.sh --dry-run          # Show what would happen
#   ./bin/retrain-monthly.sh --train-end 2026-02-28  # Custom end date
#
# See docs/08-projects/current/model-management/MONTHLY-RETRAINING.md for details

set -e

# Configuration
PROJECT="nba-props-platform"
REGION="us-west2"
GCS_BUCKET="gs://nba-props-platform-models"
MODEL_VERSION="v9"
FEATURE_COUNT=33
TRAINING_START="2025-11-02"  # Start of current season

# Parse arguments
DRY_RUN=false
PROMOTE=false
TRAIN_END=""
CUSTOM_NAME=""

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
        --features)
            FEATURE_COUNT="$2"
            shift 2
            ;;
        -h|--help)
            echo "Monthly Model Retraining Script"
            echo ""
            echo "Usage:"
            echo "  ./bin/retrain-monthly.sh [options]"
            echo ""
            echo "Options:"
            echo "  --dry-run         Show what would happen without executing"
            echo "  --promote         Automatically promote to production after training"
            echo "  --train-end DATE  Set training end date (default: yesterday)"
            echo "  --name NAME       Custom experiment name (default: V9_MMM_RETRAIN)"
            echo "  --features N      Feature count (default: 33)"
            echo "  -h, --help        Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./bin/retrain-monthly.sh --dry-run"
            echo "  ./bin/retrain-monthly.sh --promote"
            echo "  ./bin/retrain-monthly.sh --train-end 2026-02-28 --name V9_FEB_FINAL"
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
TRAIN_DATE=$(date +%Y%m%d)
MONTH_NAME=$(date +%b | tr '[:lower:]' '[:upper:]')

if [ -z "$TRAIN_END" ]; then
    TRAIN_END=$(date -d "yesterday" +%Y-%m-%d)
fi

if [ -z "$CUSTOM_NAME" ]; then
    EXPERIMENT_NAME="V9_${MONTH_NAME}_RETRAIN"
else
    EXPERIMENT_NAME="$CUSTOM_NAME"
fi

MODEL_ID="catboost_${MODEL_VERSION}_${FEATURE_COUNT}features_${TRAIN_DATE}"
MODEL_FILE="${MODEL_ID}.cbm"
GCS_PATH="${GCS_BUCKET}/catboost/${MODEL_VERSION}/${MODEL_FILE}"

echo "=============================================="
echo "MONTHLY MODEL RETRAINING"
echo "=============================================="
echo "Experiment Name: $EXPERIMENT_NAME"
echo "Model ID:        $MODEL_ID"
echo "Training Range:  $TRAINING_START to $TRAIN_END"
echo "Feature Count:   $FEATURE_COUNT"
echo "GCS Path:        $GCS_PATH"
echo "Promote:         $PROMOTE"
echo "=============================================="
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would execute the following steps:"
    echo ""
    echo "1. Train model:"
    echo "   PYTHONPATH=. python ml/experiments/quick_retrain.py \\"
    echo "       --name \"$EXPERIMENT_NAME\" \\"
    echo "       --train-start $TRAINING_START \\"
    echo "       --train-end $TRAIN_END"
    echo ""
    echo "2. Upload to GCS:"
    echo "   gsutil cp models/${MODEL_FILE} $GCS_PATH"
    echo ""
    echo "3. Register in model_registry:"
    echo "   INSERT INTO nba_predictions.model_registry ..."
    echo ""
    if [ "$PROMOTE" = true ]; then
        echo "4. Promote to production:"
        echo "   - Update prediction-worker env var"
        echo "   - Mark previous model as deprecated"
    fi
    exit 0
fi

# Step 1: Train the model
echo "[1/4] Training model..."
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "$EXPERIMENT_NAME" \
    --train-start "$TRAINING_START" \
    --train-end "$TRAIN_END"

# Check if model file was created
LOCAL_MODEL="models/${MODEL_FILE}"
if [ ! -f "$LOCAL_MODEL" ]; then
    # Try to find the model file with different naming
    FOUND_MODEL=$(ls -t models/*.cbm 2>/dev/null | head -1)
    if [ -n "$FOUND_MODEL" ]; then
        echo "Found model at: $FOUND_MODEL"
        LOCAL_MODEL="$FOUND_MODEL"
    else
        echo "ERROR: Model file not found after training"
        echo "Expected: $LOCAL_MODEL"
        exit 1
    fi
fi

echo "Model trained: $LOCAL_MODEL"
echo ""

# Step 2: Upload to GCS
echo "[2/4] Uploading to GCS..."
gsutil cp "$LOCAL_MODEL" "$GCS_PATH"
echo "Uploaded: $GCS_PATH"
echo ""

# Step 3: Register in model_registry
echo "[3/4] Registering in model_registry..."
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

bq query --use_legacy_sql=false "
INSERT INTO nba_predictions.model_registry (
  model_id, model_version, model_type, gcs_path, feature_count,
  features_json, training_start_date, training_end_date,
  git_commit, status, is_production,
  notes, created_at, created_by
) VALUES (
  '${MODEL_ID}',
  '${MODEL_VERSION}',
  'catboost',
  '${GCS_PATH}',
  ${FEATURE_COUNT},
  (SELECT features_json FROM nba_predictions.model_registry WHERE model_version = '${MODEL_VERSION}' AND features_json IS NOT NULL LIMIT 1),
  DATE '${TRAINING_START}',
  DATE '${TRAIN_END}',
  '${GIT_COMMIT}',
  'active',
  FALSE,
  'Monthly retrain ${MONTH_NAME} ${TODAY}. Trained by retrain-monthly.sh',
  CURRENT_TIMESTAMP(),
  'retrain-monthly'
)"

echo "Registered: $MODEL_ID"
echo ""

# Step 4: Optionally promote to production
if [ "$PROMOTE" = true ]; then
    echo "[4/4] Promoting to production..."

    # Get current production model
    CURRENT_PROD=$(bq query --use_legacy_sql=false --format=csv --quiet "
    SELECT model_id FROM nba_predictions.model_registry
    WHERE is_production = TRUE AND model_version = '${MODEL_VERSION}'
    LIMIT 1" | tail -1)

    echo "Current production model: $CURRENT_PROD"

    # Mark current as deprecated
    if [ -n "$CURRENT_PROD" ] && [ "$CURRENT_PROD" != "model_id" ]; then
        bq query --use_legacy_sql=false "
        UPDATE nba_predictions.model_registry
        SET is_production = FALSE,
            status = 'deprecated',
            production_end_date = CURRENT_DATE()
        WHERE model_id = '${CURRENT_PROD}'"
        echo "Deprecated: $CURRENT_PROD"
    fi

    # Mark new model as production
    bq query --use_legacy_sql=false "
    UPDATE nba_predictions.model_registry
    SET is_production = TRUE,
        production_start_date = CURRENT_DATE()
    WHERE model_id = '${MODEL_ID}'"
    echo "Promoted: $MODEL_ID"

    # Update Cloud Run env var
    echo ""
    echo "Updating prediction-worker env var..."
    gcloud run services update prediction-worker \
        --region="$REGION" \
        --project="$PROJECT" \
        --update-env-vars="CATBOOST_V9_MODEL_PATH=${GCS_PATH}"

    echo ""
    echo "✅ Model promoted to production!"
else
    echo "[4/4] Skipping promotion (use --promote to auto-promote)"
    echo ""
    echo "To manually promote:"
    echo "  1. Update env var:"
    echo "     gcloud run services update prediction-worker --region=$REGION \\"
    echo "       --update-env-vars=\"CATBOOST_V9_MODEL_PATH=${GCS_PATH}\""
    echo ""
    echo "  2. Mark as production in registry:"
    echo "     bq query 'UPDATE nba_predictions.model_registry SET is_production=TRUE WHERE model_id=\"${MODEL_ID}\"'"
fi

echo ""
echo "=============================================="
echo "RETRAINING COMPLETE"
echo "=============================================="
echo "Model ID:  $MODEL_ID"
echo "GCS Path:  $GCS_PATH"
echo "Status:    $([ "$PROMOTE" = true ] && echo "PRODUCTION" || echo "Ready for promotion")"
echo "=============================================="
echo ""
echo "Verify with: ./bin/model-registry.sh list"
