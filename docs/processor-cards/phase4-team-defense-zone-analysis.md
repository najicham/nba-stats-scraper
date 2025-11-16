# Team Defense Zone Analysis Processor - Quick Reference

**Last Updated**: 2025-11-15
**Verified**: ✅ Code and tests verified against source

---

## Essential Facts

| Attribute | Value |
|-----------|-------|
| **Type** | Phase 4 - Precompute |
| **Schedule** | Nightly at 11:00 PM (runs FIRST in Phase 4) |
| **Duration** | ~2 minutes (30 teams) |
| **Priority** | **High** - Required for Phase 5 Week 1 |
| **Status** | ✅ Production Ready |

---

## Code & Tests

| Component | Location | Size |
|-----------|----------|------|
| **Processor** | `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py` | 804 lines |
| **Schema** | `schemas/bigquery/precompute/team_defense_zone_analysis.sql` | 30 fields |
| **Tests** | `tests/processors/precompute/team_defense_zone_analysis/` | **45 total** |
| | - Unit tests | 21 tests |
| | - Integration tests | 8 tests |
| | - Validation tests | 16 tests |

---

## Dependencies (v4.0 Tracking)

```
Phase 3 Analytics:
  └─ team_defense_game_summary (CRITICAL) - Last 15 games defensive stats

Consumers (Phase 4):
  ├─ player_composite_factors - Shot zone mismatch score
  └─ player_shot_zone_analysis - Used for matchup calculations

Consumers (Phase 5):
  └─ All prediction systems - Defensive matchup context
```

---

## What It Does

1. **Primary Function**: Aggregates team defensive performance by shot zone over last 15 games
2. **Key Output**: One row per team with paint/mid-range/three-point defense metrics
3. **Value**: Identifies defensive weaknesses for player matchup analysis

---

## Key Metrics Calculated

### 1. Paint Defense vs League Average
```python
# How much better/worse than league at defending paint
paint_defense_vs_league = team_paint_pct_allowed - league_avg_paint_pct

# Positive = worse defense (allowing more)
# Negative = better defense (allowing less)
```
- **Range**: -10.0 to +10.0 percentage points
- **Example**: +3.0 = allows 3% more than league (weak paint defense)

### 2. Strongest/Weakest Zone Identification
```python
# Find team's best and worst defensive zones
zones = {
    'paint': paint_defense_vs_league_avg,
    'mid_range': mid_range_defense_vs_league_avg,
    'perimeter': three_pt_defense_vs_league_avg
}
strongest_zone = min(zones)  # Most negative
weakest_zone = max(zones)    # Most positive
```
- **Values**: 'paint', 'mid_range', 'perimeter'
- **Example**: Weakest = 'paint' (opponent paint scorers exploit this)

### 3. League Average Calculation
```python
# Calculate from all teams with sufficient data
if teams_with_15_games >= 10:
    league_avg = mean(all_teams_paint_pct)
else:
    league_avg = 0.580  # Hardcoded early season default
```
- **Range**: 0.550 - 0.610 (paint), 0.350 - 0.380 (three-point)
- **Updates**: Dynamically calculated from teams with 15+ games

---

## Output Schema Summary

**Total Fields**: 30

| Category | Count | Examples |
|----------|-------|----------|
| Identifiers | 2 | team_abbr, analysis_date |
| Paint Defense | 5 | paint_pct_allowed, paint_attempts_per_game, paint_defense_vs_league |
| Mid-Range Defense | 4 | mid_range_pct_allowed, mid_range_defense_vs_league |
| Three-Point Defense | 4 | three_pt_pct_allowed, three_pt_defense_vs_league |
| Overall Metrics | 4 | defensive_rating, opponent_ppg, games_in_sample |
| Strengths/Weaknesses | 2 | strongest_zone, weakest_zone |
| Data Quality | 2 | data_quality_tier, calculation_notes |
| Source Tracking (v4.0) | 3 | source_team_defense_* |
| Early Season | 2 | early_season_flag, insufficient_data_reason |
| Metadata | 2 | processed_at, created_at |

---

## Health Check Query

```sql
-- Run this to verify processor health
SELECT
  COUNT(DISTINCT team_abbr) as teams_processed,
  AVG(games_in_sample) as avg_games_sampled,
  AVG(source_team_defense_completeness_pct) as avg_completeness,
  COUNT(CASE WHEN data_quality_tier = 'high' THEN 1 END) as high_quality_count,
  MAX(processed_at) as last_run
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE();

-- Expected Results:
-- teams_processed: 30 (all NBA teams)
-- avg_games_sampled: 15 (mid-season)
-- avg_completeness: > 95%
-- high_quality_count: > 25 teams
-- last_run: < 24 hours old
```

---

## Common Issues & Quick Fixes

### Issue 1: Low Completeness (<90%)
**Symptom**: `source_team_defense_completeness_pct < 90%`
**Diagnosis**:
```sql
-- Find teams with incomplete data
SELECT team_abbr, games_in_sample,
       source_team_defense_completeness_pct
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND source_team_defense_completeness_pct < 90
ORDER BY source_team_defense_completeness_pct;
```
**Fix**:
1. Check if `team_defense_game_summary` has last 15 games
2. Verify Phase 3 processor ran successfully
3. Early season: Expected (teams haven't played 15 games yet)

### Issue 2: League Averages Using Defaults
**Symptom**: `calculation_notes` mentions "using default league averages"
**Diagnosis**:
```sql
-- Check how many teams have calculation notes
SELECT COUNT(*) as teams_with_defaults,
       calculation_notes
FROM `nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND calculation_notes LIKE '%default%'
GROUP BY calculation_notes;
```
**Fix**:
1. Expected in first 2-3 weeks of season (<10 teams with 15 games)
2. Mid-season: Investigate why teams lack historical data
3. Run Phase 3 backfill if needed

### Issue 3: Processing Takes >5 Minutes
**Symptom**: Slow performance
**Fix**:
1. Check Phase 3 table partitioning (should be by game_date)
2. Verify clustering on defending_team_abbr
3. Check for BigQuery streaming buffer locks

---

## Processing Flow

```
team_defense_game_summary ─→ TEAM DEFENSE ZONE ANALYSIS ─┬─→ player_composite_factors
  (last 15 games)              (30 teams nightly)         └─→ Phase 5 predictions
```

**Timing**:
- Runs: 11:00 PM nightly (FIRST in Phase 4 sequence)
- Waits for: Team Defense Game Summary (Phase 3)
- Must complete before: Player Composite Factors can run
- Total window: Must finish by 11:15 PM (15 min window)

---

## Monitoring Alerts

| Alert | Threshold | Severity |
|-------|-----------|----------|
| Teams processed | < 30 | Critical |
| Avg completeness | < 90% | Warning |
| Avg completeness | < 85% | Critical |
| Processing time | > 5 min | Warning |
| Source age | > 24 hrs | Warning |
| Source age | > 72 hrs | Critical |
| Early season teams | > 20 (after week 3) | Warning |

---

## Quick Links

- 📄 **Detailed Documentation**: [Wiki - Team Defense Zone Analysis Processor]
- 🗂️ **Schema Definition**: `schemas/bigquery/precompute/team_defense_zone_analysis.sql`
- 🧪 **Test Suite**: `tests/processors/precompute/team_defense_zone_analysis/`
- 📊 **Related Processors**:
  - ↑ Upstream: Team Defense Game Summary (Phase 3)
  - ↓ Downstream: Player Composite Factors (Phase 4)
  - 🔄 Peer: Player Shot Zone Analysis (can run in parallel)

---

## Notes

- **15-Game Window**: Balances recency with statistical significance (~3 weeks of data)
- **League Average**: Dynamically calculated from teams with sufficient data
- **Early Season Strategy**: Uses hardcoded defaults when <10 teams have 15 games
- **Runs FIRST**: No Phase 4 dependencies, can start immediately at 11 PM
- **Parallel Capable**: Can run simultaneously with Player Shot Zone Analysis

---

**Card Version**: 1.0
**Created**: 2025-11-15
**Verified Against**: Code commit 71f4bde
