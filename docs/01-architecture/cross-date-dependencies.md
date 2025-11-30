# Cross-Date Dependency Management

**File:** `docs/01-architecture/cross-date-dependencies.md`
**Created:** 2025-11-18 14:30 PST
**Last Updated:** 2025-11-18 14:30 PST
**Purpose:** Document how processors depend on historical data across multiple dates
**Status:** Current
**Audience:** Engineers designing processors, backfill operators, system architects

---

## 🎯 Overview

**This document covers:**
- ✅ Same-date dependencies (Phase 2→3 for single date)
- ✅ Cross-date dependencies (Phase 4 needs last 10 games from multiple dates)
- ✅ Why this matters for backfills and early season processing
- ✅ How to calculate lookback windows correctly
- ✅ Backfill orchestration order to satisfy dependencies

---

## 📊 Dependency Types

### Type 1: Same-Date Dependencies

**Definition:** Data from one phase is required for the same game date in a later phase

**Example:**
```
Nov 18 Phase 2 → Nov 18 Phase 3 → Nov 18 Phase 4
```

**Characteristics:**
- Simple to manage: Process date-by-date
- Validate one date at a time
- No lookback required

**Current Implementation:**
- Phase 2 (raw) processes game_date
- Phase 3 (analytics) processes same game_date using Phase 2 data
- Phase 4 (precompute) can use same game_date from Phase 3

---

### Type 2: Cross-Date Dependencies

**Definition:** Data from MULTIPLE historical game dates is required for processing current date

**Example:**
```
Player shot zone analysis for Nov 18:
  Requires: Phase 3 data for Oct 29, Oct 31, Nov 2, Nov 4, Nov 6, Nov 8, Nov 10, Nov 12, Nov 15, Nov 17
  (Last 10 games the player actually played)
```

**Characteristics:**
- **Complex to manage:** Cannot process date-by-date
- **Lookback window required:** Must have historical data ready first
- **Player-specific or team-specific:** Lookback is entity-dependent, not calendar-based
- **Backfill order critical:** Must fill ALL historical dates before processing current date

**Future Implementation:**
- Phase 4 processors need historical context
- Phase 5 predictions need historical features
- Fatigue score calculator (future) needs season-to-date data

---

## 📋 Cross-Date Dependency Matrix

### Current & Planned Processors

| Processor | Phase | Depends On (Phase) | Lookback Window | Min Required | Fallback Strategy |
|-----------|-------|-------------------|-----------------|--------------|-------------------|
| player_shot_zone_analysis | 4 | Phase 3: player_game_summary | Last 10 games | 5 games | Use available, set quality_score |
| player_composite_factors | 4 | Phase 3: player_game_summary | Season-to-date | 3 games | Early season flag |
| team_offensive_trends | 4 | Phase 3: team_offense_game_summary | Last 15 games | 8 games | Use available, lower confidence |
| player_matchup_history | 4 | Phase 3: player_game_summary | Last 20 H2H games | 3 games | Use positional average |
| ml_feature_store_v2 | 5 | Phase 4: player_shot_zone_analysis | Last 15 games | 10 games | Use available, flag low confidence |
| fatigue_score (future) | 4 | Phase 3: player_game_summary | Season start OR 1 year | 30 games | Skip if insufficient |
| rest_days_impact (future) | 4 | Phase 3: player_game_summary | Last 30 games | 15 games | Use league average |

---

### Reading the Matrix

**Column Definitions:**

1. **Processor:** Name of the processing job
2. **Phase:** Which phase this processor belongs to
3. **Depends On:** Which earlier phase(s) must be complete first
4. **Lookback Window:** How much historical data is required
5. **Min Required:** Minimum threshold to attempt processing
6. **Fallback Strategy:** What to do when insufficient data exists

**Example: player_shot_zone_analysis**
- Needs Phase 3 data for last 10 games
- Will run with as few as 5 games (degraded mode)
- Sets quality_score based on how many games available
- Never blocks entirely

---

## 🔍 Lookback Window Requirements

### Game-Based Lookback (NOT Calendar Days!)

**Critical Distinction:** "Last 10 games" means last 10 game dates the PLAYER played, NOT last 10 calendar days

**Why This Matters:**
- Players rest, get injured, sit out back-to-backs
- 10 calendar days might only have 3-4 games for a specific player
- 10 games might span 20-30 calendar days

**Example: LeBron James Last 10 Games**

```
Current date: Nov 18, 2024
Last 10 games LeBron actually played:

Nov 17 - played (30 min)
Nov 15 - played (35 min)
Nov 13 - played (28 min)
Nov 12 - DNP - Rest ❌ (doesn't count)
Nov 10 - played (32 min)
Nov 8  - played (29 min)
Nov 6  - played (31 min)
Nov 4  - DNP - Load Management ❌ (doesn't count)
Nov 2  - played (27 min)
Oct 31 - played (33 min)
Oct 29 - played (30 min)
Oct 27 - played (28 min)

Last 10 games span: Oct 27 - Nov 17 (22 calendar days)
```

**Query Pattern:**
```sql
-- WRONG: Calendar-based
SELECT * FROM player_game_summary
WHERE player_id = 'lebron_james'
  AND game_date BETWEEN DATE_SUB('2024-11-18', INTERVAL 10 DAY) AND '2024-11-17'
-- This only gets games from Nov 8-17, might only be 5 games!

-- CORRECT: Game-based
SELECT * FROM player_game_summary
WHERE player_id = 'lebron_james'
  AND game_date < '2024-11-18'
  AND minutes_played > 0  -- Exclude DNPs
ORDER BY game_date DESC
LIMIT 10
-- This gets last 10 games LeBron actually played
```

---

### Calendar-Based Lookback

**Used For:**
- Team-level stats (team plays every 2-3 days)
- League-wide aggregations
- Schedule-dependent features (back-to-back detection)

**Example: Team Last 10 Games**

```
Team: Los Angeles Lakers
Current date: Nov 18, 2024

Team schedule is more predictable than individual player participation
Last 10 games span ~20 calendar days (team plays every 2 days on average)
```

**Query Pattern:**
```sql
-- Team games are more predictable
SELECT * FROM team_offense_game_summary
WHERE team_id = 'lakers'
  AND game_date < '2024-11-18'
ORDER BY game_date DESC
LIMIT 10
```

---

### Season-to-Date Lookback

**Used For:**
- Season averages (PPG, APG, etc.)
- Season rankings and percentiles
- Composite factors that need full season context

**Example: Player Season Stats**

```
Current date: Nov 18, 2024
Season start: Oct 22, 2024
Lookback window: Oct 22 - Nov 17 (all games this season)
```

**Query Pattern:**
```sql
-- Get all games this season for player
SELECT * FROM player_game_summary
WHERE player_id = 'lebron_james'
  AND game_date >= (SELECT season_start_date FROM season_config WHERE season = '2024-25')
  AND game_date < '2024-11-18'
ORDER BY game_date
```

---

## 🌱 Early Season Handling

### The Problem: Insufficient Historical Data

**Scenario:**
- Season starts Oct 22, 2024
- Today is Oct 28, 2024 (6 days into season)
- Player has only played 3 games
- Processor needs "last 10 games"
- **Only 3 available** → How to handle?

---

### Solution 1: Degraded Mode with Quality Scores

**Approach:** Process with available data, flag quality as degraded

**Implementation:**
```sql
-- player_shot_zone_analysis processor
DECLARE target_date DATE DEFAULT '2024-10-28';
DECLARE required_games INT64 DEFAULT 10;
DECLARE minimum_games INT64 DEFAULT 5;

WITH player_history AS (
  SELECT
    player_id,
    COUNT(*) as available_games
  FROM nba_analytics.player_game_summary
  WHERE game_date < target_date
    AND game_date >= DATE_SUB(target_date, INTERVAL 30 DAY)
  GROUP BY player_id
)

INSERT INTO nba_precompute.player_shot_zone_analysis (
  player_id,
  analysis_date,
  shot_zone_data,
  quality_score,
  early_season_flag,
  games_used
)
SELECT
  player_id,
  target_date,
  CALCULATE_SHOT_ZONES(...),  -- Your calculation logic
  -- Quality score based on available data
  CASE
    WHEN available_games >= required_games THEN 100
    WHEN available_games >= minimum_games THEN (available_games / required_games) * 100
    ELSE 0  -- Skip if below minimum
  END as quality_score,
  -- Flag early season
  available_games < required_games as early_season_flag,
  available_games
FROM player_history
WHERE available_games >= minimum_games;
```

**Quality Score Examples:**
- 10 games available → quality_score = 100 ✅
- 7 games available → quality_score = 70 ⚠️
- 5 games available → quality_score = 50 ⚠️ (minimum threshold)
- 3 games available → quality_score = 0 ❌ (skip, below minimum)

---

### Solution 2: Skip Processing Until Sufficient Data

**Approach:** Don't process until minimum threshold met

**Implementation:**
```sql
-- Skip if below minimum threshold
WITH player_history AS (
  SELECT
    player_id,
    COUNT(*) as available_games
  FROM nba_analytics.player_game_summary
  WHERE game_date < target_date
    AND game_date >= DATE_SUB(target_date, INTERVAL 30 DAY)
  GROUP BY player_id
)

-- Only process players with enough games
SELECT
  player_id,
  available_games,
  'Skipped: Insufficient data' as reason
FROM player_history
WHERE available_games < 10
ORDER BY available_games;

-- Log skipped players
INSERT INTO processing_log (date, processor, message)
SELECT
  target_date,
  'player_shot_zone_analysis',
  FORMAT('Skipped %d players: insufficient games (min 10)', COUNT(*))
FROM player_history
WHERE available_games < 10;
```

**When to Use:**
- Critical processors where degraded data is worse than no data
- Prediction systems where low-quality features reduce accuracy
- Financial or high-stakes decisions

---

### Solution 3: Use Defaults or League Averages

**Approach:** Fill missing data with league/position averages

**Implementation:**
```sql
-- Use league average when insufficient player history
WITH player_history AS (
  SELECT
    player_id,
    COUNT(*) as available_games
  FROM nba_analytics.player_game_summary
  WHERE game_date < target_date
  GROUP BY player_id
),
league_averages AS (
  SELECT
    position,
    AVG(points_per_game) as avg_ppg,
    AVG(assists_per_game) as avg_apg
  FROM nba_analytics.player_season_summary
  WHERE season = '2024-25'
  GROUP BY position
)

SELECT
  p.player_id,
  CASE
    WHEN ph.available_games >= 10 THEN p.actual_ppg
    ELSE la.avg_ppg  -- Use league average
  END as ppg,
  ph.available_games < 10 as using_defaults,
  'LOW' as confidence_score
FROM players p
LEFT JOIN player_history ph ON p.player_id = ph.player_id
LEFT JOIN league_averages la ON p.position = la.position;
```

**When to Use:**
- Display purposes (show something rather than nothing)
- Non-critical features
- User-facing dashboards

---

### Early Season Decision Matrix

| Available Games | Quality Score | Action | Confidence |
|----------------|---------------|--------|------------|
| ≥ 10 games | 100 | ✅ Process normally | HIGH |
| 7-9 games | 70-90 | ⚠️ Process, flag degraded | MEDIUM |
| 5-6 games | 50-60 | ⚠️ Process, flag degraded | LOW |
| 3-4 games | 30-40 | ❓ Skip OR use defaults | VERY LOW |
| 0-2 games | 0-20 | ❌ Skip processing | N/A |

**Recommendation:** Configure thresholds per processor based on business requirements

---

## 🔍 Dependency Check Queries

### Query 1: Check Historical Data Availability for Phase 4

**Purpose:** Before running Phase 4 for Nov 18, verify Phase 3 has sufficient historical data

```sql
-- Check if Phase 4 can run for Nov 18 (needs last 10 games per player)
DECLARE target_date DATE DEFAULT '2025-11-18';
DECLARE lookback_days INT64 DEFAULT 30;  -- 30 days should capture ~10 games
DECLARE required_games INT64 DEFAULT 10;
DECLARE minimum_games INT64 DEFAULT 5;

WITH player_history AS (
  SELECT
    player_id,
    COUNT(DISTINCT game_date) as historical_games,
    MIN(game_date) as first_game,
    MAX(game_date) as last_game,
    ARRAY_AGG(game_date ORDER BY game_date DESC LIMIT 10) as last_10_dates
  FROM nba_analytics.player_game_summary
  WHERE game_date BETWEEN DATE_SUB(target_date, INTERVAL lookback_days DAY) AND DATE_SUB(target_date, INTERVAL 1 DAY)
  GROUP BY player_id
)

SELECT
  player_id,
  historical_games,
  first_game,
  last_game,
  CASE
    WHEN historical_games >= required_games THEN '✅ Can process normally'
    WHEN historical_games >= minimum_games THEN FORMAT('⚠️ Degraded mode (%d games)', historical_games)
    WHEN historical_games >= 3 THEN FORMAT('⚠️ Early season mode (%d games)', historical_games)
    ELSE FORMAT('❌ Skip (only %d games)', historical_games)
  END as processing_status,
  last_10_dates
FROM player_history
ORDER BY historical_games ASC;
```

**Example Output:**
```
player_id     | historical_games | first_game | last_game | processing_status           | last_10_dates
--------------|------------------|------------|-----------|-----------------------------|--------------
player_rookie | 2                | 2025-11-14 | 2025-11-17| ❌ Skip (only 2 games)      | [2025-11-17, 2025-11-14]
player_new    | 4                | 2025-11-01 | 2025-11-17| ⚠️ Early season mode (4)    | [2025-11-17, ...]
player_vet    | 7                | 2025-10-25 | 2025-11-17| ⚠️ Degraded mode (7 games)  | [2025-11-17, ...]
player_star   | 12               | 2025-10-22 | 2025-11-17| ✅ Can process normally     | [2025-11-17, ...]
```

**Action:**
- ✅ 75% of players have 10+ games → Safe to run Phase 4
- ⚠️ <50% have 10+ games → Early season, expect degraded quality
- ❌ <25% have 10+ games → Too early, wait or use defaults

---

### Query 2: Check Cross-Phase Historical Dependencies

**Purpose:** Verify ALL required historical dates have Phase 3 data before running Phase 4

```sql
-- Verify all required historical data exists before running Phase 4 for Nov 18
DECLARE target_date DATE DEFAULT '2025-11-18';
DECLARE lookback_days INT64 DEFAULT 30;  -- Should capture 10 games

-- Step 1: What dates had games in the lookback window?
WITH game_dates AS (
  SELECT DISTINCT game_date
  FROM nba_raw.nbac_schedule
  WHERE game_date BETWEEN DATE_SUB(target_date, INTERVAL lookback_days DAY) AND DATE_SUB(target_date, INTERVAL 1 DAY)
),

-- Step 2: Which of those dates have Phase 3 data?
phase3_dates AS (
  SELECT DISTINCT game_date
  FROM nba_analytics.player_game_summary
  WHERE game_date BETWEEN DATE_SUB(target_date, INTERVAL lookback_days DAY) AND DATE_SUB(target_date, INTERVAL 1 DAY)
)

-- Step 3: Find gaps
SELECT
  gd.game_date,
  CASE WHEN p3.game_date IS NOT NULL THEN '✅ Phase 3 Ready' ELSE '❌ Phase 3 Missing' END as status,
  CASE WHEN p3.game_date IS NULL THEN 'BLOCKER: Cannot run Phase 4 for ' || target_date ELSE NULL END as impact
FROM game_dates gd
LEFT JOIN phase3_dates p3 ON gd.game_date = p3.game_date
ORDER BY gd.game_date;
```

**Example Output:**
```
game_date  | status              | impact
-----------|---------------------|------------------------------------------
2025-10-29 | ✅ Phase 3 Ready    | NULL
2025-10-31 | ✅ Phase 3 Ready    | NULL
2025-11-02 | ❌ Phase 3 Missing  | BLOCKER: Cannot run Phase 4 for 2025-11-18
2025-11-04 | ✅ Phase 3 Ready    | NULL
2025-11-06 | ❌ Phase 3 Missing  | BLOCKER: Cannot run Phase 4 for 2025-11-18
...
```

**Action:**
- If ANY ❌ → **STOP, backfill Phase 3 for missing dates first**
- If ALL ✅ → **Proceed with Phase 4**

---

### Query 3: Validate Sufficient Data Per Player

**Purpose:** For each player, confirm they have enough games to process

```sql
-- Which players are ready for Phase 4 processing?
DECLARE target_date DATE DEFAULT '2025-11-18';
DECLARE required_games INT64 DEFAULT 10;

WITH player_readiness AS (
  SELECT
    player_id,
    player_name,
    team,
    COUNT(DISTINCT game_date) as games_available,
    MAX(game_date) as most_recent_game,
    CASE
      WHEN COUNT(DISTINCT game_date) >= required_games THEN 'READY'
      WHEN COUNT(DISTINCT game_date) >= 5 THEN 'DEGRADED'
      ELSE 'SKIP'
    END as status
  FROM nba_analytics.player_game_summary
  WHERE game_date < target_date
    AND game_date >= DATE_SUB(target_date, INTERVAL 30 DAY)
  GROUP BY player_id, player_name, team
)

SELECT
  status,
  COUNT(*) as player_count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as percentage,
  STRING_AGG(player_name, ', ' LIMIT 5) as example_players
FROM player_readiness
GROUP BY status
ORDER BY
  CASE status
    WHEN 'READY' THEN 1
    WHEN 'DEGRADED' THEN 2
    ELSE 3
  END;
```

**Example Output:**
```
status   | player_count | percentage | example_players
---------|--------------|------------|----------------------------------
READY    | 420          | 82.0%      | LeBron James, Stephen Curry, ...
DEGRADED | 75           | 14.6%      | Rookie A, Injury Return B, ...
SKIP     | 17           | 3.3%       | Two-Way Player X, New Call-Up Y
```

**Interpretation:**
- 82% ready → Good to run Phase 4 for most players
- 14.6% degraded → Will process with quality_score < 100
- 3.3% skip → Won't process (below minimum threshold)

---

## 🔄 Backfill Orchestration Order

### The Problem: Date-by-Date Backfill Fails

**WRONG Approach:**
```bash
# Don't do this! This will fail!
for date in Nov-08 Nov-09 Nov-10 ... Nov-18; do
  run_phase1_scrapers $date
  run_phase2_raw $date
  run_phase3_analytics $date
  run_phase4_precompute $date  # ❌ FAILS: Nov-08 needs Oct 29-Nov 07 data from Phase 3
  run_phase5_predictions $date
done
```

**Why This Fails:**
- Nov 8 Phase 4 needs Phase 3 data for Oct 29 - Nov 7 (last 10 games)
- But we haven't run Phase 3 for those dates yet!
- Phase 4 will fail or produce degraded results

---

### The Solution: Phase-by-Phase Backfill

**CORRECT Approach:**

```bash
# Fill ALL dates for Phase N before starting Phase N+1

# Define ranges
TARGET_START="2024-11-08"
TARGET_END="2024-11-18"
LOOKBACK_DAYS=30
PHASE_23_START=$(date -d "$TARGET_START - $LOOKBACK_DAYS days" +%Y-%m-%d)  # Oct 9
PHASE_23_END=$TARGET_END         # Nov 18
PHASE_45_START=$TARGET_START      # Nov 8
PHASE_45_END=$TARGET_END          # Nov 18

echo "Phase 2-3 range: $PHASE_23_START to $PHASE_23_END (includes lookback)"
echo "Phase 4-5 range: $PHASE_45_START to $PHASE_45_END (target only)"

# ===================================================================
# STEP 1: Phase 1 - Scrapers (can be parallel for different dates)
# ===================================================================
echo "Step 1: Running Phase 1 scrapers..."
for date in $(seq -f "%Y-%m-%d" ...); do
  run_phase1_scrapers $date &  # Run in parallel
done
wait  # Wait for all scrapers to complete

# Validate Phase 1 complete
./bin/backfill/validate_phase1.sh --start=$PHASE_23_START --end=$PHASE_23_END

# ===================================================================
# STEP 2: Phase 2 - Raw Processing (can be parallel after Phase 1)
# ===================================================================
echo "Step 2: Running Phase 2 for Oct 9 - Nov 18..."
for date in $(generate_dates $PHASE_23_START $PHASE_23_END); do
  run_phase2_raw $date &  # Run in parallel
done
wait

# Validate Phase 2 complete for ALL dates before proceeding
./bin/backfill/validate_phase2.sh --start=$PHASE_23_START --end=$PHASE_23_END
if [ $? -ne 0 ]; then
  echo "❌ Phase 2 incomplete, cannot proceed to Phase 3"
  exit 1
fi

# ===================================================================
# STEP 3: Phase 3 - Analytics (can be parallel after Phase 2)
# ===================================================================
echo "Step 3: Running Phase 3 for Oct 9 - Nov 18..."
for date in $(generate_dates $PHASE_23_START $PHASE_23_END); do
  run_phase3_analytics $date &  # Run in parallel
done
wait

# Validate Phase 3 complete for ALL dates before proceeding
./bin/backfill/validate_phase3.sh --start=$PHASE_23_START --end=$PHASE_23_END
if [ $? -ne 0 ]; then
  echo "❌ Phase 3 incomplete, cannot proceed to Phase 4"
  exit 1
fi

# ===================================================================
# STEP 4: Phase 4 - Precompute (NOW SAFE: has Oct 9-Nov 17 historical data)
# ===================================================================
echo "Step 4: Running Phase 4 for Nov 8 - Nov 18 (has historical context now!)..."
for date in $(generate_dates $PHASE_45_START $PHASE_45_END); do
  run_phase4_precompute $date &  # Run in parallel
done
wait

# Validate Phase 4 complete
./bin/backfill/validate_phase4.sh --start=$PHASE_45_START --end=$PHASE_45_END

# ===================================================================
# STEP 5: Phase 5 - Predictions
# ===================================================================
echo "Step 5: Running Phase 5 for Nov 8 - Nov 18..."
for date in $(generate_dates $PHASE_45_START $PHASE_45_END); do
  run_phase5_predictions $date &  # Run in parallel
done
wait

# Final validation
./bin/backfill/validate_all_phases.sh --start=$PHASE_45_START --end=$PHASE_45_END
```

---

### Backfill Order Rules

**Rule 1: Sequential Phases**
- Complete Phase N for ALL dates before starting Phase N+1
- This ensures cross-date dependencies are satisfied

**Rule 2: Parallel Within Phase**
- Can run multiple dates in parallel within the same phase
- Phase 2 for Nov 8 and Nov 9 can run simultaneously

**Rule 3: Validate Between Phases**
- Always validate completeness before proceeding
- Use validation queries from `05-data-completeness-validation.md`

**Rule 4: Include Lookback in Range**
- Calculate Phase 2-3 range = target range + lookback window
- Phase 4-5 range = target range only

---

## 📐 Date Range Calculation

### Calculate Required Backfill Range

**Problem:** User wants to backfill Nov 8-14, what's the actual range needed?

**Solution:** Include lookback window in Phase 2-3 range

```python
from datetime import datetime, timedelta

def calculate_backfill_range(target_start, target_end, lookback_days=30):
    """
    Calculate full range needed for backfill including lookback.

    Args:
        target_start: First date user wants to backfill (datetime.date)
        target_end: Last date user wants to backfill (datetime.date)
        lookback_days: How many days of history needed (default 30 for ~10 games)

    Returns:
        dict with phase ranges
    """
    # Phase 2-3 must cover lookback window
    phase2_start = target_start - timedelta(days=lookback_days)
    phase2_end = target_end

    # Phase 4-5 only for target range
    phase4_start = target_start
    phase4_end = target_end

    return {
        'target': {'start': target_start, 'end': target_end},
        'phase2_3': {'start': phase2_start, 'end': phase2_end},
        'phase4_5': {'start': phase4_start, 'end': phase4_end},
        'lookback_days': lookback_days
    }

# Example usage
from datetime import date

target_start = date(2024, 11, 8)
target_end = date(2024, 11, 14)

ranges = calculate_backfill_range(target_start, target_end, lookback_days=30)

print(f"User requested: {ranges['target']['start']} to {ranges['target']['end']}")
print(f"Phase 2-3 range: {ranges['phase2_3']['start']} to {ranges['phase2_3']['end']}")
print(f"Phase 4-5 range: {ranges['phase4_5']['start']} to {ranges['phase4_5']['end']}")

# Output:
# User requested: 2024-11-08 to 2024-11-14
# Phase 2-3 range: 2024-10-09 to 2024-11-14  (includes lookback)
# Phase 4-5 range: 2024-11-08 to 2024-11-14  (target only)
```

---

### Bash Script Example

```bash
#!/bin/bash
# bin/backfill/calculate_range.sh

TARGET_START=$1  # e.g., 2024-11-08
TARGET_END=$2    # e.g., 2024-11-14
LOOKBACK_DAYS=${3:-30}  # Default 30 days for ~10 games

# Calculate Phase 2-3 range (includes lookback)
if [[ "$OSTYPE" == "darwin"* ]]; then
  # macOS date command
  PHASE2_START=$(date -j -v-${LOOKBACK_DAYS}d -f "%Y-%m-%d" "$TARGET_START" "+%Y-%m-%d")
else
  # Linux date command
  PHASE2_START=$(date -d "$TARGET_START - $LOOKBACK_DAYS days" +%Y-%m-%d)
fi

PHASE2_END=$TARGET_END

# Phase 4-5 range (target only)
PHASE4_START=$TARGET_START
PHASE4_END=$TARGET_END

echo "=============================================="
echo "Backfill Range Calculator"
echo "=============================================="
echo "User requested: $TARGET_START to $TARGET_END"
echo ""
echo "Phase 2-3 range: $PHASE2_START to $PHASE2_END"
echo "  (includes $LOOKBACK_DAYS day lookback)"
echo ""
echo "Phase 4-5 range: $PHASE4_START to $PHASE4_END"
echo "  (target range only)"
echo "=============================================="
echo ""
echo "Next steps:"
echo "1. Run Phase 1-3 for: $PHASE2_START to $PHASE2_END"
echo "2. Validate Phase 3 complete"
echo "3. Run Phase 4-5 for: $PHASE4_START to $PHASE4_END"
```

**Usage:**
```bash
./bin/backfill/calculate_range.sh 2024-11-08 2024-11-14 30

# Output:
# ==============================================
# Backfill Range Calculator
# ==============================================
# User requested: 2024-11-08 to 2024-11-14
#
# Phase 2-3 range: 2024-10-09 to 2024-11-14
#   (includes 30 day lookback)
#
# Phase 4-5 range: 2024-11-08 to 2024-11-14
#   (target range only)
# ==============================================
```

---

### Check What Already Exists

**Before backfilling, check what data already exists:**

```bash
#!/bin/bash
# bin/backfill/check_existing.sh

START_DATE=$1
END_DATE=$2

echo "Checking existing data for: $START_DATE to $END_DATE"

bq query --use_legacy_sql=false --format=pretty "
WITH date_range AS (
  SELECT date
  FROM UNNEST(GENERATE_DATE_ARRAY(DATE('$START_DATE'), DATE('$END_DATE'))) AS date
),
phase2_dates AS (
  SELECT DISTINCT game_date FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
  WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'
),
phase3_dates AS (
  SELECT DISTINCT game_date FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'
),
phase4_dates AS (
  SELECT DISTINCT game_date FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
  WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'
)

SELECT
  d.date,
  CASE WHEN p2.game_date IS NOT NULL THEN '✅' ELSE '❌' END as phase2,
  CASE WHEN p3.game_date IS NOT NULL THEN '✅' ELSE '❌' END as phase3,
  CASE WHEN p4.game_date IS NOT NULL THEN '✅' ELSE '❌' END as phase4
FROM date_range d
LEFT JOIN phase2_dates p2 ON d.date = p2.game_date
LEFT JOIN phase3_dates p3 ON d.date = p3.game_date
LEFT JOIN phase4_dates p4 ON d.date = p4.game_date
ORDER BY d.date;
"
```

**Example Output:**
```
date       | phase2 | phase3 | phase4
-----------|--------|--------|--------
2024-10-09 | ❌     | ❌     | ❌      ← Need to backfill
2024-10-11 | ❌     | ❌     | ❌
...
2024-11-01 | ✅     | ✅     | ❌      ← Phase 2-3 exist, only need Phase 4
2024-11-08 | ❌     | ❌     | ❌      ← Target start, need all phases
2024-11-14 | ❌     | ❌     | ❌      ← Target end
```

**Decision:**
- Oct 9 - Oct 31: Need Phase 2-3 (for historical context)
- Nov 1 - Nov 7: Already have Phase 2-3, skip
- Nov 8 - Nov 14: Need Phase 2-5 (target range)

---

## 🎯 Practical Examples

### Example 1: Backfill Nov 8-14 (7 Days)

**Goal:** Fill missing data for Nov 8-14

**Step 1: Calculate ranges**
```bash
./bin/backfill/calculate_range.sh 2024-11-08 2024-11-14 30

# Phase 2-3: Oct 9 - Nov 14 (includes lookback)
# Phase 4-5: Nov 8 - Nov 14 (target only)
```

**Step 2: Check existing data**
```bash
./bin/backfill/check_existing.sh 2024-10-09 2024-11-14

# Discovers:
# - Oct 9-31: Missing Phase 2-3
# - Nov 1-7: Phase 2-3 exist ✅
# - Nov 8-14: Missing everything
```

**Step 3: Backfill Phase 2-3 for Oct 9-31 + Nov 8-14**
```bash
# Run Phase 1-3 for gaps only
./bin/backfill/run_phases_1_3.sh --start=2024-10-09 --end=2024-10-31
./bin/backfill/run_phases_1_3.sh --start=2024-11-08 --end=2024-11-14

# Validate
./bin/backfill/validate_phase3.sh --start=2024-10-09 --end=2024-11-14
```

**Step 4: Backfill Phase 4-5 for Nov 8-14 only**
```bash
# Now Phase 4 has Oct 9-Nov 7 historical context
./bin/backfill/run_phase_4.sh --start=2024-11-08 --end=2024-11-14

# Validate
./bin/backfill/validate_phase4.sh --start=2024-11-08 --end=2024-11-14
```

---

### Example 2: Full Season Backfill (2023-24)

**Goal:** Backfill entire 2023-24 season

**Dates:**
- Season: Oct 24, 2023 - Apr 14, 2024 (~180 game dates)
- Lookback: Start from Oct 1, 2023 (to have data for Oct 24)

**Approach:**
```bash
# 1. Define ranges
SEASON_START="2023-10-24"
SEASON_END="2024-04-14"
PHASE_23_START="2023-10-01"  # Include lookback for first games
PHASE_23_END="2024-04-14"

# 2. Run Phase 1-3 for entire extended range
./bin/backfill/run_phases_1_3.sh \
  --start=$PHASE_23_START \
  --end=$PHASE_23_END \
  --parallel=10  # Run 10 dates in parallel

# 3. Validate Phase 3 complete
./bin/backfill/validate_phase3.sh --start=$PHASE_23_START --end=$PHASE_23_END

# 4. Run Phase 4-5 for season only
./bin/backfill/run_phases_4_5.sh \
  --start=$SEASON_START \
  --end=$SEASON_END \
  --parallel=10

# 5. Final validation
./bin/backfill/validate_all_phases.sh --start=$SEASON_START --end=$SEASON_END
```

**Timeline:**
- Phase 1-3: ~180 dates × 3 phases = ~540 phase-date combinations
- Phase 4-5: ~180 dates × 2 phases = ~360 phase-date combinations
- Total: ~900 phase-date combinations

**Validation Critical:**
- Any missing date blocks downstream phases
- Use Query 2 from `05-data-completeness-validation.md` to find gaps

---

### Example 3: Early Season Backfill (First 10 Games)

**Goal:** Backfill Oct 22 - Nov 5 (season start)

**Challenge:** No historical context for first 10 games

**Approach:**
```bash
# 1. Run Phase 1-3 normally
./bin/backfill/run_phases_1_3.sh --start=2024-10-22 --end=2024-11-05

# 2. Run Phase 4-5 with early_season_mode flag
gcloud run jobs execute phase4-player-shot-zone-analysis \
  --region us-central1 \
  --set-env-vars "START_DATE=2024-10-22,END_DATE=2024-11-05,EARLY_SEASON_MODE=true"

# Early season mode:
# - Oct 22: 0 games → skip OR use defaults, quality_score = 0
# - Oct 24: 1 game → quality_score = 10, degraded
# - Oct 27: 3 games → quality_score = 30, degraded
# - Nov 1: 6 games → quality_score = 60, medium quality
# - Nov 5: 10 games → quality_score = 100 ✅
```

**Expectations:**
- First ~10 dates will have low quality_score
- Predictions will have low confidence
- This is expected and acceptable for early season

---

## 🔗 Related Documentation

**Backfill Operations:**
- `docs/operations/01-backfill-operations-guide.md` - How to actually run backfills (step-by-step)
- `docs/monitoring/05-data-completeness-validation.md` - Validation queries

**Monitoring:**
- `docs/monitoring/01-grafana-monitoring-guide.md` - Comprehensive monitoring
- `docs/monitoring/04-observability-gaps-and-improvement-plan.md` - What's missing

**Architecture:**
- `docs/01-architecture/pipeline-design.md` - Overview of 5-phase system
- `docs/01-architecture/change-detection/` - Entity-level change detection

---

## 📝 Quick Reference

### Key Concepts

| Concept | Definition | Example |
|---------|-----------|---------|
| Same-date dependency | Phase N+1 needs Phase N for same date | Nov 18 Phase 3 needs Nov 18 Phase 2 |
| Cross-date dependency | Phase N needs data from multiple historical dates | Nov 18 Phase 4 needs Oct 29-Nov 17 Phase 3 |
| Lookback window | How much historical data required | Last 10 games, season-to-date |
| Game-based lookback | Count games player played, not calendar days | Last 10 games ≠ last 10 days |
| Quality score | Measure of data completeness (0-100) | 10 games = 100, 5 games = 50 |
| Early season mode | Special handling when insufficient history | Use defaults or degrade gracefully |

---

### Decision Trees

**Should I use calendar-based or game-based lookback?**
- Player stats → Game-based (players sit out, get injured)
- Team stats → Calendar-based (teams play regularly)
- League aggregates → Calendar-based

**What quality score threshold to use?**
- Critical processors → Require 100 (skip if below)
- Standard processors → Accept 50+ (degrade gracefully)
- Display only → Accept any, use defaults

**How to order backfill?**
- Always: Phase-by-phase (not date-by-date)
- Always: Validate between phases
- Always: Include lookback in Phase 2-3 range

---

**Created:** 2025-11-18
**Next Review:** After first full season backfill
**Status:** ✅ Ready to use
