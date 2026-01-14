# Upcoming Tables TTL Cleanup Cloud Function

## Purpose

Automatically removes stale records from `upcoming_*` tables daily to prevent partial/stale data from blocking backfill fallback logic.

## Incident Background

**Jan 6, 2026**: Partial UPCG data (1/187 players) blocked fallback causing incomplete backfill that went undetected for 6 days.

## Tables Cleaned

- `nba_analytics.upcoming_player_game_context`
- `nba_analytics.upcoming_team_game_context`

## Configuration

- **TTL**: 7 days (configurable in `main.py`)
- **Schedule**: Daily at 4:00 AM ET
- **Notification Threshold**: > 10,000 records deleted

## Deployment

### 1. Deploy Cloud Function

```bash
gcloud functions deploy upcoming-tables-cleanup \
  --gen2 \
  --runtime=python311 \
  --region=us-east1 \
  --source=orchestration/cloud_functions/upcoming_tables_cleanup \
  --entry-point=cleanup_upcoming_tables \
  --trigger-topic=upcoming-tables-cleanup-trigger \
  --timeout=540s \
  --memory=512MB \
  --service-account=nba-orchestration@nba-props-platform.iam.gserviceaccount.com \
  --set-env-vars=GCP_PROJECT_ID=nba-props-platform
```

### 2. Create Cloud Scheduler Job

```bash
gcloud scheduler jobs create pubsub upcoming-tables-cleanup-schedule \
  --location=us-east1 \
  --schedule="0 4 * * *" \
  --time-zone="America/New_York" \
  --topic=upcoming-tables-cleanup-trigger \
  --message-body='{"trigger":"scheduled"}' \
  --description="Daily TTL cleanup for upcoming_* tables (4 AM ET)"
```

### 3. Create Pub/Sub Topic (if not exists)

```bash
gcloud pubsub topics create upcoming-tables-cleanup-trigger \
  --project=nba-props-platform
```

### 4. Grant Permissions

```bash
# Allow Cloud Scheduler to publish to topic
gcloud pubsub topics add-iam-policy-binding upcoming-tables-cleanup-trigger \
  --member=serviceAccount:service-PROJECT_NUMBER@gcp-sa-cloudscheduler.iam.gserviceaccount.com \
  --role=roles/pubsub.publisher

# Allow Cloud Function to access BigQuery
gcloud projects add-iam-policy-binding nba-props-platform \
  --member=serviceAccount:nba-orchestration@nba-props-platform.iam.gserviceaccount.com \
  --role=roles/bigquery.dataEditor
```

## Testing

### Local Testing

```bash
cd orchestration/cloud_functions/upcoming_tables_cleanup
python main.py
```

### Manual Trigger (Cloud)

```bash
gcloud scheduler jobs run upcoming-tables-cleanup-schedule --location=us-east1
```

### Dry Run SQL (BigQuery Console)

```sql
-- Check what would be deleted
SELECT
  'upcoming_player_game_context' as table_name,
  COUNT(*) as records_to_delete,
  MIN(game_date) as oldest_date,
  MAX(game_date) as newest_date
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date < CURRENT_DATE() - INTERVAL 7 DAY

UNION ALL

SELECT
  'upcoming_team_game_context' as table_name,
  COUNT(*) as records_to_delete,
  MIN(game_date) as oldest_date,
  MAX(game_date) as newest_date
FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
WHERE game_date < CURRENT_DATE() - INTERVAL 7 DAY;
```

## Monitoring

### View Cleanup History

```sql
SELECT
  cleanup_time,
  total_records_deleted,
  tables_cleaned,
  errors
FROM `nba-props-platform.nba_orchestration.cleanup_operations`
WHERE cleanup_type = 'upcoming_tables_ttl'
ORDER BY cleanup_time DESC
LIMIT 30;
```

### Check for Failed Cleanups

```sql
SELECT
  cleanup_time,
  errors,
  total_records_deleted
FROM `nba-props-platform.nba_orchestration.cleanup_operations`
WHERE cleanup_type = 'upcoming_tables_ttl'
  AND (errors IS NOT NULL OR total_records_deleted = 0)
ORDER BY cleanup_time DESC;
```

### View Cloud Function Logs

```bash
gcloud functions logs read upcoming-tables-cleanup \
  --region=us-east1 \
  --limit=50
```

## Alerts

The function automatically sends notifications for:

1. **Unusual Cleanup**: > 10,000 records deleted (potential backlog)
2. **Cleanup Failure**: Any exception during execution

Notifications are sent via Slack (configured in `shared.utils.notification_system`)

## Troubleshooting

### No Records Being Deleted

**Cause**: No stale records exist (this is normal!)

**Action**: None required

### Excessive Deletions (> 10,000 records)

**Cause**: Backlog of historical data that wasn't cleaned up

**Action**:
1. Review notification details
2. Verify this is expected (e.g., first run after deployment)
3. If unexpected, investigate why upcoming tables have historical data

### Cleanup Fails with Permission Error

**Cause**: Service account lacks BigQuery dataEditor role

**Action**:
```bash
gcloud projects add-iam-policy-binding nba-props-platform \
  --member=serviceAccount:nba-orchestration@nba-props-platform.iam.gserviceaccount.com \
  --role=roles/bigquery.dataEditor
```

### Cleanup Runs But Logs Missing

**Cause**: BigQuery audit table doesn't exist or insert fails

**Action**: Ensure `nba_orchestration.cleanup_operations` table exists with schema:
- `cleanup_type` STRING
- `cleanup_time` TIMESTAMP
- `ttl_days` INTEGER
- `tables_cleaned` STRING (JSON)
- `total_records_deleted` INTEGER
- `errors` STRING (JSON, nullable)

## Configuration Changes

### Adjust TTL Days

Edit `main.py`:
```python
TTL_DAYS = 14  # Change from 7 to 14 days
```

Redeploy:
```bash
gcloud functions deploy upcoming-tables-cleanup --source=orchestration/cloud_functions/upcoming_tables_cleanup
```

### Change Schedule

```bash
# Change to daily at 2 AM
gcloud scheduler jobs update pubsub upcoming-tables-cleanup-schedule \
  --location=us-east1 \
  --schedule="0 2 * * *"
```

## Related Documentation

- Incident Report: `docs/08-projects/current/historical-backfill-audit/ROOT-CAUSE-ANALYSIS-2026-01-12.md`
- Improvement Plan: `docs/08-projects/current/historical-backfill-audit/BACKFILL-IMPROVEMENTS-PLAN-2026-01-12.md`
- Manual Cleanup Script: `scripts/cleanup_stale_upcoming_tables.py`

## Maintenance

- **Review logs monthly** to ensure normal operation
- **Keep audit logs for 90 days** minimum
- **Update TTL if data access patterns change**

---

**Author**: Claude (Session 30)
**Date**: 2026-01-13
**Version**: 1.0
