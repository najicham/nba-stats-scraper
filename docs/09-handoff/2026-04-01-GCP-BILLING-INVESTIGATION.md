# GCP Billing Investigation — $950/Month Alert
**Date:** April 1, 2026
**Context:** User received email alert showing ~$950 billing for the current month (March/April 2026). Previous baseline was ~$140-160/mo. This is a ~$800 spike that needs investigation.

---

## Your Mission

Find exactly where the $950 is coming from across all GCP projects and provide prioritized recommendations to cut costs without breaking the NBA/MLB prediction system.

---

## GCP Account Overview

**Billing Accounts:**
- `01169A-2CADBE-978AC6` — "Firebase Payment" — **OPEN (active)**
- `0186FA-8777DE-2487B8` — "My Billing Account" — **CLOSED** (check if anything is still billing here)

**All Projects on this account:**

| Project ID | Name | Notes |
|------------|------|-------|
| `nba-props-platform` | NBA Props Platform | Main active project — 91 Cloud Run services |
| `props-platform-web` | Props Platform Web | Frontend for playerprops.io |
| `memberradar-prod` | MemberRadar | Unknown activity level |
| `infinite-case` | Infinite Case | Unknown activity level |
| `infinite-case-d09b5` | infinite-case | Duplicate? Unknown |
| `recipe-platform-25` | Recipe Platform | Unknown activity level |
| `shipping-insights-25` | Shipping Stats | Unknown activity level |
| `testing-479218` | Testing | Should be idle |
| `gen-lang-client-0866788294` | Default Gemini Project | Could have AI API costs |
| `urcwest` | urcwest | Unknown |

**Start here — pull itemized costs per project:**
```bash
# Costs by project this month
gcloud billing accounts list
# Then use the billing console or BigQuery billing export to get per-project breakdown
# If billing export is enabled:
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT project.id as project_id, service.description as service,
  ROUND(SUM(cost), 2) as total_cost
FROM \`nba-props-platform.billing_export.gcp_billing_export_v1_*\`
WHERE DATE(_PARTITIONTIME) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY 1,2 ORDER BY 3 DESC
LIMIT 50"
```

If no billing export table, check:
```bash
bq ls --project_id=nba-props-platform 2>/dev/null | grep billing
```

---

## Known Baseline (Session 492, ~March 2026)

Before the MLB system was deployed, monthly costs were approximately:
- **BigQuery:** ~$120/mo (dominant cost — 40+ scrapers, ML training, analytics)
- **Cloud Run:** ~$22/mo (always-on services)
- **Cloud Storage:** ~$5/mo
- **Pub/Sub + misc:** ~$5/mo
- **Total: ~$150/mo**

The NBA system alone should be ~$150/mo. The $950 represents **~$800 in new/unexpected costs**.

---

## Highest-Suspect Cost Drivers (Investigate These First)

### 🔴 SUSPECT #1: MLB Services (Deployed March 2026 — NEW)

The MLB prediction system was launched in Sessions 444-501. These services were added after the last billing audit:

| Service | Memory | CPU | Notes |
|---------|--------|-----|-------|
| `mlb-phase4-precompute-processors` | **8Gi** | **4 CPU** | **Extremely expensive if always-on** |
| `mlb-phase3-analytics-processors` | 4Gi | 2 CPU | Significant |
| `mlb-prediction-worker` | 2Gi | 2 CPU | **Deployed in TWO regions** (us-west2 + us-central1) |
| `mlb-phase1-scrapers` | 2Gi | 2 CPU | |
| `mlb-phase2-raw-processors` | 2Gi | 1 CPU | |
| `mlb-phase6-grading` | 2Gi | 1 CPU | |
| `mlb-alert-forwarder` | 256Mi | 0.17 CPU | |

**Check if these have min instances set:**
```bash
for svc in mlb-phase4-precompute-processors mlb-phase3-analytics-processors mlb-prediction-worker mlb-phase1-scrapers mlb-phase2-raw-processors mlb-phase6-grading; do
  echo -n "$svc: "
  gcloud run services describe $svc --region=us-west2 --project=nba-props-platform \
    --format="value(spec.template.metadata.annotations.'autoscaling.knative.dev/minScale')" 2>/dev/null
done
```

**Also check the second region for mlb-prediction-worker:**
```bash
gcloud run services list --project=nba-props-platform --regions=us-central1 2>/dev/null
```

### 🔴 SUSPECT #2: 91 Cloud Run Services (vs ~40 before MLB)

The project has **91 Cloud Run services** — this is roughly double what the billing audit saw. Even at scale-to-zero, each service has idle costs for image storage, revision metadata, and minimum memory allocation.

**Always-on services (min-instances=1, billing 24/7):**
```
phase3-to-phase4-orchestrator  — 1Gi / 0.58 CPU  (always on)
phase4-to-phase5-orchestrator  — 1Gi / 0.58 CPU  (always on)
phase5-to-phase6-orchestrator  — 1Gi / 0.58 CPU  (always on)
prediction-coordinator         — 2Gi / 2 CPU     (always on) ← EXPENSIVE
prediction-worker              — 2Gi / 1 CPU     (always on) ← EXPENSIVE
```

The `prediction-coordinator` (2Gi/2CPU) and `prediction-worker` (2Gi/1CPU) running 24/7 = significant cost.

**Check all services with min instances:**
```bash
gcloud run services list --project=nba-props-platform \
  --format="table(metadata.name,spec.template.spec.containers[0].resources.limits.memory,spec.template.spec.containers[0].resources.limits.cpu,spec.template.metadata.annotations.'autoscaling.knative.dev/minScale')" \
  2>/dev/null | grep -v "^NAME"
```

### 🟡 SUSPECT #3: Duplicate/Stale Services

Several services appear to be duplicates or superseded:

| Service | Issue |
|---------|-------|
| `nba-phase1-scrapers` | Legacy name — superseded by `nba-scrapers`. Should be deleted. |
| `prediction-coordinator-dev` | Dev environment — should be idle or deleted |
| `self-heal-check-staging` | Staging service — may be unnecessary |
| `phase2-to-phase3-staging`, `phase3-to-phase4-staging` | Staging environments — needed? |
| `box-score-completeness-alert` | Deployed in `uw` (us-west1?) — different region, extra cost |
| `upcoming-tables-cleanup` | Deployed in `ue` (us-east?) — different region |
| `nba-scrapers` appears **twice** — two different regions |

**List stale/duplicate services:**
```bash
gcloud run services list --project=nba-props-platform \
  --format="value(metadata.name,metadata.namespace)" 2>/dev/null | sort | uniq -d
```

### 🟡 SUSPECT #4: BigQuery — Unpartitioned Queries / ML Training

The BQ cost could have spiked due to:
1. **Model training:** `weekly-retrain` CF at 4Gi/2CPU scans large training datasets weekly
2. **Unpartitioned queries:** 40+ scrapers writing to raw tables, analytics queries
3. **New MLB BQ tables:** MLB pipeline adds new raw/analytics datasets

**Check BQ usage this month:**
```bash
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT
  user_email,
  ROUND(SUM(total_bytes_processed) / POW(10,12), 3) as tb_processed,
  ROUND(SUM(total_bytes_processed) / POW(10,12) * 6.25, 2) as estimated_cost_usd,
  COUNT(*) as query_count
FROM \`region-us-west2\`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND statement_type != 'SCRIPT'
GROUP BY 1 ORDER BY 2 DESC
LIMIT 20"
```

```bash
# Top queries by bytes scanned
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT
  SUBSTR(query, 1, 100) as query_snippet,
  ROUND(total_bytes_processed / POW(10,9), 1) as gb_scanned,
  creation_time,
  job_id
FROM \`region-us-west2\`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND total_bytes_processed > 10000000000
ORDER BY total_bytes_processed DESC
LIMIT 20"
```

### 🟡 SUSPECT #5: Other Projects

Other projects on the account haven't been audited. Check each:

```bash
for project in props-platform-web memberradar-prod infinite-case recipe-platform-25 shipping-insights-25 testing-479218; do
  echo "=== $project ==="
  gcloud run services list --project=$project --format="value(metadata.name)" 2>/dev/null | wc -l
  echo "services"
done
```

```bash
# Check if any other projects have always-on Cloud Run
for project in props-platform-web memberradar-prod infinite-case recipe-platform-25; do
  echo "=== $project ==="
  gcloud run services list --project=$project \
    --format="table(metadata.name,spec.template.metadata.annotations.'autoscaling.knative.dev/minScale')" 2>/dev/null \
    | grep -v "^NAME" | grep -v "^$"
done
```

---

## Key Commands for Full Cost Breakdown

### If Cloud Billing Export is Available
```bash
# Full cost breakdown by service and SKU (last 30 days)
bq query --project_id=nba-props-platform --use_legacy_sql=false "
SELECT
  project.id,
  service.description,
  sku.description,
  ROUND(SUM(cost), 2) as cost_usd,
  ROUND(SUM(cost) * 100 / SUM(SUM(cost)) OVER(), 1) as pct_of_total
FROM \`nba-props-platform.billing_export.gcp_billing_export_v1_*\`
WHERE DATE(_PARTITIONTIME) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY 1,2,3
ORDER BY 4 DESC
LIMIT 30"
```

### Cloud Monitoring — Cloud Run request counts
```bash
# Check which services are actually receiving traffic
gcloud monitoring metrics list --filter="metric.type=run.googleapis.com/request_count" \
  --project=nba-props-platform 2>/dev/null | head -20
```

### Check Container Registry / Artifact Registry storage
```bash
# 91 services = 91 Docker images = significant storage cost
gcloud artifacts repositories list --project=nba-props-platform 2>/dev/null
gsutil du -sh gs://artifacts.nba-props-platform.appspot.com 2>/dev/null
```

---

## Quick Wins to Investigate

| Action | Estimated Savings | Risk |
|--------|-----------------|------|
| Delete `nba-phase1-scrapers` (legacy, replaced by `nba-scrapers`) | ~$2-5/mo | Low |
| Delete `prediction-coordinator-dev` | ~$5-10/mo | Low |
| Delete staging services (3-4 unused) | ~$5/mo | Low |
| Set `mlb-phase4-precompute-processors` to min-instances=0 | ~$50-100/mo | Low (job-based) |
| Reduce `mlb-prediction-worker` to 1 region | ~$20-30/mo | Low |
| Check if `nba-phase1-scrapers` is still receiving traffic | Depends | Medium |
| Audit BQ unpartitioned queries | ~$50-200/mo | Medium |
| Delete stale Docker image tags in Artifact Registry | ~$10-20/mo | Low |

---

## System Context for Safe Deletions

The NBA prediction system (`nba-props-platform`) is a live production system that makes real NBA player prop predictions. **Do NOT delete or modify these core services without confirming they're truly inactive:**

- `prediction-worker`, `prediction-coordinator` — Phase 5, always-on intentionally
- `nba-scrapers`, `nba-phase2-raw-processors` through `nba-phase4-precompute-processors` — daily pipeline
- `nba-grading-service` — grades past predictions
- `phase6-export` — publishes picks to playerprops.io frontend
- Any `mlb-*` service — MLB season started March 2026, system is live

**Safe to investigate for deletion:**
- Services with "staging", "dev", "test" in name
- `nba-phase1-scrapers` (confirmed legacy in code — `CLAUDE.md` notes it was renamed to `nba-scrapers`)
- Services not touched in 30+ days (check `gcloud run revisions list`)

---

## Context from Prior Session (Session 492, ~March 26, 2026)

A prior billing audit (Session 492) identified and fixed 3 BQ cost issues:
- BQ MERGE statements scanning full tables instead of using partition filters
- Commit `77095d94` deployed March 26 — fixed these

The MLB system was deployed AFTER that audit (Sessions 496-508, March 28 - April 1). The MLB pipeline adds significant compute:
- 6 new Cloud Run services
- New BQ datasets: `mlb_raw`, `mlb_analytics`, `mlb_predictions`
- `mlb-prediction-worker` running in 2 regions (us-west2 + us-central1)

This timing strongly suggests **MLB deployment is the primary cost driver for the spike**.
