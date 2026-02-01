# Feature Quality Monitoring System

**Created:** 2026-01-30
**Updated:** 2026-02-01 (Session 63)
**Status:** CRITICAL - Daily vs Backfill Code Path Difference Identified
**Priority:** CRITICAL (V8 hit rate collapsed Jan 9+ due to daily orchestration issues)

---

## Overview

A multi-layer system to detect ML feature quality issues before they impact predictions.

| Layer | Detection Time | Status |
|-------|---------------|--------|
| Pre-write validation | <1 hour | ✅ Implemented |
| Daily health monitoring | <24 hours | ✅ Implemented |
| Drift detection (vs last season) | <48 hours | ✅ `/validate-feature-drift` skill (Session 61) |
| Real-time alerting | <30 min | ❌ Not implemented |

### Critical: Vegas Line Drift Incident (Session 61) - FIXED Session 62

**Root cause found:** Feature store `vegas_line` coverage dropped from **99.4%** (Jan 2025) to **43.4%** (Jan 2026).

This caused V8 hit rate to collapse from 70-76% to 48-67% (high-edge: 86% → 60%).

**Why:** 2025-26 season feature store was generated in backfill mode which includes ALL players but didn't join with betting data. Last season only included players with props.

**Fix Applied (Session 62):**
1. Modified `_batch_extract_vegas_lines()` to accept `backfill_mode` parameter
2. In backfill mode, queries raw betting tables (odds_api, bettingpros) instead of Phase 3
3. Added Vegas coverage check to `/validate-daily` skill

**Re-run required:** Feature store backfill for Nov 2025 - Feb 2026

**See:**
- `2026-02-01-VEGAS-LINE-DRIFT-INCIDENT.md` - Original discovery
- `2026-02-01-VEGAS-LINE-ROOT-CAUSE-ANALYSIS.md` - Detailed root cause & fix design

### CRITICAL: Daily vs Backfill Code Path Difference (Session 63)

**Root cause LIKELY identified:** Hit rate collapsed on **Jan 9, 2026** - the same day daily orchestration started running.

| Period | Hit Rate | Source |
|--------|----------|--------|
| Jan 1-7, 2026 | 62-70% | Backfilled |
| **Jan 9+, 2026** | **40-58%** | Daily orchestration |

**Key Difference Found:**

| Aspect | Daily Mode | Backfill Mode |
|--------|-----------|---------------|
| **Vegas Line Source** | Phase 3 (43% coverage) | Raw tables (95% coverage) |
| **Player Query** | `upcoming_player_game_context` | `player_game_summary` |
| **Completeness Checks** | Full validation | Skipped |

**Impact:** Daily mode gets Vegas lines from Phase 3 which only has 43% coverage, while backfill queries raw betting tables with 95% coverage.

**See:**
- `2026-02-01-SESSION-63-INVESTIGATION-FINDINGS.md` - Full investigation
- `V8-FIX-EXECUTION-PLAN.md` - Step-by-step fix plan

---

### Additional Issues Found (Session 63)

| Issue | Impact | Status |
|-------|--------|--------|
| pace_score = 0 for 100% | Broken feature | ❌ Needs fix |
| usage_spike_score = 0 for 100% | Broken feature | ❌ Needs fix |
| No `predicted_at` timestamp | Can't track when predictions made | ❌ Needs implementation |
| No `feature_source_mode` field | Can't distinguish daily vs backfill | ❌ Needs implementation |

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

## Prevention Mechanisms (Session 62)

### 1. Vegas Coverage Check in `/validate-daily`

Added Priority 2F check that alerts when vegas_line coverage drops below 80%:

```sql
SELECT
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_line_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND ARRAY_LENGTH(features) >= 33
-- ALERT if < 80%
```

### 2. Historical Baseline Comparison in `/validate-feature-drift`

Compares current coverage to same period last season. Alerts if >20% drop.

### 3. Backfill Mode Fix

`_batch_extract_vegas_lines()` now accepts `backfill_mode` parameter and queries raw betting tables directly for historical dates.

### 4. Unit Test Recommendation

Add test to verify backfill maintains >80% Vegas coverage:

```python
def test_backfill_vegas_coverage():
    players = extractor.get_players_with_games(date(2025, 1, 15), backfill_mode=True)
    extractor.batch_extract_all_data(date(2025, 1, 15), players, backfill_mode=True)
    with_vegas = sum(1 for p in players if extractor.get_vegas_lines(p['player_lookup']))
    assert with_vegas / len(players) >= 0.80
```

---

## What's Still Needed

### CRITICAL Priority (Session 63)

| Task | Description | Status |
|------|-------------|--------|
| **Fix daily Vegas source** | Daily mode should use raw tables like backfill | ❌ CRITICAL |
| Add `feature_source_mode` | Track 'daily' vs 'backfill' in feature store | ❌ Pending |
| Add `predicted_at` timestamp | Track when predictions were made | ❌ Pending |
| Re-run Jan 9+ predictions | Verify hypothesis by re-running with backfill | ❌ Pending |

### High Priority

| Task | Description | Status |
|------|-------------|--------|
| Re-run feature store backfill | Nov 2025 - Feb 2026 with fix | ❌ Pending |
| Deploy Phase 4 | Activate pre-write validation | ❌ Pending |
| Scheduled query | Daily population of health table | ❌ Pending |
| Fix usage_spike_score | `projected_usage_rate = None` | ❌ Pending |
| Fix pace_score | 100% zeros - investigate | ❌ Pending |
| Fix team_win_pct | Not passed to final record | ✅ Fixed |

### Medium Priority

| Task | Description | Status |
|------|-------------|--------|
| Add broken feature detection | Alert if pace_score or usage_spike 100% zeros | ❌ Pending |
| Daily vs backfill comparison | Dashboard to compare coverage | ❌ Pending |
| Expand drift detector | 12 → 37 features | ❌ Pending |
| Add to /validate-daily | Vegas coverage check | ✅ Added Session 62 |
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

## Known Broken Features (Session 49 Investigation)

### Critical Bugs (Fixed)

| Feature | Issue | Root Cause | Status | Commit |
|---------|-------|-----------|--------|--------|
| back_to_back (16) | **100% zeros** | `days_rest == 0` should be `== 1` | ✅ Fixed | a7381972 |
| team_win_pct (24) | 99.8% = 0.5 | `team_abbr` not passed through | ✅ Fixed | 1c8d84d3 |
| fatigue_score (5) | Was 0 (Jan 25-30) | Wrong value extracted | ✅ Fixed | cec08a99 |

### High Severity (Upstream Issues)

| Feature | Issue | Root Cause | Status |
|---------|-------|-----------|--------|
| usage_spike_score (8) | 98.8% zeros | `projected_usage_rate` 100% NULL upstream | ❌ Needs impl |
| pace_score (7) | 93.9% zeros | `opponent_pace_last_10` NULL upstream | ❌ Needs fix |
| games_in_last_7_days (4) | Values up to 24 | Bug since Dec 2025 | ⚠️ Investigate |

### Working as Designed

| Feature | Issue | Explanation | Status |
|---------|-------|-------------|--------|
| injury_risk (10) | 99.3% zeros | No injury report = healthy | ✅ Correct |
| vegas_opening_line (26) | ~50% zeros | BettingPros coverage limit | ✅ Expected |

### Validation Added

| Feature | Issue | Fix | Commit |
|---------|-------|-----|--------|
| vegas_opening_line (26) | Was 67-100% zeros | Added `market_type` filter | 0ea398bd |
| vegas_points_line (25) | Was 67-100% zeros | Added `market_type` filter | 0ea398bd |
| All 37 features | No variance check | Added batch variance validation | 72d1ba8d |

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
| 2026-02-01 | 61 | Vegas line drift discovered |
| 2026-02-01 | 62 | Vegas line backfill fix implemented |
| 2026-02-01 | 63 | **Daily vs backfill code path difference identified** |
| TBD | - | Fix daily Vegas source |
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

*Last updated: 2026-02-01 (Session 63 - Daily vs Backfill investigation)*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
