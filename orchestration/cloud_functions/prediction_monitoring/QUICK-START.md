# Prediction Monitoring - Quick Start Guide

**Session 106 Deliverable**
**Deploy Time:** ~10 minutes

---

## Problem This Solves

**On 2026-01-18:** 14 players (20%) were missing predictions despite having betting lines.

**Root Cause:** Phase 3 data ran 26 hours AFTER predictions instead of before.

**Solution:** 3-layer monitoring that validates data freshness, detects missing players, and sends critical Slack alerts.

---

## Quick Deploy (3 Commands)

```bash
# 1. Set environment variables
export SLACK_WEBHOOK_URL_ERROR="<your-critical-alerts-webhook>"
export GCP_PROJECT_ID="nba-props-platform"

# 2. Deploy Cloud Functions
cd orchestration/cloud_functions/prediction_monitoring
./deploy.sh

# 3. Setup Cloud Schedulers
./setup_schedulers.sh
```

**Done!** Monitoring is now active.

---

## What Gets Deployed

### Cloud Functions (3 endpoints)

| Endpoint | Purpose | When |
|----------|---------|------|
| `/validate-freshness` | Check data is fresh | Before predictions (5:45 PM ET) |
| `/check-missing` | Detect missing predictions | After predictions (7:00 PM ET) |
| `/reconcile` | Full pipeline validation | Next morning (9:00 AM ET) |

### Cloud Schedulers (3 jobs)

| Time (ET) | Job | Action |
|-----------|-----|--------|
| 5:45 PM | `validate-freshness-check` | Validates Phase 3/4 data is fresh |
| 7:00 PM | `missing-prediction-check` | Detects missing players, sends Slack alert |
| 9:00 AM | `daily-reconciliation` | Full end-to-end pipeline check |

---

## Verify Deployment

```bash
# Check Cloud Functions deployed
gcloud functions list --gen2 --region=us-west2 | grep -E 'validate-freshness|check-missing|reconcile'

# Check schedulers created
gcloud scheduler jobs list --location=us-west2 | grep -E 'validate-freshness|missing-prediction|daily-reconciliation'

# Test manually
gcloud scheduler jobs run missing-prediction-check --location=us-west2
```

**Expected:** Slack alert in #app-error-alerts if any predictions missing

---

## Alert Example

When predictions are missing, you'll see in Slack:

```
🚨 MISSING PREDICTIONS ALERT - 2026-01-19

Coverage: 57/71 players (80.3%)

14 players with betting lines did NOT receive predictions:
🌟 2 high-value players (≥20 PPG) missing

Missing Players:
• Jamal Murray (DEN vs CHA): 28.5 pts
• Ja Morant (MEM vs ORL): 17.5 pts
• ...

Investigation Needed:
1. Check if Phase 3 ran before Phase 5
2. Verify betting lines data available
```

**Actionable** - Shows exactly which players and investigation steps

---

## Manual Testing

```bash
# Test today's predictions
curl "https://us-west2-nba-props-platform.cloudfunctions.net/check-missing?game_date=$(date +%Y-%m-%d)"

# Test data freshness
curl "https://us-west2-nba-props-platform.cloudfunctions.net/validate-freshness?game_date=$(date +%Y-%m-%d)"

# Test reconciliation
curl "https://us-west2-nba-props-platform.cloudfunctions.net/reconcile?game_date=$(date +%Y-%m-%d)"
```

---

## Troubleshooting

**No Slack alerts?**
```bash
# Check if SLACK_WEBHOOK_URL_ERROR is set
gcloud functions describe check-missing --gen2 --region=us-west2 --format="value(serviceConfig.environmentVariables)"
```

**Scheduler not running?**
```bash
# Check scheduler state
gcloud scheduler jobs describe missing-prediction-check --location=us-west2

# View recent runs
gcloud logging read 'resource.type="cloud_scheduler_job" AND resource.labels.job_id="missing-prediction-check"' --limit=5 --format=json
```

**Function errors?**
```bash
# View function logs
gcloud functions logs read check-missing --gen2 --region=us-west2 --limit=20
```

---

## Next Steps After Deployment

1. **Monitor first run** - Check Slack at 7 PM ET tonight
2. **Verify accuracy** - Ensure no false positives
3. **Fix root cause** - Investigate Phase 3 timing issue
4. **Tune thresholds** - Adjust if too sensitive

---

## Files Reference

- **README.md** - Full documentation
- **SESSION-106-SUMMARY.md** - Complete session summary
- **deploy.sh** - Deployment script
- **setup_schedulers.sh** - Scheduler configuration

---

**Questions?** See README.md for full details

**Status:** ✅ Ready to deploy
