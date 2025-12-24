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
```
