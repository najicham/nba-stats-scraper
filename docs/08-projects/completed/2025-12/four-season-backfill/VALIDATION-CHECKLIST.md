# Four-Season Backfill Validation Checklist

**Created:** 2025-12-11

---

## Comprehensive Validation Reference

**For detailed validation procedures, failure analysis, and troubleshooting, see:**

`docs/02-operations/backfill/backfill-validation-checklist.md`

This document contains:
- Stop thresholds and when to halt
- Real-time monitoring during backfill
- Failure record analysis
- Name resolution checks
- Cascade contamination detection
- Phase 5 predictions validation
- Known issues and workarounds
- Checklist template for each run

**This file contains project-specific queries with 4-season date ranges pre-filled.**

---

## Quick Status Check

Run this to get current coverage:

```bash
bq query --use_legacy_sql=false "
WITH seasons AS (
  SELECT '2021-22' as season, DATE('2021-10-01') as start_dt, DATE('2022-06-30') as end_dt UNION ALL
  SELECT '2022-23', DATE('2022-10-01'), DATE('2023-06-30') UNION ALL
  SELECT '2023-24', DATE('2023-10-01'), DATE('2024-06-30') UNION ALL
  SELECT '2024-25', DATE('2024-10-01'), DATE('2025-06-30')
),
phase3 AS (
  SELECT
    CASE
      WHEN game_date BETWEEN '2021-10-01' AND '2022-06-30' THEN '2021-22'
      WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
      WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
      WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
    END as season,
    COUNT(DISTINCT game_date) as dates
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  GROUP BY 1
),
phase4 AS (
  SELECT
    CASE
      WHEN game_date BETWEEN '2021-10-01' AND '2022-06-30' THEN '2021-22'
      WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
      WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
      WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
    END as season,
    COUNT(DISTINCT game_date) as dates
  FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
  GROUP BY 1
),
phase5a AS (
  SELECT
    CASE
      WHEN game_date BETWEEN '2021-10-01' AND '2022-06-30' THEN '2021-22'
      WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
      WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
      WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
    END as season,
    COUNT(DISTINCT game_date) as dates
  FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
  WHERE system_id = 'ensemble_v1'
  GROUP BY 1
),
phase5b AS (
  SELECT
    CASE
      WHEN game_date BETWEEN '2021-10-01' AND '2022-06-30' THEN '2021-22'
      WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
      WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
      WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
    END as season,
    COUNT(DISTINCT game_date) as dates
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
  WHERE system_id = 'ensemble_v1'
  GROUP BY 1
)
SELECT
  s.season,
  COALESCE(p3.dates, 0) as phase3_raw,
  COALESCE(p4.dates, 0) as phase4_mlfs,
  COALESCE(p5a.dates, 0) as phase5a_preds,
  COALESCE(p5b.dates, 0) as phase5b_graded
FROM seasons s
LEFT JOIN phase3 p3 ON s.season = p3.season
LEFT JOIN phase4 p4 ON s.season = p4.season
LEFT JOIN phase5a p5a ON s.season = p5a.season
LEFT JOIN phase5b p5b ON s.season = p5b.season
ORDER BY s.season
"
```

**Expected Final Output:**
```
+---------+-------------+-------------+--------------+---------------+
| season  | phase3_raw  | phase4_mlfs | phase5a_preds | phase5b_graded |
+---------+-------------+-------------+--------------+---------------+
| 2021-22 |         117 |         117 |          117 |           117 |
| 2022-23 |         117 |         117 |          117 |           117 |
| 2023-24 |         119 |         119 |          119 |           119 |
| 2024-25 |         ~50 |         ~50 |          ~50 |           ~50 |
+---------+-------------+-------------+--------------+---------------+
```

---

## Phase 4 Validation

### Check MLFS Record Counts

```bash
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN game_date BETWEEN '2021-10-01' AND '2022-06-30' THEN '2021-22'
    WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
    WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
    WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
  END as season,
  COUNT(DISTINCT game_date) as dates,
  COUNT(*) as total_records,
  COUNT(DISTINCT player_lookup) as unique_players
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
GROUP BY 1 ORDER BY 1
"
```

### Check for Missing Dates

```bash
# Find gaps in MLFS data for 2021-22
bq query --use_legacy_sql=false "
WITH date_range AS (
  SELECT date
  FROM UNNEST(GENERATE_DATE_ARRAY('2021-10-19', '2022-04-10')) as date
),
mlfs_dates AS (
  SELECT DISTINCT game_date
  FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
  WHERE game_date BETWEEN '2021-10-19' AND '2022-04-10'
),
phase3_dates AS (
  SELECT DISTINCT game_date
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date BETWEEN '2021-10-19' AND '2022-04-10'
)
SELECT dr.date as missing_date
FROM date_range dr
JOIN phase3_dates p3 ON dr.date = p3.game_date  -- Only dates with Phase 3 data
LEFT JOIN mlfs_dates m ON dr.date = m.game_date
WHERE m.game_date IS NULL
ORDER BY dr.date
LIMIT 20
"
```

### Check Phase 4 Processor Failures

```bash
bq query --use_legacy_sql=false "
SELECT
  processor_name,
  failure_category,
  COUNT(*) as count
FROM \`nba-props-platform.nba_processing.precompute_failures\`
WHERE analysis_date >= '2021-10-01'
GROUP BY 1, 2
ORDER BY 1, count DESC
"
```

---

## Phase 5A Validation

### Check Predictions Per Date

```bash
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT system_id) as systems
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date >= '2021-10-01'
GROUP BY 1
HAVING COUNT(DISTINCT system_id) < 5  -- Should have 5 systems
ORDER BY game_date
LIMIT 20
"
```

### Check Tier Distribution

```bash
bq query --use_legacy_sql=false "
SELECT
  scoring_tier,
  COUNT(*) as count,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(adjusted_points), 1) as avg_adjusted,
  ROUND(AVG(tier_adjustment), 2) as avg_adjustment
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE system_id = 'ensemble_v1'
  AND scoring_tier IS NOT NULL
GROUP BY 1
ORDER BY 1
"
```

---

## Phase 5B Validation

### Check Grading Coverage

```bash
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN game_date BETWEEN '2021-10-01' AND '2022-06-30' THEN '2021-22'
    WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
    WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
    WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
  END as season,
  COUNT(*) as graded,
  ROUND(AVG(absolute_error), 2) as MAE,
  ROUND(AVG(signed_error), 2) as bias,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as win_rate_pct
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE system_id = 'ensemble_v1'
GROUP BY 1
ORDER BY 1
"
```

### Check MAE by System

```bash
bq query --use_legacy_sql=false "
SELECT
  system_id,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as MAE,
  ROUND(AVG(signed_error), 2) as bias
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
GROUP BY 1
ORDER BY MAE
"
```

---

## Phase 5C Validation (Tier Adjustments)

### Verify Adjustments Improve MAE

```bash
PYTHONPATH=. .venv/bin/python -c "
from data_processors.ml_feedback.scoring_tier_processor import ScoringTierProcessor

processor = ScoringTierProcessor()

seasons = [
    ('2021-22', '2021-11-01', '2022-04-10'),
    ('2022-23', '2022-10-19', '2023-04-09'),
    ('2023-24', '2023-10-25', '2024-04-14'),
    ('2024-25', '2024-10-22', '2025-12-10'),
]

print('Season   | MAE Raw | MAE Adj | Change | Status')
print('---------|---------|---------|--------|-------')

for name, start, end in seasons:
    try:
        r = processor.validate_adjustments_improve_mae(start, end)
        status = 'PASS' if r['is_improving'] else 'WARN'
        print(f'{name}   | {r[\"mae_raw\"]:.3f}   | {r[\"mae_adjusted\"]:.3f}   | {r[\"mae_change\"]:+.3f}  | {status}')
    except Exception as e:
        print(f'{name}   | ERROR: {str(e)[:40]}')
"
```

### Check Tier Adjustment Values

```bash
bq query --use_legacy_sql=false "
SELECT
  as_of_date,
  scoring_tier,
  ROUND(avg_signed_error, 2) as bias,
  ROUND(recommended_adjustment, 2) as adjustment,
  sample_size
FROM \`nba-props-platform.nba_predictions.scoring_tier_adjustments\`
ORDER BY as_of_date DESC, scoring_tier
LIMIT 20
"
```

---

## Phase 6 Validation (Publishing)

### Check GCS File Counts

```bash
# Count results files
echo "Results files:"
gsutil ls gs://nba-props-platform-api/v1/results/*.json 2>/dev/null | wc -l

# Count best-bets files
echo "Best bets files:"
gsutil ls gs://nba-props-platform-api/v1/best-bets/*.json 2>/dev/null | wc -l

# Count player profiles
echo "Player profiles:"
gsutil ls gs://nba-props-platform-api/v1/players/*.json 2>/dev/null | wc -l
```

### Verify Latest Files

```bash
# Check most recent results file
gsutil ls -l gs://nba-props-platform-api/v1/results/*.json | tail -5

# Sample a file to verify content
gsutil cat gs://nba-props-platform-api/v1/results/2022-01-07.json | head -100
```

---

## Final Validation Checklist

Run through this checklist after backfill is complete:

### Data Coverage
- [ ] Phase 4 MLFS dates match Phase 3 raw dates for all seasons
- [ ] Phase 5A predictions exist for all MLFS dates
- [ ] Phase 5B grading exists for all predictions
- [ ] No unexpected gaps in any phase

### Data Quality
- [ ] MAE < 5.0 for all systems
- [ ] Tier adjustments improving MAE (negative change)
- [ ] Win rate > 50% for ensemble system
- [ ] No anomalous bias values (should be between -3 and +3)

### System Health
- [ ] No PROCESSING_ERROR failures in precompute_failures table
- [ ] All 5 prediction systems present for each date
- [ ] Tier distribution looks reasonable (most players in BENCH/ROTATION)

### Publishing
- [ ] GCS files exist for all graded dates
- [ ] Player profiles generated for players with 5+ games
- [ ] System performance file updated

---

## Troubleshooting Queries

### Find Ungraded Predictions

```bash
bq query --use_legacy_sql=false "
SELECT p.game_date, COUNT(*) as ungraded
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\` p
LEFT JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON p.player_lookup = pa.player_lookup
  AND p.game_date = pa.game_date
  AND p.system_id = pa.system_id
WHERE p.system_id = 'ensemble_v1'
  AND pa.player_lookup IS NULL
GROUP BY 1
ORDER BY 1
LIMIT 20
"
```

### Find Missing MLFS for Dates with Predictions

```bash
bq query --use_legacy_sql=false "
SELECT p.game_date, COUNT(DISTINCT p.player_lookup) as players_missing_mlfs
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\` p
LEFT JOIN \`nba-props-platform.nba_predictions.ml_feature_store_v2\` m
  ON p.player_lookup = m.player_lookup
  AND p.game_date = m.game_date
WHERE p.system_id = 'ensemble_v1'
  AND m.player_lookup IS NULL
GROUP BY 1
HAVING COUNT(DISTINCT p.player_lookup) > 0
ORDER BY 1
"
```
