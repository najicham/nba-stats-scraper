# GCP Cost Reduction — Execution Log
**Period:** 2026-04-24 to 2026-04-26
**Trigger:** GCP bill spiked; user requested full audit + reduction
**Outcome:** ~$870/mo → projected ~$270-300/mo (~65-70% reduction)

---

## Context

GCP daily spend was running ~$24-35/day (~$720-870/mo) across the billing account. NBA is in offseason (playoffs started Apr 19, no regular-season games until October 2026). MLB is in-season but a low-priority hobby project — not monetized. The site (`playerprops.io`) reads cached static JSON from GCS and does not need any backend Cloud Run service to be live for NBA during offseason.

This document captures the full audit, decisions, fixes applied, and the October re-enablement runbook.

---

## Initial Audit (30-day billing breakdown)

| Project | 30-day Cost | Primary Driver |
|---------|------------|----------------|
| `infinite-case` | $337 | Cloud Run instance-based billing, 4CPU/16Gi, min=1 (always on, 24/7 CPU billed) |
| `nba-props-platform` | $483 | Phase processors $94, prediction services $73, BQ $77, GCS $33, AR $19, Logging $16, Scheduler $17 |
| `urcwest` | $28 | Firebase functions with min-instances (separate Bid management app) |
| `memberradar-prod` | $14 | Cloud SQL micro instance (separate cycling studio app) |
| `props-platform-web` | $1 | Frontend |
| **Total** | **~$870/mo** | |

### Key anomalies discovered

1. **`infinitecase-backend` was over-provisioned and billed 24/7.** Despite Session 511 supposedly downscaling to 4Gi/2CPU, all revisions still showed 4CPU/16Gi with `cpu-throttling=false`.
2. **`nba-bigquery-backups` GCS bucket was generating 1M+ Class A operations/month** ($31/mo). Lifecycle policy was tier-transitioning daily (Standard → Nearline → Coldline → Archive) — each transition is a Class A op.
3. **NBA Phase 3/4 processors were running daily despite no NBA games.** ~$94/mo of execution cost from a cascade triggered by 5 Cloud Workflow scheduler jobs that fire 12×/day year-round with no season awareness.
4. **3 NBA orchestrator Cloud Functions were costing $42/mo in min=1 idle warmup** — added after a Feb 23 cold-start incident.
5. **Cloud Logging exclusion filters that were added in Session 510 were missing.**
6. **70+ NBA-specific Cloud Scheduler jobs were enabled year-round** despite triggering pure-NBA pipeline work.

---

## Multi-Agent Review Process

To validate proposed changes, four parallel research agents reviewed each domain (services, anomalies, offseason architecture, separate projects). After preliminary findings, four reviewer agents pushed back:

- **Risk Reviewer** flagged that setting NBA orchestrators to `min=0` carries CRITICAL risk (Pub/Sub retry storms if any message arrives), and that `prediction-worker` at `min=0` will hurt UX in October.
- **Cost Validator** verified actual savings via daily billing data and lowered the realistic target from $230/mo → $270/mo.
- **Operations Reviewer** found that October re-enablement requires backfilling `league_macro_daily` and `model_performance_daily` before predictions resume, or the regime detection and decay state machine will be wrong for week 1.
- **Architecture Reviewer** challenged the entire "manual pause" approach and proposed two surgical code fixes that eliminate the need for offseason pausing entirely.

The plan was revised based on this feedback before any changes were applied.

---

## Changes Applied

### 1. `infinitecase-backend` (separate `infinite-case` project)

**Two fixes deployed:**

| Step | Date | Change | Saves |
|------|------|--------|-------|
| 1a | 2026-04-24 | 4CPU/16Gi → 2CPU/4Gi (revision `00143-xpj`) | ~$184/mo |
| 1b | 2026-04-25 | `cpu-throttling=false → true` + `min=1 → min=0` (revision `00144-gm5`) | ~$237/mo |

**Note on cold start:** `infinitecase.com` (legal case management for nchammas@gmail.com + max.a.gruenberg@gmail.com) now cold-starts on first request after idle (~3-5 seconds). User accepted this. **When measuring app performance, ignore the first request after a quiet period — wait for the warm second request.**

### 2. `prediction-worker` (nba-props-platform)

**Date:** 2026-04-24
**Change:** `min=1 → min=0` (revision `00493-6cx`)
**Saves:** ~$30/mo
**Rationale:** Worker is invoked by `prediction-coordinator` (which keeps `min=1`), not by Pub/Sub directly — no cold-start storm risk. Safe during NBA offseason.
**October note:** Risk reviewer recommends restoring to `min=1` before NBA daily prediction batches resume, to avoid 30-60s cold start on the first daily batch of 450+ messages.

### 3. Cloud Logging exclusions restored

**Date:** 2026-04-25
**Change:** Re-created 3 log exclusion filters via REST API:
- `exclude-health-checks` — drops `GET /health|/healthz|/ready` logs
- `exclude-heartbeats` — drops `jsonPayload.message="Heartbeat"` from processors
- `monitoring-info-suppression` — drops INFO from canary/drift services

**Saves:** ~$15-40/mo (variable; bigger impact at NBA-season log volume)
**Method:** `gcloud logging exclusions` is no longer a valid subcommand in current gcloud — used the Cloud Logging REST API directly.

### 4. `nba-bigquery-backups` lifecycle simplified

**Date:** 2026-04-26
**Change:** Replaced complex tiering policy with simple 30-day delete:

```json
// Before: 4 lifecycle rules (3 tier transitions + delete)
{"rule": [
  {"action": {"storageClass": "NEARLINE"},  "condition": {"age": 7}},
  {"action": {"storageClass": "COLDLINE"},  "condition": {"age": 30}},
  {"action": {"storageClass": "ARCHIVE"},   "condition": {"age": 90}},
  {"action": {"type": "Delete"},            "condition": {"age": 365}}
]}

// After: 1 rule
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 30}}]}
```

**Saves:** ~$30/mo
**Why this works:** The bucket is and always was Standard storage. The Class A ops cost was driven by the tier transitions themselves (each move is a billable op). Removing the transitions eliminates ~1M ops/month.

### 5. Phase 3 offseason early-exit (commit `cb0516dc`)

**Date:** 2026-04-26
**File:** `data_processors/analytics/main_analytics_service.py`
**Change:** Added `has_regular_season_games()` check at the `/process` Pub/Sub entry point:

```python
# Offseason early-exit: skip Phase 3 work on no-game days unless backfilling.
# Stops the Phase 2→3→4 cascade naturally during NBA offseason.
if game_date and not message.get('backfill_mode', False):
    from shared.utils.schedule_guard import has_regular_season_games
    if not has_regular_season_games(game_date, project=get_project_id()):
        logger.info(f"No NBA games on {game_date} — offseason skip for {source_table}")
        return jsonify({"status": "skipped_offseason", "game_date": game_date}), 200
```

**Saves:** ~$94/mo
**Why this is the right fix:** Architecture Reviewer's recommendation. Instead of pausing 5 Cloud Workflow schedulers each year, the code itself returns 200 immediately on no-game days. The Pub/Sub message is acked, no Phase 4 cascade fires, and the cost goes to zero. Backfill mode bypasses the check. The behavior is harmless during NBA season — `has_regular_season_games` returns `True` whenever schedule data shows games. Fail-open: returns `True` on any BQ error so real game-day errors still surface.

### 6. Pub/Sub orchestrator ACK deadlines

**Verified:** All 3 NBA orchestrator subscriptions already at 600s ACK deadline (likely fixed in a prior session). No change needed.

### 7. 70 NBA-specific Cloud Scheduler jobs paused

**Date:** 2026-04-26
**Method:** `xargs -P 10` parallel `gcloud scheduler jobs pause`
**Result:** State went from 179 enabled / 3 paused → 109 enabled / 73 paused.
**Saves:** ~$5/mo direct (scheduler fees) + defense-in-depth alongside the Phase 3 code fix.

The list of paused jobs is documented at `/tmp/nba_pause_list.txt` (and reproduced in this doc's appendix).

---

## What was NOT changed (and why)

| Item | Why not |
|------|---------|
| `prediction-coordinator` min=1 | Shared with MLB pipeline. Cold start would hurt MLB predictions. Apr-Sep MLB in season. |
| 3 NBA orchestrator CFs min=1 | Risk Reviewer rated min=0 as CRITICAL — Pub/Sub retry storms if any message arrives. Phase 3 code fix achieves the same outcome safely. |
| `memberradar-prod` Cloud SQL | Recently deployed (Mar 26, last build Apr 4) — appears active. $11/mo not worth disturbing. |
| `urcwest` Firebase functions | User-facing bid management app (separate from NBA). Min-instance functions are HTTP-callable, low-latency required. |
| Stale scheduler job deletions | Audit found 0 jobs pointing to truly deleted services (no `nba-phase1-scrapers` or BDL targets remain). |
| MLB-specific anything | MLB is in-season. All MLB jobs and services left untouched. |

---

## Cost trajectory (verified)

| Period | Daily | Monthly |
|--------|-------|---------|
| Pre-fix baseline (Apr 20-24) | ~$24 | ~$705-720 |
| After Apr 24 fixes (Apr 25) | $17.76 | ~$530 |
| After Apr 25 fixes (Apr 26) | $10.54 | ~$315 |
| Projected with Apr 26 deploy + scheduler pause | ~$9 | **~$270-300** |

Total reduction: **~$570-600/mo (~70%)**

---

## October 2026 — NBA Season Re-Enablement Runbook

Mark calendar reminder for **September 25, 2026** to begin re-enablement (1 week before season).

### Step 1 — Restore `prediction-worker` to min=1
```bash
gcloud run services update prediction-worker \
  --project=nba-props-platform --region=us-west2 --min-instances=1
```
Update `bin/deploy-service.sh` `get_min_instances()` to add `prediction-worker` back to the min=1 list.

### Step 2 — Resume the 70 paused NBA scheduler jobs
```bash
# Use the pause list from this session (preserved in memory)
while IFS= read -r job; do
  gcloud scheduler jobs resume "$job" --project=nba-props-platform --location=us-west2
done < nba_pause_list.txt
```

### Step 3 — Backfill stale rolling tables BEFORE first prediction
**Critical** — the regime detection and decay state machine read these tables. If stale, models may be wrongly BLOCKED for week 1.

```bash
# Recompute league_macro_daily for Sep 25 → Oct 1
PYTHONPATH=. python ml/analysis/league_macro.py --backfill --start 2026-09-25 --end 2026-10-01

# Recompute model_performance_daily
PYTHONPATH=. python orchestration/cloud_functions/post_grading_export/main.py --date 2026-10-01 --backfill
```

### Step 4 — Verify Phase 3 early-exit doesn't fire on real game days
The early-exit only activates on no-game days. To sanity-check on first October game day:
```bash
# Should return >0 if games exist
bq query --nouse_legacy_sql 'SELECT COUNT(*) FROM `nba-props-platform.nba_reference.nba_schedule` WHERE game_date = CURRENT_DATE() AND (game_id LIKE "002%" OR game_id LIKE "004%")'
```

### Step 5 — Watch the canary alerts on first game day
First NBA game day in October:
- `#canary-alerts` should NOT fire `Phase 5 - Prediction Gap` (means predictions ran)
- `#nba-alerts` should NOT fire `Pick drought`

If predictions are missing, `self-heal-predictions` runs at 12:45 PM ET as a safety net and will trigger Phase 3→4→5 cascade.

### Estimated re-enablement time
Automated steps: ~5 minutes. Backfill: ~10-20 minutes. Verification: ~10 minutes. **Total: ~30 minutes hands-off.**

---

## What's left on the table for future cost work

These were identified during the audit but not pursued this session:

1. **Phase 2 processors $32/mo** — `mlb-phase2-raw-processors` and `nba-phase2-raw-processors` cost more than expected for event-driven services. Worth investigating Pub/Sub trigger frequency.
2. **BigQuery $77/mo** — top queries via `INFORMATION_SCHEMA.JOBS` have not been audited recently. Some unfiltered scans likely remain.
3. **Cloud Workflows architecture** — Architecture Reviewer suggested the entire 5-workflow + 6-phase system is overengineered for a hobby project. Consider rebuilding as a single daily Cloud Run Job during summer 2026 (estimated $54-70/mo total cost vs current $270).
4. **Artifact Registry $19/mo** — `cloud-run-source-deploy` (17GB) and `gcf-artifacts` (15GB) auto-managed repos have no lifecycle policy.

---

## Appendix — Paused Scheduler Job List (70 jobs)

```
covers-referee-stats-weekly
dailyfantasyfuel-projections-daily
decay-detection-daily
dimers-projections-daily
espn-projections-daily
evening-analytics-10pm-et
evening-analytics-6pm-et
execute-workflows
fantasypros-projections-daily
filter-counterfactual-evaluator-daily
grading-daily
grading-latenight
grading-morning
grading-readiness-check
hashtagbasketball-dvp-daily
kalshi-props-scraper
live-export-evening
live-export-late-night
ml-feature-store-10am-et
ml-feature-store-1pm-et
ml-feature-store-7am-et
ml-feature-store-daily
missing-prediction-check
morning-predictions
nba-assists-props-morning
nba-assists-props-pregame
nba-grading-gap-detector
nba-playoffs-shadow-review
nba-props-evening-closing
nba-props-midday
nba-props-morning
nba-props-pregame
nba-rebounds-props-morning
nba-rebounds-props-pregame
nba-tracking-stats-daily
nbac-player-movement-daily
numberfire-projections-daily
overnight-analytics-6am-et
overnight-predictions
player-composite-factors-daily
player-composite-factors-upcoming
player-daily-cache-daily
player-movement-registry-afternoon
player-movement-registry-morning
predictions-12pm
predictions-9am
predictions-final-retry
predictions-last-call
rotowire-lineups-daily
same-day-phase3
same-day-phase3-tomorrow
same-day-phase4
same-day-phase4-tomorrow
same-day-predictions
self-heal-predictions
signal-weight-report-weekly
vsin-betting-splits-daily
weekly-retrain-trigger
overnight-phase4
overnight-phase4-7am-et
phase4-timeout-check-job
phase6-tonight-picks
phase6-tonight-picks-morning
phase6-tonight-picks-pregame
phase6-daily-results
odds-sweep-nightly
boxscore-completeness-check
validation-pre-game-final
validation-pre-game-prep
validation-post-overnight
```

---

## References

- Initial audit: `docs/08-projects/current/2026-offseason-plan/02-GCP-BILLING-AUDIT.md`
- Validation backlog (separate scope): `docs/08-projects/current/2026-offseason-plan/01-VALIDATION-AND-IMPROVEMENT-PLAN.md`
- Phase 3 early-exit commit: `cb0516dc`
- Memory: `gcp-cost-structure.md` (under `~/.claude/projects/.../memory/`)
