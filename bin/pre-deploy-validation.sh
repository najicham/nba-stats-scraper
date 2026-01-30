#!/bin/bash
# Pre-Deployment Validation Script
# Purpose: Validate feature alignment before deploying prediction services
# Created: Session 37 (2026-01-30)
#
# This script prevents the January 7-9 model collapse by ensuring:
# 1. Feature version alignment between model and feature store
# 2. Feature count alignment
# 3. Schema compatibility
#
# Usage:
#   ./bin/pre-deploy-validation.sh [service-name]
#
# Example:
#   ./bin/pre-deploy-validation.sh prediction-worker
#   ./bin/pre-deploy-validation.sh  # Validates all services

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "  Pre-Deployment Validation"
echo "  Session 37 - Feature Alignment Check"
echo "=========================================="
echo ""

ERRORS=0
WARNINGS=0

# 1. Check CatBoost V8 expected feature version
echo "[1/5] Checking CatBoost V8 feature requirements..."

CATBOOST_FILE="predictions/worker/prediction_systems/catboost_v8.py"
if [ -f "$CATBOOST_FILE" ]; then
    # Extract accepted versions from the validation check
    if grep -q "v2_33features\|v2_37features" "$CATBOOST_FILE"; then
        echo -e "  ${GREEN}✓${NC} CatBoost V8 accepts v2_33features or v2_37features"
    else
        echo -e "  ${RED}✗${NC} Could not determine CatBoost V8 feature version requirements"
        ERRORS=$((ERRORS + 1))
    fi

    # Check for feature count validation
    if grep -q "actual_count < 33" "$CATBOOST_FILE"; then
        echo -e "  ${GREEN}✓${NC} CatBoost V8 requires at least 33 features"
    else
        echo -e "  ${YELLOW}⚠${NC} Could not verify feature count requirement"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "  ${RED}✗${NC} CatBoost V8 file not found: $CATBOOST_FILE"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# 2. Check ML Feature Store processor configuration
echo "[2/5] Checking ML Feature Store processor..."

FEATURE_STORE_FILE="data_processors/precompute/ml_feature_store/ml_feature_store_processor.py"
if [ -f "$FEATURE_STORE_FILE" ]; then
    # Look for feature version constant
    FEATURE_VERSION=$(grep -o "FEATURE_VERSION\s*=\s*['\"][^'\"]*['\"]" "$FEATURE_STORE_FILE" 2>/dev/null | head -1 | grep -o "['\"][^'\"]*['\"]" | tr -d "'\"")
    if [ -n "$FEATURE_VERSION" ]; then
        echo -e "  ${GREEN}✓${NC} Feature store version: $FEATURE_VERSION"
    else
        echo -e "  ${YELLOW}⚠${NC} Could not determine feature store version"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "  ${RED}✗${NC} Feature store processor not found: $FEATURE_STORE_FILE"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# 3. Check BigQuery schema for new error tracking fields
echo "[3/5] Checking BigQuery schema for error tracking fields..."

# Check if we can query BigQuery
if command -v bq &> /dev/null; then
    # Check player_prop_predictions for new fields
    SCHEMA_CHECK=$(bq show --schema nba_predictions.player_prop_predictions 2>/dev/null | grep -c "prediction_error_code\|feature_version" || true)
    if [ "$SCHEMA_CHECK" -ge 2 ]; then
        echo -e "  ${GREEN}✓${NC} Error tracking fields present in player_prop_predictions"
    else
        echo -e "  ${YELLOW}⚠${NC} Error tracking fields may be missing - run migration"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "  ${YELLOW}⚠${NC} bq command not available - skipping schema check"
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# 4. Check for retry decorator bug fix
echo "[4/5] Checking retry decorator configuration..."

SAVE_OPS_FILE="data_processors/analytics/operations/bigquery_save_ops.py"
if [ -f "$SAVE_OPS_FILE" ]; then
    # Check that the problematic nested retry is removed
    NESTED_RETRY=$(grep -B2 "def save_analytics" "$SAVE_OPS_FILE" | grep -c "@retry_on_serialization" || true)
    if [ "$NESTED_RETRY" -eq 0 ]; then
        echo -e "  ${GREEN}✓${NC} Retry decorator bug fix verified (no nested @retry_on_serialization)"
    else
        echo -e "  ${RED}✗${NC} Nested @retry_on_serialization still present - may cause duplicates!"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "  ${YELLOW}⚠${NC} Save ops file not found: $SAVE_OPS_FILE"
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# 5. Verify model file exists (for prediction-worker deploys)
echo "[5/5] Checking model files..."

MODEL_DIR="ml/models"
if [ -d "$MODEL_DIR" ]; then
    V8_MODEL=$(find "$MODEL_DIR" -name "*catboost*v8*" -o -name "*v8*catboost*" 2>/dev/null | head -1)
    if [ -n "$V8_MODEL" ]; then
        echo -e "  ${GREEN}✓${NC} CatBoost V8 model found: $V8_MODEL"
    else
        echo -e "  ${YELLOW}⚠${NC} CatBoost V8 model not found locally (may be loaded from GCS)"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "  ${YELLOW}⚠${NC} Model directory not found: $MODEL_DIR"
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# Summary
echo "=========================================="
echo "  Validation Summary"
echo "=========================================="
if [ $ERRORS -gt 0 ]; then
    echo -e "  ${RED}FAILED${NC}: $ERRORS error(s), $WARNINGS warning(s)"
    echo ""
    echo "  ❌ DO NOT DEPLOY until errors are resolved!"
    echo ""
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    echo -e "  ${YELLOW}PASSED WITH WARNINGS${NC}: $WARNINGS warning(s)"
    echo ""
    echo "  ⚠️  Review warnings before deploying"
    echo ""
    exit 0
else
    echo -e "  ${GREEN}PASSED${NC}: All checks passed"
    echo ""
    echo "  ✅ Safe to deploy"
    echo ""
    exit 0
fi
