# Change Detection - Current State Investigation

**File:** `docs/01-architecture/change-detection/change-detection-investigation.md`
**Created:** 2025-11-18
**Last Updated:** 2025-11-18
**Purpose:** Investigate current implementation of change detection and entity-level processing
**Status:** Investigation in progress
**Related:** [06-change-detection-and-event-granularity.md](./06-change-detection-and-event-granularity.md) (design patterns)

---

## 🎯 Questions to Answer

This document investigates the **actual current implementation** to answer:

### Player-Level Changes
1. **Does Phase 2 send one message per date or one per player?**
2. **Does Phase 3 process all players or only changed players?**
3. **Does Phase 2 update `processed_at` only for changed records?**
4. **Can we detect single-player changes without entity-level messages?**
5. **What happens when one player's injury status changes mid-day?**

### Team-Level Changes
6. **Does Phase 2 send one message per date or one per team?**
7. **Does Phase 3 process all teams or only changed teams?**
8. **What happens when one team's pointspread changes mid-day?**
9. **Does team data change trigger reprocessing of all teams downstream?**

### General Entity-Level Concerns
10. **Does the same cascading issue affect teams, players, and games?**
11. **Can we handle entity-level changes for ANY entity type, not just players?**

---

## 📋 Investigation Checklist

### Phase 1: Code Inspection

- [ ] **Check Phase 2 Pub/Sub Publishing**
  - File: `data_processors/raw/processor_base.py`
  - Question: Does it publish one message per execution or per entity?

- [ ] **Check Phase 2 MERGE Logic**
  - Files: `data_processors/raw/*_processor.py`
  - Question: Does MERGE detect changes before updating `processed_at`?

- [ ] **Check Phase 3 Processing Logic**
  - Files: `data_processors/analytics/*_processor.py`
  - Question: Does it process entire date or use incremental WHERE clause?

- [ ] **Check Output Table Schemas**
  - Location: BigQuery `nba_raw.*` and `nba_analytics.*`
  - Question: Do tables have `processed_at` and `data_hash` fields?

### Phase 2: Query Investigation

- [ ] **Run queries to check `processed_at` behavior**
- [ ] **Check Pub/Sub message history**
- [ ] **Measure batch size vs change frequency**
- [ ] **Analyze cost impact of batch processing**

### Phase 3: Documentation

- [ ] **Document current behavior**
- [ ] **Document gaps and workarounds**
- [ ] **Create improvement recommendations**
- [ ] **Estimate effort for changes**

---

## 🔍 Investigation Queries

### Query 1: Check Phase 2 `processed_at` Behavior

**Purpose:** Determine if `processed_at` updates only for changed records

```sql
-- Check if processed_at differs across records for same scraper run
WITH last_scraper_run AS (
  SELECT MAX(triggered_at) as last_run
  FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
  WHERE scraper_name = 'nbac_injury_report'
    AND status IN ('success', 'no_data')
    AND DATE(triggered_at) = CURRENT_DATE()
),
raw_data AS (
  SELECT
    player_id,
    game_date,
    injury_status,
    processed_at,
    TIMESTAMP_DIFF(processed_at, (SELECT last_run FROM last_scraper_run), SECOND) as seconds_after_scraper
  FROM `nba-props-platform.nba_raw.nbac_injury_report`
  WHERE game_date = CURRENT_DATE()
)
SELECT
  COUNT(DISTINCT processed_at) as distinct_processed_timestamps,
  MIN(seconds_after_scraper) as min_delay_seconds,
  MAX(seconds_after_scraper) as max_delay_seconds,
  COUNT(*) as total_records
FROM raw_data;

-- Interpretation:
-- If distinct_processed_timestamps = 1: All records updated at same time (batch update)
-- If distinct_processed_timestamps > 1: Selective updates (good for change detection)
```

### Query 2: Check for Data Hash or Checksum

**Purpose:** See if Phase 2 tracks record changes via hash

```sql
-- Check if tables have change tracking fields
SELECT
  table_name,
  column_name,
  data_type
FROM `nba-props-platform.nba_raw.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name IN ('nbac_injury_report', 'nbac_gamebook_player_stats', 'odds_api_player_points_props')
  AND column_name IN ('data_hash', 'checksum', 'record_hash', 'change_hash', 'processed_at', 'updated_at')
ORDER BY table_name, column_name;
```

### Query 3: Measure Change Frequency (Players & Teams)

**Purpose:** How often do single-entity changes happen vs full batch updates?

```sql
-- Count unique processed_at timestamps per scraper run
WITH scraper_runs AS (
  SELECT
    DATE(triggered_at) as run_date,
    scraper_name,
    triggered_at,
    JSON_VALUE(data_summary, '$.record_count') as records_scraped,
    -- Categorize by entity type
    CASE
      WHEN scraper_name LIKE '%player%' OR scraper_name LIKE '%injury%' OR scraper_name LIKE '%props%' THEN 'player'
      WHEN scraper_name LIKE '%team%' OR scraper_name LIKE '%spread%' OR scraper_name LIKE '%totals%' THEN 'team'
      WHEN scraper_name LIKE '%game%' OR scraper_name LIKE '%schedule%' THEN 'game'
      ELSE 'other'
    END as entity_type
  FROM `nba-props-platform.nba_orchestration.scraper_execution_log`
  WHERE scraper_name IN (
    -- Player-level scrapers
    'nbac_injury_report', 'odds_api_player_points_props',
    -- Team-level scrapers
    'nbac_team_boxscore', 'odds_api_team_totals', 'odds_api_spreads'
  )
    AND status IN ('success', 'no_data')
    AND DATE(triggered_at) >= CURRENT_DATE() - 7
)
SELECT
  entity_type,
  scraper_name,
  run_date,
  COUNT(*) as runs_that_day,
  AVG(CAST(records_scraped AS INT64)) as avg_records_per_run,
  MIN(CAST(records_scraped AS INT64)) as min_records,
  MAX(CAST(records_scraped AS INT64)) as max_records
FROM scraper_runs
GROUP BY entity_type, scraper_name, run_date
ORDER BY entity_type, scraper_name, run_date DESC;

-- Interpretation:
-- If min_records << max_records: Some runs are small updates (candidates for optimization)
-- If min_records ≈ max_records: Most runs are full batches
-- Compare player vs team update patterns
```

### Query 4: Check Phase 3 Table Update Patterns

**Purpose:** See if Phase 3 does batch DELETE+INSERT or incremental MERGE

```sql
-- Look at Phase 3 output table update patterns
-- Check if all records for a date have same processed_at (batch) or different (incremental)
SELECT
  game_date,
  COUNT(DISTINCT processed_at) as distinct_update_times,
  MIN(processed_at) as first_update,
  MAX(processed_at) as last_update,
  TIMESTAMP_DIFF(MAX(processed_at), MIN(processed_at), SECOND) as update_window_seconds,
  COUNT(*) as total_records
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY game_date DESC;

-- Interpretation:
-- If distinct_update_times = 1: Batch DELETE+INSERT (all at once)
-- If distinct_update_times > 1: Incremental updates (some records updated separately)
-- If update_window_seconds < 5: Probably batch
-- If update_window_seconds > 60: Definitely incremental
```

### Query 5: Check Pub/Sub Message Granularity

**Purpose:** See how many messages Phase 2 publishes per scraper run

```bash
# Check Cloud Logging for Phase 2 Pub/Sub publishing
gcloud logging read \
  "resource.labels.service_name=nba-processors
   AND textPayload:\"Published to phase3\"
   AND timestamp>=\"$(date -u -d '1 day ago' --iso-8601=seconds)\"" \
  --limit=100 \
  --format=json \
  | jq -r '.[] | .timestamp + " " + .textPayload' \
  | sort

# Count messages per processor execution
# If you see 1 message per execution: Date-level messages
# If you see N messages per execution: Entity-level messages (where N = number of changed entities)
```

---

## 📊 Findings (To Be Filled In)

### Finding 1: Phase 2 Message Granularity

**Status:** 🔴 Not Yet Investigated

**What to check:**
- [ ] Review `data_processors/raw/processor_base.py` publish method
- [ ] Check logs from last Phase 2 execution
- [ ] Count messages published vs records processed

**Expected findings:**
- Option A: One message per processor execution (date-level)
- Option B: One message per changed entity (entity-level)

**Actual findings:**
```
[To be filled in after code inspection]
```

---

### Finding 2: Phase 2 `processed_at` Update Strategy

**Status:** 🔴 Not Yet Investigated

**What to check:**
- [ ] Run Query 1 above
- [ ] Check MERGE statement in processor code
- [ ] Look for change detection logic

**Expected findings:**
- Option A: All records get `processed_at` updated (batch)
- Option B: Only changed records get `processed_at` updated (selective)

**Actual findings:**
```
[To be filled in after running Query 1]

Example output:
distinct_processed_timestamps: 1
total_records: 450
→ Interpretation: Batch update, all records updated at once
```

---

### Finding 3: Phase 3 Processing Strategy

**Status:** 🔴 Not Yet Investigated

**What to check:**
- [ ] Review Phase 3 processor SQL logic
- [ ] Run Query 4 to check output patterns
- [ ] Look for WHERE clauses with timestamp filters

**Expected findings:**
- Option A: DELETE entire date + INSERT all (batch)
- Option B: MERGE with WHERE processed_at > last_run (incremental)

**Actual findings:**
```
[To be filled in after code inspection]
```

---

### Finding 4: Change Detection Capability

**Status:** 🔴 Not Yet Investigated

**What to check:**
- [ ] Run Query 2 to check for hash fields
- [ ] Check for `data_hash`, `checksum`, or similar fields
- [ ] Review schemas for change tracking metadata

**Expected findings:**
- Option A: No hash fields, no change detection
- Option B: Hash fields exist, can detect changes

**Actual findings:**
```
[To be filled in after running Query 2]
```

---

### Finding 5: Cost Impact Analysis

**Status:** 🔴 Not Yet Investigated

**What to measure:**
- [ ] Run Query 3 to measure change frequency
- [ ] Calculate: % of runs that are small updates vs full batches
- [ ] Estimate: Wasted computation when reprocessing unchanged entities

**Metrics to collect:**
```
Average scraper run sizes:
- Full batch: 450 players
- Small update: ??? players
- Frequency of small updates: ???% of runs

Estimated waste:
- If 30% of runs are 1-player updates
- And we reprocess all 450 players each time
- Waste = 449 players × 30% of runs = ???% total waste
```

---

## 🚨 Key Scenarios to Test

### Scenario 1A: Single Player Injury Update (Mid-Day)

**Setup:**
```
9:00 AM  - Initial injury report scraper runs, 45 players injured
         - Phase 2: Processes 45 players → nba_raw.nbac_injury_report
         - Phase 3: Processes all 450 active players (injury status is one field)

3:00 PM  - Player X's status changes from Questionable → Out
         - Injury report scraper runs again
         - Finds: 1 changed player, 44 unchanged players
```

**Questions:**
1. Does Phase 2 update only Player X's record?
2. Does Phase 2 publish one message or 45 messages?
3. Does Phase 3 reprocess all 450 players or just Player X?
4. Does Phase 4 recompute features for all 450 or just Player X?
5. Does Phase 5 re-run predictions for all 450 or just Player X?

**Current behavior (hypothesis based on doc 06):**
```
Phase 2: Updates Player X only ✅ (MERGE should handle this)
Phase 2: Publishes 1 message for date=2025-11-18 ⚠️ (date-level)
Phase 3: Reprocesses ALL 450 players ❌ (date-level processing)
Phase 4: Reprocesses ALL 450 players ❌ (cascading date-level)
Phase 5: Re-runs predictions for ALL 450 ❌ (cascading date-level)
```

**Test procedure:**
1. Manually trigger injury report scraper at 9 AM
2. Check `nba_raw.nbac_injury_report` row count
3. Manually update one player's status directly in BigQuery
4. Trigger scraper again at 3 PM
5. Monitor Pub/Sub messages published
6. Check which Phase 3 records got updated (processed_at timestamps)

---

### Scenario 1B: Single Team Pointspread Change (Mid-Day)

**Setup:**
```
9:00 AM  - Initial spreads scraper runs, 14 games = 28 teams
         - Lakers -6.5 vs Warriors
         - Phase 2: Processes 28 team spreads → nba_raw.odds_api_spreads
         - Phase 3: Processes team_offense_game_summary, team_defense_game_summary

3:00 PM  - Lakers spread moves from -6.5 to -7.5 (sharp money)
         - Spreads scraper runs again
         - Finds: 1 changed team spread, 27 unchanged
```

**Questions:**
1. Does Phase 2 update only Lakers' spread record?
2. Does Phase 2 publish one message or 28 messages?
3. Does Phase 3 reprocess all 28 teams or just Lakers?
4. Does Phase 4 recompute team_defense_zone_analysis for all 28 or just Lakers?
5. Does Phase 5 re-run predictions for all games or just Lakers game?

**Current behavior (hypothesis based on doc 06):**
```
Phase 2: Updates Lakers spread only ✅ (MERGE should handle this)
Phase 2: Publishes 1 message for date=2025-11-18 ⚠️ (date-level)
Phase 3: Reprocesses ALL 28 teams ❌ (date-level processing)
Phase 4: Reprocesses ALL 28 teams ❌ (cascading date-level)
Phase 5: Re-runs predictions for ALL games ❌ (cascading date-level)
```

**Efficient behavior (desired):**
```
Phase 2: Updates Lakers spread only ✅
Phase 2: Publishes: {"entity_type": "team", "team_id": "lakers", "game_date": "2025-11-18"} ✅
Phase 3: Processes ONLY Lakers-related team records ✅
Phase 4: Recomputes ONLY Lakers team_defense_zone_analysis ✅
Phase 5: Re-runs predictions ONLY for Lakers vs Warriors game ✅
```

**Test procedure:**
1. Manually trigger spreads scraper at 9 AM
2. Check `nba_raw.odds_api_spreads` row count
3. Manually update Lakers spread in BigQuery
4. Trigger scraper again at 3 PM
5. Monitor Pub/Sub messages published
6. Check which Phase 3 team records got updated (processed_at timestamps)
7. Check if all teams or just Lakers got reprocessed

**Cost Impact:**
- Wasted computation: 27 teams × (Phase 3 + Phase 4 + Phase 5) = ~27x waste
- If this happens 10x per day, that's 270 unnecessary team processings/day

---

### Scenario 2: Props Line Movement (Player)

**Setup:**
```
10:00 AM - Initial props scraper, Player Y line = 25.5 points
11:00 AM - Line moves to 26.5 points (sharp action)
         - Only Player Y changed, 449 players unchanged
```

**Questions:**
1. Does Phase 2 detect the line moved and update only Player Y?
2. Does downstream processing update only Player Y?

**Efficient behavior (desired):**
```
Phase 2: UPDATE only Player Y ✅
Phase 2: Publish message: {"entity_type": "player", "player_id": "player_y", "game_date": "2025-11-18"}
Phase 3: Update only Player Y's upcoming_player_game_context
Phase 4: Recompute only Player Y's composite factors
Phase 5: Re-run prediction ONLY for Player Y ✅
```

**Current behavior (likely):**
```
Phase 2: UPDATE only Player Y ✅
Phase 2: Publish message: {"game_date": "2025-11-18"} ⚠️
Phase 3: Reprocess ALL 450 players ❌
Phase 4: Recompute ALL 450 players ❌
Phase 5: Re-run predictions for ALL 450 ❌
```

---

---

### Scenario 3: Cross-Entity Impact (Team Change Affects Players)

**Setup:**
```
2:00 PM  - Team injury report updates: Lakers list 2 starters as OUT
         - This affects team_defense_game_summary (Lakers defense weaker)
         - This affects upcoming_player_game_context for Warriors players (easier matchup)
         - This affects predictions for ALL Warriors players in that game
```

**Questions:**
1. Does team-level change trigger player-level reprocessing?
2. How do we know which players are affected by team change?
3. Do we reprocess all players or just Warriors players in that game?

**Dependency chain:**
```
Team Change (Lakers defense)
  → Affects: team_defense_game_summary (Lakers)
  → Affects: upcoming_team_game_context (Lakers vs Warriors)
  → Affects: upcoming_player_game_context (Warriors players only - easier matchup)
  → Affects: player_composite_factors (Warriors players only)
  → Affects: predictions (Warriors players only)
```

**Current behavior (likely):**
```
Phase 2: Updates team injury data ✅
Phase 2: Publishes: {"game_date": "2025-11-18"} ⚠️
Phase 3: Reprocesses ALL teams ❌
Phase 3: Reprocesses ALL players ❌ (even though only Warriors affected)
Phase 4: Reprocesses ALL players ❌
Phase 5: Re-runs predictions for ALL players ❌
```

**Efficient behavior (desired):**
```
Phase 2: Updates team injury data ✅
Phase 2: Publishes: {"entity_type": "team", "team_id": "lakers", "field": "defense_rating"} ✅
Phase 3: Identifies affected game: Lakers vs Warriors ✅
Phase 3: Reprocesses ONLY Lakers team defense + Warriors opponent context ✅
Phase 4: Reprocesses ONLY Warriors players (easier matchup) ✅
Phase 5: Re-runs predictions ONLY for Warriors players ✅
```

**This scenario shows:**
- Entity-level changes can cascade across entity types (team → player)
- Need dependency mapping to know which entities are affected
- Most complex scenario for change detection

---

## 💡 Recommendations (Based on Findings)

### If Current State = Date-Level Processing (Hypothesis)

**Short-term (2-4 hours):**
1. ✅ Add `records_changed` count to Pub/Sub messages
2. ✅ Add `entity_type` field to messages (player, team, game)
3. ✅ Add `incremental_update` boolean flag to messages
4. ✅ Log entity IDs that changed (for debugging)

**Medium-term (6-8 hours):**
1. ✅ Use `processed_at` filtering in Phase 3
   - WHERE processed_at > last_checkpoint
   - Only process records newer than last run
2. ✅ Implement MERGE instead of DELETE+INSERT
3. ✅ Add monitoring for wasted processing

**Long-term (15-20 hours):**
1. ✅ Entity-level Pub/Sub messages (for all entity types)
2. ✅ Per-entity change propagation (player, team, game)
3. ✅ Cross-entity dependency mapping (team changes → affected players)
4. ✅ Batching for efficiency (5-min window)
5. ✅ Hash-based change detection

### If Current State = Entity-Level Processing (Optimistic)

**No changes needed!** Document and celebrate. 🎉

Just add observability:
1. ✅ Log entity-level processing metrics
2. ✅ Monitor entity processing counts
3. ✅ Alert on unexpected batch sizes

---

## 📝 Investigation Plan

### Week 1: Code Inspection (2-3 hours)

**Tasks:**
- [ ] Read Phase 2 processor code (player processors)
- [ ] Read Phase 2 processor code (team processors)
- [ ] Read Phase 3 processor code (player analytics)
- [ ] Read Phase 3 processor code (team analytics)
- [ ] Document MERGE logic for both entity types
- [ ] Document Pub/Sub publishing logic
- [ ] Check for entity-type awareness in messages
- [ ] Fill in "Findings" sections above

**Deliverable:** Updated this document with findings

---

### Week 1: Query Analysis (1-2 hours)

**Tasks:**
- [ ] Run all investigation queries
- [ ] Collect metrics on change frequency
- [ ] Measure batch sizes
- [ ] Document current behavior patterns

**Deliverable:** Completed "Findings" section with data

---

### Week 2: Test Scenarios (3-4 hours)

**Tasks:**
- [ ] Set up test environment
- [ ] Execute Scenario 1A (single player injury update)
- [ ] Execute Scenario 1B (single team spread change)
- [ ] Execute Scenario 2 (props line movement)
- [ ] Execute Scenario 3 (team change affecting players)
- [ ] Measure actual behavior for each scenario
- [ ] Document discrepancies from expected
- [ ] Compare player vs team processing patterns

**Deliverable:** Test results and behavior confirmation for all entity types

---

### Week 2: Recommendations (1-2 hours)

**Tasks:**
- [ ] Analyze findings
- [ ] Calculate cost impact
- [ ] Prioritize improvements
- [ ] Create implementation plan
- [ ] Update architecture/06 doc with findings

**Deliverable:** Action plan with effort estimates

---

## 🔗 Related Documentation

**Design Patterns:**
- `06-change-detection-and-event-granularity.md` - Future enhancement patterns
- `02-phase1-to-phase5-granular-updates.md` - Entity-level granularity design

**Current Implementation:**
- `docs/infrastructure/02-pubsub-schema-management.md` - Message schemas
- `docs/processors/02-phase3-operations-guide.md` - Phase 3 processing logic
- `docs/processors/05-phase4-operations-guide.md` - Phase 4 processing logic

**Code Locations:**
- `data_processors/raw/processor_base.py` - Phase 2 base class
- `shared/utils/pubsub_publishers.py` - Pub/Sub publishing utilities
- `data_processors/analytics/*` - Phase 3 processors

---

## 📊 Decision Matrix

Based on investigation findings, use this to decide next steps:

| Finding | Action | Priority | Effort |
|---------|--------|----------|--------|
| **Messages = Date-level** AND **Processing = Batch** (both entities) | Implement incremental processing | High | 8-10 hrs |
| **Messages = Date-level** AND **Processing = Incremental** | Add entity type + list to messages | Medium | 4-6 hrs |
| **Messages = Entity-level** AND **Processing = Batch** | Update Phase 3+ to use entity filtering | High | 10 hrs |
| **Messages = Entity-level** AND **Processing = Incremental** | Just add monitoring | Low | 2 hrs |
| **No change detection** (players or teams) | Add hash-based change tracking | Medium | 8 hrs |
| **Change detection exists** | Leverage for optimization | Low | 2 hrs |
| **Waste >30%** (players) | Prioritize entity-level events | High | 15 hrs |
| **Waste >30%** (teams) | Add to entity-level implementation | High | +5 hrs |
| **Cross-entity dependencies exist** (team → player) | Design dependency mapping | High | 12 hrs |
| **Waste <10%** (both) | Ship as-is, monitor | Low | 0 hrs |

---

## 🎯 Success Criteria

Investigation is complete when we can answer:

### Player-Level Questions
- ✅ Exactly how Phase 2 publishes player messages (date vs entity)
- ✅ Exactly how Phase 3 processes player updates (batch vs incremental)
- ✅ Whether `processed_at` tracks player changes or just execution time
- ✅ Cost impact of player batch processing (% waste, $ amount)

### Team-Level Questions
- ✅ Exactly how Phase 2 publishes team messages (date vs entity)
- ✅ Exactly how Phase 3 processes team updates (batch vs incremental)
- ✅ Whether `processed_at` tracks team changes or just execution time
- ✅ Cost impact of team batch processing (% waste, $ amount)

### Cross-Entity Questions
- ✅ Do team changes trigger player reprocessing?
- ✅ Are there dependency mappings between entity types?
- ✅ Can we isolate affected entities across types?

### Decision
- ✅ Whether optimization is needed based on metrics (by entity type)

---

**Next Steps:** Run investigation queries and fill in findings sections

**Owner:** Engineering team
**Timeline:** Week 1-2 investigation, Week 2-3 implementation (if needed)
**Status:** 🔴 Investigation not yet started

---

## 📋 Investigation Log

### 2025-11-18: Document Created
- Created investigation framework
- Defined queries and test scenarios
- Established decision criteria

### [Future entries as investigation progresses]
