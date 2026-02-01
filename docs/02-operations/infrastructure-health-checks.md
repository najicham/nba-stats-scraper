# Infrastructure Health Checks

**Purpose:** Quick reference for running systematic infrastructure health audits

**When to Use:**
- After major deployments
- When investigating production issues
- Monthly infrastructure reviews
- Before important events (playoffs, etc.)

**Time Required:** 20-30 minutes for full audit

---

## Quick Health Audit Checklist

| Component | Check | Expected | Command/Query |
|-----------|-------|----------|---------------|
| **BigQuery** | Query costs (7 days) | <$50 | See 1.1 |
| **BigQuery** | Staging tables | <10 | See 1.2 |
| **Cloud Run** | Deployment drift | All current | See 2.1 |
| **Cloud Run** | Error rate | <1% | See 2.2 |
| **GCS** | Bucket sizes | <5 TB total | See 3.1 |
| **Logs** | Unidentified errors | 0 | See 4.1 |
| **Costs** | Monthly spending | <$500 | See 5.1 |
| **Monitoring** | Metrics recording | All services | See 6.1 |

---

## 1. BigQuery Health

### 1.1 - Find Expensive Queries

**Check:** Identify queries that processed >100 GB in past 7 days

```bash
bq query --use_legacy_sql=false "
SELECT
  user_email,
  SUBSTR(query, 1, 100) as query_preview,
  total_bytes_processed / POW(10, 9) as gb_processed,
  ROUND(total_bytes_processed / POW(10, 12) * 6.25, 2) as cost_usd,
  creation_time
FROM \`nba-props-platform.region-us-west2.INFORMATION_SCHEMA.JOBS_BY_PROJECT\`
WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND job_type = 'QUERY'
  AND total_bytes_processed > 100000000000  -- >100 GB
ORDER BY total_bytes_processed DESC
LIMIT 20"
```

**What to Look For:**
- Queries processing >1 TB (>$6 cost)
- Repeated expensive queries (optimization opportunity)
- Queries missing partition filters (`WHERE game_date >= ...`)

**Common Issues:**
- Forgetting partition filter on `nba_raw.*` tables
- Full table scans when indexes would help
- Redundant queries (caching opportunity)

---

### 1.2 - Find Staging/Temp Tables

**Check:** Count temporary tables taking up storage

```bash
# Check each dataset for staging tables
for dataset in nba_raw nba_analytics nba_precompute nba_predictions nba_orchestration; do
  echo "=== $dataset ==="
  bq ls --max_results=1000 $dataset | \
    grep -E "_temp|_staging|_backup|_old|_test" | \
    wc -l
done

# Show largest staging tables
bq ls --max_results=1000 nba_raw --format=json | \
  jq -r '.[] | select(.tableReference.tableId | test("_temp|_staging|_backup")) |
    [.tableReference.tableId, .numBytes, .lastModifiedTime] | @tsv' | \
  sort -k2 -rn | head -20
```

**What to Look For:**
- >10 staging tables in any dataset
- Staging tables >30 days old
- Staging tables >100 GB

**Cleanup:**
```bash
# Delete old staging tables (BE CAREFUL)
# Always verify table contents first!
bq rm -f nba_raw.table_name_staging_old
```

---

### 1.3 - Check Table Sizes

**Check:** Find largest tables to track storage costs

```bash
bq ls --max_results=1000 nba_raw --format=json | \
  jq -r '.[] | [.tableReference.tableId, (.numBytes | tonumber / 1073741824), .lastModifiedTime] |
    @tsv' | \
  awk '{printf "%-50s %8.2f GB  %s\n", $1, $2, $3}' | \
  sort -k2 -rn | head -20
```

**Expected Top Tables:**
- `bdl_player_boxscores` - 50-100 GB
- `nbac_play_by_play` - 30-50 GB
- `bigdataball_play_by_play` - 20-40 GB

---

## 2. Cloud Run Health

### 2.1 - Check Deployment Drift

**Check:** Verify all services running latest code

```bash
# Use built-in drift checker
./bin/check-deployment-drift.sh --verbose

# Or manually check each service
for service in prediction-worker prediction-coordinator \
               nba-phase3-analytics-processors nba-phase4-precompute-processors; do
  echo "=== $service ==="
  gcloud run services describe $service --region=us-west2 \
    --format="value(metadata.labels.commit-sha,status.latestReadyRevisionName)"
done

# Compare to latest commit
git log -1 --format="%h %s"
```

**What to Look For:**
- Services 10+ commits behind main
- Services missing recent bug fixes
- Services with `BUILD_COMMIT` label missing

**Fix:**
```bash
./bin/deploy-service.sh SERVICE_NAME
```

---

### 2.2 - Check Error Rates

**Check:** Find services with high error rates

```bash
# Count errors by service (last 24 hours)
gcloud logging read 'severity>=ERROR AND resource.type="cloud_run_revision"' \
  --limit=1000 --freshness=24h --format=json | \
  jq -r '.[] | .resource.labels.service_name' | \
  sort | uniq -c | sort -rn

# Get error details for specific service
gcloud logging read 'severity>=ERROR
  AND resource.type="cloud_run_revision"
  AND resource.labels.service_name="prediction-worker"' \
  --limit=50 --freshness=24h --format=json | \
  jq -r '.[] | [.timestamp, .textPayload // .jsonPayload.message] | @tsv'
```

**What to Look For:**
- >10 errors/hour for any service
- Repeated identical errors (systematic issue)
- Permission denied errors
- Timeout errors

**Common Errors:**
- `403 Permission denied` - IAM role missing
- `Exceeded rate limits` - Need batching
- `Timeout exceeded` - Service too slow or timeout too short

---

### 2.3 - Check Old Revisions

**Check:** Count revisions per service (Cloud Run auto-cleans at 1000)

```bash
gcloud run revisions list --region=us-west2 --format=json | \
  jq -r '.[] | .metadata.labels."serving.knative.dev/service"' | \
  sort | uniq -c | sort -rn
```

**What to Look For:**
- >100 revisions (frequent deployments - OK)
- >800 revisions (approaching cleanup threshold)

**Note:** Cloud Run automatically deletes old revisions, no action needed unless approaching 1000.

---

## 3. GCS Health

### 3.1 - Check Bucket Sizes

**Check:** Total storage per bucket

```bash
# List all buckets with sizes
gsutil du -sh gs://nba-*

# Detailed breakdown of largest bucket
gsutil du -sh gs://nba-scraped-data/*
```

**Expected Sizes:**
- `nba-scraped-data` - 1-3 TB (raw scraped data)
- `nba-models-production` - <10 GB (ML models)
- `nba-backups` - 100-500 GB (database backups)

**What to Look For:**
- Unexpected growth (>20% month-over-month)
- Very old data (>2 years) that could be archived
- Duplicate/redundant data

---

### 3.2 - Check Lifecycle Policies

**Check:** Verify lifecycle policies are set

```bash
# Check lifecycle policy for main bucket
gsutil lifecycle get gs://nba-scraped-data

# If no policy set, you'll see error:
# "gs://nba-scraped-data/ has no lifecycle configuration."
```

**Recommended Policy:**
```json
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "SetStorageClass", "storageClass": "COLDLINE"},
        "condition": {"age": 365}
      },
      {
        "action": {"type": "Delete"},
        "condition": {"age": 1095}
      }
    ]
  }
}
```

**Set Policy:**
```bash
# Save policy to file
cat > lifecycle.json << 'EOF'
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "SetStorageClass", "storageClass": "COLDLINE"},
        "condition": {"age": 365}
      }
    ]
  }
}
EOF

# Apply to bucket
gsutil lifecycle set lifecycle.json gs://nba-scraped-data
```

**Cost Savings:** ~$10/month per TB moved to Coldline

---

## 4. Logs and Monitoring

### 4.1 - Find Unidentified Errors

**Check:** Find errors with empty or unhelpful messages

```bash
# Find errors with empty messages
gcloud logging read 'severity>=ERROR AND resource.type="cloud_run_revision"' \
  --limit=500 --freshness=7d --format=json | \
  jq -r '.[] | select(.textPayload == "Error: " or .textPayload == "Error") |
    [.timestamp, .resource.labels.service_name, .textPayload] | @tsv'

# Count by pattern
gcloud logging read 'severity>=ERROR AND resource.type="cloud_run_revision"' \
  --limit=500 --freshness=7d --format=json | \
  jq -r '.[] | .textPayload // .jsonPayload.message' | \
  sort | uniq -c | sort -rn | head -20
```

**What to Look For:**
- Errors with message "Error: " (no context)
- Generic exceptions without stack traces
- >10 occurrences of same unhandled error

**Fix:**
Add error context in code:
```python
try:
    process_data()
except Exception as e:
    # BAD
    logger.error("Error: ")

    # GOOD
    logger.error(f"Failed to process data for player {player_id}: {str(e)}", exc_info=True)
```

---

### 4.2 - Check Monitoring Metrics

**Check:** Verify custom metrics are recording

```bash
# List custom metrics
gcloud monitoring metrics-descriptors list \
  --filter="custom.googleapis.com/prediction" \
  --format="table(type,description)"

# Check recent data points
gcloud monitoring time-series list \
  --filter='metric.type="custom.googleapis.com/prediction/hit_rate"' \
  --interval-start-time="2026-01-28T00:00:00Z" \
  --format=json | \
  jq -r '.[] | .points[] | [.interval.endTime, .value.doubleValue] | @tsv'
```

**Expected Metrics:**
- `prediction/hit_rate`
- `prediction/latency_ms`
- `prediction/confidence_score`
- `prediction/feature_quality`

**If Missing:**
Check monitoring permissions (see CLAUDE.md "Monitoring Permissions Error")

---

## 5. Cost Analysis

### 5.1 - Check Monthly Spending

**Check:** Current month spending by service

```bash
# Get billing account
gcloud beta billing accounts list

# Export to BigQuery for analysis (if not already set up)
# Then query billing data
bq query --use_legacy_sql=false "
SELECT
  service.description as service,
  ROUND(SUM(cost), 2) as total_cost,
  ROUND(SUM(usage.amount), 2) as total_usage
FROM \`nba-props-platform.billing.gcp_billing_export_*\`
WHERE DATE(_PARTITIONTIME) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY service
ORDER BY total_cost DESC"
```

**Expected Top Services:**
- BigQuery - $100-200/month
- Cloud Run - $50-100/month
- Cloud Storage - $30-60/month
- Networking - $20-40/month

**What to Look For:**
- Unexpected spikes (>2x normal)
- New services with high costs
- Total >$500/month

---

### 5.2 - Set Budget Alerts

**Check:** Verify budget alerts are configured

```bash
# List budgets
gcloud billing budgets list --billing-account=BILLING_ACCOUNT_ID
```

**If No Budgets:**
```bash
# Create budget with alert at 80% of $500/month
gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="NBA Props Platform Budget" \
  --budget-amount=500 \
  --threshold-rule=percent=80
```

---

## 6. Firestore Health

### 6.1 - Check Collection Sizes

**Check:** Verify heartbeat collection is not growing unbounded

```bash
# Count documents in processor_heartbeats
gcloud firestore documents list processor_heartbeats --limit=100 2>/dev/null | wc -l

# Expected: ~30 (one per processor)
# If >100: Heartbeat proliferation issue (see CLAUDE.md)
```

**Group by processor:**
```python
from google.cloud import firestore
from collections import Counter

db = firestore.Client(project='nba-props-platform')
docs = list(db.collection('processor_heartbeats').stream())

print(f"Total documents: {len(docs)}")

processor_counts = Counter()
for doc in docs:
    parts = doc.id.split('_')
    processor_name = parts[0] if len(parts) > 0 else doc.id
    processor_counts[processor_name] += 1

print("\nDocuments per processor:")
for processor, count in processor_counts.most_common(10):
    print(f"  {processor}: {count} documents")
```

**Expected:** Each processor = 1 document

**If >1 doc per processor:** Run cleanup script (see Session 61 handoff)

---

## Full Audit Script

**Run all checks in sequence:**

```bash
#!/bin/bash
# infrastructure-health-audit.sh

echo "=== Infrastructure Health Audit ==="
echo "Started: $(date)"
echo ""

echo "1. BigQuery Query Costs (7 days)..."
bq query --use_legacy_sql=false "
SELECT ROUND(SUM(total_bytes_processed / POW(10, 12) * 6.25), 2) as total_cost_usd
FROM \`nba-props-platform.region-us-west2.INFORMATION_SCHEMA.JOBS_BY_PROJECT\`
WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND job_type = 'QUERY'"

echo ""
echo "2. BigQuery Staging Tables..."
for dataset in nba_raw nba_analytics nba_precompute nba_predictions; do
  count=$(bq ls --max_results=1000 $dataset | grep -cE "_temp|_staging|_backup" || echo 0)
  echo "  $dataset: $count staging tables"
done

echo ""
echo "3. Cloud Run Deployment Drift..."
./bin/check-deployment-drift.sh

echo ""
echo "4. Cloud Run Error Counts (24h)..."
gcloud logging read 'severity>=ERROR AND resource.type="cloud_run_revision"' \
  --limit=500 --freshness=24h --format=json | \
  jq -r '.[] | .resource.labels.service_name' | \
  sort | uniq -c | sort -rn | head -10

echo ""
echo "5. GCS Bucket Sizes..."
gsutil du -sh gs://nba-*

echo ""
echo "6. Firestore Heartbeat Documents..."
count=$(gcloud firestore documents list processor_heartbeats --limit=100 2>/dev/null | wc -l)
echo "  processor_heartbeats: $count documents (expect ~30)"

echo ""
echo "=== Audit Complete ==="
echo "Finished: $(date)"
```

**Usage:**
```bash
chmod +x infrastructure-health-audit.sh
./infrastructure-health-audit.sh > audit-$(date +%Y%m%d).txt
```

---

## Issue Triage

### Severity Levels

| Severity | Impact | Response Time | Examples |
|----------|--------|---------------|----------|
| **CRITICAL** | Production down | Immediate | All services failing, BigQuery unavailable |
| **HIGH** | Data quality impact | <4 hours | Unidentified errors, missing predictions |
| **MEDIUM** | Observability gap | <24 hours | Monitoring not recording, permissions errors |
| **LOW** | Cleanup/optimization | Next maintenance | Staging tables, old revisions, lifecycle policies |

### Common Findings by Severity

**CRITICAL (fix immediately):**
- All Cloud Run services down
- BigQuery dataset deleted
- Firestore collection corrupted
- GCS bucket deleted

**HIGH (fix within 4 hours):**
- >100 unidentified errors
- Deployment drift >7 days
- Production predictions missing
- Query costs >$100/day

**MEDIUM (fix within 24 hours):**
- Monitoring metrics not recording
- Permission errors in logs
- Firestore collection growing >10/day
- Error rate >5%

**LOW (fix in next maintenance window):**
- >20 staging tables
- GCS lifecycle policies missing
- Budget alerts not configured
- Old Cloud Run revisions >500

---

## Related Documentation

- **Troubleshooting Matrix:** `docs/02-operations/troubleshooting-matrix.md`
- **Session 61 Handoff:** `docs/09-handoff/2026-02-01-SESSION-61-HANDOFF.md`
- **Deployment Guide:** `bin/deploy-service.sh`
- **CLAUDE.md:** Project-level health check commands

---

**Last Updated:** 2026-02-01 (Session 61)
**Maintained By:** Engineering Team
**Review Frequency:** After each major infrastructure change
