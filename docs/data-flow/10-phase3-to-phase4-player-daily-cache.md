# Phase 3→4 Mapping: Player Daily Cache

**File:** `docs/data-flow/10-phase3-to-phase4-player-daily-cache.md`
**Created:** 2025-10-30
**Last Updated:** 2025-11-15
**Purpose:** Data mapping for daily player performance cache (Phase 3+4 → Phase 4 precompute)
**Audience:** Engineers implementing Phase 4 caching layer and Phase 5 prediction pipelines
**Status:** ✅ Production Ready - Implementation complete, all sources available

---

## 🚧 Current Deployment Status

**Implementation:** ✅ **COMPLETE**
- Phase 3 Sources: Multiple analytics tables (all exist)
- Phase 4 Dependency: `nba_precompute.player_shot_zone_analysis` (exists)
- Phase 4 Processor: `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py` (652 lines, 50 tests)
- Precompute Table: `nba_precompute.player_daily_cache` (created, 43 fields)

**Blocker:** ✅ **NONE - Ready for production**
- ✅ All 3 Phase 3 source tables exist and are populated
- ✅ Phase 4 dependency (player_shot_zone_analysis) exists
- ✅ Phase 4 processor is implemented
- ✅ Phase 4 output table exists
- ✅ All dependencies satisfied

**Processing Strategy:**
- **Daily cache pattern** - Load once at 12:00 AM, reuse all day
- **Multi-source aggregation** - Combines 4 upstream tables
- **30-day retention** in Phase 4 (partitioned by cache_date)
- **Early season handling** for players with <10 games

**Purpose:**
Cache static daily player data that **won't change during the day**. This enables Phase 5 to load data once at 6:00 AM and reuse it for multiple real-time updates throughout the day when prop lines change, **improving performance and reducing BigQuery costs**.

**Consumers:**
- Phase 5 Predictions (loads cache at 6:00 AM once, reuses all day)
- Real-time prop updates (no need to re-query analytics)
- Cost optimization (single daily load vs hundreds of queries)

**See:** `docs/processors/` for Phase 4 deployment procedures

---

## 📊 Executive Summary

This Phase 4 processor creates a **daily cache** of player performance metrics by aggregating data from 3 Phase 3 analytics tables + 1 Phase 4 precompute table. It runs once nightly at 12:00 AM to pre-calculate all player stats needed for next-day predictions, enabling Phase 5 to load once at 6:00 AM and reuse the cache for all prop updates throughout the day.

**Processor:** `player_daily_cache_processor.py`
**Output Table:** `nba_precompute.player_daily_cache`
**Processing Strategy:** MERGE_UPDATE (daily cache refresh)
**Update Frequency:** Nightly at 12:00 AM (after all Phase 3+4 processors complete)
**Granularity:** 1 row per player per day (~450 rows/day)
**Cache Lifetime:** 1 day (loaded by Phase 5 at 6:00 AM, used all day)

**Key Features:**
- **Performance optimization** - Load once, reuse hundreds of times
- **Cost optimization** - Single BQ query vs 100+ real-time queries
- **Multi-source aggregation** - 4 upstream tables combined
- **Recent performance windows** - Last 5, 10 games + season aggregates
- **Team context** - Pace and offensive rating
- **Fatigue metrics** - Pre-calculated from upcoming_player_game_context
- **Shot zone tendencies** - Pre-calculated from player_shot_zone_analysis
- **Early season handling** - Graceful degradation for players with <10 games

**Data Flow:**
- **Input:** ~450 players × (10-82 games + team context + fatigue + shot zones)
- **Processing:** Aggregate to single row per player
- **Output:** ~450 rows (1 per active player)

**Cost Savings:**
- **Without cache:** 100 prop updates/day × 450 players × 4 tables = 180,000 BQ queries
- **With cache:** 1 load at 6 AM × 1 table = 1 BQ query (reused 100 times)
- **Savings:** ~99.9% reduction in real-time BQ queries

---

## 🗂️ Upstream Sources

### Source 1: Player Game Summary (Phase 3 - CRITICAL)

**Table:** `nba_analytics.player_game_summary`
**Status:** ✅ **EXISTS**
**Update Frequency:** Nightly at ~10:30 PM
**Dependency:** CRITICAL - Primary source for recent performance
**Lookback:** Last 10 games, last 5 games, full season

**Purpose:**
- Recent performance stats (points averages, volatility)
- Usage rates and efficiency metrics (TS%, usage%)
- Playing time trends
- Shot creation (assisted rate)

**Key Fields Used:**

| Field | Type | Description | Lookback Window |
|-------|------|-------------|-----------------|
| player_lookup | STRING | Player key | - |
| universal_player_id | STRING | Universal ID | - |
| game_date | DATE | For windowing | Season to date |
| points | INT64 | Points scored | Last 5, 10, season |
| minutes_played | NUMERIC | Minutes played | Last 10 |
| usage_rate | FLOAT64 | Usage percentage | Last 10, season |
| ts_pct | FLOAT64 | True shooting % | Last 10 |
| fg_makes | INT64 | Field goals made | Last 10 |
| assisted_fg_makes | INT64 | Assisted FG | Last 10 |
| season_year | INT64 | Season filter | Current season |

**Expected Input Volume:** ~10-82 games per player (depends on season progress)

---

### Source 2: Team Offense Game Summary (Phase 3 - CRITICAL)

**Table:** `nba_analytics.team_offense_game_summary`
**Status:** ✅ **EXISTS**
**Update Frequency:** Nightly at ~10:15 PM
**Dependency:** CRITICAL - Team pace and offensive rating
**Lookback:** Last 10 games

**Purpose:**
- Team pace (possessions per game)
- Team offensive rating
- Context for player performance environment

**Key Fields Used:**

| Field | Type | Description | Lookback Window |
|-------|------|-------------|-----------------|
| team_abbr | STRING | Team key | - |
| game_date | DATE | For windowing | Last 10 games |
| pace | FLOAT64 | Team pace | Last 10 |
| offensive_rating | FLOAT64 | Team offensive rating | Last 10 |

**Expected Input Volume:** ~10 games per team

---

### Source 3: Upcoming Player Game Context (Phase 3 - CRITICAL)

**Table:** `nba_analytics.upcoming_player_game_context`
**Status:** ✅ **EXISTS**
**Update Frequency:** Multiple times per day (morning, midday, pre-game)
**Dependency:** CRITICAL - Pre-calculated fatigue metrics
**Lookback:** Today's game context (date match)

**Purpose:**
- Fatigue metrics (games/minutes in last 7/14 days)
- Back-to-backs tracking
- Player age

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| player_lookup | STRING | Player key |
| game_date | DATE | Today's game |
| games_in_last_7_days | INT64 | Games played (last 7 days) |
| games_in_last_14_days | INT64 | Games played (last 14 days) |
| minutes_in_last_7_days | NUMERIC | Total minutes (last 7 days) |
| minutes_in_last_14_days | NUMERIC | Total minutes (last 14 days) |
| back_to_backs_last_14_days | INT64 | Back-to-back count |
| avg_minutes_per_game_last_7 | NUMERIC | Avg minutes (last 7 days) |
| fourth_quarter_minutes_last_7 | NUMERIC | 4Q minutes (last 7 days) |
| player_age | INT64 | Player age |

**Expected Input Volume:** 1 row per player (today's game)

---

### Source 4: Player Shot Zone Analysis (Phase 4 - CRITICAL)

**Table:** `nba_precompute.player_shot_zone_analysis`
**Status:** ✅ **EXISTS**
**Update Frequency:** Nightly at ~11:23 PM
**Dependency:** CRITICAL - Pre-calculated shot zone tendencies
**Lookback:** Latest analysis (cache_date = today)

**Purpose:**
- Primary scoring zone classification
- Shot distribution by zone
- Zone tendency rates

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| player_lookup | STRING | Player key |
| analysis_date | DATE | Today's analysis |
| primary_scoring_zone | STRING | Paint/perimeter/mid-range/balanced |
| paint_rate_last_10 | NUMERIC | % of shots in paint |
| three_pt_rate_last_10 | NUMERIC | % of shots from three |

**Expected Input Volume:** 1 row per player

**NOTE:** This is a Phase 4 dependency - player_shot_zone_analysis must complete BEFORE player_daily_cache runs.

---

## 🔄 Data Flow

### Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Load Player Game Summary (Season to Date)               │
│ Query: player_game_summary WHERE season = current                │
│ Window: ROW_NUMBER() OVER (PARTITION BY player ORDER BY date)   │
│ Result: ~450 players × (10-82 games each) = variable rows       │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Aggregate Recent Performance (Multiple Windows)         │
│ For each player:                                                │
│ • Last 5 games: points_avg_last_5                               │
│ • Last 10 games: points_avg_last_10, std, minutes, usage, TS%  │
│ • Season: points_avg_season, games_played, usage_rate          │
│ • Shot creation: assisted_rate (last 10)                        │
│ Result: Recent performance metrics per player                   │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: Load Team Context (Player's Current Team)               │
│ Query: team_offense_game_summary WHERE team = player's team     │
│ Window: Last 10 games                                           │
│ Calculate:                                                      │
│ • team_pace_last_10 = AVG(pace)                                 │
│ • team_off_rating_last_10 = AVG(offensive_rating)              │
│ Result: Team context per player                                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: Copy Fatigue Metrics (Already Calculated!)              │
│ Query: upcoming_player_game_context WHERE date = cache_date     │
│ Fields: games_in_last_7_days, minutes_in_last_7_days, etc.     │
│ Action: Direct copy (no calculation needed)                     │
│ Result: Fatigue metrics per player                              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: Copy Shot Zone Tendencies (Already Calculated!)         │
│ Query: player_shot_zone_analysis WHERE date = cache_date        │
│ Fields: primary_scoring_zone, paint_rate, three_pt_rate        │
│ Action: Direct copy (no calculation needed)                     │
│ Result: Shot zone tendencies per player                         │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 6: Quality Checks & Early Season Handling                  │
│ For each player:                                                │
│ • Check: games_played >= 10?                                    │
│ • IF < 10: Set early_season_flag = TRUE                        │
│ • IF < 5: Skip player (insufficient data)                      │
│ • Track source completeness (4 sources)                         │
│ Result: Quality metadata populated                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📋 Field Mappings

### Complete Field-by-Field Mapping

**Core Identifiers (3 fields)**

| Phase 4 Field | Source Table | Source Field | Transformation |
|---------------|--------------|--------------|----------------|
| player_lookup | player_game_summary | player_lookup | Direct copy (distinct) |
| universal_player_id | player_game_summary | universal_player_id | Direct copy (distinct) |
| cache_date | N/A | Parameter | Input: analysis_date |

**Recent Performance - Multiple Windows (8 fields)**

| Phase 4 Field | Source Table | Source Field | Transformation |
|---------------|--------------|--------------|----------------|
| points_avg_last_5 | player_game_summary | points | AVG(points) WHERE game_rank <= 5 |
| points_avg_last_10 | player_game_summary | points | AVG(points) WHERE game_rank <= 10 |
| points_avg_season | player_game_summary | points | AVG(points) WHERE season = current |
| points_std_last_10 | player_game_summary | points | STDDEV(points) WHERE game_rank <= 10 |
| minutes_avg_last_10 | player_game_summary | minutes_played | AVG(minutes_played) WHERE game_rank <= 10 |
| usage_rate_last_10 | player_game_summary | usage_rate | AVG(usage_rate) WHERE game_rank <= 10 |
| ts_pct_last_10 | player_game_summary | ts_pct | AVG(ts_pct) WHERE game_rank <= 10 |
| games_played_season | player_game_summary | COUNT(*) | COUNT(*) WHERE season = current |

**Team Context (3 fields)**

| Phase 4 Field | Source Table | Source Field | Transformation |
|---------------|--------------|--------------|----------------|
| team_pace_last_10 | team_offense_game_summary | pace | AVG(pace) WHERE team = player's team AND game_rank <= 10 |
| team_off_rating_last_10 | team_offense_game_summary | offensive_rating | AVG(offensive_rating) WHERE team = player's team AND game_rank <= 10 |
| player_usage_rate_season | player_game_summary | usage_rate | AVG(usage_rate) WHERE season = current |

**Fatigue Metrics - Pre-Calculated (7 fields)**

| Phase 4 Field | Source Table | Source Field | Transformation |
|---------------|--------------|--------------|----------------|
| games_in_last_7_days | upcoming_player_game_context | games_in_last_7_days | Direct copy |
| games_in_last_14_days | upcoming_player_game_context | games_in_last_14_days | Direct copy |
| minutes_in_last_7_days | upcoming_player_game_context | minutes_in_last_7_days | Direct copy |
| minutes_in_last_14_days | upcoming_player_game_context | minutes_in_last_14_days | Direct copy |
| back_to_backs_last_14_days | upcoming_player_game_context | back_to_backs_last_14_days | Direct copy |
| avg_minutes_per_game_last_7 | upcoming_player_game_context | avg_minutes_per_game_last_7 | Direct copy |
| fourth_quarter_minutes_last_7 | upcoming_player_game_context | fourth_quarter_minutes_last_7 | Direct copy |

**Shot Zone Tendencies - Pre-Calculated (4 fields)**

| Phase 4 Field | Source Table | Source Field | Transformation |
|---------------|--------------|--------------|----------------|
| primary_scoring_zone | player_shot_zone_analysis | primary_scoring_zone | Direct copy |
| paint_rate_last_10 | player_shot_zone_analysis | paint_rate_last_10 | Direct copy |
| three_pt_rate_last_10 | player_shot_zone_analysis | three_pt_rate_last_10 | Direct copy |
| assisted_rate_last_10 | player_game_summary | assisted_fg_makes, fg_makes | SUM(assisted) / SUM(fg_makes) WHERE game_rank <= 10 |

**Demographics (1 field)**

| Phase 4 Field | Source Table | Source Field | Transformation |
|---------------|--------------|--------------|----------------|
| player_age | upcoming_player_game_context | player_age | Direct copy |

**Source Tracking (12 fields - 3 per source × 4 sources)**

| Phase 4 Field | Value | Description |
|---------------|-------|-------------|
| source_player_game_last_updated | MAX(processed_at) | When player_game_summary was last processed |
| source_player_game_rows_found | COUNT(*) | Number of games found for player |
| source_player_game_completeness_pct | (rows_found / expected) × 100 | Completeness percentage |
| source_team_offense_last_updated | MAX(processed_at) | When team_offense was last processed |
| source_team_offense_rows_found | COUNT(*) | Number of team games found |
| source_team_offense_completeness_pct | (rows_found / expected) × 100 | Completeness percentage |
| source_upcoming_context_last_updated | MAX(processed_at) | When upcoming_context was last processed |
| source_upcoming_context_rows_found | 0 or 1 | Should be 1 |
| source_upcoming_context_completeness_pct | 0 or 100 | Completeness percentage |
| source_shot_zone_last_updated | MAX(processed_at) | When shot_zone_analysis was last processed |
| source_shot_zone_rows_found | 0 or 1 | Should be 1 |
| source_shot_zone_completeness_pct | 0 or 100 | Completeness percentage |

**Data Quality (3 fields)**

| Phase 4 Field | Calculation | Logic |
|---------------|-------------|-------|
| early_season_flag | Based on games_played_season | TRUE if < 10 games OR team < 10 games |
| insufficient_data_reason | Explanation | "Only {n} games played, need 10 minimum" |
| cache_version | Static | "v1" (for future schema changes) |

**Processing Metadata (1 field)**

| Phase 4 Field | Value | Description |
|---------------|-------|-------------|
| processed_at | CURRENT_TIMESTAMP() | When cache was built |

---

## 📐 Calculation Examples

### Example 1: LeBron James (Mid-Season)

**Phase 3 Input - player_game_summary (Last 10 games):**
```
Games ranked by date DESC:
Rank 1 (2025-01-20): 28 pts, 36 min, 31.2% usage, 0.623 TS%, 11 FGM, 5 assisted
Rank 2 (2025-01-18): 24 pts, 34 min, 29.5% usage, 0.591 TS%, 9 FGM, 4 assisted
Rank 3 (2025-01-16): 31 pts, 38 min, 33.1% usage, 0.645 TS%, 12 FGM, 4 assisted
... (7 more games)

Season total: 45 games
```

**Phase 3 Input - team_offense_game_summary (LAL, Last 10):**
```
Rank 1 (2025-01-20): pace = 102.3, off_rating = 116.8
Rank 2 (2025-01-18): pace = 104.1, off_rating = 114.2
... (8 more games)
```

**Phase 3 Input - upcoming_player_game_context (Today):**
```
game_date: 2025-01-21
games_in_last_7_days: 3
minutes_in_last_7_days: 108
back_to_backs_last_14_days: 1
player_age: 40
```

**Phase 4 Input - player_shot_zone_analysis (Today):**
```
analysis_date: 2025-01-21
primary_scoring_zone: "paint"
paint_rate_last_10: 48.3
three_pt_rate_last_10: 31.2
```

**Phase 4 Calculations:**
```python
# Recent performance
points_avg_last_5 = AVG(28, 24, 31, ...) = 27.6
points_avg_last_10 = AVG(10 games) = 26.4
points_avg_season = AVG(45 games) = 25.8
points_std_last_10 = STDDEV(10 games) = 3.42
minutes_avg_last_10 = AVG(36, 34, 38, ...) = 35.8
usage_rate_last_10 = AVG(31.2, 29.5, 33.1, ...) = 30.8
ts_pct_last_10 = AVG(0.623, 0.591, 0.645, ...) = 0.618

# Team context
team_pace_last_10 = AVG(102.3, 104.1, ...) = 103.2
team_off_rating_last_10 = AVG(116.8, 114.2, ...) = 115.6

# Fatigue (direct copy)
games_in_last_7_days = 3
minutes_in_last_7_days = 108
...

# Shot zones (direct copy)
primary_scoring_zone = "paint"
paint_rate_last_10 = 48.3
...

# Shot creation
assisted_rate_last_10 = SUM(5,4,4,...) / SUM(11,9,12,...) = 0.423
```

**Phase 4 Output:**
```json
{
  "player_lookup": "lebronjames",
  "universal_player_id": "lebronjames_001",
  "cache_date": "2025-01-21",

  "points_avg_last_5": 27.6,
  "points_avg_last_10": 26.4,
  "points_avg_season": 25.8,
  "points_std_last_10": 3.42,
  "minutes_avg_last_10": 35.8,
  "usage_rate_last_10": 30.8,
  "ts_pct_last_10": 0.618,
  "games_played_season": 45,

  "team_pace_last_10": 103.2,
  "team_off_rating_last_10": 115.6,
  "player_usage_rate_season": 29.9,

  "games_in_last_7_days": 3,
  "games_in_last_14_days": 5,
  "minutes_in_last_7_days": 108,

  "primary_scoring_zone": "paint",
  "paint_rate_last_10": 48.3,
  "three_pt_rate_last_10": 31.2,
  "assisted_rate_last_10": 0.423,

  "player_age": 40,

  "early_season_flag": false,
  "cache_version": "v1",
  "processed_at": "2025-01-21T00:15:00Z"
}
```

---

## ⚠️ Known Issues & Edge Cases

### Issue 1: Early Season (< 10 Games)
**Problem:** Rookie with only 7 games played
**Solution:**
- Use 7 games for all calculations
- `points_avg_last_10` = AVG of 7 games (not 10)
- Set `early_season_flag = TRUE`
- Set `insufficient_data_reason = "Only 7 games played, need 10 minimum"`
**Impact:** Phase 5 can decide whether to use early season cache

### Issue 2: Missing Shot Zone Analysis
**Problem:** Player hasn't played enough for shot zone analysis (<10 games)
**Solution:**
- Skip this player entirely (don't write cache record)
- `source_shot_zone_rows_found = 0`
- `source_shot_zone_completeness_pct = 0`
**Impact:** Phase 5 can't predict without zones - player skipped

### Issue 3: Traded Player
**Problem:** Player traded mid-season, now on new team
**Solution:**
- Use player's CURRENT team from `upcoming_player_game_context`
- Calculate `team_pace_last_10` for NEW team only
- Player stats include ALL games (both teams)
**Impact:** Team context reflects current environment

### Issue 4: Injured Player (No Recent Games)
**Problem:** Player with 30 season games but last game was 2 weeks ago
**Solution:**
- Calculate metrics from available games
- Source tracking will show staleness (`source_*_last_updated`)
- Phase 5 can decide whether to use stale cache
**Impact:** Cache exists but may be stale

### Issue 5: DNP Games (Did Not Play)
**Problem:** Player has DNP games mixed with active games
**Solution:**
- Include ALL games in `games_played_season` count
- Filter to `minutes > 0` for performance metrics
- Mark as `early_season_flag` if < 10 games with minutes
**Impact:** Accurate season count, meaningful performance metrics

---

## ✅ Validation Rules

### Input Validation (Source Checks)
- ✅ **player_game_summary:** ≥10 games for high quality (≥5 minimum)
- ✅ **team_offense_game_summary:** ≥10 games for team
- ✅ **upcoming_player_game_context:** Exactly 1 row (today's game)
- ✅ **player_shot_zone_analysis:** Exactly 1 row (today's analysis)

### Output Validation (Cache Quality)
- ✅ **Completeness:** 95%+ of players with scheduled games have cache records
- ✅ **Source freshness:** All source tables < 24 hours old
- ✅ **Quality:** 90%+ of cache records have 100% completeness across all sources
- ✅ **Calculations:** Spot-check 10 random players matches manual verification

### Data Quality Tiers
```python
if games_played_season >= 10 and team_games >= 10:
    early_season_flag = False
elif games_played_season >= 5:
    early_season_flag = True
    insufficient_data_reason = f"Only {games_played_season} games played, need 10"
else:
    # Skip player - insufficient data
    return None
```

---

## 📈 Success Criteria

**Processing Success:**
- ✅ ~450 rows output (1 per active player)
- ✅ Processing completes within 15 minutes (by 12:15 AM)
- ✅ All 4 sources successfully joined
- ✅ No missing critical fields (points_avg, team_pace, shot zones)

**Data Quality Success:**
- ✅ 95%+ completeness (players with games have cache)
- ✅ Source freshness < 24 hours
- ✅ 90%+ have 100% source completeness
- ✅ Early season players properly flagged

**Performance Success:**
- ✅ BigQuery cost: ~$0.23/day (45 GB scanned)
- ✅ Phase 5 loads cache in < 5 seconds
- ✅ Cache reused 100+ times during day (no re-queries)

---

## 🔗 Related Documentation

**Processor Implementation:**
- Code: `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`

**Phase 3 Dependencies:**
- Schema: `bq show --schema nba_analytics.player_game_summary`
- Schema: `bq show --schema nba_analytics.team_offense_game_summary`
- Schema: `bq show --schema nba_analytics.upcoming_player_game_context`

**Phase 4 Dependencies:**
- Schema: `bq show --schema nba_precompute.player_shot_zone_analysis`
- Source mapping: `docs/data-flow/09-phase3-to-phase4-player-shot-zone-analysis.md`

**Phase 4 Output:**
- Schema: `bq show --schema nba_precompute.player_daily_cache`

**Downstream Consumers:**
- Phase 5 Predictions (loads cache at 6:00 AM once, reuses all day)

**Monitoring:**
- `docs/monitoring/` - Data quality metrics for Phase 4

---

## 📅 Processing Schedule & Dependencies

**Critical Path:**
```
10:00 PM - Phase 3 analytics processors start
10:30 PM - player_game_summary completes
10:15 PM - team_offense_game_summary completes
11:45 PM - upcoming_player_game_context completes (last update)
11:23 PM - player_shot_zone_analysis completes (Phase 4 dependency)
12:00 AM - player_daily_cache starts
12:15 AM - player_daily_cache completes
---
6:00 AM - Phase 5 loads cache (once)
6:00 AM - All day: Phase 5 reuses cache for 100+ prop updates
```

**Dependency Graph:**
```
Phase 3:
├─ player_game_summary (10:30 PM) ───┐
├─ team_offense_game_summary (10:15 PM) ──┤
├─ upcoming_player_game_context (11:45 PM) ──┤
                                             ├─→ Phase 4: player_daily_cache (12:00 AM)
Phase 4:                                     │
└─ player_shot_zone_analysis (11:23 PM) ─────┘
```

**Retention:**
- Phase 4 table: 30 days (partitioned by cache_date)
- Automatic expiration via partition expiration

---

## 💡 Cache Usage Pattern

**Without Cache (Old Pattern):**
```
For each prop update (100x per day):
  ├─ Query player_game_summary (450 players)
  ├─ Query team_offense_game_summary (30 teams)
  ├─ Query upcoming_player_game_context (450 players)
  └─ Query player_shot_zone_analysis (450 players)

Total BQ queries: 100 updates × 4 tables = 400 queries/day
Cost: ~$92/day
```

**With Cache (New Pattern):**
```
At 6:00 AM (once):
  └─ Load player_daily_cache (1 table, 450 rows)

For each prop update (100x per day):
  └─ Use in-memory cache (no BQ query)

Total BQ queries: 1 query/day
Cost: ~$0.23/day
Savings: 99.75% reduction
```

---

**Document Version:** 1.0
**Status:** ✅ Production Ready - All sources available, ready for deployment
**Next Steps:** Deploy to production, monitor cache hit rates and cost savings
