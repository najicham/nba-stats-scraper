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

## Root Cause Checklist

When feature degradation is detected:

1. **Check upstream data sources**
   - Odds API scraper running? Check GCS files
   - BettingPros scraper running? Check GCS files
   - Player matching working? Check `upcoming_player_game_context.current_points_line`

2. **Check Phase 3 context**
   ```sql
   SELECT
     ROUND(100.0 * COUNTIF(current_points_line IS NOT NULL) / COUNT(*), 1) as pct
   FROM nba_analytics.upcoming_player_game_context
   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
   ```

3. **Check feature store generation**
   - Feature extraction query working?
   - Phase 4 processor running?

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
