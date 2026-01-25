# Troubleshooting Runbook

Common issues and how to fix them.

## Decision Tree

```
Error emails flooding inbox?
├── Yes → Check rate limiting (see below)
└── No
    │
    Data not flowing?
    ├── Yes → Check pipeline flow (see below)
    └── No
        │
        Specific processor failing?
        └── Yes → Check processor-specific issues (see below)
```

## Issue: Email Flood (100+ emails/hour)

### Symptoms
- Inbox overwhelmed with identical error emails
- All emails have same error message

### Cause
Rate limiting may not be working, or new error type not covered.

### Fix
1. Check if rate limiting is enabled in Cloud Run env vars
2. If errors are systematic, fix the root cause first
3. Redeploy with rate limiting: `./bin/raw/deploy/deploy_processors_simple.sh`

---

## Issue: Schedule Data Stale

### Symptoms
- Games showing wrong status (e.g., "Scheduled" when game is "Final")
- Game times incorrect

### Check
```sql
SELECT game_date, MAX(created_at) as last_update,
       TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), MINUTE) as mins_stale
FROM nba_raw.nbac_schedule
WHERE game_date >= CURRENT_DATE()
GROUP BY 1;
```

### Fix
1. Check schedule scraper runs in `nba_orchestration.scraper_execution_log`
2. If gcs_path is NULL, scraper isn't writing data - check logs
3. Manually trigger schedule refresh via HTTP

---

## Issue: Phase 2 Not Processing

### Symptoms
- Files in GCS but not in BigQuery
- Pub/Sub messages not being processed

### Common Causes
1. gcs_path is NULL in Pub/Sub message
2. No processor registered for file type
3. Processor failing consistently

### Manual Reprocess
Use curl with base64-encoded Pub/Sub message to trigger reprocessing.

---

## Issue: Early Game Workflows Not Running

### Symptoms
- Christmas/MLK Day games not being collected
- early_game_window workflows showing "No early games"

### Common Causes
1. Wrong attribute name in NBAGame model (use commence_time not game_date_et)
2. Schedule not showing early games correctly

---

## Issue: Service is Stale (Old Deployment)

### Check
```bash
gcloud run revisions list --service=SERVICE_NAME --region=us-west2 \
  --format="table(REVISION,DEPLOYED)" | head -3
```

### Fix
Redeploy the service using the appropriate deploy script.

---

## Issue: Orchestrator Shows Wrong Processor Names

### Symptoms
- Phase 2 shows 1/6 or 0/6 complete despite scrapers running successfully
- Logs show: `Missing: ['bdl_player_boxscores', ...]` (old names)
- Scrapers publish `p2_*` prefixed names but orchestrator expects unprefixed

### Cause
Processor names in `shared/config/orchestration_config.py` don't match the `processor_name` field in scraper Pub/Sub messages.

### Check
```bash
# See what names orchestrator expects
python -c "from shared.config.orchestration_config import get_orchestration_config; print(get_orchestration_config().phase_transitions.phase2_expected_processors)"

# See what scrapers publish (check workflows.yaml)
grep "processor_name:" config/workflows.yaml
```

### Fix
1. Update `shared/config/orchestration_config.py` with correct `p2_*` prefixed names
2. Run sync: `python bin/maintenance/sync_shared_utils.py --all`
3. Redeploy: `./bin/orchestrators/deploy_phase2_to_phase3.sh`

---

## Issue: Cloud Function Memory Exceeded

### Symptoms
- Container fails to start with health check failure
- Logs show: `Memory limit of X MiB exceeded with Y MiB used`
- Error code 137 (OOM killed)

### Cause
Cloud Function allocated insufficient memory. Orchestrators need ~250MB just for BigQuery/Firestore client initialization.

### Check
```bash
# Check all service memory allocations
./bin/monitoring/check_cloud_resources.sh

# Check with OOM warnings from logs
./bin/monitoring/check_cloud_resources.sh --check-logs
```

### Fix
1. Update memory in deploy script: `MEMORY="512MB"` (minimum for orchestrators)
2. Redeploy the function

### Prevention
- All orchestrators should use minimum 512MB
- Check memory allocation before deployment
- Add `check_cloud_resources.sh` to CI/CD pre-deployment checks

---

## Issue: BigQuery Insert "Not a Record" Error

### Symptoms
- Logs show: `BigQuery insert errors: [...'This field: metadata is not a record']`
- Phase execution logging fails silently

### Cause
Python dict passed to BigQuery JSON field without `json.dumps()` serialization.

### Fix
In the logging code, change:
```python
"metadata": metadata,  # WRONG
```
to:
```python
"metadata": json.dumps(metadata) if metadata else None,  # CORRECT
```

---

## Issue: Cloud Function Import Error

### Symptoms
- Container fails to start
- Logs show: `ModuleNotFoundError: No module named 'shared.utils.some_module'`

### Cause
Cloud Function's `shared/` directory is out of sync with main codebase.

### Check
```bash
# Compare files
diff <(ls shared/utils/*.py | sed 's|.*/||' | sort) \
     <(ls orchestration/cloud_functions/FUNCTION_NAME/shared/utils/*.py | sed 's|.*/||' | sort)
```

### Fix
1. Run full sync: `python bin/maintenance/sync_shared_utils.py --all`
2. If specific file missing, copy manually:
   ```bash
   cp shared/utils/missing_file.py orchestration/cloud_functions/FUNCTION_NAME/shared/utils/
   ```
3. Simplify `shared/utils/__init__.py` if it imports heavy dependencies not needed by the function

---

## Issue: Master Controller Firestore Lock Permission Denied

### Symptoms
- Workflow controller evaluates 0 workflows despite games being scheduled
- Logs show: `ERROR: Firestore error acquiring lock: 403 Missing or insufficient permissions`
- Scrapers stop running (except those with dedicated schedulers like bdl_live_boxscores)
- Schedule data becomes stale (games show "Scheduled" when they're "Final")

### Cause
The Cloud Run service account doesn't have Firestore/Datastore permissions. The master controller uses Firestore for distributed locking to prevent concurrent workflow evaluations.

### Check
```bash
# Check for lock errors in logs
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-scrapers" AND textPayload:"403 Missing or insufficient permissions"' --project=nba-props-platform --limit=10

# Check which service account is used
gcloud run services describe nba-scrapers --region=us-west2 --format='value(spec.template.spec.serviceAccountName)'

# Check if service account has datastore.user role
gcloud projects get-iam-policy nba-props-platform --filter="bindings.role:roles/datastore.user"
```

### Fix
Grant Firestore permissions to the service account:
```bash
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:bigdataball-puller@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
```

### Post-Fix Recovery
After fixing permissions:
1. Check for stuck locks:
   ```python
   from google.cloud import firestore
   db = firestore.Client(project='nba-props-platform')
   locks = list(db.collection('workflow_controller_locks').stream())
   print(f"Found {len(locks)} locks")
   # Delete if stuck: db.collection('workflow_controller_locks').document('LOCK_ID').delete()
   ```

2. Update schedule to get correct game statuses:
   ```bash
   curl -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
     -H "Content-Type: application/json" \
     -d '{"scraper": "nbac_schedule_api", "season": "2025"}'
   ```

3. Trigger workflow evaluation:
   ```bash
   curl -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/evaluate" \
     -H "Content-Type: application/json" -d '{}'
   ```

4. Backfill any missed analytics:
   ```bash
   ./bin/backfill/run_year_phase3.sh --start-date YYYY-MM-DD --end-date YYYY-MM-DD
   ```

### Prevention
- Add the `datastore.user` role to all service accounts that run workflow controllers
- Include IAM permission checks in deployment validation
- Add monitoring alert for "403 Missing or insufficient permissions" errors

### Incident History
- **2026-01-25**: Discovered master controller had been failing since Jan 23 due to missing Firestore permissions on `bigdataball-puller` service account. Fixed by adding `datastore.user` role.

---

## Issue: Auto-Retry System Not Working

### Symptoms
- Failed processors not being retried
- `failed_processor_queue` table has entries but they're not being processed
- auto-retry-processor Cloud Function not running

### Check
```bash
# Check if scheduler job is enabled
gcloud scheduler jobs describe auto-retry-processor-trigger --location=us-west2

# Check pending retries
bq query 'SELECT * FROM nba_orchestration.failed_processor_queue WHERE status = "pending"'

# Check auto-retry function logs
gcloud functions logs read auto-retry-processor --region us-west2 --limit 20
```

### Fix
1. Ensure scheduler job is enabled:
   ```bash
   gcloud scheduler jobs resume auto-retry-processor-trigger --location=us-west2
   ```

2. Manually trigger a retry run:
   ```bash
   gcloud scheduler jobs run auto-retry-processor-trigger --location=us-west2
   ```

3. If function is failing, check for permission issues or code errors in logs

---

## Quick Commands Reference

```bash
# Get auth token for manual API calls
TOKEN=$(gcloud auth print-identity-token)

# Check recent errors across all services
gcloud logging read 'severity>=ERROR' --limit=20 --freshness=1h

# Check specific service
gcloud run services logs read SERVICE_NAME --region=us-west2 --limit=50

# List all scheduler jobs
gcloud scheduler jobs list --location=us-west2

# Check Cloud Function logs specifically
gcloud functions logs read FUNCTION_NAME --region=us-west2 --limit=30

# Check memory allocations
./bin/monitoring/check_cloud_resources.sh

# Sync shared utilities to Cloud Functions
python bin/maintenance/sync_shared_utils.py --all
```
