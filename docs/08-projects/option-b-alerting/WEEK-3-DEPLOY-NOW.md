# Week 3 - Ready to Deploy

**All implementation complete!** Copy and run these commands to deploy Week 3 features.

---

## Step 1: Deploy Cloud Monitoring Dashboards (2-3 min)

```bash
cd /home/naji/code/nba-stats-scraper

# Deploy all 3 dashboards
./bin/alerts/create_dashboards.sh nba-props-platform prod

# ✅ Expected: 3 dashboard URLs printed
# Save these URLs for your team
```

**Verify:**
Open the dashboard URLs in your browser. You should see all widgets displaying metrics.

---

## Step 2: Deploy Daily Slack Summary (3-5 min)

**First, set your Slack webhook URL:**

```bash
# Get your Slack webhook URL from:
# https://api.slack.com/messaging/webhooks
# Or use existing webhook from Secret Manager

export SLACK_WEBHOOK_URL='https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX'
```

**Deploy Cloud Function:**

```bash
cd /home/naji/code/nba-stats-scraper

# Deploy Cloud Function + Scheduler
./bin/alerts/deploy_daily_summary.sh nba-props-platform us-west2 prod

# ✅ Expected: Cloud Function deployed, Scheduler created
```

**Test immediately:**

```bash
# Trigger summary now (don't wait for 9 AM)
gcloud scheduler jobs run nba-daily-summary-prod \
  --location=us-west2 \
  --project=nba-props-platform

# ✅ Expected: Slack message received within 1 minute
```

---

## Step 3: Create BigQuery Audit Table (1-2 min)

```bash
# Create audit table
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  "$(cat schemas/bigquery/nba_orchestration/env_var_audit.sql)"

# Create view
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  "$(cat schemas/bigquery/nba_orchestration/recent_env_changes_view.sql)"

# ✅ Expected: Table and view created
```

**Verify:**

```bash
# Check table exists
bq show nba_orchestration.env_var_audit

# Query view
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  'SELECT * FROM `nba_orchestration.recent_env_changes` LIMIT 5'
```

---

## Step 4: Deploy Updated env_monitor.py (5-7 min)

The updated `env_monitor.py` with BigQuery logging is already in the worker code. Deploy it:

```bash
cd /home/naji/code/nba-stats-scraper

# Deploy prediction worker with updated env_monitor.py
./bin/predictions/deploy/deploy_prediction_worker.sh prod

# ✅ Expected: New revision deployed
```

**Verify audit logging works:**

```bash
# Trigger env check
curl -X POST https://prediction-worker-f7p3g7f6ya-wl.a.run.app/internal/check-env

# Check BigQuery for new audit entry
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  'SELECT * FROM `nba_orchestration.env_var_audit` ORDER BY timestamp DESC LIMIT 5'

# ✅ Expected: New row in audit table
```

---

## Verification Checklist

### ✅ Dashboards
- [ ] 3 dashboards visible in Cloud Monitoring console
- [ ] All widgets showing data (not "No data available")
- [ ] Thresholds visible (yellow/red lines on charts)

### ✅ Daily Summary
- [ ] Cloud Function deployed: `nba-daily-summary-prod`
- [ ] Scheduler created: runs daily at 9 AM ET
- [ ] Test message received in Slack
- [ ] Message shows yesterday's stats and top picks

### ✅ Audit Trail
- [ ] BigQuery table created: `nba_orchestration.env_var_audit`
- [ ] View created: `nba_orchestration.recent_env_changes`
- [ ] Audit entries appear after env check
- [ ] Can query recent changes

### ✅ Updated Worker
- [ ] New revision deployed with updated env_monitor.py
- [ ] Audit logging working (entries in BigQuery)
- [ ] No errors in worker logs

---

## Troubleshooting

### Dashboard shows "No data"
**Solution:** Wait 5 minutes for metrics to populate, then refresh

### Daily summary not received
**Check:**
```bash
# View Cloud Function logs
gcloud functions logs read nba-daily-summary-prod \
  --region=us-west2 \
  --project=nba-props-platform \
  --limit=50
```

### Audit table not getting data
**Check:**
```bash
# View worker logs for BigQuery errors
gcloud run services logs read prediction-worker \
  --project=nba-props-platform \
  --region=us-west2 \
  --limit=20
```

---

## Next Steps

After successful deployment:

1. **Share dashboard URLs** with your team
2. **Document dashboard links** in your internal wiki
3. **Test daily summary** by waiting for 9 AM ET delivery
4. **Review audit trail** periodically for unexpected changes

---

## Quick Reference

### Dashboard URLs
```bash
# Get all dashboard URLs
gcloud monitoring dashboards list \
  --project=nba-props-platform \
  --format="table(name,displayName)"
```

### Trigger Daily Summary
```bash
# Manual trigger (for testing)
gcloud scheduler jobs run nba-daily-summary-prod \
  --location=us-west2 \
  --project=nba-props-platform
```

### Query Audit Trail
```sql
-- Recent env var changes
SELECT * FROM `nba_orchestration.recent_env_changes`
ORDER BY timestamp DESC LIMIT 20;
```

---

**Status:** Ready to deploy! Run the commands above to complete Week 3.

**Deployment Time:** ~15-20 minutes total
**Documentation:** See `WEEK-3-IMPLEMENTATION-COMPLETE.md` for full details
