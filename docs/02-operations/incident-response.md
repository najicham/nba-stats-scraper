# Incident Response Guide

**Last Updated:** 2025-12-02
**Purpose:** How to respond to pipeline incidents
**Audience:** Anyone on-call or responding to alerts

---

## Severity Levels

| Level | Description | Response Time | Examples |
|-------|-------------|---------------|----------|
| **P1 Critical** | Complete pipeline failure | 15 min | All phases down, no predictions |
| **P2 High** | Major functionality impacted | 1 hour | Phase failing, data missing |
| **P3 Medium** | Partial functionality impacted | 4 hours | Single processor failing |
| **P4 Low** | Minor issue | Next business day | Performance degradation |

---

## Quick Diagnosis

### Step 1: Identify the Scope

```bash
# Quick health check
python3 bin/validate_pipeline.py $(date -d "yesterday" +%Y-%m-%d)

# Check all services
gcloud run services list --project=nba-props-platform --region=us-west2
```

### Step 2: Check Recent Errors

```sql
SELECT
  processor_name,
  phase,
  data_date,
  status,
  error_message,
  created_at
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'error'
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY created_at DESC;
```

### Step 3: Check Orchestrator Logs

```bash
# Phase 2→3 orchestrator
gcloud functions logs read phase2-to-phase3-orchestrator \
  --region=us-west2 --limit=50

# Phase 3→4 orchestrator
gcloud functions logs read phase3-to-phase4-orchestrator \
  --region=us-west2 --limit=50
```

---

## Common Incidents

### Incident: Pipeline Stuck (No Progress)

**Symptoms:**
- No new processor runs
- Orchestrators not triggering
- Data not updating

**Diagnosis:**
1. Check Firestore state for stuck completions
2. Check Pub/Sub for message backlog
3. Check Cloud Run services are responding

**Resolution:**
```bash
# Check Firestore (via console)
# https://console.firebase.google.com/project/nba-props-platform/firestore

# Check Pub/Sub subscription backlog
gcloud pubsub subscriptions list --project=nba-props-platform

# Force re-trigger (if needed)
gcloud pubsub topics publish nba-phase2-raw-complete \
  --project=nba-props-platform \
  --message='{"game_date": "2024-01-15", "source": "manual_recovery"}'
```

---

### Incident: Phase 2 Processors Failing

**Symptoms:**
- Raw data not appearing in BigQuery
- Error alerts from Phase 2 processors

**Diagnosis:**
```bash
gcloud run services logs read nba-phase2-raw-processors \
  --project=nba-props-platform --region=us-west2 --limit=100
```

**Common Causes:**
- Source API down (NBA.com, ESPN)
- GCS file not found
- Schema mismatch

**Resolution:**
1. Wait and retry (transient API issues)
2. Check source data exists in GCS
3. Manual re-run if needed

---

### Incident: Phase 3/4 Missing Data

**Symptoms:**
- Analytics tables empty for date
- Precompute tables not updated

**Diagnosis:**
```sql
-- Check Phase 2 completed
SELECT COUNT(*) FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date = '2024-01-15' AND phase = 2 AND status = 'success';

-- Check dependencies
SELECT processor_name, status, dependency_check_passed
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date = '2024-01-15' AND phase IN (3, 4);
```

**Common Causes:**
- Upstream phase didn't complete
- Dependency check failed
- Bootstrap period (first 14 days of season)

**Resolution:**
1. Ensure upstream phases completed
2. Re-trigger orchestrator
3. Manual processor run if needed

---

### Incident: Predictions All PASS

**Symptoms:**
- Predictions generated but all PASS
- No actionable OVER/UNDER

**Diagnosis:**
```sql
SELECT AVG(confidence_score), AVG(quality_score)
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
JOIN `nba-props-platform.nba_predictions.ml_feature_store_v2` f
  USING (player_lookup, game_date)
WHERE p.game_date = CURRENT_DATE();
```

**Common Causes:**
- Low confidence (early season)
- Poor data quality in features
- Missing prop lines

**Resolution:**
- Usually expected behavior early season
- Check feature quality scores
- Verify prop lines are loaded

---

### Incident: Service Not Responding

**Symptoms:**
- 503 errors from Cloud Run
- Timeouts

**Diagnosis:**
```bash
# Check service status
gcloud run services describe [SERVICE_NAME] \
  --project=nba-props-platform --region=us-west2

# Check recent revisions
gcloud run revisions list --service=[SERVICE_NAME] \
  --project=nba-props-platform --region=us-west2
```

**Resolution:**
1. Check if service is deploying new revision
2. Force redeploy if stuck
3. Roll back to previous revision if needed

---

## Escalation Path

```
Level 1: Self-Service
  ↓ (if unresolved after 30 min)
Level 2: Investigation
  ↓ (if critical or spreading)
Level 3: Emergency Response
```

### Level 1: Self-Service

- Run validation scripts
- Check logs
- Wait and retry
- Document what you found

### Level 2: Investigation

- Deep log analysis
- Check GCP console
- Review recent changes
- Consider rollback

### Level 3: Emergency Response

- Stop all processing if data corruption
- Rollback recent deployments
- Notify stakeholders
- Post-incident review

---

## Post-Incident

### Checklist

- [ ] Incident resolved
- [ ] Root cause identified
- [ ] Impacted data verified/reprocessed
- [ ] Documentation updated if needed
- [ ] Prevention measures identified

### Template for Notes

```markdown
## Incident: [Brief Description]

**Date:** YYYY-MM-DD
**Duration:** X hours
**Severity:** P1/P2/P3/P4
**Impact:** [What was affected]

### Timeline
- HH:MM - Incident detected
- HH:MM - Investigation started
- HH:MM - Root cause identified
- HH:MM - Resolution applied
- HH:MM - Confirmed resolved

### Root Cause
[What caused the incident]

### Resolution
[What fixed it]

### Prevention
[How to prevent recurrence]
```

---

## Contact Points

| Role | Contact |
|------|---------|
| Pipeline Owner | [Your info] |
| GCP Admin | [Admin info] |
| Alert System | Email alerts |

---

## Related Documentation

- [Daily Operations Runbook](./daily-operations-runbook.md)
- [Emergency Runbook](./runbooks/emergency/)
- [Validation System](../07-monitoring/validation-system.md)
