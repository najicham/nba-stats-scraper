# Session 332 Handoff — Tonight Re-Export Fix, Completeness Checker Bug, Full Pipeline Recovery

**Date:** 2026-02-22
**Previous Session:** 331 — VOID/DNP Fix, Daily Steering, Weekend Pipeline Check

## What Was Done

### 1. Fixed "Waiting on Results" bug — tonight JSON re-export

**Problem:** Frontend showed "Waiting on Results" indefinitely for finished games because `actual_points` was null in `tonight/all-players.json`. The `live_export` CF stops refreshing at ~1 AM ET, and no subsequent pipeline step re-exported tonight JSON after actuals became available.

**Fix:** Added step 6 to `post_grading_export` Cloud Function — re-exports `tonight/all-players.json` via `TonightAllPlayersExporter` after grading completes.

**Commit:** `0b72da74` — `feat: add tonight JSON re-export to post-grading pipeline`

**Files changed:**
- `orchestration/cloud_functions/post_grading_export/main.py` — Added step 6, updated version to 1.3
- `docs/08-projects/current/frontend-data-design/10-WAITING-ON-RESULTS-BUG.md` — Added backend response with answers to 5 frontend questions

### 2. Diagnosed and fixed completeness checker CASE WHEN bug

**Problem:** 4 of 11 games (CLE@OKC, DAL@IND, PHI@MIN, POR@PHX) had zero predictions. Root cause: `TeamDefenseZoneAnalysisProcessor` only produced data for 11/30 teams because the completeness checker's `_query_expected_games_team` had a CASE WHEN that attributed each game only to the home team when both teams were in the list. This undercounted expected games by ~50%, dropping 19 teams below the 70% production_ready threshold.

**Fix:** Replaced CASE WHEN with UNNEST to count both home and away games per team.

**Commit:** `b4a2dd7e` — `fix: completeness checker CASE WHEN undercounting team games by ~50%`

**File changed:** `shared/utils/completeness_checker.py` lines 318-330

### 3. Updated overnight-phase4 scheduler for same-day TDZA

**Problem:** No scheduler job ran `TeamDefenseZoneAnalysisProcessor` for TODAY with `backfill_mode=true`. The 7 AM job processes YESTERDAY; the 6 AM job only ran `MLFeatureStoreProcessor`.

**Fix:** Updated `overnight-phase4` (6 AM ET) to run all 5 Phase 4 processors with `backfill_mode=true`:
- TeamDefenseZoneAnalysisProcessor
- PlayerShotZoneAnalysisProcessor
- PlayerCompositeFactorsProcessor
- PlayerDailyCacheProcessor
- MLFeatureStoreProcessor

**Command:** `gcloud scheduler jobs update http overnight-phase4 ...`

### 4. Manual pipeline recovery for Feb 22

Ran manual TDZA + MLFeatureStore rebuild, then triggered prediction batch:

| Metric | Before Recovery | After Recovery |
|--------|----------------|----------------|
| Games with predictions | 7/11 | **11/11** |
| V9 predictions | 84 | **184** |
| Players with lines | 52 | **151** |
| Clean players (feature store) | ~27 | **132** |
| Best bets | 0 | **4 picks** |

Re-exported tonight JSON and signal best bets to GCS.

### 5. Fixed two non-fatal warnings

**Commit:** `e34465a8` — `fix: SQL escape in model_direction_affinity, Decimal serialization in signal_subset_materializer`

1. **`ml/signals/model_direction_affinity.py`** — Removed invalid `\_` backslash escapes from LIKE patterns. BigQuery standard SQL treats `_` as literal; the backslash caused "Illegal escape sequence" errors.

2. **`data_processors/publishing/signal_subset_materializer.py`** — Added `Decimal`-to-`float` conversion in `_write_rows` before `insert_rows_json`, matching the existing pattern in `subset_materializer.py`.

## Bugs Found & Fixed

| Bug | Impact | Fix | Status |
|-----|--------|-----|--------|
| Tonight JSON not re-exported after grading | "Waiting on Results" indefinitely | Added step 6 to post_grading_export | DEPLOYED |
| Completeness checker CASE WHEN | 19/30 teams fail completeness → 4+ games with 0 predictions | UNNEST both home/away teams | DEPLOYED |
| No same-day TDZA scheduler | Defense features missing for today's predictions | Updated overnight-phase4 to run all processors | DEPLOYED |
| SQL `\_` escape in model_direction_affinity | Query error (non-fatal, caught by try/except) | Removed backslash escapes | DEPLOYED |
| Decimal serialization in signal_subset_materializer | BQ insert fails for signal subsets (non-fatal) | Added Decimal→float conversion | DEPLOYED |

## Architecture Insight: Phase 4 Timing Chain

```
5:30 PM ET (day before) — same-day-phase4-tomorrow: PCF + MLFS for TOMORROW (Pub/Sub trigger)
                          TDZA also runs via Pub/Sub but WITHOUT backfill_mode → completeness check fails for some teams
6:00 AM ET — overnight-phase4: ALL 5 processors for TODAY with backfill_mode=true ← FIXED (was MLFS only)
7:00 AM ET — overnight-phase4-7am-et: ALL 5 processors for YESTERDAY with backfill_mode=true
11:00 AM ET — same-day-phase4: MLFS only for TODAY
```

The 6 AM job now ensures defense data is complete for today before predictions run.

## What's NOT Done

1. **All-Star break amplification** — The break (Feb 13-18) reduced rolling game counts, making the completeness bug worse. The UNNEST fix resolves this, but worth monitoring next year's break.
2. **Completeness checker still uses f-string SQL** — Not parameterized. Low risk (team_ids are internal), but could be improved.

## Deploy Status

All 3 commits pushed to main, auto-deploying:
- `0b72da74` — post_grading_export CF (Cloud Build confirmed WORKING)
- `b4a2dd7e` — shared/utils (deploys with all services)
- `e34465a8` — ml/signals + data_processors/publishing

## For Next Session

- Monitor tomorrow's 6 AM overnight-phase4 run — verify all 5 processors complete and all 30 teams have defense data
- Check that post-grading export step 6 (tonight re-export) fires after grading completes
- 4 best bets generated for tonight — check grading results tomorrow
