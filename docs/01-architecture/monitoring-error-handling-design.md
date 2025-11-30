# Pipeline Monitoring & Error Handling

**File:** `docs/01-architecture/monitoring-error-handling-design.md`
**Created:** 2025-11-14 22:22 PST
**Last Updated:** 2025-11-27 (Added processor run history logging via RunHistoryMixin)
**Purpose:** End-to-end monitoring, dependency failure handling, correlation ID tracking, DLQ handling, run history logging, and recovery procedures
**Status:** Design Complete - Partially Implemented (Run History Logging complete)
**Related:** [04-event-driven-pipeline-architecture.md](./04-event-driven-pipeline-architecture.md), `docs/monitoring/01-grafana-monitoring-guide.md`, `docs/07-monitoring/run-history-guide.md`

---

## Table of Contents

1. [The Problem: Silent Partial Failures](#the-problem-silent-partial-failures)
2. [Pub/Sub Retry & DLQ Behavior](#pubsub-retry--dlq-behavior)
3. [Message Acknowledgment Strategy (ACK vs NACK)](#message-acknowledgment-strategy-ack-vs-nack)
4. [Dependency Failure Scenarios](#dependency-failure-scenarios)
5. [Enhanced Dependency Checking](#enhanced-dependency-checking)
6. [End-to-End Pipeline Tracking](#end-to-end-pipeline-tracking)
7. [Processor Run History Logging](#processor-run-history-logging) *(NEW - Implemented)*
8. [Monitoring & Alerting](#monitoring--alerting)
9. [Recovery Procedures](#recovery-procedures)

---

## The Problem: Silent Partial Failures

### Scenario: Phase 4 Fails Silently

**What happens:**
```
2:00 PM - LeBron ruled OUT (injury update)

Phase 1 (Scrapers): ✅ SUCCESS
  └─ nbac_injury_report scraper runs
  └─ Publishes to Phase 2

Phase 2 (Raw Processors): ✅ SUCCESS
  └─ NbacInjuryReportProcessor loads to BigQuery
  └─ Publishes to Phase 3

Phase 3 (Analytics): ✅ SUCCESS
  └─ PlayerGameSummaryProcessor updates LeBron's record
  └─ Publishes to Phase 4

Phase 4 (Precompute): ❌ FAILS
  └─ PlayerDailyCacheProcessor receives event
  └─ ERROR: "Connection timeout to BigQuery"
  └─ ??? What happens now ???

Phase 5 (Predictions): ⏸️ NEVER TRIGGERED
  └─ Waiting for Phase 4 (which failed)
  └─ Old predictions still in system
  └─ Web app shows stale data

Phase 6 (Publishing): ⏸️ NEVER TRIGGERED
  └─ Firestore has outdated prediction
  └─ Users see LeBron as "probable" when he's OUT
```

**The Questions:**
1. ✅ **Will the message be there for it to retry later?** → YES (with DLQ)
2. ✅ **Will there be a way for the monitor to know what happened?** → YES (with tracking)
3. ✅ **Will we know the change didn't reach Phase 5/6?** → YES (with end-to-end tracking)

Let's design the system to answer all three!

---

## Pub/Sub Retry & DLQ Behavior

### How Pub/Sub Handles Failures

**Automatic Retry Mechanism:**

```
Phase 3 publishes event → Phase 4 subscription receives
                               ↓
                    Phase 4 processor tries to process
                               ↓
                         ERROR occurs
                               ↓
                    Returns 500 (not 200)
                               ↓
               Pub/Sub: "Message not acknowledged"
                               ↓
                 Wait (exponential backoff)
                               ↓
                    Retry #1 (after ~10 seconds)
                               ↓
                    Still fails? Retry #2 (after ~30 seconds)
                               ↓
                    Still fails? Retry #3 (after ~1 minute)
                               ↓
                    Still fails? Retry #4 (after ~3 minutes)
                               ↓
                    Still fails? Retry #5 (after ~7 minutes)
                               ↓
              After 5 attempts → Move to Dead Letter Queue
```

**Configuration (from Phase 1 → Phase 2 reference):**
```bash
gcloud pubsub subscriptions create nba-precompute-sub \
  --topic=nba-analytics-complete \
  --push-endpoint=https://nba-precompute-processors-f7p3g7f6ya-wl.a.run.app/process \
  --ack-deadline=600 \              # 10 minutes to process
  --message-retention-duration=3600s \  # Keep for 1 hour
  --dead-letter-topic=nba-analytics-complete-dlq \
  --max-delivery-attempts=5         # Try 5 times before DLQ
```

### Answer to Question 1: Message Retention

**YES, the message will be available for retry!**

**Timeline:**
```
2:00 PM - Phase 4 receives message, fails (Connection timeout)
2:00 PM - Pub/Sub retries automatically (attempt 1/5)
2:01 PM - Still fails (attempt 2/5)
2:02 PM - Still fails (attempt 3/5)
2:05 PM - Still fails (attempt 4/5)
2:12 PM - Still fails (attempt 5/5)
2:12 PM - Message moved to Dead Letter Queue (DLQ)

DLQ Retention:
  - Message stored in DLQ topic
  - Can be pulled manually
  - Can be replayed when issue fixed
  - Persists for 7 days (configurable)
```

**What this means:**
- Message is NOT lost
- Automatic retries handle transient errors
- DLQ preserves failed messages for manual recovery
- Can replay DLQ when Phase 4 is fixed

**However:** While in retry/DLQ, Phase 5 is NOT triggered (pipeline stalled)

---

## Message Acknowledgment Strategy (ACK vs NACK)

### The Critical Decision: When to Return 200 vs 500

**This is the most important architectural decision for Pub/Sub message handling.**

When your Cloud Run service receives a Pub/Sub push message, you have **TWO choices**:

1. **Return 200 (Success)** → Message is **DELETED** from subscription (acknowledged/ACK)
2. **Return 500 (Failure)** → Message is **RETRIED** with exponential backoff (not acknowledged/NACK)

**You CANNOT "put a message back in the queue" to handle later.** It's either deleted (ACK) or retried (NACK).

### Why This Matters

**Wrong choice = lost data or infinite retry loops:**

```
❌ BAD: Return 200 when dependencies missing
   → Message deleted
   → No retry
   → Data never processed
   → Silent failure

❌ BAD: Return 500 for same-day dependencies
   → Retries every 10s-7min (5 attempts)
   → Goes to DLQ
   → Manual intervention needed
   → Wastes resources

✅ GOOD: Return 200 for same-day deps (opportunistic triggering)
   → Message deleted (no retry needed)
   → Next Phase 2 event will trigger again
   → Self-healing

✅ GOOD: Return 500 for historical deps (backfill needed)
   → Retries (gives time for backfill)
   → Goes to DLQ if unresolved
   → Alert for manual intervention
```

### Dependency Failure Types

We classify dependency failures into **three types**, each requiring different handling:

#### Type 1: Same-Day Dependencies (Opportunistic Triggering)

**Characteristics:**
- Dependencies from **current processing cycle** (same game_date)
- Will arrive soon (within minutes/hours) via normal pipeline flow
- Example: Phase 3 needs 6 Phase 2 tables for today's games

**Handling Strategy:**
- ✅ **Return 200 (ACK)** - Delete message
- ✅ **Log as 'waiting'** - Not an error, expected behavior
- ✅ **Wait for next trigger** - Opportunistic pattern

**Rationale:**
- Every Phase 2 table publishes its own event
- Each event triggers Phase 3 to check dependencies
- Eventually all dependencies arrive → processing succeeds
- No manual intervention needed

**Example Timeline:**
```
10:05 PM - Table 1 loads → Phase 3 triggered
           ├─ check_dependencies() → Missing tables 2-6
           ├─ Returns 200 → Message DELETED
           └─ Waits for next trigger

10:10 PM - Table 2 loads → Phase 3 triggered (NEW MESSAGE)
           ├─ check_dependencies() → All critical deps present!
           ├─ Processes data
           └─ Returns 200 → Message DELETED
```

#### Type 2: Historical Dependencies (Backfill Needed)

**Characteristics:**
- Dependencies from **past dates** (historical data)
- Will NOT arrive via normal pipeline flow
- Example: Phase 3 needs last 10 days of player stats for rolling averages
- Requires manual backfill or data migration

**Handling Strategy:**
- ✅ **Return 500 (NACK)** - Retry message
- ✅ **Send alert** after 2-3 retries
- ✅ **Move to DLQ** after max retries (5 attempts)
- ✅ **Manual intervention** required

**Rationale:**
- Historical data won't arrive automatically
- Retry gives time for backfill to run
- Alert notifies ops team of missing data
- DLQ preserves message for replay after backfill

**Example Timeline:**
```
2:00 PM - Phase 3 triggered for game_date 2025-11-15
          ├─ check_dependencies() → Need 10 days history (2025-11-05 to 2025-11-14)
          ├─ Only 3 days exist in database
          ├─ Returns 500 → Message RETRIED
          └─ Alert: "Missing historical data"

2:00 PM - Retry 1 → Still missing → 500
2:01 PM - Retry 2 → Still missing → 500
2:02 PM - Retry 3 → Alert escalated
2:05 PM - Retry 4 → Still missing → 500
2:12 PM - Retry 5 → Still missing → 500
2:12 PM - Moved to DLQ
        → Ops investigates
        → Runs backfill
        → Replays DLQ
```

#### Type 3: Optional Dependencies (Degraded Processing)

**Characteristics:**
- Dependencies that **enhance** but don't block processing
- Nice to have, not required
- Example: Betting odds enhance predictions but aren't critical

**Handling Strategy:**
- ✅ **Return 200 (ACK)** - Process with degraded features
- ✅ **Log as warning** - Track missing optional data
- ✅ **Proceed without** optional data

**Rationale:**
- Better to have partial data than no data
- User experience degraded but not broken
- Can backfill later if needed

### Decision Tree for Message Handling

```
┌─────────────────────────────────────────────────────────────────┐
│             PUB/SUB MESSAGE HANDLING DECISION TREE              │
└─────────────────────────────────────────────────────────────────┘

Message arrives
    ↓
Check idempotency: Already processed recently?
    │
    ├─► YES → Return 200 (ACK) - Skip duplicate processing
    │
    └─► NO → Continue
           ↓
       Check dependencies
           ↓
    ┌──────────────────────────────────────────┐
    │                                          │
    ├─► All dependencies met?                  │
    │   ├─ YES → Process data                  │
    │   │         Return 200 (ACK)             │
    │   │                                      │
    │   └─ NO → What type of failure?         │
    │            ↓                             │
    │       ┌────────────────────┐             │
    │       │                    │             │
    │       ├─► Same-day deps?   │             │
    │       │   ├─ YES → Return 200 (ACK)      │
    │       │   │        Log: "waiting"        │
    │       │   │        Wait for next trigger │
    │       │   │                              │
    │       ├─► Historical deps?               │
    │       │   ├─ YES → Check override        │
    │       │   │        │                     │
    │       │   │        ├─► Override exists?  │
    │       │   │        │   ├─ YES → Process  │
    │       │   │        │   │        Return 200│
    │       │   │        │   │                 │
    │       │   │        │   └─ NO → Continue  │
    │       │   │        │           ↓         │
    │       │   │        └─► Check retry count │
    │       │   │             │                │
    │       │   │             ├─► <3 retries?  │
    │       │   │             │   ├─ YES →     │
    │       │   │             │   │   Return 500│
    │       │   │             │   │   (NACK)   │
    │       │   │             │   │            │
    │       │   │             │   └─ NO →      │
    │       │   │             │       Alert ops│
    │       │   │             │       Return 200│
    │       │   │             │       (send to  │
    │       │   │             │       manual    │
    │       │   │             │       queue)    │
    │       │   │                               │
    │       └─► Optional deps?                  │
    │           └─ YES → Process with degraded │
    │                    features               │
    │                    Log warning            │
    │                    Return 200 (ACK)       │
    │                                          │
    └──────────────────────────────────────────┘
```

### Implementation: Enhanced Message Handler

```python
from enum import Enum

class DependencyType(Enum):
    SAME_DAY = "same_day"        # Will arrive soon via opportunistic triggering
    HISTORICAL = "historical"     # Needs backfill or manual intervention
    OPTIONAL = "optional"         # Nice to have, not required

class MessageAction(Enum):
    ACK = "ack"                  # Return 200 - delete message
    NACK = "nack"                # Return 500 - retry message

@app.route('/process', methods=['POST'])
def process_message():
    """
    Enhanced Pub/Sub message handler with smart ACK/NACK logic.

    Returns:
        tuple: (response_dict, status_code)
            - 200: Message acknowledged (deleted)
            - 500: Message not acknowledged (will retry)
    """

    # Decode message
    message = decode_pubsub_message(request)
    game_date = message.get('game_date')
    correlation_id = message.get('correlation_id')
    retry_count = int(request.headers.get('X-CloudTasks-TaskRetryCount', 0))

    # Initialize processor
    processor = get_processor_for_message(message)

    # Check idempotency
    if processor.already_processed_recently(game_date):
        logger.info(f"Already processed {game_date} recently, skipping")
        return jsonify({
            "status": "skipped",
            "reason": "already_processed"
        }), 200  # ACK - don't reprocess

    # Check dependencies
    dep_check = processor.check_dependencies(game_date, correlation_id)

    # Log dependency check result
    processor.log_dependency_check(dep_check, retry_count)

    # Handle based on dependency check result
    if dep_check.status == 'ready':
        # All dependencies met - process!
        logger.info(f"Dependencies met, processing {game_date}")
        processor.run(message)
        return jsonify({"status": "completed"}), 200  # ACK

    elif dep_check.dependency_type == DependencyType.SAME_DAY:
        # Same-day dependencies not ready yet - ACK and wait for next trigger
        logger.info(
            f"Same-day dependencies not ready: {dep_check.missing_deps}. "
            f"Will retry on next Phase 2 event."
        )
        return jsonify({
            "status": "skipped",
            "reason": "waiting_for_same_day_dependencies",
            "missing": dep_check.missing_deps
        }), 200  # ACK - opportunistic triggering will retry

    elif dep_check.dependency_type == DependencyType.HISTORICAL:
        # Historical dependencies missing - needs backfill

        # Check for manual override
        if dep_check.has_override:
            logger.warning(
                f"Historical deps missing but OVERRIDE exists: {dep_check.override_reason}"
            )
            processor.run(message, allow_missing_deps=True)
            return jsonify({
                "status": "completed_with_override",
                "override": dep_check.override_reason
            }), 200  # ACK

        # No override - check retry count
        if retry_count < 3:
            # Retry a few times in case backfill is running
            logger.warning(
                f"Missing historical dependencies (retry {retry_count}/3): "
                f"{dep_check.missing_deps}"
            )
            return jsonify({
                "status": "retry",
                "reason": "missing_historical_dependencies",
                "missing": dep_check.missing_deps,
                "retry_count": retry_count
            }), 500  # NACK - will retry

        else:
            # Retried enough - send alert and ACK (don't retry forever)
            logger.error(
                f"Historical dependencies missing after {retry_count} retries. "
                f"Sending to manual queue."
            )

            # Send alert
            send_alert(
                title="⚠️ Missing Historical Data - Manual Intervention Needed",
                severity="warning",
                message=f"{processor.__class__.__name__} missing historical dependencies",
                details={
                    "processor": processor.__class__.__name__,
                    "game_date": game_date,
                    "missing_deps": dep_check.missing_deps,
                    "retry_count": retry_count,
                    "correlation_id": correlation_id
                }
            )

            # Log to manual intervention queue
            log_manual_intervention_needed(processor, message, dep_check)

            return jsonify({
                "status": "needs_manual_intervention",
                "reason": "missing_historical_dependencies",
                "missing": dep_check.missing_deps
            }), 200  # ACK - stop retrying, needs manual fix

    elif dep_check.dependency_type == DependencyType.OPTIONAL:
        # Optional dependencies missing - process with degraded features
        logger.warning(
            f"Optional dependencies missing, processing with degraded features: "
            f"{dep_check.missing_deps}"
        )
        processor.run(message, allow_missing_optional=True)
        return jsonify({
            "status": "completed_degraded",
            "missing_optional": dep_check.missing_deps
        }), 200  # ACK

    else:
        # Unknown dependency type - fail safe
        logger.error(f"Unknown dependency type: {dep_check.dependency_type}")
        return jsonify({
            "status": "error",
            "reason": "unknown_dependency_type"
        }), 500  # NACK
```

### Key Takeaways

**ACK (Return 200) when:**
- ✅ Processing succeeded
- ✅ Already processed recently (idempotency)
- ✅ Same-day dependencies not ready (opportunistic triggering will retry)
- ✅ Historical dependencies missing AND retry limit reached (send to manual queue)
- ✅ Optional dependencies missing (process with degraded features)
- ✅ Manual override exists

**NACK (Return 500) when:**
- ✅ Processing failed due to transient error (connection timeout, etc.)
- ✅ Historical dependencies missing AND retry count < 3 (give time for backfill)
- ✅ Data validation failed (bad data format)

**Never NACK for:**
- ❌ Same-day dependencies (use opportunistic triggering instead)
- ❌ After max retries (send to manual queue instead)
- ❌ Idempotency skips (already processed)

---

## Dependency Failure Scenarios

This section details **six specific scenarios** with concrete examples, detection strategies, and handling procedures.

### Scenario 1: Same-Day Dependencies Not Ready (Normal Operation)

**What triggers it:**
- Phase 3 analytics processor receives event from Phase 2
- Some Phase 2 tables for today's games haven't loaded yet
- This is **EXPECTED** behavior during the processing window

**Example:**
```
10:05 PM - nbac_gamebook_player_stats loads (table 1/6)
           → Triggers PlayerGameSummaryProcessor
           → Missing: bdl_player_boxscores, play_by_play, odds data
           → 5 out of 6 tables still pending
```

**Detection:**
```python
dep_check = processor.check_dependencies(game_date='2025-11-15')

if dep_check.status == 'waiting_same_day':
    # Missing: ['bdl_player_boxscores', 'nbac_play_by_play', ...]
    # Type: SAME_DAY (will arrive soon)
```

**Handling:**
- ✅ **Return 200 (ACK)** - Delete message
- ✅ **Log as INFO** level (not an error)
- ✅ **Wait for next trigger** - Opportunistic pattern
- ❌ **NO alert needed** - This is normal

**What happens next:**
```
10:10 PM - bdl_player_boxscores loads (table 2/6)
           → Triggers PlayerGameSummaryProcessor again (NEW MESSAGE)
           → All CRITICAL dependencies now present
           → Processes successfully
```

**Pipeline execution log entry:**
```json
{
  "status": "skipped",
  "dependency_check_result": "waiting_same_day",
  "dependency_failure_type": "same_day",
  "message_acknowledgment": "ack",
  "missing_dependencies": ["bdl_player_boxscores", "nbac_play_by_play"],
  "manual_override_used": false
}
```

---

### Scenario 2: Historical Dependencies Missing (Backfill Needed)

**What triggers it:**
- Processor needs historical data that doesn't exist in database
- Common during: New deployment, data migration, new feature requiring lookback

**Example:**
```python
# PlayerGameSummaryProcessor needs last 10 games for rolling averages
def get_dependencies(self):
    return {
        'nba_raw.nbac_gamebook_player_stats': {
            'critical': True,
            'type': DependencyType.SAME_DAY
        },
        'nba_analytics.player_rolling_10_game_avg': {
            'critical': True,
            'type': DependencyType.HISTORICAL,
            'lookback_days': 10,
            'min_days_required': 10
        }
    }

# check_dependencies() finds:
# - Today's data: ✅ Present
# - Last 10 days: ❌ Only 3 days exist (need 10)
```

**Detection:**
```python
dep_check = processor.check_dependencies(game_date='2025-11-15')

if dep_check.status == 'missing_historical':
    # Missing: Days 2025-11-05 to 2025-11-11 (7 days)
    # Type: HISTORICAL (won't arrive automatically)
```

**Handling (Retry Strategy):**
```
Attempt 1 (2:00 PM): Return 500 (NACK) - Retry in 10s
Attempt 2 (2:00 PM): Return 500 (NACK) - Retry in 30s
Attempt 3 (2:01 PM): Return 500 (NACK) - Retry in 1min
                     → Send alert to ops
Attempt 4 (2:05 PM): Return 500 (NACK) - Retry in 3min
Attempt 5 (2:12 PM): Return 500 (NACK) - Retry in 7min
After 5 attempts:    Move to DLQ
                     → Log to manual_intervention_needed table
```

**Alert sent (after attempt 3):**
```
⚠️ Missing Historical Data - Manual Intervention Needed

Processor: PlayerGameSummaryProcessor
Game Date: 2025-11-15
Missing: player_rolling_10_game_avg (7 of 10 days)
Retry Count: 3/5
Action: Run backfill or approve override

Query to check:
SELECT COUNT(DISTINCT game_date) as days_available
FROM nba_analytics.player_rolling_10_game_avg
WHERE game_date BETWEEN '2025-11-05' AND '2025-11-14'
```

**Recovery options:**

**Option A: Backfill the data**
```bash
# Run backfill for missing dates
python backfill_analytics.py \
  --processor=PlayerGameSummaryProcessor \
  --start-date=2025-11-05 \
  --end-date=2025-11-14

# Replay DLQ messages
python bin/orchestration/replay_dlq.py \
  --dlq=nba-raw-data-complete-dlq-sub \
  --limit=100
```

**Option B: Manual override (approve to run without historical data)**
```sql
-- Insert override approval
INSERT INTO nba_orchestration.processing_overrides (
    processor_name,
    game_date,
    override_reason,
    approved_by,
    approved_at,
    expires_at
)
VALUES (
    'PlayerGameSummaryProcessor',
    '2025-11-15',
    'New deployment - historical data not critical for first run',
    'ops-engineer@example.com',
    CURRENT_TIMESTAMP(),
    TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
);

-- Replay DLQ (will check for override and proceed)
python bin/orchestration/replay_dlq.py \
  --dlq=nba-raw-data-complete-dlq-sub \
  --correlation-id=abc123
```

---

### Scenario 3: Optional Dependencies Missing (Degraded Processing)

**What triggers it:**
- Optional data sources unavailable or incomplete
- Processing can continue with reduced features

**Example:**
```python
def get_dependencies(self):
    return {
        # Critical dependencies
        'nba_raw.nbac_gamebook_player_stats': {
            'critical': True,
            'type': DependencyType.SAME_DAY
        },
        # Optional dependencies
        'nba_raw.odds_api_player_points_props': {
            'critical': False,  # OPTIONAL
            'type': DependencyType.OPTIONAL
        },
        'nba_raw.bettingpros_player_points_props': {
            'critical': False,  # OPTIONAL
            'type': DependencyType.OPTIONAL
        }
    }

# check_dependencies() finds:
# - Critical data: ✅ All present
# - Optional betting odds: ❌ Missing (API down)
```

**Detection:**
```python
dep_check = processor.check_dependencies(game_date='2025-11-15')

if dep_check.status == 'ready_degraded':
    # All critical present
    # Missing optional: ['odds_api_player_points_props', 'bettingpros_player_points_props']
```

**Handling:**
- ✅ **Return 200 (ACK)** - Process successfully
- ✅ **Log as WARNING** - Track missing optional data
- ✅ **Process with degraded features** - Output still valid
- ⚠️ **Track frequency** - If always missing, investigate

**Processing behavior:**
```python
def process(self, game_date, allow_missing_optional=True):
    # Fetch critical data
    player_stats = get_player_stats(game_date)

    # Try to fetch optional data
    betting_odds = get_betting_odds(game_date)  # May be None

    # Calculate analytics
    result = {
        'points': player_stats['points'],
        'rebounds': player_stats['rebounds'],
        # ... critical fields always present
    }

    # Enhance with optional data if available
    if betting_odds:
        result['betting_line'] = betting_odds['points_line']
        result['line_differential'] = result['points'] - betting_odds['points_line']
    else:
        result['betting_line'] = None
        result['line_differential'] = None

    return result
```

**Monitoring:**
```sql
-- Check frequency of missing optional dependencies
SELECT
    processor_name,
    JSON_EXTRACT_SCALAR(missing_dependencies, '$[0]') as missing_dep,
    COUNT(*) as occurrences,
    COUNT(*) / (
        SELECT COUNT(*)
        FROM pipeline_execution_log sub
        WHERE sub.processor_name = main.processor_name
          AND sub.game_date >= CURRENT_DATE() - 7
    ) * 100 as miss_rate_pct
FROM nba_orchestration.pipeline_execution_log main
WHERE dependency_failure_type = 'optional'
  AND game_date >= CURRENT_DATE() - 7
GROUP BY processor_name, missing_dep
HAVING miss_rate_pct > 20;  -- Alert if >20% miss rate
```

---

### Scenario 4: Circular Dependency Detection

**What triggers it:**
- Multiple processors waiting on each other's outputs
- OR: Single dependency that never arrives

**Example:**
```
Processor A: Waiting for table X (never loads)
Processor B: Waiting for table X (never loads)
Processor C: Waiting for table Y from Processor A (blocked)

Result: 3 processors stuck, pipeline stalled
```

**Detection:**
```sql
-- Find dependencies that are blocking multiple processors
WITH blocking_deps AS (
    SELECT
        JSON_EXTRACT_SCALAR(missing_dependencies, '$[0]') as missing_dep,
        COUNT(DISTINCT processor_name) as blocked_processor_count,
        ARRAY_AGG(DISTINCT processor_name) as blocked_processors,
        MAX(started_at) as latest_attempt
    FROM nba_orchestration.pipeline_execution_log
    WHERE dependency_check_result IN ('waiting_same_day', 'missing_historical')
      AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
    GROUP BY missing_dep
)
SELECT *
FROM blocking_deps
WHERE blocked_processor_count >= 2  -- Same dep blocking 2+ processors
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), latest_attempt, MINUTE) > 120;  -- Stuck for 2+ hours
```

**Alert:**
```
🚨 Circular Dependency Detected

Missing Dependency: nba_raw.bdl_player_boxscores
Blocked Processors: [PlayerGameSummaryProcessor, TeamOffenseProcessor, TeamDefenseProcessor]
Duration: 2.5 hours
Last Attempt: 2025-11-15 22:30:00

Action Required:
1. Check if upstream scraper failed: bdl_player_boxscores_scraper
2. Check scraper_execution_log for failures
3. Manually trigger scraper if needed
```

**Recovery:**
```bash
# Check scraper status
bq query "
SELECT status, error_message, execution_id
FROM nba_orchestration.scraper_execution_log
WHERE scraper_name = 'bdl_player_boxscores'
  AND DATE(started_at) = CURRENT_DATE()
ORDER BY started_at DESC
LIMIT 1
"

# If scraper failed, manually trigger
curl -X POST https://nba-scrapers-.../scrape \
  -H "Content-Type: application/json" \
  -d '{"scraper": "bdl_player_boxscores", "force": true}'
```

---

### Scenario 5: Data Quality Issues (Validation Failures)

**What triggers it:**
- Dependencies exist BUT data is corrupt/invalid
- Processor detects bad data during processing

**Example:**
```python
def process(self, game_date):
    # Dependencies check passed - data exists
    player_stats = fetch_player_stats(game_date)

    # Data validation during processing
    if player_stats.empty:
        raise ValidationError("Player stats table exists but has 0 rows")

    if player_stats['points'].isnull().all():
        raise ValidationError("All points values are NULL")

    if (player_stats['minutes'] < 0).any():
        raise ValidationError("Negative minutes detected")

    # Continue processing...
```

**Detection:**
```python
# In message handler
try:
    processor.run(message)
    return jsonify({"status": "completed"}), 200

except ValidationError as e:
    # Data quality issue - NOT a dependency issue
    logger.error(f"Data validation failed: {e}")

    # Log with specific error type
    processor.log_pipeline_execution(
        status='failed',
        error_type='ValidationError',
        error_message=str(e)
    )

    # Send alert
    send_alert(
        title="🚨 Data Quality Issue Detected",
        severity="error",
        message=f"Data validation failed in {processor.__class__.__name__}",
        details={"error": str(e), "game_date": game_date}
    )

    # Return 500 for retry (maybe transient)
    return jsonify({"status": "failed", "reason": "validation_error"}), 500
```

**Monitoring:**
```sql
-- Track validation failures
SELECT
    processor_name,
    error_message,
    COUNT(*) as failure_count,
    MAX(started_at) as latest_occurrence
FROM nba_orchestration.pipeline_execution_log
WHERE error_type = 'ValidationError'
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY processor_name, error_message
ORDER BY failure_count DESC;
```

**Recovery:**
- Investigate upstream data (Phase 2)
- Check scraper output files for corruption
- Re-run scraper if needed
- Fix data manually if one-off issue

---

### Scenario 6: Partial Backfill (Some Historical Data Present)

**What triggers it:**
- Need 10 days of historical data
- Only 5 days available in database
- Partial processing possible with reduced accuracy

**Example:**
```python
def check_dependencies(self, game_date):
    # Need 10 days of rolling averages
    result = bq.query(f"""
        SELECT COUNT(DISTINCT game_date) as days_available
        FROM nba_analytics.player_game_summary
        WHERE game_date BETWEEN DATE_SUB('{game_date}', INTERVAL 10 DAY)
          AND DATE_SUB('{game_date}', INTERVAL 1 DAY)
    """).to_dataframe()

    days_available = result['days_available'].iloc[0]

    if days_available >= 10:
        return DependencyCheckResult(status='ready')
    elif days_available >= 5:  # Partial data
        return DependencyCheckResult(
            status='ready_degraded',
            missing_historical_days=10 - days_available,
            warning=f"Only {days_available}/10 days available - reduced accuracy"
        )
    else:  # < 5 days - not enough
        return DependencyCheckResult(
            status='missing_historical',
            missing_historical_days=10 - days_available
        )
```

**Handling:**
- ✅ **If >= 5 days:** Process with degraded accuracy (ACK)
- ❌ **If < 5 days:** Fail and request backfill (NACK)
- ✅ **Log degradation level** for monitoring

**Processing behavior:**
```python
def calculate_rolling_average(self, player_id, game_date, days_available):
    # Calculate with available data
    avg = calculate_avg(player_id, game_date, lookback=days_available)

    # Flag as degraded
    return {
        'rolling_avg_points': avg,
        'rolling_avg_accuracy': 'degraded' if days_available < 10 else 'full',
        'rolling_avg_sample_size': days_available,
        'rolling_avg_target_size': 10
    }
```

---

## Enhanced Dependency Checking

### DependencyCheckResult Class

**Structured result object for dependency validation:**

```python
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

class DependencyType(Enum):
    """Classification of dependency failure types."""
    SAME_DAY = "same_day"        # Will arrive soon via opportunistic triggering
    HISTORICAL = "historical"     # Needs backfill or manual intervention
    OPTIONAL = "optional"         # Nice to have, not required
    NONE = "none"                # No failure

@dataclass
class DependencyCheckResult:
    """
    Result of dependency validation check.

    Attributes:
        status: Overall dependency status
        dependency_type: Type of dependency failure (if any)
        missing_deps: List of missing dependency table names
        missing_historical_days: Number of historical days missing
        has_override: Whether manual override exists
        override_reason: Reason for override (if exists)
        action: Recommended action (ACK or NACK)
        warning: Optional warning message
    """
    status: str  # 'ready', 'waiting_same_day', 'missing_historical', 'ready_degraded'
    dependency_type: DependencyType = DependencyType.NONE
    missing_deps: List[str] = None
    missing_historical_days: int = 0
    has_override: bool = False
    override_reason: Optional[str] = None
    action: str = 'process'  # 'process', 'skip_ack', 'skip_nack'
    warning: Optional[str] = None

    def __post_init__(self):
        if self.missing_deps is None:
            self.missing_deps = []
```

### Enhanced check_dependencies() Method

**Implementation with dependency type classification:**

```python
class AnalyticsProcessorBase:
    """Enhanced base class with dependency type support."""

    def get_dependencies(self):
        """
        Define processor dependencies with type classification.

        Returns:
            dict: Dependency configuration with types
        """
        return {
            'nba_raw.nbac_gamebook_player_stats': {
                'critical': True,
                'type': DependencyType.SAME_DAY,
                'expected_count_min': 200,
                'max_age_hours_fail': 24
            },
            'nba_raw.bdl_player_boxscores': {
                'critical': True,
                'type': DependencyType.SAME_DAY
            },
            'nba_analytics.player_rolling_10_game_avg': {
                'critical': True,
                'type': DependencyType.HISTORICAL,
                'lookback_days': 10,
                'min_days_required': 10
            },
            'nba_raw.odds_api_player_points_props': {
                'critical': False,  # OPTIONAL
                'type': DependencyType.OPTIONAL
            }
        }

    def check_dependencies(self, game_date: str, correlation_id: str = None):
        """
        Enhanced dependency checking with type-aware handling.

        Args:
            game_date: Game date to check dependencies for
            correlation_id: Correlation ID for tracking

        Returns:
            DependencyCheckResult: Structured result with handling guidance
        """
        dependencies = self.get_dependencies()
        result = DependencyCheckResult(status='ready')

        missing_critical_same_day = []
        missing_critical_historical = []
        missing_optional = []

        for table, config in dependencies.items():
            is_critical = config.get('critical', True)
            dep_type = config.get('type', DependencyType.SAME_DAY)

            # Check if dependency exists
            exists = self._check_table_exists(table, game_date, config)

            if not exists:
                # Classify missing dependency
                if is_critical:
                    if dep_type == DependencyType.SAME_DAY:
                        missing_critical_same_day.append(table)
                    elif dep_type == DependencyType.HISTORICAL:
                        missing_critical_historical.append(table)
                else:  # Optional
                    missing_optional.append(table)

        # Check for manual override (only relevant for historical deps)
        override = None
        if missing_critical_historical:
            override = self._check_manual_override(
                processor_name=self.__class__.__name__,
                game_date=game_date
            )

        # Determine result based on what's missing
        if missing_critical_same_day:
            # Same-day deps not ready - ACK and wait for next trigger
            result = DependencyCheckResult(
                status='waiting_same_day',
                dependency_type=DependencyType.SAME_DAY,
                missing_deps=missing_critical_same_day,
                action='skip_ack'
            )

        elif missing_critical_historical:
            if override:
                # Override exists - process anyway
                result = DependencyCheckResult(
                    status='ready',
                    has_override=True,
                    override_reason=override['override_reason'],
                    action='process',
                    warning=f"Processing with override: {override['override_reason']}"
                )
            else:
                # No override - NACK to retry (give time for backfill)
                result = DependencyCheckResult(
                    status='missing_historical',
                    dependency_type=DependencyType.HISTORICAL,
                    missing_deps=missing_critical_historical,
                    missing_historical_days=self._count_missing_historical_days(
                        missing_critical_historical, game_date
                    ),
                    action='skip_nack'
                )

        elif missing_optional:
            # Optional deps missing - process with degraded features
            result = DependencyCheckResult(
                status='ready_degraded',
                dependency_type=DependencyType.OPTIONAL,
                missing_deps=missing_optional,
                action='process',
                warning=f"Processing without optional data: {missing_optional}"
            )

        else:
            # All dependencies met
            result = DependencyCheckResult(
                status='ready',
                action='process'
            )

        return result

    def _check_manual_override(self, processor_name: str, game_date: str):
        """Check if manual override exists for this processor and date."""
        query = f"""
        SELECT
            override_reason,
            approved_by,
            approved_at
        FROM nba_orchestration.processing_overrides
        WHERE processor_name = '{processor_name}'
          AND game_date = '{game_date}'
          AND expires_at > CURRENT_TIMESTAMP()
        LIMIT 1
        """

        result = self.bq_client.query(query).to_dataframe()

        if not result.empty:
            return result.iloc[0].to_dict()
        return None

    def _count_missing_historical_days(self, missing_tables: List[str], game_date: str):
        """Count how many historical days are missing for historical dependencies."""
        # Implementation depends on specific dependency config
        # Return number of days missing for historical lookback
        for table in missing_tables:
            dep_config = self.get_dependencies().get(table, {})
            if dep_config.get('type') == DependencyType.HISTORICAL:
                lookback_days = dep_config.get('lookback_days', 10)
                # Query to count available days
                # ... implementation ...
                return lookback_days  # Simplified
        return 0
```

### Manual Override Table Schema

**Create table for manual processing approvals:**

```sql
CREATE TABLE IF NOT EXISTS nba_orchestration.processing_overrides (
    -- Identification
    override_id STRING DEFAULT GENERATE_UUID(),
    processor_name STRING NOT NULL,
    game_date DATE NOT NULL,

    -- Approval details
    override_reason STRING NOT NULL,
    approved_by STRING NOT NULL,          -- Email of person who approved
    approved_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    expires_at TIMESTAMP NOT NULL,         -- Override expiration (prevent stale overrides)

    -- Metadata
    created_by_system STRING,              -- 'manual', 'automated', 'backfill_script'
    notes STRING,
    metadata JSON
)
PARTITION BY game_date
CLUSTER BY processor_name, approved_at
OPTIONS(
    description="Manual overrides to allow processing despite missing dependencies"
);
```

### Usage Example: Complete Flow

```python
# In Phase 3 analytics service
@app.route('/process', methods=['POST'])
def process_analytics():
    message = decode_pubsub_message(request)
    game_date = message['game_date']
    correlation_id = message['correlation_id']
    retry_count = int(request.headers.get('X-CloudTasks-TaskRetryCount', 0))

    # Get processor
    processor = PlayerGameSummaryProcessor()

    # Check dependencies (enhanced)
    dep_check = processor.check_dependencies(game_date, correlation_id)

    # Log dependency check
    log_dependency_check_result(dep_check, processor, retry_count)

    # Handle based on result
    if dep_check.action == 'process':
        # Either all deps met OR override exists
        if dep_check.has_override:
            logger.warning(f"Processing with override: {dep_check.override_reason}")

        processor.run(message)
        return jsonify({"status": "completed"}), 200

    elif dep_check.action == 'skip_ack':
        # Same-day deps not ready - ACK and wait for next trigger
        logger.info(f"Waiting for same-day dependencies: {dep_check.missing_deps}")
        return jsonify({
            "status": "skipped",
            "reason": "waiting_same_day",
            "missing": dep_check.missing_deps
        }), 200

    elif dep_check.action == 'skip_nack':
        # Historical deps missing - NACK to retry

        if retry_count < 3:
            # Retry a few times
            logger.warning(
                f"Missing historical dependencies (retry {retry_count}/3): "
                f"{dep_check.missing_deps}"
            )
            return jsonify({
                "status": "retry",
                "reason": "missing_historical",
                "missing": dep_check.missing_deps
            }), 500  # NACK

        else:
            # Retried enough - alert and ACK
            send_alert(
                title="⚠️ Missing Historical Data",
                message=f"{processor.__class__.__name__} needs backfill or override",
                details={
                    "missing_deps": dep_check.missing_deps,
                    "missing_days": dep_check.missing_historical_days,
                    "game_date": game_date
                }
            )

            return jsonify({
                "status": "needs_manual_intervention",
                "reason": "missing_historical",
                "missing": dep_check.missing_deps
            }), 200  # ACK - stop retrying
```

### Manual Override Workflow

**When ops engineer receives alert:**

```bash
# Step 1: Investigate what's missing
bq query "
SELECT COUNT(DISTINCT game_date) as days_available
FROM nba_analytics.player_rolling_10_game_avg
WHERE game_date BETWEEN '2025-11-05' AND '2025-11-14'
"
# Result: 3 days available (need 10)

# Step 2: Decide on action

# Option A: Backfill missing data (preferred)
python backfill_analytics.py \
  --processor=PlayerGameSummaryProcessor \
  --start-date=2025-11-05 \
  --end-date=2025-11-14

# Option B: Approve override (if backfill not critical)
bq query "
INSERT INTO nba_orchestration.processing_overrides (
    processor_name,
    game_date,
    override_reason,
    approved_by,
    expires_at
)
VALUES (
    'PlayerGameSummaryProcessor',
    '2025-11-15',
    'New deployment - rolling averages not critical for first run',
    'ops-engineer@example.com',
    TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
)
"

# Step 3: Replay DLQ (message will check for override)
python bin/orchestration/replay_dlq.py \
  --dlq=nba-raw-data-complete-dlq-sub \
  --game-date=2025-11-15

# Step 4: Verify processing succeeded
bq query "
SELECT status, has_override, override_reason
FROM nba_orchestration.pipeline_execution_log
WHERE processor_name = 'PlayerGameSummaryProcessor'
  AND game_date = '2025-11-15'
ORDER BY started_at DESC
LIMIT 1
"
```

---

## End-to-End Pipeline Tracking

**Create central tracking table:**

```sql
CREATE TABLE IF NOT EXISTS nba_orchestration.pipeline_execution_log (
    -- Unique identifiers
    execution_id STRING NOT NULL,           -- UUID for this specific processing event
    source_execution_id STRING,             -- Links back to triggering event
    correlation_id STRING NOT NULL,         -- Links entire pipeline run

    -- What & When
    phase INT64 NOT NULL,                   -- 1, 2, 3, 4, 5, 6
    processor_name STRING NOT NULL,         -- e.g., "PlayerDailyCacheProcessor"
    event_type STRING NOT NULL,             -- e.g., "raw_data_loaded", "analytics_complete"

    -- Processing context
    game_date DATE,
    game_ids ARRAY<STRING>,
    affected_entities JSON,                 -- {players: [...], teams: [...], games: [...]}

    -- Status tracking
    status STRING NOT NULL,                 -- 'started', 'completed', 'failed', 'skipped'
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    duration_seconds FLOAT64,

    -- Dependency tracking (ENHANCED for dependency failure monitoring)
    dependencies_met BOOL,
    missing_dependencies ARRAY<STRING>,
    dependency_check_result STRING,        -- NEW: 'ready', 'waiting_same_day', 'missing_historical', 'ready_degraded'
    dependency_failure_type STRING,        -- NEW: 'same_day', 'historical', 'optional', 'none'
    message_acknowledgment STRING,         -- NEW: 'ack', 'nack'
    manual_override_used BOOL,             -- NEW: Whether manual override was used
    override_reason STRING,                -- NEW: Reason for override (if used)

    -- Error details
    error_type STRING,
    error_message STRING,
    retry_count INT64,

    -- Pub/Sub metadata
    pubsub_message_id STRING,               -- For debugging
    pubsub_subscription STRING,

    -- Data metrics
    records_processed INT64,
    records_inserted INT64,
    records_updated INT64,

    -- Metadata
    metadata JSON
)
PARTITION BY game_date
CLUSTER BY correlation_id, phase, status, started_at
OPTIONS(
    description="Tracks all pipeline executions across all phases for end-to-end monitoring"
);
```

### How It Works

**Every processor logs its execution:**

```python
class BaseProcessor:
    """Enhanced base class with pipeline tracking."""

    def run(self, opts):
        # Generate IDs
        self.execution_id = str(uuid.uuid4())
        self.correlation_id = opts.get('correlation_id') or self.execution_id

        # Log START
        self.log_pipeline_execution('started')

        try:
            # Process data
            result = self.process()

            # Log SUCCESS
            self.log_pipeline_execution('completed')

            # Publish event with correlation_id
            self.publish_event(correlation_id=self.correlation_id)

        except Exception as e:
            # Log FAILURE
            self.log_pipeline_execution('failed', error=e)
            raise

    def log_pipeline_execution(self, status, error=None):
        """Log to central pipeline execution log."""
        log_entry = {
            'execution_id': self.execution_id,
            'source_execution_id': self.opts.get('source_execution_id'),
            'correlation_id': self.correlation_id,
            'phase': self.get_phase_number(),  # 2, 3, 4, etc.
            'processor_name': self.__class__.__name__,
            'event_type': self.get_event_type(),
            'game_date': self.opts.get('game_date'),
            'status': status,
            'started_at': self.started_at,
            'completed_at': datetime.utcnow() if status != 'started' else None,
            'error_type': type(error).__name__ if error else None,
            'error_message': str(error) if error else None,
            'pubsub_message_id': self.opts.get('pubsub_message_id'),
            # ... other fields
        }

        # Insert to BigQuery
        insert_bigquery_rows('nba_orchestration', 'pipeline_execution_log', [log_entry])
```

### Correlation ID: The Key to End-to-End Tracking

**Correlation ID flows through entire pipeline:**

```
Phase 1: Scraper runs
  ├─ Generates: correlation_id = "abc123"
  └─ Publishes: {correlation_id: "abc123", ...}

Phase 2: Processor receives
  ├─ Extracts: correlation_id = "abc123"
  ├─ Logs with: correlation_id = "abc123"
  └─ Publishes: {correlation_id: "abc123", ...}

Phase 3: Processor receives
  ├─ Extracts: correlation_id = "abc123"
  ├─ Logs with: correlation_id = "abc123"
  └─ Publishes: {correlation_id: "abc123", ...}

Phase 4: Processor receives
  ├─ Extracts: correlation_id = "abc123"
  ├─ Logs with: correlation_id = "abc123"
  └─ ❌ FAILS - but logged!

Phase 5: Never receives (waiting for Phase 4)
Phase 6: Never receives (waiting for Phase 5)
```

**Now we can query:**

```sql
-- Track entire pipeline for one correlation_id
SELECT
    phase,
    processor_name,
    status,
    started_at,
    completed_at,
    error_message
FROM nba_orchestration.pipeline_execution_log
WHERE correlation_id = 'abc123'
ORDER BY phase, started_at;

-- Result:
-- phase | processor_name              | status    | error_message
-- ------|----------------------------|-----------|------------------
-- 1     | NbacInjuryReportScraper    | completed | NULL
-- 2     | NbacInjuryReportProcessor  | completed | NULL
-- 3     | PlayerGameSummaryProcessor | completed | NULL
-- 4     | PlayerDailyCacheProcessor  | failed    | Connection timeout
-- (no Phase 5, no Phase 6 - pipeline stalled!)
```

**Answer to Question 3:** ✅ YES, we can detect the change didn't reach Phase 5/6!

---

## Processor Run History Logging

> **Status:** ✅ **IMPLEMENTED** (2025-11-27)

All processor base classes now automatically log runs to `nba_reference.processor_run_history` via `RunHistoryMixin`. This provides comprehensive audit trails for debugging and investigation.

### Overview

Every processor run is automatically logged with:
- **Trigger information:** What caused the run (Pub/Sub, scheduler, manual)
- **Dependency check results:** What dependencies were checked and their status
- **Alert tracking:** Whether an alert was sent and what type
- **Cloud Run metadata:** Service name, revision for deployment correlation
- **Performance metrics:** Duration, records processed, etc.

### Implementation

**Mixin-based approach:**

```python
# All processor base classes now inherit from RunHistoryMixin
class ProcessorBase(RunHistoryMixin):          # Phase 2 Raw
class AnalyticsProcessorBase(RunHistoryMixin): # Phase 3 Analytics
class PrecomputeProcessorBase(RunHistoryMixin): # Phase 4 Precompute
```

**Location:** `shared/processors/mixins/run_history_mixin.py`

### Schema: processor_run_history

**Key columns for debugging:**

| Column | Type | Purpose |
|--------|------|---------|
| `run_id` | STRING | Unique run identifier |
| `processor_name` | STRING | Which processor ran |
| `phase` | STRING | Processing phase (phase_2_raw, phase_3_analytics, etc.) |
| `status` | STRING | success, failed, skipped |
| `trigger_source` | STRING | pubsub, scheduler, manual, api |
| `trigger_message_id` | STRING | Pub/Sub message ID for correlation |
| `parent_processor` | STRING | Upstream processor that triggered this |
| `dependency_check_passed` | BOOLEAN | Did all critical dependencies pass? |
| `missing_dependencies` | JSON | Array of missing table names |
| `stale_dependencies` | JSON | Array of stale table names |
| `alert_sent` | BOOLEAN | Was an alert sent? |
| `alert_type` | STRING | error, warning, info |
| `cloud_run_service` | STRING | K_SERVICE environment variable |
| `cloud_run_revision` | STRING | K_REVISION environment variable |

### Tracing an Alert Back to Its Cause

When you receive an error alert, use the `run_id` to investigate:

```sql
-- Find the failed run by run_id (from alert email)
SELECT
    processor_name,
    phase,
    status,
    trigger_source,
    trigger_message_id,
    parent_processor,
    dependency_check_passed,
    missing_dependencies,
    alert_sent,
    alert_type,
    errors,
    started_at,
    duration_seconds
FROM nba_reference.processor_run_history
WHERE run_id LIKE '%fea26b01%'  -- run_id from alert
ORDER BY started_at DESC;
```

### Finding What Triggered a Failure

```sql
-- Find all runs for a specific date and processor
SELECT
    run_id,
    status,
    trigger_source,
    trigger_message_id,
    dependency_check_passed,
    missing_dependencies,
    started_at
FROM nba_reference.processor_run_history
WHERE processor_name = 'MLFeatureStoreProcessor'
  AND data_date = '2025-11-26'
ORDER BY started_at DESC;
```

### Correlating with Pub/Sub Messages

```sql
-- Find all processors triggered by the same Pub/Sub message
SELECT
    processor_name,
    phase,
    status,
    started_at
FROM nba_reference.processor_run_history
WHERE trigger_message_id = '12345678901234567'
ORDER BY started_at;
```

### Phase 5 Prediction Worker Tracking

Phase 5 uses a separate table (`nba_predictions.prediction_worker_runs`) optimized for per-player prediction tracking. It now includes tracing columns:

| Column | Type | Purpose |
|--------|------|---------|
| `trigger_source` | STRING | What triggered: pubsub, scheduler, manual |
| `trigger_message_id` | STRING | Pub/Sub message ID |
| `cloud_run_service` | STRING | K_SERVICE environment variable |
| `cloud_run_revision` | STRING | K_REVISION environment variable |
| `retry_attempt` | INTEGER | Which retry attempt |
| `batch_id` | STRING | Batch ID for bulk requests |

### See Also

- **Full guide:** `docs/07-monitoring/run-history-guide.md`
- **Mixin implementation:** `shared/processors/mixins/run_history_mixin.py`
- **Schema migration:** `scripts/migrations/add_run_history_columns.py`

---

## Monitoring & Alerting

### Monitor 1: Detect Stuck Pipelines

**Query: Find incomplete pipelines:**

```sql
-- Find pipelines that started but never completed end-to-end
WITH pipeline_phases AS (
    SELECT
        correlation_id,
        game_date,
        MAX(phase) as max_phase_reached,
        COUNTIF(status = 'failed') as failure_count,
        ARRAY_AGG(
            IF(status = 'failed',
               STRUCT(phase, processor_name, error_message),
               NULL)
            IGNORE NULLS
        ) as failures
    FROM nba_orchestration.pipeline_execution_log
    WHERE game_date = CURRENT_DATE('America/New_York')
    GROUP BY correlation_id, game_date
)
SELECT
    correlation_id,
    game_date,
    max_phase_reached,
    failure_count,
    failures
FROM pipeline_phases
WHERE max_phase_reached < 6  -- Didn't reach Phase 6 (publishing)
  OR failure_count > 0
ORDER BY game_date DESC, max_phase_reached ASC
LIMIT 100;
```

**Expected output:**
```
correlation_id | game_date  | max_phase | failures
---------------|------------|-----------|----------
abc123         | 2025-11-15 | 4         | [{phase: 4, processor: "PlayerDailyCacheProcessor", error: "Timeout"}]
```

**Answer to Question 2:** ✅ YES, monitoring can detect what happened!

### Monitor 2: Dead Letter Queue Monitoring

**Query: Check DLQ message count:**

```bash
# Check all DLQs
gcloud pubsub subscriptions describe nba-analytics-complete-dlq-sub \
  --format="value(numUndeliveredMessages)"

# If > 0, alert!
```

**Automated alert:**

```python
def check_dlq_health():
    """Check all DLQs for messages."""
    dlqs = [
        'nba-scraper-complete-dlq-sub',      # Phase 1 → Phase 2
        'nba-raw-data-complete-dlq-sub',     # Phase 2 → Phase 3
        'nba-analytics-complete-dlq-sub',    # Phase 3 → Phase 4
        'nba-precompute-complete-dlq-sub',   # Phase 4 → Phase 5
        'nba-predictions-complete-dlq-sub',  # Phase 5 → Phase 6
    ]

    for dlq in dlqs:
        count = get_dlq_message_count(dlq)
        if count > 0:
            notify_error(
                title=f"🚨 Dead Letter Queue Alert: {dlq}",
                message=f"{count} messages in DLQ - pipeline failures detected",
                details={
                    'dlq': dlq,
                    'message_count': count,
                    'action': 'Investigate failed messages and replay when fixed'
                }
            )
```

### Monitor 3: Phase Completion Latency

**Query: Detect slow phases:**

```sql
-- Average time for each phase to complete
SELECT
    phase,
    processor_name,
    COUNT(*) as executions,
    AVG(duration_seconds) as avg_duration,
    MAX(duration_seconds) as max_duration,
    COUNTIF(status = 'failed') as failures,
    COUNTIF(duration_seconds > 300) as slow_executions  -- > 5 minutes
FROM nba_orchestration.pipeline_execution_log
WHERE game_date = CURRENT_DATE('America/New_York')
  AND status IN ('completed', 'failed')
GROUP BY phase, processor_name
ORDER BY phase, avg_duration DESC;
```

**Alert if:**
- Any phase takes > 10 minutes on average
- Any phase has failure rate > 5%
- Any pipeline takes > 30 minutes end-to-end

### Monitor 4: Entity-Level Tracking

**Query: Track specific entity through pipeline:**

```sql
-- Did LeBron's injury update reach Phase 6?
SELECT
    phase,
    processor_name,
    status,
    started_at,
    duration_seconds,
    JSON_EXTRACT_SCALAR(affected_entities, '$.players[0]') as player_id
FROM nba_orchestration.pipeline_execution_log
WHERE game_date = '2025-11-15'
  AND JSON_EXTRACT_SCALAR(affected_entities, '$.players[0]') = '1630567'  -- LeBron
ORDER BY phase, started_at;
```

**Result shows complete journey:**
```
phase | processor              | status    | player_id
------|------------------------|-----------|----------
1     | NbacInjuryReportScraper| completed | 1630567
2     | NbacInjuryReportProc   | completed | 1630567
3     | PlayerGameSummaryProc  | completed | 1630567
4     | PlayerDailyCacheProc   | failed    | 1630567  ← STUCK HERE
```

### Monitor 5: Grafana Dashboard

**Create comprehensive monitoring dashboard:**

```sql
-- Panel 1: Pipeline Health (Today)
SELECT
    COUNT(DISTINCT correlation_id) as total_pipelines,
    COUNTIF(max_phase >= 6) as completed_pipelines,
    COUNTIF(max_phase < 6) as incomplete_pipelines,
    COUNTIF(has_failures) as failed_pipelines
FROM (
    SELECT
        correlation_id,
        MAX(phase) as max_phase,
        COUNTIF(status = 'failed') > 0 as has_failures
    FROM nba_orchestration.pipeline_execution_log
    WHERE game_date = CURRENT_DATE('America/New_York')
    GROUP BY correlation_id
);

-- Panel 2: Phase-by-Phase Breakdown
SELECT
    phase,
    COUNT(*) as executions,
    COUNTIF(status = 'completed') as successes,
    COUNTIF(status = 'failed') as failures,
    COUNTIF(status = 'skipped') as skipped,
    AVG(duration_seconds) as avg_duration
FROM nba_orchestration.pipeline_execution_log
WHERE game_date = CURRENT_DATE('America/New_York')
GROUP BY phase
ORDER BY phase;

-- Panel 3: Recent Failures
SELECT
    phase,
    processor_name,
    error_type,
    error_message,
    COUNT(*) as occurrence_count,
    MAX(started_at) as last_occurrence
FROM nba_orchestration.pipeline_execution_log
WHERE status = 'failed'
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY phase, processor_name, error_type, error_message
ORDER BY last_occurrence DESC
LIMIT 20;

-- Panel 4: DLQ Message Counts (query via gcloud)
```

### Monitor 6: Dependency Failure Monitoring (NEW)

**Purpose:** Track dependency failures by type, detect patterns, optimize retry logic

#### What to Log (Sprint 1-3 Implementation)

**Enhanced logging in message handler:**

```python
def log_dependency_check_result(dep_check: DependencyCheckResult, processor, retry_count: int):
    """Log dependency check results to pipeline_execution_log."""

    log_entry = {
        'execution_id': str(uuid.uuid4()),
        'correlation_id': processor.correlation_id,
        'phase': processor.get_phase_number(),
        'processor_name': processor.__class__.__name__,
        'status': 'skipped' if dep_check.action.startswith('skip') else 'started',
        'game_date': processor.game_date,

        # NEW: Dependency failure tracking fields
        'dependency_check_result': dep_check.status,
        'dependency_failure_type': dep_check.dependency_type.value,
        'message_acknowledgment': 'ack' if dep_check.action == 'skip_ack' else 'nack',
        'manual_override_used': dep_check.has_override,
        'override_reason': dep_check.override_reason,
        'missing_dependencies': dep_check.missing_deps,
        'retry_count': retry_count,

        'started_at': datetime.utcnow()
    }

    insert_bigquery_rows('nba_orchestration', 'pipeline_execution_log', [log_entry])
```

#### Query 1: Dependency Failure Rate by Type

**Purpose:** Understand which dependency types fail most often

```sql
-- Dependency failure breakdown
SELECT
    phase,
    processor_name,
    dependency_failure_type,
    COUNT(*) as failure_count,
    ROUND(COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY phase, processor_name) * 100, 2) as pct_of_total,
    ARRAY_AGG(DISTINCT missing_dependencies LIMIT 5) as common_missing_deps
FROM nba_orchestration.pipeline_execution_log,
UNNEST(missing_dependencies) as missing_dep
WHERE game_date >= CURRENT_DATE() - 7
  AND dependency_failure_type IS NOT NULL
  AND dependency_failure_type != 'none'
GROUP BY phase, processor_name, dependency_failure_type
ORDER BY failure_count DESC;
```

**Expected output:**
```
phase | processor_name              | failure_type | count | pct   | common_missing_deps
------|----------------------------|--------------|-------|-------|--------------------
3     | PlayerGameSummaryProcessor | same_day     | 150   | 75%   | [bdl_player_boxscores, nbac_play_by_play]
3     | PlayerGameSummaryProcessor | historical   | 45    | 22.5% | [player_rolling_10_game_avg]
3     | PlayerGameSummaryProcessor | optional     | 5     | 2.5%  | [odds_api_player_props]
4     | PlayerDailyCacheProcessor  | same_day     | 80    | 90%   | [player_game_summary]
4     | PlayerDailyCacheProcessor  | historical   | 9     | 10%   | [player_season_stats]
```

**Alert Threshold:** If `historical` failure rate >10%, investigate backfill gaps

#### Query 2: ACK vs NACK Rate

**Purpose:** Ensure we're not over-retrying (too many NACKs) or under-retrying (lost data)

```sql
-- ACK/NACK distribution by processor
SELECT
    phase,
    processor_name,
    message_acknowledgment,
    COUNT(*) as count,
    ROUND(COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY phase, processor_name) * 100, 2) as pct
FROM nba_orchestration.pipeline_execution_log
WHERE game_date >= CURRENT_DATE() - 7
  AND message_acknowledgment IS NOT NULL
GROUP BY phase, processor_name, message_acknowledgment
ORDER BY phase, processor_name, message_acknowledgment;
```

**Expected output:**
```
phase | processor_name              | ack_nack | count | pct
------|----------------------------|----------|-------|------
3     | PlayerGameSummaryProcessor | ack      | 180   | 80%
3     | PlayerGameSummaryProcessor | nack     | 45    | 20%
4     | PlayerDailyCacheProcessor  | ack      | 170   | 95%
4     | PlayerDailyCacheProcessor  | nack     | 9     | 5%
```

**Alert Threshold:**
- 🔴 NACK rate >25% → Too many retries, check if dependencies are broken
- 🟡 NACK rate 10-25% → Monitor closely
- ✅ NACK rate <10% → Healthy

#### Query 3: Most Problematic Dependencies

**Purpose:** Identify which specific dependencies cause the most failures

```sql
-- Dependencies causing most failures
SELECT
    missing_dep,
    COUNT(DISTINCT processor_name) as affected_processors,
    COUNT(*) as total_failures,
    ROUND(AVG(retry_count), 2) as avg_retries,
    MAX(started_at) as latest_failure,
    ARRAY_AGG(DISTINCT processor_name LIMIT 5) as processors
FROM nba_orchestration.pipeline_execution_log,
UNNEST(missing_dependencies) as missing_dep
WHERE game_date >= CURRENT_DATE() - 7
  AND dependency_check_result != 'ready'
GROUP BY missing_dep
ORDER BY total_failures DESC
LIMIT 20;
```

**Expected output:**
```
missing_dep                     | affected_processors | total_failures | avg_retries | processors
-------------------------------|---------------------|----------------|-------------|------------------
bdl_player_boxscores           | 3                   | 250            | 0           | [PlayerGameSummaryProcessor, TeamOffenseProcessor, TeamDefenseProcessor]
player_rolling_10_game_avg     | 1                   | 45             | 2.5         | [PlayerGameSummaryProcessor]
odds_api_player_props          | 2                   | 12             | 0           | [PlayerGameSummaryProcessor, BettingContextProcessor]
```

**Alert Threshold:** If same dependency fails >100 times/week, investigate upstream scraper/processor

#### Query 4: Manual Override Usage

**Purpose:** Track override patterns, detect abuse

```sql
-- Manual override tracking
SELECT
    processor_name,
    COUNT(*) as override_count,
    COUNT(DISTINCT game_date) as dates_affected,
    ARRAY_AGG(DISTINCT override_reason LIMIT 3) as reasons,
    MAX(started_at) as latest_override
FROM nba_orchestration.pipeline_execution_log
WHERE manual_override_used = true
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY processor_name
ORDER BY override_count DESC;
```

**Expected output:**
```
processor_name              | override_count | dates_affected | reasons                          | latest_override
----------------------------|----------------|----------------|----------------------------------|-----------------
PlayerGameSummaryProcessor  | 3              | 3              | ["New deployment", "Backfill..."]| 2025-11-15 14:30
TeamOffenseProcessor        | 1              | 1              | ["Emergency fix"]                | 2025-11-14 10:15
```

**Alert Threshold:**
- 🔴 >5 overrides in 24 hours → Investigate systemic issue
- 🟡 Same processor override >3 days in row → May need permanent fix

#### Grafana Dashboard Panels (Sprint 4)

**Panel 6: Dependency Health Heatmap**

```sql
-- Heatmap showing dependency failure rate by processor
SELECT
    processor_name,
    dependency_failure_type,
    COUNT(*) as failures,
    ROUND(COUNT(*) / NULLIF((
        SELECT COUNT(*)
        FROM nba_orchestration.pipeline_execution_log sub
        WHERE sub.processor_name = main.processor_name
          AND sub.game_date >= CURRENT_DATE() - 1
    ), 0) * 100, 2) as failure_rate_pct
FROM nba_orchestration.pipeline_execution_log main
WHERE game_date >= CURRENT_DATE() - 1
  AND dependency_failure_type IS NOT NULL
  AND dependency_failure_type != 'none'
GROUP BY processor_name, dependency_failure_type
ORDER BY failure_rate_pct DESC;
```

**Visualization:** Heatmap with processor_name on Y-axis, dependency_failure_type on X-axis, color intensity = failure_rate_pct

**Panel 7: ACK/NACK Ratio Trend**

```sql
-- ACK/NACK ratio over time (hourly)
SELECT
    TIMESTAMP_TRUNC(started_at, HOUR) as hour,
    message_acknowledgment,
    COUNT(*) as count
FROM nba_orchestration.pipeline_execution_log
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND message_acknowledgment IS NOT NULL
GROUP BY hour, message_acknowledgment
ORDER BY hour DESC;
```

**Visualization:** Stacked bar chart showing ACK vs NACK over time

**Panel 8: Historical Dependency Failure Trend**

```sql
-- Historical dependency failures over time
SELECT
    DATE(started_at) as date,
    COUNT(*) as historical_dep_failures,
    COUNT(DISTINCT processor_name) as affected_processors,
    COUNT(DISTINCT correlation_id) as affected_pipelines
FROM nba_orchestration.pipeline_execution_log
WHERE dependency_failure_type = 'historical'
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY date
ORDER BY date DESC;
```

**Visualization:** Line chart showing historical dependency failures trend

#### Alert Configuration (Sprint 4)

**Alert 1: High NACK Rate**

```yaml
name: "High NACK Rate - {processor_name}"
query: |
  SELECT
    processor_name,
    COUNTIF(message_acknowledgment = 'nack') / COUNT(*) * 100 as nack_rate
  FROM nba_orchestration.pipeline_execution_log
  WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
    AND message_acknowledgment IS NOT NULL
  GROUP BY processor_name
condition: nack_rate > 10
severity: warning
message: |
  {{processor_name}} has {{nack_rate}}% NACK rate (returning 500).
  Check if historical dependencies need backfill or if there's a systemic issue.
```

**Alert 2: Same-Day Dependency Never Arriving**

```yaml
name: "Same-Day Dependency Stuck - {missing_dep}"
query: |
  SELECT
    missing_dep,
    COUNT(DISTINCT processor_name) as blocked_processors,
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MIN(started_at), HOUR) as hours_stuck
  FROM nba_orchestration.pipeline_execution_log,
  UNNEST(missing_dependencies) as missing_dep
  WHERE dependency_failure_type = 'same_day'
    AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
  GROUP BY missing_dep
condition: hours_stuck > 2
severity: critical
message: |
  Dependency {{missing_dep}} has been missing for {{hours_stuck}} hours.
  Blocking {{blocked_processors}} processors.
  Check if upstream scraper/processor failed.
```

**Alert 3: Manual Override Overuse**

```yaml
name: "Excessive Manual Overrides"
query: |
  SELECT COUNT(*) as override_count
  FROM nba_orchestration.pipeline_execution_log
  WHERE manual_override_used = true
    AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
condition: override_count > 5
severity: warning
message: |
  {{override_count}} manual overrides used in past 24 hours.
  Investigate if systemic backfill needed instead of repeated overrides.
```

**Alert 4: Historical Dependency Backlog**

```yaml
name: "Historical Dependency Backlog Growing"
query: |
  SELECT
    processor_name,
    COUNT(*) as historical_failures
  FROM nba_orchestration.pipeline_execution_log
  WHERE dependency_failure_type = 'historical'
    AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR)
  GROUP BY processor_name
condition: historical_failures > 10
severity: warning
message: |
  {{processor_name}} has {{historical_failures}} historical dependency failures in past 6 hours.
  Run backfill to resolve: python backfill_analytics.py --processor={{processor_name}}
```

#### Monitoring Best Practices

**Daily Health Check:**
```bash
# Run daily health check script
bin/orchestration/check_dependency_health.sh

# Checks:
# 1. NACK rate < 10% for all processors
# 2. No same-day deps stuck > 2 hours
# 3. Historical dep failures < 5/day per processor
# 4. Manual override count < 3/day
```

**Weekly Review:**
```sql
-- Weekly dependency health report
SELECT
    processor_name,
    COUNTIF(dependency_failure_type = 'same_day') as same_day_failures,
    COUNTIF(dependency_failure_type = 'historical') as historical_failures,
    COUNTIF(dependency_failure_type = 'optional') as optional_failures,
    COUNTIF(manual_override_used) as override_count,
    ROUND(AVG(retry_count), 2) as avg_retries
FROM nba_orchestration.pipeline_execution_log
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY processor_name
ORDER BY historical_failures DESC;
```

**Action Items from Monitoring:**
- Same-day failures >100/week → Check if upstream processor publishing correctly
- Historical failures >10/week → Schedule backfill
- Optional failures >50/week → Investigate if data source unreliable
- Override count >5/week → Consider permanent fix vs repeated overrides

---

## Recovery Procedures

### Scenario 1: Transient Error (Connection Timeout)

**Problem:** Phase 4 processor failed due to temporary BigQuery timeout

**Detection:**
1. DLQ receives message after 5 retries
2. Alert fires: "🚨 DLQ has 1 message"
3. Query shows: Phase 4 failed with "Connection timeout"

**Recovery:**

```bash
# 1. Check DLQ
gcloud pubsub subscriptions describe nba-analytics-complete-dlq-sub

# 2. Verify issue is fixed (BigQuery is responsive)
bq query "SELECT 1"  # Quick health check

# 3. Replay DLQ messages
gcloud pubsub subscriptions pull nba-analytics-complete-dlq-sub \
  --limit=10 \
  --auto-ack=false

# 4. Manually republish to main topic
gcloud pubsub topics publish nba-analytics-complete \
  --message='{...message data from DLQ...}'

# 5. Verify processing
# Check pipeline_execution_log for new execution
```

**Automated recovery (future):**

```python
def auto_replay_dlq():
    """Automatically replay DLQ if issue is resolved."""

    # Check if system is healthy
    if not check_system_health():
        return

    # Pull messages from DLQ
    messages = pull_dlq_messages(limit=100, auto_ack=False)

    for message in messages:
        try:
            # Republish to main topic
            republish_message(message)
            # Acknowledge in DLQ
            message.ack()
        except Exception as e:
            # Don't ack - will retry later
            logger.error(f"Failed to replay: {e}")
```

### Scenario 2: Code Bug in Phase 4

**Problem:** Phase 4 processor has a bug causing all messages to fail

**Detection:**
1. DLQ accumulates many messages
2. Alert: "🚨 DLQ has 50 messages" (escalating)
3. Query shows: Same error repeated 50 times

**Recovery:**

```bash
# 1. Identify the bug
# Check error messages in pipeline_execution_log
bq query "
SELECT error_message, COUNT(*) as count
FROM nba_orchestration.pipeline_execution_log
WHERE phase = 4 AND status = 'failed'
  AND game_date = CURRENT_DATE()
GROUP BY error_message
"

# 2. Fix the bug in code
# ... deploy fixed version ...

# 3. Verify fix works with one message
gcloud pubsub subscriptions pull nba-analytics-complete-dlq-sub \
  --limit=1 \
  --auto-ack=false

# Test manually, then ack if successful

# 4. Replay all DLQ messages
# ... bulk replay script ...
```

### Scenario 3: Data Quality Issue

**Problem:** Phase 3 completes but produces bad data, Phase 4 detects and rejects it

**Detection:**
1. Phase 4 logs: "Validation failed - missing required fields"
2. Pipeline execution log shows: Phase 4 status='failed', error='ValidationError'

**Recovery:**

```bash
# 1. Identify root cause
# Check what Phase 3 produced
bq query "
SELECT *
FROM nba_analytics.player_game_summary
WHERE game_date = '2025-11-15'
  AND universal_player_id = '1630567'
"

# 2. If Phase 3 data is bad, need to re-run Phase 3
# Find the correlation_id
SELECT correlation_id
FROM nba_orchestration.pipeline_execution_log
WHERE phase = 3
  AND game_date = '2025-11-15'
  AND JSON_EXTRACT(affected_entities, '$.players[0]') = '1630567'

# 3. Manually trigger Phase 3 re-processing
curl -X POST https://nba-analytics-processors-.../process \
  -H "Content-Type: application/json" \
  -d '{
    "game_date": "2025-11-15",
    "player_ids": ["1630567"],
    "force_refresh": true  # Bypass idempotency
  }'

# 4. Monitor Phase 3 → Phase 4 → Phase 5 → Phase 6 flow
```

### Scenario 4: Complete Pipeline Replay

**Problem:** Need to replay entire pipeline for a game_date

**Recovery:**

```python
def replay_pipeline_for_date(game_date: str, start_phase: int = 2):
    """
    Replay pipeline starting from specified phase.

    Args:
        game_date: Date to replay (YYYY-MM-DD)
        start_phase: Which phase to start from (2-6)
    """

    # Get all correlation_ids for this date
    query = f"""
    SELECT DISTINCT correlation_id
    FROM nba_orchestration.pipeline_execution_log
    WHERE game_date = '{game_date}'
      AND phase < {start_phase}
    """
    correlation_ids = execute_query(query)

    # For each correlation_id, trigger from start_phase
    for corr_id in correlation_ids:
        # Get context from pipeline log
        context = get_pipeline_context(corr_id, start_phase - 1)

        # Trigger processor
        trigger_processor(
            phase=start_phase,
            game_date=game_date,
            correlation_id=corr_id,
            affected_entities=context['affected_entities'],
            force_refresh=True
        )

        logger.info(f"Triggered Phase {start_phase} replay for {corr_id}")
```

---

## Implementation Timeline

**For complete prioritized implementation roadmap**, see [05-implementation-status-and-roadmap.md](./05-implementation-status-and-roadmap.md).

### Monitoring-Related Sprints

**Sprint 2 (Week 1-2):** Correlation ID & Unified Logging (~8 hrs)
- Create `pipeline_execution_log` table
- Implement correlation_id propagation
- Add logging to all processor base classes

**Sprint 4 (Week 3):** Monitoring Dashboards (~8 hrs)
- Create Grafana dashboard with pipeline health panels
- Set up DLQ, stuck pipeline, and failure rate alerts

**Sprint 5 (Week 3-4):** DLQ Recovery Automation (~8 hrs)
- Create DLQ replay scripts
- Document recovery procedures

**Operational monitoring** (existing): See `docs/monitoring/01-grafana-monitoring-guide.md` for current Phase 1 health checks

---

## Summary: Answers to Your Questions

### ✅ Question 1: "Will that message be there for it to retry later?"

**YES!**
- Pub/Sub retries automatically (5 attempts with exponential backoff)
- Failed messages move to Dead Letter Queue
- DLQ retains messages for 7 days
- Can manually replay when issue is fixed

### ✅ Question 2: "Will there be a way for the monitor to know what happened?"

**YES!**
- `pipeline_execution_log` tracks every execution across all phases
- Each processor logs status: started → completed/failed
- Error details captured (error_type, error_message)
- DLQ monitoring alerts on failures
- Grafana dashboard shows real-time health

### ✅ Question 3: "Will we know the change in phase 2 did not go all the way to phase 5 or phase 6?"

**YES!**
- `correlation_id` links entire pipeline run
- Query by correlation_id shows which phases completed
- Monitoring detects "stuck pipelines" (max_phase < 6)
- Can track specific entities (e.g., LeBron) through all phases
- Alert fires if pipeline doesn't reach Phase 6 within threshold time

### The Complete Picture

```
Injury update happens
    ↓
Every phase logs execution
    ↓
correlation_id flows through pipeline
    ↓
Phase 4 fails → logged → retries → DLQ
    ↓
Monitor detects:
  - DLQ has messages (immediate alert)
  - Pipeline stuck at Phase 4 (correlation_id query)
  - LeBron's update didn't reach Phase 6 (entity tracking)
    ↓
Recovery:
  - Fix issue (bug/timeout)
  - Replay DLQ messages
  - Verify end-to-end completion
    ↓
System resumes normal operation
```

**All three questions answered with robust, production-ready monitoring!**

---

## Document Summary

This document provides a **complete end-to-end monitoring and error handling strategy** for the NBA data pipeline, covering:

### What We Designed

**1. Message Acknowledgment Strategy (Section 3)**
- ACK vs NACK decision logic for Pub/Sub messages
- 3 dependency types: Same-Day, Historical, Optional
- Complete decision tree for message handling
- Production-ready message handler implementation

**2. Dependency Failure Scenarios (Section 4)**
- 6 detailed scenarios with detection and recovery procedures
- Circular dependency detection
- Data quality validation
- Partial backfill handling

**3. Enhanced Dependency Checking (Section 5)**
- `DependencyCheckResult` class design
- `DependencyType` enum for classification
- Manual override mechanism with approval workflow
- Complete implementation examples

**4. End-to-End Pipeline Tracking (Section 6)**
- Enhanced `pipeline_execution_log` schema with dependency failure fields
- Correlation ID propagation across all 6 phases
- Complete pipeline tracking from Phase 1 → Phase 6

**5. Comprehensive Monitoring (Section 7)**
- 6 monitoring queries covering all failure types
- 4 Grafana dashboard panels (dependency health, ACK/NACK ratio, trends)
- 4 automated alerts with clear thresholds
- Daily/weekly health check procedures

**6. Recovery Procedures (Section 8)**
- 4 recovery scenarios with step-by-step procedures
- DLQ replay automation
- Manual override workflow
- Complete pipeline replay

### Implementation Timeline

**Sprint 1-3: Core Implementation**
- Add dependency failure fields to `pipeline_execution_log`
- Implement `DependencyCheckResult` class and enhanced `check_dependencies()`
- Create `processing_overrides` table
- Enhanced message handler with ACK/NACK logic
- Logging hooks for dependency checks

**Sprint 4: Monitoring & Alerts**
- Build Grafana dashboard (8 panels total)
- Configure 4 automated alerts
- Create daily health check script
- Set up DLQ monitoring

**Sprint 5: Automation**
- DLQ replay automation
- Manual override management scripts
- Complete pipeline replay tool

### Key Metrics to Watch

**Health Indicators:**
- ✅ NACK rate <10% (optimal retry behavior)
- ✅ Same-day deps resolve within 1 hour
- ✅ Historical deps <5 failures/week per processor
- ✅ Manual overrides <3/week

**Red Flags:**
- 🔴 NACK rate >25% (over-retrying)
- 🔴 Same-day dep stuck >2 hours (upstream failure)
- 🔴 >5 manual overrides/24hr (systemic issue)
- 🔴 Same dependency blocking multiple processors (circular dep)

### Production Readiness

This design is **ready for production implementation** because:

1. **Comprehensive:** Covers all failure scenarios (same-day, historical, optional, circular, validation, partial)
2. **Actionable:** Every scenario has clear detection and recovery procedures
3. **Observable:** Full monitoring with metrics, dashboards, and alerts
4. **Maintainable:** Manual override mechanism for emergency bypasses
5. **Self-healing:** Opportunistic triggering for same-day dependencies
6. **Validated:** Decision tree ensures correct ACK/NACK behavior

### Next Steps

1. **Review & Approve:** Team reviews this design, provides feedback
2. **Schema Migration:** Add new fields to `pipeline_execution_log`, create `processing_overrides` table
3. **Core Implementation (Sprint 1-3):** Implement enhanced dependency checking and logging
4. **Monitoring Setup (Sprint 4):** Build dashboards and configure alerts
5. **Operations Training:** Train ops team on monitoring and recovery procedures

---

**Last Updated:** 2025-11-15 (Major expansion: ACK/NACK strategy, dependency failure handling, comprehensive monitoring)
**Status:** ✅ Design Complete - Ready for Sprint 1-4 Implementation
**Document Size:** ~2,100 lines covering all error handling and monitoring scenarios
