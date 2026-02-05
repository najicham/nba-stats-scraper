# Daily Health Check Procedure

**Purpose:** Verify all monitoring and self-healing systems are operational
**Frequency:** Daily (morning)
**Duration:** 5-10 minutes
**Owner:** On-call engineer

## Quick Check (2 minutes)

```bash
# 1. Check recent alerts
# Review Slack channels:
# - #deployment-alerts (should see updates every 2h)
# - #canary-alerts (should be quiet unless issues)
# - #nba-alerts (healing events if batches stalled)

# 2. Verify schedulers running
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform | grep nba-

# Expected output:
# - nba-deployment-drift-alerter-trigger (ENABLED)
# - nba-pipeline-canary-trigger (ENABLED)
# - nba-auto-batch-cleanup-trigger (ENABLED)
```

## Detailed Check (5 minutes)

### 1. Deployment Drift Status

```bash
# Check for any drifted services
./bin/check-deployment-drift.sh

# If drift found, review commits and deploy if needed
./bin/deploy-service.sh <service-name>
```

### 2. Pipeline Canary Status

```bash
# Run canaries manually
python bin/monitoring/pipeline_canary_queries.py

# All 6 phases should pass:
# ✅ Phase 1 - Scrapers
# ✅ Phase 2 - Raw Processing
# ✅ Phase 3 - Analytics
# ✅ Phase 4 - Precompute
# ✅ Phase 5 - Predictions
# ✅ Phase 6 - Publishing
```

### 3. Healing Event Analysis

```bash
# Check if self-healing ran overnight
python bin/monitoring/analyze_healing_patterns.py --start "$(date -d 'yesterday' '+%Y-%m-%d 00:00')"

# Expected: 0-2 batch cleanups per day
# If >3, investigate root causes
```

### 4. Batch Health Check

```python
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')

# Check for stalled batches
batches = db.collection('prediction_batches').where('is_complete', '==', False).stream()
stalled = []
for batch in batches:
    data = batch.to_dict()
    if data.get('updated_at'):
        age_hours = (datetime.now(timezone.utc) - data['updated_at']).total_seconds() / 3600
        if age_hours > 1:
            stalled.append((batch.id, age_hours))

if stalled:
    print(f"⚠️ Found {len(stalled)} stalled batch(es)")
else:
    print("✅ No stalled batches")
```

## Health Score

| Metric | Target | Status |
|--------|--------|--------|
| Deployment drift | <2 hours | ✅ |
| Canary failures | 0/6 | ✅ |
| Healing events (24h) | 0-2 | ✅ |
| Stalled batches | 0 | ✅ |

**Overall: HEALTHY** ✅

## Alert Thresholds

| Alert | Condition | Action |
|-------|-----------|--------|
| 🟡 Yellow | 3+ healings in 1h | Investigate root cause |
| 🔴 Red | 10+ healings in 24h | Implement prevention fix |
| 🚨 Critical | Healing failure rate >20% | Immediate investigation |

## Common Issues

### Issue: Deployment drift >4 hours

**Symptom:** Multiple services behind
**Cause:** Commits made but not deployed
**Fix:** Deploy stale services

```bash
./bin/deploy-service.sh prediction-worker
./bin/deploy-service.sh prediction-coordinator
# etc.
```

### Issue: Canary failures

**Symptom:** One or more phases failing
**Cause:** Data quality issue or pipeline failure
**Fix:** Follow runbook in `canary-failure-response.md`

### Issue: Frequent healing events

**Symptom:** 5+ batch cleanups in 12 hours
**Cause:** Systemic issue causing stalls
**Fix:** Analyze root causes and implement prevention

```bash
python bin/monitoring/analyze_healing_patterns.py --type batch_cleanup --export analysis.csv
# Review top triggers, fix root cause
```

## Escalation

**If health check fails:**
1. Check Slack alerts for context
2. Review logs for affected component
3. Follow component-specific runbook
4. If unresolved after 30 min, escalate to team lead

## Documentation

- Deployment monitoring: `docs/02-operations/runbooks/deployment-monitoring.md`
- Canary failures: `docs/02-operations/runbooks/canary-failure-response.md`
- System features: `docs/02-operations/system-features.md`
