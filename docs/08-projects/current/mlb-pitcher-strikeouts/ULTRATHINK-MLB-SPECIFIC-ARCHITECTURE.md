# ULTRATHINK: MLB-Specific Architecture Requirements

**Date**: 2026-01-07
**Focus**: What makes MLB fundamentally different from NBA for predictions

---

## THE FUNDAMENTAL DIFFERENCE

### NBA: Team Sport, Probabilistic Matchups
- Player points depend on defensive matchups that are UNKNOWN before the game
- Who guards LeBron? Depends on coach decisions, rotations, foul trouble
- Prediction is probabilistic: "LeBron averages 27 against strong defenses"

### MLB: Sequential Matchups, DETERMINISTIC Lineup
- Pitcher faces KNOWN batters in KNOWN order
- The lineup is announced 1-2 hours before the game
- Prediction can be CALCULATED: "Pitcher faces 9 batters, sum their K rates"

**Key Insight**: The bottom-up model is MORE deterministic for MLB than any equivalent in NBA.

---

## MLB-SPECIFIC DATA WE SHOULD STORE

### 1. LINEUP-LEVEL ANALYSIS (Not in NBA)

NBA doesn't know who will guard whom. MLB KNOWS the exact batting order.

**New Table: `lineup_k_analysis`**

```sql
CREATE TABLE mlb_precompute.lineup_k_analysis (
  -- Identifiers
  game_id STRING,
  game_date DATE,
  pitcher_lookup STRING,
  opponent_team_abbr STRING,

  -- Lineup Summary Stats
  lineup_avg_k_rate FLOAT64,           -- Average K rate of all 9 batters
  lineup_k_rate_vs_hand FLOAT64,       -- K rate vs this pitcher's handedness
  lineup_chase_rate FLOAT64,           -- How often they swing at balls
  lineup_whiff_rate FLOAT64,           -- Swing and miss rate
  lineup_contact_rate FLOAT64,         -- Contact rate when swinging

  -- The Bottom-Up Calculation (THE KEY FEATURE)
  bottom_up_expected_k FLOAT64,        -- Sum of individual batter K probs
  bottom_up_k_std FLOAT64,             -- Standard deviation
  bottom_up_k_floor FLOAT64,           -- 10th percentile
  bottom_up_k_ceiling FLOAT64,         -- 90th percentile

  -- Individual Batter Breakdown (denormalized for speed)
  lineup_batters ARRAY<STRUCT<
    batting_order INT64,
    batter_lookup STRING,
    handedness STRING,
    season_k_rate FLOAT64,
    k_rate_last_10 FLOAT64,
    k_rate_vs_pitcher_hand FLOAT64,
    expected_pa FLOAT64,
    expected_k FLOAT64,
    historical_vs_pitcher_k_rate FLOAT64,
    historical_vs_pitcher_ab INT64
  >>,

  -- Lineup Quality Assessment
  lineup_quality_tier STRING,          -- ELITE_K_RESISTANT, AVERAGE, HIGH_K_PRONE
  weak_spot_positions ARRAY<INT64>,    -- Batting order positions with high K rates

  -- Data Quality
  batters_with_k_data INT64,           -- How many of 9 have K rate data
  data_completeness_pct FLOAT64,

  created_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY pitcher_lookup, opponent_team_abbr;
```

**Why this matters**: This table stores the CALCULATED bottom-up expectation plus individual batter details. The feature processor can then compare `bottom_up_expected_k` vs `pitcher_avg_k` vs `k_line` to find edges.

---

### 2. PITCHER ARSENAL ANALYSIS (Unique to Pitching)

NBA players don't have "pitch arsenals" - they just shoot. Pitchers have distinct weapons.

**New Table: `pitcher_arsenal_summary`**

```sql
CREATE TABLE mlb_precompute.pitcher_arsenal_summary (
  -- Identifiers
  pitcher_lookup STRING,
  analysis_date DATE,
  season_year INT64,

  -- Pitch Mix (what pitches they throw)
  fastball_pct FLOAT64,
  slider_pct FLOAT64,
  curveball_pct FLOAT64,
  changeup_pct FLOAT64,
  cutter_pct FLOAT64,
  sinker_pct FLOAT64,

  -- Velocity Metrics
  avg_fastball_velocity FLOAT64,
  max_fastball_velocity FLOAT64,
  velocity_last_3_starts FLOAT64,
  velocity_trend FLOAT64,              -- Positive = gaining velo, negative = declining

  -- Strikeout Ability (THE KEY METRICS)
  overall_whiff_rate FLOAT64,          -- Swings and misses / total swings
  chase_rate FLOAT64,                  -- Swings at balls / balls thrown
  called_strike_rate FLOAT64,          -- Called strikes / pitches taken
  put_away_rate FLOAT64,               -- K rate with 2 strikes
  first_pitch_strike_rate FLOAT64,

  -- By Pitch Type Effectiveness
  fastball_whiff_rate FLOAT64,
  breaking_whiff_rate FLOAT64,
  offspeed_whiff_rate FLOAT64,
  best_strikeout_pitch STRING,         -- Which pitch gets most Ks

  -- Count Leverage
  k_rate_ahead_in_count FLOAT64,       -- When 0-1, 0-2, 1-2
  k_rate_behind_in_count FLOAT64,      -- When 1-0, 2-0, 3-1
  k_rate_even_count FLOAT64,           -- When 0-0, 1-1, 2-2

  -- Source: Statcast
  data_source STRING,
  games_analyzed INT64,
  created_at TIMESTAMP
)
PARTITION BY analysis_date
CLUSTER BY pitcher_lookup;
```

**Why this matters**: A pitcher with high whiff_rate and put_away_rate will get more Ks than raw K/9 suggests. This is predictive of FUTURE Ks.

---

### 3. BATTER K VULNERABILITY PROFILE (More Granular than NBA)

In NBA, we track shot zones. In MLB, we track K vulnerability.

**New Table: `batter_k_profile`**

```sql
CREATE TABLE mlb_precompute.batter_k_profile (
  -- Identifiers
  batter_lookup STRING,
  analysis_date DATE,
  season_year INT64,

  -- Overall K Tendencies
  season_k_rate FLOAT64,
  k_rate_last_10 FLOAT64,
  k_rate_last_30 FLOAT64,

  -- Platoon Splits (CRITICAL for MLB)
  k_rate_vs_rhp FLOAT64,
  k_rate_vs_lhp FLOAT64,
  platoon_k_advantage FLOAT64,         -- vs_rhp - vs_lhp (positive = easier to K vs RHP)

  -- Approach Metrics
  swing_rate FLOAT64,                  -- How often they swing
  contact_rate FLOAT64,                -- Contact when swinging
  whiff_rate FLOAT64,                  -- Miss when swinging
  chase_rate FLOAT64,                  -- Swing at balls

  -- Situational K Rates
  k_rate_first_ab FLOAT64,             -- 1st plate appearance in game
  k_rate_second_ab FLOAT64,            -- 2nd time through order
  k_rate_third_ab FLOAT64,             -- 3rd time through (often bullpen)
  k_rate_with_2_strikes FLOAT64,       -- Put-away vulnerability
  k_rate_with_risp FLOAT64,            -- Runners in scoring position

  -- Pitch Type Vulnerability
  k_rate_vs_fastball FLOAT64,
  k_rate_vs_breaking FLOAT64,
  k_rate_vs_offspeed FLOAT64,
  weak_spot_pitch STRING,              -- Which pitch type Ks them most

  -- Data Quality
  plate_appearances INT64,
  data_quality_tier STRING,
  created_at TIMESTAMP
)
PARTITION BY analysis_date
CLUSTER BY batter_lookup;
```

**Why this matters**: When building bottom-up model, we need per-batter K vulnerability. A batter with 35% K rate vs LHP is very different from 20% K rate vs RHP.

---

### 4. UMPIRE STRIKE ZONE (Unique to MLB)

NBA has refs, but they don't directly affect scoring. MLB umpires directly affect K rates.

**New Table: `umpire_game_assignment`**

```sql
CREATE TABLE mlb_raw.umpire_game_assignment (
  -- Identifiers
  game_id STRING,
  game_date DATE,
  umpire_name STRING,
  umpire_id STRING,

  -- Zone Tendencies
  career_k_adjustment FLOAT64,         -- +/- Ks per game from average
  zone_size STRING,                    -- TIGHT, NORMAL, LOOSE
  called_strike_rate FLOAT64,          -- % of taken pitches called strikes
  pitcher_favor_pct FLOAT64,           -- How often borderline goes to pitcher

  -- Recent Form
  k_adjustment_last_10 FLOAT64,
  consistency_score FLOAT64,           -- How predictable is their zone

  -- By Count
  k_adjustment_0_2_count FLOAT64,      -- Do they expand zone with 2 strikes?
  k_adjustment_3_0_count FLOAT64,      -- Do they shrink zone when behind?

  created_at TIMESTAMP
)
PARTITION BY game_date;
```

**Why this matters**: An umpire with a +0.5 K adjustment means pitcher gets ~0.5 extra Ks per game on average. This is a meaningful feature.

---

### 5. INNINGS PROJECTION (Unique to Starting Pitchers)

In NBA, players play ~32 minutes on average. In MLB, starting pitchers' innings are HIGHLY variable (4-8 IP).

**New Table: `pitcher_innings_projection`**

```sql
CREATE TABLE mlb_precompute.pitcher_innings_projection (
  -- Identifiers
  game_id STRING,
  game_date DATE,
  pitcher_lookup STRING,

  -- Base Projections
  projected_innings FLOAT64,           -- Expected IP
  projected_batters_faced INT64,       -- Expected TBF
  projected_pitches INT64,             -- Expected pitch count

  -- Factors Affecting IP
  recent_avg_ip FLOAT64,               -- Average IP last 5 starts
  season_avg_ip FLOAT64,               -- Season average IP
  pitch_count_avg FLOAT64,             -- Avg pitches per start
  team_bullpen_quality FLOAT64,        -- Strong bullpen = shorter starts
  game_importance FLOAT64,             -- Playoff race = might go longer
  days_rest INT64,                     -- More rest = might go longer

  -- Risk Factors
  blowout_risk FLOAT64,                -- If down early, might get pulled
  injury_risk_score FLOAT64,           -- Recent arm fatigue indicators

  -- Derived K Expectations
  expected_k_opportunities FLOAT64,    -- Projected TBF × avg K rate
  innings_adjusted_k_floor FLOAT64,    -- Low IP scenario
  innings_adjusted_k_ceiling FLOAT64,  -- High IP scenario

  created_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY pitcher_lookup;
```

**Why this matters**: A pitcher with 10 K/9 but projected for only 5 IP has different expected Ks than same pitcher projected for 7 IP. Vegas lines factor this in.

---

### 6. PITCHER-BATTER HISTORICAL MATCHUPS (Unique Level of Granularity)

NBA doesn't track player-vs-player at this level. MLB has EXACT matchup history.

**New Table: `pitcher_batter_history`**

```sql
CREATE TABLE mlb_analytics.pitcher_batter_history (
  -- Identifiers
  pitcher_lookup STRING,
  batter_lookup STRING,
  as_of_date DATE,

  -- Career Matchup Stats
  career_ab INT64,
  career_k INT64,
  career_k_rate FLOAT64,
  career_hits INT64,
  career_hr INT64,
  career_bb INT64,

  -- Recent Matchup (if available)
  ab_last_season INT64,
  k_last_season INT64,
  k_rate_last_season FLOAT64,

  -- Matchup Quality
  sample_size_tier STRING,             -- SMALL (<10 AB), MEDIUM (10-30), LARGE (30+)
  matchup_confidence FLOAT64,          -- How reliable is this data

  created_at TIMESTAMP
)
PARTITION BY as_of_date
CLUSTER BY pitcher_lookup, batter_lookup;
```

**Why this matters**: If a pitcher has 15 Ks in 30 career AB against a specific batter, that's a 50% K rate - way above league average. This specific matchup data is predictive.

---

## NEW FEATURES TO ADD (Beyond Current 25)

### Current Features (f00-f24): GOOD, keep them

### Proposed New Features (f25-f34):

| Feature | Name | Source | Range | Why It Matters |
|---------|------|--------|-------|----------------|
| f25 | bottom_up_k_expected | lineup_k_analysis | 0-15 | THE KEY FEATURE - sum of individual K probs |
| f26 | lineup_k_vs_hand | lineup_k_analysis | 0-0.5 | Lineup K rate vs pitcher's handedness |
| f27 | platoon_advantage | batter_k_profile | -0.1 to 0.1 | LHP vs mostly RHH lineup = advantage |
| f28 | umpire_k_factor | umpire_assignment | -1 to +1 | Umpire's K adjustment |
| f29 | projected_innings | innings_projection | 4-8 | Expected IP (affects K opportunities) |
| f30 | velocity_trend | arsenal_summary | -3 to +3 | Velo change vs season average |
| f31 | whiff_rate | arsenal_summary | 0.15-0.35 | Overall swing-and-miss ability |
| f32 | put_away_rate | arsenal_summary | 0.2-0.5 | K rate with 2 strikes |
| f33 | lineup_weak_spots | lineup_k_analysis | 0-9 | Number of high-K-rate batters |
| f34 | matchup_edge | history aggregated | -3 to +3 | Historical advantage vs this lineup |

### Updated Feature Vector: 35 Features

This gives us 10 MORE predictive features than current 25, specifically designed for MLB strikeout prediction.

---

## GRADING DIFFERENCES FROM NBA

### NBA Grading:
- Predicted points vs actual points
- Within 3/5 points accuracy
- Over/under recommendation hit rate

### MLB Grading - MUST ACCOUNT FOR IP:

**Key Issue**: If we predict 7 Ks but pitcher only goes 4 IP (pulled early), actual is 4 Ks. Is prediction wrong?

**Solution: Dual Grading System**

1. **Absolute Grading** (for betting):
   - Predicted K vs Actual K
   - Over/under hit rate
   - This is what matters for betting

2. **Rate-Adjusted Grading** (for model improvement):
   - Predicted K/9 vs Actual K/9
   - Removes IP variance from evaluation
   - Better for understanding true model quality

**New Grading Table Fields**:

```sql
-- Standard grading (same as NBA)
absolute_error FLOAT64,
prediction_correct BOOLEAN,
within_1_k BOOLEAN,
within_2_k BOOLEAN,

-- MLB-specific rate adjustments
actual_innings FLOAT64,
actual_k_per_9 FLOAT64,
predicted_k_per_9 FLOAT64,
rate_adjusted_error FLOAT64,
was_short_outing BOOLEAN,             -- <5 IP indicates early pull
short_outing_reason STRING,           -- INJURY, PERFORMANCE, BLOWOUT, PITCH_COUNT

-- Innings-adjusted expectations
expected_k_for_actual_ip FLOAT64,     -- What we'd predict given actual IP
ip_adjusted_error FLOAT64,            -- Error accounting for IP difference
```

---

## WHAT TO CHANGE IN CURRENT ARCHITECTURE

### 1. Enhance `pitcher_ml_features` Table

Add these columns:
```sql
-- New feature columns
f25_bottom_up_k_expected FLOAT64,
f26_lineup_k_vs_hand FLOAT64,
f27_platoon_advantage FLOAT64,
f28_umpire_k_factor FLOAT64,
f29_projected_innings FLOAT64,
f30_velocity_trend FLOAT64,
f31_whiff_rate FLOAT64,
f32_put_away_rate FLOAT64,
f33_lineup_weak_spots INT64,
f34_matchup_edge FLOAT64,

-- Grading support
actual_innings FLOAT64,
actual_k_per_9 FLOAT64,
```

### 2. Add Source Tracking for New Data Sources

```sql
-- New source tracking (v4.0 pattern)
source_lineup_analysis_last_updated TIMESTAMP,
source_lineup_analysis_hash STRING,
source_arsenal_last_updated TIMESTAMP,
source_arsenal_hash STRING,
source_umpire_last_updated TIMESTAMP,
```

### 3. Create New Analytics Tables

Priority order:
1. `lineup_k_analysis` - CRITICAL (bottom-up model core)
2. `pitcher_arsenal_summary` - HIGH (whiff/velocity features)
3. `batter_k_profile` - HIGH (individual K vulnerability)
4. `umpire_game_assignment` - MEDIUM (umpire factor)
5. `pitcher_innings_projection` - MEDIUM (IP adjustment)
6. `pitcher_batter_history` - LOWER (specific matchup, needs lots of data)

---

## SUMMARY: MLB vs NBA Architecture

| Aspect | NBA | MLB | Action |
|--------|-----|-----|--------|
| **Matchup Certainty** | Unknown who guards whom | KNOWN batting order | Store full lineup analysis |
| **Bottom-Up Model** | Probabilistic (opponent defense) | DETERMINISTIC (sum batter Ks) | **This is the key feature** |
| **Player Arsenal** | Just shoots | Pitch types, velocities, spin | Store pitcher arsenal data |
| **Opponent Vulnerability** | Shot zone defense | Per-batter K rates, platoon splits | Store batter K profiles |
| **Officials Impact** | Minimal on points | Direct on Ks (strike zone) | Store umpire tendencies |
| **Playing Time Variance** | ~32 min avg, predictable | 4-8 IP, highly variable | Store innings projections |
| **Historical Matchups** | Limited player-vs-player | Extensive pitcher-vs-batter | Store matchup history |
| **Grading Complexity** | Points only | Ks + IP (confounding variable) | Dual grading system |

---

## IMPLEMENTATION PRIORITY

### MUST HAVE (for v1):
1. `lineup_k_analysis` with bottom_up_k_expected
2. Enhanced features f25-f29 (bottom-up, platoon, umpire, IP, velocity)
3. Dual grading system (absolute + rate-adjusted)

### SHOULD HAVE (for v2):
4. `pitcher_arsenal_summary` with whiff rates
5. `batter_k_profile` with platoon splits
6. Features f30-f34

### NICE TO HAVE (for v3):
7. `umpire_game_assignment`
8. `pitcher_batter_history`
9. Real-time velocity tracking integration

---

## CONCLUSION

The MLB prediction system should NOT just copy NBA's architecture. The fundamental difference is:

**NBA**: "Player X averages Y points against defenses like this"
**MLB**: "Pitcher X faces batters A-I, each with K rates. Sum = expected Ks"

The **bottom-up model** is the unique advantage for MLB predictions. We should:
1. Store detailed lineup analysis with per-batter K expectations
2. Add 10 new features specifically for MLB (f25-f34)
3. Implement dual grading to account for IP variance
4. Track pitcher arsenal and batter vulnerability separately

This will give us a significant edge over models that just use pitcher averages.
