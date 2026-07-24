# GCP Cost Audit — Full Analysis

**Date:** 2026-07-21
**Scope:** All Google Cloud spend across every project and billing account associated with `nchammas@gmail.com`
**Method:** 10 parallel investigation agents against the resource-level billing export, live `gcloud` inventory, Cloud Monitoring metrics, Cloud Audit Logs, and repo history
**Status:** Investigation complete. No changes applied — every action in this document is a proposal awaiting approval.

---

## 1. Executive Summary

The trigger for this audit was a ~$1,000/month Google Cloud bill. The June 2026 invoice confirms it: **$1,019.49**.

The investigation found four things:

1. **You are no longer paying $1,000/month.** Spend dropped from ~$24/day to ~$7.40/day on 2026-07-04 and has been flat there for 17 days. Current run rate is **~$225/month**.

2. **June was not a normal month.** Roughly **$550 of the $1,019 was either a one-time event or a bug**: a $232 one-off backfill, a $225 Pub/Sub redelivery storm, and ~$75-100 of an off-season backfill loop. Strip the accidents and June would have been ~$450-475. June had **7 NBA game days**; March had 31 and cost less.

3. **The largest remaining cost is idle capacity, not workload.** $114/month is `min-instances` holding warm containers for services that are serving nothing. Four of the seven affected functions have had **zero invocations in 90 days**.

4. **Nothing was watching.** A single service stepped from $0.03/day to $10.75/day overnight on 2026-03-22 and ran for 104 days — about $1,120 — before anyone noticed. Eight budgets exist; all of them alert on *actual* spend, to email, at thresholds that either never fire or fire every month.

**The most valuable output of this audit is not a cut. It is a $12/day spend alarm** that would have caught both incidents within 24 hours.

### Headline numbers

| | Value |
|---|---|
| June 2026 invoice (actual) | **$1,019.49** |
| Current run rate | **~$225/mo** ($7.40/day) |
| Achievable off-season floor | **~$70/mo** |
| Forecast in-season, do nothing | **~$880/mo** |
| Forecast in-season, after fixes | **~$650/mo** |
| Annual: do nothing vs fixed | **$6,300 → $4,200** |
| Safe savings identified | **~$160/mo** |

---

## 2. What You Were Actually Charged

Net of credits, from the resource-level billing export.

| Month | Net spend | Notes |
|---|---|---|
| Jan 2026 | $27.80 | **Single day** — export enabled 2026-01-31 |
| Feb 2026 | $567.77 | Cleanest in-season month, NBA-only |
| Mar 2026 | $955.69 | Seasonal peak (31 game days) + deploy churn |
| Apr 2026 | $694.98 | NBA winding down, InfiniteCase ramping |
| May 2026 | $602.01 | Closest thing to a clean idle month |
| **Jun 2026** | **$1,025.24** | **Two bugs + one backfill** |
| Jul 2026 MTD (21d) | $188.76 | ~$7.40/day post-cliff |

### Invoice reconciliation — the export is trustworthy

The June invoice from the Console versus what the billing export predicted:

| Project | Invoice | Export analysis | Match |
|---|---|---|---|
| NBA Props Platform | $636.02 | $641.75 | Δ $5.73 |
| Infinite Case | $334.35 | $334.37 | ✅ |
| urcwest | $35.42 | $35.41 | ✅ |
| MemberRadar | $13.14 | $13.14 | ✅ |
| Props Platform Web | $0.57 | $0.57 | ✅ |
| **Total** | **$1,019.49** | $1,025.24 | Δ $5.75 |

Four of five match to the cent. The variance is invoice-period versus usage-date grouping. **No hidden spend on this billing account.** Tax is $0. No credits beyond the standard free tier.

### Credits — nothing expired

Every month Feb–Jul shows an identical credit set totalling ~$10.45, all `type = DISCOUNT`, all at the capped free-tier maximum (Cloud Run / Cloud Functions CPU and memory allowances, fully consumed every month).

**There is no promotional credit, no free-trial credit, and no committed-use discount anywhere in this billing account, in any month.** No credit boundary explains any part of the cost pattern.

---

## 3. The July 4 Cliff

Daily spend went **$23.11 (Jul 3) → $7.75 (Jul 4)** and has held at $7.00–7.75/day since. Delta: **−$16.49/day = −$501/month**.

The cliff lands at 2026-07-04 00:00 UTC = Jul 3 ~5:00 PM PT. Two independent deliberate actions, same evening, both by the account owner.

### What stopped, by resource

| Project | Resource | Jul 1-3 $/day | Jul 5-20 $/day | Δ $/mo |
|---|---|---|---|---|
| infinite-case | `infinitecase-backend` CPU (instance-based) | 7.306 | 0.000 | **−222** |
| infinite-case | `infinitecase-backend` Memory (instance-based) | 3.247 | 0.000 | **−99** |
| nba-props-platform | `nba-phase4-precompute-processors` | 2.989 | 0.000 | −90 |
| nba-props-platform | `backfill-pubsub-subscriber` (CF) | 1.220 | 0.013 | −37 |
| nba-props-platform | `nba-pipeline-canary` (Run Job) | 0.647 | 0.000 | −20 |
| nba-props-platform | `nba-scrapers` | 0.422 | 0.068 | −11 |
| nba-props-platform | `prediction-worker` min-instances | 0.315 | 0.000 | −10 |
| nba-props-platform | Artifact Registry storage | 0.596 | 0.356 | −7 |
| nba-props-platform | Cloud Scheduler | 0.587 | 0.374 | −6 |
| nba-props-platform | Cloud Logging | 0.069 | 0.000 | −2 |
| nba-props-platform | `bluesky-nba-listener` (Run Job) | 0.208 | 0.626 | **+13** |

**Split: infinite-case 64% of the drop, nba-props-platform 36%.**

### Cause (a) — InfiniteCase revision change

Revision `infinitecase-backend-00148-9nc` deployed 2026-07-03T22:36:30Z:
- `run.googleapis.com/cpu-throttling`: `false` → **`true`** (instance-based → request-based billing)
- `autoscaling.knative.dev/minScale`: `1` → **removed**
- `maxScale`: `10` → `1`

The container is **4 vCPU / 16 GiB**. Billing math confirms the waste exactly: June billed 10,371,997 vCPU-seconds ÷ 4 = 2,592,000 instance-seconds = 30 days × 86,400. **100% of the month.** Memory resolves to exactly 16 GiB.

Both deploy paths (`backend/deploy.sh:60-67`, `cloudbuild.yaml:71-82`) were updated with inline comments, so this cannot silently regress.

### Cause (b) — NBA off-season scheduler purge

Commit `666d33e4` (Jul 3, 17:20 PT): *"2026-07-03 cost cuts: 10 NBA-only scheduler jobs paused, 94 deleted, retry loop killed."*

Cloud Audit Logs confirm a bulk `CloudScheduler.DeleteJob` of ~65 NBA jobs at 22:48–22:49 UTC, plus `PauseJob` on 10 more at 23:45 UTC. Backup at `gs://nba-bigquery-backups/scheduler-jobs-backup/scheduler_jobs_backup_2026-07-03.json` (204 jobs).

**Ruled out:** free-trial expiry, committed-use discount, promotional credit boundary, quota suspension, service crash.

---

## 4. Root Causes of the Expensive Months

### Loop A — the MLB Pub/Sub redelivery storm (~$225 in June)

`nba-phase2-raw-processors` went from ~$1/day to **$20.9/day** starting 2026-05-31, tapering to $13/day, then dying instantly on 2026-06-17.

Usage: **5.88M CPU-seconds and 1.06M requests over Jun 1–16** — roughly 46 requests/minute sustained, during an off-season with zero NBA games.

Cause, pinned by commit `64315182` (2026-06-16): *"fix(mlb): force mlb_raw dataset in BP props processor (stop 404 redelivery storm)."* A BettingPros MLB props processor wrote to a nonexistent dataset → 404 → Pub/Sub nack → infinite redelivery.

Two independent traces confirm the same incident:
- **BigQuery:** `SELECT COUNT(*) FROM nba_raw.bp_pitcher_props WHERE source_file_path = @file_path LIMIT 1` executed **1,035,031 times** between Jun 1 and Jun 16
- **Cloud Logging:** ~2 GB/day of `cloud_run_revision` errors plus ~1 GB/day of correlated BigQuery audit logs, stepping down 4.75 → 1.71 GB/day on Jun 18

**Cost: ~$225 on Cloud Run, plus a share of the $46 BigQuery and $21 Logging lines. Zero alerting fired.**

### Loop B — the off-season backfill treadmill (~$75-100/mo, May 11 – Jul 3)

`backfill-pubsub-subscriber` (deployed 2026-05-11, trigger topic `nba-backfill-trigger`) burned a flat **$1.30/day for 53 days** (~$70 total) and drove `nba-phase4-precompute-processors` from ~$1.00/day to **$3.00–3.60/day**.

Mechanism (high-confidence inference): `gap-detector-30min` → stale `expected_outputs` rows in an off-season with no games → `nba-backfill-trigger` → `backfill-pubsub-subscriber` → phase4 `/process-date` → still no data → stale again.

> ⚠️ **This loop is structurally still armed.** `gap-detector-30min`, `expected-outputs-planner-nightly`, and `phase-completion-reconciler-30min` are all **ENABLED today**. The loop stopped because its fuel was removed, not because it was fixed.

### The broken canary (~$20/mo, months)

`nba-pipeline-canary` billed $0.66/day while **100% broken** — every execution failed with `can't open file '/app/bin/monitoring/pipeline_canary_queries.py'`, roughly 100×/day. Paying for monitoring that monitored nothing. Fixed by commit `f51742b7` (Jul 4); triggers currently PAUSED.

### The one-off backfill (~$232 in June)

`nba-phase2-raw-processors` also ran a legitimate backfill May 31 → Jun 16 (5.79M CPU-sec, 1.07M requests), then flattened to ~$0.14/day. This is **53% of June's Cloud Run bill** and is not part of any forward run rate.

### Why March cost $956

Genuine seasonality plus self-inflicted churn:
- **31 game days / 240 games** — maximum-density month of the NBA calendar
- Pipeline compute $355 (phase3 $130, prediction-worker $106, phase2 $60, phase4 $59)
- **BigQuery analysis $182** — ad-hoc research query spend, not pipeline
- **Cloud Logging $68** (200 GB ingested) and Cloud Build $23 — driven by what CLAUDE.md records as *"10+ algorithm versions in March vs 1 in January (panic-deploy churn)"*
- **Min-instances switched on and never off:** $8.65 (Feb) → $111.08 (Mar), and it has stayed $117-134/mo ever since

That last item is the single most consequential line in this document. **A March decision created a permanent ~$100/month step change that is still running today.**

---

## 5. Cost Anatomy by Service

### 5.1 Cloud Run — nba-props-platform

June $442.68. **Forward run rate: $78.40/mo** (measured Jul 13–19).

| Item | $/mo now | Idle share | Notes |
|---|---|---|---|
| `prediction-coordinator` | **36.82** | **36.76 (99.85%)** | min-instances=1, 2 vCPU / 2 GiB, 24/7. Request CPU = $0.05/mo |
| `bluesky-nba-listener` (Job) | **20.14** | effectively 100% | 8 h/day websocket listener |
| `nba-auto-batch-cleanup` (Job) | 3.99 | — | 96 runs/day |
| MLB services + jobs | ~8.7 | — | in-season, halted strategy |
| `nba-scrapers` | 1.94 | — | real work |
| all others (~20) | ~7 | — | |

**Idle capacity is 47% of the run rate, and it is one service.**

`prediction-coordinator`'s only callers are Cloud Scheduler hitting `POST /check-stalled` (~37/day) plus one daily `/cleanup-staging`. Zero prediction work — the halt means there are no batches to find stalled.

**Service configuration (verified):**

| Service | min | max | CPU | Mem | CPU mode |
|---|---|---|---|---|---|
| prediction-coordinator | **1** | 1 | 2 | 2Gi | throttled |
| prediction-worker | 0 | 10 | 1 | 2Gi | throttled |
| nba-phase2-raw-processors | 0 | 10 | 1 | 2Gi | default |
| nba-phase3-analytics-processors | 0 | 10 | 2 | 2Gi | default |
| nba-phase4-precompute-processors | 0 | 5 | 2 | 2Gi | throttled |
| nba-scrapers | 0 | 10 | 2 | 2Gi | throttled |
| nba-grading-service | 0 | 20 | 1 | 512Mi | throttled |

No service is on always-allocated CPU — Session 388 already fixed that. `prediction-coordinator` is the only one with min-instances > 0.

**Note:** the June "Requests" SKU billed **$0.00 on 1,342,678 requests.** Request count is never a cost lever at this volume.

#### `bluesky-nba-listener` — $20/mo writing to a table that does not exist

Created 2026-06-30. 17 consecutive daily 8-hour runs (Jul 5–21), 1 vCPU / 512 MiB. Every run reports `Posts seen: 0-3, Posts matched: 0, BQ rows inserted: 0`.

**Its destination table `nba_raw.bluesky_nba_news` does not exist.** The schema JSON is in the repo (`schemas/bigquery/nba_raw/bluesky_nba_news.json`) but the table was never created — so even a matched post could not persist.

### 5.2 Cloud Run Functions — all projects

**$84.33/mo total, of which $77.17 (91.6%) is `Min-Instance CPU` + `Min-Instance Memory`.** All 154 other functions and ~100 schedulers combined cost about $7/mo.

| Function | Project | $/mo | Invocations |
|---|---|---|---|
| `phase3-to-phase4-orchestrator` | nba | 14.76 | ~36/day |
| `phase4-to-phase5-orchestrator` | nba | 14.68 | **0 in 30d** |
| `phase5-to-phase6-orchestrator` | nba | 14.67 | **0 in 30d** |
| `awardBidCF` | urcwest | 8.27 | **0 in 90d** |
| `submitBidCF` | urcwest | 8.27 | **0 in 90d** |
| `markBidRecommendedCF` | urcwest | 8.26 | **0 in 90d** |
| `withdrawBidCF` | urcwest | 8.26 | **0 in 90d** |
| `live-freshness-monitor` | nba | 0.89 | 132/day |
| all remaining (~147) | all | ~6 | |

**Historical burn on min-instances alone: $331** — $211 in nba-props-platform since ~February, $120 in urcwest since ~April.

**Why urcwest never dropped on July 4:** it is a construction bid-management Firebase app with no relationship to the NBA pipeline. Its daily series pins the cause to the day: $0.11/day through Mar 27 → $0.63 (Mar 29) → $0.86 (Apr 3) → $0.97 (Apr 4) → **$1.22/day flat ever since.** Each step is a min-instance deploy date.

> **Architectural note:** the three NBA orchestrators use `retryPolicy: RETRY_POLICY_DO_NOT_RETRY` on their Pub/Sub triggers. `min-instances=1` is being used as an **expensive workaround for a missing retry policy** — the fear is a cold start blowing the ack deadline and dropping a message. Enabling `--retry` on the Eventarc trigger fixes the actual problem and lets min-instances stay at 0 permanently, in-season included. This converts a $44/mo seasonal cut into a permanent one.

**`weekly-retrain` costs $0.00 and appears nowhere in billing** — independent confirmation of the CLAUDE.md note that its scheduler was deleted and the CF fires never.

### 5.3 BigQuery

| Month | Analysis (query) | Storage | Streaming | Egress | **Total** |
|---|---|---|---|---|---|
| Apr | $49.92 | $0.20 | $0.03 | $0.16 | $50.31 |
| May | $15.58 | $0.15 | $0.04 | $0.17 | $15.94 |
| Jun | $45.37 | $0.09 | $0.02 | $0.16 | $45.64 |
| Jul MTD | $1.90 | $0.05 | $0.00 | $0.11 | $2.07 |

**Storage is $0.09/month. It is not a cost lever and should be ignored.**

You hold 73.2 GB across 34 datasets. The largest, `nba_predictions_backups` (43.6 GB, 150 tables), consists of **`CREATE SNAPSHOT TABLE ... CLONE` snapshots** on 30-day rolling retention. Snapshots bill only *delta* bytes; the off-season froze the source, so all 30 `ml_feature_store_v2` snapshots are byte-identical (1,091,034,305 bytes each) and share storage. `__TABLES__.size_bytes` reports full logical size and **massively overstates** billed storage.

> **Deleting the backups dataset would save approximately $0.00 and destroy the only rollback path.**

All `mlb_*` datasets combined: 1.29 GB ≈ **$0.026/month**. All `test_*`/stale datasets combined: under $0.01/month. Total dead-storage recovery available: **under $0.05/month.** Logical→physical billing conversion would save at most $0.05 and could cost more.

**The real BigQuery cost was micro-query volume hitting the 10 MB minimum-billing floor:**

| Month | Jobs | TiB billed | TiB actually read | **Floor padding** |
|---|---|---|---|---|
| May | 574,919 | 2.845 | 0.658 | **68.4%** |
| Jun | **2,566,281** | 6.377 | 1.053 | **54.4%** |
| Jul | 245,932 | 1.239 | 0.372 | 56.9% |

June ran **2.57 million query jobs** — ~55/second in an off-season. **$24.75 of June's $45.37 was pure minimum-billing padding.** No individual query was expensive: the priciest pattern all month cost $2.96, and max bytes billed by any single job was 0.32 GB.

Post-cliff: 5,405 jobs/day, ~1.055 TiB/month billed. Since on-demand includes **1 TiB/month free**, the July bill collapsed to $1.90. **Usage now sits right at the free-tier boundary** — in-season growth crosses into billed territory quickly.

**Still running:** `prediction-worker` polls `SELECT COUNT(*) FROM player_prop_predictions WHERE game_date >= CURRENT_DATE()` **865×/day (every ~100s)** with zero games. It is the only BQ offender that did not drop on July 4 (7,785 executions before, 7,786 after).

**Structural item:** `nba_predictions.ml_feature_store_v2` is **NOT PARTITIONED** (`part=NONE`, no clustering). Every query full-scans 1.02 GB, growing ~1 GB/season. Every other high-growth table is correctly partitioned on `game_date`.

### 5.4 Cloud SQL

**$21.95/mo combined, and this is a permanent 24/7 floor that does not move with the season.**

| Instance | Project | State | $/mo | Used? |
|---|---|---|---|---|
| `infinitecase-db` | infinite-case | RUNNING | $11.19 | **No** — 0 connections for 10+ days |
| `memberradar-db` | memberradar-prod | **STOPPED** | $7.50–10.76 | **No** — off since Jul 3 |

Both are already `db-f1-micro`, 10 GB PD_SSD, ZONAL, no HA. **There is zero right-sizing headroom.**

#### The stop-does-not-save finding

Measured empirically when `memberradar-db` was stopped on 2026-07-03:

| SKU | Before | After |
|---|---|---|
| Micro instance | $0.302/day | $0.009/day ✅ |
| **IP address reservation** | $0.000/day | **$0.288/day** ❌ |
| Storage | $0.066/day | $0.066/day |
| **Net** | **$0.368/day** | **$0.354/day** |

**96% of the cost survived the stop.** GCP begins billing the retained public IPv4 as an idle reservation the moment the instance stops paying for it as part of the running instance.

| Option | Saving |
|---|---|
| Right-size tier | $0 — already cheapest tier |
| Turn off HA | $0 — never enabled |
| Cut backups / PITR | $0 |
| **Stop the instance** | **$0.43/mo** |
| **Export + delete** | **$21.95/mo combined** |

`infinitecase-db` holds **79.5 MB** and grew 0.4 MB in 60 days. That fits in Neon's or Supabase's free tier.

> ⚠️ **`infinitecase-db` has backups DISABLED and zero backups exist.** `backupConfiguration.enabled: false`; `gcloud sql backups list` returns nothing; ZONAL single-zone; no PITR. This is the database used for ad-hoc case processing and it has **no recovery point of any kind.** Unrelated to cost, and more urgent than any item in this document.

> ⚠️ Both instances have `storageAutoResize: true` with **limit 0 (unlimited)** and `deletionProtectionEnabled: false`. A runaway write grows the disk permanently — Cloud SQL storage never shrinks back.

### 5.5 Cloud Logging

June $20.93 (93.4 GiB ingested − 50 GiB free = 43 GiB billable). **Now $0.30/mo.**

Two discrete, durable step-downs:
- **Jun 18: 4.75 → 1.71 GB/day** — commit `64315182` killed the Loop A redelivery storm
- **Jul 5: 1.22 → 0.07 GB/day** — the `exclude-bq-audit-noise` exclusion added to `_Default` on 2026-07-03. BigQuery audit logs were **67% of all ingestion** (41.3 of 62 GB over Jun 9–Jul 21)

Retention is clean: only `_Default` (30d) and `_Required` (400d, free). No custom buckets, no export sinks. **100% of the cost was ingestion; zero was retention.**

**In-season risk:** Feb was $24.36 (106 GB), March $68.30 (200 GB). Applying the June ratio, a March-2027 repeat lands ~85 GB → ~$17/mo instead of $68 — the exclusion is doing real structural work.

**Current top producer is MLB:** of ~2,000 sampled Cloud Run entries in the last 24h, **1,706 (85%) come from `mlb-phase3-analytics-processors` (451 WARNING/day), `mlb-phase1-scrapers`, and `mlb-phase2-raw-processors`** — for a strategically halted sport.

### 5.6 Cloud Scheduler

**139 jobs across 5 projects and 8 locations. $13.60/mo.** ($0.10/job/month beyond 3 free.)

| Project | Location | Jobs |
|---|---|---|
| nba-props-platform | us-west2 | 110 (100 enabled, 10 paused) |
| nba-props-platform | us-central1 | 6 |
| urcwest | us-central1 | 19 |
| props-platform-web | us-central1 | 4 |

- **32 of 116 NBA-project jobs are MLB** (`0 * 3-10 *`), all enabled, all fired within the last 24h
- **PAUSED jobs are still billed.** 10 paused = $1.00/mo
- **2 zombie jobs point at 2 zombie Cloud Functions** — see §5.10

**Counterintuitive:** deleting 94 scheduler jobs saved only ~$9/mo in Scheduler fees directly. The savings came entirely from the compute those jobs triggered. Restoring them as PAUSED is nearly free; the cost lands the moment they resume.

### 5.7 Artifact Registry

**136.4 GB across 10 repos. $13.64/mo.**

| Project | Repo | Loc | Size | Images | Untagged | >180d | Newest |
|---|---|---|---|---|---|---|---|
| nba-props-platform | **gcr.io** | us | **42.50 GB** | 228 | **154** | **205** | 2026-05-16 |
| nba-props-platform | nba-props | us-west2 | 34.54 GB | 93 | 15 | 3 | 2026-07-05 |
| nba-props-platform | gcf-artifacts | us-west2 | 19.49 GB | 375 | **219** | 39 | 2026-07-05 |
| nba-props-platform | cloud-run-source-deploy | us-west2 | 11.75 GB | 33 | 21 | 10 | 2026-02-01 |
| memberradar-prod | memberradar | us-west2 | 16.80 GB | 106 | 0 | 0 | 2026-04-04 |
| infinite-case | infinitecase | us-west2 | 5.58 GB | 112 | 20 | 0 | 2026-05-11 |
| nba-props-platform | mlb-monitoring | us-west2 | 1.75 GB | 4 | 0 | 4 | 2026-01-16 |
| nba-props-platform | cloud-run-source-deploy | us-west1 | 1.70 GB | 4 | 3 | 4 | 2026-01-20 |
| nba-props-platform | **pipeline** | us-west2 | 1.41 GB | 9 | 6 | 9 | **2025-08-14** |
| nba-props-platform | mlb-validators | us-west2 | 0.87 GB | 3 | 0 | 3 | 2026-01-16 |

> 🐛 **`bin/cleanup-artifact-registry.sh` has a coverage bug.** It hardcodes `REPOS=("nba-props" "cloud-run-source-deploy" "gcf-artifacts")` and `REGION="us-west2"`. The `ar-weekly-cleanup` job has therefore been succeeding every Sunday while **silently ignoring `gcr.io` — the single largest repo at 42.5 GB.** It also prunes by tag count only, never deleting the 219 untagged images in `gcf-artifacts`. Fix the script rather than layering cleanup policies on top, or you will have two competing mechanisms.

**Deletion-safety check:** `prediction-coordinator-dev`, `processing-gap-monitor`, `nba-pipeline-canary`, and `mlb-phase4-precompute-processors` are digest-pinned by `@sha256:` — all four digests carry the `latest` tag, so a keep-`latest` rule protects them. ~40 backfill Cloud Run jobs pin `gcr.io` images untagged (→ `:latest`), so `gcr.io` can be pruned but not blanket-deleted.

### 5.8 Cloud Storage

**$2.10/mo.** Mostly fine — one real problem.

`gs://nba-props-platform-api`: **44.65 GB, 793,824 objects, versioning ENABLED, lifecycle NONE.**

| Prefix | Live objects | Total versions | Amplification |
|---|---|---|---|
| `v1/trends/` | **8** | **13,559** | **1,695×** |
| `v1/signal-best-bets/` | 161 | 1,432 | 8.9× |

Hourly trend re-exports (6 AM–11 PM), the 4:30 PM CLV re-export, and post-grading re-exports each mint a permanent noncurrent version.

Everything else is correctly configured: `nba-scraped-data` and `mlb-scraped-data` have Nearline@30d + Delete@90d; backup/cloudbuild/gcf buckets have Delete@30d or @1d; gcf-v2-sources uses `numNewerVersions:3`. Only other gap is `infinite-case_cloudbuild` (1.23 GB, no lifecycle).

### 5.9 Secret Manager

**80 versions across 63 secrets, $4.40/mo** ($0.06/active version, 6 free). No secret has more than 3 versions.

Real waste is duplicate pairs in nba-props-platform: `BDL_API_KEY`/`bdl-api-key`, `ODDS_API_KEY`/`odds-api-key`, `SENTRY_DSN`/`sentry-dsn`, plus both `CLAUDE_API_KEY` and `anthropic-api-key`. `slack-webhook-error` has **zero versions** (dead shell).

### 5.10 Zombie infrastructure

**There is no App Engine app.** `gcloud app describe` returns *"does not contain an App Engine application."* The billing label is a legacy rollup for **Firestore**. nba-props-platform recorded **2,287,242 Firestore entity writes in June** ($2.02) → $0.00 in July. 2.29M writes in an off-season month (76K/day, zero games) is itself worth a look.

> 🐛 **Two live, scheduled, alert-emitting Cloud Functions have no source code in the repo.** `box-score-completeness-alert` and `phase4-failure-alert` (both us-west1) are ACTIVE and deployed, triggered by `box-score-alert-job` (every 6h) and `phase4-alert-job` (daily). CLAUDE.md records their source directories as removed in the Task #35 orphan cleanup — the *directories* were cleaned up, the *deployments* were not. If either fires a false alert, there is no code to debug.

Other zombies: `grading-readiness-monitor` (state FAILED, duplicate of an ACTIVE one), `backfill-trigger` (UNKNOWN), `phase3-to-phase4` / `phase5-to-phase6` (UNKNOWN, legacy duplicates of the orchestrators). All $0 cost.

**Stray cross-project function:** `nba-grading-alerts` — NBA pipeline code — is deployed in the **urcwest** project, where NBA deployment-drift checks will never find it.

### 5.11 Verified absent

Rather than assuming, the audit checked enabled-API lists per project *and* full 2026 billing history:

- **Compute Engine VMs — none. The Compute Engine API is not enabled on any of the 5 projects**, which categorically rules out persistent disks (attached or unattached), snapshots, reserved static external IPs, load balancers/forwarding rules, Cloud NAT, and VPN tunnels
- **Memorystore, Filestore, Composer, GKE, Dataflow, Dataproc, Bigtable, Spanner, AlloyDB, Vertex AI, Notebooks — none.** APIs disabled, $0.00 across all of 2026
- **No non-GCP charges.** No Workspace, no Maps billing, no Marketplace SaaS, no Play. Firebase Hosting $0.00; Places API $0.00 since April. "Firebase Payment" is just the account's name
- Pub/Sub: 49 topics / 22 subscriptions, sane retention, $0.01 in June
- Cloud Build: $0.01–0.02/mo egress only; build minutes inside free tier
- **No egress spike anywhere** — all network SKUs ≤$0.30/month across the entire history

**Complete list of services that billed anything in 2026:** Cloud Run $2,530 · Cloud Run Functions $518 · BigQuery $461 · Artifact Registry $143 · Cloud Logging $116 · Cloud Scheduler $105 · Cloud SQL $91 · Cloud Storage $75 · Cloud Build $58 · Secret Manager $21 · App Engine/Firestore $10 · Pub/Sub $0.02.

---

## 6. The Multi-Account Picture

**You have 5 billing accounts and 17 projects — not 4 and 5.** `gcloud billing accounts list` shows 4; a fifth surfaced via project linkage.

| Billing account | Projects | Export? | Analyzed? |
|---|---|---|---|
| `01169A-2CADBE-978AC6` "Firebase Payment" | nba-props-platform, infinite-case, urcwest, memberradar-prod, props-platform-web | ✅ | ✅ |
| `012771-2FDDA2-05C7DB` "My Billing Account 1" | **jett-prod**, urcw-prod, urcw-staging, appius-construction-demo, gen-lang-client-0866788294 | ❌ | ❌ |
| `017067-5DE13C-479720` "June 2026 Billing Account" | **dmhr-platform**, jig-hq-demo | ❌ | ❌ |
| `0186FA-8777DE-2487B8` (CLOSED) | none | — | harmless |
| `00A629-69CB1B-9B0FA6` | klipschweb-maps-1 (2013) | 🚫 no permission | — |

Unlinked / no billing (zero cost): `recipe-platform-25`, `shipping-insights-25`, `testing-479218`, `infinite-case-d09b5`.

### Per-project verdicts

| Project | Verdict | $/mo | What it is |
|---|---|---|---|
| nba-props-platform | Active | $450–830 in-season | The NBA props system |
| **urcwest** | **Active but idle** | $36.85 | Construction bid platform. 71 Gen2 functions, 19 schedulers, zero user traffic on bid functions |
| **memberradar-prod** | **Abandoned** | $13.14 | SQL stopped since March, still billing. 16 GB dead images |
| infinite-case | Dormant | $12 (was $336) | Legal-AI SaaS. Fixed Jul 3 |
| props-platform-web | Active, trivial | $0.57 | NBA pick'em app. $7/year |
| **jett-prod** ⚠️ | **Live — do not touch** | ~$45–75 est. | `api.jetthq.com`. Postgres 16 `db-g1-small` always-on + Cloud Run `minScale=1` with **`cpu-throttling: false`** |
| dmhr-platform | Active | ~$2–10 est. | Del Mar Horse Races. 3 daily Cloud Run jobs, racing season now |
| urcw-prod / urcw-staging | **Empty shells** | ~$0 | Created 2026-04-19 as urcwest v2. Zero services, zero functions, zero DBs |
| appius-construction-demo | Abandoned | ~$0 | Firebase demo, one bucket |
| jig-hq-demo | New, unknown | unknown | Created 2026-07-07. **Geocoding + Static Maps + Street View + Vertex AI enabled** — can spike |
| gen-lang-client-… | Unknown | unknown | Gemini API. **Paid-tier Gemini bills through GCP** to account `012771` |
| klipschweb-maps-1 | **Not yours** (probably) | — | 2013, Maps/YouTube APIs, on a billing account you have no permission for |

### ⚠️ Open question — the two unexamined accounts

**`jett-prod` runs the exact configuration that cost $321/month on InfiniteCase**: `minScale=1` plus `cpu-throttling: false`, alongside an always-on Postgres instance. It sits on a billing account with **no export and no budget**.

Two possibilities, and only the Console settles it:
1. Both accounts are inside a 90-day $300 free-trial window (both are new; one is literally named "June 2026 Billing Account") — meaning cost is $0 today and **a cliff is coming**
2. They are already charging a second payment method not reconciled against the invoice above

**Action required:** Console → Billing → switch account → **Credits** page for both `012771-2FDDA2-05C7DB` and `017067-5DE13C-479720`.

---

## 7. Seasonality and Forecast

### Floor vs variable

Measured from the clean Jul 5–20 window (16 days, zero NBA activity), scaled to 30.4 days.

**STRUCTURAL FLOOR — $168.09/mo (75% of current spend)**

| Component | $/mo |
|---|---|
| Min-instance CPU+mem, 4 NBA services | $80.99 |
| urcwest CF min-instances | $32.86 |
| Cloud SQL, 2 dead side projects | $21.95 |
| Cloud Scheduler (139 jobs) | $13.63 |
| Artifact Registry (136 GB) | $12.87 |
| Secret Manager | $4.71 |
| GCS storage | $1.10 |
| BigQuery storage | $0.17 |

**SEMI-FIXED / DISCRETIONARY IDLE — $56.56/mo (25%)**
Cloud Run Jobs $30.78 (bluesky $20, batch-cleanup $4, mlb-stall-detector $3) · residual invocations $21.72 · BQ analysis $2.49 · GCS ops $1.57

**VARIABLE LOAD — $0/mo now; $21.60 per game-day in season**

Derived two independent ways that converge tightly:

| Month | NBA+shared | minus floor | Game days | **$/game-day** | $/game |
|---|---|---|---|---|---|
| Feb 2026 | $564.17 | $491.7 | 22 | **$22.35** | $2.96 |
| Mar 2026 | $825.43 | $671.4 | 31 | **$21.66** | $2.80 |
| Apr 2026 (playoffs) | $327.88 | $187.3 | 27 | $6.94 | $1.25 |

### The split

| | Off-season (now) | In-season (30 game-days, do nothing) |
|---|---|---|
| Structural floor | $168 (**75%**) | $174 (20%) |
| Semi-fixed idle | $57 (25%) | $57 (6%) |
| Variable NBA load | $0 | **$650 (74%)** |
| **Total** | **$225** | **~$880** |

**Off-season, you pay 75% floor for a system doing nothing. In-season, 74% is genuine pipeline compute that no amount of infra hygiene will touch.**

### Three scenarios for 2026-27

Assumptions: opener Oct 21 2026; game-day calendar mirrors 2025-26 (Oct 11, Nov 29, Dec 30, Jan 31, Feb 22, Mar 31, Apr 27); variable rate $21.60/game-day regular, $7/game-day playoffs (**±20%**); MLB stays halted; no repeat of the June runaway.

| Scenario | Oct | Nov | Dec | Jan | Feb | Mar | Apr | Off-season | **Annual** |
|---|---|---|---|---|---|---|---|---|---|
| **(a) Do nothing** | 468 | 856 | 878 | 900 | 705 | 900 | 419 | 231 | **~$6,300** |
| **(b) Obvious fixes** | 273 | 621 | 643 | 665 | 470 | 665 | 224 | 76 | **~$4,200** |
| **(c) Also kill MLB + side projects** | 220 | 570 | 592 | 615 | 420 | 615 | 175 | 41 | **~$3,550** |

The model is calibrated: scenario (a) reproduces actual March 2026 ($956) to within $56.

**Scenario (c) only saves ~$50/mo more than (b).** Scenario (b) captures ~90% of achievable savings. Everything past it is diminishing returns.

**All three leave the $650/mo in-season variable load untouched.** Getting below ~$600 in-season requires pipeline compute efficiency work — `nba-phase3-analytics-processors` ($130/mo), `prediction-worker` ($110/mo), BigQuery analysis ($180/mo), `nba-phase4-precompute` ($60/mo). That is an engineering project, not a cleanup.

### Unbounded growers — 12-month projection

| Driver | Today | Jul 2027 | Verdict |
|---|---|---|---|
| **Cloud Run min-instances** | $114/mo | Each new `minScale=1` adds ~$20/mo permanently | **THE real unbounded grower.** 93 services exist; 4 have it. Governance item |
| Artifact Registry | $13.64/mo | $19–25 if cleanup lapses; $8 if `gcr.io` pruned | Real but modest |
| Cloud Logging | $0.30 idle | $25–70 in-season | Scales with services × verbosity; doesn't compound YoY |
| Cloud Scheduler | $13.63 (139 jobs) | $17–22 | Monotonic — jobs get added, rarely deleted |
| **BigQuery storage** | **$0.17/mo** | ~$2 even at 10× growth | **Myth-busted. Ignore.** |
| Cloud SQL side projects | $22/mo | $22/mo forever | Pure carry cost |

**12-month growth if nothing is touched: +$15 to +$25/mo.** Genuinely modest. The storage-growth worry is misplaced; the money is in min-instances and in-season pipeline compute.

---

## 8. Per-Unit Economics

| Unit | Cost |
|---|---|
| Per game-day (regular season) | **$21.60** |
| Per game-day (playoffs) | $6.94 |
| Per NBA game | **$2.90** |
| Per raw prediction row | $0.020 |
| Per scraper run | ~$0.005 |
| **Per published best-bets pick** | **$12.82** NBA-attributable / **$16.55** all-in |

Scraping is nearly free; **processing** is the cost.

### Cost per pick, in context

At -110 (breakeven 52.38%), gross modeled EV per pick:

| Hit rate | EV @ $100 | EV @ $250 | EV @ $500 | Stake to cover $12.82 |
|---|---|---|---|---|
| 60% | +$14.55 | +$36.4 | +$72.7 | **$88** |
| 57% | +$8.81 | +$22.0 | +$44.1 | **$146** |
| 55% | +$5.00 | +$12.5 | +$25.0 | **$256** |
| 53% | +$1.18 | +$2.9 | +$5.9 | **$1,086** |

**Two caveats that cut in opposite directions:**

- *Against:* project memory records the honest live curve as **flat ~50-51%** for the raw stream, with only 175–203 graded live BB picks — below the N≥300 needed for an honest sizing decision. The 60% figure is not yet confirmed at scale.
- *In favor:* **infrastructure cost is largely fixed per game-day, not per pick.** You pay $21.60/game-day whether you publish 3 picks or 15. Volume was deliberately throttled to ~3.4/day by the edge-based auto-halt and the OVER floor. Doubling pick volume at constant HR would roughly halve cost-per-pick without materially raising spend. **Cost-per-pick is high mainly because pick volume is deliberately low, not because the infrastructure is expensive.**

---

## 9. Action Plan

Nothing below has been applied.

### Tier 1 — safe now, no judgment required (~$97/mo)

| # | Action | $/mo | Restore in Oct? |
|---|---|---|---|
| 1.1 | urcwest: 4 bid functions → `min-instances=0` | 33.06 | **No — permanent** |
| 1.2 | `prediction-coordinator` → `min-instances=0` | 36.80 | **Yes** |
| 1.3 | Kill `bluesky-nba-listener` scheduler | 20.14 | No |
| 1.4 | Pause `nba-auto-batch-cleanup` + 2 stall schedulers | 4.05 | **Yes** |
| 1.5 | Fix `cleanup-artifact-registry.sh` + cleanup policies on all repos | ~8.16 | No |
| 1.6 | Delete dead AR repos (`pipeline`, `cloud-run-source-deploy` us-west1) | 0.31 | No |
| 1.7 | Lifecycle rule on `gs://nba-props-platform-api` noncurrent versions | 0.75 | No |
| 1.8 | Delete 2 zombie CFs + their 2 schedulers | 0.30 | No |
| 1.9 | Delete 4 paused rebounds/assists jobs | 0.40 | No |

```bash
# 1.1 — urcwest bid functions (ALSO remove minInstances:1 from Firebase TS source)
for f in awardBidCF submitBidCF withdrawBidCF markBidRecommendedCF; do
  gcloud functions deploy $f --project=urcwest --region=us-central1 --gen2 --min-instances=0
done

# 1.2 — prediction-coordinator (ALSO edit bin/deploy-service.sh:51-62)
gcloud run services update prediction-coordinator \
  --region=us-west2 --project=nba-props-platform --min-instances=0

# 1.3 — bluesky listener
gcloud scheduler jobs pause nba-bluesky-listener-daily \
  --location=us-west2 --project=nba-props-platform

# 1.4 — off-season cleanup jobs
gcloud scheduler jobs pause nba-auto-batch-cleanup-trigger --location=us-west2 --project=nba-props-platform
gcloud scheduler jobs pause stalled-batch-cleanup        --location=us-west2 --project=nba-props-platform
gcloud scheduler jobs pause prediction-stall-check       --location=us-west2 --project=nba-props-platform
```

`ar-policy.json` (keep rules always beat delete rules; run `--dry-run` for a week first):
```json
[
  {"name":"keep-latest-tag","action":{"type":"Keep"},
   "condition":{"tagState":"TAGGED","tagPrefixes":["latest"]}},
  {"name":"keep-5-recent","action":{"type":"Keep"},
   "mostRecentVersions":{"keepCount":5}},
  {"name":"delete-untagged-30d","action":{"type":"Delete"},
   "condition":{"tagState":"UNTAGGED","olderThan":"30d"}},
  {"name":"delete-stale-tagged-180d","action":{"type":"Delete"},
   "condition":{"tagState":"TAGGED","olderThan":"180d"}}
]
```

`api-lifecycle.json`:
```json
{"lifecycle":{"rule":[
  {"action":{"type":"Delete"},"condition":{"isLive":false,"numNewerVersions":3}},
  {"action":{"type":"Delete"},"condition":{"isLive":false,"daysSinceNoncurrentTime":14}}
]}}
```

### Tier 2 — safe, with care (~$59/mo)

| # | Action | $/mo | Note |
|---|---|---|---|
| 2.1 | 3 NBA orchestrators → `min-instances=0` | 44.19 | **Prefer `--retry` on the Eventarc trigger** — makes it permanent |
| 2.2 | Delete `memberradar-prod` (SQL + 16 GB images) | 12.50 | Export first. Stopped since March |
| 2.3 | Gate `prediction-worker`'s off-season BQ poll on halt-state | ~2 | Code change |
| 2.4 | Delete duplicate/empty secrets | 0.50 | Grep deployments first |

```bash
# 2.1 — durable fix: change the trigger substitution, THEN redeploy
gcloud builds triggers update github deploy-phase4-to-phase5-orchestrator \
  --project=nba-props-platform --region=us-west2 --update-substitutions=_MIN_INSTANCES=0
gcloud builds triggers update github deploy-phase5-to-phase6-orchestrator \
  --project=nba-props-platform --region=us-west2 --update-substitutions=_MIN_INSTANCES=0
# also: bin/orchestrators/deploy_phase{3,4,5}_to_phase{4,5,6}.sh  MIN_INSTANCES="1" -> "0"

# 2.2 — export BEFORE deleting
gcloud sql instances patch memberradar-db --project=memberradar-prod --activation-policy=ALWAYS
gcloud sql export sql memberradar-db gs://BUCKET/memberradar-$(date +%Y%m%d).sql.gz \
  --database=DBNAME --project=memberradar-prod
gcloud sql instances delete memberradar-db --project=memberradar-prod
```

### Tier 3 — judgment calls

| Action | $/mo | Decision needed |
|---|---|---|
| Retire MLB entirely (32 schedulers + 12 Cloud Run services + log exclusion) | $20–35 | MLB is halted per strategy, but halted ≠ no data clock. If the info product needs one, keep `mlb-schedule-daily` + `mlb-box-scores-daily` only |
| `infinitecase-db` — keep, delete, or migrate | $11.19 | The availability premium for ad-hoc case processing. 79.5 MB fits a free tier elsewhere |
| `jett-prod` billing-mode fix | ~$15–30 est. | Live production API. Validate before changing |

### Not recommended

- **Deleting BigQuery datasets for cost.** Total recovery under $0.05/mo; destroys rollback paths
- **Stopping Cloud SQL instances.** Proven to save $0.43/mo
- **Budget-triggered billing disable.** See §10

### Where this lands

| | Now | After Tier 1+2 | After Tier 3 |
|---|---|---|---|
| Off-season | $225/mo | **~$70/mo** | **~$40/mo** |
| In-season (Oct+) | ~$880/mo | **~$650/mo** | **~$615/mo** |

---

## 10. Guardrails — Getting Ahead of It

### Current controls, honestly assessed

**Eight budgets exist on `01169A`. All are structurally incapable of early warning.**

| Budget | Amount | Verdict |
|---|---|---|
| "NBA Props Alert" ×5 | $200–800 | Hand-rolled ladder, one 100% threshold each |
| NBA Props Platform Monthly | **$40** | Actual $450–830 → **fires at 1000–2000% every month** |
| urcwest | $40 | Reasonable |
| props-platform-web | $40 | Actual $0.57 → can never fire |

Five gaps:
1. **All 8 use `spendBasis: CURRENT_SPEND`.** Zero forecast alerts. You are only told after the money is spent
2. **All 8 have `notificationsRule: {}`** — email to billing admins only. Nothing reaches `#nba-alerts`
3. **The $40 NBA budget is alert fatigue by construction.** A budget that always fires is one you have learned to ignore
4. **`infinite-case` and `memberradar-prod` have no project budget at all.** InfiniteCase was the #2 spender
5. **Highest ceiling ($800) < June ($1,025)**

**No cost-related alert policies exist.** `monitoring/alert-policies/` holds 8 YAMLs, all pipeline-health. `monitoring/bigquery_cost_tracker.py` and `scraper_cost_tracker.py` read `INFORMATION_SCHEMA.JOBS` for a dashboard — neither reads the billing export, neither alerts.

**Hard caps are missing.** BigQuery has **no consumer quota override at all** — the project sits at the stock 200 TiB/day (~$1,250/day of headroom) and **per-user is literally unlimited (int64 max)** against ~$29/mo actual usage. 4 Cloud Run services and 7 Cloud Functions have **no `maxScale`** (default 100).

### The case that proves the gap

```
2026-03-20   $0.03
2026-03-21   $0.72
2026-03-22  $10.75   ← 335x overnight
...flat ~$10.80/day for 104 days...
2026-07-03  $10.77
2026-07-04   $0.00
```

**One service stepped 335× overnight and ran for 3.5 months — about $1,120 — on a project with no budget.**

### Recommended budget scheme — $700/month account ceiling

Justification: off-season floor $225 sits at 32% (quiet); in-season forecast ~$615 lands at 88% (75%/90% thresholds carry real signal); a June repeat trips **100% forecasted in the first week**, not on the invoice.

| Project | Recommended | Actual run rate | Today |
|---|---|---|---|
| nba-props-platform | $550 | $450–830 in-season | $40 (noise) |
| infinite-case | $60 | $11 floor, was $330 | **none** |
| urcwest | $60 | ~$35 | $40 |
| memberradar-prod | $30 | ~$13 | **none** |
| props-platform-web | $10 | ~$0.57 | $40 (dead) |

```bash
BA=01169A-2CADBE-978AC6
SLACK=projects/nba-props-platform/notificationChannels/13444328261517403081
BP="--billing-project=nba-props-platform"   # required, or SERVICE_DISABLED

# Account ceiling — actual AND forecast, routed to Slack
gcloud billing budgets create $BP --billing-account=$BA \
  --display-name="ALL PROJECTS — Monthly Ceiling \$700" \
  --budget-amount=700USD --calendar-period=month \
  --credit-types-treatment=include-all-credits \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.75 \
  --threshold-rule=percent=0.9 --threshold-rule=percent=1.0 \
  --threshold-rule=percent=0.75,basis=forecasted-spend \
  --threshold-rule=percent=1.0,basis=forecasted-spend \
  --notifications-rule-monitoring-notification-channels=$SLACK

# Seasonality-proof companion — auto-adapts to last month, never needs retuning
gcloud billing budgets create $BP --billing-account=$BA \
  --display-name="ALL PROJECTS — vs Last Month (auto-seasonal)" \
  --last-period-amount --calendar-period=month \
  --credit-types-treatment=include-all-credits \
  --threshold-rule=percent=1.15 --threshold-rule=percent=1.30 \
  --threshold-rule=percent=1.30,basis=forecasted-spend \
  --notifications-rule-monitoring-notification-channels=$SLACK
```

The `--last-period-amount` budget matters because of the 2.7× seasonal swing between $225 off-season and ~$615 in-season — it absorbs that automatically.

### Daily cost anomaly detector — backtested

Proposed as `bin/monitoring/cost_anomaly_detector.py`, deployed as a CF on the existing `cloudbuild-functions.yaml` pattern, scheduled 9 AM ET.

**Validation against real history:**

| Backtest date | Result |
|---|---|
| **2026-03-22** | `SPIKE_MAJOR infinite-case / Cloud Run — $10.75 vs $0.03 median, 335×, z=26` ✅ **catches the $1,120 leak on day one** |
| **2026-06-05** | `SPIKE_MAJOR nba-props / Cloud Run — $25.32 vs $5.42 median, 4.67×` ✅ **catches the June ramp 25 days before the invoice** |
| 2026-03-13 | `SPIKE_MINOR Cloud Logging — $2.58 vs $0.46, 5.6×` ✅ real, minor |
| 2026-04-02, 2026-07-04 | no alert ✅ correctly quiet on steady state and on *drops* |

**Cost: 34 MB scanned per run ≈ $0.0002/day (~$0.08/year).**

```sql
-- Params: @target_date (DATE). Scans ~34MB.
WITH daily AS (
  SELECT
    DATE(usage_start_time) AS usage_date,
    project.id             AS project_id,
    service.description    AS service,
    SUM(cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS net_cost
  FROM `nba-props-platform.billing_export.gcp_billing_export_resource_v1_01169A_2CADBE_978AC6`
  -- CRITICAL: partitioned on _PARTITIONTIME (ingestion), NOT usage_start_time.
  -- Filtering only usage_start_time scans all 3.45 GB. Pad 4 days for restatements.
  WHERE _PARTITIONTIME >= TIMESTAMP(DATE_SUB(@target_date, INTERVAL 32 DAY))
    AND DATE(usage_start_time) BETWEEN DATE_SUB(@target_date, INTERVAL 28 DAY) AND @target_date
    AND project.id IS NOT NULL
  GROUP BY 1, 2, 3
),
baseline AS (
  SELECT project_id, service,
    AVG(net_cost)    AS mean_28d,
    STDDEV(net_cost) AS sd_28d,
    APPROX_QUANTILES(net_cost, 100)[OFFSET(50)] AS median_28d,  -- robust to one-off bursts
    COUNT(*)         AS days_seen
  FROM daily
  WHERE usage_date BETWEEN DATE_SUB(@target_date, INTERVAL 28 DAY)
                       AND DATE_SUB(@target_date, INTERVAL 1 DAY)
  GROUP BY 1, 2
),
yday AS (
  SELECT project_id, service, net_cost FROM daily WHERE usage_date = @target_date
)
SELECT
  @target_date AS usage_date,
  COALESCE(y.project_id, b.project_id) AS project_id,
  COALESCE(y.service, b.service)       AS service,
  ROUND(IFNULL(y.net_cost, 0), 2)                           AS cost_yday,
  ROUND(IFNULL(b.median_28d, 0), 2)                         AS median_28d,
  ROUND(IFNULL(y.net_cost,0) - IFNULL(b.median_28d,0), 2)   AS delta_usd,
  ROUND(SAFE_DIVIDE(IFNULL(y.net_cost,0), NULLIF(b.median_28d,0)), 2)          AS ratio,
  ROUND(SAFE_DIVIDE(IFNULL(y.net_cost,0) - b.mean_28d, NULLIF(b.sd_28d,0)), 2) AS zscore,
  CASE
    WHEN b.project_id IS NULL AND IFNULL(y.net_cost,0) >= 1.0 THEN 'NEW_SPEND'
    -- dual gate: absolute dollars AND relative ratio, so cheap noisy lines can't spam
    WHEN IFNULL(y.net_cost,0) - IFNULL(b.median_28d,0) >= 5.0
         AND IFNULL(y.net_cost,0) >= 1.5 * IFNULL(b.median_28d, 0.01) THEN 'SPIKE_MAJOR'
    WHEN IFNULL(y.net_cost,0) - IFNULL(b.median_28d,0) >= 1.5
         AND IFNULL(y.net_cost,0) >= 1.5 * IFNULL(b.median_28d, 0.01) THEN 'SPIKE_MINOR'
    ELSE 'OK'
  END AS verdict
FROM yday y
FULL OUTER JOIN baseline b USING (project_id, service)   -- catches new spend AND total stops
WHERE IFNULL(y.net_cost,0) >= 0.25 OR IFNULL(b.median_28d,0) >= 0.25
ORDER BY delta_usd DESC
```

Use `LAG_DAYS = 2` — at D-1 the export is still partially loaded and would generate false "spend collapsed" alerts every morning.

> **Trap:** `weekly-retrain` is a live example in this repo of a function whose scheduler was deleted, leaving it firing never. Add a freshness check on `cost_daily_usd` to `daily-health-check` so this detector cannot die the same way.

### Hard caps — what actually stops spend

Budgets only notify. These have teeth.

1. **BigQuery daily quota override — do this first.** Console → IAM & Admin → Quotas → `bigquery.googleapis.com/quota/query/usage`. Set per-project/day **2 TiB** (~$12.50/day, ~13× normal) and per-user/day **1 TiB**. *Tradeoff, stated plainly:* when hit, queries hard-fail with `quotaExceeded` until midnight PT, breaking the pipeline for the rest of the day. 2 TiB is chosen to be far above any legitimate day — the entire billing export is 3.45 GB — so only a genuine runaway trips it. The override can be raised in ~1 minute.

2. **`max-instances` on the 11 uncapped services/functions.** `backfill-trigger`, `box-score-completeness-alert`, `phase4-failure-alert`, `upcoming-tables-cleanup` have no ceiling (default 100). A retry storm fans out to 100 instances. Monitors have no business above ~5. Essentially zero risk.

3. **Budget-triggered billing disable — NOT recommended.** The pattern (budget → Pub/Sub → `projects.updateBillingInfo(billingAccountName='')`) is the only control that truly stops all spend, but detaching billing does not gracefully pause anything — it **destroys** resources. Cloud SQL instances, GCS data, and Cloud Run services can be irrecoverably lost, and re-attaching does not restore them. It fires on forecast noise. With 419K+ grading records in BQ and the public API bucket in GCS, the blast radius of a false positive vastly exceeds the cost of a bad month. **June was painful, not existential; this control's failure mode is existential.** If a kill switch is ever wanted, build the safe version: budget → Pub/Sub → set `--max-instances=0` on non-critical Cloud Run services, leaving data services untouched, gated behind manual Slack approval.

### Labeling

Cost-weighted, Cloud Run is 90% of spend and is 95–100% labeled — the existing `billing_service = nba|mlb` key is the right idea. The unlabeled money is the long tail: BigQuery $57/60d, Cloud SQL $44, Cloud Scheduler $34, Artifact Registry $32, GCS $7, Secret Manager $5 ≈ **~$90/mo unattributable**.

Proposed taxonomy: `billing_service` (`nba|mlb|shared|sideproject`), `phase` (`p1_scrapers`…`p6_publishing`, `orchestration`, `monitoring`, `ml`), `environment`.

> **Do not label BigQuery query jobs.** Query cost is attributed by *job* labels, not dataset labels; the repo has **5,210 `QueryJobConfig` sites and no central client wrapper**. That is a large refactor for $29/mo (3% of spend). Use `INFORMATION_SCHEMA.JOBS` instead — `monitoring/bigquery_cost_tracker.py` already does. Cloud Scheduler jobs do not support user labels at all; cap that spend by pruning jobs.

### Review ritual

- **Daily, automated:** the CF posts to `#nba-alerts` only on anomaly. Silence = healthy. No new habit required — this is the layer that actually protects
- **Weekly, manual:** a `/cost-check` skill alongside `/daily-steering`. Catches slow ramps that never trip a daily threshold
- **Monthly, in the handoff doc:** one line — actual vs budget, top mover, label drift
- **Season open/close:** revisit budget amounts (the auto-seasonal budget absorbs most of this)

Runbook placement: `docs/02-operations/runbooks/cost-controls.md`, matching `halt-mode-operations.md` and `observability-alerts.md`.

---

## 11. October Restore Requirements

Anything cut for the off-season must come back before the 2026-27 opener (Oct 21). Source: `docs/02-operations/scheduler-restore-manifest-2026.md` (58 jobs, waves A/B/C) and `docs/runbooks/nba-offseason-2026-reenable.md`.

### Restore-wave costs

| Wave | Timing | Jobs | Scheduler $/mo | Triggered compute | **Total $/mo** |
|---|---|---|---|---|---|
| **A** — data collection | T-14 to T-10 | 19 | $1.90 | scrapers $10, phase2 $25-45 | **$40–60** |
| **B** — analytics + feature store | T-7 | 18 | $1.80 | phase3 $65-130, phase4 $35-60 | **$110–190** ← most expensive |
| **C** — predictions + exports | T-3 to opening night | 21 | $2.10 | prediction-worker $110, exports $10 | **$125–145** |
| Wave-independent overhead | — | — | — | BQ analysis $50-180, Logging $25-68, Cloud Build $23-33 | **$150–250** |

### Items to add to the restore manifest from this audit

| Item | Why |
|---|---|
| `prediction-coordinator` → `min-instances=1` | Cut in Tier 1.2. Also revert `bin/deploy-service.sh` if edited |
| 3 orchestrators → `min-instances=1` **or** confirm `--retry` is enabled | Cut in Tier 2.1. `--retry` is the better permanent answer |
| `stalled-batch-cleanup`, `prediction-stall-check` | Paused in Tier 1.4 |
| `nba-auto-batch-cleanup-trigger` | Paused in Tier 1.4 |

### Restore-time traps

1. **Do NOT resume `nba-pipeline-canary-trigger` / `-routine-trigger`** until the image fix (commit `f51742b7`) is verified deployed — it was $20/mo of 100%-failing executions
2. **Loop B is still armed.** `gap-detector-30min`, `expected-outputs-planner-nightly`, `phase-completion-reconciler-30min` are enabled today. Add a budget alert on `backfill-pubsub-subscriber` — a flat, always-on CF cost is the signature
3. **`phase4-precompute` has an unexplained latency regression** since ~May 31 (60–220s per `/process-date`, 3× cost on +12% volume). At in-season volume this multiplies directly into the bill. **Highest-leverage unfixed item in the forecast**
4. **`nba-monitoring-alerts` has broken queries** (`Unrecognized name: is_correct`, `Dataset ml_nba was not found`). Fix before trusting alerts in season

### Items worth questioning before restoring

| Job | Concern |
|---|---|
| `execute-workflows` (`5 0-23 * * *`) | 720 invocations/month, 24×/day including no-game days. Add a game-day guard |
| 4× `ml-feature-store-*` daily | Four full feature-store rebuilds/day against a 2 GiB service. Does the 1 PM rebuild change any pick? |
| `phase4-timeout-check-job` (`*/15`) | 2,880 invocations/month, year-round schedule |
| `live-export-evening` / `-late-night` (`*/3`) | ~6,000+ invocations/month. **UI feature, zero effect on pick quality** |
| `grading-readiness-check` (`*/15`) | Manifest concedes the eventarc path is primary; this is a 20×/night backstop |
| `kalshi-props-scraper` | Manifest: "ZERO consumers in ml/, shared/, precompute, publishing" |
| 31 MLB schedulers | Currently enabled for a strategy-halted sport with 5 documented no-edge confirmations |

---

## 12. Appendix

### 12.1 Billing export quirks — required reading before querying

1. **Partitioned on `_PARTITIONTIME` (ingestion time), NOT `usage_start_time`.** `timePartitioning` has no `field`, and `requirePartitionFilter` is **not** set — a query filtering only `usage_start_time` silently scans all 3.45 GB with no warning. Always filter `_PARTITIONTIME`, padded ~4 days wider than the usage window, because rows for one usage day arrive across several ingestion days.
2. **Credits are a nested ARRAY and are NEGATIVE — UNNEST and ADD, do not subtract:**
   ```sql
   cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0) AS net_cost
   ```
   Bare `cost` overstates spend (60d: $1,481 gross vs $1,459 net). Wrong sign doubles the error.
3. **~1 day lag, and the most recent day is partial.** Use **D-2** for comparisons.
4. **This is a `_resource_` export**, not the standard export — it carries `resource.name`/`resource.global_name` for per-instance attribution, 5.2M rows. Queries written against a standard-export schema will not map cleanly. `project.id` is nullable on a small number of account-level rows; filter `project.id IS NOT NULL` when grouping by project.

### 12.2 Method

Ten parallel agents, each read-only, covering: Cloud Run (nba-props-platform) · the `infinite-case` project · Cloud Functions (all projects) · July 4 cliff forensics · BigQuery · the long tail (logging, scheduler, Artifact Registry, GCS, secrets) · Cloud SQL and always-on resources · non-NBA projects and hidden-spend hunt · seasonality forecasting · budgets and guardrails.

Sources: the resource-level billing export (Jan 31 – Jul 21 2026), live `gcloud` inventory across 5 projects and 8 locations, Cloud Monitoring metrics, Cloud Audit Logs, Cloud Logging, `INFORMATION_SCHEMA.JOBS_BY_PROJECT`, repo git history, and the June 2026 Console invoice.

### 12.3 Contradictions resolved during the audit

| Claim | Resolution |
|---|---|
| "Stopping Cloud SQL saves ~$9/mo" | **Refuted.** Measured on `memberradar-db`: saves $0.43/mo. IP reservation charge replaces the instance charge |
| "No budgets exist" | **Wrong.** 8 exist on `01169A`. The `budgets list` failure was on the *other* two accounts (Budget API disabled) |
| "infinite-case has no billing export" | **Wrong.** The export exists and is populated back to January |
| "January was a partial month" | **It is a single day** — export enabled 2026-01-31 |
| June `nba-props-platform` = $641.75 vs invoice $636.02 | Invoice-period vs usage-date grouping. Δ $5.73, immaterial |
| memberradar Cloud SQL $10.76 vs $7.50/mo | Different measurement windows (Jul 1-3 rate vs Jul MTD). Range is $7.50–10.76 |

### 12.4 Known unknowns

- **The $21.60/game-day variable rate** is measured from one season that included heavy backfills and abnormal deploy churn. **±20%**
- **Whether Cloud Scheduler bills PAUSED jobs** is inferred from billing math, not documentation. **±$6/mo**
- **`jett-prod`, `dmhr-platform`, `jig-hq-demo` costs are resource-based estimates**, not measured — those billing accounts have no export
- **Whether free-trial credit is masking spend** on accounts `012771` and `017067` — requires the Console Credits page
- **Cold-start latency for `prediction-coordinator`** is unmeasured; the "low risk" rating reasons from its trigger pattern (scheduler/Pub-Sub batch orchestration), not a timed test
- **The cause of `backfill-pubsub-subscriber` self-resolving on July 4** was not established — most likely off-season date-grid rows aging out, but worth confirming it was not a silently-disabled backfill path needed in October
- **`phase4-precompute`'s May 31 latency regression** is undiagnosed

### 12.5 Non-cost findings surfaced

Ranked by severity. None of these are about money.

1. **`infinitecase-db` has no backups and no PITR.** Zero backups exist. The database used for ad-hoc case processing has no recovery point
2. **`urcwest`'s `backupFirestoreCron` has been failing daily with `PERMISSION_DENIED`** (21 errors in 7 days). Silently broken Firestore backups
3. **Two live alert-emitting Cloud Functions have no source code** — `box-score-completeness-alert`, `phase4-failure-alert`. Undebuggable by construction
4. **`bin/cleanup-artifact-registry.sh` silently skips the largest repo** — hardcoded `REPOS`/`REGION` mean 42.5 GB has never been pruned while the weekly job reports success
5. **`nba-monitoring-alerts` has broken queries** — `Unrecognized name: is_correct`, `Dataset ml_nba was not found`
6. **`nba-grading-alerts` (NBA code) is deployed in the `urcwest` project** — invisible to NBA deployment-drift checks
7. **Both Cloud SQL instances have unlimited `storageAutoResize` and no deletion protection**
8. **`nba_predictions.ml_feature_store_v2` is unpartitioned** — every query full-scans it
9. **`nba_raw.bluesky_nba_news` does not exist** — its writer job has run 8h/day for 17 days
10. **2.29M Firestore writes in an off-season month** (76K/day, zero games) — unexplained

---

*Generated 2026-07-21. No changes applied.*
