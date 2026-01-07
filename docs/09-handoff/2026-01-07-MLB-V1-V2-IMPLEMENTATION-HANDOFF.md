# MLB Pitcher Strikeouts - V1/V2 Implementation Handoff

**Date**: 2026-01-07
**Status**: Architecture analysis complete, ready to implement
**Priority**: Create MLB-specific tables and features

---

## EXECUTIVE SUMMARY

We completed comprehensive analysis comparing NBA vs MLB architecture. The key finding:

**MLB's advantage**: We KNOW the exact batting order before the game, so we can calculate expected Ks by summing individual batter K probabilities. This "bottom-up model" is THE key feature.

### What Needs Implementation

| Version | Components | Priority |
|---------|------------|----------|
| **V1** | lineup_k_analysis table, features f25-f29, dual grading | MUST HAVE |
| **V2** | pitcher_arsenal_summary, batter_k_profile, features f30-f34 | SHOULD HAVE |

---

## V1 IMPLEMENTATION (MUST HAVE)

### 1. Create `lineup_k_analysis` Table

**Location**: `mlb_precompute.lineup_k_analysis`

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_precompute.lineup_k_analysis` (
  -- Identifiers
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  pitcher_lookup STRING NOT NULL,
  opponent_team_abbr STRING NOT NULL,

  -- Lineup Summary Stats
  lineup_avg_k_rate FLOAT64,
  lineup_k_rate_vs_hand FLOAT64,
  lineup_chase_rate FLOAT64,
  lineup_whiff_rate FLOAT64,
  lineup_contact_rate FLOAT64,

  -- Bottom-Up Calculation (THE KEY)
  bottom_up_expected_k FLOAT64,
  bottom_up_k_std FLOAT64,
  bottom_up_k_floor FLOAT64,
  bottom_up_k_ceiling FLOAT64,

  -- Individual Batter Details (JSON for flexibility)
  lineup_batters JSON,

  -- Lineup Quality
  lineup_quality_tier STRING,
  weak_spot_count INT64,
  batters_with_k_data INT64,
  data_completeness_pct FLOAT64,

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY pitcher_lookup, opponent_team_abbr;
```

**Processor to create**: `data_processors/precompute/mlb/lineup_k_analysis_processor.py`

### 2. Create `umpire_game_assignment` Table

**Location**: `mlb_raw.umpire_game_assignment`

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.umpire_game_assignment` (
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  umpire_name STRING,
  umpire_id STRING,

  -- Tendencies
  career_k_adjustment FLOAT64,
  zone_size STRING,
  called_strike_rate FLOAT64,
  k_adjustment_last_10 FLOAT64,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date;
```

### 3. Create `pitcher_innings_projection` Table

**Location**: `mlb_precompute.pitcher_innings_projection`

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_precompute.pitcher_innings_projection` (
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  pitcher_lookup STRING NOT NULL,

  -- Projections
  projected_innings FLOAT64,
  projected_batters_faced INT64,
  projected_pitches INT64,

  -- Factors
  recent_avg_ip FLOAT64,
  season_avg_ip FLOAT64,
  pitch_count_avg FLOAT64,

  -- Derived
  expected_k_opportunities FLOAT64,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY pitcher_lookup;
```

### 4. Add Features f25-f29 to Feature Processor

**File**: `data_processors/precompute/mlb/pitcher_features_processor.py`

Add these features to the 25-feature vector:

```python
# New V1 Features (f25-f29)
'f25_bottom_up_k_expected': bottom_up_k,  # Already calculated!
'f26_lineup_k_vs_hand': lineup_k_vs_hand,
'f27_platoon_advantage': platoon_advantage,
'f28_umpire_k_factor': umpire_k_factor,
'f29_projected_innings': projected_innings,
```

### 5. Update ML Feature Store Schema

Add columns to `mlb_precompute.pitcher_ml_features`:

```sql
ALTER TABLE `nba-props-platform.mlb_precompute.pitcher_ml_features`
ADD COLUMN IF NOT EXISTS f25_bottom_up_k_expected FLOAT64,
ADD COLUMN IF NOT EXISTS f26_lineup_k_vs_hand FLOAT64,
ADD COLUMN IF NOT EXISTS f27_platoon_advantage FLOAT64,
ADD COLUMN IF NOT EXISTS f28_umpire_k_factor FLOAT64,
ADD COLUMN IF NOT EXISTS f29_projected_innings FLOAT64,
ADD COLUMN IF NOT EXISTS actual_innings FLOAT64,
ADD COLUMN IF NOT EXISTS actual_k_per_9 FLOAT64;
```

---

## V2 IMPLEMENTATION (SHOULD HAVE)

### 1. Create `pitcher_arsenal_summary` Table

**Location**: `mlb_precompute.pitcher_arsenal_summary`

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_precompute.pitcher_arsenal_summary` (
  pitcher_lookup STRING NOT NULL,
  analysis_date DATE NOT NULL,
  season_year INT64,

  -- Pitch Mix
  fastball_pct FLOAT64,
  slider_pct FLOAT64,
  curveball_pct FLOAT64,
  changeup_pct FLOAT64,
  cutter_pct FLOAT64,

  -- Velocity
  avg_fastball_velocity FLOAT64,
  velocity_trend FLOAT64,

  -- Strikeout Metrics
  overall_whiff_rate FLOAT64,
  chase_rate FLOAT64,
  put_away_rate FLOAT64,
  first_pitch_strike_rate FLOAT64,

  -- By Pitch Type
  fastball_whiff_rate FLOAT64,
  breaking_whiff_rate FLOAT64,
  offspeed_whiff_rate FLOAT64,
  best_strikeout_pitch STRING,

  -- Source
  data_source STRING,
  games_analyzed INT64,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY analysis_date
CLUSTER BY pitcher_lookup;
```

### 2. Create `batter_k_profile` Table

**Location**: `mlb_precompute.batter_k_profile`

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_precompute.batter_k_profile` (
  batter_lookup STRING NOT NULL,
  analysis_date DATE NOT NULL,
  season_year INT64,

  -- K Tendencies
  season_k_rate FLOAT64,
  k_rate_last_10 FLOAT64,
  k_rate_last_30 FLOAT64,

  -- Platoon Splits (CRITICAL)
  k_rate_vs_rhp FLOAT64,
  k_rate_vs_lhp FLOAT64,
  platoon_k_diff FLOAT64,

  -- Approach Metrics
  swing_rate FLOAT64,
  contact_rate FLOAT64,
  whiff_rate FLOAT64,
  chase_rate FLOAT64,

  -- Situational
  k_rate_first_ab FLOAT64,
  k_rate_second_ab FLOAT64,
  k_rate_with_2_strikes FLOAT64,

  -- Quality
  plate_appearances INT64,
  data_quality_tier STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY analysis_date
CLUSTER BY batter_lookup;
```

### 3. Add Features f30-f34

```python
# New V2 Features (f30-f34)
'f30_velocity_trend': velocity_trend,
'f31_whiff_rate': whiff_rate,
'f32_put_away_rate': put_away_rate,
'f33_lineup_weak_spots': lineup_weak_spots,
'f34_matchup_edge': matchup_edge,
```

---

## IMPLEMENTATION ORDER

### Step 1: Create BigQuery Tables
```bash
# Run these SQL statements in BigQuery console or via bq command
bq query --use_legacy_sql=false "CREATE TABLE IF NOT EXISTS..."
```

### Step 2: Create lineup_k_analysis Processor
```
File: data_processors/precompute/mlb/lineup_k_analysis_processor.py
Template: Copy from pitcher_features_processor.py
Key method: _calculate_lineup_analysis()
```

### Step 3: Update pitcher_features_processor.py
- Add queries for new data sources
- Add features f25-f34
- Update feature vector from 25 to 35 elements

### Step 4: Create V2 Processors
- pitcher_arsenal_summary_processor.py (source: Statcast data)
- batter_k_profile_processor.py (source: batter_game_summary)

### Step 5: Update Grading System
- Add actual_innings, actual_k_per_9 columns
- Implement dual grading (absolute + rate-adjusted)

---

## KEY FILES TO MODIFY

| File | Changes Needed |
|------|----------------|
| `data_processors/precompute/mlb/pitcher_features_processor.py` | Add f25-f34, update feature vector |
| `schemas/bigquery/mlb_precompute/ml_feature_store_tables.sql` | Add new columns |
| NEW: `data_processors/precompute/mlb/lineup_k_analysis_processor.py` | Create processor |
| NEW: `data_processors/precompute/mlb/pitcher_arsenal_processor.py` | Create processor |
| NEW: `data_processors/precompute/mlb/batter_k_profile_processor.py` | Create processor |

---

## EXISTING ASSETS TO LEVERAGE

### Already Have:
- `bottom_up_k_expected` calculation in pitcher_features_processor.py (line 512-543)
- Lineup data from `mlb_raw.mlb_lineup_batters`
- Batter stats from `mlb_analytics.batter_game_summary`
- Statcast scraper for arsenal data
- Ballpark factors table

### Need Data For:
- Umpire assignments (need scraper or manual entry)
- Pitcher velocity trends (from Statcast)
- Batter platoon splits (need to compute from batter_stats)

---

## COPY-PASTE FOR NEXT SESSION

```
Continue MLB pitcher strikeouts implementation.

Read these docs first:
- docs/08-projects/current/mlb-pitcher-strikeouts/ULTRATHINK-MLB-SPECIFIC-ARCHITECTURE.md
- docs/09-handoff/2026-01-07-MLB-V1-V2-IMPLEMENTATION-HANDOFF.md

CONTEXT:
- Completed architecture analysis comparing NBA vs MLB
- Key insight: MLB can use "bottom-up model" (sum of batter K rates)
- Need to implement MLB-specific tables and features

V1 IMPLEMENTATION (DO FIRST):
1. Create lineup_k_analysis table in BigQuery
2. Create lineup_k_analysis_processor.py
3. Add features f25-f29 to pitcher_features_processor.py
4. Update ML feature store schema

V2 IMPLEMENTATION (DO SECOND):
5. Create pitcher_arsenal_summary table + processor
6. Create batter_k_profile table + processor
7. Add features f30-f34

NEW TABLES TO CREATE:
- mlb_precompute.lineup_k_analysis (bottom-up K calculation)
- mlb_raw.umpire_game_assignment (umpire K factor)
- mlb_precompute.pitcher_innings_projection (IP projection)
- mlb_precompute.pitcher_arsenal_summary (whiff rates)
- mlb_precompute.batter_k_profile (platoon splits)

NEW FEATURES (10 total):
f25: bottom_up_k_expected (THE KEY FEATURE)
f26: lineup_k_vs_hand
f27: platoon_advantage
f28: umpire_k_factor
f29: projected_innings
f30: velocity_trend
f31: whiff_rate
f32: put_away_rate
f33: lineup_weak_spots
f34: matchup_edge

Start by creating the BigQuery tables, then the processors.
```

---

## DOCUMENTATION REFERENCE

| Document | Purpose |
|----------|---------|
| `PHASE-ARCHITECTURE-ANALYSIS.md` | NBA vs MLB gap analysis |
| `ULTRATHINK-MLB-SPECIFIC-ARCHITECTURE.md` | MLB-specific requirements |
| `CURRENT-STATUS.md` | Overall project status |
| `SCRAPERS-INVENTORY.md` | All 28 scrapers |
| This doc | Implementation handoff |

---

## SUCCESS CRITERIA

### V1 Complete When:
- [ ] lineup_k_analysis table exists and populates
- [ ] Features f25-f29 added to feature vector
- [ ] Feature vector is 30 elements (was 25)
- [ ] Dual grading columns added

### V2 Complete When:
- [ ] pitcher_arsenal_summary table exists
- [ ] batter_k_profile table exists
- [ ] Features f30-f34 added
- [ ] Feature vector is 35 elements
- [ ] All processors tested with sample data
