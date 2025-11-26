# Phase 2 Processor Smart Idempotency Strategy

**Purpose:** Define hash field strategies for each Phase 2 raw processor to prevent unnecessary downstream cascade processing.

**Created:** 2025-11-21 08:15 AM PST
**Last Updated:** 2025-11-21 09:30 AM PST
**Pattern:** #14 - Smart Idempotency
**Status:** 📝 Planning Phase

---

## Problem Statement

Phase 2 raw processors currently update `processed_at` on every run, even when data hasn't meaningfully changed. This causes:

- **Unnecessary Phase 3 reprocessing** (5 analytics processors × 450 players)
- **Unnecessary Phase 4 reprocessing** (5 precompute processors × 450 players)
- **Unnecessary Phase 5 predictions** (1 worker × 450 players × 5 systems)

**Example Cascade:**
```
Injury report scraped 4x/day (no status changes)
→ Phase 2 writes 4x, updates processed_at 4x
→ Phase 3 sees "fresh" data, processes 450 players 4x
→ Phase 4 sees "fresh" data, processes 450 players 4x
→ Phase 5 generates predictions 4x
= 3,600 wasted operations (75% could be avoided)
```

---

## Solution: Selective Field Hashing

Add `data_hash` column to Phase 2 tables and compute hash of **only the fields downstream processors care about**.

### Key Principles

1. **Fail Open** - If hash check fails, process anyway (safety first)
2. **Selective Fields** - Only hash fields that trigger downstream logic changes
3. **Exclude Metadata** - Don't hash: `processed_at`, `scraped_at`, `source_url`, etc.
4. **Exclude Noise** - Don't hash fields that change frequently but don't affect predictions (e.g., odds movements)

---

## Phase 2 Processor Inventory

**Total:** 22 processors across 5 data sources

### By Data Source

| Source | Processors | Priority |
|--------|-----------|----------|
| **nbacom** | 10 | 🔴 High (official source) |
| **balldontlie** | 4 | 🟡 Medium |
| **espn** | 3 | 🟡 Medium |
| **oddsapi** | 2 | 🔴 High (frequent updates) |
| **bettingpros** | 1 | 🔴 High (frequent updates) |
| **bigdataball** | 1 | 🟢 Low |
| **basketball_ref** | 1 | 🟢 Low |

### By Update Frequency

| Frequency | Processors | Impact |
|-----------|-----------|--------|
| **Multiple times daily** | Injuries (2), Props (3), Scoreboard (2) | 🔴 Critical - highest cascade risk |
| **Daily** | Boxscores (5), Schedule (1), Standings (1) | 🟡 Medium |
| **Weekly/Seasonal** | Rosters (2), Player List (1), Schedule (1) | 🟢 Low |
| **Per game** | Play-by-play (2), Gamebook (1), Team stats (1) | 🟡 Medium |

---

## Processor-by-Processor Analysis

### 🔴 Critical Priority (Implement First)

#### 1. **nbac_injury_report_processor.py**
- **Table:** `nba_raw.nbac_injury_report`
- **Strategy:** `APPEND_ALWAYS`
- **Update Frequency:** 4-6x daily (morning, afternoon, evening, pre-game)
- **Downstream Impact:** Phase 3 (player context), Phase 5 (all prediction systems)
- **Primary Key:** `(player_lookup, game_id, report_date, report_hour)`

**Hash Fields (Schema-Validated):**
```python
HASH_FIELDS = [
    'player_lookup',        # Schema: player_lookup STRING
    'team',                 # Schema: team STRING (player's team)
    'game_date',            # Schema: game_date DATE
    'game_id',              # Schema: game_id STRING
    'injury_status',        # Schema: injury_status STRING ("out", "questionable", "doubtful", "probable", "available")
    'reason',               # Schema: reason STRING (full reason text)
    'reason_category'       # Schema: reason_category STRING ("injury", "g_league", "suspension", etc.)
]
```

**Exclude:**
- `report_date` (scrape date - metadata)
- `report_hour` (scrape hour - metadata)
- `scrape_time` (scraper timestamp)
- `run_id` (scraper run ID)
- `source_file_path` (GCS path)
- `processed_at` (processing timestamp)
- `confidence_score` (parsing confidence - changes with scraper improvements)
- `overall_report_confidence` (report confidence)
- Game metadata: `matchup`, `away_team`, `home_team`, `game_time` (duplicative)
- Player name variants: `player_name_original`, `player_full_name` (use normalized lookup)

**Rationale:** If player status unchanged (e.g., "Out - Ankle" → "Out - Ankle"), skip write. Downstream only cares if status/injury/availability changes, not when it was scraped.

---

#### 2. **bdl_injuries_processor.py**
- **Table:** `nba_raw.bdl_injuries`
- **Strategy:** `APPEND_ALWAYS`
- **Update Frequency:** 4-6x daily
- **Downstream Impact:** Phase 3 (player context), Phase 5 (predictions)

**Hash Fields:**
```python
HASH_FIELDS = [
    'player_lookup',
    'game_date',
    'status',               # Out, Day-To-Day, etc.
    'injury_type',          # Body part injured
    'injury_description'
]
```

**Exclude:**
- `date_recorded`
- `source_data` (raw JSON)
- Metadata fields

**Rationale:** Similar to NBA.com injuries - only hash what affects player availability.

---

#### 3. **odds_api_props_processor.py**
- **Table:** `nba_raw.odds_api_player_points_props`
- **Strategy:** TBD (likely MERGE_UPDATE with snapshots)
- **Update Frequency:** Hourly (lines move throughout day)
- **Downstream Impact:** Phase 5 (prop predictions)
- **Primary Key:** `(game_id, player_lookup, bookmaker, snapshot_timestamp)`
- **Note:** Currently only tracks **points** props

**Hash Fields (Schema-Validated):**
```python
HASH_FIELDS = [
    'player_lookup',        # Schema: player_lookup STRING (normalized)
    'game_date',            # Schema: game_date DATE
    'game_id',              # Schema: game_id STRING
    'bookmaker',            # Schema: bookmaker STRING
    'points_line',          # Schema: points_line FLOAT64 (25.5, 26.5, etc.)
    # EXCLUDE: over_price, over_price_american, under_price, under_price_american
]
```

**Exclude:**
- `over_price` (decimal odds - changes constantly)
- `over_price_american` (American odds e.g., -110 → -115)
- `under_price` (decimal odds)
- `under_price_american` (American odds)
- `snapshot_timestamp` (when scraped)
- `snapshot_tag` (scrape identifier)
- `capture_timestamp` (scraper run time)
- `minutes_before_tipoff` (calculated field)
- `bookmaker_last_update` (API timestamp)
- `source_file_path` (GCS path)
- `data_source` (collection method)
- `processing_timestamp` (processing time)
- Game details: `odds_api_event_id`, `home_team_abbr`, `away_team_abbr`, `game_start_time` (duplicative)
- Player name: `player_name` (use normalized lookup)

**Rationale:**
- If **points line** changes (25.5 → 26.5), trigger reprocessing (meaningful prediction change)
- If just **odds** change (-110 → -115), skip write (line didn't move, just juice adjusted)
- Prevents cascade from constant odds movements while catching actual line movements
- **Critical:** This prevents 10-20 writes per game per player from becoming 1-2 writes only when line moves

---

#### 4. **bettingpros_player_props_processor.py**
- **Table:** `nba_raw.bettingpros_player_points_props`
- **Strategy:** `CHECK_BEFORE_INSERT`
- **Update Frequency:** Multiple times daily
- **Downstream Impact:** Phase 5 (prop predictions)
- **Primary Key:** `(offer_id, bet_side)` or `(game_date, player_lookup, bookmaker, bet_side)`
- **Note:** Currently only tracks **points** props

**Hash Fields (Schema-Validated):**
```python
HASH_FIELDS = [
    'player_lookup',        # Schema: player_lookup STRING (normalized)
    'game_date',            # Schema: game_date DATE
    'market_type',          # Schema: market_type STRING ("points")
    'bookmaker',            # Schema: bookmaker STRING
    'bet_side',             # Schema: bet_side STRING ("over" or "under")
    'points_line',          # Schema: points_line FLOAT64 (5.5, 10.5, etc.)
    'is_best_line',         # Schema: is_best_line BOOLEAN (flagged as best available)
    # EXCLUDE: odds_american, validation fields
]
```

**Exclude:**
- `odds_american` (odds e.g., -143, +105 - changes constantly)
- `bp_event_id`, `market_id`, `offer_id`, `bet_side` metadata IDs
- `bp_player_id`, `book_id`, `line_id` (internal IDs)
- `player_name`, `player_team`, `player_position` (use normalized lookup and validated team)
- All validation/quality fields:
  - `team_source`, `has_team_issues`, `validated_team`
  - `validation_confidence`, `validation_method`, `validation_notes`
  - `player_complications`
- Opening line tracking (historical data):
  - `opening_line`, `opening_odds`, `opening_book_id`, `opening_timestamp`
- Status flags: `is_active` (changes frequently)
- Timestamps: `bookmaker_last_update`, `created_at`, `processed_at`
- `source_file_path` (GCS path)

**Rationale:**
- Hash the actual **line value** and which side (over/under)
- Include `is_best_line` as it indicates consensus/market efficiency
- Exclude odds movements (juice changes don't affect predictions)
- Exclude all validation fields (they improve over time but don't change the line)

---

#### 5. **odds_game_lines_processor.py**
- **Table:** `nba_raw.odds_api_game_lines`
- **Strategy:** Snapshot-based (multiple records per game)
- **Update Frequency:** Hourly (lines move throughout day)
- **Downstream Impact:** Phase 3 (team context), Phase 5 (game predictions)
- **Primary Key:** `(game_id, bookmaker_key, market_key, outcome_name, snapshot_timestamp)`
- **Note:** Flattened structure - one row per outcome (spread has 2 rows, total has 2 rows)

**Hash Fields (Schema-Validated):**
```python
HASH_FIELDS = [
    'game_id',              # Schema: game_id STRING
    'game_date',            # Schema: game_date DATE
    'bookmaker_key',        # Schema: bookmaker_key STRING
    'market_key',           # Schema: market_key STRING ('spreads' or 'totals')
    'outcome_name',         # Schema: outcome_name STRING (team name or 'Over'/'Under')
    'outcome_point',        # Schema: outcome_point FLOAT64 (spread value or total value)
    # EXCLUDE: outcome_price (odds change constantly)
]
```

**Exclude:**
- `outcome_price` (decimal odds - changes constantly)
- `snapshot_timestamp` (when scraped)
- `previous_snapshot_timestamp`, `next_snapshot_timestamp` (snapshot linking)
- `commence_time` (game start time - metadata)
- `sport_key`, `sport_title` (always "basketball_nba")
- Team names: `home_team`, `away_team`, `home_team_abbr`, `away_team_abbr` (duplicative with game_id)
- `bookmaker_title` (use key)
- Timestamps: `bookmaker_last_update`, `market_last_update`
- `source_file_path` (GCS path)
- `data_source` (collection method)
- `created_at`, `processed_at` (processing timestamps)

**Rationale:**
- Hash the **line value** (`outcome_point`) - e.g., spread changes from -7.5 to -8.0
- Exclude **odds** (`outcome_price`) - e.g., -110 to -115 doesn't affect predictions
- Flattened structure means:
  - Spread: 2 rows (home team point, away team point)
  - Total: 2 rows (Over point, Under point)
- If spread moves from LAL -7.5 to LAL -8.0, trigger reprocessing
- If just odds move (LAL -7.5 -110 to LAL -7.5 -115), skip write

---

### 🟡 Medium Priority

#### 6. **nbac_scoreboard_v2_processor.py**
- **Table:** `nba_raw.nbac_scoreboard_v2`
- **Strategy:** `MERGE_UPDATE`
- **Update Frequency:** Throughout game day (live scores)
- **Downstream Impact:** Phase 3 (game results)

**Hash Fields:**
```python
HASH_FIELDS = [
    'game_id',
    'game_date',
    'game_status',          # Scheduled, In Progress, Final
    'home_team_score',
    'away_team_score',
    'period',               # Quarter
    'game_clock'
]
```

**Exclude:**
- `last_updated` timestamp
- `attendance`
- `officials` (unless needed)

**Rationale:** Only hash what changes game outcome. Live updates during game need to trigger reprocessing.

**Note:** May want to skip hash check for in-progress games (always update).

---

#### 7. **espn_scoreboard_processor.py**
- **Table:** `nba_raw.espn_scoreboard`
- **Strategy:** `MERGE_UPDATE`
- **Update Frequency:** Throughout game day
- **Downstream Impact:** Phase 3 (game results)

**Hash Fields:** Similar to nbac_scoreboard_v2

---

#### 8. **nbac_gamebook_processor.py**
- **Table:** `nba_raw.nbac_gamebook_player_stats`
- **Strategy:** `MERGE_UPDATE`
- **Update Frequency:** Post-game (should be stable)
- **Downstream Impact:** Phase 3 (player game summary)

**Hash Fields:**
```python
HASH_FIELDS = [
    'game_id',
    'player_lookup',
    'team_tricode',
    'minutes_played',
    'points',
    'rebounds',
    'assists',
    # All box score stats
    'dnp_reason',           # Did Not Play
    'starter_bench'         # Starter vs Bench
]
```

**Exclude:**
- Resolution metadata
- Cache hit/miss info
- Processing timestamps

**Rationale:** Box scores should be final after game ends. Hash check prevents reprocessing if scraper runs again.

**Question:** Do gamebook stats ever change post-game? (Stat corrections?)

---

#### 9-13. **Other Boxscore Processors**
- `bdl_boxscores_processor.py`
- `espn_boxscore_processor.py`
- `nbac_player_boxscore_processor.py`
- `nbac_team_boxscore_processor.py`
- `bigdataball_pbp_processor.py`

**Similar Strategy:** Hash all stats, exclude metadata.

**Question:** How often do these sources update post-game? If stable, hash check valuable.

---

### 🟢 Low Priority (Implement Later)

#### 14-22. **Reference/Roster Tables**
- `nbac_schedule_processor.py` - Schedule changes infrequent
- `bdl_standings_processor.py` - Daily updates but low downstream impact
- `br_roster_processor.py` - Weekly updates
- `espn_team_roster_processor.py` - Weekly updates
- `nbac_player_list_processor.py` - Seasonal
- `bdl_active_players_processor.py` - Daily but low impact
- `nbac_player_movement_processor.py` - Rare
- `nbac_referee_processor.py` - Per game
- `nbac_play_by_play_processor.py` - Per game, large data

**Rationale:** These update infrequently or have low downstream impact. Implement hash checking if monitoring shows unnecessary cascade.

---

## Implementation Phases

### Phase 1: Critical High-Frequency Processors (Week 1)
**Target:** Prevent 75% of cascade processing

1. ✅ Document strategy (this file)
2. [ ] Review and finalize hash fields for each processor
3. [ ] Add schema migrations (data_hash column)
4. [ ] Implement SmartIdempotencyMixin
5. [ ] Apply to 5 critical processors:
   - nbac_injury_report_processor.py
   - bdl_injuries_processor.py
   - odds_api_props_processor.py
   - bettingpros_player_props_processor.py
   - odds_game_lines_processor.py
6. [ ] Test locally with sample data
7. [ ] Deploy to production
8. [ ] Monitor skip rates for 1 week

### Phase 2: Medium-Frequency Processors (Week 2)
**Target:** Prevent remaining cascade processing

1. [ ] Apply to scoreboard/boxscore processors (7 processors)
2. [ ] Monitor effectiveness
3. [ ] Adjust hash fields based on learning

### Phase 3: Remaining Processors (Week 3+)
**Target:** Complete coverage

1. [ ] Apply to all remaining processors
2. [ ] Document lessons learned
3. [ ] Update pattern catalog

---

## Schema Changes Required

### Tables Needing data_hash Column

**Critical (Phase 1):**
```sql
ALTER TABLE `nba_raw.nbac_injury_report` ADD COLUMN IF NOT EXISTS data_hash STRING;
ALTER TABLE `nba_raw.bdl_injuries` ADD COLUMN IF NOT EXISTS data_hash STRING;
ALTER TABLE `nba_raw.odds_api_props` ADD COLUMN IF NOT EXISTS data_hash STRING;
ALTER TABLE `nba_raw.bettingpros_player_points_props` ADD COLUMN IF NOT EXISTS data_hash STRING;
ALTER TABLE `nba_raw.odds_game_lines` ADD COLUMN IF NOT EXISTS data_hash STRING;
```

**Medium (Phase 2):**
```sql
ALTER TABLE `nba_raw.nbac_scoreboard_v2` ADD COLUMN IF NOT EXISTS data_hash STRING;
ALTER TABLE `nba_raw.espn_scoreboard` ADD COLUMN IF NOT EXISTS data_hash STRING;
ALTER TABLE `nba_raw.nbac_gamebook_player_stats` ADD COLUMN IF NOT EXISTS data_hash STRING;
ALTER TABLE `nba_raw.bdl_player_boxscores` ADD COLUMN IF NOT EXISTS data_hash STRING;
ALTER TABLE `nba_raw.espn_boxscores` ADD COLUMN IF NOT EXISTS data_hash STRING;
ALTER TABLE `nba_raw.nbac_team_boxscore` ADD COLUMN IF NOT EXISTS data_hash STRING;
ALTER TABLE `nba_raw.bigdataball_play_by_play` ADD COLUMN IF NOT EXISTS data_hash STRING;
```

**Low (Phase 3):** Remaining tables as needed

---

## Open Questions

### 1. Gamebook Stat Corrections
**Question:** Do NBA.com gamebook stats ever get corrected post-game?
**Impact:** If yes, hash checking could prevent corrections from flowing downstream
**Research Needed:** Check historical data for stat changes

### 2. Processing Strategy Compatibility
**Question:** How does hash checking work with different processing strategies?
- `APPEND_ALWAYS` - Need to check if latest row has same hash
- `MERGE_UPDATE` - Check before DELETE+INSERT
- `INSERT_NEW_ONLY` - Less critical (already checking existence)
- `CHECK_BEFORE_INSERT` - Already has some checking logic

**Action:** Review each strategy implementation

### 3. Composite Keys
**Question:** How do we handle processors with composite keys?
**Example:** `(game_id, player_lookup)` for boxscores
**Solution:** Pass multiple key fields to `check_if_data_changed()`

### 4. Hash Performance
**Question:** Does hash checking add significant latency?
**Estimate:** 1 BigQuery query per row to check existing hash
**Mitigation:** Batch hash checks? Cache recent hashes?

### 5. Partial Updates
**Question:** What if only some rows in a batch have changed?
**Example:** Injury report with 100 players, only 5 status changes
**Solution:** Check each row individually, only write changed rows

---

## Success Metrics

### Week 1 (After Phase 1 Deployment)

**Primary Metrics:**
- [ ] Hash skip rate for injury reports (target: 70-90%)
- [ ] Hash skip rate for props (target: 60-80%)
- [ ] Reduction in Phase 3 processing runs (target: 50%+)
- [ ] No missed data changes (validate sample)

**Secondary Metrics:**
- [ ] BigQuery query cost reduction
- [ ] Cloud Run execution time reduction
- [ ] Phase 3 `processed_at` updates per day (before/after)

### Week 2 (After Phase 2 Deployment)

- [ ] Overall cascade reduction (target: 75%+)
- [ ] Hash check performance impact (latency)
- [ ] False negative rate (missed changes)

---

## Risk Mitigation

### Risk 1: Missing Real Changes
**Mitigation:**
- Fail-open design (errors → process anyway)
- Comprehensive testing with real data
- Monitor false negative rate in production

### Risk 2: Hash Collisions
**Mitigation:**
- Use SHA256 (first 16 chars = 2^64 space)
- Include key fields in hash to reduce collision probability

### Risk 3: Performance Degradation
**Mitigation:**
- Measure latency in testing
- Add timeout on hash check (fail-open if slow)
- Consider caching recent hashes in memory

### Risk 4: Field Selection Errors
**Mitigation:**
- Document rationale for each field decision (this doc)
- Review with domain knowledge
- Monitor for unexpected behavior in production

---

## Next Steps

1. **Review this document** - Validate approach and field selections
2. **Answer open questions** - Research gamebook corrections, etc.
3. **Create implementation branch** - `feature/pattern14-smart-idempotency`
4. **Implement Phase 1** - 5 critical processors
5. **Test thoroughly** - Sample data from each source
6. **Deploy and monitor** - 1 week observation period

---

## References

- [Pattern #14: Smart Idempotency](../patterns/12-smart-idempotency-reference.md)
- [Pattern Rollout Plan](../implementation/pattern-rollout-plan.md)
- [Phase 2 Processor Architecture](../architecture/phase2-raw-processors.md)

---

**Last Updated:** 2025-11-21 09:30 AM PST
**Next Review:** After Phase 1 implementation complete
