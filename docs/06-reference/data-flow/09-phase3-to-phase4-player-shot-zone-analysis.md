# Phase 3→4 Mapping: Player Shot Zone Analysis

**File:** `docs/data-flow/09-phase3-to-phase4-player-shot-zone-analysis.md`
**Created:** 2025-10-30
**Last Updated:** 2025-11-15
**Purpose:** Data mapping from Phase 3 analytics to Phase 4 rolling window player shot zone precompute
**Audience:** Engineers implementing Phase 4 processors and debugging player shot selection analysis
**Status:** ✅ Production Ready - Implementation complete, all sources available

---

## 🚧 Current Deployment Status

**Implementation:** ✅ **COMPLETE**
- Phase 3 Source: `nba_analytics.player_game_summary` (EXISTS)
- Phase 4 Processor: `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py` (647 lines, 78 tests)
- Precompute Table: `nba_precompute.player_shot_zone_analysis` (created, 32 fields)

**Blocker:** ✅ **NONE - Ready for production**
- ✅ Phase 3 source table exists and is populated
- ✅ Phase 4 processor is implemented
- ✅ Phase 4 output table exists
- ✅ All dependencies satisfied

**Processing Strategy:**
- **Dual rolling windows:** Last 10 games (primary) + Last 20 games (trend comparison)
- **Nightly updates** at 11:15 PM (after Team Defense Zone Analysis completes)
- **90-day retention** in Phase 4 (partitioned by analysis_date)
- **Early season handling** for players with <10 games

**Consumers:**
- Phase 5 Predictions (player prop models)
- Shot selection analysis
- Matchup analysis (combined with team defense)
- Player performance forecasting

**See:** `docs/processors/` for Phase 4 deployment procedures

---

## 📊 Executive Summary

This Phase 4 processor transforms per-game player shot zone analytics from Phase 3 into **dual rolling windows** (10 & 20 games) with shot distribution, efficiency, volume, and creation metrics. It identifies each player's primary scoring zone and shooting tendencies, enabling downstream prop predictions and matchup analysis.

**Processor:** `player_shot_zone_analysis_processor.py`
**Output Table:** `nba_precompute.player_shot_zone_analysis`
**Processing Strategy:** MERGE_UPDATE (daily aggregation)
**Update Frequency:** Nightly at 11:15 PM
**Window Sizes:**
- **Primary:** Last 10 games (detailed metrics)
- **Trend:** Last 20 games (trend comparison)
**Granularity:** 1 row per player per day (~450 rows/day)

**Key Features:**
- **Dual rolling windows** - 10 games (recent form) vs 20 games (longer trend)
- **Shot distribution** - Paint, mid-range, three-point rate percentages
- **Shooting efficiency** - FG% by zone
- **Volume metrics** - Attempts per game by zone
- **Shot creation** - Assisted vs unassisted rate
- **Primary zone identification** - Automatically classify player's scoring preference
- **Early season handling** - Graceful degradation for players with <10 games
- **Quality tiers** - High/medium/low based on sample size

**Data Quality:** High - Depends on Phase 3 player game summary (~450 players × 20 games = ~9,000 input rows)

---

## 🗂️ Phase 3 Source (Analytics)

### Source 1: Player Game Summary (PRIMARY - CRITICAL)

**Table:** `nba_analytics.player_game_summary`
**Status:** ✅ **EXISTS**
**Update Frequency:** Nightly at ~10:30 PM (after games complete)
**Dependency:** CRITICAL - Only source for this processor
**Granularity:** One row per player per game

**Purpose:**
- Per-game player shot zone statistics
- Shot distribution by zone (paint, mid-range, three-point)
- Shooting efficiency by zone
- Shot creation (assisted vs unassisted)

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| player_lookup | STRING | Normalized player key |
| universal_player_id | STRING | Universal player ID |
| game_date | DATE | Game date (for windowing) |
| is_active | BOOLEAN | Player was active (not DNP) |
| minutes_played | NUMERIC | Minutes played (filter >0) |
| **Paint Zone (≤8 feet)** | | |
| paint_attempts | INT64 | Paint shot attempts |
| paint_makes | INT64 | Paint shot makes |
| **Mid-Range Zone (9+ feet, 2PT)** | | |
| mid_range_attempts | INT64 | Mid-range shot attempts |
| mid_range_makes | INT64 | Mid-range shot makes |
| **Three-Point Zone** | | |
| three_pt_attempts | INT64 | Three-point attempts |
| three_pt_makes | INT64 | Three-point makes |
| **Shot Creation** | | |
| fg_makes | INT64 | Total field goals made |
| assisted_fg_makes | INT64 | Assisted field goals |
| unassisted_fg_makes | INT64 | Unassisted field goals |
| **Metadata** | | |
| season_year | INT64 | Season year (for filtering) |

**Data Quality Requirements:**
- ✅ Active players only (is_active = TRUE)
- ✅ Players with >0 minutes played
- ✅ Games from current season only (starts Oct 1)
- ✅ Minimum 10 games for high-quality analysis

**Window Query Pattern:**
```sql
-- Get last 10 and 20 games per player
WITH ranked_games AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY player_lookup
      ORDER BY game_date DESC
    ) as game_rank
  FROM `nba_analytics.player_game_summary`
  WHERE game_date <= @analysis_date
    AND game_date >= @season_start_date
    AND is_active = TRUE
    AND minutes_played > 0
)
SELECT *
FROM ranked_games
WHERE game_rank <= 20  -- Take last 20 for trends
```

**Expected Input Volume:**
- **~450 active players** (typical game day)
- **20 games per player** = ~9,000 rows
- **Early season:** Variable (some players with <10 games)

---

## 🔄 Data Flow

### Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Extract Last 20 Games per Player                        │
│ Query: player_game_summary WHERE game_date <= target            │
│ Filter: is_active = TRUE AND minutes_played > 0                 │
│ Window: ROW_NUMBER() OVER (PARTITION BY player ORDER BY date)   │
│ Filter: WHERE game_rank <= 20                                   │
│ Result: ~9,000 rows (450 players × 20 games each)               │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Aggregate 10-Game Window (Primary Metrics)              │
│ For each player (WHERE game_rank <= 10):                        │
│ • Shot distribution: % of attempts by zone                      │
│   - paint_rate = (SUM(paint_att) / SUM(all_att)) × 100         │
│   - mid_range_rate = (SUM(mid_att) / SUM(all_att)) × 100       │
│   - three_pt_rate = (SUM(3pt_att) / SUM(all_att)) × 100        │
│ • Efficiency: FG% by zone                                       │
│   - paint_pct = SUM(paint_makes) / SUM(paint_att)              │
│ • Volume: Attempts per game by zone                             │
│   - paint_per_game = SUM(paint_att) / 10                       │
│ • Shot creation: Assisted vs unassisted                         │
│   - assisted_rate = (SUM(assisted) / SUM(fg_makes)) × 100      │
│ Result: Primary metrics for ~450 players                        │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: Aggregate 20-Game Window (Trend Comparison)             │
│ For each player (WHERE game_rank <= 20):                        │
│ • Calculate same metrics over 20 games                          │
│ • Purpose: Compare recent form (10 games) vs trend (20 games)  │
│ • Enables trend detection (improving/declining)                 │
│ Result: Trend metrics for ~450 players                          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: Identify Primary Scoring Zone                           │
│ For each player:                                                │
│ • IF paint_rate >= 40% → primary_scoring_zone = "paint"        │
│ • ELIF three_pt_rate >= 40% → "perimeter"                      │
│ • ELIF mid_range_rate >= 35% → "mid_range"                     │
│ • ELSE → "balanced"                                             │
│ Result: Categorical zone classification                         │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: Data Quality Tier Assignment                            │
│ Based on games_in_sample_10:                                    │
│ • High: >= 10 games                                             │
│ • Medium: 7-9 games                                             │
│ • Low: < 7 games                                                │
│ Sample quality levels:                                          │
│ • Excellent: >= 10 games                                        │
│ • Good: 7-9 games                                               │
│ • Limited: 5-6 games                                            │
│ • Insufficient: < 5 games                                       │
│ Result: Quality metadata populated                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📋 Field Mappings

### Complete Field-by-Field Mapping

**Core Identifiers (3 fields)**

| Phase 4 Field | Phase 3 Source | Transformation |
|---------------|----------------|----------------|
| player_lookup | player_lookup | Direct copy |
| universal_player_id | universal_player_id | Direct copy (first value) |
| analysis_date | Processor parameter | Input parameter (usually CURRENT_DATE()) |

**Shot Distribution - 10 Game Window (4 fields)**

| Phase 4 Field | Calculation | Phase 3 Source Fields |
|---------------|-------------|----------------------|
| paint_rate_last_10 | (SUM(paint_attempts) / SUM(all_attempts)) × 100 | paint_attempts, total attempts |
| mid_range_rate_last_10 | (SUM(mid_range_attempts) / SUM(all_attempts)) × 100 | mid_range_attempts, total attempts |
| three_pt_rate_last_10 | (SUM(three_pt_attempts) / SUM(all_attempts)) × 100 | three_pt_attempts, total attempts |
| total_shots_last_10 | SUM(paint_att + mid_range_att + three_pt_att) | All zone attempts |

**Shooting Efficiency - 10 Game Window (3 fields)**

| Phase 4 Field | Calculation | Phase 3 Source Fields |
|---------------|-------------|----------------------|
| paint_pct_last_10 | SUM(paint_makes) / SUM(paint_attempts) | paint_makes, paint_attempts |
| mid_range_pct_last_10 | SUM(mid_range_makes) / SUM(mid_range_attempts) | mid_range_makes, mid_range_attempts |
| three_pt_pct_last_10 | SUM(three_pt_makes) / SUM(three_pt_attempts) | three_pt_makes, three_pt_attempts |

**Volume Metrics - 10 Game Window (3 fields)**

| Phase 4 Field | Calculation | Phase 3 Source Fields |
|---------------|-------------|----------------------|
| paint_attempts_per_game | SUM(paint_attempts) / COUNT(games) | paint_attempts |
| mid_range_attempts_per_game | SUM(mid_range_attempts) / COUNT(games) | mid_range_attempts |
| three_pt_attempts_per_game | SUM(three_pt_attempts) / COUNT(games) | three_pt_attempts |

**Shot Creation - 10 Game Window (2 fields)**

| Phase 4 Field | Calculation | Phase 3 Source Fields |
|---------------|-------------|----------------------|
| assisted_rate_last_10 | (SUM(assisted_fg_makes) / SUM(fg_makes)) × 100 | assisted_fg_makes, fg_makes |
| unassisted_rate_last_10 | (SUM(unassisted_fg_makes) / SUM(fg_makes)) × 100 | unassisted_fg_makes, fg_makes |

**Trend Comparison - 20 Game Window (2 fields)**

| Phase 4 Field | Calculation | Phase 3 Source Fields |
|---------------|-------------|----------------------|
| paint_rate_last_20 | Same as 10-game, but over 20 games | paint_attempts (20 games) |
| paint_pct_last_20 | Same as 10-game, but over 20 games | paint_makes, paint_attempts (20 games) |

**Sample Quality Metrics (4 fields)**

| Phase 4 Field | Calculation | Logic |
|---------------|-------------|-------|
| games_in_sample_10 | COUNT(games WHERE game_rank <= 10) | Row count |
| games_in_sample_20 | COUNT(games WHERE game_rank <= 20) | Row count |
| sample_quality_10 | Based on games count | excellent (≥10), good (7-9), limited (5-6), insufficient (<5) |
| sample_quality_20 | Based on games count | excellent (≥20), good (14-19), limited (10-13), insufficient (<10) |

**Derived Fields (3 fields)**

| Phase 4 Field | Calculation | Logic |
|---------------|-------------|-------|
| primary_scoring_zone | Based on distribution rates | paint (≥40%), perimeter (3PT≥40%), mid_range (≥35%), balanced (else) |
| data_quality_tier | Based on games_in_sample_10 | high (≥10), medium (7-9), low (<7) |
| early_season_flag | Processor logic | TRUE if games < 10 AND days_since_season_start < 14 |

**Processing Metadata (2 fields)**

| Phase 4 Field | Value | Description |
|---------------|-------|-------------|
| processed_at | CURRENT_TIMESTAMP() | When Phase 4 processor ran |
| created_at | BigQuery default | When row was created |

---

## 📐 Calculation Examples

### Example 1: LeBron James (Normal Season - 10 Games)

**Phase 3 Input (10 games):**
```
Game 1 (2025-01-27): 8 paint, 4 mid, 6 three = 18 total attempts
Game 2 (2025-01-26): 8 paint, 4 mid, 6 three = 18 total attempts
...
Game 10 (2025-01-18): 8 paint, 4 mid, 6 three = 18 total attempts

Totals:
- Paint: 80 attempts, 50 makes
- Mid-range: 40 attempts, 20 makes
- Three-point: 60 attempts, 20 makes
- Total: 180 attempts, 90 makes
- Assisted: 60 makes
- Unassisted: 30 makes
```

**Phase 4 Calculations:**
```python
# Shot distribution (rates)
total_attempts = 80 + 40 + 60 = 180
paint_rate = (80 / 180) × 100 = 44.44%
mid_range_rate = (40 / 180) × 100 = 22.22%
three_pt_rate = (60 / 180) × 100 = 33.33%

# Efficiency (FG%)
paint_pct = 50 / 80 = 0.625 (62.5%)
mid_range_pct = 20 / 40 = 0.500 (50.0%)
three_pt_pct = 20 / 60 = 0.333 (33.3%)

# Volume (per game)
paint_per_game = 80 / 10 = 8.0
mid_range_per_game = 40 / 10 = 4.0
three_pt_per_game = 60 / 10 = 6.0

# Shot creation
assisted_rate = (60 / 90) × 100 = 66.67%
unassisted_rate = (30 / 90) × 100 = 33.33%

# Primary zone
# paint_rate = 44.44% >= 40% → primary_scoring_zone = "paint"
```

**Phase 4 Output:**
```json
{
  "player_lookup": "lebronjames",
  "universal_player_id": "lebronjames_001",
  "analysis_date": "2025-01-27",

  "paint_rate_last_10": 44.44,
  "mid_range_rate_last_10": 22.22,
  "three_pt_rate_last_10": 33.33,
  "total_shots_last_10": 180,

  "paint_pct_last_10": 0.625,
  "mid_range_pct_last_10": 0.500,
  "three_pt_pct_last_10": 0.333,

  "paint_attempts_per_game": 8.0,
  "mid_range_attempts_per_game": 4.0,
  "three_pt_attempts_per_game": 6.0,

  "assisted_rate_last_10": 66.67,
  "unassisted_rate_last_10": 33.33,

  "games_in_sample_10": 10,
  "sample_quality_10": "excellent",
  "data_quality_tier": "high",

  "primary_scoring_zone": "paint"
}
```

**Interpretation:**
- LeBron takes 44% of his shots in the paint (primary zone)
- Highly efficient in paint (62.5% FG%)
- Averages 8.0 paint attempts per game
- 67% of his makes are assisted (catch-and-finish style)

---

### Example 2: Early Season (3 games available)

**Phase 3 Input (3 games):**
```
Game 1: 8 paint, 4 mid, 6 three
Game 2: 8 paint, 4 mid, 6 three
Game 3: 8 paint, 4 mid, 6 three

Totals: 24 paint, 12 mid, 18 three
```

**Phase 4 Logic:**
```python
games_in_sample_10 = 3
days_since_season_start = 6
early_season = (games < 10 and days < 14) = True

# Write placeholder row with NULLs
```

**Phase 4 Output:**
```json
{
  "player_lookup": "rookieplayer",
  "universal_player_id": "rookieplayer_001",
  "analysis_date": "2024-10-28",

  "paint_rate_last_10": null,
  "mid_range_rate_last_10": null,
  "three_pt_rate_last_10": null,
  "total_shots_last_10": null,

  "paint_pct_last_10": null,
  "mid_range_pct_last_10": null,
  "three_pt_pct_last_10": null,

  "games_in_sample_10": 3,
  "sample_quality_10": "insufficient",
  "data_quality_tier": "low",
  "early_season_flag": true,
  "insufficient_data_reason": "Only 3 games available, need 10"
}
```

---

## ⚠️ Known Issues & Edge Cases

### Issue 1: Zero Attempts in a Zone
**Problem:** Player has 0 attempts in a zone (e.g., center never takes three-pointers)
**Solution:**
- Processor sets zone_pct to NULL (prevents division by zero)
- zone_rate will be 0.0%
**Impact:** Downstream consumers must handle NULL in efficiency metrics

### Issue 2: Early Season Data Sparsity
**Problem:** First 2 weeks of season, players have <10 games
**Solution:**
- Processor writes placeholder rows with `early_season_flag = TRUE`
- All metrics set to NULL
- `insufficient_data_reason` populated
**Impact:** Consumers must filter: `WHERE early_season_flag IS NULL OR early_season_flag = FALSE`

### Issue 3: DNP Games (Did Not Play)
**Problem:** Player has DNP games mixed with active games
**Solution:**
- Filter: `WHERE is_active = TRUE AND minutes_played > 0`
- Only count games where player actually played
**Impact:** Games count may be less than expected

### Issue 4: Primary Zone Classification Edge Cases
**Problem:** Player is truly balanced (33%/33%/33% split)
**Solution:**
- Apply thresholds in order (paint 40% → perimeter 40% → mid-range 35%)
- Default to "balanced" if no threshold met
**Impact:** "balanced" category captures versatile scorers

---

## ✅ Validation Rules

### Input Validation (Phase 3 Check)
- ✅ **Active players only:** is_active = TRUE
- ✅ **Minutes filter:** minutes_played > 0
- ✅ **Season filter:** Games from current season only
- ✅ **Minimum games:** ≥10 games for high-quality analysis

### Output Validation (Phase 4 Check)
- ✅ **Rate sum:** paint_rate + mid_range_rate + three_pt_rate ≈ 100% (±1% tolerance)
- ✅ **Creation sum:** assisted_rate + unassisted_rate ≈ 100% (±1% tolerance)
- ✅ **FG% range:** All percentages between 0.0 and 1.0
- ✅ **Primary zone logic:** Matches rate thresholds
- ✅ **Games consistency:** games_in_sample_10 <= games_in_sample_20

### Data Quality Tiers
```python
if games_in_sample_10 >= 10:
    data_quality_tier = 'high'
elif games_in_sample_10 >= 7:
    data_quality_tier = 'medium'
else:
    data_quality_tier = 'low'
```

---

## 📈 Success Criteria

**Processing Success:**
- ✅ ~450 rows output (1 per active player) for normal season dates
- ✅ Processing completes within 5-8 minutes
- ✅ All calculations complete (or NULL with reason documented)
- ✅ No joins required (single table processing)

**Data Quality Success:**
- ✅ ≥300 players have `data_quality_tier = 'high'` (normal season)
- ✅ Rate sums validate to 100% (±1%)
- ✅ FG% values within realistic ranges (paint 45-70%, mid 35-50%, 3PT 25-45%)
- ✅ Primary zone classifications are logical

**Timing Success:**
- ✅ Phase 4 completes by 11:23 PM (8 minutes after start)
- ✅ Ready for downstream Phase 5 predictions

---

## 🔗 Related Documentation

**Processor Implementation:**
- Code: `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py`

**Phase 3 Dependencies:**
- Schema: Run `bq show --schema nba_analytics.player_game_summary`
- Source mapping: `docs/data-flow/07-phase2-to-phase3-player-game-summary.md`

**Phase 4 Output:**
- Schema: Run `bq show --schema nba_precompute.player_shot_zone_analysis`

**Downstream Consumers:**
- Phase 5 Predictions (player prop models)
- Matchup analysis (combined with team defense zone analysis)

**Monitoring:**
- `docs/monitoring/` - Data quality metrics for Phase 4

---

## 📅 Processing Schedule

**Daily Pipeline Timing:**
```
10:30 PM - Phase 3 player_game_summary completes
11:00 PM - Phase 4 Team Defense Zone Analysis starts
11:02 PM - Phase 4 Team Defense completes
11:15 PM - Phase 4 Player Shot Zone Analysis starts
11:23 PM - Phase 4 Player Shot Zone Analysis completes (~8 min)
```

**Data Lag:**
- Phase 3 → Phase 4: ~45 minutes
- Game End → Phase 4: ~2.5 hours
- **Total Lag:** Games played at 7:00 PM are in Phase 4 by 11:23 PM same day

**Retention:**
- Phase 4 table: 90 days (partitioned by analysis_date)
- Automatic expiration via partition expiration

---

## 🎯 Formula Reference

**Distribution Rate:**
```python
zone_rate = (zone_attempts / total_attempts) × 100
```

**Efficiency (FG%):**
```python
zone_pct = zone_makes / zone_attempts  # NULL if attempts = 0
```

**Volume:**
```python
zone_per_game = zone_attempts / games_count
```

**Creation Rate:**
```python
creation_rate = (creation_type_makes / total_makes) × 100
```

---

**Document Version:** 1.0
**Status:** ✅ Production Ready - All sources available, ready for deployment
**Next Steps:** Continue documenting remaining Phase 3→4 mappings (3 more docs to reformat)
