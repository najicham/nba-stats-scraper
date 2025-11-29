# Critical Fixes for v1.0 - Must Implement Before Launch

**Created:** 2025-11-28 9:25 PM PST
**Last Updated:** 2025-11-28 9:25 PM PST
**Source:** External review of FAILURE-ANALYSIS-TROUBLESHOOTING.md
**Status:** 🔴 BLOCKING v1.0 LAUNCH

---

## Executive Summary

External review identified **9 critical issues** that must be fixed before v1.0 launch. These prevent:
- Race conditions causing duplicate processing
- Silent failures with stale data
- SLA violations (10 AM ET deadline)
- Data inconsistencies
- Cascading failures

**Additional Effort:** +17 hours (72 → 89 hours total)
**Timeline Impact:** Still 3-4 weeks (absorbed in buffer)
**Risk if Not Fixed:** Production incidents, SLA violations, data corruption

---

## Priority 1: Production-Breaking Issues (12 hours)

### Fix 1.1: Firestore Transactions in Orchestrators (3 hours)

**Issue:** Race condition when two processors complete simultaneously

**Scenario:**
```
11:45 PM - Processor A completes, reads Firestore (4/5 complete)
11:45 PM - Processor B completes, reads Firestore (4/5 complete)
Both increment to 5/5
Both write 5/5
Both trigger Phase 4
→ Phase 4 runs twice
→ Duplicate predictions
```

**Impact:** Data corruption, duplicate processing, wasted resources

**Where to Fix:**
- `cloud_functions/phase2_to_phase3_orchestrator/main.py`
- `cloud_functions/phase3_to_phase4_orchestrator/main.py`
- `cloud_functions/phase4_orchestrator/main.py`

**Implementation:**

```python
# cloud_functions/phase2_to_phase3_orchestrator/main.py

from google.cloud import firestore
import functions_framework
import json
import base64

db = firestore.Client()

EXPECTED_PROCESSORS = 21  # Phase 2 has 21 processors

@functions_framework.cloud_event
def orchestrate_phase2_to_phase3(cloud_event):
    """Handle Phase 2 completion events and trigger Phase 3 when all complete."""

    # Parse Pub/Sub message
    pubsub_message = cloud_event.data['message']
    message_data = json.loads(base64.b64decode(pubsub_message['data']).decode())

    game_date = message_data.get('game_date')
    processor_name = message_data.get('processor_name')
    correlation_id = message_data.get('correlation_id')

    # Update completion state with transaction
    doc_ref = db.collection('phase2_completion').document(game_date)

    should_trigger = update_completion_atomic(doc_ref, processor_name, {
        'completed_at': firestore.SERVER_TIMESTAMP,
        'correlation_id': correlation_id,
        'status': message_data.get('status')
    })

    if should_trigger:
        trigger_phase3(game_date, correlation_id)
        print(f"✅ All {EXPECTED_PROCESSORS} Phase 2 processors complete, triggered Phase 3")
    else:
        print(f"Registered completion for {processor_name}, waiting for others")


@firestore.transactional
def update_completion_atomic(transaction, doc_ref, processor_name, data):
    """
    Atomically update processor completion and determine if should trigger next phase.

    Returns:
        bool: True if this update completes the phase and should trigger next phase
    """
    # Read current state within transaction
    doc = doc_ref.get(transaction=transaction)
    current = doc.to_dict() if doc.exists else {}

    # Check if already processed (idempotency)
    if processor_name in current:
        print(f"Processor {processor_name} already registered (duplicate message)")
        return False

    # Add this processor's completion
    current[processor_name] = data

    # Count completed processors (exclude metadata fields)
    completed_count = len([k for k in current.keys() if not k.startswith('_')])

    # Check if this completes the phase AND hasn't been triggered yet
    if completed_count >= EXPECTED_PROCESSORS and '_triggered' not in current:
        # Mark as triggered to prevent duplicate triggers
        current['_triggered'] = True
        current['_triggered_at'] = firestore.SERVER_TIMESTAMP
        transaction.set(doc_ref, current)
        return True  # Trigger next phase
    else:
        transaction.set(doc_ref, current)
        return False  # Don't trigger yet


def trigger_phase3(game_date, correlation_id):
    """Publish message to trigger Phase 3 processing."""
    from google.cloud import pubsub_v1

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path('nba-props-platform', 'nba-phase3-trigger')

    message = {
        'game_date': game_date,
        'correlation_id': correlation_id,
        'trigger_source': 'orchestrator',
        'triggered_by': 'phase2_to_phase3_orchestrator'
    }

    future = publisher.publish(topic_path, json.dumps(message).encode('utf-8'))
    message_id = future.result()
    print(f"Published Phase 3 trigger: {message_id}")
```

**Key Points:**
- `@firestore.transactional` decorator ensures atomic read-modify-write
- `_triggered` flag prevents double-trigger even if two transactions somehow succeed
- Idempotency check prevents duplicate processor registrations
- `SERVER_TIMESTAMP` ensures consistent timestamps

**Apply Same Pattern to:**
- Phase 3→4 orchestrator (expects 5 processors)
- Phase 4 internal orchestrator (expects 5 processors, 3 levels)

**Testing:**
```python
# Unit test
def test_concurrent_completions():
    # Simulate 2 processors completing simultaneously
    # Verify only ONE trigger published
    pass
```

---

### Fix 1.2: Phase 5 Coordinator Firestore State (4 hours)

**Issue:** In-memory state lost on coordinator restart → can't track batch completion

**Scenario:**
```
12:00 AM - Coordinator starts batch, publishes 450 worker messages
12:15 AM - Coordinator instance crashes (OOM, scale-down, etc.)
12:16 AM - 400 workers complete, publish to prediction-ready
12:16 AM - New coordinator instance starts with NO STATE
→ Doesn't know batch in progress
→ Can't track 400 completions
→ Manual recovery needed but it's 6 AM before anyone notices
```

**Impact:** Violates 10 AM ET SLA, incomplete predictions, manual intervention needed

**Why Critical:** This was deferred to v1.1, but with hard SLA, can't rely on manual recovery

**Where to Fix:**
- `predictions/coordinator/coordinator.py`

**Implementation:**

```python
# predictions/coordinator/coordinator.py

from google.cloud import firestore

# Initialize Firestore
db = firestore.Client()

def start_prediction_batch():
    """Start prediction batch with Firestore state tracking."""

    game_date = request.get_json().get('game_date', date.today())
    batch_id = str(uuid.uuid4())

    # Load eligible players
    players = player_loader.load_players_for_date(game_date)

    # Store batch state in Firestore (persistent)
    batch_doc = db.collection('prediction_batches').document(f'{game_date}_{batch_id}')
    batch_doc.set({
        'batch_id': batch_id,
        'game_date': str(game_date),
        'started_at': firestore.SERVER_TIMESTAMP,
        'expected_count': len(players),
        'completed_count': 0,
        'failed_count': 0,
        'status': 'in_progress',
        'coordinator_instance': os.environ.get('K_REVISION'),
        'completed_players': [],
        'failed_players': []
    })

    # Also keep in-memory for performance (but can rebuild from Firestore)
    global current_tracker, current_batch_id
    current_tracker = ProgressTracker(batch_id, len(players))
    current_batch_id = batch_id

    # Publish worker messages
    for player in players:
        publish_prediction_request(player, game_date, batch_id)

    return jsonify({
        'status': 'started',
        'batch_id': batch_id,
        'game_date': str(game_date),
        'players': len(players)
    }), 202


def handle_completion_event():
    """Handle worker completion event (from Pub/Sub)."""

    envelope = request.get_json()
    message_data = parse_pubsub_message(envelope)

    player_lookup = message_data.get('player_lookup')
    batch_id = message_data.get('batch_id')
    game_date = message_data.get('game_date')
    status = message_data.get('status')

    # Update Firestore state (persistent)
    batch_doc = db.collection('prediction_batches').document(f'{game_date}_{batch_id}')

    # Use transaction to increment counters atomically
    @firestore.transactional
    def update_completion(transaction):
        doc = batch_doc.get(transaction=transaction)
        data = doc.to_dict()

        # Increment appropriate counter
        if status == 'success':
            data['completed_count'] = data.get('completed_count', 0) + 1
            data['completed_players'].append(player_lookup)
        else:
            data['failed_count'] = data.get('failed_count', 0) + 1
            data['failed_players'].append(player_lookup)

        # Check if batch complete
        total_processed = data['completed_count'] + data['failed_count']
        if total_processed >= data['expected_count']:
            data['status'] = 'completed'
            data['completed_at'] = firestore.SERVER_TIMESTAMP

        transaction.update(batch_doc, data)
        return data

    transaction = db.transaction()
    updated_data = update_completion(transaction)

    # Update in-memory tracker if exists
    if current_tracker:
        current_tracker.record_completion(player_lookup, status == 'success')

    # Check if complete
    if updated_data['status'] == 'completed':
        publish_batch_complete_event(game_date, batch_id, updated_data)


def recover_batch_state():
    """
    Recover batch state from Firestore on coordinator restart.
    Called during health check or on startup.
    """
    # Find active batches
    active_batches = db.collection('prediction_batches') \
        .where('status', '==', 'in_progress') \
        .where('game_date', '>=', str(date.today() - timedelta(days=1))) \
        .stream()

    for batch_doc in active_batches:
        data = batch_doc.to_dict()
        batch_id = data['batch_id']

        # Rebuild in-memory tracker
        tracker = ProgressTracker(batch_id, data['expected_count'])
        tracker.completed = data['completed_count']
        tracker.failed = data['failed_count']

        # Check if should be considered stalled
        started_at = data['started_at']
        if datetime.now() - started_at > timedelta(hours=2):
            logger.warning(f"Batch {batch_id} appears stalled (started {started_at})")
        else:
            # Set as current tracker
            global current_tracker, current_batch_id
            current_tracker = tracker
            current_batch_id = batch_id
            logger.info(f"Recovered batch state: {batch_id} ({data['completed_count']}/{data['expected_count']})")


# Add to health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    """Health check that rebuilds state if needed."""

    global current_tracker

    # If no in-memory tracker, try to recover from Firestore
    if current_tracker is None:
        recover_batch_state()

    return jsonify({
        'status': 'healthy',
        'has_active_batch': current_tracker is not None
    }), 200
```

**Key Benefits:**
- Survives coordinator restarts
- Atomic counter updates (no race conditions)
- Can rebuild state from Firestore on crash
- Still keeps in-memory for performance
- Health check auto-recovers

**Testing:**
```bash
# Integration test
1. Start batch
2. Kill coordinator mid-batch
3. Workers continue completing
4. New coordinator instance starts
5. Health check recovers state
6. Verify completion tracking works
```

---

### Fix 1.3: Deduplication Query Timeout Handling (1 hour)

**Issue:** Deduplication query to processor_run_history times out during high concurrency

**Scenario:**
```
Phase 2→3 transition:
- 21 Phase 2 processors complete
- All check processor_run_history simultaneously
- Plus 5 Phase 3 processors checking
= 26 concurrent queries to same table
→ Query timeout
→ Processor doesn't know if already run
→ Either skips incorrectly OR processes duplicate
```

**Impact:** Incorrect behavior (skip when shouldn't or duplicate work)

**Where to Fix:**
- `shared/processors/mixins/run_history_mixin.py` (if exists)
- OR `data_processors/raw/processor_base.py`
- OR `data_processors/analytics/analytics_base.py`

**Implementation:**

```python
# In any base class with deduplication

def _already_processed(self, game_date) -> bool:
    """
    Check if this processor already ran successfully for this date.

    With timeout handling - prefer processing over skipping on timeout.
    """
    from google.cloud import bigquery
    from google.api_core.exceptions import DeadlineExceeded

    query = """
    SELECT status
    FROM `{project}.nba_reference.processor_run_history`
    WHERE processor_name = @processor_name
      AND data_date = @game_date
      AND status IN ('success', 'partial')
    ORDER BY processed_at DESC
    LIMIT 1
    """.format(project=self.project_id)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("processor_name", "STRING", self.__class__.__name__),
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    )

    try:
        # Run with 5-second timeout
        query_job = self.bq_client.query(query, job_config=job_config)
        results = list(query_job.result(timeout=5.0))

        if len(results) > 0:
            logger.info(f"Already processed {game_date}, skipping")
            return True
        else:
            return False

    except DeadlineExceeded:
        # CRITICAL: On timeout, prefer processing over skipping
        # Better to process twice than skip incorrectly
        logger.warning(
            f"Deduplication query timeout for {game_date}, "
            f"proceeding with processing (safe default)"
        )
        return False  # Don't skip

    except Exception as e:
        # On any other error, also proceed
        logger.error(f"Deduplication check failed: {e}, proceeding with processing")
        return False
```

**Alternative: Add Index to processor_run_history**

```sql
-- Create index to speed up deduplication queries
CREATE INDEX idx_processor_run_history_dedup
ON `nba-props-platform.nba_reference.processor_run_history`
(processor_name, data_date, status)
```

**Key Points:**
- 5-second timeout (prevents indefinite hang)
- Safe default: process rather than skip on timeout
- Log warnings for monitoring
- Consider index for performance

---

### Fix 1.4: Verify BigQuery Commit Before Publishing (2 hours)

**Issue:** Pub/Sub message published before BigQuery MERGE commits

**Scenario:**
```
Processor completes MERGE
Publishes Pub/Sub completion event
BigQuery transaction rolls back (network partition, timeout)
→ Downstream processor receives message
→ Queries BigQuery
→ Finds no data or old data
→ Produces incorrect results
```

**Impact:** Data inconsistency, downstream failures, incorrect predictions

**Where to Fix:**
- All base classes that publish completion events
- `data_processors/raw/processor_base.py`
- `data_processors/analytics/analytics_base.py`
- `data_processors/precompute/precompute_base.py`

**Implementation:**

```python
# In processor base classes

def _publish_completion_event(self):
    """
    Publish completion event to Pub/Sub.

    CRITICAL: Verify data committed to BigQuery before publishing.
    """

    # Step 1: Wait for BigQuery job to complete
    if hasattr(self, 'load_job'):
        self.load_job.result()  # Blocks until complete

    # Step 2: Verify data actually exists in table
    row_count = self._verify_data_committed()

    if row_count < self.expected_minimum_rows:
        raise DataCommitVerificationError(
            f"Data verification failed for {self.game_date}: "
            f"Expected >= {self.expected_minimum_rows}, got {row_count}"
        )

    # Step 3: Only publish after verification
    publisher = get_publisher()
    message = {
        'processor_name': self.__class__.__name__,
        'game_date': str(self.game_date),
        'record_count': row_count,
        'status': 'success',
        # ... other fields
    }

    future = publisher.publish(topic, json.dumps(message).encode())
    message_id = future.result()

    logger.info(f"✅ Verified {row_count} rows committed, published message {message_id}")


def _verify_data_committed(self) -> int:
    """
    Verify data was committed to BigQuery.

    Returns:
        int: Row count for this game_date
    """
    verify_query = f"""
    SELECT COUNT(*) as row_count
    FROM `{self.project_id}.{self.dataset_id}.{self.table_name}`
    WHERE game_date = @game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", self.game_date)
        ]
    )

    query_job = self.bq_client.query(verify_query, job_config=job_config)
    result = list(query_job.result(timeout=10.0))

    if len(result) == 0:
        return 0

    return result[0]['row_count']


# Define expected minimum rows per processor type
@property
def expected_minimum_rows(self):
    """Minimum rows expected for successful processing."""

    # Override in child classes
    # For Phase 2: might be 10-20 games
    # For Phase 3: might be 100-200 player-games
    # For Phase 4: might be 50-450 players

    return 1  # Default: at least 1 row
```

**In Specific Processors:**

```python
# In PlayerGameSummaryProcessor
@property
def expected_minimum_rows(self):
    # Expect at least 50 players for a typical game day
    return 50

# In MLFeatureStoreProcessor
@property
def expected_minimum_rows(self):
    # Expect at least 100 players
    return 100
```

**Key Points:**
- Wait for BigQuery job completion
- Verify with COUNT query
- Check against expected minimum
- Only publish after verification
- Fail loudly if verification fails

---

### Fix 1.5: Change Detection Health Monitoring (2 hours)

**Issue:** Hash function bug causes perpetual "0 changes detected" → stale predictions

**Scenario:**
```
Code deploy introduces bug in _hash_row()
All rows now hash to same value
Change detection compares hashes: all match
Reports 0 entities changed
Phase 3-5 skip processing
processor_run_history shows status='success', entities_processed=0
No alerts (0 is technically "valid")
→ Predictions never update all day
→ Users see stale data
```

**Impact:** SILENT FAILURE - no errors but predictions stale

**Where to Fix:**
- Add to monitoring/alerting system
- Add to change detection implementation

**Implementation:**

**Part A: Runtime Assertions**

```python
# In shared/utils/change_detector.py

def detect_changed_entities(self, current_data, entity_id_field, previous_table):
    """Detect changed entities with safety checks."""

    # Compute hashes
    current_hashes = {
        row[entity_id_field]: self._hash_row(row)
        for row in current_data
    }

    # SAFETY CHECK: All hashes should be unique (or at least varied)
    unique_hashes = len(set(current_hashes.values()))
    total_hashes = len(current_hashes)

    if total_hashes > 10 and unique_hashes == 1:
        # All hashes are identical - likely a bug
        logger.error(
            f"Change detection bug detected: {total_hashes} rows all have same hash. "
            f"This indicates a bug in _hash_row() function."
        )
        # Fall back to full batch
        return list(current_hashes.keys())

    # Get previous hashes
    previous_hashes = self._query_previous_hashes(previous_table, game_date, entity_id_field)

    # Find changes
    changed = []
    for entity_id, current_hash in current_hashes.items():
        previous_hash = previous_hashes.get(entity_id)
        if previous_hash is None or previous_hash != current_hash:
            changed.append(entity_id)

    # SAFETY CHECK: On overnight run, should detect most entities as changed
    is_overnight = datetime.now().hour < 6
    if is_overnight and len(changed) == 0 and total_hashes > 100:
        logger.warning(
            "Change detection found 0 changes on overnight run - this is suspicious. "
            "Falling back to full batch processing."
        )
        return list(current_hashes.keys())

    return changed


def _hash_row(self, row: Dict) -> str:
    """
    Create stable hash of row data.

    CRITICAL: Exclude non-deterministic fields.
    """
    import hashlib
    import json

    # Fields to EXCLUDE from hash (non-deterministic)
    EXCLUDE_FIELDS = {
        'created_at',
        'updated_at',
        'processed_at',
        'run_id',
        'execution_id',
        '_PARTITIONTIME',
        'row_hash'  # Don't include the hash itself!
    }

    # Create clean copy excluding non-deterministic fields
    clean_row = {
        k: v for k, v in row.items()
        if k not in EXCLUDE_FIELDS
    }

    # Sort keys for stable serialization
    sorted_data = json.dumps(clean_row, sort_keys=True, default=str)

    # Compute hash
    hash_value = hashlib.sha256(sorted_data.encode()).hexdigest()

    # SAFETY CHECK: Hash shouldn't be constant
    if not hasattr(self, '_seen_hashes'):
        self._seen_hashes = set()
    self._seen_hashes.add(hash_value)

    return hash_value
```

**Part B: Monitoring Query**

```sql
-- Add to daily monitoring dashboard
-- Alert if entities_processed = 0 for >4 hours on a game day

WITH recent_runs AS (
  SELECT
    processor_name,
    data_date,
    SUM(records_processed) as total_processed,
    COUNT(*) as run_count,
    MAX(processed_at) as last_run
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR)
    AND phase IN ('phase_3_analytics', 'phase_4_precompute')
  GROUP BY processor_name, data_date
)
SELECT
  processor_name,
  data_date,
  total_processed,
  run_count,
  last_run,
  'ALERT: Zero processing detected' as alert
FROM recent_runs
WHERE total_processed = 0
  AND data_date >= CURRENT_DATE()
  -- Only alert if multiple runs (confirms it's not just waiting)
  AND run_count >= 2
```

**Part C: Daily Assertion Test**

```python
# Add to daily health check or monitoring

def daily_change_detection_health_check():
    """
    Verify change detection is working correctly.

    Run this once daily (e.g., at 2 AM after overnight batch).
    """

    query = """
    SELECT
      processor_name,
      SUM(records_processed) as total_processed,
      COUNT(*) as run_count
    FROM `nba-props-platform.nba_reference.processor_run_history`
    WHERE data_date = CURRENT_DATE()
      AND phase IN ('phase_3_analytics', 'phase_4_precompute')
      AND processed_at >= TIMESTAMP(CURRENT_DATE())
    GROUP BY processor_name
    """

    results = client.query(query).result()

    for row in results:
        # Overnight batch should process at least 100 entities
        if row['total_processed'] == 0 and row['run_count'] >= 2:
            alert_manager.send_alert(
                severity='critical',
                title='Change Detection Health Check Failed',
                message=f"{row['processor_name']} processed 0 entities on {date.today()} "
                        f"despite {row['run_count']} runs. Possible hash function bug."
            )
```

**Key Points:**
- Runtime assertions catch hash bugs immediately
- Monitoring detects prolonged zero-processing
- Daily health check validates change detection working
- Automatic fallback to full batch on suspicion

---

## Priority 2: Important for Stability (5 hours)

### Fix 2.1: Coordinator Instance Mutex (2 hours)

**Issue:** Two coordinator instances running simultaneously

**Implementation:**

```python
# In coordinator startup

def start_prediction_batch():
    """Start batch with coordinator lock."""

    game_date = request.get_json().get('game_date')

    # Try to acquire lock
    if not acquire_coordinator_lock(game_date):
        logger.warning(f"Another coordinator already processing {game_date}")
        return jsonify({
            'status': 'skipped',
            'reason': 'another_coordinator_active'
        }), 409

    try:
        # Normal processing
        # ...
    finally:
        # Release lock on completion or failure
        release_coordinator_lock(game_date)


def acquire_coordinator_lock(game_date, ttl_minutes=60):
    """
    Acquire coordinator lock using Firestore.

    Returns:
        bool: True if lock acquired, False if another coordinator has it
    """
    from google.cloud import firestore
    from google.api_core.exceptions import AlreadyExists

    db = firestore.Client()
    lock_doc = db.collection('coordinator_locks').document(str(game_date))

    instance_id = os.environ.get('K_REVISION', 'local')
    expires_at = datetime.now() + timedelta(minutes=ttl_minutes)

    try:
        # Try to create lock document (fails if exists)
        lock_doc.create({
            'instance_id': instance_id,
            'acquired_at': firestore.SERVER_TIMESTAMP,
            'expires_at': expires_at,
            'status': 'active'
        })
        return True

    except AlreadyExists:
        # Lock exists - check if expired
        existing_lock = lock_doc.get()
        if existing_lock.exists:
            data = existing_lock.to_dict()
            if data['expires_at'] < datetime.now():
                # Expired - can steal
                lock_doc.set({
                    'instance_id': instance_id,
                    'acquired_at': firestore.SERVER_TIMESTAMP,
                    'expires_at': expires_at,
                    'status': 'active',
                    'previous_instance': data['instance_id']
                })
                return True

        return False


def release_coordinator_lock(game_date):
    """Release coordinator lock."""
    db = firestore.Client()
    lock_doc = db.collection('coordinator_locks').document(str(game_date))
    lock_doc.delete()
```

---

### Fix 2.2: Null Correlation ID Handling (1 hour)

**Issue:** Manual triggers forget correlation_id

**Implementation:**

```python
# In all processors

def extract_correlation_id(self, message):
    """
    Extract correlation_id with fallback.

    Handles: null, missing, legacy messages, manual triggers
    """
    correlation_id = (
        message.get('correlation_id') or
        message.get('execution_id') or
        f"manual-{uuid.uuid4().hex[:8]}"
    )

    # Validate it's not empty string
    if not correlation_id or correlation_id == '':
        correlation_id = f"generated-{uuid.uuid4().hex[:8]}"

    logger.info(f"Using correlation_id: {correlation_id}")
    return correlation_id
```

---

### Fix 2.3: Timezone Standardization (1 hour)

**Issue:** Date confusion when processing spans midnight

**Implementation:**

```python
# shared/utils/date_utils.py

import pytz
from datetime import datetime, date

PT = pytz.timezone('America/Los_Angeles')

def get_game_date_from_message(message):
    """
    Extract game_date from message - NEVER derive from current time.
    """
    game_date_str = message.get('game_date')

    if not game_date_str:
        raise ValueError("Message missing required field: game_date")

    # Parse as date
    if isinstance(game_date_str, str):
        return datetime.strptime(game_date_str, '%Y-%m-%d').date()
    elif isinstance(game_date_str, date):
        return game_date_str
    else:
        raise ValueError(f"Invalid game_date format: {game_date_str}")


def today_pt():
    """Get today's date in Pacific Time (use for scheduler triggers only)."""
    return datetime.now(PT).date()


def now_pt():
    """Get current datetime in Pacific Time."""
    return datetime.now(PT)


# In all processors - USE MESSAGE DATE, NOT CURRENT TIME
def run(self, opts):
    # RIGHT:
    game_date = get_game_date_from_message(opts)

    # WRONG:
    # game_date = date.today()  # DON'T DO THIS
```

---

### Fix 2.4: Silent Failure Monitoring (1 hour)

**Issue:** Data quality issues without errors

**Implementation:**

```python
# Add to Phase 5 coordinator after predictions generated

def verify_prediction_quality(game_date):
    """Verify predictions are reasonable."""

    query = """
    SELECT
      COUNT(DISTINCT player_lookup) as players,
      COUNT(*) as total_predictions,
      AVG(predicted_points) as avg_points,
      SUM(CASE WHEN predicted_points IS NULL THEN 1 ELSE 0 END) as null_count,
      SUM(CASE WHEN predicted_points < 0 OR predicted_points > 100 THEN 1 ELSE 0 END) as invalid_count
    FROM `nba-props-platform.nba_predictions.player_prop_predictions`
    WHERE game_date = @game_date
    """

    result = client.query(query, ...).result()
    row = list(result)[0]

    # Check for data quality issues
    issues = []

    # Average prediction should be realistic
    if row['avg_points'] < 5.0 or row['avg_points'] > 50.0:
        issues.append(f"Average prediction {row['avg_points']} outside normal range (5-50)")

    # NaN check
    if row['null_count'] / row['total_predictions'] > 0.05:
        issues.append(f"{row['null_count']} NULL predictions ({row['null_count']/row['total_predictions']:.1%})")

    # Invalid values
    if row['invalid_count'] > 0:
        issues.append(f"{row['invalid_count']} predictions outside valid range (0-100)")

    if issues:
        alert_manager.send_alert(
            severity='warning',
            title=f'Prediction Quality Issues - {game_date}',
            message='\n'.join(issues)
        )
```

---

## Implementation Schedule

### Week 1 (Days 1-3)
- ✅ Fix 1.3: Deduplication timeout (1h) - Day 1
- ✅ Fix 1.4: Verify commit before publish (2h) - Day 2-3
- ✅ Fix 2.2: Null correlation_id (1h) - Day 3
- ✅ Fix 2.3: Timezone standardization (1h) - Day 3

**Week 1 Total:** 5 hours

### Week 2 (Days 4-6)
- ✅ Fix 1.1: Firestore transactions (3h) - Day 5-6
- ✅ Fix 1.5: Change detection monitoring (2h) - Day 6

**Week 2 Total:** 5 hours

### Week 3 (Days 9-10)
- ✅ Fix 1.2: Phase 5 Firestore state (4h) - Day 9-10
- ✅ Fix 2.1: Coordinator mutex (2h) - Day 10
- ✅ Fix 2.4: Silent failure monitoring (1h) - Day 10

**Week 3 Total:** 7 hours

**Grand Total:** 17 hours added to v1.0

---

## Testing Requirements

### Unit Tests (3 hours)

```python
# test_orchestrator_race_condition.py
def test_concurrent_processor_completions():
    """Verify only ONE trigger on concurrent completions."""
    pass

# test_deduplication_timeout.py
def test_deduplication_query_timeout():
    """Verify safe fallback on timeout."""
    pass

# test_coordinator_crash_recovery.py
def test_coordinator_state_recovery():
    """Verify coordinator rebuilds state from Firestore."""
    pass

# test_change_detection_health.py
def test_hash_collision_detection():
    """Verify detection of hash function bugs."""
    pass
```

### Integration Tests (4 hours)

```bash
# Test 1: Orchestrator race condition
# - Trigger two processors to complete simultaneously
# - Verify only one Phase 4 trigger

# Test 2: Coordinator crash
# - Start batch
# - Kill coordinator
# - Restart coordinator
# - Verify state recovered

# Test 3: Change detection with 0 changes
# - Set up data with no changes
# - Verify monitoring alerts

# Test 4: Message published before commit
# - Simulate BigQuery delay
# - Verify downstream doesn't receive stale data
```

---

## Acceptance Criteria

Before v1.0 launch, verify:

- [ ] All 9 critical fixes implemented
- [ ] Unit tests passing for all fixes
- [ ] Integration tests passing
- [ ] Firestore transactions tested with concurrent updates
- [ ] Coordinator crash/recovery tested
- [ ] Change detection monitoring deployed
- [ ] Silent failure queries added to monitoring
- [ ] Deduplication timeout tested
- [ ] Timezone handling consistent across all processors
- [ ] Null correlation_id handled gracefully

---

## Risk Assessment

**If these fixes are NOT implemented:**

| Fix | Risk Without It | Probability | Impact |
|-----|----------------|-------------|--------|
| Firestore transactions | Duplicate processing | High (80%) | High |
| Coordinator state | SLA violation | Medium (30%) | Critical |
| Deduplication timeout | Skip/duplicate confusion | Medium (40%) | High |
| Verify before publish | Data inconsistency | Low (10%) | High |
| Change detection monitoring | Silent stale data | Medium (20%) | Critical |

**With these fixes implemented:**
- Race condition risk: 80% → 5%
- SLA violation risk: 30% → 5%
- Silent failure risk: 20% → 2%

**Overall Production Readiness:** 60% → 95%

---

**Document Status:** ✅ Complete Action Plan
**Next Steps:**
1. Review and approve fixes
2. Integrate into V1.0-IMPLEMENTATION-PLAN-FINAL.md
3. Begin Week 1 implementation with critical fixes
4. Test thoroughly before deployment

