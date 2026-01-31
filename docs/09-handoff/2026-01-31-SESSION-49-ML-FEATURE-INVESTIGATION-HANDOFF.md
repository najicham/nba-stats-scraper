# Session 49 Handoff: ML Feature Store Comprehensive Investigation

**Date:** 2026-01-31
**Session:** 49
**Focus:** Comprehensive ML feature quality investigation
**Status:** Investigation complete, fixes committed, backfill pending

---

## Read First (Priority Order)

```bash
# 1. Comprehensive investigation findings
cat docs/08-projects/current/feature-quality-monitoring/SESSION-49-COMPREHENSIVE-INVESTIGATION.md

# 2. Admin dashboard enhancement proposal
cat docs/08-projects/current/feature-quality-monitoring/ADMIN-DASHBOARD-PROPOSAL.md

# 3. Project README (updated with all bugs)
cat docs/08-projects/current/feature-quality-monitoring/README.md

# 4. Combined findings from Sessions 47-48
cat docs/08-projects/current/feature-quality-monitoring/COMBINED-FINDINGS.md
```

---

## Executive Summary

Session 49 conducted a **comprehensive audit of all 37 ML features**. We discovered 6 bugs affecting the majority of historical data (127K+ records).

### Bugs Fixed This Session

| Bug | Feature | Impact | Commit |
|-----|---------|--------|--------|
| `days_rest == 0` → `== 1` | `back_to_back` (16) | 100% zeros | `a7381972` |
| Missing `team_abbr` passthrough | `team_win_pct` (24) | 99.8% = 0.5 | `1c8d84d3` |
| Added variance validation | All 37 features | Prevention | `72d1ba8d` |

### Bugs Found (Upstream Issues - Not Fixed)

| Bug | Feature | Impact | Root Cause |
|-----|---------|--------|-----------|
| `projected_usage_rate` = NULL | `usage_spike_score` (8) | 98.8% zeros | Never implemented |
| `opponent_pace_last_10` = NULL | `pace_score` (7) | 93.9% zeros | Broken upstream |
| Impossible values (up to 24) | `games_in_last_7_days` (4) | 546 records | Unknown (Dec 2025+) |

### Not Bugs (Working as Designed)

| Feature | Observation | Explanation |
|---------|-------------|-------------|
| `injury_risk` (10) | 99.3% zeros | No injury report = healthy = 0 |
| `recent_trend` (11) | Only 5 values | Intentionally bucketed [-2, -1, 0, 1, 2] |

---

## CatBoost V8 Model Clarification

**The model uses 34 features** (not 33 or 37):

- Model file: `catboost_v8_33features_*.cbm` (misleading name)
- Actual features: 34 (added `has_shot_zone_data` on 2026-01-25)
- ML feature store has 37 features (includes experimental: dnp_rate, slope, zscore, breakout)

---

## Commits Made This Session

```bash
git log --oneline -5
# b2ee9af5 docs: Add comprehensive Session 49 ML feature investigation findings
# a7381972 fix: Correct back_to_back calculation from days_rest==0 to days_rest==1
# 72d1ba8d feat: Add batch variance validation to detect constant feature values
# 1c8d84d3 fix: Add team_abbr to get_players_with_games for team_win_pct calculation
# df8995b6 docs: Add combined findings and next session handoff for feature quality
```

---

## Current Deployment Status

| Service | Revision | Has Fix? | Notes |
|---------|----------|----------|-------|
| Phase 4 (precompute) | 00086-fcc | ✅ team_win_pct, variance validation | Deployed |
| Phase 3 (analytics) | ? | ❌ back_to_back | **NEEDS DEPLOY** |

---

## Pending Tasks (Priority Order)

### Priority 1: Deploy Phase 3 with back_to_back fix

```bash
# Deploy Phase 3 analytics processors
./bin/deploy-service.sh nba-phase3-analytics-processors

# Verify deployment
gcloud run services describe nba-phase3-analytics-processors --region=us-west2 --format="value(status.latestReadyRevisionName)"
```

### Priority 2: Historical Backfill (127K+ records)

**Order matters - cascade dependencies:**

1. Backfill `upcoming_player_game_context` (Phase 3) - fixes back_to_back
2. Backfill `player_composite_factors` (Phase 4) - picks up corrected values
3. Backfill `ml_feature_store_v2` (Phase 4) - regenerates all features

**Backfill commands:**
```bash
# Phase 3: upcoming_player_game_context (back_to_back fix)
python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2026-01-30

# Phase 4: ML feature store (team_win_pct + back_to_back)
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2026-01-30
```

**Note:** This is a LARGE backfill (~127K records). Consider:
- Running in date chunks (e.g., 1 season at a time)
- Running overnight
- Monitoring for quota issues

### Priority 3: Investigate games_in_last_7_days Bug

```sql
-- Find when impossible values started
SELECT game_date, COUNT(*) as count
FROM nba_predictions.ml_feature_store_v2
WHERE features[OFFSET(4)] > 5  -- games_in_last_7_days > 5 (impossible)
  AND game_date >= '2025-12-01'
GROUP BY 1
ORDER BY 1;
```

Look in:
- `data_processors/precompute/player_daily_cache/` - where this is calculated
- Check if there's a window calculation bug

### Priority 4: Add ML Feature Health Tab to Admin Dashboard

See: `docs/08-projects/current/feature-quality-monitoring/ADMIN-DASHBOARD-PROPOSAL.md`

Create:
- `services/admin_dashboard/blueprints/feature_health.py`
- `services/admin_dashboard/templates/components/feature_health.html`

Query source: `nba_monitoring_west2.feature_health_daily`

### Priority 5: Set Up Scheduled Query for Daily Health Monitoring

```bash
# Create scheduled query in BigQuery
bq query --use_legacy_sql=false --destination_table=nba_monitoring_west2.feature_health_daily \
  --schedule="every day 06:00" \
  --location=us-west2 \
  < schemas/bigquery/monitoring/feature_health_daily.sql
```

### Priority 6: Fix Upstream Issues (Longer Term)

**usage_spike_score (98.8% zeros):**
- Root cause: `projected_usage_rate` is 100% NULL in `upcoming_player_game_context`
- File: `data_processors/analytics/upcoming_player_game_context/player_stats.py`
- Needs: Implement usage rate calculation from play-by-play or possession data

**pace_score (93.9% zeros):**
- Root cause: `opponent_pace_last_10` is 65-100% NULL
- File: `data_processors/analytics/upcoming_player_game_context/team_context.py`
- Needs: Fix the team pace lookup query

---

## Verification Commands

### Check Feature Health
```bash
bq query --use_legacy_sql=false --location=us-west2 "
SELECT feature_name, health_status, ROUND(mean,2) as mean,
  ROUND(zero_pct,1) as zero_pct, ARRAY_TO_STRING(alert_reasons, ', ') as alerts
FROM nba_monitoring_west2.feature_health_daily
WHERE report_date >= CURRENT_DATE() - 3
ORDER BY health_status, feature_name"
```

### Check team_win_pct Variance (Should See Values After Backfill)
```bash
bq query --use_legacy_sql=false --location=us-west2 "
SELECT game_date,
  ROUND(AVG(features[OFFSET(24)]), 3) as avg_win_pct,
  COUNT(DISTINCT ROUND(features[OFFSET(24)], 2)) as distinct_values
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-01-25'
GROUP BY 1 ORDER BY 1"
```

### Check back_to_back (Should See Non-Zero After Backfill)
```bash
bq query --use_legacy_sql=false --location=us-west2 "
SELECT game_date,
  COUNTIF(features[OFFSET(16)] = 1) as back_to_back_true,
  COUNTIF(features[OFFSET(16)] = 0) as back_to_back_false,
  COUNT(*) as total
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-01-25'
GROUP BY 1 ORDER BY 1"
```

---

## Key Files Reference

| Purpose | File |
|---------|------|
| back_to_back fix | `data_processors/analytics/upcoming_player_game_context/player_stats.py:61` |
| team_win_pct fix | `data_processors/precompute/ml_feature_store/feature_extractor.py:154,179` |
| Variance validation | `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py:230-338` |
| ML feature backfill | `backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py` |
| Health table schema | `schemas/bigquery/monitoring/feature_health_daily.sql` |
| Admin dashboard | `services/admin_dashboard/blueprints/data_quality.py` |
| Investigation docs | `docs/08-projects/current/feature-quality-monitoring/SESSION-49-COMPREHENSIVE-INVESTIGATION.md` |
| Dashboard proposal | `docs/08-projects/current/feature-quality-monitoring/ADMIN-DASHBOARD-PROPOSAL.md` |

---

## Prevention Mechanisms Added

### 1. Batch Variance Validation (Active)

```python
# ml_feature_store_processor.py
FEATURE_VARIANCE_THRESHOLDS = {
    24: (0.05, 5, 'team_win_pct'),    # Detects constant 0.5
    5: (5.0, 10, 'fatigue_score'),    # Detects constant 50.0
    16: (0.1, 2, 'back_to_back'),     # Detects all zeros
    # ... 10 features monitored
}
```

### 2. Pre-Write Range Validation (Active)
- 37 features validated against min/max ranges
- Critical violations block writes

### 3. Feature Health Monitoring Table (Needs Scheduled Query)
- Daily statistics per feature
- Baseline comparison (30-day rolling)
- Health status: healthy/warning/critical

---

## What NOT To Do

1. **Don't backfill ML feature store before Phase 3** - The fixes cascade from upstream
2. **Don't fix usage_spike_score yet** - Requires play-by-play data implementation
3. **Don't worry about injury_risk = 99% zeros** - This is correct behavior
4. **Don't expect team_win_pct fix in old data** - Needs backfill first

---

## Success Criteria for Next Session

1. ✅ Phase 3 deployed with back_to_back fix
2. ✅ At least one date range backfilled and verified
3. ✅ back_to_back shows ~15-20% true (not 0%)
4. ✅ team_win_pct shows variance (0.24-0.80, not all 0.5)
5. ✅ games_in_last_7_days bug root cause identified

---

## Quick Start for Next Session

```bash
# 1. Check current status
cat docs/09-handoff/2026-01-31-SESSION-49-ML-FEATURE-INVESTIGATION-HANDOFF.md

# 2. Verify Phase 4 deployment (should have variance validation)
gcloud run services describe nba-phase4-precompute-processors --region=us-west2 \
  --format="value(status.latestReadyRevisionName)"

# 3. Deploy Phase 3 with back_to_back fix
./bin/deploy-service.sh nba-phase3-analytics-processors

# 4. Test backfill on a single date first
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --dates 2026-01-28

# 5. Verify the fix worked
bq query --use_legacy_sql=false --location=us-west2 "
SELECT
  COUNTIF(features[OFFSET(16)] = 1) as b2b_true,
  COUNTIF(features[OFFSET(24)] != 0.5) as win_pct_varied
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-01-28'"
```

---

## Contact Points

- **Feature Quality Monitoring Project:** `docs/08-projects/current/feature-quality-monitoring/`
- **Data Quality Self-Healing Project:** `docs/08-projects/current/data-quality-self-healing/`
- **Admin Dashboard:** `services/admin_dashboard/`

---

*Session 49 Handoff - ML Feature Store Comprehensive Investigation*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
