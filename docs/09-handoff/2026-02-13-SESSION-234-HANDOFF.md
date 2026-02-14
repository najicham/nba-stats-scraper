# Session 234 Handoff — Grading Deployments + Retrain Attempts

**Date:** 2026-02-13
**Status:** Deployments complete, retrain attempted but gates failed
**Context:** All-Star break (no games until Feb 19)

---

## What Was Done

### 1. Deployed phase5b-grading (Cloud Function)

The Cloud Build trigger had raced on two commits (`290c51c` and `8454ccb4`) — the wrong one won (409 conflict). Manually triggered rebuild.

- **Before:** Deployed at `290c51c` (missing grading threshold fix)
- **After:** Deployed at `31e9f25` (includes commit `8454ccb4` — remove minimum prediction threshold from grading)
- **Build ID:** `a0e39f82-b44f-417d-94d3-8f63c2cccb36`

### 2. Deployed nba-grading-service (Cloud Run)

- **Before:** Deployed at `3bc60ca1` (4 commits behind)
- **After:** Deployed at `31e9f25e` (current)
- All smoke tests passed (health, BQ connectivity, Firestore, 337 recent writes)
- Grading completeness healthy: catboost_v9 at 95.4% coverage

### 3. Champion Model Retrain — GATES FAILED

Attempted two retrains during the All-Star break window:

| Attempt | Train Window | Eval Window | MAE | Edge 3+ HR | Edge 3+ N | Result |
|---------|-------------|-------------|-----|-----------|-----------|--------|
| A | Nov 2 - Feb 6 | Feb 7-12 (6d) | 4.76 | 60.0% | 5 | FAIL: sample too small |
| B | Nov 2 - Jan 31 | Feb 1-12 (12d) | 4.95 | 44.4% | 9 | FAIL: HR + sample + OVER |

Both models saved locally and registered in `ml_experiments`:
- A: `catboost_v9_33f_train20251102-20260206_20260213_085335.cbm` (SHA: `c8a8d148...`)
- B: `catboost_v9_33f_train20251102-20260131_20260213_085918.cbm` (SHA: `45fe869b...`)

**Key finding:** Standard MAE retrains produce very few edge 3+ picks (5-9 from hundreds of predictions). The model is too conservative to generate actionable bets. This confirms previous sessions' finding that quantile models (Q43/Q45) are the better path.

### 4. Confirmed Games Resume Feb 19

10 games on Feb 19, full schedule through Feb 27. Pipeline deployments are ready.

---

## What's NOT Done

### 1. Remaining Stale Deployments (P3)

| Service | Status | Priority |
|---------|--------|----------|
| `validation-runner` | 4 commits behind | P3 (non-critical) |
| `reconcile` | 1 commit behind (f-string fix) | P3 |
| `validate-freshness` | 1 commit behind (f-string fix) | P3 |

### 2. Model Strategy Decision Needed

Champion decaying (40-47% edge 3+ HR, 36+ days stale). Standard retrain won't solve it. Options:

1. **Promote Q45** — Currently 60.0% HR edge 3+ (25 picks). Needs 50+ graded for governance. Will resume accumulating when games start Feb 19.
2. **Quantile retrain** — Try Q43 or Q45 with extended training data (Nov 2 - Feb 6):
   ```bash
   PYTHONPATH=. python ml/experiments/quick_retrain.py --name "Q43_FEB" --quantile-alpha 0.43 --train-start 2025-11-02 --train-end 2026-02-06 --eval-start 2026-02-07 --eval-end 2026-02-12 --force
   ```
3. **Deploy V12** — Vegas-free model, avg 67% HR edge 3+ across 4 eval windows. See `docs/08-projects/current/model-improvement-analysis/22-PHASE1B-RESULTS.md`.

### 3. BDL API Key in Cloud Functions

Still missing from `live-export` CF env. Not urgent (BigQuery fallback works for final games) but will fail for real-time in-progress scoring.

---

## Quick Start for Next Session

```bash
# 1. Read this handoff

# 2. Check deployment drift
./bin/check-deployment-drift.sh --verbose

# 3. If games are happening, run daily validation
/validate-daily

# 4. Check shadow model accumulation
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q45_train1102_0131 --days 14
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q43_train1102_0131 --days 14

# 5. Deploy remaining P3 services if desired
./bin/deploy-service.sh validation-runner
# reconcile and validate-freshness are Cloud Functions — check triggers
```
