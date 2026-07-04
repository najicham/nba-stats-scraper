#!/usr/bin/env bash
# Re-enable NBA pipeline pieces paused for the 2026 off-season (2026-07-03).
# See docs/runbooks/nba-offseason-2026-reenable.md for full context.
set -euo pipefail

PROJECT=nba-props-platform
LOCATION=us-west2

echo "== Resuming paused NBA scheduler jobs =="
for job in \
  nba-pipeline-canary-trigger \
  nba-pipeline-canary-routine-trigger \
  nba-deployment-drift-alerter-trigger \
  nba-rebounds-props-morning \
  rotowire-nba-news-daily \
  rotowire-nba-news-frequent \
  espn-injuries-hourly \
  nba-assists-props-morning \
  nba-assists-props-pregame \
  nba-rebounds-props-pregame; do
  gcloud scheduler jobs resume "$job" --project="$PROJECT" --location="$LOCATION" \
    && echo "resumed: $job" \
    || echo "WARN: could not resume $job (deleted? already running?)"
done

echo
echo "== Reverting news-fetcher to NBA+MLB =="
gcloud scheduler jobs update http news-fetcher \
  --project="$PROJECT" --location="$LOCATION" \
  --message-body='{"sports": ["nba", "mlb"], "generate_summaries": true, "max_articles": 50}'
echo "news-fetcher now covers nba+mlb"

echo
echo "== CLV closing-line capture (P1.2, 2026-07-03) — CREATE these before opening night =="
echo "1. T-30 closing-line sweep (cannot be backfilled — every missed night is lost CLV data):"
echo "   ./bin/deploy/deploy_closing_lines_scheduler.sh"
echo "2. Late-slate CLV re-export (7:30 PM ET) — created by the phase6 scheduler deploy:"
echo "   ./bin/deploy/deploy_phase6_scheduler.sh   # includes phase6-clv-reexport-late"
echo "3. Restore the DELETED 'execute-workflows' job (workflow engine executor — betting_lines"
echo "   and every other workflow is dark without it). Pull config from the backup JSON:"
echo "   gs://nba-bigquery-backups/scheduler-jobs-backup/scheduler_jobs_backup_2026-07-03.json"
echo "   (POST {nba-scrapers}/execute-workflows at '5 6-23 * * *' ET, OIDC auth; its twin"
echo "   master-controller-hourly is still ENABLED — decisions get written but nothing"
echo "   executes them until this job is restored.)"

echo
echo "== Pre-season fixes required (from the 2026-07-03 ten-agent review) =="
echo "1. nba-pipeline-canary job is BROKEN: every execution fails with"
echo "   \"can't open file '/app/bin/monitoring/pipeline_canary_queries.py'\"."
echo "   Rebuild/fix the image BEFORE resuming its triggers, or it burns \$18/mo failing."
echo "2. nba-monitoring-alerts has broken BQ queries ('Unrecognized name: is_correct',"
echo "   'Dataset ml_nba was not found') — fix before trusting its alerts."
echo "3. phase4-precompute /process-date latency tripled ~May 31 (60-220s/request)."
echo "   Diff the revision that shipped around then before season load returns."

echo
echo "== Reminder: deleted jobs =="
echo "94 previously-paused jobs were DELETED on 2026-07-03."
echo "Backup: gs://nba-bigquery-backups/scheduler-jobs-backup/scheduler_jobs_backup_2026-07-03.json"
echo "Restore any you need with 'gcloud scheduler jobs create http' using the backed-up config."
echo "See docs/runbooks/nba-offseason-2026-reenable.md for the notable-jobs list."
