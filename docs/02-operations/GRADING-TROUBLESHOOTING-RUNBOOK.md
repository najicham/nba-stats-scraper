# Grading System Troubleshooting Runbook

**Last Updated:** 2026-01-18 (Session 99)
**Audience:** Operations, On-Call Engineers

---

## Common Issues & Solutions

### Issue 1: Low Grading Coverage (<70%)

**Symptoms:**
- Grading coverage below 70% for dates 2+ days ago
- Boxscores exist but predictions not graded

**Investigation Steps:**

```bash
# Step 1: Check if boxscores actually exist
bq query --use_legacy_sql=false '
SELECT
  game_date,
  COUNT(*) as boxscore_count,
  COUNT(DISTINCT player_lookup) as unique_players
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = "2026-01-XX"  -- Replace with problem date
GROUP BY game_date
'

# Step 2: Check if predictions exist
bq query --use_legacy_sql=false '
SELECT
  COUNT(*) as prediction_count,
  COUNT(DISTINCT system_id) as systems
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = "2026-01-XX"  -- Replace with problem date
'

# Step 3: Check grading function logs
gcloud functions logs read phase5b-grading --region=us-west2 --limit=100 | grep "2026-01-XX"
```

**Common Causes:**

**A. Grading Never Ran**
- **Check:** Cloud Scheduler status for `nba-daily-grading`
- **Fix:**
  ```bash
  gcloud scheduler jobs describe nba-daily-grading --location=us-west2
  gcloud scheduler jobs run nba-daily-grading --location=us-west2
  ```

**B. Grading Failed (Auto-Heal Pending)**
- **Check:** Logs show "auto_heal_pending" or "No actuals"
- **Fix:** Wait for Phase 3 to process boxscores, or manually trigger:
  ```bash
  # Trigger Phase 3 manually
  TOKEN=$(gcloud auth print-identity-token --audiences="https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app")
  curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"start_date": "2026-01-XX", "end_date": "2026-01-XX", "processors": ["PlayerGameSummaryProcessor"], "backfill_mode": true}'

  # Then retry grading
  gcloud pubsub topics publish nba-grading-trigger --message='{"target_date":"2026-01-XX","trigger_source":"manual_retry"}'
  ```

**C. Predictions Don't Match Boxscores**
- **Check:** Player lookups match between predictions and boxscores
- **Query:**
  ```sql
  -- Find predictions without matching boxscores
  SELECT DISTINCT p.player_lookup
  FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
  LEFT JOIN `nba-props-platform.nba_analytics.player_game_summary` b
    ON p.player_lookup = b.player_lookup AND p.game_date = b.game_date
  WHERE p.game_date = "2026-01-XX"
    AND b.player_lookup IS NULL
  LIMIT 20
  ```
- **Fix:** May indicate player lookup normalization issue in Phase 2 or Phase 3

---

### Issue 2: Phase 3 503 Errors

**Symptoms:**
- Logs show: "Phase 3 analytics trigger failed: 503 - Service Unavailable"
- Auto-heal failing repeatedly

**Investigation Steps:**

```bash
# Step 1: Check Phase 3 service status
gcloud run services describe nba-phase3-analytics-processors --region=us-west2 \
  --format="yaml(status.conditions, spec.template.metadata.annotations)"

# Step 2: Check minScale setting
gcloud run services describe nba-phase3-analytics-processors --region=us-west2 \
  --format="yaml(spec.template.metadata.annotations)" | grep Scale
```

**Root Cause:** Cold start timeouts (if minScale=0)

**Fix (Session 99):**

```bash
# Ensure minScale=1 to keep instance warm
gcloud run services update nba-phase3-analytics-processors \
  --region=us-west2 \
  --min-instances=1 \
  --max-instances=10
```

**Verification:**
```bash
# Should respond in <10 seconds
TOKEN=$(gcloud auth print-identity-token --audiences="https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app")
time curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2026-01-15", "end_date": "2026-01-15", "processors": ["PlayerGameSummaryProcessor"], "backfill_mode": true}'
```

---

### Issue 3: Duplicate Grading Records

**Symptoms:**
- Same prediction graded multiple times
- Duplicate business keys in `prediction_accuracy` table

**Investigation Steps:**

```bash
# Check for duplicates
bq query --use_legacy_sql=false '
SELECT
  player_lookup,
  game_id,
  system_id,
  line_value,
  COUNT(*) as occurrence_count,
  ARRAY_AGG(graded_at ORDER BY graded_at LIMIT 5) as graded_timestamps
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY player_lookup, game_id, system_id, line_value
HAVING COUNT(*) > 1
LIMIT 20
'
```

**Root Cause (Fixed in Session 94-97):**
- Race condition in concurrent grading operations
- Distributed lock not applied

**Check if Fix is Deployed:**

```bash
# Verify grading function has distributed lock code
gcloud functions describe phase5b-grading --region=us-west2 | grep "updateTime"
# Should show deployment after 2026-01-18 04:28 UTC (Session 97)

# Check Firestore for lock collections
gcloud firestore collections list | grep lock
# Should show: grading_locks, daily_performance_locks, etc.
```

**If Duplicates Still Occur:**
1. Check Cloud Function logs for lock acquisition failures
2. Verify Firestore permissions for grading service account
3. Check if `use_lock=False` was accidentally set anywhere

**Cleanup Duplicates:**
```sql
-- See: docs/08-projects/current/ml-model-v8-deployment/SESSION-94-FIX-DESIGN.md
-- for deduplication procedure
```

---

### Issue 4: Grading Function Timeout

**Symptoms:**
- Logs show "Function execution took X ms, finished with status: timeout"
- Grading incomplete for large dates

**Investigation Steps:**

```bash
# Check function timeout setting
gcloud functions describe phase5b-grading --region=us-west2 | grep timeout
# Should be: timeout: 300s (5 minutes)

# Check execution time trends
gcloud logging read "resource.type=cloud_function AND resource.labels.function_name=phase5b-grading" \
  --format=json \
  --limit=50 | jq -r '.[] | select(.jsonPayload.executionId) | [.jsonPayload.executionId, .jsonPayload.timeMs] | @tsv' | sort -k2 -rn | head -10
```

**Common Causes:**

**A. Large Grading Volume**
- **Fix:** May need to increase timeout or process in batches

**B. Phase 3 Auto-Heal Taking Too Long**
- **Check:** Logs show Phase 3 call + 10s wait + retry
- **Fix:** Reduce wait time or make auto-heal async

**C. Lock Contention**
- **Check:** Logs show "waiting for lock" messages
- **Fix:** Check for stuck locks in Firestore

---

### Issue 5: No Grading for 48+ Hours

**Symptoms:**
- `last_graded_at` timestamp >48 hours old
- No recent grading activity

**Investigation Steps:**

```bash
# Step 1: Check Cloud Scheduler job
gcloud scheduler jobs describe nba-daily-grading --location=us-west2

# Step 2: Check recent scheduler executions
gcloud scheduler jobs describe nba-daily-grading --location=us-west2 | grep state

# Step 3: Check if Pub/Sub messages are being delivered
gcloud pubsub topics list | grep grading
gcloud pubsub subscriptions list | grep grading
```

**Common Causes:**

**A. Scheduler Paused**
```bash
# Resume scheduler
gcloud scheduler jobs resume nba-daily-grading --location=us-west2
```

**B. Grading Function Disabled**
```bash
# Check function state
gcloud functions describe phase5b-grading --region=us-west2 | grep state

# If not ACTIVE, may need redeployment
```

**C. Pub/Sub Subscription Issues**
```bash
# Check subscription health
gcloud pubsub subscriptions describe eventarc-us-west2-phase5b-grading-663180-sub-865
```

**Manual Trigger:**
```bash
# Trigger grading manually for specific date
gcloud pubsub topics publish nba-grading-trigger \
  --message='{"target_date":"2026-01-XX","trigger_source":"manual_recovery"}'
```

---

### Issue 6: High Phase 3 Costs (>$30/month)

**Symptoms:**
- Cloud Run costs for Phase 3 exceed $30/month
- Expected: ~$12-15/month with minScale=1

**Investigation Steps:**

```bash
# Check instance count and scaling events
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=nba-phase3-analytics-processors" \
  --limit=100 \
  --format=json | jq -r '.[] | select(.textPayload | contains("Instance")) | .textPayload'

# Check request volume
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=nba-phase3-analytics-processors AND httpRequest.requestMethod!=null" \
  --limit=100 \
  --format=json | jq -r '.[] | .timestamp' | wc -l
```

**Common Causes:**

**A. Unexpected Scaling (maxScale too high)**
```bash
# Reduce maxScale if necessary
gcloud run services update nba-phase3-analytics-processors \
  --region=us-west2 \
  --max-instances=5  # Down from 10
```

**B. High Request Volume**
- Check if backfill operations are running constantly
- Review Cloud Scheduler jobs triggering Phase 3

**C. Resource Sizing Too Large**
```bash
# Current: 2 CPU, 2Gi RAM
# If utilization is low, can reduce to 1 CPU, 1Gi:
gcloud run services update nba-phase3-analytics-processors \
  --region=us-west2 \
  --cpu=1 \
  --memory=1Gi
```

---

## Emergency Procedures

### Disable Auto-Heal Temporarily

If auto-heal is causing issues, disable temporarily:

```python
# In orchestration/cloud_functions/grading/main.py
# Change line ~344:
if validation['can_auto_heal'] and validation['missing_reason'] == 'no_actuals':
# To:
if False:  # Temporarily disable auto-heal

# Redeploy:
cd orchestration/cloud_functions/grading
./deploy.sh
```

### Force Grading Without Validation

```python
# In orchestration/cloud_functions/grading/main.py
# Call: run_prediction_accuracy_grading(target_date, skip_validation=True)

# Or via Pub/Sub:
gcloud pubsub topics publish nba-grading-trigger \
  --message='{"target_date":"2026-01-XX","trigger_source":"force_grading","skip_validation":true}'
```

### Clean Up Stuck Locks

```bash
# List all active locks
gcloud firestore documents list grading_locks

# Force delete stuck lock (use with caution!)
gcloud firestore documents delete grading_locks/grading_2026-01-XX
```

---

## Escalation Path

### Level 1: Automated Monitoring
- Slack alerts for low coverage
- Cloud Monitoring alerts for 503s
- Daily validation checks

### Level 2: Manual Investigation (this runbook)
- Check grading logs
- Verify Phase 3 health
- Manual grading triggers

### Level 3: Code Changes
- Adjust timeout settings
- Fix distributed lock issues
- Update grading logic

### Level 4: Architecture Review
- Redesign auto-heal mechanism
- Consider async grading pipeline
- Evaluate alternative boxscore sources

---

## Related Documentation

- **Monitoring Guide:** `docs/02-operations/GRADING-MONITORING-GUIDE.md`
- **Phase 3 Fix:** `docs/09-handoff/SESSION-99-PHASE3-FIX-COMPLETE.md`
- **Distributed Locking:** `docs/09-handoff/SESSION-97-MONITORING-COMPLETE.md`
- **Root Cause Analysis:** `docs/08-projects/current/ml-model-v8-deployment/SESSION-94-ROOT-CAUSE-ANALYSIS.md`

---

**Last Updated:** 2026-01-18 (Session 99)
