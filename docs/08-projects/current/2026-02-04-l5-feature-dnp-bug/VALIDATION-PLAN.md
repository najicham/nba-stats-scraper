# L5 Feature Bug - Comprehensive Validation Plan

**Date:** 2026-02-04
**Session:** 113
**Scope:** Validate EVERY feature in ML feature store against source tables

## Validation Strategy

We will spot-check **5 random players from November 2025** and validate ALL 37 features against their source tables. This thorough approach will:
1. Verify the L5/L10 bug is the only issue
2. Check if other features have similar bugs
3. Validate fallback logic for all feature types
4. Ensure data quality across all sources

## Test Cases Selection

### Sample Date: 2025-11-15 (Mid-November, after cold start)

**Why this date:**
- After initial season bootstrap (Nov 4-9)
- Stable pipeline operation
- Players have 10+ games of history
- Good representation of normal operation

### Sample Players (Random Selection)

We'll select players across different tiers to test various scenarios:
1. **Star player** (30+ PPG) - Tests high-volume scorer
2. **Starter** (15-25 PPG) - Tests typical rotation player
3. **Role player** (8-15 PPG) - Tests bench rotation
4. **DNP-prone player** - Tests DNP handling explicitly
5. **Two-way player** - Tests edge cases (limited games)

## Feature Validation Matrix

### Feature 0-4: Recent Performance (Phase 4 → Phase 3 → Default)

| Feature | Field Name | Phase 4 Source | Phase 3 Source | Validation Query |
|---------|-----------|----------------|----------------|------------------|
| 0 | points_avg_last_5 | player_daily_cache | player_game_summary (L5 avg) | Manual calc from last 5 games |
| 1 | points_avg_last_10 | player_daily_cache | player_game_summary (L10 avg) | Manual calc from last 10 games |
| 2 | points_avg_season | player_daily_cache | player_game_summary (season avg) | AVG(points) for season |
| 3 | points_std_last_10 | player_daily_cache | player_game_summary (L10 std) | STDDEV(points) for last 10 |
| 4 | games_in_last_7_days | player_daily_cache | upcoming_player_game_context | COUNT games in 7 days |

### Feature 5-8: Composite Factors (Phase 4 ONLY)

| Feature | Field Name | Source Table | Validation |
|---------|-----------|--------------|------------|
| 5 | fatigue_score | player_composite_factors | Check value in [0, 100] |
| 6 | shot_zone_mismatch_score | player_composite_factors | Check value in [-20, 20] |
| 7 | pace_score | player_composite_factors | Check value in [-20, 20] |
| 8 | usage_spike_score | player_composite_factors | Check value in [-20, 20] |

### Feature 9-12: Calculated Features

| Feature | Field Name | Calculation | Validation |
|---------|-----------|-------------|------------|
| 9 | rest_advantage | player.days_rest - opponent.days_rest | Verify from upcoming_player_game_context |
| 10 | injury_risk | Status mapping (available=0, out=3) | Verify from player_status field |
| 11 | recent_trend | L5 split comparison | Verify first 3 vs last 2 games |
| 12 | minutes_change | L10 mins - season mins | Verify from minutes fields |

### Feature 13-17: Matchup Context

| Feature | Field Name | Source | Validation |
|---------|-----------|--------|------------|
| 13 | opponent_def_rating | team_defense_zone_analysis | Check opponent's defensive rating |
| 14 | opponent_pace | team_defense_zone_analysis | Check opponent's pace |
| 15 | home_game | upcoming_player_game_context | Boolean (1.0 or 0.0) |
| 16 | back_to_back | upcoming_player_game_context | Boolean (1.0 or 0.0) |
| 17 | season_phase | upcoming_player_game_context | Enum (0=pre, 1=regular, 2=post) |

### Feature 18-24: Shot Zones & Team Context

| Feature | Field Name | Source | Validation |
|---------|-----------|--------|------------|
| 18 | paint_rate_last_10 | player_shot_zone_analysis | % of shots in paint |
| 19 | mid_range_rate_last_10 | player_shot_zone_analysis | % of mid-range shots |
| 20 | three_pt_rate_last_10 | player_shot_zone_analysis | % of 3-pt shots |
| 21 | pct_free_throw | Calculated (FT makes / total points) | Verify from last 10 games |
| 22 | team_pace_last_10 | player_daily_cache | Team's offensive pace |
| 23 | team_off_rating_last_10 | player_daily_cache | Team's offensive rating |
| 24 | team_win_pct | Calculated (wins / games) | Verify from team_offense_game_summary |

### Feature 25-32: V8 Model Features

| Feature | Field Name | Source | Validation |
|---------|-----------|--------|------------|
| 25 | vegas_points_line | Raw betting tables | Current DraftKings line |
| 26 | vegas_opening_line | Raw betting tables | Opening line |
| 27 | vegas_line_move | Calculated (current - opening) | Verify subtraction |
| 28 | has_vegas_line | Boolean | 1.0 if line exists, 0.0 otherwise |
| 29 | avg_points_vs_opponent | player_game_summary | AVG vs this opponent (3 years) |
| 30 | games_vs_opponent | player_game_summary | COUNT vs this opponent (3 years) |
| 31 | minutes_avg_last_10 | player_game_summary | AVG minutes (last 30 days) |
| 32 | ppm_avg_last_10 | Calculated (points / minutes) | Verify from last 10 games |

### Feature 33-36: V9 Model Features

| Feature | Field Name | Source | Validation |
|---------|-----------|--------|------------|
| 33 | dnp_rate | Calculated (DNPs / games) | COUNT is_dnp in last 10 |
| 34 | pts_slope_10g | Calculated (linear regression) | Verify trend from last 10 |
| 35 | pts_vs_season_zscore | Calculated (L5 - season) / std | Verify z-score formula |
| 36 | breakout_flag | Calculated (L5 > season + 2*std) | Verify threshold |

## Validation Queries

### Query 1: Get Sample Players

```sql
-- Select 5 diverse players from Nov 15, 2025
WITH player_stats AS (
  SELECT
    player_lookup,
    ROUND(features[OFFSET(0)], 1) as pts_l5,
    ROUND(features[OFFSET(2)], 1) as pts_season,
    data_source,
    feature_quality_score
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date = '2025-11-15'
    AND features[OFFSET(2)] > 0  -- Has season data
)
SELECT
  player_lookup,
  pts_l5,
  pts_season,
  data_source,
  feature_quality_score,
  CASE
    WHEN pts_season >= 30 THEN 'star'
    WHEN pts_season >= 15 THEN 'starter'
    WHEN pts_season >= 8 THEN 'role'
    ELSE 'bench'
  END as tier
FROM player_stats
ORDER BY RAND()
LIMIT 5;
```

### Query 2: For Each Player - Get All 37 Features

```sql
-- Get ML feature store record
SELECT
  player_lookup,
  game_date,
  game_id,
  features,
  data_source,
  feature_quality_score
FROM nba_predictions.ml_feature_store_v2
WHERE player_lookup = '{PLAYER}'
  AND game_date = '2025-11-15';
```

### Query 3: Validate Each Feature Against Source

See detailed queries in VALIDATION-QUERIES.sql (to be created).

## Validation Checklist

For EACH of the 5 sample players:

### Phase 1: Recent Performance (Features 0-4)
- [ ] Feature 0 (L5): Manual calculation matches?
- [ ] Feature 1 (L10): Manual calculation matches?
- [ ] Feature 2 (Season): Manual calculation matches?
- [ ] Feature 3 (Std): Manual calculation matches?
- [ ] Feature 4 (Games 7d): Count matches?

### Phase 2: Composite Factors (Features 5-8)
- [ ] Feature 5: Value in valid range?
- [ ] Feature 6: Value in valid range?
- [ ] Feature 7: Value in valid range?
- [ ] Feature 8: Value in valid range?

### Phase 3: Calculated (Features 9-12)
- [ ] Feature 9: Rest calculation correct?
- [ ] Feature 10: Injury risk mapping correct?
- [ ] Feature 11: Trend calculation correct?
- [ ] Feature 12: Minutes change correct?

### Phase 4: Matchup (Features 13-17)
- [ ] Feature 13: Opponent def rating matches?
- [ ] Feature 14: Opponent pace matches?
- [ ] Feature 15: Home game boolean correct?
- [ ] Feature 16: Back-to-back boolean correct?
- [ ] Feature 17: Season phase correct?

### Phase 5: Shot Zones (Features 18-24)
- [ ] Feature 18: Paint rate matches?
- [ ] Feature 19: Mid-range rate matches?
- [ ] Feature 20: Three-pt rate matches?
- [ ] Feature 21: FT percentage correct?
- [ ] Feature 22: Team pace matches?
- [ ] Feature 23: Team off rating matches?
- [ ] Feature 24: Win percentage correct?

### Phase 6: V8 Features (Features 25-32)
- [ ] Feature 25: Vegas line matches raw table?
- [ ] Feature 26: Opening line matches?
- [ ] Feature 27: Line move = current - opening?
- [ ] Feature 28: Has line boolean correct?
- [ ] Feature 29: Avg vs opponent correct?
- [ ] Feature 30: Games vs opponent count correct?
- [ ] Feature 31: Minutes L10 correct?
- [ ] Feature 32: PPM calculation correct?

### Phase 7: V9 Features (Features 33-36)
- [ ] Feature 33: DNP rate correct?
- [ ] Feature 34: Points slope correct?
- [ ] Feature 35: Z-score calculation correct?
- [ ] Feature 36: Breakout flag logic correct?

## Pass/Fail Criteria

### Individual Feature
- **PASS:** Value within 0.1 of expected (for floats) or exact match (for booleans/enums)
- **FAIL:** Value off by >0.1 or wrong type

### Overall Validation
- **PASS:** ≥95% of features pass for all 5 players
- **INVESTIGATE:** 90-95% pass - some features need attention
- **FAIL:** <90% pass - systematic issues exist

## Results Documentation

Results will be documented in:
1. **VALIDATION-RESULTS.md** - Summary by player and feature
2. **VALIDATION-QUERIES.sql** - All validation queries used
3. **ISSUES-FOUND.md** - List of any additional bugs discovered

## Timeline

- **Phase 1:** Select sample players (5 min)
- **Phase 2:** Run validation queries (30 min)
- **Phase 3:** Analyze results (15 min)
- **Phase 4:** Document findings (10 min)
- **Total:** ~60 minutes

## Success Metrics

After validation:
1. Know exact scope of L5/L10 bug (confirmed to only those features)
2. Confidence in other 35 features (95%+ pass rate)
3. List of any additional bugs to fix
4. Updated spot-check-features skill with better validation

---

**Status:** Ready to execute
**Next:** Run Query 1 to select sample players
