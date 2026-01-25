# Execution Plan

## Overview

This document provides the step-by-step execution plan for validating all 2024-25 season data and identifying what needs to be backfilled.

## Prerequisites

Before starting:

1. **BigQuery Access**: Ensure you have query access to all `nba_*` datasets
2. **GCS Access**: Ensure you can list `gs://nba-scrapers-output/`
3. **Validation Tables Created**: Run schema creation from `04-RESULTS-STORAGE-SCHEMA.md`
4. **Python Environment**: Activate the project virtualenv

```bash
cd /home/naji/code/nba-stats-scraper
source venv/bin/activate
```

## Phase 1: Discovery Scan (Quick)

### Step 1.1: Run Quick Completeness Scan

Get a high-level view of data completeness across all phases.

```bash
# Quick scan of last 90 days
python bin/validation/daily_data_completeness.py \
  --days 90 \
  --output-format json \
  > validation_results/quick_scan_90d.json

# Full season scan (slower)
python bin/validation/daily_data_completeness.py \
  --start-date 2024-10-22 \
  --end-date 2026-01-25 \
  --output-format json \
  > validation_results/quick_scan_full_season.json
```

### Step 1.2: Identify Obvious Gaps

Parse the quick scan to find dates with zero records:

```bash
# Find dates with Phase 2 gaps
jq '.dates[] | select(.phase2.status == "FAIL")' \
  validation_results/quick_scan_full_season.json \
  > validation_results/phase2_gaps.json

# Find dates with Phase 3 gaps
jq '.dates[] | select(.phase3.status == "FAIL")' \
  validation_results/quick_scan_full_season.json \
  > validation_results/phase3_gaps.json

# Find dates with Phase 4 gaps
jq '.dates[] | select(.phase4.status == "FAIL")' \
  validation_results/quick_scan_full_season.json \
  > validation_results/phase4_gaps.json
```

### Step 1.3: Summary Report

```bash
# Count gaps by phase
echo "Phase 2 gaps:" && wc -l validation_results/phase2_gaps.json
echo "Phase 3 gaps:" && wc -l validation_results/phase3_gaps.json
echo "Phase 4 gaps:" && wc -l validation_results/phase4_gaps.json
```

---

## Phase 2: Detailed Validation

### Step 2.1: Run Phase-Specific Validators

For each phase, run the detailed validators to get quality metrics.

```bash
# Phase 2 validation (raw data)
./validation/test_validation_system.sh \
  --processor bdl_boxscores \
  --days 365 \
  --verbose \
  > validation_results/phase2_bdl_detailed.txt

./validation/test_validation_system.sh \
  --processor nbac_player_boxscore \
  --days 365 \
  --verbose \
  > validation_results/phase2_nbac_detailed.txt

# Phase 3 validation (analytics)
./validation/test_validation_system.sh \
  --processor player_game_summary \
  --days 365 \
  --verbose \
  > validation_results/phase3_pgs_detailed.txt

# Phase 4 validation (precompute)
./validation/test_validation_system.sh \
  --processor ml_feature_store \
  --days 365 \
  --verbose \
  > validation_results/phase4_mlfs_detailed.txt
```

### Step 2.2: Run Comprehensive Health Check

```bash
# Run 9-angle health check for specific date ranges
python bin/validation/comprehensive_health_check.py \
  --start-date 2024-10-22 \
  --end-date 2024-11-30 \
  --output-format json \
  > validation_results/health_oct_nov.json

python bin/validation/comprehensive_health_check.py \
  --start-date 2024-12-01 \
  --end-date 2024-12-31 \
  --output-format json \
  > validation_results/health_dec.json

python bin/validation/comprehensive_health_check.py \
  --start-date 2025-01-01 \
  --end-date 2025-01-25 \
  --output-format json \
  > validation_results/health_jan.json
```

### Step 2.3: Check Quality Metrics

Run BigQuery queries to check quality distributions:

```sql
-- Phase 3 quality distribution
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(is_production_ready = TRUE) as production_ready,
  ROUND(AVG(completeness_pct), 1) as avg_completeness,
  CASE
    WHEN AVG(completeness_pct) >= 70 THEN 'PASS'
    WHEN AVG(completeness_pct) >= 50 THEN 'WARN'
    ELSE 'FAIL'
  END as quality_status
FROM `nba_analytics.player_game_summary`
WHERE game_date BETWEEN '2024-10-22' AND CURRENT_DATE()
GROUP BY game_date
HAVING quality_status IN ('WARN', 'FAIL')
ORDER BY game_date;
```

```sql
-- Phase 4 quality distribution
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(data_quality_tier = 'gold') as gold,
  COUNTIF(data_quality_tier = 'silver') as silver,
  COUNTIF(data_quality_tier = 'bronze') as bronze,
  CASE
    WHEN COUNTIF(data_quality_tier = 'gold') / COUNT(*) >= 0.5 THEN 'PASS'
    WHEN COUNTIF(data_quality_tier IN ('gold', 'silver')) / COUNT(*) >= 0.5 THEN 'WARN'
    ELSE 'FAIL'
  END as quality_status
FROM `nba_precompute.ml_feature_store_v2`
WHERE game_date BETWEEN '2024-10-22' AND CURRENT_DATE()
GROUP BY game_date
HAVING quality_status IN ('WARN', 'FAIL')
ORDER BY game_date;
```

---

## Phase 3: Cascade Impact Analysis

### Step 3.1: Identify All Direct Gaps

Consolidate gaps from all phases:

```sql
-- Create consolidated gaps table
CREATE OR REPLACE TABLE `nba_validation.identified_gaps` AS
WITH phase2_gaps AS (
  SELECT DISTINCT game_date, 'phase2' as phase
  FROM `nba_raw.nbac_schedule` s
  LEFT JOIN `nba_raw.nbac_gamebook_player_stats` g USING (game_date)
  WHERE s.season_year = 2024
    AND s.game_status = 'Final'
    AND g.game_date IS NULL
),
phase3_gaps AS (
  SELECT DISTINCT game_date, 'phase3' as phase
  FROM `nba_raw.nbac_schedule` s
  LEFT JOIN `nba_analytics.player_game_summary` g USING (game_date)
  WHERE s.season_year = 2024
    AND s.game_status = 'Final'
    AND g.game_date IS NULL
),
phase4_gaps AS (
  SELECT DISTINCT game_date, 'phase4' as phase
  FROM `nba_raw.nbac_schedule` s
  LEFT JOIN `nba_precompute.ml_feature_store_v2` g USING (game_date)
  WHERE s.season_year = 2024
    AND s.game_status = 'Final'
    AND g.game_date IS NULL
)
SELECT * FROM phase2_gaps
UNION ALL
SELECT * FROM phase3_gaps
UNION ALL
SELECT * FROM phase4_gaps
ORDER BY game_date, phase;
```

### Step 3.2: Calculate Cascade Impact

```sql
-- Calculate cascade impact for each gap
CREATE OR REPLACE TABLE `nba_validation.cascade_impact_calculated` AS
WITH gaps AS (
  SELECT DISTINCT game_date as gap_date, phase as gap_phase
  FROM `nba_validation.identified_gaps`
),
future_dates AS (
  SELECT DISTINCT game_date
  FROM `nba_raw.nbac_schedule`
  WHERE season_year = 2024
    AND game_status = 'Final'
)
SELECT
  g.gap_date,
  g.gap_phase,
  f.game_date as affected_date,
  DATE_DIFF(f.game_date, g.gap_date, DAY) as days_downstream,
  CASE
    WHEN g.gap_phase = 'phase2' THEN 'phase3'
    WHEN g.gap_phase = 'phase3' THEN 'phase4'
    WHEN g.gap_phase = 'phase4' THEN 'phase5'
  END as affected_phase,
  CASE
    WHEN DATE_DIFF(f.game_date, g.gap_date, DAY) <= 5 THEN 'HIGH'
    WHEN DATE_DIFF(f.game_date, g.gap_date, DAY) <= 15 THEN 'MEDIUM'
    ELSE 'LOW'
  END as impact_severity
FROM gaps g
CROSS JOIN future_dates f
WHERE f.game_date > g.gap_date
  AND f.game_date <= DATE_ADD(g.gap_date, INTERVAL
    CASE g.gap_phase
      WHEN 'phase2' THEN 20
      WHEN 'phase3' THEN 20
      WHEN 'phase4' THEN 10
      ELSE 5
    END DAY)
ORDER BY g.gap_date, f.game_date;
```

### Step 3.3: Generate Cascade Report

```sql
-- Summary of cascade contamination
SELECT
  affected_date,
  COUNT(DISTINCT gap_date) as upstream_gaps,
  STRING_AGG(CAST(gap_date AS STRING), ', ' ORDER BY gap_date LIMIT 5) as gap_dates_sample,
  MAX(impact_severity) as max_severity,
  CASE
    WHEN COUNT(DISTINCT gap_date) >= 3 THEN 'CRITICAL'
    WHEN COUNT(DISTINCT gap_date) >= 2 THEN 'HIGH'
    ELSE 'MEDIUM'
  END as contamination_level
FROM `nba_validation.cascade_impact_calculated`
GROUP BY affected_date
ORDER BY contamination_level DESC, affected_date;
```

---

## Phase 4: Generate Backfill Queue

### Step 4.1: Calculate Priority Scores

```sql
-- Generate prioritized backfill queue
CREATE OR REPLACE TABLE `nba_validation.backfill_queue_generated` AS
WITH gaps AS (
  SELECT
    game_date,
    MIN(phase) as earliest_phase,  -- Fix earliest phase first
    ARRAY_AGG(DISTINCT phase ORDER BY phase) as all_phases
  FROM `nba_validation.identified_gaps`
  GROUP BY game_date
),
cascade_counts AS (
  SELECT
    gap_date as game_date,
    COUNT(DISTINCT affected_date) as cascade_impact_count
  FROM `nba_validation.cascade_impact_calculated`
  GROUP BY gap_date
)
SELECT
  GENERATE_UUID() as queue_id,
  g.game_date,
  g.earliest_phase as phase_to_fix,
  g.all_phases as all_phases_to_rerun,
  -- Priority calculation
  (
    -- Recency factor (0.4 weight)
    CASE
      WHEN DATE_DIFF(CURRENT_DATE(), g.game_date, DAY) < 30 THEN 1.0
      WHEN DATE_DIFF(CURRENT_DATE(), g.game_date, DAY) < 60 THEN 0.7
      WHEN DATE_DIFF(CURRENT_DATE(), g.game_date, DAY) < 90 THEN 0.4
      ELSE 0.2
    END * 0.4
    +
    -- Cascade impact factor (0.3 weight)
    CASE
      WHEN COALESCE(c.cascade_impact_count, 0) >= 20 THEN 1.0
      WHEN COALESCE(c.cascade_impact_count, 0) >= 10 THEN 0.7
      WHEN COALESCE(c.cascade_impact_count, 0) >= 5 THEN 0.4
      ELSE 0.2
    END * 0.3
    +
    -- Phase severity factor (0.3 weight)
    CASE g.earliest_phase
      WHEN 'phase2' THEN 1.0
      WHEN 'phase3' THEN 0.8
      WHEN 'phase4' THEN 0.6
      ELSE 0.4
    END * 0.3
  ) as priority_score,
  -- Priority tier
  CASE
    WHEN DATE_DIFF(CURRENT_DATE(), g.game_date, DAY) < 14 AND g.earliest_phase = 'phase2' THEN 'P0'
    WHEN DATE_DIFF(CURRENT_DATE(), g.game_date, DAY) < 30 THEN 'P1'
    WHEN DATE_DIFF(CURRENT_DATE(), g.game_date, DAY) < 60 THEN 'P2'
    ELSE 'P3'
  END as priority_tier,
  DATE_DIFF(CURRENT_DATE(), g.game_date, DAY) as recency_days,
  TRUE as is_direct_gap,
  COALESCE(c.cascade_impact_count, 0) as cascade_impact_count,
  'PENDING' as backfill_status
FROM gaps g
LEFT JOIN cascade_counts c USING (game_date)
ORDER BY priority_score DESC;
```

### Step 4.2: Export Backfill Queue

```bash
# Export to JSON for processing
bq query --format=json --use_legacy_sql=false '
SELECT
  game_date,
  phase_to_fix,
  priority_tier,
  priority_score,
  cascade_impact_count
FROM `nba_validation.backfill_queue_generated`
WHERE backfill_status = "PENDING"
ORDER BY priority_score DESC
' > validation_results/backfill_queue.json
```

---

## Phase 5: Execute Backfills

### Step 5.1: Phase 2 Backfills (Raw Data)

Fix Phase 2 gaps first (oldest to newest):

```bash
# Get Phase 2 gap dates
P2_DATES=$(bq query --format=csv --use_legacy_sql=false '
SELECT game_date
FROM `nba_validation.backfill_queue_generated`
WHERE phase_to_fix = "phase2"
ORDER BY game_date
' | tail -n +2)

# Run Phase 2 backfill for each date
for DATE in $P2_DATES; do
  echo "Backfilling Phase 2 for $DATE"
  python bin/backfill/run_phase2_single.py --date $DATE
done
```

Or use the batch backfill:

```bash
# Batch Phase 2 backfill
python backfill_jobs/raw/bdl_player_boxscores/bdl_player_boxscores_raw_backfill.py \
  --start-date 2024-10-22 \
  --end-date 2026-01-25 \
  --only-missing
```

### Step 5.2: Phase 3 Backfills (Analytics)

After Phase 2 is complete:

```bash
# Run Phase 3 backfill
./bin/backfill/run_year_phase3.sh \
  --start-date 2024-10-22 \
  --end-date 2026-01-25 \
  --parallel
```

### Step 5.3: Verify Phase 3 Before Phase 4

```bash
# Verify Phase 3 is ready
python bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2024-10-22 \
  --end-date 2026-01-25 \
  --verbose
```

### Step 5.4: Phase 4 Backfills (Precompute)

After Phase 3 verification passes:

```bash
# Run Phase 4 backfill (respects dependency order)
./bin/backfill/run_phase4_backfill.sh \
  --start-date 2024-10-22 \
  --end-date 2026-01-25
```

### Step 5.5: Phase 5 Backfills (Predictions)

After Phase 4 is complete:

```bash
# Run Phase 5 prediction generation
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2024-10-22 \
  --end-date 2026-01-25
```

### Step 5.6: Phase 6 Backfills (Grading)

After Phase 5 is complete:

```bash
# Run grading backfill
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2024-10-22 \
  --end-date 2026-01-25
```

---

## Phase 6: Verification

### Step 6.1: Re-run Validation Scan

```bash
# Re-run full season scan
python bin/validation/daily_data_completeness.py \
  --start-date 2024-10-22 \
  --end-date 2026-01-25 \
  --output-format json \
  > validation_results/post_backfill_scan.json
```

### Step 6.2: Compare Before/After

```bash
# Compare gap counts
echo "Before backfill:"
jq '[.dates[] | select(.overall_status == "FAIL")] | length' validation_results/quick_scan_full_season.json

echo "After backfill:"
jq '[.dates[] | select(.overall_status == "FAIL")] | length' validation_results/post_backfill_scan.json
```

### Step 6.3: Update Backfill Status

```sql
-- Mark completed backfills
UPDATE `nba_validation.backfill_queue_generated`
SET
  backfill_status = 'COMPLETED',
  backfill_completed_at = CURRENT_TIMESTAMP()
WHERE game_date IN (
  -- Dates that now pass validation
  SELECT game_date
  FROM validation_post_backfill_results
  WHERE phase_status = 'PASS'
)
AND backfill_status = 'PENDING';
```

---

## Quick Reference Commands

### One-Liner: Full Validation Pipeline

```bash
# Run everything in sequence
cd /home/naji/code/nba-stats-scraper && \
source venv/bin/activate && \
mkdir -p validation_results && \
python bin/validation/daily_data_completeness.py --start-date 2024-10-22 --end-date 2026-01-25 --output-format json > validation_results/full_scan.json && \
echo "Scan complete. Review validation_results/full_scan.json"
```

### Check Specific Date

```bash
python bin/validation/comprehensive_health_check.py --date 2025-01-15
```

### Monitor Active Backfill

```bash
watch -n 60 './bin/backfill/monitor_backfill.sh 2024-10-22 2026-01-25'
```

### Emergency: Backfill Single Date All Phases

```bash
DATE="2025-01-15"
python backfill_jobs/raw/bdl_player_boxscores/bdl_player_boxscores_raw_backfill.py --date $DATE && \
python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py --start-date $DATE --end-date $DATE && \
./bin/backfill/run_phase4_backfill.sh --start-date $DATE --end-date $DATE
```

---

## Estimated Timeline

| Phase | Duration | Description |
|-------|----------|-------------|
| Discovery | 30 min | Quick scan + gap identification |
| Detailed Validation | 2-4 hours | Run all validators |
| Cascade Analysis | 30 min | BigQuery queries |
| Backfill Queue | 15 min | Generate priority queue |
| Phase 2 Backfill | 2-4 hours | Raw data recovery |
| Phase 3 Backfill | 4-6 hours | Analytics reprocessing |
| Phase 4 Backfill | 6-8 hours | Feature recomputation |
| Phase 5-6 Backfill | 2-4 hours | Predictions + grading |
| Verification | 1 hour | Final validation scan |
| **Total** | **18-28 hours** | Full season validation + repair |

## Notes

1. **Run during off-peak hours** - BigQuery costs and processor availability
2. **Monitor progress** - Use monitor_backfill.sh
3. **Checkpoint files** - Backfill jobs auto-resume from checkpoints
4. **Parallel execution** - Phase 3 analytics can run in parallel
5. **Sequential Phase 4** - Must respect dependency order (TDZA → PSZA → PCF → PDC → MLFS)
