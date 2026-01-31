# Combined Feature Quality Findings

**Sessions:** 47 + 48
**Date:** 2026-01-31
**Status:** Investigation complete, implementation in progress

---

## Executive Summary

Two investigation sessions identified the root causes for all ML feature quality issues:

| Feature | Session 47 Finding | Session 48 Finding | Final Status |
|---------|-------------------|-------------------|--------------|
| `fatigue_score` | Timing bug (Jan 30) | Refactor bug (Jan 25-30) + fix deployed | ✅ FIXED |
| `vegas_points_line` | "Not a bug" (limited coverage) | **REAL BUG**: missing `market_type` filter | ⚠️ FIX COMMITTED |
| `usage_spike_score` | Intentionally deferred | Confirmed: `projected_usage_rate = None` | ❌ TODO (by design) |
| `team_win_pct` | Not investigated | Not passed to final record | ❌ TODO |
| `pace_score` | Working (adjustment value) | Confirmed working | ✅ OK |
| `shot_zone_mismatch` | Working (adjustment value) | Confirmed working | ✅ OK |

---

## Reconciliation of Findings

### 1. Vegas Lines (Session 47 vs 48 DISAGREE)

**Session 47 conclusion:** "NOT A BUG - BettingPros only provides lines for ~8 star players per team (40-50% coverage expected)"

**Session 48 discovery:** There IS a bug - `feature_extractor.py:628` was missing `market_type = 'points'` filter.

**Evidence:**
```sql
-- Session 36 already fixed this in other files:
-- shared_ctes.py:212 ✅
-- betting_data.py:185 ✅
-- player_loader.py:710,940 ✅
-- feature_extractor.py:628 ❌ WAS MISSING

-- The query had:
WHERE bet_side = 'over'  -- Wrong: includes all prop types

-- Should have:
WHERE market_type = 'points' AND bet_side = 'over'  -- Correct
```

**Resolution:** Session 48 fixed this in commit `0ea398bd`. The 40-50% natural coverage IS real, but the bug was making it worse (67-100% zeros on some days).

---

### 2. Fatigue Score (Both sessions identified issues)

**Session 47 finding:** Jan 30 ML feature store generated 9 hours before source data existed → timing dependency bug

**Session 48 finding:** Jan 25-30 had refactor bug where `factor_scores['fatigue_score']` (adjustment -5 to 0) was used instead of `factor_contexts['fatigue_context_json']['final_score']` (raw 0-100)

**Both are correct - there were TWO bugs:**
1. **Refactor bug** (Jan 25+): Wrong value extracted from worker.py
2. **Timing bug** (Jan 30): Feature store ran before upstream data existed

**Resolution:**
- Refactor bug fixed in commits `cec08a99`, `c475cb9e`
- Backfill completed in Session 48 (Jan 25-30)
- Pre-write validation added to catch future issues

---

### 3. Usage Spike Score (Both sessions agree)

**Both sessions confirm:** `projected_usage_rate = None` in context_builder.py:295 (TODO comment)

**Implementation requires:**
- Play-by-play data ingestion
- Usage rate calculation from possession data
- Significant pipeline addition

**Status:** Intentionally deferred, not a bug

---

### 4. Team Win Pct (Session 48 only)

**Session 48 finding:** Value calculated in feature_calculator.py but never passed to final record

**Root cause:** Missing from context_builder.py output

**Status:** TODO - needs fix

---

## What's Been Implemented (Session 48)

| Implementation | Status | Commit |
|----------------|--------|--------|
| Fix Vegas query (`market_type = 'points'`) | ✅ Committed | `0ea398bd` |
| Pre-write validation (ML_FEATURE_RANGES) | ✅ Committed | `0ea398bd` |
| Feature health monitoring table | ✅ Created | `nba_monitoring_west2.feature_health_daily` |
| Fatigue backfill (Jan 25-30) | ✅ Complete | Cloud Run endpoint |
| Phase 4 deployment | ✅ Complete | Revision 00084-lqh |

---

## What Still Needs Deployment

| Item | Reason |
|------|--------|
| Phase 4 re-deploy | Pick up Vegas query fix + pre-write validation |
| ML Feature Store backfill (Jan 30) | Re-generate with correct fatigue values |

---

## What's Still TODO (Code Changes Needed)

| Task | Root Cause | Priority |
|------|-----------|----------|
| Fix `usage_spike_score` | `projected_usage_rate = None` | LOW (intentional) |
| Fix `team_win_pct` | Not passed to final record | MEDIUM |
| Integrate `schedule_context_calculator` | File exists but not called | LOW |
| Expand drift detector to 37 features | Currently only 12 | LOW |

---

## Correct Feature Ranges (Final)

Based on both sessions' investigations:

| Feature | Type | Expected Range | Mean Expected |
|---------|------|----------------|---------------|
| `fatigue_score` | Raw score | 0-100 | ~90 (well-rested) |
| `pace_score` | Adjustment | -8 to +8 | ~0 |
| `shot_zone_mismatch_score` | Adjustment | -15 to +15 | ~0 |
| `usage_spike_score` | Adjustment | -8 to +8 | 0 (not implemented) |
| `vegas_points_line` | Raw line | 5-60 | ~20 |
| `has_vegas_line` | Boolean | 0-1 | ~0.4-0.5 (40-50% coverage) |
| `team_win_pct` | Percentage | 0-1 | ~0.5 (should vary, currently stuck) |

---

## Key Learnings Combined

From Session 47:
1. Different factor types have different storage patterns (raw vs adjustment)
2. Expected Vegas coverage is ~40-50% (sportsbook data limitation)
3. Timing dependencies are critical (ML feature store must run AFTER upstream)
4. TODO markers indicate intentional gaps

From Session 48:
5. Query bugs can hide in multiple files (Vegas filter was fixed in 4 files, missed in 1)
6. Pre-write validation catches bugs in <1 hour vs 6 days
7. Monitoring tables enable proactive detection
8. Bytecode cache can cause stale code execution (ProcessPoolExecutor)

---

## Files Reference (Combined)

### Fixed in Session 48
- `data_processors/precompute/ml_feature_store/feature_extractor.py` - Vegas query fix
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` - Pre-write validation

### Fixed in Sessions 44-47
- `data_processors/precompute/player_composite_factors/worker.py` - Fatigue extraction + bytecode validation
- `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` - Fatigue extraction

### Still Need Fixes
- `data_processors/analytics/upcoming_player_game_context/calculators/context_builder.py:295` - usage_spike TODO
- `data_processors/analytics/upcoming_player_game_context/calculators/context_builder.py` - team_win_pct passthrough

---

*Combined from Sessions 47 + 48*
*Last updated: 2026-01-31*
