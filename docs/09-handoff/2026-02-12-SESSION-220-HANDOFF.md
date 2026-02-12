# Session 220 Handoff — Pipeline Recovery, Phase 4 Fixes, Model Decay Assessment

**Date:** 2026-02-12
**Session:** 220
**Status:** Complete — 4 code fixes committed, pipeline recovered (337 predictions), scheduler triage finished, model decay confirmed

## TL;DR

Feb 12 pipeline had only 105 predictions due to Phase 4 defensive checks blocking same-day processing. Manually recovered to 337 predictions across 3 games. Fixed 4 issues: Phase 4 same-day bypass, auto-retry message format + infinite loop, Docker cache busting, monitoring HTTP codes. Completed scheduler job investigation (2 still failing, down from 11). Champion model in severe decay (39.9% edge 3+ HR since Feb 1). Q43 not ready for promotion (48.3%, 29/50 picks).

## Pipeline Recovery

### Problem
Phase 4 defensive checks expected `player_game_summary` data for Feb 12, but games hadn't been played yet. The checks reported 0% coverage and blocked all 5 processors.

### Recovery Steps
1. Triggered Phase 4 with `strict_mode: false` to bypass defensive checks
2. Feature store went from 11 → 35 players (27 quality-ready)
3. Reset stale prediction batch (`batch_2026-02-12_1770908404`)
4. Triggered Phase 5 — 35 players dispatched across 11 model variants
5. Result: 337 predictions across all 3 games (MIL@OKC, POR@UTA, DAL@LAL)

### Metrics After Recovery

| Metric | Before | After |
|--------|--------|-------|
| Predictions | 105 | 337 |
| Games covered | unknown | 3/3 |
| Models running | unknown | 11 (champion + challengers) |
| Zero defaults | - | 337/337 (100%) |
| With prop lines | - | 337/337 (100%) |

## Code Fixes (Commit `6fa33e2c`)

### 1. Phase 4 Same-Day Bypass
- **File:** `data_processors/precompute/mixins/defensive_check_mixin.py`
- **Problem:** Defensive checks fail for today/future dates (0% game summary coverage since games not played)
- **Fix:** Skip dependency checks when `analysis_date >= today`
- **Impact:** Phase 4 will auto-process same-day requests without needing `strict_mode: false` override

### 2. Auto-Retry Endpoint Fix
- **File:** `orchestration/cloud_functions/auto_retry_processor/main.py`
- **Problem:** Phase 4 retries sent requests to `/process` (expects Pub/Sub envelope) instead of `/process-date` (accepts JSON)
- **Fix:** Changed Phase 4 endpoint to `/process-date` with correct `{analysis_date, strict_mode: false}` format

### 3. Auto-Retry Infinite Loop Fix
- **File:** `orchestration/cloud_functions/auto_retry_processor/main.py`
- **Problem:** 4xx errors left entries as `pending` forever, causing 322 retry attempts per 6 hours
- **Fix:** 4xx responses now mark entries as `failed_permanent` with alert, breaking the loop

### 4. Docker Layer Cache Busting
- **Files:** `cloudbuild.yaml`, `bin/hot-deploy.sh`
- **Problem:** Cloud Build Docker cache served stale code layers (doc-only commits didn't invalidate code)
- **Fix:** Added `--no-cache` flag to Docker build steps in both files

### 5. Monitoring HTTP Codes (bonus)
- **File:** `orchestration/cloud_functions/prediction_monitoring/main.py`
- **Problem:** Monitoring function returned 400 on data freshness issues, causing Cloud Scheduler INTERNAL errors
- **Fix:** Return 200 always (reporter, not gatekeeper)

## Daily Validation Results

| Check | Status | Details |
|-------|--------|---------|
| Deployment drift | ✅ | All services up to date |
| Feature quality | ✅ | 77% ready, matchup 97%, vegas 100%, 0 red |
| Cross-model parity | ✅ | All 5 models at 100% (32 predictions each) |
| Enrichment | ✅ | 100% today, 98% yesterday |
| Duplicate subs | ✅ | Clean (17 topics) |
| Yesterday box scores | ✅ | 14 games, 505 players, 98.8% |
| Pre-game signal | 🔴 | RED — 3-game slate, 20.6% HR historically, skip day |
| Grading (7-day) | 🟡 | 47% — expected (today's not graded yet) |
| Phase 3→4 orchestrator | ⚠️ | 1/5 complete — EXPECTED for same_day mode (see below) |
| Scheduler jobs | 🟠 | 11 → 2 still failing (see below) |
| Phase 4 400 errors | 🔴 | auto-retry sending wrong format (322/6h) — FIXED |

## Investigation Results

### Phase 3→4 Orchestrator: EXPECTED BEHAVIOR

The orchestrator uses mode-aware requirements. For `same_day` mode (today's date), only 1 processor is required: `upcoming_player_game_context`. The 3 overnight processors (`player_game_summary`, `team_defense_game_summary`, `team_offense_game_summary`) are NOT expected for unplayed games. The `should_trigger_phase4` function returns `(True, "all_complete")` with 1/1 critical processor complete.

**No action needed.**

### catboost_v9_2026_02: DISABLED MODEL, NO ACTION

| Property | Value |
|----------|-------|
| Status | `enabled: False` (disabled Session 169) |
| Reason | 50.84% hit rate, systematic UNDER bias |
| Predictions | 1,525 total (Feb 1-8) |
| Graded | 369 (Feb 1-3 only — active at the time) |
| Feb 4-8 | All `is_active = FALSE`, correctly excluded from grading |

Edge 3+ performance on graded days: 60% (Feb 1, 10 picks), 21.9% (Feb 2, 32 picks), 27.8% (Feb 3, 18 picks). Confirmed the disable decision was correct.

### Scheduler Jobs: 2 Still Failing (down from 11)

9 of 11 jobs now OK (fixed in Sessions 218B/219). Remaining:

#### `firestore-state-cleanup` — Code 13 INTERNAL
- **Target:** `transition-monitor` Cloud Function Gen2, entry point `monitor_transitions`
- **Root cause:** Gen2 functions expose a single entry point. The `/cleanup` path in the scheduler URL is ignored — it runs `monitor_transitions` instead of `cleanup_firestore_documents`
- **Fix:** Deploy a separate Cloud Function with entry point `cleanup_firestore_documents`

#### `live-freshness-monitor` — Code 4 DEADLINE_EXCEEDED
- **Target:** Gen1 Cloud Function (one of only 2 remaining Gen1 functions)
- **Root causes (multiple):**
  1. Missing `google-cloud-bigquery` in requirements.txt
  2. Broken `shared/` import (Gen1 can't include it)
  3. Indentation bug at line 161 (`from shared.clients...` at column 0 instead of inside `try:` block)
  4. Cascading timeouts: 2 retry attempts × 120s each = 240s > 180s function deadline
- **Fix:** Redeploy as Gen2 with fixed imports, add bigquery dependency, fix indentation

#### `registry-health-check` — PAUSED, underlying broken
- Stale `gcr.io` image from Jan 10 (not Artifact Registry)
- No impact while paused. Consider deleting if service unused.

### Model Performance: Champion in Severe Decay

**Since Feb 1, 2026:**

| Model | Edge 3+ Graded | HR Edge 3+ | Status |
|-------|---------------|------------|--------|
| **catboost_v9** (champion) | 183 | **39.9%** | SEVERE DECAY |
| catboost_v9_q43 | 29 | **48.3%** | Outperforming but below gate |
| catboost_v9_q45 | 18 | **50.0%** | Too small sample |

**Champion has dropped from 71.2% → 39.9%** (well below 52.4% breakeven). 35+ days stale (trained through Jan 8).

**Q43 Promotion Assessment:**

| Criterion | Required | Actual | Status |
|-----------|----------|--------|--------|
| Edge 3+ graded picks | ≥ 50 | 29 | NOT MET |
| Edge 3+ hit rate | ≥ 60% | 48.3% | BELOW GATE |

Q43 also regressed from initial 60.0% (Feb 8-10) to 48.3% with more data. At ~29 picks/week, will reach 50-pick threshold ~Feb 22-24.

**Recommendation:** Don't promote Q43 yet. Continue monitoring. Consider fresh retrain with training data through Feb 10, using quantile alpha=0.43 approach.

## Commits

```
6fa33e2c fix: Phase 4 same-day bypass, auto-retry message format, Docker cache busting
```

### Files Changed (4)
- `data_processors/precompute/mixins/defensive_check_mixin.py` — Same-day bypass for defensive checks
- `orchestration/cloud_functions/auto_retry_processor/main.py` — Correct endpoint + 4xx failure handling
- `cloudbuild.yaml` — `--no-cache` for Docker builds
- `bin/hot-deploy.sh` — `--no-cache` for hot deploys

### Deployment
- Pushed to main, Cloud Build succeeded
- All services up to date (verified via `check-deployment-drift.sh`)
- 4 pre-existing stale Cloud Functions noted (reconcile, nba-grading-service, validate-freshness, pipeline-health-summary) — from before this session

## Signal Advisory

🔴 **RED — Skip day.** Only 3 games, light slate. Historically 20.6% HR on 1-4 game slates. 1 high-edge pick only.

## Next Session Priorities

1. **Fix 2 remaining scheduler jobs** (P2)
   - `firestore-state-cleanup`: Deploy separate CF with `cleanup_firestore_documents` entry point
   - `live-freshness-monitor`: Migrate Gen1→Gen2 with fixed deps (same pattern as `live-export` in 218B)
2. **Monthly retrain decision** (P1) — Champion at 39.9%, Q43 at 48.3%. Both below breakeven. Fresh retrain through Feb 10 with quantile alpha=0.43 is warranted.
3. **Q43 monitoring** — Continue tracking. Need 21 more edge 3+ picks to reach 50-pick threshold (~10-12 days).
4. **Delete/clean `registry-health-check`** (P3) — Paused job with stale gcr.io image, consider removing entirely.

## Morning Quick Check

```bash
# 1. Verify Phase 4 same-day bypass works (no more strict_mode override needed)
bq query --nouse_legacy_sql "SELECT game_date, COUNT(*) FROM nba_predictions.ml_feature_store_v2 WHERE game_date = CURRENT_DATE() GROUP BY 1"

# 2. Check prediction count for today
bq query --nouse_legacy_sql "SELECT game_date, COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date >= CURRENT_DATE() - 1 GROUP BY 1 ORDER BY 1 DESC"

# 3. Check auto-retry queue is clean (no more infinite loops)
bq query --nouse_legacy_sql "SELECT status, COUNT(*) FROM nba_orchestration.failed_processor_queue WHERE inserted_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR) GROUP BY 1"

# 4. Monitor Q43 shadow performance
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q43_train1102_0131 --days 14

# 5. Run daily validation
/validate-daily
```

---

**Session completed:** 2026-02-12 ~10:00 AM PT
