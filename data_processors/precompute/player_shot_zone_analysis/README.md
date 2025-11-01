# Player Shot Zone Analysis Processor

**Phase 4 Precompute Processor #2**

## Overview

Analyzes each player's shot distribution and shooting efficiency by court zone (paint, mid-range, three-point) over their recent games. Pre-calculated nightly for fast Phase 5 predictions and matchup analysis.

## Quick Facts

| Attribute | Value |
|-----------|-------|
| **Type** | Precompute Processor |
| **Priority** | High (Required for Phase 5 Week 1) |
| **Schedule** | Nightly at 11:15 PM |
| **Duration** | 5-8 minutes (450 players) |
| **Dependencies** | Phase 3: `nba_analytics.player_game_summary` |
| **Output** | `nba_precompute.player_shot_zone_analysis` |
| **Version** | 1.0 with v4.0 dependency tracking |
| **Status** | ✅ Production Ready |

---

## What It Does

### Shot Zones Analyzed

1. **Paint** (≤8 feet from basket)
   - Attempts and makes
   - Field goal percentage
   - Volume per game

2. **Mid-Range** (9+ feet, 2-point shots)
   - Attempts and makes
   - Field goal percentage
   - Volume per game

3. **Three-Point** (Beyond the arc)
   - Attempts and makes
   - Three-point percentage
   - Volume per game

### Key Calculations

**Shot Distribution** - What % of total shots from each zone?
```
paint_rate = (paint_attempts / total_attempts) × 100
mid_range_rate = (mid_range_attempts / total_attempts) × 100
three_pt_rate = (three_pt_attempts / total_attempts) × 100
```

**Shooting Efficiency** - What FG% from each zone?
```
paint_pct = paint_makes / paint_attempts
mid_range_pct = mid_range_makes / mid_range_attempts
three_pt_pct = three_pt_makes / three_pt_attempts
```

**Volume Per Game** - How many shots from each zone per game?
```
paint_attempts_pg = total_paint_attempts / games_in_sample
mid_range_attempts_pg = total_mid_range_attempts / games_in_sample
three_pt_attempts_pg = total_three_pt_attempts / games_in_sample
```

**Shot Creation** - Assisted vs self-created shots
```
assisted_rate = (assisted_fg_makes / total_makes) × 100
unassisted_rate = (unassisted_fg_makes / total_makes) × 100
```

**Primary Scoring Zone** - Player's preferred shooting area
```python
if paint_rate >= 40%:
    primary_zone = 'paint'
elif three_pt_rate >= 40%:
    primary_zone = 'perimeter'
elif mid_rate >= 35%:
    primary_zone = 'mid_range'
else:
    primary_zone = 'balanced'
```

---

## Processing Windows

| Window | Games | Purpose |
|--------|-------|---------|
| **Primary** | Last 10 games | Main analysis for predictions |
| **Trend** | Last 20 games | Compare recent vs longer trend |

- **10-game window**: More responsive to recent changes (role changes, hot/cold streaks)
- **20-game window**: More stable baseline (less affected by variance)

---

## Data Quality Tiers

| Tier | Games | Description |
|------|-------|-------------|
| **high** | ≥10 games | Full confidence in metrics |
| **medium** | 7-9 games | Usable but limited confidence |
| **low** | <7 games | Insufficient for reliable predictions |

### Sample Quality Assessment

| Quality | 10-Game Window | 20-Game Window |
|---------|---------------|----------------|
| **excellent** | 10 games | 20 games |
| **good** | 7-9 games | 14-19 games |
| **limited** | 5-6 games | 10-13 games |
| **insufficient** | <5 games | <10 games |

---

## Edge Cases & Special Handling

### Early Season (< 10 games available)

**Scenario:** Player has <10 games available (rookies, returning from injury, season start)

**Behavior:** Write placeholder rows with:
- All metrics set to NULL
- `early_season_flag = TRUE`
- `insufficient_data_reason` populated (e.g., "Only 3 games available, need 10")
- Source tracking still recorded
- `sample_quality = 'insufficient'`

**Recovery:** Once player reaches 10 games, next run will replace placeholder with actual analysis

**Duration:** Typically first 14 days of season

### Injured Players (< 10 recent games)

**Scenario:** Player returning from injury or limited playing time

**Behavior:**
- Added to `failed_entities` list
- Reason: "Only X games, need 10"
- Can retry: TRUE (will process when more games available)

**Not Saved:** No record written until 10 games available

### Zero Attempts in a Zone

**Scenario:** Player takes 0 mid-range shots over 10 games (common for modern 3-and-D players)

**Behavior:**
- Zone percentage = NULL (prevents division by zero)
- Zone rate = 0.0% (included in distribution)
- Other zones calculated normally

**Example:**
```json
{
  "mid_range_attempts_per_game": 0.0,
  "mid_range_pct_last_10": null,      // NULL - can't calculate
  "mid_range_rate_last_10": 0.0,      // 0% of shots
  "paint_pct_last_10": 0.625,         // Still calculated
  "three_pt_pct_last_10": 0.367       // Still calculated
}
```

### Stale Source Data

| Age | Behavior |
|-----|----------|
| < 24 hours | Normal processing |
| 24-72 hours | Warning notification, continues processing |
| > 72 hours | Error, blocks processing |

**Notification:** Sent via Slack + Email when data is stale

---

## v4.0 Dependency Tracking

### Source Tracked

| Source | Prefix | Check Type | Min Required |
|--------|--------|-----------|--------------|
| `player_game_summary` | `source_player_game` | per_player_game_count | 10 games per player |

### Tracking Fields (per record)

```sql
-- When source was last processed
source_player_game_last_updated TIMESTAMP

-- How many game records found for this player
source_player_game_rows_found INT64

-- Percentage of expected games found
source_player_game_completeness_pct NUMERIC(5,2)
```

### Quality Thresholds

| Metric | Threshold | Action |
|--------|-----------|--------|
| **Source Age** | >24 hours | Warning |
| **Source Age** | >72 hours | Fail (block processing) |
| **Completeness** | <85% | Warning |
| **Active Players** | <400 | Warning |

---

## Complete Schema Reference

### Identifiers
| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `player_lookup` | STRING | Player identifier | 'lebronjames' |
| `universal_player_id` | STRING | Universal player ID | 'lebronjames_001' |
| `analysis_date` | DATE | Date of analysis | '2025-10-30' |

### Shot Distribution (Last 10 Games)
| Field | Type | Description | Range |
|-------|------|-------------|-------|
| `paint_rate_last_10` | FLOAT64 | % of shots from paint | 0-100 |
| `mid_range_rate_last_10` | FLOAT64 | % of shots from mid-range | 0-100 |
| `three_pt_rate_last_10` | FLOAT64 | % of shots from three | 0-100 |
| `total_shots_last_10` | INT64 | Total shot attempts | 0+ |
| `games_in_sample_10` | INT64 | Games in sample | 0-15 |
| `sample_quality_10` | STRING | Quality tier | excellent/good/limited/insufficient |

### Shooting Efficiency (Last 10 Games)
| Field | Type | Description | Range | Notes |
|-------|------|-------------|-------|-------|
| `paint_pct_last_10` | FLOAT64 | FG% in paint | 0.0-1.0 | NULL if 0 attempts |
| `mid_range_pct_last_10` | FLOAT64 | FG% mid-range | 0.0-1.0 | NULL if 0 attempts |
| `three_pt_pct_last_10` | FLOAT64 | 3P% | 0.0-1.0 | NULL if 0 attempts |

### Volume (Per Game)
| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `paint_attempts_per_game` | FLOAT64 | Paint attempts per game | 8.2 |
| `mid_range_attempts_per_game` | FLOAT64 | Mid-range attempts per game | 3.7 |
| `three_pt_attempts_per_game` | FLOAT64 | Three-point attempts per game | 6.1 |

### Trend Comparison (Last 20 Games)
| Field | Type | Description |
|-------|------|-------------|
| `paint_rate_last_20` | FLOAT64 | Paint rate over 20 games |
| `paint_pct_last_20` | FLOAT64 | Paint FG% over 20 games |
| `games_in_sample_20` | INT64 | Games in 20-game sample |
| `sample_quality_20` | STRING | Quality of 20-game sample |

### Shot Creation
| Field | Type | Description | Range |
|-------|------|-------------|-------|
| `assisted_rate_last_10` | FLOAT64 | % of makes that were assisted | 0-100 |
| `unassisted_rate_last_10` | FLOAT64 | % of makes unassisted | 0-100 |

### Player Profile
| Field | Type | Description | Values |
|-------|------|-------------|--------|
| `player_position` | STRING | Player position | PG/SG/SF/PF/C (currently NULL) |
| `primary_scoring_zone` | STRING | Primary shot zone | paint/mid_range/perimeter/balanced |
| `data_quality_tier` | STRING | Data quality | high/medium/low |
| `calculation_notes` | STRING | Processing notes | NULL or error messages |

### v4.0 Source Tracking
| Field | Type | Description |
|-------|------|-------------|
| `source_player_game_last_updated` | TIMESTAMP | When source data last updated |
| `source_player_game_rows_found` | INT64 | Rows found in source |
| `source_player_game_completeness_pct` | FLOAT64 | Source completeness % |

### Early Season Handling
| Field | Type | Description |
|-------|------|-------------|
| `early_season_flag` | BOOLEAN | TRUE if < 10 games available |
| `insufficient_data_reason` | STRING | Reason for insufficient data |

### Metadata
| Field | Type | Description |
|-------|------|-------------|
| `created_at` | TIMESTAMP | Record creation time |
| `processed_at` | TIMESTAMP | Processing completion time |

### Example Record

```json
{
  "player_lookup": "lebronjames",
  "universal_player_id": "lebronjames_001",
  "analysis_date": "2025-10-30",
  
  "paint_rate_last_10": 45.2,
  "mid_range_rate_last_10": 19.8,
  "three_pt_rate_last_10": 35.0,
  "total_shots_last_10": 181,
  "games_in_sample_10": 10,
  "sample_quality_10": "excellent",
  
  "paint_pct_last_10": 0.623,
  "mid_range_pct_last_10": 0.412,
  "three_pt_pct_last_10": 0.367,
  
  "paint_attempts_per_game": 8.2,
  "mid_range_attempts_per_game": 3.7,
  "three_pt_attempts_per_game": 6.1,
  
  "paint_rate_last_20": 44.8,
  "paint_pct_last_20": 0.618,
  "games_in_sample_20": 20,
  "sample_quality_20": "excellent",
  
  "assisted_rate_last_10": 62.3,
  "unassisted_rate_last_10": 37.7,
  
  "player_position": null,
  "primary_scoring_zone": "paint",
  "data_quality_tier": "high",
  "calculation_notes": null,
  
  "source_player_game_last_updated": "2025-10-30T10:00:00Z",
  "source_player_game_rows_found": 10,
  "source_player_game_completeness_pct": 100.00,
  
  "early_season_flag": false,
  "insufficient_data_reason": null,
  
  "created_at": "2025-10-30T23:15:00Z",
  "processed_at": "2025-10-30T23:15:00Z"
}
```

---

## File Structure

```
data_processors/precompute/player_shot_zone_analysis/
├── __init__.py                              # Package initialization
├── player_shot_zone_analysis_processor.py   # Main processor (625 lines)
└── README.md                                # This file

tests/processors/precompute/player_shot_zone_analysis/
├── __init__.py
├── conftest.py                              # Test configuration
├── run_tests.py                             # Test runner
├── test_unit.py                             # 50 unit tests
├── test_integration.py                      # 10 integration tests
└── test_validation.py                       # 15 validation tests
```

---

## Usage

### Running Locally

```bash
# Set environment
export GCP_PROJECT_ID="nba-props-platform"

# Run for specific date
python player_shot_zone_analysis_processor.py 2025-10-30

# Run for today
python player_shot_zone_analysis_processor.py
```

### Running via Service

```python
from data_processors.precompute.player_shot_zone_analysis import PlayerShotZoneAnalysisProcessor

# Initialize
processor = PlayerShotZoneAnalysisProcessor()
processor.opts = {'analysis_date': date(2025, 10, 30)}

# Execute full flow
processor.run()

# Or step-by-step
processor.extract_raw_data()
processor.calculate_precompute()
processor.save_precompute()
```

### Integration with Workflow

```python
# In Phase 4 coordinator
processors = [
    TeamDefenseZoneAnalysisProcessor(),  # Runs first (11:00 PM)
    PlayerShotZoneAnalysisProcessor(),   # Runs second (11:15 PM)
    # ... other processors
]

for processor in processors:
    processor.opts = {'analysis_date': current_date}
    success = processor.run()
    if not success:
        logger.error(f"Processor {processor.__class__.__name__} failed")
```

---

## Dependencies

### Python Packages

```
google-cloud-bigquery>=3.0.0
pandas>=1.5.0
python-dateutil>=2.8.0
sentry-sdk>=1.14.0
```

### Environment Variables

```bash
export GCP_PROJECT_ID="nba-props-platform"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
```

### BigQuery Tables

**Required (Input):**
- `nba_analytics.player_game_summary` - Must be current (<24 hours old)

**Created (Output):**
- `nba_precompute.player_shot_zone_analysis` - Created by this processor

**Monitoring:**
- `nba_processing.precompute_processor_runs` - Execution logs
- `nba_processing.precompute_failures` - Failed entities
- `nba_processing.precompute_data_issues` - Quality issues

---

## Performance

### Processing Time

| Players | Expected Time | Notes |
|---------|---------------|-------|
| 450 | 5-8 minutes | Full roster |
| 100 | 1-2 minutes | Testing subset |
| 10 | <30 seconds | Single team |

### BigQuery Costs

| Operation | Data Scanned | Cost (per run) |
|-----------|-------------|----------------|
| Extract | ~500 MB | ~$0.0025 |
| Save | ~5 MB | ~$0.00003 |
| **Total per day** | ~505 MB | **~$0.0025** |
| **Monthly** | ~15 GB | **~$0.075** |

### Storage

| Metric | Value |
|--------|-------|
| Row size | ~1.4 KB |
| Rows per day | ~450 players |
| Daily storage | ~630 KB |
| 90-day storage | ~55 MB |
| Annual storage | ~225 MB |

---

## Testing

### Test Suite

| Test Type | Tests | Duration | Purpose |
|-----------|-------|----------|---------|
| **Unit** | 50 tests | ~5 seconds | Individual method validation |
| **Integration** | 10 tests | ~10 seconds | End-to-end processor flow |
| **Validation** | 15 tests | ~30-60 seconds | Real BigQuery data quality |

### Test Coverage
- **Code Coverage:** >95%
- **Methods Tested:** All calculation methods, edge cases, error handling
- **Data Validation:** Schema, quality, completeness, accuracy

### Running Tests

```bash
cd tests/processors/precompute/player_shot_zone_analysis/

# Run all tests
python run_tests.py

# Run by type
python run_tests.py unit           # Fast, mocked
python run_tests.py integration    # End-to-end, mocked BigQuery
python run_tests.py validation     # Real BigQuery (after processor runs)

# Run with coverage report
python run_tests.py --coverage

# Verbose output
python run_tests.py --verbose
```

### What Tests Validate

**Unit Tests:**
- Shot zone calculations (rates, percentages, volume)
- Primary zone identification logic
- Data quality tier assignment
- NULL handling (zero attempts)
- Sample quality assessment
- Edge cases (perfect shooting, zero shooting, single game)

**Integration Tests:**
- Complete processing flow (extract → calculate → save)
- Dependency checking integration
- Early season placeholder creation
- Error handling and recovery
- Multiple player processing
- Source tracking propagation

**Validation Tests:**
- Output schema correctness
- Data quality (no duplicates, valid ranges)
- Completeness (≥400 players, ≥70% high quality)
- Calculation accuracy (spot checks with real data)
- Data freshness (≤7 days old)
- Edge case handling in production

---

## Monitoring

### Success Criteria

```sql
-- All checks should pass
SELECT 
  COUNT(*) >= 400 as enough_players,              -- At least 400 players
  AVG(source_player_game_completeness_pct) >= 85 as good_completeness,
  COUNTIF(data_quality_tier = 'high') / COUNT(*) >= 0.70 as mostly_high_quality,
  MAX(TIMESTAMP_DIFF(
    CURRENT_TIMESTAMP(), 
    source_player_game_last_updated, 
    HOUR
  )) <= 72 as source_fresh,
  MAX(TIMESTAMP_DIFF(
    CURRENT_TIMESTAMP(),
    processed_at,
    HOUR
  )) <= 24 as recently_processed
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE();
```

### Alert Conditions

| Condition | Threshold | Severity | Action |
|-----------|-----------|----------|--------|
| Players processed | <400 | Error | Check Phase 3 data |
| Avg completeness | <85% | Warning | Investigate missing games |
| High quality data | <70% | Warning | Check game availability |
| Max source age | >72 hours | Error | Run Phase 3 first |
| Early season players | >50 (after week 2) | Warning | Review data pipeline |
| Processing time | >15 minutes | Warning | Optimize or scale |

### Monitoring Queries

**Check recent run status:**
```sql
SELECT 
  processor_name,
  run_date,
  success,
  records_processed,
  duration_seconds,
  data_completeness_pct,
  dependency_check_passed
FROM `nba_processing.precompute_processor_runs`
WHERE processor_name = 'PlayerShotZoneAnalysisProcessor'
ORDER BY run_date DESC
LIMIT 10;
```

**Check data freshness:**
```sql
SELECT 
  analysis_date,
  COUNT(*) as player_count,
  AVG(source_player_game_completeness_pct) as avg_completeness,
  MAX(TIMESTAMP_DIFF(
    CURRENT_TIMESTAMP(), 
    source_player_game_last_updated, 
    HOUR
  )) as hours_since_source_update,
  COUNTIF(early_season_flag) as early_season_count
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY analysis_date
ORDER BY analysis_date DESC;
```

**Identify data quality issues:**
```sql
SELECT 
  player_lookup,
  data_quality_tier,
  games_in_sample_10,
  source_player_game_completeness_pct,
  early_season_flag,
  insufficient_data_reason
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND (
    data_quality_tier != 'high'
    OR source_player_game_completeness_pct < 85
    OR early_season_flag = TRUE
  )
ORDER BY data_quality_tier, source_player_game_completeness_pct;
```

---

## Troubleshooting

### Issue: Low completeness (<85%)

```sql
-- Find which players have incomplete data
SELECT 
  player_lookup, 
  games_in_sample_10,
  source_player_game_rows_found,
  source_player_game_completeness_pct,
  data_quality_tier
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND source_player_game_completeness_pct < 85
ORDER BY source_player_game_completeness_pct;
```
**Fix:** Check if `player_game_summary` is missing recent games. Verify Phase 3 processor ran successfully.

### Issue: Stale source data (>72 hours)

```sql
-- Check source freshness
SELECT 
  player_lookup,
  source_player_game_last_updated,
  TIMESTAMP_DIFF(
    CURRENT_TIMESTAMP(), 
    source_player_game_last_updated, 
    HOUR
  ) as hours_old
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
ORDER BY hours_old DESC
LIMIT 10;
```
**Fix:** Run Phase 3 analytics processor first. Check if Phase 3 scheduler is running.

### Issue: Many early season players (outside first 2 weeks)

```sql
-- Check early season count and reasons
SELECT 
  COUNT(*) as early_season_count,
  insufficient_data_reason,
  COUNT(*) as count_per_reason
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND early_season_flag = TRUE
GROUP BY insufficient_data_reason;
```
**Fix:** Verify `player_game_summary` has sufficient historical data. Check if recent games are being processed.

### Issue: Rates don't sum to 100%

```sql
-- Find players with incorrect rate sums
SELECT 
  player_lookup,
  paint_rate_last_10,
  mid_range_rate_last_10,
  three_pt_rate_last_10,
  (paint_rate_last_10 + mid_range_rate_last_10 + three_pt_rate_last_10) as total_rate
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND ABS((paint_rate_last_10 + mid_range_rate_last_10 + three_pt_rate_last_10) - 100) > 1.0
ORDER BY ABS((paint_rate_last_10 + mid_range_rate_last_10 + three_pt_rate_last_10) - 100) DESC;
```
**Fix:** Check `_calculate_zone_metrics()` method. Verify source data integrity. Run validation tests.

### Issue: Processing timeout (>15 minutes)

**Symptoms:** Processor doesn't complete within expected time

**Possible Causes:**
1. Too many players to process
2. BigQuery slot contention
3. Large data scans

**Fixes:**
- Check BigQuery job queue for competing jobs
- Verify query performance (check execution plans)
- Consider batching players in smaller groups
- Scale up BigQuery slots if needed

---

## Usage in Phase 5

### Zone Matchup Analysis

```sql
-- Find favorable matchups where player's strength meets opponent's weakness
SELECT 
  p.player_lookup,
  p.primary_scoring_zone,
  t.weakest_zone,
  p.paint_pct_last_10 as player_paint_efficiency,
  t.paint_pct_allowed_last_15 as opponent_paint_defense,
  (p.paint_pct_last_10 - t.paint_pct_allowed_last_15) as paint_advantage,
  p.paint_attempts_per_game
FROM `nba_precompute.player_shot_zone_analysis` p
JOIN `nba_precompute.team_defense_zone_analysis` t
  ON p.analysis_date = t.analysis_date
WHERE p.primary_scoring_zone = t.weakest_zone
  AND p.analysis_date = CURRENT_DATE()
  AND p.data_quality_tier = 'high'
ORDER BY paint_advantage DESC
LIMIT 20;
```

### Volume Projection

```sql
-- Project shot volume for tonight's game based on pace
WITH pace_factors AS (
  SELECT 
    team_abbr,
    avg_possessions_per_game / 100 as pace_factor
  FROM `nba_analytics.team_pace_stats`
  WHERE analysis_date = CURRENT_DATE()
)
SELECT 
  p.player_lookup,
  p.paint_attempts_per_game,
  p.three_pt_attempts_per_game,
  pf.pace_factor,
  (p.paint_attempts_per_game * pf.pace_factor) as projected_paint_attempts,
  (p.three_pt_attempts_per_game * pf.pace_factor) as projected_three_attempts,
  ((p.paint_attempts_per_game * p.paint_pct_last_10) + 
   (p.three_pt_attempts_per_game * p.three_pt_pct_last_10 * 1.5)) * pf.pace_factor as projected_points
FROM `nba_precompute.player_shot_zone_analysis` p
JOIN pace_factors pf
  ON pf.team_abbr = p.team_abbr  -- Would need team_abbr added to schema
WHERE p.analysis_date = CURRENT_DATE()
  AND p.data_quality_tier = 'high';
```

### Efficiency Baseline vs Opponent Defense

```sql
-- Compare player efficiency vs specific opponent defense
SELECT 
  p.player_lookup,
  p.primary_scoring_zone,
  p.paint_pct_last_10 as player_paint_pct,
  t.paint_pct_allowed_last_15 as opponent_paint_defense,
  (p.paint_pct_last_10 - t.paint_pct_allowed_last_15) as efficiency_advantage,
  p.three_pt_pct_last_10 as player_three_pct,
  t.three_pt_pct_allowed_last_15 as opponent_three_defense,
  (p.three_pt_pct_last_10 - t.three_pt_pct_allowed_last_15) as three_advantage,
  CASE 
    WHEN (p.paint_pct_last_10 - t.paint_pct_allowed_last_15) > 0.05 THEN 'Strong Paint Matchup'
    WHEN (p.three_pt_pct_last_10 - t.three_pt_pct_allowed_last_15) > 0.03 THEN 'Strong Perimeter Matchup'
    ELSE 'Neutral Matchup'
  END as matchup_assessment
FROM `nba_precompute.player_shot_zone_analysis` p
JOIN `nba_precompute.team_defense_zone_analysis` t
  ON p.analysis_date = t.analysis_date
WHERE p.analysis_date = CURRENT_DATE()
  AND p.data_quality_tier = 'high'
ORDER BY 
  GREATEST(
    (p.paint_pct_last_10 - t.paint_pct_allowed_last_15),
    (p.three_pt_pct_last_10 - t.three_pt_pct_allowed_last_15)
  ) DESC
LIMIT 20;
```

### Trend Detection (Hot/Cold Zones)

```sql
-- Find players with significant recent changes in zone preference or efficiency
SELECT 
  player_lookup,
  primary_scoring_zone,
  paint_rate_last_10,
  paint_rate_last_20,
  (paint_rate_last_10 - paint_rate_last_20) as paint_rate_change,
  paint_pct_last_10,
  paint_pct_last_20,
  (paint_pct_last_10 - paint_pct_last_20) as paint_efficiency_change,
  CASE 
    WHEN (paint_rate_last_10 - paint_rate_last_20) > 10 THEN 'Increasing Paint Usage'
    WHEN (paint_rate_last_10 - paint_rate_last_20) < -10 THEN 'Decreasing Paint Usage'
    WHEN (paint_pct_last_10 - paint_pct_last_20) > 0.10 THEN 'Hot in Paint'
    WHEN (paint_pct_last_10 - paint_pct_last_20) < -0.10 THEN 'Cold in Paint'
    ELSE 'Stable'
  END as trend_description
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND games_in_sample_20 >= 20
  AND data_quality_tier = 'high'
  AND ABS(paint_rate_last_10 - paint_rate_last_20) > 5  -- At least 5% change
ORDER BY ABS(paint_rate_last_10 - paint_rate_last_20) DESC
LIMIT 30;
```

---

## Related Documentation

- **Data Mapping**: [PLAYER_SHOT_ZONE_DATA_MAPPING.md](PLAYER_SHOT_ZONE_DATA_MAPPING.md) - Complete field transformations
- **Schema**: `schemas/bigquery/precompute/player_shot_zone_analysis.sql`
- **Phase 3 Dependency**: `schemas/bigquery/analytics/player_game_summary_tables.sql`
- **Base Class**: `data_processors/precompute/precompute_base.py`
- **Dependency Tracking**: `docs/dependency_tracking_v4_design.md`
- **Team Defense Processor**: Reference implementation (Processor #1)
- **Quick Start Guide**: [PHASE4_PROCESSOR_QUICK_START.md](PHASE4_PROCESSOR_QUICK_START.md)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Oct 30, 2025 | Initial implementation with v4.0 tracking |
| 1.0.1 | Oct 30, 2025 | Fixed save method, added timezone-aware datetimes |

---

## Support

For issues or questions:

1. **Check monitoring queries** - Most issues show up in monitoring
2. **Review test suite** - Tests have examples of correct behavior
3. **Compare with Team Defense** - Similar pattern, proven working
4. **Check Phase 3 health** - Dependency must be healthy
5. **Run validation tests** - Validates real data quality

### Key Files
- **Processor**: `player_shot_zone_analysis_processor.py`
- **Tests**: `tests/processors/precompute/player_shot_zone_analysis/`
- **Logs**: Check Sentry and Cloud Logging for errors
- **Monitoring**: `nba_processing.precompute_processor_runs`

---

**Status:** ✅ Production Ready  
**Test Coverage:** >95%  
**Documentation:** Complete  
**Next Steps:** Monitor nightly runs, validate output quality

*Last Updated: October 30, 2025*