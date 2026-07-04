# NBA Off-Season Shutdown (2026-07-03) — Re-Enable Runbook

Cost-cutting changes made 2026-07-03 during the GCP bill investigation.
**Run `./scripts/nba_offseason_reenable.sh` before the 2026-27 NBA season starts**
(preseason ~early Oct, opening night ~Oct 21).

## What was turned off (and how to turn it back on)

### 1. Paused scheduler jobs (NBA-only, high-frequency)

| Job | Schedule | Why paused |
|---|---|---|
| `nba-pipeline-canary-trigger` | every 15 min | Exercises full NBA pipeline; no games to canary |
| `nba-pipeline-canary-routine-trigger` | hourly | Same |
| `nba-deployment-drift-alerter-trigger` | every 2 h | NBA deploy monitoring |
| `nba-rebounds-props-morning` | daily 10:00 | No props off-season |
| `rotowire-nba-news-daily` | daily 12:00 (May–Sep) | NBA news off-season |
| `rotowire-nba-news-frequent` | every 10 min, 10:00–22:00 | 78 runs/day returning "0 rows" off-season (added after 10-agent review) |
| `espn-injuries-hourly` | hourly 10:00–20:00 | No GTD situations off-season |
| `nba-assists-props-morning` | daily 10:00 | No props off-season |
| `nba-assists-props-pregame` | daily 16:00 | No props off-season |
| `nba-rebounds-props-pregame` | daily 16:00 | No props off-season |

Re-enable: `gcloud scheduler jobs resume <job> --project=nba-props-platform --location=us-west2`

### 2. news-fetcher switched to MLB-only

The job still runs every 15 min but body was changed from
`{"sports": ["nba", "mlb"], ...}` to `{"sports": ["mlb"], ...}`.

Revert:
```bash
gcloud scheduler jobs update http news-fetcher \
  --project=nba-props-platform --location=us-west2 \
  --message-body='{"sports": ["nba", "mlb"], "generate_summaries": true, "max_articles": 50}'
```

### 3. 94 already-paused scheduler jobs DELETED

All jobs that were in state PAUSED before 2026-07-03 were deleted
(~$9/mo — Cloud Scheduler bills per job even when paused).

Full JSON backup of **all 204 jobs** (schedules, targets, bodies, headers):
`gs://nba-bigquery-backups/scheduler-jobs-backup/scheduler_jobs_backup_2026-07-03.json`

To restore one, pull its config from the backup and `gcloud scheduler jobs create http ...`.
Notable deleted NBA-season jobs you may want back in October:
`nba-props-pregame`, `predictions-last-call`, `same-day-predictions`, `grading-daily`,
`player-composite-factors-daily`, `player-daily-cache-daily`, `ml-feature-store-daily`,
`espn-projections-daily`, `fantasypros-projections-daily`, `dimers-projections-daily`,
`missing-prediction-check`, `decay-detection-daily`, `execute-workflows`.

### 4. NOT changed (still running, still costing)

- min-instances on `prediction-coordinator` + 3 phase orchestrators (~$75/mo) — declined
- Shared NBA+MLB services left alone: `gap-detector-30min`, `scraper-gap-backfiller-*`,
  `live-freshness-monitor` (MLB in season)
- Artifact Registry cleanup policies added (keep 5 recent, delete >30d) — permanent, no action needed
- Logging exclusion `exclude-bq-audit-noise` added — permanent, no action needed

## CLV closing-line capture (P1.2) — jobs to CREATE before opening night

These did not exist at shutdown; they ship with the 2026-07-03 P1.2 work and are
**season-open-BLOCKING** (closing lines cannot be backfilled):

1. **`nba-closing-lines-sweep`** — per-game T-30 odds snapshot. Create with
   `./bin/deploy/deploy_closing_lines_scheduler.sh` (add `--paused` if creating
   before the nba-scrapers deploy that ships `/closing-line-sweep`). Verify in
   preseason: every final game gets a snapshot with `minutes_before_tipoff IN [0,45]`
   (`snapshot_type='closing'`); the `closing_line_capture` canary alerts below 90%.
2. **`phase6-clv-reexport-late`** — 7:30 PM ET signal-best-bets re-export for the
   late slate. Created by `./bin/deploy/deploy_phase6_scheduler.sh`.
3. **Restore `execute-workflows`** (deleted in the 94-job purge) — the workflow
   executor; `betting_lines` produces zero snapshots without it. Config in the
   backup JSON (`scheduler_jobs_backup_2026-07-03.json`): POST
   `{nba-scrapers}/execute-workflows`, `5 6-23 * * *` ET, OIDC. Its twin
   `master-controller-hourly` (`/evaluate`) is still ENABLED (`0 * * * *`,
   verified 2026-07-03) — decisions are being written but nothing executes them
   until `execute-workflows` is restored.

## Pre-season fixes required (found by the 2026-07-03 ten-agent review)

1. **`nba-pipeline-canary` job is broken** — every execution fails:
   `can't open file '/app/bin/monitoring/pipeline_canary_queries.py'`. It was failing
   ~100×/day at $18.5/mo providing zero monitoring. Fix the image before resuming triggers.
2. **`nba-monitoring-alerts` queries are broken** (`Unrecognized name: is_correct`,
   `Dataset ml_nba was not found`) — repair before trusting alerts in season.
3. **phase4-precompute latency regression**: /process-date went from ~$1.00/day to
   ~$3.0-3.6/day around May 31 with only +12% request volume (60–220 s per call).
   Diff the ~May 31 revision before season load returns.
4. **Rollback caveat**: AR cleanup policies delete images >30 d (keep 5/package).
   Roll back via Cloud Run revision traffic-splitting, NOT by redeploying old tags.
5. **`deployment-drift-schedule`** (every 2 h, pub/sub topic `deployment-drift-check`)
   may be a second live trigger for the drift alerter that was paused — check its
   subscribers if drift alerts keep arriving.

## Related changes the same day (other projects)

- `infinite-case`: `infinitecase-backend` set to min-instances=0 + CPU throttling
  (was 4CPU/16Gi always-on, ~$340/mo). deploy.sh + cloudbuild.yaml updated to match.
  Cloud SQL left running (still used for case processing).
