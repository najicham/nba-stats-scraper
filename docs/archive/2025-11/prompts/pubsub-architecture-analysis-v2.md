# Pub/Sub Architecture Analysis - Comprehensive Prompt for Claude Opus

**Created:** 2025-11-19
**Version:** 2.0 (Revised)
**Purpose:** Analyze and provide actionable recommendations for implementing fine-grained change detection and entity-level processing in our NBA stats pipeline
**For:** Claude Opus analysis session
**Context:** NBA Props Platform - Event-driven data pipeline (6 phases: Scrapers → Raw → Analytics → Precompute → Predictions → Publishing)

---

## Executive Summary

We have an event-driven data pipeline that processes NBA statistics through 6 phases. Currently, **small changes trigger complete reprocessing** - a single player's injury status update causes all 450 players to be reprocessed through the entire pipeline, wasting time and compute resources.

**Current state:** Date-level Pub/Sub messages → full date reprocessing (simple, works, but inefficient)
**Desired state:** Entity-level Pub/Sub messages → targeted reprocessing (complex, but 10-60x faster for incremental updates)

**Key challenges to solve:**
1. **Change detection:** Who determines what changed? (sender vs. receiver vs. both)
2. **Message structure:** What entity IDs to include? How to handle message size limits?
3. **Cross-entity dependencies:** Team change → affects opposing team's players (cascading effects)
4. **Data completeness:** Incremental updates might process before all related data arrives
5. **Backfill integration:** How do 4-season historical backfills fit into this architecture?

**We need:** Strategic guidance on WHAT to build WHEN, not just HOW to build entity-level optimization. Help us design a system that starts simple but can evolve based on measured need.

**Our philosophy:**
- ✅ Ship simple first (date-level processing is OK initially)
- ✅ Measure everything (instrument from day 1)
- ✅ Optimize based on data (metrics tell us when entity-level is worth it)
- ✅ Design for evolution (architecture supports future optimization without rewrites)

---

## Table of Contents

1. [Background](#background)
2. [Current Implementation](#current-implementation)
3. [The Problem](#the-problem)
4. [Core Questions for Analysis](#core-questions-for-analysis)
5. [Architecture Patterns](#architecture-patterns)
6. [User Requirements & Thoughts](#user-requirements--thoughts)
7. [Edge Cases & Concerns](#edge-cases--concerns)
8. [Constraints](#constraints)
9. [Success Criteria & Deliverables](#success-criteria--deliverables)
10. [What We're NOT Looking For](#what-were-not-looking-for)
11. [Related Documentation](#related-documentation)

---

## Quick Reference: Key Decisions Needed

| Decision Area | Current State | Options to Consider | Your Recommendation Needed |
|---------------|---------------|---------------------|---------------------------|
| **Change Detection** | None | Sender / Receiver / Both | ? |
| **Message Structure** | Date-only | Date / Entity / Hybrid | ? |
| **Entity Threshold** | N/A | <50 / <100 / <200 / Adaptive | ? |
| **Dep Tracking Integration** | Separate concerns | Extend v4.0 / New System | ? |
| **Phase 1 Priority** | TBD | Monitoring First / Entity-level / Both | ? |
| **Batching Strategy** | N/A | Immediate / 30-min windows / Hybrid | ? |

**Key Metrics to Define:**
- Waste threshold triggering optimization (e.g., `waste_pct > 30%`)
- Duration threshold (e.g., `avg_duration > 60s`)
- ROI calculation for entity-level investment
- Thresholds for moving Phase 1 → Phase 2 → Phase 3

---

## Background

### Pipeline Overview (Quick Visual)

```
┌─────────────┐ Pub/Sub ┌─────────────┐ Pub/Sub ┌─────────────┐
│  Phase 1    │────────→│  Phase 2    │────────→│  Phase 3    │
│  Scrapers   │  date   │  Raw Load   │  date   │  Analytics  │
│ (GCS JSON)  │  level  │(BigQuery)   │  level  │  (BigQuery) │
└─────────────┘         └─────────────┘         └─────────────┘
                                                       ↓
                                                  Want: entity
                                                  level! ✅

┌─────────────┐ Pub/Sub ┌─────────────┐ Pub/Sub ┌─────────────┐
│  Phase 4    │────────→│  Phase 5    │────────→│  Phase 6    │
│ Precompute  │  date   │ Predictions │  date   │ Publishing  │
│ (BigQuery)  │  level  │ (BigQuery)  │  level  │ (Firestore) │
└─────────────┘         └─────────────┘         └─────────────┘

Current: All phases = date-level (simple but wasteful)
Goal: Phases 3-5 = entity-level option (complex but efficient)
```

---

### Current Implementation Status

**Phase 2→3 Connection:** Currently being implemented
- Service will listen to Pub/Sub messages from Phase 2
- Performs dependency checks when message arrives
- If dependencies satisfied, processes all data for the date
- **No entity-level filtering yet** - always processes entire date

**Dependency Tracking System:** ✅ Fully implemented (v4.0) - MAJOR EXISTING SYSTEM
- Sophisticated `track_source_usage()` and `check_dependencies()` methods in base classes
- Tracks `source_{prefix}_last_updated`, `source_{prefix}_rows_found`, `source_{prefix}_completeness_pct`
- Enables querying which sources were used, data quality, freshness
- **Could potentially be leveraged for change detection** (key integration question!)
- See: Wiki document "Dependency Tracking & Source Metadata Design" (provided in chat)

**Entity-Level Support:** Not implemented anywhere yet
- No processors currently accept `player_ids`, `team_ids`, or `game_ids` parameters
- Would be completely new functionality across all phases

### The Six-Phase Pipeline

Our event-driven data pipeline processes NBA statistics through 6 phases, connected via Google Cloud Pub/Sub:

```
Phase 1: Scrapers (data collection)
  ↓ Pub/Sub: nba-phase1-scrapers-complete
Phase 2: Raw Processors (load to BigQuery nba_raw.*)
  ↓ Pub/Sub: nba-phase2-raw-complete
Phase 3: Analytics Processors (compute analytics → nba_analytics.*)
  ↓ Pub/Sub: nba-phase3-analytics-complete
Phase 4: Precompute Processors (features & aggregations → nba_precompute.*)
  ↓ Pub/Sub: nba-phase4-precompute-complete
Phase 5: Prediction Processors (ML predictions → nba_predictions.*)
  ↓ Pub/Sub: nba-phase5-predictions-complete
Phase 6: Publishing Service (Firestore + GCS for web app)
```

**Key characteristics:**
- **Phase 1→2:** 1:1 relationship (each scraper → one raw processor)
- **Phase 2→3:** M:1 relationships (one analytics processor depends on 6+ raw tables)
- **Phase 3→4:** M:1 relationships (precompute needs multiple analytics tables)
- **Phase 4→5:** M:1 relationships (predictions need multiple features)

### Entity Types

Our data involves three main entity types:
- **Players:** ~450 active players on any given date
- **Teams:** 30 NBA teams
- **Games:** ~10-15 games per day during season

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
**Code:** `scrapers/utils/pubsub_utils.py`

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
**Code:** `shared/utils/pubsub_publishers.py`

**❌ Missing fields:**
- No `affected_entities` (no player_ids, team_ids, or game_ids)
- No change detection metadata (no `changed_fields`, `change_type`)
- No indication of which specific entities changed

---

### Phase 2: Current Raw Processor Behavior

**File:** `data_processors/raw/balldontlie/bdl_boxscores_processor.py`

**Current MERGE strategy (DELETE + INSERT ALL):**
```python
# MERGE_UPDATE strategy = DELETE entire game/date + INSERT all records
def save_data(self):
    if self.processing_strategy == 'MERGE_UPDATE':
        # Delete ALL records for this game
        delete_query = f"""
        DELETE FROM `{table_id}`
        WHERE game_id = '{game_id}'
          AND game_date = '{game_date}'
        """

        # Update processed_at for ALL records
        for row in rows:
            row['processed_at'] = datetime.utcnow().isoformat()

        # Insert ALL records
        self.bq_client.insert_rows_json(table_id, rows)
```

**Key observations:**
- ❌ **No change detection** - always deletes and reinserts entire game/date
- ❌ **No selective updates** - `processed_at` set on ALL records, not just changed ones
- ❌ **No hash-based change tracking** - no data_hash or checksum fields

**Impact:** Cannot tell which specific players/teams changed by looking at `processed_at` timestamps.

---

### Phase 3: Current Analytics Processor Behavior

**File:** `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

**Required options:**
```python
class AnalyticsProcessorBase:
    required_opts: List[str] = ['start_date', 'end_date']
    # Note: NO 'player_ids' or 'team_ids' or 'game_ids' options
```

**Current query pattern (DATE-LEVEL only):**
```python
def extract_data(self):
    start_date = self.opts['start_date']
    end_date = self.opts['end_date']

    # Always processes ALL players for the date range
    query = f"""
    SELECT *
    FROM `nba_raw.nbac_gamebook_player_stats`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        AND player_status = 'active'
    """
    # ❌ No filtering by player_ids
    # ❌ Processes all 450 players even if only 1 changed
```

**Key observations:**
- ❌ **Date-level only** - always processes entire date range
- ❌ **No entity-level support** - no `player_ids`, `team_ids`, or `game_ids` parameters
- ❌ **No incremental filtering** - no `WHERE processed_at > last_run` logic

---

## The Problem

### Complete Message Flow - Current vs. Desired

#### 🔴 Current Flow (Date-Level) - INEFFICIENT

**Scenario:** One player's injury status changes from "Questionable" → "Out"

```
2:00 PM - Phase 1: Injury scraper runs
  ├─ Detects: 45 injured players total (1 changed: LeBron)
  └─ Publishes: {"scraper_name": "nbac_injury_report", "record_count": 45}

2:01 PM - Phase 2: Injury processor
  ├─ Deletes ALL 45 injury records
  ├─ Reinserts ALL 45 records (all get same processed_at)
  └─ Publishes: {"source_table": "nbac_injury_report", "game_date": "2025-11-19", "record_count": 45}

2:02 PM - Phase 3: PlayerGameSummaryProcessor
  ├─ Query: WHERE game_date = '2025-11-19'
  ├─ Processes: ALL 450 active players
  ├─ Duration: 30 seconds
  └─ Publishes: {"analytics_table": "player_game_summary", "record_count": 450}

2:03 PM - Phase 4: PlayerDailyCacheProcessor
  ├─ Processes: ALL 450 players
  ├─ Duration: 45 seconds
  └─ Publishes: {"precompute_table": "player_daily_cache", "record_count": 450}

2:04 PM - Phase 5: Prediction workers (450 Cloud Tasks)
  ├─ Generates predictions for: ALL 450 players
  ├─ Duration: 5 minutes (parallel processing)
  └─ Publishes: 450 prediction records

Total: ~6 minutes, processes 450 players when only 1 changed (450x waste!)
```

---

#### ✅ Desired Flow (Entity-Level) - EFFICIENT

**Same scenario:** LeBron's injury status changes

```
2:00 PM - Phase 1: Injury scraper runs
  ├─ Detects: 45 injured players (1 changed)
  └─ Publishes: {"scraper_name": "nbac_injury_report", "record_count": 45}

2:01 PM - Phase 2: Injury processor
  ├─ MERGE logic detects only LeBron changed (compare hash or diff against existing data)
  ├─ Updates only LeBron's record (sets processed_at for LeBron only)
  └─ Publishes:
      {
        "source_table": "nbac_injury_report",
        "game_date": "2025-11-19",
        "record_count": 1,
        "affected_entities": {
          "players": ["1630567"],  // LeBron's ID
          "teams": ["LAL"],
          "games": ["0022500225"]
        },
        "change_type": "incremental"
      }

2:02 PM - Phase 3: PlayerGameSummaryProcessor
  ├─ Extracts player_ids from message: ["1630567"]
  ├─ Query: WHERE game_date = '2025-11-19' AND player_id IN ('1630567')
  ├─ Processes: ONLY LeBron
  ├─ Duration: 0.5 seconds (60x faster!)
  └─ Publishes: {"affected_entities": {"players": ["1630567"]}}

2:03 PM - Phase 4: PlayerDailyCacheProcessor
  ├─ Processes: ONLY LeBron
  ├─ Duration: 0.8 seconds
  └─ Publishes: {"affected_entities": {"players": ["1630567"]}}

2:04 PM - Phase 5: Prediction worker (1 Cloud Task)
  ├─ Generates prediction for: ONLY LeBron
  ├─ Duration: 2 seconds
  └─ Publishes: 1 prediction record

Total: ~4 seconds (90x faster!), processes 1 player (1x work, not 450x)
```

---

### Real-World Scenarios

#### Scenario 1: Single Player Injury Update (Mid-Day)

**Setup:**
```
9:00 AM  - Initial injury report: 45 players injured
         - Phase 2-5 process all 450 players

3:00 PM  - Player X's status changes Questionable → Out
         - Injury scraper runs again
         - Finds: 1 changed player, 44 unchanged players
```

**Current behavior (confirmed via code):**
- Phase 2: DELETE + INSERT all 45 records (all get same `processed_at`)
- Phase 3: Reprocess ALL 450 players (no entity filtering)
- Phase 4: Reprocess ALL 450 players
- Phase 5: Regenerate predictions for ALL 450 players
- **Total waste:** 449 players × (Phase 3 + Phase 4 + Phase 5)

**Desired behavior:**
- Phase 2: UPDATE only Player X (only Player X gets new `processed_at`)
- Phase 3: Process ONLY Player X
- Phase 4: Process ONLY Player X
- Phase 5: Regenerate prediction for ONLY Player X
- **No waste:** 1 player processed

---

#### Scenario 2: Single Team Pointspread Change (Mid-Day)

**Setup:**
```
9:00 AM  - Initial spreads: 14 games = 28 teams
         - Lakers -6.5 vs Warriors

3:00 PM  - Lakers spread moves to -7.5 (sharp money)
         - Spreads scraper runs again
         - Finds: 1 changed team spread, 27 unchanged
```

**Current behavior:**
- Phase 2: DELETE + INSERT all 28 team spreads
- Phase 3: Reprocess ALL 28 teams (team_offense, team_defense processors)
- Phase 4: Reprocess ALL team-level features
- Phase 5: Potentially re-run predictions for ALL games
- **Total waste:** 27 teams × (Phase 3 + Phase 4)

**Desired behavior:**
- Phase 2: UPDATE only Lakers spread
- Phase 3: Process ONLY Lakers team context
- Phase 4: Process ONLY Lakers team features
- Phase 5: Re-run predictions for ONLY Lakers vs Warriors game
- **No waste:** 1 team + 1 game processed

---

#### Scenario 3: Cross-Entity Dependency (Team → Players)

**Setup:**
```
2:00 PM  - Team injury report: Lakers list 2 starters as OUT
         - This affects:
           ✓ Lakers team_defense_game_summary (weaker defense)
           ✓ Warriors players' upcoming_player_game_context (easier matchup)
           ✓ Predictions for ALL Warriors players in that game
```

**Questions:**
- Does team-level change trigger player-level reprocessing?
- How do we know which players are affected by team change?
- Do we reprocess all 450 players or just Warriors players in that game?

**Dependency chain:**
```
Team Change (Lakers defense)
  → Affects: team_defense_game_summary (Lakers)
  → Affects: upcoming_team_game_context (Lakers vs Warriors game)
  → Affects: upcoming_player_game_context (Warriors players ONLY - easier matchup)
  → Affects: player_composite_factors (Warriors players ONLY)
  → Affects: predictions (Warriors players ONLY)
```

**Current behavior (hypothesis):**
- Reprocesses ALL 450 players (can't detect cascading effects)

**Desired behavior:**
- Identify affected game: Lakers vs Warriors
- Reprocess Lakers team defense
- Reprocess Warriors opponent context
- Reprocess Warriors players ONLY (~15 players)
- Re-run predictions for Warriors players ONLY

---

#### Scenario 4: Backfill with Cross-Date Dependencies

**Setup:**
```
Need to backfill Phase 4 "player_shot_zone_analysis" processor
Lookback window: Needs last 10 games per player
Date range: November 1-18 (18 days)
```

**Cross-date dependency challenge:**
```
To process Nov 18 for Player X:
  ├─ Need Phase 3 data for: Nov 16, Nov 14, Nov 12, Nov 10, Nov 8, Nov 6, Nov 4, Nov 2, Oct 31, Oct 29
  │  (Player X's last 10 games - NOT calendar dates, actual games played)
  └─ But: Those dates might not be in our backfill range!
     └─ Must backfill Oct 29-31 FIRST, then Nov 1-18
```

**Questions:**
- Do backfills use entity-level granularity or always process full dates?
- How do we handle historical lookback windows?
- How do we verify a backfill completed successfully?
- Can we run a "dry run" dependency check before backfilling?

**Backfill types (in order of frequency):**

1. **Full Historical Backfill** (rare - 2x per year)
   - All players, 4 seasons, all stats
   - ~1,000,000+ records
   - Triggered: New processor added, schema change
   - **Should use:** Full date processing (entity-level not worth complexity)

2. **Date Range Backfill** (occasional - weekly?)
   - Specific date range, all players
   - ~10,000-100,000 records
   - Triggered: Data quality issue found
   - **Should use:** Full date processing

3. **Single Player Correction** (frequent - daily?)
   - One player, all history or specific dates
   - ~100-1,000 records
   - Triggered: Name resolution fix, manual correction
   - **Should use:** Entity-level processing (1 player × many dates)

4. **Dependency-Driven Backfill** (automatic)
   - Missing historical data for averages
   - Variable size
   - Triggered: Processor dependency check failure
   - **Should use:** Adaptive (entity-level if <100 players, full date if more)

---

## Core Questions for Analysis

### 🔴 Critical Questions (Must Answer)

#### Q1: Change Detection Strategy

**Question:** Who determines what changed - the message sender (Phase 2) or the receiver (Phase 3)?

**Options:**
- **Option A: Sender detects changes** - Phase 2 compares new data against existing BigQuery data, includes `affected_entities` in message
  - ✅ Pros: Simple for receiver, explicit, fast
  - ❌ Cons: Sender must query existing data, more complex publishing logic

- **Option B: Receiver detects changes** - Phase 2 just publishes "data loaded", Phase 3 queries `WHERE processed_at > last_run`
  - ✅ Pros: Flexible, sender doesn't need to know about changes
  - ❌ Cons: Requires `processed_at` timestamps on changed records only, extra query overhead

- **Option C: Both (Hybrid)** - Sender includes `affected_entities`, receiver validates against actual changes
  - ✅ Pros: Most robust, catches sender errors
  - ❌ Cons: Most complex, both sender and receiver do work

**Your recommendation:** Which approach? Or different approach?

---

#### Q2: Message Structure

**Question:** What should Phase 2→3 messages look like?

**Proposed enhanced structure:**
```json
{
  "event_type": "raw_data_loaded",
  "source_table": "nbac_injury_report",
  "game_date": "2025-11-19",
  "record_count": 1,

  // NEW FIELDS:
  "affected_entities": {
    "players": ["1630567", "1629029"],      // Array of player IDs
    "teams": ["LAL", "GSW"],                // Array of team abbreviations
    "games": ["0022500225"]                 // Array of game IDs
  },

  "change_type": "incremental",             // vs "full_load"

  "metadata": {
    "changed_fields": ["injury_status"],    // Which fields changed
    "trigger_reason": "injury_update",      // Why this update happened
    "original_count": 45,                   // Total records in table
    "changed_count": 1                      // How many actually changed
  }
}
```

**Questions:**
- Should we include `affected_entities`? Format OK?
- Should we include `metadata.changed_fields` for smart routing?
- Do we need different structures for player vs. team vs. game entities?
- How do we handle message size limits (what if 100+ entities changed)?

**Your recommendation:** Minimal viable message structure to start? Full structure for future?

---

#### Q3: Cross-Entity Dependencies

**Question:** How do we handle cascading effects across entity types?

**Example:** Team defensive rating change → affects opposing team's players

**Options:**
- **Option A: Expand in message** - Phase 2 knows team change affects players, includes expanded player list
  - ❌ Problem: Phase 2 doesn't know about cross-phase dependencies

- **Option B: Downstream expansion** - Phase 3 receives team change, queries which players affected, processes them
  - ✅ Better: Each phase knows its own dependencies
  - ❌ Problem: How does Phase 3 know which players are affected by a team change?

- **Option C: Dependency mapping service** - Separate service/module that maps dependencies
  - ✅ Centralized logic
  - ❌ Complex: Another moving part

**Your recommendation:** How to handle cross-entity dependencies?

---

#### Q4: Downstream Processing Logic

**Question:** How should Phase 3 determine what to process?

**Current code:**
```python
class AnalyticsProcessorBase:
    required_opts = ['start_date', 'end_date']  # Date-level only
```

**Proposed code:**
```python
class AnalyticsProcessorBase:
    required_opts = ['start_date', 'end_date']  # Required for backward compat
    optional_opts = ['player_ids', 'team_ids', 'game_ids']  # NEW: Entity filtering

    def run(self, opts):
        # Determine processing mode
        if 'player_ids' in opts:
            # Entity-level: Process only specified players
            query = f"""
            SELECT * FROM raw_table
            WHERE game_date = '{opts['game_date']}'
              AND player_id IN UNNEST(@player_ids)
            """

        else:
            # Date-level: Process all players for date range
            query = f"""
            SELECT * FROM raw_table
            WHERE game_date BETWEEN '{opts['start_date']}' AND '{opts['end_date']}'
            """
```

**Questions:**
- Should processors accept `player_ids`/`team_ids`/`game_ids` parameters?
- Should they trust the message or verify which entities actually changed?
- How do we handle processors that CAN'T do entity-level (e.g., league-wide rankings)?

**Your recommendation:** Processor interface changes needed?

---

### 🟡 Important Questions (Should Answer)

#### Q5: Integration with Dependency Tracking System

**Question:** How should entity-level processing integrate with the existing dependency tracking system (v4.0)?

**Current dependency tracking:**
```python
class AnalyticsProcessorBase:
    def track_source_usage(self, dep_check):
        """Tracks source_{prefix}_last_updated, rows_found, completeness_pct"""
        # Already queries: WHERE game_date = X AND processed_at > last_run
        # Returns: completeness_pct, rows_found, last_updated

    def check_dependencies(self, game_date):
        """Validates all required sources are present and fresh"""
        # Checks: expected_count, max_age_hours, completeness thresholds
```

**Could this be leveraged for change detection?**
```python
# Potential enhancement:
def check_dependencies(self, game_date, player_ids=None):
    """Check dependencies for specific entities if provided"""

    if player_ids:
        # Entity-level: Check only these players have data
        query = f"""
        SELECT COUNT(*) FROM source_table
        WHERE game_date = '{game_date}'
          AND player_id IN UNNEST(@player_ids)
          AND processed_at > '{last_run}'
        """
    else:
        # Date-level: Check all data for date
        query = f"""
        SELECT COUNT(*) FROM source_table
        WHERE game_date = '{game_date}'
        """
```

**Questions:**
- Should dependency checking support entity-level filtering?
- Could `processed_at` timestamps be used for change detection?
- Or should change detection be separate from dependency tracking?

**Your recommendation:** How to integrate these systems?

---

#### Q6: Batching/Windowing Strategy

**Question:** Should we process messages immediately or batch them in time windows?

**Option A: Immediate Processing (Real-Time)**
```
2:00 PM - Player 1 injury changes → Process immediately
2:15 PM - Player 2 spread changes → Process immediately
2:25 PM - Player 3 injury changes → Process immediately
```
- ✅ Lowest latency
- ❌ More processor invocations

**Option B: Windowed Batching (Delayed but Efficient)**
```
2:00 PM - Player 1 injury changes → Queue
2:15 PM - Player 2 spread changes → Queue
2:25 PM - Player 3 injury changes → Queue
2:30 PM - Window closes → Process players 1, 2, 3 together
```
- ✅ Fewer processor invocations
- ✅ Can batch-process multiple changes
- ❌ Adds 0-30 min latency

**Option C: Hybrid (Priority-Based)**
```
Critical updates (injury OUT) → Process immediately
Non-critical (spread moves) → Batch in 30-min windows
```

**Considerations:**
- Pub/Sub doesn't have native windowing - would need application-level batching
- Could use Cloud Tasks for delayed processing
- Message attributes could indicate urgency/priority

**Questions:**
- Is real-time processing required or is 30-min delay acceptable?
- Would batching significantly reduce costs/complexity?
- How to implement windowing with Pub/Sub?

**Your recommendation:** Immediate, batched, or hybrid approach?

---

#### Q7: Message Size Limits

**Question:** What if too many entities changed to fit in one message?

**Pub/Sub limits:**
- Max message size: 10 MB
- Recommended: <1 MB
- 450 player IDs × 25 chars = ~11 KB (still small)
- But with metadata, could grow

**Threshold strategy:**
```python
affected_players = get_changed_players(game_date)

if len(affected_players) < 100:
    # Entity-level: Include explicit list
    message = {
        "affected_entities": {"players": affected_players},
        "change_type": "incremental"
    }
else:
    # Fallback to full processing
    message = {
        "affected_entities": {"count": len(affected_players)},
        "change_type": "full_load",
        "process_all": true
    }
```

**Questions:**
- What's the threshold? <50? <100? <200?
- Use message attributes vs. message body?
- Send multiple messages if needed?

**Your recommendation:** How to handle large change sets?

---

#### Q8: Monitoring & Measurement Strategy

**Question:** What metrics should we track to know WHEN entity-level optimization is worth implementing?

**Current situation:** We're okay with overprocessing initially, but need to know when it becomes a problem.

**Key metrics to potentially track:**

1. **Processing Waste Percentage**
```sql
-- How often do we process when nothing changed?
SELECT
    processor_name,
    COUNT(*) as total_runs,
    COUNTIF(records_processed = 0) as no_change_runs,
    (no_change_runs / total_runs * 100) as waste_pct
FROM pipeline_execution_log
GROUP BY processor_name
```

2. **Entity Processing Ratio**
```sql
-- How many entities processed vs how many actually changed?
SELECT
    processor_name,
    AVG(entities_processed / entities_changed) as avg_ratio
FROM pipeline_execution_log
WHERE entities_changed > 0
```

3. **Processing Duration by Update Type**
```sql
-- Which update types are most expensive?
SELECT
    update_type,  -- 'injury_update', 'spread_change', 'full_load', etc.
    COUNT(*) as frequency,
    AVG(duration_seconds) as avg_duration,
    SUM(duration_seconds) as total_time_spent
FROM pipeline_execution_log
GROUP BY update_type
```

4. **Daily Processing Cost**
```sql
-- Total compute time per day
SELECT
    DATE(processed_at) as date,
    SUM(duration_seconds) as total_processing_seconds,
    COUNT(*) as total_runs,
    SUM(records_processed) as total_records
FROM pipeline_execution_log
GROUP BY date
```

**Proposed `pipeline_execution_log` schema:**

```sql
CREATE TABLE `nba_orchestration.pipeline_execution_log` (
  -- Execution metadata
  execution_id STRING NOT NULL,
  processor_name STRING NOT NULL,
  phase INT64 NOT NULL,  -- 2, 3, 4, or 5
  game_date DATE NOT NULL,

  -- Processing scope
  processing_mode STRING,  -- 'date_level' or 'entity_level'
  affected_entity_type STRING,  -- 'player', 'team', 'game', or NULL
  affected_entity_count INT64,  -- How many entities were supposed to change
  records_processed INT64,  -- How many records actually processed
  records_changed INT64,  -- How many records actually changed (0 = waste)

  -- Change metadata
  trigger_reason STRING,  -- 'full_load', 'injury_update', 'spread_change', 'manual', etc.
  change_type STRING,  -- 'incremental' or 'full_load'
  source_table STRING,  -- Which Phase 2 table triggered this

  -- Performance metrics
  started_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP,
  duration_seconds FLOAT64,
  success BOOLEAN,
  error_message STRING,

  -- Dependency tracking
  dependencies_checked ARRAY<STRING>,  -- Which tables were checked
  dependencies_passed BOOLEAN,

  -- Cost tracking (future)
  bytes_processed INT64,
  estimated_cost_usd FLOAT64,

  -- Processing metadata
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY processor_name, phase, game_date;
```

**Questions:**
- Is this schema sufficient for decision-making?
- Which metrics are most important?
- What thresholds indicate "time to optimize"?
  - e.g., "If waste_pct > 30%, implement entity-level"
  - e.g., "If avg processing time > 60s, optimize"
  - e.g., "If records_changed / records_processed < 0.5, too much waste"
- Should we track at message level, processor level, or both?
- Any additional fields needed?

**Decision criteria we need:**
- When is date-level processing "good enough"? (Acceptable thresholds)
- When is entity-level optimization "worth it"? (ROI calculation)
- How do we measure success after implementing entity-level?

**Your recommendation:**
- Minimum viable monitoring to start?
- Key metrics for decision-making?
- Clear thresholds for when to optimize?

---

#### Q9: Smart Routing (Skipping Irrelevant Processors)

**Question:** Should messages include `changed_fields` to skip irrelevant processors?

**Example:**
```json
{
  "source_table": "odds_api_game_lines",
  "metadata": {
    "changed_fields": ["spread", "moneyline"]
  }
}
```

**Processor relevance config:**
```python
PROCESSOR_RELEVANCE = {
    'PlayerGameSummaryProcessor': {
        'relevant_tables': ['nbac_gamebook_player_stats', 'bdl_player_boxscores'],
        'irrelevant_tables': ['odds_api_game_lines']  # Doesn't use odds data
    },
    'GamePredictionProcessor': {
        'relevant_tables': ['odds_api_game_lines'],    # Does use odds data
        'relevant_fields': ['spread', 'moneyline']
    }
}

def should_trigger_processor(processor_class, message):
    source_table = message['source_table']
    config = PROCESSOR_RELEVANCE[processor_class.__name__]

    if source_table in config.get('irrelevant_tables', []):
        return False  # Skip this processor

    return True
```

**Questions:**
- Is this optimization worth the complexity?
- How do we maintain relevance configs?
- Start simple (process everything) or implement upfront?

**Your recommendation:** Include smart routing in initial design or defer?

---

#### Q10: Backfill Integration

**Question:** How should backfills use this architecture?

**Options:**
- **Option A: Always full date for backfills** - Simpler, ensures consistency
- **Option B: Entity-level for targeted backfills** - More flexible (e.g., fix one player)
- **Option C: Adaptive** - Full date for large backfills, entity-level for corrections

**Backfill triggering:**
```python
# Manual backfill script
python backfill.py \
    --processor player_game_summary \
    --start-date 2024-10-01 \
    --end-date 2025-02-01 \
    --mode full_date

# vs. Entity-level correction
python backfill.py \
    --processor player_game_summary \
    --player-ids 1630567 \
    --start-date 2024-10-01 \
    --end-date 2025-02-01 \
    --mode entity_level
```

**Questions:**
- Do backfills use pub/sub or direct processor calls?
- How do we handle cross-date dependencies (Phase 4 needs last 10 games)?
- Can we run dependency checks before backfilling?

**Your recommendation:** Backfill strategy and integration points?

---

### 🟢 Nice-to-Have Questions (If Time Permits)

#### Q11: Message Ordering

**Question:** Do we need ordering guarantees?

**Example problem:**
```
11:00 AM - Stat correction: Rebounds 12 → 13 (sequence #1)
11:15 AM - Another correction: Rebounds 13 → 11 (sequence #2)

If messages arrive out of order:
  ├─ Process #2 first: rebounds = 11 ✅
  └─ Process #1 second: rebounds = 13 ❌ (WRONG!)
```

**Solutions:**
- **Ordering keys** - Pub/Sub FIFO guarantee within key (but reduces parallelism)
- **Sequence numbers** - Detect and skip stale messages
- **Timestamps** - Last-writer-wins (simpler, but clock skew issues)

**Your recommendation:** Need ordering? If so, which approach?

---

#### Q12: Idempotency Validation

**Question:** How do we ensure all processors are idempotent?

**Idempotent patterns (SAFE):**
```python
# ✅ Overwrite with computed value
UPDATE table SET points = @points WHERE player_id = @id

# ✅ INSERT OR REPLACE
INSERT INTO table VALUES (...)
ON CONFLICT DO UPDATE SET ...

# ✅ Deterministic calculations
SELECT AVG(points) FROM games WHERE player_id = @id
```

**Non-idempotent patterns (DANGEROUS):**
```python
# ❌ Incrementing
UPDATE table SET games_played = games_played + 1

# ❌ Appending
UPDATE table SET recent_games = ARRAY_CONCAT(recent_games, [@game])

# ❌ Current timestamp (changes every run)
UPDATE table SET updated_at = CURRENT_TIMESTAMP()
```

**Your recommendation:** Testing strategy to validate idempotency?

---

#### Q13: Additional Monitoring Details

**Question:** Beyond the core metrics in Q8, what additional monitoring should we implement?

**Proposed metrics:**
```sql
-- 1. Processing waste
SELECT
    processor_name,
    COUNT(*) as total_runs,
    COUNTIF(records_processed = 0) as no_change_runs,
    ROUND(COUNTIF(records_processed = 0) / COUNT(*) * 100, 2) as waste_pct
FROM pipeline_execution_log
GROUP BY processor_name;

-- 2. Entity processing ratio
SELECT
    processor_name,
    AVG(records_processed / affected_entity_count) as avg_ratio
FROM pipeline_execution_log
WHERE affected_entity_count > 0;

-- 3. Cost by trigger type
SELECT
    trigger_reason,
    COUNT(*) as frequency,
    AVG(duration_seconds) as avg_duration,
    SUM(duration_seconds) as total_duration
FROM pipeline_execution_log
GROUP BY trigger_reason;
```

**Questions:**
- What schema for `pipeline_execution_log` table?
- How do we track entity-level vs. full processing?
- What alerts to set up?

**Your recommendation:** Minimum viable metrics to track?

---

## Architecture Patterns

We've documented three potential patterns in `docs/architecture/06-change-detection-and-event-granularity.md`. Here's a comparison:

| Pattern | Change Detection | Granularity | Complexity | When to Use |
|---------|------------------|-------------|------------|-------------|
| **Pattern 1: Change Metadata** | Sender includes changed fields | Entity list in message | Medium | Small-medium changes (<100 entities) |
| **Pattern 2: Multiple Event Types** | Different event types for different changes | Type-specific | High | Need very explicit semantics |
| **Pattern 3: Timestamp-Based** | Receiver queries for changes | Query-driven | Medium | Can't modify message structure |

### Pattern 1: Change Metadata (Recommended Starting Point)

**Enhanced message:**
```json
{
  "event_type": "raw_data_loaded",
  "source_table": "nbac_injury_report",
  "game_date": "2025-11-19",
  "affected_entities": {
    "players": ["1630567"]
  },
  "metadata": {
    "changed_fields": ["injury_status"],
    "trigger_reason": "injury_update"
  }
}
```

**Benefits:**
- ✅ Simple to implement
- ✅ Backward compatible (optional fields)
- ✅ Enables smart routing

---

### Pattern 2: Multiple Event Types

**Instead of generic `raw_data_loaded`, use specific types:**
```json
// Event Type 1: Full stats load
{
  "event_type": "game_stats_loaded",
  "trigger_all_analytics": true
}

// Event Type 2: Injury update
{
  "event_type": "player_status_changed",
  "affected_entities": {"players": ["1630567"]}
}

// Event Type 3: Betting context
{
  "event_type": "game_context_updated",
  "skip_analytics": ["player_summary"]
}
```

**Benefits:**
- ✅ Very explicit semantics
- ❌ More schemas to maintain

---

### Pattern 3: Timestamp-Based Detection

**Receiver queries for changes:**
```python
def run(self, opts):
    last_run = self.get_last_successful_run(opts['game_date'])

    if last_run:
        # Incremental: Find what changed since last run
        changed_players = query(f"""
            SELECT DISTINCT player_id
            FROM nba_raw.player_stats
            WHERE game_date = '{game_date}'
              AND processed_at > '{last_run.completed_at}'
        """)
    else:
        # First run: Process all
        changed_players = get_all_players(game_date)
```

**Benefits:**
- ✅ Flexible (receiver controls logic)
- ❌ Requires selective `processed_at` updates in Phase 2

---

## User Requirements & Thoughts

**IMPORTANT:** These are hypothetical future-state examples showing how entity-level processing MIGHT work if implemented. They describe a vision, **NOT current behavior**.

**Current reality:** None of this entity-level logic exists yet. We're asking whether this approach makes sense and how to phase it in.

These are the user's (Naji's) initial thoughts to validate or challenge through your analysis.

### Fine-Grained Change Handling

> "The main goal is to not have the prediction system run unnecessary amount of times. This starts with having the earlier phases not re-run unnecessary computations."

**Key requirement:** If a single player's injury status changes, don't reprocess all 450 players.

---

### Change Detection Responsibility

> "I don't expect the scraper to know what has changed since the last change, so maybe then the phase 2 processor will only update the database record for the player or players that have an updated status compared to what is already in the database."

**Approach:** Phase 2 processor detects changes (via MERGE logic or hash comparison), not the scraper.

**Flow:**
1. Phase 1 scraper: Collects all current data (doesn't know what changed)
2. Phase 2 processor: Compares against BigQuery, detects LeBron's status changed
3. Phase 2 processor: Updates only LeBron's record
4. Phase 2 processor: Publishes message with `affected_entities: {players: ["1630567"]}`

---

### Message Propagation

> "That way phase 3 will get a message that for a specific date, the injury data has changed and it can check which players specifically have changed data and at that point in the pipeline the players to process has been filtered."

**Flow:**
1. Phase 2 publishes: `{game_date: "2025-11-19", affected_entities: {players: ["1630567"]}}`
2. Phase 3 receives: Processes only player ID 1630567
3. Phase 3 publishes: `{game_date: "2025-11-19", affected_entities: {players: ["1630567"]}}`
4. Phase 4 receives: Processes only player ID 1630567
5. And so on...

---

### Message Content Flexibility

> "We will also need to handle messages that pass player IDs in them (or team ID if it is team data). That way I can also have the ability to tell it to process specific message IDs by passing a message to it. This will be good for testing and backfilling data as well."

**Requirements:**
- Messages can contain entity IDs (player_ids, team_ids, game_ids)
- Support manual triggers with specific IDs (testing, backfills)
- Handle different entity types (players, teams, games)

**Example manual trigger:**
```bash
# Manually trigger Phase 3 for specific players
gcloud pubsub topics publish nba-phase2-raw-complete \
  --message '{
    "source_table": "nbac_injury_report",
    "game_date": "2025-11-19",
    "affected_entities": {
      "players": ["1630567", "1629029"]
    },
    "trigger_source": "manual"
  }'
```

---

### Message Size Concerns

> "But also if there are too many IDs, the message could be too big and might exceed the allowed size."

**Questions:**
- What's the threshold? <100 entities → list them, ≥100 → process all?
- Use compression?
- Split into multiple messages?

---

### Change Detection Components

> "If the downstream processor or phase 5 service looks back to see what changed, will it be an independent new piece that determines it or part of the process or phase 5 service code?"

**Questions:**
- Should change detection be a separate service/module?
- Or embedded in each processor?
- Reusable change detection utilities?

---

## Edge Cases & Concerns

### Concern 1: Cross-Entity Dependencies

**Problem:** Entity-level processing might miss cascading effects.

**Example 1 - Direct Dependency:**
```
LeBron scores 50 points (affected entity: LeBron)
  → Team total points change (Lakers team aggregate)
  → Opponent defensive stats change (opposing team)
  → Teammate usage rates change (other Lakers players)
```

**Example 2 - Indirect Dependency:**
```
Spread changes -6.5 to -7.5 (affected entity: Lakers vs Warriors game)
  → Total points prediction changes
  → Over/under props change for ALL players in that game
```

**Question:** How do we expand affected entities based on dependencies?

**Proposed solution:**
```python
class ProcessorDependencyConfig:
    """Configure how each processor handles entity expansion."""

    PLAYER_GAME_SUMMARY = {
        'entity_level_safe': True,      # Can process single players
        'requires_expansion': False,
        'expansion_strategy': None
    }

    TEAM_AGGREGATE = {
        'entity_level_safe': False,     # Must process all team members
        'requires_expansion': True,
        'expansion_strategy': 'all_players_on_team',
        'reason': 'Sum of all players - one change affects total'
    }

    LEAGUE_RANKINGS = {
        'entity_level_safe': False,     # Rankings are relative
        'requires_expansion': True,
        'expansion_strategy': 'all_players_in_league',
        'reason': 'Rankings relative to all players'
    }
```

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

**Solution Option 1: Data Readiness Checks**
```python
class PlayerGameSummaryProcessor:
    REQUIRED_TABLES = [
        'nbac_gamebook_player_stats',
        'nbac_injury_report',
        'nbac_player_tracking'
    ]

    def validate_data_completeness(self, game_date, player_ids):
        for table in self.REQUIRED_TABLES:
            missing = check_if_data_exists(table, game_date, player_ids)
            if missing:
                raise DataNotReadyError(f"Missing {table} for {len(missing)} players")
```

**Solution Option 2: Data Completeness Metadata**
```json
{
  "source_table": "nbac_injury_report",
  "data_completeness": {
    "required_for_analytics": [
      "nbac_gamebook_player_stats",
      "nbac_injury_report"
    ],
    "tables_ready": ["nbac_injury_report"],
    "tables_pending": ["nbac_gamebook_player_stats"],
    "ready_to_process": false
  }
}
```

**Question:** Which approach? Or different approach?

---

### Concern 3: Message Ordering

**Problem:** Updates might arrive out of order.

**Solutions:**
- **Ordering keys:** Pub/Sub FIFO within key (e.g., `player:1630567:2025-11-19`)
- **Sequence numbers:** Detect stale messages
- **Timestamps:** Last-writer-wins

**Question:** Need ordering guarantees? Performance impact?

---

### Concern 4: Partial Failure Recovery

**Problem:** What if entity-level processing succeeds for some entities but fails for others?

**Example:**
```
affected_entities: [player1, player2, player3]

Processing:
  player1: ✅ Success
  player2: ❌ ERROR (missing data)
  player3: ✅ Success

Should we:
  A) Retry all 3?
  B) Just retry player2?
  C) Track partial progress?
```

**Strategy 1: All-or-Nothing (Simple)**
- Rollback entire batch if any entity fails
- Retry entire message
- ✅ Simple
- ❌ Wastes reprocessing

**Strategy 2: Per-Entity Retry (Complex)**
- Track success/failure per entity
- Retry only failed entities
- ✅ Efficient
- ❌ Complex state management

**Question:** Which strategy?

---

## Constraints

### 🔴 Hard Constraints (Cannot Violate)

1. **Google Cloud Pub/Sub limits:**
   - Maximum message size: 10 MB
   - Must handle 450 players × multiple phases
   - Cannot exceed cost budget

2. **Data consistency:**
   - Must support backfills for 4 seasons of historical data
   - Predictions must be based on complete, consistent data
   - Cannot have partial/incomplete analytics

3. **System reliability:**
   - Must handle retries (processors must be idempotent)
   - Must support manual recovery (dead letter queues, replay)
   - Cannot lose messages or data

4. **Entity scale:**
   - Must handle 450 players daily
   - Must handle 30 teams
   - Must handle 10-15 games per day

---

### 🟡 Soft Constraints (Prefer but Flexible)

1. **Performance targets:**
   - Incremental updates <5 seconds (currently ~30 seconds)
   - Want 10-60x speedup for single-entity updates
   - Total pipeline end-to-end <10 minutes

2. **Message size:**
   - Prefer messages <1 MB (more like <100 KB)
   - Avoid message splitting if possible

3. **Backward compatibility:**
   - Prefer gradual migration (support both date-level and entity-level)
   - Avoid breaking existing processors during migration
   - Enable rollback to date-level if entity-level has issues

4. **Developer experience:**
   - Solution should be easy to understand and debug
   - Prefer simple over complex unless metrics show clear need
   - Good logging and observability

5. **Cost optimization:**
   - Reduce wasted compute (processing unchanged entities)
   - But don't over-optimize prematurely

---

## Success Criteria & Deliverables

### Primary Deliverable: Strategic Guidance + Architecture Recommendation

**Critical: We want strategic guidance on WHAT to build WHEN, not just HOW to build entity-level.**

**Must include:**

**1. Strategic Roadmap:**
- ✅ **Phase 1 (Now):** What to implement immediately (likely date-level with instrumentation)
- ✅ **Phase 2 (Later):** What to add when metrics show need (entity-level optimization)
- ✅ **Phase 3 (Future):** Advanced optimizations (batching, smart routing, etc.)
- ✅ Clear triggers for moving between phases (metric thresholds)

**2. Monitoring & Measurement Strategy:**
- ✅ Minimum viable monitoring schema (`pipeline_execution_log` structure)
- ✅ Key metrics to track from day 1
- ✅ Decision criteria: When is optimization worth it?
- ✅ Thresholds for moving from date-level to entity-level

**3. Architecture Recommendations:**
- ✅ Recommended message structure (design for evolution)
- ✅ Change detection strategy (sender vs. receiver vs. both)
- ✅ Entity granularity approach (when to use which)
- ✅ Integration with existing dependency tracking system
- ✅ Cross-entity dependency handling plan
- ✅ Batching/windowing considerations

---

### Secondary Deliverable: Implementation Roadmap

**Must include:**
- ✅ Step-by-step migration plan (current date-level → future entity-level)
- ✅ Backward compatibility strategy (support both during migration)
- ✅ Key metrics to track (waste percentage, entity ratios, etc.)
- ✅ Testing/validation approach (how to verify it's working)

---

### Specific Decisions We Need

**Message Structure:**
- [ ] Should we include `affected_entities`? Format?
- [ ] Should we include `metadata.changed_fields`?
- [ ] Different structures for different entity types?

**Change Detection:**
- [ ] Who detects changes: sender, receiver, or both?
- [ ] How to detect: hash comparison, timestamp comparison, or message metadata?

**Entity Expansion:**
- [ ] How to handle cross-entity dependencies (team → players)?
- [ ] Where does expansion happen: sender, receiver, or separate service?

**Thresholds:**
- [ ] Entity count threshold for fallback to full processing?
- [ ] Message size threshold for splitting?

**Backfills:**
- [ ] Use entity-level for backfills or always full date?
- [ ] How to handle cross-date dependencies?

**Monitoring:**
- [ ] What metrics to track?
- [ ] What schema for execution log?

---

### Out of Scope (For Now)

**Not needed in this analysis:**
- ❌ Actual code implementation
- ❌ Performance benchmarks (we'll measure after implementation)
- ❌ Cost calculations (mention approach but don't calculate)
- ❌ Specific BigQuery schema changes
- ❌ Complete test suite design

---

## What We're NOT Looking For

To be clear, here's what we're **NOT** asking for:

❌ A detailed implementation with specific code
❌ Database schema changes (schemas are finalized)
❌ Replacing Pub/Sub with a different messaging system
❌ Adding a complex orchestration framework (Airflow, Prefect, etc.)
❌ Real-time streaming (we're batch-oriented with near-real-time updates)
❌ Machine learning for change prediction
❌ Complex caching layers or materialized views

✅ Practical recommendations using our existing GCP stack
✅ Incremental improvements we can ship in phases
✅ Simple solutions that we can iterate on
✅ Clear decision criteria and priorities
✅ Migration strategy from current to future state

---

## Related Documentation

### Files That Will Be Uploaded to This Chat

**✅ These will be attached for your reference:**

| File | Priority | Why | Size |
|------|----------|-----|------|
| `docs/architecture/06-change-detection-and-event-granularity.md` | **Must Read** | Core design patterns (3 approaches) | 2400 lines |
| `docs/architecture/04-event-driven-pipeline-architecture.md` | **Must Read** | Complete 6-phase pipeline overview | 800 lines |
| **Dependency Tracking Wiki Doc** | **Must Read** | Existing v4.0 system we can leverage | 1200 lines |
| `docs/architecture/07-change-detection-current-state-investigation.md` | Reference | Test scenarios and queries | 700 lines |
| `docs/architecture/03-pipeline-monitoring-and-error-handling.md` | Reference | DLQ, retry, monitoring framework | 500 lines |

**Dependency Tracking System (v4.0) - Key existing system:**
- Tracks `source_{prefix}_last_updated`, `source_{prefix}_rows_found`, `source_{prefix}_completeness_pct`
- Base class methods: `track_source_usage()`, `check_dependencies()`, `build_source_tracking_fields()`
- **Could potentially be leveraged for change detection** (key integration question!)
- Fully implemented across Phase 3/4 processors

---

### Code Examples (Referenced in This Prompt, Not Uploaded)

**ℹ️ These are described in this prompt but not uploaded as files:**

We've included relevant code snippets directly in this prompt from:
- `scrapers/utils/pubsub_utils.py` - Phase 1→2 publishing (shown in prompt)
- `shared/utils/pubsub_publishers.py` - Phase 2→3 publishing (shown in prompt)
- `data_processors/raw/balldontlie/bdl_boxscores_processor.py` - Phase 2 MERGE logic (shown in prompt)
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py` - Phase 3 queries (shown in prompt)

You have enough code context from the snippets provided - no need to review full files.

---

### Other Docs (Mentioned for Context, Not Uploaded)

**ℹ️ Referenced but not critical for this analysis:**
- `docs/architecture/01-phase1-to-phase5-integration-plan.md` - Overall integration plan
- `docs/architecture/02-phase1-to-phase5-granular-updates.md` - Entity-level granularity design
- `docs/architecture/08-cross-date-dependency-management.md` - Cross-date dependencies (summarized in this prompt)
- `docs/processors/*` - Individual processor documentation

---

## Final Request

Please provide a **comprehensive analysis** addressing the questions, concerns, and requirements outlined above.

**Focus on:**
- ✅ Practical recommendations (not just theory)
- ✅ Clear decision criteria (when to use which approach)
- ✅ Implementation roadmap (how to get from here to there)
- ✅ Edge case handling (what could go wrong and how to prevent it)
- ✅ Migration strategy (incremental, low-risk path forward)

**Prioritize:**
1. 🔴 Critical questions (Q1-Q4) - **Must answer**
2. 🟡 Important questions (Q5-Q10) - **Should answer** (especially Q8: Monitoring Strategy!)
3. 🟢 Nice-to-have questions (Q11-Q13) - **If time permits**

**Remember:**
- We want to **ship something simple first**, then optimize based on metrics
- But we want to **design the architecture** so it can evolve without major rewrites
- We value **simplicity and debuggability** over complex optimizations
- We want **clear decision points** for when to use date-level vs. entity-level

---

## What We're Really Asking

**Strategic Planning Focus:**
We're not asking "How do we build entity-level processing?" (we can figure that out later)

We're asking:
1. **What should we build NOW?** (Likely simple date-level with good instrumentation)
2. **How do we MEASURE when optimization is needed?** (Metrics, thresholds, decision criteria)
3. **How do we design for FUTURE evolution?** (Message structure, architecture patterns)
4. **What are the TRIGGER points?** (When do metrics say "time to optimize"?)

**Example Decision Framework We Need:**
```
Phase 1 (Ship Now):
  - Date-level Pub/Sub messages
  - Date-level processor execution
  - BUT: Track metrics X, Y, Z from day 1
  - Trigger: When waste_pct > 30% OR avg_duration > 60s → Move to Phase 2

Phase 2 (Optimize Later):
  - Add affected_entities to messages
  - Add entity-level filtering to processors
  - Implement for Phase 3 first, then Phase 4
  - Trigger: When ROI > threshold → Move to Phase 3

Phase 3 (Advanced):
  - Batching/windowing
  - Smart routing
  - Cross-entity dependency expansion
  - Implement only if Phase 2 metrics show need
```

**We want YOU to design this phased approach with clear, measurable triggers.**

---

**Thank you for your thorough analysis! We're looking forward to your strategic recommendations.**

---

**End of Prompt**
