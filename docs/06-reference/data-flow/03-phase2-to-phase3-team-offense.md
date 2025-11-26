# Phase 2→3 Mapping: Team Offense Game Summary

**File:** `docs/data-flow/03-phase2-to-phase3-team-offense.md`
**Created:** 2025-01-15
**Last Updated:** 2025-11-15
**Purpose:** Data mapping from Phase 2 raw tables to Phase 3 team offensive analytics
**Audience:** Engineers implementing Phase 3 processors and debugging data transformations
**Status:** ⚠️ Reference - Implementation complete, deployment blocked

---

## 🚧 Current Deployment Status

**Implementation:** ✅ **COMPLETE**
- Phase 2 Processor: `data_processors/raw/nbacom/nbac_team_boxscore_processor.py` (implemented)
- Phase 3 Processor: `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py` (692 lines, 97 tests)
- Analytics Table: `nba_analytics.team_offense_game_summary` (created, 47 fields)

**Blocker:** ❌ **Phase 2 raw table does not exist**
- `nba_raw.nbac_team_boxscore` has NOT been populated yet
- Phase 2 processor code exists but hasn't been run/deployed
- Phase 3 processor cannot run until Phase 2 table is created

**To Unblock:**
1. Deploy Phase 2 processor to Cloud Run
2. Run backfill to populate `nba_raw.nbac_team_boxscore`
3. Verify v2.0 schema (is_home field, dual game IDs)
4. Then Phase 3 processor can be scheduled

**See:** `docs/processors/` for deployment procedures

---

## 📊 Executive Summary

This Phase 3 processor transforms raw team box score statistics into comprehensive team offensive analytics. It combines official NBA.com team statistics with shot zone data from play-by-play feeds to provide complete offensive performance profiles.

**Processor:** `team_offense_game_summary_processor.py`
**Output Table:** `nba_analytics.team_offense_game_summary`
**Processing Strategy:** MERGE_UPDATE
**Schema Version:** v2.0 (includes is_home field and dual game IDs)

**v2.0 Schema Improvements:**
- ✅ `is_home` boolean field (no schedule join needed!)
- ✅ Dual game ID system (game_id standardized + nba_game_id for NBA.com)
- ✅ Simplified self-join logic
- ✅ Cleaner validation queries

**Key Complexity:**
- Self-join for opponent context (simplified in v2.0)
- Advanced metric calculations (possessions, pace, offensive rating)
- OT period parsing from time strings
- Optional shot zone extraction from play-by-play

**Data Quality:** High - NBA.com team boxscore is authoritative and reliable

---

## 🗂️ Raw Sources (Phase 2)

### Source 1: NBA.com Team Boxscore (PRIMARY - CRITICAL)

**Table:** `nba_raw.nbac_team_boxscore`
**Status:** ❌ Not yet created (blocker)
**Update Frequency:** Post-game (within minutes of final)
**Dependency:** CRITICAL - processor cannot run without this

**Purpose:**
- All basic team offensive stats (FG, 3PT, FT, AST, REB, TO, PF)
- Game scores and plus/minus
- Minutes played (for OT detection)

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| game_id | STRING | System format: "20250115_LAL_PHI" |
| nba_game_id | STRING | NBA.com format: "0022400561" |
| game_date | DATE | Partition key |
| season_year | INT64 | 2024 for 2024-25 season |
| team_id | INT64 | NBA.com team ID |
| team_abbr | STRING | "PHI", "NYK", "LAL", etc. |
| team_name | STRING | "76ers", "Knicks", "Lakers" |
| is_home | BOOLEAN | v2.0: Explicit home/away flag! |
| minutes | STRING | "240:00" reg, "265:00" 1OT |
| fg_made | INT64 | Field goals made |
| fg_attempted | INT64 | Field goals attempted |
| fg_percentage | FLOAT64 | 0.0-1.0 |
| three_pt_made | INT64 | Three-pointers made |
| three_pt_attempted | INT64 | Three-pointers attempted |
| three_pt_percentage | FLOAT64 | 0.0-1.0 |
| ft_made | INT64 | Free throws made |
| ft_attempted | INT64 | Free throws attempted |
| ft_percentage | FLOAT64 | 0.0-1.0 |
| offensive_rebounds | INT64 | Offensive rebounds |
| defensive_rebounds | INT64 | Defensive rebounds |
| total_rebounds | INT64 | Total rebounds |
| assists | INT64 | Assists |
| steals | INT64 | Steals |
| blocks | INT64 | Blocks |
| turnovers | INT64 | Turnovers |
| personal_fouls | INT64 | Personal fouls |
| points | INT64 | Points scored |
| plus_minus | INT64 | Plus/minus |
| processed_at | TIMESTAMP | Source freshness tracking |

**Sample Raw Data (v2.0 format):**

```json
{
  "game_id": "20250115_LAL_PHI",
  "nba_game_id": "0022400561",
  "team_id": 1610612755,
  "team_name": "76ers",
  "team_abbr": "PHI",
  "team_city": "Philadelphia",
  "is_home": true,
  "minutes": "265:00",
  "fg_made": 46,
  "fg_attempted": 92,
  "fg_percentage": 0.5,
  "three_pt_made": 13,
  "three_pt_attempted": 35,
  "three_pt_percentage": 0.371,
  "ft_made": 14,
  "ft_attempted": 14,
  "ft_percentage": 1.0,
  "offensive_rebounds": 11,
  "defensive_rebounds": 24,
  "total_rebounds": 35,
  "assists": 27,
  "steals": 8,
  "blocks": 2,
  "turnovers": 12,
  "personal_fouls": 19,
  "points": 119,
  "plus_minus": -6
}
```

**Data Characteristics:**
- ✅ Clean data - all fields consistently populated
- ✅ Reliable - official NBA.com source
- ✅ Math validates: Points = (FG2 × 2) + (3PT × 3) + FT
- ✅ Rebounds validate: Total = Offensive + Defensive
- ✅ v2.0: is_home field eliminates need for schedule join!
- ✅ v2.0: Standardized game_id format for system-wide consistency
- ✅ v2.0: nba_game_id preserved for NBA.com API lookups
- ⚠️ Still requires self-join for opponent stats (simplified with is_home)

### Source 2: No Schedule Lookup Needed! ✅

**Status:** NOT REQUIRED (v2.0 improvement)

**Why Not Needed:** The v2.0 schema includes `is_home` boolean field directly in `nbac_team_boxscore`:
- `is_home = TRUE` → This team is the home team
- `is_home = FALSE` → This team is the away team

The `game_id` format also indicates home/away:
- Format: "YYYYMMDD_AWAY_HOME"
- Example: "20250115_LAL_PHI" → LAL is away, PHI is home

**Previous Limitation (v1.0):**
- Old schema only had NBA.com game ID ("0022400561")
- Required schedule join to determine home/away
- v2.0 eliminates this complexity!

**For Opponent Identification:**
- Still need self-join on `game_id` (to get other team's stats)
- But much simpler without schedule join

### Source 3: NBA.com Play-by-Play (ENHANCEMENT - OPTIONAL)

**Table:** `nba_raw.nbac_play_by_play`
**Status:** ✅ Active, newly implemented
**Update Frequency:** Post-game
**Dependency:** OPTIONAL - processor can run without this (shot zones will be NULL)

**Purpose:**
- Shot zone breakdowns (paint/mid-range/three)
- Points in paint
- Second chance points
- Assisted field goals

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| game_id | STRING | Links to team_boxscore |
| game_date | DATE | Partition key |
| player_1_team_abbr | STRING | Which team took the shot |
| event_type | STRING | "fieldgoal", "freethrow" |
| shot_made | BOOLEAN | TRUE/FALSE/NULL |
| shot_type | STRING | "2PT", "3PT", "FT" |
| shot_distance | FLOAT64 | Distance in feet |
| player_2_id | INT64 | Assisting player (if applicable) |

**Shot Zone Classification Logic:**

```python
def classify_shot_zone(shot_type: str, shot_distance: float) -> str:
    """
    Classify shot into paint/mid-range/three zones.

    Paint: 2PT shots ≤ 8 feet from basket
    Mid-Range: 2PT shots > 8 feet from basket
    Three: All 3PT shots
    """
    if shot_type == '3PT':
        return 'three'
    elif shot_type == '2PT':
        if shot_distance <= 8.0:
            return 'paint'
        else:
            return 'mid_range'
    return None  # Free throws not classified
```

**Handling Missing Play-by-Play:**

```python
if play_by_play_available:
    # Extract shot zones from play-by-play
    shot_zones_available = True
    shot_zones_source = 'nbac_pbp'  # or 'bigdataball'
else:
    # Set all shot zone fields to NULL
    shot_zones_available = False
    shot_zones_source = None
    # Processor still runs, just without shot zone data
```

---

## 🚨 Known Data Quality Issues

**v2.0 Update:** Issue #1 (home/away determination) has been resolved by schema improvements. The remaining issues are inherent to the data processing logic.

### Issue 1: Home/Away Determination - ✅ SOLVED in v2.0!

**Raw Data (v2.0):**
- `game_id = "20250115_LAL_PHI"` (standardized format)
- `nba_game_id = "0022400561"` (NBA.com format)
- `is_home = TRUE/FALSE` (explicit flag)

**Problem (v1.0):** Previously required schedule join to determine home/away

**Solution (v2.0):** Direct field access - much simpler!

```sql
-- v2.0: Simple direct access
SELECT
  tb.*,
  tb.is_home as home_game,  -- Direct from schema!
  -- Opponent via self-join (still needed for opponent stats)
  t2.team_abbr as opponent_team_abbr
FROM nba_raw.nbac_team_boxscore tb
JOIN nba_raw.nbac_team_boxscore t2
  ON tb.game_id = t2.game_id
  AND tb.game_date = t2.game_date
  AND tb.is_home != t2.is_home  -- Get OTHER team (home vs away)
```

**Validation:**
- Verify `is_home` is never NULL
- Verify each `game_id` has exactly 1 home and 1 away team

### Issue 2: Minutes Format - String Parsing Required

**Raw Data:** `minutes = "265:00"` (string)

**Problem:** Need to parse to determine OT periods

**Impact:** Must calculate OT periods from total minutes

**Solution:**

```python
def parse_overtime_periods(minutes_str: str) -> int:
    """
    Parse overtime periods from minutes string.

    Regulation: 240 minutes (48 min × 5 players)
    Each OT: +25 minutes (5 min × 5 players)

    Examples:
      "240:00" = 0 OT (regulation)
      "265:00" = 1 OT (240 + 25)
      "290:00" = 2 OT (240 + 50)
      "315:00" = 3 OT (240 + 75)
    """
    if not minutes_str or minutes_str == '':
        return 0

    # Parse total minutes (before colon)
    total_minutes = int(minutes_str.split(':')[0])

    if total_minutes <= 240:
        return 0

    # Calculate OT periods
    overtime_minutes = total_minutes - 240
    return overtime_minutes // 25
```

**Validation Rules:**
- `total_minutes >= 240` (regulation minimum)
- `total_minutes <= 365` (reasonable max: 5 OT periods)
- `overtime_minutes % 25 == 0` (clean OT periods)

### Issue 3: Opponent Stats - Self-Join Required (Simplified in v2.0)

**Problem:** Each game has 2 rows (one per team), need opponent's stats

**Impact:** Must self-join to get opponent points for win/loss calculation

**Solution (v2.0 - Simplified):**

```sql
-- Get opponent stats via simplified self-join
SELECT
  t1.game_id,
  t1.team_abbr,
  t1.is_home,
  t1.points as team_points,
  t2.team_abbr as opponent_team_abbr,
  t2.is_home as opponent_is_home,
  t2.points as opponent_points,
  -- Win flag
  CASE
    WHEN t1.points > t2.points THEN TRUE
    WHEN t1.points < t2.points THEN FALSE
    ELSE NULL  -- Tie should never happen in NBA
  END as win_flag,
  -- Margin
  t1.points - t2.points as margin_of_victory
FROM nba_raw.nbac_team_boxscore t1
JOIN nba_raw.nbac_team_boxscore t2
  ON t1.game_id = t2.game_id
  AND t1.game_date = t2.game_date  -- Partition optimization
  AND t1.is_home != t2.is_home     -- Get OTHER team (simpler than team_id!)
```

**v2.0 Improvement:**
- Previous: `t1.team_id != t2.team_id` (had to use team_id)
- Now: `t1.is_home != t2.is_home` (more intuitive!)
- Also validates that one team is home and one is away

**Validation:**
- Every game should have exactly 2 teams
- `t1.plus_minus = -t2.plus_minus` (should be mirror opposites)
- `win_flag` should never be NULL
- One team has `is_home = TRUE`, other has `is_home = FALSE`

### Issue 4: Play-by-Play May Be Missing

**Problem:** Play-by-play data arrives later than team boxscore

**Impact:** Shot zones may not be available immediately post-game

**Solution:**

```python
# Graceful degradation
play_by_play_count = query_play_by_play_events(game_id)

if play_by_play_count == 0:
    logger.warning(f"No play-by-play data for {game_id}, shot zones will be NULL")
    shot_zones_available = False
    # Continue processing with NULL shot zones
else:
    shot_zones_available = True
    # Extract shot zone stats
```

**Data Quality Flags:**
```python
record['shot_zones_available'] = shot_zones_available
record['shot_zones_source'] = 'nbac_pbp' if pbp_available else None
record['processed_with_issues'] = not shot_zones_available
```

**Re-processing Strategy:**
- Initial run: Process without shot zones (shot zones = NULL)
- Later run: Re-process when play-by-play arrives (update with zones)
- Use MERGE_UPDATE strategy to update existing records

---

## 🗺️ Field Mappings

### Core Identifiers (6 fields)

| Analytics Field | Raw Source | Transformation | Notes |
|----------------|------------|----------------|-------|
| game_id | nbac_team_boxscore.game_id | Direct copy | System format: "20250115_LAL_PHI" |
| game_date | nbac_team_boxscore.game_date | Direct copy | DATE type |
| team_abbr | nbac_team_boxscore.team_abbr | Direct copy | "PHI", "NYK", "LAL", etc. |
| opponent_team_abbr | Self-join (see Issue 3) | Via self-join | Other team in same game |
| season_year | nbac_team_boxscore.season_year | Direct copy | 2024 for 2024-25 season |
| nba_game_id | nbac_team_boxscore.nba_game_id | Direct copy | NBA.com format: "0022400561" (for debugging) |

### Basic Offensive Stats (11 fields)

| Analytics Field | Raw Source | Transformation | Validation |
|----------------|------------|----------------|------------|
| points_scored | nbac_team_boxscore.points | CAST(points AS INT64) | 50-200 range |
| fg_attempts | nbac_team_boxscore.fg_attempted | CAST(fg_attempted AS INT64) | 60-120 range |
| fg_makes | nbac_team_boxscore.fg_made | CAST(fg_made AS INT64) | fg_makes ≤ fg_attempts |
| three_pt_attempts | nbac_team_boxscore.three_pt_attempted | CAST(three_pt_attempted AS INT64) | 15-50 range |
| three_pt_makes | nbac_team_boxscore.three_pt_made | CAST(three_pt_made AS INT64) | 3pt_makes ≤ 3pt_attempts |
| ft_attempts | nbac_team_boxscore.ft_attempted | CAST(ft_attempted AS INT64) | 10-40 range |
| ft_makes | nbac_team_boxscore.ft_made | CAST(ft_made AS INT64) | ft_makes ≤ ft_attempts |
| rebounds | nbac_team_boxscore.total_rebounds | CAST(total_rebounds AS INT64) | 30-65 range |
| assists | nbac_team_boxscore.assists | CAST(assists AS INT64) | 15-35 range |
| turnovers | nbac_team_boxscore.turnovers | CAST(turnovers AS INT64) | 8-25 range |
| personal_fouls | nbac_team_boxscore.personal_fouls | CAST(personal_fouls AS INT64) | 15-30 range |

**Validation Formula (Points):**

```python
# Verify points calculation
two_pt_makes = fg_makes - three_pt_makes
calculated_points = (two_pt_makes * 2) + (three_pt_makes * 3) + ft_makes

if calculated_points != points:
    log_quality_issue(
        issue_type='points_calculation_mismatch',
        severity='high',
        details={
            'reported_points': points,
            'calculated_points': calculated_points,
            'difference': points - calculated_points
        }
    )
```

### Team Shot Zone Performance (6 fields)

| Analytics Field | Raw Source | Transformation | Default if Missing |
|----------------|------------|----------------|-------------------|
| team_paint_attempts | Play-by-play aggregation | COUNT(WHERE zone='paint') | NULL |
| team_paint_makes | Play-by-play aggregation | COUNT(WHERE zone='paint' AND shot_made) | NULL |
| team_mid_range_attempts | Play-by-play aggregation | COUNT(WHERE zone='mid_range') | NULL |
| team_mid_range_makes | Play-by-play aggregation | COUNT(WHERE zone='mid_range' AND shot_made) | NULL |
| points_in_paint_scored | Play-by-play aggregation | SUM(2 WHERE zone='paint' AND shot_made) | NULL |
| second_chance_points_scored | Play-by-play analysis | Complex (see below) | NULL |

### Advanced Offensive Metrics (4 fields)

| Analytics Field | Calculation Formula | Example |
|----------------|---------------------|---------|
| offensive_rating | (points / possessions) × 100 | (119 / 102.3) × 100 = 116.3 |
| pace | possessions × (48 / actual_minutes) | 102.3 × (48 / 53) = 92.6 |
| possessions | FGA + 0.44×FTA + TO - OREB | 92 + 0.44×14 + 12 - 11 = 99.2 |
| ts_pct | PTS / (2 × (FGA + 0.44×FTA)) | 119 / (2×(92 + 6.16)) = 0.606 |

**Possessions Formula Breakdown:**

```python
def calculate_possessions(fg_attempts: int, ft_attempts: int,
                         turnovers: int, offensive_rebounds: int) -> float:
    """
    Standard NBA possessions formula.

    Logic:
    - Start with field goal attempts (each attempt uses a possession)
    - Add 44% of free throw attempts (accounts for and-1s, technical FTs)
    - Add turnovers (lost possessions)
    - Subtract offensive rebounds (didn't end possession)

    Typical range: 90-110 possessions per game
    """
    possessions = (
        fg_attempts +
        (0.44 * ft_attempts) +
        turnovers -
        offensive_rebounds
    )
    return round(possessions, 1)

# Example from sample data (PHI):
# 92 + (0.44 × 14) + 12 - 11 = 92 + 6.16 + 12 - 11 = 99.16 ≈ 99.2
```

### Game Context (4 fields)

| Analytics Field | Source/Logic | Transformation |
|----------------|--------------|----------------|
| home_game | nbac_team_boxscore.is_home | Direct copy (v2.0!) |
| win_flag | Self-join comparison | team_points > opponent_points |
| margin_of_victory | Self-join calculation | team_points - opponent_points |
| overtime_periods | Parse minutes string | (total_minutes - 240) / 25 |

---

## ✅ Validation Rules

### Rule 1: Points Calculation

```python
# Points should equal: (FG2 × 2) + (3PT × 3) + FT
two_pt_makes = fg_makes - three_pt_makes
calculated_points = (two_pt_makes * 2) + (three_pt_makes * 3) + ft_makes

assert points == calculated_points, f"Points mismatch: {points} != {calculated_points}"
```

**Tolerance:** Exact match required (no tolerance)

### Rule 2: Field Goal Math

```python
# Made shots cannot exceed attempts
assert fg_makes <= fg_attempts, "FG makes > attempts"
assert three_pt_makes <= three_pt_attempts, "3PT makes > attempts"
assert ft_makes <= ft_attempts, "FT makes > attempts"

# 3-pointers are subset of field goals
assert three_pt_makes <= fg_makes, "3PT makes > total FG makes"
```

### Rule 3: Rebounds Math

```python
# Total rebounds should equal sum
calculated_rebounds = offensive_rebounds + defensive_rebounds
assert total_rebounds == calculated_rebounds, f"Rebounds mismatch"
```

### Rule 4: Reasonable Stat Ranges

```python
# Team stats should be within reasonable NBA ranges
validation_rules = {
    'points': (50, 200),           # Min/max points
    'fg_attempts': (60, 120),      # Min/max FG attempts
    'three_pt_makes': (0, 30),     # Min/max three-pointers
    'assists': (10, 40),           # Min/max assists
    'turnovers': (5, 30),          # Min/max turnovers
    'possessions': (85, 115),      # Min/max possessions
}

for field, (min_val, max_val) in validation_rules.items():
    if not (min_val <= value <= max_val):
        log_quality_issue(
            issue_type='stat_out_of_range',
            severity='medium',
            field=field,
            value=value,
            expected_range=(min_val, max_val)
        )
```

### Rule 5: Two Teams Per Game

```python
# Every game should have exactly 2 teams
team_count = len(game_teams)
assert team_count == 2, f"Game {game_id} has {team_count} teams (expected 2)"
```

---

## 📊 Output Schema

**Table:** `nba_analytics.team_offense_game_summary`
**Total Fields:** 47 (38 business fields + 9 tracking fields)

**Field Categories:**
- Core identifiers: 6 fields
- Basic offensive stats: 11 fields
- Team shot zone performance: 6 fields
- Advanced offensive metrics: 4 fields
- Game context: 4 fields
- Team situation context: 2 fields (NULL - future)
- Referee integration: 1 field (NULL - future)
- Source tracking: 9 fields (dependency tracking v4.0)
- Processing metadata: 2 fields

**Complete schema:** See implementation in `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py`

---

## 🔄 Processing Flow

### Step 1: Extract Team Boxscore Data (v2.0 - Simplified!)

```sql
-- Get team stats with opponent context (no schedule join needed!)
SELECT
  tb.game_id,
  tb.nba_game_id,
  tb.game_date,
  tb.season_year,
  tb.team_abbr,
  tb.team_name,

  -- Home/away context (direct from schema - v2.0!)
  tb.is_home as home_game,

  -- Opponent context (via self-join - simplified)
  t2.team_abbr as opponent_team_abbr,
  t2.points as opponent_points,

  -- Basic stats
  tb.points,
  tb.fg_made,
  tb.fg_attempted,
  -- ... all other stats

  -- Minutes for OT calculation
  tb.minutes,

  -- Source tracking
  tb.processed_at as source_last_updated

FROM nba_raw.nbac_team_boxscore tb

-- Self-join for opponent context (v2.0: simplified with is_home)
JOIN nba_raw.nbac_team_boxscore t2
  ON tb.game_id = t2.game_id
  AND tb.game_date = t2.game_date
  AND tb.is_home != t2.is_home  -- Get OTHER team (v2.0 improvement!)

WHERE tb.game_date BETWEEN :start_date AND :end_date
ORDER BY tb.game_date DESC, tb.game_id
```

**v2.0 Improvements:**
- ✅ No schedule join needed (was complex in v1.0)
- ✅ Simpler self-join condition (`is_home != is_home` vs `team_id != team_id`)
- ✅ Direct `home_game` field access
- ✅ `nba_game_id` available for debugging

### Step 2: Extract Play-by-Play Shot Zones (if available)

```sql
-- Aggregate shot zones by team
WITH team_shots AS (
  SELECT
    game_id,
    player_1_team_abbr as team_abbr,
    CASE
      WHEN shot_type = '2PT' AND shot_distance <= 8.0 THEN 'paint'
      WHEN shot_type = '2PT' AND shot_distance > 8.0 THEN 'mid_range'
      WHEN shot_type = '3PT' THEN 'three'
    END as zone,
    shot_made,
    CASE WHEN shot_type = '2PT' THEN 2 WHEN shot_type = '3PT' THEN 3 END as points
  FROM nba_raw.nbac_play_by_play
  WHERE event_type = 'fieldgoal'
    AND shot_made IS NOT NULL
    AND game_date = :game_date
    AND game_id = :game_id
)
SELECT
  team_abbr,
  -- Paint
  COUNT(CASE WHEN zone = 'paint' THEN 1 END) as paint_attempts,
  COUNT(CASE WHEN zone = 'paint' AND shot_made THEN 1 END) as paint_makes,
  SUM(CASE WHEN zone = 'paint' AND shot_made THEN points ELSE 0 END) as points_in_paint,
  -- Mid-range
  COUNT(CASE WHEN zone = 'mid_range' THEN 1 END) as mid_range_attempts,
  COUNT(CASE WHEN zone = 'mid_range' AND shot_made THEN 1 END) as mid_range_makes
FROM team_shots
GROUP BY team_abbr
```

### Step 3: Calculate Advanced Metrics

```python
for row in team_boxscore_data:
    # Parse OT periods
    overtime_periods = parse_overtime_periods(row['minutes'])

    # Calculate possessions
    possessions = calculate_possessions(
        row['fg_attempted'],
        row['ft_attempted'],
        row['turnovers'],
        row['offensive_rebounds']
    )

    # Calculate efficiency metrics
    actual_minutes = int(row['minutes'].split(':')[0])
    offensive_rating = (row['points'] / possessions) * 100
    pace = possessions * (48 / actual_minutes)
    ts_pct = row['points'] / (2 * (row['fg_attempted'] + 0.44 * row['ft_attempted']))

    # Determine win/loss
    win_flag = row['points'] > row['opponent_points']
    margin_of_victory = row['points'] - row['opponent_points']
```

### Step 4: Merge Shot Zones (if available)

```python
if play_by_play_data:
    shot_zones = play_by_play_data.get(team_abbr, {})
    record.update({
        'team_paint_attempts': shot_zones.get('paint_attempts'),
        'team_paint_makes': shot_zones.get('paint_makes'),
        'team_mid_range_attempts': shot_zones.get('mid_range_attempts'),
        'team_mid_range_makes': shot_zones.get('mid_range_makes'),
        'points_in_paint_scored': shot_zones.get('points_in_paint'),
        'shot_zones_available': True,
        'shot_zones_source': 'nbac_pbp'
    })
else:
    record.update({
        'team_paint_attempts': None,
        'team_paint_makes': None,
        'team_mid_range_attempts': None,
        'team_mid_range_makes': None,
        'points_in_paint_scored': None,
        'shot_zones_available': False,
        'shot_zones_source': None
    })
```

### Step 5: Validate & Save

```python
# Validate record
validate_team_offense_record(record)

# Add source tracking
record.update(build_source_tracking_fields())

# Save to BigQuery
save_to_analytics_table(record)
```

---

## 📈 Expected Data Quality Metrics

### Completeness by Source

| Source | Expected Availability | Impact if Missing |
|--------|----------------------|------------------|
| Team Boxscore | 100% (CRITICAL) | Cannot process at all |
| Schedule Context | 100% (CRITICAL) | Cannot determine home/away |
| Opponent Data | 100% (CRITICAL) | Cannot determine win/loss |
| Play-by-Play | 70-90% (OPTIONAL) | Shot zones NULL |

### Typical Completeness

```python
# For a normal game day with 10 games:
expected_rows = 20  # 10 games × 2 teams

completeness_scenarios = {
    'perfect_day': {
        'team_boxscore': 20,      # 100%
        'play_by_play': 18,       # 90% (2 teams missing PBP)
        'output_records': 20,     # 100% (all teams processed)
        'shot_zones_available': 18  # 90%
    },
    'typical_day': {
        'team_boxscore': 20,      # 100%
        'play_by_play': 16,       # 80% (4 teams missing PBP)
        'output_records': 20,     # 100%
        'shot_zones_available': 16  # 80%
    },
    'poor_day': {
        'team_boxscore': 19,      # 95% (1 team missing)
        'play_by_play': 12,       # 60% (8 teams missing PBP)
        'output_records': 19,     # 95%
        'shot_zones_available': 12  # 60%
    }
}
```

---

## 🎯 Success Criteria

**Data Mapping Complete When:**
- [x] All raw sources identified (nbac_team_boxscore v2.0, play_by_play)
- [x] Schedule join eliminated (v2.0 improvement!)
- [x] All data quality issues documented (4 issues identified, 1 solved in v2.0)
- [x] Cleaning logic defined for each issue
- [x] Field mappings complete (39 business fields mapped)
- [x] Enrichment logic documented (shot zones)
- [x] Calculation formulas validated (possessions, pace, ORtg, TS%)
- [x] Validation rules defined (8 rules)
- [x] Alert conditions specified (4 alerts)
- [x] Output schema documented (48 total fields)
- [x] Processing flow defined (5 steps - simplified in v2.0)

**Ready for Production When:**
- [x] Data mapping document complete ✅
- [x] Sample raw data analyzed ✅
- [x] Edge cases identified ✅
- [x] Source tracking strategy defined ✅
- [x] Processor base class methods understood ✅
- [ ] **Phase 2 table deployed and populated** ⬅️ **Current blocker**
- [ ] Unit test scenarios identified (waiting for Phase 2 data)

---

## 📝 Implementation Notes

### Dependencies Configuration

```python
def get_dependencies(self) -> dict:
    return {
        'nba_raw.nbac_team_boxscore': {
            'field_prefix': 'source_nbac_boxscore',
            'description': 'Team offensive stats for each game',
            'check_type': 'date_range',
            'expected_count_min': 20,  # ~10 games × 2 teams
            'max_age_hours_warn': 24,
            'max_age_hours_fail': 72,
            'critical': True
        },
        'nba_raw.nbac_play_by_play': {
            'field_prefix': 'source_play_by_play',
            'description': 'Play-by-play for shot zones',
            'check_type': 'date_range',
            'expected_count_min': 1000,  # Many events per game
            'max_age_hours_warn': 48,
            'max_age_hours_fail': 168,
            'critical': False  # Can proceed without PBP
        }
    }
```

### Processing Strategy

**Strategy:** MERGE_UPDATE
**Merge Keys:** `[game_id, team_abbr]`
**Why:** Can re-process when play-by-play arrives later
**Handling:** Update shot zones on re-run, keep rest of data

### Data Quality Tier Calculation

```python
def calculate_data_quality_tier(has_team_stats: bool,
                               has_shot_zones: bool,
                               validation_passed: bool) -> str:
    """
    Determine data quality tier.

    HIGH: Team stats + shot zones + validation passed
    MEDIUM: Team stats + validation passed (no shot zones)
    LOW: Team stats only (validation failed or missing data)
    """
    if has_team_stats and has_shot_zones and validation_passed:
        return 'high'
    elif has_team_stats and validation_passed:
        return 'medium'
    else:
        return 'low'
```

---

**Document Status:** ✅ Complete - Implementation ready, blocked on Phase 2 deployment
**Schema Version:** v2.0
**Last Updated:** 2025-11-15
**Next Review:** After Phase 2 deployment
