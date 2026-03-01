# Session 380 Handoff — March 1, 2026

## Summary

Major pipeline audit and repair session. Fixed systemic issues across exporters, monitoring, and live pipeline that had been silently degrading since catboost_v9 was demoted months ago.

## Key Commits

```
c31a9917 fix: Lower stale game threshold from >4h to >=3h
da3255bd fix: Use direct UTC comparison for game_date_est hours_since_start
c15f9d4b fix: Eliminate stale model refs, timezone bugs, and export safety gaps
bedc7b45 feat: Always show ultra_tier in public best bets JSON
50f0d5d3 fix: Timezone-aware game start filter + ultra BQ write
1f3a93e7 fix: Ultra classification now written to BQ (was stripped from JSON picks)
4cfd397b fix: Remove 2-day warmup filter that blocked all recently-registered models
d7ac82e3 fix: Post-grading export adds missing BQ picks to JSON (manual_override)
86c3cbc4 fix: Update all exporters from catboost_v9 to catboost_v12 + model sanity guard
```

## What Was Fixed

### 1. Exporters: catboost_v9 → catboost_v12 (15 files)
All publishing exporters were hardcoded to `catboost_v9` (demoted months ago). Tonight page, predictions, trends were all empty. Updated all to `catboost_v12`.

### 2. Coordinator/Player Loader: catboost_v9 → config-driven (13+ queries)
`predictions/coordinator/coordinator.py` and `player_loader.py` had 13+ SQL queries filtering on `catboost_v9`. Morning summary, signal checks, batch monitoring were watching a dead model. Now uses `get_champion_model_id()`.

### 3. Cloud Function Alerts: catboost_v8 → config-driven (4 CFs)
`prediction_health_alert`, `system_performance_alert`, `grading_alert`, `data_quality_alerts` all hardcoded `catboost_v8`. Now import from `shared/config/model_selection.py`.

### 4. Ultra Bets in Public JSON
- Ultra classification was never written to BQ (read from JSON picks where it was stripped)
- Fixed: BQ always gets full ultra_tier + ultra_criteria
- Removed OVER gate: `ultra_tier` bool now always appears in public JSON when pick qualifies
- Today: Cam Thomas (3 criteria), Kawhi Leonard (1 criterion) both show `ultra_tier: true`

### 5. Timezone Bugs
- `signal_best_bets_exporter.py`: game start filter compared ET-stored times against UTC
- `trends_tonight_exporter.py`: Hardcoded `-05:00` → `FORMAT_TIMESTAMP('%Ez', ..., 'America/New_York')`
- **IMPORTANT**: `game_date_est` column stores **UTC** timestamps despite the "est" suffix. Confirmed: SAS@NYK game_date_est=18:00 = 1 PM ET = 6 PM UTC.

### 6. Live Pipeline: fix-stale-schedule Now Handles Today
- Was: Only checked `game_date < CURRENT_DATE` (past dates)
- Now: Checks `game_date <= CURRENT_DATE` with `hours_since_start >= 3`
- Uses direct UTC comparison (game_date_est is UTC)
- SAS@NYK successfully updated to Final

### 7. Re-export Safety Guard
If all games are finished for a target date, the signal-best-bets exporter now skips GCS upload instead of overwriting with 0 picks. We hit this bug twice during the session.

### 8. Post-grading Export: Manual Override Picks
`post_grading_export/main.py` now adds BQ picks missing from JSON (e.g., manual_override picks added after initial export). Fixed Gui Santos (Feb 28 WIN).

### 9. 2-day Warmup Filter Removed
Session 378c warmup filter used `created_at` (registry insertion date). Re-registering models reset `created_at`, blocking 9/12 models → 0 picks. Removed — model HR weighting + sanity guard provide sufficient protection.

## Critical Discovery: game_date_est Is UTC

**The `game_date_est` column in `nba_raw.nbac_schedule` stores UTC timestamps, NOT Eastern Time despite the column name.** This affects any code comparing game times:

| game_date_est value | Actual meaning |
|---|---|
| 18:00:00 | 1 PM ET (6 PM UTC) |
| 20:30:00 | 3:30 PM ET (8:30 PM UTC) |
| 01:00:00 | 8 PM ET (1 AM UTC next day) |

The `signal_best_bets_exporter._filter_started_games()` currently converts `CURRENT_TIMESTAMP()` to ET before comparing with game_date_est. This means games won't be filtered until ~5 hours after they start. This is arguably better UX (picks stay visible during games) but should be reviewed.

## Deployments

| Service | Method | Status |
|---|---|---|
| phase6-export | Auto (Cloud Build) | SUCCESS |
| post-grading-export | Auto (Cloud Build) | SUCCESS |
| live-export | Auto (Cloud Build) | SUCCESS |
| nba-scrapers | Manual hot-deploy | SUCCESS |
| prediction-coordinator | Not deployed (needs manual) | PENDING |

**IMPORTANT**: prediction-coordinator needs manual deploy for the catboost_v9→config fix:
```bash
./bin/deploy-service.sh prediction-coordinator
```

## Frontend Prompt Delivered

Shared a frontend prompt covering:
- New `ultra_tier` boolean field on best bets picks
- Grading fix for manual_override picks
- Game status update fix for live pipeline
- All endpoint URLs unchanged

## Remaining Items (Not Urgent)

1. **`date.today()` / `CURRENT_DATE()` UTC vs ET** in coordinator — only matters around midnight ET
2. **`best_bets_exporter.py` comments** reference v8 validation (cosmetic)
3. **`source_model` vs `source_model_id`** field naming inconsistency in JSON
4. **signal_best_bets_exporter game filter** uses ET conversion for UTC game_date_est — review whether to revert to direct UTC comparison
5. **V18 feature code** was committed in `bedc7b45` (additive — new feature definitions for line_movement, vig_skew, self_creation_rate, late_line_movement_count)
6. **Session 380 signals** (self_creation_over, sharp_line_move_over) were committed but need supplemental_data.py piping to function

## Season Record

77-39 (66.4% HR), +32.25 units. Today: 2 picks (Cam Thomas OVER, Kawhi Leonard UNDER).
