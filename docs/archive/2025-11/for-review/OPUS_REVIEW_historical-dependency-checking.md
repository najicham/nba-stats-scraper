# Historical Dependency Checking - Architecture Review Request

**Date:** 2025-11-22
**Purpose:** Comprehensive review of historical dependency checking strategy for NBA data pipeline
**Reviewer:** Claude Opus (external evaluation)
**Context:** Planning to backfill 4 seasons of historical data, need robust dependency checking

---

## Executive Summary

We're building a multi-phase NBA data processing pipeline that transforms raw game data through several analytical layers. We need to implement historical dependency checking before backfilling 4 years of data. The challenge: processors depend on historical windows (last 10 games, last 30 days) that may not exist during early backfill dates.

**Key Question:** How do we handle processors that need historical data when that historical data doesn't exist yet during backfill?

---

## System Architecture Overview

### Pipeline Phases

```
Phase 1: Scrapers
    ↓ (raw game data)
Phase 2: Raw Processors (22 processors)
    ↓ (cleaned, validated data)
Phase 3: Analytics Processors (5 processors)
    ↓ (aggregated stats, game summaries)
Phase 4: Precompute Processors (5 processors)  ← WE ARE HERE
    ↓ (rolling averages, zone analysis, player caches)
Phase 5: ML Feature Store + Predictions
    ↓ (feature vectors, predictions)
Phase 6: API Layer
```

### Phase 3 → Phase 4 → Phase 5 Flow

**Phase 3** (Analytics): Point-in-time aggregations
- `player_game_summary` - Single game stats for each player
- `team_offense_game_summary` - Single game offensive stats per team
- `team_defense_game_summary` - Single game defensive stats per team
- `upcoming_player_game_context` - Next game context for each player
- `upcoming_team_game_context` - Next game context for each team

**Phase 4** (Precompute): Historical window calculations
**→ THIS IS WHERE HISTORICAL DEPENDENCIES START**

- `team_defense_zone_analysis` - **Last 15 games** defense by zone (paint/mid-range/3pt)
- `player_shot_zone_analysis` - **Last 10/20 games** shot distribution
- `player_daily_cache` - **Last 5/7/10/14 games**, 180 day window for fatigue/performance
- `player_composite_factors` - Composite adjustment scores (depends on Phase 4 tables)
- `ml_feature_store` - Feature vector assembly (depends on all Phase 4 tables)

**Phase 5** (Predictions): ML predictions using Phase 4 features

---

## Current Dependency Checking Implementation

### What Phase 4 Processors Currently Do

**Example from `team_defense_zone_analysis_processor.py` (lines 295-323)**:

```python
def check_dependencies(self, analysis_date: date) -> dict:
    """
    Check if required upstream data exists and is fresh enough.

    Returns:
        dict: {
            'all_critical_present': bool,
            'all_fresh': bool,
            'missing': List[str],
            'stale': List[str],
            'details': Dict[str, Dict]
        }
    """
    dependencies = self.get_dependencies()

    results = {
        'all_critical_present': True,
        'all_fresh': True,
        'missing': [],
        'stale': [],
        'details': {}
    }

    for table_name, config in dependencies.items():
        logger.info(f"Checking dependency: {table_name}")

        # Check existence and metadata
        exists, details = self._check_table_data(
            table_name=table_name,
            analysis_date=analysis_date,
            config=config
        )

        # Check freshness (when was data last updated?)
        if exists:
            if not self._is_fresh_enough(details, config):
                results['all_fresh'] = False
                results['stale'].append(table_name)

        # Check if critical dependency missing
        if not exists and config.get('critical', False):
            results['all_critical_present'] = False
            results['missing'].append(table_name)

    return results
```

**What it checks**:
1. ✅ **Existence**: Does `nba_analytics.team_defense_game_summary` table exist?
2. ✅ **Freshness**: Was it updated in last 24 hours?
3. ✅ **Row count**: Does it have at least 300 rows (30 teams × 10 games)?
4. ❌ **Historical completeness**: NOT CHECKED

### The Missing Piece: Historical Completeness

**Current check** (from `_check_table_data` method):
```python
# Check if table has SOME data
query = f"""
SELECT
    COUNT(*) as row_count,
    MAX(processed_at) as last_updated
FROM `{table_name}`
WHERE game_date <= '{analysis_date}'
"""
```

**Problem**: Doesn't verify ALL required games exist in the historical window.

**Example scenario**:
```
Nov 22: Process team_defense_zone_analysis
        Need: LAL's last 15 games
        Current check: "Does team_defense_game_summary have >300 rows?" ✅ Yes
        Missing check: "Does LAL have all 15 games?" ❌ Unknown

        Reality: LAL has 14/17 games (missing 3)
        Current result: Processes anyway with incomplete data ❌
        Desired result: Skip LAL or alert about missing data ✅
```

---

## The Problem We're Solving

### Problem 1: Historical Window Dependencies

Phase 4 processors don't process single dates - they aggregate historical windows.

**team_defense_zone_analysis** (line 387-402):
```python
query = f"""
WITH ranked_games AS (
    SELECT *,
      ROW_NUMBER() OVER (
        PARTITION BY defending_team_abbr
        ORDER BY game_date DESC
      ) as game_rank
    FROM `nba_analytics.team_defense_game_summary`
    WHERE game_date <= '{analysis_date}'
      AND game_date >= '{season_start_date}'
)
SELECT *
FROM ranked_games
WHERE game_rank <= 15  -- LAST 15 GAMES PER TEAM
ORDER BY defending_team_abbr, game_date DESC
"""
```

**Key insight**: `WHERE game_rank <= 15` means it needs the **last 15 games played** by each team, not a fixed date range.

**For LAL on Nov 22**:
- Might need games from: Oct 31, Nov 2, 4, 6, 8, 10, 12, 13, 14, 15, 17, 18, 19, 20, 21
- NOT a simple "last 15 days" - depends on team's schedule
- If Nov 4 game is missing → incomplete data

### Problem 2: Backfill Bootstrap Scenario

**When backfilling from 4 years ago (Oct 20, 2020)**:

| Date | Games Played | Historical Data Available | Should It Run? |
|------|--------------|--------------------------|----------------|
| Oct 20 (Day 0) | 1 game per team | **0 games** (nothing to look back to) | ??? |
| Oct 25 (Day 5) | 3 games per team | **3 games** (Day 0-4 data) | ??? |
| Nov 5 (Day 15) | 8 games per team | **8 games** (Day 0-14 data) | ??? |
| Nov 15 (Day 25) | 12 games per team | **12 games** (Day 0-24 data) | ??? |
| Nov 25 (Day 35) | 15+ games per team | **15+ games** (Day 0-34 data) | ✅ Can process normally |

**Questions**:
1. How do we signal that Oct 20 (Day 0) is EXPECTED to have no historical data?
2. Should Day 0-25 run with partial data or skip entirely?
3. If they skip, how do we resume them later when data is available?
4. If they run with partial data, how do we mark "this is partial data"?

### Problem 3: Multiple Lookback Windows

**player_daily_cache** has multiple historical requirements:

```python
# Different window types in same processor:
l5_average = calculate_avg(last_5_games)      # Need 5 games
l10_average = calculate_avg(last_10_games)    # Need 10 games
l7_fatigue = calculate_fatigue(last_7_days)   # Need 7 days of games
l14_fatigue = calculate_fatigue(last_14_days) # Need 14 days of games
season_average = calculate_avg(season_games)  # Need all season games
```

**Scenario during backfill (Day 8)**:
- L5 data: ✅ Available (have 8 games)
- L7 days: ✅ Available (8 days of data)
- L10 data: ❌ Missing (only 8 games)
- L14 days: ❌ Missing (only 8 days)

**Questions**:
1. Should it run with L5+L7 and set L10+L14 to NULL?
2. Or should it wait until all 4 windows are available?
3. How do we track "this record was computed with partial windows"?

### Problem 4: Processor Interdependencies

**Phase 4 processors depend on other Phase 4 processors**:

```
team_defense_zone_analysis (L15 window)
    ↓
player_composite_factors
    ↓ (depends on team_defense_zone_analysis)
ml_feature_store
    ↓ (depends on player_composite_factors)
```

**Cascade problem**:
- If team_defense_zone_analysis skips Day 10 (insufficient data)
- Then player_composite_factors for Day 10 has no upstream data
- Then ml_feature_store for Day 10 has no upstream data
- **Result**: One missing piece breaks the entire chain

---

## What We Have (Infrastructure)

### 1. Game Schedule Table

**`nba_raw.nbac_schedule`** - knows which games SHOULD exist:

```sql
SELECT game_date, home_team_tricode, away_team_tricode, game_status
FROM `nba_raw.nbac_schedule`
WHERE game_date BETWEEN '2024-10-20' AND '2024-11-22'
  AND (home_team_tricode = 'LAL' OR away_team_tricode = 'LAL')
  AND game_status = 3  -- Final (completed games)
ORDER BY game_date;

-- Result: LAL played 17 games in this period
```

### 2. Source Tracking Fields

**Every Phase 3 table has** (from v4.0 dependency tracking):

```sql
-- Example from team_defense_game_summary schema
source_nbac_team_boxscore_last_updated TIMESTAMP,
source_nbac_team_boxscore_rows_found INT64,
source_nbac_team_boxscore_completeness_pct NUMERIC(5,2),
processed_at TIMESTAMP
```

### 3. Smart Idempotency Pattern

**Already implemented in Phase 2 & Phase 3**:

```python
# From SmartIdempotencyMixin
HASH_FIELDS = ['game_id', 'player_name', 'points', 'rebounds', ...]  # Business fields

def compute_data_hash(self, record: dict) -> str:
    """Compute SHA256 hash of meaningful fields."""
    hash_input = {k: record[k] for k in self.HASH_FIELDS if k in record}
    return hashlib.sha256(json.dumps(hash_input, sort_keys=True).encode()).hexdigest()

def should_skip_write(self, record: dict) -> bool:
    """Skip BigQuery write if data unchanged."""
    existing_hash = query_existing_hash(record['game_id'], record['player_name'])
    new_hash = self.compute_data_hash(record)
    return existing_hash == new_hash  # Skip if identical
```

### 4. Early Season Detection

**Already implemented in Phase 4 processors**:

```python
def check_dependencies(self, analysis_date: date) -> dict:
    # Check if early season
    is_early = is_early_season(
        analysis_date,
        self.opts['season_year'],
        self.early_season_threshold_days  # 14 days
    )

    if is_early:
        logger.warning("Early season detected - writing placeholder rows")
        self._write_placeholder_rows()
        return
```

**What it does**:
- First 14 days of season: Write placeholder rows with NULL metrics
- Set `early_season_flag = TRUE`
- Set `insufficient_data_reason = "Only 3 games available, need 15"`

---

## Proposed Approaches (Suggestions Only)

These are initial ideas developed during analysis. Feel free to propose entirely different approaches.

### Approach A: Schedule-Based Completeness Checking

**Concept**: Query schedule to know what SHOULD exist, compare to what DOES exist.

```python
def check_historical_completeness(entity_id, analysis_date, lookback_games=15):
    # 1. Query schedule: What games SHOULD entity have?
    expected_query = """
    SELECT COUNT(*) as expected_games
    FROM `nba_raw.nbac_schedule`
    WHERE game_date <= '{analysis_date}'
      AND game_date >= '{season_start}'
      AND (home_team_tricode = '{entity_id}' OR away_team_tricode = '{entity_id}')
      AND game_status = 3  -- Final
    """
    expected_games = run_query(expected_query)

    # 2. Query upstream: What games DO we have?
    actual_query = """
    SELECT COUNT(*) as actual_games
    FROM `nba_analytics.team_defense_game_summary`
    WHERE defending_team_abbr = '{entity_id}'
      AND game_date <= '{analysis_date}'
    """
    actual_games = run_query(actual_query)

    # 3. Compare
    if actual_games < expected_games:
        return False, f"Missing {expected_games - actual_games} games"
    elif actual_games < lookback_games:
        return False, f"Only {actual_games} games, need {lookback_games}"
    else:
        return True, "Complete"
```

**Pros**: Accurate, knows exact deficit
**Cons**: Extra queries per entity (~30 teams × 2 queries = 60 queries per run)
**Cost**: ~$0.06/month

### Approach B: Precomputed Completeness Table

**Concept**: Separate hourly job marks data completeness for all entities.

```sql
-- New table: nba_orchestration.data_completeness
CREATE TABLE data_completeness (
    dataset STRING,              -- 'team_defense_game_summary'
    entity_id STRING,            -- 'LAL'
    check_date DATE,             -- '2024-11-22'
    lookback_window INT64,       -- 15
    expected_count INT64,        -- 17 (from schedule)
    actual_count INT64,          -- 14 (from upstream)
    is_complete BOOLEAN,         -- FALSE
    missing_dates ARRAY<DATE>,   -- ['2024-11-05', '2024-11-12']
    checked_at TIMESTAMP
);
```

**Hourly job**:
1. For each table, each entity, each lookback window
2. Query schedule vs upstream
3. Write completeness status
4. Processors just query this table

**Pros**: Fast processor queries, centralized checking, can monitor/alert
**Cons**: New infrastructure, hourly update lag, maintenance overhead
**Cost**: ~$3/month

### Approach C: Partial Data Flags

**Concept**: Allow processors to run with partial data but flag it clearly.

```python
def calculate_with_partial_data(games_available, games_required):
    """Calculate metrics but flag as partial."""

    if games_available < games_required:
        metrics = calculate_metrics(games_available)  # Use what we have

        return {
            **metrics,
            'data_completeness_pct': (games_available / games_required) * 100,
            'partial_data_flag': True,
            'partial_data_reason': f'Only {games_available}/{games_required} games',
            'missing_games_count': games_required - games_available,
            # All metrics still populated, but flagged as partial
        }
```

**Schema additions**:
```sql
ALTER TABLE team_defense_zone_analysis ADD COLUMN
    partial_data_flag BOOLEAN,
    data_completeness_pct NUMERIC(5,2),
    partial_data_reason STRING,
    missing_games_count INT64;
```

**Pros**: Data exists (not NULL), downstream can filter if needed
**Cons**: Risk of using partial data unknowingly, data quality concerns

---

## Critical Questions to Resolve

### Question 1: Backfill Bootstrap Strategy

**During initial backfill from Day 0**:

**Option 1a**: Skip until sufficient data
```
Day 0-25: Skip all entities (insufficient data)
Day 25+: Start processing (have 15+ games)
Benefit: High data quality from start
Problem: First 25 days have NO Phase 4 data
```

**Option 1b**: Write placeholders
```
Day 0-25: Write placeholder rows (NULL metrics, early_season_flag=TRUE)
Day 25+: Reprocess with full data
Benefit: Continuous data coverage
Problem: Need to track which rows to reprocess later
```

**Option 1c**: Progressive fill with partial data
```
Day 0: Calculate with 1 game (mark partial_data_flag=TRUE, completeness=6.7%)
Day 5: Calculate with 5 games (mark partial_data_flag=TRUE, completeness=33.3%)
Day 25: Calculate with 15 games (mark partial_data_flag=FALSE, completeness=100%)
Benefit: Gradual quality improvement, no reprocessing needed
Problem: Partial data might be misleading
```

**Which approach?**

### Question 2: Multiple Window Handling

**When processor needs multiple lookback windows (L5, L10, L7d, L14d)**:

**Option 2a**: All-or-nothing
```python
if any_window_incomplete:
    skip_entity("Missing required windows")
```

**Option 2b**: Best-effort with flags
```python
l5_avg = calculate(l5_games) if len(l5_games) >= 5 else None
l10_avg = calculate(l10_games) if len(l10_games) >= 10 else None
# Some metrics NULL, some populated
partial_data_flag = True if any(x is None for x in [l5_avg, l10_avg]) else False
```

**Option 2c**: Degraded mode
```python
if len(games) >= 10:
    use_all_windows()  # L5, L10, L7d, L14d
elif len(games) >= 5:
    use_short_windows_only()  # L5, L7d only
    mark_degraded_mode = True
else:
    skip()
```

**Which approach? Can it vary by processor?**

### Question 3: Reprocessing After Backfill

**If Day 5 writes partial data, how do we trigger reprocessing when Day 35 backfills complete?**

**Option 3a**: Manual trigger
```bash
# After backfill completes Day 0-34
python reprocess_partial_data.py --start-date 2020-10-20 --end-date 2020-11-24
```

**Option 3b**: Automatic detection
```python
# Processor checks: "Do I have more data available now than when I last ran?"
if current_games_available > games_available_last_run:
    reprocess_entity()
```

**Option 3c**: Mark for reprocessing
```sql
-- Flag system
UPDATE team_defense_zone_analysis
SET needs_reprocessing = TRUE
WHERE partial_data_flag = TRUE
  AND analysis_date BETWEEN '2020-10-20' AND '2020-11-24';

-- Processor checks this flag
```

**Which approach? How automated should it be?**

### Question 4: Cascade Dependencies

**When upstream Phase 4 processor skips, what happens to downstream?**

```
Day 10:
  team_defense_zone_analysis: SKIP (only 10 games, need 15)
  player_composite_factors: ??? (depends on team_defense_zone_analysis)
      → Should it skip too (no upstream data)?
      → Should it write placeholder?
      → Should it process with NULL for that dependency?
```

**Option 4a**: Cascade skip
```python
if upstream_missing:
    skip_processing("Upstream dependency unavailable")
```

**Option 4b**: Partial processing
```python
if upstream_missing:
    process_without_that_dependency()  # Some factors NULL
    mark_partial_data_flag = True
```

**Option 4c**: Wait for cascade
```python
# Don't even attempt downstream until upstream succeeds
if not upstream_complete:
    defer_processing()  # Try again later
```

**Which approach?**

### Question 5: Data Quality Guarantees

**What level of completeness do we require?**

**Option 5a**: Strict (100% complete or skip)
```python
if completeness_pct < 100:
    skip_entity("Incomplete data")
```
- Benefit: Guaranteed high quality
- Problem: Many skipped dates during backfill

**Option 5b**: Tiered thresholds
```python
if completeness_pct >= 90:
    process_normally()  # "high" quality
elif completeness_pct >= 70:
    process_with_warning()  # "medium" quality
else:
    skip_entity()  # "low" quality
```
- Benefit: More flexible
- Problem: What's acceptable quality?

**Option 5c**: Progressive thresholds
```python
if days_since_season_start < 15:
    min_threshold = 50%  # Early season - lenient
elif days_since_season_start < 30:
    min_threshold = 75%  # Mid-early season
else:
    min_threshold = 90%  # Normal season - strict
```
- Benefit: Adapts to context
- Problem: Complex logic

**Which approach? Same for all processors or varies by processor?**

---

## Code Examples

### Current Processor Structure

**team_defense_zone_analysis_processor.py** (simplified):

```python
class TeamDefenseZoneAnalysisProcessor(PrecomputeProcessorBase):
    min_games_required = 15
    early_season_threshold_days = 14

    def run(self, opts: Dict) -> bool:
        # 1. Check dependencies (current implementation)
        dep_check = self.check_dependencies(opts['analysis_date'])

        if not dep_check['all_critical_present']:
            logger.error("Missing critical dependencies")
            return False

        # 2. Check early season
        if dep_check.get('is_early_season'):
            self._write_placeholder_rows(dep_check)
            return True

        # 3. Extract data (last 15 games per team)
        self.extract_raw_data()

        # 4. Calculate metrics
        self.calculate_precompute()

        # 5. Load to BigQuery
        self.load_to_bigquery()

        return True

    def calculate_precompute(self) -> None:
        for team_abbr in all_teams:
            team_games = self.raw_data[
                self.raw_data['defending_team_abbr'] == team_abbr
            ]

            # Current logic: Just check count
            if len(team_games) < self.min_games_required:
                logger.warning(f"{team_abbr}: Only {len(team_games)} games")
                self.failed_entities.append({
                    'entity_id': team_abbr,
                    'reason': f'Only {len(team_games)} games, need {self.min_games_required}',
                    'can_retry': True
                })
                continue

            # Calculate zone defense metrics
            metrics = self._calculate_zone_defense(team_games)
            self.transformed_data.append(metrics)
```

**Question**: Where should historical completeness checking be added?
- In `check_dependencies()` before extraction?
- In `calculate_precompute()` per entity?
- Both?

### Schema Structure

**Phase 4 table example** (`team_defense_zone_analysis`):

```sql
CREATE TABLE team_defense_zone_analysis (
    -- Identifiers
    team_abbr STRING NOT NULL,
    analysis_date DATE NOT NULL,

    -- Metrics (calculated from last 15 games)
    paint_pct_allowed_last_15 NUMERIC(5,3),
    mid_range_pct_allowed_last_15 NUMERIC(5,3),
    three_pt_pct_allowed_last_15 NUMERIC(5,3),
    defensive_rating_last_15 NUMERIC(6,2),
    games_in_sample INT64,

    -- Quality flags (current)
    data_quality_tier STRING,  -- 'high', 'medium', 'low'
    early_season_flag BOOLEAN,
    insufficient_data_reason STRING,

    -- Source tracking (v4.0)
    source_team_defense_last_updated TIMESTAMP,
    source_team_defense_rows_found INT64,
    source_team_defense_completeness_pct NUMERIC(5,2),
    source_team_defense_hash STRING,

    -- Smart idempotency
    data_hash STRING,

    -- Metadata
    processed_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY analysis_date
CLUSTER BY team_abbr;
```

**Possible additions** (if needed):
```sql
-- Completeness tracking
expected_games_count INT64,        -- From schedule
actual_games_count INT64,          -- From upstream
missing_games_count INT64,         -- Deficit
historical_completeness_pct NUMERIC(5,2),  -- Percentage

-- Partial data tracking
partial_data_flag BOOLEAN,         -- TRUE if incomplete windows
partial_windows ARRAY<STRING>,     -- ['l10', 'l14'] if those windows incomplete
needs_reprocessing BOOLEAN,        -- TRUE if should be reprocessed later

-- Window metadata (for debugging)
window_start_date DATE,            -- First game in window
window_end_date DATE,              -- Last game in window
window_games_found INT64           -- Actual games in window
```

---

## Real-World Scenarios

### Scenario 1: Clean Backfill (Ideal Case)

```
Phase 2 & 3 backfill complete: Oct 20 - Nov 30
Phase 4 starts processing:
  - Nov 5 (Day 15): LAL has 8 games → Skip (need 15)
  - Nov 15 (Day 25): LAL has 12 games → Skip (need 15)
  - Nov 25 (Day 35): LAL has 16 games → Process ✅
  - Nov 30 (Day 40): LAL has 17 games → Process ✅

Result: First Phase 4 data appears on Day 35
Question: Is gap from Day 0-34 acceptable?
```

### Scenario 2: Gradual Backfill

```
Phase 2 & 3 processing live, backfilling Day 0-30 gradually:
  - Current date: Nov 30
  - Nov 30 Phase 4: Has last 15 games → Process ✅
  - Nov 5 Phase 4: Only 8 games available → ???
      Option A: Skip until more backfill completes
      Option B: Process with 8 games, mark partial
      Option C: Write placeholder, reprocess later

If Option B: Nov 5 has partial data forever unless explicitly reprocessed
If Option C: Need system to trigger reprocessing
```

### Scenario 3: Data Gap in Middle

```
Complete backfill: Oct 20 - Nov 30
But: Nov 10 game for LAL is missing (scraper failed)

Nov 22 processing:
  - LAL schedule shows: 17 games should exist
  - LAL upstream has: 16 games (Nov 10 missing)
  - LAL last 15 games window includes: Nov 10 date

Current behavior: Processes with 16 games (doesn't know 1 is missing)
Desired behavior: ???
  - Skip LAL?
  - Process LAL but flag incomplete?
  - Alert about missing Nov 10?
```

### Scenario 4: Multiple Window Partial Data

```
player_daily_cache for LeBron on Nov 10 (Day 20):
  - L5 games: 5 games available ✅
  - L7 days: 6 games in last 7 days ✅
  - L10 games: 8 games available ❌ (need 10)
  - L14 days: 8 games in last 14 days ❌ (need ~10)
  - Season: 8 games total ✅

Options:
  A) Skip entirely (missing L10, L14)
  B) Calculate L5, L7, season; set L10, L14 to NULL
  C) Calculate L10, L14 with 8 games but mark "only 8/10"
  D) Use L5 as substitute for L10 (less accurate but something)

Which option? Does it depend on downstream usage?
```

---

## Additional Context

### Processing Schedule

Phase 4 processors run **nightly at specific times**:

```
11:00 PM: team_defense_zone_analysis (must complete by 11:15 PM)
11:15 PM: player_shot_zone_analysis (must complete by 11:30 PM)
11:30 PM: player_composite_factors
11:45 PM: player_daily_cache
12:00 AM: ml_feature_store
```

**Reason for stagger**: Later processors depend on earlier processors.

**Implication**: If team_defense_zone_analysis skips many entities due to incomplete data, downstream processors cascade fail.

### Data Volume

**Current season processing**:
- 30 teams × 15 games = 450 records for team processors
- 450 players × 10 games = 4,500 records for player processors
- ~5,000 BigQuery writes per night

**Backfill processing**:
- 4 seasons × 82 games/season × 30 teams = ~10,000 team records
- 4 seasons × 82 games/season × 450 players = ~150,000 player records
- Need to process efficiently (can't check every record manually)

### Cost Sensitivity

**Current costs**:
- BigQuery writes: ~$50/month
- BigQuery queries: ~$20/month
- Cloud Run: ~$100/month

**Concern**: Adding historical checks could increase query costs significantly if not designed efficiently.

**Example**:
- 450 players × 2 queries each (schedule + upstream) = 900 queries per run
- 900 queries × 30 days × $0.001 per query = ~$27/month additional

**Question**: Is cost optimization important here or is correctness more important?

---

## Success Criteria

### What does "success" look like?

1. **Data Quality**: Can confidently say "all Phase 4 records are based on complete historical data" (or clearly flagged if not)

2. **Backfill-Ready**: Can process dates from 4 years ago where historical data doesn't exist yet

3. **Transparent**: When data is missing/partial, it's clearly indicated (logs, schema flags, alerts)

4. **Auditable**: Can query "which dates have incomplete data?" and get accurate answer

5. **Recoverable**: If partial data was written, can identify and reprocess it later

6. **Efficient**: Doesn't slow down processing by 10× or cost 10× more

7. **Maintainable**: Future engineers can understand the logic without deep archaeology

---

## Questions for Reviewer (Opus)

### Core Architecture Questions

1. **Should historical completeness checking be**:
   - Part of dependency check (before extraction)?
   - Part of entity-level processing (during calculation)?
   - Separate pre-flight validation step?
   - Something else?

2. **For backfill bootstrap (Day 0-25)**:
   - Skip all dates until sufficient data?
   - Write placeholders and reprocess later?
   - Write partial data with clear flags?
   - Different strategies for different processors?

3. **For multiple lookback windows**:
   - Require all windows complete or skip?
   - Allow partial windows with NULL values?
   - Degraded mode with shorter windows?
   - Processor-specific policies?

4. **For data gaps (missing middle games)**:
   - Strict: Skip if ANY required game missing?
   - Lenient: Process with available games?
   - Threshold: Skip if >X% missing?

### Implementation Questions

5. **How should completeness be checked?**:
   - Query schedule vs upstream per entity?
   - Precomputed completeness table?
   - Heuristics (count-based with thresholds)?
   - Combination approach?

6. **How should partial data be marked?**:
   - Boolean flag only?
   - Detailed metadata (which windows incomplete)?
   - Completeness percentage?
   - Both summary and detail?

7. **How should reprocessing be triggered?**:
   - Manual scripts after backfill?
   - Automatic detection of new data availability?
   - Flag-based system processor checks?
   - Scheduled reprocessing jobs?

8. **How should cascading dependencies be handled?**:
   - Fail entire chain if one processor skips?
   - Allow partial processing downstream?
   - Explicit dependency checking at each level?

### Policy Questions

9. **What's acceptable data quality?**:
   - 100% complete or nothing?
   - Tiered quality levels (high/medium/low)?
   - Context-dependent (early season vs mid-season)?

10. **Should partial data be used downstream?**:
    - ML predictions: Use partial features or skip?
    - API responses: Return partial data with warnings?
    - Analytics dashboards: Show partial data with indicators?

### Edge Cases

11. **What if schedule data is wrong?** (Game was postponed but schedule says it happened)

12. **What if player changes teams mid-season?** (Lookback window spans two teams)

13. **What if data is corrupted vs missing?** (14 games exist but 1 is clearly bad data)

14. **What if upstream processor wrote partial data?** (Phase 3 wrote placeholder, Phase 4 depends on it)

---

## Request for Reviewer

**Please provide**:

1. **Architectural recommendation**: How should historical completeness checking be structured?

2. **Bootstrap strategy**: How to handle Day 0-25 of backfill when historical data doesn't exist?

3. **Partial data policy**: When/how should processors run with incomplete windows?

4. **Implementation approach**: Concrete recommendation on checking mechanism

5. **Edge case handling**: Guidance on the tricky scenarios above

6. **Any alternative approaches**: Ideas we haven't considered

**Feel free to**:
- Question our assumptions
- Propose entirely different approaches
- Suggest simplifications
- Point out issues we haven't considered
- Recommend staging (what to implement now vs later)

**Context provided should be sufficient, but if you need**:
- More code examples from specific processors
- Schema details for specific tables
- Query patterns or performance data
- Let us know what would be helpful

---

**Thank you for the review! We want to get this right before processing 4 years of historical data.**
