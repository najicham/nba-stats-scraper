# Dataset Isolation Guide

## Overview

Dataset isolation allows you to test pipeline changes against historical data without affecting production. This is critical for:

- **Safe Development**: Test code changes in isolation before deploying to production
- **Performance Benchmarking**: Measure the impact of optimizations on real data
- **Bug Reproduction**: Replay exact conditions that caused production issues
- **Regression Detection**: Ensure changes don't break existing functionality

## How It Works

When you specify a `dataset_prefix` parameter (e.g., `"test"`), all pipeline operations read from and write to prefixed datasets:

- `test_nba_raw` - Raw source data
- `test_nba_analytics` - Phase 3 analytics output
- `test_nba_precompute` - Phase 4 precompute output (ML features)
- `test_nba_predictions` - Phase 5 predictions output

Production datasets (`nba_raw`, `nba_analytics`, etc.) remain completely untouched.

## Quick Start

### 1. Prepare Test Data

First, ensure test raw data exists for your target date:

```bash
# Check available test dates
bq query --use_legacy_sql=false \
  "SELECT DISTINCT DATE(game_date) as date
   FROM test_nba_raw.nbac_gamebook_player_stats
   ORDER BY date"
```

If your date doesn't exist, copy from production:

```bash
DATE="2025-12-20"

# Copy gamebook data
bq query --use_legacy_sql=false --location=us-west2 \
  --destination_table=test_nba_raw.nbac_gamebook_player_stats \
  --append_table \
  "SELECT * FROM nba_raw.nbac_gamebook_player_stats
   WHERE DATE(game_date) = '$DATE'"

# Copy BDL data
bq query --use_legacy_sql=false --location=us-west2 \
  --destination_table=test_nba_raw.bdl_player_boxscores \
  --append_table \
  "SELECT * FROM nba_raw.bdl_player_boxscores
   WHERE DATE(game_date) = '$DATE'"
```

### 2. Run Full Pipeline Test

Use the `force_predictions.sh` script with the test prefix:

```bash
./bin/pipeline/force_predictions.sh 2025-12-20 test
```

This runs all pipeline phases (3, 4, 5) with isolated test datasets.

### 3. Validate Results

Use the validation script to verify isolation:

```bash
./bin/testing/validate_isolation.sh 2025-12-20 test
```

Expected output:
```
✅ Phase 3: 200+ player records in test dataset
✅ Phase 4: 300+ ML features in test dataset
✅ Phase 5: 800+ predictions in test dataset
✅ Production datasets contain data for 2025-12-20
✅ All pipeline phases have test data
```

## Phase-by-Phase Usage

### Phase 3: Analytics

Process historical game data into analytics:

```bash
TOKEN=$(gcloud auth print-identity-token)

curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2025-12-19",
    "end_date": "2025-12-19",
    "processors": ["PlayerGameSummaryProcessor", "UpcomingPlayerGameContextProcessor"],
    "backfill_mode": true,
    "dataset_prefix": "test"
  }'
```

Verify output:
```bash
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) FROM test_nba_analytics.player_game_summary
   WHERE game_date = '2025-12-20'"
```

### Phase 4: Precompute (ML Features)

Generate ML features for predictions:

```bash
TOKEN=$(gcloud auth print-identity-token)

curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_date": "2025-12-20",
    "processors": ["MLFeatureStoreProcessor"],
    "skip_dependency_check": true,
    "dataset_prefix": "test"
  }'
```

Verify output:
```bash
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) FROM test_nba_predictions.ml_feature_store_v2
   WHERE game_date = '2025-12-20'"
```

### Phase 5: Predictions

Generate player prop predictions:

```bash
TOKEN=$(gcloud auth print-identity-token)

curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "game_date": "2025-12-20",
    "dataset_prefix": "test"
  }'
```

Wait for completion (~2-5 minutes), then verify:

```bash
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
   FROM test_nba_predictions.player_prop_predictions
   WHERE game_date = '2025-12-20'"
```

## Validation & Verification

### Automated Validation

The validation script checks:
- ✅ All test datasets exist and are in the correct region
- ✅ Test data present across all pipeline phases
- ✅ Production data untouched
- ✅ Data quality (no NULL IDs, reasonable duplicate levels)
- ✅ Staging tables cleaned up

```bash
./bin/testing/validate_isolation.sh 2025-12-20 test
```

### Manual Verification

Compare test vs production counts:

```bash
bq query --use_legacy_sql=false \
  "SELECT
    (SELECT COUNT(*) FROM nba_predictions.player_prop_predictions
     WHERE game_date = '2025-12-20') as prod_count,
    (SELECT COUNT(*) FROM test_nba_predictions.player_prop_predictions
     WHERE game_date = '2025-12-20') as test_count"
```

Check for staging tables (should be 0 after consolidation):

```bash
bq ls test_nba_predictions | grep -c "_staging"
```

## Troubleshooting

### Issue: "Table not found: test_nba_predictions.player_prop_predictions"

**Cause**: Table doesn't exist in test dataset
**Solution**: Create it with the production schema:

```bash
bq show --schema --format=prettyjson nba_predictions.player_prop_predictions > /tmp/schema.json
bq mk --table --location=us-west2 test_nba_predictions.player_prop_predictions /tmp/schema.json
```

### Issue: "Invalid MERGE query: Partitioning by expressions of type FLOAT64"

**Cause**: BigQuery doesn't allow FLOAT64 in PARTITION BY clauses
**Solution**: This should be fixed in the latest code. Redeploy coordinator:

```bash
./bin/predictions/deploy/deploy_prediction_coordinator.sh
```

### Issue: No predictions in main table, but staging tables exist

**Cause**: Consolidation step failed or hasn't run yet
**Solution**: Check coordinator logs:

```bash
gcloud logging read 'resource.type=cloud_run_revision AND
  resource.labels.service_name="prediction-coordinator" AND
  textPayload:"Consolidation"' --limit=10
```

If consolidation failed, you can manually trigger it (requires Python):

```python
from google.cloud import bigquery
from predictions.worker.batch_staging_writer import BatchConsolidator

client = bigquery.Client(project="nba-props-platform", location="us-west2")
consolidator = BatchConsolidator(client, "nba-props-platform", dataset_prefix="test")

result = consolidator.consolidate_batch("batch_2025-12-20_XXXXX", "2025-12-20")
print(f"Merged {result.rows_affected} rows from {result.staging_tables_merged} tables")
```

### Issue: Region mismatch errors

**Cause**: Test datasets in wrong region (must be `us-west2`)
**Solution**: Delete and recreate datasets:

```bash
# Check region
bq show --format=json test_nba_predictions | jq -r '.location'

# If wrong region, recreate
bq rm -r -f test_nba_predictions
bq mk --location=us-west2 test_nba_predictions
```

### Issue: "PredictionDataLoader got unexpected keyword argument 'dataset_prefix'"

**Cause**: Deployed service has old code
**Solution**: Redeploy coordinator and worker:

```bash
./bin/predictions/deploy/deploy_prediction_coordinator.sh
./bin/predictions/deploy/deploy_prediction_worker.sh
```

## Best Practices

### 1. Always Validate After Testing

Run the validation script after every test to ensure:
- Data isolation worked correctly
- Production wasn't affected
- All phases completed successfully

### 2. Clean Up Old Test Data

Periodically remove old test data to save costs:

```bash
# Delete data older than 30 days
for dataset in test_nba_analytics test_nba_precompute test_nba_predictions; do
  bq query --use_legacy_sql=false \
    "DELETE FROM \`nba-props-platform.$dataset.*\`
     WHERE game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)"
done
```

### 3. Use Descriptive Prefixes for Different Test Types

- `test` - General testing
- `perf` - Performance benchmarking
- `debug` - Bug reproduction
- `exp` - Experimental features

Example:
```bash
./bin/pipeline/force_predictions.sh 2025-12-20 perf
```

### 4. Document Test Results

When testing changes, document:
- What changed
- Test date and prefix used
- Validation results
- Performance metrics (if applicable)

## Architecture Details

### Dataset Prefix Flow

1. **API Request**: User specifies `dataset_prefix` in API call
2. **Phase Processing**: Each phase constructs dataset names:
   ```python
   dataset = f"{prefix}_nba_analytics" if prefix else "nba_analytics"
   ```
3. **BigQuery Queries**: All queries use prefixed datasets
4. **Output**: Results written to prefixed datasets only

### Code Locations

**Core Prefix Logic**:
- `data_processors/analytics/analytics_base.py:157-160` - Analytics prefix handling
- `data_processors/precompute/precompute_base.py:798-801` - Precompute prefix handling
- `predictions/worker/data_loaders.py:37-53` - Worker data loading with prefix
- `predictions/worker/batch_staging_writer.py:76-90` - Staging writer with prefix

**Testing Scripts**:
- `bin/pipeline/force_predictions.sh` - Full pipeline test script
- `bin/testing/validate_isolation.sh` - Validation script
- `bin/testing/replay_pipeline.py` - Python replay orchestrator
- `bin/testing/validate_replay.py` - Python validation

### Deployment Scripts

All services support dataset_prefix in latest deployments:
- `bin/analytics/deploy/deploy_analytics_processors.sh` - Phase 3
- `bin/precompute/deploy/deploy_precompute_processors.sh` - Phase 4
- `bin/predictions/deploy/deploy_prediction_coordinator.sh` - Phase 5 coordinator
- `bin/predictions/deploy/deploy_prediction_worker.sh` - Phase 5 worker

## Performance Considerations

### Test Data Volume

Typical test run for one date:
- Phase 3: 200-250 player records (~2 seconds)
- Phase 4: 300-400 ML features (~5 seconds)
- Phase 5: 800-1000 predictions (~2-3 minutes)
- Total time: ~3-4 minutes end-to-end

### Storage Costs

Test data for 30 dates (~$0.02/GB/month in BigQuery):
- Analytics: ~50 MB
- Features: ~30 MB
- Predictions: ~20 MB
- **Total**: ~100 MB = ~$0.002/month

### Query Costs

BigQuery charges $5/TB for on-demand queries:
- Validation queries: ~100 MB scanned = $0.0005
- Full pipeline test: ~500 MB scanned = $0.0025

## Related Documentation

- [Testing Guide](testing-guide.md) - General testing practices
- [BigQuery Best Practices](bigquery-best-practices.md) - Query optimization
- [Cloud Run Deployment](cloud-run-deployment.md) - Service deployment
- [Phase 3 Architecture](../../04-architecture/phase-3-analytics.md)
- [Phase 4 Architecture](../../04-architecture/phase-4-precompute.md)
- [Phase 5 Architecture](../../04-architecture/phase-5-predictions.md)

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review recent commits for dataset_prefix changes: `git log --grep="dataset_prefix"`
3. Check Cloud Run logs for error details
4. File an issue with validation script output and error logs
