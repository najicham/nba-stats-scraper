# Phase Validation Matrix

## Overview

This document defines exactly what to validate for each phase, including tables, expected record counts, quality thresholds, and validation queries.

## Phase 1: Scrapers (GCS Files)

### What to Validate

Check that scraped JSON files exist in GCS for each game date.

### GCS Bucket Paths

| Scraper | GCS Path Pattern |
|---------|------------------|
| nbac_gamebook | `gs://nba-scrapers-output/nbac_gamebook/{YYYY-MM-DD}/` |
| nbac_player_boxscore | `gs://nba-scrapers-output/nbac_player_boxscore/{YYYY-MM-DD}/` |
| bdl_boxscores | `gs://nba-scrapers-output/bdl_boxscores/{YYYY-MM-DD}/` |
| odds_api_props | `gs://nba-scrapers-output/odds_api_player_points_props/{YYYY-MM-DD}/` |
| espn_boxscore | `gs://nba-scrapers-output/espn_boxscore/{YYYY-MM-DD}/` |

### Validation Query

```bash
# Check GCS file existence for date range
gsutil ls -l gs://nba-scrapers-output/nbac_gamebook/2024-12-*/ | wc -l
```

### Expected Thresholds

| Metric | Threshold | Notes |
|--------|-----------|-------|
| Files exist | >= 1 file per game date | At least one scraper output |
| File size | > 0 bytes | Non-empty files |
| File count | >= 5 scrapers per date | All primary scrapers ran |

---

## Phase 2: Raw Processors (BigQuery nba_raw)

### What to Validate

Raw data tables have records for each game date.

### Primary Tables

| Table | Partition Field | Expected Records/Game |
|-------|-----------------|----------------------|
| `nbac_gamebook_player_stats` | `game_date` | 20-30 (10-15 per team) |
| `nbac_player_boxscores` | `game_date` | 20-30 |
| `nbac_team_boxscore` | `game_date` | 2 (home + away) |
| `bdl_player_boxscores` | `game_date` | 20-30 |
| `odds_api_player_points_props` | `game_date` | 15-25 (players with lines) |
| `nbac_schedule` | `game_date` | 1 per game |

### Validation Query

```sql
-- Phase 2 completeness check for date range
WITH schedule AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as games_expected
  FROM `nba_raw.nbac_schedule`
  WHERE season_year = 2024
    AND game_status = 'Final'
    AND game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date
),
phase2_counts AS (
  SELECT
    game_date,
    'nbac_gamebook_player_stats' as table_name,
    COUNT(*) as record_count
  FROM `nba_raw.nbac_gamebook_player_stats`
  WHERE game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date

  UNION ALL

  SELECT
    game_date,
    'nbac_player_boxscores' as table_name,
    COUNT(*) as record_count
  FROM `nba_raw.nbac_player_boxscores`
  WHERE game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date

  UNION ALL

  SELECT
    game_date,
    'bdl_player_boxscores' as table_name,
    COUNT(*) as record_count
  FROM `nba_raw.bdl_player_boxscores`
  WHERE game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date
)
SELECT
  s.game_date,
  s.games_expected,
  p.table_name,
  COALESCE(p.record_count, 0) as record_count,
  s.games_expected * 24 as expected_min,  -- 24 players per game (both teams)
  CASE
    WHEN COALESCE(p.record_count, 0) = 0 THEN 'FAIL'
    WHEN COALESCE(p.record_count, 0) < s.games_expected * 20 THEN 'WARN'
    ELSE 'PASS'
  END as status
FROM schedule s
LEFT JOIN phase2_counts p USING (game_date)
ORDER BY s.game_date, p.table_name
```

### Expected Thresholds

| Metric | Threshold | Status |
|--------|-----------|--------|
| Record count | >= 20 per game | PASS |
| Record count | 10-19 per game | WARN |
| Record count | < 10 per game | FAIL |
| Record count | 0 | FAIL (CRITICAL) |

---

## Phase 3: Analytics (BigQuery nba_analytics)

### What to Validate

Analytics tables derived from Phase 2 raw data.

### Primary Tables

| Table | Partition Field | Expected Records/Game | Quality Columns |
|-------|-----------------|----------------------|-----------------|
| `player_game_summary` | `game_date` | 20-30 | `completeness_pct`, `is_production_ready` |
| `team_offense_game_summary` | `game_date` | 2 | None |
| `team_defense_game_summary` | `game_date` | 2 | None |
| `upcoming_player_game_context` | `game_date` | 20-30 | `completeness_l10`, `completeness_l5` |
| `upcoming_team_game_context` | `game_date` | 2 | None |

### Validation Query

```sql
-- Phase 3 completeness and quality check
WITH schedule AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as games_expected
  FROM `nba_raw.nbac_schedule`
  WHERE season_year = 2024
    AND game_status = 'Final'
    AND game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date
),
pgs_quality AS (
  SELECT
    game_date,
    COUNT(*) as record_count,
    COUNTIF(is_production_ready = TRUE) as production_ready_count,
    AVG(completeness_pct) as avg_completeness,
    COUNTIF(completeness_pct >= 70) as high_quality_count
  FROM `nba_analytics.player_game_summary`
  WHERE game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date
)
SELECT
  s.game_date,
  s.games_expected,
  COALESCE(p.record_count, 0) as pgs_records,
  s.games_expected * 24 as pgs_expected_min,
  COALESCE(p.production_ready_count, 0) as production_ready,
  ROUND(COALESCE(p.avg_completeness, 0), 1) as avg_completeness_pct,
  CASE
    WHEN COALESCE(p.record_count, 0) = 0 THEN 'FAIL'
    WHEN COALESCE(p.production_ready_count, 0) / NULLIF(p.record_count, 0) < 0.70 THEN 'WARN'
    WHEN COALESCE(p.record_count, 0) < s.games_expected * 20 THEN 'WARN'
    ELSE 'PASS'
  END as status
FROM schedule s
LEFT JOIN pgs_quality p USING (game_date)
ORDER BY s.game_date
```

### Expected Thresholds

| Metric | Threshold | Status |
|--------|-----------|--------|
| Record count | >= 20 per game | PASS |
| Production ready % | >= 70% | PASS |
| Production ready % | 50-69% | WARN |
| Production ready % | < 50% | FAIL |
| Avg completeness | >= 70% | PASS |

---

## Phase 4: Precompute (BigQuery nba_precompute)

### What to Validate

Feature engineering tables with multi-window completeness tracking.

### Primary Tables

| Table | Partition Field | Expected Records/Game | Quality Columns |
|-------|-----------------|----------------------|-----------------|
| `team_defense_zone_analysis` | `game_date` | 2 | `sample_size` |
| `player_shot_zone_analysis` | `game_date` | 20-30 | `sample_size_l10`, `sample_size_l20` |
| `player_composite_factors` | `game_date` | 20-30 | `data_quality_tier` |
| `player_daily_cache` | `game_date` | 20-30 | `is_production_ready`, `completeness_l5`, `completeness_l10` |
| `ml_feature_store_v2` | `game_date` | 20-30 | `data_quality_tier`, `feature_completeness` |

### Validation Query

```sql
-- Phase 4 completeness and quality check
WITH schedule AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as games_expected
  FROM `nba_raw.nbac_schedule`
  WHERE season_year = 2024
    AND game_status = 'Final'
    AND game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date
),
mlfs_quality AS (
  SELECT
    game_date,
    COUNT(*) as record_count,
    COUNTIF(data_quality_tier = 'gold') as gold_count,
    COUNTIF(data_quality_tier = 'silver') as silver_count,
    COUNTIF(data_quality_tier = 'bronze') as bronze_count,
    AVG(feature_completeness) as avg_feature_completeness
  FROM `nba_precompute.ml_feature_store_v2`
  WHERE game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date
),
pdc_quality AS (
  SELECT
    game_date,
    COUNT(*) as record_count,
    COUNTIF(is_production_ready = TRUE) as production_ready_count,
    AVG(completeness_l10) as avg_completeness_l10
  FROM `nba_precompute.player_daily_cache`
  WHERE game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date
)
SELECT
  s.game_date,
  s.games_expected,
  -- ML Feature Store
  COALESCE(m.record_count, 0) as mlfs_records,
  COALESCE(m.gold_count, 0) as mlfs_gold,
  COALESCE(m.silver_count, 0) as mlfs_silver,
  COALESCE(m.bronze_count, 0) as mlfs_bronze,
  ROUND(COALESCE(m.avg_feature_completeness, 0), 1) as mlfs_avg_completeness,
  -- Player Daily Cache
  COALESCE(p.record_count, 0) as pdc_records,
  COALESCE(p.production_ready_count, 0) as pdc_production_ready,
  ROUND(COALESCE(p.avg_completeness_l10, 0), 1) as pdc_avg_completeness_l10,
  -- Overall Status
  CASE
    WHEN COALESCE(m.record_count, 0) = 0 THEN 'FAIL'
    WHEN COALESCE(m.gold_count, 0) + COALESCE(m.silver_count, 0) = 0 THEN 'FAIL'  -- All bronze
    WHEN COALESCE(m.gold_count, 0) / NULLIF(m.record_count, 0) < 0.30 THEN 'WARN'
    ELSE 'PASS'
  END as status
FROM schedule s
LEFT JOIN mlfs_quality m USING (game_date)
LEFT JOIN pdc_quality p USING (game_date)
ORDER BY s.game_date
```

### Expected Thresholds

| Metric | Threshold | Status |
|--------|-----------|--------|
| Record count | >= 20 per game | PASS |
| Gold tier % | >= 50% | PASS |
| Gold tier % | 30-49% | WARN |
| Gold tier % | < 30% | FAIL |
| All bronze tier | 100% bronze | FAIL (cascade issue) |

---

## Phase 5: Predictions (BigQuery nba_predictions)

### What to Validate

Prediction outputs from ML models.

### Primary Tables

| Table | Partition Field | Expected Records/Game | Quality Columns |
|-------|-----------------|----------------------|-----------------|
| `player_prop_predictions` | `game_date` | 10-25 | `confidence_score` |

### Validation Query

```sql
-- Phase 5 prediction coverage check
WITH schedule AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as games_expected
  FROM `nba_raw.nbac_schedule`
  WHERE season_year = 2024
    AND game_status = 'Final'
    AND game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date
),
prediction_counts AS (
  SELECT
    game_date,
    COUNT(*) as prediction_count,
    COUNT(DISTINCT player_id) as unique_players,
    COUNT(DISTINCT system_name) as systems_used,
    AVG(confidence_score) as avg_confidence
  FROM `nba_predictions.player_prop_predictions`
  WHERE game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date
)
SELECT
  s.game_date,
  s.games_expected,
  COALESCE(p.prediction_count, 0) as predictions,
  COALESCE(p.unique_players, 0) as unique_players,
  COALESCE(p.systems_used, 0) as systems_used,
  ROUND(COALESCE(p.avg_confidence, 0), 3) as avg_confidence,
  CASE
    WHEN COALESCE(p.prediction_count, 0) = 0 THEN 'FAIL'
    WHEN COALESCE(p.systems_used, 0) < 5 THEN 'WARN'  -- Expect 5 systems
    WHEN COALESCE(p.unique_players, 0) < s.games_expected * 8 THEN 'WARN'
    ELSE 'PASS'
  END as status
FROM schedule s
LEFT JOIN prediction_counts p USING (game_date)
ORDER BY s.game_date
```

### Expected Thresholds

| Metric | Threshold | Status |
|--------|-----------|--------|
| Predictions | > 0 | PASS (exists) |
| Systems used | = 5 | PASS (all systems) |
| Systems used | < 5 | WARN (missing system) |
| Unique players | >= 8 per game | PASS |

---

## Phase 6: Grading (BigQuery nba_predictions)

### What to Validate

Grading completeness - predictions matched with actual results.

### Primary Tables

| Table | Partition Field | Expected Records/Game |
|-------|-----------------|----------------------|
| `prediction_accuracy` | `game_date` | ~equal to predictions |

### Validation Query

```sql
-- Phase 6 grading coverage check
WITH predictions AS (
  SELECT
    game_date,
    COUNT(*) as prediction_count
  FROM `nba_predictions.player_prop_predictions`
  WHERE game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date
),
grading AS (
  SELECT
    game_date,
    COUNT(*) as graded_count,
    COUNTIF(prediction_correct IS NOT NULL) as has_result
  FROM `nba_predictions.prediction_accuracy`
  WHERE game_date BETWEEN @start_date AND @end_date
  GROUP BY game_date
)
SELECT
  p.game_date,
  p.prediction_count,
  COALESCE(g.graded_count, 0) as graded_count,
  ROUND(SAFE_DIVIDE(g.graded_count, p.prediction_count) * 100, 1) as grading_rate_pct,
  CASE
    WHEN COALESCE(g.graded_count, 0) = 0 THEN 'FAIL'
    WHEN SAFE_DIVIDE(g.graded_count, p.prediction_count) < 0.70 THEN 'WARN'
    ELSE 'PASS'
  END as status
FROM predictions p
LEFT JOIN grading g USING (game_date)
ORDER BY p.game_date
```

### Expected Thresholds

| Metric | Threshold | Status |
|--------|-----------|--------|
| Grading rate | >= 80% | PASS |
| Grading rate | 50-79% | WARN |
| Grading rate | < 50% | FAIL |
| Grading rate | 0% | FAIL (CRITICAL) |

---

## Validation Matrix Summary

| Phase | Primary Table | Key Metrics | PASS | WARN | FAIL |
|-------|---------------|-------------|------|------|------|
| 1 | GCS files | File existence | Files exist | Partial | No files |
| 2 | nbac_player_boxscore | Record count | >= 20/game | 10-19/game | < 10/game |
| 3 | player_game_summary | Production ready % | >= 70% | 50-69% | < 50% |
| 4 | ml_feature_store_v2 | Gold tier % | >= 50% | 30-49% | < 30% |
| 5 | player_prop_predictions | Systems count | = 5 | < 5 | = 0 |
| 6 | prediction_accuracy | Grading rate | >= 80% | 50-79% | < 50% |

## Bootstrap Period Exception

For dates Oct 22 - Nov 5, 2024 (first 14 days):
- Quality thresholds are relaxed
- `is_production_ready = FALSE` is acceptable
- Bronze tier is expected
- Mark as "BOOTSTRAP" not "FAIL"
