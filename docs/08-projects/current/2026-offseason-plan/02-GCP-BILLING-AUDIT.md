# GCP Billing Audit — 2026 Off-Season
**Compiled:** 2026-04-25
**Billing account:** `01169A-2CADBE-978AC6` (Firebase Payment)
**30-day window:** 2026-03-26 → 2026-04-25
**Baseline 30-day total (before Apr 24 fixes):** ~$872/mo
**Projected after Apr 24 fixes:** ~$640-660/mo

---

## Apr 24 Fixes Applied This Session

| Fix | Savings/mo | Status |
|-----|-----------|--------|
| `infinitecase-backend`: 4CPU/16Gi → 2CPU/4Gi | ~$184 | ✅ Deployed (revision 00143-xpj) |
| `prediction-worker`: min=1 → min=0 | ~$30 | ✅ Deployed (revision 00493-6cx) |
| Cloud Logging exclusions (3) restored | ~$15-40 | ✅ Active via REST API |

These fixes do not appear in the 30-day historical numbers below — costs are still pre-fix.

---

## Full Cost Breakdown by Project

### 1. `infinite-case` — **$337/mo** ← HIGHEST COST PROJECT

| SKU | 30-day cost | Notes |
|-----|-------------|-------|
| Cloud Run CPU (instance-based) | $227 | 4CPU, cpu-throttling=OFF |
| Cloud Run Memory (instance-based) | $101 | 16Gi, cpu-throttling=OFF |
| Cloud SQL PostgreSQL micro | $9 | `infinitecase-backend` database |
| Cloud SQL storage | $2 | Standard storage |

**Verdict: PARTIALLY FIXED.** The Apr 24 fix (4CPU→2CPU, 16Gi→4Gi) will cut Cloud Run to ~$150/mo — saving ~$184/mo. Remaining concern: `cpu-throttling=false` (instance-based billing) means you still pay for CPU 24/7 regardless of traffic. If the app can tolerate the CPU being throttled when idle, switching to `cpu-throttling=true` would save another ~$100/mo.

---

### 2. `nba-props-platform` — **$483/mo**

#### 2a. Cloud Run Services — $236/mo

| Service | 30-day CPU | 30-day Mem | Total | Verdict |
|---------|-----------|-----------|-------|---------|
| `nba-phase3-analytics-processors` | $48.80 | $3.30 | **$52** | JUSTIFIED — runs 10-13×/day (6 Pub/Sub sources + 7 schedulers). 2CPU/2Gi after Session 509 downscale. |
| `nba-phase4-precompute-processors` | $38.39 | $3.11 | **$42** | JUSTIFIED — runs after Phase 3 daily. 2CPU/2Gi. |
| `prediction-coordinator` (min=1) | $18.23 warmup + $0.67 exec | $18.23 warmup | **$37** | JUSTIFIED — min=1 mandated by Feb 23 cold-start incident (42+ Pub/Sub failures). Cannot reduce without fixing Pub/Sub ACK deadline first. |
| `prediction-worker` (min=1→0) | $9.93 warmup + $4.49 exec | $19.87 warmup + $0.84 exec | **$35** | FIXED Apr 24. Worker is called by coordinator (not Pub/Sub). ~$30 in warmup was avoidable. Execution ~$5 remains. |
| `mlb-phase2-raw-processors` | $14.42 | $3.00 | **$17** | QUESTIONABLE — $17/mo for an event-driven phase 2 processor is high. Needs investigation: how many triggers/day? Why CPU Tier 2? |
| `nba-phase2-raw-processors` | $12.45 | $2.32 | **$15** | QUESTIONABLE — same concern as MLB Phase 2. |
| `nba-scrapers` | $6.82 | $0.71 | **$8** | JUSTIFIED — runs multiple scrapers daily (40+ scrapers). |
| `mlb-phase4-precompute-processors` | $2.19 | $0.90 | **$3** | JUSTIFIED — low cost, MLB precompute runs daily. |
| `mlb-phase1-scrapers` | $1.66 | — | **$2** | JUSTIFIED — MLB scrapers run daily. |
| `mlb-phase3-analytics-processors` | $0.51 | — | **$1** | JUSTIFIED — low cost. |

#### 2b. Cloud Run Jobs — $25/mo

| Job | 30-day cost | Verdict |
|-----|-------------|---------|
| `nba-pipeline-canary` | $15 ($14 CPU + $1 mem) | QUESTIONABLE — runs every 15 min (critical) and 60 min (routine) even during offseason. Could pause most checks during NBA offseason. |
| `nba-auto-batch-cleanup` | $3 | JUSTIFIED — cleanup job, runs daily. |
| `mlb-stall-detector` | $2 | JUSTIFIED — MLB in-season monitoring. |
| `nba-monitor-feature-staleness` | $1 | JUSTIFIED — low cost. |
| `mlb-freshness-checker` | $1 | JUSTIFIED — low cost. |

#### 2c. Cloud Functions — $54/mo

| Function | 30-day cost | Verdict |
|---------|-------------|---------|
| `phase3-to-phase4-orchestrator` (min=1) | $14 | JUSTIFIED — min=1 mandatory. |
| `phase4-to-phase5-orchestrator` (min=1) | $14 | JUSTIFIED — min=1 mandatory. |
| `phase5-to-phase6-orchestrator` (min=1) | $14 | JUSTIFIED — min=1 mandatory. |
| `phase6-export` (execution) | $3 | JUSTIFIED — runs after predictions. |
| `auto-retry-processor` | $2 | QUESTIONABLE — what is triggering this Gen2 CF so frequently? |
| `live-export` | $2 | JUSTIFIED — live game export. |
| `live-freshness-monitor` | $1 | JUSTIFIED. |
| `news-fetcher` (Gen1!) | $1 | SUSPICIOUS — **Gen1 CF still running**. Should be migrated or deleted. |
| Others | ~$4 | Various small CFs. |

#### 2d. BigQuery — $77/mo

| SKU | 30-day cost | Verdict |
|-----|-------------|---------|
| Analysis (us-west2) | $77 | PARTIALLY JUSTIFIED — Sessions 509-511 fixed several unfiltered scans. Still $77/mo suggests more unfiltered queries remain. Canary is the likely culprit: even tiered to 15/60 min, it runs 12 critical checks every 15 min = 1,152 checks/day. |

Note: $77/mo = ~12 TB scanned/month at $6.25/TB. That's ~400 GB/day.

#### 2e. Cloud Storage — $33/mo ← BIGGEST SURPRISE

| Bucket | 30-day cost | SKU | Operations/mo | Verdict |
|--------|------------|-----|--------------|---------|
| `nba-bigquery-backups` | **$20** | Multi-Region Coldline Class A | 507,459 | **SUSPICIOUS** — 507K write ops to Coldline backup bucket. Something is backing up to GCS ~17K times/day. At $0.04/10K ops multiregion, that's 507K × $0.04/10K = **$20.30**. Who/what is writing this often? |
| `nba-bigquery-backups` | **$11** | Multi-Region Nearline Class A | 536,519 | **SUSPICIOUS** — Same bucket, Nearline tier. 536K write ops. Combined with Coldline: >1M operations/month. |
| `nba-props-platform-api` | $0.65 | Regional Standard Class A | 133K | JUSTIFIED — daily JSON exports (picks, models, signals). |
| `nba-scraped-data` | $0.90 | Regional Standard Class A/B | 112K/920K | JUSTIFIED — scraper JSON output, Phase 2 reads. |

**Total GCS: $33/mo, of which $31 is the BigQuery backup bucket.** This needs urgent investigation. Either: (a) a BigQuery export CF is running far too frequently, or (b) the bucket storage class is wrong and should be Standard for frequently-written files. A `bigquery-backup` Cloud Run service exists — likely the culprit.

#### 2f. Artifact Registry — $19/mo

| Repo | Size | 30-day cost | Verdict |
|------|------|-------------|---------|
| `nba-props` | 56 GB | ~$11 | REDUCIBLE — AR cleanup runs weekly (Sundays) but repo keeps growing. Every Cloud Build push adds new images. Need stricter lifecycle policy (keep latest 3 per service, not just by date). |
| `cloud-run-source-deploy` | 17 GB | ~$3 | REDUCIBLE — Auto-managed by `gcloud run deploy --source`. Has no lifecycle policy. |
| `gcf-artifacts` | 15 GB | ~$3 | REDUCIBLE — Auto-managed by Cloud Functions deploys. |
| Others | ~5 GB | ~$2 | mlb-monitoring, mlb-validators, pipeline. |

AR cleanup ran Apr 12 (3 executions), yet repos are still large. The `cloud-run-source-deploy` and `gcf-artifacts` repos are not touched by the cleanup script.

#### 2g. Cloud Scheduler — $17/mo

- **182 jobs** in GCP (us-central1) vs ~50 jobs defined in code.
- **132 stale jobs** costing $13.20/mo in scheduler billing alone.
- Sources of stale jobs: BDL scrapers (disabled), `nba-phase1-scrapers` (deleted service), old phase-v1 endpoints, duplicate/test jobs.
- $16.99/mo billing shows these are all being invoked (or at minimum billed by existence).

#### 2h. Cloud Logging — $16/mo

- $15.72 log storage cost.
- 3 exclusion filters restored Apr 24 (health checks, heartbeats, monitoring info).
- Was $68/mo before Session 510. Currently lower due to offseason activity.
- Expect to rise back to $30-50/mo once NBA season resumes (October).

#### 2i. Cloud Build — $6/mo

- 7 NBA Cloud Run services auto-deploy on push to main.
- Justified — the cost per deploy is reasonable.

---

### 3. `urcwest` — **$28/mo** (separate Firebase app)

| Item | 30-day cost | Notes |
|------|-------------|-------|
| Cloud Functions min-instance CPU | $21 | Firebase functions with min-instances=1 |
| Cloud Functions min-instance Memory | $5 | Same |
| Cloud Functions execution | $1 | — |
| Cloud Scheduler | $2 | — |
| Secret Manager | $1 | — |

**Not our NBA system.** Firebase/urcwest app. Cloud Functions with min-instances are costing $26/mo in warmup. If any of these functions can run without min-instances, that would save money.

---

### 4. `memberradar-prod` — **$14/mo** (separate app)

| Item | 30-day cost | Notes |
|------|-------------|-------|
| Cloud SQL PostgreSQL micro | $9 | Database |
| Cloud SQL storage | $2 | — |
| Cloud Build | $2 | — |
| Artifact Registry | $1 | — |
| Secret Manager | $0.3 | — |

**Not our NBA system.** Separate application. Is this still in use? Cloud SQL micro at $9/mo suggests a small DB that's always on.

---

## Summary — Justified vs Reducible

| Category | Monthly Cost | Justified? | Potential Savings |
|----------|-------------|-----------|------------------|
| NBA Phase 3 processor | $52 | ✅ Yes | — |
| NBA Phase 4 processor | $42 | ✅ Yes | — |
| prediction-coordinator warmup | $37 | ✅ Yes (cold-start issue) | $35 if Pub/Sub ACK fixed |
| 3 orchestrator CFs warmup | $42 | ✅ Yes (same reason) | — |
| NBA Phase 2 processors | $32 | ⚠️ Questionable | ~$20? Needs investigation |
| BigQuery analysis | $77 | ⚠️ Partial | Unknown — more unfiltered scans? |
| `nba-bigquery-backups` GCS | $31 | ❌ Suspicious | ~$20-30 (reduce frequency or change storage class) |
| AR (nba-props + auto-repos) | $19 | ⚠️ Partial | ~$10 with better lifecycle policy |
| Cloud Scheduler stale jobs | $17 | ❌ Reducible | ~$13 (delete 132 stale jobs) |
| `nba-pipeline-canary` (job) | $15 | ⚠️ Partial | ~$8 during offseason |
| Cloud Logging | $16 | ✅ Improving | Exclusions restored |
| `infinite-case` Cloud Run | $328 | ⚠️ Fixed Apr 24 | ~$184 already saved |
| prediction-worker warmup | $30 | ❌ Fixed Apr 24 | ~$30 already saved |
| `urcwest` CFs warmup | $26 | ⚠️ Separate app | ~$20 if min→0 |
| SQL (infinite-case + memberradar) | $22 | ⚠️ Separate apps | ~$22 if not needed |
| Other (CFs, scrapers, build, etc.) | ~$30 | ✅ Mostly | — |

**30-day total (pre-fix): ~$872/mo**
**After Apr 24 fixes: ~$658/mo**
**Additional reducible (agents to study): ~$90-120/mo**
**Realistic target: ~$540-570/mo**

---

## Questions for Agent Investigation

### Q1 — `nba-bigquery-backups` bucket (Priority: HIGH, saves ~$20-30/mo)
- What is the `bigquery-backup` Cloud Run service doing?
- What is it writing to `nba-bigquery-backups`? How frequently?
- Why does the bucket have both Coldline AND Nearline prefixes (suggesting mixed storage classes)?
- Fix options: reduce export frequency, change storage class to Standard, or delete if backups aren't being restored.
- **File:** look for `bigquery-backup` scheduler, CF, or Cloud Run job config.

### Q2 — Phase 2 processors $32/mo (Priority: MEDIUM, saves ~$15-20/mo)
- `mlb-phase2-raw-processors` ($17/mo) and `nba-phase2-raw-processors` ($15/mo) are event-driven but expensive.
- How many Pub/Sub triggers per day are they receiving?
- Are they receiving Phase 3 triggers they shouldn't be (or vice versa)?
- Do they need 1CPU/2Gi or can they be downsized?

### Q3 — Cloud Scheduler 132 stale jobs (Priority: MEDIUM, saves ~$13/mo)
- Export all 182 scheduler jobs from GCP.
- Cross-reference against `deployment/scheduler/` YAML files in the repo.
- Identify and delete stale jobs (BDL, nba-phase1-scrapers, old URLs, duplicates, test jobs).

### Q4 — BigQuery $77/mo (Priority: MEDIUM, saves unknown)
- Are the Session 509-511 partition filters all still in place?
- What are the top queries by bytes scanned in the last 7 days?
- Is the tiered canary (15min critical / 60min routine) working as intended?
- Check `INFORMATION_SCHEMA.JOBS` for high-scan queries.

### Q5 — `auto-retry-processor` $2/mo (Priority: LOW)
- What triggers this Gen2 CF and how often?
- Is it still needed?

### Q6 — `news-fetcher` Gen1 CF $1/mo (Priority: LOW)
- This is a Gen1 Cloud Function (deprecated). Should be deleted or migrated.
- Likely orphaned from an older feature.

### Q7 — `urcwest` CF min-instances $26/mo (Priority: LOW, separate project)
- Which specific Firebase functions have min-instances set?
- Can any be set to min=0 without impacting cold-start UX?

### Q8 — `infinite-case` `cpu-throttling=false` (Priority: MEDIUM, saves ~$100/mo)
- After the 2CPU/4Gi downscale (already done), this is the next lever.
- cpu-throttling=true would cut CPU billing by ~65% (only billed during requests).
- Risk: latency on first request after idle period. Is this acceptable for the app?
