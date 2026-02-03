# Cost Optimization Guide

## Overview

This guide documents cost optimization strategies for the NBA Props Platform running on Google Cloud Platform. The platform processes sports data through a multi-phase pipeline using BigQuery, Cloud Run, Cloud Functions, and Cloud Storage.

**Estimated Annual Savings from Implemented Optimizations: $15,000+**

---

## Table of Contents

1. [BigQuery Optimization](#bigquery-optimization)
2. [Cloud Run Sizing](#cloud-run-sizing)
3. [Cloud Function Memory Tuning](#cloud-function-memory-tuning)
4. [GCS Storage Lifecycle Policies](#gcs-storage-lifecycle-policies)
5. [Batch vs Real-Time Tradeoffs](#batch-vs-real-time-tradeoffs)
6. [Monitoring Costs](#monitoring-costs)
7. [Cost Tracking Tools](#cost-tracking-tools)

---

## BigQuery Optimization

BigQuery is the primary data warehouse and typically the largest cost driver. On-demand pricing is **$6.25 per TB** processed.

### 1. Partitioning Strategy

**Always partition tables by date.** The platform uses `game_date` as the primary partition column.

```sql
-- Example: Partitioned table definition
CREATE TABLE nba_raw.nbac_schedule
(
  game_date DATE,
  game_id STRING,
  ...
)
PARTITION BY game_date
CLUSTER BY home_team_abbr, away_team_abbr;
```

**Key Patterns in the Codebase:**

| Table Type | Partition Column | Rationale |
|-----------|-----------------|-----------|
| Raw data tables | `game_date` | Daily data ingestion pattern |
| Analytics tables | `game_date` | Date-scoped processing |
| Predictions | `game_date` | Daily prediction generation |
| Grading | `game_date` | Post-game result processing |

**Cost Impact:** Partitioning can reduce query costs by 90%+ by scanning only relevant partitions.

### 2. Clustering Strategy

Cluster tables by frequently filtered columns after the partition column.

**Recommended Clustering:**

```sql
-- Player-centric tables
CLUSTER BY player_id, team_abbr

-- Game-centric tables
CLUSTER BY home_team_abbr, away_team_abbr

-- Prediction tables
CLUSTER BY player_lookup, prop_type
```

**Reference:** See query patterns in `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`:
```python
WHERE game_date = '{game_date}'  -- Partition pruning
  AND player_lookup = '{player}'  -- Cluster pruning
```

### 3. Query Pattern Best Practices

**DO: Always filter by partition column first**
```sql
-- GOOD: Partition filter applied first
SELECT *
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-01-23'
  AND player_id = 'abc123'
```

**DON'T: Query without partition filter**
```sql
-- BAD: Full table scan - expensive!
SELECT *
FROM nba_analytics.player_game_summary
WHERE player_id = 'abc123'
```

**DO: Use parameterized queries for caching**
```python
# GOOD: Uses query cache
job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ScalarQueryParameter("game_date", "DATE", target_date)
    ]
)
query = "SELECT * FROM table WHERE game_date = @game_date"
```

**DO: Limit SELECT columns**
```sql
-- GOOD: Select only needed columns
SELECT game_date, player_id, points, rebounds
FROM nba_analytics.player_game_summary
WHERE game_date = @game_date

-- BAD: SELECT * when you don't need all columns
SELECT * FROM nba_analytics.player_game_summary
```

### 4. Cache Optimization

BigQuery caches query results for 24 hours (free of charge).

**Current Cache Hit Rate:** Check using `monitoring/bigquery_cost_tracker.py`

```bash
# View cache hit statistics
python monitoring/bigquery_cost_tracker.py --days 7
```

**Improve Cache Hits:**
- Use identical query text (including whitespace)
- Use parameterized queries
- Avoid `CURRENT_TIMESTAMP()` in queries (use explicit dates)

### 5. Batch Loading vs Streaming

| Method | Cost | Use Case |
|--------|------|----------|
| Batch Load | Free | Daily data loads, backfills |
| Streaming Insert | $0.05/GB | Real-time requirements only |

**Platform Pattern:** Uses batch loading for all raw data ingestion.

Reference: `predictions/coordinator/batch_staging_writer.py`
```python
# Uses load_table_from_json (batch - free) instead of streaming
result = writer.write_to_staging(predictions, batch_id, worker_id)
```

### 6. Expensive Query Monitoring

The codebase includes a BigQuery cost tracker at `monitoring/bigquery_cost_tracker.py`:

```bash
# Find most expensive queries
python monitoring/bigquery_cost_tracker.py --expensive --days 7

# Get full cost report
python monitoring/bigquery_cost_tracker.py --days 30
```

---

## Cloud Run Sizing

Cloud Run charges for vCPU and memory per second of execution. Proper sizing reduces costs significantly.

### Current Configurations

| Service | CPU | Memory | Timeout | Notes |
|---------|-----|--------|---------|-------|
| MLB Freshness Checker | 1000m | 384Mi | 5 min | Optimized from 512Mi |
| MLB Schedule Validator | 1000m | 256Mi | 10 min | Lightweight validation |
| MLB Prediction Coverage | 1000m | 384Mi | 5 min | Monitoring job |
| MLB Gap Detection | 1000m | 384Mi | 5 min | Monitoring job |

### Sizing Recommendations

**1. Start Small, Scale Up**
```yaml
resources:
  limits:
    cpu: "1000m"      # 1 vCPU is sufficient for most tasks
    memory: "256Mi"   # Start here, increase if OOM
```

**2. Memory Sizing Guide**

| Workload Type | Recommended Memory | Example |
|---------------|-------------------|---------|
| Simple validation | 256Mi | Schedule validators |
| Data transformation | 384-512Mi | Analytics processors |
| ML inference | 512Mi-1Gi | Prediction workers |
| Heavy data processing | 1-2Gi | Backfill jobs |

**3. Use Gen2 Execution Environment**
```yaml
annotations:
  run.googleapis.com/execution-environment: gen2
```
Gen2 provides faster cold starts and better performance at the same cost.

**4. Set Appropriate Timeouts**
```yaml
timeoutSeconds: 300  # 5 minutes for quick jobs
timeoutSeconds: 600  # 10 minutes for validators
timeoutSeconds: 900  # 15 minutes for complex processing
```

**5. Minimize Concurrency for Cost**
```yaml
spec:
  taskCount: 1  # Run single instance for batch jobs
```

### Cloud Run Jobs vs Services

| Use Case | Type | Pricing |
|----------|------|---------|
| Scheduled tasks | Jobs | Pay only during execution |
| HTTP endpoints | Services | Pay for requests + idle time |

**Recommendation:** Use Cloud Run Jobs for scheduled work (validators, monitors).

---

## Cloud Function Memory Tuning

Cloud Functions charge based on GB-seconds (memory x execution time).

### Current Configurations

Reference: `config/phase6_publishing.yaml`

```yaml
cloud_function:
  name: "phase6-daily-export"
  runtime: "python310"
  memory: "512MB"
  timeout: "540s"  # 9 minutes
```

```yaml
# Live export function - needs lower latency
cloud_function:
  name: "live-export"
  memory: "512MB"
  timeout: "120s"
  max_instances: 5
```

### Memory Sizing Guidelines

| Function Type | Memory | CPU Allocation |
|--------------|--------|----------------|
| HTTP triggers (fast) | 256-512MB | 0.167 vCPU |
| Data processing | 512MB-1GB | 0.5-1 vCPU |
| ML/heavy processing | 1-2GB | 1 vCPU |

**Memory-CPU Relationship:**
- 128MB = 0.083 vCPU
- 256MB = 0.167 vCPU
- 512MB = 0.333 vCPU
- 1024MB = 0.583 vCPU
- 2048MB = 1 vCPU

### Optimization Strategies

**1. Right-size memory based on actual usage**
```bash
# Check function metrics in Cloud Console:
# Cloud Functions > Function > Metrics > Memory utilization
```

**2. Use Gen2 runtime for better cold starts**
```yaml
runtime: "python311"  # Gen2 compatible
```

**3. Set max_instances to prevent runaway costs**
```yaml
max_instances: 5  # Prevent cost explosion during traffic spikes
```

**4. Use HTTP triggers for lower latency**
```yaml
trigger: "http"  # Lower latency than Pub/Sub
```

---

## GCS Storage Lifecycle Policies

Storage costs add up over time. Lifecycle policies automatically move or delete data.

### Implemented Policies

Reference: `infra/gcs_lifecycle.tf`

**Estimated Annual Savings: $4,200/year**

| Bucket | Nearline Age | Delete Age | Annual Savings |
|--------|-------------|------------|----------------|
| nba-scraped-data | 30 days | 90 days | $2,400 |
| mlb-scraped-data | 30 days | 90 days | $800 |
| nba-analytics-raw-data | 14 days | 60 days | $600 |
| nba-analytics-processed-data | 30 days | 90 days | $300 |
| nba-bigquery-backups | 7d/30d/90d | 365 days | $100 |
| nba-ml-models | 90 days | Manual | Minimal |
| nba-temp-migration | - | 7 days | Minimal |

### Storage Class Pricing

| Class | Price/GB/month | Use Case |
|-------|---------------|----------|
| Standard | $0.020 | Active data |
| Nearline | $0.010 | Access < 1x/month |
| Coldline | $0.004 | Access < 1x/quarter |
| Archive | $0.0012 | Access < 1x/year |

### Lifecycle Policy Examples

**1. Raw Scraped Data (30 days active, 90 days total)**
```terraform
lifecycle_rule {
  condition {
    age = 30
  }
  action {
    type          = "SetStorageClass"
    storage_class = "NEARLINE"
  }
}

lifecycle_rule {
  condition {
    age = 90
  }
  action {
    type = "Delete"
  }
}
```

**2. Backup Data (Tiered archival)**
```terraform
lifecycle_rule {
  condition { age = 7 }
  action {
    type          = "SetStorageClass"
    storage_class = "NEARLINE"
  }
}

lifecycle_rule {
  condition { age = 30 }
  action {
    type          = "SetStorageClass"
    storage_class = "COLDLINE"
  }
}

lifecycle_rule {
  condition { age = 90 }
  action {
    type          = "SetStorageClass"
    storage_class = "ARCHIVE"
  }
}
```

### Verification Commands

```bash
# Check lifecycle policy
gsutil lifecycle get gs://nba-scraped-data

# Check bucket size
gsutil du -s gs://nba-scraped-data

# List objects by age
gsutil ls -L gs://nba-scraped-data/** | grep "Time created"
```

---

## Batch vs Real-Time Tradeoffs

### Cost Comparison

| Pattern | Cost | Latency | Use Case |
|---------|------|---------|----------|
| Batch (scheduled) | Lowest | Hours | Historical data, backfills |
| Near-real-time | Medium | Minutes | Daily predictions |
| Real-time (streaming) | Highest | Seconds | Live scores |

### Platform Patterns

**1. Batch Processing (Cost-Optimized)**

Most data processing uses batch patterns:
- Scrapers run on schedule (Cloud Scheduler triggers)
- Analytics processors batch by game_date
- Predictions run once per day per game

Reference: `shared/config/scraper_retry_config.yaml`
```yaml
retry_windows:
  - time: "10:00"
    name: "bdl_catchup_midday"
  - time: "14:00"
    name: "bdl_catchup_afternoon"
  - time: "18:00"
    name: "bdl_catchup_evening"
```

**2. Near-Real-Time (Balanced)**

For time-sensitive data like predictions:
- Pub/Sub triggers between phases
- 5-10 minute processing windows
- Event-driven orchestration

**3. Real-Time (When Necessary)**

Only for live game requirements:
```yaml
# Live scores export - every 3 minutes during games
schedule:
  evening:
    cron: "*/3 19-23 * * *"
  late_night:
    cron: "*/3 0-1 * * *"
```

### Decision Framework

Choose **Batch** when:
- Data freshness > 1 hour is acceptable
- Processing large volumes
- Cost is primary concern

Choose **Near-Real-Time** when:
- Data freshness 5-30 minutes required
- Event-driven processing fits workflow
- Moderate cost tolerance

Choose **Real-Time** when:
- Sub-minute freshness required
- User-facing live features
- Higher cost justified by business value

---

## Monitoring Costs

### Cloud Monitoring Pricing

| Feature | Free Tier | Paid |
|---------|-----------|------|
| Logs ingestion | 50 GB/month | $0.50/GB |
| Metrics ingestion | First 150 MB | $0.258/MB |
| Custom metrics | 10,000 time series | $0.10 per 1,000 |

### Cost Reduction Strategies

**1. Log Exclusion Filters**
```bash
# Exclude verbose logs
gcloud logging sinks update _Default \
  --log-filter='NOT severity="DEBUG"'
```

**2. Reduce Log Verbosity in Code**
Reference: `scrapers/scraper_base.py`
```python
# Production uses lower sample rates
traces_sample_rate=1.0 if ENV == "development" else 0.1,
profiles_sample_rate=1.0 if ENV == "development" else 0.01,
```

**3. Aggregate Metrics**
- Use pre-aggregated custom metrics
- Avoid high-cardinality labels
- Sample instead of logging every event

**4. Set Log Retention Appropriately**
```bash
# 30 days is often sufficient for operational logs
gcloud logging sinks update _Default \
  --retention-days=30
```

### Alert Policies

Reference: `monitoring/alert-policies/`

Keep alerts focused and actionable to avoid alert fatigue and unnecessary computation:
- Alert on errors, not warnings
- Use meaningful thresholds
- Group related alerts

---

## Cost Tracking Tools

### BigQuery Cost Tracker

The platform includes a built-in cost tracker at `monitoring/bigquery_cost_tracker.py`.

**Usage:**
```bash
# Daily cost report
python monitoring/bigquery_cost_tracker.py --days 7

# JSON output for dashboards
python monitoring/bigquery_cost_tracker.py --json --days 30

# Find expensive queries
python monitoring/bigquery_cost_tracker.py --expensive

# Summary only
python monitoring/bigquery_cost_tracker.py --summary
```

**Output Includes:**
- Total queries and bytes processed
- Estimated costs (at $6.25/TB)
- Cache hit rates
- Costs by dataset
- Costs by service account
- Most expensive queries

### GCP Billing Reports

1. **Console:** Billing > Reports
2. **BigQuery Export:** Enable billing export to BigQuery for detailed analysis
3. **Budgets:** Set budget alerts at 50%, 90%, 100% of expected spend

### Recommended Alerts

Set up billing alerts:
```bash
# Create budget alert
gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="NBA Props Monthly Budget" \
  --budget-amount=500USD \
  --threshold-rule=percent=50 \
  --threshold-rule=percent=90 \
  --threshold-rule=percent=100
```

---

## Summary: Quick Wins

### Immediate Actions (No Code Changes)

1. **Enable lifecycle policies** on GCS buckets (saves $4,200/year)
2. **Set billing alerts** at 50%, 90%, 100% thresholds
3. **Review expensive queries** weekly using cost tracker

### Code-Level Optimizations

1. **Always use partition filters** in BigQuery queries
2. **Use batch loading** instead of streaming inserts
3. **Right-size Cloud Run/Functions** memory allocations
4. **Reduce log verbosity** in production

### Architecture Decisions

1. **Prefer batch processing** unless real-time is required
2. **Use Cloud Run Jobs** for scheduled tasks (not Services)
3. **Implement request caching** where possible
4. **Consolidate small writes** into batch operations

---

## References

- GCP Pricing Calculator: https://cloud.google.com/products/calculator
- BigQuery Pricing: https://cloud.google.com/bigquery/pricing
- Cloud Run Pricing: https://cloud.google.com/run/pricing
- Cloud Functions Pricing: https://cloud.google.com/functions/pricing
- Cloud Storage Pricing: https://cloud.google.com/storage/pricing

---

*Last Updated: January 2026*
*Maintained by: Platform Team*
