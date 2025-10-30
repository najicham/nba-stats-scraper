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
elif mid_rate >= 30%:
    primary_zone = 'mid_range'
else:
    primary_zone = 'balanced'
```

## Processing Windows

| Window | Games | Purpose |
|--------|-------|---------|
| **Primary** | Last 10 games | Main analysis for predictions |
| **Trend** | Last 20 games | Compare recent vs longer trend |

- **10-game window**: More responsive to recent changes (role changes, hot/cold streaks)
- **20-game window**: More stable baseline (less affected by variance)

## Data Quality Tiers

| Tier | Games | Description |
|------|-------|-------------|
| **high** | ≥10 games | Full confidence in metrics |
| **medium** | 7-9 games | Usable but limited confidence |
| **low** | <7 games | Insufficient for reliable predictions |

## Sample Quality Assessment

| Quality | 10-Game Window | 20-Game Window |
|---------|---------------|----------------|
| **excellent** | 10 games | 20 games |
| **good** | 7-9 games | 14-19 games |
| **limited** | 5-6 games | 10-13 games |
| **insufficient** | <5 games | <10 games |

## Early Season Handling

**Scenario:** Player has <10 games available (rookies, returning from injury, season start)

**Behavior:** Write placeholder rows with:
- All metrics set to NULL
- `early_season_flag = TRUE`
- `insufficient_data_reason` populated
- Source tracking still recorded
- `sample_quality = 'insufficient'`

**Recovery:** Once player reaches 10 games, next run will replace placeholder with actual analysis

## v4.0 Dependency Tracking

### Source Tracked

| Source | Prefix | Check Type | Min Required |
|--------|--------|-----------|--------------|
| `player_game_summary` | `source_player_game` | per_player_game_count | 10 games per player |

### Tracking Fields

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

## File Structure

```
data_processors/precompute/player_shot_zone_analysis/
├── __init__.py                              # Package initialization
├── player_shot_zone_analysis_processor.py   # Main processor (625 lines)
└── README.md                                # This file
```

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

# Execute
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
    processor.run()
```

## Dependencies

### Python Packages

```
google-cloud-bigquery>=3.0.0
pandas>=1.5.0
python-dateutil>=2.8.0
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

## Performance

### Processing Time

| Players | Expected Time | Notes |
|---------|---------------|-------|
| 450 | 5-8 minutes | Full roster |
| 100 | 1-2 minutes | Testing subset |
| 10 | <30 seconds | Single team |

### BigQuery Costs

| Operation | Data Scanned | Cost |
|-----------|-------------|------|
| Extract (per run) | ~500 MB | ~$0.0025 |
| Save (per run) | ~5 MB | ~$0.00003 |
| **Total per day** | ~505 MB | **~$0.0025** |

### Storage

| Metric | Value |
|--------|-------|
| Row size | ~1.4 KB |
| Rows per day | ~450 players |
| Daily storage | ~630 KB |
| 90-day storage | ~55 MB |

## Output Schema

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
  
  "assisted_rate_last_10": 62.3,
  "unassisted_rate_last_10": 37.7,
  
  "primary_scoring_zone": "paint",
  "data_quality_tier": "high",
  
  "source_player_game_last_updated": "2025-10-30T10:00:00Z",
  "source_player_game_rows_found": 10,
  "source_player_game_completeness_pct": 100.00,
  
  "early_season_flag": false,
  "processed_at": "2025-10-30T23:15:00Z"
}
```

## Monitoring

### Success Criteria

```sql
-- All checks should pass
SELECT 
  COUNT(*) >= 400 as enough_players,              -- At least 400 players
  AVG(source_player_game_completeness_pct) >= 85 as good_completeness,
  MAX(TIMESTAMP_DIFF(
    CURRENT_TIMESTAMP(), 
    source_player_game_last_updated, 
    HOUR
  )) <= 72 as source_fresh
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE();
```

### Alert Conditions

| Condition | Threshold | Severity |
|-----------|-----------|----------|
| Players processed | <400 | Error |
| Avg completeness | <85% | Warning |
| Max source age | >72 hours | Error |
| Early season players | >50 (after week 2) | Warning |
| Processing time | >15 minutes | Warning |

### Common Issues

**Issue: Low completeness (<85%)**
```sql
-- Find which players have incomplete data
SELECT player_lookup, 
       games_in_sample_10,
       source_player_game_completeness_pct
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND source_player_game_completeness_pct < 85
ORDER BY source_player_game_completeness_pct;
```
**Fix:** Check if `player_game_summary` is missing recent games

**Issue: Stale source data (>72 hours)**
```sql
-- Check source freshness
SELECT MAX(TIMESTAMP_DIFF(
         CURRENT_TIMESTAMP(), 
         source_player_game_last_updated, 
         HOUR
       )) as hours_since_update
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE();
```
**Fix:** Run Phase 3 analytics processor first

**Issue: Many early season players (outside first 2 weeks)**
```sql
-- Check early season count
SELECT COUNT(*) as early_season_count
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND early_season_flag = TRUE;
```
**Fix:** Verify `player_game_summary` has sufficient historical data

## Usage in Phase 5

### Zone Matchup Analysis

```sql
-- Find favorable matchups
SELECT 
  p.player_lookup,
  p.primary_scoring_zone,
  t.weakest_zone,
  p.paint_pct_last_10,
  t.paint_pct_allowed_last_15
FROM `nba_precompute.player_shot_zone_analysis` p
JOIN `nba_precompute.team_defense_zone_analysis` t
  ON p.analysis_date = t.analysis_date
WHERE p.primary_scoring_zone = t.weakest_zone
  AND p.analysis_date = CURRENT_DATE();
```

### Volume Projection

```sql
-- Project shot volume for tonight's game
SELECT 
  player_lookup,
  paint_attempts_per_game * pace_factor as projected_paint_attempts,
  three_pt_attempts_per_game * pace_factor as projected_three_attempts
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE();
```

### Efficiency Baseline

```sql
-- Compare player efficiency vs opponent defense
SELECT 
  p.player_lookup,
  p.paint_pct_last_10 as player_paint_pct,
  t.paint_pct_allowed_last_15 as opponent_paint_defense,
  (p.paint_pct_last_10 - t.paint_pct_allowed_last_15) as efficiency_advantage
FROM `nba_precompute.player_shot_zone_analysis` p
JOIN `nba_precompute.team_defense_zone_analysis` t
  ON p.analysis_date = t.analysis_date
WHERE p.analysis_date = CURRENT_DATE()
ORDER BY efficiency_advantage DESC;
```

## Testing

See `tests/processors/precompute/` for comprehensive test suite:
- Unit tests: Individual method validation
- Integration tests: End-to-end processing
- Validation tests: BigQuery data quality

## Related Documentation

- **Schema**: `schemas/bigquery/precompute/player_shot_zone_analysis.sql`
- **Phase 3 Dependency**: `schemas/bigquery/analytics/player_game_summary_tables.sql`
- **Base Class**: `data_processors/precompute/precompute_base.py`
- **Dependency Tracking**: `docs/dependency_tracking_v4_design.md`
- **Team Defense Processor**: Reference implementation (Processor #1)

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Oct 30, 2025 | Initial implementation with v4.0 tracking |

## Support

For issues or questions:
1. Check monitoring queries above
2. Review test suite for examples
3. Compare with Team Defense processor (similar pattern)
4. Check Phase 3 dependency health

---

**Status:** ✅ Ready for Testing  
**Next Steps:** Create test suite, backfill 30 days, deploy to production