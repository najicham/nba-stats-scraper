# Prediction Monitoring - Quick Reference Card

**System Status:** ✅ DEPLOYED (2026-01-18)

---

## 🚀 Quick Commands

### Health Check (30 seconds)
```bash
# Check all components
gcloud scheduler jobs list --location=us-west2 | grep -E "validate-freshness|missing-prediction|daily-reconciliation"
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/check-missing?game_date=$(date +%Y-%m-%d)" | jq '{missing: .missing_count, coverage: .summary.coverage_percent}'
```

### Manual Trigger
```bash
# Trigger missing prediction check now
gcloud scheduler jobs run missing-prediction-check --location=us-west2

# Wait 30s and check result
sleep 30 && curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/check-missing?game_date=$(date +%Y-%m-%d)" | jq .
```

### View Logs
```bash
# Last 20 alerts
gcloud functions logs read check-missing --gen2 --region=us-west2 --limit=20 | grep -i "missing\|alert"

# Scheduler execution history
gcloud logging read 'resource.type="cloud_scheduler_job" AND resource.labels.job_id="missing-prediction-check"' --limit=5
```

---

## 📅 Daily Schedule

| Time (ET) | Job | Action |
|-----------|-----|--------|
| 5:45 PM | validate-freshness-check | ✓ Validate data before predictions |
| 6:00 PM | *predictions run* | (existing system) |
| 7:00 PM | missing-prediction-check | 🚨 Alert if ANY player missing |
| 9:00 AM | daily-reconciliation | 📊 Full pipeline validation |

---

## 🔗 Endpoints

1. **Validate Freshness**
   ```
   curl "https://us-west2-nba-props-platform.cloudfunctions.net/validate-freshness?game_date=YYYY-MM-DD"
   ```

2. **Check Missing**
   ```
   curl "https://us-west2-nba-props-platform.cloudfunctions.net/check-missing?game_date=YYYY-MM-DD"
   ```

3. **Reconcile**
   ```
   curl "https://us-west2-nba-props-platform.cloudfunctions.net/reconcile?game_date=YYYY-MM-DD"
   ```

---

## 📖 Documentation

| File | Purpose |
|------|---------|
| `QUICK-START.md` | Deploy in 3 commands |
| `README.md` | Full documentation |
| `../../docs/09-handoff/MONITORING-VALIDATION-GUIDE.md` | Validation & troubleshooting |
| `../../docs/09-handoff/SESSION-106-SUMMARY.md` | Complete session summary |

---

## 🚨 Alert Channel

**Slack Channel:** Configured via `slack-webhook-monitoring-error` secret
**Alert Level:** CRITICAL for ANY missing player
**When:** 7:00 PM ET daily (after predictions complete)

---

## 🛠️ Troubleshooting

**No alerts?**
```bash
# Check secret
gcloud secrets versions access latest --secret=slack-webhook-monitoring-error | head -c 50

# Check function logs
gcloud functions logs read check-missing --gen2 --region=us-west2 --limit=20 | grep -i slack
```

**Scheduler not running?**
```bash
# Check state
gcloud scheduler jobs describe missing-prediction-check --location=us-west2 | grep state

# Resume if paused
gcloud scheduler jobs resume missing-prediction-check --location=us-west2
```

**Redeploy:**
```bash
cd orchestration/cloud_functions/prediction_monitoring
./deploy.sh && ./setup_schedulers.sh
```

---

## 📊 What to Monitor

**Daily (9 AM ET):**
- Check overnight reconciliation: `curl .../reconcile?game_date=YESTERDAY | jq .overall_status`
- Should return: `"PASS"`

**Daily (7 PM ET):**
- Check Slack for missing prediction alert
- If alert: Investigate which players and why

**Weekly:**
- Review coverage trends (should be ≥95%)
- Check for patterns in missing players

---

## ✅ Success Metrics

- **Coverage:** ≥95% of eligible players
- **Alerts:** Immediate (within 1 hour of predictions)
- **Uptime:** All 3 schedulers ENABLED
- **Response Time:** < 15 seconds per endpoint

---

**Version:** 1.0 | **Last Updated:** 2026-01-18 | **Status:** ✅ Production Ready
