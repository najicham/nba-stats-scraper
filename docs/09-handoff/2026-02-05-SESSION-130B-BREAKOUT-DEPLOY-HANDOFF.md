# Session 130B Handoff - Breakout Classifier Deployment

**Date:** 2026-02-05
**Session:** 130B (Continuation of Session 128)
**Focus:** Deploy breakout classifier shadow mode + fix smoke test bug

---

## Summary

Deployed prediction-worker with breakout classifier shadow mode that was developed in Session 128 but not deployed. Also fixed a bug in the deploy script where smoke tests failed with 403 due to missing authentication.

---

## What Was Done

### 1. Deployed Breakout Classifier Shadow Mode

**Status:** Successfully deployed commit `8951a83c`

The breakout classifier shadow mode was developed in Session 128 (commit `2e7cf8bf`) but never deployed. This session completed that deployment.

**What Shadow Mode Does:**
- Runs breakout classifier on every prediction
- Stores results in `features_snapshot.breakout_shadow`
- Does NOT filter bets yet (validation first)

**Verification:**
- Feb 4 predictions have no shadow data (generated before classifier was committed)
- Shadow data collection will start with next prediction run (~2:30 AM ET)

### 2. Fixed Smoke Test Authentication Bug

**Issue:** Smoke tests in `bin/deploy-service.sh` failed with HTTP 403 because:
- Cloud Run services require authentication for external requests
- Smoke tests used unauthenticated `curl` requests
- This caused "DEPLOYMENT FAILED" false positives

**Fix (commit `a630f3b7`):**
- Added `gcloud auth print-identity-token` to get auth tokens
- Updated all smoke test curl calls to include `Authorization: Bearer` header
- Added graceful fallback when auth token unavailable (relies on Cloud Run revision traffic routing)

**Services affected:**
- `prediction-worker` (case statement)
- `nba-grading-service` (case statement)
- Default case (all other services)

---

## Commits

| Commit | Description |
|--------|-------------|
| `a630f3b7` | fix: Add authentication to smoke tests in deploy script |

Note: Session 128's breakout classifier commit `2e7cf8bf` was already part of main, just not deployed until now.

---

## Verification

### Service Health
```bash
# Deployed commit
gcloud run services describe prediction-worker --region=us-west2 \
    --format="value(metadata.labels.commit-sha)"
# Returns: 8951a83c
```

### Service Logs (healthy)
```
GET /health/deep HTTP/1.1" 200 1314 (Google monitoring checks passing)
```

### Shadow Data (check tomorrow)
```sql
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(JSON_VALUE(features_snapshot, '$.breakout_shadow.risk_score') IS NOT NULL) as with_shadow
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-05'
GROUP BY game_date;
```

---

## Known Issue in Logs

Some warnings about feature version mismatches for certain players:
```
Invalid feature count: 39
CatBoost V8 requires feature_version='v2_33features' or 'v2_37features', got 'v2_39features'
```

This is existing behavior - the feature store handles different versions, and V8 model only works with older features. Not related to breakout classifier.

---

## Next Steps

### P0: Verify Shadow Mode (Tomorrow)
- Run verification query above after predictions generate (~2:30 AM ET)
- Should see non-zero `with_shadow` count for Feb 5/6

### P1: Shadow Mode Validation
- Collect 7+ days of shadow data
- Analyze correlation between `risk_score` and actual bet outcomes
- Decide threshold for production filtering

### P2: Production Activation
- If validation passes, enable bet filtering based on breakout risk
- Update prediction worker to skip high-risk breakout bets

---

## Files Modified

- `bin/deploy-service.sh` - Added authentication to smoke tests

---

## Key Learnings

### Smoke Test Authentication
Cloud Run services require authentication by default. Any smoke tests hitting Cloud Run endpoints must either:
1. Use `gcloud auth print-identity-token` with `--audiences` flag
2. Make health endpoints publicly accessible (not recommended for security)
3. Rely on Cloud Run's internal monitoring (fallback approach)

### Deployment Script Exit Code
The deploy script `exit 1` on smoke test failure is intentional - it prevents silently deploying broken services. The fix was to make the tests work correctly, not remove the failure mode.

---

## Related Sessions

- **Session 128:** Developed breakout classifier, trained 7 experiments, winner: EXP_COMBINED_BEST (AUC 0.7302)
- **Session 129:** Deep health checks and deployment smoke tests infrastructure
- **Session 130:** Grading service double bug fix

---

## Quick Commands

### Redeploy prediction-worker
```bash
./bin/deploy-service.sh prediction-worker
```

### Check breakout model location
```bash
ls -la models/breakout_exp_EXP_COMBINED_BEST_20260205_084509.cbm
```

### View breakout classifier code
```bash
cat predictions/worker/prediction_systems/breakout_classifier_v1.py
```
