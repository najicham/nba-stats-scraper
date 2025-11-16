# Change Detection & Event Granularity

**File:** `docs/architecture/06-change-detection-and-event-granularity.md`
**Created:** 2025-11-15
**Last Updated:** 2025-11-15
**Purpose:** Design patterns for handling partial updates and fine-grained change detection
**Status:** Future Enhancement - Ship simple first, optimize based on real metrics
**Related:** [02-phase1-to-phase5-granular-updates.md](./02-phase1-to-phase5-granular-updates.md) (entity-level granularity)

---

## Table of Contents

1. [The Problem](#the-problem)
2. [Current Design (Sprints 1-7)](#current-design-sprints-1-7)
3. [Enhancement Patterns](#enhancement-patterns)
4. [When to Optimize](#when-to-optimize)
5. [Decision Framework](#decision-framework)
6. [Implementation Roadmap](#implementation-roadmap)

---

## The Problem

**Question:** When a small change happens in Phase 2 (e.g., pointspread moves, single player injury), should we:
- A) Reprocess everything related to that date? (simple but wasteful)
- B) Reprocess only affected entities? (efficient but complex)
- C) Skip processing if change isn't relevant? (most efficient, most complex)

**Real-world scenarios:**

1. **Pointspread changes** -5.5 to -6.5 for one game
   - Affects: Betting context for that game
   - Doesn't affect: Player stats for 450 players
   - Question: Should we trigger `PlayerGameSummaryProcessor`?

2. **Single player injury update** - LeBron ruled OUT
   - Affects: LeBron's injury_status field
   - Doesn't affect: His points/rebounds/assists stats
   - Question: Recompute all analytics or just injury-related?

3. **Stat correction** - Single player's rebounds corrected (12 → 13)
   - Affects: That player's boxscore
   - Doesn't affect: Other 24 players in the game
   - Question: Recompute all players or just that one?

**The architectural challenge:** Balance simplicity vs efficiency vs complexity.

---

## Current Design (Sprints 1-7)

### Phase 1-3: Date-Level Processing (Sprints 1-3)

**Message format:**
```json
{
  "event_type": "raw_data_loaded",
  "source_table": "odds_api_game_lines",
  "game_date": "2025-11-15",
  "record_count": 10,
  "status": "success"
}
```

**Phase 3 behavior:**
```python
# Process ALL games for the date
processor.run({
    'start_date': '2025-11-15',
    'end_date': '2025-11-15'
})
# → Reprocesses all 10 games, all ~450 players
```

**Trade-offs:**
- ✅ Simple to implement
- ✅ Always correct (no missed updates)
- ✅ No complex change tracking
- ❌ Wasteful for small changes
- ❌ Slow for single-entity updates

**Acceptable for:** Initial implementation, low update frequency, small datasets

---

### Phase 3 Enhancement: Entity-Level Processing (Sprint 8)

**Enhanced message format:**
```json
{
  "event_type": "raw_data_loaded",
  "source_table": "nbac_injury_report",
  "game_date": "2025-11-15",

  "affected_entities": {
    "players": ["1630567"],        // Just LeBron
    "teams": ["LAL"],
    "games": ["0022500225"]
  },

  "change_type": "incremental",    // vs "full_load"
  "record_count": 1
}
```

**Phase 3 behavior:**
```python
# Process only affected player
processor.run({
    'game_date': '2025-11-15',
    'player_ids': ['1630567']  # Just LeBron
})
# → Processes 1 player in 0.5s (vs 450 players in 30s)
```

**Performance improvement:**
- Injury update: **60x faster** (0.5s vs 30s)
- Stat correction: **60x faster**
- Full boxscore load: Same speed (processes all players anyway)

**Trade-offs:**
- ✅ Much faster for incremental updates
- ✅ Still simple (Publisher knows affected entities)
- ✅ Backward compatible (Subscriber can ignore and process all)
- ❌ Doesn't address "irrelevant changes" problem
- ❌ Doesn't handle field-level granularity

**Acceptable for:** 80% of optimization needs, most incremental updates

---

## Enhancement Patterns

### Pattern 1: Change Metadata (Recommended Next Step)

**Add field-level information to messages:**

```json
{
  "event_type": "raw_data_loaded",
  "source_table": "odds_api_game_lines",
  "game_date": "2025-11-15",

  "affected_entities": {
    "games": ["0022500225"],
    "teams": ["LAL", "BOS"]
  },

  "change_type": "incremental",

  "metadata": {
    "changed_fields": ["spread", "spread_odds"],
    "unchanged_fields": ["moneyline", "total", "player_props"],
    "change_scope": {
      "total_records": 1,
      "changed_records": 1,
      "new_records": 0,
      "updated_records": 1
    },
    "trigger_reason": "line_movement",
    "significant_change": true  // e.g., >1 point spread move
  }
}
```

**How Phase 3 uses this:**

```python
PROCESSOR_RELEVANCE = {
    'PlayerGameSummaryProcessor': {
        'relevant_tables': ['nbac_gamebook_player_stats', 'bdl_player_boxscores'],
        'relevant_fields': ['points', 'rebounds', 'assists', 'minutes', 'injury_status'],
        'irrelevant_tables': ['odds_api_game_lines']  # Doesn't use betting data
    },
    'TeamSpreadContextProcessor': {
        'relevant_tables': ['odds_api_game_lines'],
        'relevant_fields': ['spread', 'moneyline'],
        'skip_if_only': ['player_props']  // Skip if only props changed
    }
}

def should_trigger_processor(processor_class, message):
    """Smart routing based on change metadata."""

    source_table = message['source_table']
    changed_fields = message.get('metadata', {}).get('changed_fields', [])

    config = PROCESSOR_RELEVANCE.get(processor_class.__name__, {})

    # Check if table is irrelevant
    if source_table in config.get('irrelevant_tables', []):
        logger.info(f"Skipping {processor_class.__name__} - {source_table} not relevant")
        return False

    # Check if changed fields are relevant
    relevant_fields = config.get('relevant_fields', [])
    if changed_fields and relevant_fields:
        if not any(field in changed_fields for field in relevant_fields):
            logger.info(f"Skipping {processor_class.__name__} - no relevant fields changed")
            return False

    return True  # Default: process
```

**Example: Pointspread change doesn't trigger player processors:**

```
Phase 2: odds_api_game_lines updates
  └─► Publishes: {changed_fields: ["spread"], affected_entities: {games: ["0022500225"]}}

Phase 3 Analytics Service receives event:
  ├─► Check: PlayerGameSummaryProcessor?
  │   └─► Relevance check: odds_api_game_lines in irrelevant_tables
  │   └─► Result: SKIP ✓ (saves 30 seconds of processing)
  │
  ├─► Check: TeamSpreadContextProcessor?
  │   └─► Relevance check: "spread" in relevant_fields
  │   └─► Result: PROCESS ✓ (this one needs it)
  │
  └─► Check: GamePredictionRefreshProcessor?
      └─► Relevance check: "spread" in relevant_fields
      └─► Result: PROCESS ✓ (predictions use spread)
```

**Benefits:**
- ✅ Avoid processing when not needed
- ✅ Publisher has this info anyway (knows what it changed)
- ✅ Optional (Subscriber can ignore and process everything)
- ✅ No breaking changes (backward compatible)

**When to implement:**
- After Sprint 8 (entity-level) is working
- When metrics show unnecessary processing (see Decision Framework)
- Estimated effort: ~4-6 hours

---

### Pattern 2: Multiple Event Types (Advanced)

**Instead of one `raw_data_loaded` event, use specific event types:**

```json
// Event Type 1: Full data load (post-game boxscores)
{
  "event_type": "game_stats_loaded",
  "source_table": "nbac_gamebook_player_stats",
  "affected_entities": {
    "games": ["0022500225"],
    "players": [...],  // All players in game
    "teams": ["LAL", "BOS"]
  },
  "load_type": "full",
  "trigger_all_analytics": true
}

// Event Type 2: Injury status update
{
  "event_type": "player_status_changed",
  "source_table": "nbac_injury_report",
  "affected_entities": {
    "players": ["1630567"]
  },
  "status_change": {
    "old": "probable",
    "new": "out"
  },
  "trigger_analytics": ["player_summary", "team_roster_context"]
}

// Event Type 3: Betting context update
{
  "event_type": "game_context_updated",
  "source_table": "odds_api_game_lines",
  "affected_entities": {
    "games": ["0022500225"]
  },
  "context_type": "betting_lines",
  "trigger_analytics": ["game_predictions", "spread_analysis"],
  "skip_analytics": ["player_summary", "team_stats"]  // Explicit skip
}
```

**Phase 3 routing by event type:**

```python
ANALYTICS_TRIGGERS = {
    'game_stats_loaded': {
        'nbac_gamebook_player_stats': [
            PlayerGameSummaryProcessor,
            TeamOffenseProcessor,
            TeamDefenseProcessor,
            PlayerStreaksProcessor
        ]
    },
    'player_status_changed': {
        'nbac_injury_report': [
            PlayerGameSummaryProcessor,  // Update injury status
            TeamRosterContextProcessor   // Update team availability
            # NOT: TeamOffenseProcessor (stats unchanged)
        ]
    },
    'game_context_updated': {
        'odds_api_game_lines': [
            GamePredictionRefreshProcessor,
            TeamSpreadContextProcessor
            # NOT: PlayerGameSummaryProcessor (doesn't use odds)
        ]
    }
}
```

**Benefits:**
- ✅ Very explicit about what should process
- ✅ Clear semantics (event name describes what happened)
- ✅ Easy to route different event types differently
- ✅ Can skip irrelevant processors entirely

**Trade-offs:**
- ❌ More event schemas to maintain
- ❌ More complex publishing logic (decide which event type)
- ❌ More complex routing logic (handle multiple event types)
- ❌ Risk of missing triggers if event types wrong

**When to implement:**
- Only if Pattern 1 (change metadata) isn't sufficient
- When clear semantic differences between update types
- Estimated effort: ~8-12 hours

---

### Pattern 3: Timestamp-Based Change Detection (Subscriber-Driven)

**Publisher doesn't track changes, Subscriber queries for them:**

```python
class PlayerGameSummaryProcessor(AnalyticsProcessorBase):

    def run(self, opts):
        game_date = opts['game_date']

        # Check when we last successfully processed this date
        last_run = self.get_last_successful_run(game_date)

        if not last_run:
            # First time processing this date - process all
            player_ids = self.get_all_players_for_date(game_date)
        else:
            # Incremental - find what changed since last run
            changed_players_query = f"""
                SELECT DISTINCT universal_player_id
                FROM nba_raw.nbac_gamebook_player_stats
                WHERE game_date = '{game_date}'
                  AND updated_at > '{last_run.completed_at}'
            """
            player_ids = execute_query(changed_players_query)

            if not player_ids:
                logger.info(f"No changes since {last_run.completed_at}, skipping")
                return True

        # Process only changed players
        logger.info(f"Processing {len(player_ids)} players with changes")
        self.process_players(player_ids, game_date)
```

**Requirements:**
- All Phase 2 tables need `updated_at TIMESTAMP` column
- Phase 2 processors must update this timestamp on every write
- Phase 3 processors must track their last successful run

**Benefits:**
- ✅ Publisher doesn't need to track changes
- ✅ Subscriber has full control
- ✅ Works for any change detection logic
- ✅ Can detect changes across multiple source tables

**Trade-offs:**
- ❌ Requires timestamp columns everywhere
- ❌ Extra query on every processor run (performance overhead)
- ❌ Harder for aggregated data (how to know if average changed?)
- ❌ Clock skew issues (what if timestamps unreliable?)

**When to implement:**
- If Publisher can't reliably track changes
- If Subscriber needs complex change detection logic
- If timestamp infrastructure already exists
- Estimated effort: ~6-8 hours + schema changes

---

## When to Optimize

### Metrics to Watch

**Start simple (Sprints 1-7), optimize when you see:**

#### 1. Unnecessary Processing Time

**Metric:** Time spent processing irrelevant changes

```sql
-- Query: How often do processors run when data hasn't changed?
SELECT
    processor_name,
    COUNT(*) as total_runs,
    COUNTIF(records_processed = 0) as no_change_runs,
    ROUND(COUNTIF(records_processed = 0) / COUNT(*) * 100, 2) as waste_percentage,
    SUM(duration_seconds) as total_seconds,
    SUM(IF(records_processed = 0, duration_seconds, 0)) as wasted_seconds
FROM nba_orchestration.pipeline_execution_log
WHERE game_date >= CURRENT_DATE() - 7
  AND status = 'completed'
GROUP BY processor_name
HAVING waste_percentage > 20  -- >20% of runs process nothing
ORDER BY wasted_seconds DESC;
```

**Red flags:**
- 🔴 >30% of runs process 0 records (high waste)
- 🔴 >5 minutes/day wasted on irrelevant processing
- 🔴 Processors running >10x/day when source data changes <2x/day

**Action:** Implement Pattern 1 (change metadata) to skip irrelevant triggers

---

#### 2. Entity-Level Processing Gaps

**Metric:** How many entities affected vs how many processed

```sql
-- Query: Are we processing too many entities?
SELECT
    processor_name,
    game_date,
    JSON_EXTRACT_SCALAR(metadata, '$.affected_entity_count') as affected,
    records_processed,
    ROUND(records_processed / CAST(JSON_EXTRACT_SCALAR(metadata, '$.affected_entity_count') AS INT64), 2) as processing_ratio
FROM nba_orchestration.pipeline_execution_log
WHERE game_date >= CURRENT_DATE() - 7
  AND JSON_EXTRACT_SCALAR(metadata, '$.affected_entity_count') IS NOT NULL
  AND processing_ratio > 10  -- Processing 10x more than affected
ORDER BY processing_ratio DESC;
```

**Red flags:**
- 🔴 1 player injury → processes 450 players (ratio = 450)
- 🔴 1 game spread change → processes 10 games (ratio = 10)

**Action:** Implement Sprint 8 (entity-level granularity) if not done

---

#### 3. Field-Level Change Frequency

**Metric:** How often do specific fields change?

```sql
-- Query: Which fields change most often?
-- (Requires change metadata in messages)
SELECT
    source_table,
    field_name,
    COUNT(*) as change_count,
    COUNT(DISTINCT game_date) as days_with_changes
FROM nba_orchestration.pipeline_execution_log,
UNNEST(JSON_EXTRACT_ARRAY(metadata, '$.changed_fields')) as field_name
WHERE game_date >= CURRENT_DATE() - 30
GROUP BY source_table, field_name
ORDER BY change_count DESC;
```

**Red flags:**
- 🔴 `spread` changes 50x/day, but triggers processor that uses 0 fields from odds
- 🔴 `injury_status` changes trigger full stat recalculation

**Action:** Implement Pattern 1 (change metadata) with relevance checking

---

#### 4. Processing Cost per Change Type

**Metric:** Cost (time/compute) by update type

```sql
-- Query: What types of updates are most expensive?
SELECT
    JSON_EXTRACT_SCALAR(metadata, '$.trigger_reason') as trigger_reason,
    COUNT(*) as occurrence_count,
    AVG(duration_seconds) as avg_duration,
    SUM(duration_seconds) as total_duration,
    AVG(records_processed) as avg_records
FROM nba_orchestration.pipeline_execution_log
WHERE game_date >= CURRENT_DATE() - 7
  AND status = 'completed'
GROUP BY trigger_reason
ORDER BY total_duration DESC;
```

**Example results:**
```
trigger_reason        | occurrences | avg_duration | total_duration | avg_records
----------------------|-------------|--------------|----------------|-------------
line_movement         | 150         | 28.5s        | 4,275s (1.2hr) | 450
stat_correction       | 5           | 29.1s        | 145s           | 450
injury_update         | 8           | 27.8s        | 222s           | 450
post_game_load        | 10          | 31.2s        | 312s           | 450
```

**Red flags:**
- 🔴 `line_movement` (doesn't need player processing) = 1.2 hours/week wasted
- 🔴 All update types process same 450 records (no entity filtering)

**Action:**
1. Implement entity-level for `stat_correction`, `injury_update`
2. Implement smart routing for `line_movement` (skip player processors)

---

### Decision Framework

**Use this framework to decide when to optimize:**

```
┌─────────────────────────────────────────────────────────────┐
│                    OPTIMIZATION DECISION TREE                │
└─────────────────────────────────────────────────────────────┘

1. Is processing fast enough? (<5s for incremental updates)
   │
   ├─► YES → ✅ Keep it simple, don't optimize yet
   │
   └─► NO → Continue to #2

2. Are you processing more than 10x affected entities?
   │   (e.g., 1 player change → processes 450 players)
   │
   ├─► YES → 🔧 Implement Sprint 8 (entity-level granularity)
   │   └─► Recheck metrics after implementation → Go to #1
   │
   └─► NO → Continue to #3

3. Are >20% of runs processing 0 records?
   │   (e.g., processor runs but finds nothing changed)
   │
   ├─► YES → 🔧 Implement Pattern 3 (timestamp-based detection)
   │   └─► Recheck metrics after implementation → Go to #1
   │
   └─► NO → Continue to #4

4. Are irrelevant changes triggering processing?
   │   (e.g., spread changes trigger player stat processing)
   │
   ├─► YES → 🔧 Implement Pattern 1 (change metadata + smart routing)
   │   └─► Recheck metrics after implementation → Go to #1
   │
   └─► NO → Continue to #5

5. Do different update types need different handling?
   │   (e.g., injury vs stat correction vs full load)
   │
   ├─► YES → 🔧 Implement Pattern 2 (multiple event types)
   │   └─► Recheck metrics after implementation → Go to #1
   │
   └─► NO → ✅ Your system is probably well-optimized!
       └─► Monitor metrics quarterly
```

---

### Cost-Benefit Analysis

**Before optimizing, calculate ROI:**

```python
# Example calculation
current_waste_hours_per_week = 5  # From metrics
engineer_hours_to_implement = 6   # Pattern 1: change metadata
weeks_to_break_even = engineer_hours_to_implement / current_waste_hours_per_week
# Result: 1.2 weeks

if weeks_to_break_even < 4:
    print("✅ Worth optimizing - pays back in < 1 month")
elif weeks_to_break_even < 12:
    print("⚠️  Marginal - optimize if you have time")
else:
    print("❌ Not worth it - waste is too small")
```

**Rule of thumb:**
- 💰 **High value:** Saves >5 hours/week, costs <8 hours to implement
- 🤷 **Medium value:** Saves >2 hours/week, costs <6 hours to implement
- 💸 **Low value:** Saves <1 hour/week - probably not worth it yet

---

## Implementation Roadmap

### Sprint 1-7: Ship Simple (CURRENT)

**Approach:** Full reprocessing on any change

**Message format:**
```json
{
  "source_table": "nbac_gamebook_player_stats",
  "game_date": "2025-11-15",
  "status": "success"
}
```

**Behavior:** Process all entities for the date

**Acceptable because:**
- ✅ Simple to implement (fastest to ship)
- ✅ Always correct (no missed updates)
- ✅ Good enough for initial deployment
- ✅ Baseline for measuring future optimizations

---

### Sprint 8: Entity-Level Granularity (~12 hours)

**Approach:** Process only affected entities

**Message enhancement:**
```json
{
  "source_table": "nbac_injury_report",
  "game_date": "2025-11-15",
  "affected_entities": {
    "players": ["1630567"],
    "games": ["0022500225"]
  },
  "change_type": "incremental"
}
```

**Processor enhancement:**
```python
processor.run({
    'game_date': '2025-11-15',
    'player_ids': ['1630567']  # Only process affected
})
```

**Expected impact:**
- ⚡ 60x faster for single-entity updates (0.5s vs 30s)
- 💰 Saves ~2-5 hours/week of compute (based on update frequency)

**Implement when:**
- After Sprints 1-7 complete
- When incremental updates becoming common (>10/day)

---

### Future: Change Metadata (~4-6 hours)

**Approach:** Include field-level change info

**Message enhancement:**
```json
{
  "source_table": "odds_api_game_lines",
  "affected_entities": {...},
  "metadata": {
    "changed_fields": ["spread", "spread_odds"],
    "trigger_reason": "line_movement"
  }
}
```

**Smart routing:**
```python
if should_trigger_processor(PlayerGameSummaryProcessor, message):
    # Only if relevant fields changed
    processor.run(...)
```

**Expected impact:**
- ⚡ Skip 20-40% of irrelevant processing
- 💰 Saves ~1-3 hours/week of compute

**Implement when:**
- Metrics show >20% waste (processors running on irrelevant changes)
- Or when specific processor very expensive (>30s each run)

---

### Future: Multiple Event Types (~8-12 hours)

**Approach:** Different event types for different update semantics

**Only implement if:**
- Pattern 1 (change metadata) not sufficient
- Clear semantic differences between update types
- Need explicit control over what triggers

**Expected impact:**
- ⚡ Most precise control over triggering
- ❌ But adds complexity (more schemas to maintain)

**Implement when:**
- Never, unless metrics show clear need
- Consider Pattern 1 first (simpler, 80% of the benefit)

---

## Practical Guidelines

### For Implementers (Sprints 1-7)

**DO:**
- ✅ Ship with date-level processing (simple)
- ✅ Include `affected_entities` in messages (even if not used yet)
- ✅ Add `updated_at` timestamp columns to Phase 2 tables (future-proof)
- ✅ Log `records_processed` in pipeline_execution_log (for metrics)
- ✅ Monitor processing times and waste percentage

**DON'T:**
- ❌ Optimize prematurely (no metrics yet)
- ❌ Add complex change detection logic upfront
- ❌ Create multiple event types yet
- ❌ Worry about "wasteful processing" if total time <30s

**Remember:** "Make it work, make it right, make it fast" - you're at "make it work"

---

### For Operators (Monitoring)

**Watch these metrics:**

```sql
-- 1. Processing waste
SELECT
    processor_name,
    COUNTIF(records_processed = 0) / COUNT(*) * 100 as waste_pct
FROM pipeline_execution_log
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY processor_name;

-- 2. Entity processing ratio
SELECT
    processor_name,
    AVG(records_processed / affected_entity_count) as avg_ratio
FROM pipeline_execution_log
WHERE affected_entity_count > 0
GROUP BY processor_name;

-- 3. Processing time by trigger
SELECT
    trigger_reason,
    AVG(duration_seconds) as avg_duration,
    COUNT(*) as frequency
FROM pipeline_execution_log
GROUP BY trigger_reason;
```

**Alert when:**
- 🔴 Waste percentage >30% for any processor
- 🔴 Entity processing ratio >20 (processing 20x more than needed)
- 🔴 Total daily processing time >2 hours

---

### For Architects (Future Planning)

**Questions to ask before optimizing:**

1. **How much time are we wasting?**
   - <1 hour/week → Ignore
   - 1-5 hours/week → Monitor
   - >5 hours/week → Optimize

2. **What's the implementation cost?**
   - Pattern 1 (change metadata): ~4-6 hours
   - Sprint 8 (entity-level): ~12 hours
   - Pattern 2 (event types): ~8-12 hours

3. **What's the ROI?**
   - Break-even <4 weeks → High priority
   - Break-even 4-12 weeks → Medium priority
   - Break-even >12 weeks → Low priority

4. **What's the complexity cost?**
   - Will this make debugging harder?
   - Will this make onboarding harder?
   - Is the code maintainability worth the performance gain?

**Rule:** Optimize for developer productivity first, performance second (until performance becomes a problem).

---

## Examples

### Example 1: Injury Update (Simple → Optimized)

**Current (Sprints 1-7):**
```json
// Message
{"source_table": "nbac_injury_report", "game_date": "2025-11-15"}

// Processing
processor.run({'game_date': '2025-11-15'})
// → Processes 450 players, takes 30s
```

**Sprint 8 (Entity-level):**
```json
// Message
{
  "source_table": "nbac_injury_report",
  "game_date": "2025-11-15",
  "affected_entities": {"players": ["1630567"]}
}

// Processing
processor.run({'game_date': '2025-11-15', 'player_ids': ['1630567']})
// → Processes 1 player, takes 0.5s (60x faster ✓)
```

**Future (Change metadata):**
```json
// Message
{
  "source_table": "nbac_injury_report",
  "affected_entities": {"players": ["1630567"]},
  "metadata": {
    "changed_fields": ["injury_status"],
    "trigger_reason": "injury_update"
  }
}

// Processing
if 'injury_status' in message.metadata.changed_fields:
    processor.run({'player_ids': ['1630567']})
    // → Only injury-aware processors run
else:
    // → Skip if only other fields changed
```

---

### Example 2: Pointspread Change (Simple → Optimized)

**Current (Sprints 1-7):**
```json
// Message
{"source_table": "odds_api_game_lines", "game_date": "2025-11-15"}

// Processing - ALL processors triggered
PlayerGameSummaryProcessor.run(...)  // ❌ Doesn't use spread, wastes 30s
TeamOffenseProcessor.run(...)        // ❌ Doesn't use spread, wastes 15s
GamePredictionProcessor.run(...)     // ✅ Uses spread, needed
// Total: 45s (30s wasted)
```

**Sprint 8 (Entity-level):**
```json
// Message
{
  "source_table": "odds_api_game_lines",
  "affected_entities": {"games": ["0022500225"]}
}

// Processing - still all processors, but only 1 game
PlayerGameSummaryProcessor.run({'game_ids': ['0022500225']})  // ❌ Still processes ~25 players
GamePredictionProcessor.run({'game_ids': ['0022500225']})     // ✅ Needed
// Total: 3s (2s wasted, better but not optimal)
```

**Future (Change metadata + smart routing):**
```json
// Message
{
  "source_table": "odds_api_game_lines",
  "affected_entities": {"games": ["0022500225"]},
  "metadata": {
    "changed_fields": ["spread"],
    "trigger_reason": "line_movement"
  }
}

// Smart routing
for processor in [PlayerGameSummaryProcessor, GamePredictionProcessor]:
    if should_trigger_processor(processor, message):
        processor.run(...)

// Result:
// - PlayerGameSummaryProcessor: SKIPPED (irrelevant table)
// - GamePredictionProcessor: RUNS (uses spread)
// Total: 1s (no waste ✓)
```

---

## Summary

### What We Have (Sprints 1-7)

✅ **Date-level processing** - Simple, correct, good enough to ship

### What We Planned (Sprint 8)

⚡ **Entity-level granularity** - 60x faster for incremental updates

### What's Available (Future)

🎯 **Change metadata** - Skip irrelevant processing (Pattern 1)
🎯 **Multiple event types** - Explicit semantic control (Pattern 2)
🎯 **Timestamp detection** - Subscriber-driven change tracking (Pattern 3)

### When to Optimize

📊 **Use metrics** - Don't guess, measure waste
💰 **Calculate ROI** - Optimize only if break-even <4 weeks
🎓 **Keep it simple** - Ship, measure, optimize (in that order)

### Decision Criteria

**Optimize when you see:**
1. >30% waste (processing nothing)
2. >10x entity processing ratio
3. >5 hours/week wasted
4. Specific expensive processors (>30s each)

**Don't optimize when:**
1. Total processing time <30s
2. Changes infrequent (<10/day)
3. Implementation cost > waste cost
4. System working fine

---

**Remember:** It's okay to reprocess everything now! Ship simple, measure real usage, optimize based on actual metrics. The patterns are here when you need them.

---

**Last Updated:** 2025-11-15
**Status:** Future Enhancement - Reference when metrics indicate optimization needed
**Next Review:** After Sprint 8 completion, check metrics against Decision Framework
