# Schema Update Plan: Smart Idempotency

**File:** `docs/implementation/schema-update-plan-smart-idempotency.md`
**Created:** 2025-11-21 10:15 AM PST
**Last Updated:** 2025-11-21 11:45 AM PST
**Purpose:** Complete plan for updating schemas (both CREATE TABLE SQL and migrations) for smart idempotency
**Status:** Ready for Implementation

---

## Overview

This plan ensures **both** the original CREATE TABLE SQL files and migration SQL are updated for smart idempotency implementation.

**Key Principle:** Always maintain CREATE TABLE SQL as source of truth, then generate migrations.

**Strategy:** Add `data_hash` column to ALL Phase 2 tables now, implement hash logic gradually by priority.

---

## Phase 2: Raw Tables (Add data_hash to ALL 22 Tables)

### Strategy Decision

**User Decision:** Add `data_hash` column to all 22 Phase 2 tables immediately, implement hash computation logic by priority.

**Rationale:**
- Future-proof: All tables ready for hash checking when needed
- No breaking changes: NULL values are safe
- Low cost: 16 chars × rows is minimal
- Consistent schema: All Phase 2 tables have same structure
- Gradual implementation: Hash logic follows priority (critical → medium → low)

### Implementation Approach

1. **Schema Changes (All at Once):**
   - Update all 22 CREATE TABLE SQL files
   - Generate all 22 migration SQL files
   - Run all migrations to add `data_hash STRING` column
   - All columns will initially be NULL

2. **Hash Logic Implementation (By Priority):**
   - Week 1: Implement hash logic for 5 critical processors
   - Week 2: Implement hash logic for 7 medium priority processors
   - Week 3+: Implement hash logic for 8 low priority processors

---

## All Phase 2 Tables (22 Total)

### 🔴 Critical Priority - Implement Hash Logic Week 1 (5 tables)
**High update frequency - Maximum cascade prevention impact**

#### 1. nba_raw.nbac_injury_report

**Original SQL:** `schemas/bigquery/raw/nbac_injury_report_tables.sql`
**Processor:** `data_processors/raw/nbacom/nbac_injury_report_processor.py`
**Update Frequency:** 4-6x daily
**Cascade Impact:** 450+ players × 3 downstream phases

**Action:** Add data_hash column before processed_at

```sql
-- Add after error_details field:
data_hash STRING,  -- Hash of meaningful fields for idempotency checking

processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
```

**Hash Fields:** `player_lookup`, `team`, `game_date`, `game_id`, `injury_status`, `reason`, `reason_category`

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_nbac_injury_report.sql`
```sql
-- Migration: Add data_hash for smart idempotency
-- Date: 2025-11-21
-- Pattern: #14 Smart Idempotency

ALTER TABLE `nba_raw.nbac_injury_report`
ADD COLUMN IF NOT EXISTS data_hash STRING;

COMMENT ON COLUMN `nba_raw.nbac_injury_report`.data_hash IS
'SHA256 hash (16 chars) of: player_lookup, team, game_date, game_id, injury_status, reason, reason_category. Used to skip redundant writes when injury status unchanged.';
```

---

#### 2. nba_raw.bdl_injuries

**Original SQL:** `schemas/bigquery/raw/balldontlie_tables.sql`
**Processor:** `data_processors/raw/balldontlie/bdl_injuries_processor.py`
**Update Frequency:** 4-6x daily
**Cascade Impact:** High

**Action:** Add data_hash column before processed_at

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_bdl_injuries.sql`
```sql
ALTER TABLE `nba_raw.bdl_injuries`
ADD COLUMN IF NOT EXISTS data_hash STRING;
```

---

#### 3. nba_raw.odds_api_player_points_props

**Original SQL:** `schemas/bigquery/raw/odds_api_props_tables.sql`
**Processor:** `data_processors/raw/oddsapi/odds_api_props_processor.py`
**Update Frequency:** Hourly
**Cascade Impact:** Very High - directly feeds predictions

**Action:** Add data_hash column before processing_timestamp

```sql
-- Add after source_file_path:
data_hash STRING,  -- Hash of: player_lookup, game_date, game_id, bookmaker, points_line

processing_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
```

**Hash Fields:** `player_lookup`, `game_date`, `game_id`, `bookmaker`, `points_line`

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_odds_api_props.sql`
```sql
ALTER TABLE `nba_raw.odds_api_player_points_props`
ADD COLUMN IF NOT EXISTS data_hash STRING;
```

---

#### 4. nba_raw.bettingpros_player_points_props

**Original SQL:** `schemas/bigquery/raw/bettingpros_player_props_tables.sql`
**Processor:** `data_processors/raw/bettingpros/bettingpros_player_props_processor.py`
**Update Frequency:** Multiple times daily
**Cascade Impact:** Very High - directly feeds predictions

**Action:** Add data_hash column before processed_at

```sql
-- Add after source_file_path:
data_hash STRING,  -- Hash of: player_lookup, game_date, market_type, bookmaker, bet_side, points_line, is_best_line

processed_at TIMESTAMP NOT NULL
```

**Hash Fields:** `player_lookup`, `game_date`, `market_type`, `bookmaker`, `bet_side`, `points_line`, `is_best_line`

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_bettingpros_props.sql`
```sql
ALTER TABLE `nba_raw.bettingpros_player_points_props`
ADD COLUMN IF NOT EXISTS data_hash STRING;
```

---

#### 5. nba_raw.odds_api_game_lines

**Original SQL:** `schemas/bigquery/raw/odds_game_lines_tables.sql`
**Processor:** `data_processors/raw/oddsapi/odds_game_lines_processor.py`
**Update Frequency:** Hourly
**Cascade Impact:** High - feeds game context

**Action:** Add data_hash column before processed_at

```sql
-- Add after source_file_path:
data_hash STRING,  -- Hash of: game_id, game_date, bookmaker_key, market_key, outcome_name, outcome_point

processed_at TIMESTAMP NOT NULL
```

**Hash Fields:** `game_id`, `game_date`, `bookmaker_key`, `market_key`, `outcome_name`, `outcome_point`

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_odds_game_lines.sql`
```sql
ALTER TABLE `nba_raw.odds_api_game_lines`
ADD COLUMN IF NOT EXISTS data_hash STRING;
```

---

### 🟡 Medium Priority - Implement Hash Logic Week 2 (7 tables)
**Moderate update frequency - Post-game updates**

#### 6. nba_raw.nbac_play_by_play

**Original SQL:** `schemas/bigquery/raw/nbac_play_by_play_tables.sql`
**Processor:** `data_processors/raw/nbacom/nbac_play_by_play_processor.py`
**Update Frequency:** Per-game (during and post-game)
**Cascade Impact:** Medium

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_nbac_play_by_play.sql`

---

#### 7. nba_raw.nbac_player_boxscores

**Original SQL:** `schemas/bigquery/raw/nbac_player_boxscore_tables.sql`
**Processor:** `data_processors/raw/nbacom/nbac_player_boxscore_processor.py`
**Update Frequency:** Post-game
**Cascade Impact:** High - feeds player_game_summary

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_nbac_player_boxscores.sql`

---

#### 8. nba_raw.nbac_team_boxscore

**Original SQL:** `schemas/bigquery/raw/nbac_team_boxscore_tables.sql`
**Processor:** `data_processors/raw/nbacom/nbac_team_boxscore_processor.py`
**Update Frequency:** Post-game
**Cascade Impact:** High - feeds team summaries

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_nbac_team_boxscore.sql`

---

#### 9. nba_raw.nbac_gamebook_player_stats

**Original SQL:** `schemas/bigquery/raw/nbac_gamebook_tables.sql`
**Processor:** `data_processors/raw/nbacom/nbac_gamebook_processor.py`
**Update Frequency:** Post-game
**Cascade Impact:** High - primary source for player_game_summary

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_nbac_gamebook.sql`

---

#### 10. nba_raw.bdl_player_boxscores

**Original SQL:** `schemas/bigquery/raw/balldontlie_tables.sql`
**Processor:** `data_processors/raw/balldontlie/bdl_boxscores_processor.py`
**Update Frequency:** Post-game
**Cascade Impact:** Medium

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_bdl_boxscores.sql`

---

#### 11. nba_raw.espn_scoreboard

**Original SQL:** `schemas/bigquery/raw/espn_scoreboard_tables.sql`
**Processor:** `data_processors/raw/espn/espn_scoreboard_processor.py`
**Update Frequency:** Throughout game day
**Cascade Impact:** Medium

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_espn_scoreboard.sql`

---

#### 12. nba_raw.espn_boxscores

**Original SQL:** `schemas/bigquery/raw/espn_boxscore_tables.sql`
**Processor:** `data_processors/raw/espn/espn_boxscore_processor.py`
**Update Frequency:** Post-game
**Cascade Impact:** Medium

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_espn_boxscores.sql`

---

### 🟢 Low Priority - Implement Hash Logic Week 3+ (8 tables)
**Infrequent updates or low cascade impact**

#### 13. nba_raw.nbac_schedule

**Original SQL:** `schemas/bigquery/raw/nbac_schedule_tables.sql`
**Processor:** `data_processors/raw/nbacom/nbac_schedule_processor.py`
**Update Frequency:** Weekly/seasonal
**Cascade Impact:** Low

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_nbac_schedule.sql`

---

#### 14. nba_raw.nbac_player_list_current

**Original SQL:** `schemas/bigquery/raw/nbac_player_list_tables.sql`
**Processor:** `data_processors/raw/nbacom/nbac_player_list_processor.py`
**Update Frequency:** Seasonal
**Cascade Impact:** Low

**Note:** This table is actively used. GetNbaComTeamRoster scraper is NOT used (user confirmed).

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_nbac_player_list.sql`

---

#### 15. nba_raw.nbac_player_movement

**Original SQL:** `schemas/bigquery/raw/nbac_player_movement_tables.sql`
**Processor:** `data_processors/raw/nbacom/nbac_player_movement_processor.py`
**Update Frequency:** Rare (transactions/trades)
**Cascade Impact:** Low

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_nbac_player_movement.sql`

---

#### 16. nba_raw.nbac_referee_game_assignments

**Original SQL:** `schemas/bigquery/raw/nbac_referee_tables.sql`
**Processor:** `data_processors/raw/nbacom/nbac_referee_processor.py`
**Update Frequency:** Daily
**Cascade Impact:** Low

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_nbac_referee.sql`

---

#### 17. nba_raw.bdl_active_players_current

**Original SQL:** `schemas/bigquery/raw/balldontlie_tables.sql`
**Processor:** `data_processors/raw/balldontlie/bdl_active_players_processor.py`
**Update Frequency:** Daily
**Cascade Impact:** Low

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_bdl_active_players.sql`

---

#### 18. nba_raw.bdl_standings

**Original SQL:** `schemas/bigquery/raw/balldontlie_tables.sql`
**Processor:** `data_processors/raw/balldontlie/bdl_standings_processor.py`
**Update Frequency:** Daily
**Cascade Impact:** Low

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_bdl_standings.sql`

---

#### 19. nba_raw.espn_team_rosters

**Original SQL:** `schemas/bigquery/raw/espn_team_roster_tables.sql`
**Processor:** `data_processors/raw/espn/espn_team_roster_processor.py`
**Update Frequency:** Weekly
**Cascade Impact:** Low

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_espn_team_rosters.sql`

---

#### 20. nba_raw.bigdataball_play_by_play

**Original SQL:** `schemas/bigquery/raw/bigdataball_pbp_tables.sql`
**Processor:** `data_processors/raw/bigdataball/bigdataball_pbp_processor.py`
**Update Frequency:** Per-game
**Cascade Impact:** Low (limited downstream usage)

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_bigdataball_pbp.sql`

---

#### 21. nba_raw.br_rosters_current

**Original SQL:** `schemas/bigquery/raw/basketball_reference_tables.sql`
**Processor:** `data_processors/raw/basketball_reference/br_roster_processor.py`
**Update Frequency:** Seasonal
**Cascade Impact:** Low

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_br_rosters.sql`

---

### ⏸️ Potentially Inactive (1 table)

#### 22. nba_raw.nbac_scoreboard_v2

**Original SQL:** `schemas/bigquery/raw/nbac_scoreboard_v2_tables.sql`
**Processor:** `data_processors/raw/nbacom/nbac_scoreboard_v2_processor.py`
**Status:** User indicated "most are active" - include in schema updates but verify before implementing hash logic

**Migration:** `monitoring/schemas/migrations/add_data_hash_to_nbac_scoreboard_v2.sql`

**Action:** Add column now, implement hash logic only if processor confirmed active.

---

## Phase 3: Analytics Tables (Add per-source hashes)

### Integration with Dependency Tracking

Phase 3 tables need **BOTH** smart idempotency AND dependency tracking:

**Per dependency (4 fields):**
- `source_{prefix}_data_hash STRING` - Hash from Phase 2 (NEW)
- `source_{prefix}_last_updated TIMESTAMP` - Existing pattern
- `source_{prefix}_rows_found INT64` - Existing pattern
- `source_{prefix}_completeness_pct NUMERIC(5,2)` - Existing pattern

**No composite hash** - Individual source hashes are sufficient for checking.

### How Dependency Checking Works

**For point-in-time dependencies (Phase 3 → Phase 2):**

1. Load destination record (if exists)
2. Load source data from Phase 2 tables
3. Compare each individual `source_{prefix}_data_hash` to current Phase 2 `data_hash`
4. If ANY source hash differs → reprocess
5. If ALL source hashes match → skip

**For historical range dependencies (Phase 4 → Phase 3):**

See `docs/implementation/04-dependency-checking-strategy.md` for details on timestamp-based checking for L30/L10 calculations.

---

### 1. nba_analytics.player_game_summary

**Original SQL:** `schemas/bigquery/analytics/player_game_summary_tables.sql`
**Dependencies:** 6 Phase 2 sources

**Action:** Add after business fields, before processed_at:

```sql
-- SOURCE TRACKING: Dependency 1 - nbac_gamebook_player_stats
source_nbac_gamebook_data_hash STRING,
source_nbac_gamebook_last_updated TIMESTAMP,
source_nbac_gamebook_rows_found INT64,
source_nbac_gamebook_completeness_pct NUMERIC(5,2),

-- SOURCE TRACKING: Dependency 2 - bdl_player_boxscores
source_bdl_boxscores_data_hash STRING,
source_bdl_boxscores_last_updated TIMESTAMP,
source_bdl_boxscores_rows_found INT64,
source_bdl_boxscores_completeness_pct NUMERIC(5,2),

-- ... (repeat for all 6 dependencies)

-- Processing metadata
processed_at TIMESTAMP NOT NULL
```

**Migration:** `monitoring/schemas/migrations/add_source_tracking_to_player_game_summary.sql`
```sql
ALTER TABLE `nba_analytics.player_game_summary`

-- Dependency 1: nbac_gamebook_player_stats
ADD COLUMN IF NOT EXISTS source_nbac_gamebook_data_hash STRING,
ADD COLUMN IF NOT EXISTS source_nbac_gamebook_last_updated TIMESTAMP,
ADD COLUMN IF NOT EXISTS source_nbac_gamebook_rows_found INT64,
ADD COLUMN IF NOT EXISTS source_nbac_gamebook_completeness_pct NUMERIC(5,2),

-- Dependency 2: bdl_player_boxscores
ADD COLUMN IF NOT EXISTS source_bdl_boxscores_data_hash STRING,
ADD COLUMN IF NOT EXISTS source_bdl_boxscores_last_updated TIMESTAMP,
ADD COLUMN IF NOT EXISTS source_bdl_boxscores_rows_found INT64,
ADD COLUMN IF NOT EXISTS source_bdl_boxscores_completeness_pct NUMERIC(5,2);

-- ... (repeat for all 6)
```

---

### 2-5. Other Phase 3 Tables

Similar pattern for:
- `nba_analytics.team_defense_game_summary`
- `nba_analytics.team_offense_game_summary`
- `nba_analytics.upcoming_player_game_context`
- `nba_analytics.upcoming_team_game_context`

---

## Phase 4: Precompute Tables

Same pattern as Phase 3, for:
- `nba_precompute.player_composite_factors`
- `nba_precompute.player_shot_zone_analysis`
- `nba_precompute.team_defense_zone_analysis`
- `nba_precompute.player_daily_cache`
- `nba_precompute.ml_feature_store`

---

## Phase 5: Predictions Tables

**Table:** `nba_predictions.prediction_worker_runs`

**Original SQL:** `schemas/bigquery/predictions/prediction_worker_runs_tables.sql`

**Dependency Type:** TBD - depends on Phase 4 output structure

**If Phase 4 has point-in-time dependencies:**
- Add source tracking fields for Phase 4 precompute inputs
- Use per-source hash checking (4 fields per dependency)

**If Phase 4 uses historical ranges:**
- Use timestamp-based dependency checking (see `04-dependency-checking-strategy.md`)
- No source hash fields needed

**Decision:** Determine when designing Phase 5 prediction worker based on actual Phase 4 implementation.

---

## Implementation Workflow

### Step 1: Update Original SQL Files (Source of Truth)

**For ALL 22 Phase 2 tables:**

1. Open original CREATE TABLE SQL file in `schemas/bigquery/raw/`
2. Add `data_hash STRING` column before processed_at timestamp
3. Add comment explaining field purpose
4. Update OPTIONS description to mention smart idempotency
5. Save file

**Example locations:**
```
schemas/bigquery/raw/nbac_injury_report_tables.sql
schemas/bigquery/raw/odds_api_props_tables.sql
schemas/bigquery/raw/balldontlie_tables.sql  (multiple tables in one file)
schemas/bigquery/raw/espn_scoreboard_tables.sql
... (all 22 tables)
```

**For Phase 3/4/5 tables:**

1. Open original CREATE TABLE SQL file
2. Add source tracking fields (4 per dependency + 1 composite)
3. Add comments for each source
4. Save file

---

### Step 2: Generate Migration SQL

**Create migration files for ALL tables:**

1. Create migration file in `monitoring/schemas/migrations/`
2. Use `ADD COLUMN IF NOT EXISTS` for safety
3. Add header comment with date, pattern reference
4. Add column comments for documentation

**Migration naming convention:**
```
add_data_hash_to_{table_name}.sql              # Phase 2 tables
add_source_tracking_to_{table_name}.sql        # Phase 3/4/5 tables
```

**Total migrations to create:**
- 22 Phase 2 migrations (add data_hash)
- 5 Phase 3 migrations (add source tracking - 4 fields per dependency, no composite)
- Phase 4 migrations: TBD based on dependency types
- Phase 5 migration: TBD based on Phase 4 implementation
- **Minimum: 27 migration files (Phase 2 + Phase 3)**

---

### Step 3: Run Migrations

```bash
# Phase 2 migrations (ALL 22 tables - run all at once)
bq query < monitoring/schemas/migrations/add_data_hash_to_nbac_injury_report.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_bdl_injuries.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_odds_api_props.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_bettingpros_props.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_odds_game_lines.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_nbac_play_by_play.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_nbac_player_boxscores.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_nbac_team_boxscore.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_nbac_gamebook.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_bdl_boxscores.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_espn_scoreboard.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_espn_boxscores.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_nbac_schedule.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_nbac_player_list.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_nbac_player_movement.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_nbac_referee.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_bdl_active_players.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_bdl_standings.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_espn_team_rosters.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_bigdataball_pbp.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_br_rosters.sql
bq query < monitoring/schemas/migrations/add_data_hash_to_nbac_scoreboard_v2.sql

# Phase 3 migrations (5 analytics tables)
bq query < monitoring/schemas/migrations/add_source_tracking_to_player_game_summary.sql
bq query < monitoring/schemas/migrations/add_source_tracking_to_team_defense_summary.sql
bq query < monitoring/schemas/migrations/add_source_tracking_to_team_offense_summary.sql
bq query < monitoring/schemas/migrations/add_source_tracking_to_upcoming_player_context.sql
bq query < monitoring/schemas/migrations/add_source_tracking_to_upcoming_team_context.sql

# Phase 4 migrations (5 precompute tables)
bq query < monitoring/schemas/migrations/add_source_tracking_to_player_composite_factors.sql
bq query < monitoring/schemas/migrations/add_source_tracking_to_player_shot_zone_analysis.sql
bq query < monitoring/schemas/migrations/add_source_tracking_to_team_defense_zone_analysis.sql
bq query < monitoring/schemas/migrations/add_source_tracking_to_player_daily_cache.sql
bq query < monitoring/schemas/migrations/add_source_tracking_to_ml_feature_store.sql

# Phase 5 migration (1 predictions table)
bq query < monitoring/schemas/migrations/add_source_hash_to_prediction_worker_runs.sql
```

---

### Step 4: Verify Schema Changes

```sql
-- Verify Phase 2 tables (check random sample)
SELECT column_name, data_type
FROM `nba_raw.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'nbac_injury_report'
  AND column_name = 'data_hash';

SELECT column_name, data_type
FROM `nba_raw.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'odds_api_player_points_props'
  AND column_name = 'data_hash';

-- Verify all Phase 2 tables have data_hash
SELECT table_name, COUNT(*) as has_data_hash
FROM `nba_raw.INFORMATION_SCHEMA.COLUMNS`
WHERE column_name = 'data_hash'
GROUP BY table_name
ORDER BY table_name;

-- Should return 22 rows (one per table)

-- Verify Phase 3 tables
SELECT column_name, data_type
FROM `nba_analytics.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'player_game_summary'
  AND column_name LIKE 'source_%';
```

---

### Step 5: Update Documentation

Update these docs to reference new schema:
- [ ] `docs/reference/phase2-processor-hash-strategy.md` - Link to schema files
- [ ] `docs/data/schema-change-management-process.md` - Document this migration
- [ ] `docs/implementation/dependency-tracking-with-smart-idempotency.md` - Create new doc
- [ ] Update wiki with integrated approach

---

## Hash Logic Implementation Timeline

### Week 1: Critical Priority (5 processors)
**After schema changes complete, implement hash logic for:**

1. `nbac_injury_report_processor.py`
2. `bdl_injuries_processor.py`
3. `odds_api_props_processor.py`
4. `bettingpros_player_props_processor.py`
5. `odds_game_lines_processor.py`

**Steps:**
1. Design and implement `SmartIdempotencyMixin`
2. Add `HASH_FIELDS` class attribute to each processor
3. Integrate mixin into processor classes
4. Test locally with realistic data
5. Deploy to production
6. Monitor for 1 week

---

### Week 2: Medium Priority (7 processors)

After Week 1 validation, implement hash logic for:

1. `nbac_play_by_play_processor.py`
2. `nbac_player_boxscore_processor.py`
3. `nbac_team_boxscore_processor.py`
4. `nbac_gamebook_processor.py`
5. `bdl_boxscores_processor.py`
6. `espn_scoreboard_processor.py`
7. `espn_boxscore_processor.py`

---

### Week 3+: Low Priority (8 processors)

After Week 2 validation, implement hash logic for remaining processors.

---

## Rollback Plan

If issues arise, columns can be dropped:

```sql
-- Phase 2 rollback (example)
ALTER TABLE `nba_raw.nbac_injury_report` DROP COLUMN data_hash;

-- Phase 3 rollback (example - drop all source tracking for one dependency)
ALTER TABLE `nba_analytics.player_game_summary`
  DROP COLUMN source_nbac_gamebook_data_hash,
  DROP COLUMN source_nbac_gamebook_last_updated,
  DROP COLUMN source_nbac_gamebook_rows_found,
  DROP COLUMN source_nbac_gamebook_completeness_pct;
```

**Note:** Drop columns only if absolutely necessary. NULL values are safe and expected during gradual rollout.

---

## File Structure Summary

```
schemas/bigquery/
├── raw/
│   ├── nbac_injury_report_tables.sql          # UPDATE: Add data_hash
│   ├── nbac_play_by_play_tables.sql           # UPDATE: Add data_hash
│   ├── nbac_player_boxscore_tables.sql        # UPDATE: Add data_hash
│   ├── nbac_team_boxscore_tables.sql          # UPDATE: Add data_hash
│   ├── nbac_gamebook_tables.sql               # UPDATE: Add data_hash
│   ├── nbac_schedule_tables.sql               # UPDATE: Add data_hash
│   ├── nbac_player_list_tables.sql            # UPDATE: Add data_hash
│   ├── nbac_player_movement_tables.sql        # UPDATE: Add data_hash
│   ├── nbac_referee_tables.sql                # UPDATE: Add data_hash
│   ├── nbac_scoreboard_v2_tables.sql          # UPDATE: Add data_hash
│   ├── odds_api_props_tables.sql              # UPDATE: Add data_hash
│   ├── odds_game_lines_tables.sql             # UPDATE: Add data_hash
│   ├── bettingpros_player_props_tables.sql    # UPDATE: Add data_hash
│   ├── balldontlie_tables.sql                 # UPDATE: Add data_hash (4 tables)
│   ├── espn_scoreboard_tables.sql             # UPDATE: Add data_hash
│   ├── espn_boxscore_tables.sql               # UPDATE: Add data_hash
│   ├── espn_team_roster_tables.sql            # UPDATE: Add data_hash
│   ├── bigdataball_pbp_tables.sql             # UPDATE: Add data_hash
│   └── basketball_reference_tables.sql        # UPDATE: Add data_hash
├── analytics/
│   ├── player_game_summary_tables.sql         # UPDATE: Add source tracking
│   ├── team_defense_game_summary_tables.sql   # UPDATE: Add source tracking
│   ├── team_offense_game_summary_tables.sql   # UPDATE: Add source tracking
│   ├── upcoming_player_game_context_tables.sql # UPDATE: Add source tracking
│   └── upcoming_team_game_context_tables.sql  # UPDATE: Add source tracking
├── precompute/
│   ├── player_composite_factors_tables.sql    # UPDATE: Add source tracking
│   ├── player_shot_zone_analysis_tables.sql   # UPDATE: Add source tracking
│   ├── team_defense_zone_analysis_tables.sql  # UPDATE: Add source tracking
│   ├── player_daily_cache_tables.sql          # UPDATE: Add source tracking
│   └── ml_feature_store_tables.sql            # UPDATE: Add source tracking
└── predictions/
    └── prediction_worker_runs_tables.sql      # UPDATE: TBD based on Phase 4

monitoring/schemas/migrations/
├── add_data_hash_to_nbac_injury_report.sql                # CREATE NEW
├── add_data_hash_to_nbac_play_by_play.sql                 # CREATE NEW
├── add_data_hash_to_nbac_player_boxscores.sql             # CREATE NEW
├── ... (22 Phase 2 migrations total)                      # CREATE NEW
├── add_source_tracking_to_player_game_summary.sql         # CREATE NEW
├── ... (5 Phase 3 migrations)                             # CREATE NEW
├── ... (5 Phase 4 migrations)                             # CREATE NEW
└── add_source_hash_to_prediction_worker_runs.sql          # CREATE NEW

docs/implementation/
├── 01-phase2-idempotency-discussion-summary.md            # EXISTS
├── 02-schema-update-plan-smart-idempotency.md            # THIS FILE
└── dependency-tracking-with-smart-idempotency.md         # CREATE NEW
```

---

## Checklist

### Phase 2 Schema Updates (ALL 22 Tables)

**Critical Priority:**
- [ ] Update nbac_injury_report_tables.sql CREATE TABLE
- [ ] Create add_data_hash_to_nbac_injury_report.sql migration
- [ ] Update balldontlie_tables.sql (bdl_injuries)
- [ ] Create migration for bdl_injuries
- [ ] Update odds_api_props_tables.sql
- [ ] Create migration for odds_api_props
- [ ] Update bettingpros_player_props_tables.sql
- [ ] Create migration for bettingpros_props
- [ ] Update odds_game_lines_tables.sql
- [ ] Create migration for odds_game_lines

**Medium Priority:**
- [ ] Update nbac_play_by_play_tables.sql
- [ ] Create migration for nbac_play_by_play
- [ ] Update nbac_player_boxscore_tables.sql
- [ ] Create migration for nbac_player_boxscores
- [ ] Update nbac_team_boxscore_tables.sql
- [ ] Create migration for nbac_team_boxscore
- [ ] Update nbac_gamebook_tables.sql
- [ ] Create migration for nbac_gamebook
- [ ] Update balldontlie_tables.sql (bdl_boxscores)
- [ ] Create migration for bdl_boxscores
- [ ] Update espn_scoreboard_tables.sql
- [ ] Create migration for espn_scoreboard
- [ ] Update espn_boxscore_tables.sql
- [ ] Create migration for espn_boxscores

**Low Priority:**
- [ ] Update nbac_schedule_tables.sql
- [ ] Create migration for nbac_schedule
- [ ] Update nbac_player_list_tables.sql
- [ ] Create migration for nbac_player_list
- [ ] Update nbac_player_movement_tables.sql
- [ ] Create migration for nbac_player_movement
- [ ] Update nbac_referee_tables.sql
- [ ] Create migration for nbac_referee
- [ ] Update balldontlie_tables.sql (bdl_active_players)
- [ ] Create migration for bdl_active_players
- [ ] Update balldontlie_tables.sql (bdl_standings)
- [ ] Create migration for bdl_standings
- [ ] Update espn_team_roster_tables.sql
- [ ] Create migration for espn_team_rosters
- [ ] Update bigdataball_pbp_tables.sql
- [ ] Create migration for bigdataball_pbp
- [ ] Update basketball_reference_tables.sql
- [ ] Create migration for br_rosters

**Potentially Inactive:**
- [ ] Update nbac_scoreboard_v2_tables.sql (if processor active)
- [ ] Create migration for nbac_scoreboard_v2 (if processor active)

---

### Phase 3 Schema Updates (5 Analytics Tables)
- [ ] Update player_game_summary_tables.sql
- [ ] Create migration for player_game_summary
- [ ] Update team_defense_game_summary_tables.sql
- [ ] Create migration for team_defense_summary
- [ ] Update team_offense_game_summary_tables.sql
- [ ] Create migration for team_offense_summary
- [ ] Update upcoming_player_game_context_tables.sql
- [ ] Create migration for upcoming_player_context
- [ ] Update upcoming_team_game_context_tables.sql
- [ ] Create migration for upcoming_team_context

---

### Phase 4 Schema Updates (5 Precompute Tables)
- [ ] Update player_composite_factors_tables.sql
- [ ] Create migration for player_composite_factors
- [ ] Update player_shot_zone_analysis_tables.sql
- [ ] Create migration for player_shot_zone_analysis
- [ ] Update team_defense_zone_analysis_tables.sql
- [ ] Create migration for team_defense_zone_analysis
- [ ] Update player_daily_cache_tables.sql
- [ ] Create migration for player_daily_cache
- [ ] Update ml_feature_store_tables.sql
- [ ] Create migration for ml_feature_store

---

### Phase 5 Schema Updates (1 Predictions Table)
- [ ] Update prediction_worker_runs_tables.sql
- [ ] Create migration for prediction_worker_runs

---

### Run Migrations
- [ ] Run all 22 Phase 2 migrations
- [ ] Verify Phase 2 columns added successfully
- [ ] Run all 5 Phase 3 migrations
- [ ] Verify Phase 3 columns added successfully
- [ ] Run all 5 Phase 4 migrations
- [ ] Verify Phase 4 columns added successfully
- [ ] Run Phase 5 migration
- [ ] Verify Phase 5 columns added successfully

---

### Hash Logic Implementation (After Schema Changes)
- [ ] Design SmartIdempotencyMixin
- [ ] Implement mixin in processor_base.py
- [ ] Week 1: Apply to 5 critical processors
- [ ] Week 1: Test locally and deploy
- [ ] Week 2: Apply to 7 medium priority processors
- [ ] Week 2: Test and deploy
- [ ] Week 3+: Apply to 8 low priority processors
- [ ] Week 3+: Test and deploy

---

### Documentation
- [ ] Create dependency-tracking-with-smart-idempotency.md
- [ ] Update phase2-processor-hash-strategy.md
- [ ] Update schema-change-management-process.md
- [ ] Update wiki with integrated approach

---

## Summary

**Schema Updates:** Add `data_hash` to ALL 22 Phase 2 tables immediately (columns initially NULL)

**Hash Logic Implementation:** Gradual by priority over 3+ weeks

**Dependency Tracking:** See `docs/implementation/04-dependency-checking-strategy.md`
- Point-in-time dependencies: 4 fields per source (includes `data_hash`), NO composite hash
- Historical range dependencies: Timestamp-based checks in code, NO hash fields

**Migrations (Minimum):**
- 22 Phase 2 (add data_hash)
- 5 Phase 3 (add source tracking - 4 fields per dependency)
- Phase 4/5: TBD based on dependency types
- **Total: At least 27 migrations**

**Timeline:**
- Schema updates: Phase 2 + Phase 3 immediately (1-2 days)
- Hash logic Week 1: 5 critical processors
- Hash logic Week 2: 7 medium priority processors
- Hash logic Week 3+: 8 low priority processors
- Phase 4/5 schemas: Determine during processor design

**Benefits:**
- Complete cascade prevention across all phases
- Future-proof schema (all tables ready for hash checking)
- Simpler approach (no composite hash complexity)
- Gradual rollout minimizes risk
- Easy to validate at each step

---

**Last Updated:** 2025-11-21 12:15 PM PST
**Status:** Ready for implementation - composite hash removed per user decision
