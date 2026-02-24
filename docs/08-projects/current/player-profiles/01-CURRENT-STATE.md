# Player Profiles — Current State of Player-Level Data

## What Already Exists

The system already has substantial player-level data spread across multiple tables. The gap isn't raw data — it's that none of this is assembled into a persistent profile or used as a holistic player characterization.

### Shot Zone Analysis (Most Relevant)

**Table:** `nba_precompute.player_shot_zone_analysis`
**Processor:** `data_processors/precompute/player_shot_zone_analysis/`

Already computed per player, per game date:

| Field | Description |
|-------|-------------|
| `paint_rate_last_10` / `_last_20` | % of shots taken in the paint |
| `mid_range_rate_last_10` / `_last_20` | % of shots from mid-range |
| `three_pt_rate_last_10` / `_last_20` | % of shots from three |
| `paint_pct_last_10` / `_last_20` | FG% in the paint |
| `mid_range_pct_last_10` / `_last_20` | FG% from mid-range |
| `three_pt_pct_last_10` / `_last_20` | 3PT% |
| `paint_attempts_per_game` | Volume in paint per game |
| `mid_range_attempts_per_game` | Volume from mid-range per game |
| `three_pt_attempts_per_game` | Volume from three per game |
| `assisted_rate_last_10` | % of made FGs that were assisted |
| `unassisted_rate_last_10` | % of made FGs self-created |
| `primary_scoring_zone` | 4 buckets: paint / mid_range / perimeter / balanced |

**Classification logic** (in `_determine_primary_zone_static`):
- paint_rate >= 40% → `paint`
- three_pt_rate >= 40% → `perimeter`
- mid_range_rate >= 35% → `mid_range`
- else → `balanced`

### Player Game Summary (Raw Per-Game Data)

**Table:** `nba_analytics.player_game_summary`

Rich per-game data that could feed profiles but currently only feeds rolling aggregates:

| Field | Notes |
|-------|-------|
| `points`, `fg_attempts`, `fg_makes` | Basic scoring |
| `three_pt_attempts`, `three_pt_makes` | 3PT volume/efficiency |
| `ft_attempts`, `ft_makes` | FT drawing (FT rate = FTA/FGA) |
| `paint_attempts`, `paint_makes` | Shot zone from PBP |
| `mid_range_attempts`, `mid_range_makes` | Shot zone from PBP |
| `offensive_rebounds`, `defensive_rebounds` | Raw counts (no rates) |
| `assists`, `steals`, `blocks`, `turnovers` | Playmaking / defense |
| `usage_rate`, `ts_pct`, `efg_pct` | Efficiency |
| `assisted_fg_makes`, `unassisted_fg_makes` | Shot creation (BigDataBall source) |
| `starter_flag` | Started the game or not |
| `and1_count` | Physical play indicator |

### Player Daily Cache

**Table:** `nba_precompute.player_daily_cache`

Pre-aggregated for quick access during prediction:

| Field | Notes |
|-------|-------|
| `points_avg_last_5/10/season` | Rolling averages |
| `points_std_last_10` | Scoring volatility |
| `minutes_avg_last_10`, `usage_rate_last_10` | Playing time |
| `ts_pct_last_10` | Efficiency |
| `games_played_season` | Experience this season |
| `primary_scoring_zone` | Passthrough from shot zone analysis |
| `paint_rate_last_10`, `three_pt_rate_last_10` | Shot distribution |
| `assisted_rate_last_10` | Shot creation |

### Player Registry

**Table:** `nba_reference.nba_players_registry`

| Field | Notes |
|-------|-------|
| `position` | G / F / C only. No PG/SG/SF/PF distinction |
| `games_played`, `first_game_date`, `last_game_date` | Activity tracking |

**Missing:** Height, weight, age (age is in `upcoming_player_game_context` only), years of experience.

### Existing Tier/Style Classifications (Ad-Hoc, Not Stored)

Two inconsistent classification schemes exist:

**`pick_angle_builder.py`** — Usage-based tier from prop line:
```
star: line >= 25    starter: line >= 18
role:  line >= 12    bench:  line < 12
```

**`player_season_exporter.py`** — Style profile for frontend:
```
interior:  paint >= 50%    perimeter: three >= 50%
mid_range: mid >= 30%      balanced:  else
```

These differ from the Phase 4 `primary_scoring_zone` thresholds (paint >= 40%, three >= 40%, mid >= 35%) — three separate systems, three different cutoffs.

### What Reaches the ML Feature Vector Today

Of all the above, only these player-characterization signals make it into the 54-feature vector:

| Feature Index | Field | Notes |
|---------------|-------|-------|
| 0-3 | `points_avg_last_5/10/season`, `points_std_last_10` | Scoring level and volatility |
| 5 | `fatigue_score` | Composite (not really archetype) |
| 6 | `shot_zone_mismatch_score` | Uses primary_scoring_zone vs opponent |
| 18-20 | `pct_paint`, `pct_mid_range`, `pct_three` | Shot zone rates |
| 31-32 | `minutes_avg_last_10`, `ppm_avg_last_10` | Volume/efficiency |
| 33 | `dnp_rate` | Availability |
| 34-36 | `pts_slope_10g`, `pts_vs_season_zscore`, `breakout_flag` | Trajectory |

**NOT in the feature vector** despite existing in BQ:
- Position / starter flag
- Assists, rebounds, steals, blocks (any non-points stat)
- FT drawing rate
- Self-creation rate (assisted vs unassisted)
- Usage rate (only in rolling stats, not as a stable feature)
- Scoring consistency beyond std dev (no CV, no over/under tendency)

### Data That Does NOT Exist Anywhere

| Missing Data | Notes |
|-------------|-------|
| Height / weight / wingspan | No physical data in the system |
| PG/SG/SF/PF distinction | Registry only has G/F/C |
| Per-100-possession rates | Only raw counts exist |
| Historical over/under rates | Not tracked per player |
| Multi-season data | Feature store only has current season |
| Drive frequency | Would need PBP event parsing |
| Clutch performance splits | 4th quarter minutes in cache but no scoring splits |

## 4 Dead Features in V12

Features 41, 42, 47, and 50 always emit their default values:

| Index | Name | Default | Why Dead |
|-------|------|---------|----------|
| 41 | `spread_magnitude` | 5.0 | Data pipeline never completed |
| 42 | `implied_team_total` | 112.0 | Data pipeline never completed |
| 47 | `teammate_usage_available` | 0.0 | Always returns 0 |
| 50 | `multi_book_line_std` | 0.5 | Always returns 0.5 |

These are prime candidates for replacement with profile-derived features.
