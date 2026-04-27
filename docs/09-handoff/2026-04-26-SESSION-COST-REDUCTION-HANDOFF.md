# Session Handoff — GCP Cost Reduction + MLB Monitoring + Tier-1 Bug Fixes

**Date:** 2026-04-26
**Trigger:** User reported high GCP bill; expanded into MLB monitoring verification + Tier-1 production bug fixes
**Outcome:** Bill on track from ~$870/mo → ~$270-300/mo. MLB monitoring verified. 3 known production bugs fixed.

> **Read first:** Three docs in `docs/08-projects/current/2026-offseason-plan/` capture the full audit:
> - `02-GCP-BILLING-AUDIT.md` — initial 30-day cost breakdown
> - `03-COST-REDUCTION-EXECUTION.md` — execution log + October re-enablement runbook
> - `04-MLB-MONITORING-POSTURE.md` — MLB monitoring verification + failure-mode map

---

## TL;DR for next session

The system is in a stable, low-cost offseason posture. Nothing is broken. Three things to verify in the next session:

1. **Daily cost has stabilized at ~$9-10/day** — check via `bq query` on `billing_export` table for last 3 days
2. **No false-positive `GRADING OUTAGE` alerts in Slack** — should be silenced after the canary fix deployed
3. **`mlb-self-heal` ran cleanly** at 12:45 PM ET on the next MLB game day — check function logs

If all 3 are good, this whole stream of work is closed. Move on to other priorities.

---

## What was changed (full list, 7 commits this session)

### Code changes (auto-deployed via Cloud Build push to main)

| Commit | What | Effect |
|--------|------|--------|
| `cb0516dc` | Phase 3 entry point: `has_regular_season_games()` early-exit | Stops Phase 2→3→4 cascade on no-game days. Fixes ~$94/mo of unnecessary cost. |
| `cfd09ee3` | Canary `grading_freshness` check: skip during NBA offseason/playoffs | Eliminates daily false-positive `GRADING OUTAGE` Slack alert |
| `06feba37` | 3 Tier-1 production bugs (T1-1, T1-2, T1-3) | See "Tier-1 fixes" section below |
| `74a68459` | Deploy script: `prediction-worker` removed from min=1 list | Prevents future deploys from re-setting min=1 |
| `a1a5ac0d` | `mlb_self_heal` deploy.sh added | Reproducibility for the new MLB CF |

### Infrastructure changes (applied via gcloud, NOT in git)

| Change | Status |
|--------|--------|
| `infinitecase-backend`: 4CPU/16Gi → 2CPU/4Gi | Revision `00143-xpj` |
| `infinitecase-backend`: cpu-throttling=false → true + min=0 | Revision `00144-gm5` |
| `prediction-worker`: min=1 → min=0 | Revision `00493-6cx` |
| Cloud Logging: 3 exclusion filters restored via REST API | `exclude-health-checks`, `exclude-heartbeats`, `monitoring-info-suppression` |
| `gs://nba-bigquery-backups`: lifecycle simplified to 30-day delete | Removed Coldline/Nearline/Archive transitions |
| AR cleanup policies on `nba-props`, `cloud-run-source-deploy`, `gcf-artifacts` | keep-3, delete-30d |
| 70 NBA-only Cloud Scheduler jobs paused | Defense-in-depth alongside Phase 3 code fix |
| `mlb-self-heal` Gen2 CF deployed | URL: `https://mlb-self-heal-f7p3g7f6ya-wl.a.run.app` |
| `mlb-self-heal-trigger` Cloud Scheduler created | `45 12 * 3-10 *` America/New_York |

---

## Tier-1 fixes from validation backlog (commit `06feba37`)

All three were called out in `docs/08-projects/current/2026-offseason-plan/01-VALIDATION-AND-IMPROVEMENT-PLAN.md`.

### T1-1: `high_book_std_under_block` UnboundLocalError → silent model blackout

`ml/signals/aggregator.py:921` referenced `qualifying` and `tags` before they were defined (line 1150). On any UNDER pick with `multi_book_line_std >= 0.75`, the aggregator raised `UnboundLocalError`. `per_model_pipeline.py:1678` swallowed the exception and returned `candidates=[]` for the crashing model with no Slack alert. **Fixed:** use the function's default args for `sig_count`/`sig_tags`.

### T1-2: Daily health check queried disabled BDL table

`orchestration/cloud_functions/daily_health_check/main.py:586` queried `nba_raw.bdl_player_boxscores` (intentionally empty since BDL was disabled). Fired CRITICAL `0/N games complete` every morning. **Fixed:** switched to `nba_raw.nbac_gamebook_player_stats` per CLAUDE.md "Key Tables".

### T1-3: WARNING alerts suppressed when CRITICAL fires

`orchestration/cloud_functions/daily_health_check/main.py:699` had `if results.warnings > 0 and not results.critical and SLACK_WEBHOOK_URL_WARNING:`. The `and not results.critical` clause silently dropped warnings whenever any critical fired. **Fixed:** removed that clause. Warnings now post independently.

---

## Cost trajectory

```
Pre-fix (Apr 1):       ~$870/mo  ($28/day)
After Apr 24 fixes:    ~$425/mo  ($14/day)
After Apr 25 fixes:    ~$315/mo  ($10/day, observed Apr 26)
Projected stable:      ~$270-300/mo
```

To verify on next session:
```bash
bq query --project_id=nba-props-platform --nouse_legacy_sql --format=pretty \
'SELECT DATE(usage_start_time) as date, ROUND(SUM(cost),2) as daily_cost
FROM `nba-props-platform.billing_export.gcp_billing_export_resource_v1_01169A_2CADBE_978AC6`
WHERE DATE(usage_start_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY date ORDER BY date DESC'
```

Expected: $8-12/day for nba-props-platform + infinite-case.

---

## What's still on the backlog (not urgent)

### Tier 1 remainders (medium effort, do before Oct 2026)
- **T1-4:** Phase 4→5 orchestrator has no feature-store coverage gate
- **T1-5:** Quality scoring blind to V16/V17 features (indices 54-59) — needs schema migration
- **T1-6:** Published JSON vs BQ store consistency never reconciled

### Cost (diminishing returns, ~$30-50/mo each)
- AR cleanup policies will trim repos automatically over the next few days — verify size dropped from `du -sh` output. nba-props should shrink from 56GB → ~10GB.
- Phase 2 processor right-sizing (`mlb-phase2-raw-processors` could be 0.5CPU/1Gi instead of 1CPU/2Gi, saves ~$8-10/mo)
- `bigdataball-puller` SA scanned 116GB in 7 days during offseason — worth investigating if it's still needed

### Tier 2 (off-season project work)
See `01-VALIDATION-AND-IMPROVEMENT-PLAN.md` for the 10 Tier-2 items. Highest-value group is the **training integrity trifecta** (T2-1, T2-2, T2-3) — temporal leakage in val splits, no governance holdout, V12 augmentation joins future eval data. Together these likely explain 1-3pp of the season's edge compression and fleet instability.

---

## October 2026 NBA re-enablement runbook

Calendar reminder: **Sept 25, 2026** to begin re-enablement. Full runbook in `03-COST-REDUCTION-EXECUTION.md`. Key steps:

1. Restore `prediction-worker` min=1 (deploy script edit + redeploy)
2. Resume the 70 paused NBA scheduler jobs (list in the doc's appendix)
3. Backfill `league_macro_daily` and `model_performance_daily` for Sep 25 → Oct 1 (otherwise regime detection + decay state machine will be wrong week 1)
4. Watch `#canary-alerts` on first NBA game day

Estimated 30 minutes hands-off after script launch. Do NOT skip step 3 — Operations Reviewer specifically flagged this as a real failure mode.

---

## What to verify on next session

Quick health check (5 minutes):

```bash
# 1. Cost trajectory stable
bq query --project_id=nba-props-platform --nouse_legacy_sql --format=pretty \
'SELECT DATE(usage_start_time) date, ROUND(SUM(cost),2) cost
FROM `nba-props-platform.billing_export.gcp_billing_export_resource_v1_01169A_2CADBE_978AC6`
WHERE DATE(usage_start_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 5 DAY)
GROUP BY date ORDER BY date DESC'
# Expected: $8-12/day

# 2. mlb-self-heal ran on a recent MLB game day
gcloud functions logs read mlb-self-heal --project=nba-props-platform --region=us-west2 --gen2 --limit=20

# 3. Canary not firing GRADING OUTAGE anymore
# Check #canary-alerts Slack channel — should be quiet

# 4. AR repos shrinking
gcloud artifacts repositories list --project=nba-props-platform --location=us-west2 --format="table(name,sizeBytes)"
# Expected: nba-props < 30GB (was 56GB), gcf-artifacts < 10GB (was 15GB)

# 5. Paused scheduler jobs still paused (NBA)
gcloud scheduler jobs list --project=nba-props-platform --location=us-west2 --format="value(state)" | sort | uniq -c
# Expected: ~109 ENABLED, ~73 PAUSED
```

If all 5 are green, this work is closed.

---

## Files changed in this session

```
data_processors/analytics/main_analytics_service.py          (cb0516dc — Phase 3 early-exit)
bin/monitoring/pipeline_canary_queries.py                    (cfd09ee3 — canary offseason gate)
ml/signals/aggregator.py                                     (06feba37 — T1-1)
orchestration/cloud_functions/daily_health_check/main.py     (06feba37 — T1-2, T1-3)
bin/deploy-service.sh                                        (74a68459 — prediction-worker min=0 default)
orchestration/cloud_functions/mlb_self_heal/deploy.sh        (a1a5ac0d — new file)
docs/08-projects/current/2026-offseason-plan/01-VALIDATION-AND-IMPROVEMENT-PLAN.md  (1354e018)
docs/08-projects/current/2026-offseason-plan/02-GCP-BILLING-AUDIT.md                (1354e018)
docs/08-projects/current/2026-offseason-plan/03-COST-REDUCTION-EXECUTION.md         (2645fcc6)
docs/08-projects/current/2026-offseason-plan/04-MLB-MONITORING-POSTURE.md           (5886a842, 094c9944)
```

---

## Known caveats

- **`infinitecase-backend` cold start ~3-5 seconds** on first request after idle. Documented in `gcp-cost-structure.md` memory file. When measuring app perf, ignore the first request after a quiet period.
- **70 NBA scheduler jobs are paused** (state=PAUSED, not deleted). They will need explicit `gcloud scheduler jobs resume` calls in October. The list is preserved in `03-COST-REDUCTION-EXECUTION.md` appendix.
- **`mlb-self-heal` was deployed manually**, not via cloudbuild-functions.yaml. The new `deploy.sh` is the reproducible path. Adding it to auto-deploy is optional future work.
- **AR cleanup policies are deployed but the actual size reduction takes a few days** as the cleanup eval cycle runs. Don't expect immediate disk savings.
