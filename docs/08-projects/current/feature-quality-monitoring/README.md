# Feature Quality Monitoring System

**Created:** 2026-01-30
**Updated:** 2026-01-31 (Session 48)
**Status:** Partially Implemented
**Priority:** High (prevents fatigue_score-type bugs)

---

## Overview

A multi-layer system to detect ML feature quality issues before they impact predictions.

| Layer | Detection Time | Status |
|-------|---------------|--------|
| Pre-write validation | <1 hour | ✅ Implemented |
| Daily health monitoring | <24 hours | ✅ Implemented |
| Drift detection | <48 hours | ⚠️ Partial (12/37 features) |
| Real-time alerting | <30 min | ❌ Not implemented |

---

## Problem Statement

The fatigue_score=0 bug (Sessions 44-47) went undetected for 6 days because:
1. No automated monitoring compared feature values to historical baselines
2. Validation only checked if values were within bounds, not if they were *reasonable*
3. No alerting when feature distributions shifted dramatically

**Impact:** Wrong predictions for 6 days, 6,500+ corrupted records, lost accuracy.

---

## What's Been Implemented

### 1. Pre-Write Validation (Session 48)

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

**What it does:**
- Validates all 37 features against expected ranges before BigQuery write
- Critical violations (like fatigue_score out of 0-100) block the write
- Non-critical warnings are logged to `data_quality_issues` array

**Key code:**
```python
ML_FEATURE_RANGES = {
    5: (0, 100, True, 'fatigue_score'),   # CRITICAL - blocks write
    6: (-15, 15, False, 'shot_zone_mismatch_score'),
    # ... all 37 features
}

def validate_feature_ranges(features, player_lookup):
    """Validate before write. Returns (is_valid, warnings, critical_errors)"""
```

**Commit:** `0ea398bd`

---

### 2. Daily Health Monitoring Table (Session 48)

**Table:** `nba_monitoring_west2.feature_health_daily`

**What it does:**
- Stores daily statistics for each feature (mean, stddev, zeros, etc.)
- Computes health_status: 'healthy', 'warning', 'critical'
- Enables detecting issues within 24 hours

**Schema:**
```sql
CREATE TABLE nba_monitoring_west2.feature_health_daily (
  report_date DATE,
  feature_name STRING,
  mean FLOAT64,
  zero_count INT64,
  zero_pct FLOAT64,
  health_status STRING,  -- 'healthy', 'warning', 'critical'
  alert_reasons ARRAY<STRING>,
  ...
)
```

**File:** `schemas/bigquery/monitoring/feature_health_daily.sql`

**Current Data:** Populated with 7 days showing:
- `fatigue_score` - healthy (after backfill fix)
- `usage_spike_score` - warning (100% zeros - confirms bug)

---

### 3. Vegas Lines Query Fix (Session 48)

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py:628`

**What was fixed:**
- Added missing `market_type = 'points'` filter
- Was causing 67-100% zeros for vegas_opening_line/vegas_points_line

**Commit:** `0ea398bd`

---

## What's Still Needed

### High Priority

| Task | Description | Status |
|------|-------------|--------|
| Deploy Phase 4 | Activate pre-write validation | ❌ Pending |
| Scheduled query | Daily population of health table | ❌ Pending |
| Fix usage_spike_score | `projected_usage_rate = None` | ❌ Pending |
| Fix team_win_pct | Not passed to final record | ❌ Pending |

### Medium Priority

| Task | Description | Status |
|------|-------------|--------|
| Expand drift detector | 12 → 37 features | ❌ Pending |
| Add to /validate-daily | Feature health section | ❌ Pending |
| Real-time alerting | Slack alerts on critical | ❌ Pending |
| Integrate schedule_context_calculator | Hardcoded features | ❌ Pending |

---

## Quick Reference

### Check Feature Health
```sql
SELECT feature_name, health_status, ROUND(mean, 2), zero_pct
FROM nba_monitoring_west2.feature_health_daily
WHERE report_date >= CURRENT_DATE() - 3
ORDER BY health_status, report_date DESC;
```

### Check for Critical Validation Errors
```bash
grep "CRITICAL_VALIDATION\|BLOCKING_WRITE" /var/log/phase4.log
```

### Deploy Pre-Write Validation
```bash
./bin/deploy-service.sh nba-phase4-precompute-processors
```

---

## Feature Ranges Reference

All 37 features with expected ranges (from `ML_FEATURE_RANGES`):

| Idx | Feature | Min | Max | Critical |
|-----|---------|-----|-----|----------|
| 0 | points_avg_last_5 | 0 | 70 | No |
| 1 | points_avg_last_10 | 0 | 70 | No |
| 2 | points_avg_season | 0 | 70 | No |
| 3 | points_std_last_10 | 0 | 30 | No |
| 4 | games_in_last_7_days | 0 | 4 | No |
| **5** | **fatigue_score** | **0** | **100** | **Yes** |
| 6 | shot_zone_mismatch_score | -15 | 15 | No |
| 7 | pace_score | -8 | 8 | No |
| 8 | usage_spike_score | -8 | 8 | No |
| 9 | rest_advantage | -3 | 3 | No |
| 10 | injury_risk | 0 | 3 | No |
| 11 | recent_trend | -2 | 2 | No |
| 12 | minutes_change | -2 | 2 | No |
| 13 | opponent_def_rating | 90 | 130 | No |
| 14 | opponent_pace | 90 | 115 | No |
| 15 | home_away | 0 | 1 | No |
| 16 | back_to_back | 0 | 1 | No |
| 17 | playoff_game | 0 | 1 | No |
| 18 | pct_paint | 0 | 1 | No |
| 19 | pct_mid_range | 0 | 1 | No |
| 20 | pct_three | 0 | 1 | No |
| 21 | pct_free_throw | 0 | 0.5 | No |
| 22 | team_pace | 90 | 115 | No |
| 23 | team_off_rating | 90 | 130 | No |
| 24 | team_win_pct | 0 | 1 | No |
| 25 | vegas_points_line | 0 | 80 | No |
| 26 | vegas_opening_line | 0 | 80 | No |
| 27 | vegas_line_move | -15 | 15 | No |
| 28 | has_vegas_line | 0 | 1 | No |
| 29 | avg_points_vs_opponent | 0 | 70 | No |
| 30 | games_vs_opponent | 0 | 50 | No |
| 31 | minutes_avg_last_10 | 0 | 48 | No |
| 32 | ppm_avg_last_10 | 0 | 3 | No |
| 33 | dnp_rate | 0 | 1 | No |
| 34 | pts_slope_10g | -5 | 5 | No |
| 35 | pts_vs_season_zscore | -4 | 4 | No |
| 36 | breakout_flag | 0 | 1 | No |

---

## Known Broken Features

| Feature | Issue | Root Cause | Status |
|---------|-------|-----------|--------|
| usage_spike_score (8) | Always 0 | `projected_usage_rate = None` | ❌ TODO |
| team_win_pct (24) | Always 0.5 | Not passed to final record | ❌ TODO |
| vegas_opening_line (26) | Was 67-100% zeros | Missing `market_type` filter | ✅ Fixed |
| vegas_points_line (25) | Was 67-100% zeros | Missing `market_type` filter | ✅ Fixed |
| fatigue_score (5) | Was 0 (Jan 25-30) | Wrong value extracted | ✅ Fixed |

---

## Files Reference

| Purpose | File |
|---------|------|
| Pre-write validation | `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` |
| Vegas query fix | `data_processors/precompute/ml_feature_store/feature_extractor.py` |
| Health table schema | `schemas/bigquery/monitoring/feature_health_daily.sql` |
| Reference guide | `docs/06-reference/feature-quality-monitoring.md` |
| Session 48 handoff | `docs/09-handoff/2026-01-31-SESSION-48-FEATURE-QUALITY-MONITORING-HANDOFF.md` |

---

## Timeline

| Date | Session | Action |
|------|---------|--------|
| 2026-01-25 | - | Fatigue bug introduced (refactor) |
| 2026-01-30 | 44-47 | Bug discovered, root cause found |
| 2026-01-30 | 47 | Bytecode cache fix implemented |
| 2026-01-31 | 48 | Pre-write validation + monitoring table |
| TBD | - | Deploy Phase 4 with validation |
| TBD | - | Set up scheduled health query |

---

## Success Metrics

| Metric | Before | After | Target |
|--------|--------|-------|--------|
| Time to detect fatigue-type bug | 6 days | <24 hours | <1 hour |
| Feature coverage monitored | 12/37 | 4/37 (composite) | 37/37 |
| Pre-write validation | None | Implemented | Active |
| False positive rate | N/A | TBD | <5% |

---

*Last updated: 2026-01-31 (Session 48)*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
