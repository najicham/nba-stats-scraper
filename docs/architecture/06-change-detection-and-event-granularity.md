# Change Detection & Event Granularity

**File:** `docs/architecture/06-change-detection-and-event-granularity.md`
**Created:** 2025-11-15
**Last Updated:** 2025-11-15
**Purpose:** Design patterns for handling partial updates and fine-grained change detection
**Status:** Future Enhancement - Ship simple first, optimize based on real metrics
**Related:** [02-phase1-to-phase5-granular-updates.md](./02-phase1-to-phase5-granular-updates.md) (entity-level granularity)

---

## Implementation Status

**Last Status Update:** 2025-11-16

### ✅ Currently Implemented (Production)

| Component | Status | Location | Notes |
|-----------|--------|----------|-------|
| Phase 1→2 Event Publishing | ✅ DEPLOYED | `scrapers/utils/pubsub_utils.py` | Dual publishing to old + new topics |
| Phase 2→3 Event Publishing | ✅ CODE READY | `shared/utils/pubsub_publishers.py` | Deployed in nba-processors |
| Phase 2 Base Class Updates | ✅ CODE READY | `data_processors/raw/processor_base.py` | Publishing integration ready |
| Date-level Processing (Phase 3) | 🟡 PARTIAL | `data_processors/analytics/*` | Service deployed, needs processors |
| Basic Metrics Logging | 🔴 TODO | `nba_orchestration.pipeline_execution_log` | Schema exists, need to log |
| Message Structure (v1.0) | ✅ DEPLOYED | All publishers | Basic: source_table, game_date, status |

**Current Approach:** Everything processes at **date-level** (simple, always correct, good enough to ship)

---

### 🚧 Planned Next (Sprint 8 - Based on Metrics)

| Feature | Priority | Estimated Effort | Triggers When |
|---------|----------|------------------|---------------|
| Entity-Level Granularity | Medium | ~12 hours | Waste >30% OR duration >30s |
| `affected_entities` in messages | Medium | ~4 hours | With Sprint 8 |
| Entity-level processor support | Medium | ~8 hours | With Sprint 8 |

**Implement when:** Metrics show >30% waste or >30s processing time

---

### 📋 Future Enhancements (On-Demand)

| Pattern | Estimated Effort | Implement When | Expected Impact |
|---------|------------------|----------------|-----------------|
| Pattern 1: Change Metadata | ~4-6 hours | Waste >20% on irrelevant changes | Skip 20-40% of processing |
| Pattern 2: Multiple Event Types | ~8-12 hours | Pattern 1 insufficient | Explicit semantic control |
| Pattern 3: Timestamp Detection | ~6-8 hours | Publisher can't track changes | Subscriber-driven change detection |
| Ordering Keys + Sequence Numbers | ~6 hours | Out-of-order issues detected | Guarantee correct ordering |
| Per-Entity Retry | ~8 hours | Batch size >100, failures >5% | Efficient partial retry |
| Data Completeness Metadata | ~6 hours | Race conditions detected | Explicit readiness signals |

**Implement when:** Decision Framework (Section 5) indicates optimization needed

---

### 📖 Documentation Only (Reference)

These sections are **documentation of concerns**, not features to implement:

- ✅ Cross-Entity Dependencies (Section 7.1) - **Read before Sprint 8**
- ✅ Data Completeness & Race Conditions (Section 7.2) - **Reference if issues**
- ✅ Message Ordering (Section 7.3) - **Reference if out-of-order detected**
- ✅ Partial Failure Recovery (Section 7.4) - **Reference if retry issues**
- ✅ Idempotency Requirements (Section 7.5) - **Test checklist for Sprint 8**
- ✅ Message Size Limits (Section 7.6) - **Reference if messages too large**
- ✅ Debugging & Traceability (Section 7.7) - **Best practices reference**
- ✅ Rollback Strategy (Section 7.8) - **Emergency procedures**
- ✅ Backfill Considerations (Section 7.9) - **Reference for backfills**
- ✅ Schema Evolution (Section 7.10) - **Reference for breaking changes**
- ✅ Testing Strategies (Section 8) - **Test templates for Sprint 8**

**These are NOT tasks** - they're edge cases to be aware of when implementing optimizations.

---

## Table of Contents

1. [The Problem](#the-problem)
2. [Current Design (Sprints 1-7)](#current-design-sprints-1-7)
3. [Enhancement Patterns](#enhancement-patterns)
4. [When to Optimize](#when-to-optimize)
5. [Decision Framework](#decision-framework)
6. [Implementation Roadmap](#implementation-roadmap)
7. [Concerns & Edge Cases](#concerns--edge-cases)
8. [Testing Strategies](#testing-strategies)
9. [Practical Guidelines](#practical-guidelines)

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

## Concerns & Edge Cases

This section documents critical issues to consider when implementing entity-level processing and fine-grained change detection. **Read this before implementing Sprint 8.**

---

### 1. Cross-Entity Dependencies (CRITICAL)

**Problem:** Entity-level processing might miss cascading effects.

**Example scenario:**
```
Update: LeBron scores 50 points (affected_entities: [LeBron])

But this ALSO affects:
- Team total points (LAL team aggregate)
- Opponent defensive stats (opposing team)
- League leader boards (all players)
- Teammate usage rates (other LAL players)
- Game total score (game aggregate)
```

**The danger:** Processing only LeBron's record leaves derived/aggregate data inconsistent.

---

#### When Entity-Level is NOT Safe

**Some processors MUST process full scope, even for 1-entity changes:**

| Processor Type | Entity-Level Safe? | Reason | Expansion Required |
|----------------|-------------------|--------|-------------------|
| `PlayerGameSummaryProcessor` | ✅ YES | Each player independent | None |
| `PlayerStreaksProcessor` | ✅ YES | Streak is player-specific | None |
| `TeamAggregateProcessor` | ❌ NO | Sum of all players | All players on team |
| `TeamDefensiveRatingProcessor` | ❌ NO | Derived from opponent stats | Both teams in game |
| `LeagueRankingsProcessor` | ❌ NO | Relative to all players | All players in league |
| `GameTotalScoreProcessor` | ❌ NO | Sum of both teams | Both teams in game |
| `PlayerPercentileProcessor` | ❌ NO | Relative to all players | All players |

---

#### Processor Configuration Pattern

**Add metadata to each processor class:**

```python
class PlayerGameSummaryProcessor(AnalyticsProcessorBase):
    """Processes individual player game stats."""

    GRANULARITY_CONFIG = {
        'entity_level_safe': True,
        'entity_type': 'player',
        'requires_expansion': False,
        'dependencies': []
    }

class TeamAggregateProcessor(AnalyticsProcessorBase):
    """Computes team totals by summing player stats."""

    GRANULARITY_CONFIG = {
        'entity_level_safe': False,
        'entity_type': 'team',
        'requires_expansion': True,
        'expansion_strategy': 'all_players_on_team',
        'reason': 'Must recalculate sum of all players when any player changes',
        'dependencies': ['PlayerGameSummaryProcessor']
    }

class LeagueRankingsProcessor(AnalyticsProcessorBase):
    """Computes player rankings across entire league."""

    GRANULARITY_CONFIG = {
        'entity_level_safe': False,
        'entity_type': 'player',
        'requires_expansion': True,
        'expansion_strategy': 'all_players_in_league',
        'reason': 'Rankings are relative - one change affects all rankings',
        'dependencies': ['PlayerGameSummaryProcessor']
    }
```

---

#### Smart Expansion Logic

**Phase 3 service should expand affected entities when needed:**

```python
def expand_affected_entities(message, processor_class):
    """Expand affected entities based on processor requirements."""

    config = processor_class.GRANULARITY_CONFIG
    affected = message.get('affected_entities', {})

    if config['entity_level_safe']:
        # No expansion needed
        return affected

    expansion_strategy = config['expansion_strategy']

    if expansion_strategy == 'all_players_on_team':
        # Player changed → expand to all players on their team
        teams = get_teams_for_players(affected.get('players', []))
        return {
            'teams': teams,
            'players': get_all_players_on_teams(teams),
            'expansion_reason': 'team_aggregate_required'
        }

    elif expansion_strategy == 'all_players_in_league':
        # Any player changed → must process all players
        return {
            'players': 'ALL',
            'expansion_reason': 'league_wide_ranking'
        }

    elif expansion_strategy == 'both_teams_in_game':
        # One team changed → both teams need reprocessing
        games = affected.get('games', [])
        return {
            'games': games,
            'teams': get_both_teams_for_games(games),
            'expansion_reason': 'cross_team_dependency'
        }

    return affected
```

---

#### Testing for Dependency Issues

**Before deploying entity-level processing, test:**

```python
def test_entity_level_dependencies():
    """Ensure entity-level doesn't break aggregates."""

    # 1. Baseline: Process full date
    results_full = process_full_date('2025-11-15')

    # 2. Simulate incremental: Process just one entity
    results_incremental = process_entity_level('2025-11-15', player_ids=['1630567'])

    # 3. Compare aggregates (should be identical)
    for processor in [TeamAggregateProcessor, LeagueRankingsProcessor]:
        full_output = processor.get_output('2025-11-15')
        incremental_output = processor.get_output('2025-11-15')

        assert full_output == incremental_output, (
            f"{processor.__name__} produced different results! "
            f"Entity-level is not safe for this processor."
        )
```

**Red flag:** If aggregate results differ, entity-level is broken for that processor.

---

### 2. Data Completeness & Race Conditions

**Problem:** Incremental updates might process before all related data arrives.

**Example scenario:**
```
10:00:00 - Injury update arrives: LeBron ruled OUT
10:00:05 - Phase 2 loads injury data to BigQuery
10:00:10 - Phase 2 publishes: {affected_entities: {players: [LeBron]}}
10:00:15 - Phase 3 starts processing LeBron's analytics
          BUT: Boxscore data not loaded yet!
          Result: Analytics computed with incomplete data ❌

10:15:00 - Boxscore arrives: LeBron's stats loaded (DNP)
10:15:05 - Phase 2 publishes: {affected_entities: {players: [LeBron]}}
10:15:10 - Phase 3 processes again (now with complete data) ✅
```

**The danger:** First processing uses incomplete data, produces wrong results.

---

#### Solution 1: Data Readiness Checks (Recommended)

**Add validation to Phase 3 processors:**

```python
class PlayerGameSummaryProcessor(AnalyticsProcessorBase):

    REQUIRED_TABLES = [
        'nbac_gamebook_player_stats',  # Must have boxscore
        'nbac_injury_report',          # Must have injury status
        'nbac_player_tracking'         # Must have advanced stats
    ]

    def validate_data_completeness(self, game_date, player_ids):
        """Check if all required data is available."""

        for table in self.REQUIRED_TABLES:
            query = f"""
                SELECT COUNT(DISTINCT universal_player_id) as player_count
                FROM nba_raw.{table}
                WHERE game_date = '{game_date}'
                  AND universal_player_id IN UNNEST(@player_ids)
            """
            result = execute_query(query, params={'player_ids': player_ids})

            if result['player_count'] < len(player_ids):
                missing_count = len(player_ids) - result['player_count']
                logger.warning(
                    f"Data incomplete for {missing_count} players in {table}. "
                    f"Skipping processing until data arrives."
                )
                return False

        return True  # All data present

    def run(self, opts):
        game_date = opts['game_date']
        player_ids = opts.get('player_ids', self.get_all_players(game_date))

        # Check data completeness before processing
        if not self.validate_data_completeness(game_date, player_ids):
            logger.info("Deferring processing until all data arrives")
            raise DataNotReadyError(f"Missing required data for {game_date}")

        # All data present, safe to process
        self.process_players(player_ids, game_date)
```

**Retry behavior:**
- Pub/Sub retries failed message
- Next retry, data might be complete
- If data never arrives, eventually goes to DLQ

---

#### Solution 2: Data Completeness Metadata (Advanced)

**Publisher includes readiness info:**

```json
{
  "event_type": "raw_data_loaded",
  "source_table": "nbac_injury_report",
  "game_date": "2025-11-15",
  "affected_entities": {"players": ["1630567"]},

  "data_completeness": {
    "required_for_analytics": [
      "nbac_gamebook_player_stats",
      "nbac_injury_report",
      "nbac_player_tracking"
    ],
    "tables_ready": [
      "nbac_injury_report"
    ],
    "tables_pending": [
      "nbac_gamebook_player_stats",
      "nbac_player_tracking"
    ],
    "ready_to_process": false,
    "expected_ready_by": "2025-11-15T10:15:00Z"
  }
}
```

**Phase 3 behavior:**
```python
if not message['data_completeness']['ready_to_process']:
    logger.info("Data not ready, deferring processing")
    raise DataNotReadyError()  # Will retry later
```

**Trade-offs:**
- ✅ Explicit readiness signal
- ✅ Phase 3 doesn't need to know table dependencies
- ❌ Phase 2 must track cross-table dependencies
- ❌ More complex publishing logic

---

### 3. Message Ordering Guarantees

**Problem:** Updates might arrive out of order.

**Example scenario:**
```
11:00 AM - Stat correction: Rebounds 12 → 13 (sequence #1)
11:15 AM - Another correction: Rebounds 13 → 11 (sequence #2)

If messages arrive out of order:
  Phase 3 processes #2 first: rebounds = 11 ✅
  Phase 3 processes #1 second: rebounds = 13 ❌ (WRONG!)

Final result: 13 (should be 11)
```

---

#### Pub/Sub Ordering Guarantees

**Default Pub/Sub behavior:**
- ❌ NO ordering guarantee
- Messages can arrive in any order
- Multiple subscribers might process different messages simultaneously

**With ordering keys:**
- ✅ FIFO guarantee within same ordering key
- Messages with same key processed in order
- But: Reduces parallelism (can't process multiple messages with same key concurrently)

---

#### Solution 1: Ordering Keys + Sequence Numbers

**Publisher adds ordering metadata:**

```json
{
  "event_type": "raw_data_loaded",
  "source_table": "nbac_gamebook_player_stats",
  "game_date": "2025-11-15",
  "affected_entities": {"players": ["1630567"]},

  "ordering": {
    "key": "player:1630567:2025-11-15",
    "sequence_number": 1731772800123,
    "timestamp": "2025-11-15T11:15:00Z"
  }
}
```

**Pub/Sub configuration:**
```python
topic.publish(
    message_data,
    ordering_key="player:1630567:2025-11-15"  # Ensures FIFO
)
```

**Phase 3 validation:**
```python
def should_process_message(message, processor_state):
    """Check if we should process this message or skip as stale."""

    entity_key = message['ordering']['key']
    sequence = message['ordering']['sequence_number']

    # Get last processed sequence for this entity
    last_sequence = processor_state.get_last_sequence(entity_key)

    if last_sequence and sequence <= last_sequence:
        logger.warning(
            f"Skipping stale message (seq {sequence} <= last {last_sequence})"
        )
        return False

    return True
```

**Trade-offs:**
- ✅ Guarantees correct ordering
- ✅ Detects and skips out-of-order messages
- ❌ Reduces parallelism (can't process same entity concurrently)
- ❌ Requires state tracking per entity

---

#### Solution 2: Last-Writer-Wins (Simpler)

**Just use timestamps, accept eventual consistency:**

```python
UPDATE nba_analytics.player_game_summary
SET
    points = @points,
    rebounds = @rebounds,
    updated_at = @message_timestamp
WHERE
    universal_player_id = @player_id
    AND game_date = @game_date
    AND (updated_at IS NULL OR updated_at < @message_timestamp)  -- Only update if newer
```

**Trade-offs:**
- ✅ Simple (no ordering keys needed)
- ✅ Full parallelism
- ❌ Relies on clock accuracy
- ❌ Might briefly show stale data if out-of-order

**Recommendation:** Use Solution 2 for Sprints 1-8 (simpler), upgrade to Solution 1 only if metrics show ordering issues.

---

### 4. Partial Failure Recovery

**Problem:** What if entity-level processing succeeds for some entities but fails for others?

**Example scenario:**
```
affected_entities: [player1, player2, player3]

Processing:
  player1: ✅ Success
  player2: ❌ ERROR (missing data)
  player3: ✅ Success

Questions:
- Do we retry all 3?
- Just player2?
- How do we track partial success?
```

---

#### Strategy 1: All-or-Nothing (Recommended for Sprint 8)

**Fail entire batch if any entity fails:**

```python
def process_entities(entities):
    """Process all entities, rollback if any fail."""

    results = []

    try:
        for entity in entities:
            result = process_entity(entity)
            results.append(result)

        # All succeeded, commit batch
        commit_batch(results)
        return True

    except Exception as e:
        # Any failure → rollback entire batch
        logger.error(f"Batch failed on {entity}, rolling back all")
        rollback_batch(results)
        raise  # Let Pub/Sub retry entire message
```

**Trade-offs:**
- ✅ Simple (no partial state tracking)
- ✅ Guarantees consistency
- ✅ Easy retry logic (just reprocess all)
- ❌ Wastes reprocessing for succeeded entities

**When acceptable:**
- Batch size <100 entities
- Processing fast (<5s total)
- Failures rare (<1%)

---

#### Strategy 2: Per-Entity Retry (Advanced)

**Track success/failure per entity:**

```python
def process_entities_with_tracking(entities, message_id):
    """Process entities, track partial progress."""

    progress = load_progress(message_id) or {}

    for entity in entities:
        if progress.get(entity) == 'completed':
            logger.info(f"Skipping {entity} (already processed)")
            continue

        try:
            process_entity(entity)
            progress[entity] = 'completed'
            save_progress(message_id, progress)

        except Exception as e:
            progress[entity] = 'failed'
            logger.error(f"Failed processing {entity}: {e}")

    # Check if all completed
    if all(status == 'completed' for status in progress.values()):
        cleanup_progress(message_id)
        return True  # All done, ack message
    else:
        # Some failed, retry
        raise PartialFailureError(f"{len(failed)} entities failed")
```

**Trade-offs:**
- ✅ No wasted reprocessing
- ✅ Efficient for large batches
- ❌ Complex state management
- ❌ Need progress tracking storage

**When to use:**
- Batch size >100 entities
- Processing slow (>30s total)
- Failures common (>5%)

**Recommendation:** Start with Strategy 1, upgrade to Strategy 2 only if metrics show significant retry waste.

---

### 5. Idempotency Requirements

**Problem:** Is it safe to process the same entity multiple times?

**Critical requirement:** All Phase 3 processors MUST be idempotent.

---

#### What is Idempotency?

**Idempotent:** Running the same operation multiple times produces the same result.

**Example:**
```
First run:  process(player) → rebounds = 13
Second run: process(player) → rebounds = 13 (same ✅)

vs.

First run:  counter += 1 → counter = 1
Second run: counter += 1 → counter = 2 (different ❌)
```

---

#### Idempotent Patterns (SAFE)

```python
# ✅ SAFE: Overwrite with computed value
UPDATE player_game_summary
SET
    points = @points,
    rebounds = @rebounds,
    efficiency_rating = (@points + @rebounds + @assists) / @minutes
WHERE player_id = @player_id;

# ✅ SAFE: INSERT OR REPLACE
INSERT INTO player_game_summary (player_id, game_date, points)
VALUES (@player_id, @game_date, @points)
ON CONFLICT (player_id, game_date)
DO UPDATE SET points = EXCLUDED.points;

# ✅ SAFE: MAX/MIN values
UPDATE player_season_highs
SET max_points = GREATEST(max_points, @points)
WHERE player_id = @player_id;

# ✅ SAFE: Deterministic calculations
SELECT
    AVG(points) as avg_points,
    MAX(rebounds) as max_rebounds
FROM player_game_summary
WHERE player_id = @player_id;
```

---

#### Non-Idempotent Patterns (DANGEROUS)

```python
# ❌ DANGEROUS: Incrementing
UPDATE player_stats
SET games_played = games_played + 1
WHERE player_id = @player_id;
# Run twice → games_played = 2 (should be 1)

# ❌ DANGEROUS: Appending
UPDATE player_stats
SET recent_games = ARRAY_CONCAT(recent_games, [@game_id])
WHERE player_id = @player_id;
# Run twice → recent_games = [game1, game1] (should be [game1])

# ❌ DANGEROUS: Current timestamp
UPDATE player_stats
SET updated_at = CURRENT_TIMESTAMP()
WHERE player_id = @player_id;
# Run twice → different timestamps

# ❌ DANGEROUS: Random values
UPDATE player_stats
SET random_seed = RAND()
WHERE player_id = @player_id;
# Run twice → different values
```

---

#### How to Fix Non-Idempotent Code

**Pattern: Increment → Full Recalculation**

```python
# ❌ BEFORE (not idempotent)
def update_games_played(player_id):
    execute("""
        UPDATE player_stats
        SET games_played = games_played + 1
        WHERE player_id = ?
    """, [player_id])

# ✅ AFTER (idempotent)
def update_games_played(player_id, season):
    execute("""
        UPDATE player_stats
        SET games_played = (
            SELECT COUNT(DISTINCT game_id)
            FROM player_game_summary
            WHERE player_id = ? AND season = ?
        )
        WHERE player_id = ?
    """, [player_id, season, player_id])
```

**Pattern: Append → Replace Entire Array**

```python
# ❌ BEFORE (not idempotent)
def add_recent_game(player_id, game_id):
    execute("""
        UPDATE player_stats
        SET recent_games = ARRAY_CONCAT(recent_games, [?])
        WHERE player_id = ?
    """, [game_id, player_id])

# ✅ AFTER (idempotent)
def update_recent_games(player_id):
    execute("""
        UPDATE player_stats
        SET recent_games = (
            SELECT ARRAY_AGG(game_id ORDER BY game_date DESC LIMIT 10)
            FROM player_game_summary
            WHERE player_id = ?
        )
        WHERE player_id = ?
    """, [player_id, player_id])
```

---

#### Testing Idempotency

**Test every processor:**

```python
def test_processor_idempotency():
    """Ensure processors are idempotent."""

    # Setup test data
    setup_test_player_data('test_player', '2025-11-15')

    # Run processor first time
    processor.run({
        'game_date': '2025-11-15',
        'player_ids': ['test_player']
    })
    first_result = get_analytics_output('test_player', '2025-11-15')

    # Run processor second time (same data, no changes)
    processor.run({
        'game_date': '2025-11-15',
        'player_ids': ['test_player']
    })
    second_result = get_analytics_output('test_player', '2025-11-15')

    # Results should be IDENTICAL
    assert first_result == second_result, (
        f"Processor is not idempotent! "
        f"First: {first_result}, Second: {second_result}"
    )
```

**Run this test for every processor before deploying entity-level processing.**

---

### 6. Message Size Limits

**Problem:** What if `affected_entities` contains too many IDs?

**Pub/Sub limits:**
- Maximum message size: 10 MB
- Practical limit: Keep messages <1 MB for performance

**Example problem:**
```json
{
  "affected_entities": {
    "players": [
      "1630567", "1630568", "1630569", ... // 450 player IDs
    ]
  }
}
```

**450 player IDs × ~25 chars each = ~11 KB (still small)**

**But if adding more metadata:**
```json
{
  "affected_entities": {
    "players": [
      {
        "id": "1630567",
        "name": "LeBron James",
        "team": "LAL",
        "positions": ["SF", "PF"],
        "stats_changed": ["points", "rebounds", "assists"],
        ...
      },
      ... // 450 players with full metadata
    ]
  }
}
```

**450 players × 200 bytes each = 90 KB (getting large)**

---

#### Solution: Threshold-Based Expansion

**Strategy:**
- If few entities affected (< 100) → List them explicitly
- If many entities affected (≥ 100) → Use `process_all` flag

```json
// Small change (explicit entity list)
{
  "source_table": "nbac_injury_report",
  "game_date": "2025-11-15",
  "affected_entities": {
    "players": ["1630567"],
    "count": 1
  },
  "change_type": "incremental"
}

// Large change (fallback to full processing)
{
  "source_table": "nbac_gamebook_player_stats",
  "game_date": "2025-11-15",
  "affected_entities": {
    "count": 450,
    "type": "full_date"
  },
  "change_type": "full_load",
  "process_all": true
}
```

**Phase 3 behavior:**
```python
def get_entities_to_process(message, game_date):
    """Determine which entities to process."""

    affected = message.get('affected_entities', {})

    # Check if explicit entity list provided
    if 'players' in affected and isinstance(affected['players'], list):
        return affected['players']

    # Check if fallback to full processing
    if message.get('process_all') or affected.get('type') == 'full_date':
        return get_all_players_for_date(game_date)

    # Default: process all
    return get_all_players_for_date(game_date)
```

**Thresholds:**
```python
MAX_ENTITY_LIST_SIZE = 100  # Beyond this, use process_all
MAX_MESSAGE_SIZE_KB = 500   # Keep messages under 500 KB
```

---

### 7. Debugging & Traceability

**Problem:** With entity-level processing, debugging gets harder.

**Questions that become difficult:**
- Did we process player X for date Y?
- Why did we process only 5 players instead of all 450?
- Which message triggered this processing?
- Did entity-level expansion work correctly?

---

#### Enhanced Logging Requirements

**Every processor run should log:**

```python
def run(self, opts):
    """Process entities with comprehensive logging."""

    game_date = opts['game_date']
    player_ids = opts.get('player_ids')
    message_id = opts.get('message_id')

    # Log processing decision
    if player_ids:
        logger.info(
            f"Entity-level processing triggered",
            extra={
                'processor': self.__class__.__name__,
                'game_date': game_date,
                'entity_count': len(player_ids),
                'entity_ids': player_ids,
                'message_id': message_id,
                'processing_mode': 'incremental'
            }
        )
    else:
        logger.info(
            f"Full-date processing triggered",
            extra={
                'processor': self.__class__.__name__,
                'game_date': game_date,
                'message_id': message_id,
                'processing_mode': 'full'
            }
        )

    # Process and log results
    results = self.process_players(player_ids or self.get_all_players(game_date))

    logger.info(
        f"Processing complete",
        extra={
            'processor': self.__class__.__name__,
            'entities_requested': len(player_ids) if player_ids else 'all',
            'entities_processed': len(results),
            'entities_succeeded': sum(1 for r in results if r.success),
            'entities_failed': sum(1 for r in results if not r.success),
            'duration_seconds': results.duration,
            'message_id': message_id
        }
    )
```

---

#### Pipeline Execution Tracking

**Store in `nba_orchestration.pipeline_execution_log`:**

```sql
CREATE TABLE nba_orchestration.pipeline_execution_log (
    execution_id STRING,
    message_id STRING,
    processor_name STRING,
    game_date DATE,

    -- Processing mode
    processing_mode STRING,  -- 'full_date' or 'incremental'

    -- Entity tracking
    affected_entity_count INT64,
    affected_entity_ids ARRAY<STRING>,
    entities_processed INT64,
    entities_succeeded INT64,
    entities_failed INT64,
    failed_entity_ids ARRAY<STRING>,

    -- Expansion tracking
    expansion_occurred BOOL,
    expansion_reason STRING,
    original_entity_count INT64,
    expanded_entity_count INT64,

    -- Performance
    duration_seconds FLOAT64,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- Status
    status STRING,  -- 'completed', 'failed', 'partial'
    error_message STRING,

    -- Metadata
    source_table STRING,
    change_type STRING,
    trigger_reason STRING
);
```

---

#### Debugging Queries

```sql
-- 1. Find all processing for specific entity
SELECT
    processor_name,
    game_date,
    processing_mode,
    affected_entity_count,
    status,
    started_at
FROM nba_orchestration.pipeline_execution_log
WHERE
    '1630567' IN UNNEST(affected_entity_ids)
    OR processing_mode = 'full_date'
ORDER BY started_at DESC;

-- 2. Check if entity-level expansion is working
SELECT
    processor_name,
    COUNT(*) as total_runs,
    COUNTIF(expansion_occurred) as expanded_runs,
    ROUND(COUNTIF(expansion_occurred) / COUNT(*) * 100, 2) as expansion_pct,
    APPROX_QUANTILES(expanded_entity_count / original_entity_count, 100)[OFFSET(50)] as median_expansion_ratio
FROM nba_orchestration.pipeline_execution_log
WHERE processing_mode = 'incremental'
GROUP BY processor_name;

-- 3. Find partial failures
SELECT
    execution_id,
    processor_name,
    game_date,
    entities_processed,
    entities_failed,
    failed_entity_ids,
    error_message
FROM nba_orchestration.pipeline_execution_log
WHERE status = 'partial'
ORDER BY started_at DESC;
```

---

### 8. Rollback Strategy

**Problem:** What if entity-level processing causes issues in production?

**Safety valve:** Easy rollback to full-date processing.

---

#### Rollback Procedure

**Option 1: Configuration Flag (Immediate)**

```python
# In shared/config/processing_config.py
ENABLE_ENTITY_LEVEL_PROCESSING = True  # Set to False to disable

# In Phase 3 service
def get_entities_to_process(message, game_date):
    """Get entities to process, respecting feature flag."""

    if not config.ENABLE_ENTITY_LEVEL_PROCESSING:
        # Rollback: Always process full date
        logger.warning("Entity-level processing DISABLED, processing full date")
        return get_all_players_for_date(game_date)

    # Normal entity-level processing
    return message.get('affected_entities', {}).get('players') or get_all_players_for_date(game_date)
```

**Rollback:**
1. Set `ENABLE_ENTITY_LEVEL_PROCESSING = False`
2. Redeploy Phase 3 services
3. All processing reverts to full-date mode
4. No data loss, just slower processing

---

#### Option 2: Per-Processor Rollback

**More granular control:**

```python
PROCESSOR_ENTITY_LEVEL_ENABLED = {
    'PlayerGameSummaryProcessor': True,   # Entity-level working
    'TeamAggregateProcessor': False,      # Having issues, disabled
    'LeagueRankingsProcessor': True,
    ...
}

def should_use_entity_level(processor_class):
    """Check if entity-level enabled for this processor."""
    return PROCESSOR_ENTITY_LEVEL_ENABLED.get(
        processor_class.__name__,
        False  # Default: disabled (safe)
    )
```

---

#### Rollback Scenarios

**Scenario 1: Entity-level causing data inconsistencies**

```bash
# Immediate rollback
1. Set ENABLE_ENTITY_LEVEL_PROCESSING = False
2. Deploy Phase 3 services
3. Trigger full reprocessing for affected dates:
   python scripts/backfill_analytics.py --start-date 2025-11-10 --end-date 2025-11-15
4. Investigate root cause (likely cross-entity dependency missed)
```

**Scenario 2: Partial failures increasing**

```bash
# Rollback specific processor
1. Identify failing processor in logs
2. Set PROCESSOR_ENTITY_LEVEL_ENABLED[processor] = False
3. Redeploy
4. Other processors continue with entity-level
5. Debug failing processor offline
```

**Scenario 3: Performance degradation**

```bash
# Check if entity-level expansion causing issues
1. Query: SELECT expansion_reason, AVG(expanded_entity_count / original_entity_count)
2. If expansion ratio > 10 → entity-level isn't helping
3. Rollback or adjust expansion logic
```

---

### 9. Backfill Considerations

**Problem:** How does entity-level work with historical data backfills?

**Backfill scenarios:**
1. Full historical backfill (process 5 years of data)
2. Partial backfill (fix data for specific dates)
3. Single-entity correction (fix one player's data)

---

#### Backfill Strategies

**Strategy 1: Always Full-Date for Backfills**

```python
def run_backfill(start_date, end_date, player_ids=None):
    """Backfill analytics, always use full-date processing."""

    for date in date_range(start_date, end_date):
        # Backfills always process full date
        # Reason: Need complete data for historical accuracy
        processor.run({
            'game_date': date,
            'player_ids': None,  # Force full processing
            'source': 'backfill'
        })
```

**Rationale:**
- Historical data is static (no incremental updates)
- Want complete, consistent historical analytics
- Performance less critical (run overnight)

---

**Strategy 2: Entity-Level for Targeted Corrections**

```python
def run_correction(date, player_ids):
    """Fix analytics for specific entities."""

    processor.run({
        'game_date': date,
        'player_ids': player_ids,
        'source': 'correction',
        'force_entity_level': True
    })
```

**Use when:**
- Single data correction (one player's stats wrong)
- Want fast turnaround
- Know exactly what needs fixing

---

### 10. Schema Evolution

**Problem:** What happens when message format changes?

**Scenarios:**
1. Add new field to message (backward compatible)
2. Rename field (breaking change)
3. Change field type (breaking change)

---

#### Versioning Strategy

```json
{
  "schema_version": "2.0",
  "event_type": "raw_data_loaded",
  "source_table": "nbac_gamebook_player_stats",
  "game_date": "2025-11-15",

  "affected_entities": {
    "players": ["1630567"]
  }
}
```

**Phase 3 handling:**

```python
def parse_message(message):
    """Parse message, supporting multiple schema versions."""

    version = message.get('schema_version', '1.0')

    if version == '1.0':
        # Old format: no affected_entities
        return {
            'game_date': message['game_date'],
            'player_ids': None  # Process all
        }

    elif version == '2.0':
        # New format: with affected_entities
        return {
            'game_date': message['game_date'],
            'player_ids': message.get('affected_entities', {}).get('players')
        }

    else:
        raise ValueError(f"Unsupported schema version: {version}")
```

**Migration plan:**
1. Deploy Phase 3 with multi-version support
2. Deploy Phase 2 with new schema version
3. After 7 days, remove old version support from Phase 3

---

## Testing Strategies

### Unit Testing

**Test 1: Idempotency**

```python
def test_processor_idempotency(processor_class):
    """Verify processor is idempotent."""

    # Setup
    setup_test_data('2025-11-15', player_ids=['test_player'])

    # First run
    result1 = processor_class().run({
        'game_date': '2025-11-15',
        'player_ids': ['test_player']
    })

    # Second run (identical input)
    result2 = processor_class().run({
        'game_date': '2025-11-15',
        'player_ids': ['test_player']
    })

    # Should produce identical results
    assert result1 == result2
```

---

**Test 2: Entity-Level vs Full-Date Equivalence**

```python
def test_entity_level_equivalence(processor_class):
    """Verify entity-level produces same results as full-date."""

    # Setup
    game_date = '2025-11-15'
    all_players = setup_test_data(game_date)

    # Full-date processing
    processor_class().run({
        'game_date': game_date,
        'player_ids': None
    })
    full_results = get_analytics_output(game_date)

    # Clear results
    clear_analytics_output(game_date)

    # Entity-level processing (all entities)
    processor_class().run({
        'game_date': game_date,
        'player_ids': all_players
    })
    entity_results = get_analytics_output(game_date)

    # Should be identical
    assert full_results == entity_results
```

---

**Test 3: Cross-Entity Dependencies**

```python
def test_aggregate_consistency(processor_class):
    """Verify aggregates remain consistent with entity-level."""

    game_date = '2025-11-15'
    team_players = ['player1', 'player2', 'player3']

    # Process all players
    processor_class().run({
        'game_date': game_date,
        'player_ids': team_players
    })
    team_total_1 = get_team_aggregate(game_date, 'LAL')

    # Process just one player again
    processor_class().run({
        'game_date': game_date,
        'player_ids': ['player1']
    })
    team_total_2 = get_team_aggregate(game_date, 'LAL')

    # Team total should be unchanged
    assert team_total_1 == team_total_2
```

---

### Integration Testing

**Test 4: End-to-End Message Flow**

```python
def test_e2e_entity_level_flow():
    """Test full pipeline with entity-level messages."""

    # 1. Phase 2 publishes entity-level message
    message = {
        'event_type': 'raw_data_loaded',
        'source_table': 'nbac_injury_report',
        'game_date': '2025-11-15',
        'affected_entities': {'players': ['1630567']}
    }

    publish_to_topic('nba-phase2-raw-complete', message)

    # 2. Wait for processing
    time.sleep(5)

    # 3. Check execution log
    log = query_execution_log(message_id=message['message_id'])
    assert log['processing_mode'] == 'incremental'
    assert log['entities_processed'] == 1
    assert log['status'] == 'completed'

    # 4. Verify analytics output
    output = get_player_analytics('1630567', '2025-11-15')
    assert output is not None
```

---

**Test 5: Partial Failure Recovery**

```python
def test_partial_failure_retry():
    """Test retry behavior on partial failures."""

    # Setup: Make one player fail
    setup_test_data('2025-11-15', ['player1', 'player2', 'player3'])
    inject_failure_for_player('player2')

    # Publish message
    message = {
        'game_date': '2025-11-15',
        'affected_entities': {'players': ['player1', 'player2', 'player3']}
    }

    # First attempt: Should fail on player2
    with pytest.raises(ProcessingError):
        processor.run(message)

    # Check partial progress
    assert get_player_analytics('player1', '2025-11-15') is None  # All-or-nothing rollback

    # Fix the issue
    remove_failure_injection('player2')

    # Retry: Should succeed
    processor.run(message)
    assert get_player_analytics('player1', '2025-11-15') is not None
    assert get_player_analytics('player2', '2025-11-15') is not None
    assert get_player_analytics('player3', '2025-11-15') is not None
```

---

### Load Testing

**Test 6: Performance Comparison**

```python
def test_entity_level_performance():
    """Measure performance improvement of entity-level."""

    game_date = '2025-11-15'
    setup_test_data(game_date, player_count=450)

    # Benchmark: Full-date processing
    start = time.time()
    processor.run({'game_date': game_date})
    full_duration = time.time() - start

    # Benchmark: Entity-level (1 player)
    start = time.time()
    processor.run({
        'game_date': game_date,
        'player_ids': ['1630567']
    })
    entity_duration = time.time() - start

    # Entity-level should be much faster
    speedup = full_duration / entity_duration
    assert speedup > 10, f"Expected >10x speedup, got {speedup}x"
```

---

### Monitoring Tests

**Test 7: Metrics Validation**

```python
def test_metrics_logged():
    """Verify all required metrics are logged."""

    processor.run({
        'game_date': '2025-11-15',
        'player_ids': ['1630567']
    })

    log = get_latest_execution_log()

    # Check required fields
    assert log['processing_mode'] in ['full_date', 'incremental']
    assert log['affected_entity_count'] is not None
    assert log['entities_processed'] is not None
    assert log['duration_seconds'] is not None
    assert log['status'] in ['completed', 'failed', 'partial']
```

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

**Last Updated:** 2025-11-16
**Status:** Future Enhancement - Reference when metrics indicate optimization needed
**Next Review:** After Sprint 8 completion, check metrics against Decision Framework

---

## Document Organization Notes

**Why this is one document:**
- Complete story arc: Problem → Simple → Optimized → Edge cases
- Cross-references would be annoying if split
- It's a reference doc (people will search/jump around anyway)
- TOC provides good navigation

**If splitting in future, could organize as:**
1. Design patterns (HOW) - Patterns 1-3
2. Decision framework (WHEN) - Metrics & ROI
3. Implementation guide (WHAT) - Roadmap
4. Edge cases & concerns (GOTCHAS) - This new section

**Current recommendation:** Keep as one comprehensive reference document
