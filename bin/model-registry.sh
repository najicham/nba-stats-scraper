#!/bin/bash
# Model Registry CLI - Query and manage ML models (Session 163: added SHA256 verification)
#
# Usage:
#   ./bin/model-registry.sh list              # List all models
#   ./bin/model-registry.sh production        # Show production models
#   ./bin/model-registry.sh info <model_id>   # Get model details
#   ./bin/model-registry.sh features <model_id>  # Get feature list
#   ./bin/model-registry.sh validate          # Validate GCS paths + SHA256 integrity
#   ./bin/model-registry.sh manifest          # Show GCS manifest (source of truth)

set -e

COMMAND=${1:-list}
MODEL_ID=$2

case $COMMAND in
  list)
    echo "=== All Registered Models ==="
    bq query --use_legacy_sql=false --format=pretty "
    SELECT
      model_id,
      model_version,
      feature_count,
      training_start_date,
      training_end_date,
      CASE WHEN is_production THEN 'PROD' ELSE '' END as prod,
      status,
      SUBSTR(COALESCE(sha256_hash, ''), 1, 12) as sha256_prefix
    FROM nba_predictions.model_registry
    ORDER BY model_version DESC, created_at DESC"
    ;;

  production)
    echo "=== Production Models ==="
    bq query --use_legacy_sql=false "
    SELECT
      model_id,
      model_version,
      feature_count,
      gcs_path,
      evaluation_hit_rate_edge_5plus as hit_rate_5plus,
      production_start_date
    FROM nba_predictions.model_registry
    WHERE is_production = TRUE
    ORDER BY production_start_date DESC"
    ;;

  info)
    if [ -z "$MODEL_ID" ]; then
      echo "Usage: ./bin/model-registry.sh info <model_id>"
      exit 1
    fi
    echo "=== Model Details: $MODEL_ID ==="
    bq query --use_legacy_sql=false "
    SELECT *
    FROM nba_predictions.model_registry
    WHERE model_id = '$MODEL_ID'"
    ;;

  features)
    if [ -z "$MODEL_ID" ]; then
      echo "Usage: ./bin/model-registry.sh features <model_id>"
      exit 1
    fi
    echo "=== Features for: $MODEL_ID ==="
    bq query --use_legacy_sql=false --format=json "
    SELECT
      model_id,
      feature_count,
      TO_JSON_STRING(features_json) as features_json
    FROM nba_predictions.model_registry
    WHERE model_id = '$MODEL_ID'" 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    if data:
        features = json.loads(data[0]['features_json'])
        print(f'Feature count: {data[0][\"feature_count\"]}')
        print('')
        for i, f in enumerate(features):
            print(f'  [{i:2d}] {f}')
    else:
        print('Model not found')
except Exception as e:
    print(f'Error parsing features: {e}')
"
    ;;

  validate)
    echo "=== Validating GCS Paths + SHA256 Integrity ==="
    MODELS=$(bq query --use_legacy_sql=false --format=csv --quiet "
    SELECT model_id, gcs_path, sha256_hash
    FROM nba_predictions.model_registry
    WHERE status IN ('active', 'production')" | tail -n +2)

    ERRORS=0
    while IFS=, read -r model_id gcs_path sha256_expected; do
      if gsutil -q stat "$gcs_path" 2>/dev/null; then
        if [ -n "$sha256_expected" ]; then
          # Download and verify SHA256
          TMP_FILE="/tmp/model_validate_$(basename "$gcs_path")"
          gsutil -q cp "$gcs_path" "$TMP_FILE" 2>/dev/null
          ACTUAL_SHA=$(sha256sum "$TMP_FILE" | cut -c1-16)
          rm -f "$TMP_FILE"
          if [ "$ACTUAL_SHA" = "$sha256_expected" ]; then
            echo "OK $model_id (SHA256 verified)"
          else
            echo "FAIL $model_id - SHA256 MISMATCH! Expected=$sha256_expected Actual=$ACTUAL_SHA"
            ERRORS=$((ERRORS + 1))
          fi
        else
          echo "WARN $model_id (exists but no SHA256 registered)"
        fi
      else
        echo "FAIL $model_id - NOT FOUND: $gcs_path"
        ERRORS=$((ERRORS + 1))
      fi
    done <<< "$MODELS"

    echo ""
    if [ $ERRORS -gt 0 ]; then
      echo "$ERRORS model(s) failed validation!"
      exit 1
    else
      echo "All model paths and hashes valid"
    fi
    ;;

  manifest)
    echo "=== GCS Model Manifest ==="
    gsutil cat gs://nba-props-platform-models/catboost/v9/manifest.json 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "Manifest not found in GCS"
    ;;

  *)
    echo "Model Registry CLI"
    echo ""
    echo "Usage:"
    echo "  ./bin/model-registry.sh list              # List all models"
    echo "  ./bin/model-registry.sh production        # Show production models"
    echo "  ./bin/model-registry.sh info <model_id>   # Get model details"
    echo "  ./bin/model-registry.sh features <model_id>  # Get feature list"
    echo "  ./bin/model-registry.sh validate          # Validate GCS paths + SHA256"
    echo "  ./bin/model-registry.sh manifest          # Show GCS manifest"
    ;;
esac
