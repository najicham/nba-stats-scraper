# GCP Cost Reduction Plan — April 2026 (v3, Double Peer-Reviewed)

**Date:** 2026-04-02 (updated after second 8-agent deep-dive pass)
**Context:** Monthly bill spiked to ~$994/mo (prior baseline: ~$150/mo after Session 492)
**Research:** 5 discovery agents + 8 first-pass reviewers + 8 second-pass deep-dives = 21 agents total
**Total identified savings: $260–430/mo** (revised with concrete code-level evidence)

---

## Critical Corrections from Second Pass

| Finding | Impact on Plan |
|---------|---------------|
| **Orchestrator min-instances=1 was set 5 DAYS AGO** due to Pub/Sub retry storm (42+ cold-start failures, commit `a18d88f3`). `detect_config_drift.py` validates this. | REMOVE P0-2. Do NOT change to 0 without fixing cold-start first. |
| **Prediction coordinator and worker are ALREADY at min-instances=0** in deploy scripts | No action needed there |
| **Phase 3 fires 10-13x/day**, not 1-2x (6 Pub/Sub sources + 7 scheduler jobs, no deduplication) | CPU downgrade risk is higher; 2-week monitoring window is essential |
| **Publishing exporters scan `prediction_accuracy` without partition filters** — 10 GB+ full table scans daily | NEW P1 item — potential $85+/mo savings |
| **Cloud Build selective deployment already works** for 7 Cloud Run services | $22/mo is noise ($3-5/mo actual), not worth optimizing |
| **Terraform has no remote state backend** — local state only | Add to structural prevention |
| **Phase 3 memory is 8 GiB** (not 4 GiB as previously assumed) | Cost reconciliation adjusted |
| **MLB Phase 4 min-instances=0 confirmed** in deploy script line 95 | MLB wildcard definitively eliminated |

---

## P0 — Zero Risk, Immediate (~$100/mo)

### P0-1: Tiered Canary — Critical Checks Stay at 15min, Routine → 60min

**DO NOT reduce all checks to 60-minute.** 11 checks are revenue-critical and must stay at 15min.

**Tier 1 — KEEP at 15-minute (revenue-critical):**
Pick Drought, BB Filter Audit, Live-Grading Content, Grading Freshness, Edge Collapse Alert, Phase 5 Prediction Gap, Shadow Model Coverage, Phase 6 Publishing, Phase 3 Duplicates, Phase 3 Partial Coverage, Model Registry Blocked Models

**Tier 2 — Move to 60-minute (routine):**
Phase 1-3 basic data flow, Scheduler health, Signal freshness, Fleet diversity, Prediction accuracy duplicates

**Implementation:** Add second Cloud Scheduler job targeting canary with `tier=routine` parameter:
```bash
gcloud scheduler jobs create http nba-pipeline-canary-routine \
  --schedule="0 * * * *" --region=us-west2 --project=nba-props-platform \
  --uri="CANARY_JOB_URL" --message-body='{"tier":"routine"}'
```

Also remove duplicate **Check #11** (identical 200MB `ml_feature_store_v2` scan as Check #4).

**Savings:** ~$32/mo + $2-3/mo (duplicate check)

---

### P0-2: Phase 4 CPU 4 → 2

**First verify actual deployed config** (deploy script shows min-instances=0 and 4 CPU, but cost math doesn't reconcile at request-based rates):
```bash
gcloud run services describe nba-phase4-precompute-processors \
  --region=us-west2 --project=nba-props-platform \
  --format="value(spec.template.metadata.annotations,spec.template.spec.containers[0].resources.limits)"
```

**If actual config matches scripts** (min-instances=0, 4 CPU): downsize to 2 CPU.
**If min-instances > 0**: fix that first, then downsize CPU.

```bash
gcloud run services update nba-phase4-precompute-processors \
  --cpu=2 --region=us-west2 --project=nba-props-platform
```

**Savings:** ~$30/mo

---

### P0-3: Delete `nba-phase1-scrapers` & BigDataBall Scheduler Jobs

```bash
# Delete dead service
gcloud run services delete nba-phase1-scrapers --region=us-west2 --project=nba-props-platform --quiet

# Find and delete BDL scheduler jobs (7+ targeting disabled scrapers)
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform \
  --format="table(name,httpTarget.uri)" | grep -iE "bdl|bigdata|ball|phase1"
# Delete each found job
```

**Savings:** ~$15-18/mo (BDL $17 + phase1 $0.24)

---

### P0-4: Add Cloud Logging Exclusion Filters (via Terraform)

**Critical:** Add to `infra/cloud_logging.tf`, NOT the GCP Console — console-only changes get wiped by `terraform apply`.

Create `infra/cloud_logging.tf`:
```hcl
resource "google_logging_project_exclusion" "exclude_health_checks" {
  name        = "exclude-health-checks"
  description = "Exclude /health GET logs from Cloud Run services"
  filter      = <<-EOT
    resource.type="cloud_run_revision"
    AND (textPayload=~".*GET /health.*"
      OR textPayload=~".*GET /healthz.*"
      OR textPayload=~".*GET /ready.*")
  EOT
}

resource "google_logging_project_exclusion" "exclude_heartbeats" {
  name        = "exclude-heartbeats"
  description = "Exclude repetitive heartbeat logs from pipeline processors"
  filter      = <<-EOT
    resource.type="cloud_run_revision"
    AND jsonPayload.message="Heartbeat"
  EOT
}
```

**Do NOT use the 2xx success log filter** — Phase 3 returns HTTP 200 on partial processor failures (safety reviewer confirmed), so error-adjacent logs would be silently dropped.

**Apply:**
```bash
terraform plan -target=google_logging_project_exclusion.exclude_health_checks \
               -target=google_logging_project_exclusion.exclude_heartbeats
terraform apply -target=google_logging_project_exclusion.exclude_health_checks \
               -target=google_logging_project_exclusion.exclude_heartbeats
```

**Savings:** ~$25-35/mo (targeting 50-70 GB reduction from 186 GB)

---

## P1 — Low Risk, Confirmed, ~1-4 Hours (~$175/mo)

### P1-1: Fix Publishing Exporter BQ Scans (NEW — Biggest BQ Opportunity)

**Finding:** 4 publishing exporters scan `prediction_accuracy` (10 GB+) without `game_date` partition filters:
- `data_processors/publishing/player_profile_exporter.py` line 181
- `data_processors/publishing/best_bets_exporter.py` (multiple)
- `data_processors/publishing/results_exporter.py`
- `data_processors/publishing/trends_tonight_exporter.py`

These run daily and scan 12 months of history every time. The schema (`schemas/bigquery/nba_predictions/prediction_accuracy.sql` line 84) already sets `require_partition_filter=TRUE` but the application code bypasses it.

**Fix:** Add `game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)` to each query. Exporters only display recent data anyway.

**Verify what's being scanned:**
```sql
SELECT user_email, statement_type, total_bytes_processed, referenced_tables
FROM `region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND total_bytes_processed > 1000000000
ORDER BY total_bytes_processed DESC
LIMIT 20
```

**Savings:** ~$85/mo (the "unaccounted" BQ cost in the audit is likely these scans)

---

### P1-2: Phase 3 CPU 4 → 2

**Important context from second pass:**
- Phase 3 fires **10-13x/day** (not 1-2x): 6 independent Pub/Sub sources + 7 Cloud Scheduler jobs, no deduplication
- The $125/mo cost is consistent with this frequency at always-on pricing (if min-instances > 0) OR at ~100+ invocations/day
- **First verify actual deployed config** (same as Phase 4 above)

After verifying config:
```bash
gcloud run services update nba-phase3-analytics-processors \
  --cpu=2 --region=us-west2 --project=nba-props-platform
```

**Monitor for 2 weeks** (must cover weekday, weekend, busy day, and backfill scenarios). Phase 3 is the most complex trigger pattern in the system.

**Savings:** ~$62/mo

---

### P1-3: MLB Phase 4 CPU 4 → 2

**Confirmed:** `mlb-phase4-precompute-processors` already has `min-instances=0` (deploy script line 95). The wildcard concern was a false alarm. But 4 CPU for 3-4 strikeout predictions/day is extreme over-provisioning.

```bash
gcloud run services update mlb-phase4-precompute-processors \
  --cpu=2 --region=us-west2 --project=nba-props-platform
```

**Savings:** ~$30/mo

---

### P1-4: Artifact Registry Lifecycle Policy

**Evidence:** No lifecycle policy in `infra/artifact_registry.tf`. 111 GB in `nba-props` repo accumulating indefinitely.

Create `bin/cleanup-artifact-registry.sh` with dry-run mode (see v2 of this doc for full script).
Run dry-run first, then schedule weekly via Cloud Scheduler Sunday 11 PM.

**Corrected savings:** ~$12-13/mo (not $20/mo — only 123 GB available to prune, not 200 GB).

---

### P1-5: Canary Feature Store — Hourly Materialized View

**Correction from monitoring reviewer:** Must be **hourly** not daily — feature store quality degrades intra-day (injury news, line movement). Daily materialization = 12h blind window.

```sql
CREATE OR REPLACE TABLE `nba-props-platform.nba_predictions.feature_store_health_hourly`
PARTITION BY DATE(updated_at)
AS SELECT
  game_date,
  COUNT(DISTINCT player_lookup) AS player_count,
  ROUND(AVG(feature_quality_score), 2) AS avg_quality,
  COUNTIF(quality_alert_level = 'red') AS red_alert_count,
  COUNTIF(default_feature_count > 0) AS blocked_players,
  CURRENT_TIMESTAMP() AS updated_at
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY game_date;
```

Schedule hourly via BigQuery scheduled query. Add fallback in canary code if table is stale.

**Savings:** ~$6-8/mo

---

### P1-6: Canary Rolling Window Reduction (7/14 day → 3 day)

Checks #10, #14, #28 look back 7-14 days for health monitoring. 3-day window is sufficient.

**Savings:** ~$3-5/mo

---

### P1-7: Audit and Delete Stale Dev/Staging Services

```bash
gcloud run services list --region=us-west2 --project=nba-props-platform \
  --format="table(metadata.name)" | grep -E "dev|staging|test"
```

**Known candidates:** `prediction-coordinator-dev`, any `*-staging` services.
**Savings:** ~$10-20/mo

---

## P2 — Medium Risk, Needs Testing (~$50/mo)

### P2-1: Orchestrator Min-Instances (DOWNGRADED from P0)

**Status: HIGH RISK. Do not execute without a mitigation plan.**

Commit `a18d88f3` (5 days ago) set orchestrators to `min-instances=1` after a production incident: "42+ 'no available instance' errors from Pub/Sub retry storms hitting cold-started functions." `detect_config_drift.py` validates this config and would alert on regression.

**Before attempting min-instances=0, first implement:**
1. Increase Pub/Sub subscription ACK deadline from 60s to 120s (gives cold-start more time)
2. Verify DLQ is active on all orchestrator subscriptions
3. Add exponential backoff to Pub/Sub publisher

**If those are in place:**
- Estimated savings: ~$13-20/mo (lower than $25-35/mo originally estimated — only 3 orchestrators at 512MB each)
- The prediction-coordinator and prediction-worker are ALREADY at min-instances=0

### P2-2: Phase 2 CPU 4 → 2 (Conditional)

More I/O-bound than Phase 3/4 but higher variability (external API timeouts). Load-test at 2 CPU first.
**Concurrency also needs fixing:** Phase 2 has `--concurrency=10` but is Pub/Sub-triggered (1 message/request). Change to `--concurrency=1` (no cost impact, semantic correctness).
**Savings if safe:** ~$30/mo

### P2-3: Audit 116 Undocumented Scheduler Jobs

**Complete inventory from second pass:**
- Code defines 50 jobs; GCP has 167
- High-confidence stale categories: BDL jobs (7+), `nba-phase1-scrapers` jobs (10-15), old `phase-v1` endpoint jobs, `nba-reference-service` jobs (service may not exist)
- Some GCP jobs NOT in code: `same-day-phase3`, `same-day-phase4`, `live-export-*`, `morning-summary`, `grading-coverage-check`, fallback triggers

**Approach:**
```bash
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform \
  --format="table(name,schedule,httpTarget.uri,state)" | sort > /tmp/all-jobs.txt
# Cross-reference against 50 documented jobs
# Delete: targets dead services, disabled>90 days, contains test/dev/staging
# Keep: enabled and active, in version control
```

**Savings:** ~$5-10/mo

---

## Structural Prevention

### PREV-1: Fix Terraform Remote State Backend (Critical Risk)

Terraform state is **local only** — no `backend.tf` exists. If the developer's machine is lost, Terraform thinks all managed resources don't exist and `terraform apply` would try to recreate them.

```hcl
# Create infra/backend.tf
terraform {
  backend "gcs" {
    bucket = "nba-props-platform-terraform-state"
    prefix = "infra"
  }
}
```

```bash
# Create state bucket first
gsutil mb -p nba-props-platform -l us-west2 gs://nba-props-platform-terraform-state
gsutil versioning set on gs://nba-props-platform-terraform-state
# Then migrate local state: terraform init -migrate-state
```

**Cost:** ~$0.01/mo (negligible). **Risk prevented:** Catastrophic infra loss.

### PREV-2: Tiered Budget Alerts

Add alerts at $200, $300, $400, $600, $800 in GCP Console → Billing → Budgets. Currently no fine-grained alerts between $150 baseline and $994 spike.

### PREV-3: Canary Query Budget Enforcement

Add pre-commit hook that validates total bytes-scanned estimate for any new canary check:
```python
MAX_BYTES_SCANNED_PER_RUN = 500 * 1024 * 1024  # 500 MB hard limit
```

### PREV-4: Artifact Registry Weekly Auto-Cleanup

Schedule weekly cleanup via Cloud Scheduler (Sunday 11 PM) to prevent AR from regrowing to 111 GB after manual pruning.

### PREV-5: Scheduler Job Governance in CI

All scheduler jobs must be in version control. Add CI check comparing GCP job count against `deployment/scheduler/` configs.

### PREV-6: Cost Attribution Tags

Apply labels to all Cloud Run services: `billing_service={nba,mlb}`, `environment={production,staging,dev}`.

---

## `infinite-case` Backend — Decision Required

**Cost:** $115/mo (16 GiB / 4 CPU, min-instances=1, 84 revisions, actively developed)

| Option | Savings | Trade-off |
|--------|---------|-----------|
| **Recommended: Downsize to 4Gi/2CPU** | ~$57/mo | Still always-warm, no cold-start |
| Set min-instances=0 | $115/mo | ~5-10s cold start |
| Keep as-is | $0 | |

---

## BigQuery Slot Commitment Analysis

**On-demand pricing at current volume:** ~$65/mo (after 1TB free tier)
**Monthly slot commitment (100 slots):** $2,000/mo

**Verdict: Stay on on-demand. Slot commitment would be 31x more expensive at current volume.** Would only break even at 320+ TB/month scanned.

---

## Revised Expected Post-Fix Bill

| Category | Now | After P0 | After P0+P1 | After All |
|----------|-----|----------|-------------|-----------|
| Cloud Run (NBA) | $364 | ~$334 | ~$242 | ~$210 |
| Cloud Run (MLB) | ~$4 | ~$4 | ~$4 | ~$4 |
| BigQuery | $179 | ~$179 | ~$94 | ~$80 |
| Cloud Logging | $68 | ~$33 | ~$25 | ~$20 |
| Cloud Functions | $59 | $59 | $59 | ~$46 |
| Artifact Registry | $24 | $24 | ~$11 | ~$11 |
| Cloud Scheduler | $16 | ~$15 | ~$15 | ~$8 |
| Cloud Build | $22 | $22 | $22 | $22 |
| Cloud Storage | $26 | $26 | $26 | $26 |
| infinite-case (downsized) | $115 | $115 | $58 | $58 |
| Other | ~$18 | ~$18 | ~$18 | ~$15 |
| **Total** | **~$994** | **~$875** | **~$574** | **~$500** |

*(Phase 3 CPU savings not in P0 — needs 2-week monitoring window)*

---

## Implementation Order (Final — 3 Days)

```
DAY 1 MORNING (~2 hours):
  1. [5 min]  gcloud describe phase3/4/coordinator/worker: verify actual min-instances & CPU
  2. [5 min]  Phase 4 CPU → 2 (after verifying config)
  3. [30 min] Tiered canary: add routine 60-min job + remove duplicate check #11
  4. [30 min] Delete nba-phase1-scrapers + BDL scheduler jobs (find first)
  5. [30 min] Create infra/cloud_logging.tf + terraform apply for 2 exclusion filters

DAY 1 AFTERNOON (~2 hours):
  6. [30 min] Read + add game_date filters to 4 publishing exporters (P1-1)
  7. [30 min] Phase 3 CPU → 2 + start 2-week monitoring window
  8. [30 min] MLB Phase 4 CPU → 2
  9. [30 min] AR cleanup script dry-run + review output
  10. [15 min] Downsize infinite-case to 4Gi/2CPU (if approved)

DAY 2 (~3 hours):
  11. [1 hr]  Create feature_store_health_hourly scheduled query + test
  12. [30 min] Canary rolling windows 7/14 → 3 days
  13. [30 min] AR cleanup --execute (after day 1 dry-run review)
  14. [30 min] Begin scheduler audit: export 167 jobs, classify stale vs active
  15. [30 min] Audit + delete dev/staging services

DAY 3 (prevention + governance):
  16. [30 min] Create infra/backend.tf + migrate Terraform state to GCS
  17. [30 min] Add tiered budget alerts ($200/$300/$400/$600/$800)
  18. [30 min] Add billing labels to Cloud Run services
  19. [30 min] Add canary query budget pre-commit check
  20. [30 min] Schedule weekly AR cleanup
  21. [30 min] Complete scheduler audit deletions (stale jobs confirmed on Day 2)
```

---

## Key Reference Data

| Resource | Detail |
|----------|--------|
| Billing table | `nba-props-platform.billing_export.gcp_billing_export_resource_v1_01169A_2CADBE_978AC6` |
| Canary scheduler | `nba-pipeline-canary-trigger` (us-west2) |
| Phase 3 service | `nba-phase3-analytics-processors` (8Gi/4CPU → 8Gi/2CPU) |
| Phase 4 service | `nba-phase4-precompute-processors` (8Gi/4CPU → 8Gi/2CPU) |
| MLB Phase 4 | `mlb-phase4-precompute-processors` (min-instances=0 confirmed, 4CPU → 2CPU) |
| AR repo | `us-west2-docker.pkg.dev/nba-props-platform/nba-props` (111 GB) |
| Logging | Must go in `infra/cloud_logging.tf` (no file exists yet) |
| Terraform state | Local only — needs `infra/backend.tf` + GCS migration |
| Orchestrators | min-instances=1 intentional (commit a18d88f3, Feb 23) — do NOT change |
| BQ unfiltered exporters | `data_processors/publishing/player_profile_exporter.py:181`, `best_bets_exporter.py`, `results_exporter.py`, `trends_tonight_exporter.py` |
| Scheduler gap | 50 in code vs 167 in GCP — audit BDL/phase1/phase-v1 stale jobs first |

---

## Session History

- **Session 225 (2026-02-12):** First cost audit at $200/mo. Brought to ~$150.
- **Session 492 (2026-03-26):** BQ MERGE/partition fixes.
- **Session 509 (2026-04-02):** This audit. $994/mo from MLB launch + canary regression + uncontrolled AR growth. 21 agents across 3 rounds of investigation. v3 plan with all code-level evidence.
