# CF / service ↔ scheduler ↔ trigger pairing audit — 2026-08-21

**Why this exists.** The game plan names "code that runs and affects nothing" as a
season-costing root cause. `weekly-retrain` was the known case. This audit asks the
question systematically, for every deployed component: **is it deployed by something, and
is it invoked by something?**

**Inventory:** 76 Gen2 Cloud Functions · 93 Cloud Run services · 66 Cloud Run **Jobs** ·
110 scheduler jobs (75 ENABLED / 35 PAUSED) · 36 build triggers · 22 Pub/Sub subscriptions
(21 push).

Four invocation paths must all be considered, or the audit produces false positives:
scheduler→HTTP, scheduler→topic→push-subscription, Eventarc/`eventTrigger`, and
service→service HTTP. A first pass that ignored push subscriptions wrongly flagged
`prediction-worker` and the Phase 2/3/4 processors as orphans.

---

## 1. Live failures — ENABLED jobs whose last attempt failed (code 13 = INTERNAL)

| job | schedule | target | assessment |
|---|---|---|---|
| **master-controller-hourly** | `0 * * * *` | `nba-scrapers/evaluate` | **PAUSED 2026-08-21.** Failed every hour, and its executor `execute-workflows` is deleted — so even a success wrote decisions nothing could act on. Resume PAIRED with `execute-workflows` per the catalog trap. |
| daily-schedule-locker | `0 10 * * *` | nba-scrapers | Off-season expected (no schedule to lock) — re-check after opener. |
| nba-assists-props-morning / -pregame | `0 10` / `0 16` | nba-scrapers | Off-season expected (no props markets). |
| nba-rebounds-props-morning / -pregame | `0 10` / `0 16` | nba-scrapers | Off-season expected. |
| firestore-state-cleanup | `0 3 * * 0` | transition-monitor | Ran against the 7-week-stale build; re-check after the 2026-08-21 redeploy. |
| shadow-performance-report-job | `0 9 * * 1` | shadow-performance-report | Needs triage — weekly, not season-gated. |

## 2. Orphans — deployed, but nothing invokes them

29 components have no scheduler, no event trigger and no push subscription. **13 are
covered by `ops/scheduler-catalog-2026.yaml`** and come back when the restore runs:

`analytics-processor` · `bias-decay-monitor` · `check-missing` · **`decay-detection`** ·
**`grading-gap-detector`** · `grading-readiness-monitor` · `live-export` ·
`phase4-timeout-check` · `precompute-processor` · `self-heal-predictions` ·
`signal-weight-report` · `validation-runner` · **`weekly-retrain`**

> **`decay-detection` is the important one.** CLAUDE.md states it runs daily 11 AM ET and
> auto-disables BLOCKED models. It has no scheduler, so **that safety net does not exist**
> today. Same for `grading-gap-detector` (documented as daily 9 AM ET).

The remaining 16 are **not** in the catalog. Triaged:

| component | verdict |
|---|---|
| `news-fetcher` | **FALSE POSITIVE** — ENABLED `*/15`, succeeding. Its job targets the Gen1 alias `us-west2-nba-props-platform.cloudfunctions.net`, which works; only the host-resolver missed it. |
| `nba-grading-service` | **By design** — on-demand `/grade-range`. Its automated path is the event-driven `phase5b-grading`. |
| `phase5-to-phase6` | Superseded duplicate of `phase5-to-phase6-orchestrator` (event-driven, healthy). Retire. |
| `self-heal-check` | **No source directory in the repo.** Deployed with no code to redeploy from. Retire. |
| `backfill-trigger`, `auto-backfill-orchestrator` | Likely superseded by `gap-detector` (ENABLED, 30-min) → `nba-backfill-trigger` → `backfill-pubsub-subscriber` (event-driven). **Confirm before retiring.** |
| `slack-reminder` | Unclear. Triage. |
| 4 dashboards (`nba-admin-dashboard`, `pipeline-dashboard`, `scraper-dashboard`, `unified-dashboard`) | Human-facing; no invoker expected. `unified-`/`pipeline-`/`scraper-dashboard` had 0 requests in 30d — deletion candidates. |
| `prediction-coordinator-dev` | Dev leftover, 0 requests in 30d. Deletion candidate. |
| 4 MLB (`mlb-phase6-grading`, `mlb-filter-counterfactual-evaluator`, `mlb-regime-monitor`, `mlb-pitcher-props-closing-materialize`) | MLB is halted by design. Re-assess only if MLB resumes. |

## 3. Paused that should be noticed

- **Both pipeline canaries are PAUSED** — `nba-pipeline-canary-trigger` (`*/15`) and
  `nba-pipeline-canary-routine-trigger` (hourly). Both target the Cloud Run **Job**
  `nba-pipeline-canary`, which exists. CLAUDE.md documents 30-minute pick-drought alerting;
  **it is not running.** These must be ENABLED before opening night.
- 3 MLB components are scheduler-paused (`mlb-prediction-worker`, `mlb-self-heal`,
  `mlb-snapshot-daily`) — consistent with MLB being halted.

## 4. Method note — two traps for the next person

1. **`us-west2-run.googleapis.com` is not a broken target.** 14 scheduler jobs point there;
   it is the Cloud Run **Jobs** Admin API (`:run`). Resolve those against
   `gcloud run jobs list` (66 exist), not `run services list`. A naive resolver reports
   them all as broken.
2. **Deploy coverage ≠ invocation coverage.** A component can have a build trigger and
   still never run (`decay-detection`, `weekly-retrain`), or have no trigger and run fine
   (`gap-detector`, `halt-state-writer`). They are independent axes and must be checked
   separately.

## 5. Actions

**Done:** `master-controller-hourly` paused.

**Before opening night:**
1. Enable both pipeline canaries.
2. Ensure the restore actually *resumes* — not merely creates — the 13 covered orphans,
   especially `decay-detection`, `weekly-retrain` and `grading-gap-detector`.
3. Triage `shadow-performance-report-job` (failing weekly, not season-gated).
4. Confirm-then-retire `phase5-to-phase6`, `self-heal-check`, and (after confirming the
   `gap-detector` path) `backfill-trigger` / `auto-backfill-orchestrator`.
5. Re-check the six off-season-expected failures once games return; they are only
   "expected" while there is no schedule.

*Data: `gcloud` live queries + `ops/scheduler-snapshots/scheduler-jobs-2026-08-21.json`.*
