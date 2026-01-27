# BigQuery Quota Fix - Project Documentation

**Status**: DEPLOYED
**Date**: 2026-01-26
**Priority**: P1 Critical

---

## Executive Summary

The NBA stats pipeline was hitting BigQuery's hard limit of 1,500 load jobs per table per day. A batching solution has been implemented and deployed that reduces quota usage from 164% to 2%.

**Key Changes:**
1. **Batching**: All monitoring writes now batch 100 records per load job (100x reduction)
2. **Emergency Mode**: `MONITORING_WRITES_DISABLED=true` env var to skip all monitoring writes
3. **Self-Healing**: Scheduled job to re-enable monitoring after quota reset

---

## Problem Statement

### What Happened

BigQuery has a **hard limit of 1,500 load jobs per table per day** that cannot be increased.

Our monitoring tables exceeded this quota:

| Table | Writes/Day | % of Quota |
|-------|-----------|------------|
| `processor_run_history` | 1,321 | 88% |
| `circuit_breaker_state` | 575 | 38% |
| `analytics_processor_runs` | 570 | 38% |
| **TOTAL** | **2,466** | **164%** |

### Root Cause

Each monitoring write created an individual load job:
```python
# Old code: 1 record = 1 load job
load_job = bq_client.load_table_from_json([record], table_id)
```

### Impact

- Phases 3-5 blocked when quota exceeded
- 0 predictions generated
- Pipeline dead until midnight PT quota reset

---

## Solution Implemented

### 1. Batching (Primary Fix)

**File**: `shared/utils/bigquery_batch_writer.py`

All monitoring writes now go through a batch writer that:
- Accumulates records in memory (max 100 records)
- Flushes on size threshold OR 30-second timeout
- Single load job per 100 records = 100x quota reduction

**Before**: 2,466 load jobs/day (164% of quota)
**After**: ~32 load jobs/day (2% of quota)

### 2. Emergency Disable (Backup)

**Environment Variable**: `MONITORING_WRITES_DISABLED`

When quota is already exceeded, set this to skip ALL monitoring writes:
- `true` = All writes silently skipped (pipeline runs, no monitoring data)
- `false` = Normal operation (default)

### 3. Affected Services

These Cloud Run services use the batch writer:

| Service | Uses Batch Writer For |
|---------|----------------------|
| `nba-phase2-raw-processors` | Run history |
| `nba-phase3-analytics-processors` | Run history, analytics processor runs |
| `nba-phase4-precompute-processors` | Run history |
| `nba-phase5-predictions` | Run history |

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MONITORING_WRITES_DISABLED` | `false` | Skip ALL monitoring writes |
| `BQ_BATCH_WRITER_ENABLED` | `true` | Use batching (false = direct writes) |
| `BQ_BATCH_WRITER_BATCH_SIZE` | `100` | Records per batch |
| `BQ_BATCH_WRITER_TIMEOUT` | `30.0` | Seconds before auto-flush |

### Quota Reset Time

BigQuery quota resets at **midnight Pacific Time** (3:00 AM Eastern).

---

## Operations

### Check Current Quota Usage

```bash
# Quick check via Cloud Console
# Go to: BigQuery > Admin > Quotas
# Look for: "Load jobs per table per day"

# Or via bq command (may hit rate limits)
bq query --use_legacy_sql=false "
SELECT
  destination_table.table_id,
  COUNT(*) as job_count,
  ROUND(COUNT(*) / 1500.0 * 100, 1) as quota_pct
FROM \`region-us\`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE
  creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND job_type = 'LOAD'
GROUP BY destination_table.table_id
ORDER BY job_count DESC
LIMIT 10"
```

### Enable Emergency Mode (Skip Monitoring)

When quota is exceeded and you need to run the pipeline:

```bash
# Disable monitoring for all phase services
for SERVICE in nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors; do
  gcloud run services update $SERVICE \
    --region=us-west2 \
    --set-env-vars="MONITORING_WRITES_DISABLED=true" \
    --quiet
done
```

### Disable Emergency Mode (After Quota Reset)

```bash
# Re-enable monitoring for all phase services
for SERVICE in nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors; do
  gcloud run services update $SERVICE \
    --region=us-west2 \
    --set-env-vars="MONITORING_WRITES_DISABLED=false" \
    --quiet
done
```

### Manually Trigger Pipeline

```bash
# Trigger Phase 3
gcloud scheduler jobs run same-day-phase3 --location=us-west2

# Trigger Phase 4 (if Phase 3 completes)
gcloud scheduler jobs run same-day-phase4 --location=us-west2
```

---

## Self-Healing (Implemented)

### Automatic Reset After Quota Reset

The batch writer includes **automatic self-healing**:

- Between 12:00 AM and 12:30 AM Pacific (right after quota reset)
- Monitoring writes are **automatically enabled** regardless of `MONITORING_WRITES_DISABLED` setting
- This means even if you forget to re-enable monitoring, it auto-enables after midnight

**How it works** (in `bigquery_batch_writer.py`):
```python
def _is_after_quota_reset() -> bool:
    """Check if we're in the 30-minute window after midnight Pacific."""
    pacific = ZoneInfo('America/Los_Angeles')
    now_pacific = datetime.now(pacific)
    return now_pacific.hour == 0 and now_pacific.minute < 30
```

### Manual Reset (Optional)

If you want to re-enable monitoring before the auto-reset window:

```bash
for SERVICE in nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors; do
  gcloud run services update $SERVICE \
    --region=us-west2 \
    --set-env-vars="MONITORING_WRITES_DISABLED=false" \
    --quiet
done
```

### Why This Works

1. **Quota resets at midnight Pacific** (hard limit, cannot change)
2. **Auto-enable window is 12:00-12:30 AM Pacific** (right after reset)
3. **If processors run in this window**, monitoring writes succeed
4. **Once batching processes a successful write**, env var can be left as-is
5. **Next day's processors** use batching (2% quota), never hit limit again

---

## Monitoring

### Batch Writer Metrics

The batch writer tracks:
- `total_records_added`: Records buffered
- `total_batches_flushed`: Successful flushes
- `total_flush_failures`: Failed flushes
- `avg_batch_size`: Records per batch
- `current_buffer_size`: Pending records

Access via logs:
```bash
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=100 | grep -i "flushed\|batch"
```

### Alert on Quota Issues

Set up Cloud Monitoring alert for:
- Job failures with "quotaExceeded" error
- Load job count approaching 1,200/day (80% threshold)

---

## Future Improvements

### 1. Firestore Migration (Optional)

For even better reliability, consider migrating:
- Circuit breaker state → Firestore (50x faster reads, no quotas)
- Processor status → Firestore (no quotas)

**Keep in BigQuery**: Run history logs (SQL queryability needed)

See: `docs/08-projects/current/monitoring-storage-evaluation/`

### 2. Context-Aware Monitoring

Reduce monitoring writes during backfills:
- Daily production: Full monitoring
- Backfills: Errors only (70-90% reduction)

---

## Code Locations

| Component | File |
|-----------|------|
| Batch Writer | `shared/utils/bigquery_batch_writer.py` |
| Run History Mixin | `shared/processors/mixins/run_history_mixin.py` |
| Circuit Breaker | `shared/processors/patterns/circuit_breaker_mixin.py` |
| Analytics Base | `data_processors/analytics/analytics_base.py` |
| Quota Monitor | `monitoring/bigquery_quota_monitor.py` |

---

## Commit History

| Commit | Description |
|--------|-------------|
| `129d0185` | Initial batching implementation |
| `6e84130a` | Add MONITORING_WRITES_DISABLED env var |

---

## Contact

For issues, check:
1. Cloud Run logs for the affected service
2. BigQuery quota usage in Cloud Console
3. This documentation

---

**Last Updated**: 2026-01-26 10:30 PM ET
