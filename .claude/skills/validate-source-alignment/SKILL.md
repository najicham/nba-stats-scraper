---
name: validate-source-alignment
description: Validate that upstream source data matches ml_feature_store_v2 in BigQuery
---

# /validate-source-alignment - Source Data Alignment Validation

Validate that upstream source data matches `ml_feature_store_v2` in BigQuery. Detect data flow bugs where source tables have data but the feature store shows defaults.

## Purpose

The feature store aggregates data from multiple upstream sources (Phase 3/4 tables). This skill detects **silent data flow failures** -- cases where source tables have valid data but the feature store used defaults instead. These bugs are invisible to aggregate quality scores and cause degraded prediction accuracy.

## Usage

```
/validate-source-alignment                    # Quick mode, today's date
/validate-source-alignment 2026-02-05         # Quick mode, specific date
/validate-source-alignment deep               # Deep mode, today's date
/validate-source-alignment deep 2026-02-05    # Deep mode, specific date
```

## Workflow

### Step 1: Parse Arguments

Determine the mode and target date from user input:

- **Mode**: `quick` (default) or `deep`
- **Date**: Specific date or `CURRENT_DATE()`

```bash
# Default values
MODE="quick"
TARGET_DATE="CURRENT_DATE()"

# Parse from user input:
# - If user says "deep" -> MODE="deep"
# - If user provides a date like "2026-02-05" -> TARGET_DATE="'2026-02-05'"
# - Otherwise use defaults
```

### Step 2: Run Checks

Run the checks for the selected mode. Print a header, then run each check sequentially.

```
=== Source Alignment Validation ===
Mode: quick | Date: 2026-02-06
===================================
```

---

## Quick Mode Checks (5 checks)

### Check 1: Coverage Alignment

**What it detects:** Source table has N players for a game date, but feature store has fewer than N.

```bash
bq query --use_legacy_sql=false "
WITH source_counts AS (
  -- Player daily cache (features 0-4: history)
  SELECT 'player_daily_cache' as source_table,
    COUNT(DISTINCT player_lookup) as source_players
  FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
  WHERE cache_date = ${TARGET_DATE}

  UNION ALL

  -- Player composite factors (features 5-8: composite)
  SELECT 'player_composite_factors' as source_table,
    COUNT(DISTINCT player_lookup) as source_players
  FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
  WHERE game_date = ${TARGET_DATE}

  UNION ALL

  -- Team defense zone analysis (features 13-14: defense)
  SELECT 'team_defense_zone_analysis' as source_table,
    COUNT(DISTINCT team_abbr) as source_players
  FROM \`nba-props-platform.nba_precompute.team_defense_zone_analysis\`
  WHERE analysis_date = ${TARGET_DATE}

  UNION ALL

  -- Raw odds tables (features 25-28: vegas player prop lines)
  -- Feature 25-28 source is odds_api + bettingpros, NOT upcoming_player_game_context.game_total
  SELECT 'odds_player_props' as source_table,
    COUNT(DISTINCT player_lookup) as source_players
  FROM (
    SELECT DISTINCT player_lookup
    FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
    WHERE game_date = ${TARGET_DATE}
      AND points_line IS NOT NULL AND points_line > 0
    UNION DISTINCT
    SELECT DISTINCT player_lookup
    FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
    WHERE game_date = ${TARGET_DATE}
      AND market_type = 'points'
      AND points_line IS NOT NULL AND points_line > 0
  )
),
feature_store AS (
  SELECT COUNT(DISTINCT player_lookup) as fs_players
  FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
  WHERE game_date = ${TARGET_DATE}
)
SELECT
  sc.source_table,
  sc.source_players,
  fs.fs_players as feature_store_players,
  ROUND(SAFE_DIVIDE(fs.fs_players, sc.source_players) * 100, 1) as coverage_pct,
  CASE
    WHEN sc.source_table IN ('player_daily_cache', 'player_composite_factors')
      THEN CASE
        WHEN SAFE_DIVIDE(fs.fs_players, sc.source_players) >= 0.98 THEN 'PASS'
        WHEN SAFE_DIVIDE(fs.fs_players, sc.source_players) >= 0.90 THEN 'WARN'
        ELSE 'FAIL'
      END
    WHEN sc.source_table = 'odds_player_props'
      THEN CASE
        WHEN SAFE_DIVIDE(fs.fs_players, sc.source_players) >= 0.85 THEN 'PASS'
        WHEN SAFE_DIVIDE(fs.fs_players, sc.source_players) >= 0.70 THEN 'WARN'
        ELSE 'FAIL'
      END
    ELSE 'INFO'
  END as status
FROM source_counts sc
CROSS JOIN feature_store fs
ORDER BY sc.source_table
"
```

**Thresholds:**

| Source | PASS | WARN | FAIL |
|--------|------|------|------|
| player_daily_cache | >= 98% | 90-97% | < 90% |
| player_composite_factors | >= 98% | 90-97% | < 90% |
| odds_player_props (vegas) | >= 85% | 70-84% | < 70% |
| team_defense_zone_analysis | INFO only (team-level, not player-level) |

---

### Check 2: Default-But-Exists Bugs (KEY BUG DETECTION)

**What it detects:** Feature store says `feature_N_source = 'default'` but the upstream source table actually has data for that player+date. This is the most critical check -- it catches silent data flow failures.

```bash
bq query --use_legacy_sql=false "
WITH default_features AS (
  -- Players with defaulted composite factors (features 5-8)
  SELECT
    fs.player_lookup,
    fs.game_date,
    'composite_factors (features 5-8)' as feature_group,
    fs.feature_5_source as source_tag
  FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\` fs
  WHERE fs.game_date = ${TARGET_DATE}
    AND fs.feature_5_source = 'default'

  UNION ALL

  -- Players with defaulted history (features 0-4)
  SELECT
    fs.player_lookup,
    fs.game_date,
    'player_history (features 0-4)' as feature_group,
    fs.feature_0_source as source_tag
  FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\` fs
  WHERE fs.game_date = ${TARGET_DATE}
    AND fs.feature_0_source = 'default'

  UNION ALL

  -- Players with defaulted vegas (features 25-28)
  SELECT
    fs.player_lookup,
    fs.game_date,
    'vegas (features 25-28)' as feature_group,
    fs.feature_25_source as source_tag
  FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\` fs
  WHERE fs.game_date = ${TARGET_DATE}
    AND fs.feature_25_source = 'default'
),
source_exists AS (
  -- Check if composite factors source actually has data
  SELECT DISTINCT player_lookup, game_date, 'composite_factors (features 5-8)' as feature_group
  FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
  WHERE game_date = ${TARGET_DATE}

  UNION ALL

  -- Check if player daily cache source actually has data
  SELECT DISTINCT player_lookup, cache_date as game_date, 'player_history (features 0-4)' as feature_group
  FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
  WHERE cache_date = ${TARGET_DATE}

  UNION ALL

  -- Check if vegas source actually has player prop lines
  -- Features 25-28 come from raw odds tables, not upcoming_player_game_context.game_total
  SELECT DISTINCT player_lookup, game_date, 'vegas (features 25-28)' as feature_group
  FROM (
    SELECT player_lookup, game_date
    FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
    WHERE game_date = ${TARGET_DATE}
      AND points_line IS NOT NULL AND points_line > 0
    UNION DISTINCT
    SELECT player_lookup, game_date
    FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
    WHERE game_date = ${TARGET_DATE}
      AND market_type = 'points'
      AND points_line IS NOT NULL AND points_line > 0
  )
)
SELECT
  df.feature_group,
  COUNT(*) as default_but_exists_count,
  CASE
    WHEN COUNT(*) = 0 THEN 'PASS'
    WHEN COUNT(*) <= 5 THEN 'WARN'
    ELSE 'FAIL'
  END as status
FROM default_features df
INNER JOIN source_exists se
  ON df.player_lookup = se.player_lookup
  AND df.game_date = se.game_date
  AND df.feature_group = se.feature_group
GROUP BY df.feature_group
ORDER BY default_but_exists_count DESC
"
```

**If bugs are found**, list the affected players:

```bash
bq query --use_legacy_sql=false "
-- Show specific players with default-but-exists bugs (top 20)
WITH default_composite AS (
  SELECT fs.player_lookup, fs.game_date
  FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\` fs
  WHERE fs.game_date = ${TARGET_DATE}
    AND fs.feature_5_source = 'default'
),
source_composite AS (
  SELECT DISTINCT player_lookup, game_date
  FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
  WHERE game_date = ${TARGET_DATE}
)
SELECT
  dc.player_lookup,
  'composite_factors' as source_table,
  'Feature store used default but source has data' as issue
FROM default_composite dc
INNER JOIN source_composite sc
  ON dc.player_lookup = sc.player_lookup AND dc.game_date = sc.game_date
LIMIT 20
"
```

**Thresholds:**

| default-but-exists count | Status |
|--------------------------|--------|
| 0 | PASS |
| 1-5 per date | WARN |
| > 5 per date | FAIL |

---

### Check 3: Prediction Coverage (Gamebook)

**What it detects:** Players who appeared in gamebook/boxscores but do not have predictions.

```bash
bq query --use_legacy_sql=false "
WITH gamebook_players AS (
  SELECT DISTINCT player_lookup
  FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
  WHERE game_date = ${TARGET_DATE}
    AND minutes IS NOT NULL
    AND SAFE_CAST(minutes AS FLOAT64) > 0
),
prediction_players AS (
  SELECT DISTINCT player_lookup
  FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
  WHERE game_date = ${TARGET_DATE}
    AND system_id = 'catboost_v9'
    AND is_active = TRUE
)
SELECT
  (SELECT COUNT(*) FROM gamebook_players) as gamebook_players,
  (SELECT COUNT(*) FROM prediction_players) as prediction_players,
  (SELECT COUNT(*) FROM gamebook_players g
   INNER JOIN prediction_players p ON g.player_lookup = p.player_lookup) as matched,
  (SELECT COUNT(*) FROM gamebook_players g
   LEFT JOIN prediction_players p ON g.player_lookup = p.player_lookup
   WHERE p.player_lookup IS NULL) as missing_predictions,
  ROUND(SAFE_DIVIDE(
    (SELECT COUNT(*) FROM gamebook_players g
     INNER JOIN prediction_players p ON g.player_lookup = p.player_lookup),
    (SELECT COUNT(*) FROM gamebook_players)
  ) * 100, 1) as coverage_pct,
  CASE
    WHEN SAFE_DIVIDE(
      (SELECT COUNT(*) FROM gamebook_players g
       INNER JOIN prediction_players p ON g.player_lookup = p.player_lookup),
      (SELECT COUNT(*) FROM gamebook_players)
    ) >= 0.95 THEN 'PASS'
    WHEN SAFE_DIVIDE(
      (SELECT COUNT(*) FROM gamebook_players g
       INNER JOIN prediction_players p ON g.player_lookup = p.player_lookup),
      (SELECT COUNT(*) FROM gamebook_players)
    ) >= 0.85 THEN 'WARN'
    ELSE 'FAIL'
  END as status
"
```

**Note:** This check is most useful for past dates where gamebook data exists. For today (pre-game), gamebook data may not be available yet -- in that case, this check will return 0 gamebook players and should be treated as INFO/SKIP.

**Thresholds:**

| Coverage | Status |
|----------|--------|
| >= 95% | PASS |
| 85-94% | WARN |
| < 85% | FAIL |

---

### Check 4: Prediction Coverage (Prop Lines)

**What it detects:** Players with `current_points_line` in `upcoming_player_game_context` should have predictions with `current_points_line IS NOT NULL`.

```bash
bq query --use_legacy_sql=false "
WITH prop_line_players AS (
  SELECT DISTINCT player_lookup
  FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
  WHERE game_date = ${TARGET_DATE}
    AND current_points_line IS NOT NULL
),
prediction_with_lines AS (
  SELECT DISTINCT player_lookup
  FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
  WHERE game_date = ${TARGET_DATE}
    AND system_id = 'catboost_v9'
    AND is_active = TRUE
    AND current_points_line IS NOT NULL
)
SELECT
  (SELECT COUNT(*) FROM prop_line_players) as players_with_prop_lines,
  (SELECT COUNT(*) FROM prediction_with_lines) as predictions_with_lines,
  (SELECT COUNT(*) FROM prop_line_players p
   INNER JOIN prediction_with_lines pr ON p.player_lookup = pr.player_lookup) as matched,
  (SELECT COUNT(*) FROM prop_line_players p
   LEFT JOIN prediction_with_lines pr ON p.player_lookup = pr.player_lookup
   WHERE pr.player_lookup IS NULL) as missing_line_predictions,
  ROUND(SAFE_DIVIDE(
    (SELECT COUNT(*) FROM prop_line_players p
     INNER JOIN prediction_with_lines pr ON p.player_lookup = pr.player_lookup),
    (SELECT COUNT(*) FROM prop_line_players)
  ) * 100, 1) as coverage_pct,
  CASE
    WHEN SAFE_DIVIDE(
      (SELECT COUNT(*) FROM prop_line_players p
       INNER JOIN prediction_with_lines pr ON p.player_lookup = pr.player_lookup),
      (SELECT COUNT(*) FROM prop_line_players)
    ) >= 0.98 THEN 'PASS'
    WHEN SAFE_DIVIDE(
      (SELECT COUNT(*) FROM prop_line_players p
       INNER JOIN prediction_with_lines pr ON p.player_lookup = pr.player_lookup),
      (SELECT COUNT(*) FROM prop_line_players)
    ) >= 0.90 THEN 'WARN'
    ELSE 'FAIL'
  END as status
"
```

**Thresholds:**

| Coverage | Status |
|----------|--------|
| >= 98% | PASS |
| 90-97% | WARN |
| < 90% | FAIL |

---

### Check 5: Quick Default Summary

**What it detects:** Overall default feature usage -- how many players are relying on defaults for each feature category.

```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_rows,
  COUNTIF(feature_0_source = 'default') as history_defaults,
  COUNTIF(feature_5_source = 'default') as composite_defaults,
  COUNTIF(feature_13_source = 'default') as defense_defaults,
  COUNTIF(feature_25_source = 'default') as vegas_defaults,
  ROUND(AVG(default_feature_count), 1) as avg_default_count,
  ROUND(AVG(feature_quality_score), 1) as avg_quality_score,
  ROUND(AVG(matchup_quality_pct), 1) as avg_matchup_quality,
  COUNTIF(quality_alert_level = 'red') as red_alerts
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date = ${TARGET_DATE}
"
```

---

## Deep Mode Checks (Additional)

Deep mode runs all quick checks PLUS the following additional checks.

### Check 6: Value Comparison (Feature Values vs Source)

**What it detects:** Feature values in the store that diverge from source values by more than 0.1. Catches transformation bugs or stale cache reads.

```bash
bq query --use_legacy_sql=false "
-- Compare feature 0 (avg_points from player history) against source
WITH feature_store AS (
  SELECT player_lookup, game_date,
    features[OFFSET(0)] as fs_avg_points,
    features[OFFSET(5)] as fs_fatigue_factor,
    features[OFFSET(25)] as fs_game_total
  FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
  WHERE game_date = ${TARGET_DATE}
    AND feature_0_source != 'default'
),
source_cache AS (
  SELECT player_lookup, cache_date as game_date,
    avg_points as src_avg_points
  FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
  WHERE cache_date = ${TARGET_DATE}
),
source_composite AS (
  SELECT player_lookup, game_date,
    fatigue_factor as src_fatigue_factor
  FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
  WHERE game_date = ${TARGET_DATE}
),
source_vegas AS (
  SELECT player_lookup, game_date,
    game_total as src_game_total
  FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
  WHERE game_date = ${TARGET_DATE}
    AND game_total IS NOT NULL
)
SELECT
  'feature_0 (avg_points)' as feature,
  COUNT(*) as compared,
  COUNTIF(ABS(fs.fs_avg_points - sc.src_avg_points) > 0.1) as mismatches,
  ROUND(SAFE_DIVIDE(COUNTIF(ABS(fs.fs_avg_points - sc.src_avg_points) > 0.1), COUNT(*)) * 100, 1) as mismatch_pct,
  CASE
    WHEN SAFE_DIVIDE(COUNTIF(ABS(fs.fs_avg_points - sc.src_avg_points) > 0.1), COUNT(*)) < 0.02 THEN 'PASS'
    WHEN SAFE_DIVIDE(COUNTIF(ABS(fs.fs_avg_points - sc.src_avg_points) > 0.1), COUNT(*)) <= 0.05 THEN 'WARN'
    ELSE 'FAIL'
  END as status
FROM feature_store fs
JOIN source_cache sc ON fs.player_lookup = sc.player_lookup AND fs.game_date = sc.game_date

UNION ALL

SELECT
  'feature_5 (fatigue_factor)' as feature,
  COUNT(*) as compared,
  COUNTIF(ABS(fs.fs_fatigue_factor - scomp.src_fatigue_factor) > 0.1) as mismatches,
  ROUND(SAFE_DIVIDE(COUNTIF(ABS(fs.fs_fatigue_factor - scomp.src_fatigue_factor) > 0.1), COUNT(*)) * 100, 1) as mismatch_pct,
  CASE
    WHEN SAFE_DIVIDE(COUNTIF(ABS(fs.fs_fatigue_factor - scomp.src_fatigue_factor) > 0.1), COUNT(*)) < 0.02 THEN 'PASS'
    WHEN SAFE_DIVIDE(COUNTIF(ABS(fs.fs_fatigue_factor - scomp.src_fatigue_factor) > 0.1), COUNT(*)) <= 0.05 THEN 'WARN'
    ELSE 'FAIL'
  END as status
FROM feature_store fs
JOIN source_composite scomp ON fs.player_lookup = scomp.player_lookup AND fs.game_date = scomp.game_date
"
```

**Thresholds:**

| Mismatch rate | Status |
|---------------|--------|
| < 2% | PASS |
| 2-5% | WARN |
| > 5% | FAIL |

---

### Check 7: Freshness Comparison

**What it detects:** Feature store data is stale relative to source table timestamps. Catches cases where the feature store was built before the latest source data was available.

```bash
bq query --use_legacy_sql=false "
WITH fs_freshness AS (
  SELECT
    MAX(created_at) as fs_latest,
    COUNT(*) as fs_rows
  FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
  WHERE game_date = ${TARGET_DATE}
),
source_freshness AS (
  SELECT
    'player_daily_cache' as source_table,
    MAX(updated_at) as source_latest,
    COUNT(*) as source_rows
  FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
  WHERE cache_date = ${TARGET_DATE}

  UNION ALL

  SELECT
    'player_composite_factors' as source_table,
    MAX(created_at) as source_latest,
    COUNT(*) as source_rows
  FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
  WHERE game_date = ${TARGET_DATE}

  UNION ALL

  SELECT
    'upcoming_player_game_context' as source_table,
    MAX(updated_at) as source_latest,
    COUNT(*) as source_rows
  FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
  WHERE game_date = ${TARGET_DATE}
)
SELECT
  sf.source_table,
  sf.source_latest,
  fs.fs_latest as feature_store_latest,
  TIMESTAMP_DIFF(sf.source_latest, fs.fs_latest, MINUTE) as source_newer_by_minutes,
  CASE
    WHEN sf.source_latest <= fs.fs_latest THEN 'PASS'
    WHEN TIMESTAMP_DIFF(sf.source_latest, fs.fs_latest, MINUTE) <= 30 THEN 'WARN'
    ELSE 'FAIL'
  END as status
FROM source_freshness sf
CROSS JOIN fs_freshness fs
ORDER BY source_newer_by_minutes DESC
"
```

**Interpretation:**
- `source_newer_by_minutes > 0` means the source was updated AFTER the feature store was built
- `FAIL` if source is >30 min newer than the feature store (data was missed)
- `WARN` if source is 1-30 min newer (might be a race condition)

---

## Output Format

After running all checks, print an actionable summary:

```
=== Source Alignment Summary ===
Date: 2026-02-06 | Mode: quick

Check 1 - Coverage Alignment:         PASS
Check 2 - Default-But-Exists Bugs:    FAIL (3 composite, 1 history)
Check 3 - Prediction Coverage (GB):   PASS (97.2%)
Check 4 - Prediction Coverage (Lines): PASS (99.1%)
Check 5 - Default Summary:            WARN (avg 2.3 defaults)
[Deep only]
Check 6 - Value Comparison:           PASS
Check 7 - Freshness:                  WARN (cache 12 min stale)

Overall: WARN - 1 FAIL, 1 WARN detected

=== Action Items ===
1. FAIL: Check 2 found 3 players with composite factor defaults despite source data existing.
   -> Investigate PlayerCompositeFactorsProcessor for these players
   -> Run: SELECT * FROM nba_precompute.player_composite_factors WHERE game_date = '2026-02-06' AND player_lookup IN (...)
2. WARN: Check 5 shows avg 2.3 default features per row. Monitor for increase.
```

## Troubleshooting

| Issue Found | Root Cause | Fix |
|-------------|-----------|-----|
| default-but-exists bugs (composite) | PlayerCompositeFactorsProcessor didn't pick up all players | Check processor logs, re-run Phase 4 |
| default-but-exists bugs (history) | player_daily_cache stale or JOIN mismatch | Check cache_date vs game_date alignment |
| default-but-exists bugs (vegas) | Raw odds tables have prop lines but feature store defaulted | Check FeatureExtractor._batch_extract_vegas_lines() cache population |
| Low coverage alignment | Feature store built before source finished | Check Phase 4/5 timing, may need re-run |
| Value mismatches > 5% | Transformation bug or stale cache | Compare specific player values, check code |
| Source newer than feature store | Race condition in pipeline | Re-generate predictions to pick up latest data |
| Low gamebook prediction coverage | Players not in registry or filtered out | Check universal player registry coverage |
| Low prop line prediction coverage | Lines arrived after predictions generated | Re-run predictions with REAL_LINES_ONLY |

## Related Skills

- `/spot-check-features` - Validate feature store quality distributions
- `/validate-daily` - Full pipeline health validation
- `/hit-rate-analysis` - Check if data quality issues affect hit rates
