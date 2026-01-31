# Chat Prompts for Follow-up Investigations

Use these prompts to continue work in new Sonnet chats.

---

## Prompt 1: Shot Zone Data Fix

Copy/paste this into a new Sonnet chat:

```
I need help fixing the shot zone data quality issue in my NBA stats scraper project.

## Problem Summary

Shot zone rates are corrupted:
- Avg paint rate: 25.9% (should be 30-45%)
- Avg three rate: 61% (should be 20-50%)

## Root Cause

Data source mismatch in `player_game_summary`:
- `paint_attempts` and `mid_range_attempts` come from play-by-play data (BigDataBall/NBAC)
- `three_pt_attempts` comes from box score data

When play-by-play is missing for a player, paint/mid = 0 but three_pt = actual value, causing skewed rates.

## BigDataBall Coverage

Coverage was poor Jan 17-24 (0-30%), better Jan 25+ (86-100%).

## Files to Modify

1. `data_processors/analytics/player_game_summary/player_game_summary_processor.py`
   - Lines 1665, 2233: Change three_pt_attempts to use PBP source instead of box score

2. `data_processors/analytics/player_game_summary/sources/shot_zone_analyzer.py`
   - Add better tracking of incomplete zone data

3. `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`
   - Lines 99-180: Enhance safeguard to check data sources, not just NULL

## Goal

1. Ensure all zone data comes from the same source (play-by-play)
2. When zone data is incomplete, set rates to NULL (don't calculate with mixed sources)
3. Add a `zone_data_complete` flag to track data quality
4. Better error tracking so I get alerts when BDB data is missing

Please read the handoff doc at `docs/09-handoff/2026-01-31-SHOT-ZONE-DATA-INVESTIGATION.md` for full details, then implement the fix.
```

---

## Prompt 2: Model Drift Analysis & Retraining

Copy/paste this into a new Sonnet chat:

```
I need help analyzing the CatBoost V8 model drift and potentially retraining the model.

## Problem Summary

Model hit rate dropped from 60-66% (early Jan) to 25-42% (late Jan).

## Root Cause (Already Fixed)

Feature parameter mismatch was causing the model to use fallback values instead of actual data. This was fixed Jan 29 and deployed Jan 31.

## Current Status

- Fix deployed: prediction-worker-00051-mfb (Jan 31)
- Need to verify fix is working
- Need to assess if retraining is needed

## Questions to Answer

1. Is the fix working? Check today's predictions for:
   - `has_vegas_line = 1.0` (not 0.0)
   - `ppm_avg_last_10` = actual values (not 0.4)
   - Predictions in reasonable range (not 60+ points)

2. Should we retrain? Check:
   - MAE trend after fix
   - Hit rate trend after fix
   - Feature distribution drift

3. If retraining needed:
   - What date range to use?
   - Should we add recency weighting?
   - What features need adjustment?

## Key Files

- Model: `predictions/worker/prediction_systems/catboost_v8.py`
- Training: `ml/train_final_ensemble_v8.py`
- Root cause doc: `docs/08-projects/current/grading-validation/2026-01-29-catboost-v8-root-cause-identified.md`
- Handoff: `docs/09-handoff/2026-01-31-MODEL-DRIFT-INVESTIGATION.md`

Please read the handoff docs, verify the fix is working, and recommend next steps for model performance.
```

---

## Prompt 3: BDB Data Completeness & Retry System

Copy/paste this into a new Sonnet chat:

```
I need help improving the BigDataBall (BDB) data completeness and retry system.

## Problem Summary

BDB play-by-play data coverage was very poor Jan 17-24 (0-30%) but the system didn't alert me or retry properly.

## Current State

- `pending_bdb_games` table exists but is EMPTY (should have entries for missing games)
- BDB critical monitor exists (`bin/monitoring/bdb_critical_monitor.py`) but may not be running
- Shot zone data is incomplete when BDB is missing

## What I Need

1. **Better Detection**: When BDB data is missing for a game, it should be tracked in `pending_bdb_games`

2. **Retry Logic**:
   - Automatic retry when BDB data becomes available
   - Progressive backoff (30s, 60s, 2min)
   - Max retries before marking as failed

3. **Alerting**:
   - Alert if BDB coverage < 80% for yesterday's games
   - Alert if games are stuck in pending > 6 hours

4. **Error State**:
   - Mark games that can't get BDB data as "error" state
   - Let me know so I can investigate manually

## Key Files

- Shot zone analyzer: `data_processors/analytics/player_game_summary/sources/shot_zone_analyzer.py`
  - `_track_games_needing_bdb()` method
  - `persist_pending_bdb_games()` method
- BDB monitor: `bin/monitoring/bdb_critical_monitor.py`
- BDB scraper: `scrapers/bigdataball/bigdataball_pbp.py`

Please investigate why `pending_bdb_games` table is empty and implement better tracking and retry logic.
```

---

## Quick Reference

| Investigation | Handoff Doc | Priority |
|---------------|-------------|----------|
| Shot Zone Data | `docs/09-handoff/2026-01-31-SHOT-ZONE-DATA-INVESTIGATION.md` | P1 |
| Model Drift | `docs/09-handoff/2026-01-31-MODEL-DRIFT-INVESTIGATION.md` | P0 (fix deployed) |
| BDB Completeness | (covered in Shot Zone handoff) | P1 |
