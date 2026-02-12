# Session 211 Handoff - Orphan Eventarc Cleanup & Prevention

**Date:** 2026-02-12
**Branch:** main (all changes merged)
**Trigger:** Session 210 open items (duplicate subscriptions, all-dash players, Eventarc audit)

---

## What Happened

Resolved all 3 open items from Session 210. Performed a full Pub/Sub subscription audit, deleted 5 orphan Eventarc triggers + 3 old Cloud Functions + 2 stale subscriptions, and added 3 layers of prevention so duplicates are caught automatically going forward.

---

## Changes Made

### Code Changes (2 commits)

**Commit `24228e6d` - Duplicate subscription detection in validate-daily**
- `.claude/skills/validate-daily/SKILL.md`: Added Phase 0.65 check that detects orphan Eventarc subscriptions causing duplicate phase triggers. Uses Python to group push subscriptions by topic, accounts for known legitimate multi-sub topics (Phase 3 analytics → orchestrator + grading, Phase 2 raw → Phase 3 + completeness checker).

**Commit `7cd36609` - Post-deploy duplicate check in all orchestrator deploys**
- `bin/orchestrators/check_duplicate_subscriptions.sh`: New standalone script that verifies no duplicate push subscriptions exist on a given topic. Exits non-zero if duplicates found.
- `bin/orchestrators/deploy_phase4_to_phase5.sh`: Added post-deploy subscription check (expected: 1)
- `bin/orchestrators/deploy_phase3_to_phase4.sh`: Added post-deploy subscription check (expected: 2, because orchestrator + phase3-to-grading)
- `bin/orchestrators/deploy_phase5_to_phase6.sh`: Added post-deploy subscription check (expected: 1)
- `bin/deploy/deploy_grading_function.sh`: Added post-deploy subscription check (expected: 1)

### Infrastructure Cleanup

**Deleted Eventarc triggers (5):**
- `phase4-to-phase5-626939` (us-west2) — old Phase 4→5 function, deployed 2025-12-31
- `phase4-to-phase5-849959` (us-west1) — old Phase 4→5 function, wrong region
- `phase3-to-phase4-464258` (us-west1) — old Phase 3→4 function, wrong region
- `grading-243002` (us-west2) — old grading function, replaced by phase5b-grading
- `phase5-to-phase6-578429` (us-west2) — stale trigger, subscription already deleted in Session 210

**Deleted Cloud Functions (3):**
- `phase4-to-phase5` (us-west2) — replaced by `phase4-to-phase5-orchestrator`
- `phase4-to-phase5` (us-west1) — wrong region, orphan
- `grading` (us-west2) — replaced by `phase5b-grading`

**Deleted Pub/Sub subscriptions (2):**
- `test-phase3-debug-sub` — test artifact on `nba-phase3-analytics-complete`
- `prediction-request-dlq-temp-pull` — temporary debug subscription

**Net result:** Subscriptions 28 → 24, all topics now have correct subscription counts.

---

## Root Cause: Orphan Eventarc Pattern

### How orphans are created
1. Deploy `phase4-to-phase5` Cloud Function with Eventarc trigger
2. Later rename to `phase4-to-phase5-orchestrator` and deploy that
3. `gcloud functions deploy` creates a NEW Eventarc trigger + subscription
4. Old trigger + subscription are NOT automatically cleaned up
5. Both functions now receive every message on the topic

### Impact
- **Wasted compute**: Old functions cold-starting and failing on every trigger
- **Error log noise**: Flask tracebacks from outdated code
- **Latent race condition risk**: If old functions ever succeeded, they'd compete with orchestrators (exactly what happened in Session 210 with Phase 5→6)

### Prevention (3 layers)
1. **`/validate-daily` Phase 0.65** — catches duplicates on every daily validation
2. **Post-deploy check in deploy scripts** — catches duplicates immediately after any orchestrator deploy
3. **`bin/orchestrators/check_duplicate_subscriptions.sh`** — standalone ad-hoc check

---

## Investigation Results

### 5 All-Dash Players with Lines (NOT A BUG)
Kevin Huerter, Bennedict Mathurin, Dominick Barlow, Josh Okogie, Miles McBride had `points_line` but NULL `over_under_result`. Root cause: all are DNP rows where `points` is also NULL. Sportsbooks set lines before games, but these players didn't play. The code correctly requires both `points` AND `points_line` to compute O/U. 89 of 836 rows (10.6%) since Feb 1 — expected frequency of late scratches.

---

## Daily Validation Summary (Feb 11)

- **Pipeline**: Healthy, all services up to date
- **Games**: 3 tonight (MIL@OKC, POR@UTA, DAL@LAL) — light slate
- **Signal**: GREEN, 34.4% pct_over, BALANCED, 6 high-edge picks
- **Feature quality**: 75.8% ready, matchup 100%, history 95.3%
- **Cross-model parity**: All 5 models at 196 predictions (100%)
- **Orchestrators**: All healthy, IAM correct
- **Phase 6 exports**: Fresh (updated ~01:18 UTC)
- **Feb 10 grading**: 12/29 active predictions ungraded (58.6%) — all games Final

---

## Current Subscription Map (Clean State)

| Topic | Push Subscribers | Purpose |
|-------|-----------------|---------|
| `nba-phase1-scrapers-complete` | 1 | Phase 2 raw processors |
| `nba-phase2-raw-complete` | 2 | Phase 3 analytics + realtime completeness checker |
| `nba-phase3-analytics-complete` | 2 | Phase 3→4 orchestrator + phase3-to-grading |
| `nba-phase4-trigger` | 1 | Phase 4 precompute processors |
| `nba-phase4-precompute-complete` | 1 | Phase 4→5 orchestrator |
| `nba-phase5-predictions-complete` | 1 | Phase 5→6 orchestrator |
| `nba-grading-trigger` | 1 | phase5b-grading |
| `nba-grading-complete` | 1 | grading-coverage-monitor |
| `nba-phase6-export-trigger` | 1 | phase6-export |
| `prediction-request-prod` | 1 | prediction-worker |
| `prediction-ready-prod` | 1 | prediction-coordinator |
| `nba-prediction-trigger` | 1 | prediction-coordinator (regenerate) |
| `boxscore-gaps-detected` | 1 | backfill-trigger |
| `auto-retry-trigger` | 1 | auto-retry-processor |
| `bdb-retry-trigger` | 1 | bdb-retry-processor |
| `deployment-drift-check` | 1 | deployment-drift-monitor |
| `mlb-monitoring-alerts` | 1 | mlb-alert-forwarder |

Plus 4 DLQ monitor pull subscriptions (phase1, phase2, phase3, phase4).

---

## Open Items for Next Session

### Should Do
- **Feb 10 grading gap**: 12/29 active predictions ungraded despite all games Final. Run:
  ```bash
  PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --start-date 2026-02-10 --end-date 2026-02-10
  ```
- **`slate_size` field in daily signals**: Currently NULL. Session 211 identified this as a TODO — the signal calculation doesn't populate it yet. Historical analysis shows 20.6% HR on 1-4 game slates, so this field matters for bet sizing.

### Nice to Have
- **Clean up old Cloud Functions in us-west1**: `phase3-to-phase4` may still exist in us-west1 (we deleted its trigger but not the function itself). Check:
  ```bash
  gcloud functions list --regions=us-west1 --project=nba-props-platform
  ```

---

## Deployment Status

All services up to date, no drift. Two new commits on main (auto-deployed via Cloud Build).
