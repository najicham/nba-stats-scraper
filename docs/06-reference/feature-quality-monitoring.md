# Feature Quality Monitoring Reference

**Created:** 2026-01-31 (Session 48)
**Purpose:** Prevent feature quality bugs from reaching production

---

## Overview

The feature quality monitoring system consists of three layers:

| Layer | Detection Time | Location |
|-------|---------------|----------|
| Pre-write validation | <1 hour | ml_feature_store_processor.py |
| Daily health monitoring | <24 hours | nba_monitoring_west2.feature_health_daily |
| Drift detection | <48 hours | shared/validation/feature_drift_detector.py |

---

## 1. Pre-Write Validation

### Purpose
Validate feature values against expected ranges BEFORE writing to BigQuery. Critical violations block the write entirely.

### Location
`data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

### Configuration

```python
# Feature index -> (min, max, is_critical, name)
ML_FEATURE_RANGES = {
    # Critical features (block writes if invalid)
    5: (0, 100, True, 'fatigue_score'),

    # Non-critical features (log warning, allow write)
    0: (0, 70, False, 'points_avg_last_5'),
    6: (-15, 15, False, 'shot_zone_mismatch_score'),
    # ... all 37 features
}
```

### Critical Features

Currently, only `fatigue_score` (index 5) is marked as critical. Add more as needed:

```python
# To make a feature critical, set is_critical=True
25: (0, 80, True, 'vegas_points_line'),  # Would block if invalid
```

### Behavior

1. **Critical violation**: Write blocked, record goes to `failed_entities`
2. **Warning violation**: Write allowed, logged to `data_quality_issues` array
3. **Valid**: Write proceeds normally

### Logs to Watch

```bash
# Critical violations (blocked)
grep "CRITICAL_VALIDATION" /var/log/phase4.log
grep "BLOCKING_WRITE" /var/log/phase4.log

# Warnings (allowed but logged)
grep "VALIDATION_WARNING" /var/log/phase4.log
```

---

## 2. Daily Health Monitoring Table

### Purpose
Track daily statistics for each feature to detect gradual degradation or sudden changes.

### Table
`nba_monitoring_west2.feature_health_daily`

### Key Columns

| Column | Purpose |
|--------|---------|
| `mean` | Average value (detect drift) |
| `zero_count` | Number of zeros (detect data loss) |
| `zero_pct` | Percentage zeros (threshold-based alerting) |
| `negative_count` | Negative values (should be 0 for most features) |
| `out_of_range_count` | Values outside expected range |
| `health_status` | 'healthy', 'warning', 'critical' |
| `alert_reasons` | Array of specific issues detected |

### Health Status Rules

```sql
CASE
  -- Critical
  WHEN feature_name = 'fatigue_score' AND zero_pct > 10 THEN 'critical'
  WHEN feature_name = 'fatigue_score' AND mean < 50 THEN 'critical'
  WHEN negative_count > 0 AND feature_name = 'fatigue_score' THEN 'critical'

  -- Warning
  WHEN zero_pct > 50 THEN 'warning'
  WHEN ABS(mean_change_pct) > 20 THEN 'warning'

  ELSE 'healthy'
END
```

### Query: Check Current Health

```sql
SELECT
  report_date,
  feature_name,
  ROUND(mean, 2) as mean,
  zero_count,
  ROUND(zero_pct, 1) as zero_pct,
  health_status,
  alert_reasons
FROM nba_monitoring_west2.feature_health_daily
WHERE report_date >= CURRENT_DATE() - 7
ORDER BY
  CASE health_status
    WHEN 'critical' THEN 1
    WHEN 'warning' THEN 2
    ELSE 3
  END,
  report_date DESC;
```

### Query: Populate Daily (Scheduled)

Run daily at 6 AM ET to analyze previous day:

```sql
INSERT INTO nba_monitoring_west2.feature_health_daily
WITH feature_stats AS (
  SELECT
    DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as report_date,
    'player_composite_factors' as source_table,
    f.feature_name,
    AVG(f.value) as mean,
    STDDEV(f.value) as stddev,
    COUNT(*) as total_records,
    COUNTIF(f.value = 0) as zero_count,
    COUNTIF(f.value < 0) as negative_count
  FROM nba_precompute.player_composite_factors
  CROSS JOIN UNNEST([
    STRUCT('fatigue_score' as feature_name, fatigue_score as value),
    STRUCT('shot_zone_mismatch_score', shot_zone_mismatch_score),
    STRUCT('pace_score', pace_score),
    STRUCT('usage_spike_score', usage_spike_score)
  ]) as f
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  GROUP BY f.feature_name
)
SELECT
  report_date,
  feature_name,
  source_table,
  mean,
  stddev,
  -- ... (see full query in schemas/bigquery/monitoring/feature_health_daily.sql)
FROM feature_stats;
```

---

## 3. ML Feature Store Features

### Complete Feature List (37 features)

| Index | Name | Expected Range | Critical |
|-------|------|----------------|----------|
| 0 | points_avg_last_5 | 0-70 | No |
| 1 | points_avg_last_10 | 0-70 | No |
| 2 | points_avg_season | 0-70 | No |
| 3 | points_std_last_10 | 0-30 | No |
| 4 | games_in_last_7_days | 0-4 | No |
| **5** | **fatigue_score** | **0-100** | **Yes** |
| 6 | shot_zone_mismatch_score | -15 to 15 | No |
| 7 | pace_score | -8 to 8 | No |
| 8 | usage_spike_score | -8 to 8 | No |
| 9 | rest_advantage | -3 to 3 | No |
| 10 | injury_risk | 0-3 | No |
| 11 | recent_trend | -2 to 2 | No |
| 12 | minutes_change | -2 to 2 | No |
| 13 | opponent_def_rating | 90-130 | No |
| 14 | opponent_pace | 90-115 | No |
| 15 | home_away | 0-1 | No |
| 16 | back_to_back | 0-1 | No |
| 17 | playoff_game | 0-1 | No |
| 18 | pct_paint | 0-1 | No |
| 19 | pct_mid_range | 0-1 | No |
| 20 | pct_three | 0-1 | No |
| 21 | pct_free_throw | 0-0.5 | No |
| 22 | team_pace | 90-115 | No |
| 23 | team_off_rating | 90-130 | No |
| 24 | team_win_pct | 0-1 | No |
| 25 | vegas_points_line | 0-80 | No |
| 26 | vegas_opening_line | 0-80 | No |
| 27 | vegas_line_move | -15 to 15 | No |
| 28 | has_vegas_line | 0-1 | No |
| 29 | avg_points_vs_opponent | 0-70 | No |
| 30 | games_vs_opponent | 0-50 | No |
| 31 | minutes_avg_last_10 | 0-48 | No |
| 32 | ppm_avg_last_10 | 0-3 | No |
| 33 | dnp_rate | 0-1 | No |
| 34 | pts_slope_10g | -5 to 5 | No |
| 35 | pts_vs_season_zscore | -4 to 4 | No |
| 36 | breakout_flag | 0-1 | No |

---

## 4. Quality Gate Hard Floor Rules (Session 139)

The prediction worker enforces hard floor quality rules before generating predictions. If a player's feature row fails these checks, predictions are skipped for that player and a `PREDICTIONS_SKIPPED` Slack alert is sent.

### Hard Floor Thresholds

| Rule | Threshold | Rationale |
|------|-----------|-----------|
| `feature_quality_score` | >= 50 | Below 50 indicates too many defaulted features |
| `quality_alert_level` | != 'red' | Red alerts indicate critical data issues |
| `matchup_quality_pct` | >= 25 | Matchup features are critical for accuracy |
| `default_feature_count` | <= 12 | More than 12 defaults means >30% of features are guesses |

### is_quality_ready Field

The `is_quality_ready` boolean in `ml_feature_store_v2` is computed during feature store writes and reflects whether a row passes all hard floor rules. The prediction worker checks this field to decide whether to generate predictions.

### Recovery: BACKFILL Mode

When predictions are skipped due to quality, they can be recovered the next day using BACKFILL mode:

```bash
# Trigger backfill for a specific date
curl -X POST https://prediction-coordinator-url/start \
  -H "Content-Type: application/json" \
  -d '{"game_date":"YYYY-MM-DD","prediction_run_mode":"BACKFILL"}'
```

BACKFILL mode relaxes quality gates since Phase 4 data is typically complete by the next day.

---

## 5. Known Feature Issues

### Currently Broken (as of Jan 2026)

| Feature | Issue | Root Cause | Status |
|---------|-------|-----------|--------|
| usage_spike_score (8) | Always 0 | `projected_usage_rate = None` | TODO |
| team_win_pct (24) | Always 0.5 | Not passed to final record | TODO |

### Recently Fixed

| Feature | Issue | Fix Date | Commit |
|---------|-------|----------|--------|
| fatigue_score (5) | Was 0 (Jan 25-30) | 2026-01-30 | cec08a99, c475cb9e |
| vegas_points_line (25) | 67-100% zeros | 2026-01-31 | 0ea398bd |
| vegas_opening_line (26) | 67-100% zeros | 2026-01-31 | 0ea398bd |

---

## 6. Troubleshooting

### Feature suddenly all zeros

1. Check health table:
   ```sql
   SELECT * FROM nba_monitoring_west2.feature_health_daily
   WHERE feature_name = 'fatigue_score'
   ORDER BY report_date DESC LIMIT 7;
   ```

2. Check source data:
   ```sql
   SELECT game_date, COUNT(*), AVG(fatigue_score)
   FROM nba_precompute.player_composite_factors
   WHERE game_date >= CURRENT_DATE() - 7
   GROUP BY 1 ORDER BY 1;
   ```

3. Check for blocked writes:
   ```bash
   grep "BLOCKING_WRITE" /var/log/phase4.log | tail -20
   ```

### Feature outside expected range

1. Check validation logs:
   ```bash
   grep "CRITICAL_VALIDATION" /var/log/phase4.log
   ```

2. Update ML_FEATURE_RANGES if range is legitimately wider

### Adding a new feature

1. Add to `FEATURE_NAMES` list
2. Add to `ML_FEATURE_RANGES` with expected range
3. Update `FEATURE_COUNT`
4. Add to daily health query if tracked separately

---

## 7. Files Reference

| Purpose | Location |
|---------|----------|
| Pre-write validation | `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` |
| Health table schema | `schemas/bigquery/monitoring/feature_health_daily.sql` |
| Drift detector | `shared/validation/feature_drift_detector.py` |
| Feature store validator | `shared/validation/feature_store_validator.py` |
| Quality columns reference | `docs/06-reference/quality-columns-reference.md` |

---

## 8. Historical Context

### The Fatigue Bug (Jan 2026)

A refactor changed `fatigue_score` from returning raw score (0-100) to returning adjustment (-5 to 0). This went undetected for 6 days because:

1. No pre-write validation existed
2. No daily monitoring existed
3. Detection relied on model performance degradation

**Impact:** 6,500+ records with wrong fatigue_score, model miscalibration

**Prevention:** This monitoring system would have caught it in <24 hours (daily monitoring) or <1 hour (pre-write validation if deployed).

---

*Last updated: 2026-02-06 (Session 139 - quality gate hard floor rules)*
