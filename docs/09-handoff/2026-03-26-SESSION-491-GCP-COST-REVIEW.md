# Session 491 Handoff — GCP Cost Structure Review

**Date:** 2026-03-26
**Goal:** Review current GCP spend, identify the biggest cost drivers, and find optimization opportunities.

---

## Project Details

```
Project ID:  nba-props-platform
Primary region: us-west2
Secondary region: us-central1 (some Cloud Schedulers)
Billing account: check in GCP Console → Billing
```

---

## Start Here — Pull the Bills

```bash
# Current month spend by service
gcloud billing budgets list --billing-account=BILLING_ACCOUNT_ID

# Or go straight to BigQuery cost breakdown
bq query --project_id=nba-props-platform --use_legacy_sql=false \
"SELECT service.description, SUM(cost) as total_cost,
        SUM(cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) as net_cost
 FROM \`nba-props-platform.billing_export.gcp_billing_export_v1_*\`
 WHERE DATE(_PARTITIONTIME) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
 GROUP BY 1 ORDER BY 2 DESC"

# If billing export isn't set up, check console:
# https://console.cloud.google.com/billing → nba-props-platform → Reports
```

---

## Full Inventory of Running Resources

### Cloud Run Services (us-west2)

| Service | Purpose | Always-on? |
|---------|---------|-----------|
| `prediction-coordinator` | Phase 5 orchestration | No — triggered |
| `prediction-worker` | CatBoost/LGBM predictions | No — triggered |
| `nba-phase3-analytics-processors` | Phase 3 analytics | No — triggered |
| `nba-phase4-precompute-processors` | Phase 4 precompute | No — triggered |
| `nba-phase2-raw-processors` | Phase 2 raw ingestion | No — triggered |
| `nba-scrapers` | Phase 1 scraping | No — triggered |
| `nba-grading-service` | Grading | No — triggered |
| `mlb-prediction-worker` | MLB strikeout predictions | No — triggered |

```bash
# Check min instances (min-instances > 0 = always paying)
gcloud run services list --region=us-west2 --project=nba-props-platform \
  --format="table(metadata.name,spec.template.metadata.annotations['autoscaling.knative.dev/minScale'],spec.template.spec.containers[0].resources.limits.memory,spec.template.spec.containers[0].resources.limits.cpu)"
```

### Cloud Functions (~20 active, us-west2)

Key expensive ones to check:
- `weekly-retrain` — 4GiB / 1800s timeout, runs every Monday
- `phase6-export` — runs multiple times daily
- `self-heal-predictions` — runs every 15 min
- `pipeline-canary-queries` — runs every 30 min
- `live-freshness-monitor` — runs frequently during game hours
- `decay-detection` — daily 11 AM ET
- `filter-counterfactual-evaluator` — daily 11:30 AM ET

```bash
# List all CFs with memory/CPU
gcloud functions list --project=nba-props-platform --format="table(name,status,runtime,serviceConfig.availableMemory,serviceConfig.timeoutSeconds)"
```

### BigQuery (4 datasets)

| Dataset | Contents | Size concern? |
|---------|---------|--------------|
| `nba_predictions` | predictions, feature store, best bets | HIGH — 419K+ records in prediction_accuracy alone |
| `nba_raw` | scraped data from 40+ scrapers | HIGH — daily ingestion |
| `nba_analytics` | player/team game summaries | MEDIUM |
| `nba_orchestration` | phase completion logs | LOW |
| `mlb_predictions` | MLB pitcher strikeout predictions | GROWING |

```bash
# Table sizes and costs
bq query --project_id=nba-props-platform --use_legacy_sql=false \
"SELECT table_catalog, table_schema, table_name,
        ROUND(size_bytes / POW(10,9), 3) as size_gb,
        row_count
 FROM nba_predictions.INFORMATION_SCHEMA.TABLE_STORAGE
 ORDER BY size_bytes DESC LIMIT 20"

# Query costs this month (if INFORMATION_SCHEMA.JOBS available)
bq query --project_id=nba-props-platform --use_legacy_sql=false \
"SELECT user_email,
        ROUND(SUM(total_bytes_billed)/POW(10,12)*5, 2) as estimated_cost_usd,
        COUNT(*) as query_count,
        ROUND(SUM(total_bytes_billed)/POW(10,9), 1) as total_gb_billed
 FROM \`region-us-west2\`.INFORMATION_SCHEMA.JOBS
 WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
   AND job_type = 'QUERY'
 GROUP BY 1 ORDER BY 2 DESC LIMIT 20"
```

### GCS Buckets

```bash
# Storage sizes
gcloud storage du gs://nba-props-platform-api --project=nba-props-platform --summarize
gcloud storage ls --project=nba-props-platform  # list all buckets first
```

### Cloud Scheduler (30+ jobs)

```bash
# All scheduler jobs across all regions
gcloud scheduler jobs list --project=nba-props-platform --location=us-west2 \
  --format="table(name,schedule,state)" | wc -l

gcloud scheduler jobs list --project=nba-props-platform --location=us-central1 \
  --format="table(name,schedule,state)"
```

### Cloud Build

- Triggers on every push to main — deploys ALL changed services
- ~8-10 min per build, multiple parallel builds
- Uses `us-west2-docker.pkg.dev/nba-props-platform/nba-props` Artifact Registry

```bash
# Recent build count/duration (proxy for cost)
gcloud builds list --region=us-west2 --project=nba-props-platform \
  --limit=50 --format="table(id,status,createTime,duration,tags)"
```

### Pub/Sub Topics

High-frequency topics to check:
- `nba-phase3-analytics-sub` — fires after every Phase 2 completion
- `nba-phase6-export-trigger` — multiple times daily
- Canary queries publish to monitoring topics every 30 min

```bash
gcloud pubsub topics list --project=nba-props-platform
```

---

## Known Cost Risks

### 1. BigQuery query costs
- `prediction_accuracy` has 419K+ rows — unfiltered queries are expensive
- All queries MUST have `WHERE game_date >= ...` partition filters
- Feature store queries on `ml_feature_store_v2` are large
- Check if any dashboards/monitoring tools are running unoptimized queries

### 2. Self-healing / canary frequency
- `self-heal-predictions` runs every 15 min (96x/day)
- `pipeline-canary-queries` runs every 30 min (48x/day)
- Each invokes BQ queries — check bytes billed per invocation

### 3. weekly-retrain CF memory
- `weekly-retrain` is configured at 4GiB / 1800s
- Runs every Monday — check if the memory/timeout is actually needed

### 4. MLB worker (new)
- `mlb-prediction-worker` added recently — check its resource config
- MLB schedulers resumed March 24 — 30 jobs now active

### 5. Artifact Registry storage
- Docker images accumulate on every deploy — check if old images are being pruned

```bash
# Check image count
gcloud artifacts docker images list \
  us-west2-docker.pkg.dev/nba-props-platform/nba-props \
  --format="table(IMAGE,CREATE_TIME)" | wc -l
```

### 6. Cloud Run idle charges
- If any service has `min-instances >= 1`, it runs 24/7
- Check for accidentally set min-instances

---

## Key Commands for the Review

```bash
# 1. All Cloud Run min-instance configs
gcloud run services list --region=us-west2 --project=nba-props-platform \
  --format=json | python3 -c "
import sys, json
svcs = json.load(sys.stdin)
for s in svcs:
    name = s['metadata']['name']
    ann = s['spec']['template']['metadata'].get('annotations', {})
    min_inst = ann.get('autoscaling.knative.dev/minScale', '0')
    mem = s['spec']['template']['spec']['containers'][0]['resources']['limits'].get('memory', '?')
    cpu = s['spec']['template']['spec']['containers'][0]['resources']['limits'].get('cpu', '?')
    print(f'{name}: min={min_inst}, mem={mem}, cpu={cpu}')
"

# 2. BQ slot usage (if using on-demand pricing)
bq query --project_id=nba-props-platform --use_legacy_sql=false \
"SELECT DATE(creation_time) as date,
        COUNT(*) as queries,
        ROUND(SUM(total_bytes_billed)/POW(10,9),1) as gb_billed,
        ROUND(SUM(total_bytes_billed)/POW(10,12)*5, 2) as est_cost_usd
 FROM \`region-us-west2\`.INFORMATION_SCHEMA.JOBS
 WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
   AND job_type = 'QUERY' AND error_result IS NULL
 GROUP BY 1 ORDER BY 1 DESC"

# 3. Most expensive individual queries
bq query --project_id=nba-props-platform --use_legacy_sql=false \
"SELECT SUBSTR(query, 0, 120) as query_snippet,
        ROUND(total_bytes_billed/POW(10,9),2) as gb_billed,
        user_email, creation_time
 FROM \`region-us-west2\`.INFORMATION_SCHEMA.JOBS
 WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
   AND job_type = 'QUERY'
 ORDER BY total_bytes_billed DESC LIMIT 20"

# 4. CF invocation counts
gcloud logging read 'resource.type="cloud_function" severity="INFO"' \
  --project=nba-props-platform --limit=1000 \
  --format="value(resource.labels.function_name)" | sort | uniq -c | sort -rn | head -20
```

---

## What to Look For

1. **Biggest line items** in the billing report — usually BigQuery or Cloud Run
2. **Any service with min-instances > 0** — paying 24/7
3. **Unpartitioned BQ queries** — `total_bytes_billed` > 1GB per query is a red flag
4. **High-frequency CF invocations** hitting BQ — canaries, monitors
5. **Docker image bloat** in Artifact Registry
6. **Unused resources** — disabled scrapers still deployed, old CF versions

---

## Context from Previous Sessions

- All 30 MLB schedulers ENABLED as of March 24 — this is new load
- `weekly-retrain` CF: 4GiB memory, runs Monday 5 AM ET — check if it actually needs 4GiB
- 10+ shadow models are enabled — each prediction worker call queries all of them
- `model_performance_daily` and `signal_health_daily` are populated after every grading run
- Phase 6 export now runs for BOTH NBA and MLB (`sport:mlb` message added this session)
