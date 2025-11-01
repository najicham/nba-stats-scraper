# Team Defense Zone Analysis Processor

**Path:** `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`  
**Phase:** 4 (Precompute)  
**Output Table:** `nba_precompute.team_defense_zone_analysis`  
**Processing Strategy:** `MERGE_UPDATE` (replace by analysis_date)  
**Schedule:** Nightly at 11:00 PM (before player processors)  
**Duration:** 2-3 minutes (~30 teams)  
**Version:** 1.0

---

## Overview

### Purpose

Aggregate team defensive performance by shot zone over the last 15 games. This processor analyzes how well each NBA team defends different areas of the court (paint, mid-range, perimeter) and compares their performance to league averages.

**Key Features:**
- Calculates field goal percentage allowed by zone (paint, mid-range, three-point)
- Compares team defense to dynamic league averages
- Identifies defensive strengths and weaknesses for each team
- Processes all 30 NBA teams in ~2 minutes
- Uses v4.0 dependency tracking (3 fields per source)
- Handles early season with placeholder rows

### When to Use This Processor

✅ **Use this processor for:**
- Analyzing team defensive tendencies by court zone
- Identifying which teams are strong/weak defending specific areas
- Player opponent analysis (how hard is the matchup?)
- Team defensive scouting and preparation
- Historical defensive trend analysis

❌ **Don't use this processor if:**
- You need player-level defensive metrics (use player processors)
- You need real-time defensive data (this is daily aggregation)
- Early season (<14 days) when sample sizes are too small

### Downstream Usage

This processor's output is critical for:
- **Player Prediction Models** - Opponent defensive strength by zone
- **Matchup Analysis** - How player's scoring zones match up against team's defense
- **Team Reports** - Defensive scouting and strategy
- **Betting Models** - Team defensive factors in prop predictions

---

## Data Flow

```
Phase 3: Analytics Tables
  └─ team_defense_game_summary (game-level defensive stats by zone)
       ↓
Phase 4: team_defense_zone_analysis ← THIS PROCESSOR
  (Aggregates: 30 teams × last 15 games × 3 zones)
       ↓
Phase 5: Player Prediction Systems
  - Opponent defensive strength
  - Zone-specific matchup analysis
```

---

## Dependencies

### Critical Dependencies (1 Required Source)

This processor requires **1 critical source** from Phase 3:

#### `nba_analytics.team_defense_game_summary` (Phase 3)
- **Purpose:** Game-level defensive statistics by shot zone
- **Fields Used:**
  - Zone shooting: `opp_paint_makes`, `opp_paint_attempts`
  - Mid-range: `opp_mid_range_makes`, `opp_mid_range_attempts`
  - Three-point: `opp_three_pt_makes`, `opp_three_pt_attempts`
  - Points: `points_in_paint_allowed`, `mid_range_points_allowed`, `three_pt_points_allowed`
  - Blocks: `blocks_paint`, `blocks_mid_range`, `blocks_three_pt`
  - Overall: `points_allowed`, `defensive_rating`, `opponent_pace`
- **Requirement:** Last 15 games per team (minimum for analysis)
- **Check Type:** `per_team_game_count` (custom check)
- **Minimum Teams:** 25 teams must have 15+ games
- **Freshness:** Data should be < 72 hours old (warn), < 168 hours old (fail)

### Dependency Hierarchy

```
Phase 3 (Base Data):
  └─ team_defense_game_summary (always required)
       ↓
Phase 4 (Aggregated Features):
  └─ team_defense_zone_analysis ← THIS PROCESSOR
```

### Custom Dependency Check

This processor implements a custom `per_team_game_count` check type:

```python
def _check_table_data(self, table_name: str, analysis_date: date, config: dict):
    """
    Count how many teams have minimum required games.
    
    Different from standard checks:
    - Counts games PER TEAM (not total rows)
    - Verifies minimum teams threshold
    - Returns team-specific details
    """
    query = """
    WITH team_game_counts AS (
        SELECT defending_team_abbr, COUNT(*) as game_count
        FROM {table_name}
        WHERE game_date <= '{analysis_date}'
          AND game_date >= '{season_start}'
        GROUP BY defending_team_abbr
    )
    SELECT 
        COUNT(*) as teams_with_min_games,
        SUM(game_count) as total_games
    FROM team_game_counts
    WHERE game_count >= {min_games}
    """
    # Returns: (exists: bool, details: dict)
```

---

## Output Schema

### Table Details

**Table:** `nba_precompute.team_defense_zone_analysis`  
**Partitioned By:** `analysis_date` (daily partitions)  
**Clustered By:** `team_abbr`  
**Retention:** 365 days (automatic deletion after 1 year)

### Field Categories (33 total fields)

#### Identifiers (2 fields)
- `team_abbr` STRING (PRIMARY KEY with analysis_date)
- `analysis_date` DATE (PARTITION KEY)

#### Paint Defense (5 fields)
- `paint_pct_allowed_last_15` FLOAT64 - FG% allowed in paint (last 15 games)
- `paint_attempts_allowed_per_game` FLOAT64 - Paint FGA allowed per game
- `paint_points_allowed_per_game` FLOAT64 - Paint points allowed per game
- `paint_blocks_per_game` FLOAT64 - Paint blocks per game
- `paint_defense_vs_league_avg` FLOAT64 - Percentage points vs league (negative = better)

#### Mid-Range Defense (4 fields)
- `mid_range_pct_allowed_last_15` FLOAT64 - FG% allowed on mid-range shots
- `mid_range_attempts_allowed_per_game` FLOAT64 - Mid-range FGA allowed per game
- `mid_range_blocks_per_game` FLOAT64 - Mid-range blocks per game
- `mid_range_defense_vs_league_avg` FLOAT64 - Percentage points vs league

#### Three-Point Defense (4 fields)
- `three_pt_pct_allowed_last_15` FLOAT64 - 3PT% allowed
- `three_pt_attempts_allowed_per_game` FLOAT64 - 3PA allowed per game
- `three_pt_blocks_per_game` FLOAT64 - Three-point blocks per game
- `three_pt_defense_vs_league_avg` FLOAT64 - Percentage points vs league

#### Overall Defense (3 fields)
- `defensive_rating_last_15` FLOAT64 - Overall defensive rating (points per 100 possessions)
- `opponent_points_per_game` FLOAT64 - Points allowed per game
- `opponent_pace` FLOAT64 - Opponent possessions per game

#### Strengths/Weaknesses (2 fields)
- `strongest_zone` STRING - Best defensive zone (paint, mid_range, perimeter)
- `weakest_zone` STRING - Worst defensive zone

#### Data Quality (2 fields)
- `games_in_sample` INT64 - Number of games analyzed (should be 15)
- `data_quality_tier` STRING - Quality tier (high/medium/low)
- `calculation_notes` STRING - Notes about calculation (e.g., "No mid-range attempts")

#### Source Tracking (3 fields - v4.0 Standard)
- `source_team_defense_last_updated` TIMESTAMP
- `source_team_defense_rows_found` INT64
- `source_team_defense_completeness_pct` FLOAT64

#### Optional Tracking (2 fields)
- `early_season_flag` BOOLEAN - TRUE if early season (< 14 days)
- `insufficient_data_reason` STRING - Explanation if insufficient data

#### Metadata (1 field)
- `processed_at` TIMESTAMP - When record was processed

### Sample Record

```json
{
  "team_abbr": "BOS",
  "analysis_date": "2025-01-27",
  
  // Paint Defense - Elite (42nd percentile vs league)
  "paint_pct_allowed_last_15": 0.558,
  "paint_attempts_allowed_per_game": 32.4,
  "paint_points_allowed_per_game": 38.2,
  "paint_blocks_per_game": 2.8,
  "paint_defense_vs_league_avg": -2.2,
  
  // Mid-Range Defense - Above Average
  "mid_range_pct_allowed_last_15": 0.395,
  "mid_range_attempts_allowed_per_game": 18.6,
  "mid_range_blocks_per_game": 0.9,
  "mid_range_defense_vs_league_avg": -1.5,
  
  // Three-Point Defense - League Average
  "three_pt_pct_allowed_last_15": 0.356,
  "three_pt_attempts_allowed_per_game": 34.8,
  "three_pt_blocks_per_game": 0.3,
  "three_pt_defense_vs_league_avg": 0.1,
  
  // Overall Defense
  "defensive_rating_last_15": 108.4,
  "opponent_points_per_game": 106.2,
  "opponent_pace": 98.7,
  
  // Strengths/Weaknesses
  "strongest_zone": "paint",
  "weakest_zone": "perimeter",
  
  // Data Quality
  "games_in_sample": 15,
  "data_quality_tier": "high",
  "calculation_notes": null,
  
  // Source Tracking (v4.0)
  "source_team_defense_last_updated": "2025-01-27T23:05:00Z",
  "source_team_defense_rows_found": 450,
  "source_team_defense_completeness_pct": 100.0,
  
  // Early Season
  "early_season_flag": null,
  "insufficient_data_reason": null,
  
  // Metadata
  "processed_at": "2025-01-27T23:15:32Z"
}
```

### Understanding vs League Average

The `*_vs_league_avg` fields show percentage point differences:

- **Negative values = Better defense** (allowing lower FG%)
  - `-2.2` = Team allows 2.2 percentage points LESS than league average (good!)
  - Example: League average 58.0%, team allows 55.8%

- **Positive values = Worse defense** (allowing higher FG%)
  - `+3.5` = Team allows 3.5 percentage points MORE than league average (bad!)
  - Example: League average 35.5%, team allows 39.0%

- **Zero = League average defense**

---

## Processing Logic

### High-Level Algorithm

```python
def process_team_defense_zone_analysis(analysis_date):
    """
    1. Check dependencies (team_defense_game_summary)
    2. Check if early season (< 14 days since season start)
    3. If early season: Write placeholder rows for all 30 teams
    4. If normal season:
       - Extract last 15 games per team
       - Calculate league averages (for comparison)
       - For each team:
         * Calculate zone defense metrics
         * Compare to league averages
         * Identify strengths/weaknesses
       - Save to BigQuery (MERGE strategy)
    """
```

### Detailed Steps

#### Step 1: Dependency Checking with Early Season Detection

```python
# Check if early season
is_early = is_early_season(
    analysis_date,
    season_year,
    threshold_days=14  # First 14 days of season
)

# Run base dependency check
dep_check = check_dependencies(analysis_date)
dep_check['is_early_season'] = is_early

# Handle early season
if is_early:
    logger.warning("Early season - writing placeholder rows")
    _write_placeholder_rows(dep_check)
    return

# Handle dependency failures
if not dep_check['all_critical_present']:
    raise ValueError("Missing critical dependencies")

# Warn about stale data (but continue)
if not dep_check['all_fresh']:
    logger.warning(f"Stale data: {dep_check['stale']}")
```

#### Step 2: Data Extraction

```python
# Extract last 15 games per team
query = """
WITH ranked_games AS (
    SELECT *,
      ROW_NUMBER() OVER (
        PARTITION BY defending_team_abbr 
        ORDER BY game_date DESC
      ) as game_rank
    FROM nba_analytics.team_defense_game_summary
    WHERE game_date <= '{analysis_date}'
      AND game_date >= '{season_start_date}'
)
SELECT * 
FROM ranked_games 
WHERE game_rank <= 15
ORDER BY defending_team_abbr, game_date DESC
"""

raw_data = bq_client.query(query).to_dataframe()

logger.info(
    f"Extracted {len(raw_data)} game records for "
    f"{raw_data['defending_team_abbr'].nunique()} teams"
)
```

#### Step 3: Calculate League Averages

```python
def _calculate_league_averages(self):
    """
    Calculate league-wide defensive averages for comparison.
    
    Uses 30-day window (configurable) to get representative sample.
    Falls back to historical defaults if <10 teams available.
    """
    lookback_date = analysis_date - timedelta(days=30)
    
    query = """
    WITH team_aggregates AS (
        SELECT
            defending_team_abbr,
            SUM(opp_paint_makes) as paint_makes,
            SUM(opp_paint_attempts) as paint_attempts,
            SUM(opp_mid_range_makes) as mid_range_makes,
            SUM(opp_mid_range_attempts) as mid_range_attempts,
            SUM(opp_three_pt_makes) as three_pt_makes,
            SUM(opp_three_pt_attempts) as three_pt_attempts
        FROM nba_analytics.team_defense_game_summary
        WHERE game_date BETWEEN '{lookback_date}' AND '{analysis_date}'
        GROUP BY defending_team_abbr
        HAVING COUNT(*) >= 10
    ),
    team_percentages AS (
        SELECT
            SAFE_DIVIDE(paint_makes, paint_attempts) as paint_pct,
            SAFE_DIVIDE(mid_range_makes, mid_range_attempts) as mid_range_pct,
            SAFE_DIVIDE(three_pt_makes, three_pt_attempts) as three_pt_pct
        FROM team_aggregates
    )
    SELECT
        AVG(paint_pct) as league_avg_paint_pct,
        AVG(mid_range_pct) as league_avg_mid_range_pct,
        AVG(three_pt_pct) as league_avg_three_pt_pct,
        COUNT(*) as teams_in_sample
    FROM team_percentages
    """
    
    result = bq_client.query(query).to_dataframe()
    
    if result.empty or result['teams_in_sample'].iloc[0] < 10:
        # Use historical NBA defaults
        return {
            'paint_pct': 0.580,
            'mid_range_pct': 0.410,
            'three_pt_pct': 0.355,
            'teams_in_sample': 0
        }
    
    return {
        'paint_pct': float(result['league_avg_paint_pct'].iloc[0]),
        'mid_range_pct': float(result['league_avg_mid_range_pct'].iloc[0]),
        'three_pt_pct': float(result['league_avg_three_pt_pct'].iloc[0]),
        'teams_in_sample': int(result['teams_in_sample'].iloc[0])
    }
```

#### Step 4: Team Loop - Calculate Zone Defense

```python
successful = []
failed = []

all_teams = raw_data['defending_team_abbr'].unique()

for team_abbr in all_teams:
    try:
        # Get team's games
        team_data = raw_data[
            raw_data['defending_team_abbr'] == team_abbr
        ].copy()
        
        games_count = len(team_data)
        
        # Validate sufficient games
        if games_count < 15:
            failed.append({
                'entity_id': team_abbr,
                'reason': f"Only {games_count} games, need 15",
                'category': 'INSUFFICIENT_DATA'
            })
            continue
        
        # Sum across all games
        total_paint_makes = team_data['opp_paint_makes'].sum()
        total_paint_attempts = team_data['opp_paint_attempts'].sum()
        total_mid_range_makes = team_data['opp_mid_range_makes'].sum()
        total_mid_range_attempts = team_data['opp_mid_range_attempts'].sum()
        total_three_pt_makes = team_data['opp_three_pt_makes'].sum()
        total_three_pt_attempts = team_data['opp_three_pt_attempts'].sum()
        
        # Calculate FG% allowed
        paint_pct = (
            total_paint_makes / total_paint_attempts 
            if total_paint_attempts > 0 else None
        )
        mid_range_pct = (
            total_mid_range_makes / total_mid_range_attempts 
            if total_mid_range_attempts > 0 else None
        )
        three_pt_pct = (
            total_three_pt_makes / total_three_pt_attempts 
            if total_three_pt_attempts > 0 else None
        )
        
        # Calculate per-game metrics
        paint_attempts_pg = total_paint_attempts / games_count
        paint_points_pg = team_data['points_in_paint_allowed'].sum() / games_count
        paint_blocks_pg = team_data['blocks_paint'].sum() / games_count
        
        # Similar for mid-range and three-point...
        
        # Calculate vs league average (percentage points difference)
        paint_vs_league = (
            (paint_pct - league_averages['paint_pct']) * 100
            if paint_pct is not None else None
        )
        
        # Identify strengths/weaknesses
        zones = {
            'paint': paint_vs_league,
            'mid_range': mid_range_vs_league,
            'perimeter': three_pt_vs_league
        }
        strongest = min(zones, key=zones.get)  # Most negative = best
        weakest = max(zones, key=zones.get)    # Most positive = worst
        
        # Build output record
        record = {
            'team_abbr': team_abbr,
            'analysis_date': analysis_date.isoformat(),
            
            # Paint defense
            'paint_pct_allowed_last_15': float(paint_pct) if paint_pct else None,
            'paint_attempts_allowed_per_game': float(paint_attempts_pg),
            'paint_defense_vs_league_avg': float(paint_vs_league) if paint_vs_league else None,
            # ... more fields
            
            # Strengths
            'strongest_zone': strongest,
            'weakest_zone': weakest,
            
            # Quality
            'games_in_sample': games_count,
            'data_quality_tier': 'high' if games_count >= 15 else 'medium',
            
            # Source tracking (v4.0)
            **self.build_source_tracking_fields(),
            
            # Metadata
            'processed_at': datetime.now(UTC).isoformat()
        }
        
        successful.append(record)
        
    except Exception as e:
        failed.append({
            'entity_id': team_abbr,
            'reason': str(e),
            'category': 'PROCESSING_ERROR'
        })

self.transformed_data = successful
self.failed_entities = failed
```

---

## Early Season Handling

### Detection Rules

Early season is defined as **< 14 days since season start**.

| Days Since Season Start | Action | early_season_flag | Records Written |
|------------------------|--------|-------------------|-----------------|
| 0-13 days | **Write placeholders** | `TRUE` | All 30 teams |
| 14+ days | **Normal processing** | `NULL` | Teams with 15+ games |

### Early Season Behavior

When early season is detected:

1. **Skip normal processing** - Don't calculate metrics
2. **Write placeholder rows** - One for each of 30 NBA teams
3. **Set all metrics to NULL** - No meaningful data yet
4. **Populate source tracking** - Still track data availability
5. **Set early season flag** - Mark records as placeholders

```python
def _write_placeholder_rows(self, dep_check: dict):
    """Write placeholder rows for early season."""
    placeholders = []
    
    # Get all 30 NBA teams
    all_teams = self.team_mapper.get_all_nba_tricodes()
    
    for team_abbr in all_teams:
        # Count available games for context
        games_count = count_games_for_team(team_abbr, analysis_date)
        
        placeholder = {
            'team_abbr': team_abbr,
            'analysis_date': analysis_date.isoformat(),
            
            # All defense metrics = NULL
            'paint_pct_allowed_last_15': None,
            'mid_range_pct_allowed_last_15': None,
            'three_pt_pct_allowed_last_15': None,
            'defensive_rating_last_15': None,
            'strongest_zone': None,
            'weakest_zone': None,
            # ... all other metrics NULL
            
            # Context
            'games_in_sample': games_count,
            'data_quality_tier': 'low',
            
            # Source tracking (still populated!)
            **self.build_source_tracking_fields(),
            
            # Early season flags
            'early_season_flag': True,
            'insufficient_data_reason': (
                f"Only {games_count} games available, need 15"
            ),
            
            'processed_at': datetime.now(UTC).isoformat()
        }
        
        placeholders.append(placeholder)
    
    self.transformed_data = placeholders
```

### Example: Early Season Record

```json
{
  "team_abbr": "BOS",
  "analysis_date": "2024-10-28",
  
  // All metrics NULL
  "paint_pct_allowed_last_15": null,
  "mid_range_pct_allowed_last_15": null,
  "three_pt_pct_allowed_last_15": null,
  "defensive_rating_last_15": null,
  "strongest_zone": null,
  "weakest_zone": null,
  
  // Context
  "games_in_sample": 3,
  "data_quality_tier": "low",
  
  // Source tracking still works
  "source_team_defense_last_updated": "2024-10-28T23:05:00Z",
  "source_team_defense_rows_found": 90,
  "source_team_defense_completeness_pct": 100.0,
  
  // Early season flag
  "early_season_flag": true,
  "insufficient_data_reason": "Only 3 games available, need 15"
}
```

---

## Usage

### Command Line Execution

#### Basic Usage
```bash
# Activate environment
cd ~/code/nba-stats-scraper
source .venv/bin/activate
export GCP_PROJECT_ID="nba-props-platform"

# Run for specific date
python data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py \
  --analysis_date 2025-01-27
```

#### With Options
```bash
# Specify season year explicitly
python data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py \
  --analysis_date 2025-01-27 \
  --season_year 2024

# Dry run (no database writes)
python data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py \
  --analysis_date 2025-01-27 \
  --dry-run

# Verbose logging
python data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py \
  --analysis_date 2025-01-27 \
  --log-level DEBUG
```

### Scheduled Execution (Production)

#### Cloud Run Job Configuration

```yaml
name: team-defense-zone-analysis-processor
description: Aggregate team defensive performance by court zone

schedule:
  cron: "0 23 * * *"  # Daily at 11:00 PM
  timezone: America/New_York

resources:
  limits:
    memory: 2Gi
    cpu: "2"
  
timeout: 600s  # 10 minutes max

environment:
  - name: GCP_PROJECT_ID
    value: nba-props-platform
  - name: PYTHONUNBUFFERED
    value: "1"

command:
  - python
  - data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py
  - --analysis_date
  - "{{execution_date}}"

# Run early in Phase 4 (before player processors)
priority: high
```

#### Execution Order

```
10:00 PM - Phase 3 processors complete
           ↓
11:00 PM - Team Defense Zone Analysis (Phase 4) ← THIS PROCESSOR
11:05 PM - Team Offense Zone Analysis (Phase 4)
11:10 PM - Player Shot Zone Analysis (Phase 4)
           ↓
12:00 AM - Player Daily Cache (Phase 4)
           ↓
6:00 AM  - Phase 5 Prediction Systems start
```

### Python API

```python
from data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor import (
    TeamDefenseZoneAnalysisProcessor
)
from datetime import date

# Initialize processor
processor = TeamDefenseZoneAnalysisProcessor()

# Set options
processor.set_opts({
    'analysis_date': date(2025, 1, 27),
    'season_year': 2024,
    'run_id': 'manual-run-001'
})

# Run full pipeline
processor.run()

# Check results
print(f"Successfully processed: {len(processor.transformed_data)} teams")
print(f"Failed: {len(processor.failed_entities)} teams")

# Get statistics
stats = processor.get_precompute_stats()
print(f"Teams processed: {stats['teams_processed']}")
print(f"League avg sample: {stats['league_avg_teams_in_sample']} teams")
```

---

## Integration with Player Predictions

### How Players Use This Data

Player prediction models use team defense data to adjust for opponent strength:

```python
def predict_player_points(player, opponent_team):
    """Predict points considering opponent defense."""
    
    # Get player's scoring tendencies
    player_zones = get_player_shot_zones(player)
    # {'paint': 0.45, 'mid_range': 0.30, 'three_pt': 0.25}
    
    # Get opponent's defensive strength by zone
    opponent_defense = get_team_defense_zones(opponent_team)
    # {'paint_vs_league': -2.2, 'mid_range_vs_league': -1.5, ...}
    
    # Calculate zone-specific adjustments
    paint_adjustment = calculate_zone_adjustment(
        player_rate=player_zones['paint'],
        defense_vs_league=opponent_defense['paint_vs_league']
    )
    # If player shoots 45% in paint, opponent allows 2.2pp less than league
    # → Tougher matchup, reduce prediction
    
    mid_adjustment = calculate_zone_adjustment(
        player_rate=player_zones['mid_range'],
        defense_vs_league=opponent_defense['mid_range_vs_league']
    )
    
    three_adjustment = calculate_zone_adjustment(
        player_rate=player_zones['three_pt'],
        defense_vs_league=opponent_defense['three_pt_defense_vs_league_avg']
    )
    
    # Weight adjustments by player's shot distribution
    total_adjustment = (
        paint_adjustment * player_zones['paint'] +
        mid_adjustment * player_zones['mid_range'] +
        three_adjustment * player_zones['three_pt']
    )
    
    # Apply to base prediction
    base_prediction = player.points_avg_last_10
    adjusted_prediction = base_prediction * (1 + total_adjustment)
    
    return adjusted_prediction
```

### Example Matchup Analysis

```python
# Jayson Tatum vs Boston Celtics defense
player = "tatumja01"
opponent = "BOS"

player_zones = {
    'paint_rate': 0.35,      # 35% of shots in paint
    'mid_range_rate': 0.25,   # 25% mid-range
    'three_pt_rate': 0.40     # 40% from three
}

boston_defense = {
    'paint_vs_league': -2.2,      # Elite paint defense
    'mid_range_vs_league': -1.5,  # Above average
    'three_pt_vs_league': 0.1     # League average
}

# Tatum's primary zone (paint) faces elite defense
# → Expect tougher scoring night
# → Reduce points prediction by ~5%
```

---

## Monitoring

### Key Metrics to Track

#### 1. Processing Completeness

```sql
-- How many teams processed today?
SELECT 
  COUNT(DISTINCT team_abbr) as teams_processed,
  AVG(source_team_defense_completeness_pct) as avg_completeness,
  SUM(CASE WHEN early_season_flag THEN 1 ELSE 0 END) as early_season_count,
  SUM(CASE WHEN games_in_sample >= 15 THEN 1 ELSE 0 END) as teams_with_full_sample
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = CURRENT_DATE();

-- Expected: 30 teams processed, 100% completeness, 30 with full sample (if not early season)
```

#### 2. Data Quality Distribution

```sql
-- Distribution of defensive ratings
SELECT
  ROUND(defensive_rating_last_15, 0) as def_rating_bucket,
  COUNT(*) as team_count
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = CURRENT_DATE()
  AND early_season_flag IS NOT TRUE
GROUP BY 1
ORDER BY 1;

-- Expected: Reasonable spread from 100-120 defensive rating
```

#### 3. League Average Validation

```sql
-- Verify league averages are centered
WITH vs_league AS (
  SELECT
    AVG(paint_defense_vs_league_avg) as avg_paint_vs_league,
    AVG(mid_range_defense_vs_league_avg) as avg_mid_vs_league,
    AVG(three_pt_defense_vs_league_avg) as avg_three_vs_league
  FROM nba_precompute.team_defense_zone_analysis
  WHERE analysis_date = CURRENT_DATE()
    AND early_season_flag IS NOT TRUE
)
SELECT 
  ROUND(avg_paint_vs_league, 2) as paint_centered,
  ROUND(avg_mid_vs_league, 2) as mid_centered,
  ROUND(avg_three_vs_league, 2) as three_centered
FROM vs_league;

-- Expected: All values near 0.0 (within ±1.0 percentage points)
```

#### 4. Strength/Weakness Distribution

```sql
-- What zones are identified as strongest/weakest?
SELECT
  strongest_zone,
  COUNT(*) as team_count
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = CURRENT_DATE()
  AND early_season_flag IS NOT TRUE
GROUP BY 1
ORDER BY 2 DESC;

-- Expected: Roughly balanced distribution across paint/mid_range/perimeter
```

#### 5. Source Freshness

```sql
-- Is source data fresh?
SELECT 
  MAX(source_team_defense_last_updated) as last_updated,
  TIMESTAMP_DIFF(
    CURRENT_TIMESTAMP(), 
    MAX(source_team_defense_last_updated), 
    HOUR
  ) as age_hours
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = CURRENT_DATE();

-- Expected: < 24 hours old
```

### Alert Conditions

Configure alerts for these conditions:

| Condition | Threshold | Severity | Action |
|-----------|-----------|----------|--------|
| Missing teams | < 30 teams | 🔴 Critical | Check dependency |
| Low completeness | < 95% | 🟡 Warning | Check source processor |
| Stale source | > 72 hours | 🟡 Warning | Check upstream pipeline |
| League avg not centered | > ±2.0 pp | 🟡 Warning | Check calculation |
| Processing failure | Processor crashes | 🔴 Critical | Check logs and retry |
| Processing time | > 5 minutes | 🟡 Warning | Optimize or investigate |

### Dashboard Queries

```sql
-- Daily Team Defense Dashboard
WITH daily_stats AS (
  SELECT
    analysis_date,
    COUNT(*) as total_teams,
    SUM(CASE WHEN early_season_flag THEN 1 ELSE 0 END) as early_season_teams,
    AVG(defensive_rating_last_15) as avg_def_rating,
    AVG(paint_pct_allowed_last_15) as avg_paint_pct,
    AVG(three_pt_pct_allowed_last_15) as avg_three_pct,
    AVG(source_team_defense_completeness_pct) as avg_completeness
  FROM nba_precompute.team_defense_zone_analysis
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY 1
)
SELECT
  analysis_date,
  total_teams,
  early_season_teams,
  ROUND(avg_def_rating, 1) as avg_def_rating,
  ROUND(avg_paint_pct * 100, 1) as avg_paint_pct,
  ROUND(avg_three_pct * 100, 1) as avg_three_pct,
  ROUND(avg_completeness, 1) as avg_completeness_pct
FROM daily_stats
ORDER BY analysis_date DESC;
```

---

## Testing

### Unit Tests

**Location:** `tests/processors/precompute/team_defense_zone_analysis/test_unit.py`

**Run unit tests:**
```bash
cd ~/code/nba-stats-scraper
pytest tests/processors/precompute/team_defense_zone_analysis/test_unit.py -v
```

**Expected coverage (21 tests):**
- ✅ Zone defense calculations (FG%, per-game metrics)
- ✅ League average calculations
- ✅ Vs league average calculations (percentage points)
- ✅ Strength/weakness identification
- ✅ Data quality tier determination
- ✅ Edge cases (zero attempts, missing data)
- ✅ Source tracking field generation
- ✅ Dependency configuration

**Example test:**
```python
def test_vs_league_average_calculations(self, processor):
    """Test vs league average percentage point calculations."""
    # Team allows 57.1% in paint, league average is 58.0%
    # Should return -0.9 (better defense)
    
    zone_metrics = processor._calculate_zone_defense(team_data, 15)
    
    assert zone_metrics['paint_vs_league'] == pytest.approx(-0.9, abs=0.1)
    # Negative = Better than league (allowing lower FG%)
```

### Integration Tests

**Location:** `tests/processors/precompute/team_defense_zone_analysis/test_integration.py`

**Run integration tests:**
```bash
pytest tests/processors/precompute/team_defense_zone_analysis/test_integration.py -v
```

**Expected coverage (8 tests):**
- ✅ Full end-to-end processing flow (5 teams)
- ✅ Early season placeholder generation
- ✅ Insufficient games handling
- ✅ Custom per_team_game_count dependency check
- ✅ Missing critical dependency error handling
- ✅ Stale data warning (continues processing)
- ✅ Source tracking integration (v4.0)

**Example test:**
```python
def test_successful_processing(self, processor, mock_team_defense_data):
    """Test successful end-to-end processing."""
    # Setup with 5 teams, 15 games each
    processor.opts = {
        'analysis_date': date(2025, 1, 27),
        'season_year': 2024
    }
    
    # Execute
    processor.extract_raw_data()
    processor.calculate_precompute()
    
    # Verify
    assert len(processor.transformed_data) == 5
    
    bos_data = next(t for t in processor.transformed_data if t['team_abbr'] == 'BOS')
    assert bos_data['games_in_sample'] == 15
    assert bos_data['paint_pct_allowed_last_15'] is not None
    assert bos_data['strongest_zone'] in ['paint', 'mid_range', 'perimeter']
```

### Manual Testing

```bash
# Test with real data for recent date
python data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py \
  --analysis_date 2025-01-27

# Check results
bq query --use_legacy_sql=false '
SELECT 
  team_abbr,
  paint_pct_allowed_last_15,
  paint_defense_vs_league_avg,
  strongest_zone,
  weakest_zone,
  games_in_sample
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = "2025-01-27"
ORDER BY defensive_rating_last_15
LIMIT 10
'
```

### Validation Queries

After processing, validate output:

```sql
-- 1. Check record count
SELECT COUNT(*) as total_teams
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = '2025-01-27';
-- Expected: 30 teams

-- 2. Check no NULL values in key fields (except early season)
SELECT 
  COUNTIF(team_abbr IS NULL) as null_team,
  COUNTIF(paint_pct_allowed_last_15 IS NULL) as null_paint_pct,
  COUNTIF(defensive_rating_last_15 IS NULL) as null_def_rating,
  COUNTIF(strongest_zone IS NULL) as null_strongest
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = '2025-01-27'
  AND early_season_flag IS NOT TRUE;
-- Expected: All zeros

-- 3. Check reasonable ranges
SELECT 
  MIN(paint_pct_allowed_last_15) as min_paint_pct,
  MAX(paint_pct_allowed_last_15) as max_paint_pct,
  MIN(defensive_rating_last_15) as min_def_rating,
  MAX(defensive_rating_last_15) as max_def_rating
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = '2025-01-27'
  AND early_season_flag IS NOT TRUE;
-- Expected: paint 50-70%, def rating 100-120

-- 4. Check source completeness
SELECT 
  AVG(source_team_defense_completeness_pct) as avg_completeness,
  MIN(source_team_defense_completeness_pct) as min_completeness
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = '2025-01-27';
-- Expected: Avg 100%, min >= 95%

-- 5. Spot check specific teams
SELECT 
  team_abbr,
  paint_defense_vs_league_avg,
  mid_range_defense_vs_league_avg,
  three_pt_defense_vs_league_avg,
  strongest_zone,
  weakest_zone
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = '2025-01-27'
  AND team_abbr IN ('BOS', 'LAL', 'GSW', 'MIA')
ORDER BY team_abbr;
-- Manually verify values make sense
```

---

## Troubleshooting

### Common Issues and Solutions

#### Issue: No teams processed

**Symptoms:**
```sql
SELECT COUNT(*) FROM nba_precompute.team_defense_zone_analysis 
WHERE analysis_date = CURRENT_DATE();
-- Returns: 0
```

**Check:**
1. Is `team_defense_game_summary` populated?
   ```sql
   SELECT 
     defending_team_abbr,
     COUNT(*) as game_count
   FROM nba_analytics.team_defense_game_summary
   WHERE game_date <= CURRENT_DATE()
   GROUP BY 1
   HAVING COUNT(*) >= 15;
   -- Expected: 25-30 teams with 15+ games
   ```

2. Check for early season:
   ```sql
   SELECT 
     CURRENT_DATE() as today,
     '2024-10-22' as season_start,
     DATE_DIFF(CURRENT_DATE(), '2024-10-22', DAY) as days_since_start;
   -- If < 14 days, early season behavior is expected
   ```

**Solution:**
- Run upstream processor (team_defense_game_summary from Phase 3)
- If early season: Expected behavior, placeholders should be written
- Verify season start date is correct

---

#### Issue: League averages not centered around zero

**Symptoms:**
```sql
SELECT 
  AVG(paint_defense_vs_league_avg) as avg_paint_vs_league
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = CURRENT_DATE()
  AND early_season_flag IS NOT TRUE;
-- Returns: 3.5 (expected ~0.0)
```

**Diagnose:**
```sql
-- Check league average calculation
SELECT 
  team_abbr,
  paint_pct_allowed_last_15,
  paint_defense_vs_league_avg
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = CURRENT_DATE()
  AND early_season_flag IS NOT TRUE
ORDER BY team_abbr;
```

**Possible causes:**
1. League average calculation used too few teams (<10)
2. Calculation error in processor
3. Data quality issue in source table

**Solution:**
- Check processor logs for league average calculation
- Verify `league_avg_lookback_days` is set correctly (default 30)
- Check if enough teams have sufficient data for league average

---

#### Issue: Specific team missing

**Find missing team:**
```sql
-- All 30 NBA teams
WITH all_teams AS (
  SELECT team_abbr 
  FROM UNNEST(['ATL','BOS','BRK','CHA','CHI','CLE','DAL','DEN','DET','GSW',
               'HOU','IND','LAC','LAL','MEM','MIA','MIL','MIN','NOP','NYK',
               'OKC','ORL','PHI','PHX','POR','SAC','SAS','TOR','UTA','WAS']) 
  AS team_abbr
)
SELECT 
  t.team_abbr,
  COUNT(DISTINCT tds.game_id) as games_in_source
FROM all_teams t
LEFT JOIN nba_analytics.team_defense_game_summary tds
  ON t.team_abbr = tds.defending_team_abbr
  AND tds.game_date <= CURRENT_DATE()
LEFT JOIN nba_precompute.team_defense_zone_analysis tdza
  ON t.team_abbr = tdza.team_abbr
  AND tdza.analysis_date = CURRENT_DATE()
WHERE tdza.team_abbr IS NULL
GROUP BY 1
ORDER BY 2 DESC;
```

**Common reasons:**
1. **< 15 games** - Team hasn't played enough games yet
2. **Data missing in source** - Check team_defense_game_summary
3. **Processing error** - Check `failed_entities` in logs

**Solution:**
- For <15 games: Normal if early season
- For missing source data: Check Phase 3 processor
- For errors: Check processor logs and rerun

---

#### Issue: Strengths/weaknesses seem incorrect

**Symptoms:**
```sql
SELECT team_abbr, strongest_zone, weakest_zone
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = CURRENT_DATE()
  AND team_abbr = 'BOS';
-- Returns: strongest = 'perimeter', weakest = 'paint'
-- But Celtics are known for elite paint protection!
```

**Diagnose:**
```sql
-- Check the actual percentages
SELECT 
  team_abbr,
  paint_pct_allowed_last_15,
  paint_defense_vs_league_avg,
  mid_range_pct_allowed_last_15,
  mid_range_defense_vs_league_avg,
  three_pt_pct_allowed_last_15,
  three_pt_defense_vs_league_avg
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date = CURRENT_DATE()
  AND team_abbr = 'BOS';
```

**Verify logic:**
- Strongest zone = Most **negative** vs_league_avg (lowest FG% relative to league)
- Weakest zone = Most **positive** vs_league_avg (highest FG% relative to league)

**Solution:**
- Check if league averages are correct
- Verify calculation logic in processor
- Consider 15-game sample may not represent season trend

---

#### Issue: High variation day-to-day

**Symptoms:**
```sql
-- Check day-over-day changes
WITH daily AS (
  SELECT 
    team_abbr,
    analysis_date,
    paint_pct_allowed_last_15,
    LAG(paint_pct_allowed_last_15) OVER (
      PARTITION BY team_abbr ORDER BY analysis_date
    ) as prev_paint_pct
  FROM nba_precompute.team_defense_zone_analysis
  WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
)
SELECT 
  team_abbr,
  ABS(paint_pct_allowed_last_15 - prev_paint_pct) * 100 as pct_point_change
FROM daily
WHERE prev_paint_pct IS NOT NULL
  AND ABS(paint_pct_allowed_last_15 - prev_paint_pct) > 0.05
ORDER BY pct_point_change DESC;
-- Large changes (>5 percentage points) may indicate issues
```

**Expected behavior:**
- Rolling 15-game window should be relatively stable
- 1-2 percentage point changes are normal (one game drops off, one added)
- >5 percentage point changes warrant investigation

**Possible causes:**
1. Very strong/weak defensive game dropped off the 15-game window
2. Data quality issue in source table
3. Calculation error

**Solution:**
- Check source data for the team on outlier dates
- Verify rolling window logic is correct
- Consider if actual team performance changed significantly

---

#### Issue: Performance degradation

**Symptoms:**
- Processor takes > 5 minutes to complete
- Timeouts in Cloud Run

**Check processing time by step:**
```python
# Add timing logs to processor
logger.info(f"Extract started at {datetime.now()}")
self.extract_raw_data()
logger.info(f"Extract completed at {datetime.now()}")

logger.info(f"Calculate started at {datetime.now()}")
self.calculate_precompute()
logger.info(f"Calculate completed at {datetime.now()}")
```

**Optimize:**
1. Check if source table has grown significantly
2. Add indexes to source table if needed
3. Increase Cloud Run resources:
   ```yaml
   memory: 4Gi  # Up from 2Gi
   cpu: "4"     # Up from 2
   ```

---

### Debugging Checklist

When troubleshooting, go through this checklist:

- [ ] Processor completed successfully (no crashes)
- [ ] team_defense_game_summary is populated
- [ ] At least 25 teams have 15+ games
- [ ] Source data is < 72 hours old
- [ ] Check if early season (< 14 days since season start)
- [ ] All 30 teams in output
- [ ] Source completeness > 95%
- [ ] League averages centered around 0
- [ ] Reasonable value ranges (FG%, ratings)
- [ ] Strengths/weaknesses make logical sense
- [ ] Check failed_entities in logs if teams missing

---

## Files Structure

```
data_processors/precompute/team_defense_zone_analysis/
├── __init__.py                                    # Package initialization
├── team_defense_zone_analysis_processor.py        # Main processor (850 lines)
└── README.md                                      # This file

schemas/bigquery/precompute/
└── team_defense_zone_analysis.sql                 # BigQuery schema

tests/processors/precompute/team_defense_zone_analysis/
├── __init__.py
├── test_unit.py                                   # Unit tests (21 tests)
├── test_integration.py                            # Integration tests (8 tests)
├── test_validation.py                             # Validation tests (BigQuery)
└── run_tests.py                                   # Test runner script
```

---

## Related Documentation

### Core Documentation
- **Schema:** `schemas/bigquery/precompute/team_defense_zone_analysis.sql`
- **Dependency Tracking:** `docs/Dependency_Tracking_v4_Design.md`
- **Phase 4 Guide:** `docs/Phase_4_Processor_Quick_Start.md`

### Related Processors
- **team_defense_game_summary** - Phase 3 (source data)
- **team_offense_zone_analysis** - Phase 4 (parallel)
- **player_shot_zone_analysis** - Phase 4 (parallel)

### Base Classes
- **PrecomputeProcessorBase:** `data_processors/precompute/precompute_base.py`
- **BaseProcessor:** `data_processors/base/base_processor.py`

---

## Success Criteria

Your processor is working correctly when:

✅ **Completeness:** All 30 NBA teams have records (or placeholders if early season)  
✅ **Freshness:** Source data < 72 hours old  
✅ **Quality:** 95%+ source completeness across all teams  
✅ **Accuracy:** Spot-check 5 teams shows calculations match manual verification  
✅ **League Averages:** vs_league_avg fields average to ~0.0 (within ±1.0 pp)  
✅ **Timeliness:** Processor completes in < 5 minutes  
✅ **Tests:** 21/21 unit tests pass, 8/8 integration tests pass  
✅ **Stability:** Day-over-day changes < 5 percentage points  

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Nov 1, 2025 | Initial release with all tests passing |

---

## Support

### Questions or Issues?

1. **Check this README first** - Most common issues covered
2. **Review logs** - Check Cloud Run logs for errors
3. **Run validation queries** - Verify data quality
4. **Check dependencies** - Ensure team_defense_game_summary has data
5. **Test manually** - Run processor locally with recent date

### Contact

- **System Owner:** [Your team]
- **Documentation:** This README + schema file
- **Issue Tracker:** [Your project management tool]

---

**Last Updated:** November 1, 2025  
**Status:** Production Ready ✅  
**Tests:** All 29 tests passing (21 unit + 8 integration)