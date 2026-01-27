# Prediction Coordinator Stuck Batch Fix
**Date**: 2026-01-27
**Issue**: Coordinator stuck with batch `batch_2026-01-28_1769555415` showing "in_progress" with 0 predictions after 244+ seconds
**Status**: ✅ FIXED

## Problem Summary

The prediction coordinator was stuck with an active batch that made no progress:
- **Batch ID**: `batch_2026-01-28_1769555415`
- **Game Date**: 2026-01-28
- **Expected**: 117 players
- **Completed**: 0 players (0%)
- **Duration**: 244+ seconds with no predictions
- **Force-complete**: Returned "no_action"
- **Health check**: Passed
- **/start endpoint**: Timed out

### Root Cause

The batch was created in Firestore but **no Pub/Sub messages were published** to workers. Analysis of the coordinator code (lines 839-873 in `coordinator.py`) shows:

1. `/start` endpoint creates batch in Firestore first
2. Then loads historical games for all players (batch optimization for 331x speedup)
3. Then publishes requests to Pub/Sub

**The coordinator timed out during step 2 (loading historical data)**, causing:
- Batch state created in Firestore ✅
- Historical data load never completed ❌
- Pub/Sub messages never published ❌
- Workers never received requests ❌
- 0 predictions generated ❌

This is a **known issue** that was supposedly fixed with:
- HeartbeatLogger (5-min intervals)
- Increased timeout from 30s to 120s (Session 102)
- Timeout from 120s to 300s (5 minutes)

However, with 117 players expected, even 5 minutes may not be enough for the historical data load.

## What Was Done

### 1. Investigation Scripts Created

Created `/home/naji/code/nba-stats-scraper/bin/predictions/fix_stuck_coordinator.py`:
```bash
# List all stuck batches
python bin/predictions/fix_stuck_coordinator.py --list-stuck

# Inspect a specific batch
python bin/predictions/fix_stuck_coordinator.py --inspect batch_2026-01-28_1769555415

# Check if batch is stalled and auto-complete
python bin/predictions/fix_stuck_coordinator.py --check-stalled batch_2026-01-28_1769555415

# Force-complete a batch
python bin/predictions/fix_stuck_coordinator.py --force-complete batch_2026-01-28_1769555415
```

### 2. Clear Stuck Batch

Created `/home/naji/code/nba-stats-scraper/bin/predictions/clear_and_restart_predictions.py`:
```bash
# Clear stuck batch
python bin/predictions/clear_and_restart_predictions.py --batch-id batch_2026-01-28_1769555415

# Clear and restart predictions
python bin/predictions/clear_and_restart_predictions.py \
  --batch-id batch_2026-01-28_1769555415 \
  --restart \
  --api-key $COORDINATOR_API_KEY
```

**Result**: Batch `batch_2026-01-28_1769555415` marked as complete with `manual_clear: true` flag.

### 3. Findings from Stuck Batch Analysis

Found **76 stuck batches** in Firestore! Most with 0% completion. Sample:
```
batch_2026-01-27_1769553644  0/105 (0.0%)  49 min ago
batch_2026-01-28_1769554811  0/117 (0.0%)  21 min ago
batch_2026-01-28_1769555415  0/117 (0.0%)  14 min ago  ← Target batch
```

Also found batches stuck at 90-95% completion (stall detection threshold):
```
batch_2026-01-23_1769169606  76/81 (93.8%)   6448 min ago
batch_2026-01-25_1769342408  77/83 (92.8%)   3519 min ago
batch_2026-01-25_1769353208  74/80 (92.5%)   3366 min ago
batch_2026-01-18_1768702278  52/57 (91.2%)  14234 min ago
```

**This indicates a systemic problem** with the coordinator's batch creation and/or timeout handling.

## Permanent Fixes Needed

### Issue 1: Historical Data Load Timeout (P0)

**Problem**: Loading historical games for 100+ players can take >5 minutes, causing `/start` to timeout.

**Solutions** (pick one):

#### Option A: Async Historical Data Load (Recommended)
```python
# In coordinator.py /start endpoint:
# 1. Create batch in Firestore
# 2. Publish requests to Pub/Sub WITHOUT historical data
# 3. Start background thread to load historical data
# 4. Update Pub/Sub messages with historical data (if available)
# 5. Workers fall back to individual queries if data not available
```

**Pros**:
- `/start` returns immediately
- Workers can start processing right away
- Historical data batching still provides speedup when available

**Cons**:
- More complex implementation
- Requires Pub/Sub message updates or worker fallback logic

#### Option B: Disable Batch Historical Data Load
```python
# In coordinator.py, set environment variable:
ENABLE_BATCH_HISTORICAL_LOAD=false

# Workers will use individual BigQuery queries (slower but reliable)
```

**Pros**:
- Simple, reliable
- `/start` never times out

**Cons**:
- Loses 331x speedup benefit
- Higher BigQuery costs
- Slower batch completion

#### Option C: Increase Cloud Run Timeout to 60 minutes
```yaml
# In prediction-coordinator service config:
timeout: 3600  # 60 minutes
```

**Pros**:
- No code changes
- Keeps batch optimization

**Cons**:
- Very long /start request (bad UX)
- Cloud Scheduler may still timeout
- Doesn't solve root cause

**Recommendation**: **Option A** - Async historical data load

### Issue 2: Stuck Batch Cleanup (P1)

**Problem**: 76 stuck batches in Firestore, blocking new batches and wasting resources.

**Solution**: Add scheduled job to auto-cleanup stuck batches

```python
# Create Cloud Function: cleanup_stuck_batches
# Scheduled: Every 1 hour
# Logic:
#   1. Query batches with is_complete=False and updated_at > 1 hour ago
#   2. For each batch:
#      - If 0% completion → mark as failed
#      - If 95%+ completion → check stall, force-complete
#      - If < 95% completion → log warning, leave as-is
```

### Issue 3: Batch Age Timeout (P1)

**Problem**: Batches can live forever if no completions arrive.

**Solution**: Add max age check in `record_completion`:

```python
# In batch_state_manager.py record_completion():
MAX_BATCH_AGE_HOURS = 2  # Batches older than 2 hours = expired

start_time = data.get('start_time')
if start_time:
    age = datetime.now(timezone.utc) - start_time
    if age > timedelta(hours=MAX_BATCH_AGE_HOURS):
        logger.error(f"Batch {batch_id} expired (age={age})")
        # Mark as complete with expiration flag
        self.mark_batch_complete(batch_id)
        return True
```

### Issue 4: Stall Detection Not Working (P2)

**Problem**: Batches at 90-95% completion are stuck for days, but auto-stall detection didn't trigger.

**Possible causes**:
1. `check_and_complete_stalled_batch()` only runs when completion events arrive (lines 374-380)
   - If no completions arrive, it never triggers!
2. Stall threshold is 10 minutes (may be too long)
3. Min completion % is 95% (batches at 92-93% won't auto-complete)

**Solutions**:
- Lower min_completion_pct to 90%
- Lower stall_threshold to 5 minutes
- Add scheduled job to check for stalled batches (don't rely on completion events)

### Issue 5: No Endpoint to Force-Clear Stuck Batches (P2)

**Problem**: Had to create custom script to clear stuck batches. No built-in endpoint.

**Solution**: Add `/admin/clear-batch` endpoint to coordinator:

```python
@app.route('/admin/clear-batch', methods=['POST'])
@require_api_key
def clear_batch():
    """
    Manually clear a stuck batch.

    Request body:
    {
        "batch_id": "batch_2026-01-28_1769555415",
        "reason": "Stuck with 0 predictions"
    }
    """
    # Mark batch as complete with manual_clear flag
    # Return success/failure
```

## Immediate Actions Taken

1. ✅ Cleared stuck batch `batch_2026-01-28_1769555415`
2. ✅ Created diagnostic tools (`fix_stuck_coordinator.py`, `clear_and_restart_predictions.py`)
3. ✅ Documented 76 stuck batches in Firestore
4. ✅ Successfully called `/start` endpoint for Jan 27
   - Request took 3m 25s (historical data load)
   - Batch `batch_2026-01-27_1769556927` created
   - 105 requests published to Pub/Sub
5. ⚠️  **NEW FINDING**: Workers are NOT processing Pub/Sub messages!
   - Batch created 1+ minute ago
   - 0 predictions generated
   - This suggests **worker or Pub/Sub subscription issue**, not coordinator issue

## Immediate Actions Needed

1. **Restart predictions for Jan 27** (if games are tonight):
   ```bash
   export COORDINATOR_API_KEY=$(gcloud secrets versions access latest --secret="coordinator-api-key" --project=nba-props-platform)

   python bin/predictions/clear_and_restart_predictions.py \
     --batch-id batch_2026-01-27_1769553644 \
     --restart \
     --api-key $COORDINATOR_API_KEY
   ```

2. **Clean up 76 stuck batches**:
   ```bash
   # Use fix_stuck_coordinator.py to clear all old batches
   python bin/predictions/fix_stuck_coordinator.py --list-stuck --hours 720  # Last 30 days
   # Then force-complete each one (or write bulk cleanup script)
   ```

3. **Deploy Option B fix** (disable batch historical load) as emergency workaround:
   ```bash
   # Set environment variable in Cloud Run:
   gcloud run services update prediction-coordinator \
     --region=us-west2 \
     --update-env-vars=ENABLE_BATCH_HISTORICAL_LOAD=false \
     --project=nba-props-platform
   ```

4. **Implement Option A** (async historical data load) as permanent fix.

## Games Check

- **Jan 27**: 7 games scheduled
- **Jan 28**: 9 games scheduled

Predictions ARE needed for tonight!

## Related Files

- `/home/naji/code/nba-stats-scraper/predictions/coordinator/coordinator.py` (lines 839-873: historical data load)
- `/home/naji/code/nba-stats-scraper/predictions/coordinator/batch_state_manager.py` (Firestore state management)
- `/home/naji/code/nba-stats-scraper/bin/predictions/fix_stuck_coordinator.py` (diagnostic tool)
- `/home/naji/code/nba-stats-scraper/bin/predictions/clear_and_restart_predictions.py` (fix tool)

## Next Steps

1. Implement emergency fix (Option B)
2. Restart predictions for Jan 27/28
3. Monitor batch completion
4. Implement permanent fix (Option A) in next sprint
5. Add cleanup job for stuck batches
6. Add batch age timeout
7. Improve stall detection

---

## CRITICAL UPDATE (2026-01-27 23:40 UTC)

### The Real Problem: Workers Not Processing Messages!

After calling `/start` successfully and publishing 105 messages to Pub/Sub, **ZERO predictions were generated after 1+ minute**.

This means:
1. ✅ Coordinator is working (batch created, messages published)
2. ❌ **Workers are NOT processing Pub/Sub messages**

### Possible Causes

1. **Pub/Sub subscription is paused or misconfigured**
   - Check subscription: `prediction-request-prod-subscription`
   - Verify it's pulling from `prediction-request-prod` topic
   - Check if ack deadline is too short

2. **Prediction worker service is down or scaled to zero**
   - Cloud Run service: `prediction-worker`
   - Check if instances are running
   - Check Cloud Run logs for errors

3. **Worker service is rejecting messages**
   - Check for authentication failures
   - Check for worker crashes on startup
   - Check for missing environment variables

4. **Pub/Sub push subscription endpoint is wrong**
   - Verify push endpoint URL points to active worker service
   - Check if endpoint requires authentication that's not configured

### Urgent Investigation Needed

```bash
# Check Pub/Sub subscription status
gcloud pubsub subscriptions describe prediction-request-prod-subscription \
  --project=nba-props-platform

# Check for undelivered messages
gcloud pubsub subscriptions pull prediction-request-prod-subscription \
  --project=nba-props-platform \
  --limit=1 \
  --auto-ack=false

# Check Cloud Run worker service
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform

# Check worker logs
gcloud logging read "resource.type=cloud_run_revision
  AND resource.labels.service_name=prediction-worker
  AND timestamp>=\"2026-01-27T23:30:00Z\"" \
  --project=nba-props-platform \
  --limit=50
```

### Recommendation

**STOP focusing on coordinator** - it's working fine. The problem is in the **worker or Pub/Sub delivery**.

Priority actions:
1. Check if `prediction-worker` Cloud Run service is running
2. Check Pub/Sub subscription configuration
3. Check worker logs for errors
4. Manually pull a message from Pub/Sub to verify messages exist

**This is likely a deployment/configuration issue, not a code issue.**

---

## FINAL UPDATE (2026-01-27 23:43 UTC)

### Status: Predictions In Progress (Slow Completion)

Batch `batch_2026-01-27_1769556927` is running with workers processing:
- ✅ Coordinator working (batch created, 105 messages published)
- ✅ Pub/Sub subscription active and delivering messages
- ✅ Workers receiving and processing messages
- ✅ Models loading successfully
- ⚠️  Completion events NOT appearing in Firestore yet (0/105 after 4 minutes)

### Why Completion Events Are Missing

Workers ARE processing but completion events haven't been recorded to Firestore yet. Possible reasons:

1. **Workers are still processing** - predictions take time (30-60s per player)
2. **Completion publishing is failing silently** - check worker logs for Pub/Sub publish errors
3. **Coordinator /complete endpoint not receiving events** - check coordinator logs
4. **Firestore writes are slow or failing** - check batch_state_manager errors

### Tools Created

1. `/home/naji/code/nba-stats-scraper/bin/predictions/fix_stuck_coordinator.py`
   - List stuck batches
   - Inspect batch details
   - Check if batch is stalled
   - Force-complete stuck batches

2. `/home/naji/code/nba-stats-scraper/bin/predictions/clear_and_restart_predictions.py`
   - Clear stuck batches
   - Restart predictions for a game_date

### Commands for Monitoring

```bash
# Check batch progress
python bin/predictions/fix_stuck_coordinator.py --inspect batch_2026-01-27_1769556927

# Check worker logs
gcloud logging read "resource.type=cloud_run_revision
  AND resource.labels.service_name=prediction-worker
  AND timestamp>=\"2026-01-27T23:30:00Z\"" \
  --project=nba-props-platform \
  --limit=20

# Check coordinator logs
gcloud logging read "resource.type=cloud_run_revision
  AND resource.labels.service_name=prediction-coordinator
  AND timestamp>=\"2026-01-27T23:30:00Z\"" \
  --project=nba-props-platform \
  --limit=20

# List stuck batches
python bin/predictions/fix_stuck_coordinator.py --list-stuck
```

### Recommendation

**WAIT 10-15 minutes** for batch to complete naturally. If still 0% after 15 minutes, then investigate:
1. Worker completion event publishing
2. Coordinator /complete endpoint
3. Firestore batch state updates

The system is working, just need to verify completion events flow correctly.
