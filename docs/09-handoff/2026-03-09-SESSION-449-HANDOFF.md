# Session 449 Handoff — Session 448 Cleanup + Next Priorities

**Date:** 2026-03-09
**Focus:** Completed all remaining Session 448 TODOs + identified next priorities

## What Was Done

This session finished the Session 448 infrastructure fixes that were interrupted by context loss.

### Fixes Applied (Session 448b continuation)

| Fix | Details |
|-----|---------|
| `monthly-retrain` CF redeployed | `db-dtypes` dependency now included. Revision `monthly-retrain-00002-biy` ACTIVE |
| `monthly-retrain/deploy.sh` hardened | `--set-env-vars` → `--update-env-vars`, `--allow-unauthenticated` → `--no-allow-unauthenticated` |
| `decay-detection` SQL bug fixed | `check_pick_volume_anomaly`: `BETWEEN...AND game_date <` → `>= ... AND game_date <` |
| Cloud Build trigger: `deploy-morning-deployment-check` | Auto-deploys on push to main, watches `functions/monitoring/morning_deployment_check/**` |
| Cloud Build trigger: `deploy-monthly-retrain` | Auto-deploys on push to main, watches `orchestration/cloud_functions/monthly_retrain/**` |
| `bin/deploy-function.sh` | Added `morning-deployment-check` + `monthly-retrain` to function registry + usage help |
| `CLAUDE.md` | Updated auto-deploy list with both new CFs |
| Session 448 handoff doc | Updated with all resolutions, all TODOs marked ✅ |

### Verified Working

- `decay-detection-daily` scheduler: fired at 16:00 UTC Mar 8, HTTP 200
- 7 BLOCKED models detected in `model_performance_daily` (Mar 7): xgb_v12_noveg, catboost_v12_noveg, catboost_v16_noveg, lgbm_v12_noveg (3 variants), xgb_v12_noveg_s42
- Auto-disable should fire on next decay-detection run (16:00 UTC today)
- All 8 scheduler job fixes from Session 448 still cached old status — will clear on next scheduled execution

## Uncommitted Changes

```
Modified:
  CLAUDE.md                                          (auto-deploy list, common issues)
  bin/deploy-function.sh                             (morning-deployment-check + monthly-retrain entries)
  orchestration/cloud_functions/decay_detection/main.py  (SQL bug fix)
  orchestration/cloud_functions/monthly_retrain/deploy.sh  (--update-env-vars, --no-allow-unauthenticated)
  docs/02-operations/session-learnings.md            (Gen2 CF URL mismatch + timeout patterns)
  docs/02-operations/troubleshooting-matrix.md       (3 new rows)
  docs/09-handoff/2026-03-08-SESSION-448-HANDOFF.md  (all TODOs resolved)

Also modified (from prior sessions, not yet committed):
  bin/replay_per_model_pipeline.py
  ml/signals/per_model_pipeline.py
  shared/config/cross_model_subsets.py
  + several MLB files
  + several new untracked files (docker/, results/, docs/)
```

**ACTION NEEDED:** These changes need to be committed and pushed. The decay-detection SQL fix and deploy.sh fixes will auto-deploy on push.

## Next Priorities (Ranked)

### 1. Commit & Push (immediate)
Push the accumulated changes from Sessions 445-449. This triggers auto-deploy of the decay-detection SQL fix.

### 2. Verify Scheduler Jobs Clear (after next execution cycle)
Run `/validate-daily` — all 8 previously-failing scheduler jobs should show code=0.

### 3. Verify BLOCKED Models Auto-Disabled (after 16:00 UTC)
After decay-detection fires today, check:
```sql
SELECT system_id, is_active FROM nba_predictions.model_registry
WHERE system_id IN ('xgb_v12_noveg_train0107_0219', 'lgbm_v12_noveg_train1102_0209',
  'lgbm_v12_noveg_vw015_train1215_0208', 'lgbm_v12_noveg_train0103_0227',
  'catboost_v12_noveg_train0107_0219', 'catboost_v16_noveg_train0105_0221',
  'xgb_v12_noveg_s42_train1215_0208')
```

### 4. Per-Model Pipeline Replay & Deploy (biggest pending feature)
Session 445 built `per_model_pipeline.py` (1,621 lines) + `pipeline_merger.py` (366 lines). Replaces winner-take-all with per-model aggregation + pool-and-rank merge. **NOT YET DEPLOYED** — needs:
```bash
python bin/replay_per_model_pipeline.py  # Season replay validation
```
Then compare results vs current system, get user sign-off, deploy.

### 5. Re-enable catboost_v9_train1102_0108
On the TODO list since Session 445.

### 6. Observation Promotion Check
Several observations accumulating data — check if any hit promotion thresholds (HR >= 60% + N >= 30):
- `hot_shooting_reversion_obs`, `over_low_rsc`, `mae_gap`, `thin_slate`
- `hot_streak_under`, `solo_game_pick`, `depleted_stars_over_obs`

### 7. UNDER Signal Expansion
UNDER is 71% HR but bottlenecked by signal coverage (907 candidates/day → 25 BB picks at 2.8%). Signals are OVER-oriented — UNDER picks left on table.

## Key Context for New Session

- **Algorithm version:** `v442_autopsy_observations`
- **9 enabled models**, 7 BLOCKED (pending auto-disable)
- **Top performers:** catboost_v12_train0104_0222 (82.4%), catboost_v12_noveg_train0104_0215 (76.9%)
- **Mar 8 was a caution day** — 7/9 models showed UNDER_HEAVY (RED signal)
- **Per-model pipeline** is the biggest unreleased feature — read Session 445 handoff for architecture
