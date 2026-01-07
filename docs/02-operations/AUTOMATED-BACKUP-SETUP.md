# Automated BigQuery Backup Setup Guide

**Status:** 🟡 READY TO DEPLOY
**Priority:** HIGH (30-day plan Week 1)
**Last Updated:** 2026-01-03

---

## 📋 OVERVIEW

This guide provides instructions for setting up automated daily BigQuery backups to protect against data loss.

**What Gets Backed Up:**
- Phase 3: Analytics tables (5 tables)
- Phase 4: Precompute tables (4 tables)
- Orchestration tables (2 tables)
- **Total:** 11 critical tables

**Backup Location:** `gs://nba-bigquery-backups/`
**Retention:** 90 days (lifecycle policy)
**Schedule:** Daily at 2:00 AM PST

---

## 🚀 DEPLOYMENT OPTIONS

### Option 1: Cloud Scheduler + Cloud Function (RECOMMENDED)

**Pros:**
- ✅ Fully managed
- ✅ Automatic execution
- ✅ Error logging
- ✅ Retry on failure

**Cons:**
- Requires Cloud Function deployment
- Slightly more complex setup

**Deployment Steps:**

```bash
# 1. Make deployment script executable
chmod +x bin/operations/deploy_backup_function.sh

# 2. Deploy Cloud Function and Scheduler
./bin/operations/deploy_backup_function.sh

# 3. Verify deployment
gcloud scheduler jobs describe bigquery-daily-backup --location=us-west2

# 4. Test manual trigger
gcloud scheduler jobs run bigquery-daily-backup --location=us-west2

# 5. Check logs
gcloud functions logs read bigquery-backup --region=us-west2 --limit=50
```

**Time to Deploy:** 10-15 minutes

---

### Option 2: Cron + Server (SIMPLE)

**Pros:**
- ✅ Simple setup
- ✅ No additional GCP services
- ✅ Full control

**Cons:**
- Requires a server that's always running
- Manual monitoring needed
- Single point of failure

**Setup Steps:**

```bash
# 1. On a server (e.g., development machine or Compute Engine VM)
crontab -e

# 2. Add this line (runs daily at 2 AM):
0 2 * * * cd /home/naji/code/nba-stats-scraper && ./bin/operations/export_bigquery_tables.sh daily >> /var/log/bigquery-backup.log 2>&1

# 3. Verify cron entry
crontab -l

# 4. Test immediately
./bin/operations/export_bigquery_tables.sh daily
```

**Time to Setup:** 5 minutes

---

### Option 3: Manual Weekly Backups (TEMPORARY)

**Pros:**
- ✅ No automation setup needed
- ✅ Immediate start

**Cons:**
- Requires manual execution
- Easy to forget
- Not production-grade

**Process:**

```bash
# Run this every Monday morning:
./bin/operations/export_bigquery_tables.sh full

# Set a calendar reminder for every Monday 9 AM
```

**Time to Setup:** 1 minute (but manual ongoing)

---

## 📊 DEPLOYED INFRASTRUCTURE (Option 1)

### Cloud Function Details

**Name:** `bigquery-backup`
**Runtime:** Python 3.11
**Region:** us-west2
**Timeout:** 3600s (1 hour)
**Memory:** 512MB
**Trigger:** HTTP

**Environment Variables:**
- `PROJECT_ID=nba-props-platform`

**Files:**
- `cloud_functions/bigquery_backup/main.py`
- `cloud_functions/bigquery_backup/requirements.txt`
- `bin/operations/deploy_backup_function.sh`

### Cloud Scheduler Details

**Name:** `bigquery-daily-backup`
**Schedule:** `0 2 * * *` (2:00 AM daily)
**Timezone:** America/Los_Angeles
**Target:** Cloud Function HTTP endpoint
**Retry:** 3 attempts with exponential backoff

---

## ✅ VERIFICATION CHECKLIST

### After Deployment

- [ ] Cloud Function deployed successfully
  ```bash
  gcloud functions describe bigquery-backup --region=us-west2 --gen2
  ```

- [ ] Cloud Scheduler job created
  ```bash
  gcloud scheduler jobs describe bigquery-daily-backup --location=us-west2
  ```

- [ ] Backup bucket exists with lifecycle policy
  ```bash
  gsutil lifecycle get gs://nba-bigquery-backups
  ```

- [ ] Manual test backup succeeds
  ```bash
  gcloud scheduler jobs run bigquery-daily-backup --location=us-west2
  ```

- [ ] Backup files visible in GCS
  ```bash
  gsutil ls gs://nba-bigquery-backups/daily/$(date +%Y%m%d)/
  ```

- [ ] Backup logs show success
  ```bash
  gcloud functions logs read bigquery-backup --region=us-west2 --limit=10
  ```

### Weekly Monitoring

- [ ] Check last backup date
  ```bash
  gsutil ls -l gs://nba-bigquery-backups/daily/ | tail -10
  ```

- [ ] Verify backup file sizes reasonable
  ```bash
  gsutil du -sh gs://nba-bigquery-backups/daily/$(date +%Y%m%d)/
  ```

- [ ] Check for failures in logs
  ```bash
  gcloud logging read "resource.type=cloud_function AND resource.labels.function_name=bigquery-backup AND severity>=ERROR" --limit=20 --format=json
  ```

---

## 🔧 OPERATIONAL COMMANDS

### Manual Backup Triggers

```bash
# Trigger daily backup now
gcloud scheduler jobs run bigquery-daily-backup --location=us-west2

# Or call function directly
FUNCTION_URL=$(gcloud functions describe bigquery-backup --region=us-west2 --gen2 --format='value(serviceConfig.uri)')
curl -X POST "$FUNCTION_URL?type=daily"

# Run full historical backup (large)
curl -X POST "$FUNCTION_URL?type=full"
```

### Monitoring

```bash
# View recent backup runs
gcloud scheduler jobs executions list bigquery-daily-backup --location=us-west2 --limit=10

# Check function logs
gcloud functions logs read bigquery-backup --region=us-west2 --limit=50

# List recent backups
gsutil ls -lh gs://nba-bigquery-backups/daily/ | tail -7

# Check backup sizes
gsutil du -sh gs://nba-bigquery-backups/daily/$(date +%Y%m%d)/*
```

### Troubleshooting

```bash
# Check function status
gcloud functions describe bigquery-backup --region=us-west2 --gen2

# View error logs
gcloud functions logs read bigquery-backup --region=us-west2 --filter="severity>=ERROR" --limit=20

# Test function locally
cd cloud_functions/bigquery_backup
functions-framework --target=backup_bigquery_tables --debug

# Re-deploy if needed
./bin/operations/deploy_backup_function.sh
```

---

## 📁 BACKUP STRUCTURE

```
gs://nba-bigquery-backups/
├── daily/
│   ├── 20260103/
│   │   ├── phase3/
│   │   │   ├── player_game_summary/
│   │   │   │   ├── 000000000000.avro
│   │   │   │   └── metadata.json
│   │   │   ├── team_offense_game_summary/
│   │   │   ├── team_defense_game_summary/
│   │   │   ├── upcoming_player_game_context/
│   │   │   └── upcoming_team_game_context/
│   │   ├── phase4/
│   │   │   ├── player_composite_factors/
│   │   │   ├── player_shot_zone_analysis/
│   │   │   ├── team_defense_zone_analysis/
│   │   │   └── player_daily_cache/
│   │   └── orchestration/
│   │       ├── processor_output_validation/
│   │       └── workflow_decisions/
│   ├── 20260104/
│   └── ...
├── full/
│   └── (full historical backups, run manually)
└── lifecycle-config.json
```

---

## 🎯 RECOVERY PROCEDURES

### Restore Single Table

```bash
# Load backup into BigQuery
bq load \
  --source_format=AVRO \
  --replace \
  nba-props-platform:nba_analytics.player_game_summary \
  gs://nba-bigquery-backups/daily/20260103/phase3/player_game_summary/*.avro
```

### Restore All Tables

```bash
# Use the restore script (to be created)
./bin/operations/restore_bigquery_tables.sh --date 20260103 --dry-run

# If dry-run looks good, execute
./bin/operations/restore_bigquery_tables.sh --date 20260103
```

### Disaster Recovery

See: `docs/02-operations/disaster-recovery-runbook.md` Section 1

---

## 💰 COST ESTIMATION

### Storage Costs
- **Backup size per day:** ~5-10 GB
- **Retention:** 90 days
- **Total storage:** ~450-900 GB
- **Cost:** $10-20/month (Standard Storage)

### Compute Costs
- **Cloud Function:** $0.40/million invocations
- **Daily runs:** 30/month
- **Cost:** ~$0.01/month

### Data Transfer
- **BigQuery → GCS:** Free (same region)
- **GCS → BigQuery (restore):** Free (same region)

**Total Monthly Cost:** ~$10-20 (primarily storage)

---

## 📈 METRICS & MONITORING

### Success Metrics

- **Backup Success Rate:** >99%
- **Backup Duration:** <30 minutes per day
- **Data Size Trend:** Monitored for anomalies
- **Restore Test:** Monthly (at minimum)

### Alerts to Configure

```bash
# Alert on backup failure
gcloud alpha monitoring policies create \
  --notification-channels=[CHANNEL_ID] \
  --display-name="BigQuery Backup Failure" \
  --condition-display-name="Backup failed" \
  --condition-threshold-value=1 \
  --condition-threshold-duration=3600s \
  --condition-filter='resource.type="cloud_function"
    AND resource.labels.function_name="bigquery-backup"
    AND metric.type="logging.googleapis.com/user/backup_failed"'
```

---

## 🔐 SECURITY CONSIDERATIONS

### Service Account Permissions

The Cloud Function uses the default compute SA. Required permissions:
- `bigquery.jobs.create` (to export)
- `bigquery.tables.get` (to read table metadata)
- `storage.objects.create` (to write backups)
- `storage.objects.delete` (for lifecycle management)

**Security Recommendation:**
Create dedicated backup service account with minimal permissions.

```bash
# Create dedicated SA
gcloud iam service-accounts create bigquery-backup-sa \
  --display-name="BigQuery Backup Service Account"

# Grant minimal required roles
gcloud projects add-iam-policy-binding nba-props-platform \
  --member='serviceAccount:bigquery-backup-sa@nba-props-platform.iam.gserviceaccount.com' \
  --role='roles/bigquery.dataViewer'

gcloud projects add-iam-policy-binding nba-props-platform \
  --member='serviceAccount:bigquery-backup-sa@nba-props-platform.iam.gserviceaccount.com' \
  --role='roles/bigquery.jobUser'

# Grant GCS write access to backup bucket only
gsutil iam ch \
  serviceAccount:bigquery-backup-sa@nba-props-platform.iam.gserviceaccount.com:objectCreator \
  gs://nba-bigquery-backups
```

---

## 📝 TESTING CHECKLIST

Before going live:

- [ ] Test Cloud Function deployment
- [ ] Test manual scheduler trigger
- [ ] Verify backup files created in GCS
- [ ] Verify lifecycle policy applies
- [ ] Test backup restoration process
- [ ] Document recovery time (RTO)
- [ ] Configure failure alerts
- [ ] Update runbooks with backup info

---

## 🔄 MAINTENANCE SCHEDULE

### Daily
- Automated backup runs at 2 AM PST
- Automatic lifecycle cleanup (90+ days)

### Weekly
- Review backup logs for failures
- Check backup file sizes for anomalies

### Monthly
- Test restore procedure (sample table)
- Review storage costs
- Audit service account permissions

### Quarterly
- Full disaster recovery test
- Review and update documentation
- Verify compliance requirements

---

## 📞 SUPPORT

**Issues with backups:**
1. Check Cloud Function logs
2. Check Cloud Scheduler execution history
3. Verify GCS bucket permissions
4. Review disaster recovery runbook

**Escalation:**
- On-call engineer: [FILL IN]
- Slack: #nba-incidents

---

## 📋 DEPLOYMENT STATUS

**Current Status:** 🟡 **READY TO DEPLOY**

**Action Required:**
Choose deployment option and execute:
- **Option 1 (Recommended):** Run `./bin/operations/deploy_backup_function.sh`
- **Option 2 (Simple):** Set up cron job
- **Option 3 (Temporary):** Manual weekly backups until automated

**Estimated Time:** 10-15 minutes (Option 1)

**Priority:** HIGH (Week 1 of 30-day plan)

---

**Next Steps:**
1. Review this guide
2. Choose deployment option
3. Execute deployment
4. Run verification checklist
5. Update disaster recovery runbook with backup info
6. Schedule monthly restore test

**END OF SETUP GUIDE**
