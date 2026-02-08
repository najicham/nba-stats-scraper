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
          ACTUAL_SHA=$(sha256sum "$TMP_FILE" | cut -d' ' -f1)
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

  sync)
    echo "=== Syncing GCS Manifest to BQ Model Registry ==="
    echo "Fetching manifest from GCS..."
    MANIFEST=$(gsutil cat gs://nba-props-platform-models/catboost/v9/manifest.json 2>/dev/null)
    if [ -z "$MANIFEST" ]; then
      echo "ERROR: Could not fetch manifest from GCS"
      exit 1
    fi

    echo "Parsing manifest and upserting to BigQuery..."
    export MANIFEST_DATA="$MANIFEST"
    python3 - <<'PYEOF'
import json
import sys
import os
from datetime import datetime
from google.cloud import bigquery

manifest_json = os.environ.get('MANIFEST_DATA', '')
if not manifest_json:
    print("ERROR: No manifest data provided", file=sys.stderr)
    sys.exit(1)

manifest = json.loads(manifest_json)
client = bigquery.Client(project='nba-props-platform')

# Build MERGE query with inline values
merge_parts = []
for model_name, model_data in manifest.get('models', {}).items():
    status = model_data.get('status', 'active')
    is_production = status == 'production'
    prod_date = model_data.get('production_since') if is_production else None
    notes = model_data.get('deprecation_reason') or model_data.get('evaluation', {}).get('note', '')
    mae = model_data.get('evaluation', {}).get('mae')
    hr_3plus = model_data.get('evaluation', {}).get('high_edge_hit_rate_3plus')

    print(f"  Upserting: {model_name} (status={status}, training={model_data.get('training_start')} to {model_data.get('training_end')})")

    # Build struct literal for this model (handle None values properly)
    struct_parts = []
    struct_parts.append(f"'{model_name}' AS model_id")
    struct_parts.append(f"'v9' AS model_version")
    struct_parts.append(f"'{model_data.get('model_type', 'catboost')}' AS model_type")
    struct_parts.append(f"'{model_data.get('gcs_path', '')}' AS gcs_path")
    struct_parts.append(f"{model_data.get('feature_count', 0)} AS feature_count")
    struct_parts.append(f"DATE'{model_data.get('training_start')}' AS training_start_date")
    struct_parts.append(f"DATE'{model_data.get('training_end')}' AS training_end_date")
    struct_parts.append(f"{model_data.get('training_samples', 0)} AS training_samples")
    struct_parts.append(f"{mae if mae is not None else 'NULL'} AS evaluation_mae")
    struct_parts.append(f"{hr_3plus if hr_3plus is not None else 'NULL'} AS evaluation_hit_rate_edge_3plus")
    struct_parts.append(f"'{model_data.get('sha256', '')}' AS sha256_hash")
    struct_parts.append(f"'{status}' AS status")
    struct_parts.append(f"{'TRUE' if is_production else 'FALSE'} AS is_production")
    # Handle production_start_date
    prod_date_sql = f"DATE'{prod_date}'" if prod_date else 'NULL'
    struct_parts.append(f"{prod_date_sql} AS production_start_date")
    # Escape single quotes in notes (handle empty notes)
    if notes:
        escaped_notes = notes.replace("'", "''")
        struct_parts.append(f"'{escaped_notes}' AS notes")
    else:
        struct_parts.append(f"NULL AS notes")
    struct_parts.append(f"'model-registry-sync' AS created_by")

    merge_parts.append(f"SELECT {', '.join(struct_parts)}")

# Build full MERGE query
source_query = ' UNION ALL '.join(merge_parts)
merge_query = f"""
MERGE nba_predictions.model_registry AS target
USING ({source_query}) AS source
ON target.model_id = source.model_id
WHEN MATCHED THEN
  UPDATE SET
    model_version = source.model_version,
    model_type = source.model_type,
    gcs_path = source.gcs_path,
    feature_count = source.feature_count,
    training_start_date = source.training_start_date,
    training_end_date = source.training_end_date,
    training_samples = source.training_samples,
    evaluation_mae = source.evaluation_mae,
    evaluation_hit_rate_edge_3plus = source.evaluation_hit_rate_edge_3plus,
    sha256_hash = source.sha256_hash,
    status = source.status,
    is_production = source.is_production,
    production_start_date = source.production_start_date,
    notes = source.notes
WHEN NOT MATCHED THEN
  INSERT (model_id, model_version, model_type, gcs_path, feature_count,
          training_start_date, training_end_date, training_samples,
          evaluation_mae, evaluation_hit_rate_edge_3plus, sha256_hash,
          status, is_production, production_start_date, notes, created_by, created_at)
  VALUES (source.model_id, source.model_version, source.model_type, source.gcs_path,
          source.feature_count, source.training_start_date, source.training_end_date,
          source.training_samples, source.evaluation_mae, source.evaluation_hit_rate_edge_3plus,
          source.sha256_hash, source.status, source.is_production, source.production_start_date,
          source.notes, source.created_by, CURRENT_TIMESTAMP())
"""

try:
    query_job = client.query(merge_query)
    query_job.result()
    print(f"\nSynced {len(manifest.get('models', {}))} models to BigQuery model_registry")
    print("Run './bin/model-registry.sh list' to verify")
except Exception as e:
    print(f"ERROR: Failed to sync to BigQuery: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYEOF
    ;;

  claude-md)
    echo "=== Auto-Generated CLAUDE.md Model Section ==="
    echo ""
    bq query --use_legacy_sql=false --format=json --quiet "
    SELECT
      model_id,
      training_start_date,
      training_end_date,
      evaluation_hit_rate_edge_3plus,
      evaluation_hit_rate_edge_5plus,
      evaluation_mae,
      status,
      SUBSTR(sha256_hash, 1, 12) as sha256_prefix,
      production_start_date,
      notes
    FROM nba_predictions.model_registry
    WHERE is_production = TRUE
    ORDER BY production_start_date DESC
    LIMIT 1" | python3 -c "
import json, sys
from datetime import datetime

try:
    data = json.load(sys.stdin)
    if not data:
        print('No production model found in registry')
        sys.exit(1)

    model = data[0]
    model_id = model['model_id']
    train_start = model['training_start_date']
    train_end = model['training_end_date']
    hr_3plus = model.get('evaluation_hit_rate_edge_3plus')
    hr_5plus = model.get('evaluation_hit_rate_edge_5plus')
    mae = model.get('evaluation_mae')
    status = model['status']
    sha_prefix = model['sha256_prefix']
    prod_date = model.get('production_start_date')
    notes = model.get('notes', '')

    # Format the CLAUDE.md section
    print('## ML Model - CatBoost V9 [Keyword: MODEL]')
    print('')
    print('| Property | Value |')
    print('|----------|-------|')
    print(f'| System ID | \`catboost_v9\` |')
    print(f'| Production Model | \`{model_id}\` (Session 163) |')
    print(f'| Training | {train_start} to {train_end} |')
    if hr_3plus:
        hr_3plus_val = float(hr_3plus) if isinstance(hr_3plus, str) else hr_3plus
        print(f'| **Medium Quality (3+ edge)** | **{hr_3plus_val:.1f}% hit rate** |')
    if hr_5plus:
        hr_5plus_val = float(hr_5plus) if isinstance(hr_5plus, str) else hr_5plus
        print(f'| **High Quality (5+ edge)** | **{hr_5plus_val:.1f}% hit rate** |')
    if mae:
        mae_val = float(mae) if isinstance(mae, str) else mae
        print(f'| MAE | {mae_val:.2f} |')
    print(f'| SHA256 (prefix) | \`{sha_prefix}\` |')
    print(f'| Status | {status.upper()} (since {prod_date}) |')
    print('')
    print('**CRITICAL:** Use edge >= 3 filter. Lower edge predictions have worse performance.')
    print('')
    if notes:
        print(f'**Notes:** {notes}')
        print('')
    print('### Model Governance (Sessions 163-164)')
    print('')
    print('See CLAUDE.md for full governance documentation.')
    print('')
    print('<!-- Auto-generated by ./bin/model-registry.sh claude-md -->')
    print(f'<!-- Last updated: {datetime.now().strftime(\"%Y-%m-%d %H:%M:%S UTC\")} -->')

except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
"
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
    echo "  ./bin/model-registry.sh sync              # Sync GCS manifest to BQ registry"
    echo "  ./bin/model-registry.sh claude-md         # Generate CLAUDE.md model section"
    ;;
esac
