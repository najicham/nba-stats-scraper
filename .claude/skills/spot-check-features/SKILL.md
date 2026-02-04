---
name: spot-check-features
description: Validate feature store data quality before model training
---

# Spot Check Features Skill

Validate ML Feature Store data quality to ensure model training uses clean data.

## Trigger
- Before running `/model-experiment`
- User asks "is feature store data good?"
- User types `/spot-check-features`
- "Check feature quality", "Validate training data"

## Quick Start

```bash
# Check last 7 days of feature data
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(feature_quality_score >= 85) as high_quality,
  COUNTIF(feature_quality_score >= 70 AND feature_quality_score < 85) as medium_quality,
  COUNTIF(feature_quality_score < 70) as low_quality,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  data_source,
  COUNTIF(features[OFFSET(25)] > 0) as has_vegas_line
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND feature_count >= 37
GROUP BY game_date, data_source
ORDER BY game_date DESC"
```

## Validation Checks

### 1. Quality Score Distribution

**Healthy:** >80% records have quality_score >= 70

```sql
SELECT
  CASE
    WHEN feature_quality_score >= 85 THEN 'High (85+)'
    WHEN feature_quality_score >= 70 THEN 'Medium (70-84)'
    ELSE 'Low (<70)'
  END as quality_tier,
  COUNT(*) as records,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND feature_count >= 37
GROUP BY 1
ORDER BY 1
```

### 2. Vegas Line Coverage

**Healthy:** >90% records have Vegas lines for recent dates

```sql
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(features[OFFSET(25)] > 0) as has_vegas,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND feature_count >= 37
GROUP BY 1
ORDER BY 1 DESC
```

### 3. Data Source Distribution

**Healthy:** <5% partial data, <10% early season data

```sql
SELECT
  data_source,
  COUNT(*) as records,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND feature_count >= 37
GROUP BY 1
ORDER BY records DESC
```

### 4. Feature Completeness

**Healthy:** All 37 features populated (feature_count = 37)

```sql
SELECT
  feature_count,
  COUNT(*) as records
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1
ORDER BY 1
```

### 5. Rolling Average Staleness

**Healthy:** points_avg_last_5 > 0 for most records

```sql
SELECT
  game_date,
  COUNTIF(features[OFFSET(0)] = 0) as missing_points_avg,
  COUNTIF(features[OFFSET(31)] = 0) as missing_minutes_avg,
  COUNT(*) as total
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND feature_count >= 37
GROUP BY 1
ORDER BY 1 DESC
```

### 6. Vegas Line Coverage by Player Tier (Session 103)

**Critical for training data quality.** Sportsbooks don't offer props for most bench players.
Training data should have balanced coverage or tier-aware model features.

```sql
-- Check Vegas line coverage by tier
SELECT
  CASE
    WHEN pgs.points >= 25 THEN 'star'
    WHEN pgs.points >= 15 THEN 'starter'
    WHEN pgs.points >= 5 THEN 'role'
    ELSE 'bench'
  END as tier,
  COUNT(*) as n,
  ROUND(AVG(CASE WHEN f.features[OFFSET(25)] > 0 THEN 1 ELSE 0 END) * 100, 1) as pct_has_vegas,
  ROUND(AVG(CASE WHEN f.features[OFFSET(29)] > 0 THEN 1 ELSE 0 END) * 100, 1) as pct_has_matchup
FROM nba_predictions.ml_feature_store_v2 f
JOIN nba_analytics.player_game_summary pgs
  ON f.player_lookup = pgs.player_lookup AND f.game_date = pgs.game_date
WHERE f.game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY) AND DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND f.feature_count >= 33
GROUP BY 1
ORDER BY 1
```

**Expected (based on sportsbook behavior):**
| Tier | Vegas Coverage | Matchup Coverage |
|------|----------------|------------------|
| Star | ~95% | ~85% |
| Starter | ~90% | ~80% |
| Role | ~40% | ~30% |
| Bench | ~15% | ~10% |

**Why this matters:** If model trains mostly on players WITH vegas lines (stars), it learns
"vegas line → scoring" but can't generalize to players without lines. This causes
regression-to-mean bias.

### 7. Vegas Line Bias Check (Session 103)

**Vegas lines themselves are biased.** Sportsbooks set conservative lines.

```sql
-- Check if Vegas lines match actual scoring by tier
SELECT
  CASE
    WHEN pgs.points >= 25 THEN 'star'
    WHEN pgs.points >= 15 THEN 'starter'
    WHEN pgs.points >= 5 THEN 'role'
    ELSE 'bench'
  END as tier,
  COUNT(*) as n,
  ROUND(AVG(f.features[OFFSET(25)]), 1) as avg_vegas_line,
  ROUND(AVG(pgs.points), 1) as avg_actual,
  ROUND(AVG(f.features[OFFSET(25)]) - AVG(pgs.points), 1) as vegas_bias
FROM nba_predictions.ml_feature_store_v2 f
JOIN nba_analytics.player_game_summary pgs
  ON f.player_lookup = pgs.player_lookup AND f.game_date = pgs.game_date
WHERE f.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND f.features[OFFSET(25)] > 0
GROUP BY 1
ORDER BY 1
```

**Expected:** Vegas under-predicts stars by ~8 pts, over-predicts bench by ~5 pts.
This is intentional by sportsbooks but causes model bias if not accounted for.

## Quality Thresholds

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Avg Quality Score | >= 80 | 70-79 | < 70 |
| High Quality % | >= 70% | 50-69% | < 50% |
| Vegas Coverage | >= 40% | 30-39% | < 30% |
| Partial Data % | < 5% | 5-10% | > 10% |
| Early Season % | < 10% | 10-20% | > 20% |

**Note on Vegas Coverage (Session 103):** 40% is realistic because sportsbooks don't
offer props for bench players. The key is ensuring BALANCED coverage by tier, not
forcing 90%+ overall coverage.

## Training Data Recommendations

Based on Session 103 investigation, model bias occurs when:
1. **Tier imbalance:** Stars have high Vegas coverage, bench has low → model learns "Vegas = high scorer"
2. **Vegas line following:** Model follows Vegas too closely instead of learning to diverge
3. **Missing data pattern:** Model can't distinguish "missing because bench player" vs "missing because data issue"

**Solutions:**
- Add `scoring_tier` as categorical training feature
- Filter training data to quality_score >= 70
- Consider separate models per tier or tier-aware weighting

### 8. Full Season Audit (Session 107)

**Run this to find ALL bad records in the entire season:**

```sql
-- FULL SEASON AUDIT: Find all potentially bad records
SELECT
  'Bad Default (L5=10, L10>15)' as issue_type,
  COUNT(*) as records,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-01'
  AND features[OFFSET(0)] = 10.0
  AND features[OFFSET(1)] > 15

UNION ALL

SELECT
  'Zero fatigue_score' as issue_type,
  COUNT(*) as records,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-01'
  AND features[OFFSET(5)] = 0.0

UNION ALL

SELECT
  'L5 much higher than L10 (>10 diff)' as issue_type,
  COUNT(*) as records,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-01'
  AND (features[OFFSET(0)] - features[OFFSET(1)]) > 10

ORDER BY records DESC
```

**Expected results (as of Session 107 audit):**
- Bad Default: ~15 records (Nov 4-9 cold start + rare late season)
- Zero fatigue: 0 (would indicate bug)
- L5 > L10: ~5 (usually legitimate hot streaks)

**If Bad Default > 20 or Zero fatigue > 0, investigate immediately!**

**Get details on bad records:**
```sql
SELECT game_date, player_lookup,
  ROUND(features[OFFSET(0)], 1) as pts_avg_l5,
  ROUND(features[OFFSET(1)], 1) as pts_avg_l10,
  ROUND(features[OFFSET(2)], 1) as pts_avg_season
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-01'
  AND features[OFFSET(0)] = 10.0 AND features[OFFSET(1)] > 15
ORDER BY game_date
```

### 9. DNP Handling Validation (Session 113)

**CRITICAL:** Verify L5/L10 calculations exclude DNP games correctly.
Session 113 discovered Phase 3 fallback was converting NULL points to 0, causing
10-25 point errors for stars with frequent DNPs (Kawhi, Jokic, Curry).

```sql
-- Validate L5 calculation matches manual for star players
WITH manual_calc AS (
  SELECT
    player_lookup,
    game_date,
    ROUND(AVG(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
    ), 1) as manual_l5
  FROM nba_analytics.player_game_summary
  WHERE game_date >= CURRENT_DATE() - 30
    AND points IS NOT NULL  -- Exclude DNPs
),
feature_values AS (
  SELECT
    player_lookup,
    game_date,
    ROUND(features[OFFSET(0)], 1) as ml_l5,
    data_source
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date >= CURRENT_DATE() - 7
)
SELECT
  f.player_lookup,
  f.game_date,
  f.ml_l5,
  m.manual_l5,
  ROUND(ABS(f.ml_l5 - m.manual_l5), 1) as diff,
  f.data_source
FROM feature_values f
JOIN manual_calc m
  ON f.player_lookup = m.player_lookup
  AND f.game_date = m.game_date
WHERE ABS(f.ml_l5 - m.manual_l5) > 3  -- Flag >3pt errors
ORDER BY diff DESC
LIMIT 20;
```

**Expected:** All diff < 1.0 after Session 113 fix.
**If diff > 3:** DNP bug may have recurred - check feature_extractor.py Phase 3 fallback.

### 10. Unmarked DNP Detection (Session 113)

**Data quality issue:** Some games have NULL points but is_dnp = NULL (should be TRUE).
These pollute L5/L10 calculations if not properly filtered.

```sql
-- Find games that look like DNPs but aren't marked
SELECT
  game_date,
  player_lookup,
  points,
  minutes_played,
  is_dnp,
  dnp_reason,
  team_abbr
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 30
  AND (
    (points = 0 AND minutes_played IS NULL AND is_dnp IS NULL)
    OR (points IS NULL AND minutes_played IS NULL AND is_dnp IS NULL)
  )
ORDER BY game_date DESC
LIMIT 50;
```

**Expected:** 0 records (all DNPs properly marked).
**If found:** Upstream data issue - notify scraper team to fix is_dnp marking.

### 11. Player Daily Cache Reconciliation (Session 113)

**Validate that player_daily_cache matches manual calculations.**

```sql
-- Spot check 10 random star players
WITH star_sample AS (
  SELECT DISTINCT player_lookup
  FROM nba_precompute.player_daily_cache
  WHERE cache_date = CURRENT_DATE() - 1
    AND points_avg_last_5 > 20
  ORDER BY RAND()
  LIMIT 10
),
manual_calc AS (
  SELECT
    player_lookup,
    ROUND(AVG(points), 1) as manual_l5
  FROM (
    SELECT
      player_lookup,
      points,
      ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
    FROM nba_analytics.player_game_summary
    WHERE game_date < CURRENT_DATE() - 1
      AND points IS NOT NULL
  )
  WHERE rn <= 5
  GROUP BY player_lookup
)
SELECT
  c.player_lookup,
  ROUND(c.points_avg_last_5, 1) as cache_l5,
  m.manual_l5,
  ROUND(ABS(c.points_avg_last_5 - m.manual_l5), 1) as diff
FROM nba_precompute.player_daily_cache c
JOIN manual_calc m ON c.player_lookup = m.player_lookup
WHERE c.cache_date = CURRENT_DATE() - 1
  AND c.player_lookup IN (SELECT player_lookup FROM star_sample)
ORDER BY diff DESC;
```

**Expected:** All diff < 1.0
**If diff > 3:** Bug in player_daily_cache StatsAggregator - investigate Phase 4 processor.

### 12. Phase 4 DNP Pollution Check (Session 113+)

**CRITICAL:** Verify player_daily_cache excludes DNP games correctly.
Session 113+ audit found Nov 1 - Dec 2, 2025 had 100% DNP pollution in cached L5/L10 values.

```sql
-- Verify player_daily_cache excludes DNP games
SELECT
  cache_date,
  COUNT(*) as total_cached,
  COUNTIF(is_dnp_in_source) as dnp_players_cached,
  ROUND(100.0 * COUNTIF(is_dnp_in_source) / COUNT(*), 1) as dnp_pct
FROM (
  SELECT
    pdc.cache_date,
    pdc.player_lookup,
    BOOL_OR(pgs.is_dnp = TRUE) as is_dnp_in_source
  FROM nba_precompute.player_daily_cache pdc
  JOIN nba_analytics.player_game_summary pgs
    ON pdc.player_lookup = pgs.player_lookup
    AND pgs.game_date = pdc.cache_date
  WHERE pdc.cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY pdc.cache_date, pdc.player_lookup
)
GROUP BY cache_date
ORDER BY cache_date DESC
```

**Expected:** dnp_pct = 0% (no DNP players should be in cache)
**If > 0%:** CRITICAL - Phase 4 DNP filter broken, investigate player_daily_cache processor

### 13. Team Pace Outlier Detection (Session 113+)

**CRITICAL:** Detect team pace corruption in Phase 4 cache.
Session 113+ audit found Dec 30, 2025 had team_pace values of 200+ (normal is 95-110).

```sql
-- Detect team pace outliers in player_daily_cache
SELECT
  cache_date,
  COUNT(*) as records,
  MIN(team_pace_last_10) as min_pace,
  MAX(team_pace_last_10) as max_pace,
  COUNTIF(team_pace_last_10 < 80 OR team_pace_last_10 > 120) as outliers,
  ROUND(100.0 * COUNTIF(team_pace_last_10 < 80 OR team_pace_last_10 > 120) / COUNT(*), 1) as outlier_pct
FROM nba_precompute.player_daily_cache
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY cache_date
HAVING outliers > 0
ORDER BY cache_date DESC
```

**Expected:** 0 outliers (all team_pace 80-120 range)
**If outliers found:** CRITICAL - Source data corruption or Phase 3 calculation bug

### 14. DNP Players in Cache (Session 113+)

**HIGH:** Find DNP players incorrectly cached in Phase 4.
After DNP filter added Feb 3, 2026, historical dates (Dec 18 - Feb 2) still had DNP players cached.

```sql
-- Find DNP players incorrectly cached
SELECT
  pdc.cache_date,
  COUNT(*) as dnp_players_cached,
  ARRAY_AGG(STRUCT(pdc.player_lookup, pgs.dnp_reason) LIMIT 5) as examples
FROM nba_precompute.player_daily_cache pdc
JOIN nba_analytics.player_game_summary pgs
  ON pdc.player_lookup = pgs.player_lookup
  AND pdc.cache_date = pgs.game_date
WHERE pdc.cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND pgs.is_dnp = TRUE
GROUP BY pdc.cache_date
HAVING COUNT(*) > 0
ORDER BY pdc.cache_date DESC
```

**Expected:** 0 DNP players cached
**If > 0:** HIGH - Cache includes DNP players, needs regeneration or filter fix

### 15. Early Season Bootstrap Coverage (Session 113+)

**MEDIUM:** Validate upstream dependency coverage during bootstrap period.
Shot_zone analysis requires 10 games of history, causing incomplete coverage in first 2-3 weeks of season.

```sql
-- Check shot_zone coverage and identify bootstrap period
WITH season_start AS (
  SELECT MIN(game_date) as start_date
  FROM nba_analytics.player_game_summary
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 120 DAY)
),
coverage AS (
  SELECT
    pdc.cache_date,
    COUNT(*) as total_cache_records,
    COUNT(DISTINCT psz.player_lookup) as players_with_shot_zone,
    ROUND(100.0 * COUNT(DISTINCT psz.player_lookup) / COUNT(*), 1) as shot_zone_pct,
    DATE_DIFF(pdc.cache_date, s.start_date, DAY) as days_into_season,
    CASE
      WHEN DATE_DIFF(pdc.cache_date, s.start_date, DAY) <= 21 THEN 'BOOTSTRAP'
      ELSE 'NORMAL'
    END as period_type
  FROM nba_precompute.player_daily_cache pdc
  CROSS JOIN season_start s
  LEFT JOIN nba_precompute.player_shot_zone_analysis psz
    ON pdc.player_lookup = psz.player_lookup
    AND pdc.cache_date = psz.analysis_date
  WHERE pdc.cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY pdc.cache_date, s.start_date
)
SELECT
  cache_date,
  total_cache_records,
  players_with_shot_zone,
  shot_zone_pct,
  days_into_season,
  period_type,
  CASE
    WHEN period_type = 'BOOTSTRAP' AND shot_zone_pct < 50 THEN 'OK (early season)'
    WHEN period_type = 'NORMAL' AND shot_zone_pct < 90 THEN 'WARNING (should be >90%)'
    ELSE 'OK'
  END as status
FROM coverage
ORDER BY cache_date DESC
```

**Expected Coverage by Season Day (Session 113+ Fix Applied):**

After implementing dynamic threshold (commit e06043b9), expected coverage:

| Days Into Season | Min Games Required | Expected Coverage |
|------------------|--------------------|-------------------|
| Days 1-6 | 3-4 games | 0-30% (very early) |
| Days 7-14 | 4-6 games | 30-60% (building) |
| Days 15-21 | 7-9 games | 60-85% (approaching full) |
| Days 22+ | 10 games | >90% (full coverage) |

**Interpretation:**
- Bootstrap period (days 0-21): Coverage gradually increases - THIS IS EXPECTED
- Normal period (days 22+): >90% coverage required
- If actual coverage significantly below expected for day range: WARNING

**If low coverage after day 21:** WARNING - player_shot_zone_analysis may not be running or has data quality issues

**Context:** Session 113+ investigation found ML feature store failures on Nov 4-6 due to missing shot_zone data. Root cause: Hard 10-game requirement when players had only 4-7 games. Fixed with dynamic threshold that adapts to days into season while maintaining quality flags.

## Pre-Training Checklist

Before running `/model-experiment`:

1. Run quality distribution check (target: >80% quality >= 70)
2. Check Vegas line coverage by tier (not overall - expect 40% for bench, 95% for stars)
3. Verify Vegas bias by tier (expect stars under-predicted ~8pts)
4. Check for unusual data source distribution (<5% partial)
5. Confirm model experiment includes tier bias analysis (built-in since Session 104)
6. **NEW (Session 113):** Validate L5/L10 calculations match manual (DNP handling check #9)
7. **NEW (Session 113):** Check for unmarked DNPs in source data (check #10)
8. **CRITICAL (Session 113+):** Verify no DNP pollution in Phase 4 cache (check #12)
9. **CRITICAL (Session 113+):** Check team pace outliers (check #13)
10. **HIGH (Session 113+):** Verify no DNP players in cache (check #14)
11. **MEDIUM (Session 113+):** Check early season bootstrap coverage (check #15)

## Example Output

```
=== Feature Store Quality Report ===
Date Range: 2026-01-20 to 2026-02-03

Quality Distribution:
  High (85+):   12,450 (78.2%)
  Medium (70-84): 2,890 (18.1%)
  Low (<70):      590 (3.7%)

Vegas Coverage: 94.2%
Partial Data: 0.5%
Early Season: 2.1%

Status: GOOD - Ready for model training
```

## Related Skills

- `/model-experiment` - Train challenger models
- `/validate-daily` - Full daily validation
- `/hit-rate-analysis` - Analyze model performance

## Files

| File | Purpose |
|------|---------|
| `ml/experiments/quick_retrain.py` | Has check_training_data_quality() |
| `data_processors/precompute/ml_feature_store/` | Feature store processor |

---
*Created: Session 104*
*Updated: Session 113 (Added DNP validation checks)*
*Part of: Data Quality & Model Experiment Infrastructure*
