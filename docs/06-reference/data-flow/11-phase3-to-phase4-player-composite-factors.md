# Phase 3→4 Mapping: Player Composite Factors

**File:** `docs/data-flow/11-phase3-to-phase4-player-composite-factors.md`
**Created:** 2025-10-30
**Last Updated:** 2025-11-15
**Purpose:** Data mapping from Phase 3 analytics to Phase 4 player composite factor scoring
**Audience:** Engineers implementing Phase 4 processors and debugging player adjustment factors
**Status:** ✅ Production Ready - Implementation complete, all sources available

---

## 🚧 Current Deployment Status

**Implementation:** ✅ **COMPLETE**
- Phase 3 Sources: `nba_analytics.upcoming_player_game_context`, `nba_analytics.upcoming_team_game_context` (EXIST)
- Phase 4 Dependencies: `nba_precompute.player_shot_zone_analysis`, `nba_precompute.team_defense_zone_analysis` (EXIST)
- Phase 4 Processor: `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` (1010 lines, 54 tests)
- Precompute Table: `nba_precompute.player_composite_factors` (created, 39 fields)

**Blocker:** ✅ **NONE - Ready for production**
- ✅ Phase 3 source tables exist and are populated
- ✅ Phase 4 dependency tables exist (zone analysis processors)
- ✅ Phase 4 processor is implemented
- ✅ Phase 4 output table exists
- ✅ All dependencies satisfied

**Processing Strategy:**
- **Week 1-4 Implementation:** 4 active factors, 4 deferred factors (placeholder values)
- **Nightly updates** at 11:30 PM (after zone analysis completes)
- **90-day retention** in Phase 4 (partitioned by game_date)
- **Factor evolution:** Monitor XGBoost feature importance after 3 months

**Consumers:**
- ML Feature Store V2 (Phase 4)
- Phase 5 Predictions
- Web app player matchup analysis

**See:** `docs/processors/` for Phase 4 deployment procedures

---

## 📊 Executive Summary

This Phase 4 processor transforms player and team context from Phase 3 into **composite adjustment factors** that quantify game conditions. It calculates 8 factors (4 active, 4 deferred) that measure fatigue, matchup quality, pace, and usage changes, enabling downstream prediction adjustments.

**Processor:** `player_composite_factors_processor.py`
**Output Table:** `nba_precompute.player_composite_factors`
**Processing Strategy:** MERGE_UPDATE (daily processing for players with games)
**Update Frequency:** Nightly at 11:30 PM
**Factor Count:** 8 total (4 active in Week 1-4, 4 deferred with neutral defaults)
**Granularity:** 1 row per player per game_date (~450 rows/day)

**Key Features:**
- **4 active factors** - Fatigue, shot zone mismatch, pace, usage spike (Week 1-4)
- **4 deferred factors** - Referee, look-ahead, matchup history, momentum (zeros until validated)
- **Multi-source integration** - Combines Phase 3 context + Phase 4 zone analysis
- **Score-to-adjustment conversion** - Normalized scores convert to point adjustments
- **Data quality tracking** - Completeness percentage and warning flags
- **Phased rollout strategy** - Monitor XGBoost importance before activating deferred factors

**Data Quality:** High - Depends on Phase 3 context (fresh daily) and Phase 4 zone analysis

---

## 🗂️ Phase 3 Source (Analytics)

### Source 1: Upcoming Player Game Context (PRIMARY - CRITICAL)

**Table:** `nba_analytics.upcoming_player_game_context`
**Status:** ✅ **EXISTS**
**Update Frequency:** Nightly at ~6:00 AM
**Dependency:** CRITICAL - Primary source for fatigue and usage factors
**Granularity:** One row per player per game_date

**Purpose:**
- Pre-game context for players with games today
- Recent workload and fatigue indicators
- Projected usage rates and team availability
- Rest days and schedule density

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| player_lookup | STRING | Player identifier (e.g., "lebron-james") |
| universal_player_id | STRING | Stable player ID across seasons |
| game_date | DATE | Game date (partition key) |
| game_id | STRING | Unique game identifier |
| **Fatigue Inputs** | | |
| days_rest | INT64 | Days since last game (0=B2B) |
| back_to_back | BOOLEAN | TRUE if back-to-back game |
| games_in_last_7_days | INT64 | Games played in last 7 days |
| minutes_in_last_7_days | INT64 | Total minutes in last 7 days |
| avg_minutes_per_game_last_7 | NUMERIC(5,1) | Average MPG last 7 games |
| back_to_backs_last_14_days | INT64 | Count of B2B games last 14 days |
| player_age | INT64 | Player age in years |
| **Usage Inputs** | | |
| projected_usage_rate | NUMERIC(5,2) | Expected usage% today |
| avg_usage_rate_last_7_games | NUMERIC(5,2) | Average usage% last 7 games |
| star_teammates_out | INT64 | Number of star teammates out |
| **Pace Inputs** | | |
| pace_differential | NUMERIC(5,1) | Team pace - opponent pace |
| opponent_pace_last_10 | NUMERIC(5,1) | Opponent's pace last 10 games |

**Data Quality Requirements:**
- ✅ All players with games today must have a row
- ✅ Typical volume: ~450 players per game day
- ✅ No NULL values in required fields (processor uses defaults)
- ✅ Data must be <24 hours old (freshness check)

---

### Source 2: Upcoming Team Game Context (SUPPORTING)

**Table:** `nba_analytics.upcoming_team_game_context`
**Status:** ✅ **EXISTS**
**Update Frequency:** Nightly at ~6:00 AM
**Dependency:** SUPPORTING - Used for deferred factors (Week 1-4: not active)
**Granularity:** One row per team per game_date

**Purpose:**
- Team-level context for games today
- Betting lines and referee assignments (future use)
- Look-ahead pressure factors (future use)

**Key Fields Used (Deferred):**

| Field | Type | Description | Status |
|-------|------|-------------|--------|
| referee_crew_id | STRING | Referee assignment | Week 1-4: Not used |
| betting_line | NUMERIC(4,1) | Point spread | Week 1-4: Not used |
| betting_total | NUMERIC(5,1) | Over/under total | Week 1-4: Not used |

**Week 1-4 Usage:** NOT QUERIED (deferred factors disabled)

---

## Phase 4 Dependencies (Zone Analysis)

### Source 3: Player Shot Zone Analysis (CRITICAL)

**Table:** `nba_precompute.player_shot_zone_analysis`
**Status:** ✅ **EXISTS**
**Update Frequency:** Nightly at 11:15 PM
**Dependency:** CRITICAL - Must complete before composite factors runs
**Granularity:** One row per player per analysis_date

**Purpose:**
- Player's shot distribution by court zone
- Primary zone identification (paint, midrange, 3PT)
- Zone frequency percentages

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| player_lookup | STRING | Player identifier |
| primary_zone | STRING | Main shooting zone ('paint', 'midrange', '3pt') |
| primary_zone_frequency | NUMERIC(5,2) | % of shots from primary zone |
| paint_rate_last_10 | NUMERIC(5,2) | % paint shots last 10 games |
| mid_range_rate_last_10 | NUMERIC(5,2) | % mid-range shots last 10 games |
| three_pt_rate_last_10 | NUMERIC(5,2) | % three-point shots last 10 games |

---

### Source 4: Team Defense Zone Analysis (CRITICAL)

**Table:** `nba_precompute.team_defense_zone_analysis`
**Status:** ✅ **EXISTS**
**Update Frequency:** Nightly at 11:00 PM
**Dependency:** CRITICAL - Must complete before composite factors runs
**Granularity:** One row per team per analysis_date

**Purpose:**
- Opponent team defensive performance by zone
- League-relative defensive ratings
- Identify defensive strengths/weaknesses

**Key Fields Used:**

| Field | Type | Description |
|-------|------|-------------|
| team_abbr | STRING | Team abbreviation (opponent) |
| paint_defense_vs_league | NUMERIC(6,2) | Paint defense vs league avg (points/100) |
| midrange_defense_vs_league | NUMERIC(6,2) | Mid-range defense vs league avg |
| three_point_defense_vs_league | NUMERIC(6,2) | 3PT defense vs league avg |
| defensive_rating_last_15 | NUMERIC(6,2) | Overall defensive rating |

**Note:** Positive values = weak defense (favorable for offense)

---

## 🔄 Data Flow

### Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Extract Player Context (Phase 3)                        │
│ Query: upcoming_player_game_context WHERE game_date = target    │
│ Result: ~450 rows (all players with games today)                │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Extract Zone Analysis (Phase 4)                         │
│ Query: player_shot_zone_analysis JOIN team_defense_zone_analysis│
│ Join: player.primary_zone → opponent.defense_vs_league          │
│ Result: Zone matchup data for each player                       │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: Calculate Active Factors (4 factors)                    │
│                                                                  │
│ Factor 1 - FATIGUE_SCORE (0-100):                              │
│ • Start: 100 (fresh)                                            │
│ • Penalty: -15 if B2B, -10 if 4+ games in 7 days              │
│ • Penalty: -10 if 240+ minutes in 7 days                       │
│ • Penalty: -8 if 35+ MPG, -12 if 2+ B2B in 14 days            │
│ • Penalty: -5 if age 35+, -3 if age 30-34                      │
│ • Clamp: [0, 100]                                               │
│                                                                  │
│ Factor 2 - SHOT_ZONE_MISMATCH_SCORE (-10.0 to +10.0):         │
│ • Get player primary zone (paint/midrange/3pt)                  │
│ • Get opponent defense rating in that zone                      │
│ • Weight by zone frequency (50%+ = full weight)                 │
│ • Bonus: +20% if extreme matchup (>5.0 differential)           │
│ • Clamp: [-10.0, 10.0]                                          │
│                                                                  │
│ Factor 3 - PACE_SCORE (-3.0 to +3.0):                          │
│ • Use pace_differential (team pace - opponent pace)             │
│ • Scale: pace_diff / 2.0                                        │
│ • Clamp: [-3.0, 3.0]                                            │
│                                                                  │
│ Factor 4 - USAGE_SPIKE_SCORE (-3.0 to +3.0):                   │
│ • Diff: projected_usage - avg_usage_last_7                      │
│ • Scale: diff × 0.3                                             │
│ • Boost: +30% if 2+ stars out, +15% if 1 star out              │
│ • Clamp: [-3.0, 3.0]                                            │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: Set Deferred Factors (4 factors - Week 1-4)             │
│ • referee_favorability_score = 0.0 (neutral)                    │
│ • look_ahead_pressure_score = 0.0 (neutral)                     │
│ • matchup_history_score = 0 (neutral)                           │
│ • momentum_score = 0 (neutral)                                  │
│ Status: Deferred until XGBoost feature importance >5%           │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: Convert Scores to Adjustments                           │
│ • fatigue_adjustment = (score - 100) × 0.05  [-5.0 to 0.0]     │
│ • shot_zone_adjustment = score  [-10.0 to +10.0]               │
│ • pace_adjustment = score  [-3.0 to +3.0]                       │
│ • usage_spike_adjustment = score  [-3.0 to +3.0]               │
│ • All deferred adjustments = 0.0                                │
│                                                                  │
│ • total_composite_adjustment = SUM(all adjustments)             │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 6: Data Quality & Warnings                                 │
│ • Calculate data_completeness_pct (required fields present)     │
│ • Flag warnings: EXTREME_FATIGUE (<50), EXTREME_MATCHUP (>8.0)  │
│ • Flag warnings: INCOMPLETE_DATA (<80% complete)                │
│ • Set has_warnings flag and warning_details string              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 7: Add Metadata                                            │
│ • calculation_version = "v1_4factors"                           │
│ • factors_active = "fatigue,shot_zone,pace,usage_spike"         │
│ • factors_deferred = "referee,look_ahead,matchup_history,..."   │
│ • processed_at = CURRENT_TIMESTAMP()                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📋 Field Mappings

### Complete Field-by-Field Mapping

**Core Identifiers (4 fields)**

| Phase 4 Field | Phase 3 Source | Transformation |
|---------------|----------------|----------------|
| player_lookup | player_lookup | Direct copy |
| universal_player_id | universal_player_id | Direct copy |
| game_date | game_date | Direct copy |
| game_id | game_id | Direct copy |

**Active Factor Scores (4 fields - Week 1-4)**

| Phase 4 Field | Calculation | Source Tables |
|---------------|-------------|---------------|
| fatigue_score | Complex (see Step 3) | upcoming_player_game_context |
| shot_zone_mismatch_score | Complex (see Step 3) | player_shot_zone_analysis + team_defense_zone_analysis |
| pace_score | pace_differential / 2.0 | upcoming_player_game_context |
| usage_spike_score | Complex (see Step 3) | upcoming_player_game_context |

**Deferred Factor Scores (4 fields - Week 1-4: zeros)**

| Phase 4 Field | Week 1-4 Value | Future Source | Activation Criteria |
|---------------|----------------|---------------|-------------------|
| referee_favorability_score | 0.0 | upcoming_team_game_context | XGBoost importance >5% |
| look_ahead_pressure_score | 0.0 | upcoming_player_game_context | XGBoost importance >5% |
| matchup_history_score | 0 | Historical boxscores | XGBoost importance >5% |
| momentum_score | 0 | upcoming_player_game_context | XGBoost importance >5% |

**Active Factor Adjustments (4 fields)**

| Phase 4 Field | Calculation | Range |
|---------------|-------------|-------|
| fatigue_adjustment | (fatigue_score - 100) × 0.05 | [-5.0, 0.0] |
| shot_zone_adjustment | shot_zone_mismatch_score | [-10.0, 10.0] |
| pace_adjustment | pace_score | [-3.0, 3.0] |
| usage_spike_adjustment | usage_spike_score | [-3.0, 3.0] |

**Deferred Factor Adjustments (4 fields - Week 1-4: zeros)**

| Phase 4 Field | Week 1-4 Value | Future Range |
|---------------|----------------|--------------|
| referee_adjustment | 0.0 | TBD |
| look_ahead_adjustment | 0.0 | TBD |
| matchup_history_adjustment | 0.0 | TBD |
| momentum_adjustment | 0.0 | TBD |

**Composite Total (1 field)**

| Phase 4 Field | Calculation |
|---------------|-------------|
| total_composite_adjustment | SUM(all 8 adjustments) - Week 1-4: sum of 4 active only |

**Context Fields (3 fields)**

| Phase 4 Field | Source | Description |
|---------------|--------|-------------|
| opponent_team_abbr | Extracted from game_id or context | Opponent team |
| fatigue_context | JSON object | Fatigue calculation breakdown |
| shot_zone_context | JSON object | Zone mismatch details |
| pace_context | JSON object | Pace calculation details |
| usage_context | JSON object | Usage spike details |

**Data Quality (3 fields)**

| Phase 4 Field | Calculation | Logic |
|---------------|-------------|-------|
| data_completeness_pct | (fields_present / 7) × 100 | Required fields check |
| has_warnings | Boolean | TRUE if any warnings triggered |
| warning_details | STRING | Comma-separated warning codes |

**Version Metadata (3 fields)**

| Phase 4 Field | Week 1-4 Value | Description |
|---------------|----------------|-------------|
| calculation_version | "v1_4factors" | Version identifier |
| factors_active | "fatigue,shot_zone,pace,usage_spike" | Active factors list |
| factors_deferred | "referee,look_ahead,matchup_history,momentum" | Deferred factors list |

**Processing Metadata (2 fields)**

| Phase 4 Field | Value | Description |
|---------------|-------|-------------|
| processed_at | CURRENT_TIMESTAMP() | When Phase 4 processor ran |
| created_at | BigQuery default | When row was created |

---

## 📐 Calculation Examples

### Example 1: LeBron James - High Fatigue Game

**Phase 3 Input:**
```json
{
  "player_lookup": "lebron-james",
  "game_date": "2025-01-15",
  "days_rest": 0,
  "back_to_back": true,
  "games_in_last_7_days": 4,
  "minutes_in_last_7_days": 245.5,
  "avg_minutes_per_game_last_7": 35.1,
  "back_to_backs_last_14_days": 2,
  "player_age": 40,
  "projected_usage_rate": 28.5,
  "avg_usage_rate_last_7_games": 24.2,
  "star_teammates_out": 1,
  "pace_differential": 5.2
}
```

**Phase 4 Calculations:**

**Factor 1 - Fatigue Score:**
```python
fatigue_score = 100

# Days rest penalty
if days_rest == 0:  # Back-to-back
    fatigue_score -= 15  # = 85

# Recent games penalty
if games_in_last_7_days >= 4:  # 4 games
    fatigue_score -= 10  # = 75

# Minutes load penalty
if minutes_in_last_7_days > 240:  # 245.5 minutes
    fatigue_score -= 10  # = 65

# Heavy minutes per game
if avg_minutes_per_game_last_7 > 35:  # 35.1 MPG
    fatigue_score -= 8  # = 57

# Multiple back-to-backs
if back_to_backs_last_14_days >= 2:  # 2 B2Bs
    fatigue_score -= 12  # = 45

# Age penalty
if player_age >= 35:  # 40 years old
    fatigue_score -= 5  # = 40

# Final: 40 (exhausted)
fatigue_adjustment = (40 - 100) × 0.05 = -3.0 points
```

**Factor 2 - Shot Zone Mismatch:**
```python
# Assume LeBron's primary zone is 'paint' at 65.2% frequency
# Opponent (GSW) paint defense: +4.3 (weak)
shot_zone_mismatch_score = 4.3

# Weight by zone frequency
zone_weight = min(65.2 / 50.0, 1.0) = 1.0 (full weight)
shot_zone_mismatch_score = 4.3 × 1.0 = 4.3

# No extreme bonus (4.3 < 5.0)
# Final: 4.3 (favorable matchup)
shot_zone_adjustment = 4.3 points
```

**Factor 3 - Pace Score:**
```python
pace_score = pace_differential / 2.0
pace_score = 5.2 / 2.0 = 2.6

# Final: 2.6 (faster game)
pace_adjustment = 2.6 points
```

**Factor 4 - Usage Spike:**
```python
usage_diff = 28.5 - 24.2 = 4.3
usage_spike_score = 4.3 × 0.3 = 1.29

# Boost (1 star out)
if star_teammates_out == 1:
    usage_spike_score = 1.29 × 1.15 = 1.48

# Final: 1.5 (rounded)
usage_spike_adjustment = 1.5 points
```

**Deferred Factors (Week 1-4):**
```python
referee_adjustment = 0.0
look_ahead_adjustment = 0.0
matchup_history_adjustment = 0.0
momentum_adjustment = 0.0
```

**Total Composite:**
```python
total_composite_adjustment = -3.0 + 4.3 + 2.6 + 1.5 + 0 + 0 + 0 + 0
                           = +5.4 points
```

**Phase 4 Output:**
```json
{
  "player_lookup": "lebron-james",
  "game_date": "2025-01-15",
  "fatigue_score": 40,
  "shot_zone_mismatch_score": 4.3,
  "pace_score": 2.6,
  "usage_spike_score": 1.5,
  "referee_favorability_score": 0.0,
  "look_ahead_pressure_score": 0.0,
  "matchup_history_score": 0,
  "momentum_score": 0,
  "fatigue_adjustment": -3.0,
  "shot_zone_adjustment": 4.3,
  "pace_adjustment": 2.6,
  "usage_spike_adjustment": 1.5,
  "referee_adjustment": 0.0,
  "look_ahead_adjustment": 0.0,
  "matchup_history_adjustment": 0.0,
  "momentum_adjustment": 0.0,
  "total_composite_adjustment": 5.4,
  "data_completeness_pct": 100.0,
  "has_warnings": true,
  "warning_details": "EXTREME_FATIGUE",
  "calculation_version": "v1_4factors",
  "factors_active": "fatigue,shot_zone,pace,usage_spike",
  "factors_deferred": "referee,look_ahead,matchup_history,momentum"
}
```

**Interpretation:**
- **Extreme fatigue** (score 40) = -3.0 point penalty
- **Very favorable paint matchup** vs weak GSW paint defense = +4.3 points
- **Fast-paced game** expected = +2.6 points
- **Usage spike** (AD out) = +1.5 points
- **Net adjustment:** +5.4 points (favorable game conditions offset fatigue)

---

### Example 2: Fresh Player - Normal Rest

**Phase 3 Input:**
```json
{
  "player_lookup": "stephen-curry",
  "game_date": "2025-01-15",
  "days_rest": 2,
  "back_to_back": false,
  "games_in_last_7_days": 3,
  "minutes_in_last_7_days": 180.5,
  "avg_minutes_per_game_last_7": 30.1,
  "back_to_backs_last_14_days": 0,
  "player_age": 36,
  "projected_usage_rate": 30.2,
  "avg_usage_rate_last_7_games": 30.5,
  "star_teammates_out": 0,
  "pace_differential": -2.0
}
```

**Phase 4 Calculations:**

**Factor 1 - Fatigue Score:**
```python
fatigue_score = 100

# No B2B penalty
# No games penalty (3 < 4)
# No minutes penalty (180.5 < 200)
# No heavy MPG penalty (30.1 < 35)
# No multiple B2B penalty (0)
# Age penalty (36 >= 35)
fatigue_score -= 5  # = 95

# Final: 95 (well rested)
fatigue_adjustment = (95 - 100) × 0.05 = -0.25 points
```

**Factor 2 - Shot Zone Mismatch:**
```python
# Assume Curry's primary zone is '3pt' at 75% frequency
# Opponent 3PT defense: -1.5 (strong defense, unfavorable)
shot_zone_mismatch_score = -1.5

# Weight by zone frequency
zone_weight = min(75.0 / 50.0, 1.0) = 1.0
shot_zone_mismatch_score = -1.5 × 1.0 = -1.5

# Final: -1.5 (unfavorable matchup)
shot_zone_adjustment = -1.5 points
```

**Factor 3 - Pace Score:**
```python
pace_score = -2.0 / 2.0 = -1.0

# Final: -1.0 (slower game)
pace_adjustment = -1.0 points
```

**Factor 4 - Usage Spike:**
```python
usage_diff = 30.2 - 30.5 = -0.3
usage_spike_score = -0.3 × 0.3 = -0.09

# No boost (no stars out)
# Final: -0.1 (rounded, slight usage drop)
usage_spike_adjustment = -0.1 points
```

**Total Composite:**
```python
total_composite_adjustment = -0.25 + (-1.5) + (-1.0) + (-0.1)
                           = -2.85 points
```

**Interpretation:**
- Minimal fatigue penalty (well rested)
- Tough 3PT defense matchup = -1.5 points
- Slower game = fewer possessions = -1.0 points
- Stable usage = -0.1 points
- **Net adjustment:** -2.85 points (challenging conditions)

---

## ⚠️ Known Issues & Edge Cases

### Issue 1: Missing Zone Analysis Data (Early Season)
**Problem:** Player or team doesn't have zone analysis data (early season, new player)
**Solution:**
- Processor sets `shot_zone_mismatch_score = 0.0` (neutral)
- Adds note to `warning_details`: "MISSING_ZONE_DATA"
- `data_completeness_pct` reduced accordingly
**Impact:** Composite adjustment less accurate (missing one factor)

### Issue 2: Extreme Fatigue Edge Cases
**Problem:** Player with fatigue_score <20 (extremely exhausted)
**Solution:**
- Processor allows calculation to proceed (no hard block)
- Sets `has_warnings = TRUE`
- Adds "EXTREME_FATIGUE" to `warning_details`
- Downstream consumers can filter or reduce confidence
**Impact:** Flags unusual cases for human review

### Issue 3: Deferred Factors Always Zero (Week 1-4)
**Problem:** 4 factors contribute nothing to composite adjustment
**Solution:**
- **By design** - Monitor XGBoost feature importance for 3 months
- If importance >5%, implement that factor
- If importance <5%, keep deferred (noise reduction)
**Impact:** Week 1-4 composite may be less predictive (acceptable tradeoff)

### Issue 4: Zone Analysis Timing Dependencies
**Problem:** Composite factors must run AFTER zone analysis processors
**Solution:**
- Strict scheduling: Zone analysis at 11:00-11:15 PM, composite at 11:30 PM
- Processor checks zone analysis freshness (<2 hours)
- Fails if dependencies not met (safe failure mode)
**Impact:** Requires reliable Phase 4 orchestration

---

## ✅ Validation Rules

### Input Validation (Phase 3 + Phase 4 Dependencies)
- ✅ **Players with games:** upcoming_player_game_context has all expected players
- ✅ **Zone analysis fresh:** player_shot_zone_analysis updated <2 hours ago
- ✅ **Team defense fresh:** team_defense_zone_analysis updated <2 hours ago
- ✅ **Reasonable ranges:** fatigue inputs within expected ranges (e.g., days_rest 0-7)

### Output Validation (Phase 4 Check)
- ✅ **Player count:** ~450 rows (matches games schedule)
- ✅ **Score ranges:**
  - fatigue_score: [0, 100]
  - shot_zone_mismatch_score: [-10.0, 10.0]
  - pace_score: [-3.0, 3.0]
  - usage_spike_score: [-3.0, 3.0]
- ✅ **Adjustment ranges:**
  - fatigue_adjustment: [-5.0, 0.0]
  - total_composite_adjustment: [-18.5, 13.0] (sum of all possible)
- ✅ **Deferred factors:** All = 0.0 (Week 1-4)
- ✅ **Version metadata:** calculation_version = "v1_4factors"

### Data Quality Checks
```sql
-- Validate output
SELECT
  COUNT(*) as total_rows,
  AVG(data_completeness_pct) as avg_completeness,
  SUM(CASE WHEN has_warnings THEN 1 ELSE 0 END) as warnings_count,
  AVG(total_composite_adjustment) as avg_adjustment
FROM `nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE();

-- Expected:
-- total_rows: ~450
-- avg_completeness: >90
-- warnings_count: <50 (normal season)
-- avg_adjustment: ~0 (centered around neutral)
```

---

## 📈 Success Criteria

**Processing Success:**
- ✅ ~450 rows output (1 per player with game today)
- ✅ Processing completes within 10 minutes
- ✅ All 4 active factors calculated (or defaulted with warning)
- ✅ All 4 deferred factors = 0.0

**Data Quality Success:**
- ✅ ≥90% players have data_completeness_pct ≥80
- ✅ <10% players have warnings flagged
- ✅ Average total_composite_adjustment near 0 (±2.0)
- ✅ No NULL values in required fields

**Timing Success:**
- ✅ Zone analysis completes by 11:25 PM
- ✅ Composite factors completes by 11:40 PM (10-minute window)
- ✅ Ready for ML Feature Store by 12:00 AM

**Future Evolution:**
- ✅ After 3 months: Review XGBoost feature importance
- ✅ Activate deferred factors if importance >5%
- ✅ Version bump to "v2_8factors" when factors added

---

## 🔗 Related Documentation

**Processor Implementation:**
- Code: `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`

**Phase 3 Dependencies:**
- Schema: Run `bq show --schema nba_analytics.upcoming_player_game_context`
- Schema: Run `bq show --schema nba_analytics.upcoming_team_game_context`
- Source mapping: `docs/data-flow/05-phase2-to-phase3-upcoming-player-game-context.md`

**Phase 4 Dependencies:**
- Schema: Run `bq show --schema nba_precompute.player_shot_zone_analysis`
- Schema: Run `bq show --schema nba_precompute.team_defense_zone_analysis`
- Source mapping: `docs/data-flow/09-phase3-to-phase4-player-shot-zone-analysis.md`
- Source mapping: `docs/data-flow/08-phase3-to-phase4-team-defense-zone-analysis.md`

**Phase 4 Output:**
- Schema: Run `bq show --schema nba_precompute.player_composite_factors`

**Downstream Consumers:**
- ML Feature Store V2 (Phase 4) - Reads composite factors as Features 5-8
- Phase 5 Predictions - Uses total_composite_adjustment for point adjustments

**Monitoring:**
- `docs/monitoring/` - Data quality metrics for Phase 4

---

## 📅 Processing Schedule

**Daily Pipeline Timing:**
```
6:00 AM  - Phase 3 upcoming context tables updated
10:00 PM - Phase 3 game summaries processed
11:00 PM - Phase 4 Team Defense Zone Analysis starts
11:02 PM - Phase 4 Team Defense Zone Analysis completes
11:15 PM - Phase 4 Player Shot Zone Analysis starts
11:23 PM - Phase 4 Player Shot Zone Analysis completes
11:30 PM - Phase 4 Player Composite Factors starts ← THIS PROCESSOR
11:40 PM - Phase 4 Player Composite Factors completes
12:00 AM - Phase 4 ML Feature Store starts (depends on composite factors)
```

**Data Lag:**
- Morning context → Composite factors: ~17.5 hours (acceptable for daily predictions)
- Zone analysis → Composite factors: ~15 minutes
- **Total Lag:** Morning context available by 6:00 AM, composite factors by 11:40 PM

**Retention:**
- Phase 4 table: 90 days (partitioned by game_date)
- Automatic expiration via partition expiration

**Dependency Chain:**
1. Phase 3 context (6:00 AM)
2. Phase 4 zone analysis (11:00-11:25 PM)
3. **Phase 4 composite factors (11:30 PM)** ← Current doc
4. Phase 4 ML feature store (12:00 AM)

---

**Document Version:** 1.0
**Status:** ✅ Production Ready - All sources available, ready for deployment
**Next Steps:** Continue documenting remaining Phase 3→4 mappings
