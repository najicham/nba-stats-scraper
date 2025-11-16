# Phase 2→3 Mapping: Team Defense Game Summary

**File:** `docs/data-flow/04-phase2-to-phase3-team-defense.md`
**Created:** 2025-11-02
**Last Updated:** 2025-11-15
**Purpose:** Data mapping from Phase 2 raw tables to Phase 3 team defensive analytics
**Audience:** Engineers implementing Phase 3 processors and debugging data transformations
**Status:** ⚠️ Reference - Implementation complete, deployment blocked

---

## 🚧 Current Deployment Status

**Implementation:** ✅ **COMPLETE**
- Phase 3 Processor: `data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py` (740 lines, 39 tests)
- Analytics Table: `nba_analytics.team_defense_game_summary` (created, 54 fields)

**Blocker:** ❌ **Phase 2 critical table does not exist**
- `nba_raw.nbac_team_boxscore` has NOT been populated yet (same as team_offense)
- 2 of 3 Phase 2 dependencies ARE operational:
  - ✅ `nba_raw.nbac_gamebook_player_stats` - EXISTS
  - ✅ `nba_raw.bdl_player_boxscores` - EXISTS
  - ❌ `nba_raw.nbac_team_boxscore` - MISSING (critical blocker)
- Phase 3 processor cannot run until Phase 2 team_boxscore is created

**To Unblock:**
1. Deploy Phase 2 `nbac_team_boxscore_processor` to Cloud Run
2. Run backfill to populate `nba_raw.nbac_team_boxscore`
3. Verify v2.0 schema (is_home field, dual game IDs)
4. Then Phase 3 processor can be scheduled

**See:** `docs/processors/` for deployment procedures

---

## 📋 Executive Summary

This processor calculates team defensive metrics by reading Phase 2 raw data and aggregating opponent offensive performance with defensive actions.

**Processor:** `team_defense_game_summary_processor.py` v2.0
**Output Table:** `nba_analytics.team_defense_game_summary`
**Processing Strategy:** MERGE_UPDATE
**Architecture:** Phase 2 → Phase 3 (CORRECTED from v1.0)

**Key Architecture Change:**
- ❌ v1.0: Read Phase 3 tables (team_offense_game_summary, player_game_summary) - **architectural violation**
- ✅ v2.0: Read Phase 2 raw tables (nbac_team_boxscore, nbac_gamebook_player_stats, bdl_player_boxscores) - **correct!**

**Multi-Source Fallback Strategy:**
1. Primary: `nbac_gamebook_player_stats` (best quality, name resolution)
2. Fallback #1: `bdl_player_boxscores` (good quality, fast updates)
3. Fallback #2: `nbac_player_boxscores` (last resort)

---

## 🗂️ Raw Sources (Phase 2)

### Primary Sources

| Table | Type | Purpose | Criticality |
|-------|------|---------|-------------|
| nba_raw.nbac_team_boxscore | Phase 2 Raw | Opponent team offensive stats | 🔴 CRITICAL |
| nba_raw.nbac_gamebook_player_stats | Phase 2 Raw | Individual defensive actions | 🟡 PRIMARY |
| nba_raw.bdl_player_boxscores | Phase 2 Raw | Individual defensive actions (fallback) | 🟢 FALLBACK |
| nba_raw.nbac_player_boxscores | Phase 2 Raw | Individual defensive actions (last resort) | 🟢 FALLBACK #2 |

### Source Selection Priority

```
1. nbac_team_boxscore (ALWAYS REQUIRED)
   ↓
2. Try nbac_gamebook_player_stats (PRIMARY - best quality)
   ↓
3. If incomplete → Try bdl_player_boxscores (FALLBACK #1)
   ↓
4. If still incomplete → Try nbac_player_boxscores (FALLBACK #2)
```

---

## 🔍 Known Data Quality Issues

### Phase 2 Data Characteristics

**nbac_team_boxscore:**
- ✅ Generally clean and complete
- ✅ Official NBA.com data
- ⚠️ Occasionally missing for recent games (processing delay)
- ⚠️ Plus/minus can be NULL in rare cases

**nbac_gamebook_player_stats:**
- ✅ Best quality for defensive actions
- ✅ Has name resolution built-in
- ⚠️ May lag by 2-4 hours after games
- ⚠️ Inactive players need filtering (`player_status != 'active'`)
- ⚠️ ~5% of players may have NULL steals/blocks

**bdl_player_boxscores:**
- ✅ Good quality, fast updates
- ⚠️ No `player_status` field (all players included)
- ⚠️ Inconsistent `player_lookup` values
- ⚠️ Team abbreviations may differ from gamebook

---

## 🔄 Data Flow

### High-Level Flow

```
Phase 2 Raw Data
    ↓
┌─────────────────────────────────────────┐
│ 1. Extract Opponent Offense             │
│    Source: nbac_team_boxscore          │
│    Logic: Perspective flip             │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ 2. Extract Defensive Actions            │
│    Source: gamebook → BDL → nbac       │
│    Logic: Multi-source fallback        │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ 3. Merge Opponent Offense + Defense     │
│    Logic: LEFT JOIN on game_id + team  │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ 4. Calculate Analytics                   │
│    - Defensive rating                   │
│    - Data quality tier                  │
│    - Source tracking                    │
└─────────────────────────────────────────┘
    ↓
Phase 3 Analytics
nba_analytics.team_defense_game_summary
```

---

## 🗺️ Detailed Field Mappings

### Source 1: nbac_team_boxscore → Opponent Offense

**Strategy:** For each game, join teams in same game to get opponent's stats (perspective flip).

```sql
-- Self-join to get opponent
SELECT
    t1.team_abbr as defending_team_abbr,    -- This team (defense)
    t2.team_abbr as opponent_team_abbr,     -- Other team (offense)
    t2.points as points_allowed,            -- Opponent scored
    t2.turnovers as turnovers_forced        -- Defense forced
FROM nba_raw.nbac_team_boxscore t1
INNER JOIN nba_raw.nbac_team_boxscore t2
    ON t1.game_id = t2.game_id
    AND t1.team_abbr != t2.team_abbr  -- Get the OTHER team
```

**Field Mapping:**

| Raw Field (Opponent t2) | Analytics Field | Transformation | Notes |
|------------------------|-----------------|----------------|-------|
| game_id | game_id | Direct copy | Standardized format |
| game_date | game_date | Direct copy | DATE type |
| season_year | season_year | Direct copy | INT64 |
| t1.team_abbr | defending_team_abbr | Defense perspective | Who played defense |
| t2.team_abbr | opponent_team_abbr | Offense perspective | Who they defended |
| t2.points | points_allowed | Direct copy | Opponent's points |
| t2.fg_made | opp_fg_makes | Direct copy | FG made by opponent |
| t2.fg_attempted | opp_fg_attempts | Direct copy | FG attempted |
| t2.three_pt_made | opp_three_pt_makes | Direct copy | 3PT made |
| t2.three_pt_attempted | opp_three_pt_attempts | Direct copy | 3PT attempted |
| t2.ft_made | opp_ft_makes | Direct copy | FT made |
| t2.ft_attempted | opp_ft_attempts | Direct copy | FT attempted |
| t2.total_rebounds | opp_rebounds | Direct copy | Total rebounds |
| t2.offensive_rebounds | opp_offensive_rebounds | Direct copy | For second chance points |
| t2.assists | opp_assists | Direct copy | Assists allowed |
| t2.turnovers | turnovers_forced | Perspective flip | Defense forced these |
| t1.personal_fouls | fouls_committed | Direct copy (t1) | Defense committed |
| t1.is_home | home_game | Direct copy (t1) | Defense perspective |
| t1.plus_minus > 0 | win_flag | Boolean conversion | Did defense win? |
| t1.plus_minus | margin_of_victory | Direct copy (t1) | Defense margin |

**Calculated Fields:**

```sql
-- Defensive Rating (points allowed per 100 possessions)
ROUND(
    (t2.points / NULLIF(
        t2.fg_attempted + (0.44 * t2.ft_attempted) - t2.offensive_rebounds + t2.turnovers,
        0
    )) * 100,
    2
) as defensive_rating

-- Opponent Pace
ROUND(
    (t2.fg_attempted + (0.44 * t2.ft_attempted) - t2.offensive_rebounds + t2.turnovers),
    1
) as opponent_pace

-- Opponent True Shooting %
ROUND(
    t2.points / NULLIF(2.0 * (t2.fg_attempted + 0.44 * t2.ft_attempted), 0),
    3
) as opponent_ts_pct
```

### Source 2: Player Boxscores → Defensive Actions

**Multi-Source Strategy:**

```python
# Priority 1: Gamebook (best quality)
SELECT
    game_id,
    team_abbr as defending_team_abbr,
    SUM(CASE WHEN player_status = 'active' THEN steals ELSE 0 END) as steals,
    SUM(CASE WHEN player_status = 'active' THEN blocks ELSE 0 END) as blocks_total,
    SUM(CASE WHEN player_status = 'active' THEN defensive_rebounds ELSE 0 END) as defensive_rebounds
FROM nba_raw.nbac_gamebook_player_stats
WHERE player_status = 'active'  # Only active players
GROUP BY game_id, team_abbr

# Priority 2: BDL fallback (if gamebook incomplete)
SELECT
    game_id,
    team_abbr as defending_team_abbr,
    SUM(steals) as steals,
    SUM(blocks) as blocks_total,
    SUM(defensive_rebounds) as defensive_rebounds
FROM nba_raw.bdl_player_boxscores
GROUP BY game_id, team_abbr
```

**Field Mapping:**

| Raw Field (Player) | Analytics Field | Aggregation | Notes |
|-------------------|-----------------|-------------|-------|
| steals | steals | SUM(steals) | Team total steals |
| blocks | blocks_total | SUM(blocks) | Team total blocks |
| defensive_rebounds | defensive_rebounds | SUM(defensive_rebounds) | Team defensive rebounds |

**Data Quality Filters:**

```sql
# Gamebook: Only active players
WHERE player_status = 'active'

# BDL: Ensure minimum players
HAVING COUNT(*) >= 5  # At least 5 players

# Gamebook: Ensure reasonable data
HAVING COUNT(CASE WHEN player_status = 'active' THEN 1 END) >= 5
```

---

## 🔧 Cleaning Logic

### Issue 1: Missing Opponent Offensive Stats

**Raw Issue:**
```sql
-- nbac_team_boxscore missing for some games
SELECT COUNT(*) FROM nba_raw.nbac_team_boxscore
WHERE game_date = '2025-11-01'
-- Returns 0 (game not processed yet)
```

**Cleaning Logic:**
```python
if opponent_offense_df.empty:
    logger.error("No opponent offensive data found")
    raise ValueError("Missing opponent offensive data from nbac_team_boxscore")
```

**Validation:**
- CRITICAL failure - Cannot calculate defense without opponent offense
- Send notification
- Do NOT proceed

### Issue 2: Incomplete Defensive Actions

**Raw Issue:**
```python
# Gamebook has data for some teams but not all
gamebook_df: 18 teams (2 missing from 10-game day)
```

**Cleaning Logic:**
```python
all_games = get_all_game_ids(start_date, end_date)
games_with_gamebook = set(gamebook_df['game_id'].unique())
missing_games = all_games - games_with_gamebook

if missing_games:
    logger.warning(f"Gamebook missing {len(missing_games)} games")
    # Fall back to BDL
    bdl_df = try_bdl_defensive_actions(start_date, end_date, missing_games)
    combined_df = pd.concat([gamebook_df, bdl_df])
```

**Validation:**
- Non-critical - Can proceed without defensive actions
- Use fallback sources
- Track which source was used
- Set `data_quality_tier` accordingly

### Issue 3: NULL Defensive Actions

**Raw Issue:**
```python
# Some players have NULL steals/blocks
player_stats: {steals: None, blocks: None}
```

**Cleaning Logic:**
```sql
# In aggregation query
SUM(CASE WHEN player_status = 'active' THEN COALESCE(steals, 0) ELSE 0 END) as steals

# In merge logic
merged_df['steals'] = merged_df['steals'].fillna(0)
merged_df['blocks_total'] = merged_df['blocks_total'].fillna(0)
```

**Validation:**
- Convert NULL to 0
- Track `data_quality_tier`
- Log as data quality issue if > 10% NULL

### Issue 4: Player Status Filtering

**Raw Issue:**
```sql
-- Gamebook includes inactive players (DNP, injuries)
SELECT * FROM nba_raw.nbac_gamebook_player_stats
WHERE game_id = '...'
-- Returns 17 rows (12 active, 5 inactive)
```

**Cleaning Logic:**
```sql
-- Only aggregate active players
SUM(CASE WHEN player_status = 'active' THEN steals ELSE 0 END) as steals
```

**Validation:**
- Filter to `player_status = 'active'` only
- Count active players to ensure >= 5
- Reject if < 5 active players (bad data)

---

## 📊 Field Mappings to Analytics

### Complete Mapping Table

| Analytics Field | Source | Calculation | NULL Handling | Notes |
|----------------|--------|-------------|---------------|-------|
| game_id | nbac_team_boxscore | Direct | NEVER NULL | Primary key |
| game_date | nbac_team_boxscore | Direct | NEVER NULL | Partition key |
| defending_team_abbr | nbac_team_boxscore (t1) | Direct | NEVER NULL | Defense perspective |
| opponent_team_abbr | nbac_team_boxscore (t2) | Direct | NEVER NULL | Offense perspective |
| season_year | nbac_team_boxscore | Direct | NEVER NULL | INT64 |
| points_allowed | nbac_team_boxscore (t2.points) | Direct | Set to NULL if missing | Opponent scored |
| opp_fg_attempts | nbac_team_boxscore (t2) | Direct | Set to NULL | FG attempted |
| opp_fg_makes | nbac_team_boxscore (t2) | Direct | Set to NULL | FG made |
| opp_three_pt_attempts | nbac_team_boxscore (t2) | Direct | Set to NULL | 3PT attempted |
| opp_three_pt_makes | nbac_team_boxscore (t2) | Direct | Set to NULL | 3PT made |
| opp_ft_attempts | nbac_team_boxscore (t2) | Direct | Set to NULL | FT attempted |
| opp_ft_makes | nbac_team_boxscore (t2) | Direct | Set to NULL | FT made |
| opp_rebounds | nbac_team_boxscore (t2) | Direct | Set to NULL | Total rebounds |
| opp_assists | nbac_team_boxscore (t2) | Direct | Set to NULL | Assists allowed |
| turnovers_forced | nbac_team_boxscore (t2) | Direct | Set to NULL | Defense forced |
| fouls_committed | nbac_team_boxscore (t1) | Direct | Set to NULL | Defense committed |
| steals | Player boxscores | SUM(steals) | Set to 0 if NULL | Team total |
| defensive_rebounds | Player boxscores | SUM(def_reb) | Set to 0 if NULL | Team total |
| defensive_rating | Calculated | Formula | Set to NULL if bad | Points/100 poss |
| opponent_pace | Calculated | Formula | Set to NULL if bad | Possessions |
| opponent_ts_pct | Calculated | Formula | Set to NULL if bad | True shooting % |
| home_game | nbac_team_boxscore (t1) | Direct | Default FALSE | Boolean |
| win_flag | nbac_team_boxscore (t1) | plus_minus > 0 | Set to NULL if tie | Boolean |
| margin_of_victory | nbac_team_boxscore (t1) | Direct | Set to NULL | Can be negative |
| overtime_periods | Derived | From minutes | Default 0 | TODO |

### Deferred Fields (Phase 2 Enhancement Needed)

| Field | Reason Deferred | Future Source | Status |
|-------|----------------|---------------|--------|
| opp_paint_attempts | Need shot location | Play-by-play processor | 🚧 Not built |
| opp_paint_makes | Need shot location | Play-by-play processor | 🚧 Not built |
| opp_mid_range_attempts | Need shot location | Play-by-play processor | 🚧 Not built |
| opp_mid_range_makes | Need shot location | Play-by-play processor | 🚧 Not built |
| points_in_paint_allowed | Need shot location | Play-by-play processor | 🚧 Not built |
| mid_range_points_allowed | Need shot location | Play-by-play processor | 🚧 Not built |
| three_pt_points_allowed | Can calculate now | opp_three_pt_makes * 3 | ✅ Implemented |
| second_chance_points_allowed | Need play-by-play | Play-by-play processor | 🚧 Not built |
| fast_break_points_allowed | Need play-by-play | Play-by-play processor | 🚧 Not built |
| blocks_paint | Need shot location | Play-by-play processor | 🚧 Not built |
| blocks_mid_range | Need shot location | Play-by-play processor | 🚧 Not built |
| blocks_three_pt | Need shot location | Play-by-play processor | 🚧 Not built |
| players_inactive | Need roster data | Injury/roster scraper | 🚧 Not built |
| starters_inactive | Need roster data | Injury/roster scraper | 🚧 Not built |
| referee_crew_id | Need referee data | Referee scraper | 🚧 Not built |

---

## 🎯 Validation Rules

### Critical Validations (Must Pass)

```python
# 1. Opponent offense data exists
if opponent_offense_df.empty:
    raise ValueError("Missing opponent offensive data")

# 2. Points in reasonable range
if points_allowed < 50 or points_allowed > 200:
    log_quality_issue('unrealistic_points_allowed', 'HIGH', game_id)

# 3. Defensive rating in reasonable range
if defensive_rating < 80 or defensive_rating > 140:
    log_quality_issue('unrealistic_defensive_rating', 'MEDIUM', game_id)

# 4. Core identifiers present
if pd.isna(game_id) or pd.isna(defending_team_abbr):
    raise ValueError("Missing core identifiers")
```

### Data Quality Validations (Warning Level)

```python
# 1. Defensive actions missing
if steals is None and blocks_total is None:
    data_quality_tier = 'low'
    processed_with_issues = True

# 2. Unrealistic steals
if steals > 30:  # NBA record is 27
    log_quality_issue('unrealistic_steals', 'LOW', game_id)

# 3. Missing defensive actions source
if defensive_actions_source == 'none':
    logger.warning("No defensive actions data available")
```

---

## 🏷️ Data Quality Tracking

### Quality Tier Assignment

```python
def determine_quality_tier(row):
    has_defensive_actions = (
        pd.notna(row.get('steals')) or
        pd.notna(row.get('blocks_total')) or
        pd.notna(row.get('defensive_rebounds'))
    )

    defensive_actions_source = row.get('defensive_actions_source', 'none')

    if has_defensive_actions and defensive_actions_source == 'nbac_gamebook':
        return 'high'     # Best: gamebook with name resolution
    elif has_defensive_actions:
        return 'medium'   # Good: BDL or nbac fallback
    else:
        return 'low'      # Poor: opponent stats only, no defensive actions
```

### Primary Source Used

```python
def determine_primary_source(row):
    defensive_actions_source = row.get('defensive_actions_source', 'none')

    if defensive_actions_source != 'none':
        return f"nbac_team_boxscore+{defensive_actions_source}"
    else:
        return "nbac_team_boxscore"
```

**Examples:**
- `"nbac_team_boxscore+nbac_gamebook"` - Opponent stats + gamebook defensive actions
- `"nbac_team_boxscore+bdl_player_boxscores"` - Opponent stats + BDL fallback
- `"nbac_team_boxscore"` - Opponent stats only (no defensive actions)

### Processed With Issues Flag

```python
processed_with_issues = not has_defensive_actions
```

**Set to TRUE if:**
- No defensive actions data found
- Used only opponent offensive stats
- Missing steals, blocks, and defensive rebounds

---

## 📈 Output Schema

**Table:** `nba_analytics.team_defense_game_summary`
**Total Fields:** 54

**Field Categories:**
- Core identifiers: 5 fields
- Defensive stats: 11 fields
- Shot zones: 9 fields (mostly NULL - deferred)
- Defensive actions: 5 fields
- Advanced metrics: 3 fields
- Game context: 4 fields
- Team situation: 2 fields (NULL - future)
- Referee: 1 field (NULL - future)
- Data quality: 3 fields
- Dependency tracking: 9 fields (v4.0 spec)
- Processing metadata: 2 fields

**Complete schema:** See implementation in `data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py`

---

## 🚀 Processing Workflow

### Step-by-Step Execution

```python
# 1. Check dependencies (base class)
dep_check = self.check_dependencies(start_date, end_date)

if not dep_check['all_critical_present']:
    raise DependencyError("Missing nbac_team_boxscore")

# 2. Extract opponent offense (perspective flip)
opponent_offense_df = self._extract_opponent_offense(start_date, end_date)
# Returns: game_id, defending_team_abbr, points_allowed, etc.

# 3. Extract defensive actions (multi-source)
defensive_actions_df = self._extract_defensive_actions(start_date, end_date)
# Priority: gamebook → BDL → nbac_player_boxscores
# Returns: game_id, defending_team_abbr, steals, blocks, data_source

# 4. Merge opponent offense + defensive actions
merged_df = self._merge_defense_data(opponent_offense_df, defensive_actions_df)
# LEFT JOIN on (game_id, defending_team_abbr)
# Fill missing defensive actions with 0

# 5. Calculate analytics
for each row in merged_df:
    - Determine data_quality_tier
    - Determine primary_source_used
    - Set processed_with_issues flag
    - Add dependency tracking fields
    - Convert data types
    - Handle NULLs

# 6. Save to BigQuery
# MERGE strategy: Delete existing rows for date range, then INSERT new rows
```

---

## 📊 Expected Data Distribution

### Typical Game Day (10 games)

| Metric | Expected Value | Notes |
|--------|---------------|-------|
| Total Records | 20 | 10 games × 2 teams |
| High Quality | 17-18 (85-90%) | Has gamebook defensive actions |
| Medium Quality | 1-2 (5-10%) | Used BDL fallback |
| Low Quality | 0-1 (0-5%) | No defensive actions |
| Avg Points Allowed | 105-115 | NBA average |
| Avg Defensive Rating | 100-115 | Per 100 possessions |
| Avg Steals | 7-8 | Team average |
| Avg Turnovers Forced | 12-14 | Team average |

---

## 🎯 Success Criteria

### Data Extraction Success

- ✅ All 20 team-game records found (10 games)
- ✅ 100% have opponent offensive stats
- ✅ 85%+ have gamebook defensive actions
- ✅ 95%+ have defensive actions (any source)
- ✅ All dependency tracking fields populated

### Data Quality Success

- ✅ 85%+ records are "high" quality
- ✅ < 5% records are "low" quality
- ✅ All points_allowed in 50-200 range
- ✅ All defensive_rating in 80-140 range
- ✅ No processing errors (0% error rate)

### Processing Success

- ✅ Runs in < 30 seconds per game day
- ✅ Saves successfully to BigQuery
- ✅ Phase 4 processors can read data
- ✅ No circular dependency errors

---

## 🔍 Change Log

### v2.0 (November 2, 2025) - Phase 2 Architecture

**BREAKING:** Changed from Phase 3 → Phase 3 to Phase 2 → Phase 3

**Added:**
- Multi-source fallback logic (gamebook → BDL → nbac)
- 9 dependency tracking fields (Phase 2 sources)
- Data quality tier assignment
- Primary source tracking

**Removed:**
- Dependency on team_offense_game_summary (Phase 3)
- Dependency on player_game_summary (Phase 3)

### v1.0 (Original) - Phase 3 Circular Dependency

**Issues:**
- ❌ Read from Phase 3 tables (architectural violation)
- ❌ No multi-source fallback
- ❌ Single data source (team_offense_game_summary)

---

## ✅ Completion Checklist

- [x] Raw sources identified (Phase 2 only)
- [x] Data quality issues documented
- [x] Cleaning logic defined
- [x] Field mappings complete
- [x] Validation rules defined
- [x] Quality tracking implemented
- [x] Dependency tracking v4.0 compliant
- [x] Multi-source fallback logic
- [x] Deferred fields documented
- [x] Success criteria defined
- [ ] **Phase 2 table deployed** ⬅️ **Current blocker**

---

**Document Status:** ✅ Complete - Implementation ready, blocked on Phase 2 deployment
**Architecture:** Phase 2 → Phase 3 (Correct - v2.0)
**Version:** 2.0
**Last Updated:** 2025-11-15
**Next Review:** After Phase 2 deployment
