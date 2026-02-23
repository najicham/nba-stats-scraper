# Session 329 Handoff — Backfill Angles Restored + Env Var Drift Fixed

**Date:** 2026-02-22
**Previous Session:** 328 — Admin Dashboard Picks Funnel + Public Best Bets Polish

## What Was Done

### 1. P1: Re-ran backfill to restore pick_angles in BQ (Jan 9 - Feb 21)

Session 327's ultra backfill had overwritten all `pick_angles` to `[]` in `signal_best_bets_picks`. Session 328 fixed the code (added `build_pick_angles()` + `CrossModelScorer` to backfill script).

This session re-ran the full backfill:
```bash
PYTHONPATH=. python bin/backfill_dry_run.py --start 2026-01-09 --end 2026-02-21 --write
```
**Result:** 105/105 picks now have angles. Zero gaps. ~8 min runtime.

**Backfill summary:** 67W-32L (67.7% HR). Weekly breakdown:
- Jan 9 week: 22W-10L (69%)
- Jan 16 week: 16W-6L (73%)
- Jan 23 week: 9W-1L (90%)
- Jan 30 week: 7W-4L (64%)
- Feb 6 week: 10W-8L (56%)
- Feb 13 week: 2W-2L (50%)
- Feb 20 week: 1W-1L (50%)

### 2. P2: Fixed BEST_BETS_MODEL_ID env var drift

**Finding:** Both `phase6-export` and `post-grading-export` CFs had `BEST_BETS_MODEL_ID=catboost_v12` — stale from a prior model evaluation. Production champion is `catboost_v9`.

**Impact analysis:** Multi-model pick selection (`multi_model=True`) queries all CatBoost families and is NOT affected. The env var only affected:
- Direction health queries (was computing V12 HR instead of V9)
- Admin dashboard `champion_id` label
- Decay detection model selection

**Fix:** Removed `BEST_BETS_MODEL_ID` from both CFs via Cloud Run service update. They now fall back to code default (`CHAMPION_MODEL_ID = 'catboost_v9'`).

### 3. P3: Verified angles restored

```sql
SELECT COUNT(*) as total_picks,
       COUNTIF(ARRAY_LENGTH(pick_angles) > 0) as has_angles,
       COUNTIF(ARRAY_LENGTH(pick_angles) = 0) as no_angles
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-01-09'
-- Result: 105 total, 105 has_angles, 0 no_angles
```

### 4. Triggered Phase 6 re-export

Published `nba-phase6-export-trigger` with `best-bets-all`, `admin-dashboard`, `admin-picks` for 2026-02-23.

### 5. Updated session-learnings.md

Added two new entries:
- **Backfill Script Overwrites pick_angles** — root cause and prevention
- **Stale BEST_BETS_MODEL_ID Env Var** — detection and cleanup procedure

## Follow-Up (Next Session)

None critical. All P1-P3 items from Session 328 are resolved.

**Optional:**
- Monitor ultra performance — trending down (2-3 last 2 weeks vs 14-1 before). May need criteria tightening if trend continues.
- Ultra OVER gate: 17-2 (89.5%, N=19). Need 50 for public exposure. ~10 weeks at current pace.

## Key Observations

- **0 picks on 2026-02-22:** Post-All-Star thin slate. Max edge 4.9 across all models. Edge floor (5.0) correctly rejected all 44 candidates.
- **Player blacklist growing:** By Feb 3+, 4 players blocked (jarenjacksonjr 0%, jabarismithjr 12.5%, treymurphyiii 30%, lukadoncic 33.3%). Blacklist working as intended.
- **Model families expanded mid-season:** Jan 9-22 had 2 families (v12_mae, v9_mae). By Feb 19, 7 families active (v12_mae, v12_q43, v12_q45, v9_low_vegas, v9_mae, v9_q43, v9_q45).
