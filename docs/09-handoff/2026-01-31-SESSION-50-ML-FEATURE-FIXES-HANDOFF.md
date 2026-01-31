# Session 50 Handoff: ML Feature Store Bug Fixes and Backfill

**Date:** 2026-01-31
**Session:** 50
**Focus:** Deploy fixes and verify back_to_back + team_win_pct corrections
**Status:** Fixes deployed and verified, historical backfill pending

---

## Session Summary

Deployed and verified fixes for two ML feature bugs identified in Session 49:
1. **back_to_back** - Now showing 9.8% true (was 0%)
2. **team_win_pct** - Now showing 14 distinct values (was all 0.5)

Also discovered and fixed a critical join bug that was blocking Phase 3 backfill.

---

## Bugs Fixed This Session

| Bug | Root Cause | Fix | Commit |
|-----|-----------|-----|--------|
| Phase 3 backfill failing | `g.game_id = s.nba_game_id` join mismatch (gamebook uses `YYYYMMDD_AWAY_HOME`, not NBA official format) | Changed to `g.game_id = s.game_id` | `fe0a3d85` |

## Bugs Fixed in Session 49 (Now Deployed)

| Bug | Fix | Commit |
|-----|-----|--------|
| back_to_back always 0 | Changed `days_rest == 0` to `days_rest == 1` | `a7381972` |
| team_win_pct always 0.5 | Added team_abbr passthrough | `1c8d84d3` |

---

## Current Deployment Status

| Service | Revision | Commit | Notes |
|---------|----------|--------|-------|
| Phase 3 (analytics) | 00157-zbb | fe0a3d85 | ✅ All fixes deployed |
| Phase 4 (precompute) | 00086-fcc | df4f0aea | ✅ team_win_pct fix deployed |

---

## Verification Results (2026-01-28)

After backfilling 2026-01-28:

```
+----------+-----------+---------+----------------+-------------------------+-------+
| b2b_true | b2b_false | b2b_pct | win_pct_varied | win_pct_distinct_values | total |
+----------+-----------+---------+----------------+-------------------------+-------+
|       32 |       294 |     9.8 |            305 |                      14 |   326 |
+----------+-----------+---------+----------------+-------------------------+-------+
```

✅ back_to_back: 32 players (9.8%) correctly marked as true
✅ team_win_pct: 14 distinct values (was all 0.5)

---

## Historical Backfill Plan

### Record Counts by Year

| Year | Records | Phase 3 First | Then ML Store |
|------|---------|---------------|---------------|
| 2021 | 12,569 | ~2 hours | ~1 hour |
| 2022 | 26,209 | ~4 hours | ~2 hours |
| 2023 | 24,265 | ~4 hours | ~2 hours |
| 2024 | 25,929 | ~4 hours | ~2 hours |
| 2025 | 31,233 | ~5 hours | ~2.5 hours |
| 2026 | 7,936 | ~1 hour | ~30 min |
| **Total** | **128,141** | ~20 hours | ~10 hours |

### Backfill Order (Critical)

**Phase 3 MUST be backfilled before ML Feature Store** because ML store reads `back_to_back` from Phase 3.

1. **Phase 3: upcoming_player_game_context** (fixes back_to_back)
2. **Phase 4: ml_feature_store_v2** (picks up corrected values)

### Backfill Commands (Run by Season)

```bash
# Phase 3 - 2025-26 Season
python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2025-10-22 --end-date 2026-01-30

# Phase 3 - 2024-25 Season
python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2024-10-22 --end-date 2025-06-23

# Phase 3 - 2023-24 Season
python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2023-10-24 --end-date 2024-06-18

# Phase 3 - 2022-23 Season
python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2022-10-18 --end-date 2023-06-13

# Phase 3 - 2021-22 Season
python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2021-10-19 --end-date 2022-06-17
```

Then after all Phase 3 is complete:

```bash
# ML Feature Store - All dates
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2026-01-30
```

### Recommendation: Run Overnight

The full backfill takes ~30 hours. Consider:
1. Run Phase 3 backfill overnight
2. Run ML feature store backfill the next night
3. Or use tmux/screen to run in background

---

## Known Issues Still to Investigate

### Priority 1: games_in_last_7_days Bug
- **Symptom**: Values up to 24 (impossible - only 7 days)
- **Scope**: 546 records (mostly Dec 2025+)
- **Investigation needed**: Check player_daily_cache calculation

```sql
-- Find affected records
SELECT game_date, COUNT(*) as count
FROM nba_predictions.ml_feature_store_v2
WHERE features[OFFSET(4)] > 5  -- games_in_last_7_days > 5 (impossible)
GROUP BY 1
ORDER BY 1 DESC
LIMIT 10
```

### Priority 2: usage_spike_score (98.8% zeros)
- **Root cause**: `projected_usage_rate` is 100% NULL in upstream
- **Needs**: Implementation of usage rate calculation

### Priority 3: pace_score (93.9% zeros)
- **Root cause**: `opponent_pace_last_10` is 65-100% NULL
- **Needs**: Fix team pace lookup query

---

## Verification Commands (After Backfill)

```bash
# Check back_to_back distribution (should be ~10-15% true)
bq query --use_legacy_sql=false --location=us-west2 "
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  ROUND(100.0 * COUNTIF(features[OFFSET(16)] = 1) / COUNT(*), 1) as b2b_pct,
  COUNT(*) as records
FROM nba_predictions.ml_feature_store_v2
GROUP BY 1 ORDER BY 1"

# Check team_win_pct variance (should have many distinct values)
bq query --use_legacy_sql=false --location=us-west2 "
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(DISTINCT ROUND(features[OFFSET(24)], 2)) as distinct_win_pcts,
  COUNTIF(features[OFFSET(24)] = 0.5) as constant_0_5
FROM nba_predictions.ml_feature_store_v2
GROUP BY 1 ORDER BY 1"
```

---

## Commits This Session

```
fe0a3d85 fix: Correct game_id join in gamebook_players_with_games_cte
```

---

## Files Modified

| File | Change |
|------|--------|
| `data_processors/analytics/upcoming_player_game_context/queries/shared_ctes.py` | Fixed join from `s.nba_game_id` to `s.game_id` |

---

## Quick Start for Next Session

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-01-31-SESSION-50-ML-FEATURE-FIXES-HANDOFF.md

# 2. Check current back_to_back status across all years
bq query --use_legacy_sql=false --location=us-west2 "
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  ROUND(100.0 * COUNTIF(features[OFFSET(16)] = 1) / COUNT(*), 1) as b2b_pct
FROM nba_predictions.ml_feature_store_v2
GROUP BY 1 ORDER BY 1"

# 3. If back_to_back is still 0% for most years, start Phase 3 backfill
# Start with current season for fastest feedback:
python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2025-10-22 --end-date 2026-01-30

# 4. Then ML feature store
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2025-10-22 --end-date 2026-01-30
```

---

## Success Criteria for Backfill

1. ✅ back_to_back shows ~10-15% true across all years (not 0%)
2. ✅ team_win_pct shows 10+ distinct values per year (not all 0.5)
3. ✅ No Phase 3 backfill failures due to NULL game_id

---

*Session 50 Handoff - ML Feature Store Bug Fixes and Backfill*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
