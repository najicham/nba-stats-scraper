# Session 337 Handoff — Morning Validation, Deployment Fixes, minScale Discovery

**Date:** 2026-02-24
**Focus:** Morning validation (daily-steering + validate-daily), fixed grading service drift, discovered all Cloud Run services have minScale=0
**Status:** Validation complete, one action item outstanding (minScale)

## Current System State

| Property | Value |
|----------|-------|
| Champion Model | `catboost_v12` (interim) |
| Champion State | **DEGRADING** — 54.5% HR 7d (was WATCH 55.6% last session) |
| Champion Edge 5+ | **LOSING — 41.7% HR 14d (N=12)** |
| Best Bets 7d | **7-3 (70.0% HR)** |
| Best Bets 30d | **34-16 (68.0% HR)** |
| Fresh Retrains | 4x `train0104_0215` models LIVE — 141 preds each today |
| V9 in Best Bets | **DISPLACED** — zero picks since Feb 19 (was 66% of picks 30d ago) |
| Pre-Game Signal | **RED** — UNDER_HEAVY (15.6% pct_over) |
| Deployment Drift | `nba-grading-service` FIXED, `daily-health-check` CF still stale (low priority) |

## What This Session Did

### 1. Daily Steering Report
- Champion V12 slipped from WATCH to DEGRADING (54.5% 7d, first day below threshold)
- Shadow models carrying best bets: `v9_low_vegas` (60.5% HEALTHY) and fresh retrains leading
- Market regime GREEN (compression 1.246, edges expanding)
- All 4 fresh retrains (`train0104_0215`) confirmed producing 141 predictions for today's 11-game slate
- V9 base model fully displaced from best bets picks since Feb 19

### 2. Fixed Deployment Drift
- **`nba-grading-service`**: Deployed successfully (was at commit `070657bf`, now at `42806517`)
- **`daily-health-check` CF**: NOT fixed — deploy script only handles Cloud Run services, not Cloud Functions. Low priority (monitoring reporter only).

### 3. Daily Validation — All Phases Healthy
- Phase 3 yesterday: 3 games, 112 players (all OK, coverage query had false alarm due to game_id format mismatch)
- Phase 4 today: 368 cache records, 196 feature store records
- Phase 5 today: 141 V12 predictions across 11 games
- Cross-model parity: 19 models all at 141 predictions (100%)
- Feature quality: 72.4% quality-ready, matchup=100%, vegas=87%

### 4. Discovered minScale=0 on ALL Cloud Run Services

**This is the key finding.** User expected all services to have `minScale=1` but every service has it NOT SET (defaults to 0):

```
phase4-to-phase5-orchestrator: NOT_SET (0)
phase3-to-phase4-orchestrator: NOT_SET (0)
phase5-to-phase6-orchestrator: NOT_SET (0)
prediction-worker: NOT_SET (0)
prediction-coordinator: NOT_SET (0)
nba-phase3-analytics-processors: NOT_SET (0)
nba-phase4-precompute-processors: NOT_SET (0)
```

**Impact observed today:** `phase4-to-phase5-orchestrator` had **20 "no available instance" errors** between 11:03-12:03 UTC — a full hour of cold start failures before recovering. This delays the Phase 4→5 transition.

### 5. Error Log Analysis

| Service | Errors | Issue | Severity |
|---------|--------|-------|----------|
| `nba-phase3-analytics-processors` | 55 | HTTP 500s on `/process`, retries succeed | P3 |
| `phase4-to-phase5-orchestrator` | 20 | Cold start "no available instance" | P2 |
| `nba-phase2-raw-processors` | 16 | Empty payloads | P3 |
| `prediction-worker` | 6 | Invalid features for 4 players (zone_matchup only) | P4 |
| `nba-phase4-precompute-processors` | 4 | DependencyError — defensive check blocked correctly | P2 (working as designed) |

### 6. Scheduler Health — 4 Failing Jobs

Regression from Session 219 baseline of 0:
- `execute-workflows`: DEADLINE_EXCEEDED
- `nba-props-midday`: DEADLINE_EXCEEDED
- `self-heal-predictions`: DEADLINE_EXCEEDED
- `predictions-9am`: UNKNOWN

All are timeout issues, not auth/permission failures.

## Priority 1 (Next Session): Fix minScale on Critical Services

Set `minScale=1` on orchestrators and key pipeline services to prevent cold start failures:

```bash
# CRITICAL: Use --update-env-vars NOT --set-env-vars to avoid wiping config!
for svc in phase4-to-phase5-orchestrator phase3-to-phase4-orchestrator prediction-worker prediction-coordinator; do
  gcloud run services update $svc \
    --region=us-west2 \
    --project=nba-props-platform \
    --min-instances=1
done
```

**Cost consideration:** Each warm instance costs ~$0.01/hr idle. 4 services = ~$0.96/day. Worth it to avoid 1-hour pipeline delays.

**Verify after setting:**
```bash
for svc in phase4-to-phase5-orchestrator phase3-to-phase4-orchestrator prediction-worker prediction-coordinator; do
  min=$(gcloud run services describe $svc --region=us-west2 --project=nba-props-platform --format="value(spec.template.metadata.annotations['autoscaling.knative.dev/minScale'])" 2>/dev/null)
  echo "$svc: minScale=${min:-NOT_SET}"
done
```

## Priority 2: Investigate Scheduler Timeouts

4 scheduler jobs failing with DEADLINE_EXCEEDED. Check if they need longer `attemptDeadline`:

```bash
for job in execute-workflows nba-props-midday self-heal-predictions predictions-9am; do
  echo "=== $job ==="
  gcloud scheduler jobs describe $job --location=us-west2 --project=nba-props-platform --format="yaml(attemptDeadline,httpTarget.uri)" 2>/dev/null
done
```

These may be related to the minScale=0 issue — if target services cold-start slowly, the scheduler deadline expires before the instance is ready.

## Priority 3: Standard Daily Checks

```bash
/daily-steering           # Includes edge-5+ health section
/validate-daily
./bin/check-deployment-drift.sh --verbose
```

## Priority 4: Deploy daily-health-check CF (Low)

The `daily-health-check` Cloud Function is at commit `da1969d` (HEAD is `42806517`). The deploy script doesn't handle CFs. Either:
- Wait for Cloud Build auto-deploy trigger to pick it up
- Or manually deploy via `gcloud functions deploy`

This is monitoring-only so it's low priority.

## Key Signals for Today's Games

- **RED pre-game signal**: UNDER_HEAVY (15.6% pct_over), only 4 high-edge picks
- Historical: 54% HR on UNDER_HEAVY days vs 82% on balanced (p=0.0065)
- **Recommendation**: Reduce bet sizing by 50% or be very selective
- 11-game slate with full schedule ahead all week

## Files Changed This Session

None — this was a validation/diagnosis session only.

## Key Insights

1. **minScale=0 everywhere** — Either was never set to 1, or deployments reverted it. Every `gcloud run deploy` resets annotations unless explicitly preserved. This is likely the root cause of intermittent pipeline delays.
2. **System self-heals through retries** — Despite 20 cold start failures, predictions still generated. But the 1-hour delay is wasteful.
3. **V9 displacement confirmed** — The multi-model architecture naturally displaced the BLOCKED V9 model from best bets through edge competition. No manual intervention needed.
4. **Champion V12 degrading but system profitable** — 70% best bets 7d HR because shadow models carry the load.
