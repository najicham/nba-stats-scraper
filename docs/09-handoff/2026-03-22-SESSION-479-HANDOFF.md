# Session 479 Handoff — MLB Opening Day Prep + Canary Fixes + System Diagnostics

**Date:** 2026-03-22
**Previous:** Session 478 (grading outage fix, 8 monitoring improvements)

---

## TL;DR

Full system diagnostic. Fixed 3 canary script bugs (stale column names + catboost_v9 hardcodes). Populated MLB 2026 schedule data (Mar 27 - Apr 3) in BQ — was completely missing. Fixed broken `mlb-schedule-daily` scheduler (was sending wrong payload to wrong endpoint — 400 every day). Fleet state confirmed healthy: new `lgbm_v12_noveg_train1215_0214` already generating picks.

---

## What Was Done

### 1. Daily Steering Report

Full diagnostic run. Key findings:
- **Fleet**: Both enabled models (train0103_0227, train1215_0214) show INSUFFICIENT_DATA in model_performance_daily due to grading outage window. `train1215_0214` already has a LeBron UNDER pick for Mar 21 — working.
- **BB track record**: 8-4 (66.7%) last 14d, 50% last 30d (distorted by Mar 8 crash: 3-11).
- **Market regime**: LOOSE (vegas_mae 5.71), MAE gap 0.97 (model falling behind Vegas — can't retrain yet).
- **Edge 5+ health**: All models LOSING at edge 5+ in 14d window — but N=5-21 includes Mar 8 crash + grading outage. Not actionable until clean data accumulates.
- **Signals**: 20+ HOT, 8 COLD (behavioral only — no model-dependent COLD signals). No weight zeroing active.

### 2. Canary Script Bug Fixes (commit `7ea94d42`)

Fixed 3 bugs in `bin/monitoring/pipeline_canary_queries.py` that caused runtime 400 errors:

| Bug | Old | Fixed |
|-----|-----|-------|
| `model_performance_daily` columns | `system_id`, `model_state`, `n_graded_7d` | `model_id`, `state`, `rolling_n_7d` |
| `phase_completions` column | `phase_name` | `phase` |
| Phase 6 signal check | `system_id = 'catboost_v9'` (hardcoded dead model) | subquery against `model_registry WHERE enabled=TRUE` |
| Shadow coverage check | Champion=catboost_v9, shadow=catboost_v9_% | Rewritten: enabled model registry coverage check |

### 3. MLB 2026 Schedule — Populated (CRITICAL)

**Problem**: `mlb_raw.mlb_schedule` had zero 2026 data (ended 2025-09-28). Opening Day is March 27.

**Root cause chain**:
1. `mlb-schedule-daily` scheduler was sending `{"workflow": "mlb_schedule"}` to `/execute-workflow`
2. `/execute-workflow` expects `workflow_name` key → returned 400 "Missing required parameter"
3. Even with correct key, `mlb_schedule` isn't in `config/workflows.yaml` (NBA-only) → would return 404
4. The correct endpoint is `/scrape` with `{"scraper": "mlb_schedule"}`

**Fixed**: Updated `mlb-schedule-daily` scheduler URI and payload:
- Old: `POST /execute-workflow` with `{"workflow": "mlb_schedule"}`
- New: `POST /scrape` with `{"scraper": "mlb_schedule"}`

**Data populated**: Scraped and processed Mar 27 - Apr 3 directly:

| Date | Games |
|------|-------|
| Mar 27 (Opening Day) | 8 |
| Mar 28 | 15 |
| Mar 29 | 12 |
| Mar 30 | 15 |
| Mar 31 | 14 |
| Apr 1 | 15 |
| Apr 2 | 8 (off day) |
| Apr 3 | 14 |

**Scrape path**: GCS `gs://nba-scraped-data/mlb-stats-api/schedule/{date}/` → processed via `data_processors/raw/mlb/mlb_schedule_processor.py` with `SPORT=mlb` env var.

### 4. Fleet State Clarified

| Model | Registry | Performance |
|-------|----------|-------------|
| `lgbm_v12_noveg_train0103_0227` | enabled=TRUE | INSUFFICIENT_DATA (grading outage 7d window) |
| `lgbm_v12_noveg_train1215_0214` | enabled=TRUE, created Mar 21 | brand new, already generated LeBron UNDER pick |
| `lgbm_v12_noveg_vw015_train1215_0208` | enabled=FALSE, status=BLOCKED | HEALTHY 64.3% HR (7d, N=14) — was bridge model, blocked by decay detection |

Fleet is in transition but working. `train1215_0214` generated its first pick today.

---

## State of Key Tables (as of Mar 22)

| Table | Status |
|-------|--------|
| `mlb_raw.mlb_schedule` | ✅ Populated through Apr 3 (first week of 2026 season) |
| `prediction_accuracy` (NBA) | ✅ Current through Mar 20, Mar 21 pending tonight |
| `signal_best_bets_picks` | ✅ Mar 21 LeBron UNDER pick active |
| `model_performance_daily` | Will refresh tonight post-grading — INSUFFICIENT_DATA states are transient |
| `league_macro_daily` | ✅ Current through Mar 19 |

---

## Open Items / Next Session

### Must Do Before March 27 (MLB Opening Day)
- **Verify `mlb-predictions-generate` runs on March 27** — scheduler is NOT month-restricted (`0 13 * * *`) so it will fire. But it needs the schedule data populated (now done). Double-check predictions are generated the morning of Mar 27.
- **March 24**: `mlb-resume-reminder-mar24` fires 8 AM ET. Slack reminder will appear. Verify it triggers correctly and follow up with `./bin/mlb-season-resume.sh` if needed.
- **Pitcher props scraper**: `mlb-pitcher-props-validator-4hourly` is month-restricted (Apr-Oct). Opening Day is March, so pitcher prop lines won't be validated automatically. May need manual trigger on March 27.

### Monitor This Week (NBA)
- **lgbm_1215 first full week**: `lgbm_v12_noveg_train1215_0214` is brand new. Watch hit rate once 7+ picks accumulate. Deactivate if HR < 52.4% by Mar 25.
- **train0103_0227 INSUFFICIENT_DATA**: Should clear tonight as model_performance_daily refreshes after Mar 21 grading. If still INSUFFICIENT_DATA tomorrow, investigate why it's not generating gradable picks.
- **MAE gap 0.97**: Model falling behind Vegas. Cannot retrain (Vegas MAE gate at 5.0, current ~5.7). Monitor weekly.
- **Weekly-retrain CF**: Keep paused. Do NOT resume.
- **OVER floor at 5.0**: Do NOT lower. Wait for lgbm_1215 data.

### Known Constraints (Sessions 477-479)
- Do NOT resume `weekly-retrain` CF (Vegas MAE gate: 5.0)
- Do NOT re-enable `catboost_v9_low_vegas` (45.6% HR + sanity guard loop)
- Do NOT lower OVER floor to 4.5 (wait for lgbm_1215 full week)

---

## Key Files Changed This Session

```
bin/monitoring/pipeline_canary_queries.py   # 3 column name bugs + catboost_v9 hardcodes fixed
```

**Commits this session:**
- `7ea94d42` — canary script column name bugs + stale catboost_v9 references fixed

**Infrastructure changes (no code commit):**
- `mlb-schedule-daily` scheduler: URI updated from `/execute-workflow` to `/scrape`, payload fixed from `{"workflow": ...}` to `{"scraper": "mlb_schedule"}`
- MLB schedule data manually populated for Mar 27 - Apr 3 (via direct scraper invocation + processor run)

---

## Session Learnings Added

1. **mlb-schedule-daily scheduler broken** — Sending `{"workflow": "mlb_schedule"}` to `/execute-workflow`, but the endpoint expects `workflow_name` key, and `mlb_schedule` isn't in `config/workflows.yaml` (NBA-only). Fixed: now points to `/scrape` with `{"scraper": "mlb_schedule"}`. This was silently failing (400 response) and went undetected.

2. **MLB schedule processor requires `SPORT=mlb` env var** — Default is NBA. `get_raw_dataset()` returns `nba_raw` without it. Set `SPORT=mlb` when running any MLB processor locally.

3. **Canary column names drifted** — `model_performance_daily` evolved from `system_id`/`model_state`/`n_graded_7d` to `model_id`/`state`/`rolling_n_7d`. Canary queries were never updated. Pre-commit hook on BQ schema (`validate-schema-fields`) doesn't catch column name changes in monitoring scripts. Manual audit needed periodically.
