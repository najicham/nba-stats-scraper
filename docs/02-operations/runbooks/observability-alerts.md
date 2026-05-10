# Pipeline Observability + Alert Runbook

**Audience:** on-call. **Last updated:** 2026-05-09.

## What's emitting metrics

Every phase processor + Cloud Function calls `shared.observability.metrics.emit_metric()` at run-end. Three custom metrics live under `custom.googleapis.com/nba_pipeline/`:

| Metric | Kind | Labels | What it means |
|---|---|---|---|
| `phase_completion` | GAUGE 0–1 | `phase`, `output_type`, `status`, `sport` | 1.0 = COMPLETE/EMPTY_OK, 0.5 = EXPECTED/RUNNING, 0.25 = DEGRADED, 0.0 = FAILED |
| `phase_row_count` | GAUGE | same | Actual row count of the output |
| `halt_state_age_hours` | GAUGE | `sport` | Hours since last halt_state write — alerts on writer death |

The emitter is fail-open: telemetry failures never crash callers.

## The three alert policies

All defined in `monitoring/alert-policies/`. Deploy with `./monitoring/alert-policies/deploy-alert-policies.sh`. Notification channels are attached manually in Cloud Monitoring console (gcloud doesn't support during create).

### `expected-output-overdue` (Critical)

**Fires when:** `expected_outputs_gaps` has > 5 overdue rows (status in EXPECTED/FAILED/DEGRADED, expected_by in past) for 30+ min.

**What to do:**
1. Open the gaps view: `SELECT * FROM nba_orchestration.expected_outputs_gaps ORDER BY hours_overdue DESC LIMIT 50`
2. Cluster the rows — same phase? Same date? Same output type? That tells you whether it's a single-output bug or a systemic issue.
3. If most are NBA halt-era dates and `halt_state.halt_active` says halted: reconciler should be flipping to EMPTY_OK on the next cycle. Wait one cycle. If still EXPECTED, halt_state may be lying — read [halt-mode-operations.md](halt-mode-operations.md).
4. If a specific scraper keeps failing: check `nba-backfill-trigger` Pub/Sub backlog and `scraper-gap-backfiller` logs.
5. If gap_detector is itself stuck at MAX_PUBLISHES_PER_RUN: temporary env var bump (see [backfill-a-date.md](backfill-a-date.md)).

### `halt-state-stale` (Warning)

**Fires when:** `halt_state_age_hours` > 36.

**What to do:** see [halt-mode-operations.md](halt-mode-operations.md) → "What if halt_state is stale?"

### `phase-error-rate` (Warning)

**Fires when:** `phase_completion` 1h mean < 0.7. Multiple outputs are unhealthy concurrently.

**What to do:**
1. Find the unhealthy phases:
   ```sql
   SELECT phase, status, COUNT(*) AS n
   FROM `nba-props-platform.nba_orchestration.expected_outputs`
   WHERE updated_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
   GROUP BY phase, status ORDER BY phase
   ```
2. Look for cross-cutting clustering (same phase across many dates → orchestrator bug; same date across phases → upstream data issue).
3. Check shared infra — BQ slot quota, GCS quotas, Cloud Run service errors panel.
4. Recent deploys? `gcloud builds list --region=us-west2 --project=nba-props-platform --limit=10`. Roll back the last service deploy if the error correlation matches its rollout time.

## Dashboard

`nba-pipeline-health` Cloud Monitoring dashboard (Phase L deliverable):
- Top row: phase × date heatmap, sourced from `expected_outputs_coverage` view.
- Middle: latency histograms by phase.
- Bottom: halt_state timeline (NBA + MLB), MLB-specific equivalents.

Until that's built, use the gaps view + the BQ console.

## Retired CFs (Phase G follow-up)

Eight CFs are scheduled for retirement once the new alerts have run cleanly for 7 days:

- `daily-health-check` — replaced by `expected-output-overdue` + `halt-state-stale`.
- `transition-monitor` — replaced by `phase-error-rate`.
- `pipeline-health-summary` — replaced by `nba-pipeline-health` dashboard.
- `live-freshness-monitor` — replaced by `expected_outputs` coverage during live game windows.
- `gcs-freshness-monitor` — replaced by reconciler GCS checks.
- `pipeline-reconciliation` — replaced by `phase_completion_reconciler`.
- `realtime-completeness-checker` — replaced by reconciler at higher cadence (today: 30min; can drop to 5min).
- `historical_completeness_monitor.py` — replaced entirely; was never deployed.

Do NOT retire any of these until 2026-05-16 at earliest.

## Manual notification channel attachment

```bash
# List channels
gcloud alpha monitoring channels list \
  --project=nba-props-platform --format='value(displayName, name)'

# Attach a channel to a policy (in Cloud Monitoring console: Alerting → Policies → Edit → add channel)
# CLI alternative:
gcloud alpha monitoring policies update <policy-id> \
  --add-notification-channels=<channel-name> \
  --project=nba-props-platform
```
