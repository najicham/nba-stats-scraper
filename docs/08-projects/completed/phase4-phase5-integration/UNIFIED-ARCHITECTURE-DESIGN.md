# Unified Event-Driven Architecture - Complete Design Specification

**Status:** 📐 Design Review
**Scope:** Complete pipeline redesign (Phases 1-5)
**Approach:** Meticulous, ultrathought, no rush
**Version:** 1.1 (Updated with Change Detection & v1.1 Real-Time Path)

---

## Executive Summary

This document specifies a **completely unified, event-driven architecture** for the NBA Props Platform pipeline (Phases 1-5).

**Current State:**
- ✅ Phases 1-2: Working with backfills, good Pub/Sub implementation
- ❌ Phases 3-5: Never run in production, perfect greenfield opportunity

**Proposed State:**
- ✅ Unified patterns across ALL phases
- ✅ Consistent message formats
- ✅ Comprehensive error handling
- ✅ Production-grade monitoring
- ✅ Clean, maintainable codebase

**Philosophy:** Get it right from the start, no technical debt, no compromises.

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Design Principles](#2-design-principles)
3. [Message Format Specification](#3-message-format-specification)
4. [Error Handling Strategy](#4-error-handling-strategy)
5. [Deduplication Strategy](#5-deduplication-strategy)
6. [Change Detection Strategy](#6-change-detection-strategy)
7. [Monitoring & Observability](#7-monitoring--observability)
8. [Phase-by-Phase Architecture](#8-phase-by-phase-architecture)
9. [v1.1 Real-Time Architecture](#9-v11-real-time-architecture)
10. [Migration Decision Framework](#10-migration-decision-framework)
11. [Implementation Roadmap](#11-implementation-roadmap)
12. [Design Decisions](#12-design-decisions)

---

## 1. Current State Analysis

### 1.1 Phase 1 (Scrapers) - Current Implementation ✅

**What's Good:**
- ✅ Dual publishing mode (old + new topics) for safe migration
- ✅ Comprehensive error handling (doesn't fail scraper if Pub/Sub fails)
- ✅ Good message structure with metadata
- ✅ Batch publishing support
- ✅ Integration with Sentry for monitoring
- ✅ Multi-channel notifications (Email + Slack)

**Message Format:**
```python
{
    'name': 'bdl_games',  # Scrapers expect 'name'
    'scraper_name': 'bdl_games',  # Backwards compatibility
    'execution_id': 'abc-123',  # Unique run ID
    'status': 'success',  # success | no_data | failed
    'gcs_path': 'gs://bucket/path/file.json',
    'record_count': 150,
    'duration_seconds': 28.5,
    'timestamp': '2025-11-28T12:00:00Z',
    'workflow': 'MANUAL',
    'error_message': null,
    'metadata': {...}  # Optional additional data
}
```

**Publishing:**
```python
publisher = ScraperPubSubPublisher()
message_id = publisher.publish_completion_event(
    scraper_name='bdl_games',
    execution_id=run_id,
    status='success',
    gcs_path='gs://...',
    record_count=150
)
```

**Topics:**
- Primary: `nba-phase1-scrapers-complete` (new, from config)
- Legacy: `nba-scraper-complete` (dual publish during migration)

**What Could Be Better:**
- ⚠️ Topic naming: Uses centralized config (`TOPICS.PHASE1_SCRAPERS_COMPLETE`) - good!
- ⚠️ Dual publishing: Can remove once fully migrated to new topic
- ⚠️ Message has both 'name' and 'scraper_name' - redundant but needed for compatibility

**Recommendation:** Keep as-is, just deprecate dual publishing after Phase 2 migration complete.

---

### 1.2 Phase 2 (Raw Processors) - Current Implementation ✅

**What's Good:**
- ✅ Uses `RunHistoryMixin` for automatic logging to `processor_run_history`
- ✅ Backfill mode with `skip_downstream_trigger` flag
- ✅ Non-blocking Pub/Sub publishing (failures don't fail processor)
- ✅ Correlation ID tracking (traces back to scraper)

**Message Format:**
```python
{
    'source_table': 'bdl_player_boxscores',
    'game_date': '2025-11-28',
    'record_count': 450,
    'execution_id': 'def-456',
    'correlation_id': 'abc-123',  # From Phase 1 scraper
    'success': True
}
```

**Publishing:**
```python
publisher = RawDataPubSubPublisher(project_id=project_id)
message_id = publisher.publish_raw_data_loaded(
    source_table=self.table_name,
    game_date=str(game_date),
    record_count=stats['rows_inserted'],
    execution_id=self.run_id,
    correlation_id=correlation_id,
    success=True
)
```

**Topics:**
- Primary: `nba-phase2-raw-complete`

**What Could Be Better:**
- ⚠️ Message format inconsistent with Phase 1 (different field names)
- ⚠️ No `timestamp` field (Phase 1 has it)
- ⚠️ No `status` field (uses `success` boolean instead)
- ⚠️ No `processor_name` field (only has `source_table`)
- ⚠️ Publishing code in separate utility (`RawDataPubSubPublisher`) vs Phase 1's `ScraperPubSubPublisher`

**Recommendation:** Unify message format across all phases.

---

### 1.3 Phase 3 (Analytics) - Current Implementation ⚠️

**What's Good:**
- ✅ Has `_publish_completion_message()` in `AnalyticsProcessorBase` (line 1516)
- ✅ Publishes to `nba-phase3-analytics-complete`
- ✅ Uses `RunHistoryMixin`

**Message Format (current):**
```python
{
    'source_table': 'player_game_summary',
    'analysis_date': '2025-11-28',
    'processor_name': 'PlayerGameSummaryProcessor',
    'success': True,
    'run_id': 'xyz-789'
}
```

**What's Missing:**
- ❌ No deduplication check (could process same date twice on Pub/Sub retry)
- ❌ No record_count field
- ❌ No timestamp field
- ❌ No correlation tracking back to Phase 2
- ❌ Inconsistent with Phases 1-2 message format

**Recommendation:** Add deduplication, unify message format.

---

### 1.4 Phases 4-5 - Current Implementation ❌

**Status:** Code deployed but NEVER run in production

**What exists:**
- Cloud Run services deployed
- Base classes written (`PrecomputeProcessorBase`)
- Coordinator and workers code exists

**What's missing:**
- ❌ No Pub/Sub completion publishing in Phase 4
- ❌ No orchestration for Phase 4 dependencies
- ❌ No event-driven trigger for Phase 5
- ❌ No deduplication anywhere

**Recommendation:** Build from scratch with unified architecture.

---

## 2. Design Principles

### 2.1 Core Principles

**1. Event-Driven Architecture**
- Every phase publishes completion events
- Every phase subscribes to upstream completion events
- No time-based assumptions (except scheduler backups)
- Processors trigger immediately when dependencies ready

**2. Unified Message Format**
- ALL phases use same message structure
- Consistent field names across phases
- Standard envelope with phase-specific payload

**3. Idempotency & Deduplication**
- ALL processors check if already run for a date
- Pub/Sub retries don't cause duplicate processing
- Safe to manually re-trigger

**4. Graceful Degradation**
- Partial data is better than no data
- Process what's available, retry for missing
- Clear alerts for incomplete batches

**5. Comprehensive Observability**
- ALL runs logged to `processor_run_history`
- Correlation IDs trace through entire pipeline
- Clear audit trail for debugging

**6. Non-Blocking Error Handling**
- Pub/Sub publish failures don't fail processors
- Alert on failures but continue processing
- Retry mechanisms for transient failures

---

### 2.2 Consistency Rules

**Message Field Names:**
- Use `processor_name` (not `name`, not `source_table`)
- Use `game_date` or `analysis_date` consistently
- Use `status` enum (not `success` boolean)
- Always include `timestamp`, `execution_id`, `correlation_id`

**Topic Naming:**
- Pattern: `nba-phase{N}-{description}-complete`
- Examples:
  - `nba-phase1-scrapers-complete`
  - `nba-phase2-raw-complete`
  - `nba-phase3-analytics-complete`
  - `nba-phase4-precompute-complete`
  - `nba-phase5-predictions-complete`

**Subscription Naming:**
- Pattern: `nba-phase{N}-{description}-sub`
- Push subscriptions for all (event-driven)

**Status Values:**
- `success`: Completed successfully with data
- `partial`: Completed but some records failed
- `no_data`: Ran but found no data to process
- `failed`: Error occurred, did not complete

**Error Handling:**
- Log errors locally
- Publish failure events to Pub/Sub (downstream knows)
- Send alerts for critical failures
- Don't block on Pub/Sub publish failures

---

## 3. Message Format Specification

### 3.1 Unified Message Envelope (ALL Phases)

```python
{
    # === Identity ===
    "processor_name": str,      # e.g., "bdl_games", "PlayerGameSummaryProcessor"
    "phase": str,               # e.g., "phase_1_scrapers", "phase_3_analytics"
    "execution_id": str,        # UUID for this run
    "correlation_id": str,      # UUID from original trigger (traces full pipeline)

    # === Data Reference ===
    "game_date": str,           # ISO date "2025-11-28" (or "analysis_date" if differs)
    "output_table": str,        # BigQuery table name (e.g., "bdl_player_boxscores")
    "output_dataset": str,      # BigQuery dataset (e.g., "nba_raw")

    # === Status ===
    "status": str,              # "success" | "partial" | "no_data" | "failed"
    "record_count": int,        # Records processed
    "records_failed": int,      # Records that failed (0 if all succeeded)

    # === Timing ===
    "timestamp": str,           # ISO 8601 UTC timestamp
    "duration_seconds": float,  # How long it took

    # === Tracing ===
    "parent_processor": str,    # Upstream processor that triggered this (optional)
    "trigger_source": str,      # "pubsub" | "scheduler" | "manual"
    "trigger_message_id": str,  # Pub/Sub message ID that triggered this

    # === Error Info (if failed) ===
    "error_message": str | null,
    "error_type": str | null,

    # === Phase-Specific Payload ===
    "metadata": dict            # Phase-specific additional data
}
```

### 3.2 Phase-Specific Metadata

**Phase 1 (Scrapers):**
```python
"metadata": {
    "gcs_path": "gs://bucket/path/file.json",  # Where data was saved
    "workflow": "MANUAL" | "SCHEDULED",
    "scraper_type": "api" | "web" | "file"
}
```

**Phase 2 (Raw Processors):**
```python
"metadata": {
    "source_gcs_path": "gs://bucket/path/file.json",  # Input file
    "rows_inserted": 450,
    "rows_updated": 0,
    "processing_strategy": "INSERT" | "MERGE"
}
```

**Phase 3 (Analytics):**
```python
"metadata": {
    "players_processed": 450,
    "teams_processed": 30,
    "calculation_type": "game_summary" | "game_context" | "team_summary"
}
```

**Phase 4 (Precompute):**
```python
"metadata": {
    "players_processed": 450,
    "players_ready": 420,  # is_production_ready = TRUE
    "features_generated": 25,
    "dependency_check_passed": true,
    "missing_dependencies": []
}
```

**Phase 5 (Predictions):**
```python
"metadata": {
    "players_processed": 420,
    "predictions_generated": 2100,  # 420 players × 5 systems
    "systems_run": ["moving_avg", "zone_matchup", "similarity", "xgboost", "ensemble"],
    "avg_confidence": 0.85
}
```

---

## 4. Error Handling Strategy

### 4.1 Error Classification

**Transient Errors (Retry):**
- Network timeouts
- BigQuery rate limits
- Temporary API unavailability
- Pub/Sub publish timeouts

**Permanent Errors (Don't Retry):**
- Invalid data format
- Missing required fields
- Schema validation failures
- Authorization errors

**Partial Failures (Continue + Alert):**
- Some players failed, others succeeded
- Some dependencies missing
- Data quality below threshold but above minimum

### 4.2 Error Handling Pattern (All Phases)

```python
def run(self, opts):
    try:
        # Main processing logic
        result = self.process_data()

        # Publish success event
        self._publish_completion_event(status='success', result=result)

        return True

    except TransientError as e:
        # Log and retry (Pub/Sub handles retries)
        logger.warning(f"Transient error: {e}")
        raise  # Let Pub/Sub retry

    except PermanentError as e:
        # Log, alert, publish failure event
        logger.error(f"Permanent error: {e}")
        self._send_alert(severity='critical', message=str(e))
        self._publish_completion_event(status='failed', error=e)
        return False

    except PartialFailure as e:
        # Log, alert, publish partial event
        logger.warning(f"Partial failure: {e}")
        self._send_alert(severity='warning', message=str(e))
        self._publish_completion_event(status='partial', result=e.partial_result)
        return True  # Consider partial success
```

### 4.3 Pub/Sub Publishing Error Handling

**Rule:** NEVER fail processor due to Pub/Sub publish failure

```python
def _publish_completion_event(self, status, result=None, error=None):
    """
    Publish completion event - failures are logged but don't fail processor.
    """
    try:
        publisher = get_publisher()
        message = self._build_message(status, result, error)
        message_id = publisher.publish(topic, message)
        logger.info(f"Published completion event: {message_id}")

    except Exception as pub_error:
        # Log but don't fail - downstream has scheduler backup
        logger.error(f"Failed to publish completion event: {pub_error}")

        # Send alert so ops knows Pub/Sub is broken
        try:
            self._send_alert(
                severity='warning',
                title='Pub/Sub Publishing Failed',
                message=f"Event-driven trigger broken for {self.__class__.__name__}. "
                        f"Downstream will use scheduler backup."
            )
        except:
            pass  # Don't fail on alert failure either
```

---

## 5. Deduplication Strategy

### 5.1 Why Deduplication Matters

**Problem:** Pub/Sub can deliver messages multiple times (at-least-once delivery)

**Without deduplication:**
```
Phase 2 publishes completion event
  → Pub/Sub delivers to Phase 3
  → Phase 3 processes data
  → Phase 3 crashes before ACK
  → Pub/Sub redelivers message
  → Phase 3 processes AGAIN (duplicate!)
```

**With deduplication:**
```
Phase 2 publishes completion event
  → Pub/Sub delivers to Phase 3
  → Phase 3 checks: "Already processed 2025-11-28?" → No
  → Phase 3 processes data
  → Phase 3 crashes before ACK
  → Pub/Sub redelivers message
  → Phase 3 checks: "Already processed 2025-11-28?" → YES
  → Phase 3 returns success, no reprocessing
```

### 5.2 Deduplication Implementation (All Phases 2-5)

```python
def run(self, opts):
    """
    Main entry point with deduplication check.
    """
    # Extract date
    game_date = opts.get('game_date') or opts.get('analysis_date')

    # Check if already processed
    if self._already_processed(game_date):
        logger.info(f"{self.__class__.__name__} already processed {game_date}, skipping")
        return True  # Return success to ACK Pub/Sub message

    # Process normally
    # ...

def _already_processed(self, game_date: date) -> bool:
    """
    Check if this processor already successfully ran for this date.

    Uses processor_run_history table (via RunHistoryMixin).
    Only checks for 'success' or 'partial' status (not 'failed').
    """
    from google.cloud import bigquery
    client = bigquery.Client(project=self.project_id)

    query = """
    SELECT status, processed_at
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

    results = list(client.query(query, job_config=job_config).result())

    if results:
        last_run = results[0]
        logger.info(
            f"Found existing successful run: {last_run.status} at {last_run.processed_at}"
        )
        return True

    return False
```

**Benefits:**
- ✅ Safe Pub/Sub retries
- ✅ Safe manual re-triggers
- ✅ Idempotent operations
- ✅ No duplicate data

**Trade-off:**
- ⚠️ Can't automatically reprocess failed dates (must manually clear processor_run_history)
- ✅ But this is actually a FEATURE - prevents accidental reprocessing

---

## 6. Change Detection Strategy

### 6.1 The Problem: Wasteful Reprocessing

**Scenario:** Injury report at 2:00 PM, LeBron James ruled OUT

**Without change detection:**
```
2:00 PM - Injury scraper runs, gets ALL 450 players
  ↓ Phase 2 processes ALL 450 players (MERGE upsert)
  ↓ Only LeBron's row actually changes in BigQuery
  ↓ Phase 3 receives trigger
  ↓ Phase 3 processes ALL 450 players again
  ↓ Only LeBron's analytics actually change
  ↓ Phase 4 processes ALL 450 players
  ↓ Phase 5 generates predictions for ALL 450 players

Result: ❌ Wasteful - 449 players unnecessarily reprocessed
```

**With change detection:**
```
2:00 PM - Injury scraper runs, gets ALL 450 players
  ↓ Phase 2 processes ALL 450 players (MERGE upsert)
  ↓ Only LeBron's row changes
  ↓ Phase 3 receives trigger
  ↓ Phase 3 detects only LeBron changed
  ↓ Phase 3 processes ONLY LeBron (1 player)
  ↓ Phase 4 processes ONLY LeBron
  ↓ Phase 5 generates predictions for ONLY LeBron
2:03 PM - Done!

Result: ✅ Efficient - Only 1 player processed, 3 minutes total
```

---

### 6.2 v1.0 Implementation: Query-Based Change Detection

**Architecture:** Batch messages + change detection in processors

```python
class AnalyticsProcessorBase(RunHistoryMixin):
    """
    Base class for Phase 3 analytics processors.
    v1.0 adds change detection to avoid wasteful reprocessing.
    """

    # NEW: Enable change detection (child classes can override)
    enable_change_detection: bool = True
    change_detection_fields: List[str] = []  # Fields to check for changes

    def run(self, opts):
        """Main processing with change detection."""
        game_date = opts.get('game_date')
        correlation_id = opts.get('correlation_id')

        # Deduplication check (from section 5)
        if self._already_processed(game_date):
            logger.info("Already processed, skipping")
            return True

        # NEW: Change detection
        if self.enable_change_detection:
            changed_entities = self._detect_changed_entities(game_date)

            if not changed_entities:
                logger.info(f"No data changes detected for {game_date}, skipping processing")
                # Still record the run (with 0 records processed)
                self._record_no_changes_run(game_date, correlation_id)
                return True

            logger.info(
                f"Detected {len(changed_entities)} changed entities "
                f"out of {self._count_total_entities(game_date)} total"
            )

            # Process only changed entities
            self._process_entities(changed_entities, game_date)
        else:
            # Process all entities (normal batch mode)
            all_entities = self._get_all_entities(game_date)
            self._process_entities(all_entities, game_date)

    def _detect_changed_entities(self, game_date: date) -> List[str]:
        """
        Detect which entities (players/teams) have changed data.

        Compares current raw data vs last processed analytics data.
        Returns list of entity IDs (player_lookup, team_abbr, etc.) that changed.

        Strategy:
        1. Query current upstream data (Phase 2 raw tables)
        2. Query last processed analytics data (Phase 3 analytics tables)
        3. Compare relevant fields
        4. Return entities where data differs
        """
        from google.cloud import bigquery
        client = bigquery.Client(project=self.project_id)

        # Build comparison query (child classes customize)
        query = self._build_change_detection_query(game_date)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )

        results = client.query(query, job_config=job_config).result()
        changed_entities = [row.entity_id for row in results]

        return changed_entities

    def _build_change_detection_query(self, game_date: date) -> str:
        """
        Build change detection query (child classes override).

        Example for PlayerGameSummaryProcessor:
        """
        # This is customized per processor based on their data sources
        # See examples below for each processor type
        raise NotImplementedError("Child class must implement")


# Example: PlayerGameSummaryProcessor change detection
class PlayerGameSummaryProcessor(AnalyticsProcessorBase):

    enable_change_detection = True
    change_detection_fields = [
        'minutes', 'points', 'rebounds', 'assists',
        'injury_status', 'active_status'
    ]

    def _build_change_detection_query(self, game_date: date) -> str:
        """
        Compare current raw player data vs last processed analytics.
        """
        return """
        WITH current_raw AS (
            -- Current data from Phase 2 raw tables
            SELECT
                player_lookup,
                minutes,
                points,
                rebounds,
                assists,
                injury_status,
                active_status
            FROM `{project}.nba_raw.nbac_player_boxscore`
            WHERE game_date = @game_date
        ),
        last_processed AS (
            -- Last processed analytics
            SELECT
                player_lookup,
                minutes,
                points,
                rebounds,
                assists,
                injury_status,
                active_status
            FROM `{project}.nba_analytics.player_game_summary`
            WHERE game_date = @game_date
        )
        SELECT DISTINCT r.player_lookup as entity_id
        FROM current_raw r
        LEFT JOIN last_processed p USING (player_lookup)
        WHERE
            -- New player (not in analytics yet)
            p.player_lookup IS NULL
            -- OR any tracked field changed
            OR r.minutes != p.minutes
            OR r.points != p.points
            OR r.rebounds != p.rebounds
            OR r.assists != p.assists
            OR r.injury_status != p.injury_status
            OR r.active_status != p.active_status
        """.format(project=self.project_id)
```

---

### 6.3 Change Detection for Each Processor Type

**Phase 3 - Player Analytics:**
```python
# PlayerGameSummaryProcessor
# Detects: Player stats changes, injury status changes

# UpcomingPlayerGameContextProcessor
# Detects: Lineup changes, injury changes, matchup changes
```

**Phase 4 - Precompute:**
```python
# TeamDefenseZoneAnalysisProcessor
# Detects: Team defense stats changes

# PlayerComposi teFactorsProcessor
# Detects: Any upstream Phase 3 or Phase 4 changes for player
```

**Phase 5 - Predictions:**
```python
# Coordinator
# Detects: Phase 4 ml_feature_store changes for players
# Only generates predictions for players with updated features
```

---

### 6.4 Updated Message Format (With Change Tracking)

```python
{
    # ... existing unified fields ...

    # NEW: Change tracking fields
    "entities_total": 450,              # Total entities in dataset
    "entities_processed": 1,            # Entities actually processed
    "entities_skipped": 449,            # Entities skipped (no changes)
    "entities_changed": ["lebron-james"],  # List of changed entity IDs
    "change_type": "injury_status",     # What type of change triggered this
    "is_incremental": false,            # v1.0 = always false, v1.1 = true for real-time

    "metadata": {
        "change_detection_enabled": true,
        "change_detection_query_time_ms": 150,
        "efficiency_gain_pct": 99.8  # (449/450) * 100
    }
}
```

---

### 6.5 Benefits of v1.0 Change Detection

**Performance:**
- ✅ 99%+ reduction in processing time for mid-day updates
- ✅ 99%+ reduction in compute costs for incremental updates
- ✅ Query-based detection is cheap (< 1 second)

**Simplicity:**
- ✅ Works with existing batch architecture
- ✅ No new Pub/Sub topics or orchestration
- ✅ Single code path (batch + detection)
- ✅ Easy to debug and monitor

**Flexibility:**
- ✅ Can disable per processor if needed
- ✅ Customizable change detection logic per processor
- ✅ Foundation for v1.1 real-time (see section 9)

**User Experience:**
- ✅ Injury report at 2 PM → Updated predictions by 2:03 PM
- ✅ Lineup change → Quick updates
- ✅ Still works for full daily batch processing

---

### 6.6 Trade-offs & Limitations

**Query Overhead:**
- ⚠️ Adds one query per processor run (to detect changes)
- ✅ But query is cheap (< $0.01, < 1 sec)
- ✅ Saves massive processing costs (99% reduction)

**Not True Real-Time:**
- ⚠️ Still requires full scraper run + batch processing
- ⚠️ Can't detect changes instantly (must wait for scraper to run)
- ✅ Good enough for v1.0 (3-minute updates vs 6-hour wait)
- ✅ v1.1 adds true real-time (see section 9)

**Complexity:**
- ⚠️ Each processor needs custom change detection query
- ⚠️ Must maintain list of fields to compare
- ✅ But queries are straightforward SQL
- ✅ Well-documented examples for each processor type

---

## 7. Monitoring & Observability

### 7.1 Unified Logging to processor_run_history

**All processors (Phases 2-5) use `RunHistoryMixin`:**

```sql
-- nba_reference.processor_run_history schema
CREATE TABLE processor_run_history (
    -- Identity
    processor_name STRING,              -- e.g., "PlayerGameSummaryProcessor"
    run_id STRING,                      -- Unique execution ID
    phase STRING,                       -- e.g., "phase_3_analytics"

    -- Data reference
    data_date DATE,                     -- Which date was processed
    output_table STRING,                -- Target table
    output_dataset STRING,              -- Target dataset

    -- Status
    status STRING,                      -- "success" | "partial" | "failed"
    records_processed INT64,
    records_failed INT64,

    -- Timing
    started_at TIMESTAMP,
    processed_at TIMESTAMP,
    duration_seconds FLOAT64,

    -- Triggering
    trigger_source STRING,              -- "pubsub" | "scheduler" | "manual"
    trigger_message_id STRING,          -- Pub/Sub message ID
    parent_processor STRING,            -- Upstream processor
    correlation_id STRING,              -- Traces to Phase 1 scraper

    -- Dependencies
    dependency_check_passed BOOLEAN,
    missing_dependencies ARRAY<STRING>,
    stale_dependencies ARRAY<STRING>,

    -- Alerting
    alert_sent BOOLEAN,
    alert_type STRING,                  -- "critical" | "warning" | "info"

    -- Error details
    error_message STRING,
    error_type STRING,

    -- Metadata
    summary JSON,                       -- Phase-specific details
    cloud_run_service STRING,
    cloud_run_revision STRING,

    -- Retry tracking
    retry_attempt INT64,
    skipped BOOLEAN,
    skip_reason STRING
);
```

**Benefits:**
- ✅ Complete audit trail
- ✅ Correlation tracking across phases
- ✅ Easy debugging (trace correlation_id from Phase 1 → 5)
- ✅ Performance analysis
- ✅ Alert tracking

---

### 7.2 Monitoring Dashboards

**Dashboard 1: Pipeline Health (Real-Time)**
- Current processing status by phase
- Last successful run time per processor
- Current errors/warnings
- Pub/Sub queue depths

**Dashboard 2: Latency Metrics**
- Phase 1 → 2 latency (scraper complete → raw processed)
- Phase 2 → 3 latency (raw complete → analytics processed)
- Phase 3 → 4 latency (analytics complete → precompute processed)
- Phase 4 → 5 latency (precompute complete → predictions generated)
- End-to-end latency (scraper start → predictions complete)

**Dashboard 3: Data Quality**
- Records processed per phase
- Failure rates by processor
- Deduplication hit rate
- Partial completion frequency

**Dashboard 4: Historical Trends (30 days)**
- Processing times by phase
- Failure patterns
- Alert frequency
- Coverage metrics (predictions generated / expected)

---

### 7.3 Alerting Strategy

**Critical Alerts (Immediate Response):**
- Phase fails completely (0% success)
- End-to-end latency > 2 hours
- Predictions missing for >20% of players
- Deduplication failures (data corruption risk)

**Warning Alerts (Review Same Day):**
- Phase completes with partial failures (>10%)
- Pub/Sub publishing fails (event-driven broken)
- End-to-end latency > 1 hour
- Missing dependencies detected

**Info Notifications (Daily Summary):**
- Successful daily runs
- Performance metrics
- Coverage statistics

---

## 8. Phase-by-Phase Architecture

### 8.1 Phase 1: Data Collection (Scrapers)

**Current State:** ✅ Good, minor improvements

**Changes:**
1. Remove dual publishing after migration complete
2. Standardize message format to match unified spec
3. Add correlation_id from the start (traces full pipeline)

**New Message Format:**
```python
{
    "processor_name": "bdl_games",
    "phase": "phase_1_scrapers",
    "execution_id": "abc-123",
    "correlation_id": "abc-123",  # Same as execution_id for Phase 1
    "game_date": "2025-11-28",
    "output_table": "bdl_games",
    "output_dataset": "nba_raw",
    "status": "success",  # Changed from boolean
    "record_count": 150,
    "records_failed": 0,
    "timestamp": "2025-11-28T12:00:00Z",
    "duration_seconds": 28.5,
    "parent_processor": null,
    "trigger_source": "scheduler",
    "trigger_message_id": null,
    "error_message": null,
    "error_type": null,
    "metadata": {
        "gcs_path": "gs://bucket/path/file.json",
        "workflow": "SCHEDULED",
        "scraper_type": "api"
    }
}
```

**Publishing:**
```python
# Updated ScraperPubSubPublisher
publisher = ScraperPubSubPublisher()
message_id = publisher.publish_completion_event(
    processor_name='bdl_games',
    execution_id=run_id,
    game_date='2025-11-28',
    status='success',  # Not 'success' boolean
    record_count=150,
    gcs_path='gs://...',
    # ... other unified fields
)
```

**Infrastructure:**
- Topic: `nba-phase1-scrapers-complete` ✅ (already exists)
- Subscription: `nba-phase2-raw-sub` → Phase 2 processors ✅ (already exists)

---

### 8.2 Phase 2: Raw Processing

**Current State:** ✅ Good, needs message format update + deduplication

**Changes:**
1. Unify message format with Phase 1
2. Add deduplication check
3. Add correlation_id tracking

**New Implementation:**
```python
class ProcessorBase(RunHistoryMixin):

    def run(self, opts):
        # Extract date and correlation_id from upstream message
        game_date = opts.get('game_date')
        correlation_id = opts.get('correlation_id') or opts.get('execution_id')

        # NEW: Deduplication check
        if self._already_processed(game_date):
            logger.info(f"Already processed {game_date}, skipping")
            return True

        # Start run tracking with correlation
        self.start_run_tracking(
            data_date=game_date,
            trigger_source=opts.get('trigger_source', 'pubsub'),
            trigger_message_id=opts.get('trigger_message_id'),
            parent_processor=opts.get('processor_name'),  # From Phase 1
            correlation_id=correlation_id
        )

        # Process normally
        # ...

        # Publish completion event
        self._publish_completion_event(
            game_date=game_date,
            correlation_id=correlation_id
        )

    def _publish_completion_event(self, game_date, correlation_id):
        """Publish using unified message format."""
        publisher = UnifiedPubSubPublisher()  # NEW: Unified publisher

        message = {
            "processor_name": self.__class__.__name__,
            "phase": "phase_2_raw",
            "execution_id": self.run_id,
            "correlation_id": correlation_id,  # Track from Phase 1
            "game_date": str(game_date),
            "output_table": self.table_name,
            "output_dataset": self.dataset_id,
            "status": "success",
            "record_count": self.stats.get('rows_inserted', 0),
            "records_failed": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": self.stats.get('total_runtime', 0),
            "parent_processor": self.opts.get('processor_name'),
            "trigger_source": self.opts.get('trigger_source'),
            "trigger_message_id": self.opts.get('trigger_message_id'),
            "error_message": null,
            "error_type": null,
            "metadata": {
                "source_gcs_path": self.opts.get('gcs_path'),
                "rows_inserted": self.stats.get('rows_inserted', 0),
                "processing_strategy": "INSERT"
            }
        }

        publisher.publish(topic='nba-phase2-raw-complete', message=message)
```

**Infrastructure:**
- Topic: `nba-phase2-raw-complete` ✅ (already exists)
- Subscription: `nba-phase3-analytics-sub` → Phase 3 processors ✅ (already exists)

---

### 8.3 Phase 3: Analytics Processing

**Current State:** ⚠️ Needs deduplication + orchestrator

**Changes:**
1. Add deduplication check
2. Unify message format
3. Build orchestrator to track all 5 processors

**New Implementation:**
```python
class AnalyticsProcessorBase(RunHistoryMixin):

    def run(self, opts):
        analysis_date = opts.get('analysis_date')
        correlation_id = opts.get('correlation_id')

        # NEW: Deduplication check
        if self._already_processed(analysis_date):
            logger.info(f"Already processed {analysis_date}, skipping")
            return True

        # Start tracking
        self.start_run_tracking(
            data_date=analysis_date,
            trigger_source=opts.get('trigger_source'),
            correlation_id=correlation_id,
            parent_processor=opts.get('processor_name')  # From Phase 2
        )

        # Process
        # ...

        # Publish completion (triggers Phase 3→4 orchestrator)
        self._publish_completion_event()
```

**NEW: Phase 3→4 Orchestrator (Cloud Function):**
```python
# cloud_functions/phase3_to_phase4_orchestrator/main.py

PHASE3_PROCESSORS = [
    'PlayerGameSummaryProcessor',
    'TeamOffenseGameSummaryProcessor',
    'TeamDefenseGameSummaryProcessor',
    'UpcomingPlayerGameContextProcessor',
    'UpcomingTeamGameContextProcessor'
]

@functions_framework.cloud_event
def handle_phase3_completion(cloud_event):
    """
    Track Phase 3 processors, trigger Phase 4 when all complete.
    Uses Firestore for atomic state tracking.
    """
    # Decode message
    event = json.loads(base64.b64decode(cloud_event.data["message"]["data"]))

    processor_name = event['processor_name']
    analysis_date = event['game_date']
    correlation_id = event['correlation_id']

    # Track in Firestore (atomic)
    db = firestore.Client()
    doc_ref = db.collection('phase3_completion').document(analysis_date)
    doc_ref.set({
        processor_name: {
            'completed_at': firestore.SERVER_TIMESTAMP,
            'correlation_id': correlation_id
        }
    }, merge=True)

    # Check if all complete
    doc = doc_ref.get()
    completed = set(doc.to_dict().keys())
    required = set(PHASE3_PROCESSORS)

    if completed >= required:
        # Trigger Phase 4
        publisher = pubsub_v1.PublisherClient()
        topic = 'nba-phase4-trigger'

        message = {
            "event_type": "phase3_all_complete",
            "game_date": analysis_date,
            "correlation_id": correlation_id,
            "processors_completed": list(completed)
        }

        publisher.publish(topic, json.dumps(message).encode())
        logger.info(f"Triggered Phase 4 for {analysis_date}")
```

**Infrastructure:**
- Topic (from processors): `nba-phase3-analytics-complete` ✅
- Topic (to Phase 4): `nba-phase4-trigger` ❌ NEW
- Cloud Function: `phase3-to-phase4-orchestrator` ❌ NEW

---

### 8.4 Phase 4: Precompute Processing

**Current State:** ❌ Needs complete rebuild

**New Architecture:**
1. Event-driven trigger from Phase 3 orchestrator
2. Internal orchestrator for 5 processor dependencies
3. Completion event to trigger Phase 5

**Processor Dependency Graph:**
```
Level 1 (Parallel - triggered by Phase 3→4 orchestrator):
├─ team_defense_zone_analysis
├─ player_shot_zone_analysis
└─ player_daily_cache

Level 2 (Waits for Level 1 + upcoming_player_game_context):
└─ player_composite_factors

Level 3 (Waits for ALL above):
└─ ml_feature_store_v2
```

**NEW: Phase 4 Internal Orchestrator:**
```python
# Similar to Phase 3→4, but tracks 5 Phase 4 processors
# Triggers ml_feature_store_v2 when all dependencies ready
```

**Phase 4 Completion Publishing (ml_feature_store_v2):**
```python
def post_process(self):
    """Publish Phase 4 completion to trigger Phase 5."""
    super().post_process()
    self._publish_phase5_trigger()

def _publish_phase5_trigger(self):
    """Same as IMPLEMENTATION-FULL.md - triggers Phase 5."""
    # Publishes to: nba-phase4-precompute-complete
    # Message includes: players_ready, players_total, etc.
```

**Infrastructure:**
- Topic (trigger): `nba-phase4-trigger` ❌ NEW
- Topic (internal): `nba-phase4-processor-complete` ❌ NEW
- Topic (to Phase 5): `nba-phase4-precompute-complete` ❌ NEW
- Cloud Function: `phase4-orchestrator` ❌ NEW

---

### 8.5 Phase 5: Predictions

**Current State:** ❌ Needs complete rebuild

**New Implementation:**
- Same as IMPLEMENTATION-FULL.md
- `/trigger` endpoint (Pub/Sub from Phase 4)
- `/start` endpoint (scheduler backup with 30-min wait)
- `/retry` endpoint (6:15 AM, 6:30 AM PT)
- `/status` endpoint (7:00 AM PT SLA check)

**Already fully specified in IMPLEMENTATION-FULL.md** ✅

---

## 9. v1.1 Real-Time Architecture (Future)

**Note:** Complete v1.1 architecture and migration framework documented in separate file:
**`V1.1-REALTIME-SUPPLEMENT.md`**

### Quick Summary

**v1.0 (This Design):**
- Batch processing with change detection
- 2-5 minute latency for updates
- Cost: ~$20/month
- Timeline: 3-4 weeks implementation

**v1.1 (Future):**
- Dual-path: Batch + real-time incremental
- Sub-minute latency for single-player updates
- Cost: ~$35-50/month
- Additional 3-4 weeks implementation

**When to migrate to v1.1:**
- Daily incremental updates > 20/day
- Sub-minute latency required
- User demand for real-time features
- After v1.0 stable for 1-2 months

See **V1.1-REALTIME-SUPPLEMENT.md** for:
- Complete incremental architecture
- Per-player processing endpoints
- Prediction versioning strategy
- Cost/benefit analysis
- Migration decision framework
- Go/no-go checklist

---

## 10. Migration Decision Framework

See **V1.1-REALTIME-SUPPLEMENT.md** section 10 for complete framework.

**Key Decision Points:**

| When | Decision |
|------|----------|
| **Now** | Implement v1.0 (batch + change detection) |
| **Month 1-2** | Monitor usage, gather metrics |
| **Month 3** | Evaluate: Do we need v1.1? |
| **If yes** | Implement v1.1 incremental path |
| **If no** | Continue with v1.0, re-evaluate in 3 months |

**Quantitative Triggers for v1.1:**
- Incremental updates > 20/day
- User requests > 10/week
- Revenue opportunity identified
- Acceptable cost increase ($30-50/month)

---

## 11. Implementation Roadmap

### Week 1: Foundation & Unification

**Day 1-2: Create Unified Infrastructure (8 hours)**
1. Create `UnifiedPubSubPublisher` class (shared across all phases)
2. Update message format validation
3. Create Pub/Sub topics for Phase 3→4→5
4. Write comprehensive unit tests

**Day 3: Update Phase 1-2 (6 hours)**
1. Update Phase 1 to use unified message format
2. Update Phase 2 to use unified message format
3. Add deduplication to Phase 2
4. Test end-to-end Phase 1→2

### Week 2: Build Phases 3-4

**Day 4-5: Build Phase 3 (8 hours)**
1. Add deduplication to `AnalyticsProcessorBase`
2. Update message publishing to unified format
3. Build Phase 3→4 orchestrator Cloud Function
4. Test with backfill data

**Day 6-7: Build Phase 4 (12 hours)**
1. Add deduplication to `PrecomputeProcessorBase`
2. Build Phase 4 internal orchestrator
3. Add completion publishing to ml_feature_store_v2
4. Test dependency orchestration

### Week 3: Build Phase 5 & Test

**Day 8-9: Build Phase 5 (10 hours)**
1. Implement all endpoints (from IMPLEMENTATION-FULL.md)
2. Add all helper functions
3. Deploy infrastructure
4. Test Pub/Sub trigger path

**Day 10-11: End-to-End Testing (12 hours)**
1. Test complete pipeline with backfill data
2. Test failure scenarios
3. Test retry logic
4. Performance testing

### Week 4: Deploy & Monitor

**Day 12: Deploy to Production (4 hours)**
1. Deploy all services
2. Enable current season processing
3. Monitor first production run

**Day 13-14: Monitoring & Validation (8 hours)**
1. Create dashboards
2. Set up alerts
3. Document operational procedures

**Total: ~68 hours over 3-4 weeks**

---

## 12. Design Decisions

### Decision 1: Unified Message Format vs Phase-Specific

**Options:**
- A) Each phase has own message format (current state)
- B) Unified format across all phases (proposed)

**Decision:** B - Unified format

**Rationale:**
- Easier to understand and maintain
- Simplifies debugging (consistent structure)
- Enables generic tooling (monitors, dashboards)
- Only slightly more verbose

### Decision 2: Deduplication Strategy

**Options:**
- A) No deduplication (idempotent processing)
- B) Deduplication via processor_run_history
- C) Deduplication via Pub/Sub message deduplication

**Decision:** B - processor_run_history

**Rationale:**
- Works for both Pub/Sub AND manual triggers
- Already have processor_run_history table
- Provides audit trail
- Pub/Sub deduplication has limited time window (10 min)

### Decision 3: Phase 3→4 Orchestration

**Options:**
- A) Cloud Function with Firestore state
- B) Cloud Workflows
- C) Time-based scheduler with delays

**Decision:** A - Cloud Function + Firestore

**Rationale:**
- Simpler than Cloud Workflows for this use case
- Atomic state updates with Firestore
- Can migrate to Workflows later if needed
- Low cost, high reliability

### Decision 4: Phase 4 Internal Orchestration

**Options:**
- A) Separate orchestrator for Phase 4 dependencies
- B) Time-based scheduler (current state)
- C) Each processor checks dependencies on startup

**Decision:** A - Separate orchestrator

**Rationale:**
- Consistent with Phase 3→4 pattern
- No time assumptions
- Processors start ASAP when dependencies ready
- Clear separation of concerns

### Decision 5: Error Handling Philosophy

**Options:**
- A) Fail fast (any error fails entire pipeline)
- B) Graceful degradation (process what's available)
- C) Best effort (try everything, report what failed)

**Decision:** B - Graceful degradation

**Rationale:**
- Partial data is better than no data
- Clear alerts for incomplete batches
- Retry mechanisms for missing data
- Better user experience

---

### Decision 6: Change Detection Strategy

**Options:**
- A) No change detection (always reprocess everything)
- B) Query-based change detection (v1.0)
- C) Incremental messages from scrapers (per-player events)
- D) Hybrid (batch for daily, incremental for real-time)

**Decision for v1.0:** B - Query-based change detection

**Rationale:**
- Works with existing batch architecture (no new infrastructure)
- Solves mid-day update inefficiency (injury reports, lineup changes)
- Query overhead is minimal (< $0.01, < 1 sec per processor)
- Saves massive processing costs (99% reduction for single-player changes)
- Foundation for future v1.1 real-time architecture
- User experience improvement: 2 PM injury → 2:03 PM updated prediction

**Future (v1.1):** Hybrid - Keep batch + add incremental real-time path

**Why not C or D now:**
- C/D require significant new infrastructure (per-player endpoints, versioning)
- C/D higher complexity without proven user demand yet
- Better to validate v1.0 works before investing in real-time
- Can migrate to D in 2-3 months if metrics justify it

---

## Next Steps

**For You (User):**
1. Review this design thoroughly
2. Ask questions about any aspect
3. Suggest changes or improvements
4. Approve design before implementation starts

**For Me (Claude):**
1. Wait for your feedback
2. Make any requested changes
3. Create detailed implementation specs for each phase
4. Begin implementation only after your approval

---

**Document Status:** 📐 Awaiting Review
**Next Action:** User review and feedback
**Questions to Consider:**
- Do you agree with the unified message format?
- Do you like the orchestration approach (Cloud Functions)?
- Any concerns about deduplication strategy?
- Timeline acceptable (3-4 weeks)?
- Anything you'd do differently?
