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
# Check last 7 days - quality readiness and alert levels (Session 139)
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(is_quality_ready = TRUE) as quality_ready,
  ROUND(COUNTIF(is_quality_ready = TRUE) * 100.0 / COUNT(*), 1) as ready_pct,
  COUNTIF(quality_alert_level = 'green') as green,
  COUNTIF(quality_alert_level = 'yellow') as yellow,
  COUNTIF(quality_alert_level = 'red') as red,
  ROUND(AVG(feature_quality_score), 1) as avg_score,
  ROUND(AVG(matchup_quality_pct), 1) as matchup_q,
  ROUND(AVG(player_history_quality_pct), 1) as history_q,
  ROUND(AVG(vegas_quality_pct), 1) as vegas_q
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND feature_count >= 37
GROUP BY game_date
ORDER BY game_date DESC"
```

## Validation Checks

### 1. Quality Tier & Alert Level Distribution (Session 139)

**Healthy:** >80% records are `is_quality_ready = TRUE`, <5% red alerts

```sql
-- Quality tier distribution (gold/silver/bronze/poor/critical)
SELECT
  quality_tier,
  quality_alert_level,
  COUNT(*) as records,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct,
  ROUND(AVG(feature_quality_score), 1) as avg_score,
  ROUND(AVG(matchup_quality_pct), 1) as avg_matchup
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND feature_count >= 37
GROUP BY 1, 2
ORDER BY 1, 2
```

### 1b. Category Quality Breakdown (Session 139)

**Critical:** If `matchup_quality_pct < 50` for many records, this is a Session 132-style failure.

```sql
-- Per-category quality breakdown
SELECT
  game_date,
  ROUND(AVG(matchup_quality_pct), 1) as matchup_q,
  ROUND(AVG(player_history_quality_pct), 1) as history_q,
  ROUND(AVG(team_context_quality_pct), 1) as team_ctx_q,
  ROUND(AVG(vegas_quality_pct), 1) as vegas_q,
  ROUND(AVG(game_context_quality_pct), 1) as game_ctx_q,
  ROUND(AVG(default_feature_count), 1) as avg_defaults,
  COUNTIF(has_composite_factors = FALSE) as missing_composite
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND feature_count >= 37
GROUP BY 1
ORDER BY 1 DESC
```

### 1c. Per-Feature Quality for Critical Features (Session 139)

**Check individual feature health for the most impactful features:**

```sql
-- Critical feature quality (features 5-8: composite, 13-14: opponent, 25-26: vegas)
SELECT
  game_date,
  ROUND(AVG(feature_5_quality), 1) as fatigue_q,
  ROUND(AVG(feature_6_quality), 1) as shot_zone_q,
  ROUND(AVG(feature_7_quality), 1) as pace_q,
  ROUND(AVG(feature_8_quality), 1) as usage_q,
  ROUND(AVG(feature_13_quality), 1) as opp_def_q,
  ROUND(AVG(feature_14_quality), 1) as opp_pace_q,
  ROUND(AVG(feature_25_quality), 1) as vegas_line_q,
  ROUND(AVG(feature_26_quality), 1) as vegas_total_q
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND feature_count >= 37
GROUP BY 1
ORDER BY 1 DESC
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
| `is_quality_ready` % | >= 80% | 60-79% | < 60% |
| `quality_alert_level = 'red'` % | < 5% | 5-15% | > 15% |
| `matchup_quality_pct` avg | >= 70 | 50-69 | < 50 (Session 132!) |
| `player_history_quality_pct` avg | >= 80 | 60-79 | < 60 |
| `vegas_quality_pct` avg | >= 40 | 30-39 | < 30 |
| `default_feature_count` avg | < 3 | 3-6 | > 6 |
| Avg Quality Score (legacy) | >= 80 | 70-79 | < 70 |
| Vegas Coverage | >= 40% | 30-39% | < 30% |
| Partial Data % | < 5% | 5-10% | > 10% |

**Key insight (Session 134):** The aggregate `feature_quality_score` is a lie — it masks component failures. Always check category-level quality (`matchup_quality_pct`, `player_history_quality_pct`, etc.) for root cause.

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

### 16. ML Feature Store vs Cache Match Rate (Session 113+)

**CRITICAL:** Verify L5 values in ml_feature_store_v2 match player_daily_cache.
Session 113+ discovered massive mismatch (44% in November) due to DNP pollution in cache.

```sql
-- Check match rate between ML feature store and Phase 4 cache
SELECT
  DATE_TRUNC(c.cache_date, MONTH) as month,
  COUNT(*) as total_records,
  COUNTIF(ABS(c.points_avg_last_5 - m.features[OFFSET(0)]) < 0.1) as matches,
  ROUND(100.0 * COUNTIF(ABS(c.points_avg_last_5 - m.features[OFFSET(0)]) < 0.1) / COUNT(*), 1) as match_pct,
  -- Show mismatches by magnitude
  COUNTIF(ABS(c.points_avg_last_5 - m.features[OFFSET(0)]) BETWEEN 0.1 AND 3.0) as small_mismatch,
  COUNTIF(ABS(c.points_avg_last_5 - m.features[OFFSET(0)]) BETWEEN 3.0 AND 10.0) as medium_mismatch,
  COUNTIF(ABS(c.points_avg_last_5 - m.features[OFFSET(0)]) > 10.0) as large_mismatch
FROM nba_precompute.player_daily_cache c
JOIN nba_predictions.ml_feature_store_v2 m
  ON c.cache_date = m.game_date
  AND c.player_lookup = m.player_lookup
WHERE c.cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY month
ORDER BY month DESC
```

**Expected (Post Session 113+ Fixes):**
- December - February: 97-99% match rate
- November: 95%+ (after shot_zone regeneration)
- Large mismatches (>10 pts): < 0.1%

**If match rate < 95% for recent months:**
- CRITICAL - DNP pollution may have recurred
- Check Phase 4 cache DNP filter (check #12)
- Verify no unmarked DNPs in Phase 3 (check #10)

**If large mismatches > 1%:**
- CRITICAL - Severe data quality issue
- Run smoking gun query with specific player examples
- Investigate Phase 3 → Phase 4 data flow

### 17. Shot Zone Dynamic Threshold Effectiveness (Session 113+)

**MEDIUM:** Verify shot_zone processor handles early season correctly.
After commit e06043b9 (dynamic 3-10 game threshold), coverage should improve.

```sql
-- Compare shot_zone coverage before/after dynamic threshold fix
WITH season_start AS (
  SELECT MIN(game_date) as start_date
  FROM nba_analytics.player_game_summary
  WHERE EXTRACT(YEAR FROM game_date) = 2025
    AND EXTRACT(MONTH FROM game_date) >= 10
),
daily_coverage AS (
  SELECT
    psz.analysis_date,
    DATE_DIFF(psz.analysis_date, s.start_date, DAY) as days_into_season,
    COUNT(DISTINCT psz.player_lookup) as players_with_shot_zone,
    COUNT(DISTINCT pgs.player_lookup) as total_active_players,
    ROUND(100.0 * COUNT(DISTINCT psz.player_lookup) / COUNT(DISTINCT pgs.player_lookup), 1) as coverage_pct
  FROM nba_precompute.player_shot_zone_analysis psz
  CROSS JOIN season_start s
  JOIN nba_analytics.player_game_summary pgs
    ON psz.analysis_date = pgs.game_date
    AND pgs.points IS NOT NULL  -- Active players only
  WHERE psz.analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  GROUP BY psz.analysis_date, s.start_date
)
SELECT
  analysis_date,
  days_into_season,
  players_with_shot_zone,
  total_active_players,
  coverage_pct,
  CASE
    WHEN days_into_season <= 6 AND coverage_pct < 20 THEN 'OK (very early)'
    WHEN days_into_season BETWEEN 7 AND 14 AND coverage_pct < 40 THEN 'WARNING (expected 30-60%)'
    WHEN days_into_season BETWEEN 15 AND 21 AND coverage_pct < 70 THEN 'WARNING (expected 60-85%)'
    WHEN days_into_season > 21 AND coverage_pct < 90 THEN 'CRITICAL (expected >90%)'
    ELSE 'OK'
  END as status
FROM daily_coverage
ORDER BY analysis_date DESC
```

**Expected After Fix (commit e06043b9):**
- Days 1-6: 0-30% (very limited data)
- Days 7-14: 30-60% (building up)
- Days 15-21: 60-85% (approaching full)
- Days 22+: >90% (full coverage)

**If coverage significantly below expected:**
- Check if dynamic threshold code deployed (commit e06043b9)
- Verify _get_dynamic_min_games() method exists in deployed image
- May need to regenerate historical dates with new code

### 18. Silent Write Failure Detection (Session 113+)

**HIGH:** Catch save_precompute() bug pattern where logs say "FAILED" but writes succeeded.
Session 113+ found save_precompute() returned None instead of bool, causing misleading errors.

```sql
-- Check for date ranges with suspicious write patterns
WITH daily_writes AS (
  SELECT
    game_date,
    COUNT(*) as records_written
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date
)
SELECT
  game_date,
  records_written,
  LAG(records_written) OVER (ORDER BY game_date) as prev_day_records,
  CASE
    WHEN records_written = 0 THEN 'CRITICAL - No writes'
    WHEN records_written < 50 THEN 'WARNING - Very low writes'
    WHEN ABS(records_written - LAG(records_written) OVER (ORDER BY game_date)) > 200
      THEN 'WARNING - Large change from previous day'
    ELSE 'OK'
  END as status
FROM daily_writes
ORDER BY game_date DESC
LIMIT 14
```

**Expected:**
- Each day: 200-400 records (varies by game schedule)
- No days with 0 records (unless no games scheduled)
- Gradual changes day-to-day (±50 records typical)

**If suspicious pattern found:**
- Check BigQuery streaming inserts vs batch writes
- Verify service logs don't report false failures
- Check if return type bug recurred (operations/bigquery_save_ops.py)

### 19. Deployment Drift Pre-Check (Session 113+)

**CRITICAL:** Before validating data, verify services are up-to-date.
Sessions 64, 81, 82, 97, 113+ had fixes committed but not deployed, causing recurring issues.

```bash
# Check deployment status before running validation
./bin/whats-deployed.sh

# Look for services that are behind:
# ✗ nba-phase4-precompute-processors - 5 commits behind
# ✗ prediction-worker - 13 commits behind

# If any data processing services are behind, deploy first:
./bin/deploy-service.sh nba-phase4-precompute-processors
```

**Services to Check:**
- `nba-phase4-precompute-processors` (Phase 4 cache, ML features)
- `nba-phase3-analytics-processors` (player_game_summary)
- `prediction-worker` (Predictions)
- `prediction-coordinator` (Orchestration)

**Why this matters:** Validation against stale code will show issues that are already fixed in repo but not deployed. Deploy first, then validate.

### 20. Monthly Data Quality Trend (Session 113+)

**MEDIUM:** Track data quality improvements/regressions over time.
Session 113+ improved Dec-Feb from ~44% to 97-99% match rate.

```sql
-- Monthly data quality trend (3-month view)
WITH monthly_quality AS (
  SELECT
    DATE_TRUNC(c.cache_date, MONTH) as month,
    -- Match rate (primary metric)
    ROUND(100.0 * COUNTIF(ABS(c.points_avg_last_5 - m.features[OFFSET(0)]) < 0.1) / COUNT(*), 1) as match_pct,
    -- DNP pollution (should be 0%)
    ROUND(100.0 * COUNTIF(c.points_avg_last_5 = 0 AND m.features[OFFSET(0)] > 0) / COUNT(*), 1) as dnp_pollution_pct,
    -- Coverage
    COUNT(*) as total_records,
    COUNT(DISTINCT c.player_lookup) as unique_players
  FROM nba_precompute.player_daily_cache c
  JOIN nba_predictions.ml_feature_store_v2 m
    ON c.cache_date = m.game_date
    AND c.player_lookup = m.player_lookup
  WHERE c.cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
  GROUP BY month
)
SELECT
  month,
  match_pct,
  dnp_pollution_pct,
  total_records,
  unique_players,
  CASE
    WHEN match_pct >= 95 AND dnp_pollution_pct < 1 THEN 'EXCELLENT'
    WHEN match_pct >= 90 AND dnp_pollution_pct < 3 THEN 'GOOD'
    WHEN match_pct >= 80 AND dnp_pollution_pct < 5 THEN 'WARNING'
    ELSE 'CRITICAL'
  END as quality_grade
FROM monthly_quality
ORDER BY month DESC
```

**Expected (Post Session 113+):**
- December 2025 onwards: EXCELLENT (97-99% match, <1% pollution)
- November 2025: GOOD (95%+, after shot_zone fix)

**If quality degrades:**
- Check if recent code changes broke DNP filtering
- Verify deployment status (check #19)
- Run full diagnostic suite (checks #9-15)

### 21. DNP Players in Cache Rate (Session 115)

**LOW:** Verify DNP player caching is within expected range.
Session 115 investigation confirmed DNP caching is INTENTIONAL DESIGN, not a bug.

**Context:** Phase 4's `player_daily_cache` caches ALL scheduled players (including DNPs). DNP filtering happens during L5/L10 calculation, not at the row-writing level. This is correct behavior.

```sql
-- Check percentage of cache records for DNP games
SELECT
  pdc.cache_date,
  COUNT(*) as total_cached,
  COUNT(DISTINCT CASE WHEN pgs.is_dnp = TRUE OR (pgs.points IS NULL AND pgs.minutes_played IS NULL) THEN pdc.player_lookup END) as dnp_players_cached,
  ROUND(100.0 * COUNT(DISTINCT CASE WHEN pgs.is_dnp = TRUE OR (pgs.points IS NULL AND pgs.minutes_played IS NULL) THEN pdc.player_lookup END) / COUNT(DISTINCT pdc.player_lookup), 1) as dnp_pct
FROM nba_precompute.player_daily_cache pdc
LEFT JOIN nba_analytics.player_game_summary pgs
  ON pdc.player_lookup = pgs.player_lookup
  AND pdc.cache_date = pgs.game_date
WHERE pdc.cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY pdc.cache_date
ORDER BY pdc.cache_date DESC
```

**Expected (Session 115 Baseline):**
- DNP players cached: 70-160 per day
- DNP percentage: 15-30% of total players
- This is NORMAL and CORRECT behavior

**Interpretation:**
- **10-30% DNP rate:** NORMAL - Expected mix of injuries, rest, roster decisions
- **> 40% DNP rate:** WARNING - Unusually high injuries or schedule data issue
- **> 60% DNP rate:** CRITICAL - Likely data quality problem

**Why this is acceptable:**
- Cache is for "players scheduled to play" not "players who actually played"
- DNP status often determined after cache generation (injury reports)
- L5/L10 calculations correctly exclude DNP games from historical data
- Allows predictions for all scheduled players

**If DNP rate is abnormally high (>40%):**
- Check if there's a major injury outbreak affecting multiple teams
- Verify roster/schedule data is accurate
- Confirm DNP filtering in stats_aggregator.py is working (should see 99%+ match rate in check #16)

### 22. Phase 3 vs Phase 4 Consistency (Session 115)

**MEDIUM:** Verify Phase 3 analytics and Phase 4 cache agree on L5/L10 values.
Session 115 found Phase 3/4 discrepancies due to stale Phase 3 data after deploying DNP fixes.

**Context:** Both Phase 3 (`upcoming_player_game_context`) and Phase 4 (`player_daily_cache`) calculate L5/L10 averages. They should agree when both use current code with DNP fixes.

```sql
-- Compare Phase 3 analytics vs Phase 4 cache L5/L10 values
SELECT
  p3.game_date,
  COUNT(*) as total_players,
  -- Exact matches (within 0.1 points)
  COUNTIF(ABS(p3.points_avg_last_5 - p4.points_avg_last_5) < 0.1) as exact_matches,
  ROUND(100.0 * COUNTIF(ABS(p3.points_avg_last_5 - p4.points_avg_last_5) < 0.1) / COUNT(*), 1) as match_pct,
  -- Small mismatches (0.1-3 points)
  COUNTIF(ABS(p3.points_avg_last_5 - p4.points_avg_last_5) BETWEEN 0.1 AND 3.0) as small_mismatch,
  -- Large mismatches (>5 points = likely stale data)
  COUNTIF(ABS(p3.points_avg_last_5 - p4.points_avg_last_5) > 5.0) as large_mismatch
FROM nba_analytics.upcoming_player_game_context p3
JOIN nba_precompute.player_daily_cache p4
  ON p3.player_lookup = p4.player_lookup
  AND p3.game_date = p4.cache_date
WHERE p3.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY p3.game_date
ORDER BY p3.game_date DESC
```

**Expected (Post Session 115 Regeneration):**
- Match rate: **>95%** (both using same DNP filtering logic)
- Small mismatches: <5% (rounding or timing differences)
- Large mismatches: <1% (rare edge cases)

**Interpretation:**
- **>95% match:** EXCELLENT - Both phases synchronized
- **90-95% match:** GOOD - Minor discrepancies, acceptable
- **<90% match:** WARNING - Possible stale data or code drift
- **Large mismatches >5%:** CRITICAL - Stale data or algorithm mismatch

**Root Causes of Mismatches:**
1. **Stale Phase 3 data:** Generated before DNP fix deployment (Session 115)
2. **Code drift:** Phase 3 and Phase 4 have different DNP filtering logic (should not happen)
3. **Timing:** Phase 3 generated at different time than Phase 4 for same date

**If large mismatches found:**
```sql
-- Get specific examples to investigate
SELECT
  p3.player_lookup,
  p3.game_date,
  ROUND(p3.points_avg_last_5, 1) as phase3_l5,
  ROUND(p4.points_avg_last_5, 1) as phase4_l5,
  ROUND(ABS(p3.points_avg_last_5 - p4.points_avg_last_5), 1) as diff
FROM nba_analytics.upcoming_player_game_context p3
JOIN nba_precompute.player_daily_cache p4
  ON p3.player_lookup = p4.player_lookup
  AND p3.game_date = p4.cache_date
WHERE p3.game_date = CURRENT_DATE() - 1
  AND ABS(p3.points_avg_last_5 - p4.points_avg_last_5) > 5.0
ORDER BY diff DESC
LIMIT 10
```

**Resolution:**
- If stale data: Regenerate Phase 3 `upcoming_player_game_context` for affected dates
- If code drift: Verify both phases have commit 981ff460 (Session 114 DNP fix)
- If timing: Check if Phase 3 processes triggered for today's games

### 23. DNP Filtering Validation (Session 115)

**MEDIUM:** Verify L5/L10 calculations properly exclude DNP games.
Session 114 fixed critical bug where DNP games polluted averages (e.g., Jokic: 6.2 → 34.0).

**Context:** For players with recent DNPs, verify the L5/L10 averages only include games where they actually played.

```sql
-- For star players with recent DNPs, validate L5 calculation
WITH player_dnp_history AS (
  SELECT
    player_lookup,
    game_date,
    points,
    minutes_played,
    CASE
      WHEN points IS NULL OR (points = 0 AND minutes_played IS NULL) THEN 1
      ELSE 0
    END as is_dnp,
    ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as game_num
  FROM nba_analytics.player_game_summary
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 15 DAY)
),
players_with_dnp AS (
  SELECT DISTINCT player_lookup
  FROM player_dnp_history
  WHERE game_num <= 10  -- DNP in last 10 games
    AND is_dnp = 1
),
manual_l5 AS (
  SELECT
    pdh.player_lookup,
    ROUND(AVG(CASE WHEN is_dnp = 0 THEN points END), 1) as expected_l5,
    COUNT(CASE WHEN is_dnp = 0 THEN 1 END) as games_played_in_l5
  FROM player_dnp_history pdh
  WHERE pdh.game_num BETWEEN 2 AND 6  -- Last 5 games (excluding current)
  GROUP BY pdh.player_lookup
  HAVING COUNT(CASE WHEN is_dnp = 1 THEN 1 END) > 0  -- Only players with DNPs
)
SELECT
  pdc.player_lookup,
  pdc.cache_date,
  ROUND(pdc.points_avg_last_5, 1) as cache_l5,
  m.expected_l5,
  m.games_played_in_l5,
  ROUND(ABS(pdc.points_avg_last_5 - m.expected_l5), 1) as diff
FROM nba_precompute.player_daily_cache pdc
JOIN manual_l5 m ON pdc.player_lookup = m.player_lookup
WHERE pdc.cache_date = CURRENT_DATE() - 1
  AND m.games_played_in_l5 BETWEEN 3 AND 5  -- Valid sample size
ORDER BY diff DESC
LIMIT 20
```

**Expected (Post Session 114 Fix):**
- All diff < 1.0 (rounding tolerance)
- No systematic bias for DNP players
- Games counted matches actual games played (not including DNPs)

**Interpretation:**
- **diff < 1.0:** EXCELLENT - DNP filtering working correctly
- **diff 1.0-3.0:** ACCEPTABLE - May be rounding or window edge cases
- **diff > 3.0:** WARNING - Investigate specific player
- **diff > 10.0:** CRITICAL - DNP bug may have recurred

**Example of correct DNP filtering (Session 114):**
```
Nikola Jokic last 5 games:
- Game 1: 35 points (played) ✅
- Game 2: DNP (excluded) ❌
- Game 3: 33 points (played) ✅
- Game 4: DNP (excluded) ❌
- Game 5: 34 points (played) ✅

L5 average = (35 + 33 + 34) / 3 = 34.0 ✅ CORRECT
NOT (35 + 0 + 33 + 0 + 34) / 5 = 20.4 ❌ WRONG (old bug)
```

**If DNP filtering errors found:**
- Verify stats_aggregator.py has lines 27-36 DNP filter (commit 981ff460)
- Check if deployment drift occurred (use check #19)
- Verify player_stats.py has lines 163-172 DNP filter
- Regenerate affected dates with correct code

### 24. Player Record Coverage vs Game Summary (Session 144)

**CRITICAL:** Verify every player in `player_game_summary` has a feature store record.

```sql
-- Player record coverage: does every player have a feature store record?
SELECT
  g.game_date,
  COUNT(DISTINCT g.player_lookup) as game_summary_players,
  COUNT(DISTINCT f.player_lookup) as feature_store_players,
  COUNT(DISTINCT g.player_lookup) - COUNT(DISTINCT f.player_lookup) as missing_records,
  ROUND(COUNT(DISTINCT f.player_lookup) / COUNT(DISTINCT g.player_lookup) * 100, 1) as record_coverage_pct
FROM nba_analytics.player_game_summary g
LEFT JOIN nba_predictions.ml_feature_store_v2 f
  ON g.player_lookup = f.player_lookup AND g.game_date = f.game_date
WHERE g.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1 ORDER BY 1
```

| Metric | GOOD | WARNING | CRITICAL |
|--------|------|---------|----------|
| Record coverage | 100% | 95-99% | <95% |

**If missing records:** Check if MLFeatureStoreProcessor ran for the date. Check `processor_run_history` for errors.

### 25. Per-Feature Default Breakdown (Session 144)

**CRITICAL:** Understand exactly which features are defaulted and which upstream component is responsible.

```sql
-- Which features default most often? (maps to upstream pipeline component)
SELECT
  idx as feature_index,
  CASE
    WHEN idx IN (0,1,2,3,4,5,6,7,8,13,14,22,23,29,31,32) THEN 'phase4'
    WHEN idx IN (15,16,17) THEN 'phase3'
    WHEN idx IN (25,26,27) THEN 'vegas'
    WHEN idx IN (18,19,20) THEN 'shot_zone'
    ELSE 'calculated'
  END as upstream_source,
  COUNT(*) as default_count,
  ROUND(COUNT(*) / (SELECT COUNT(*) FROM nba_predictions.ml_feature_store_v2
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)) * 100, 1) as pct_defaulted
FROM nba_predictions.ml_feature_store_v2,
UNNEST(default_feature_indices) as idx
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1, 2 ORDER BY 4 DESC
```

**Feature Index → Name → Upstream Source:**
| Index | Name | Source | Fix If Defaulted |
|-------|------|--------|-----------------|
| 0-4 | pts_avg_l5/l10/season, std, games_7d | Phase 4 player_daily_cache | Check player_daily_cache processor |
| 5-8 | fatigue, shot_zone, pace, usage | Phase 4 player_composite_factors | Check player_composite_factors processor |
| 13-14 | opp_def_rating, opp_pace | Phase 4 team_defense_zone_analysis | Check team_defense_zone_analysis processor |
| 18-20 | pct_paint/mid/three | Phase 4 player_shot_zone_analysis | Check player_shot_zone_analysis processor |
| 22-23 | team_pace, team_off_rating | Phase 4 player_daily_cache | Check player_daily_cache processor |
| 25-27 | vegas_line, opening, line_move | Vegas odds_api scrapers | Check odds_api scraper ran, line coverage |
| 31-32 | minutes_avg_l10, ppm_avg_l10 | Phase 4 player_daily_cache | Check player_daily_cache processor |

### 26. Feature Completeness Dashboard (Session 144)

**HIGH:** Combined view showing both player coverage and feature completeness.

```sql
-- Combined coverage dashboard: records + feature quality
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(default_feature_count = 0) as fully_complete,
  ROUND(COUNTIF(default_feature_count = 0) / COUNT(*) * 100, 1) as pct_fully_complete,
  COUNTIF(is_quality_ready) as quality_ready,
  ROUND(AVG(default_feature_count), 1) as avg_defaults,
  ROUND(AVG(matchup_quality_pct), 1) as matchup_q,
  ROUND(AVG(vegas_quality_pct), 1) as vegas_q,
  ROUND(AVG(player_history_quality_pct), 1) as history_q
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1 ORDER BY 1
```

| Metric | GOOD | WARNING | CRITICAL |
|--------|------|---------|----------|
| pct_fully_complete | >50% | 30-50% | <30% |
| avg_defaults | <2 | 2-5 | >5 |
| vegas_q | >70 | 50-70 | <50 |
| matchup_q | >90 | 70-90 | <70 |

**Key insight (Session 144):** "100% player coverage" ≠ "100% feature completeness". Always check BOTH dimensions. Vegas lines (features 25-27) are the #1 blocker at ~57% defaulted. All other categories are >90%.

### 27. Feature Store Gap Tracking (Session 144)

**MEDIUM:** Check the gap tracking table for unresolved gaps needing backfill.

```sql
-- Unresolved feature store gaps
SELECT
  game_date,
  reason,
  COUNT(*) as gap_count,
  COUNT(DISTINCT player_lookup) as unique_players
FROM nba_predictions.feature_store_gaps
WHERE resolved_at IS NULL
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC
LIMIT 20
```

**If gaps exist:** Run backfill for the affected dates:
```bash
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date YYYY-MM-DD --end-date YYYY-MM-DD --skip-preflight
```

### 28. Training Data Contamination Check (Session 158)

**CRITICAL:** Check if the V9 training window has clean data (no default contamination).

**Context:** Session 157 discovered 33.2% of training data was contaminated with default values.
Three prevention layers were added (shared loader, quality score capping, historical fix).
This check verifies the fix is holding and catches any new contamination.

**Quick script check:**
```bash
./bin/monitoring/check_training_data_quality.sh
```

**Detailed SQL check with monthly breakdown:**
```sql
-- Training data contamination by month
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(*) as total,
  COUNTIF(required_default_count = 0) as clean,
  COUNTIF(required_default_count > 0) as contaminated,
  ROUND(COUNTIF(required_default_count > 0) * 100.0 / COUNT(*), 1) as contam_pct,
  ROUND(COUNTIF(is_quality_ready = TRUE) * 100.0 / COUNT(*), 1) as quality_ready_pct,
  ROUND(AVG(default_feature_count), 2) as avg_defaults,
  ROUND(AVG(feature_quality_score), 1) as avg_quality_score
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-02'
  AND game_date < CURRENT_DATE()
  AND feature_count >= 37
GROUP BY 1
ORDER BY 1
```

**Which features are most commonly defaulted (root cause analysis):**
```sql
-- Top defaulted features across training window
SELECT
  idx as feature_index,
  CASE idx
    WHEN 0 THEN 'pts_avg_l5' WHEN 1 THEN 'pts_avg_l10' WHEN 2 THEN 'pts_avg_season'
    WHEN 3 THEN 'pts_std_l10' WHEN 4 THEN 'games_7d'
    WHEN 5 THEN 'fatigue' WHEN 6 THEN 'shot_zone_mismatch' WHEN 7 THEN 'pace' WHEN 8 THEN 'usage_spike'
    WHEN 13 THEN 'opp_def_rating' WHEN 14 THEN 'opp_pace'
    WHEN 25 THEN 'vegas_line' WHEN 26 THEN 'vegas_total' WHEN 27 THEN 'line_move'
    ELSE CONCAT('feature_', CAST(idx AS STRING))
  END as feature_name,
  COUNT(*) as default_count,
  ROUND(COUNT(*) * 100.0 / (
    SELECT COUNT(*) FROM nba_predictions.ml_feature_store_v2
    WHERE game_date >= '2025-11-02' AND game_date < CURRENT_DATE() AND feature_count >= 37
  ), 1) as pct_of_records
FROM nba_predictions.ml_feature_store_v2,
UNNEST(default_feature_indices) as idx
WHERE game_date >= '2025-11-02'
  AND game_date < CURRENT_DATE()
  AND feature_count >= 37
GROUP BY 1, 2
ORDER BY 3 DESC
LIMIT 15
```

**Session 157 baseline comparison:**
| Metric | Pre-Fix (Session 157) | Target (Post-Fix) |
|--------|-----------------------|-------------------|
| Contamination % | 33.2% | < 5% |
| Quality-ready % | ~40% | > 60% |
| Avg defaults | ~4.2 | < 2 |

**Expected (after Session 158 backfill):**
- November 2025: < 5% contaminated (was 33.2%)
- December 2025+: < 5% contaminated
- Vegas features (25-27) are expected to be commonly defaulted (sportsbook coverage)
- Non-vegas contamination > 5%: investigate Phase 4 processors

**If contamination is high:**
1. Run `./bin/monitoring/check_training_data_quality.sh` for quick summary
2. Check which months/features are worst (queries above)
3. Backfill affected dates: `./bin/backfill/run_phase4_backfill.sh --start-date YYYY-MM-DD --end-date YYYY-MM-DD`

## Pre-Training Checklist

Before running `/model-experiment`:

**Deployment & System Health:**
1. **CRITICAL (Session 113+):** Check deployment drift first (check #19) - deploy stale services before validation
2. **HIGH (Session 113+):** Check for silent write failures (check #18) - verify writes succeeded

**Data Quality - Core Metrics:**
3. Run quality distribution check (target: >80% quality >= 70)
4. Check Vegas line coverage by tier (not overall - expect 40% for bench, 95% for stars)
5. Verify Vegas bias by tier (expect stars under-predicted ~8pts)
6. Check for unusual data source distribution (<5% partial)

**Data Quality - DNP & Phase 4:**
7. **CRITICAL (Session 113+):** Verify no DNP pollution in Phase 4 cache (check #12)
8. **CRITICAL (Session 113+):** ML feature store vs cache match rate >95% (check #16)
9. **CRITICAL (Session 113+):** Check team pace outliers (check #13)
10. **MEDIUM (Session 115):** DNP players in cache rate 15-30% expected (check #21) - caching DNPs is intentional
11. **MEDIUM (Session 115):** Phase 3 vs Phase 4 consistency >95% match (check #22)
12. **MEDIUM (Session 115):** DNP filtering validation - verify L5/L10 exclude DNPs (check #23)
13. **NEW (Session 113):** Validate L5/L10 calculations match manual (DNP handling check #9)
14. **NEW (Session 113):** Check for unmarked DNPs in source data (check #10)

**Data Quality - Coverage & Completeness (Session 144):**
15. **CRITICAL (Session 144):** Player record coverage vs game_summary - must be 100% (check #24)
16. **CRITICAL (Session 144):** Per-feature default breakdown - identify upstream blockers (check #25)
17. **HIGH (Session 144):** Feature completeness dashboard - both dimensions (check #26)
18. **MEDIUM (Session 144):** Feature store gap tracking table (check #27)

**Data Quality - Early Season & Coverage:**
19. **MEDIUM (Session 113+):** Check early season bootstrap coverage (check #15)
20. **MEDIUM (Session 113+):** Shot zone dynamic threshold effectiveness (check #17)

**Model Training:**
17. Confirm model experiment includes tier bias analysis (built-in since Session 104)
18. **MEDIUM (Session 113+):** Review monthly data quality trend (check #20) - ensure no regressions

**Recommended Order:**
1. Run deployment check (#19) FIRST - fix drift before validation
2. Run CRITICAL checks (#12, #16, #13, #7) - these catch major data issues
3. Run MEDIUM checks (#21, #22, #23) - Session 115 new DNP architecture validation
4. Run HIGH checks (#9, #10) - catch moderate issues
5. Run MEDIUM checks (#15, #17, #20) - nice-to-have context
6. Run standard quality checks (#3-6) - normal model prep

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

### Distribution Health Audit (Session 375)

**Catches "plausible but wrong" bugs** like Feature 41 (spread_magnitude) being ALL ZEROS for 4 months. Existing checks miss constant-value bugs because the values are non-NULL, within range, and have 100% coverage.

**Run the CLI tool:**

```bash
# Check last 7 days
python bin/validation/feature_distribution_health.py --date $(date +%Y-%m-%d)

# Verbose output (shows PASS results too)
python bin/validation/feature_distribution_health.py --date $(date +%Y-%m-%d) --verbose

# Check specific date with wider lookback
python bin/validation/feature_distribution_health.py --date 2026-02-28 --lookback 14
```

**What it checks per feature:**
1. Constant-value detection (stddev + distinct count below thresholds)
2. Zero-rate anomaly (zeros exceed expected baseline)
3. NULL-rate anomaly (>30% NULLs)
4. Distribution drift (mean shifted >3 sigma vs 4-week baseline)
5. Source cross-validation (raw table comparison for features 25, 41)

**Expected output:**
```
=== Feature Distribution Health Check ===
Date: 2026-02-28 (lookback: 7 days)

WARNINGS:
  WARN  Feature 8 (usage_spike_score): Distribution drift - mean shifted 3.2 sigma

SUMMARY: 56 features checked, 0 FAIL, 1 WARN, 1 SKIP
STATUS: WARN - Minor anomalies detected, review recommended
```

**If FAIL on constant-value:**
1. Check the feature extraction query in `ml_feature_store_processor.py`
2. Verify upstream data in the source table (see profile's `source_table`)
3. Fix the extraction bug
4. Backfill the feature store for affected dates
5. Retrain models if the feature was used in training

## Related Skills

- `/model-experiment` - Train challenger models
- `/validate-daily` - Full daily validation
- `/hit-rate-analysis` - Analyze model performance

## Files

| File | Purpose |
|------|---------|
| `ml/experiments/quick_retrain.py` | Has check_training_data_quality() |
| `data_processors/precompute/ml_feature_store/` | Feature store processor |
| `bin/validation/feature_distribution_health.py` | Distribution health CLI (Session 375) |

---
*Created: Session 104*
*Updated: Session 115 (Added 3 new validation checks: #21-23)*
*Updated: Session 375 (Added Distribution Health Audit section)*
*Major Updates:*
- Session 113: DNP pollution detection (#10, #12, #14)
- Session 113+: Early season bootstrap (#15), shot zone dynamic threshold (#17)
- Session 113+: ML feature vs cache match rate (#16), silent write failures (#18)
- Session 113+: Deployment drift pre-check (#19), monthly quality trends (#20)
- **Session 115: DNP caching architecture validation (#21), Phase 3/4 consistency (#22), DNP filtering validation (#23)**
- **Session 115 Key Finding:** DNP players in cache is INTENTIONAL design (not a bug) - filtering happens during aggregation
- **Session 144: Player record coverage (#24), per-feature default breakdown (#25), feature completeness dashboard (#26), gap tracking (#27)**
- **Session 144 Key Finding:** "100% player coverage" ≠ "100% feature completeness". Vegas lines (25-27) cause 57% of defaults. Only 37-45% of records are fully complete.
- **Session 158: Training data contamination check (#28) — prevents Session 157 33.2% contamination from recurring**
*Part of: Data Quality & Model Experiment Infrastructure*
