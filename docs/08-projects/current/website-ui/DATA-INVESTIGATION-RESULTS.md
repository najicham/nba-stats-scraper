# UI Data Investigation Results

Investigation completed: 2025-12-11

---

## Question 1: Situational Splits Availability

### 1.1 Days Rest
**Status:** ✅ Available

| Table | Field | Notes |
|-------|-------|-------|
| `nba_analytics.upcoming_player_game_context` | `days_rest` | Current rest for upcoming game |
| `nba_analytics.upcoming_player_game_context` | `days_rest_before_last_game` | Previous rest (trend) |
| `nba_analytics.upcoming_player_game_context` | `days_since_2_plus_days_rest` | Time since real rest |
| `nba_predictions.ml_feature_store_v2` | `days_rest` | Stored as feature |
| `nba_precompute.player_composite_factors` | `fatigue_context_json` | Contains `days_rest` in JSON |

**Sample Query - Player avg points by rest bucket:**
```sql
SELECT
  player_lookup,
  CASE
    WHEN days_rest = 0 THEN 'B2B'
    WHEN days_rest = 1 THEN '1 day'
    WHEN days_rest = 2 THEN '2 days'
    ELSE '3+ days'
  END as rest_bucket,
  AVG(points) as avg_points,
  COUNT(*) as games
FROM `nba_analytics.player_game_summary` pgs
JOIN `nba_analytics.upcoming_player_game_context` ctx
  ON pgs.player_lookup = ctx.player_lookup AND pgs.game_date = ctx.game_date
WHERE pgs.game_date >= '2021-10-01'
GROUP BY player_lookup, rest_bucket
```

**Gap:** Historical `days_rest` not directly stored in `player_game_summary` - would need to calculate from schedule or join with context table.

---

### 1.2 Home/Away
**Status:** ✅ Available

| Table | Field | Notes |
|-------|-------|-------|
| `nba_analytics.upcoming_player_game_context` | `home_game` | BOOLEAN |
| `nba_analytics.team_offense_game_summary` | `home_game` | BOOLEAN |
| `nba_analytics.team_defense_game_summary` | `home_game` | BOOLEAN |
| `nba_raw.nbac_team_boxscore` | `is_home` | BOOLEAN |
| `nba_predictions.ml_feature_store_v2` | `is_home` | BOOLEAN |

**Sample Query - Home/Away splits:**
```sql
SELECT
  player_lookup,
  CASE WHEN team_abbr = SPLIT(game_id, '_')[OFFSET(2)] THEN 'home' ELSE 'away' END as location,
  AVG(points) as avg_points,
  COUNT(*) as games
FROM `nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY player_lookup, location
```

**Complexity:** Easy - data exists, just need to derive from game_id or join with context.

---

### 1.3 Opponent History
**Status:** ✅ Available

| Table | Field | Notes |
|-------|-------|-------|
| `nba_analytics.player_game_summary` | `opponent_team_abbr` | Opponent team per game |

**Sample Query - Player vs specific opponent:**
```sql
SELECT
  player_lookup,
  opponent_team_abbr,
  AVG(points) as avg_points,
  AVG(minutes_played) as avg_minutes,
  COUNT(*) as games
FROM `nba_analytics.player_game_summary`
WHERE player_lookup = 'lebronjames'
  AND opponent_team_abbr = 'MIA'
  AND game_date >= '2020-01-01'
GROUP BY player_lookup, opponent_team_abbr
```

**Complexity:** Easy - direct query on existing table.

---

### 1.4 Defensive Ratings / Opponent Tiers
**Status:** ✅ Available

| Table | Field | Notes |
|-------|-------|-------|
| `nba_analytics.team_defense_game_summary` | `defensive_rating` | Points allowed per 100 poss |
| `nba_precompute.team_defense_zone_analysis` | `defensive_rating_last_15` | Rolling 15-game avg |
| `nba_analytics.upcoming_player_game_context` | `opponent_def_rating_last_10` | Opponent's recent def rating |
| `nba_predictions.ml_feature_store_v2` | `features[13]` | opponent_def_rating feature |

**Sample Query - Performance vs defensive tiers:**
```sql
WITH defense_tiers AS (
  SELECT
    team_abbr,
    AVG(defensive_rating) as avg_def_rating,
    NTILE(3) OVER (ORDER BY AVG(defensive_rating)) as tier  -- 1=best defense, 3=worst
  FROM `nba_analytics.team_defense_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY team_abbr
)
SELECT
  pgs.player_lookup,
  dt.tier as opponent_def_tier,
  AVG(pgs.points) as avg_points,
  COUNT(*) as games
FROM `nba_analytics.player_game_summary` pgs
JOIN defense_tiers dt ON pgs.opponent_team_abbr = dt.team_abbr
WHERE pgs.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY pgs.player_lookup, dt.tier
```

**Complexity:** Medium - requires joining with team defense data and bucketing.

---

### 1.5 Back-to-Back Detection
**Status:** ✅ Available

| Table | Field | Notes |
|-------|-------|-------|
| `nba_analytics.upcoming_player_game_context` | `back_to_back` | BOOLEAN flag |
| `nba_analytics.upcoming_player_game_context` | `back_to_backs_last_14_days` | Count of B2Bs |
| `nba_analytics.upcoming_team_game_context` | `team_back_to_back` | Team-level B2B flag |
| `nba_analytics.upcoming_team_game_context` | `is_back_to_back` | Game is B2B |
| `nba_precompute.player_daily_cache` | `back_to_backs_last_14_days` | Cached count |
| `nba_predictions.ml_feature_store_v2` | Feature 16 | `back_to_back` (1=B2B, 0=normal) |

**Complexity:** Easy - direct boolean field available.

---

## Question 2: Game Log Data Structure

### 2.1 Primary Table
**Table:** `nba_analytics.player_game_summary`
**Partition:** `game_date`
**Cluster:** `universal_player_id, player_lookup, team_abbr, game_date`

### 2.2 Available Fields Per Game (79 total)

**Core Stats (16 fields):**
- `points`, `minutes_played`, `assists`
- `offensive_rebounds`, `defensive_rebounds`
- `steals`, `blocks`, `turnovers`
- `fg_attempts`, `fg_makes`
- `three_pt_attempts`, `three_pt_makes`
- `ft_attempts`, `ft_makes`
- `plus_minus`, `personal_fouls`

**Shot Zones (8 fields):**
- `paint_attempts`, `paint_makes`
- `mid_range_attempts`, `mid_range_makes`
- `paint_blocks`, `mid_range_blocks`, `three_pt_blocks`
- `and1_count`

**Advanced (5 fields):**
- `usage_rate`, `ts_pct`, `efg_pct`
- `starter_flag`, `win_flag`

**Prop Results (7 fields):**
- `points_line` (closing line)
- `opening_line`
- `line_movement` (closing - opening)
- `over_under_result` ('OVER', 'UNDER', NULL)
- `margin` (actual - line)
- `points_line_source`, `opening_line_source`

### 2.3 Historical Betting Lines
**Status:** ✅ Available

Historical lines ARE stored in `player_game_summary`:
- `points_line` - closing line
- `opening_line` - opening line
- `line_movement` - change

**Sample Query - Last N games with prop results:**
```sql
SELECT
  game_date,
  opponent_team_abbr,
  points,
  minutes_played,
  fg_makes || '/' || fg_attempts as fg,
  three_pt_makes || '/' || three_pt_attempts as three_pt,
  points_line,
  over_under_result,
  margin
FROM `nba_analytics.player_game_summary`
WHERE player_lookup = 'lebronjames'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
ORDER BY game_date DESC
LIMIT 20
```

---

## Question 3: Real-Time vs Static Data

### 3.1 Injury Status
**Status:** ✅ Available

**Table:** `nba_raw.nbac_injury_report`
**View:** `nba_raw.nbac_injury_report_latest` (most recent per player/game)
**View:** `nba_raw.injury_impact_for_props` (with prop recommendation)

**Fields:**
- `injury_status`: 'out', 'questionable', 'doubtful', 'probable', 'available'
- `reason`: Full injury text
- `reason_category`: 'injury', 'g_league', 'suspension', etc.
- `report_date`, `report_hour`: When report was issued

**Freshness:** Updated multiple times daily (NBA releases injury reports at specific times before games)

**Sample Query:**
```sql
SELECT
  player_lookup,
  player_full_name,
  team,
  injury_status,
  reason,
  prop_recommendation,
  report_date,
  report_hour
FROM `nba_raw.injury_impact_for_props`
WHERE game_date = CURRENT_DATE()
ORDER BY team, injury_status
```

---

### 3.2 Lineup Confirmations
**Status:** ⚠️ Partial

**What exists:**
- `starter_flag` in `player_game_summary` (post-game, minutes > 20)
- `starter` in `nba_raw.nbac_player_boxscore` (post-game)
- `starters_out_count` in `upcoming_team_game_context` (count of starters on injury report)

**What doesn't exist:**
- Pre-game starting lineup confirmations
- Real-time lineup lock data

**Gap:** No pre-game lineup confirmation scraping. Would need to add a new data source.

**Complexity:** Medium - would require new scraper for rotowire/fantasylabs lineup data.

---

### 3.3 Line Movement Tracking
**Status:** ✅ Available

**Table:** `nba_raw.odds_api_player_points_props`
**View:** `nba_raw.odds_api_line_movements` (calculated line changes)

**Fields:**
- `snapshot_timestamp`: When line was captured
- `points_line`: Line at that snapshot
- `minutes_before_tipoff`: How close to game
- `over_price`, `under_price`: Odds
- `bookmaker`: Which book

**Line movement view provides:**
- `line_change`: Difference from previous snapshot
- `movement_type`: 'LINE_MOVED', 'ODDS_CHANGED', 'NO_CHANGE'

**Sample Query - Line movement for a player:**
```sql
SELECT
  player_name,
  bookmaker,
  points_line,
  line_change,
  minutes_before_tipoff,
  snapshot_timestamp
FROM `nba_raw.odds_api_line_movements`
WHERE game_id = '20231024_LAL_DEN'
  AND player_name = 'LeBron James'
ORDER BY snapshot_timestamp
```

---

## Question 4: Player Sample Size Edge Cases

### 4.1 Rookies / Limited History
**Status:** ✅ Handled

**Registry:** `nba_reference.nba_players_registry`
- Tracks `games_played` per season/team
- `first_game_date`, `last_game_date`

**Prediction handling:**
- `is_production_ready` flag in predictions (requires completeness >= 90%)
- `season_boundary_detected` flag for season start handling
- `backfill_bootstrap_mode` for limited data scenarios
- `data_quality_issues` array lists problems

**Minimum data for prediction:**
- System generates predictions even with limited history
- `completeness_percentage` tracks how much data exists
- `warnings` JSON contains `["low_sample_size"]` when applicable

---

### 4.2 Recently Traded Players
**Status:** ✅ Handled

**Registry tracks team per season:**
- `team_abbr` in registry
- `last_gamebook_activity_date` for freshness

**Game summary has per-game team:**
- `team_abbr` in `player_game_summary` reflects team at time of game

**Sample Query - Games with new team:**
```sql
SELECT
  game_date,
  team_abbr,
  opponent_team_abbr,
  points
FROM `nba_analytics.player_game_summary`
WHERE player_lookup = 'dejountmurray'
  AND team_abbr = 'NOP'  -- New team
  AND game_date >= '2024-01-01'
ORDER BY game_date
```

---

### 4.3 Sparsest Data Scenario
**For a player with a prop line tonight:**

**Minimum guaranteed:**
- Name/ID from prop scraper
- Current prop line from odds API
- Team from game context

**May be missing:**
- Historical games (if rookie/new)
- Shot zone data (60-70% coverage)
- Previous prop results

**Predictions still generated:**
- Uses `estimation_method` = 'default_15.5' if no history
- `has_prop_line` = TRUE (they have a line)
- `line_source` = 'ACTUAL_PROP'
- Confidence will be lower

---

## Question 5: Prediction System Output Structure

### 5.1 Schema Location
**Table:** `nba_predictions.player_prop_predictions`
**Partition:** `game_date`
**Cluster:** `system_id, player_lookup, confidence_score DESC, game_date`

### 5.2 Core Output Fields

| Field | Type | Description |
|-------|------|-------------|
| `predicted_points` | NUMERIC(5,1) | The prediction |
| `confidence_score` | NUMERIC(5,2) | 0-100 score |
| `recommendation` | STRING | 'OVER', 'UNDER', 'PASS', 'NO_LINE' |
| `current_points_line` | NUMERIC(4,1) | Line at prediction time |
| `line_margin` | NUMERIC(5,2) | predicted - line (edge) |

### 5.3 Key Factors / Reasoning
**Status:** ✅ Stored as JSON

| Field | Type | Example |
|-------|------|---------|
| `key_factors` | JSON | `{"extreme_fatigue": true, "paint_mismatch": 6.2}` |
| `warnings` | JSON | `["low_sample_size", "high_variance"]` |

**Adjustment breakdown stored:**
- `fatigue_adjustment`
- `shot_zone_adjustment`
- `pace_adjustment`
- `home_away_adjustment`
- `referee_adjustment`
- `look_ahead_adjustment`
- `usage_spike_adjustment`
- `other_adjustments`

### 5.4 System Agreement
**Status:** ✅ Tracked

| Field | Type | Description |
|-------|------|-------------|
| `prediction_variance` | NUMERIC | Variance across systems |
| `system_agreement_score` | NUMERIC | 0-100 (100 = perfect agreement) |
| `contributing_systems` | INT64 | Count of systems that predicted |

**5 systems generate predictions:**
1. `moving_average_baseline_v1` (rule-based)
2. `zone_matchup_v1` (zone analysis)
3. `similarity_balanced_v1` (historical similarity)
4. `xgboost_v1` (ML model)
5. `meta_ensemble_v1` (ensemble)

### 5.5 Where UI Consumes This
**Phase 6 JSON endpoints:**
- `/v1/predictions/today.json` - All predictions
- `/v1/best-bets/today.json` - Top ranked picks
- `/v1/players/{lookup}.json` - Player-specific

**Direct BigQuery** also possible for custom queries.

---

## Question 6: Data Freshness and Update Timing

### 6.1 Prop Line Availability
**Typical timing:**
- Lines appear 12-24 hours before game
- Major movement in final 2-4 hours
- Final lines ~30 min before tipoff

**From schema:** `minutes_before_tipoff` field tracks this.

### 6.2 Pipeline Timing

| Phase | Schedule | Latency | Output |
|-------|----------|---------|--------|
| **Phase 2: Raw Scraping** | Continuous | Real-time | Raw tables |
| **Phase 3: Analytics** | 1-6 hrs post-game | Multi-pass | `player_game_summary` |
| **Phase 4: Precompute** | 12:00 AM nightly | Overnight | `player_daily_cache` |
| **Phase 5A: Predictions** | 6:00 AM daily | Morning | `player_prop_predictions` |
| **Phase 5B: Grading** | 2:00 AM next day | Post-game | `prediction_accuracy` |
| **Phase 6: Publishing** | 7:00 AM daily | After predictions | JSON on GCS |

### 6.3 Intraday Updates
**What updates during the day:**
- Prop lines (Odds API scraper runs periodically)
- Injury reports (multiple times daily)
- Predictions can re-run when lines change significantly

**What's static after morning:**
- `player_daily_cache` (frozen for day)
- ML features (frozen for day)

### 6.4 For UI Display
**Recommendations:**
- Fetch predictions JSON once in morning (6-7 AM)
- Poll injury reports every 30-60 min
- Poll line changes every 15-30 min close to games
- Results available next morning

---

## Summary Table

| Feature | Status | Table(s) | Complexity |
|---------|--------|----------|------------|
| Days rest splits | ✅ Available | `upcoming_player_game_context` | Easy |
| Home/away splits | ✅ Available | `player_game_summary` | Easy |
| Opponent history | ✅ Available | `player_game_summary` | Easy |
| Defensive rating tiers | ✅ Available | `team_defense_game_summary` | Medium |
| Back-to-back flag | ✅ Available | `upcoming_player_game_context` | Easy |
| Game log (last N) | ✅ Available | `player_game_summary` | Easy |
| Historical prop lines | ✅ Available | `player_game_summary` | Easy |
| Injury status | ✅ Available | `nbac_injury_report` | Easy |
| Lineup confirmations | ⚠️ Partial | Post-game only | Medium |
| Line movement | ✅ Available | `odds_api_player_points_props` | Easy |
| Rookie handling | ✅ Available | Flags in predictions | Built-in |
| Trade handling | ✅ Available | Per-game team_abbr | Easy |
| Key factors JSON | ✅ Available | `player_prop_predictions` | Easy |
| System agreement | ✅ Available | `player_prop_predictions` | Easy |

---

## Gaps to Address

### High Priority (Needed for MVP)
1. **None critical** - All essential data exists

### Medium Priority (Nice to Have)
1. **Pre-game lineup confirmations** - Would require new scraper
2. **Historical days_rest in player_game_summary** - Currently requires join

### Low Priority (Future)
1. **Real-time prediction updates** - Currently daily batch
2. **Websocket for live updates** - Currently polling only

---

## Next Steps

1. **No new endpoints needed for MVP** - Phase 6 provides everything
2. **Streaks endpoint** - Would need new Phase 6 exporter (~2-3 hours)
3. **Leaderboards endpoint** - Would need new Phase 6 exporter (~2-3 hours)
4. **Frontend can start** - Data layer is complete
