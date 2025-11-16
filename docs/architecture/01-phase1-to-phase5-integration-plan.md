# Phase 1-5 Event-Driven Integration Plan

**File:** `docs/architecture/01-phase1-to-phase5-integration-plan.md`
**Created:** 2025-11-14 22:03 PST
**Last Updated:** 2025-11-15 (Status update, content reduction)
**Purpose:** Detailed integration plan for Phase 2→3 connection with dependency coordination
**Status:** Partially Implemented - See [05-implementation-status-and-roadmap.md](./05-implementation-status-and-roadmap.md) for current gaps
**Related:** [04-event-driven-pipeline-architecture.md](./04-event-driven-pipeline-architecture.md) (comprehensive architecture)

---

## Table of Contents

1. [Current State Assessment](#current-state-assessment)
2. [Dependency Graph](#dependency-graph)
3. [Key Architectural Challenges](#key-architectural-challenges)
4. [Proposed Solutions](#proposed-solutions)
5. [Implementation Roadmap](#implementation-roadmap)
6. [Open Questions](#open-questions)

---

## Current State Assessment

### Phase 1 → Phase 2: ✅ FULLY IMPLEMENTED

**Status:** Production, working correctly

**How it works:**
```
Scraper runs → Writes GCS file → Publishes Pub/Sub event → Processor receives → Loads to BigQuery raw
```

**Implementation:**
- **Scrapers:** All inherit from `ScraperBase` which automatically publishes to `nba-scraper-complete` topic
- **Pub/Sub:** Push subscription `nba-processors-sub` sends to `nba-processors` Cloud Run service
- **Processors:** `main_processor_service.py` routes messages to appropriate processor class
- **Message format:**
  ```json
  {
    "name": "nbac_injury_report",
    "scraper_name": "nbac_injury_report",
    "execution_id": "a1b2c3d4",
    "status": "success|no_data|failed",
    "gcs_path": "gs://bucket/path/file.json",
    "record_count": 450,
    "timestamp": "2025-11-15T00:00:00Z",
    "workflow": "morning_operations"
  }
  ```

**Evidence:**
- 1,482 events in past 3 hours
- 100% delivery rate
- Full documentation in `docs/orchestration/pubsub-integration-status-2025-11-15.md`

### Phase 2 → Phase 3: ⚠️ PARTIALLY IMPLEMENTED

**Status:** Infrastructure exists, but NOT connected via Pub/Sub

**What EXISTS:**

1. **Analytics Service** (`data_processors/analytics/main_analytics_service.py`)
   - Cloud Run service ready to receive Pub/Sub messages
   - Has `ANALYTICS_TRIGGERS` registry mapping Phase 2 tables → Phase 3 processors
   - Example:
     ```python
     ANALYTICS_TRIGGERS = {
         'nbac_gamebook_player_stats': [PlayerGameSummaryProcessor],
         'bdl_player_boxscores': [PlayerGameSummaryProcessor, TeamOffenseProcessor],
         'nbac_scoreboard_v2': [TeamOffenseProcessor, TeamDefenseProcessor],
     }
     ```

2. **Dependency Tracking** (`data_processors/analytics/analytics_base.py`)
   - Each Phase 3 processor defines dependencies via `get_dependencies()`
   - `check_dependencies()` validates Phase 2 data exists and is fresh
   - Example from `PlayerGameSummaryProcessor`:
     ```python
     def get_dependencies(self):
         return {
             'nba_raw.nbac_gamebook_player_stats': {
                 'critical': True,
                 'expected_count_min': 200,
                 'max_age_hours_fail': 24
             },
             'nba_raw.bdl_player_boxscores': {
                 'critical': True  # Fallback for stats
             },
             # ... 4 more dependencies
         }
     ```

**What's MISSING:**

1. ❌ **Phase 2 processors don't publish Pub/Sub events**
   - Need to add publishing code to each processor
   - Need to define message format

2. ❌ **No Pub/Sub topic/subscription for Phase 2 → Phase 3**
   - Need to create topic (e.g., `nba-raw-data-complete`)
   - Need to create subscription pointing to analytics service

3. ❌ **Coordination mechanism not implemented**
   - How do we wait for ALL required dependencies?
   - When do we trigger the analytics processor?

### Phase 3 → Phase 4: ❓ STATUS UNKNOWN

**Need to investigate:**
- Does Phase 4 precompute exist?
- If so, how should it be triggered?
- Same coordination challenges as Phase 2 → Phase 3

### Phase 4 → Phase 5: ❓ STATUS UNKNOWN

**Need to investigate:**
- How are predictions triggered?
- Daily batch? Event-driven? Manual?
- What are dependencies?

---

## Dependency Graph

### Phase 2 → Phase 3 Dependencies

**Player Game Summary** (Phase 3) depends on **6 Phase 2 tables:**

```
Phase 2 (Raw)                          Phase 3 (Analytics)
───────────────────────────────────    ────────────────────────
nba_raw.nbac_gamebook_player_stats ┐
                                    │
nba_raw.bdl_player_boxscores       ├──→ nba_analytics.player_game_summary
                                    │
nba_raw.bigdataball_play_by_play   │
                                    │
nba_raw.nbac_play_by_play          │
                                    │
nba_raw.odds_api_player_points_props│
                                    │
nba_raw.bettingpros_player_points_props┘
```

**Team Offense Summary** (Phase 3) depends on **3 Phase 2 tables:**

```
Phase 2 (Raw)                          Phase 3 (Analytics)
───────────────────────────────────    ────────────────────────
nba_raw.bdl_player_boxscores ┐
                              │
nba_raw.nbac_scoreboard_v2   ├──→ nba_analytics.team_offense_game_summary
                              │
nba_raw.nbac_team_stats      ┘
```

**Key Insight:** Phase 3 processors have **many-to-one** dependencies, unlike Phase 1 → Phase 2 which is **one-to-one**.

### Reverse Dependency Map

**When a Phase 2 table updates, which Phase 3 processors should run?**

```
nbac_gamebook_player_stats updated ──→ Trigger: PlayerGameSummaryProcessor

bdl_player_boxscores updated ──→ Trigger: PlayerGameSummaryProcessor
                                         TeamOffenseProcessor
                                         TeamDefenseProcessor

nbac_scoreboard_v2 updated ──→ Trigger: TeamOffenseProcessor
                                        TeamDefenseProcessor

odds_api_player_points_props updated ──→ Trigger: PlayerGameSummaryProcessor
```

---

## Key Architectural Challenges

### Challenge 1: Dependency Coordination

**Problem:** Phase 3 processors need MULTIPLE Phase 2 tables. How do we know when all dependencies are ready?

**Example Scenario:**
- `PlayerGameSummaryProcessor` needs 6 Phase 2 tables
- Scraper A completes → Phase 2 processor A loads table 1 → Pub/Sub event published
- Scraper B completes → Phase 2 processor B loads table 2 → Pub/Sub event published
- ... (4 more tables)
- **Question:** When do we trigger `PlayerGameSummaryProcessor`?

**Options:**

**Option A: Trigger on ANY dependency update (Opportunistic)**
- Phase 2 processor publishes: "table X updated for game_date Y"
- Analytics service receives event
- Checks if ALL dependencies are ready via `check_dependencies()`
- If ready → process, if not → skip

**Pros:**
- Simple implementation
- Works for both initial load and incremental updates
- Leverages existing `check_dependencies()` method

**Cons:**
- May trigger analytics processor multiple times unnecessarily
- Need idempotency (don't re-process if already done)

**Option B: Dependency Aggregation Service (Complex)**
- Track which dependencies have completed
- Only trigger when ALL critical dependencies ready
- Store state in BigQuery or Cloud Storage

**Pros:**
- More efficient (only process when ready)
- Better visibility into dependency status

**Cons:**
- More complex implementation
- Need state management
- Risk of missing triggers if state tracking fails

**Option C: Time-Based Batching (Simple but Less Real-Time)**
- Phase 3 processors run on schedule (e.g., every hour)
- Check dependencies and process if ready
- Don't use Pub/Sub at all for Phase 2 → Phase 3

**Pros:**
- Very simple
- Works reliably
- No coordination needed

**Cons:**
- Higher latency (wait for next batch)
- Less real-time
- Still need to determine WHICH entities to process

**RECOMMENDATION:** Start with **Option A** (Opportunistic) + idempotency

### Challenge 2: Initial Load vs Incremental Updates

**Problem:** First time vs subsequent runs have different needs.

**Initial Load (Backfill):**
- Process ALL players/teams
- May take hours
- Need to ensure completeness

**Incremental Update:**
- Process only affected entities
- Should be fast
- Need to identify WHAT changed

**Questions:**
1. How do we know WHICH players/teams were affected by a Phase 2 update?
2. Should Phase 2 publish "game_date: 2025-11-15" or "player_ids: [123, 456]"?
3. Do we re-process the entire game_date or just specific entities?

**Example:**
- `nbac_gamebook_player_stats` updates for game LAL vs BOS on 2025-11-15
- This affects ~25 players (12 LAL + 13 BOS)
- Should we:
  - A) Re-run `PlayerGameSummaryProcessor` for ALL players in DB? (slow)
  - B) Re-run for just game_date 2025-11-15? (medium)
  - C) Re-run for just the 25 affected players? (fast, complex)

**RECOMMENDATION:**
- **For now:** Process by `game_date` (Option B)
- **Future:** Add entity-level tracking (Option C) for efficiency

### Challenge 3: Idempotency & Duplicate Prevention

**Problem:** Multiple Phase 2 updates may trigger the same Phase 3 processor.

**Example:**
1. `bdl_player_boxscores` updated for 2025-11-15 → Triggers `PlayerGameSummaryProcessor`
2. `nbac_gamebook_player_stats` updated for 2025-11-15 → Triggers `PlayerGameSummaryProcessor` AGAIN

**How do we prevent duplicate processing?**

**Options:**

**Option A: Check if already processed**
```python
# Before processing, check if output already exists
result = bq.query(f"""
    SELECT COUNT(*) as count
    FROM nba_analytics.player_game_summary
    WHERE game_date = '{game_date}'
      AND updated_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
""")
if result.count > 0:
    logger.info("Already processed recently, skipping")
    return
```

**Option B: Processing Run Log**
```python
# Track each processing run
INSERT INTO nba_orchestration.analytics_processing_log (
    processor_name,
    game_date,
    started_at,
    status,
    run_id
)
VALUES ('PlayerGameSummaryProcessor', '2025-11-15', NOW(), 'in_progress', 'abc123')

# Before starting, check if already in progress or recently completed
```

**Option C: Pub/Sub Message Deduplication**
- Use Pub/Sub's message deduplication (10-minute window)
- Not sufficient for our use case (need longer windows)

**RECOMMENDATION:** Combine Option A + Option B

### Challenge 4: Pub/Sub Message Format

**Problem:** What information should Phase 2 processors publish?

**Proposal:**

```json
{
  "event_type": "raw_data_loaded",
  "source_table": "nbac_gamebook_player_stats",
  "target_table": "nba_raw.nbac_gamebook_player_stats",
  "processor_name": "NbacGamebookProcessor",
  "execution_id": "xyz789",
  "game_date": "2025-11-15",
  "game_ids": ["0022500225", "0022500226"],
  "record_count": 450,
  "status": "success",
  "timestamp": "2025-11-15T02:30:00Z",
  "source_scraper_execution_id": "abc123",
  "metadata": {
    "duration_seconds": 3.5,
    "rows_inserted": 400,
    "rows_updated": 50
  }
}
```

**Key Fields:**
- `source_table`: Which Phase 2 table updated (for routing)
- `game_date`: Date-based filtering for analytics
- `game_ids`: Game-level granularity (optional)
- `record_count`: Data volume indicator
- `status`: success/failed
- `source_scraper_execution_id`: Traceability back to scraper

**Benefits:**
- Analytics service can route to correct processors
- Supports both date-based and game-based processing
- Full audit trail

### Challenge 5: Error Handling & Partial Failures

**Problem:** What if some Phase 2 dependencies succeed and others fail?

**Example:**
- `nbac_gamebook_player_stats` loads successfully
- `bdl_player_boxscores` FAILS
- Should `PlayerGameSummaryProcessor` run with partial data?

**Current Behavior (via `check_dependencies()`):**
- If CRITICAL dependency missing → Fail immediately
- If OPTIONAL dependency missing → Proceed with warning
- If dependency STALE → Warn or fail based on threshold

**This is good!** But need to ensure:
1. Failed Phase 2 processors DON'T publish success events
2. Analytics processors properly handle partial data scenarios
3. Retry logic for failed dependencies

**RECOMMENDATION:** Keep current dependency checking logic, ensure failed processors don't publish.

---

## Proposed Solutions

### Solution 1: Phase 2 → Phase 3 Event Publishing

**Overview:** Add Pub/Sub publishing to Phase 2 processors so they trigger Phase 3 analytics after successful BigQuery loads.

**Key Components:**

1. **RawDataPubSubPublisher** utility class
   - Publishes `raw_data_loaded` events to `nba-raw-data-complete` topic
   - Message format includes: source_table, game_date, record_count, execution_id, correlation_id
   - Graceful degradation (processor doesn't fail if publishing fails)

2. **Phase 2 Processor Enhancement**
   - Add publishing call after successful BigQuery load
   - Extract game_date and affected entities from processed data
   - Flow correlation_id from scraper through to analytics

3. **Pub/Sub Infrastructure**
   - Topic: `nba-raw-data-complete`
   - Subscription: `nba-analytics-sub` (push to analytics service)
   - DLQ: `nba-raw-data-complete-dlq` (for failed deliveries)

**Code examples** available in: `examples/pubsub_integration/raw_data_publisher.py` (to be created)

### Solution 2: Analytics Service Enhancement

**Overview:** Analytics service receives Phase 2 events, routes to appropriate processors based on `ANALYTICS_TRIGGERS` registry, with built-in idempotency checking.

**Key Features:**
- Decode Pub/Sub message and extract event metadata
- Route to processors via `ANALYTICS_TRIGGERS` registry (one source table → multiple processors)
- Check idempotency before processing (prevent duplicate work)
- Run processors with dependency validation (via `analytics_base.check_dependencies()`)
- Handle individual processor failures gracefully (don't block others)

**Implementation notes:**
- This pattern is **already implemented** in `data_processors/analytics/main_analytics_service.py`
- Just needs Phase 2 to start publishing events

### Solution 3: Idempotency Tracking

**Overview:** Track processor executions in `nba_orchestration.analytics_processing_log` to prevent duplicate processing.

**Table schema:** run_id, processor_name, game_date, started_at, completed_at, status, duration, metadata

**Logic:**
- Before processing: Check if processor ran for this game_date in last N hours
- If yes: Skip (already processed recently)
- If no: Process and log execution

**Query pattern:**
```sql
SELECT COUNT(*) FROM analytics_processing_log
WHERE processor_name = 'PlayerGameSummaryProcessor'
  AND game_date = '2025-11-15'
  AND status = 'completed'
  AND completed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
```

**Note:** Full unified pipeline execution log designed in [03-pipeline-monitoring-and-error-handling.md](./03-pipeline-monitoring-and-error-handling.md)

---

## Implementation Roadmap

**For complete implementation roadmap** with 8-sprint plan, effort estimates, and priorities, see [05-implementation-status-and-roadmap.md](./05-implementation-status-and-roadmap.md).

### Phase 2 → 3 Connection (Sprint 1: ~5 hours)

**Critical gap to address first:**
1. Create `RawDataPubSubPublisher` utility class
2. Add publishing to Phase 2 processor base classes
3. Create Pub/Sub topic and subscription infrastructure
4. Test end-to-end flow

**Impact:** Unlocks automatic Phase 3 analytics processing

---

## Open Questions

### Question 1: Granularity of Processing

**Q:** Should analytics processors run per game_date or per game_id?

**Options:**
- **A) game_date:** Process all games for the date (simpler)
- **B) game_id:** Process individual games (more granular)

**Recommendation:** Start with game_date (simpler), add game_id later for optimization.

### Question 2: Handling Late-Arriving Data

**Q:** What if Phase 2 data arrives out of order?

**Example:**
- Game at 7 PM
- `nbac_gamebook_player_stats` loads at 10 PM (3 hours later)
- `bdl_player_boxscores` loads at 10:15 PM (15 min after)
- Should we re-process? How many times?

**Options:**
- **A) Process each time:** Accept duplicate processing, rely on idempotency
- **B) Wait period:** Wait 30 min for all dependencies before processing
- **C) Smart trigger:** Only process if NOT processed recently

**Recommendation:** Option C - check if processed in last hour before re-running.

### Question 3: Error Notification Strategy

**Q:** When should we notify about Phase 2 → Phase 3 issues?

**Scenarios:**
1. Phase 2 publishes event but analytics service crashes
2. Analytics processor runs but ALL dependencies missing
3. Analytics processor runs with SOME dependencies missing

**Recommendation:**
- Scenario 1: DLQ handles retry, notify after 5 failures
- Scenario 2: Notify immediately (critical)
- Scenario 3: Warn but don't fail (existing behavior)

### Question 4: Backfill Strategy

**Q:** How do we backfill analytics data?

**Options:**
- **A) Pub/Sub replay:** Replay Phase 2 events (not possible, events expire)
- **B) Manual trigger:** Run analytics processors with historical date ranges
- **C) Automatic detection:** Analytics service detects gaps and fills them

**Recommendation:** Option B - manual trigger for backfills, document process.

### Question 5: Phase 4 & Phase 5 Triggering

**Q:** Should Phase 4 (precompute) and Phase 5 (predictions) be event-driven or scheduled?

**Considerations:**
- **Event-driven:** More real-time, higher complexity
- **Scheduled:** Simpler, batch-friendly, higher latency

**Recommendation:**
- Phase 4: Event-driven (follows same pattern)
- Phase 5: Hybrid (event-driven for live games, scheduled for daily batch)

---

## Related Documentation

**Current Implementation:**
- `docs/orchestration/pubsub-integration-status-2025-11-15.md` - Phase 1 → Phase 2 status
- `docs/infrastructure/01-pubsub-integration-verification.md` - Testing guide
- `docs/infrastructure/02-pubsub-schema-management.md` - Schema management

**Code References:**
- `data_processors/analytics/analytics_base.py` - Dependency checking logic
- `data_processors/analytics/main_analytics_service.py` - Analytics service
- `scrapers/scraper_base.py` - Phase 1 Pub/Sub publishing

**Future Documentation Needed:**
- Phase 2 → Phase 3 integration guide
- Analytics processor development guide
- End-to-end pipeline monitoring guide

---

**Next Steps:** Review this plan, discuss open questions, then begin Phase 1 implementation.

**Last Updated:** 2025-11-15
