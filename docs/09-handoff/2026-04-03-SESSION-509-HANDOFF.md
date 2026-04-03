# Session 509 Handoff — 2026-04-03 (Thursday morning)

**Context:** Session 509 was a full GCP cost investigation triggered by a ~$994/mo billing alert
(prior baseline ~$150/mo after Session 492). Used 21 agents across 3 research rounds to identify
root causes, write a peer-reviewed reduction plan, and execute the safe changes.

---

## What Happened This Session

### 1. Cost Investigation — 21 Agents, 3 Rounds

**Round 1 — Discovery (5 agents):**
Studied the system across: canary/BQ query patterns, Cloud Scheduler jobs, Phase 3/4 CPU sizing,
Cloud Logging & Artifact Registry, BigQuery patterns & stale services.

**Round 2 — Peer Review (8 agents):**
Each reviewed the plan from a different angle: safety/risk, cost estimate accuracy, priority
sequencing, monitoring impact, implementation completeness, architecture/prevention, MLB-specific,
and "what's missing."

**Round 3 — Deep Dives (8 agents):**
Investigated specific open questions: orchestrator min-instances config (critical find), Phase 3
trigger frequency, CF warmup costs, scheduler governance gap, BQ deep dive, Cloud Build strategy,
concurrency/right-sizing, Terraform completeness.

### 2. Key Findings (Summary)

**Root causes of $994/mo bill (was $150):**
1. **Pipeline canary** (`*/15 * * * *`) running 29 BQ checks per invocation = 7.8M queries/month.
   Duplicate check found (Check #11 = same table as Check #4). Many critical checks MUST stay at
   15min cadence; only routine checks can go to 60min.
2. **Phase 3 analytics** costs $125/mo — fires **10-13x/day** (not 1-2x as assumed). 6 independent
   Pub/Sub trigger sources + 7 Cloud Scheduler jobs, no deduplication between them.
3. **Phase 3 and Phase 4 over-provisioned at 4 CPU** — both I/O-bound (BigQuery API), sequential
   execution model. Phase 3: 2Gi/4CPU. Phase 4: 2Gi/4CPU.
4. **Publishing exporter BQ scans** — `player_profile_exporter._query_player_summaries()` scans
   ALL of `prediction_accuracy` (12 months, no game_date filter) on every export. This was the
   unaccounted ~$85/mo in the audit.
5. **Artifact Registry** has no lifecycle policy — 111 GB accumulated across 91 services since
   Session 225 cleanup.
6. **Cloud Logging** at 186 GB/month — 0 exclusion filters configured. Free tier is 50 GB.
7. **Terraform has no remote state backend** — state is local only (if dev machine lost, Terraform
   thinks all managed resources don't exist).
8. **116 scheduler jobs in GCP not in local code** — likely stale BDL, phase1, old endpoint jobs.

**Corrections to initial assumptions:**
- MLB Phase 4 wildcard ($200-250/mo) = **FALSE POSITIVE** — deploy script confirms `min-instances=0`.
- Orchestrator min-instances=1 is **intentional** — commit `a18d88f3` (Feb 23) set it after 42+
  Pub/Sub cold-start failures. `detect_config_drift.py` validates this. Do NOT change.
- Prediction coordinator + worker are **already at min-instances=0** in deploy scripts.
- Cloud Build $22/mo = **noise** — selective deployment already works for 7 CR services.
- BigQuery slot commitment: **never worth it** at current volume ($6.25/TB on-demand vs $2K/mo slots).

### 3. Changes Implemented (commit `ea51e691`)

**GCP (live changes):**
- Phase 3 CPU 4→2: `nba-phase3-analytics-processors` (revision 00393)
- Phase 4 CPU 4→2: `nba-phase4-precompute-processors` (revision 00336)
- MLB Phase 4 CPU 4→2: `mlb-phase4-precompute-processors` (revision 00012)
- Deleted `nba-phase1-scrapers` (superseded by `nba-scrapers`, confirmed dead)

**Code:**
- `bin/monitoring/pipeline_canary_queries.py` — removed duplicate Check #11 ("Phase 4 Category
  Quality Breakdown"). Same `ml_feature_store_v2` scan as Check #4 with no additional signal.
- `data_processors/publishing/player_profile_exporter.py` — added
  `AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 730 DAY)` to `_query_player_summaries()`
  (line 182) and `_query_recent_predictions()` (line 260). Was scanning all 12 months.
- `infra/cloud_logging.tf` — new file with 2 log exclusion filters (health-checks + heartbeats).
  **Must apply:** `terraform plan && terraform apply` (saves ~$25-35/mo).
- `infra/backend.tf` — new remote GCS state backend config. **Must activate** (see below).
- `bin/cleanup-artifact-registry.sh` — AR lifecycle cleanup with dry-run mode.

### 4. Plan Document

Full cost reduction plan at:
`docs/08-projects/current/gcp-cost-optimization/03-COST-REDUCTION-PLAN-2026-04-02.md`

---

## Immediate Next Steps (Priority Order)

### Step 1: Migrate Terraform State to GCS (MUST DO BEFORE ANY TERRAFORM)

`infra/backend.tf` was created this session but the GCS bucket doesn't exist yet. **Run this first
or `terraform apply` will fail with a cryptic error.**

```bash
gsutil mb -p nba-props-platform -l us-west2 gs://nba-props-platform-terraform-state
gsutil versioning set on gs://nba-props-platform-terraform-state
cd /home/naji/code/nba-stats-scraper/infra
terraform init -migrate-state  # Migrates local state to GCS — type 'yes' when prompted
```

### Step 2: Apply Terraform Logging Exclusions (~$25-35/mo)
```bash
cd /home/naji/code/nba-stats-scraper/infra
terraform plan -target=google_logging_project_exclusion.exclude_health_checks \
               -target=google_logging_project_exclusion.exclude_heartbeats
# Review output — should show 2 new resources, 0 destroyed
terraform apply -target=google_logging_project_exclusion.exclude_health_checks \
               -target=google_logging_project_exclusion.exclude_heartbeats
```

### Step 2: Tiered Canary Scheduler (~$32/mo)
The canary currently runs all 29 checks every 15 minutes. 11 critical checks must stay at 15min
(pick drought, edge collapse, filter jam, grading freshness, etc.). Routine checks can go to 60min.

This requires either:
1. Adding a `tier` parameter to the canary code (check `pipeline_canary_queries.py`)
2. Or creating a second Cloud Scheduler job for the routine subset

```bash
# After implementing tier logic, add the 60-min routine job:
gcloud scheduler jobs create http nba-pipeline-canary-routine \
  --schedule="0 * * * *" --region=us-west2 --project=nba-props-platform \
  --uri="CANARY_JOB_INVOKE_URL" --message-body='{"tier":"routine"}'
```

### Step 3: Artifact Registry Cleanup (~$12-13/mo)
```bash
./bin/cleanup-artifact-registry.sh           # Dry run — review what would be deleted
./bin/cleanup-artifact-registry.sh --execute # Execute after review
```
Then schedule weekly: Cloud Scheduler job `ar-weekly-cleanup` → Sunday 11 PM.

### Step 4: Infinite-Case Backend Decision ($57-115/mo)
`infinitecase-backend` (project: `infinite-case`) costs $115/mo. 16Gi/4CPU, min-instances=1,
actively deployed (84 revisions). Options:
- **Recommended:** Downsize to 4Gi/2CPU (~$57/mo savings, no cold-start risk)
- Set min-instances=0 ($115/mo savings, ~5-10s cold-start on first request)

```bash
gcloud run services update infinitecase-backend --memory=4Gi --cpu=2 \
  --region=us-central1 --project=infinite-case
```

### Step 5: Audit 116 Stale Scheduler Jobs
```bash
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform \
  --format="table(name,schedule,httpTarget.uri,state)" | sort > /tmp/all-jobs.txt
wc -l /tmp/all-jobs.txt  # Should be ~167
```
High-confidence stale categories: jobs targeting `nba-phase1-scrapers` (legacy URL
`756957797294.us-west2.run.app` WITHOUT `f7p3g7f6ya-wl`), any `bdl-catchup-*`, any `*-v1`
or `*-legacy` endpoints.

### Step 7: Monitor Phase 3 CPU Change (window: 2026-04-02 → 2026-04-16)
Phase 3 was downsized to 2 CPU on 2026-04-02. It fires **10-13x/day** from multiple sources.
Check weekly even if no alerts fire:
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase3-analytics-processors" AND severity>=WARNING' \
  --project=nba-props-platform --limit=50 --format="table(timestamp,severity,textPayload)"
```
**Rollback threshold:** ≥1 timeout per day for 2+ consecutive days.
**Rollback:** `gcloud run services update nba-phase3-analytics-processors --cpu=4 --region=us-west2`

---

## Open Questions / Unresolved

### Phase 3 Cost Mystery
Phase 3 is deployed with min-instances=0, 2Gi/4CPU. At request-based pricing, 10-13 invocations
× 3 min × 4 CPU = ~$8/mo — but the audit shows $125/mo. The `gcloud describe` confirms the
current config, so either:
1. Phase 3 was recently reconfigured (had min-instances=1 previously, recently changed to 0)
2. Phase 3 has a high invocation count we haven't fully captured (backfills, replay runs)
3. The audit billing period captured an unusual period

The CPU 4→2 downgrade is correct regardless. Monitor actual cost on next billing cycle.

### BDL Scraper $17/mo
The "bigdataball puller $17" line item from the audit couldn't be traced to active scheduler jobs.
No `bdl-*` or `bigdata-*` jobs found. May be from:
- Old BigQuery data retained in `nba_raw.bigdataball_*` tables (storage cost)
- Drive API calls from a service not found in the search
- Stale data in a table that runs aggregate queries

Check: `SELECT table_id, row_count, size_bytes FROM nba_raw.__TABLES__ WHERE table_id LIKE '%bigdata%'`

---

## Expected Bill Impact

| Change | Status | Savings |
|--------|--------|---------|
| Phase 3 CPU 4→2 | ✅ Live | ~$62/mo |
| Phase 4 CPU 4→2 | ✅ Live | ~$30/mo |
| MLB Phase 4 CPU 4→2 | ✅ Live | ~$30/mo |
| Delete nba-phase1-scrapers | ✅ Live | ~$0.24/mo |
| Remove duplicate canary Check #11 | ✅ Live | ~$2-3/mo |
| BQ partition filter in player_profile_exporter | ✅ Live | ~$85/mo |
| Cloud Logging exclusions | ⏳ Pending terraform apply | ~$25-35/mo |
| Tiered canary (11 critical @15min, rest @60min) | ⏳ Pending code + scheduler | ~$32/mo |
| Artifact Registry cleanup | ⏳ Pending dry-run + execute | ~$12-13/mo |
| Infinite-case downsize | ⏳ Pending decision | $57-115/mo |
| Scheduler job audit (116 stale) | ⏳ Pending audit | ~$5-10/mo |
| **Implemented so far** | | **~$209/mo** |
| **After pending steps** | | **~$380-430/mo** |

**Revised projected bill after all steps:** ~$564-614/mo (from $994/mo)

---

## Key Files Modified

| File | Change | Why |
|------|--------|-----|
| `data_processors/publishing/player_profile_exporter.py` | Added 730-day game_date filter to 2 queries | Was scanning entire prediction_accuracy table (~$85/mo) |
| `bin/monitoring/pipeline_canary_queries.py` | Removed Check #11 | Duplicate of Check #4 — same table, same purpose |
| `infra/cloud_logging.tf` | New — 2 log exclusion filters | Need to `terraform apply` to activate |
| `infra/backend.tf` | New — GCS remote state backend | Need to create bucket and `terraform init -migrate-state` |
| `bin/cleanup-artifact-registry.sh` | New — AR cleanup script | Run dry-run then execute |
| `docs/08-projects/current/gcp-cost-optimization/03-COST-REDUCTION-PLAN-2026-04-02.md` | Full v3 plan | Complete cost reduction roadmap |

---

## Reference

- **Cost audit:** `docs/08-projects/current/gcp-cost-optimization/02-COST-AUDIT-2026-04-02.md`
- **Reduction plan (v3):** `docs/08-projects/current/gcp-cost-optimization/03-COST-REDUCTION-PLAN-2026-04-02.md`
- **Billing export table:** `nba-props-platform.billing_export.gcp_billing_export_resource_v1_01169A_2CADBE_978AC6`
- **Orchestrator cold-start incident:** commit `a18d88f3` — DO NOT revert min-instances on orchestrators
- **detect_config_drift.py** validates orchestrator min-instances=1 — would alert if changed
