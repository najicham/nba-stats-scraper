# Player Shot Zone Analysis Processor - Quick Reference

**Last Updated**: 2025-11-15
**Verified**: ✅ Code and tests verified against source

---

## Essential Facts

| Attribute | Value |
|-----------|-------|
| **Type** | Phase 4 - Precompute |
| **Schedule** | Nightly at 11:15 PM (parallel with team defense) |
| **Duration** | 5-8 minutes (450 players) |
| **Priority** | **High** - Required for Phase 5 Week 1 |
| **Status** | ✅ Production Ready |

---

## Code & Tests

| Component | Location | Size |
|-----------|----------|------|
| **Processor** | `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py` | 647 lines |
| **Schema** | `schemas/bigquery/precompute/player_shot_zone_analysis.sql` | 32 fields |
| **Tests** | `tests/processors/precompute/player_shot_zone_analysis/` | **78 total** |
| | - Unit tests | 50 tests |
| | - Integration tests | 10 tests |
| | - Validation tests | 18 tests |

---

## Dependencies (v4.0 Tracking)

```
Phase 3 Analytics:
  └─ player_game_summary (CRITICAL) - Shot distribution, efficiency (last 10 games)

Consumers (Phase 4):
  ├─ player_composite_factors - Primary scoring zone for matchup
  └─ player_daily_cache - Copies shot zone tendencies

Consumers (Phase 5):
  └─ All prediction systems - Shot zone matchup analysis
```

---

## What It Does

1. **Primary Function**: Analyzes player shot distribution and efficiency by court zone over last 10 games
2. **Key Output**: One row per player with paint/mid-range/three-point rates and percentages
3. **Value**: Identifies player shooting tendencies for matchup advantage calculations

---

## Key Metrics Calculated

### 1. Shot Distribution (% of Total Shots)
```python
# Calculate what % of shots come from each zone
paint_rate = (paint_attempts / total_attempts) * 100
mid_range_rate = (mid_range_attempts / total_attempts) * 100
three_pt_rate = (three_pt_attempts / total_attempts) * 100
# Should sum to ~100%
```
- **Range**: 0-100% per zone
- **Example**: Paint 45.3%, Mid-range 19.9%, Three-point 34.8%

### 2. Shooting Efficiency by Zone
```python
# Calculate FG% in each zone
paint_pct = paint_makes / paint_attempts
mid_range_pct = mid_range_makes / mid_range_attempts
three_pt_pct = three_pt_makes / three_pt_attempts
```
- **Range**: 0.300 - 0.700 (varies by zone)
- **Example**: Paint 62.2%, Mid-range 41.7%, Three-point 36.5%

### 3. Primary Scoring Zone Logic
```python
# Identify player's preferred shooting area
if paint_rate >= 40:
    primary_zone = 'paint'
elif three_pt_rate >= 40:
    primary_zone = 'perimeter'
elif mid_range_rate >= 30:
    primary_zone = 'mid_range'
else:
    primary_zone = 'balanced'
```
- **Values**: 'paint', 'perimeter', 'mid_range', 'balanced'
- **Example**: Big man = 'paint', Shooter = 'perimeter'

---

## Output Schema Summary

**Total Fields**: 32

| Category | Count | Examples |
|----------|-------|----------|
| Identifiers | 3 | player_lookup, universal_player_id, analysis_date |
| Shot Distribution (10-game) | 6 | paint_rate, mid_range_rate, three_pt_rate, total_shots |
| Efficiency by Zone | 3 | paint_pct, mid_range_pct, three_pt_pct |
| Volume by Zone | 3 | paint_attempts_per_game, mid_range_per_game |
| Shot Distribution (20-game) | 4 | paint_rate_last_20, paint_pct_last_20 (trend comparison) |
| Shot Creation | 2 | assisted_rate, unassisted_rate |
| Player Characteristics | 2 | player_position, primary_scoring_zone |
| Data Quality | 2 | data_quality_tier, calculation_notes |
| Source Tracking (v4.0) | 3 | source_player_game_* |
| Early Season | 2 | early_season_flag, insufficient_data_reason |
| Metadata | 2 | created_at, processed_at |

---

## Health Check Query

```sql
-- Run this to verify processor health
SELECT
  COUNT(DISTINCT player_lookup) as players_processed,
  AVG(source_player_game_completeness_pct) as avg_completeness,
  COUNT(CASE WHEN sample_quality_10 = 'excellent' THEN 1 END) as excellent_count,
  AVG(total_shots_last_10) as avg_shot_volume,
  MAX(processed_at) as last_run
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE();

-- Expected Results:
-- players_processed: 400-450
-- avg_completeness: > 85%
-- excellent_count: > 300 players (10 games)
-- avg_shot_volume: 100-180 shots
-- last_run: < 24 hours old
```

---

## Common Issues & Quick Fixes

### Issue 1: Shot Rates Don't Sum to 100%
**Symptom**: `paint_rate + mid_range_rate + three_pt_rate != 100`
**Diagnosis**:
```sql
-- Find players with incorrect distributions
SELECT player_lookup,
       paint_rate_last_10 + mid_range_rate_last_10 + three_pt_rate_last_10 as total_rate,
       ABS(100 - (paint_rate_last_10 + mid_range_rate_last_10 + three_pt_rate_last_10)) as deviation
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND ABS(100 - (paint_rate_last_10 + mid_range_rate_last_10 + three_pt_rate_last_10)) > 2.0;
```
**Fix**:
1. Check Phase 3 data for missing shot type classifications
2. Verify calculation handles NULL values correctly
3. May indicate data quality issue in source table

### Issue 2: Low Sample Quality
**Symptom**: Many players with `sample_quality_10 = 'limited'` or `'insufficient'`
**Diagnosis**:
```sql
-- Check sample quality distribution
SELECT sample_quality_10, COUNT(*) as player_count
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
GROUP BY sample_quality_10
ORDER BY player_count DESC;
```
**Fix**:
1. Early season: Expected (first 2 weeks)
2. Mid-season: Check if player_game_summary has 10-game history
3. Verify returning from injury players have sufficient data

### Issue 3: Missing Shot Zone Data
**Symptom**: All zone percentages are NULL
**Fix**:
1. Verify `player_game_summary` has shot zone fields populated
2. Check Phase 2 scrapers include shot zone data
3. May require play-by-play data enhancement

---

## Processing Flow

```
player_game_summary ─→ PLAYER SHOT ZONE ─┬─→ player_composite_factors
  (last 10/20 games)     ANALYSIS         ├─→ player_daily_cache
                        (450 players)     └─→ Phase 5 predictions
```

**Timing**:
- Runs: 11:15 PM nightly (can run in PARALLEL with team_defense_zone)
- Waits for: Player Game Summary (Phase 3)
- Must complete before: Player Composite Factors can run
- Total window: 5-8 minutes

---

## Monitoring Alerts

| Alert | Threshold | Severity |
|-------|-----------|----------|
| Players processed | < 400 | Critical |
| Avg completeness | < 85% | Warning |
| Excellent quality | < 300 players | Warning |
| Shot rate deviation | > 5% | Warning |
| Processing time | > 15 min | Warning |
| Early season players | > 50 (after week 2) | Warning |

---

## Quick Links

- 📄 **Detailed Documentation**: [Wiki - Player Shot Zone Analysis Processor]
- 🗂️ **Schema Definition**: `schemas/bigquery/precompute/player_shot_zone_analysis.sql`
- 🧪 **Test Suite**: `tests/processors/precompute/player_shot_zone_analysis/`
- 📊 **Related Processors**:
  - ↑ Upstream: Player Game Summary (Phase 3)
  - ↓ Downstream: Player Composite Factors, Player Daily Cache (Phase 4)
  - 🔄 Peer: Team Defense Zone Analysis (can run in parallel)

---

## Notes

- **10-Game Window**: More responsive to recent changes than 15-game team defense window
- **20-Game Comparison**: Helps identify hot/cold streaks (10-game vs 20-game comparison)
- **Assisted Rate**: >60% = role player (catch and shoot), <40% = shot creator
- **Parallel Capable**: Can run simultaneously with Team Defense Zone Analysis
- **Shot Creation Insight**: Assisted rate distinguishes primary vs secondary scorers

---

**Card Version**: 1.0
**Created**: 2025-11-15
**Verified Against**: Code commit 71f4bde
