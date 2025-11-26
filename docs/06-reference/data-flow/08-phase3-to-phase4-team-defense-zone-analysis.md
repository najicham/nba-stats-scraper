# Phase 3→4 Mapping: Team Defense Zone Analysis

**File:** `docs/data-flow/08-phase3-to-phase4-team-defense-zone-analysis.md`
**Created:** 2025-10-29
**Last Updated:** 2025-11-15
**Purpose:** Data mapping from Phase 3 analytics to Phase 4 rolling window team defense precompute
**Audience:** Engineers implementing Phase 4 processors and debugging team defense analysis
**Status:** ✅ Production Ready - Implementation complete, all sources available

---

## 🚧 Current Deployment Status

**Implementation:** ✅ **COMPLETE**
- Phase 3 Source: `nba_analytics.team_defense_game_summary` (EXISTS)
- Phase 4 Processor: `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py` (804 lines, 45 tests)
- Precompute Table: `nba_precompute.team_defense_zone_analysis` (created, 30 fields)

**Blocker:** ✅ **NONE - Ready for production**
- ✅ Phase 3 source table exists and is populated
- ✅ Phase 4 processor is implemented
- ✅ Phase 4 output table exists
- ✅ All dependencies satisfied

**Processing Strategy:**
- **Rolling 15-game window** aggregation per team
- **Nightly updates** at 11:00 PM (after Phase 3 completes)
- **90-day retention** in Phase 4 (partitioned by analysis_date)
- **Early season handling** for teams with <15 games

**Consumers:**
- Player Shot Zone Analysis (Phase 4)
- Phase 5 Predictions
- Web app matchup analysis

**See:** `docs/processors/` for Phase 4 deployment procedures

---

## 📊 Executive Summary

This Phase 4 processor transforms per-game team defensive analytics from Phase 3 into **rolling 15-game windows** with league-relative performance metrics. It identifies each team's defensive strengths and weaknesses by zone (paint, mid-range, perimeter), enabling downstream player shot zone analysis.

**Processor:** `team_defense_zone_analysis_processor.py`
**Output Table:** `nba_precompute.team_defense_zone_analysis`
**Processing Strategy:** MERGE_UPDATE (daily aggregation)
**Update Frequency:** Nightly at 11:00 PM
**Window Size:** Last 15 games per team
**Granularity:** 1 row per team per day (30 rows/day)

**Key Features:**
- **Rolling windows** - Last 15 games per team (handles recency)
- **Zone-by-zone analysis** - Paint, mid-range, three-point defense
- **League-relative metrics** - Compare each team to league average
- **Strength/weakness identification** - Automatically flag best/worst zones
- **Early season handling** - Graceful degradation for teams with <15 games
- **Source tracking** - Full dependency tracking per v4.0 spec

**Data Quality:** High - Depends on Phase 3 team defense data (30 teams × 15 games = 450 input rows)

---

## 🗂️ Phase 3 Source (Analytics)

### Source 1: Team Defense Game Summary (PRIMARY - CRITICAL)

**Table:** `nba_analytics.team_defense_game_summary`
**Status:** ✅ **EXISTS**
**Update Frequency:** Nightly at ~10:00 PM (after games complete)
**Dependency:** CRITICAL - Only source for this processor
**Granularity:** One row per team per game

**Purpose:**
- Per-game team defensive performance by zone
- Opponent shooting percentages by zone
- Blocks and points allowed by zone
- Overall defensive rating and pace

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| defending_team_abbr | STRING | Team abbreviation (e.g., "LAL") |
| game_date | DATE | Game date (partition key) |
| game_id | STRING | Unique game identifier |
| **Paint Defense (≤8 feet)** | | |
| opp_paint_makes | INT64 | Opponent FGM in paint |
| opp_paint_attempts | INT64 | Opponent FGA in paint |
| points_in_paint_allowed | INT64 | Points allowed in paint |
| blocks_paint | INT64 | Blocks in paint |
| **Mid-Range Defense (9+ feet, 2PT)** | | |
| opp_mid_range_makes | INT64 | Opponent mid-range FGM |
| opp_mid_range_attempts | INT64 | Opponent mid-range FGA |
| mid_range_points_allowed | INT64 | Mid-range points allowed |
| blocks_mid_range | INT64 | Mid-range blocks |
| **Three-Point Defense** | | |
| opp_three_pt_makes | INT64 | Opponent 3PM |
| opp_three_pt_attempts | INT64 | Opponent 3PA |
| three_pt_points_allowed | INT64 | Three-point points allowed |
| blocks_three_pt | INT64 | Three-point blocks |
| **Overall Defensive Metrics** | | |
| points_allowed | INT64 | Total points allowed |
| defensive_rating | FLOAT64 | Defensive rating (pts/100 poss) |
| opponent_pace | FLOAT64 | Opponent's pace |
| processed_at | TIMESTAMP | When Phase 3 processed |

**Data Quality Requirements:**
- ✅ All 30 teams must have data
- ✅ Each team should have ≥15 games (for normal season)
- ✅ No NULL values in defensive metrics
- ✅ Data must be <24 hours old (freshness check)

**Window Query Pattern:**
```sql
-- Get last 15 games per team
WITH ranked_games AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY defending_team_abbr
      ORDER BY game_date DESC
    ) as game_rank
  FROM `nba_analytics.team_defense_game_summary`
  WHERE game_date <= @analysis_date
    AND game_date >= @season_start_date
)
SELECT *
FROM ranked_games
WHERE game_rank <= 15
```

**Expected Input Volume:**
- **Normal season:** 30 teams × 15 games = 450 rows
- **Early season:** Variable (some teams with <15 games)

---

## 🔄 Data Flow

### Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Extract Last 15 Games per Team                          │
│ Query: team_defense_game_summary WHERE game_date <= target      │
│ Window: ROW_NUMBER() OVER (PARTITION BY team ORDER BY date DESC)│
│ Filter: WHERE game_rank <= 15                                   │
│ Result: 450 rows (30 teams × 15 games each)                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Aggregate by Team (Rolling 15-Game Windows)             │
│ For each team:                                                  │
│ • Paint FG% allowed = SUM(opp_paint_makes) / SUM(opp_paint_att) │
│ • Mid-range FG% allowed = SUM(mid_makes) / SUM(mid_att)        │
│ • Perimeter FG% allowed = SUM(3pt_makes) / SUM(3pt_att)        │
│ • Points per game by zone                                       │
│ • Blocks per game by zone                                       │
│ • Overall defensive rating (AVG)                                │
│ Result: 30 rows (1 per team)                                    │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: Calculate League Averages (30-day lookback)             │
│ Query all teams from last 30 days:                             │
│ • League avg paint FG% allowed                                 │
│ • League avg mid-range FG% allowed                             │
│ • League avg three-point FG% allowed                           │
│ Require: ≥10 games per team to include in league average       │
│ Result: 3 league benchmark values                              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: Compare to League Average                               │
│ For each team:                                                  │
│ • paint_defense_vs_league = (team_pct - league_pct) × 100      │
│ • mid_range_defense_vs_league = (team_pct - league_pct) × 100  │
│ • three_pt_defense_vs_league = (team_pct - league_pct) × 100   │
│ Values: Negative = Better defense, Positive = Worse defense    │
│ Result: League-relative metrics in percentage points           │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: Identify Strengths & Weaknesses                         │
│ For each team:                                                  │
│ • strongest_zone = Zone with most negative vs_league_avg       │
│ • weakest_zone = Zone with most positive vs_league_avg         │
│ Example: LAL allows -1.2pp in mid-range (best), +0.5pp 3PT     │
│ Result: Categorical strength/weakness flags                    │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 6: Data Quality Tier Assignment                            │
│ Based on games_in_sample:                                       │
│ • High: ≥15 games                                               │
│ • Medium: 10-14 games                                           │
│ • Low: <10 games                                                │
│ Early season flag: <15 games AND <14 days since season start   │
│ Result: Quality metadata populated                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📋 Field Mappings

### Complete Field-by-Field Mapping

**Core Identifiers (2 fields)**

| Phase 4 Field | Phase 3 Source | Transformation |
|---------------|----------------|----------------|
| team_abbr | defending_team_abbr | Direct copy |
| analysis_date | Processor parameter | Input parameter (usually CURRENT_DATE()) |

**Paint Defense Metrics (5 fields)**

| Phase 4 Field | Calculation | Phase 3 Source Fields |
|---------------|-------------|----------------------|
| paint_pct_allowed_last_15 | SUM(opp_paint_makes) / SUM(opp_paint_attempts) | opp_paint_makes, opp_paint_attempts |
| paint_attempts_allowed_per_game | SUM(opp_paint_attempts) / 15 | opp_paint_attempts |
| paint_points_allowed_per_game | SUM(points_in_paint_allowed) / 15 | points_in_paint_allowed |
| paint_blocks_per_game | SUM(blocks_paint) / 15 | blocks_paint |
| paint_defense_vs_league_avg | (team_paint_pct - league_avg_paint_pct) × 100 | Calculated |

**Mid-Range Defense Metrics (4 fields)**

| Phase 4 Field | Calculation | Phase 3 Source Fields |
|---------------|-------------|----------------------|
| mid_range_pct_allowed_last_15 | SUM(opp_mid_range_makes) / SUM(opp_mid_range_attempts) | opp_mid_range_makes, opp_mid_range_attempts |
| mid_range_attempts_allowed_per_game | SUM(opp_mid_range_attempts) / 15 | opp_mid_range_attempts |
| mid_range_blocks_per_game | SUM(blocks_mid_range) / 15 | blocks_mid_range |
| mid_range_defense_vs_league_avg | (team_mid_pct - league_avg_mid_pct) × 100 | Calculated |

**Three-Point Defense Metrics (4 fields)**

| Phase 4 Field | Calculation | Phase 3 Source Fields |
|---------------|-------------|----------------------|
| three_pt_pct_allowed_last_15 | SUM(opp_three_pt_makes) / SUM(opp_three_pt_attempts) | opp_three_pt_makes, opp_three_pt_attempts |
| three_pt_attempts_allowed_per_game | SUM(opp_three_pt_attempts) / 15 | opp_three_pt_attempts |
| three_pt_blocks_per_game | SUM(blocks_three_pt) / 15 | blocks_three_pt |
| three_pt_defense_vs_league_avg | (team_3pt_pct - league_avg_3pt_pct) × 100 | Calculated |

**Overall Defensive Metrics (4 fields)**

| Phase 4 Field | Calculation | Phase 3 Source Fields |
|---------------|-------------|----------------------|
| defensive_rating_last_15 | AVG(defensive_rating) | defensive_rating |
| opponent_points_per_game | SUM(points_allowed) / 15 | points_allowed |
| opponent_pace | AVG(opponent_pace) | opponent_pace |
| games_in_sample | COUNT(*) | Row count per team |

**Strengths & Weaknesses (2 fields)**

| Phase 4 Field | Calculation | Logic |
|---------------|-------------|-------|
| strongest_zone | MIN(vs_league_avg) → zone name | Zone with most negative vs_league_avg |
| weakest_zone | MAX(vs_league_avg) → zone name | Zone with most positive vs_league_avg |

**Data Quality (4 fields)**

| Phase 4 Field | Calculation | Logic |
|---------------|-------------|-------|
| data_quality_tier | Based on games_in_sample | IF ≥15 THEN 'high' ELIF ≥10 THEN 'medium' ELSE 'low' |
| calculation_notes | Processor logic | Notes about issues (e.g., "No mid-range attempts") |
| early_season_flag | Processor logic | TRUE if games < 15 AND days_since_season_start < 14 |
| insufficient_data_reason | Processor logic | Explanation when early season |

**Source Tracking (3 fields - v4.0 spec)**

| Phase 4 Field | Value | Description |
|---------------|-------|-------------|
| source_team_defense_last_updated | MAX(processed_at) from Phase 3 | When source was last processed |
| source_team_defense_rows_found | COUNT(*) from extraction | Number of rows retrieved (should be 450 for 30 teams) |
| source_team_defense_completeness_pct | (rows_found / rows_expected) × 100 | Completeness percentage |

**Processing Metadata (2 fields)**

| Phase 4 Field | Value | Description |
|---------------|-------|-------------|
| processed_at | CURRENT_TIMESTAMP() | When Phase 4 processor ran |
| created_at | BigQuery default | When row was created |

---

## 📐 Calculation Examples

### Example 1: Lakers Paint Defense (Normal Season)

**Phase 3 Input (15 games):**
```
Game 1: 18 FGM / 32 FGA in paint = 56.3%
Game 2: 22 FGM / 38 FGA in paint = 57.9%
Game 3: 19 FGM / 34 FGA in paint = 55.9%
...
Game 15: 20 FGM / 35 FGA in paint = 57.1%

Totals:
- Total FGM: 300
- Total FGA: 525
- Total points: 630
- Total blocks: 30
```

**Phase 4 Calculations:**
```python
paint_pct_allowed = 300 / 525 = 0.571 (57.1%)
attempts_per_game = 525 / 15 = 35.0
points_per_game = 630 / 15 = 42.0
blocks_per_game = 30 / 15 = 2.0

# League average: 58.0%
vs_league_avg = (0.571 - 0.580) × 100 = -0.9 percentage points
```

**Phase 4 Output:**
```json
{
  "team_abbr": "LAL",
  "analysis_date": "2025-01-27",
  "paint_pct_allowed_last_15": 0.571,
  "paint_attempts_allowed_per_game": 35.0,
  "paint_points_allowed_per_game": 42.0,
  "paint_blocks_per_game": 2.0,
  "paint_defense_vs_league_avg": -0.9,
  "games_in_sample": 15,
  "data_quality_tier": "high"
}
```

**Interpretation:**
- LAL allows 57.1% shooting in paint (last 15 games)
- **0.9 percentage points BETTER than league average** (negative value)
- Opponents attempt 35.0 paint shots per game vs LAL
- LAL blocks 2.0 paint shots per game

---

### Example 2: Early Season (3 games available)

**Phase 3 Input (3 games):**
```
Game 1: 18 FGM / 32 FGA
Game 2: 22 FGM / 38 FGA
Game 3: 19 FGM / 34 FGA

Totals: 59 FGM / 104 FGA
```

**Phase 4 Logic:**
```python
games_in_sample = 3
days_since_season_start = 6
early_season = (games < 15 and days < 14) = True

# Write placeholder row with NULLs
```

**Phase 4 Output:**
```json
{
  "team_abbr": "LAL",
  "analysis_date": "2024-10-28",
  "paint_pct_allowed_last_15": null,
  "paint_attempts_allowed_per_game": null,
  "paint_points_allowed_per_game": null,
  "paint_blocks_per_game": null,
  "paint_defense_vs_league_avg": null,
  "games_in_sample": 3,
  "data_quality_tier": "low",
  "early_season_flag": true,
  "insufficient_data_reason": "Only 3 games available, need 15",
  "source_team_defense_last_updated": "2024-10-28T23:05:00Z",
  "source_team_defense_rows_found": 90,
  "source_team_defense_completeness_pct": 100.0
}
```

**Downstream Usage:**
Consumers filter out early season rows:
```sql
WHERE early_season_flag IS NULL OR early_season_flag = FALSE
```

---

## ⚠️ Known Issues & Edge Cases

### Issue 1: Zero Attempts in a Zone (Rare)
**Problem:** Some teams allow 0 mid-range attempts in a game (rare but possible)
**Solution:**
- Processor sets FG% to NULL for that zone
- Adds note to `calculation_notes`: "No mid-range attempts in sample"
- `vs_league_avg` will be NULL for that zone
**Impact:** Downstream consumers must handle NULL

### Issue 2: Early Season Data Sparsity
**Problem:** First 2 weeks of season, teams have <15 games
**Solution:**
- Processor writes placeholder rows with `early_season_flag = TRUE`
- All metrics set to NULL
- `insufficient_data_reason` populated with explanation
**Impact:** Consumers must filter: `WHERE early_season_flag IS NULL OR early_season_flag = FALSE`

### Issue 3: Missing Phase 3 Points Fields (Historical)
**Problem:** `mid_range_points_allowed` and `three_pt_points_allowed` were added to Phase 3 schema recently
**Solution:**
- Phase 4 handles NULL by calculating:
  - Mid-range points = `opp_mid_range_makes × 2`
  - Three-point points = `opp_three_pt_makes × 3`
**Status:** NOW PRESENT in Phase 3 schema (fixed)

### Issue 4: League Average Outliers
**Problem:** Team with extreme defensive performance skews league average
**Solution:**
- Require ≥10 games per team to include in league average calculation
- Use 30-day lookback (not just 15 games) for more stable averages
**Impact:** League averages are more representative

---

## ✅ Validation Rules

### Input Validation (Phase 3 Check)
- ✅ **All teams present:** Count distinct teams = 30
- ✅ **Sufficient games:** ≥25 teams have ≥15 games (normal season)
- ✅ **No NULL metrics:** All defensive fields NOT NULL (or processor handles)
- ✅ **Reasonable ranges:** FG% between 0.3-0.8
- ✅ **Data freshness:** `processed_at` < 24 hours old

### Output Validation (Phase 4 Check)
- ✅ **Team count:** COUNT(DISTINCT team_abbr) = 30
- ✅ **FG% ranges:**
  - Paint: 0.40-0.75
  - Mid-range: 0.30-0.55
  - Three-point: 0.25-0.45
- ✅ **Source tracking:** All 3 fields NOT NULL (100% populated)
- ✅ **Games in sample:** Normal season = 15 (consistent)
- ✅ **vs League centered:** AVG(vs_league_avg) ≈ 0 (within ±1.0 percentage points)

### Data Quality Tiers
```python
if games_in_sample >= 15:
    data_quality_tier = 'high'
elif games_in_sample >= 10:
    data_quality_tier = 'medium'
else:
    data_quality_tier = 'low'
```

---

## 📈 Success Criteria

**Processing Success:**
- ✅ 30 rows output (1 per team) for normal season dates
- ✅ Processing completes within 2 minutes
- ✅ All calculations complete (or NULL with reason documented)
- ✅ Source tracking populated for 100% of rows

**Data Quality Success:**
- ✅ ≥25 teams have `data_quality_tier = 'high'` (normal season)
- ✅ No NULL values in metrics (except early season or zero attempts)
- ✅ League averages within expected ranges (paint ~58%, mid-range ~41%, 3PT ~35.5%)
- ✅ All `vs_league_avg` values within ±10 percentage points

**Timing Success:**
- ✅ Phase 4 completes by 11:02 PM (2 minutes after start)
- ✅ Ready for downstream Player Shot Zone Analysis by 11:15 PM

---

## 🔗 Related Documentation

**Processor Implementation:**
- Code: `data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`

**Phase 3 Dependencies:**
- Schema: Run `bq show --schema nba_analytics.team_defense_game_summary`
- Source mapping: `docs/data-flow/04-phase2-to-phase3-team-defense.md`

**Phase 4 Output:**
- Schema: Run `bq show --schema nba_precompute.team_defense_zone_analysis`

**Downstream Consumers:**
- Player Shot Zone Analysis (Phase 4) - Reads this table to match player tendencies vs team defense
- Phase 5 Predictions - Uses league-relative metrics for matchup analysis

**Monitoring:**
- `docs/monitoring/` - Data quality metrics for Phase 4

---

## 📅 Processing Schedule

**Daily Pipeline Timing:**
```
10:00 PM - Phase 3 processes games
10:30 PM - Phase 3 completes
11:00 PM - Phase 4 Team Defense Zone Analysis starts
11:02 PM - Phase 4 Team Defense Zone Analysis completes
11:15 PM - Phase 4 Player Shot Zone Analysis starts (depends on Team Defense)
```

**Data Lag:**
- Phase 3 → Phase 4: ~30 minutes
- Game End → Phase 4: ~2 hours
- **Total Lag:** Games played at 7:00 PM are in Phase 4 by 11:00 PM same day

**Retention:**
- Phase 4 table: 90 days (partitioned by analysis_date)
- Automatic expiration via partition expiration

---

**Document Version:** 1.0
**Status:** ✅ Production Ready - All sources available, ready for deployment
**Next Steps:** Continue documenting remaining Phase 3→4 mappings
