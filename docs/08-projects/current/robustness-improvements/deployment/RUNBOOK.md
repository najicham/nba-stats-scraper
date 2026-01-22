# Robustness Improvements Deployment Runbook

**Version:** 1.0
**Last Updated:** January 21, 2026
**Owner:** Data Engineering Team
**Emergency Contact:** [Team Slack #data-eng-oncall]

---

## Quick Links

- **Staging Deployment:** `./deploy-staging.sh`
- **Production Deployment:** `./deploy-production.sh <phase>`
- **Monitoring Dashboards:** [Looker Studio URLs]
- **Runbook Location:** `docs/08-projects/current/robustness-improvements/deployment/`

---

## Overview

This runbook covers deployment and operational procedures for the NBA stats scraper robustness improvements, including:
1. Rate limit handling with circuit breakers
2. Phase boundary validation gates
3. Expanded self-healing capabilities

---

## Pre-Deployment Checklist

- [ ] All unit tests passing (`pytest tests/unit/shared/ -v`)
- [ ] Code reviewed and approved
- [ ] Staging deployment successful (if prod deployment)
- [ ] Monitoring dashboards created
- [ ] Slack webhooks configured
- [ ] BigQuery dataset `nba_monitoring` exists
- [ ] Team notified of deployment window

---

## Staging Deployment

### Command
```bash
cd docs/08-projects/current/robustness-improvements/deployment
./deploy-staging.sh
```

### What It Deploys
1. BigQuery table: `nba_monitoring.phase_boundary_validations`
2. Phase transition functions (all in WARNING mode)
3. Self-heal function with Phase 2/4 support
4. Scrapers with rate limiting enabled

### Monitoring (24 hours)
- Check Cloud Logging for errors
- Review BigQuery validation table
- Verify no pipeline failures
- Check Slack alerts (if configured)

### Success Criteria
- ✓ All functions deployed without errors
- ✓ BigQuery table created and accessible
- ✓ Validation records appearing in BigQuery
- ✓ No pipeline failures or performance degradation

---

## Production Deployment (Gradual Rollout)

### Phase 1: Rate Limiting Only (Week 1)

**Deploy:**
```bash
./deploy-production.sh phase1
```

**Monitor for 3 days:**
- Cloud Logging → Search: `component="rate_limit_handler"`
- Check 429 error count reduced
- Verify circuit breaker trips < 5/day
- Confirm no pipeline failures

**Success Criteria:**
- ✓ 429 errors reduced by >80%
- ✓ Circuit breaker working correctly
- ✓ No pipeline disruptions

---

### Phase 2: Validation Gates - WARNING Mode (Week 2)

**Deploy:**
```bash
./deploy-production.sh phase2
```

**Monitor for 3 days:**
```sql
-- Check validation records
SELECT * FROM nba_monitoring.phase_boundary_validations
ORDER BY timestamp DESC LIMIT 100;

-- Calculate false positive rate
SELECT
  phase_name,
  COUNTIF(is_valid) / COUNT(*) as success_rate
FROM nba_monitoring.phase_boundary_validations
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY phase_name;
```

**Success Criteria:**
- ✓ Validation records in BigQuery
- ✓ False positive rate < 5%
- ✓ Expected issues being caught

---

### Phase 3: Enable BLOCKING Mode (Week 3)

**Deploy:**
```bash
./deploy-production.sh phase3
```

**⚠️ CRITICAL:** This enables BLOCKING mode for phase3→4. Bad data will prevent Phase 4 from running.

**Monitor for 7 days:**
```sql
-- Check for BLOCKING events
SELECT *
FROM nba_monitoring.phase_boundary_validations
WHERE mode = 'blocking' AND is_valid = FALSE
ORDER BY timestamp DESC;
```

**Success Criteria:**
- ✓ Bad data blocked from Phase 4
- ✓ No false positive blocks
- ✓ Alerts sent for BLOCKING events

---

### Phase 4: Self-Heal Expansion (Week 4)

**Prerequisites:**
```bash
export SLACK_WEBHOOK_URL_PROD="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
```

**Deploy:**
```bash
./deploy-production.sh phase4
```

**Monitor ongoing:**
- Check Firestore `self_heal_history` collection
- Verify Slack alerts
- Confirm healing operations work

**Success Criteria:**
- ✓ Phase 2/4 issues detected
- ✓ Healing triggered successfully
- ✓ Slack alerts received

---

## Post-Deployment Verification

```bash
./deploy-production.sh verify
```

This checks:
- BigQuery table exists and has recent data
- All Cloud Functions deployed
- Validation mode set correctly
- Environment variables configured

---

## Rollback Procedures

### Rollback Rate Limiting
```bash
gcloud functions deploy phase1-scrapers-prod \
  --update-env-vars=RATE_LIMIT_CB_ENABLED=false
```

### Rollback Validation Gates
```bash
gcloud functions deploy phase3-to-phase4-prod \
  --update-env-vars=PHASE_VALIDATION_MODE=warning
```

### Full Rollback
Re-deploy previous version from git tag:
```bash
git checkout <previous-release-tag>
./deploy-production.sh <phase>
```

---

## Incident Response

### BLOCKING Validation Failure

**Alert:** "Phase validation failed in BLOCKING mode"

**Steps:**
1. Check BigQuery for failure details
2. Identify root cause (game count, processor, quality)
3. If legitimate issue: Fix and re-run pipeline
4. If false positive: Adjust thresholds and redeploy

### Circuit Breaker Storm

**Alert:** "> 10 circuit breaker trips in 15 minutes"

**Steps:**
1. Check which domain is affected
2. Verify API status (BallDontLie, NBA.com, Odds API)
3. If API down: Wait for recovery, circuit will auto-close
4. If persists: Increase `RATE_LIMIT_CB_THRESHOLD`

### Self-Heal Not Triggering

**Symptom:** Missing data not being healed

**Steps:**
1. Check Cloud Function logs for errors
2. Verify Firestore permissions
3. Test manually: `gcloud functions call self-heal-check-prod`
4. Check correlation IDs in logs

---

## Configuration Reference

### Environment Variables

**Rate Limiting:**
- `RATE_LIMIT_MAX_RETRIES` (default: 5)
- `RATE_LIMIT_BASE_BACKOFF` (default: 2.0)
- `RATE_LIMIT_MAX_BACKOFF` (default: 120.0)
- `RATE_LIMIT_CB_THRESHOLD` (default: 10)
- `RATE_LIMIT_CB_TIMEOUT` (default: 300)
- `RATE_LIMIT_CB_ENABLED` (default: true)

**Phase Validation:**
- `PHASE_VALIDATION_ENABLED` (default: true)
- `PHASE_VALIDATION_MODE` (warning | blocking)
- `PHASE_VALIDATION_GAME_COUNT_THRESHOLD` (default: 0.8)
- `PHASE_VALIDATION_QUALITY_THRESHOLD` (default: 0.7)

**Self-Heal:**
- `SLACK_WEBHOOK_URL` (required for alerts)

---

## Monitoring Queries

### Daily Health Check
```sql
-- Validation success rate (last 24h)
SELECT
  phase_name,
  COUNTIF(is_valid) as passed,
  COUNTIF(NOT is_valid) as failed,
  ROUND(COUNTIF(is_valid) / COUNT(*) * 100, 2) as success_rate_pct
FROM nba_monitoring.phase_boundary_validations
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY phase_name;
```

### Rate Limit Events
```sql
-- Check Cloud Logging (replace with your query)
resource.type="cloud_function"
jsonPayload.component="rate_limit_handler"
severity>="WARNING"
timestamp>="2026-01-21T00:00:00Z"
```

---

## Troubleshooting

### Validation Not Running

**Check:**
1. `PHASE_VALIDATION_ENABLED=true`?
2. BigQuery table exists?
3. Cloud Function has BigQuery write permissions?

### High False Positive Rate

**Fix:**
Adjust thresholds:
```bash
gcloud functions deploy phase3-to-phase4-prod \
  --update-env-vars=PHASE_VALIDATION_GAME_COUNT_THRESHOLD=0.75
```

### Self-Heal Firestore Errors

**Check:**
1. Cloud Function service account has Firestore permissions
2. `self_heal_history` collection exists

---

## Contacts

- **On-Call Engineer:** Slack #data-eng-oncall
- **Data Engineering Lead:** [Name]
- **DevOps/SRE:** [Team Slack Channel]

---

## Related Documentation

- [Rate Limiting Implementation](../WEEK-1-2-RATE-LIMITING-COMPLETE.md)
- [Phase Validation Implementation](../WEEK-3-4-PHASE-VALIDATION-COMPLETE.md)
- [Self-Heal Implementation](../WEEK-5-6-SELF-HEAL-COMPLETE.md)
- [Monitoring Dashboards](../monitoring/)

---

**Last Deployment:** [Date]
**Next Review:** [Date + 30 days]
