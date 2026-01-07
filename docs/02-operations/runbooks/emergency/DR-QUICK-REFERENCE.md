# Disaster Recovery - Quick Reference Card

**🚨 EMERGENCY USE ONLY**

For complete procedures, see: `docs/02-operations/disaster-recovery-runbook.md`

---

## 📞 Emergency Contacts

```
On-call:    [PHONE] [EMAIL]
Manager:    [PHONE] [EMAIL]
VP Eng:     [PHONE] [EMAIL]
Slack:      #nba-incidents
```

---

## 🎯 Quick Triage

**First, assess the damage:**
```bash
./bin/operations/ops_dashboard.sh quick
```

Match symptoms to scenario below →

---

## 🔥 Disaster Scenarios

### 1. BigQuery Data Loss (P0 - 2-4 hours)

**Symptoms:** Tables missing, queries failing

**Recovery:**
```bash
# Stop pipeline
gcloud scheduler jobs pause morning-operations --location=us-west2
gcloud scheduler jobs pause real-time-business --location=us-west2

# Option A: Restore from backup (if available)
gsutil ls gs://nba-bigquery-backups/daily/
bq load --source_format=AVRO --replace \
  nba_analytics.player_game_summary \
  gs://nba-bigquery-backups/daily/YYYYMMDD/phase3/player_game_summary/*.avro

# Option B: Rebuild from source (4-8 hours)
PYTHONPATH=. python3 backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-01 --end-date 2024-12-31 --workers 15

# Resume pipeline
gcloud scheduler jobs resume morning-operations --location=us-west2
```

---

### 2. GCS Bucket Corruption (P0 - 1-2 hours)

**Symptoms:** Files missing, 404 errors

**Recovery:**
```bash
# Check versioning
gsutil ls -a gs://nba-scraped-data/path/to/file.json

# Restore from version
gsutil cp gs://nba-scraped-data/file.json#1234567890 \
          gs://nba-scraped-data/file.json

# Or restore from backup bucket
gsutil -m rsync -r gs://nba-scraped-data-backup/ gs://nba-scraped-data/
```

---

### 3. Complete System Outage (P0 - 4-8 hours)

**Symptoms:** All services down, no data flowing

**Recovery:**
```bash
cd /home/naji/code/nba-stats-scraper

# Redeploy everything
./bin/raw/deploy/deploy_processors_simple.sh
./bin/analytics/deploy/deploy_analytics_processors.sh
./bin/precompute/deploy/deploy_precompute_processors.sh
./bin/predictions/deploy/deploy_prediction_coordinator.sh
./bin/orchestrators/deploy_phase2_to_phase3.sh
./bin/orchestrators/deploy_phase3_to_phase4.sh
./bin/pubsub/create_pubsub_infrastructure.sh

# Verify
./bin/operations/ops_dashboard.sh
```

---

### 4. Processor Failures (P2 - 1-3 hours)

**Symptoms:** Data gaps for specific dates

**Recovery:**
```bash
# Find missing dates
./bin/operations/ops_dashboard.sh pipeline

# Re-run specific date
PYTHONPATH=. python3 backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2024-11-15 --end-date 2024-11-15

# Verify
bq query "SELECT COUNT(*) FROM nba_analytics.player_game_summary WHERE game_date = '2024-11-15'"
```

---

## ✅ Post-Recovery Validation

```bash
# 1. Check ops dashboard
./bin/operations/ops_dashboard.sh

# 2. Validate row counts
bq query < bin/operations/monitoring_queries.sql

# 3. Test pipeline flow
gcloud scheduler jobs run morning-operations --location=us-west2
watch -n 60 "./bin/operations/ops_dashboard.sh quick"

# 4. Monitor for 24 hours
```

---

## 🔄 Daily Backup (Prevention)

```bash
# Run daily backups
./bin/operations/export_bigquery_tables.sh daily

# Enable GCS versioning
gsutil versioning set on gs://nba-scraped-data/

# Verify backups exist
gsutil ls gs://nba-bigquery-backups/daily/
```

---

## 📋 Incident Reporting

After recovery, create incident report:
```bash
cp /tmp/dr_assessment.txt docs/incidents/INC-$(date +%Y%m%d).md
# Fill in: Timeline, Root cause, Recovery actions, Lessons learned
```

---

## 🔍 Useful Commands

```bash
# Check all datasets
bq ls --project_id=nba-props-platform

# Check scheduler status
gcloud scheduler jobs list --location=us-west2

# Check Cloud Run services
gcloud run services list --region=us-west2

# Check recent errors
python3 monitoring/scripts/nba-monitor errors 24

# Check workflows
python3 monitoring/scripts/nba-monitor workflows

# Full system status
./bin/operations/ops_dashboard.sh
```

---

**REMEMBER:** Stop data ingestion FIRST before any recovery work!

**FULL RUNBOOK:** `docs/02-operations/disaster-recovery-runbook.md`
