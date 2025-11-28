# NBA Data Pipeline Overview

**Purpose:** Condensed reference of all data sources and their flow through the prediction pipeline
**Use:** Provide as context when discussing data completeness strategy

---

## Pipeline Summary

```
Phase 1 (Scrapers)     →  Phase 2 (Raw)        →  Phase 3 (Analytics)     →  Phase 4 (Features)      →  Phase 5 (Predictions)
33 scrapers               21 BigQuery tables       5 analytics tables         5 precompute tables        5 prediction systems
7 data sources            nba_raw.*               nba_analytics.*            nba_precompute.*           nba_predictions.*
GCS JSON files            ~50 files/day           ~2,000 rows/day            ~1,350 rows/day            ~2,250 predictions/day
```

---

## Phase 1: All Scrapers (33 Total)

### NBA.com (10 scrapers) - Primary Source
| Scraper | Data Type | Key Fields | Update Freq |
|---------|-----------|------------|-------------|
| `nbac_team_boxscore` | Team game totals | points, rebounds, assists, FG%, turnovers | Post-game |
| `nbac_player_boxscore` | Player game stats | points, rebounds, assists, minutes, +/- | Post-game |
| `nbac_play_by_play` | Play-by-play | shot locations, play types, timestamps | Post-game |
| `nbac_gamebook_pdf` | Official box score PDF | Complete stats, parsed from PDF | Post-game |
| `nbac_schedule_api` | Game schedule | game_id, date, teams, time, status | Daily |
| `nbac_schedule_cdn` | Schedule (backup) | Same as above | Daily |
| `nbac_scoreboard_v2` | Live scores | Current scores, game status | Every 30s |
| `nbac_injury_report` | Injury report | Player, status, injury, return date | Daily |
| `nbac_roster` | Team rosters | Player, jersey, position | Weekly |
| `nbac_player_list` | All players | Player IDs, names, teams | Weekly |

### Ball Don't Lie API (6 scrapers) - Reliable Backup
| Scraper | Data Type | Key Fields | Update Freq |
|---------|-----------|------------|-------------|
| `bdl_box_scores` | Game box scores | Team totals per game | Post-game |
| `bdl_player_box_scores` | Player stats | Full player box score | Post-game |
| `bdl_games` | Game info | Scores, status, teams | Post-game |
| `bdl_standings` | Standings | Wins, losses, PCT, streak | Daily |
| `bdl_injuries` | Injuries | Player, status, notes | Daily |
| `bdl_active_players` | Player list | All active players | Weekly |

### Odds API (6 scrapers) - Betting Data
| Scraper | Data Type | Key Fields | Update Freq |
|---------|-----------|------------|-------------|
| `oddsa_events` | Today's games | Game IDs, teams, times | Daily |
| `oddsa_events_his` | Historical games | Past games lookup | On-demand |
| `oddsa_game_lines` | Spreads/totals | Spread, O/U, moneyline | Every 15min |
| `oddsa_game_lines_his` | Historical lines | Past lines | On-demand |
| `oddsa_player_props` | Player props | Points/rebounds/assists lines | Every 15min |
| `oddsa_player_props_his` | Historical props | Past prop lines | On-demand |

### ESPN (3 scrapers) - Backup Source
| Scraper | Data Type | Key Fields | Update Freq |
|---------|-----------|------------|-------------|
| `espn_game_boxscore` | Game box scores | Team and player stats | Post-game |
| `espn_roster` | Rosters | Players per team | Weekly |
| `espn_scoreboard` | Live scores | Current game status | Real-time |

### BettingPros (2 scrapers) - Backup Odds
| Scraper | Data Type | Key Fields | Update Freq |
|---------|-----------|------------|-------------|
| `bp_events` | Games list | Game IDs, matchups | Daily |
| `bp_player_props` | Player props | Backup prop lines | Daily |

### BigDataBall (2 scrapers) - Enhanced Play-by-Play
| Scraper | Data Type | Key Fields | Update Freq |
|---------|-----------|------------|-------------|
| `bigdataball_discovery` | Available games | Which games have PBP | Daily |
| `bigdataball_pbp` | Play-by-play | Shot zones, coordinates | ~2hr post-game |

### Basketball Reference (1 scraper) - Reference Data
| Scraper | Data Type | Key Fields | Update Freq |
|---------|-----------|------------|-------------|
| `br_season_roster` | Historical rosters | Player-team mapping | Quarterly |

### Other (3 scrapers)
| Scraper | Data Type | Key Fields | Update Freq |
|---------|-----------|------------|-------------|
| `nbac_player_movement` | Trades/signings | Player transactions | Daily |
| `nbac_referee_assignments` | Referees | Which refs for which game | Daily |
| `oddsa_team_players` | Player IDs | Odds API player mapping | Weekly |

---

## Phase 2: Raw Tables (21 Tables in `nba_raw`)

| Table | Primary Source | Backup Sources | Key Use |
|-------|---------------|----------------|---------|
| `nbac_team_boxscore` | nbac_team_boxscore | espn_game_boxscore | Team totals per game |
| `nbac_player_boxscore` | nbac_player_boxscore | bdl_player_box_scores | Player stats per game |
| `nbac_gamebook_player_stats` | nbac_gamebook_pdf | - | Official player stats |
| `nbac_play_by_play` | nbac_play_by_play | - | Shot locations |
| `bigdataball_play_by_play` | bigdataball_pbp | - | Enhanced shot zones |
| `nbac_schedule` | nbac_schedule_api | nbac_schedule_cdn | Game schedule |
| `nbac_injury_report` | nbac_injury_report | bdl_injuries | Injury status |
| `bdl_player_boxscores` | bdl_player_box_scores | - | Reliable player stats |
| `bdl_standings` | bdl_standings | - | Team standings |
| `odds_api_game_lines` | oddsa_game_lines | bp_events | Spreads, O/U |
| `odds_api_player_props` | oddsa_player_props | bp_player_props | Player betting lines |
| `espn_team_rosters` | espn_roster | nbac_roster | Current rosters |
| ... | | | |

---

## Phase 3: Analytics Tables (5 Tables in `nba_analytics`)

### `team_offense_game_summary` (~47 fields, per-team-per-game)
**Depends on:** `nba_raw.nbac_team_boxscore`
| Field Category | Key Fields |
|---------------|------------|
| Identifiers | team_abbr, game_id, game_date, opponent_team_abbr, is_home |
| Basic Stats | points, rebounds, assists, turnovers, steals, blocks |
| Shooting | fg_made/attempted, fg3_made/attempted, ft_made/attempted, fg_pct, fg3_pct |
| Advanced | offensive_rating, pace, possessions, effective_fg_pct, true_shooting_pct |
| Source Tracking | source_last_updated, data_quality_score |

### `team_defense_game_summary` (~54 fields, per-team-per-game)
**Depends on:** `nba_raw.nbac_team_boxscore`, `nba_raw.bdl_player_boxscores` (fallback)
| Field Category | Key Fields |
|---------------|------------|
| Identifiers | defending_team_abbr, game_id, game_date, opponent_team_abbr |
| Defense Stats | opponent_points_allowed, opponent_fg_pct, blocks, steals |
| Zone Defense | paint_fg_pct_allowed, midrange_fg_pct_allowed, three_pt_fg_pct_allowed |
| Advanced | defensive_rating, opponent_possessions, opponent_turnovers_forced |
| Quality | data_quality_tier (high/medium/low) |

### `player_game_summary` (~78 fields, per-player-per-game)
**Depends on:** `nba_raw.nbac_gamebook_player_stats` (primary), `nba_raw.bdl_player_boxscores` (fallback), `nba_raw.bigdataball_play_by_play` (shot zones)
| Field Category | Key Fields |
|---------------|------------|
| Identifiers | player_lookup, universal_player_id, game_id, game_date, team_abbr |
| Basic Stats | points, minutes_played, assists, rebounds, steals, blocks, turnovers |
| Shooting | fg_made/attempted, fg3_made/attempted, ft_made/attempted, plus_minus |
| Shot Zones | paint_attempts, paint_fg_pct, midrange_attempts, three_pt_attempts |
| Prop Results | actual_points (for comparing to betting lines) |
| Source Tracking | 18 fields (3 per source × 6 sources) |

### `upcoming_team_game_context` (~40 fields, per-team-per-upcoming-game)
**Depends on:** `nba_raw.nbac_schedule`, `nba_raw.odds_api_game_lines`, `nba_raw.nbac_injury_report`
| Field Category | Key Fields |
|---------------|------------|
| Game Info | game_id, game_date, team_abbr, opponent_team_abbr, is_home |
| Fatigue | days_rest, back_to_back, games_last_7_days, travel_distance |
| Betting | spread, over_under, moneyline, implied_total |
| Injuries | players_out, players_questionable, impact_score |

### `upcoming_player_game_context` (~72 fields, per-player-per-upcoming-game)
**Depends on:** `nba_raw.odds_api_player_props` (driver), `nba_raw.nbac_schedule`, `nba_raw.bdl_player_boxscores`
| Field Category | Key Fields |
|---------------|------------|
| Identifiers | player_lookup, universal_player_id, game_id, game_date |
| Prop Lines | points_line, points_over_odds, points_under_odds |
| Recent Performance | avg_points_last_5, avg_points_last_10, avg_minutes_last_5 |
| Fatigue | days_rest, back_to_back, minutes_last_3_games |
| Trend | points_trend_7d, usage_rate_trend |
| Quality | sample_size_tier (high/medium/low) |

---

## Phase 4: Precompute Tables (6 Tables in `nba_precompute`)

### `team_defense_zone_analysis` (~35 fields, per-team-per-day)
**Depends on:** `nba_analytics.team_defense_game_summary`
**Aggregation:** Rolling last 15 games
| Field Category | Key Fields |
|---------------|------------|
| Identifiers | team_abbr, analysis_date |
| Zone Defense | paint_fg_pct_allowed, midrange_fg_pct_allowed, three_pt_fg_pct_allowed |
| Volume | paint_attempts_faced_per_game, three_pt_attempts_faced_per_game |
| League Relative | paint_defense_vs_league, perimeter_defense_vs_league |
| Strength/Weakness | primary_weakness_zone, primary_strength_zone |

### `player_shot_zone_analysis` (~40 fields, per-player-per-day)
**Depends on:** `nba_analytics.player_game_summary`
**Aggregation:** Dual windows - last 10 games (primary) + last 20 games (trend)
| Field Category | Key Fields |
|---------------|------------|
| Identifiers | player_lookup, universal_player_id, analysis_date |
| Shot Distribution | paint_rate, midrange_rate, three_pt_rate |
| Efficiency | paint_fg_pct, midrange_fg_pct, three_pt_fg_pct |
| Volume | paint_attempts_per_game, three_pt_attempts_per_game |
| Primary Zone | primary_scoring_zone (paint/perimeter/midrange/balanced) |
| Quality | sample_size_tier, games_in_window |

### `player_daily_cache` (~50 fields, per-player-per-day)
**Depends on:** Phase 3 (player_game_summary, team_offense_game_summary, upcoming_player_game_context) + Phase 4 (player_shot_zone_analysis)
**Purpose:** Single daily load reduces queries by 99.75%
| Field Category | Key Fields |
|---------------|------------|
| Identifiers | player_lookup, universal_player_id, cache_date |
| Performance Windows | avg_points_last_5, avg_points_last_10, avg_points_season |
| Minutes | avg_minutes_last_5, avg_minutes_last_10 |
| Team Context | team_pace, team_offensive_rating |
| Pre-calculated | fatigue_score, shot_zone_tendencies |

### `player_composite_factors` (~30 fields, per-player-per-day)
**Depends on:** Phase 3 (upcoming contexts) + Phase 4 (zone analyses)
**Purpose:** Pre-computed adjustment factors for predictions
| Field Category | Key Fields |
|---------------|------------|
| Identifiers | player_lookup, universal_player_id, game_date |
| Active Factors | fatigue_adjustment, shot_zone_mismatch, pace_adjustment, usage_spike |
| Deferred Factors | home_away_adjustment, matchup_history (zeros until validated) |
| Scores | composite_score (0-100) |

### `ml_feature_store_v2` (~50 fields, per-player-per-game, in `nba_predictions`)
**Depends on:** ALL Phase 3 + ALL Phase 4 tables
**Purpose:** Final 25 ML features for predictions
| Field Category | Key Fields |
|---------------|------------|
| Identifiers | player_lookup, universal_player_id, game_date, game_id |
| Features | features ARRAY<FLOAT64>[25] - indexed 0-24 |
| Feature Index | [0]=avg_pts_5, [1]=avg_pts_10, [2]=fatigue, [3]=matchup... |
| Quality | quality_score (0-100), completeness_pct |
| Sources | source_player_daily_cache_status, source_composite_factors_status |
| Flags | early_season_flag, feature_version |

---

## Phase 5: Predictions (`nba_predictions`)

### Feature Store → 5 Prediction Systems

| System | Features Used | Method | Output |
|--------|--------------|--------|--------|
| Moving Average | 10 of 25 | Weighted rolling averages | predicted_points, confidence |
| Zone Matchup V1 | 14 of 25 | Shot zone tendencies vs defense | predicted_points, zone_advantage |
| Similarity | 15 of 25 | Find similar historical games | predicted_points, similar_games_found |
| XGBoost | All 25 | Gradient boosting ML model | predicted_points, feature_importance |
| Ensemble | All 25 | Meta-learning combination | predicted_points, system_weights |

### `player_prop_predictions` (~40 fields, per-player-per-game-per-system)
**Depends on:** `nba_predictions.ml_feature_store_v2`
| Field Category | Key Fields |
|---------------|------------|
| Identifiers | player_lookup, universal_player_id, game_id, game_date, system_id |
| Prediction | predicted_points, confidence_score, recommendation (over/under/skip) |
| Prop Line | current_points_line, line_margin (predicted - line) |
| Versioning | prediction_version, is_active, superseded_by |
| Quality | data_quality_score, early_season_flag |
| Tracking | created_at, updated_at |

**Volume:** ~450 players × 5 systems = 2,250 predictions/day

---

## Data Redundancy Map

Shows which data has backup sources:

| Data Type | Primary | Backup 1 | Backup 2 | Reconstructible? |
|-----------|---------|----------|----------|------------------|
| Team boxscore | NBA.com | ESPN | Sum from players | ✅ Yes (from players) |
| Player boxscore | NBA.com Gamebook | BDL | ESPN | ✅ Yes (multiple sources) |
| Play-by-play | NBA.com | BigDataBall | - | ❌ No |
| Game schedule | NBA.com API | NBA.com CDN | ESPN | ✅ Yes |
| Betting lines | Odds API | BettingPros | - | ❌ No |
| Player props | Odds API | BettingPros | - | ❌ No |
| Injuries | NBA.com | BDL | - | ❌ No |

---

## Critical Data Paths

### For Player Points Predictions

```
Player Props (odds_api_player_props)
    → upcoming_player_game_context
        → ml_feature_store_v2
            → All 5 prediction systems
```

### For Matchup Analysis

```
Team Boxscore (nbac_team_boxscore)
    → team_offense_game_summary
    → team_defense_game_summary
        → team_defense_zone_analysis
            → player_composite_factors
                → ml_feature_store_v2
```

### For Player Performance History

```
Player Boxscore (nbac_gamebook_player_stats OR bdl_player_boxscores)
    → player_game_summary
        → player_shot_zone_analysis
        → player_daily_cache
            → ml_feature_store_v2
```

---

## Known Data Gaps

| Gap | Impact | Fallback Available? |
|-----|--------|---------------------|
| 6 Play-In games (April 2025) | Missing team boxscores | Could reconstruct from player data |
| Some historical games | Incomplete analytics | Can backfill if source available |
| New players (no history) | Can't compute rolling averages | Use league averages |
| Trade mid-season | Different team context | Handle as new context |

---

## Questions for Data Completeness Strategy

1. When team boxscore is missing, should we auto-reconstruct from player data at Phase 2 or Phase 3?
2. Should each player-game have a completeness score flowing through all phases?
3. How do we handle partial player coverage (8/10 players have data)?
4. Should predictions run with degraded data quality or skip entirely?
5. Where should alerts trigger - at Phase 2 detection or Phase 5 impact?
