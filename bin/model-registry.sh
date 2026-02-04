#!/bin/bash
# Model Registry CLI - Query and manage ML models
#
# Usage:
#   ./bin/model-registry.sh list              # List all models
#   ./bin/model-registry.sh production        # Show production models
#   ./bin/model-registry.sh info <model_id>   # Get model details
#   ./bin/model-registry.sh features <model_id>  # Get feature list
#   ./bin/model-registry.sh validate          # Validate GCS paths exist

set -e

COMMAND=${1:-list}
MODEL_ID=$2

case $COMMAND in
  list)
    echo "=== All Registered Models ==="
    bq query --use_legacy_sql=false "
    SELECT
      model_id,
      model_version,
      feature_count,
      training_start_date,
      training_end_date,
      CASE WHEN is_production THEN '✅ PROD' ELSE '' END as prod,
      status
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
    echo "=== Validating GCS Paths ==="
    MODELS=$(bq query --use_legacy_sql=false --format=csv --quiet "
    SELECT model_id, gcs_path
    FROM nba_predictions.model_registry
    WHERE status = 'active'" | tail -n +2)

    ERRORS=0
    while IFS=, read -r model_id gcs_path; do
      if gsutil -q stat "$gcs_path" 2>/dev/null; then
        echo "✅ $model_id"
      else
        echo "❌ $model_id - NOT FOUND: $gcs_path"
        ERRORS=$((ERRORS + 1))
      fi
    done <<< "$MODELS"

    echo ""
    if [ $ERRORS -gt 0 ]; then
      echo "⚠️  $ERRORS model(s) have invalid GCS paths!"
      exit 1
    else
      echo "✅ All model paths valid"
    fi
    ;;

  *)
    echo "Model Registry CLI"
    echo ""
    echo "Usage:"
    echo "  ./bin/model-registry.sh list              # List all models"
    echo "  ./bin/model-registry.sh production        # Show production models"
    echo "  ./bin/model-registry.sh info <model_id>   # Get model details"
    echo "  ./bin/model-registry.sh features <model_id>  # Get feature list"
    echo "  ./bin/model-registry.sh validate          # Validate GCS paths exist"
    ;;
esac
