# Phase 5 Scheduling Strategy

**File:** `docs/processors/10-phase5-scheduling-strategy.md`
**Created:** 2025-11-09 14:45 PST
**Last Updated:** 2025-11-15 17:00 PST
**Purpose:** Cloud Scheduler configuration and dependency management for Phase 5
**Status:** Draft (awaiting deployment)

---

## 📋 Table of Contents

1. [Cloud Scheduler Configuration](#cloud-scheduler)
2. [Dependency Management Strategy](#dependency-management)
3. [Worker Auto-Scaling](#auto-scaling)
4. [Integration with Phase 6](#phase6-integration)
5. [Retry Strategy](#retry-strategy)
6. [Line Generation Modes](#line-generation)
7. [Related Documentation](#related-docs)

---

## ⏰ Cloud Scheduler Configuration {#cloud-scheduler}

### Primary Trigger (6:15 AM ET)

**Job Name:** `phase5-daily-predictions-trigger`

**Schedule:** `15 6 * * *` (6:15 AM daily)

**Timezone:** America/New_York

**Target:** HTTP POST to Coordinator Cloud Run service

**Payload:**
```json
{
  "processor": "prediction_coordinator",
  "phase": "5",
  "trigger_time": "{{TIMESTAMP}}",
  "game_date": "{{TODAY}}",
  "source": "cloud-scheduler"
}
```

### Creating the Job

```bash
gcloud scheduler jobs create http phase5-daily-predictions-trigger \
  --schedule "15 6 * * *" \
  --time-zone "America/New_York" \
  --location us-central1 \
  --uri "https://prediction-coordinator-xxx.run.app/start-daily-predictions" \
  --http-method POST \
  --headers "Content-Type=application/json" \
  --message-body '{"processor":"prediction_coordinator","phase":"5","trigger_time":"{{TIMESTAMP}}","game_date":"{{TODAY}}","source":"cloud-scheduler"}' \
  --oidc-service-account-email prediction-coordinator@nba-props-platform.iam.gserviceaccount.com \
  --oidc-token-audience https://prediction-coordinator-xxx.run.app
```

### Manual Trigger Commands

**Trigger via Cloud Scheduler:**
```bash
# Manual trigger via gcloud (for testing or recovery)
gcloud scheduler jobs run phase5-daily-predictions-trigger \
  --location us-central1
```

**Trigger via HTTP:**
```bash
# Manual trigger via curl (with auth)
curl -X POST https://prediction-coordinator-xxx.run.app/start-daily-predictions \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-11-07"}'
```

---

## 🔗 Dependency Management Strategy {#dependency-management}

### Strategy: Hybrid Approach

Phase 5 uses a combination of:
- **Explicit validation** - Coordinator checks Phase 4 completion log
- **Data validation** - Coordinator queries `ml_feature_store_v2` table
- **Wait logic** - Coordinator waits up to 15 minutes if Phase 4 late

This ensures Phase 5 only runs when Phase 4 features are actually ready.

### Phase 4 Completion Check

**Step 1: Check Completion Log (Fast)**

```python
def check_phase4_completion_log(game_date: str) -> bool:
    """
    Check if Phase 4 marked complete in completion log.
    """
    query = """
    SELECT status
    FROM `nba_analytics.phase_completion_log`
    WHERE game_date = @game_date
      AND phase_name = 'phase4'
      AND processor_name IS NULL  -- Phase-level completion
      AND status = 'completed'
    LIMIT 1
    """

    results = list(bq_client.query(query, params={'game_date': game_date}).result())
    return len(results) > 0
```

**Step 2: Validate Feature Data (Thorough)**

```python
def validate_phase4_features(game_date: str) -> tuple[bool, str]:
    """
    Validate that ml_feature_store_v2 has quality features.

    Checks:
    - Player count >= 400
    - Average quality >= 70
    - Minimum quality >= 60
    """
    query = """
    SELECT
      COUNT(*) as player_count,
      AVG(feature_quality_score) as avg_quality,
      MIN(feature_quality_score) as min_quality
    FROM `nba_predictions.ml_feature_store_v2`
    WHERE game_date = @game_date
      AND feature_version = 'v1_baseline_25'
    """

    results = list(bq_client.query(query, params={'game_date': game_date}).result())

    if len(results) == 0:
        return (False, "No features found")

    row = results[0]

    if row.player_count < 400:
        return (False, f"Only {row.player_count} players (need 400+)")

    if row.avg_quality < 70:
        return (False, f"Avg quality {row.avg_quality} too low (need 70+)")

    if row.min_quality < 60:
        return (False, f"Min quality {row.min_quality} too low (need 60+)")

    return (True, f"Features validated: {row.player_count} players, quality {row.avg_quality:.1f}")
```

**Step 3: Combined Check**

```python
def check_dependencies(game_date: str) -> tuple[bool, str]:
    """
    Hybrid check: Completion log + data validation.
    """
    # Check 1: Completion log (fast)
    log_complete = check_phase4_completion_log(game_date)

    if not log_complete:
        return (False, "Phase 4 not marked complete in log")

    # Check 2: Validate actual data (thorough)
    data_valid, reason = validate_phase4_features(game_date)

    if not data_valid:
        return (False, f"Phase 4 marked complete but validation failed: {reason}")

    return (True, "Phase 4 complete and validated")
```

### Wait Logic

**If Phase 4 Not Ready (Wait Up to 15 Minutes):**

```python
def wait_for_phase4(game_date: str, timeout_minutes: int = 15) -> bool:
    """
    Wait for Phase 4 to complete (poll every 1 minute).

    Why 15 minutes?
    - Phase 4 runs 11:00 PM - 12:15 AM (75 min)
    - If Phase 4 runs late to 12:30 AM, still OK
    - Phase 5 at 6:15 AM has 15 min buffer
    """
    start_time = time.time()
    check_interval_seconds = 60  # 1 minute

    while time.time() - start_time < timeout_minutes * 60:
        elapsed = time.time() - start_time
        logger.info(f"Waiting for Phase 4... ({elapsed:.0f}s elapsed)")

        ready, reason = check_dependencies(game_date)

        if ready:
            logger.info(f"Phase 4 ready (waited {elapsed:.0f}s)")
            return True

        logger.info(f"Not ready: {reason}")
        time.sleep(check_interval_seconds)

    logger.error(f"Phase 4 not ready within {timeout_minutes} minutes")
    return False
```

### Startup Flow

**Normal Flow (Phase 4 Ready):**

```
┌─────────────────────────────────────────────────────────────┐
│  COORDINATOR STARTUP (6:15 AM)                              │
└─────────────────────────────────────────────────────────────┘

6:15:00 - Cloud Scheduler triggers coordinator
6:15:05 - Coordinator starts, checks dependencies
          ├─ Check completion log (5 sec)
          ├─ Validate feature data (5 sec)
          └─ Result: Phase 4 READY ✓

6:15:10 - Query players with games today (10 sec)
6:15:20 - Query opening prop lines (10 sec)
6:15:30 - Calculate line spreads (5 sec)
6:15:35 - Fan out: Publish 450 messages (30 sec)
6:16:05 - Coordinator complete
```

**Alternative Flow (Phase 4 Late):**

```
6:15:00 - Cloud Scheduler triggers coordinator
6:15:05 - Check dependencies: Phase 4 NOT READY ✗
6:15:05 - Enter wait loop (max 15 min)
          ├─ Check every 1 minute
          ├─ 6:16:05 - Still not ready
          ├─ 6:17:05 - Still not ready
          └─ 6:18:05 - Phase 4 READY ✓ (waited 3 min)

6:18:05 - Proceed with normal flow
6:18:15 - Query players
6:18:25 - Query lines
6:18:35 - Fan out
6:19:05 - Coordinator complete
```

---

## 📈 Worker Auto-Scaling {#auto-scaling}

### Scaling Behavior

**Worker Auto-Scaling (based on Pub/Sub queue depth):**

| Time    | Queue Depth | Instances Active | Concurrent Capacity | Processing Status |
|---------|-------------|------------------|---------------------|-------------------|
| 6:15:00 | 0           | 0                | 0                   | Idle              |
| 6:16:00 | 450         | 0 → 5            | 25                  | Cold start        |
| 6:16:30 | 425         | 5 → 10           | 50                  | Warming up        |
| 6:17:00 | 350         | 10 → 20          | 100                 | Full capacity     |
| 6:17:30 | 250         | 20               | 100                 | Processing        |
| 6:18:00 | 150         | 20               | 100                 | Processing        |
| 6:18:30 | 50          | 20               | 100                 | Processing        |
| 6:19:00 | 0           | 20 → 5           | 25                  | Scaling down      |
| 6:19:30 | 0           | 5 → 1            | 5                   | Minimum (prod)    |
| 6:20:00 | 0           | 1 → 0            | 0                   | Idle (dev)        |

### Scaling Formula

```
Target Instances = CEIL(Queue Depth / (concurrency × target_utilization))
                 = CEIL(Queue Depth / (5 × 0.8))
                 = CEIL(Queue Depth / 4)

Examples:
- Queue depth 450 → CEIL(450/4) = 113 instances (capped at 20)
- Queue depth 100 → CEIL(100/4) = 25 instances (capped at 20)
- Queue depth 20 → CEIL(20/4) = 5 instances
- Queue depth 0 → 0 instances (or 1 if min-instances=1)
```

### Threading Architecture

**Worker Instance (5 concurrent threads):**

```
┌────────────────────────────────────────────────────────┐
│  WORKER INSTANCE                                       │
│                                                        │
│  Main Process:                                         │
│    ├─ Thread 1: Process player A (10s)                │
│    ├─ Thread 2: Process player B (10s)                │
│    ├─ Thread 3: Process player C (10s)                │
│    ├─ Thread 4: Process player D (10s)                │
│    └─ Thread 5: Process player E (10s)                │
│                                                        │
│  Total Concurrency: 5 players simultaneously          │
└────────────────────────────────────────────────────────┘

Total System Concurrency: 20 workers × 5 threads = 100 players
```

### Concurrency Tuning

**Current: concurrency=5** (handles 5 concurrent requests)

**Why 5?**
- Typical request: ~200-300ms
- 5 concurrent = 1 request completes every 40-60ms
- Good throughput without overwhelming single instance

**What if we increase to 10?**

Pros:
- 2x more concurrent processing per instance
- Fewer instances needed (10 instead of 20)
- Lower cold start impact (fewer instances to start)

Cons:
- Higher memory per instance (more requests in-flight)
- Higher CPU contention (10 threads on 2 vCPUs)
- Risk of request timeouts (less CPU per request)

**Recommendation:** Keep concurrency=5 for v1.0. Test with 10 if latency improves.

---

## 🔗 Integration with Phase 6 {#phase6-integration}

### Phase 5 → Phase 6 Handoff

```
6:18 AM ┌─────────────────────────────────┐
        │ Workers complete predictions    │
        └─────────────────────────────────┘
             ↓ (publishes: prediction-ready per player)

6:18:30 ┌─────────────────────────────────┐
        │ Coordinator receives all        │
        │ completion events (450/450)     │
        │ Publishes: batch-complete       │
        └─────────────────────────────────┘
             ↓

6:19 AM ┌─────────────────────────────────┐
        │ Phase 6 Publisher               │
        │ Listens for batch-complete      │
        │ Queries BigQuery for predictions│
        └─────────────────────────────────┘
             ↓

6:20 AM ┌─────────────────────────────────┐
        │ Generate website JSON files     │
        │ - Player prediction pages       │
        │ - Daily recommendations         │
        │ - System comparison reports     │
        └─────────────────────────────────┘
             ↓

6:22 AM ┌─────────────────────────────────┐
        │ Upload to Cloud Storage/CDN     │
        │ Website updated with new data   │
        └─────────────────────────────────┘
```

### Pub/Sub Events

**Event 1: prediction-ready (Worker → Coordinator)**

```json
{
  "player_lookup": "lebron-james",
  "game_date": "2025-11-08",
  "predictions_generated": 5,
  "timestamp": "2025-11-08T06:18:15.123Z",
  "worker_instance": "prediction-worker-xk8sh"
}
```

**Event 2: prediction-batch-complete (Coordinator → Phase 6)**

```json
{
  "batch_id": "batch_2025-11-08_1731052500",
  "game_date": "2025-11-08",
  "total_players": 450,
  "completed_players": 450,
  "failed_players": 0,
  "total_predictions": 2250,
  "duration_seconds": 142,
  "success_rate": 100.0,
  "timestamp": "2025-11-08T06:18:30.456Z"
}
```

### Phase 6 Readiness Check

Before publishing (6:19 AM), Phase 6 verifies predictions are complete:

```sql
-- Phase 6 Pre-Flight Check
WITH prediction_counts AS (
  SELECT
    COUNT(DISTINCT player_lookup) as players_with_predictions,
    COUNT(DISTINCT CASE WHEN system_id = 'ensemble_v1' THEN player_lookup END) as ensemble_count,
    COUNT(*) as total_predictions,
    COUNT(DISTINCT system_id) as systems_running,
    MIN(created_at) as first_prediction,
    MAX(created_at) as last_prediction
  FROM `nba_predictions.player_prop_predictions`
  WHERE game_date = CURRENT_DATE()
)
SELECT
  players_with_predictions,
  ensemble_count,
  total_predictions,
  systems_running,
  TIMESTAMP_DIFF(last_prediction, first_prediction, SECOND) as processing_duration_seconds
FROM prediction_counts
```

**Expected Results:**
- `players_with_predictions`: 450
- `ensemble_count`: 450 (ensemble is critical)
- `total_predictions`: 2,250 (single line) or 11,250 (multi-line)
- `systems_running`: 5
- `processing_duration_seconds`: 120-180 (2-3 minutes)

### If Incomplete (<90% players)

```python
# Phase 6 waits 2 minutes
time.sleep(120)

# Re-check
results = check_predictions_complete()

if results['completeness'] < 90%:
    # Publish with partial data + alert
    logger.critical("Predictions incomplete after wait period")
    send_alert("#nba-props-critical", "Phase 5 predictions incomplete")
    publish_partial_predictions()
else:
    # All good
    publish_complete_predictions()
```

---

## 🔄 Retry Strategy {#retry-strategy}

### Three Levels of Retries

**Level 1: Cloud Run Job Retries (Coordinator)**

```bash
--max-retries 2  # Coordinator retries 2 times (3 total attempts)
```

Coordinator Failure → Retry:
```
Attempt 1: 6:15 AM (fails)
Attempt 2: 6:16 AM (retry 1)
Attempt 3: 6:17 AM (retry 2)
If all fail: Alert CRITICAL
```

**Level 2: Pub/Sub Message Retries (Workers)**

```bash
--max-delivery-attempts 3  # Workers retry each message 3 times
```

Worker Failure → Pub/Sub Retry:
```
Attempt 1: Worker instance A (fails)
Attempt 2: Worker instance B (retry 1, after 10s)
Attempt 3: Worker instance C (retry 2, after 30s)
If all fail: Move to DLQ
```

**Level 3: Application-Level Retries (Per-System)**

```python
def predict_with_retry(system, features, max_retries=2):
    """
    Retry individual prediction system if fails.
    """
    for attempt in range(max_retries + 1):
        try:
            return system.predict(features)
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"System {system.id} failed (attempt {attempt+1}), retrying...")
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                logger.error(f"System {system.id} failed after {max_retries+1} attempts")
                return None  # Graceful degradation
```

### Retry Decision Matrix

| Failure Type | Retry? | Strategy |
|--------------|--------|----------|
| Coordinator crash | ✅ Yes | Cloud Run job retries (2×) |
| Worker crash | ✅ Yes | Pub/Sub redelivery (3×) |
| Worker timeout | ✅ Yes | Pub/Sub redelivery (3×) |
| Feature not found | ❌ No | Skip player, alert |
| Invalid prediction | ❌ No | Log error, continue |
| System bug | ❌ No | Fail fast, rollback |

---

## 📊 Line Generation Modes {#line-generation}

### Configuration

**Default Mode: Single Line (Production)**

```json
{
    "game_date": "2025-11-08",
    "use_multiple_lines": false  // Default
}
```

Coordinator generates:
```python
line_values = [25.5]  # Just the opening line
```

Worker generates:
```
450 players × 1 line × 5 systems = 2,250 predictions total
```

**Testing Mode: Multiple Lines (5 lines per player)**

```json
{
    "game_date": "2025-11-08",
    "use_multiple_lines": true
}
```

Coordinator generates:
```python
line_values = [23.5, 24.5, 25.5, 26.5, 27.5]  # Opening ± 2
```

Worker generates:
```
450 players × 5 lines × 5 systems = 11,250 predictions total
```

### Line Generation Algorithm

**Strategy:**
1. Try actual line from `odds_player_props` (Phase 2)
2. Fallback: Estimate from season average
3. Generate ±2 if `use_multiple_lines=True`

```python
def _get_betting_lines(
    self,
    player_lookup: str,
    game_date: date,
    use_multiple_lines: bool
) -> List[float]:
    """
    Get betting lines for player
    """
    # Step 1: Try actual betting line
    actual_line = self._query_actual_betting_line(player_lookup, game_date)

    if actual_line is not None:
        base_line = actual_line
    else:
        # Step 2: Fallback to estimated line
        base_line = self._estimate_betting_line(player_lookup)

    # Step 3: Generate multiple lines if requested
    if use_multiple_lines:
        lines = [
            round(base_line - 2.0, 1),
            round(base_line - 1.0, 1),
            round(base_line, 1),
            round(base_line + 1.0, 1),
            round(base_line + 2.0, 1)
        ]
    else:
        lines = [round(base_line, 1)]

    return lines
```

### Examples

**Player with actual line (LeBron James):**
```
Opening line: 25.5 points
Single mode: [25.5]
Multi mode: [23.5, 24.5, 25.5, 26.5, 27.5]
```

**Player with estimated line (Rookie):**
```
Season average: 12.3 points
Rounded: 12.5 points (nearest 0.5)
Single mode: [12.5]
Multi mode: [10.5, 11.5, 12.5, 13.5, 14.5]
```

**Edge case: Low scorer:**
```
Season average: 5.8 points
Rounded: 6.0 points
Single mode: [6.0]
Multi mode: [4.0, 5.0, 6.0, 7.0, 8.0]
```

### Processing Impact

| Mode | Players | Lines | Systems | Total Predictions | Processing Time |
|------|---------|-------|---------|-------------------|-----------------|
| Single (prod) | 450 | 1 | 5 | 2,250 | 2-3 min |
| Multi (test) | 450 | 5 | 5 | 11,250 | 8-12 min |

### When to Use

- **Production:** Single line (default)
- **Development:** Multi-line for testing
- **Reporting:** Multi-line for comprehensive reports
- **Backtesting:** Multi-line for line range analysis

### Why Multi-Line Mode?

1. **Backtesting** - Test system performance across line ranges
2. **Line Movement Analysis** - See how predictions change with line
3. **Report Generation** - Show predictions at multiple lines (Phase 6 use case)
4. **Sensitivity Testing** - Understand recommendation stability

---

## 🔗 Related Documentation {#related-docs}

**Phase 5 Docs:**
- **Operations Guide:** `09-phase5-operations-guide.md` - Coordinator/worker configuration, Pub/Sub topics
- **Troubleshooting:** `11-phase5-troubleshooting.md` - Failure scenarios, incident response
- **Worker Deep-Dive:** `12-phase5-worker-deepdive.md` - Model loading, concurrency, performance

**Upstream Dependencies:**
- **Phase 4:** `05-phase4-operations-guide.md` - Feature generation (ml_feature_store_v2)
- **Phase 3:** `02-phase3-operations-guide.md` - Upcoming player game context
- **Phase 2:** `01-phase2-operations-guide.md` - Prop lines from scrapers

**Infrastructure:**
- **Pub/Sub:** `docs/01-architecture/orchestration/pubsub-topics.md` - Event infrastructure
- **Architecture:** `docs/01-architecture/pipeline-design.md` - Overall pipeline

---

**Last Updated:** 2025-11-15 17:00 PST
**Next Review:** After Phase 5 deployment
**Status:** Draft - Ready for implementation review
