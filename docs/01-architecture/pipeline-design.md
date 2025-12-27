# Event-Driven Pipeline Architecture: Phase 1-6

**File:** `docs/01-architecture/pipeline-design.md`
**Created:** 2025-11-14 22:33 PST
**Last Updated:** 2025-12-27
**Purpose:** ⭐ **START HERE** - Complete 6-phase event-driven architecture from scrapers to web app
**Status:** v1.0 Deployed - All 6 phases production ready
**Current Status:** See [SYSTEM_STATUS.md](../00-start-here/SYSTEM_STATUS.md) for live deployment status

---

## Executive Summary

This document describes the complete event-driven architecture for the NBA Props Platform's data pipeline, from data collection (Phase 1) through to web application publishing (Phase 6). The architecture is designed to be **efficient, reliable, and observable** while handling the complexities of many-to-one dependencies, incremental updates, and error recovery.

**Key Design Principles:**
- **Event-driven:** Each phase triggers the next via Pub/Sub (real-time, decoupled)
- **Granular updates:** Support for entity-level incremental processing (players, teams, games)
- **Dependency-aware:** Processors validate dependencies before running
- **Idempotent:** Safe to retry, no duplicate processing
- **Observable:** Full end-to-end tracking and monitoring
- **Resilient:** Automatic retries, Dead Letter Queues, manual recovery procedures

---

## User Concerns & Requirements

Before diving into the architecture, let's outline the key concerns and requirements that shaped this design:

### Concern 1: Dependency Complexity

**Issue:** Phase 1 → Phase 2 is straightforward (1:1 relationship), but Phase 2 → Phase 3 becomes complex (many:1 relationships).

**Example:** `PlayerGameSummaryProcessor` (Phase 3) depends on 6 different Phase 2 tables:
- `nbac_gamebook_player_stats` (CRITICAL - primary stats)
- `bdl_player_boxscores` (CRITICAL - fallback stats)
- `bigdataball_play_by_play` (OPTIONAL - shot zones)
- `nbac_play_by_play` (OPTIONAL - backup shot zones)
- `odds_api_player_points_props` (OPTIONAL - prop lines)
- `bettingpros_player_points_props` (OPTIONAL - backup prop lines)

**Question:** How do we know when to trigger Phase 3 if it needs multiple Phase 2 tables?

### Concern 2: Triggering Strategy

**Issue:** Do we wait for ALL dependencies to be ready, or trigger opportunistically?

**Example Timeline:**
- 10:05 PM - Table 1 loads (5 more tables still pending)
- 10:10 PM - Table 2 loads (4 more tables still pending)
- ...should we trigger Phase 3 at 10:05? 10:10? Wait for all 6?

**Question:** How do we balance real-time processing with dependency requirements?

### Concern 3: Incremental vs Full Updates

**Issue:** Minor changes (e.g., one player injury update) shouldn't require re-processing all 450+ players.

**Example:**
- 2:00 PM - LeBron James ruled OUT (1 player affected)
- Current plan: Re-process entire game_date (all 450 players) = wasteful
- Desired: Re-process only LeBron's record = efficient

**Question:** How do we support granular, entity-level updates instead of all-or-nothing processing?

### Concern 4: Pub/Sub Message Sharing

**Issue:** Understanding how Pub/Sub messages work with multiple consumers.

**Example:** When `bdl_player_boxscores` updates, THREE Phase 3 processors need it:
- `PlayerGameSummaryProcessor`
- `TeamOffenseProcessor`
- `TeamDefenseProcessor`

**Question:** Can multiple processors use the same Pub/Sub message, or does only one get it?

### Concern 5: End-to-End Observability

**Issue:** Need to detect when data doesn't propagate through the entire pipeline.

**Example:**
- Phase 1 ✅ Scraper runs
- Phase 2 ✅ Raw processor loads data
- Phase 3 ✅ Analytics processor runs
- Phase 4 ❌ Precompute processor FAILS
- Phase 5 ⏸️ Never runs (waiting for Phase 4)
- Phase 6 ⏸️ Never publishes (web app shows stale data)

**Questions:**
- Will the failed message be available to retry later?
- Will monitoring detect that Phase 4 failed?
- Will we know the change didn't reach Phase 5 or Phase 6?

### Concern 6: Phase 6 Publishing Layer

**Issue:** Need to publish predictions to Firestore and GCS for web app consumption.

**Requirements:**
- Web app should NOT query BigQuery directly
- Data should be pre-computed and optimized for reads
- Support both real-time (Firestore) and cacheable (GCS) formats

---

## Architecture Overview

### The Six-Phase Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DATA FLOW PIPELINE                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Phase 1: Scrapers                                                      │
│  ├─ Collect data from external APIs                                     │
│  ├─ Write raw JSON to Cloud Storage                                     │
│  └─ Publish: "scraper_complete" event                                   │
│      ↓ Pub/Sub: nba-phase1-scrapers-complete                            │
│                                                                          │
│  Phase 2: Raw Processors (1:1 with Phase 1)                            │
│  ├─ Download JSON from GCS                                              │
│  ├─ Transform and validate                                              │
│  ├─ Load to BigQuery raw tables (nba_raw.*)                            │
│  └─ Publish: "raw_data_loaded" event                                    │
│      ↓ Pub/Sub: nba-phase2-raw-complete                                 │
│                                                                          │
│  Phase 3: Analytics Processors (M:1 with Phase 2)                      │
│  ├─ Check dependencies (are all required Phase 2 tables ready?)        │
│  ├─ Query raw tables, calculate analytics                               │
│  ├─ Load to BigQuery analytics tables (nba_analytics.*)                │
│  └─ Publish: "analytics_complete" event                                 │
│      ↓ Pub/Sub: nba-phase3-analytics-complete                           │
│                                                                          │
│  Phase 4: Precompute Processors (M:1 with Phase 3)                     │
│  ├─ Check dependencies (Phase 3 analytics ready?)                       │
│  ├─ Calculate expensive aggregations                                    │
│  ├─ Load to BigQuery precompute tables (nba_precompute.*)              │
│  └─ Publish: "precompute_complete" event                                │
│      ↓ Pub/Sub: nba-phase4-precompute-complete                          │
│                                                                          │
│  Phase 5: Prediction Processors (M:1 with Phase 4)                     │
│  ├─ Check dependencies (Phase 4 precompute ready?)                      │
│  ├─ Run ML models, generate predictions                                 │
│  ├─ Load to BigQuery predictions tables (nba_predictions.*)            │
│  └─ Publish: "predictions_ready" event                                  │
│      ↓ Pub/Sub: nba-phase5-predictions-complete                         │
│                                                                          │
│  Phase 6: Publishing Service (1:1 with Phase 5)                        │
│  ├─ Fetch predictions from BigQuery                                     │
│  ├─ Transform to web-friendly JSON                                      │
│  ├─ Publish to Firestore (real-time access)                            │
│  ├─ Publish to GCS (CDN-cacheable)                                      │
│  └─ Web app reads published data                                        │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Relationship Patterns

**Phase 1 → Phase 2:** **1:1** (Simple)
- One scraper → One raw processor
- Scraper `nbac_injury_report` → Processor `NbacInjuryReportProcessor`
- Direct mapping, straightforward

**Phase 2 → Phase 3:** **M:1** (Complex) ← **Key Challenge**
- Multiple raw tables → One analytics processor
- Example: 6 raw tables → `PlayerGameSummaryProcessor`
- Requires dependency coordination

**Phase 3 → Phase 4:** **M:1** (Similar to 2→3)
- Multiple analytics tables → One precompute processor
- Same patterns as Phase 2 → Phase 3

**Phase 4 → Phase 5:** **M:1** (Similar to 2→3)
- Multiple precompute tables → One prediction processor

**Phase 5 → Phase 6:** **1:1** (Simple)
- Predictions ready → Publish to web formats
- Direct mapping, straightforward

---

## Addressing Concern 1: Dependency Coordination

### The Opportunistic Triggering Pattern

**Design Decision:** Every Phase 2 update triggers Phase 3, which checks if dependencies are ready.

**How It Works:**

```python
# Phase 2 publishes event:
{
  "event_type": "raw_data_loaded",
  "source_table": "nbac_gamebook_player_stats",
  "game_date": "2025-11-15"
}

# Phase 3 analytics service receives:
def process_analytics_event(message):
    source_table = message['source_table']
    game_date = message['game_date']

    # Look up which processors need this table
    processors = ANALYTICS_TRIGGERS[source_table]
    # → [PlayerGameSummaryProcessor, TeamOffenseProcessor, ...]

    for ProcessorClass in processors:
        processor = ProcessorClass()

        # Processor checks its dependencies
        processor.run({'game_date': game_date})
```

**Inside the processor:**

```python
class PlayerGameSummaryProcessor(AnalyticsProcessorBase):
    def run(self, opts):
        # 1. Check if already processed recently (idempotency)
        if self._already_processed_recently(opts['game_date']):
            logger.info("Already processed, skipping")
            return

        # 2. Check if ALL dependencies are ready
        dep_check = self.check_dependencies(
            opts['game_date'],
            opts['game_date']
        )

        # 3. If critical dependencies missing → SKIP
        if not dep_check['all_critical_present']:
            logger.warning(f"Missing dependencies: {dep_check['missing']}")
            return  # Will retry when next dependency loads

        # 4. If dependencies ready → PROCESS
        logger.info("All dependencies ready, processing...")
        self.process_data()
```

### Concrete Example Timeline

**Scenario:** 10 games played on 2025-11-15, `PlayerGameSummaryProcessor` needs 6 tables

```
10:00 PM - Games end

10:05 PM - nbac_gamebook_player_stats loads
           ├─ Publishes: "nbac_gamebook_player_stats updated"
           ├─ Triggers: PlayerGameSummaryProcessor
           ├─ check_dependencies() runs:
           │   ✅ nbac_gamebook_player_stats: EXISTS
           │   ❌ bdl_player_boxscores: MISSING (CRITICAL!)
           │   ❌ Other 4 tables: MISSING
           └─ Result: SKIP "Waiting for bdl_player_boxscores"

10:10 PM - bdl_player_boxscores loads
           ├─ Publishes: "bdl_player_boxscores updated"
           ├─ Triggers: PlayerGameSummaryProcessor (again!)
           ├─ check_dependencies() runs:
           │   ✅ nbac_gamebook_player_stats: EXISTS (loaded at 10:05)
           │   ✅ bdl_player_boxscores: EXISTS (just loaded)
           │   ❌ bigdataball_play_by_play: MISSING (optional - OK!)
           │   ❌ Other 3 tables: MISSING (optional - OK!)
           │   ✓ ALL CRITICAL DEPENDENCIES MET!
           └─ Result: PROCESS ✅
               ├─ Processes 450 player records for 2025-11-15
               ├─ Takes ~30 seconds
               └─ Publishes to Phase 4

10:15 PM - bigdataball_play_by_play loads (optional data)
           ├─ Publishes: "bigdataball_play_by_play updated"
           ├─ Triggers: PlayerGameSummaryProcessor (again!)
           ├─ Idempotency check:
           │   Query: "Did I process 2025-11-15 in last hour?"
           │   Result: YES (processed at 10:10, only 5 minutes ago)
           └─ Result: SKIP "Already processed recently"
```

**Key Insights:**
- ✅ Automatic retry mechanism (each Phase 2 update triggers Phase 3)
- ✅ No complex state management needed
- ✅ Can process with critical dependencies only
- ✅ Optional dependencies enhance but don't block
- ✅ Idempotency prevents duplicate processing

**Benefits:**
- **Real-time:** Process as soon as dependencies ready (not waiting for ALL 6 tables)
- **Resilient:** Automatic retries via event-driven architecture
- **Simple:** No coordination service needed, just check dependencies on each trigger
- **Flexible:** Can process with subset of dependencies (critical vs optional)

---

## Addressing Concern 2: Incremental vs Full Updates

### Entity-Level Granularity Design

**The Problem with Date-Level Processing:**

```python
# Current approach (simple but wasteful):
processor.run({'game_date': '2025-11-15'})
# → Processes ALL 450 players for that date
# → Takes 30 seconds
# → Even if only LeBron changed!
```

**The Solution: Entity-Level Updates**

### Enhanced Message Format

**Phase 2 publishes with affected entities:**

```json
{
  "event_type": "raw_data_loaded",
  "source_table": "nbac_injury_report",
  "game_date": "2025-11-15",

  "affected_entities": {
    "players": ["1630567"],           // LeBron's universal_player_id
    "teams": ["LAL"],                 // Lakers
    "games": ["0022500225"]           // LAL vs BOS game
  },

  "change_type": "incremental",       // or "full_load"
  "record_count": 1,
  "timestamp": "2025-11-15T14:30:00Z"
}
```

### Enhanced Processor Support

**Phase 3 processors accept granular parameters:**

```python
class PlayerGameSummaryProcessor(AnalyticsProcessorBase):
    def run(self, opts):
        """
        Supports multiple processing modes:

        - Full date range: {'start_date': '2025-11-15', 'end_date': '2025-11-15'}
        - Specific players: {'game_date': '2025-11-15', 'player_ids': ['1630567']}
        - Specific games: {'game_date': '2025-11-15', 'game_ids': ['0022500225']}
        - Specific teams: {'game_date': '2025-11-15', 'team_ids': ['LAL']}
        """

        # Determine scope
        if 'player_ids' in opts:
            # Process only specified players
            self.process_players(opts['player_ids'])
            logger.info(f"Processed {len(opts['player_ids'])} players")

        elif 'game_ids' in opts:
            # Process all players in specified games
            self.process_games(opts['game_ids'])

        else:
            # Full date range processing
            self.process_date_range(opts['start_date'], opts['end_date'])
```

### Real-World Example: Injury Update

**Scenario:** LeBron ruled OUT at 2:00 PM (pre-game)

```
2:00 PM - Injury scraper detects change

Phase 1: nbac_injury_report scraper
  └─ Publishes: {scraper: "nbac_injury_report", ...}

Phase 2: NbacInjuryReportProcessor
  ├─ Loads 1 record to nba_raw.nbac_injury_report
  └─ Publishes:
      {
        "source_table": "nbac_injury_report",
        "affected_entities": {
          "players": ["1630567"],    // LeBron
          "games": ["0022500225"]    // LAL vs BOS
        },
        "change_type": "incremental"
      }

Phase 3: PlayerGameSummaryProcessor receives
  ├─ Extracts: player_ids = ["1630567"]
  ├─ Processes ONLY LeBron's record
  ├─ Takes 0.5 seconds (not 30 seconds!)
  └─ Publishes:
      {
        "affected_entities": {
          "players": ["1630567"],
          "games": ["0022500225"]
        }
      }

Phase 4: PlayerDailyCacheProcessor receives
  ├─ Extracts: player_ids = ["1630567"]
  ├─ Updates ONLY LeBron's precomputed features
  ├─ Takes 1 second
  └─ Publishes: {...}

Phase 5: PredictionProcessor receives
  ├─ Extracts: game_ids = ["0022500225"]
  ├─ Re-runs predictions for ONLY LAL vs BOS game
  ├─ Doesn't re-run other 9 games
  ├─ Takes 2 seconds
  └─ Publishes: {...}

Phase 6: PublishingService receives
  ├─ Publishes updated prediction for game 0022500225
  └─ Firestore + GCS updated with new data

Total time: ~4 seconds (vs 2+ minutes for full processing)
```

**Performance Comparison:**

| Approach | LeBron Injury Update | Full Boxscore Load |
|----------|----------------------|---------------------|
| Date-level | 30s (all 450 players) | 30s (all 450 players) |
| Entity-level | 0.5s (1 player) | 30s (all 450 players) |
| **Speedup** | **60x faster** | **Same** |

### Implementation Strategy

**Phase 1: Ship with Date-Level (Weeks 1-4)**
```python
# Simple, working implementation
processor.run({'game_date': '2025-11-15'})
```

**Benefits:**
- Ships quickly
- Proven pattern
- Works correctly
- Can measure actual performance

**Phase 2: Add Game-Level Granularity (Weeks 5-6)**
```python
# Add game filtering
processor.run({
    'game_date': '2025-11-15',
    'game_ids': ['0022500225', '0022500226']
})
```

**Benefits:**
- Reduces scope significantly
- Still relatively simple
- Good for live game updates

**Phase 3: Add Entity-Level Granularity (Weeks 7-8)**
```python
# Full granular control
processor.run({
    'game_date': '2025-11-15',
    'player_ids': ['1630567'],     # Just LeBron
    'team_ids': ['LAL'],            # Or Lakers
    'game_ids': ['0022500225']      # Or specific game
})
```

**Benefits:**
- Maximum efficiency
- Perfect for incremental updates
- Optimize based on real metrics

**Recommendation:** Progressive enhancement - ship simple first, optimize based on actual usage patterns.

---

## Addressing Concern 3: Pub/Sub Multi-Subscriber Pattern

### How Pub/Sub Enables Fan-Out

**Traditional Queue (NOT what we're using):**
```
Message → Queue → Consumer A reads → Message DELETED
                                   → Consumer B: "Message gone!"
```

**Pub/Sub Pattern (WHAT WE'RE USING):**
```
Message → Topic → Subscription A → Consumer A reads ✅
               ├→ Subscription B → Consumer B reads ✅
               └→ Subscription C → Consumer C reads ✅

Each subscriber gets their own COPY of the message!
```

### Our Implementation

**One Phase 2 event triggers multiple Phase 3 processors:**

```python
# Phase 2 publishes ONE message
{
  "source_table": "bdl_player_boxscores",
  "game_date": "2025-11-15"
}

# Phase 3 analytics service routing table
ANALYTICS_TRIGGERS = {
    'bdl_player_boxscores': [
        PlayerGameSummaryProcessor,   # Processor 1
        TeamOffenseProcessor,         # Processor 2
        TeamDefenseProcessor          # Processor 3
    ]
}

# Analytics service receives message and triggers all three
@app.route('/process', methods=['POST'])
def process_analytics():
    message = decode_pubsub_message(request)
    source_table = message['source_table']

    # Get list of processors for this source table
    processors = ANALYTICS_TRIGGERS.get(source_table, [])

    # Run each processor independently
    for ProcessorClass in processors:
        try:
            processor = ProcessorClass()
            processor.run({'game_date': message['game_date']})
        except Exception as e:
            # One failure doesn't stop others
            logger.error(f"{ProcessorClass.__name__} failed: {e}")

    # Return 200 → Pub/Sub acknowledges message
    return jsonify({"status": "completed"}), 200
```

### Key Benefits

**1. One Message → Many Consumers**
- Phase 2 publishes once
- Multiple Phase 3 processors receive it
- No duplicate message publishing needed

**2. Independent Execution**
- Each processor runs independently
- One failure doesn't block others
- Each has its own retry logic

**3. Future Extensibility**
- Want to add monitoring? Add new subscription
- Want to track lineage? Add another subscription
- Original system unaffected

**4. Reliability**
```
If Processor A fails:
  ├─ Processors B and C still succeed
  ├─ Message acknowledged (B and C worked)
  ├─ Processor A can be retried separately
  └─ System keeps moving forward
```

### Multiple Subscriptions (Advanced)

**Can also use separate subscriptions for different purposes:**

```
nba-raw-data-complete (topic)
    │
    ├─→ nba-analytics-sub (subscription)
    │   └─→ Analytics Service
    │       ├─→ PlayerGameSummaryProcessor
    │       ├─→ TeamOffenseProcessor
    │       └─→ TeamDefenseProcessor
    │
    ├─→ nba-monitoring-sub (subscription)
    │   └─→ Monitoring Service
    │       └─→ Log all data loads
    │
    └─→ nba-audit-sub (subscription)
        └─→ Audit Service
            └─→ Track data lineage
```

**Each subscription:**
- Gets its own copy
- Independent acknowledgment
- Independent retry/DLQ
- Can be added without affecting others

---

## Addressing Concern 4: End-to-End Observability

### The Challenge: Silent Partial Failures

**What we need to detect:**

```
Phase 1 ✅ → Phase 2 ✅ → Phase 3 ✅ → Phase 4 ❌ → Phase 5 ⏸️ → Phase 6 ⏸️
                                        │
                                        └─ Pipeline stalled here!
                                           Need to know:
                                           - What failed?
                                           - Why did it fail?
                                           - Which data is affected?
                                           - Can we retry?
```

### Solution 1: Pub/Sub Automatic Retry & DLQ

**How Pub/Sub handles failures:**

```
Phase 4 receives message → Processing error occurs → Returns 500
    ↓
Pub/Sub: "Not acknowledged, will retry"
    ↓
Retry #1 (after 10 seconds) → Still fails
Retry #2 (after 30 seconds) → Still fails
Retry #3 (after 1 minute) → Still fails
Retry #4 (after 3 minutes) → Still fails
Retry #5 (after 7 minutes) → Still fails
    ↓
Move to Dead Letter Queue (DLQ)
    ↓
Message preserved for 7 days
Can be replayed when issue is fixed
```

**Configuration:**
```bash
gcloud pubsub subscriptions create nba-precompute-sub \
  --topic=nba-analytics-complete \
  --push-endpoint=https://nba-precompute-processors-.../process \
  --ack-deadline=600 \
  --max-delivery-attempts=5 \
  --dead-letter-topic=nba-analytics-complete-dlq
```

**Answer:** ✅ YES, messages are preserved for retry via DLQ

### Solution 2: Pipeline Execution Tracking

**Central tracking table:**

```sql
CREATE TABLE nba_orchestration.pipeline_execution_log (
    -- Unique identifiers
    execution_id STRING,              -- This specific execution
    correlation_id STRING,            -- Links entire pipeline run
    source_execution_id STRING,       -- What triggered this

    -- What & When
    phase INT64,                      -- 1, 2, 3, 4, 5, 6
    processor_name STRING,
    event_type STRING,

    -- Context
    game_date DATE,
    affected_entities JSON,           -- Which players/teams/games

    -- Status
    status STRING,                    -- 'started', 'completed', 'failed', 'skipped'
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_seconds FLOAT64,

    -- Dependency tracking
    dependencies_met BOOL,
    missing_dependencies ARRAY<STRING>,

    -- Error details
    error_type STRING,
    error_message STRING,
    retry_count INT64,

    -- Metrics
    records_processed INT64,

    -- Metadata
    pubsub_message_id STRING,
    metadata JSON
)
PARTITION BY game_date
CLUSTER BY correlation_id, phase, status;
```

### The Correlation ID Pattern

**Every event carries a correlation_id through the entire pipeline:**

```
Phase 1: Scraper runs
  ├─ Generates: correlation_id = "abc123"
  ├─ Logs: {correlation_id: "abc123", phase: 1, status: 'completed'}
  └─ Publishes: {correlation_id: "abc123", ...}

Phase 2: Receives event
  ├─ Extracts: correlation_id = "abc123"
  ├─ Logs: {correlation_id: "abc123", phase: 2, status: 'completed'}
  └─ Publishes: {correlation_id: "abc123", ...}

Phase 3: Receives event
  ├─ Extracts: correlation_id = "abc123"
  ├─ Logs: {correlation_id: "abc123", phase: 3, status: 'completed'}
  └─ Publishes: {correlation_id: "abc123", ...}

Phase 4: Receives event
  ├─ Extracts: correlation_id = "abc123"
  ├─ Logs: {correlation_id: "abc123", phase: 4, status: 'failed',
  │         error: "Connection timeout"}
  └─ ❌ Fails - doesn't publish

Phase 5: Never receives (waiting for Phase 4)
Phase 6: Never receives (waiting for Phase 5)
```

**Now we can query end-to-end:**

```sql
-- Track entire pipeline for correlation_id "abc123"
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

-- Result shows exactly where it stopped:
-- phase | processor_name              | status    | error_message
-- ------|----------------------------|-----------|------------------
-- 1     | NbacInjuryReportScraper    | completed | NULL
-- 2     | NbacInjuryReportProcessor  | completed | NULL
-- 3     | PlayerGameSummaryProcessor | completed | NULL
-- 4     | PlayerDailyCacheProcessor  | failed    | Connection timeout
-- (no Phase 5, no Phase 6 - stuck at Phase 4!)
```

**Answer:** ✅ YES, we can detect exactly what failed and where the pipeline stopped

### Solution 3: Detecting Incomplete Pipelines

**Monitor query to find stuck pipelines:**

```sql
-- Find pipelines that didn't complete end-to-end
WITH pipeline_status AS (
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
SELECT *
FROM pipeline_status
WHERE max_phase_reached < 6  -- Should reach Phase 6 (publishing)
   OR failure_count > 0
ORDER BY max_phase_reached ASC;
```

**Results show incomplete pipelines:**
```
correlation_id | game_date  | max_phase | failures
---------------|------------|-----------|----------
abc123         | 2025-11-15 | 4         | [{phase: 4, error: "Timeout"}]
def456         | 2025-11-15 | 3         | [{phase: 3, error: "Invalid data"}]
```

**Answer:** ✅ YES, we can detect that changes didn't reach Phase 5/6

### Solution 4: Entity-Level Tracking

**Track specific entities through pipeline:**

```sql
-- Did LeBron's injury update reach Phase 6?
SELECT
    phase,
    processor_name,
    status,
    started_at,
    JSON_EXTRACT_SCALAR(affected_entities, '$.players[0]') as player_id
FROM nba_orchestration.pipeline_execution_log
WHERE game_date = '2025-11-15'
  AND JSON_EXTRACT_SCALAR(affected_entities, '$.players[0]') = '1630567'
ORDER BY phase, started_at;

-- Result shows LeBron's journey:
-- phase | processor              | status    | player_id
-- ------|------------------------|-----------|----------
-- 1     | NbacInjuryReportScraper| completed | 1630567
-- 2     | NbacInjuryReportProc   | completed | 1630567
-- 3     | PlayerGameSummaryProc  | completed | 1630567
-- 4     | PlayerDailyCacheProc   | failed    | 1630567  ← STUCK
```

**Can answer specific questions:**
- "Did LeBron's injury update reach the web app?" → NO (stuck at Phase 4)
- "Which updates completed end-to-end today?" → Query where max_phase = 6
- "What's the average time from scraper to web app?" → AVG(duration) by phase

### Solution 5: Automated Monitoring & Alerts

**Grafana Dashboard Panels:**

```sql
-- Panel 1: Pipeline Health Overview
SELECT
    COUNT(DISTINCT correlation_id) as total_pipelines,
    COUNTIF(max_phase = 6) as completed,
    COUNTIF(max_phase < 6) as incomplete,
    COUNTIF(has_failures) as failed
FROM (
    SELECT
        correlation_id,
        MAX(phase) as max_phase,
        COUNTIF(status = 'failed') > 0 as has_failures
    FROM pipeline_execution_log
    WHERE game_date = CURRENT_DATE()
    GROUP BY correlation_id
);

-- Panel 2: Recent Failures
SELECT
    phase,
    processor_name,
    error_type,
    COUNT(*) as count,
    MAX(started_at) as last_occurrence
FROM pipeline_execution_log
WHERE status = 'failed'
  AND started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY phase, processor_name, error_type
ORDER BY count DESC;

-- Panel 3: DLQ Status
-- (Queried via gcloud command)
gcloud pubsub subscriptions describe nba-phase3-analytics-complete-dlq-sub \
  --format="value(numUndeliveredMessages)"
```

**Automated Alerts:**

```python
def check_pipeline_health():
    """Alert on pipeline issues."""

    # Alert 1: DLQ has messages
    for dlq in ALL_DLQS:
        if get_message_count(dlq) > 0:
            notify_error(
                title=f"🚨 DLQ Alert: {dlq}",
                message=f"Messages in Dead Letter Queue - failures detected"
            )

    # Alert 2: Stuck pipelines
    stuck = query_stuck_pipelines()
    if stuck:
        notify_error(
            title="🚨 Stuck Pipelines Detected",
            message=f"{len(stuck)} pipelines didn't reach Phase 6",
            details=stuck
        )

    # Alert 3: High failure rate
    failure_rate = get_failure_rate_today()
    if failure_rate > 0.05:  # > 5%
        notify_warning(
            title="⚠️ High Failure Rate",
            message=f"Failure rate: {failure_rate*100:.1f}%"
        )
```

### Recovery Procedures

**Scenario 1: Transient Error (Temporary timeout)**

```bash
# 1. Issue resolves itself (BigQuery back online)
# 2. DLQ messages can be replayed
gcloud pubsub subscriptions pull nba-analytics-complete-dlq-sub --limit=10

# 3. Manually republish or use replay script
python replay_dlq.py --dlq=nba-analytics-complete-dlq-sub --limit=100

# 4. Monitor pipeline completion
```

**Scenario 2: Code Bug**

```bash
# 1. Identify bug from error messages
# 2. Fix and deploy
# 3. Replay DLQ messages (will use new code)
# 4. Verify completion
```

**Scenario 3: Data Quality Issue**

```bash
# 1. Identify bad data in upstream phase
# 2. Fix upstream data
# 3. Trigger re-processing from that phase
python replay_pipeline.py --correlation-id=abc123 --start-phase=3

# 4. Monitor downstream propagation
```

---

## Addressing Concern 5: Phase 6 Publishing Layer

### Architecture

**Purpose:** Transform BigQuery predictions into web-optimized formats

```
Phase 5 (Predictions) → BigQuery tables
    ↓
    Pub/Sub: "predictions_ready" event
    ↓
Phase 6 (Publishing Service)
    ├─→ Fetch from BigQuery
    ├─→ Transform to web-friendly JSON
    ├─→ Publish to Firestore (real-time)
    ├─→ Publish to GCS (cacheable, CDN)
    └─→ Update metadata

Web App
    ├─→ Read from Firestore (live updates)
    └─→ Read from GCS (cached, fast)
```

### Message Format (Phase 5 → Phase 6)

```json
{
  "event_type": "predictions_ready",
  "prediction_type": "game_predictions",
  "game_date": "2025-11-15",
  "game_ids": ["0022500225", "0022500226"],
  "affected_entities": {
    "games": ["0022500225"],
    "players": ["1630567"]
  },
  "prediction_count": 24,
  "model_version": "ensemble_v2.1",
  "confidence_threshold": 0.65,
  "correlation_id": "abc123"
}
```

### Publishing Service Implementation

```python
class PublishingService:
    """Phase 6: Publish predictions to Firestore and GCS."""

    def process_predictions_ready(self, message):
        """Handle predictions_ready event."""

        game_date = message['game_date']
        game_ids = message['game_ids']
        correlation_id = message['correlation_id']

        # Log start
        self.log_pipeline_execution('started', correlation_id, phase=6)

        try:
            # 1. Fetch predictions from BigQuery
            predictions = self.fetch_predictions(game_date, game_ids)

            # 2. Transform to web format
            web_data = self.transform_for_web(predictions)

            # 3. Publish to Firestore (real-time)
            self.publish_to_firestore(web_data)

            # 4. Publish to GCS (cacheable)
            self.publish_to_gcs(web_data)

            # 5. Update metadata
            self.update_publish_timestamp(game_date)

            # Log success
            self.log_pipeline_execution('completed', correlation_id, phase=6)

            return True

        except Exception as e:
            # Log failure
            self.log_pipeline_execution('failed', correlation_id, phase=6, error=e)
            raise

    def transform_for_web(self, predictions):
        """Transform BigQuery schema to web-friendly JSON."""
        return {
            "games": [
                {
                    "game_id": "0022500225",
                    "teams": {
                        "home": "Lakers",
                        "away": "Celtics"
                    },
                    "predictions": {
                        "winner": "Lakers",
                        "confidence": 0.72,
                        "spread": -5.5
                    }
                }
            ],
            "player_props": [...],
            "meta": {
                "generated_at": "2025-11-15T17:00:00Z",
                "model_version": "ensemble_v2.1"
            }
        }
```

### Publishing Formats

**Firestore Structure:**
```
/predictions
    /daily
        /2025-11-15
            games: [...],
            player_props: [...],
            meta: {...}

    /games
        /0022500225
            teams: {...},
            predictions: {...},
            player_props: [...]

    /players
        /1630567
            props: [...],
            recent_performance: {...}
```

**GCS Structure:**
```
gs://nba-predictions-public/
    latest/
        daily.json
        games/
            0022500225.json
            0022500226.json
        players/
            1630567.json

    historical/
        2025-11-15/
            daily.json
            games/...

    api/
        v1/
            daily/latest.json
            games/{game_id}.json
```

### Benefits

**1. Optimized for Reads**
- Pre-computed, denormalized
- No complex joins needed
- Fast CDN caching (GCS)
- Real-time updates (Firestore)

**2. Security**
- Web app doesn't query BigQuery directly
- Can filter sensitive fields
- Can add authentication layer

**3. Versioning**
- Can publish multiple versions (v1, v2)
- Can A/B test model outputs
- Can roll back if needed

**4. Decoupling**
- Prediction schema changes don't break web app
- Can transform format without re-running predictions
- Can add new fields incrementally

---

## Implementation Roadmap

**For complete prioritized implementation roadmap**, see [05-implementation-status-and-roadmap.md](./05-implementation-status-and-roadmap.md).

### Quick Summary: 8-Sprint Plan (~73 hours total)

**Sprint 1 (Week 1):** Phase 2→3 Connection (~5 hrs) - **Highest priority**
- Add Pub/Sub publishing to Phase 2 processors
- Create infrastructure (topic, subscription, DLQ)
- Test end-to-end flow

**Sprint 2 (Week 1-2):** Correlation ID Tracking (~8 hrs)
- Implement correlation_id propagation through all phases
- Create unified `pipeline_execution_log` table
- Enable end-to-end tracing

**Sprint 3 (Week 2):** Phase 3→4 Connection (~8 hrs)
- Extend pattern to precompute layer
- Complete Phase 4 orchestration service

**Sprint 4-8:** Monitoring, Phase 4→5→6, Entity-level granularity

**Current Status:** ~45% complete (Phase 1→2 working 100%, verified 2025-11-15)

---

## Key Design Decisions Summary

### Decision 1: Opportunistic Triggering
**Choice:** Trigger Phase 3 on ANY Phase 2 update, check dependencies each time

**Rationale:**
- Automatic retry mechanism
- No complex state management
- Real-time processing when ready
- Simple to implement and understand

### Decision 2: Progressive Granularity
**Choice:** Ship date-level first, add entity-level later

**Rationale:**
- Ship working system quickly
- Optimize based on real metrics
- Avoid over-engineering
- Can measure actual benefit

### Decision 3: correlation_id Tracking
**Choice:** Flow correlation_id through entire pipeline

**Rationale:**
- End-to-end visibility
- Easy debugging
- Clear data lineage
- Simple implementation

### Decision 4: Pub/Sub with DLQ
**Choice:** Use Pub/Sub push subscriptions with Dead Letter Queues

**Rationale:**
- Automatic retries (handles transient errors)
- Message preservation (can replay)
- Multi-subscriber support (fan-out)
- Proven reliability

### Decision 5: Central Execution Log
**Choice:** Single `pipeline_execution_log` table for all phases

**Rationale:**
- Unified monitoring
- Easy cross-phase queries
- Clear pipeline status
- Simple alerting

---

## Conclusion

This architecture addresses all user concerns through a combination of:

1. **Opportunistic triggering** - Balances real-time processing with dependency requirements
2. **Entity-level granularity** - Enables efficient incremental updates
3. **Pub/Sub fan-out** - Multiple consumers can use the same message
4. **End-to-end tracking** - correlation_id provides complete visibility
5. **Automatic retry with DLQ** - Messages never lost, can always recover
6. **Comprehensive monitoring** - Detect issues at any phase
7. **Phase 6 publishing** - Optimized web app data access

The system is designed to be **efficient** (incremental updates), **reliable** (automatic retries, DLQ), and **observable** (end-to-end tracking), while maintaining simplicity through progressive enhancement.

**Next Steps:** Begin Phase 1 implementation with date-level granularity, full monitoring, and end-to-end tracking.

---

**Last Updated:** 2025-12-27
**Status:** v1.0 Deployed - All 6 Phases Production Ready
**Related Documents:**
- [SYSTEM_STATUS.md](../00-start-here/SYSTEM_STATUS.md) - Current deployment status
- [Orchestrator docs](./orchestration/) - v1.0 Pub/Sub orchestration
- `monitoring-error-handling-design.md` - Monitoring deep dive
