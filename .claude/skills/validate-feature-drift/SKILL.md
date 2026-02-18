---
name: validate-feature-drift
description: Detect feature store quality degradation and drift from previous season
---

# /validate-feature-drift - Feature Quality & Drift Detection

Detect when ML feature quality degrades compared to historical baselines. This would have caught the Jan 2026 vegas_line issue before it impacted predictions.

## When to Use

- Weekly feature store health check
- Before ML model retraining
- When hit rates drop unexpectedly
- After pipeline changes
- Start of new season (compare to previous season)
- **When tier bias detected** (Session 101) - feature quality issues can cause prediction bias

## Usage

```
/validate-feature-drift
/validate-feature-drift --weeks 4
/validate-feature-drift --compare-season 2024-25
```

## Critical Features to Monitor

These features have the highest model importance and must be populated:

| Feature | Index | Threshold | Impact if Missing |
|---------|-------|-----------|-------------------|
| `vegas_points_line` | 25 | >95% populated | HIGH - model loses key input |
| `points_avg_last_5` | 0 | >98% populated | HIGH - recent performance |
| `points_avg_last_10` | 1 | >98% populated | HIGH - recent performance |
| `fatigue_score` | 5 | >90% populated | MEDIUM - Phase 4 composite |
| `opponent_def_rating` | 13 | >95% populated | MEDIUM - matchup context |

## Validation Queries

### Check 1: Feature Coverage This Week vs Last Season

```sql
-- Compare current season to same period last season
WITH current_season AS (
  SELECT
    'Current' as period,
    COUNT(*) as total_records,
    COUNTIF(features[OFFSET(25)] > 0) as with_vegas_line,
    COUNTIF(features[OFFSET(0)] > 0) as with_points_avg_5,
    COUNTIF(features[OFFSET(5)] > 0) as with_fatigue
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND ARRAY_LENGTH(features) >= 33
),
last_season AS (
  SELECT
    'Last Year' as period,
    COUNT(*) as total_records,
    COUNTIF(features[OFFSET(25)] > 0) as with_vegas_line,
    COUNTIF(features[OFFSET(0)] > 0) as with_points_avg_5,
    COUNTIF(features[OFFSET(5)] > 0) as with_fatigue
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date >= DATE_SUB(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), INTERVAL 7 DAY)
    AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR)
    AND ARRAY_LENGTH(features) >= 33
)
SELECT
  period,
  total_records,
  ROUND(100.0 * with_vegas_line / total_records, 1) as vegas_line_pct,
  ROUND(100.0 * with_points_avg_5 / total_records, 1) as points_avg_pct,
  ROUND(100.0 * with_fatigue / total_records, 1) as fatigue_pct
FROM current_season
UNION ALL
SELECT * FROM last_season
```

**Expected**: Current season should be within 5% of last season for all features.

**Alert thresholds**:
- 🔴 CRITICAL: vegas_line < 80% (was 99%+ last season)
- 🟡 WARNING: Any feature >10% below last season
- ✅ OK: Within 5% of last season

### Check 2: Weekly Trend (Catch Gradual Degradation)

```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as records,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_line_pct,
  ROUND(100.0 * COUNTIF(features[OFFSET(0)] > 0) / COUNT(*), 1) as points_avg_pct,
  ROUND(100.0 * COUNTIF(features[OFFSET(5)] > 0) / COUNT(*), 1) as fatigue_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
  AND ARRAY_LENGTH(features) >= 33
GROUP BY 1
ORDER BY 1 DESC
```

**Alert thresholds**:
- 🔴 CRITICAL: Week-over-week drop >20%
- 🟡 WARNING: Consistent decline for 3+ weeks
- ✅ OK: Stable or improving

### Check 3: Feature Value Distribution Drift

```sql
-- Detect if feature values shifted significantly
WITH current_stats AS (
  SELECT
    'Current' as period,
    ROUND(AVG(features[OFFSET(25)]), 1) as avg_vegas_line,
    ROUND(STDDEV(features[OFFSET(25)]), 2) as std_vegas_line,
    ROUND(AVG(features[OFFSET(0)]), 1) as avg_points_5
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND ARRAY_LENGTH(features) >= 33
    AND features[OFFSET(25)] > 0  -- Only where populated
),
last_year_stats AS (
  SELECT
    'Last Year' as period,
    ROUND(AVG(features[OFFSET(25)]), 1) as avg_vegas_line,
    ROUND(STDDEV(features[OFFSET(25)]), 2) as std_vegas_line,
    ROUND(AVG(features[OFFSET(0)]), 1) as avg_points_5
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date >= DATE_SUB(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), INTERVAL 30 DAY)
    AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR)
    AND ARRAY_LENGTH(features) >= 33
    AND features[OFFSET(25)] > 0
)
SELECT * FROM current_stats UNION ALL SELECT * FROM last_year_stats
```

## Integration with /validate-daily

Add to Priority 2 checks in `/validate-daily`:

```
### Priority 2D: Feature Store Quality (NEW)

Run weekly or when hit rates drop:

bq query --use_legacy_sql=false "
SELECT
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_line_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND ARRAY_LENGTH(features) >= 33"

Expected: >95% (matches historical baseline)
If <80%: 🔴 CRITICAL - Feature store degradation detected
```

## Automated Monitoring (Future)

Add to daily Cloud Function or scheduled query:

```python
# Alert if vegas_line coverage drops below 90%
threshold = 0.90
coverage = query_vegas_line_coverage(last_7_days)
if coverage < threshold:
    send_alert(
        severity="CRITICAL",
        message=f"Feature store vegas_line coverage dropped to {coverage:.1%}",
        comparison=f"Last season was 99%+"
    )
```

### Check 4: Records Per Day (Detect Dilution)

```sql
-- If records/day increased significantly, you may have dilution (all players vs only those with props)
SELECT
  'Current' as period,
  COUNT(*) / COUNT(DISTINCT game_date) as avg_records_per_day
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND ARRAY_LENGTH(features) >= 33
UNION ALL
SELECT
  'Last Year' as period,
  COUNT(*) / COUNT(DISTINCT game_date) as avg_records_per_day
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), INTERVAL 7 DAY)
  AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR)
  AND ARRAY_LENGTH(features) >= 33
```

**Alert thresholds**:
- 🔴 CRITICAL: Records/day increased >100% (indicates ALL players included, not just those with props)
- 🟡 WARNING: Records/day changed >50%
- ✅ OK: Within 30% of last season

### Check 5: has_vegas_line Flag vs Actual Coverage

```sql
-- If has_vegas_line=1 but vegas_line=0, there's a data extraction bug
SELECT
  ROUND(100.0 * COUNTIF(features[OFFSET(28)] = 1) / COUNT(*), 1) as has_line_flag_pct,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as actual_line_pct,
  ROUND(100.0 * COUNTIF(features[OFFSET(28)] = 1 AND features[OFFSET(25)] = 0) / COUNT(*), 1) as mismatch_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND ARRAY_LENGTH(features) >= 33
```

**Alert thresholds**:
- 🔴 CRITICAL: mismatch_pct > 5% (flag says has line but value is 0)
- ✅ OK: mismatch_pct < 1%

## Root Cause Checklist

When feature degradation is detected:

### Step 1: Check upstream data sources
- Odds API scraper running? Check GCS files
- BettingPros scraper running? Check GCS files
- Player matching working? Check `upcoming_player_game_context.current_points_line`

### Step 2: Check Phase 3 context
```sql
SELECT
  ROUND(100.0 * COUNTIF(current_points_line IS NOT NULL AND current_points_line > 0) / COUNT(*), 1) as pct
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
```

### Step 3: Check feature store generation mode
```sql
-- Check if backfill mode was used (includes ALL players, not just those with props)
-- Symptom: High record count per day but low vegas_line coverage
SELECT
  game_date,
  COUNT(*) as records,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND ARRAY_LENGTH(features) >= 33
GROUP BY 1
ORDER BY 1 DESC
```

If records are HIGH (300-500) but vegas_pct is LOW (<50%), the feature store was likely generated in **backfill mode** which includes all players but sets `has_prop_line=FALSE`.

**Fix:** Re-run feature store in production mode or fix backfill mode to join with betting data.

### Step 4: Check Phase 4 processor running
- Feature extraction query working?
- Check Cloud Run logs for errors

## Example Output

```
=== FEATURE DRIFT VALIDATION ===
Period: 2026-01-25 to 2026-02-01
Comparison: Same week last season (2025-01-25 to 2025-02-01)

FEATURE COVERAGE:
                  Current   Last Year   Delta    Status
vegas_line         43.4%      99.4%    -56.0%   🔴 CRITICAL
points_avg_5       99.8%      99.9%     -0.1%   ✅ OK
fatigue_score      91.2%      89.5%     +1.7%   ✅ OK

🔴 CRITICAL: vegas_line coverage dropped 56% from last season!

WEEKLY TREND (vegas_line):
Week         Coverage   Change
2026-01-25    43.4%     -2.1%
2026-01-18    45.5%     +3.0%
2026-01-11    42.5%    -15.4%  ⚠️ Drop
2026-01-04    57.9%     --

RECOMMENDATION:
1. Investigate Odds API scraper for Jan 2026
2. Check player matching in upcoming_player_game_context
3. Consider backfilling feature store after fix

This issue explains the model hit rate degradation in Jan 2026.
```

## Related Skills

- `/validate-daily` - Add feature check to Priority 2
- `/validate-historical` - Add feature store coverage
- `/hit-rate-analysis` - Cross-reference when hit rates drop

---
*Created: Session 61 - After discovering vegas_line feature degradation*
*This validation would have caught the Jan 2026 issue weeks earlier*
