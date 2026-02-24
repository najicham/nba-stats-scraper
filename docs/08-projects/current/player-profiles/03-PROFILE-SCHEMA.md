# Player Profiles — Profile Schema

## Overview

A player profile is a persistent, daily-updated characterization stored in BigQuery. It captures who a player is and how they tend to perform, distinct from the ephemeral rolling stats that already exist in `player_daily_cache`.

## Proposed Table: `nba_precompute.player_profiles`

### Identity

| Field | Type | Description |
|-------|------|-------------|
| `player_lookup` | STRING | Primary key (normalized name) |
| `universal_player_id` | STRING | Cross-reference ID |
| `game_date` | DATE | Partition key — profile as of this date |
| `team_abbr` | STRING | Current team |
| `season` | STRING | e.g., "2025-26" |
| `games_in_profile` | INT64 | Number of games feeding the profile |

### Scoring Zone Profile

Derived from `player_shot_zone_analysis` and `player_game_summary`.

| Field | Type | Description |
|-------|------|-------------|
| `paint_rate_season` | NUMERIC(5,2) | Season-long paint shot rate |
| `mid_range_rate_season` | NUMERIC(5,2) | Season-long mid-range rate |
| `three_pt_rate_season` | NUMERIC(5,2) | Season-long 3PT rate |
| `paint_pct_season` | NUMERIC(5,3) | Season FG% in paint |
| `mid_range_pct_season` | NUMERIC(5,3) | Season mid-range FG% |
| `three_pt_pct_season` | NUMERIC(5,3) | Season 3PT% |
| `ft_rate_season` | NUMERIC(5,3) | FTA / FGA season-long |
| `scoring_zone_archetype` | STRING | interior / perimeter / mid_range / balanced |

### Shot Creation

| Field | Type | Description |
|-------|------|-------------|
| `assisted_rate_season` | NUMERIC(5,2) | % of made FGs that were assisted |
| `unassisted_rate_season` | NUMERIC(5,2) | % self-created |
| `creation_archetype` | STRING | self_creator / catch_and_shoot / mixed |

### Scoring Consistency

| Field | Type | Description |
|-------|------|-------------|
| `points_cv_season` | NUMERIC(5,3) | Coefficient of variation (std/mean) |
| `points_cv_last_20` | NUMERIC(5,3) | Rolling 20-game CV |
| `over_rate_season` | NUMERIC(5,3) | % of games above season avg |
| `bust_rate_season` | NUMERIC(5,3) | % of games < 60% of season avg |
| `boom_rate_season` | NUMERIC(5,3) | % of games > 140% of season avg |
| `consistency_archetype` | STRING | metronome / normal / volatile |
| `scoring_floor` | NUMERIC(5,1) | 10th percentile scoring output |
| `scoring_ceiling` | NUMERIC(5,1) | 90th percentile scoring output |

### Usage and Role

| Field | Type | Description |
|-------|------|-------------|
| `usage_rate_season` | NUMERIC(5,2) | Season USG% |
| `minutes_avg_season` | NUMERIC(5,1) | Season minutes per game |
| `starter_rate_season` | NUMERIC(5,3) | % of games started |
| `usage_archetype` | STRING | primary / secondary / role_player / low_usage |

### Free Throw Drawing

| Field | Type | Description |
|-------|------|-------------|
| `ft_attempt_rate` | NUMERIC(5,3) | FTA per FGA |
| `ft_points_pct` | NUMERIC(5,3) | % of total points from FTs |
| `ft_drawing_archetype` | STRING | high / moderate / low |

### Rebounding and Playmaking (Non-Points Stats)

| Field | Type | Description |
|-------|------|-------------|
| `oreb_per_game` | NUMERIC(4,1) | Offensive rebounds per game |
| `dreb_per_game` | NUMERIC(4,1) | Defensive rebounds per game |
| `assists_per_game` | NUMERIC(4,1) | Assists per game |
| `turnovers_per_game` | NUMERIC(4,1) | Turnovers per game |
| `ast_to_ratio` | NUMERIC(4,2) | Assist-to-turnover ratio |
| `steals_per_game` | NUMERIC(4,1) | Steals per game |
| `blocks_per_game` | NUMERIC(4,1) | Blocks per game |

### Profile Stability Tracking

| Field | Type | Description |
|-------|------|-------------|
| `zone_shift_l20` | NUMERIC(5,3) | How much shot zone distribution changed over last 20 games |
| `usage_shift_l20` | NUMERIC(5,3) | How much usage changed (detect role changes) |
| `structural_change_flag` | BOOLEAN | Trade, long absence, or coach change detected |
| `profile_confidence` | STRING | high (30+ games) / medium (15-29) / low (< 15) |

### Betting-Relevant Derived Fields

| Field | Type | Description |
|-------|------|-------------|
| `historical_over_rate` | NUMERIC(5,3) | Over rate on predictions (from `prediction_accuracy`) |
| `historical_hr_at_edge3` | NUMERIC(5,3) | Hit rate on edge 3+ picks |
| `historical_pick_count` | INT64 | Total graded edge 3+ picks |
| `prediction_difficulty` | STRING | easy / normal / hard (based on CV + historical HR) |

## Season-Level Baseline Table (Optional)

**Table:** `nba_precompute.player_profile_baselines`

For multi-season analysis. One row per player per season. Same fields as above but computed over the full season. Allows questions like:
- "Does this player typically improve post-All-Star break?"
- "Is their current season an outlier vs career norms?"

This is lower priority than the daily rolling profile but valuable for structural context.

## Relationship to Existing Tables

```
player_game_summary (raw per-game)
    ↓ aggregated into
player_shot_zone_analysis (L10/L20 shot zones)
player_daily_cache (L5/L10/season scoring)
    ↓ assembled into
player_profiles (holistic characterization)    ← NEW
    ↓ feeds into
ml_feature_store_v2 (prediction features)
signal evaluation (filtering/annotation)
```

The profile sits between the existing precompute tables and the feature store. It doesn't replace `player_daily_cache` or `player_shot_zone_analysis` — it consumes them and adds derived characterization that doesn't exist today.
