# Session 337B Handoff — Deployment Fixes, Scheduler Fixes, ft_rate_bench_over Verification

**Date:** 2026-02-24
**Focus:** Complete Session 337 action items — deploy stale services, fix scheduler timeouts, verify ft_rate_bench_over signal readiness
**Status:** Mostly complete. ft_rate_bench_over signal ready but waiting for Phase 6 to run.

---

## What This Session Did

### 1. Deployed 2 Stale Cloud Run Services

| Service | Before | After | Status |
|---------|--------|-------|--------|
| `nba-grading-service` | `070657bf` | `42806517` (HEAD) | DEPLOYED |
| `nba-phase4-precompute-processors` | stale | `42806517` (HEAD) | DEPLOYED |
| `daily-health-check` (CF) | `da1969d` label | Built from `43e93d0` | STALE (see below) |

**daily-health-check:** Cloud Function auto-deployed via Cloud Build at 02:19 UTC but from commit `43e93d0` (Session 334), not HEAD (`42806517`). The label still shows `da1969d`. The drift is in `shared/ml/feature_contract.py` (V15 feature contract) which doesn't affect health monitoring. **Low priority — cosmetic drift only.**

### 2. Fixed Scheduler Timeout

- **`execute-workflows`**: Increased `attemptDeadline` from 180s to 540s

### 3. Investigated 4 Failing Scheduler Jobs

| Job | Timeout | Target | Status Code | Notes |
|-----|---------|--------|-------------|-------|
| `execute-workflows` | 540s (was 180s) | `nba-phase1-scrapers/execute-workflow` | 4 (DEADLINE_EXCEEDED) | Timeout increased, monitor |
| `nba-props-midday` | 900s | `nba-phase1-scrapers/execute-workflow` | 4 | Already max reasonable timeout |
| `self-heal-predictions` | 900s (scheduler) / 540s (CF) | CF backed by Cloud Run | 4 | Empty error logs — likely OOM (512Mi) |
| `predictions-9am` | 540s | `prediction-coordinator/start` | 2 (UNKNOWN) | Intermittent |

**Root cause:** These are all timeout/crash issues, not auth/IAM. `self-heal-predictions` may need memory increase (512Mi → 1Gi). The others may benefit from `minScale=1` on target services (Session 337 Priority 1).

### 4. Verified ft_rate_bench_over Signal Readiness

**Full data path traced and confirmed working:**

```
player_game_summary (ft_attempts, fg_attempts)
  → supplemental_data.py lines 220-228 (computes ft_rate_season via window function)
  → supplemental_data.py line 550 (populates supplemental['player_profile']['ft_rate_season'])
  → supplemental_data.py line 587 (copies to pred['ft_rate_season'])
  → ft_rate_bench_over.py line 40 (reads prediction.get('ft_rate_season'))
  → signal_annotator.py line 130 (evaluates signal)
  → pick_signal_tags table (writes qualifying tags)
  → signal_subset_materializer.py (materializes subset 'signal_ft_rate_bench_over')
```

**Why it hasn't fired yet:** Signal annotator runs during Phase 6 (publishing). Phase 6 hasn't run for today (Feb 24) — only Feb 23 data exists in `pick_signal_tags`, and Feb 23 ran before the signal was deployed.

**Candidates ready for today (11 games):**

| Player | Line | FT Rate | Signal Status |
|--------|------|---------|---------------|
| Day'Ron Sharpe | 8.5 | 0.498 | QUALIFIES |
| Daniel Gafford | 8.5 | 0.492 | QUALIFIES |
| Ryan Kalkbrenner | 5.5 | 0.491 | QUALIFIES |
| Jarrett Allen | 13.5 | 0.429 | QUALIFIES |
| Tre Jones | 9.5 | 0.416 | QUALIFIES |
| Bilal Coulibaly | 9.5 | 0.390 | QUALIFIES |

All are bench tier (line < 15) + OVER + FT rate >= 0.30. Signal will fire when Phase 6 runs.

---

## Current Deployment Drift

After this session's deploys:

| Service | Status |
|---------|--------|
| `nba-grading-service` | UP TO DATE |
| `nba-phase4-precompute-processors` | UP TO DATE |
| `daily-health-check` (CF) | STALE (cosmetic, V15 feature contract only) |
| All other services | UP TO DATE |

---

## Outstanding Items (For Next Session)

### Priority 1: Set minScale=1 on Critical Services
From Session 337 — cold start failures caused 1-hour pipeline delays:
```bash
for svc in phase4-to-phase5-orchestrator phase3-to-phase4-orchestrator prediction-worker prediction-coordinator; do
  gcloud run services update $svc \
    --region=us-west2 \
    --project=nba-props-platform \
    --min-instances=1
done
```

### Priority 2: Verify ft_rate_bench_over Signal After Pipeline
After Phase 6 runs today:
```sql
-- Check signal fires
SELECT signal_tag, COUNT(*)
FROM `nba-props-platform.nba_predictions.pick_signal_tags`,
  UNNEST(signal_tags) AS signal_tag
WHERE game_date = '2026-02-24'
  AND signal_tag = 'ft_rate_bench_over'
GROUP BY 1;

-- Check subset materializes
SELECT COUNT(*), subset_id
FROM `nba-props-platform.nba_predictions.current_subset_picks`
WHERE game_date = '2026-02-24'
  AND subset_id = 'signal_ft_rate_bench_over'
GROUP BY 2;
```

### Priority 3: Monitor V9 Q45/Q43 Staleness
At 29 days — hitting retrain threshold tomorrow. Check decay-detection state.

### Priority 4: Investigate self-heal-predictions OOM
Currently 512Mi, empty error logs suggest crash. Consider:
```bash
gcloud functions deploy self-heal-predictions \
  --region=us-west2 --project=nba-props-platform \
  --memory=1024Mi
```

---

## System Health Summary

| Metric | Value | Status |
|--------|-------|--------|
| Best Bets 7d | 7-3 (70.0%) | HEALTHY |
| Best Bets 30d | 34-16 (68.0%) | HEALTHY |
| V12 Champion 7d | 54.5% | DEGRADING |
| V12 Edge 5+ 14d | 41.7% (N=12) | LOSING |
| V9_low_vegas 7d | 60.5% | HEALTHY (carrying best bets) |
| Fresh retrains | 4x train0104_0215 | PRODUCING |
| Pipeline | All phases running | HEALTHY |
| Scheduler | 109/113 passing | 4 FAILING (timeouts) |
| Deployment drift | 1 service (cosmetic) | MOSTLY CLEAN |
| ft_rate_bench_over | Code deployed, data path verified | WAITING FOR PHASE 6 |

---

## Files Changed This Session

None — validation and deployment session only. No code changes.
