# Pub/Sub Architecture Analysis Prompt

**Created:** 2025-11-19
**Purpose:** Analyze and provide recommendations for implementing fine-grained change detection and entity-level processing in our NBA stats pipeline pub/sub system
**For:** Claude Opus analysis session
**Context:** NBA Props Platform - Event-driven data pipeline (Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5)

---

## Background

We have an event-driven data pipeline that processes NBA statistics through 5 phases:

1. **Phase 1 (Scrapers)**: Collect raw data from various sources (NBA.com, ESPN, BallDontLie, odds APIs)
2. **Phase 2 (Raw Processors)**: Load scraped data into BigQuery `nba_raw` dataset
3. **Phase 3 (Analytics Processors)**: Compute analytics from raw data → `nba_analytics` dataset
4. **Phase 4 (Precompute/Features)**: Compute composite factors and features for ML
5. **Phase 5 (Predictions)**: Generate player prop predictions using ML models

Currently, phases communicate via **Google Cloud Pub/Sub** messages. Each phase publishes completion events that trigger the next phase.

---

## Current Implementation

### Phase 1 → Phase 2 Messages
**Topic:** `nba-phase1-scrapers-complete`

**Message structure:**
```json
{
  "name": "bdl_player_boxscores",
  "scraper_name": "bdl_player_boxscores",
  "execution_id": "abc-123",
  "status": "success",
  "gcs_path": "gs://bucket/path/file.json",
  "record_count": 450,
  "timestamp": "2025-11-19T10:00:00Z"
}
```

**Granularity:** One message per scraper execution (date-level)

---

### Phase 2 → Phase 3 Messages
**Topic:** `nba-phase2-raw-complete`

**Message structure:**
```json
{
  "event_type": "raw_data_loaded",
  "source_table": "nbac_gamebook_player_stats",
  "game_date": "2025-11-19",
  "record_count": 450,
  "execution_id": "proc-xyz-789",
  "timestamp": "2025-11-19T10:05:00Z",
  "phase": 2,
  "success": true
}
```

**Granularity:** One message per raw table loaded (date-level)

**Key observations:**
- No `affected_entities` field
- No change detection metadata
- No indication of which specific players/teams/games changed
- Simple structure: just table name, date, and total record count

---

### Phase 3 → Phase 4 Messages
**Topic:** `nba-phase3-analytics-complete`

**Message structure:**
```json
{
  "event_type": "analytics_complete",
  "analytics_table": "player_game_summary",
  "game_date": "2025-11-19",
  "record_count": 450,
  "execution_id": "analytics-abc-456",
  "timestamp": "2025-11-19T10:10:00Z",
  "phase": 3,
  "success": true
}
```

**Granularity:** One message per analytics table (date-level)

---

## The Problem

### Main Goal
**Avoid unnecessary reprocessing when only small changes occur.**

For example:
- **Scenario 1**: Single player injury status changes from "Questionable" → "Out"
  - **Current behavior**: Reprocess ALL 450 players through Phase 3, 4, and 5
  - **Desired behavior**: Reprocess only the affected player

- **Scenario 2**: One team's pointspread moves from -6.5 → -7.5
  - **Current behavior**: Reprocess ALL teams and potentially all players
  - **Desired behavior**: Reprocess only affected team/game

- **Scenario 3**: Player props line movement for Player X (25.5 → 26.5 points)
  - **Current behavior**: Reprocess all 450 player props
  - **Desired behavior**: Reprocess only Player X

---

## Key Questions to Answer

### 1. Change Detection Strategy

**Questions:**
- Should the **upstream phase** (message sender) determine what changed?
- Or should the **downstream phase** (message receiver) look back to detect changes?
- Or both?

**Example:**
- Phase 2 publishes "injury report scraped for 2025-11-19"
- Should Phase 2 include which specific players changed in the message?
- Or should Phase 3 query `WHERE processed_at > last_run` to find changes?

**Trade-offs:**
- **Sender determines changes**: Simple for receiver, but sender must track changes
- **Receiver detects changes**: Flexible, but requires timestamp infrastructure and extra queries
- **Both**: Most robust, but most complex

---

### 2. Message Granularity

**Questions:**
- Should we send **one message per date** (current) or **one message per entity** (player/team/game)?
- If entity-level, should we batch multiple entities in one message or send separate messages?
- What happens if 100+ entities change? Do we send 100 messages or one message with a large entity list?

**Message size limits:**
- Pub/Sub max message size: 10 MB
- Practical limit: <1 MB recommended
- 450 player IDs × 25 chars = ~11 KB (still small)
- But with metadata, could grow larger

**Options:**
1. **Date-level messages** (current): Simple, but triggers full reprocessing
2. **Entity-level messages**: One message per changed entity - very granular but lots of messages
3. **Batched entity messages**: One message with list of changed entities - balance
4. **Threshold-based**: If <100 entities changed → list them, if >100 → process all (fallback)

---

### 3. Entity Types

**Questions:**
- Do we need different handling for different entity types?
  - **Players**: Most common, high granularity needed
  - **Teams**: Less common, but important for spread/totals
  - **Games**: Game-level data (schedules, results)
- Can we use a unified approach or need specialized handling per entity type?

**Cross-entity dependencies:**
- Team defensive rating change → affects opposing team's players (easier matchup)
- Player injury → affects team aggregate stats
- How do we track these cascading effects?

---

### 4. Downstream Filtering

**Questions:**
- If a message says "injury report updated for date X", should:
  - **All Phase 3 processors** run (player stats, team stats, predictions)?
  - Or only **relevant processors** (injury-aware processors)?
- How do we define "relevance"?

**Example:**
- Message: `{"source_table": "odds_api_game_lines", "game_date": "2025-11-19"}`
- Should `PlayerGameSummaryProcessor` run? (It doesn't use odds data)
- Should `GamePredictionProcessor` run? (It does use odds data)

**Possible solutions:**
- Message includes `changed_fields: ["spread", "moneyline"]`
- Processors declare what fields/tables they depend on
- Smart routing: Only trigger relevant processors

---

### 5. Backfill Handling

**Questions:**
- How do backfills fit into this architecture?
- Should backfills use the same entity-level granularity or always process full dates?
- How do we handle dependency checks during backfills?

**Backfill scenarios:**
1. **Full historical backfill**: Process 4 seasons of data for all players
2. **Partial backfill**: Fix data for specific dates
3. **Single-entity correction**: Fix one player's data
4. **Dependency-driven backfill**: Backfill missing historical data when processor fails dependency check

**Considerations:**
- Backfills are often run offline/overnight (performance less critical)
- Need complete, consistent historical data
- Manual triggers vs. automatic dependency-driven backfills
- How to verify a backfill completed successfully?

---

### 6. Monitoring & Observability

**Questions:**
- How do we monitor whether entity-level processing is working?
- What metrics track "wasted processing" (processing unchanged entities)?
- How do we debug when entity-level filtering goes wrong?

**Metrics needed:**
- Processing waste percentage: `records_processed = 0 / total_runs`
- Entity processing ratio: `records_processed / affected_entity_count`
- Cost by trigger type: Which changes are most expensive?

---

## Architectural Concerns

### Concern 1: Cross-Entity Dependencies

**Problem:** Entity-level processing might miss cascading effects.

**Example:**
- LeBron scores 50 points (affected entity: LeBron)
- But this ALSO affects:
  - Team total points (Lakers team aggregate)
  - Opponent defensive stats (opposing team)
  - Teammate usage rates (other Lakers players)

**Question:** Do we need to expand affected entities based on dependencies?

---

### Concern 2: Data Completeness & Race Conditions

**Problem:** Incremental updates might process before all related data arrives.

**Example:**
```
10:00:00 - Injury update arrives: LeBron OUT
10:00:05 - Phase 2 loads injury data
10:00:10 - Phase 2 publishes message
10:00:15 - Phase 3 starts processing
          BUT: Boxscore not loaded yet!
          Result: Analytics computed with incomplete data ❌

10:15:00 - Boxscore arrives
10:15:05 - Phase 3 processes again ✅
```

**Questions:**
- Do we need readiness checks before processing?
- Should messages include data completeness metadata?
- How do we handle partial data availability?

---

### Concern 3: Message Ordering

**Problem:** Updates might arrive out of order.

**Example:**
```
11:00 - Stat correction: Rebounds 12 → 13
11:15 - Another correction: Rebounds 13 → 11

If messages arrive out of order:
  Process #2 first: rebounds = 11 ✅
  Process #1 second: rebounds = 13 ❌ (WRONG!)
```

**Questions:**
- Do we need ordering keys?
- Do we need sequence numbers to detect stale messages?
- Or can we rely on timestamps?

---

### Concern 4: Idempotency

**Problem:** Processors must handle duplicate messages safely.

**Questions:**
- Are all processors idempotent?
- Do we use `INSERT OR REPLACE` or incremental updates?
- How do we ensure reprocessing same entity produces same result?

---

## Design Patterns from Architecture Doc

### Pattern 1: Change Metadata (Recommended)

**Enhance messages with field-level information:**

```json
{
  "event_type": "raw_data_loaded",
  "source_table": "odds_api_game_lines",
  "game_date": "2025-11-19",
  "affected_entities": {
    "games": ["0022500225"]
  },
  "metadata": {
    "changed_fields": ["spread", "spread_odds"],
    "trigger_reason": "line_movement",
    "change_type": "incremental"
  }
}
```

**Benefits:**
- Downstream can skip if irrelevant fields changed
- Publisher knows what it changed anyway
- Backward compatible (optional field)

---

### Pattern 2: Multiple Event Types

**Use specific event types instead of generic `raw_data_loaded`:**

```json
// Event Type 1: Full data load
{
  "event_type": "game_stats_loaded",
  "trigger_all_analytics": true
}

// Event Type 2: Injury status update
{
  "event_type": "player_status_changed",
  "affected_entities": {"players": ["1630567"]},
  "trigger_analytics": ["player_summary", "team_roster_context"]
}

// Event Type 3: Betting context update
{
  "event_type": "game_context_updated",
  "trigger_analytics": ["game_predictions"],
  "skip_analytics": ["player_summary"]
}
```

**Benefits:**
- Very explicit about what should process
- Clear semantics
- Easy to route different event types differently

**Trade-offs:**
- More schemas to maintain
- More complex publishing logic

---

### Pattern 3: Timestamp-Based Change Detection

**Publisher doesn't track changes, subscriber queries for them:**

```python
def run(self, opts):
    game_date = opts['game_date']
    last_run = self.get_last_successful_run(game_date)

    if last_run:
        # Incremental - find what changed since last run
        changed_players = query(f"""
            SELECT DISTINCT player_id
            FROM nba_raw.nbac_gamebook_player_stats
            WHERE game_date = '{game_date}'
              AND updated_at > '{last_run.completed_at}'
        """)
    else:
        # First time - process all
        changed_players = get_all_players(game_date)
```

**Benefits:**
- Publisher doesn't need to track changes
- Subscriber has full control
- Works for any change detection logic

**Trade-offs:**
- Requires `updated_at` timestamp columns everywhere
- Extra query overhead
- Clock skew issues

---

## User's Thoughts & Requirements

### Fine-Grained Change Handling

> "The main goal is to not have the prediction system run unnecessary amount of times. This starts with having the earlier phases not re-run unnecessary computations."

**Key requirement:** If a single player's injury status changes, don't reprocess all 450 players.

---

### Change Detection Responsibility

> "I don't expect the scraper to know what has changed since the last change, so maybe then the phase 2 processor will only update the database record for the player or players that have an updated status compared to what is already in the database."

**Approach:** Phase 2 processor detects changes (via MERGE logic or hash comparison), not the scraper.

---

### Message Propagation

> "That way phase 3 will get a message that for a specific date, the injury data has changed and it can check which players specifically have changed data and at that point in the pipeline the players to process has been filtered."

**Flow:**
1. Phase 2 MERGE updates only changed records
2. Phase 2 publishes message (date + affected players)
3. Phase 3 receives message, processes only those players
4. Phase 4 receives filtered list, processes only those players

---

### Message Content Flexibility

> "We will also need to handle messages that pass player IDs in them (or team ID if it is team data). That way I can also have the ability to tell it to process specific message IDs by passing a message to it."

**Requirements:**
- Messages can contain entity IDs (player_ids, team_ids, game_ids)
- Support manual triggers with specific IDs (testing, backfills)
- But need to handle message size limits (too many IDs → message too big)

---

### Message Size Concerns

> "But also if there are too many IDs, the message could be too big and might exceed the allowed size."

**Questions:**
- What's the threshold? <100 entities → list them, ≥100 → process all?
- Use message attributes vs. message body?
- Compress entity lists?
- Multiple messages if needed?

---

### Change Detection Components

> "If the downstream processor or phase 5 service looks back to see what changed, will it be an independent new piece that determines it or part of the process or phase 5 service code?"

**Questions:**
- Should change detection be a separate service/module?
- Or embedded in each processor?
- Reusable change detection utilities?

---

### Backfill Integration

> "We should also think about how backfills fit in with everything. We will need to backfill on the phases for all players for the past four seasons."

**Backfill scenarios:**
1. Historical data backfill (4 seasons, all players)
2. Dependency-driven backfill (missing data for averages)
3. Manual retry after dependency check failure
4. Verification that backfill completed successfully

**Questions:**
- Do backfills use the same entity-level logic?
- Or always process full dates for historical consistency?
- How to trigger backfills via pub/sub vs. manual scripts?

---

### Dependency Checking

> "The dependency checks in some processors will check historical data is present as well if it needs to compute averages or things that require historical data."

**Current approach:** Processors have dependency checks (e.g., "need last 10 games for moving average")

**Questions:**
- If dependency check fails, how do we trigger backfill?
- Manual process or automatic?
- How to verify backfill before retrying processor?
- Can we run dependency check independently to verify readiness?

---

## Current Investigation Status

From `docs/architecture/07-change-detection-current-state-investigation.md`, we need to answer:

### Unknown: Phase 2 Behavior
- [ ] Does Phase 2 MERGE update ALL records or only changed records?
- [ ] Does Phase 2 set `processed_at` for all records or only changed ones?
- [ ] Does Phase 2 have hash-based change detection?

### Unknown: Phase 3 Behavior
- [ ] Does Phase 3 use `WHERE processed_at > last_run` to filter?
- [ ] Or does it DELETE+INSERT all records for the date?
- [ ] Does Phase 3 support entity-level filtering (`player_ids` parameter)?

### Unknown: Current Waste
- [ ] How often are small updates (1-10 entities) vs. full batches (450 entities)?
- [ ] What percentage of processing is "wasted" (processing unchanged data)?
- [ ] Which update types are most expensive?

---

## What We Need from This Analysis

### 1. Architecture Recommendations

**Please provide:**
- Recommended message structure (what fields to include)
- Recommended change detection strategy (sender vs. receiver vs. both)
- Recommended entity granularity approach
- Recommended handling for different entity types (player, team, game)

### 2. Implementation Strategy

**Please outline:**
- Step-by-step implementation plan
- Which pattern(s) to use (Pattern 1, 2, 3, or combination)
- Migration strategy (current state → future state)
- Backward compatibility approach

### 3. Edge Cases & Solutions

**Please address:**
- Cross-entity dependencies (how to handle cascading effects)
- Data completeness & race conditions (how to ensure all data ready)
- Message ordering (do we need ordering keys/sequence numbers?)
- Message size limits (how to handle 100+ entity changes)
- Backfill integration (how do backfills fit in)

### 4. Monitoring & Validation

**Please recommend:**
- Key metrics to track
- How to detect "wasted processing"
- How to validate entity-level filtering is working
- How to debug issues

### 5. Decision Framework

**Please provide:**
- When to use date-level vs. entity-level messages
- When to expand entity lists (cross-entity dependencies)
- When to fallback to full processing (too many changes)
- How to measure ROI of optimizations

---

## Success Criteria

A successful analysis should help us:

1. **Decide on message structure** - What fields do we include in Phase 2→3 messages?
2. **Decide on change detection** - Who detects changes? How are they communicated?
3. **Decide on granularity** - Entity-level, date-level, or adaptive?
4. **Handle edge cases** - Cross-entity dependencies, race conditions, ordering
5. **Plan implementation** - Clear roadmap from current state to optimized state
6. **Ensure monitoring** - Track waste, validate improvements

---

## Related Documentation

Please review these files for additional context:

1. **Architecture docs:**
   - `docs/architecture/06-change-detection-and-event-granularity.md` - Design patterns (VERY DETAILED)
   - `docs/architecture/07-change-detection-current-state-investigation.md` - Investigation checklist

2. **Current implementation:**
   - `scrapers/utils/pubsub_utils.py` - Phase 1→2 publishing
   - `shared/utils/pubsub_publishers.py` - Phase 2→3 publishing
   - `data_processors/raw/processor_base.py` - Phase 2 base class

3. **Pipeline overview:**
   - `docs/architecture/01-phase1-to-phase5-integration-plan.md`
   - `docs/architecture/04-event-driven-pipeline-architecture.md`

---

## Constraints

Please keep in mind:

1. **Google Cloud Pub/Sub limits:**
   - Max message size: 10 MB
   - Recommended: <1 MB per message
   - Ordering requires ordering keys (reduces parallelism)

2. **Performance targets:**
   - Incremental updates should complete in <5 seconds
   - Full date processing currently takes ~30 seconds for 450 players
   - Want >10x speedup for single-entity updates

3. **Developer experience:**
   - Solution should be easy to understand and debug
   - Prefer simple over complex unless metrics show clear need
   - Backward compatibility preferred (gradual migration)

4. **Future-proofing:**
   - Solution should work for players, teams, and games
   - Should scale to handle increased data volume
   - Should support both real-time updates and backfills

---

## Questions for Your Analysis

1. **Should Phase 2 include `affected_entities` in messages? If so, what format?**

2. **Should messages include change metadata (changed_fields, trigger_reason)?**

3. **Do we need different message structures for different entity types (player vs. team vs. game)?**

4. **How should Phase 3 determine what to process?**
   - Trust the message's `affected_entities` list?
   - Query for changes using timestamps?
   - Both (verify message against actual changes)?

5. **How do we handle cross-entity dependencies?**
   - Expand affected entities in message?
   - Downstream processor expands based on dependencies?
   - Separate dependency resolution service?

6. **What's the threshold for entity-level vs. full processing?**
   - <10 entities → entity-level
   - <100 entities → batched entity-level
   - ≥100 entities → full date processing
   - Or different thresholds?

7. **Do we need ordering guarantees? If so, how to implement?**

8. **How should backfills integrate with this architecture?**
   - Same entity-level logic?
   - Always full date?
   - Configurable per backfill?

9. **What metrics should we collect to validate this is working?**

10. **What's the migration path from current (date-level) to optimized (entity-level)?**

---

## Thank You!

Please provide a comprehensive analysis addressing these questions, concerns, and requirements. Focus on:

- **Practical recommendations** (not just theory)
- **Clear decision criteria** (when to use which approach)
- **Implementation roadmap** (how to get from here to there)
- **Edge case handling** (what could go wrong and how to prevent it)

We want to ship something simple first, then optimize based on metrics - but we want to design the architecture so it can evolve without major rewrites.

---

**End of Prompt**
