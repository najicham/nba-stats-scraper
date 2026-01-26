# Daily Operations Runbook

**Last Updated:** 2026-01-26
**Purpose:** Step-by-step guide for daily pipeline operations
**Audience:** Anyone operating the NBA Props Pipeline

---

## Claude Code Skill: `/validate-daily` ⭐ RECOMMENDED

**NEW (2026-01-26)**: Use the Claude Code skill for intelligent daily validation.

### Quick Start

```bash
# In Claude Code, simply run:
/validate-daily
```

This skill provides:
- ✅ Comprehensive validation of all pipeline phases
- ✅ Intelligent investigation of issues (not just command execution)
- ✅ Severity classification (P1-P5) with actionable recommendations
- ✅ Context-aware expectations (pre-game vs post-game timing)
- ✅ Known issue pattern matching
- ✅ Structured report with specific remediation steps

### When to Use

**Pre-game (5 PM ET)**: Verify data ready before games
```
/validate-daily
```

**Post-game (6 AM ET next day)**: Verify complete pipeline ran
```
/validate-daily
```

**After fixes**: Re-validate to confirm resolution
```
/validate-daily
```

### What You Get

The skill produces a report like:

```
## Daily Orchestration Validation - 2026-01-26

### Summary: ⚠️ NEEDS ATTENTION

| Phase | Status | Details |
|-------|--------|---------|
| Phase 2 (Betting) | ✅ OK | 147 props, 28 lines |
| Phase 3 (Analytics) | ⚠️ 80% | 4/5 processors complete |
...

### Issues Found
🔴 P1 CRITICAL: BigQuery Quota Exceeded
  - Impact: Phase 3 processors cannot write results
  - Recommendation: [specific commands to run]

### Recommended Actions
1. IMMEDIATE: Investigate quota issue [commands]
2. HIGH: Review stale dependencies [what to check]
```

**Learn More**: See `docs/02-operations/VALIDATE-DAILY-SKILL-CREATION-GUIDE.md`

---

## Quick Reference (Manual Validation)

> **Note**: The `/validate-daily` skill (above) is recommended over manual validation.
> Use these manual steps only if you need to run specific checks independently.

### Morning Health Check (5 min)

```bash
# 1. Check all services are running
gcloud run services list --project=nba-props-platform --region=us-west2

# 2. Validate yesterday's data
python3 bin/validate_pipeline.py $(date -d "yesterday" +%Y-%m-%d)

# 3. Check for failed processors
bq query --use_legacy_sql=false "
SELECT processor_name, status, error_message
FROM \`nba-props-platform.nba_reference.processor_run_history\`
WHERE data_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  AND status = 'error'
"
```

### Key Metrics to Monitor

| Metric | Expected | Alert Threshold |
|--------|----------|-----------------|
| Phase 2 processors | 21 complete | <21 |
| Phase 3 analytics | 5 complete | <5 |
| Phase 4 precompute | 5 complete | <5 |
| Phase 5 predictions | 100-450 rows | <50 |
| Overall success rate | >95% | <90% |

---

## Daily Schedule

### Game Days (Most Nights)

| Time (PT) | Event | Action |
|-----------|-------|--------|
| 6:00 AM | Morning check | Verify overnight processing |
| 10:00 AM | Prop lines update | Phase 5 coordinator triggered |
| 2:00 PM | Afternoon update | Check for line changes |
| 7:00 PM | Games start | Monitor real-time |
| 11:00 PM | Phase 4 starts | Precompute processors |
| 12:00 AM | Phase 4 completes | ML features ready |
| 1:00 AM | Phase 5 runs | Predictions generated |

### Non-Game Days

- Minimal activity
- Good time for maintenance, backfill, or updates

---

## Common Operations

### 1. Check Pipeline Health

```bash
# Quick validation for specific date
python3 bin/validate_pipeline.py 2024-01-15

# Date range validation
python3 bin/validate_pipeline.py 2024-01-15 2024-01-28

# JSON output for scripting
python3 bin/validate_pipeline.py 2024-01-15 --format json
```

### 2. Check Processor Run History

```sql
-- Recent processor runs
SELECT
  processor_name,
  data_date,
  status,
  rows_processed,
  duration_seconds,
  error_message
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
ORDER BY created_at DESC
LIMIT 50;
```

### 3. Check Orchestrator Status

```bash
# Phase 2→3 orchestrator logs
gcloud functions logs read phase2-to-phase3-orchestrator \
  --region=us-west2 --limit=20

# Phase 3→4 orchestrator logs
gcloud functions logs read phase3-to-phase4-orchestrator \
  --region=us-west2 --limit=20

# Firestore state (visit in browser)
# https://console.firebase.google.com/project/nba-props-platform/firestore
```

### 4. Check Cloud Run Service Health

```bash
# List all services
gcloud run services list --project=nba-props-platform --region=us-west2

# Check specific service
gcloud run services describe nba-phase3-analytics-processors \
  --project=nba-props-platform --region=us-west2

# View recent logs
gcloud run services logs read nba-phase3-analytics-processors \
  --project=nba-props-platform --region=us-west2 --limit=50
```

### 5. Manual Trigger (if needed)

```bash
# Trigger Phase 3 for specific date
curl -X POST "https://nba-phase3-analytics-processors-xxx.run.app/process-analytics" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"processor": "player_game_summary", "start_date": "2024-01-15", "end_date": "2024-01-15"}'
```

---

## Troubleshooting

### Symptom: No data for yesterday

1. **Check if games occurred**
   ```sql
   SELECT COUNT(*) FROM `nba-props-platform.nba_raw.nbac_schedule`
   WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
   ```

2. **Check Phase 2 completed**
   ```sql
   SELECT processor_name, status
   FROM `nba-props-platform.nba_reference.processor_run_history`
   WHERE data_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
     AND phase = 2
   ```

3. **Check orchestrator logs** for errors

### Symptom: Predictions missing

1. **Check Phase 4 completed** (prerequisite)
   ```sql
   SELECT COUNT(*) FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
   WHERE game_date = CURRENT_DATE()
   ```

2. **Check Phase 5 coordinator logs**
   ```bash
   gcloud run services logs read prediction-coordinator \
     --project=nba-props-platform --region=us-west2 --limit=50
   ```

3. **Check for prop lines** (Phase 5 needs lines to generate predictions)

### Symptom: Processor failed

1. **Get error details**
   ```sql
   SELECT * FROM `nba-props-platform.nba_reference.processor_run_history`
   WHERE status = 'error'
     AND data_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
   ```

2. **Check dependency status** - was the upstream data available?

3. **Manual re-run** if needed (see Manual Trigger section)

---

## Escalation

### Level 1: Self-Service (Most Issues)

- Run validation script
- Check logs
- Wait and retry (transient failures)

### Level 2: Investigation Required

- Multiple processors failing
- Orchestrator not triggering
- Data quality issues

### Level 3: Urgent (Production Impact)

- All predictions missing
- Pipeline completely stuck
- Data corruption detected

---

## Maintenance Windows

### Safe Times for Maintenance

- **Best:** Non-game days (rare in season)
- **Good:** 6 AM - 10 AM PT (between overnight processing and game prep)
- **Avoid:** 10 AM - 2 AM PT (active processing)

### Pre-Maintenance Checklist

- [ ] Check game schedule for the day
- [ ] Verify no critical backfills in progress
- [ ] Notify stakeholders if extended downtime
- [ ] Document what you're changing

### Post-Maintenance Checklist

- [ ] Run health check
- [ ] Verify all services responding
- [ ] Run validation on recent date
- [ ] Monitor for 30 minutes

---

## Related Documentation

- [Validation System](../07-monitoring/validation-system.md)
- [Orchestrator Monitoring](./orchestrator-monitoring.md)
- [Emergency Runbook](./runbooks/emergency/)
- [Backfill Runbook](./runbooks/backfill/)
- [Phase Operations Docs](../03-phases/)

---

## Quick Commands Cheat Sheet

```bash
# Health check
python3 bin/validate_pipeline.py $(date +%Y-%m-%d)

# Yesterday's validation
python3 bin/validate_pipeline.py $(date -d "yesterday" +%Y-%m-%d)

# List services
gcloud run services list --project=nba-props-platform --region=us-west2

# Orchestrator logs
gcloud functions logs read phase2-to-phase3-orchestrator --region=us-west2 --limit=20

# Service logs
gcloud run services logs read prediction-coordinator --project=nba-props-platform --region=us-west2 --limit=50
```
