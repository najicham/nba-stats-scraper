# Session 128B Handoff - Daily Validation & Bug Fixes

**Date:** 2026-02-05
**Focus:** Comprehensive daily validation for Feb 4 game date, bug fixes

---

## Summary

Ran comprehensive daily validation for 2026-02-04 game date. Discovered and fixed multiple critical issues affecting data quality and prediction accuracy.

## Issues Fixed This Session

### 1. Edge Filter Bug in OddsAPI Processor (P1 CRITICAL)

**Problem:** When oddsapi_batch_processor updates predictions with new Vegas lines, it set `recommendation = 'HOLD'` for low-edge predictions but did NOT set `is_actionable = FALSE`. This caused 78 predictions to have OVER/UNDER recommendations on low-edge bets.

**Fix:** Added `is_actionable = FALSE` and `filter_reason = 'low_edge'` to the UPDATE query.

**File:** `data_processors/raw/oddsapi/oddsapi_batch_processor.py` (lines 505-513)

### 2. DNP Recency Filter for Player Cache (P2)

**Problem:** 12 players on extended DNP (30-90 days inactive) were being cached with stale "last 10" averages from months ago (Bradley Beal, Zach Edey, etc.).

**Fix:** Added 30-day recency filter. Players with no active game in 30+ days are now skipped with category `STALE_DATA`.

**Files:**
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
- `data_processors/precompute/player_daily_cache/worker.py`

### 3. Missing Games Reprocessed

**Problem:** CLE_LAC and MEM_SAC games missing from player_game_summary (5/7 games)

**Root Cause:** Change detection uses BDL, extraction uses gamebook - source mismatch

**Fix:** Triggered reprocessing with `backfill_mode: true`. All 7 games now in player_game_summary.

**Commit:** `a7dc5d9d`

---

## Issues NOT Fixed (Handled by Other Session)

- **Model tier calibration** - Being addressed by another chat session
- **Edge filter in prediction-worker** - Part of model calibration work
- **Model bias (-9.7 pts for stars)** - Model team handling

---

## Deployment Status

| Service | Status | Notes |
|---------|--------|-------|
| nba-phase4-precompute-processors | 🔄 Pending | Contains DNP recency fix |
| nba-phase2-raw-processors | 🔄 Pending | Contains oddsapi edge filter fix |
| Cloud Functions | ⏳ Pending | phase3_to_phase4, phase4_to_phase5 |

**Note:** Network TLS timeouts during deployment. Run manually:

```bash
./bin/deploy-service.sh nba-phase4-precompute-processors
./bin/deploy-service.sh nba-phase2-raw-processors
```

---

## Key Investigation Findings

### 1. Source Mismatch in Change Detection

The incremental change detection system has a fundamental flaw:
- **Change detection** queries `bdl_player_boxscores`
- **Extraction** queries `nbac_gamebook_player_stats`
- When BDL arrives late, gamebook-only players are excluded

**Recommendation:** Align change detection to use gamebook (future fix)

### 2. Model Bias Confirmed

- Stars (25+ pts): -9.7 pts bias (worsening: was -5.4 in Jan)
- 6:1 UNDER skew in high-edge picks
- Tier calibration exists but not applied
- Being handled by other session

### 3. Vegas Line Coverage is EXPECTED

- 42.5% overall coverage is normal
- Sportsbooks only offer props for ~150 players
- Effective coverage for 15+ min players: 80.5%
- Update monitoring thresholds (alarm at 35%, not 80%)

### 4. Odds Coverage is Intermittent

Some days get 100% coverage, others 25-43%:
- Jan 24: 0% coverage
- Jan 25, 27, 29: 25-43% coverage
- Most other days: 100%

---

## Data Quality Metrics - Feb 4, 2026

| Metric | Before | After |
|--------|--------|-------|
| Games in analytics | 5/7 | **7/7** ✅ |
| Predictions gradable | 54% | ~100% (pending grading) |
| Hit rate | 42.5% | TBD (model issue) |
| DNP pollution | 12 players | 0 (after filter) |
| Minutes coverage | 58.5% | 100% ✅ |

---

## Commands for Next Session

```bash
# 1. Check deployment status
./bin/check-deployment-drift.sh --verbose

# 2. If stale, deploy
./bin/deploy-service.sh nba-phase4-precompute-processors
./bin/deploy-service.sh nba-phase2-raw-processors

# 3. Verify Feb 4 games complete
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT game_id) as games
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-02-04'"

# 4. Check edge filter working (after deployment)
bq query --use_legacy_sql=false "
SELECT is_actionable, COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-05'
  AND ABS(predicted_points - current_points_line) < 3
  AND line_source != 'NO_PROP_LINE'
GROUP BY 1"

# 5. Run grading backfill for Feb 4
PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2026-02-04 --end-date 2026-02-04
```

---

## Files Changed

```
data_processors/precompute/player_daily_cache/player_daily_cache_processor.py  (+43 lines)
data_processors/precompute/player_daily_cache/worker.py                        (+16 lines)
data_processors/raw/oddsapi/oddsapi_batch_processor.py                         (+9 lines)
orchestration/cloud_functions/phase3_to_phase4/main.py                         (+54 lines)
orchestration/cloud_functions/phase4_to_phase5/main.py                         (+77 lines)
docs/08-projects/current/session-128-validation-issues/README.md               (new)
```

---

## Documentation Created

- `docs/08-projects/current/session-128-validation-issues/README.md` - Full investigation details

---

## Follow-up Tasks

1. [ ] Complete deployments (Phase 2 & Phase 4)
2. [ ] Deploy Cloud Functions (phase3_to_phase4, phase4_to_phase5)
3. [ ] Run grading backfill for Feb 4
4. [ ] Future: Fix change detection source mismatch
5. [ ] Future: Update Vegas coverage monitoring thresholds

---

*Session 128B - Daily Validation & Bug Fixes*
*Commit: a7dc5d9d*
