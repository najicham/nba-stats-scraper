# Phase 3→4 Mapping: ML Feature Store V2

**File:** `docs/data-flow/12-phase3-to-phase4-ml-feature-store-v2.md`
**Created:** 2025-11-08
**Last Updated:** 2025-11-25
**Purpose:** Data mapping from Phase 3 analytics and Phase 4 precompute to unified ML feature store
**Audience:** Engineers implementing Phase 5 predictions and debugging ML feature generation
**Status:** ✅ Production Ready - Deployed and operational

---

## ✅ Current Deployment Status

**Implementation:** ✅ **COMPLETE**
- Phase 3 Sources: `nba_analytics.upcoming_player_game_context`, `nba_analytics.player_game_summary`, `nba_analytics.team_offense_game_summary` (ALL EXIST)
- Phase 4 Sources: `nba_precompute.player_daily_cache`, `nba_precompute.player_composite_factors`, `nba_precompute.player_shot_zone_analysis`, `nba_precompute.team_defense_zone_analysis` (ALL EXIST)
- Phase 4 Processor: `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` (1115 lines, 158 tests)
- Output Table: `nba_predictions.ml_feature_store_v2` (✅ DEPLOYED, 30 fields)

**Status:** ✅ **All systems operational**
- ✅ All Phase 3 source tables exist
- ✅ All Phase 4 dependency tables exist
- ✅ Processor code is implemented
- ✅ Output table `nba_predictions.ml_feature_store_v2` deployed
- ✅ Cross-dataset write permissions configured

**Processing Strategy:**
- **Flexible array-based design:** 25 features stored as ARRAY<FLOAT64>
- **Three-tier fallback:** Phase 4 (preferred) → Phase 3 (fallback) → Defaults (last resort)
- **Nightly updates** at 12:00 AM (after all Phase 4 processors complete)
- **Quality scoring:** Weighted by data source (phase4=100, phase3=75, default=40)
- **Early season handling:** NULL feature arrays with early_season_flag = TRUE

**Consumers:**
- Phase 5 Prediction Models (XGBoost, ensemble)
- Phase 5 Confidence Scoring
- ML model training pipelines

**See:** `docs/processors/` for Phase 4 deployment procedures

---

## 📊 Executive Summary

This Phase 4 processor creates a **unified ML feature store** by extracting 25 features from 7 source tables (3 Phase 3 + 4 Phase 4). It's the final Phase 4 processor that consolidates all precompute outputs into a single ML-ready table.

**Processor:** `ml_feature_store_processor.py`
**Output Table:** `nba_predictions.ml_feature_store_v2`
**Processing Strategy:** MERGE_UPDATE (daily feature extraction)
**Update Frequency:** Nightly at 12:00 AM
**Feature Count:** 25 features (stored as array)
**Granularity:** 1 row per player per game_date (~450 rows/day)

**Key Features:**
- **Multi-source integration** - 7 tables (3 Phase 3 + 4 Phase 4)
- **25 ML features** - Performance, composite, derived, matchup, shot zones, team context
- **Flexible array design** - Features stored as ARRAY<FLOAT64> for easy evolution
- **Three-tier fallback** - Phase 4 → Phase 3 → Defaults
- **Quality scoring** - 0-100 score based on data source weights
- **v4.0 dependency tracking** - 12 source tracking fields (4 sources × 3 fields)
- **Early season handling** - Placeholder rows with NULL features

**Data Quality:** Variable - Highest when all Phase 4 sources complete, degrades gracefully to Phase 3 fallback

**Innovation:** Array-based storage allows adding features (25→47+) without schema changes or breaking existing queries.

---

## 🗂️ Phase 3 Sources (Analytics) - Fallback

### Source 1: Upcoming Player Game Context (FALLBACK)

**Table:** `nba_analytics.upcoming_player_game_context`
**Status:** ✅ **EXISTS**
**Update Frequency:** Nightly at ~6:00 AM
**Dependency:** FALLBACK - Used when Phase 4 incomplete
**Granularity:** One row per player per game_date
**Features Provided:** 15-17 (game context), data for calculated features (9-12)

**Key Fields Used:**

| Field | Type | Feature(s) | Usage |
|-------|------|-----------|--------|
| home_game | BOOLEAN | 15 | Boolean to float (0.0/1.0) |
| back_to_back | BOOLEAN | 16 | Boolean to float (0.0/1.0) |
| season_phase | STRING | 17 | "playoffs" → 1.0, else 0.0 |
| days_rest | INT64 | 9 | For rest_advantage calculation |
| opponent_days_rest | INT64 | 9 | For rest_advantage calculation |
| player_status | STRING | 10 | Map to injury_risk score |

---

### Source 2: Player Game Summary (FALLBACK)

**Table:** `nba_analytics.player_game_summary`
**Status:** ✅ **EXISTS**
**Update Frequency:** After each game (nightly ~10:30 PM)
**Dependency:** FALLBACK - Used for Features 0-4, 9-12, 18-21
**Granularity:** One row per player per game
**Features Provided:** Fallback for performance (0-4), shot zones (18-20), calculated features

**Key Fields Used:**

| Field | Type | Feature(s) | Usage |
|-------|------|-----------|--------|
| points | INT64 | 0-4, 11 | Aggregate for averages, trend |
| minutes_played | NUMERIC(5,1) | 12 | Minutes change calculation |
| ft_makes | INT64 | 21 | Free throw percentage |
| paint_attempts | INT64 | 18 | Paint shot rate fallback |
| mid_range_attempts | INT64 | 19 | Mid-range shot rate fallback |
| three_pt_attempts | INT64 | 20 | Three-point shot rate fallback |
| fg_attempts | INT64 | 18-20 | Total attempts denominator |

---

### Source 3: Team Offense Game Summary (FALLBACK)

**Table:** `nba_analytics.team_offense_game_summary`
**Status:** ✅ **EXISTS**
**Update Frequency:** After each game (nightly ~10:30 PM)
**Dependency:** FALLBACK - Used for Feature 24
**Granularity:** One row per team per game
**Features Provided:** 24 (team_win_pct)

**Key Fields Used:**

| Field | Type | Feature(s) | Usage |
|-------|------|-----------|--------|
| win_flag | BOOLEAN | 24 | Count wins for win percentage |
| game_date | DATE | 24 | Filter to current season |
| season_year | INT64 | 24 | Filter to current season |

---

## Phase 4 Sources (Precompute) - Preferred

### Source 4: Player Daily Cache (PRIMARY - PREFERRED)

**Table:** `nba_precompute.player_daily_cache`
**Status:** ✅ **EXISTS**
**Update Frequency:** Nightly at 11:45 PM
**Dependency:** PRIMARY - Preferred source for Features 0-4, 18, 20, 22-23
**Granularity:** One row per player per cache_date
**Features Provided:** 0-4 (performance), 18, 20 (partial shot zones), 22-23 (team context)

**Key Fields Used:**

| Field | Type | Feature(s) | Notes |
|-------|------|-----------|-------|
| points_avg_last_5 | NUMERIC(5,1) | 0 | Feature 0 |
| points_avg_last_10 | NUMERIC(5,1) | 1 | Feature 1 |
| points_avg_season | NUMERIC(5,1) | 2 | Feature 2 |
| points_std_last_10 | NUMERIC(5,2) | 3 | Feature 3 |
| games_in_last_7_days | INT64 | 4 | Feature 4 |
| paint_rate_last_10 | NUMERIC(5,2) | 18 | Convert to decimal (÷100) |
| three_pt_rate_last_10 | NUMERIC(5,2) | 20 | Convert to decimal (÷100) |
| team_pace_last_10 | NUMERIC(5,1) | 22 | Feature 22 |
| team_off_rating_last_10 | NUMERIC(6,2) | 23 | Feature 23 |
| minutes_avg_last_10 | NUMERIC(5,1) | 12 | For minutes_change calc |
| player_age | INT64 | - | Player characteristic |

---

### Source 5: Player Composite Factors (PRIMARY - CRITICAL)

**Table:** `nba_precompute.player_composite_factors`
**Status:** ✅ **EXISTS**
**Update Frequency:** Nightly at 11:30 PM
**Dependency:** PRIMARY - **NO Phase 3 fallback** (Phase 4 only)
**Granularity:** One row per player per game_date
**Features Provided:** 5-8 (composite factors)

**Key Fields Used:**

| Field | Type | Feature(s) | Default if Missing |
|-------|------|-----------|-------------------|
| fatigue_score | INT64 | 5 | 50.0 (neutral) |
| shot_zone_mismatch_score | NUMERIC(4,1) | 6 | 0.0 (neutral) |
| pace_score | NUMERIC(3,1) | 7 | 0.0 (neutral) |
| usage_spike_score | NUMERIC(3,1) | 8 | 0.0 (neutral) |

**Critical:** These features are pre-computed and don't exist in Phase 3. If Phase 4 is incomplete, defaults are used.

---

### Source 6: Player Shot Zone Analysis (PRIMARY - PREFERRED)

**Table:** `nba_precompute.player_shot_zone_analysis`
**Status:** ✅ **EXISTS**
**Update Frequency:** Nightly at 11:15 PM
**Dependency:** PRIMARY - Preferred source for Features 18-20
**Granularity:** One row per player per analysis_date
**Features Provided:** 18-20 (shot zones)

**Key Fields Used:**

| Field | Type | Feature(s) | Notes |
|-------|------|-----------|-------|
| paint_rate_last_10 | NUMERIC(5,2) | 18 | Convert to decimal (÷100) |
| mid_range_rate_last_10 | NUMERIC(5,2) | 19 | Convert to decimal (÷100) |
| three_pt_rate_last_10 | NUMERIC(5,2) | 20 | Convert to decimal (÷100) |

**Note:** Includes mid_range_rate which player_daily_cache doesn't have.

---

### Source 7: Team Defense Zone Analysis (PRIMARY - PREFERRED)

**Table:** `nba_precompute.team_defense_zone_analysis`
**Status:** ✅ **EXISTS**
**Update Frequency:** Nightly at 11:00 PM
**Dependency:** PRIMARY - Preferred source for Features 13-14
**Granularity:** One row per team per analysis_date
**Features Provided:** 13-14 (opponent defense)

**Key Fields Used:**

| Field | Type | Feature(s) | Notes |
|-------|------|-----------|-------|
| defensive_rating_last_15 | NUMERIC(6,2) | 13 | As opponent_def_rating |
| opponent_pace | NUMERIC(5,1) | 14 | Feature 14 |

---

## 🔄 Data Flow

### Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Dependency Validation (All 4 Phase 4 tables)            │
│ Check: player_daily_cache, player_composite_factors,           │
│        player_shot_zone_analysis, team_defense_zone_analysis   │
│ Requirements: All <2 hours old, ≥100 players, ≥20 teams        │
│ Result: all_critical_present, all_fresh flags                  │
│ Early Season: If >50% players have early_season_flag → placeholders│
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Extract Features (Three-Tier Fallback)                  │
│                                                                  │
│ For each of 25 features:                                        │
│                                                                  │
│ Tier 1 (Preferred): Try Phase 4 table                          │
│ • Features 0-4: player_daily_cache                              │
│ • Features 5-8: player_composite_factors (NO fallback)          │
│ • Features 13-14: team_defense_zone_analysis                    │
│ • Features 18-20: player_shot_zone_analysis                     │
│ • Features 22-23: player_daily_cache                            │
│                                                                  │
│ Tier 2 (Fallback): Try Phase 3 table                           │
│ • Features 0-4: Aggregate from player_game_summary              │
│ • Features 15-17: upcoming_player_game_context                  │
│ • Features 18-20: Calculate from player_game_summary            │
│ • Feature 22-23: Aggregate from team_offense_summary            │
│                                                                  │
│ Tier 3 (Default): Hardcoded defaults                           │
│ • Feature 0-2: 10.0 points                                      │
│ • Feature 3: 5.0 (stddev)                                       │
│ • Feature 5-8: Neutral values (50.0, 0.0, 0.0, 0.0)            │
│ • Features 13-14: League average (112.0, 100.0)                 │
│ • And so on...                                                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: Calculate Derived Features (6 features)                 │
│                                                                  │
│ Feature 9 - rest_advantage:                                     │
│ • player_rest - opponent_rest (clamped to [-2, 2])             │
│                                                                  │
│ Feature 10 - injury_risk:                                       │
│ • Map player_status → 0.0/1.0/2.0/3.0                          │
│                                                                  │
│ Feature 11 - recent_trend:                                      │
│ • Compare avg(first 3 games) vs avg(last 2 games)              │
│ • Map to -2.0/-1.0/0.0/+1.0/+2.0                                │
│                                                                  │
│ Feature 12 - minutes_change:                                    │
│ • (recent_minutes - season_avg) / season_avg                    │
│ • Map to -2.0/-1.0/0.0/+1.0/+2.0                                │
│                                                                  │
│ Feature 21 - pct_free_throw:                                    │
│ • SUM(ft_makes) / SUM(points) last 10 games                     │
│ • Clamp to [0.0, 0.5]                                           │
│                                                                  │
│ Feature 24 - team_win_pct:                                      │
│ • SUM(wins) / COUNT(games) current season                       │
│ • Range [0.0, 1.0]                                              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: Quality Scoring                                         │
│ Track source for each feature:                                  │
│ • 'phase4' = 100 points                                         │
│ • 'phase3' = 75 points                                          │
│ • 'calculated' = 100 points                                     │
│ • 'default' = 40 points                                         │
│                                                                  │
│ Quality Score = (sum of all weights) / 25                       │
│ Tiers: 95-100=Excellent, 85-94=Good, 70-84=Medium, <70=Low    │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: Package as Array + Metadata                             │
│ • features: ARRAY<FLOAT64> (25 values)                         │
│ • feature_names: ARRAY<STRING> (25 labels)                     │
│ • feature_count: 25                                             │
│ • feature_version: "v1_baseline_25"                             │
│ • feature_quality_score: 0-100                                  │
│ • data_source: 'phase4'/'phase3'/'mixed'/'early_season'         │
│ • Source tracking: 12 fields (v4.0 spec)                        │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 6: Handle Early Season                                     │
│ If early_season (>50% players lack data):                       │
│ • features = [null, null, ..., null] (25 nulls)                │
│ • early_season_flag = TRUE                                      │
│ • insufficient_data_reason = "Early season: X/450 players..."  │
│ • Phase 5 systems skip these rows                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📋 Field Mappings

### Complete Feature Mapping (25 Features)

**Core Identifiers (4 fields)**

| Phase 4 Field | Source | Description |
|---------------|--------|-------------|
| player_lookup | Phase 3 context | Player identifier |
| universal_player_id | Phase 3 context | Stable player ID |
| game_date | Processor input | Game date (partition key) |
| game_id | Phase 3 context | Unique game identifier |

**Feature Array (4 fields)**

| Phase 4 Field | Type | Description |
|---------------|------|-------------|
| features | ARRAY<FLOAT64> | 25 feature values |
| feature_names | ARRAY<STRING> | 25 feature labels |
| feature_count | INT64 | Always 25 (version tracking) |
| feature_version | STRING | "v1_baseline_25" |

**25 Features by Category:**

**Category 1: Recent Performance (Features 0-4)**

| # | Name | Primary Source | Fallback | Default | Range |
|---|------|---------------|----------|---------|-------|
| 0 | points_avg_last_5 | player_daily_cache | player_game_summary | 10.0 | 0-50 |
| 1 | points_avg_last_10 | player_daily_cache | player_game_summary | 10.0 | 0-50 |
| 2 | points_avg_season | player_daily_cache | player_game_summary | 10.0 | 0-50 |
| 3 | points_std_last_10 | player_daily_cache | player_game_summary | 5.0 | 0-20 |
| 4 | games_in_last_7_days | player_daily_cache | upcoming_player_context | 3.0 | 0-7 |

**Category 2: Composite Factors (Features 5-8) - Phase 4 ONLY**

| # | Name | Primary Source | Fallback | Default | Range |
|---|------|---------------|----------|---------|-------|
| 5 | fatigue_score | player_composite_factors | **NONE** | 50.0 | 0-100 |
| 6 | shot_zone_mismatch_score | player_composite_factors | **NONE** | 0.0 | -10 to +10 |
| 7 | pace_score | player_composite_factors | **NONE** | 0.0 | -3 to +3 |
| 8 | usage_spike_score | player_composite_factors | **NONE** | 0.0 | -3 to +3 |

**Category 3: Derived Factors (Features 9-12) - Calculated**

| # | Name | Calculation | Source | Range |
|---|------|-------------|--------|-------|
| 9 | rest_advantage | player_rest - opponent_rest | upcoming_player_context | -2 to +2 |
| 10 | injury_risk | Map status → score | upcoming_player_context | 0-3 |
| 11 | recent_trend | avg(last2) - avg(first3) | player_game_summary | -2 to +2 |
| 12 | minutes_change | (recent - season) / season | player_daily_cache | -10 to +10 |

**Category 4: Matchup Context (Features 13-17)**

| # | Name | Primary Source | Fallback | Default | Range |
|---|------|---------------|----------|---------|-------|
| 13 | opponent_def_rating | team_defense_zone_analysis | player_game_summary | 112.0 | 100-130 |
| 14 | opponent_pace | team_defense_zone_analysis | player_game_summary | 100.0 | 95-105 |
| 15 | home_away | N/A | upcoming_player_context | 0.5 | 0 or 1 |
| 16 | back_to_back | N/A | upcoming_player_context | 0.0 | 0 or 1 |
| 17 | playoff_game | N/A | upcoming_player_context | 0.0 | 0 or 1 |

**Category 5: Shot Zones (Features 18-21)**

| # | Name | Primary Source | Fallback | Default | Range |
|---|------|---------------|----------|---------|-------|
| 18 | pct_paint | player_shot_zone_analysis | player_game_summary | 0.30 | 0-1 |
| 19 | pct_mid_range | player_shot_zone_analysis | player_game_summary | 0.20 | 0-1 |
| 20 | pct_three | player_shot_zone_analysis | player_game_summary | 0.35 | 0-1 |
| 21 | pct_free_throw | N/A (calculated) | player_game_summary | 0.15 | 0-0.5 |

**Category 6: Team Context (Features 22-24)**

| # | Name | Primary Source | Fallback | Default | Range |
|---|------|---------------|----------|---------|-------|
| 22 | team_pace | player_daily_cache | team_offense_summary | 100.0 | 95-105 |
| 23 | team_off_rating | player_daily_cache | team_offense_summary | 112.0 | 100-130 |
| 24 | team_win_pct | N/A (calculated) | team_offense_summary | 0.500 | 0-1 |

**Feature Metadata (2 fields)**

| Phase 4 Field | Calculation | Description |
|---------------|-------------|-------------|
| feature_generation_time_ms | Processor timing | Processing time per player |
| feature_quality_score | Quality scorer | 0-100 weighted average |

**Player Context (3 fields)**

| Phase 4 Field | Source | Description |
|---------------|--------|-------------|
| opponent_team_abbr | Phase 3 context | Opponent team |
| is_home | Phase 3 context | Home game flag |
| days_rest | Phase 3 context | Rest days before game |

**Data Source (1 field)**

| Phase 4 Field | Values | Description |
|---------------|--------|-------------|
| data_source | 'phase4', 'phase3', 'mixed', 'early_season' | Primary source indicator |

**Source Tracking (12 fields - v4.0 spec)**

| Phase 4 Field | Description |
|---------------|-------------|
| source_daily_cache_last_updated | When cache was updated |
| source_daily_cache_rows_found | Rows found in cache |
| source_daily_cache_completeness_pct | % complete |
| source_composite_last_updated | When composite updated |
| source_composite_rows_found | Rows found |
| source_composite_completeness_pct | % complete |
| source_shot_zones_last_updated | When shot zones updated |
| source_shot_zones_rows_found | Rows found |
| source_shot_zones_completeness_pct | % complete |
| source_team_defense_last_updated | When team defense updated |
| source_team_defense_rows_found | Rows found |
| source_team_defense_completeness_pct | % complete |

**Early Season (2 fields)**

| Phase 4 Field | Calculation | Description |
|---------------|-------------|-------------|
| early_season_flag | Processor logic | TRUE if insufficient data |
| insufficient_data_reason | Processor logic | Explanation |

**Processing Metadata (2 fields)**

| Phase 4 Field | Value | Description |
|---------------|-------|-------------|
| created_at | CURRENT_TIMESTAMP() | When row was created |
| updated_at | NULL | Reserved for updates |

---

## 📐 Calculation Examples

### Example 1: LeBron James - All Phase 4 Sources Complete (High Quality)

**Phase 4 Input:**
- player_daily_cache: ✅ All performance features available
- player_composite_factors: ✅ All composite factors available
- player_shot_zone_analysis: ✅ Shot zones available
- team_defense_zone_analysis: ✅ Opponent defense available

**Feature Extraction:**
```python
# Features 0-4: From player_daily_cache (phase4)
features[0] = 25.2  # points_avg_last_5
features[1] = 24.8  # points_avg_last_10
features[2] = 24.5  # points_avg_season
features[3] = 4.23  # points_std_last_10
features[4] = 3.0   # games_in_last_7_days

# Features 5-8: From player_composite_factors (phase4)
features[5] = 75.0  # fatigue_score
features[6] = 3.5   # shot_zone_mismatch_score
features[7] = 1.5   # pace_score
features[8] = 0.8   # usage_spike_score

# Features 9-12: Calculated
features[9] = 0.0   # rest_advantage (1 - 1)
features[10] = 0.0  # injury_risk (available)
features[11] = -2.0 # recent_trend (declining)
features[12] = 1.0  # minutes_change (+16%)

# Features 13-14: From team_defense_zone_analysis (phase4)
features[13] = 110.5 # opponent_def_rating
features[14] = 101.2 # opponent_pace

# Features 15-17: From upcoming_player_context (phase3)
features[15] = 0.0  # home_away (away)
features[16] = 0.0  # back_to_back (no)
features[17] = 0.0  # playoff_game (no)

# Features 18-20: From player_shot_zone_analysis (phase4)
features[18] = 0.35 # pct_paint (35%)
features[19] = 0.20 # pct_mid_range (20%)
features[20] = 0.45 # pct_three (45%)

# Feature 21: Calculated
features[21] = 0.286 # pct_free_throw (72/252)

# Features 22-23: From player_daily_cache (phase4)
features[22] = 99.8  # team_pace
features[23] = 115.2 # team_off_rating

# Feature 24: Calculated
features[24] = 0.700 # team_win_pct (35/50)
```

**Quality Score:**
```python
Source distribution:
- phase4: 16 features (0-8, 13-14, 18-20, 22-23) = 16 × 100 = 1600
- phase3: 3 features (15-17) = 3 × 75 = 225
- calculated: 6 features (9-12, 21, 24) = 6 × 100 = 600

Total weight: 1600 + 225 + 600 = 2425
Quality score: 2425 / 25 = 97.0 (Excellent)
```

**Output:**
```json
{
  "player_lookup": "lebron-james",
  "game_date": "2025-01-15",
  "features": [25.2, 24.8, 24.5, 4.23, 3.0, 75.0, 3.5, 1.5, 0.8,
               0.0, 0.0, -2.0, 1.0, 110.5, 101.2, 0.0, 0.0, 0.0,
               0.35, 0.20, 0.45, 0.286, 99.8, 115.2, 0.700],
  "feature_names": ["points_avg_last_5", "points_avg_last_10", ...],
  "feature_count": 25,
  "feature_version": "v1_baseline_25",
  "feature_generation_time_ms": 52,
  "feature_quality_score": 97.0,
  "data_source": "phase4",
  "early_season_flag": false
}
```

---

### Example 2: Early Season - Placeholder Row

**Detection:**
```sql
-- Check player_daily_cache for early_season_flag
SELECT
  SUM(CASE WHEN early_season_flag = TRUE THEN 1 ELSE 0 END) / COUNT(*) as pct
FROM nba_precompute.player_daily_cache
WHERE cache_date = '2024-10-25';

-- Result: 62% (>50% threshold)
```

**Output:**
```json
{
  "player_lookup": "rookie-player",
  "game_date": "2024-10-25",
  "features": [null, null, null, null, null, null, null, null, null,
               null, null, null, null, null, null, null, null, null,
               null, null, null, null, null, null, null],
  "feature_names": ["points_avg_last_5", "points_avg_last_10", ...],
  "feature_count": 25,
  "feature_version": "v1_baseline_25",
  "feature_generation_time_ms": null,
  "feature_quality_score": 0.0,
  "data_source": "early_season",
  "early_season_flag": true,
  "insufficient_data_reason": "Early season: 280/450 players lack historical data"
}
```

**Downstream Usage:** Phase 5 systems filter: `WHERE early_season_flag IS NULL OR early_season_flag = FALSE`

---

## ⚠️ Known Issues & Edge Cases

### Issue 1: Composite Factors Have No Phase 3 Fallback
**Problem:** Features 5-8 are Phase 4-only, don't exist in Phase 3
**Solution:** Use neutral defaults (50.0, 0.0, 0.0, 0.0) if Phase 4 incomplete
**Impact:** Quality score drops from 95-100 to 85-94 range
**Status:** By design - composite factors are Phase 4 innovation

### Issue 2: Cross-Dataset Write (nba_predictions not nba_precompute)
**Problem:** Breaks pattern of "Phase 4 → nba_precompute"
**Reason:** Phase 5 prediction systems need access to nba_predictions dataset
**Impact:** Requires special permissions for cross-dataset writes
**Status:** Intentional for Phase 5 access control

### Issue 3: Shot Zone Rates Stored as Percentages vs Decimals
**Problem:** Phase 4 stores as 35.0 (35%), ML needs 0.35 (decimal)
**Solution:** Divide by 100.0 during extraction
**Code:**
```python
features.append(phase4_data.get('paint_rate_last_10', 30.0) / 100.0)
```
**Status:** Handled automatically in processor

### Issue 4: Early Season Detection Cascades from player_daily_cache
**Problem:** Processor doesn't independently detect early season
**Design:** Trusts player_daily_cache early_season_flag (>50% threshold)
**Benefit:** Consistent early season handling across all Phase 4 processors
**Status:** By design

---

## ✅ Validation Rules

### Input Validation (Phase 4 Dependency Check)
- ✅ **All 4 Phase 4 tables present:** player_daily_cache, player_composite_factors, player_shot_zone_analysis, team_defense_zone_analysis
- ✅ **All <2 hours old:** Freshness check
- ✅ **Minimum counts:** ≥100 players, ≥20 teams
- ✅ **Critical check:** If missing → processor fails (except early season)

### Output Validation (Phase 4 Check)
- ✅ **Player count:** ~450 rows (matches game schedule)
- ✅ **Array size:** All features arrays LENGTH = 25
- ✅ **Quality distribution:**
  - Normal season: ≥85% players with quality ≥95
  - Normal season: <5% players with quality <85
- ✅ **Source tracking:** All 12 fields populated (v4.0 spec)
- ✅ **Version:** feature_version = "v1_baseline_25"

### Data Quality Tiers
```sql
-- Expected distribution (normal season)
SELECT
  CASE
    WHEN feature_quality_score >= 95 THEN '95-100 (Excellent)'
    WHEN feature_quality_score >= 85 THEN '85-94 (Good)'
    WHEN feature_quality_score >= 70 THEN '70-84 (Medium)'
    ELSE '<70 (Low)'
  END as tier,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE()
GROUP BY tier;

-- Expected:
-- 95-100: 85% (383 players)
-- 85-94:  10% (45 players)
-- 70-84:  5%  (22 players)
```

---

## 📈 Success Criteria

**Processing Success:**
- ✅ ~450 rows output (1 per player with game today)
- ✅ Processing completes within 2 minutes
- ✅ All 25 features calculated (or NULL with early_season_flag)
- ✅ Source tracking populated for 100% of rows

**Data Quality Success:**
- ✅ ≥85% players have quality_score ≥95 (normal season)
- ✅ <5% players have quality_score <70
- ✅ Average quality_score ≥90
- ✅ All feature arrays LENGTH = 25

**Timing Success:**
- ✅ All Phase 4 dependencies complete by 11:50 PM
- ✅ ML Feature Store completes by 12:02 AM (2-minute window)
- ✅ Ready for Phase 5 predictions by 12:05 AM

**Cost Success:**
- ✅ Daily BQ cost <$0.001 (less than a penny)
- ✅ Storage growth ~540 KB/day (~190 MB/year)

---

## 🔗 Related Documentation

**Processor Implementation:**
- Main: `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- Feature extractor: `data_processors/precompute/ml_feature_store/feature_extractor.py`
- Feature calculator: `data_processors/precompute/ml_feature_store/feature_calculator.py`
- Quality scorer: `data_processors/precompute/ml_feature_store/quality_scorer.py`
- Batch writer: `data_processors/precompute/ml_feature_store/batch_writer.py`

**Phase 3 Dependencies:**
- Schema: Run `bq show --schema nba_analytics.upcoming_player_game_context`
- Schema: Run `bq show --schema nba_analytics.player_game_summary`
- Schema: Run `bq show --schema nba_analytics.team_offense_game_summary`

**Phase 4 Dependencies:**
- Schema: Run `bq show --schema nba_precompute.player_daily_cache`
- Schema: Run `bq show --schema nba_precompute.player_composite_factors`
- Schema: Run `bq show --schema nba_precompute.player_shot_zone_analysis`
- Schema: Run `bq show --schema nba_precompute.team_defense_zone_analysis`
- Source mapping: `docs/data-flow/10-phase3-to-phase4-player-daily-cache.md`
- Source mapping: `docs/data-flow/11-phase3-to-phase4-player-composite-factors.md`
- Source mapping: `docs/data-flow/09-phase3-to-phase4-player-shot-zone-analysis.md`
- Source mapping: `docs/data-flow/08-phase3-to-phase4-team-defense-zone-analysis.md`

**Phase 4 Output:**
- Schema: Run `bq show --schema nba_predictions.ml_feature_store_v2` (⚠️ MISSING)
- Schema file: `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`

**Downstream Consumers:**
- Phase 5 Prediction Models - Reads feature arrays for ML inference
- Phase 5 Confidence Scoring - Uses quality_score for confidence weighting

**Monitoring:**
- `docs/monitoring/` - Data quality metrics for Phase 4

---

## 📅 Processing Schedule

**Daily Pipeline Timing:**
```
6:00 AM  - Phase 3 upcoming context tables updated
10:00 PM - Phase 3 game summaries processed
10:30 PM - Phase 3 completes
11:00 PM - Phase 4 Team Defense Zone Analysis starts
11:02 PM - Phase 4 Team Defense Zone Analysis completes
11:15 PM - Phase 4 Player Shot Zone Analysis starts
11:23 PM - Phase 4 Player Shot Zone Analysis completes
11:30 PM - Phase 4 Player Composite Factors starts
11:40 PM - Phase 4 Player Composite Factors completes
11:45 PM - Phase 4 Player Daily Cache starts
11:50 PM - Phase 4 Player Daily Cache completes
12:00 AM - Phase 4 ML Feature Store V2 starts ← THIS PROCESSOR
12:02 AM - Phase 4 ML Feature Store V2 completes
12:05 AM - Phase 5 Predictions start (depends on feature store)
```

**Data Lag:**
- Phase 4 zone analysis → ML Feature Store: ~40 minutes
- Phase 3 context → ML Feature Store: ~18 hours (acceptable for daily)
- **Total Lag:** Morning context available by 6:00 AM, features by 12:00 AM

**Retention:**
- Phase 4 output: No automatic expiration (predictions dataset)
- Manual cleanup required after predictions are generated

**Dependency Chain:**
1. Phase 3 context (6:00 AM)
2. Phase 4 zone analysis (11:00-11:25 PM)
3. Phase 4 composite factors (11:30-11:40 PM)
4. Phase 4 daily cache (11:45-11:50 PM)
5. **Phase 4 ML feature store (12:00 AM)** ← Current doc
6. Phase 5 predictions (12:05 AM)

**Critical:** ML Feature Store runs LAST in Phase 4 because it depends on all other Phase 4 processors.

---

**Document Version:** 2.0
**Status:** ⚠️ Blocked - Processor implemented, output table missing
**Next Steps:** Create `nba_predictions.ml_feature_store_v2` table, verify cross-dataset permissions
