# BigQuery Quota Issue - Prevention Plan

**Date**: 2026-01-26
**Priority**: P1 Critical
**Status**: Fix implemented locally, NOT deployed

---

## Executive Summary

The NBA stats pipeline has been blocked multiple times today by BigQuery quota exceeded errors. A batching fix has been implemented but **is sitting in a local commit that hasn't been pushed**. Additionally, there are 44 other places in the codebase still using direct writes that could hit quota in the future.

**This document outlines what happened, why, and a comprehensive plan to ensure this never happens again.**

---

## What Happened

### The Root Cause

BigQuery has a **hard limit of 1,500 load jobs per table per day** that **CANNOT be increased**. Our monitoring tables were creating individual load jobs for every single record:

| Table | Writes/Day | % of Quota | Status |
|-------|-----------|------------|--------|
| `processor_run_history` | 1,321 | 88% | ❌ Over limit |
| `circuit_breaker_state` | 575 | 38% | ⚠️ High |
| `analytics_processor_runs` | 570 | 38% | ⚠️ High |
| **TOTAL** | **2,466** | **164%** | ❌ **EXCEEDED** |

### The Cascade

Once quota exceeded:
1. ❌ All writes to monitoring tables fail with 403
2. ❌ Processors can't log completion status
3. ❌ Phase 3 analytics blocked
4. ❌ Phase 4 can't run (depends on Phase 3)
5. ❌ Phase 5 can't run (depends on Phase 4)
6. ❌ **No predictions generated**

### Why It Wasn't Caught

1. **No monitoring**: No quota usage tracking existed
2. **Gradual buildup**: Started small, grew as we added processors
3. **Invisible quota**: "Load jobs per table" not shown in Cloud Console quotas page
4. **Misleading assumption**: Developers assumed BigQuery had high/unlimited limits

---

## Current State

### What's Implemented (Committed Locally)

**Commit**: `129d0185` - "fix: Implement BigQuery batching to prevent quota exceeded errors"

**Files created/modified**:
- `shared/utils/bigquery_batch_writer.py` - New batching utility (432 lines)
- `monitoring/bigquery_quota_monitor.py` - Quota monitoring script (439 lines)
- `shared/processors/mixins/run_history_mixin.py` - Updated to use batching
- `shared/processors/patterns/circuit_breaker_mixin.py` - Updated to use batching
- `data_processors/analytics/analytics_base.py` - Updated to use batching

**Expected Impact**:
- Before: 2,466 jobs/day (164% of quota)
- After: 32 jobs/day (2% of quota)
- Safety margin: 98% quota headroom

### What's NOT Deployed

**The commit has NOT been pushed to origin/main.**

```bash
# Current state
git log --oneline -1
# 129d0185 fix: Implement BigQuery batching to prevent quota exceeded errors

git status
# Your branch is ahead of 'origin/main' by 1 commit.
```

**Cloud Run is still running the OLD code without batching.**

### What's Still Vulnerable (44 Other Places)

The Explore agent found **44 direct `load_table_from_json()` calls** that are NOT using batching:

```
grep -r "load_table_from_json" --include="*.py" | wc -l
# Result: 44
```

**High-risk locations**:
- `tools/player_registry/` - Player data updates
- `scripts/` - Validation and backfill scripts
- `data_processors/raw/` - Raw data processors
- `data_processors/precompute/` - Precompute processors
- `shared/utils/bigquery_client.py` - Utility functions

These could hit quota if they have high-frequency writes.

---

## Immediate Actions Required

### Action 1: Deploy the Batching Fix (NOW)

```bash
# Push the commit
git push origin main

# Verify it's pushed
git log --oneline origin/main -1
# Should show: 129d0185 fix: Implement BigQuery batching...
```

### Action 2: Rebuild Cloud Run Services

After pushing, rebuild the services to pick up the new code:

```bash
# Phase 3 Analytics
gcloud builds submit \
  --config=cloudbuild-phase3.yaml \
  --project=nba-props-platform \
  .

# Phase 4 Precompute
gcloud builds submit \
  --config=cloudbuild-phase4.yaml \
  --project=nba-props-platform \
  .
```

### Action 3: Verify Deployment

```bash
# Check for batching log messages
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 \
  --limit=100 | grep -i "flushed\|batch"

# Expected output:
# "Flushed 100 records to nba_reference.processor_run_history"
```

### Action 4: Run Quota Monitor

```bash
# Check current quota usage
python monitoring/bigquery_quota_monitor.py --dry-run

# Expected output after deployment:
# ✅ processor_run_history: 14 jobs (0.9%)
# ✅ circuit_breaker_state: 12 jobs (0.8%)
```

---

## Short-Term Prevention (This Week)

### 1. Set Up Hourly Quota Monitoring

Deploy the quota monitoring script to run hourly:

```bash
# Create the monitoring infrastructure
./bin/setup/setup_quota_monitoring.sh
```

This creates:
- Cloud Scheduler job running hourly
- BigQuery table for historical tracking
- Alert thresholds (80% warning, 95% critical)

### 2. Add Quota Check to `/validate-daily`

The skill already has a "Phase 0: Proactive Quota Check" documented but should be implemented:

```markdown
## Phase 0: Proactive Quota Check (NEW)

Before running validation, check BigQuery quota status:

```bash
python monitoring/bigquery_quota_monitor.py --quick
```

If any table is >80% quota:
- 🔴 P1 CRITICAL: Alert immediately
- Recommend: Wait for quota reset (midnight PT) or enable batching
```

### 3. Update `/validate-historical` Skill

Add quota monitoring to historical validation:
- Check quota before starting large backfills
- Estimate quota impact of planned operations
- Warn if backfill would exceed quota

### 4. Add CI/CD Lint Check

Create a pre-commit or CI check that catches naive write patterns:

```bash
# Check for direct load_table_from_json calls
grep -r "load_table_from_json\s*\(\s*\[" --include="*.py" | grep -v "batch_writer"

# If any matches found, fail with:
# "ERROR: Use BigQueryBatchWriter instead of direct load_table_from_json calls"
```

---

## Medium-Term Prevention (This Month)

### 1. Migrate Remaining 44 Direct Write Calls

**Priority order** (by write frequency):

| Priority | File/Location | Estimated Writes/Day | Risk |
|----------|---------------|---------------------|------|
| P1 | `shared/utils/bigquery_client.py` | Unknown | High |
| P1 | `data_processors/precompute/` | ~200 | High |
| P2 | `tools/player_registry/` | ~50 | Medium |
| P2 | `scripts/validation/` | ~30 | Medium |
| P3 | `scripts/backfill/` | Variable | Low (ad-hoc) |
| P3 | MLB data collection | ~100 | Medium |

**Migration pattern**:

```python
# BEFORE (dangerous)
load_job = bq_client.load_table_from_json([record], table_id, job_config)
load_job.result(timeout=60)

# AFTER (safe)
from shared.utils.bigquery_batch_writer import get_batch_writer

writer = get_batch_writer(
    table_id=table_id,
    project_id=project_id,
    batch_size=100,
    timeout_seconds=30.0
)
writer.add_record(record)
```

### 2. Create Batch Writer Usage Guide

Document in `docs/05-development/guides/bigquery-batch-writer.md`:
- When to use batch writer vs streaming inserts
- Batch size recommendations by use case
- Timeout configuration
- Error handling
- Testing patterns

### 3. Add Quota Dashboard

Create a Grafana/Looker dashboard showing:
- Current quota usage by table
- 7-day trend
- Alert history
- Predicted time until quota exceeded

### 4. Implement Alert Channels

Connect quota monitoring to:
- Slack webhook (>80% quota)
- Email (>95% quota)
- PagerDuty (quota exceeded)

---

## Long-Term Prevention (This Quarter)

### 1. Architecture Review

Consider hybrid storage strategy:
- **BigQuery**: Structured analytics data (current)
- **Cloud Logging**: High-frequency event logs (reduce BQ writes)
- **Firestore**: Real-time circuit breaker state (if needed)

### 2. Adaptive Batching

Implement dynamic batch sizing based on traffic:

```python
if records_per_hour > 1000:
    batch_size = 200  # More aggressive batching
elif records_per_hour < 100:
    batch_size = 50   # Less aggressive
```

### 3. Smart Sampling

For debugging tables, consider sampling:

```python
# Only log 10% of routine successes
if status == 'success' and random.random() > 0.1:
    return  # Skip logging
```

### 4. Quota Budgeting

Allocate quota budget per component:
- Run history: 500 jobs/day (33%)
- Circuit breaker: 200 jobs/day (13%)
- Analytics: 200 jobs/day (13%)
- Reserve: 600 jobs/day (40%)

Alert if any component exceeds its budget.

---

## Integration with Validation Skills

### `/validate-daily` Enhancements

Add these checks to the skill:

```markdown
## Phase 0: Infrastructure Health

### Quota Check
```bash
python monitoring/bigquery_quota_monitor.py --quick
```

| Table | Usage | Status |
|-------|-------|--------|
| processor_run_history | 14/1500 (0.9%) | ✅ |
| circuit_breaker_state | 12/1500 (0.8%) | ✅ |

If any table >80%: 🔴 P1 CRITICAL - Pipeline at risk
```

### `/validate-historical` Enhancements

Add quota impact estimation:

```markdown
## Before Running Backfill

### Quota Impact Assessment
Backfill for 7 days:
- Estimated writes: ~700 records
- Current quota used: 32/1500 (2%)
- After backfill: ~39/1500 (3%)
- Status: ✅ Safe to proceed

If >50% quota after backfill: ⚠️ Consider splitting into smaller batches
```

---

## Monitoring Checklist

### Daily Checks
- [ ] Quota usage <50% for all tables
- [ ] No quota exceeded errors in logs
- [ ] Batching messages appearing in logs

### Weekly Checks
- [ ] Review quota usage trends
- [ ] Check for new direct write patterns in code
- [ ] Verify monitoring alerts working

### Monthly Checks
- [ ] Capacity planning review
- [ ] Update batch sizes if traffic changed
- [ ] Review and migrate any new direct writes

---

## Emergency Procedures

### If Quota Exceeded Again

**Immediate (within 5 minutes)**:
1. Check when quota resets: `date -u -d "tomorrow 00:00 PT"`
2. Disable non-critical writes:
   ```bash
   gcloud run services update nba-phase3-analytics-processors \
     --region=us-west2 \
     --set-env-vars="DISABLE_RUN_HISTORY_LOGGING=true"
   ```

**Short-term (within 1 hour)**:
1. Identify which table hit quota
2. Check if batching is deployed
3. If not deployed, push and rebuild immediately

**Recovery (after quota resets)**:
1. Re-enable all logging
2. Run `/validate-daily` to check pipeline health
3. Backfill any missing data

---

## Key Files Reference

### Batching Implementation
- `shared/utils/bigquery_batch_writer.py` - Core batching utility
- `shared/processors/mixins/run_history_mixin.py` - Run history batching
- `shared/processors/patterns/circuit_breaker_mixin.py` - Circuit breaker batching
- `data_processors/analytics/analytics_base.py` - Analytics batching

### Monitoring
- `monitoring/bigquery_quota_monitor.py` - Quota monitoring script
- `bin/setup/setup_quota_monitoring.sh` - Monitoring setup script

### Documentation
- `docs/technical/BIGQUERY-QUOTA-ISSUE-COMPLETE-ANALYSIS.md` - Full technical analysis
- `docs/incidents/2026-01-26-bigquery-quota-exceeded.md` - Incident report

---

## Success Metrics

### After Deployment
- [ ] Quota usage drops from 164% to <5%
- [ ] No quota exceeded errors for 24 hours
- [ ] Batching log messages appearing

### After 1 Week
- [ ] Hourly monitoring running
- [ ] Alerts configured and tested
- [ ] CI/CD lint check added

### After 1 Month
- [ ] All 44 direct writes migrated to batching
- [ ] Dashboard operational
- [ ] Zero quota incidents

---

## Lessons Learned

### What Went Wrong
1. **No visibility**: Quota limit not visible in Cloud Console
2. **No monitoring**: No proactive quota tracking
3. **Naive patterns**: Individual writes instead of batching
4. **Gradual buildup**: Crossed threshold without warning

### What We're Fixing
1. **Batching**: 100x reduction in quota usage
2. **Monitoring**: Hourly quota checks with alerts
3. **Prevention**: CI/CD checks, code review guidelines
4. **Documentation**: Comprehensive guides and runbooks

### What We Learned
1. BigQuery has hard limits that can't be increased
2. "Load jobs per table" quota is invisible in Console
3. Batching is essential for high-frequency writes
4. Monitoring must be proactive, not reactive

---

## Next Session Handoff

### Immediate Priority
1. **PUSH THE CODE**: `git push origin main`
2. **REBUILD SERVICES**: Deploy to Cloud Run
3. **VERIFY**: Check for batching log messages

### This Week
1. Set up hourly quota monitoring
2. Add quota check to `/validate-daily` skill
3. Add CI/CD lint check

### This Month
1. Migrate remaining 44 direct write calls
2. Create Grafana dashboard
3. Set up Slack/email alerts

---

**Document Status**: Complete
**Ready for Action**: Yes
**Critical Path**: Push code → Rebuild → Verify → Monitor
