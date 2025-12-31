# Pipeline Replay Usage Guide

## Prerequisites

1. **Python Environment**:
   ```bash
   cd /home/naji/code/nba-stats-scraper
   source .venv/bin/activate
   ```

2. **GCP Authentication**:
   ```bash
   gcloud auth application-default login
   # Or ensure GOOGLE_APPLICATION_CREDENTIALS is set
   ```

3. **Test Datasets Created**:
   ```bash
   ./bin/testing/setup_test_datasets.sh
   ```

## Basic Usage

### Replay Yesterday's Pipeline

```bash
./bin/testing/replay_pipeline.sh
```

This will:
1. Run all phases (2-6) for yesterday's date
2. Write to `test_*` datasets in BigQuery
3. Export to `gs://bucket/test/exports/`
4. Print timing and validation report

### Replay a Specific Date

```bash
./bin/testing/replay_pipeline.sh 2024-12-15
```

### Custom Dataset Prefix

```bash
./bin/testing/replay_pipeline.sh 2024-12-15 mytest_
```

Results go to `mytest_nba_analytics`, `mytest_nba_predictions`, etc.

### Dry Run

```bash
./bin/testing/replay_pipeline.sh 2024-12-15 test_ --dry-run
```

Shows what would be executed without actually running.

## Phase-by-Phase Execution

### Run Individual Phases

```bash
# Just Phase 2 (Raw Processing)
DATASET_PREFIX=test_ python -m data_processors.raw.run_all --date 2024-12-15

# Just Phase 3 (Analytics)
DATASET_PREFIX=test_ python -m data_processors.analytics.run_all --date 2024-12-15

# Just Phase 5 (Predictions)
DATASET_PREFIX=test_ python -m predictions.coordinator.run_local --date 2024-12-15
```

### Resume from a Phase

```bash
# If Phase 3 failed, fix the issue and resume:
./bin/testing/replay_pipeline.sh 2024-12-15 test_ --start-phase 3
```

## Validation

### Run Validation Only

```bash
python bin/testing/validate_replay.py --date 2024-12-15 --prefix test_
```

### Validation Output

```
=== REPLAY VALIDATION REPORT ===
Date: 2024-12-15
Prefix: test_

PREDICTIONS:
  ✓ Count: 487 (minimum: 400)
  ✓ Unique: 487 (no duplicates)
  ✓ Games covered: 8/8

ANALYTICS:
  ✓ player_game_summary: 245 records
  ✓ team_defense_game_summary: 16 records

EXPORTS:
  ✓ predictions.json: valid
  ✓ best_bets.json: valid
  ✓ tonight_all_players.json: valid

PERFORMANCE:
  Phase 2: 3m 42s ✓
  Phase 3: 8m 15s ✓
  Phase 4: 6m 30s ✓
  Phase 5: 12m 18s ✓
  Phase 6: 2m 05s ✓
  Total: 32m 50s ✓

STATUS: PASSED
```

## Compare with Production

```bash
python bin/testing/compare_outputs.py --date 2024-12-15 --prefix test_
```

Output:
```
=== COMPARISON: test_ vs production ===
Date: 2024-12-15

PREDICTIONS:
  Production: 485 records
  Test: 487 records
  Difference: +2 records (0.4%)

  Matching predictions: 483 (99.6%)
  Different values: 2
  Extra in test: 2
  Missing in test: 0

DIFFERENCES:
  1. player_id=203507, stat_type=points
     - Production: prediction=24.5
     - Test: prediction=24.8

  2. player_id=1629029, stat_type=rebounds
     - Production: (missing)
     - Test: prediction=8.2

STATUS: ACCEPTABLE (< 1% difference)
```

## Common Use Cases

### 1. Test a Code Change

```bash
# 1. Make your code changes
git checkout -b feature/new-prediction-logic

# 2. Run replay
./bin/testing/replay_pipeline.sh 2024-12-15

# 3. Compare with production
python bin/testing/compare_outputs.py --date 2024-12-15

# 4. If acceptable, commit and deploy
```

### 2. Debug a Production Issue

```bash
# 1. Find the date with the issue
# 2. Run replay with verbose logging
DEBUG=1 ./bin/testing/replay_pipeline.sh 2024-12-10

# 3. Inspect test datasets
bq query "SELECT * FROM test_nba_predictions.player_prop_predictions WHERE game_date = '2024-12-10' LIMIT 10"
```

### 3. Performance Benchmarking

```bash
# Run multiple dates and aggregate timings
for date in 2024-12-{10..15}; do
  ./bin/testing/replay_pipeline.sh $date test_ --timing-only
done

# View benchmark results
python bin/testing/analyze_benchmarks.py
```

### 4. Test Edge Cases

```bash
# Double-header day
./bin/testing/replay_pipeline.sh 2024-01-15

# Light game day (2 games)
./bin/testing/replay_pipeline.sh 2024-12-25

# Season opener
./bin/testing/replay_pipeline.sh 2024-10-22
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATASET_PREFIX` | `''` | Prefix for all BigQuery datasets |
| `GCS_PREFIX` | `''` | Prefix for GCS paths |
| `FIRESTORE_PREFIX` | `''` | Prefix for Firestore collections |
| `DEBUG` | `0` | Enable verbose logging |
| `SKIP_VALIDATION` | `0` | Skip post-replay validation |
| `PARALLEL_WORKERS` | `4` | Number of parallel prediction workers |

## Cleanup

### Delete Test Data

```bash
# Delete test datasets
bq rm -r -f nba-props-platform:test_nba_source
bq rm -r -f nba-props-platform:test_nba_analytics
bq rm -r -f nba-props-platform:test_nba_predictions

# Delete test GCS files
gsutil -m rm -r gs://nba-props-platform-api/test/
```

### Auto-Cleanup (Recommended)

Set up TTL on test datasets:
```bash
# Tables automatically deleted after 7 days
bq update --default_table_expiration 604800 nba-props-platform:test_nba_predictions
```

## Troubleshooting

### "Dataset not found"

```bash
# Create test datasets first
./bin/testing/setup_test_datasets.sh
```

### "No GCS files for date"

The replay reads from production GCS (raw scraper data). Ensure:
1. Scrapers ran for that date
2. Date format is correct (YYYY-MM-DD)

### "Phase 5 timeout"

Predictions are compute-intensive. Try:
```bash
# Reduce parallel workers
PARALLEL_WORKERS=2 ./bin/testing/replay_pipeline.sh 2024-12-15
```

### "Validation failed"

Check specific failures:
```bash
python bin/testing/validate_replay.py --date 2024-12-15 --prefix test_ --verbose
```
