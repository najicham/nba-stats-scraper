# Session 175 Handoff

**Date:** 2026-02-09
**Previous:** Session 174

---

## What Was Done

### 1. P0/P1: Verified Pipeline Status
- **Feb 10 predictions:** Not yet generated (pipeline runs ~6 AM ET) — expected
- **Feb 9 games:** All 10 games still at status=1 (Scheduled) — no grading possible yet
- **Action:** Check Feb 10 FIRST-run after 6 AM ET tomorrow for bias (avg_pvl, OVER%)

### 2. P3: Hit Rate Investigation — CRITICAL FINDING

**Recommendation Direction Mismatch (Feb 4-8 BACKFILL data)**

Discovered that Feb 4-8 BACKFILL predictions have misaligned recommendations: predictions where `predicted_points > current_points_line` are marked as `UNDER` instead of `OVER`.

| Date | Above Line + OVER (correct) | Above Line + UNDER (BUG) | Total |
|------|---------------------------|--------------------------|-------|
| Feb 4 | 6 | **18** | 100 |
| Feb 5 | 4 | **17** | 104 |
| Feb 6 | 7 | **13** | 73 |
| Feb 7 | 13 | **22** | 137 |
| Feb 8 | 5 | **5** | 53 |
| **Feb 9 (regenerated)** | **20** | **0** | **67** |

**Root cause:** Feb 4-8 BACKFILL predictions were generated before Session 170 multi-line fix was deployed. The multi-line logic set recommendations based on aggregate of multiple lines, not the stored `current_points_line`. Feb 9 was regenerated in Session 174 with fixes deployed, so it has zero mismatches.

**Impact on hit rate measurement:** The reported 42.6% hit rate (Feb 1 week) includes these misaligned recommendations. Even filtering to correctly-aligned recommendations only improves it to 46.5%.

**Model decay trend (edge 3+):**

| Week | Graded | Hits | Hit Rate |
|------|--------|------|----------|
| Jan 12 | 127 | 91 | 71.7% |
| Jan 18 | 111 | 74 | 66.7% |
| Jan 25 | 101 | 56 | 55.4% |
| Feb 1 | 43 | 20 | 46.5% |
| Feb 8 | 9 | 3 | 33.3% (tiny sample) |

The model (trained Nov 2 - Jan 8) is decaying as it gets further from training data. **Model retrain recommended** once Feb data accumulates enough volume.

### 3. P4: Fixed subset_picks_notifier.py Correlated Subquery Bug

The `historical_performance` CTE in `_query_subset_picks()` used a correlated subquery (`WHERE game_date = p.game_date`) referencing the outer table. BigQuery rejects this pattern.

**Fix:** Added `majority_model_by_date` CTE that pre-computes the majority model version per day, then JOINs to it instead of using a correlated subquery. This eliminates the 8+/hour BQ errors.

### 4. P2: Added OddsAPI Diagnostic Logging

Added to `player_loader.py`:
- `_track_no_line_reason()` — per-player diagnostic when no line found. Checks if OddsAPI has ANY rows for the player (name mismatch) vs zero rows (not offered/not scraped).
- `diagnose_odds_api_coverage()` — batch-level diagnostic. Runs once per batch to report overall OddsAPI player count, bookmakers available, and coverage percentage.
- Integrated into coordinator.py to run after each batch.

### 5. Recommendation Direction Validation (Prevention)

Added defense-in-depth check in `worker.py` (after line 2008):
- After recommendation is assigned (from model or calculated), verifies it matches the predicted-vs-line direction
- If predicted > line but recommendation = UNDER (or vice versa), logs `RECOMMENDATION_DIRECTION_MISMATCH` warning and **corrects the recommendation**
- Prevents future misaligned recommendations regardless of root cause

---

## Prevention Mechanisms Added

| Prevention | What It Catches | Where |
|-----------|----------------|-------|
| Recommendation direction validation | pred > line marked as UNDER | `worker.py` (post-recommendation) |
| OddsAPI coverage diagnostic | Low/zero OddsAPI data for game date | `player_loader.py` + `coordinator.py` |
| Per-player no-line diagnostic | Name mismatch vs no data | `player_loader.py` |
| Correlated subquery fix | BQ query failures in notifier | `subset_picks_notifier.py` |

---

## Files Modified

| File | Change |
|------|--------|
| `predictions/worker/worker.py` | Recommendation direction validation (Session 175) |
| `predictions/coordinator/player_loader.py` | `_track_no_line_reason()`, `diagnose_odds_api_coverage()` methods |
| `predictions/coordinator/coordinator.py` | Batch-level OddsAPI coverage diagnostic call |
| `shared/notifications/subset_picks_notifier.py` | `majority_model_by_date` CTE replacing correlated subquery |

---

## Priority Work for Next Session

### P0: Verify Feb 10 FIRST-run (same as Session 174 P0)
First FIRST-run with ALL fixes deployed including Session 175's recommendation validation.

### P1: Grade Feb 9 Games
All 10 games are scheduled for today. Once Final, trigger grading if needed.

### P2: Regenerate Feb 4-8 Predictions
The Feb 4-8 BACKFILL predictions have misaligned recommendations (pre-Session 170). Need regeneration to get clean data for accurate hit rate measurement. Use `/regenerate-with-supersede` for each date.

### P3: Model Retrain Decision
Hit rate declining from 71.7% → 46.5%. After regenerating Feb 4-8 with clean recommendations, re-evaluate hit rate. If still below 55%, use `/model-experiment` to train with extended data through Jan 31.

### P4 (Low): OddsAPI Root Cause
With new diagnostic logging deployed, check Cloud Run logs after next prediction run to see if failures are "no data scraped" vs "player name mismatch".

---

## Key Queries

```sql
-- Check for recommendation direction mismatches (should be ZERO after Session 175)
SELECT game_date,
  COUNTIF(predicted_points > current_points_line AND recommendation = 'UNDER') as above_but_under,
  COUNTIF(predicted_points < current_points_line AND recommendation = 'OVER') as below_but_over,
  COUNT(*) as total
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9' AND game_date >= '2026-02-10'
  AND is_active = TRUE AND current_points_line IS NOT NULL
GROUP BY 1 ORDER BY 1;

-- Check OddsAPI coverage diagnostic (from Cloud Run logs)
-- Search for: ODDS_API_COVERAGE or NO_LINE_DIAGNOSTIC
```
