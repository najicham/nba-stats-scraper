# Four-Season Backfill Execution Plan

**Created:** 2025-12-11
**Last Updated:** 2025-12-11

---

## Pre-Requisites

Before starting, ensure:
- [ ] Virtual environment activated: `source .venv/bin/activate`
- [ ] BigQuery credentials configured
- [ ] Sufficient disk space for logs
- [ ] No other backfills running

---

## Phase 4: Precompute Backfill

### Order of Operations

Phase 4 processors must run in this order:
```
TDZA + PSZA (parallel) → PCF → PDC → ML Feature Store
```

The backfill script handles this automatically.

---

### Season 1: 2021-22 (Remaining Dates)

**Date Range:** 2022-01-08 to 2022-04-10 (~52 dates)
**Note:** We already have Nov 2 2021 - Jan 7 2022 (65 dates)

#### Step 1: Pre-flight Check

```bash
# Check Phase 3 data exists for target dates
PYTHONPATH=. .venv/bin/python -c "
from google.cloud import bigquery
client = bigquery.Client()
query = '''
SELECT COUNT(DISTINCT game_date) as dates
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2022-01-08' AND '2022-04-10'
'''
result = list(client.query(query).result())[0]
print(f'Phase 3 dates available: {result.dates}')
print('Expected: ~52 dates')
print('Status: OK to proceed' if result.dates >= 50 else 'WARNING: Missing Phase 3 data!')
"
```

#### Step 2: Run Phase 4 Backfill

```bash
# Run Phase 4 for remaining 2021-22 season
./bin/backfill/run_phase4_backfill.sh --start 2022-01-08 --end 2022-04-10

# OR run individual processors manually:

# 1. TDZA (Team Defense Zone Analysis)
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2022-01-08 --end-date 2022-04-10 --skip-preflight

# 2. PSZA (Player Shot Zone Analysis) - can run parallel with TDZA
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --start-date 2022-01-08 --end-date 2022-04-10 --skip-preflight

# 3. PCF (Player Composite Factors) - after TDZA+PSZA
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2022-01-08 --end-date 2022-04-10 --skip-preflight

# 4. PDC (Player Daily Cache) - after PCF
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2022-01-08 --end-date 2022-04-10 --skip-preflight

# 5. ML Feature Store - after all above
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2022-01-08 --end-date 2022-04-10 --skip-preflight
```

#### Step 3: Validate Phase 4

```bash
# Check MLFS coverage
bq query --use_legacy_sql=false "
SELECT
  MIN(game_date) as first_date,
  MAX(game_date) as last_date,
  COUNT(DISTINCT game_date) as dates
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date BETWEEN '2021-10-01' AND '2022-06-30'
"
# Expected: ~117 dates (65 existing + 52 new)
```

---

### Season 2: 2022-23

**Date Range:** 2022-10-19 to 2023-04-09 (117 dates)

#### Step 1: Pre-flight Check

```bash
PYTHONPATH=. .venv/bin/python -c "
from google.cloud import bigquery
client = bigquery.Client()
query = '''
SELECT COUNT(DISTINCT game_date) as dates
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2022-10-19' AND '2023-04-09'
'''
result = list(client.query(query).result())[0]
print(f'Phase 3 dates available: {result.dates}')
print('Expected: 117 dates')
"
```

#### Step 2: Run Phase 4 Backfill

```bash
# Run full Phase 4 backfill for 2022-23
./bin/backfill/run_phase4_backfill.sh --start 2022-10-19 --end 2023-04-09

# Or run in chunks if needed (30 days each):
# Chunk 1: Oct-Nov 2022
./bin/backfill/run_phase4_backfill.sh --start 2022-10-19 --end 2022-11-30

# Chunk 2: Dec 2022
./bin/backfill/run_phase4_backfill.sh --start 2022-12-01 --end 2022-12-31

# Chunk 3: Jan 2023
./bin/backfill/run_phase4_backfill.sh --start 2023-01-01 --end 2023-01-31

# Chunk 4: Feb 2023
./bin/backfill/run_phase4_backfill.sh --start 2023-02-01 --end 2023-02-28

# Chunk 5: Mar-Apr 2023
./bin/backfill/run_phase4_backfill.sh --start 2023-03-01 --end 2023-04-09
```

#### Step 3: Validate

```bash
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT game_date) as dates
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date BETWEEN '2022-10-19' AND '2023-04-09'
"
# Expected: 117 dates
```

---

### Season 3: 2023-24

**Date Range:** 2023-10-25 to 2024-04-14 (119 dates)

#### Step 1: Pre-flight Check

```bash
PYTHONPATH=. .venv/bin/python -c "
from google.cloud import bigquery
client = bigquery.Client()
query = '''
SELECT COUNT(DISTINCT game_date) as dates
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2023-10-25' AND '2024-04-14'
'''
result = list(client.query(query).result())[0]
print(f'Phase 3 dates available: {result.dates}')
print('Expected: 119 dates')
"
```

#### Step 2: Run Phase 4 Backfill

```bash
./bin/backfill/run_phase4_backfill.sh --start 2023-10-25 --end 2024-04-14
```

#### Step 3: Validate

```bash
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT game_date) as dates
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date BETWEEN '2023-10-25' AND '2024-04-14'
"
# Expected: 119 dates
```

---

### Season 4: 2024-25 (Current Season)

**Date Range:** 2024-10-22 to 2025-12-10 (~50 dates so far)

#### Step 1: Pre-flight Check

```bash
PYTHONPATH=. .venv/bin/python -c "
from google.cloud import bigquery
from datetime import date
client = bigquery.Client()
query = '''
SELECT COUNT(DISTINCT game_date) as dates, MAX(game_date) as last_date
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date BETWEEN '2024-10-22' AND CURRENT_DATE()
'''
result = list(client.query(query).result())[0]
print(f'Phase 3 dates available: {result.dates}')
print(f'Last date: {result.last_date}')
"
```

#### Step 2: Run Phase 4 Backfill

```bash
# Run up to yesterday (today's data may not be complete)
./bin/backfill/run_phase4_backfill.sh --start 2024-10-22 --end 2025-12-10
```

#### Step 3: Validate

```bash
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT game_date) as dates
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date BETWEEN '2024-10-22' AND '2025-12-10'
"
```

---

## Phase 4 Complete Validation

After all seasons are done:

```bash
# Full Phase 4 coverage check
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN game_date BETWEEN '2021-10-01' AND '2022-06-30' THEN '2021-22'
    WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
    WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
    WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
  END as season,
  COUNT(DISTINCT game_date) as mlfs_dates
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
GROUP BY 1 ORDER BY 1
"

# Expected output:
# | season  | mlfs_dates |
# |---------|------------|
# | 2021-22 | ~117       |
# | 2022-23 | ~117       |
# | 2023-24 | ~119       |
# | 2024-25 | ~50        |
```

---

## Phase 5A: Predictions Backfill

**Prerequisite:** Phase 4 MLFS must be complete for all target dates.

### Step 1: Compute Tier Adjustments

Before running predictions, compute tier adjustments at key dates:

```bash
PYTHONPATH=. .venv/bin/python -c "
from data_processors.ml_feedback.scoring_tier_processor import ScoringTierProcessor

processor = ScoringTierProcessor(lookback_days=30, min_sample_size=10)

# Compute adjustments for key dates across all seasons
dates = [
    # 2021-22 season
    '2021-12-01', '2021-12-15', '2022-01-01', '2022-01-15', '2022-02-01',
    '2022-02-15', '2022-03-01', '2022-03-15', '2022-04-01',
    # 2022-23 season
    '2022-11-01', '2022-11-15', '2022-12-01', '2022-12-15', '2023-01-01',
    '2023-01-15', '2023-02-01', '2023-02-15', '2023-03-01', '2023-03-15', '2023-04-01',
    # 2023-24 season
    '2023-11-01', '2023-11-15', '2023-12-01', '2023-12-15', '2024-01-01',
    '2024-01-15', '2024-02-01', '2024-02-15', '2024-03-01', '2024-03-15', '2024-04-01',
    # 2024-25 season
    '2024-11-01', '2024-11-15', '2024-12-01',
]

for date in dates:
    try:
        result = processor.process(date, 'ensemble_v1')
        print(f'{date}: {result[\"status\"]}')
    except Exception as e:
        print(f'{date}: FAILED - {e}')
"
```

### Step 2: Run Predictions Backfill by Season

```bash
# 2021-22 Season
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2021-11-01 --end-date 2022-04-10 --no-resume

# 2022-23 Season
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2022-10-19 --end-date 2023-04-09 --no-resume

# 2023-24 Season
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2023-10-25 --end-date 2024-04-14 --no-resume

# 2024-25 Season
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2024-10-22 --end-date 2025-12-10 --no-resume
```

### Step 3: Validate Predictions Coverage

```bash
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN game_date BETWEEN '2021-10-01' AND '2022-06-30' THEN '2021-22'
    WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
    WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
    WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
  END as season,
  COUNT(DISTINCT game_date) as prediction_dates,
  COUNT(*) as total_predictions
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE system_id = 'ensemble_v1'
GROUP BY 1 ORDER BY 1
"
```

---

## Phase 5B: Grading Backfill

**Prerequisite:** Phase 5A predictions must be complete.

### Run Grading Backfill

```bash
# 2021-22 Season
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2021-11-01 --end-date 2022-04-10

# 2022-23 Season
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2022-10-19 --end-date 2023-04-09

# 2023-24 Season
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2023-10-25 --end-date 2024-04-14

# 2024-25 Season
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2024-10-22 --end-date 2025-12-10
```

### Validate Grading Coverage

```bash
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN game_date BETWEEN '2021-10-01' AND '2022-06-30' THEN '2021-22'
    WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
    WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
    WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
  END as season,
  COUNT(DISTINCT game_date) as graded_dates,
  COUNT(*) as total_graded,
  ROUND(AVG(absolute_error), 2) as avg_mae
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE system_id = 'ensemble_v1'
GROUP BY 1 ORDER BY 1
"
```

---

## Phase 5C: Validate Tier Adjustments

After grading is complete, validate that tier adjustments are helping:

```bash
PYTHONPATH=. .venv/bin/python -c "
from data_processors.ml_feedback.scoring_tier_processor import ScoringTierProcessor

processor = ScoringTierProcessor()

# Validate for each season
seasons = [
    ('2021-22', '2021-11-01', '2022-04-10'),
    ('2022-23', '2022-10-19', '2023-04-09'),
    ('2023-24', '2023-10-25', '2024-04-14'),
    ('2024-25', '2024-10-22', '2025-12-10'),
]

for name, start, end in seasons:
    try:
        result = processor.validate_adjustments_improve_mae(start, end)
        status = 'PASS' if result['is_improving'] else 'WARN'
        print(f'{name}: {status} - MAE change: {result[\"mae_change\"]:+.3f}')
    except Exception as e:
        print(f'{name}: ERROR - {e}')
"
```

---

## Phase 6: Publishing

**Prerequisite:** All grading must be complete.

### Run Publishing Backfill

```bash
# Export all historical data
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py --backfill-all

# Or by season:
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --start-date 2021-11-01 --end-date 2022-04-10

PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --start-date 2022-10-19 --end-date 2023-04-09

PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --start-date 2023-10-25 --end-date 2024-04-14

PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --start-date 2024-10-22 --end-date 2025-12-10

# Export player profiles
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py --players --min-games 5
```

### Validate Publishing

```bash
# Check GCS bucket
gsutil ls gs://nba-props-platform-api/v1/results/ | wc -l
gsutil ls gs://nba-props-platform-api/v1/best-bets/ | wc -l
gsutil ls gs://nba-props-platform-api/v1/players/ | wc -l
```

---

## Estimated Timeline

| Phase | Seasons | Est. Time | Notes |
|-------|---------|-----------|-------|
| Phase 4 | All 4 | 12-16 hours | Can run overnight |
| Phase 5A | All 4 | 4-6 hours | ~30s per date |
| Phase 5B | All 4 | 2-3 hours | ~15s per date |
| Phase 6 | All 4 | 30 minutes | Fast exports |
| **Total** | | **~20-25 hours** | |

---

## Troubleshooting

### Phase 4 Taking Too Long

If Phase 4 is slow, check that backfill mode is enabled:
```bash
# Should see "backfill_mode: True" in logs
# If not, add --skip-preflight flag
```

### Missing Dependencies Error

If you see "MISSING_DEPENDENCY" errors:
1. Check if upstream processor (PSZA/PCF) failed
2. Re-run the failed upstream processor first

### Streaming Buffer Errors

If you see "streaming buffer" errors during predictions:
- Wait 90 minutes and retry, OR
- The batch loading fix from Session 124 should prevent this

---

## Checkpoints

Use these to resume if interrupted:

```bash
# Check what's completed for Phase 4
bq query --use_legacy_sql=false "
SELECT
  MIN(game_date) as first_date,
  MAX(game_date) as last_date,
  COUNT(DISTINCT game_date) as dates
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
"

# Check what's completed for Phase 5A
bq query --use_legacy_sql=false "
SELECT MAX(game_date) as last_prediction_date
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE system_id = 'ensemble_v1'
"

# Check what's completed for Phase 5B
bq query --use_legacy_sql=false "
SELECT MAX(game_date) as last_graded_date
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE system_id = 'ensemble_v1'
"
```

---

## Post-Backfill Handoff to Daily Orchestration

After backfill is complete:

1. **Verify latest date is current**: Make sure predictions exist up to yesterday
2. **Enable daily orchestration**: Configure Cloud Scheduler to trigger daily processors
3. **Monitor first few days**: Watch for any issues with daily runs
4. **Document completion**: Update this project status to "Complete"
