# MLB Monitoring Posture — Offseason Verification
**Compiled:** 2026-04-26
**Trigger:** After scaling down NBA infrastructure, verify that MLB monitoring will reliably catch issues during the season.

---

## Summary

MLB monitoring is **operational and properly alerting**, but with one fix needed (canary was firing false-positive `GRADING OUTAGE` alerts during NBA playoffs, drowning real MLB issues — fixed in commit `cfd09ee3`). Slack alert delivery is verified working.

One known gap: `mlb_self_heal` Cloud Function exists in code but has never been deployed. Documented below as a future improvement, not blocking.

---

## What's Monitoring MLB Right Now

### 1. Pipeline Canary (every 15 minutes, CRITICAL tier)

`nba-pipeline-canary-trigger` (Cloud Run Job, every 15 min) runs the CRITICAL tier of `bin/monitoring/pipeline_canary_queries.py`. The CRITICAL set includes 2 dedicated MLB checks:

| Check | Phase tag | What it catches |
|-------|-----------|----------------|
| MLB Phase 5 — Pitcher Strikeout Predictions | `mlb_phase5_predictions` | Yesterday's predictions count < 3 (means MLB pipeline didn't generate predictions) |
| MLB Phase 6 — Best Bets Published | `mlb_phase6_best_bets` | Predictions exist but BB pipeline produced 0 picks (silent failure) |

Both fire to `#canary-alerts` via Slack webhook (`slack-webhook-canary-alerts` secret, verified populated).

### 2. MLB-specific schedulers (47 enabled, all month-restricted to `3-10`)

| Job | Cadence | Purpose |
|-----|---------|---------|
| `mlb-stall-detector-hourly` | hourly | Detects pipeline stalls |
| `mlb-freshness-checker-hourly` | every 2h | Validates table freshness |
| `mlb-gap-detection-daily` | 1pm | Finds prediction/grading gaps |
| `mlb-prediction-coverage-pregame` | pregame | Coverage validation before first pitch |
| `mlb-prediction-coverage-postgame` | postgame | Coverage validation after games |
| `mlb-prediction-coverage-validator-pregame` / `-postgame` | both | Secondary validators |
| `mlb-pitcher-props-validator-4hourly` | every 4h | Validates pitcher prop data |
| `mlb-grading-daily` | daily | Grades MLB picks |
| `mlb-shadow-grading-daily` | daily | Shadow model grading |
| `mlb-schedule-validator-daily` | daily | Validates schedule integrity |
| `mlb-overnight-results` | overnight | Pulls overnight results |

### 3. Sport-agnostic monitors (cover MLB too)

| Job | What it catches |
|-----|----------------|
| `dlq-monitor-job` (every 15min) | Dead-letter queue messages from any pipeline |
| `gcs-freshness-monitor` (4×/day) | Stale/missing GCS objects |
| `daily-pipeline-health-summary` (daily 6am) | Cross-pipeline health roll-up |
| `daily-health-check-8am-et` | Daily freshness check across all critical tables |
| `nba-deployment-drift-alerter-trigger` (every 2h) | Detects config drift on ALL Cloud Run services including MLB |
| `data-quality-alerts-job` (daily 7pm) | Cross-sport data quality issues |
| `pipeline-health-monitor-job` (every 30min during late-night window) | Pipeline state during overnight hours |

### 4. Alert routing

All alerts route to `#canary-alerts` Slack channel via `SLACK_WEBHOOK_URL_CANARY_ALERTS` env var sourced from Secret Manager. Verified the secret contains a valid webhook URL.

---

## Gaps Found and Fixed

### Fix 1 — `grading_freshness` false positives during NBA playoffs (commit `cfd09ee3`)

**Symptom:** Local canary runs were producing `GRADING OUTAGE` alerts because `prediction_accuracy` has 0 records during NBA playoffs/offseason (NBA predictions intentionally halted).

**Fix:** Added `not is_nba_offseason` guard to the `grading_freshness` check (matches the existing pattern used by `edge_collapse_alert`). The `is_nba_offseason` variable already detects both true offseason and playoff windows.

**Why this matters for MLB:** Without this fix, the canary fires alerts every 15 minutes for an NBA-only condition. Alert fatigue would mask real MLB failures hidden in the same channel. MLB monitoring is unaffected — the dedicated MLB checks always run.

---

## Known Gap (Not Fixed This Session)

### `mlb_self_heal` Cloud Function exists in code but is not deployed

**Location:** `orchestration/cloud_functions/mlb_self_heal/main.py`

**What it does:** Mirrors the NBA `self-heal-predictions` CF — checks if MLB predictions exist for today, triggers Phase 3→4→predictions cascade if missing. Runs at 12:45 PM ET (45 minutes before Phase 6 export).

**Why it's not deployed:** No `deploy.sh` was ever written for this CF. The directory only has `main.py` and `requirements.txt`.

**Impact today:** If MLB predictions silently fail, the canary will alert within 15 minutes (good), but no automatic recovery happens. Manual intervention required to re-run the pipeline. NBA has self-heal-predictions for this exact scenario.

**Recommendation:** Deploy `mlb_self_heal` if MLB becomes higher-priority. Not urgent for a hobby-tier MLB project — Slack alerts are sufficient awareness.

---

## How to Verify Alerts Are Working

To sanity-check the alert path without waiting for a real incident:

```bash
# Trigger a manual canary run with --tier critical
gcloud run jobs execute nba-pipeline-canary --project=nba-props-platform --region=us-west2 --wait

# Check the execution status
gcloud run jobs executions list --job=nba-pipeline-canary --project=nba-props-platform --region=us-west2 --limit=3
```

Watch `#canary-alerts` in Slack — if any check fails the message will appear there.

To force-test the alert path itself, you could temporarily lower a threshold (e.g., set `mlb_phase5_predictions` min from 3 to 99) to make a check intentionally fail. Restore after.

---

## What Will Catch What — Failure Mode Map

| If this breaks | Detected by | Time to alert |
|----------------|-------------|---------------|
| MLB scrapers stop running | `mlb-stall-detector-hourly` + `mlb-freshness-checker-hourly` | ≤ 1-2 hours |
| MLB Phase 2 raw processing fails | `dlq-monitor-job` (failed messages → DLQ) | 15 min |
| MLB Phase 3 analytics doesn't run | `mlb-gap-detection-daily` + canary `mlb_phase5_predictions` | 15 min – 24h |
| MLB predictions don't generate | Canary `mlb_phase5_predictions` | 15 min |
| MLB best bets pipeline produces 0 picks | Canary `mlb_phase6_best_bets` (silent-failure detection) | 15 min |
| MLB grading fails | `mlb-grading-daily` failure + canary | next-day |
| MLB BQ tables go stale | `mlb-freshness-checker-hourly` + `gcs-freshness-monitor` | 2 hours |
| A deployed MLB service crashes / drifts | `nba-deployment-drift-alerter-trigger` | 2 hours |
| MLB schedule data missing for a date | `mlb-schedule-validator-daily` | next-day |
| Pipeline overall health degrades | `daily-pipeline-health-summary` (6 AM) | next-day |

---

## What's NOT Currently Covered

These conditions would not trigger a Slack alert automatically:

1. **MLB Pub/Sub topic backlog (no DLQ overflow)** — Messages stuck in retry without flowing to DLQ won't fire `dlq-monitor-job`. Would need a custom Pub/Sub backlog metric.
2. **MLB scraper output drops below historical baseline (but isn't zero)** — Detection requires baseline tracking, which `scrapers/mixins/validation_mixin.py` lacks (T3-6 in the validation backlog).
3. **MLB model drift on a specific feature** — No MLB equivalent of NBA `decay-detection` CF. MLB grading happens but no automated decay state machine.

These are pre-existing gaps, not introduced by the offseason cost reduction work. They're tracked for future improvements.

---

## References

- Cost reduction execution log: `docs/08-projects/current/2026-offseason-plan/03-COST-REDUCTION-EXECUTION.md`
- Canary code: `bin/monitoring/pipeline_canary_queries.py`
- MLB-specific check definitions: lines 441-484 in canary code
- Slack webhook secret: `slack-webhook-canary-alerts` in Secret Manager
- Tier classification: `CRITICAL_CHECKS` frozenset, ~line 1600 in canary code
