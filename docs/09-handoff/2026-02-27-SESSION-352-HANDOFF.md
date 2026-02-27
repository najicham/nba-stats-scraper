# Session 352 Handoff — LightGBM Fix, CI/CD Bug, Edge Floor Adjustment

**Date:** 2026-02-27
**Previous:** Session 351 — LightGBM validation, fleet triage (docs/09-handoff/2026-02-27-SESSION-351-HANDOFF.md)

## What Happened

### 1. LightGBM Models Were Not Loading (Fixed)

**Root cause:** Two bugs prevented LightGBM from producing predictions:

1. **CI/CD image push ordering bug** — `cloudbuild.yaml` pushed Docker images AFTER the deploy step via the `images:` section. But `gcloud run deploy --image :latest` pulls from the registry immediately, getting the PREVIOUS build's image. The `BUILD_COMMIT` env var was updated correctly, masking the stale image (drift check showed "up to date").

2. **Missing libgomp1** — The `python:3.11-slim` Docker base image doesn't include `libgomp.so.1` (OpenMP), which LightGBM requires at runtime. Even with correct code, `import lightgbm` would fail.

**Fixes:**
- Added explicit `docker push` steps in `cloudbuild.yaml` before the deploy step
- Added `apt-get install libgomp1` to `predictions/worker/Dockerfile`
- Hot-deployed revision `00285` with both fixes
- Verified `lightgbm 4.6.0` imports correctly in the new Docker image

**Verification needed:** Check Feb 28 prediction cycle logs for `"LightGBM Monthly model loaded"` messages. If not appearing, check `gcloud logging read` for revision `prediction-worker-00285-8pv`.

### 2. CI/CD Auto-Deploy Bug (Fixed)

The GitHub Actions `deploy-service.yml` workflow didn't pass `_MIN_INSTANCES` to Cloud Build, causing every auto-deploy to reset prediction-worker to `min-instances=0`. Fixed by computing min-instances based on service name in the workflow.

### 3. Best Bets Edge Floor Lowered (3.0 from 5.0)

**Problem:** Best bets exported 0 picks on Feb 27 (and will on most days) because:
- Edge floor at 5.0 blocked 49/50 candidates
- The 1 candidate with edge ≥ 5 (Jokic edge 9.7) was blocked by signal_density (base signals only)
- Cascading: degraded models → fewer high-edge picks → signal desert → 0 picks

**Analysis:** `docs/08-projects/current/model-diversity-session-350/BEST-BETS-ZERO-PICKS-ANALYSIS.md`

**Changes (Option D from analysis):**
- `MIN_EDGE = 3.0` (was 5.0) — edge 3-4 is the best V12 performance band during degradation
- Signal density bypass for edge ≥ 7.0 — extreme edge picks pass even with base-only signals
- Algorithm version: `v352_edge_floor_3_density_bypass`

**Immediate impact:** 2 picks generated for Feb 27 (was 0):
1. Jokic UNDER 28.5 (edge 9.7, V12) — via signal density bypass
2. Isaiah Joe OVER 9.5 (edge 3.4, v9_low_vegas) — contextual signal: prop_line_drop_over

**Monitor:** Track best bets HR over next 7 days. If HR drops below 55%, consider reverting to 4.0.

## Fleet Status (Feb 19-26, edge 3+)

| Model | HR | N | Notes |
|-------|-----|---|-------|
| `v9_low_vegas_train0106_0205` | **56.1%** | 57 | LEADER, above breakeven |
| `ensemble_v1` | 56.5% | 46 | Decent |
| `v12_train1102_1225` | 54.5% | 33 | |
| `v9_q45_train1102_0125` | 53.3% | 30 | |
| `catboost_v12` (production) | 51.1% | 90 | Below breakeven |
| `v12_noveg_q43_train0104_0215` | 50.0% | 16 | DISABLED |
| `catboost_v9` (production) | 45.5% | 22 | Weak |
| `v12_noveg_mae_train0104_0215` | 40.0% | 15 | Trending bad, needs N≥20 |
| `v12_mae_train0104_0215` | 40.0% | 5 | Too small to act |

**New models (Feb 26-27):** 0-1 edge 3+ bets graded. Need 5-7 more days.
**LightGBM:** 0 predictions (blocked by bugs, now fixed).

## Next Session Priorities

1. **Verify LightGBM predictions** — Check Feb 28 logs and `player_prop_predictions` for `lgbm%` system_ids
2. **Monitor edge floor impact** — Compare best bets volume and HR with the new 3.0 floor
3. **Triage MAE models** — `v12_noveg_mae_train0104_0215` should hit N≥20 by Feb 28-Mar 1. Disable if <40%
4. **Evaluate new shadow models** — Session 343-348 models accumulating data. Check at N≥20
5. **Fresh LightGBM retrain** — If LightGBM validates (≥55% live HR after 3+ days), retrain through Feb 20+

## Files Changed

| File | Change |
|------|--------|
| `cloudbuild.yaml` | Add docker push before deploy (fix stale image bug) |
| `predictions/worker/Dockerfile` | Add libgomp1 for LightGBM runtime |
| `.github/workflows/deploy-service.yml` | Pass _MIN_INSTANCES per service |
| `ml/signals/aggregator.py` | Edge floor 3.0, signal density bypass for edge ≥ 7 |
| `CLAUDE.md` | Update best bets filter documentation |

## Dead Ends Confirmed

- None this session (diagnostic + fix session)

## Key Discovery: CI/CD Image Push Bug

**The `images:` section in Cloud Build pushes AFTER all steps.** This means `gcloud run deploy --image :latest` in a build step gets the PREVIOUS build's image. This bug has been silently deploying stale code on every auto-deploy since the cloudbuild.yaml was created. The `BUILD_COMMIT` env var masked it because it's set by the deploy step, not by the image content.

This explains several past "deployment drift" issues where code was committed but behavior didn't change. The hot-deploy script was NOT affected (it pushes before deploying).
