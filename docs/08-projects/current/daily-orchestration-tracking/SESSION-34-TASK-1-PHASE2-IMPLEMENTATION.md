# Task 1 Phase 2: Heartbeat Implementation Plan
**Started:** 2026-01-14 Evening
**Status:** Implementation Plan Ready
**Priority:** P0 - Critical for debugging stuck predictions

---

## 📍 HEARTBEAT IMPLEMENTATION STRATEGY

### What We Found

**Prediction Coordinator Structure:**
- **Location:** `/home/naji/code/nba-stats-scraper/predictions/coordinator/coordinator.py`
- **Main Flow:**
  1. `/start` endpoint → creates prediction requests
  2. `publish_prediction_requests()` → publishes to Pub/Sub (line 583-652)
  3. Workers process predictions (separate service)
  4. `/complete` endpoint → receives completion events
  5. Batch consolidation → merges staging tables to production

**Current Logging:**
- Logs every 50 players during publish (line 635-636)
- No time-based heartbeat
- No visibility into long-running operations

**Potential Hang Points:**
1. **Data loading:** `load_historical_games_batch()` (line 336) - loads 90 days of data for ~450 players
2. **Publish loop:** Publishing 450+ messages to Pub/Sub
3. **Batch consolidation:** Merging staging tables (not in this file)
4. **Worker processing:** External to coordinator (separate Cloud Run service)

---

## 💡 HEARTBEAT DESIGN

### Heartbeat Utility Class

Create a reusable heartbeat logger that can be used throughout the coordinator:

```python
# Add to top of coordinator.py

import threading
from datetime import datetime

class HeartbeatLogger:
    """
    Periodic heartbeat logger for long-running operations.

    Logs a heartbeat message every N seconds to prove the process is still alive.
    Helps debugging hung processes by showing where they got stuck.

    Usage:
        with HeartbeatLogger("Loading historical games", interval=300):  # 5 min
            # Long-running operation
            data = load_historical_games_batch(...)
    """
    def __init__(self, operation_name: str, interval_seconds: int = 300):
        """
        Args:
            operation_name: Name of the operation for logging
            interval_seconds: Heartbeat interval in seconds (default 5 minutes)
        """
        self.operation_name = operation_name
        self.interval = interval_seconds
        self.start_time = None
        self.timer = None
        self._active = False

    def __enter__(self):
        """Start heartbeat logging when entering context"""
        self.start_time = time.time()
        self._active = True
        logger.info(f"HEARTBEAT START: {self.operation_name}")
        print(f"💓 HEARTBEAT START: {self.operation_name}", flush=True)
        self._schedule_next_heartbeat()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop heartbeat logging when exiting context"""
        self._active = False
        if self.timer:
            self.timer.cancel()

        elapsed = time.time() - self.start_time
        elapsed_min = elapsed / 60

        if exc_type:
            logger.error(f"HEARTBEAT END (ERROR): {self.operation_name} failed after {elapsed_min:.1f} min")
            print(f"❌ HEARTBEAT END (ERROR): {self.operation_name} failed after {elapsed_min:.1f} min", flush=True)
        else:
            logger.info(f"HEARTBEAT END: {self.operation_name} completed in {elapsed_min:.1f} min")
            print(f"✅ HEARTBEAT END: {self.operation_name} completed in {elapsed_min:.1f} min", flush=True)

        return False  # Don't suppress exceptions

    def _schedule_next_heartbeat(self):
        """Schedule the next heartbeat log"""
        if not self._active:
            return

        # Log current heartbeat
        if self.start_time:
            elapsed = time.time() - self.start_time
            elapsed_min = elapsed / 60
            logger.info(f"HEARTBEAT: {self.operation_name} still running ({elapsed_min:.1f} min elapsed)")
            print(f"💓 HEARTBEAT: {self.operation_name} still running ({elapsed_min:.1f} min elapsed)", flush=True)

        # Schedule next heartbeat
        self.timer = threading.Timer(self.interval, self._schedule_next_heartbeat)
        self.timer.daemon = True  # Don't prevent process exit
        self.timer.start()
```

---

## 🎯 IMPLEMENTATION LOCATIONS

### Location 1: Historical Games Batch Loading (HIGH PRIORITY)

**Where:** Line 330-349 in `start_prediction_batch()`

**Before:**
```python
try:
    player_lookups = [r.get('player_lookup') for r in requests if r.get('player_lookup')]
    if player_lookups:
        print(f"🚀 Pre-loading historical games for {len(player_lookups)} players (batch optimization)", flush=True)
        logger.info(f"🚀 Pre-loading historical games for {len(player_lookups)} players (batch optimization)")

        from data_loaders import PredictionDataLoader

        data_loader = PredictionDataLoader(project_id=PROJECT_ID, dataset_prefix=dataset_prefix)
        batch_historical_games = data_loader.load_historical_games_batch(
            player_lookups=player_lookups,
            game_date=game_date,
            lookback_days=90,
            max_games=30
        )

        print(f"✅ Batch loaded historical games for {len(batch_historical_games)} players", flush=True)
```

**After (with heartbeat):**
```python
try:
    player_lookups = [r.get('player_lookup') for r in requests if r.get('player_lookup')]
    if player_lookups:
        # Use heartbeat logger for long-running data load
        with HeartbeatLogger(f"Loading historical games for {len(player_lookups)} players", interval=300):
            from data_loaders import PredictionDataLoader

            data_loader = PredictionDataLoader(project_id=PROJECT_ID, dataset_prefix=dataset_prefix)
            batch_historical_games = data_loader.load_historical_games_batch(
                player_lookups=player_lookups,
                game_date=game_date,
                lookback_days=90,
                max_games=30
            )

        print(f"✅ Batch loaded historical games for {len(batch_historical_games)} players", flush=True)
```

**Expected Logs:**
```
💓 HEARTBEAT START: Loading historical games for 450 players
💓 HEARTBEAT: Loading historical games for 450 players still running (5.0 min elapsed)
💓 HEARTBEAT: Loading historical games for 450 players still running (10.0 min elapsed)
✅ HEARTBEAT END: Loading historical games for 450 players completed in 12.3 min
```

---

### Location 2: Pub/Sub Publishing Loop (MEDIUM PRIORITY)

**Where:** Line 608-652 in `publish_prediction_requests()`

**Before:**
```python
for request_data in requests:
    # Add batch metadata
    message = {...}

    # Publish to Pub/Sub with retry logic
    if publish_with_retry(publisher, topic_path, message_bytes, player_lookup):
        published_count += 1

        # Log every 50 players
        if published_count % 50 == 0:
            logger.info(f"Published {published_count}/{len(requests)} requests")
```

**After (with heartbeat):**
```python
# Add heartbeat for long publish operations
with HeartbeatLogger(f"Publishing {len(requests)} prediction requests", interval=300):
    for request_data in requests:
        # Add batch metadata
        message = {...}

        # Publish to Pub/Sub with retry logic
        if publish_with_retry(publisher, topic_path, message_bytes, player_lookup):
            published_count += 1

            # Log every 50 players (more frequent than heartbeat for progress visibility)
            if published_count % 50 == 0:
                logger.info(f"Published {published_count}/{len(requests)} requests")
```

**Expected Logs:**
```
💓 HEARTBEAT START: Publishing 450 prediction requests
Published 50/450 requests
Published 100/450 requests
Published 150/450 requests
Published 200/450 requests
Published 250/450 requests
💓 HEARTBEAT: Publishing 450 prediction requests still running (5.0 min elapsed)
Published 300/450 requests
Published 350/450 requests
Published 400/450 requests
Published 450/450 requests
✅ HEARTBEAT END: Publishing 450 prediction requests completed in 8.5 min
```

---

### Location 3: Batch Consolidation (if needed)

**Note:** Consolidation happens in `/complete` endpoint when batch finishes. Need to check `publish_batch_summary_from_firestore()` function.

Let me search for that function first before implementing.

---

## ✅ IMPLEMENTATION STEPS

### Step 1: Add HeartbeatLogger Class (5 min)
- Add class definition at top of coordinator.py (after imports)
- Import threading module
- Test locally with simple usage

### Step 2: Add Heartbeat to Historical Games Loading (10 min)
- Wrap load_historical_games_batch call with HeartbeatLogger
- Keep existing print statements for compatibility
- Test with local run

### Step 3: Add Heartbeat to Publish Loop (10 min)
- Wrap entire publish loop with HeartbeatLogger
- Keep existing per-50 progress logs
- Test with local run

### Step 4: Deploy Updated Coordinator (10 min)
- Deploy to Cloud Run
- Verify new revision
- Check Cloud Logging for heartbeat messages

### Step 5: Verify Heartbeat in Production (15 min)
- Trigger test prediction batch
- Monitor Cloud Logging for heartbeat messages
- Verify 5-minute intervals
- Confirm heartbeat shows elapsed time

---

## 🧪 TESTING STRATEGY

### Local Testing
```bash
cd /home/naji/code/nba-stats-scraper/predictions/coordinator

# Test with Flask dev server
export FLASK_APP=coordinator.py
export GCP_PROJECT_ID=nba-props-platform
export COORDINATOR_API_KEY=test-key-local

# Run dev server
flask run --port=8080

# In another terminal, trigger test batch
curl -X POST http://localhost:8080/start \
  -H "X-API-Key: test-key-local" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "TODAY", "force": true}'
```

### Production Testing
```bash
# After deployment, trigger test batch
curl -X POST https://prediction-coordinator-756957797294.us-west2.run.app/start \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "TODAY", "force": true}'

# Monitor logs in real-time
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=prediction-coordinator \
  AND textPayload:HEARTBEAT" \
  --limit=50 \
  --format=json \
  --project=nba-props-platform
```

---

## 📊 EXPECTED OUTCOMES

### Before Heartbeat Implementation
- No visibility into long-running operations
- If coordinator hangs, no indication where
- Debugging requires guessing from last log entry

### After Heartbeat Implementation
- Heartbeat every 5 minutes shows operation still running
- Elapsed time helps identify slow operations
- Clear indication of where process is stuck
- Can distinguish "slow but working" from "hung"

### Example Stuck Scenario
```
💓 HEARTBEAT START: Loading historical games for 450 players
💓 HEARTBEAT: Loading historical games for 450 players still running (5.0 min elapsed)
💓 HEARTBEAT: Loading historical games for 450 players still running (10.0 min elapsed)
💓 HEARTBEAT: Loading historical games for 450 players still running (15.0 min elapsed)
💓 HEARTBEAT: Loading historical games for 450 players still running (20.0 min elapsed)
💓 HEARTBEAT: Loading historical games for 450 players still running (25.0 min elapsed)
💓 HEARTBEAT: Loading historical games for 450 players still running (30.0 min elapsed)
[Cloud Run timeout kills the process here - 30 minutes]
```

**Diagnosis:** Historical games loading is stuck. Takes >30 minutes, needs optimization or timeout.

---

## 🚀 NEXT STEPS

1. ✅ Implementation plan documented
2. ⬜ Add HeartbeatLogger class to coordinator.py
3. ⬜ Add heartbeat to historical games loading
4. ⬜ Add heartbeat to publish loop
5. ⬜ Deploy to Cloud Run
6. ⬜ Verify in production logs
7. ⬜ Update progress documentation
8. ⬜ Mark Phase 2 complete

**Estimated Time Remaining:** 45-60 minutes

Let's implement! 🚀
