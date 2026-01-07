# Disaster Recovery Runbook

**Created:** 2026-01-03 (Session 6)
**Version:** 1.0
**Owner:** Operations Team
**Criticality:** HIGH - Required for Production

---

## 🎯 Purpose

This runbook provides step-by-step procedures for recovering from catastrophic system failures. These procedures are designed to be executed under pressure during incidents.

**When to use this runbook:**
- Complete data loss in BigQuery datasets
- GCS bucket corruption or deletion
- Firestore orchestration state loss
- Multiple processor failures
- Complete system outage

---

## 📋 Table of Contents

1. [Emergency Contacts & Escalation](#emergency-contacts--escalation)
2. [Disaster Scenarios Overview](#disaster-scenarios-overview)
3. [DR Scenario 1: BigQuery Dataset Loss](#dr-scenario-1-bigquery-dataset-loss)
4. [DR Scenario 2: GCS Bucket Corruption](#dr-scenario-2-gcs-bucket-corruption)
5. [DR Scenario 3: Firestore State Loss](#dr-scenario-3-firestore-state-loss)
6. [DR Scenario 4: Complete System Outage](#dr-scenario-4-complete-system-outage)
7. [DR Scenario 5: Phase Processor Failures](#dr-scenario-5-phase-processor-failures)
8. [Backup & Export Procedures](#backup--export-procedures)
9. [Recovery Validation](#recovery-validation)
10. [Post-Recovery Checklist](#post-recovery-checklist)

---

## 🚨 Emergency Contacts & Escalation

### Severity Levels

| Level | Description | Response Time | Escalation |
|-------|-------------|---------------|------------|
| **P0** | Complete system down, data loss | Immediate | VP Engineering |
| **P1** | Critical pipeline failure, major data corruption | <15 min | Engineering Manager |
| **P2** | Partial pipeline failure, recoverable | <1 hour | Team Lead |
| **P3** | Non-critical issues, monitoring alerts | <4 hours | On-call Engineer |

### Contact Information

```
# UPDATE WITH ACTUAL CONTACTS
On-call Engineer:    [PHONE] [EMAIL]
Team Lead:           [PHONE] [EMAIL]
Engineering Manager: [PHONE] [EMAIL]
VP Engineering:      [PHONE] [EMAIL]
GCP Support:         [SUPPORT CASE URL]
```

### Communication Channels

- **Primary:** Slack #nba-incidents
- **Secondary:** Email distribution list
- **Emergency:** Phone tree

---

## 🗺️ Disaster Scenarios Overview

| Scenario | Severity | Recovery Time | Data Loss Risk | Prerequisites |
|----------|----------|---------------|----------------|---------------|
| BigQuery Dataset Loss | P0 | 2-4 hours | HIGH | GCS backups |
| GCS Bucket Corruption | P0 | 1-2 hours | MEDIUM | Versioning enabled |
| Firestore State Loss | P1 | 30-60 min | LOW | Logs intact |
| Complete System Outage | P0 | 4-8 hours | VARIES | All components |
| Phase Processor Failures | P2 | 1-3 hours | LOW | Re-run capability |

---

## DR Scenario 1: BigQuery Dataset Loss

**Severity:** P0
**Estimated Recovery Time:** 2-4 hours
**Data Loss Risk:** HIGH (without backups)

### Symptoms
- BigQuery tables missing or empty
- Queries failing with "Not found: Table"
- Pipeline cannot write data

### Prerequisites
- GCS backup bucket exists: `gs://nba-scraped-data/`
- Sufficient BigQuery quota
- Dataset export/import permissions

### Recovery Procedure

#### Step 1: Assess Damage (5 minutes)

```bash
# Check which datasets are affected
bq ls --project_id=nba-props-platform

# Expected datasets:
# - nba_raw
# - nba_analytics
# - nba_precompute
# - nba_predictions
# - nba_grading
# - nba_orchestration

# Check specific tables
bq ls nba_analytics
bq ls nba_precompute

# Document which tables are missing
echo "Missing tables:" > /tmp/dr_assessment.txt
```

#### Step 2: Stop All Data Ingestion (2 minutes)

**CRITICAL:** Prevent data corruption during recovery

```bash
# Disable all Cloud Scheduler jobs
gcloud scheduler jobs pause morning-operations --location=us-west2
gcloud scheduler jobs pause early-morning-final-check --location=us-west2
gcloud scheduler jobs pause real-time-business --location=us-west2
gcloud scheduler jobs pause post-game-collection --location=us-west2
gcloud scheduler jobs pause late-night-recovery --location=us-west2

# Verify paused
gcloud scheduler jobs list --location=us-west2 | grep PAUSED

# Document pause time
echo "Pipeline paused at: $(date)" >> /tmp/dr_assessment.txt
```

#### Step 3: Recreate Datasets (if completely missing)

```bash
# Recreate nba_analytics dataset
bq mk --dataset \
  --location=US \
  --description="Analytics layer (Phase 3) - Recovered $(date)" \
  nba-props-platform:nba_analytics

# Recreate nba_precompute dataset
bq mk --dataset \
  --location=US \
  --description="Precompute layer (Phase 4) - Recovered $(date)" \
  nba-props-platform:nba_precompute

# Recreate nba_predictions dataset
bq mk --dataset \
  --location=US \
  --description="Predictions (Phase 5) - Recovered $(date)" \
  nba-props-platform:nba_predictions

# Recreate nba_orchestration dataset
bq mk --dataset \
  --location=US \
  --description="Orchestration metadata - Recovered $(date)" \
  nba-props-platform:nba_orchestration
```

#### Step 4A: Restore from BigQuery Backups (if available)

**Option 1: Restore from table snapshots**

```bash
# List available snapshots
bq ls --project_id=nba-props-platform --snapshots nba_analytics

# Restore specific table from snapshot
bq cp \
  nba-props-platform:nba_analytics.player_game_summary@1234567890000 \
  nba-props-platform:nba_analytics.player_game_summary

# Restore all Phase 3 tables
for table in player_game_summary team_offense_game_summary team_defense_game_summary \
             upcoming_player_game_context upcoming_team_game_context; do
  echo "Restoring $table..."
  # Find latest snapshot (replace TIMESTAMP)
  bq cp \
    nba-props-platform:nba_analytics.${table}@TIMESTAMP \
    nba-props-platform:nba_analytics.${table}
done
```

**Option 2: Restore from exports**

```bash
# If tables were exported to GCS (recommended setup)
# Check for exports
gsutil ls gs://nba-bigquery-backups/exports/

# Restore from exports
bq load \
  --source_format=AVRO \
  --replace \
  nba_analytics.player_game_summary \
  gs://nba-bigquery-backups/exports/player_game_summary/*.avro
```

#### Step 4B: Rebuild from Source Data (if no backups)

**WARNING:** This takes 4-8 hours for full historical data

```bash
# Phase 3: Re-run analytics backfill from GCS source data
cd /home/naji/code/nba-stats-scraper

# Start Phase 3 backfill (2021-2024)
PYTHONPATH=. python3 backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2021-10-01 \
  --end-date 2024-12-31 \
  --workers 15

# Monitor progress
tail -f logs/analytics_backfill_*.log

# Phase 4: Re-run precompute backfill (depends on Phase 3)
# Wait for Phase 3 to complete first!
./bin/backfill/run_phase4_backfill.sh 2021-10-01 2024-12-31
```

#### Step 5: Validate Recovery (15 minutes)

```bash
# Check row counts match expectations
bq query --use_legacy_sql=false "
SELECT
  'player_game_summary' as table_name,
  COUNT(*) as row_count,
  COUNT(DISTINCT game_date) as unique_dates,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
UNION ALL
SELECT
  'player_composite_factors' as table_name,
  COUNT(*) as row_count,
  COUNT(DISTINCT game_date) as unique_dates,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
"

# Expected results (approximate):
# - player_game_summary: ~130,000 rows, ~1000 dates (2021-2024)
# - player_composite_factors: ~100,000 rows, ~880 dates (88% coverage)

# Run ops dashboard to verify
./bin/operations/ops_dashboard.sh pipeline
```

#### Step 6: Resume Operations (2 minutes)

```bash
# Re-enable schedulers ONLY after validation passes
gcloud scheduler jobs resume morning-operations --location=us-west2
gcloud scheduler jobs resume early-morning-final-check --location=us-west2
gcloud scheduler jobs resume real-time-business --location=us-west2
gcloud scheduler jobs resume post-game-collection --location=us-west2
gcloud scheduler jobs resume late-night-recovery --location=us-west2

# Verify resumed
gcloud scheduler jobs list --location=us-west2

# Document recovery completion
echo "Recovery complete at: $(date)" >> /tmp/dr_assessment.txt
echo "Pipeline resumed at: $(date)" >> /tmp/dr_assessment.txt
```

#### Step 7: Post-Recovery Actions

```bash
# Create incident report
cp /tmp/dr_assessment.txt docs/incidents/bigquery_recovery_$(date +%Y%m%d).md

# Setup automated backups (if not already configured)
# See "Backup & Export Procedures" section below

# Monitor for 24 hours
watch -n 300 "./bin/operations/ops_dashboard.sh quick"
```

---

## DR Scenario 2: GCS Bucket Corruption

**Severity:** P0
**Estimated Recovery Time:** 1-2 hours
**Data Loss Risk:** MEDIUM (if versioning enabled: LOW)

### Symptoms
- GCS files missing or corrupted
- Processors failing to read source data
- "404 Not Found" errors in logs

### Prerequisites
- Object versioning enabled on buckets
- Sufficient storage quota
- GCS admin permissions

### Recovery Procedure

#### Step 1: Assess Damage (5 minutes)

```bash
# Check bucket status
gsutil ls gs://nba-scraped-data/

# Check for missing or corrupted files
gsutil ls -l gs://nba-scraped-data/ball-dont-lie/live-boxscores/2024-*/ | head -n 20

# Count files by source
echo "=== File counts by source ==="
gsutil ls gs://nba-scraped-data/**/2024-* | wc -l
```

#### Step 2: Stop Data Ingestion (2 minutes)

```bash
# Pause scrapers to prevent overwriting
gcloud scheduler jobs pause morning-operations --location=us-west2
gcloud scheduler jobs pause real-time-business --location=us-west2

# Verify no active uploads
gsutil ls -l gs://nba-scraped-data/ | grep "$(date +%Y-%m-%d)"
```

#### Step 3A: Restore from Object Versioning (if enabled)

```bash
# List object versions
gsutil ls -a gs://nba-scraped-data/ball-dont-lie/live-boxscores/2024-11-15/

# Restore specific file from version
gsutil cp \
  gs://nba-scraped-data/ball-dont-lie/live-boxscores/2024-11-15/file.json#1234567890 \
  gs://nba-scraped-data/ball-dont-lie/live-boxscores/2024-11-15/file.json

# Bulk restore (if many files affected)
# Create recovery script
cat > /tmp/restore_gcs.sh <<'EOF'
#!/bin/bash
BUCKET="gs://nba-scraped-data"
DATE_RANGE="2024-11-*"

# List all deleted files
gsutil ls -a "$BUCKET/**/$DATE_RANGE" | grep "#" | while read versioned_path; do
  # Extract original path
  original_path=$(echo "$versioned_path" | cut -d'#' -f1)

  # Restore if original doesn't exist
  if ! gsutil ls "$original_path" 2>/dev/null; then
    echo "Restoring: $original_path"
    gsutil cp "$versioned_path" "$original_path"
  fi
done
EOF

chmod +x /tmp/restore_gcs.sh
/tmp/restore_gcs.sh
```

#### Step 3B: Restore from Backup Bucket (if versioning not enabled)

```bash
# Assuming backup bucket: gs://nba-scraped-data-backup/
# Copy from backup
gsutil -m rsync -r \
  gs://nba-scraped-data-backup/ball-dont-lie/ \
  gs://nba-scraped-data/ball-dont-lie/

# Verify restored
gsutil ls -r gs://nba-scraped-data/ball-dont-lie/live-boxscores/2024-11-15/
```

#### Step 3C: Re-scrape Data (if no backups available)

```bash
# Re-run scrapers for affected dates
cd /home/naji/code/nba-stats-scraper

# Identify missing dates
echo "Checking missing dates..."
for date in $(seq -f "2024-11-%02g" 1 30); do
  count=$(gsutil ls gs://nba-scraped-data/ball-dont-lie/live-boxscores/$date/ 2>/dev/null | wc -l)
  if [[ $count -eq 0 ]]; then
    echo "Missing: $date"
  fi
done

# Re-run backfill for missing dates
# See backfill procedures in backfill section
```

#### Step 4: Validate GCS Recovery

```bash
# Verify file counts match expectations
echo "=== Validation ==="
gsutil ls gs://nba-scraped-data/ball-dont-lie/live-boxscores/2024-11-15/ | wc -l
# Expected: 10-15 files per game date

# Check file integrity
gsutil cat gs://nba-scraped-data/ball-dont-lie/live-boxscores/2024-11-15/file.json | jq . > /dev/null
echo "File integrity: OK"

# Run ops dashboard
./bin/operations/ops_dashboard.sh pipeline
```

#### Step 5: Resume Operations

```bash
# Resume scrapers
gcloud scheduler jobs resume morning-operations --location=us-west2
gcloud scheduler jobs resume real-time-business --location=us-west2

# Monitor for 1 hour
watch -n 300 "gsutil ls gs://nba-scraped-data/**/$(date +%Y-%m-%d)/"
```

---

## DR Scenario 3: Firestore State Loss

**Severity:** P1
**Estimated Recovery Time:** 30-60 minutes
**Data Loss Risk:** LOW

### Symptoms
- Orchestrators not transitioning between phases
- Phase 2→3, 3→4 coordination failing
- Firestore queries returning empty results

### Prerequisites
- Cloud Logging intact (90 day retention)
- Firestore admin permissions

### Recovery Procedure

#### Step 1: Assess Firestore Damage (5 minutes)

```bash
# Check Firestore collections exist
gcloud firestore databases list --project=nba-props-platform

# List collections (via gcloud)
# Note: Requires firestore CLI or Python script
python3 <<EOF
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')

# Check key collections
collections = ['phase2_completion', 'phase3_completion', 'phase4_completion', 'processor_run_history']
for coll in collections:
    docs = list(db.collection(coll).limit(5).stream())
    print(f"{coll}: {len(docs)} docs (sample)")
EOF
```

#### Step 2: Stop Orchestrators (2 minutes)

```bash
# Pause orchestrators to prevent conflicts
gcloud scheduler jobs pause morning-operations --location=us-west2
gcloud scheduler jobs pause real-time-business --location=us-west2
```

#### Step 3: Rebuild State from Logs (30 minutes)

**Firestore is primarily used for phase transition coordination. We can rebuild from:**
1. BigQuery processor completion records
2. Cloud Logging
3. GCS file timestamps

```python
# Save as: /tmp/rebuild_firestore_state.py
"""Rebuild Firestore orchestration state from BigQuery and logs."""

from google.cloud import firestore, bigquery
from datetime import datetime, timedelta

db = firestore.Client(project='nba-props-platform')
bq = bigquery.Client(project='nba-props-platform')

# Rebuild phase completion state for last 30 days
end_date = datetime.now().date()
start_date = end_date - timedelta(days=30)

print(f"Rebuilding Firestore state from {start_date} to {end_date}")

# Query Phase 3 completion from BigQuery
phase3_query = f"""
SELECT DISTINCT
    game_date,
    'player_game_summary' as processor,
    MAX(TIMESTAMP(created_at)) as completed_at
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '{start_date}'
GROUP BY game_date
"""

phase3_results = bq.query(phase3_query).result()

# Rebuild phase3_completion collection
for row in phase3_results:
    game_date = row.game_date.strftime('%Y-%m-%d')
    doc_ref = db.collection('phase3_completion').document(game_date)

    doc_ref.set({
        'game_date': game_date,
        'processors': {
            'player_game_summary': {
                'completed': True,
                'completed_at': row.completed_at,
                'status': 'recovered'
            }
        },
        'all_complete': False,  # Conservative - will be updated by next run
        'recovered_at': firestore.SERVER_TIMESTAMP
    }, merge=True)

    print(f"Recovered: {game_date}")

print("Firestore state recovery complete")
```

Run recovery script:

```bash
PYTHONPATH=. python3 /tmp/rebuild_firestore_state.py
```

#### Step 4: Validate Firestore Recovery

```bash
# Check collections are populated
python3 <<EOF
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')

# Verify phase3_completion
docs = list(db.collection('phase3_completion').limit(10).stream())
print(f"phase3_completion docs: {len(docs)}")

for doc in docs[:3]:
    print(f"  {doc.id}: {doc.to_dict()}")
EOF
```

#### Step 5: Resume Operations

```bash
# Resume orchestrators
gcloud scheduler jobs resume morning-operations --location=us-west2
gcloud scheduler jobs resume real-time-business --location=us-west2

# Monitor orchestration logs
gcloud logging read 'resource.type="cloud_function" AND resource.labels.function_name="phase3_to_phase4"' \
  --limit=10 \
  --format="table(timestamp,textPayload)"
```

---

## DR Scenario 4: Complete System Outage

**Severity:** P0
**Estimated Recovery Time:** 4-8 hours
**Data Loss Risk:** VARIES

### Symptoms
- All Cloud Run services down
- No data flowing through pipeline
- All workflows failing
- Complete loss of service

### Prerequisites
- Infrastructure as Code (deployment scripts)
- Container images in Container Registry
- GCP project permissions

### Recovery Procedure

#### Step 1: Assess Scope (10 minutes)

```bash
# Check all Cloud Run services
gcloud run services list --platform=managed --region=us-west2

# Check Cloud Functions
gcloud functions list --region=us-west2

# Check Cloud Scheduler
gcloud scheduler jobs list --location=us-west2

# Check Pub/Sub topics
gcloud pubsub topics list

# Document status
./bin/operations/ops_dashboard.sh > /tmp/outage_assessment_$(date +%Y%m%d_%H%M%S).txt
```

#### Step 2: Redeploy Infrastructure (2-4 hours)

**Phase 2: Raw Processors**

```bash
cd /home/naji/code/nba-stats-scraper

# Deploy Phase 2 processors
./bin/raw/deploy/deploy_processors_simple.sh

# Verify deployment
gcloud run services list --region=us-west2 | grep nba-phase2
```

**Phase 3: Analytics Processors**

```bash
# Deploy Phase 3 processors
./bin/analytics/deploy/deploy_analytics_processors.sh

# Verify
gcloud run services list --region=us-west2 | grep nba-phase3
```

**Phase 4: Precompute Processors**

```bash
# Deploy Phase 4 processors
./bin/precompute/deploy/deploy_precompute_processors.sh

# Verify
gcloud run services list --region=us-west2 | grep nba-phase4
```

**Phase 5: Predictions**

```bash
# Deploy prediction services
./bin/predictions/deploy/deploy_prediction_coordinator.sh
./bin/predictions/deploy/deploy_prediction_worker.sh

# Verify
gcloud run services list --region=us-west2 | grep prediction
```

**Orchestrators**

```bash
# Deploy orchestration Cloud Functions
./bin/orchestrators/deploy_phase2_to_phase3.sh
./bin/orchestrators/deploy_phase3_to_phase4.sh
./bin/orchestrators/deploy_phase4_to_phase5.sh
./bin/orchestrators/deploy_phase5_to_phase6.sh

# Verify
gcloud functions list --region=us-west2
```

**Pub/Sub Infrastructure**

```bash
# Recreate Pub/Sub topics and subscriptions
./bin/pubsub/create_pubsub_infrastructure.sh

# Verify
gcloud pubsub topics list
gcloud pubsub subscriptions list
```

**Cloud Schedulers**

```bash
# Setup schedulers
./bin/orchestrators/setup_same_day_schedulers.sh
./bin/orchestrators/setup_yesterday_analytics_scheduler.sh

# Verify
gcloud scheduler jobs list --location=us-west2
```

#### Step 3: Validate End-to-End Flow (30 minutes)

```bash
# Test Phase 1→2 flow
# Trigger a test scraper run
gcloud scheduler jobs run morning-operations --location=us-west2

# Monitor logs
gcloud logging read 'resource.type="cloud_run_revision"' --limit=20 --freshness=5m

# Check Phase 2→3 transition
# Wait for Phase 2 to complete, verify Phase 3 triggered

# Run full dashboard check
./bin/operations/ops_dashboard.sh
```

#### Step 4: Resume Normal Operations

```bash
# Enable all schedulers
gcloud scheduler jobs resume morning-operations --location=us-west2
gcloud scheduler jobs resume early-morning-final-check --location=us-west2
gcloud scheduler jobs resume real-time-business --location=us-west2
gcloud scheduler jobs resume post-game-collection --location=us-west2
gcloud scheduler jobs resume late-night-recovery --location=us-west2

# Monitor continuously
watch -n 300 "./bin/operations/ops_dashboard.sh quick"
```

---

## DR Scenario 5: Phase Processor Failures

**Severity:** P2
**Estimated Recovery Time:** 1-3 hours
**Data Loss Risk:** LOW

### Symptoms
- Specific processor returning errors
- Data gaps for specific dates
- Processor logs showing failures

### Recovery Procedure

#### Step 1: Identify Failed Dates (5 minutes)

```bash
# Check ops dashboard for failures
./bin/operations/ops_dashboard.sh pipeline

# Query for missing dates
bq query --use_legacy_sql=false "
SELECT DISTINCT
    schedule.game_date,
    CASE WHEN pgs.game_date IS NULL THEN 'MISSING' ELSE 'OK' END as status
FROM (
    SELECT DISTINCT game_date
    FROM \`nba-props-platform.nba_raw.nbac_schedule\`
    WHERE game_date >= '2024-10-01'
) schedule
LEFT JOIN \`nba-props-platform.nba_analytics.player_game_summary\` pgs
    ON schedule.game_date = pgs.game_date
WHERE pgs.game_date IS NULL
ORDER BY schedule.game_date
"
```

#### Step 2: Re-run Failed Processors

**Phase 3: Analytics Processor**

```bash
# Re-run specific dates
curl -X POST https://nba-phase3-analytics-processors-XXXXX.run.app/process-date \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2024-11-15", "processor": "player_game_summary"}'

# Or use backfill script
PYTHONPATH=. python3 backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2024-11-15 \
  --end-date 2024-11-15
```

**Phase 4: Precompute Processor**

```bash
# Re-run Phase 4 for specific dates
curl -X POST https://nba-phase4-precompute-processors-XXXXX.run.app/process-date \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2024-11-15"}'
```

#### Step 3: Validate Recovery

```bash
# Check data now exists
bq query --use_legacy_sql=false "
SELECT COUNT(*) as row_count
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2024-11-15'
"

# Run ops dashboard
./bin/operations/ops_dashboard.sh pipeline
```

---

## 🔄 Backup & Export Procedures

### Automated BigQuery Backups

**Setup scheduled exports (recommended):**

```bash
# Create backup bucket
gsutil mb -l US gs://nba-bigquery-backups/

# Setup lifecycle policy
cat > /tmp/lifecycle.json <<EOF
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {"age": 90}
      }
    ]
  }
}
EOF

gsutil lifecycle set /tmp/lifecycle.json gs://nba-bigquery-backups/

# Create export script
cat > /home/naji/code/nba-stats-scraper/bin/operations/export_bigquery_tables.sh <<'EOF'
#!/bin/bash
# Export critical BigQuery tables to GCS

DATE=$(date +%Y%m%d)
BACKUP_BUCKET="gs://nba-bigquery-backups"

# Export Phase 3 tables
bq extract --destination_format=AVRO \
  nba-props-platform:nba_analytics.player_game_summary \
  "${BACKUP_BUCKET}/daily/${DATE}/player_game_summary/*.avro"

bq extract --destination_format=AVRO \
  nba-props-platform:nba_analytics.team_offense_game_summary \
  "${BACKUP_BUCKET}/daily/${DATE}/team_offense_game_summary/*.avro"

# Export Phase 4 tables
bq extract --destination_format=AVRO \
  nba-props-platform:nba_precompute.player_composite_factors \
  "${BACKUP_BUCKET}/daily/${DATE}/player_composite_factors/*.avro"

echo "Backup complete: ${BACKUP_BUCKET}/daily/${DATE}/"
EOF

chmod +x /home/naji/code/nba-stats-scraper/bin/operations/export_bigquery_tables.sh
```

**Schedule daily exports:**

```bash
# Create Cloud Scheduler job for daily backups
gcloud scheduler jobs create http bigquery-daily-backup \
  --location=us-west2 \
  --schedule="0 4 * * *" \
  --uri="https://CLOUD_FUNCTION_URL/export-bigquery" \
  --http-method=POST \
  --oidc-service-account-email="nba-scheduler@nba-props-platform.iam.gserviceaccount.com"
```

### GCS Versioning & Backup

```bash
# Enable versioning on main bucket (if not already enabled)
gsutil versioning set on gs://nba-scraped-data/

# Create backup bucket with cross-region replication
gsutil mb -l US-WEST2 gs://nba-scraped-data-backup/

# Setup rsync cron job
crontab -e
# Add: 0 3 * * * gsutil -m rsync -r gs://nba-scraped-data/ gs://nba-scraped-data-backup/
```

### Manual On-Demand Backup

```bash
# Export all analytics tables
./bin/operations/export_bigquery_tables.sh

# Snapshot GCS bucket
gsutil -m rsync -r gs://nba-scraped-data/ gs://nba-scraped-data-snapshot-$(date +%Y%m%d)/

# Export Firestore (requires firestore export setup)
gcloud firestore export gs://nba-firestore-backups/$(date +%Y%m%d) --async
```

---

## ✅ Recovery Validation

After any recovery procedure, run these validation checks:

### 1. Data Completeness Check

```bash
# Run ops dashboard
./bin/operations/ops_dashboard.sh

# Check expected row counts
bq query --use_legacy_sql=false < bin/operations/monitoring_queries.sql
```

### 2. Pipeline Flow Test

```bash
# Trigger test workflow
gcloud scheduler jobs run morning-operations --location=us-west2

# Monitor for 30 minutes
watch -n 60 "./bin/operations/ops_dashboard.sh quick"
```

### 3. Data Quality Validation

```bash
# Run validation scripts
./scripts/validation/validate_player_summary.sh
./scripts/validation/validate_team_offense.sh

# Check feature quality
bq query --use_legacy_sql=false "
SELECT
    COUNT(*) as total,
    COUNTIF(minutes_played IS NULL) as null_minutes,
    COUNTIF(usage_rate IS NULL) as null_usage_rate
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '2024-10-01'
"
```

### 4. End-to-End Flow Validation

```bash
# Test complete pipeline: Phase 1 → Phase 6
# 1. Scraper runs
# 2. Raw processors run
# 3. Analytics processors run
# 4. Precompute processors run
# 5. Predictions generated
# 6. Publishing completes

# Monitor via workflows
python3 monitoring/scripts/nba-monitor workflows 1
```

---

## 📋 Post-Recovery Checklist

After completing disaster recovery:

- [ ] **All services deployed and healthy**
  - [ ] Cloud Run services: `gcloud run services list`
  - [ ] Cloud Functions: `gcloud functions list`
  - [ ] Cloud Schedulers: `gcloud scheduler jobs list`

- [ ] **Data validated**
  - [ ] BigQuery row counts match expectations
  - [ ] GCS files present for recent dates
  - [ ] Firestore collections populated

- [ ] **Pipeline flowing**
  - [ ] Test workflow executed successfully
  - [ ] Phase transitions working
  - [ ] No errors in last hour

- [ ] **Monitoring active**
  - [ ] Ops dashboard showing healthy status
  - [ ] Alerts configured and firing correctly
  - [ ] Logs being written

- [ ] **Backups configured**
  - [ ] Automated BigQuery exports enabled
  - [ ] GCS versioning enabled
  - [ ] Firestore exports scheduled

- [ ] **Documentation updated**
  - [ ] Incident report created in `docs/incidents/`
  - [ ] Recovery procedure notes added to runbook
  - [ ] Team notified of recovery completion

- [ ] **Monitoring period**
  - [ ] Monitor system for 24 hours
  - [ ] Check ops dashboard every 4 hours
  - [ ] Review error logs daily

---

## 🔍 Testing Disaster Recovery

**Recommended: Test DR procedures quarterly**

### DR Drill Schedule

| Quarter | Scenario to Test | Expected Duration |
|---------|------------------|-------------------|
| Q1 | Phase Processor Failure | 1-2 hours |
| Q2 | GCS File Restore | 1 hour |
| Q3 | BigQuery Table Restore | 2-3 hours |
| Q4 | Complete System Redeploy | 4-6 hours |

### Test Procedure

1. **Schedule DR drill** - Announce to team, avoid production hours
2. **Create test environment** - Use separate GCP project if possible
3. **Execute recovery steps** - Follow runbook exactly
4. **Document deviations** - Note any steps that didn't work as documented
5. **Update runbook** - Improve procedures based on findings
6. **Team debrief** - Discuss lessons learned

---

## 📞 Escalation Paths

### When to Escalate

| Situation | Escalate To | Timeline |
|-----------|-------------|----------|
| Recovery time exceeds estimate by 2x | Engineering Manager | Immediately |
| Data loss confirmed | VP Engineering | Immediately |
| Unable to restore from backups | GCP Support | Within 15 min |
| Customer-facing impact | Product/Business Lead | Immediately |
| Need additional resources/permissions | Engineering Manager | Immediately |

### GCP Support Contacts

```
# Open P1 support case
gcloud support cases create \
  --priority=P1 \
  --title="NBA Props Platform - [ISSUE]" \
  --description="[DETAILED DESCRIPTION]" \
  --service="BigQuery" \
  --category="Data Loss"

# Check case status
gcloud support cases list
```

---

## 📝 Incident Documentation Template

After recovery, document the incident:

```markdown
# Incident Report: [DATE]

## Summary
- **Incident ID:** INC-YYYYMMDD-NNN
- **Severity:** P0/P1/P2
- **Duration:** X hours Y minutes
- **Data Loss:** Yes/No - [description]
- **Customer Impact:** Yes/No - [description]

## Timeline
- [HH:MM] Issue detected
- [HH:MM] Team notified
- [HH:MM] Root cause identified
- [HH:MM] Recovery started
- [HH:MM] Service restored
- [HH:MM] Validation complete

## Root Cause
[Detailed analysis of what caused the issue]

## Recovery Actions Taken
1. [Step by step what was done]
2. ...

## Data Impact
- Tables affected: [list]
- Date range affected: [range]
- Recovery method: [snapshots/backups/rebuild]
- Data loss: [none/partial/complete]

## Lessons Learned
- What went well:
- What could be improved:
- Action items:

## Follow-up Actions
- [ ] Update runbook with [specific improvements]
- [ ] Implement [preventive measure]
- [ ] Schedule DR drill to test [scenario]
```

---

## 🔒 Version Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-03 | Operations Team | Initial DR runbook created (Session 6) |

---

## 📚 Related Documentation

- **Operations Dashboard:** `bin/operations/README.md`
- **Daily Operations:** `docs/02-operations/daily-operations-runbook.md`
- **Incident Response:** `docs/02-operations/incident-response.md`
- **Troubleshooting:** `docs/02-operations/troubleshooting-guide.md`
- **Architecture:** `docs/01-architecture/v1.0-architecture-overview.md`

---

**END OF DISASTER RECOVERY RUNBOOK**
