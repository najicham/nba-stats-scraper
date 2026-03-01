---
name: validate-feature-drift
description: Detect feature store quality degradation and drift from previous season
---

# /validate-feature-drift - Feature Quality & Drift Detection

Detect when ML feature quality degrades compared to historical baselines. This would have caught the Jan 2026 vegas_line issue before it impacted predictions, and the Feature 41 (spread_magnitude) ALL ZEROS bug that persisted for 4 months.

## When to Use

- Weekly feature store health check
- Before ML model retraining
- When hit rates drop unexpectedly
- After pipeline changes
- Start of new season (compare to previous season)
- **When tier bias detected** (Session 101) - feature quality issues can cause prediction bias
- **When constant-value bugs suspected** (Session 375) - features returning same value for all players

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
| `spread_magnitude` | 41 | stddev > 1.0 | HIGH - was ALL ZEROS for 4 months |
| `implied_team_total` | 42 | stddev > 2.0 | HIGH - derived from game total/spread |
| `usage_spike_score` | 8 | drift monitoring | MEDIUM - seasonal drift (Session 370) |
| `minutes_avg_last_10` | 31 | >95% populated | HIGH - minutes context |
| `game_total_line` | 38 | stddev > 2.0 | MEDIUM - game environment |
| `team_pace` | 22 | stddev > 0.5 | MEDIUM - team context |

**CRITICAL:** Use `feature_N_value` columns, NOT `features[OFFSET(N)]`. The array column is deprecated.

## Validation Queries

### Check 1: Feature Coverage This Week vs Last Season

```sql
-- Compare current season to same period last season
WITH current_season AS (
  SELECT
    'Current' as period,
    COUNT(*) as total_records,
    COUNTIF(feature_25_value > 0) as with_vegas_line,
    COUNTIF(feature_0_value > 0) as with_points_avg_5,
    COUNTIF(feature_5_value > 0) as with_fatigue,
    COUNTIF(feature_41_value > 0) as with_spread_mag,
    COUNTIF(feature_42_value > 0) as with_implied_total,
    COUNTIF(feature_31_value > 0) as with_minutes_avg
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
),
last_season AS (
  SELECT
    'Last Year' as period,
    COUNT(*) as total_records,
    COUNTIF(feature_25_value > 0) as with_vegas_line,
    COUNTIF(feature_0_value > 0) as with_points_avg_5,
    COUNTIF(feature_5_value > 0) as with_fatigue,
    COUNTIF(feature_41_value > 0) as with_spread_mag,
    COUNTIF(feature_42_value > 0) as with_implied_total,
    COUNTIF(feature_31_value > 0) as with_minutes_avg
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date >= DATE_SUB(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), INTERVAL 7 DAY)
    AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR)
)
SELECT
  period,
  total_records,
  ROUND(100.0 * with_vegas_line / total_records, 1) as vegas_line_pct,
  ROUND(100.0 * with_points_avg_5 / total_records, 1) as points_avg_pct,
  ROUND(100.0 * with_fatigue / total_records, 1) as fatigue_pct,
  ROUND(100.0 * with_spread_mag / total_records, 1) as spread_mag_pct,
  ROUND(100.0 * with_implied_total / total_records, 1) as implied_total_pct,
  ROUND(100.0 * with_minutes_avg / total_records, 1) as minutes_avg_pct
FROM current_season
UNION ALL
SELECT * FROM last_season
```

**Expected**: Current season should be within 5% of last season for all features.

**Alert thresholds**:
- CRITICAL: vegas_line < 80% (was 99%+ last season)
- WARNING: Any feature >10% below last season
- OK: Within 5% of last season

### Check 2: Weekly Trend (Catch Gradual Degradation)

```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as records,
  ROUND(100.0 * COUNTIF(feature_25_value > 0) / COUNT(*), 1) as vegas_line_pct,
  ROUND(100.0 * COUNTIF(feature_0_value > 0) / COUNT(*), 1) as points_avg_pct,
  ROUND(100.0 * COUNTIF(feature_5_value > 0) / COUNT(*), 1) as fatigue_pct,
  ROUND(100.0 * COUNTIF(feature_41_value > 0) / COUNT(*), 1) as spread_mag_pct,
  ROUND(100.0 * COUNTIF(feature_8_value IS NOT NULL) / COUNT(*), 1) as usage_spike_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
GROUP BY 1
ORDER BY 1 DESC
```

**Alert thresholds**:
- CRITICAL: Week-over-week drop >20%
- WARNING: Consistent decline for 3+ weeks
- OK: Stable or improving

### Check 3: Feature Value Distribution Drift

```sql
-- Detect if feature values shifted significantly
WITH current_stats AS (
  SELECT
    'Current' as period,
    ROUND(AVG(feature_25_value), 1) as avg_vegas_line,
    ROUND(STDDEV(feature_25_value), 2) as std_vegas_line,
    ROUND(AVG(feature_0_value), 1) as avg_points_5,
    ROUND(AVG(feature_41_value), 2) as avg_spread_mag,
    ROUND(STDDEV(feature_41_value), 2) as std_spread_mag,
    ROUND(AVG(feature_8_value), 3) as avg_usage_spike,
    ROUND(STDDEV(feature_8_value), 3) as std_usage_spike,
    ROUND(AVG(feature_22_value), 1) as avg_team_pace,
    ROUND(AVG(feature_38_value), 1) as avg_game_total
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND feature_25_value > 0  -- Only where populated
),
last_year_stats AS (
  SELECT
    'Last Year' as period,
    ROUND(AVG(feature_25_value), 1) as avg_vegas_line,
    ROUND(STDDEV(feature_25_value), 2) as std_vegas_line,
    ROUND(AVG(feature_0_value), 1) as avg_points_5,
    ROUND(AVG(feature_41_value), 2) as avg_spread_mag,
    ROUND(STDDEV(feature_41_value), 2) as std_spread_mag,
    ROUND(AVG(feature_8_value), 3) as avg_usage_spike,
    ROUND(STDDEV(feature_8_value), 3) as std_usage_spike,
    ROUND(AVG(feature_22_value), 1) as avg_team_pace,
    ROUND(AVG(feature_38_value), 1) as avg_game_total
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date >= DATE_SUB(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), INTERVAL 30 DAY)
    AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR)
    AND feature_25_value > 0
)
SELECT * FROM current_stats UNION ALL SELECT * FROM last_year_stats
```

### Check 3B: Constant-Value Detection (Session 375)

**Would have caught Feature 41 ALL ZEROS bug within 24 hours.**

```sql
-- Detect features with suspiciously low variance (constant-value bugs)
SELECT
  'feature_41' as feature, 'spread_magnitude' as name,
  COUNT(*) as n,
  ROUND(AVG(feature_41_value), 4) as mean_val,
  ROUND(STDDEV(feature_41_value), 4) as stddev_val,
  COUNT(DISTINCT ROUND(feature_41_value, 2)) as distinct_vals,
  COUNTIF(feature_41_value = 0) as zero_count,
  CASE WHEN STDDEV(feature_41_value) < 1.0 AND COUNT(DISTINCT ROUND(feature_41_value, 2)) < 5
       THEN 'FAIL' ELSE 'OK' END as status
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
UNION ALL
SELECT
  'feature_42', 'implied_team_total',
  COUNT(*), ROUND(AVG(feature_42_value), 4), ROUND(STDDEV(feature_42_value), 4),
  COUNT(DISTINCT ROUND(feature_42_value, 2)), COUNTIF(feature_42_value = 0),
  CASE WHEN STDDEV(feature_42_value) < 2.0 AND COUNT(DISTINCT ROUND(feature_42_value, 2)) < 5
       THEN 'FAIL' ELSE 'OK' END
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
UNION ALL
SELECT
  'feature_22', 'team_pace',
  COUNT(*), ROUND(AVG(feature_22_value), 4), ROUND(STDDEV(feature_22_value), 4),
  COUNT(DISTINCT ROUND(feature_22_value, 2)), COUNTIF(feature_22_value = 0),
  CASE WHEN STDDEV(feature_22_value) < 0.5 AND COUNT(DISTINCT ROUND(feature_22_value, 2)) < 5
       THEN 'FAIL' ELSE 'OK' END
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
UNION ALL
SELECT
  'feature_38', 'game_total_line',
  COUNT(*), ROUND(AVG(feature_38_value), 4), ROUND(STDDEV(feature_38_value), 4),
  COUNT(DISTINCT ROUND(feature_38_value, 2)), COUNTIF(feature_38_value = 0),
  CASE WHEN STDDEV(feature_38_value) < 2.0 AND COUNT(DISTINCT ROUND(feature_38_value, 2)) < 5
       THEN 'FAIL' ELSE 'OK' END
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
UNION ALL
SELECT
  'feature_24', 'team_win_pct',
  COUNT(*), ROUND(AVG(feature_24_value), 4), ROUND(STDDEV(feature_24_value), 4),
  COUNT(DISTINCT ROUND(feature_24_value, 2)), COUNTIF(feature_24_value = 0),
  CASE WHEN STDDEV(feature_24_value) < 0.05 AND COUNT(DISTINCT ROUND(feature_24_value, 2)) < 5
       THEN 'FAIL' ELSE 'OK' END
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
```

**Alert thresholds**:
- FAIL: stddev below minimum AND distinct values below minimum = constant-value bug
- OK: Normal variance

**For comprehensive constant-value detection across ALL 57 features**, use:
```bash
python bin/validation/feature_distribution_health.py --date $(date +%Y-%m-%d)
```

## Integration with /validate-daily

Added as **Phase 0.493** in `/validate-daily`. Run the CLI tool:

```bash
python bin/validation/feature_distribution_health.py --date $(date +%Y-%m-%d)
```

Expected: PASS or WARN. FAIL requires investigation.

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
UNION ALL
SELECT
  'Last Year' as period,
  COUNT(*) / COUNT(DISTINCT game_date) as avg_records_per_day
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR), INTERVAL 7 DAY)
  AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR)
```

**Alert thresholds**:
- CRITICAL: Records/day increased >100% (indicates ALL players included, not just those with props)
- WARNING: Records/day changed >50%
- OK: Within 30% of last season

### Check 5: has_vegas_line Flag vs Actual Coverage

```sql
-- If has_vegas_line=1 but vegas_line=0, there's a data extraction bug
SELECT
  ROUND(100.0 * COUNTIF(feature_28_value = 1) / COUNT(*), 1) as has_line_flag_pct,
  ROUND(100.0 * COUNTIF(feature_25_value > 0) / COUNT(*), 1) as actual_line_pct,
  ROUND(100.0 * COUNTIF(feature_28_value = 1 AND feature_25_value = 0) / COUNT(*), 1) as mismatch_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
```

**Alert thresholds**:
- CRITICAL: mismatch_pct > 5% (flag says has line but value is 0)
- OK: mismatch_pct < 1%

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
  ROUND(100.0 * COUNTIF(feature_25_value > 0) / COUNT(*), 1) as vegas_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY 1
ORDER BY 1 DESC
```

If records are HIGH (300-500) but vegas_pct is LOW (<50%), the feature store was likely generated in **backfill mode** which includes all players but sets `has_prop_line=FALSE`.

**Fix:** Re-run feature store in production mode or fix backfill mode to join with betting data.

### Step 4: Check Phase 4 processor running
- Feature extraction query working?
- Check Cloud Run logs for errors

### Step 5: Run distribution health check (Session 375)
```bash
python bin/validation/feature_distribution_health.py --date $(date +%Y-%m-%d) --verbose
```
This checks ALL 57 features for constant values, zero-rate anomalies, NULL rates, distribution drift, and source cross-validation.

## Example Output

```
=== FEATURE DRIFT VALIDATION ===
Period: 2026-01-25 to 2026-02-01
Comparison: Same week last season (2025-01-25 to 2025-02-01)

FEATURE COVERAGE:
                  Current   Last Year   Delta    Status
vegas_line         43.4%      99.4%    -56.0%   CRITICAL
points_avg_5       99.8%      99.9%     -0.1%   OK
fatigue_score      91.2%      89.5%     +1.7%   OK
spread_magnitude   95.2%      94.8%     +0.4%   OK

CONSTANT-VALUE CHECK:
spread_magnitude   stddev=3.21  distinct=15  OK
implied_team_total stddev=4.87  distinct=22  OK
team_pace          stddev=2.14  distinct=28  OK

WEEKLY TREND (vegas_line):
Week         Coverage   Change
2026-01-25    43.4%     -2.1%
2026-01-18    45.5%     +3.0%
2026-01-11    42.5%    -15.4%  Drop
2026-01-04    57.9%     --

RECOMMENDATION:
1. Investigate Odds API scraper for Jan 2026
2. Check player matching in upcoming_player_game_context
3. Consider backfilling feature store after fix

This issue explains the model hit rate degradation in Jan 2026.
```

## Related Skills

- `/validate-daily` - Add feature check to Priority 2 (includes Phase 0.493)
- `/validate-historical` - Add feature store coverage
- `/hit-rate-analysis` - Cross-reference when hit rates drop
- `/spot-check-features` - Distribution Health Audit section

---
*Created: Session 61 - After discovering vegas_line feature degradation*
*Updated: Session 375 - Fixed deprecated features[OFFSET(N)] → feature_N_value columns, added constant-value detection (Check 3B), expanded monitored features, added CLI tool reference*
*This validation would have caught the Jan 2026 issue weeks earlier and the Feature 41 bug within 24 hours*
