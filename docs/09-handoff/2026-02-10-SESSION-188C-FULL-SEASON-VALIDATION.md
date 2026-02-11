# Session 188C — Full Season Data Validation & Grading Gap Investigation

**Date:** 2026-02-10
**Previous:** Session 188B (Phase 3/4 validation), Session 188 (breakout classifier fix)
**Audience:** Next session chat handling Phase 6 publishing and data quality

## Executive Summary

Validated Phase 3, Phase 4, and prediction grading across the entire 2025-26 season (Oct 22 - Feb 10). The data pipeline is healthy from Nov 4 onward with one critical gap: **catboost_v9 predictions on Feb 1-3 are all `is_active = FALSE` with no active replacements**, causing zero grading for those 3 dates. This is the Session 174 "orphaned staging" pattern — predictions were deactivated during regeneration but replacements were never consolidated.

## Critical Finding: Feb 1-3 catboost_v9 Predictions Inactive

### The Problem

513 `catboost_v9` predictions across Feb 1-3 have `is_active = FALSE`. Since the grading processor filters on `is_active = TRUE`, these predictions have **zero grading records**. All games on these dates are final with actual points available.

### Root Cause: Orphaned Supersede (Session 174 Pattern)

A regeneration/supersede process deactivated old predictions but the replacement batch was never consolidated to active status. Evidence:

| Date | Run Modes Present | is_active | Created | Notes |
|------|------------------|-----------|---------|-------|
| Jan 30 | NULL | **TRUE** | Feb 1 10:11 | Normal (pre-run_mode tracking) |
| Jan 31 | NULL | **TRUE** | Feb 1 10:11 | Normal |
| **Feb 1** | BACKFILL | **FALSE** | Feb 8 21:39 | No original predictions exist at all. BACKFILL added them Feb 8 but inactive. |
| **Feb 2** | OVERNIGHT, SAME_DAY | **FALSE** | Feb 2-3 | Original predictions exist but deactivated. No active replacements. |
| **Feb 3** | OVERNIGHT, PRE_GAME, BACKFILL | **FALSE** | Feb 2 - Feb 9 | Multiple run modes, all deactivated. |
| Feb 4 | BACKFILL(3), PRE_GAME(51), **OVERNIGHT(112)** | **Mixed** | Feb 3-10 | Has active OVERNIGHT predictions |
| Feb 5 | BACKFILL(42), OVERNIGHT(25), **OVERNIGHT(125)** | **Mixed** | Feb 5-10 | Has active OVERNIGHT predictions |

The pattern is clear: Feb 4+ has active OVERNIGHT predictions from regeneration. Feb 1-3 had their old predictions deactivated but no new active ones were created.

### Impact

- **Grading:** 3 days of catboost_v9 performance data missing. The grading service correctly skips inactive predictions.
- **Phase 6 publishing:** If Phase 6 exports filter on `is_active = TRUE`, these dates have zero catboost_v9 picks.
- **Model evaluation:** Any model comparison analysis (e.g., `compare-model-performance.py`) that queries `prediction_accuracy` will have a gap for Feb 1-3.

### `catboost_v9_2026_02` Also Affected

Same pattern — 513 predictions on Feb 1-3, all `is_active = FALSE`. This is the deprecated Feb 2 retrain model (UNDER bias). Less important since it's retired, but same fix applies.

### Recommended Fix

Set `is_active = TRUE` on the latest catboost_v9 prediction per player/game for Feb 1-3. These are the only predictions that exist — they weren't replaced by newer ones, they were orphaned.

```sql
-- STEP 1: Verify what we're about to update (DRY RUN)
SELECT game_date, system_id, COUNT(*) as to_reactivate
FROM nba_predictions.player_prop_predictions
WHERE system_id IN ('catboost_v9', 'catboost_v9_2026_02')
  AND game_date BETWEEN '2026-02-01' AND '2026-02-03'
  AND is_active = FALSE
GROUP BY 1, 2 ORDER BY 1, 2;

-- STEP 2: Reactivate (UPDATE DML)
UPDATE nba_predictions.player_prop_predictions
SET is_active = TRUE
WHERE system_id IN ('catboost_v9', 'catboost_v9_2026_02')
  AND game_date BETWEEN '2026-02-01' AND '2026-02-03'
  AND is_active = FALSE;

-- STEP 3: Verify reactivation
SELECT game_date, system_id, COUNTIF(is_active) as active, COUNTIF(NOT is_active) as inactive
FROM nba_predictions.player_prop_predictions
WHERE system_id IN ('catboost_v9', 'catboost_v9_2026_02')
  AND game_date BETWEEN '2026-02-01' AND '2026-02-03'
GROUP BY 1, 2 ORDER BY 1, 2;

-- STEP 4: Trigger grading for these dates
-- (run from CLI)
for date in 2026-02-01 2026-02-02 2026-02-03; do
  gcloud pubsub topics publish nba-grading-trigger \
    --project=nba-props-platform \
    --message="{\"target_date\":\"$date\",\"run_aggregation\":true}"
done

-- STEP 5: Verify grading completed
SELECT game_date, COUNT(*) as graded,
  COUNTIF(prediction_correct) as correct,
  ROUND(COUNTIF(prediction_correct) / COUNT(*) * 100, 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date BETWEEN '2026-02-01' AND '2026-02-03'
  AND system_id = 'catboost_v9'
GROUP BY 1 ORDER BY 1;
```

### Why This Wasn't Caught Earlier

1. **Daily validation looks at current day + 3-day window.** By the time Feb 1-3 predictions were deactivated (Feb 8 backfill), daily validation had moved on.
2. **No monitoring for "zero active predictions for a system_id on a game date."** Existing checks monitor prediction count, quality gates, and grading — but none check whether predictions are actually marked active.
3. **Grading service was stale until Session 187.** Even if grading had been triggered, the old code had other bugs. After deploying the fix, the `is_active = FALSE` filter still blocked grading.

### Prevention: Suggested Monitoring Addition

Add to daily validation or canary queries:
```sql
-- Alert: system_ids with predictions but zero active on any recent date
SELECT game_date, system_id,
  COUNT(*) as total_predictions,
  COUNTIF(is_active) as active_predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 7
  AND system_id IN ('catboost_v9')
GROUP BY 1, 2
HAVING COUNTIF(is_active) = 0
ORDER BY 1;
```

---

## Phase 3 Season Validation (Complete)

### player_game_summary

| Period | Schedule | PGS | Gap | Root Cause |
|--------|----------|-----|-----|------------|
| Oct 22-26 | 38 games | 4 | 34 missing | Raw data never scraped (pipeline not operational) |
| Oct 27+ | 497 | 499 | 0 | Perfect (+2 postponed games in Dec with old game_id format) |

**Verdict:** Oct opening week gap is permanent (no raw data exists). Not fixable, not impactful — outside model training window (Nov 2+).

### team_offense_game_summary

**100% complete for the entire season.** Every date Oct 22 - Feb 9 matches `schedule_games × 2` team records. Zero gaps.

---

## Phase 4 Season Validation (Complete)

### Table Coverage

| Table | First Date | Dates | Mid-Season Gaps |
|-------|-----------|-------|-----------------|
| `player_daily_cache` | Nov 1 | 100 | **None** |
| `player_composite_factors` | Nov 4 | 97 | **None** |
| `player_shot_zone_analysis` | Nov 4 | 97 | **None** |
| `team_defense_zone_analysis` | Nov 16 | 82 | **3** (Jan 23, Feb 6-7) |
| `daily_game_context` | — | 0 | N/A (unused placeholder) |
| `daily_opponent_defense_zones` | — | 0 | N/A (unused placeholder) |

### team_defense_zone_analysis Gaps — Not Impactful

3 gaps: Jan 23, Feb 6, Feb 7. Checked matchup quality on those dates:
- Jan 23: 99.0% matchup quality (vs 98.3% neighbors)
- Feb 6: 99.4%
- Feb 7: 98.6%

Matchup features come from `player_composite_factors` (zero gaps), not solely from `team_defense_zone_analysis`. **No backfill needed.**

### Unused Tables

`daily_game_context` and `daily_opponent_defense_zones` have schemas but zero records. Not referenced in any processor or prediction code — planned but never implemented.

---

## Phase 6 Publishing Implications

For the chat handling Phase 6 exports:

1. **Feb 1-3 catboost_v9 picks won't appear in exports** if Phase 6 filters on `is_active = TRUE`. After reactivation + grading, they will.
2. **All other dates (Nov 4+) are clean.** Phase 3 and Phase 4 data is complete and consistent.
3. **Oct 22 - Nov 3 have no predictions** — no pipeline data existed. Phase 6 doesn't need to worry about these dates.

---

## What Doesn't Need Backfilling

| Gap | Why Leave It |
|-----|-------------|
| Oct 22-26 PGS (34 games) | No raw data. Outside training window. |
| Oct 22-31 Phase 4 | Downstream of PGS. No predictions from this period. |
| Nov 1-3 low cache (<20 players) | Pipeline ramp-up. Minimal training impact. |
| Nov 4-15 team_defense_zone (12 days) | Historical. Matchup quality unaffected. |
| Jan 23, Feb 6-7 team_defense_zone | Matchup quality 98-100% without it. |
| Dec 28-29 duplicate game_ids | Cosmetic. Postponed games with old NBA.com format. |

---

## Action Items for Next Session

### Must Do
1. **Reactivate Feb 1-3 catboost_v9 predictions** — Run the UPDATE DML above to set `is_active = TRUE`
2. **Re-trigger grading for Feb 1-3** — After reactivation, publish to `nba-grading-trigger`
3. **Verify grading completed** — Check `prediction_accuracy` for Feb 1-3 catboost_v9 records

### Should Do
4. **Add "zero active predictions" monitoring** — Prevent this from happening silently again
5. **Investigate why Feb 1 had no original predictions** — Only BACKFILL exists (from Feb 8). Was the original prediction run skipped?

### Nice to Have
6. **Fix grading `yaml` import error** — `No module named 'yaml'` in post-grading validation (non-blocking but noisy)
7. **Fix `game_datetime_utc` column reference** — Tip time lookup query references non-existent column (non-blocking)
