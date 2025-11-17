# Phase 5 Composite Factor Calculations

**File:** `docs/predictions/algorithms/01-composite-factor-calculations.md`
**Created:** 2025-11-16
**Purpose:** Mathematical specifications for composite factors that adjust prediction baselines
**Status:** ✅ Current

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [Player Registry Integration](#player-registry)
3. [Fatigue Score](#fatigue-score)
4. [Shot Zone Mismatch Score](#shot-zone-mismatch)
5. [Referee Favorability Score](#referee-favorability)
6. [Look-Ahead Pressure Score](#look-ahead-pressure)
7. [Pace/Environment Score](#pace-score)
8. [Usage Spike Score](#usage-spike)
9. [Combining Factors](#combining-factors)
10. [Related Documentation](#related-docs)

---

## 🎯 Executive Summary {#executive-summary}

Composite Factor Calculations transform raw game context into scored adjustments that modify the similarity baseline prediction. Each factor represents a specific influence on player performance (fatigue, matchups, schedule, etc.) and produces a numeric score indicating expected performance impact.

### Core Principle

The similarity baseline shows historical performance in similar situations. Composite factors adjust that baseline for today's unique circumstances that make this game different from the historical average.

### Example Flow

```
Similarity Baseline: 29.2 points (from 28 similar historical games)

Composite Factors:
  Fatigue Score: 75/100 (well-rested) → +0.5 points adjustment
  Shot Zone Mismatch: +6.2 (favorable) → +1.2 points adjustment
  Referee Favorability: +2.1 (high-scoring crew) → +0.3 points adjustment
  Look-Ahead Pressure: -3.5 (big game tomorrow) → -0.4 points adjustment
  ... (other factors)

Final Prediction: 29.2 × 1.016 = 29.7 points
```

---

## 🔗 Player Registry Integration {#player-registry}

### Integration Pattern

All composite factor calculation functions follow this pattern:

1. Accept human-readable `player_lookup` as input
2. Convert to `universal_player_id` using RegistryReader
3. Query Phase 3+ tables using `universal_player_id`
4. Return calculated scores

### Example Pattern

```python
from shared.utils.player_registry import RegistryReader

def calculate_factor_score(player_lookup: str, game_date: str,
                          season: str, registry: RegistryReader):
    """
    Calculate composite factor score

    Args:
        player_lookup: Human-readable player identifier (e.g., 'lebronjames')
        game_date: Game date for calculation
        season: Season string (e.g., '2024-25')
        registry: Initialized RegistryReader instance

    Returns:
        Calculated score
    """
    # Step 1: Get universal player ID
    registry.set_default_context(season=season)
    universal_player_id = registry.get_universal_id(
        player_lookup,
        required=True,
        context={'game_date': game_date}
    )

    # Step 2: Load context using universal_player_id
    query = """
    SELECT * FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
    WHERE universal_player_id = @uid
      AND game_date = @game_date
    """

    context = execute_query(query, {
        'uid': universal_player_id,
        'game_date': game_date
    })

    # Step 3: Calculate score
    score = perform_calculation(context)

    return score
```

**Note:** All functions in this document accept `player_lookup` and require a `registry` parameter.

---

## 💪 Fatigue Score (0-100 Scale) {#fatigue-score}

### Overview

The fatigue score captures cumulative physical and mental fatigue from recent workload, travel, schedule compression, and age effects.

**Scale:**

- **100** = Completely fresh (3+ days rest, light recent schedule)
- **80-99** = Well-rested (normal NBA recovery)
- **65-79** = Normal load (standard NBA scheduling)
- **50-64** = Moderate fatigue (heavy recent schedule)
- **35-49** = High fatigue (compressed schedule, extensive travel)
- **0-34** = Extreme fatigue (brutal schedule, minimal rest)

### Calculation Algorithm

```python
from shared.utils.player_registry import RegistryReader
from google.cloud import bigquery

def calculate_fatigue_score(player_lookup: str, game_date: str,
                           season: str, registry: RegistryReader):
    """
    Calculate comprehensive 0-100 fatigue score
    Higher = better (more rested)

    Args:
        player_lookup: Player identifier (e.g., 'lebronjames')
        game_date: Game date for calculation
        season: Season string (e.g., '2024-25')
        registry: RegistryReader instance

    Returns:
        int: Fatigue score 0-100
    """
    # Get universal player ID
    registry.set_default_context(season=season)
    universal_player_id = registry.get_universal_id(
        player_lookup,
        required=True,
        context={'game_date': game_date}
    )

    # Load player context using universal_player_id
    bq = bigquery.Client()
    query = """
    SELECT * FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
    WHERE universal_player_id = @uid
      AND game_date = @game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("uid", "STRING", universal_player_id),
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    )

    result = bq.query(query, job_config=job_config).to_dataframe()
    player_context = result.iloc[0]

    base_score = 100  # Start fully rested

    # ===== MULTI-WINDOW LOAD PENALTIES =====

    # Weekly load (most important recent factor)
    if player_context.games_in_last_7_days >= 5:
        base_score -= 20  # Brutal week
    elif player_context.games_in_last_7_days >= 4:
        base_score -= 12  # Heavy week
    elif player_context.games_in_last_7_days >= 3:
        base_score -= 5   # Normal week

    # Bi-weekly accumulation
    if player_context.games_in_last_14_days >= 8:
        base_score -= 15  # Sustained heavy load
    elif player_context.games_in_last_14_days >= 6:
        base_score -= 8   # Above average load

    # ===== MINUTES LOAD ANALYSIS =====

    # Weekly minutes (physical workload)
    if player_context.minutes_in_last_7_days >= 280:  # 40+ MPG
        base_score -= 15
    elif player_context.minutes_in_last_7_days >= 245:  # 35+ MPG
        base_score -= 8
    elif player_context.minutes_in_last_7_days >= 210:  # 30+ MPG
        base_score -= 3

    # Bi-weekly minutes accumulation
    if player_context.minutes_in_last_14_days >= 560:  # 40+ MPG sustained
        base_score -= 10
    elif player_context.minutes_in_last_14_days >= 490:  # 35+ MPG sustained
        base_score -= 5

    # ===== USAGE INTENSITY =====

    # High usage rate = harder minutes
    if player_context.avg_usage_rate_last_7_games >= 32:
        base_score -= 12  # Star load
    elif player_context.avg_usage_rate_last_7_games >= 28:
        base_score -= 6   # High load
    elif player_context.avg_usage_rate_last_7_games >= 24:
        base_score -= 2   # Moderate load

    # Fourth quarter minutes (high-stress)
    if player_context.fourth_quarter_minutes_last_7 >= 56:  # 8+ per game
        base_score -= 8
    elif player_context.fourth_quarter_minutes_last_7 >= 42:  # 6+ per game
        base_score -= 4

    # Clutch minutes (final 5 min of close games)
    if player_context.clutch_minutes_last_7_games >= 35:
        base_score -= 6
    elif player_context.clutch_minutes_last_7_games >= 21:
        base_score -= 3

    # ===== REST PATTERN ANALYSIS =====

    # Current rest (immediate factor)
    if player_context.days_rest >= 3:
        base_score += 5   # Extra rest bonus
    elif player_context.days_rest == 0:
        base_score -= 15  # Back-to-back penalty

    # Time since meaningful rest
    if player_context.days_since_2_plus_days_rest >= 14:
        base_score -= 18  # No real rest in 2 weeks
    elif player_context.days_since_2_plus_days_rest >= 10:
        base_score -= 10
    elif player_context.days_since_2_plus_days_rest >= 7:
        base_score -= 5

    # ===== TRAVEL FATIGUE =====

    # Miles traveled (bi-weekly)
    if player_context.miles_traveled_last_14_days >= 4000:
        base_score -= 12  # Cross-country heavy travel
    elif player_context.miles_traveled_last_14_days >= 2500:
        base_score -= 6   # Moderate travel
    elif player_context.miles_traveled_last_14_days >= 1500:
        base_score -= 2   # Light travel

    # Time zones crossed (jet lag factor)
    if player_context.time_zones_crossed_last_14_days >= 6:
        base_score -= 8
    elif player_context.time_zones_crossed_last_14_days >= 4:
        base_score -= 4
    elif player_context.time_zones_crossed_last_14_days >= 2:
        base_score -= 2

    # Road trip length (being away from home)
    if player_context.consecutive_road_games >= 4:
        base_score -= 10
    elif player_context.consecutive_road_games >= 3:
        base_score -= 5
    elif player_context.consecutive_road_games >= 2:
        base_score -= 2

    # ===== SCHEDULE COMPRESSION =====

    # Back-to-backs recently
    base_score -= (player_context.back_to_backs_last_14_days * 6)

    # ===== GAME INTENSITY =====

    # Close games (high stress)
    close_games = player_context.games_decided_by_5_minus_last_7
    base_score -= (close_games * 3)

    # Blowouts (easier games, less fatigue)
    blowouts = player_context.games_decided_by_10_plus_last_7
    base_score += (blowouts * 2)

    # ===== AGE ADJUSTMENT =====

    # Age affects fatigue accumulation
    if player_context.player_age >= 33:
        base_score *= 0.90  # 10% more fatigue sensitivity
    elif player_context.player_age >= 30:
        base_score *= 0.95  # 5% more fatigue sensitivity
    elif player_context.player_age <= 23:
        base_score *= 1.05  # 5% less fatigue sensitivity (young recovery)

    # Ensure score stays in 0-100 range
    final_score = max(0, min(100, base_score))

    return int(final_score)
```

### Fatigue Score to Performance Impact

```python
def fatigue_adjustment(fatigue_score, baseline_prediction, player_age):
    """
    Convert fatigue score to performance adjustment
    Returns: adjustment in points
    """
    if fatigue_score >= 85:
        # Very fresh: slight boost
        adjustment = baseline_prediction * 0.03  # +3%
    elif fatigue_score >= 75:
        # Well-rested: small boost
        adjustment = baseline_prediction * 0.02  # +2%
    elif fatigue_score >= 65:
        # Normal fatigue: no adjustment
        adjustment = 0
    elif fatigue_score >= 55:
        # Moderate fatigue: small penalty
        adjustment = baseline_prediction * -0.03  # -3%
    elif fatigue_score >= 45:
        # High fatigue: significant penalty
        adjustment = baseline_prediction * -0.06  # -6%
    elif fatigue_score >= 35:
        # Very high fatigue: major penalty
        adjustment = baseline_prediction * -0.09  # -9%
    else:
        # Extreme fatigue: severe penalty
        adjustment = baseline_prediction * -0.12  # -12%

    # Age amplification (veterans more affected)
    if player_age >= 30 and fatigue_score < 60:
        adjustment *= 1.3  # 30% more impact for veterans

    return adjustment
```

---

## 🎯 Shot Zone Mismatch Score (-10 to +10 Scale) {#shot-zone-mismatch}

### Overview

Compares a player's offensive shot preferences against the opponent's defensive weaknesses. Positive scores indicate favorable matchups (player attacks opponent's weak zone), negative scores indicate difficult matchups.

**Scale:**

- **+10** = Extreme favorable mismatch (elite paint scorer vs terrible paint defense)
- **+5 to +9** = Strong favorable mismatch
- **+2 to +4** = Moderate favorable mismatch
- **-1 to +1** = Neutral matchup
- **-2 to -4** = Moderate unfavorable mismatch
- **-5 to -9** = Strong unfavorable mismatch
- **-10** = Extreme unfavorable mismatch (paint specialist vs elite rim protection)

### Calculation Algorithm

```python
def calculate_shot_zone_mismatch(player_lookup: str, game_date: str,
                                season: str, registry: RegistryReader):
    """
    Calculate shot zone mismatch score

    Args:
        player_lookup: Player identifier
        game_date: Game date
        season: Season string
        registry: RegistryReader instance

    Returns:
        float: Score from -10.0 to +10.0
    """
    # Get universal player ID
    registry.set_default_context(season=season)
    universal_player_id = registry.get_universal_id(
        player_lookup,
        required=True
    )

    bq = bigquery.Client()

    # Load player shot zone data
    player_query = """
    SELECT * FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
    WHERE universal_player_id = @uid
      AND analysis_date = @game_date
    """

    player_shot_data = bq.query(player_query, job_config=bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("uid", "STRING", universal_player_id),
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    )).to_dataframe().iloc[0]

    # Load opponent defense data
    opponent_query = """
    SELECT opp.*
    FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis` opp
    JOIN `nba-props-platform.nba_analytics.upcoming_player_game_context` upg
      ON opp.team_abbr = upg.opponent_team_abbr
      AND opp.analysis_date = upg.game_date
    WHERE upg.universal_player_id = @uid
      AND upg.game_date = @game_date
    """

    opponent_defense_data = bq.query(opponent_query, job_config=bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("uid", "STRING", universal_player_id),
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    )).to_dataframe().iloc[0]

    # Get player's primary scoring zones
    paint_rate = player_shot_data.paint_rate_last_10  # % of shots in paint
    mid_range_rate = player_shot_data.mid_range_rate_last_10
    three_pt_rate = player_shot_data.three_pt_rate_last_10

    # Get player's efficiency in each zone
    paint_eff = player_shot_data.paint_pct_last_10  # FG% in paint
    mid_range_eff = player_shot_data.mid_range_pct_last_10
    three_pt_eff = player_shot_data.three_pt_pct_last_10

    # Get opponent's defensive performance by zone
    opp_paint_def = opponent_defense_data.paint_pct_allowed_last_15
    opp_mid_def = opponent_defense_data.mid_range_pct_allowed_last_15
    opp_three_def = opponent_defense_data.three_pt_pct_allowed_last_15

    # League averages for comparison
    LEAGUE_AVG_PAINT = 55.0
    LEAGUE_AVG_MID = 40.0
    LEAGUE_AVG_THREE = 36.0

    # Calculate mismatch in each zone
    # Positive = opponent allows more than league average (favorable)
    paint_mismatch = (opp_paint_def - LEAGUE_AVG_PAINT)
    mid_mismatch = (opp_mid_def - LEAGUE_AVG_MID)
    three_mismatch = (opp_three_def - LEAGUE_AVG_THREE)

    # Weight by player's usage of each zone
    weighted_mismatch = (
        paint_mismatch * (paint_rate / 100) * 1.5 +      # Paint weighted higher
        mid_mismatch * (mid_range_rate / 100) * 1.0 +
        three_mismatch * (three_pt_rate / 100) * 1.2     # Threes weighted higher
    )

    # Efficiency amplifier (elite scorers exploit mismatches more)
    if paint_rate >= 40 and paint_eff >= 60:  # Paint-dominant elite scorer
        if paint_mismatch > 3:
            weighted_mismatch *= 1.3  # Amplify favorable paint matchup

    if three_pt_rate >= 40 and three_pt_eff >= 37:  # Elite shooter
        if three_mismatch > 2:
            weighted_mismatch *= 1.2  # Amplify favorable perimeter matchup

    # Normalize to -10 to +10 scale
    score = weighted_mismatch * 1.5

    # Clamp to range
    final_score = max(-10, min(10, score))

    return round(final_score, 1)
```

### Shot Zone Mismatch to Performance Impact

```python
def shot_zone_adjustment(mismatch_score, baseline_prediction):
    """
    Convert shot zone mismatch to performance adjustment
    Returns: adjustment in points
    """
    # Mismatch score ranges from -10 to +10
    # At +10 (extreme favorable): +4% boost
    # At -10 (extreme unfavorable): -4% penalty

    percentage_adjustment = mismatch_score * 0.004  # 0.4% per point
    adjustment = baseline_prediction * percentage_adjustment

    return adjustment
```

---

## 🏀 Referee Favorability Score (-5 to +5 Scale) {#referee-favorability}

### Overview

Captures the scoring environment created by the referee crew. High-scoring crews and foul-happy refs benefit offensive players, while low-scoring and whistle-swallowing crews reduce scoring opportunities.

**Scale:**

- **+5** = Extremely favorable (high-scoring crew, lots of FT opportunities)
- **+3 to +4** = Very favorable
- **+1 to +2** = Slightly favorable
- **-1 to +1** = Neutral
- **-2 to -3** = Slightly unfavorable
- **-4 to -5** = Very unfavorable (low-scoring crew, limited FT opportunities)

### Calculation Algorithm

```python
def calculate_referee_favorability(player_lookup: str, game_date: str,
                                  season: str, registry: RegistryReader):
    """
    Calculate referee favorability score

    Args:
        player_lookup: Player identifier
        game_date: Game date
        season: Season string
        registry: RegistryReader instance

    Returns:
        float: Score from -5.0 to +5.0
    """
    # Get universal player ID
    registry.set_default_context(season=season)
    universal_player_id = registry.get_universal_id(player_lookup, required=True)

    bq = bigquery.Client()

    # Get referee data for this game
    query = """
    SELECT gr.*
    FROM `nba-props-platform.nba_analytics.game_referees` gr
    JOIN `nba-props-platform.nba_analytics.upcoming_player_game_context` upg
      ON gr.game_id = upg.game_id
    WHERE upg.universal_player_id = @uid
      AND upg.game_date = @game_date
    """

    game_referees = bq.query(query, job_config=bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("uid", "STRING", universal_player_id),
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    )).to_dataframe().iloc[0]

    # Get crew chief tendencies (most predictive)
    chief_avg_total_points = game_referees.chief_avg_total_points
    chief_avg_fouls = game_referees.chief_avg_fouls_per_game

    # League averages for comparison
    LEAGUE_AVG_TOTAL = 220.0
    LEAGUE_AVG_FOULS = 38.0

    # Calculate deviations from league average
    points_deviation = chief_avg_total_points - LEAGUE_AVG_TOTAL
    fouls_deviation = chief_avg_fouls - LEAGUE_AVG_FOULS

    # Convert to scoring environment score
    # Higher total points = more favorable for scorers
    points_component = points_deviation / 5  # Each 5 points = 1 score point

    # More fouls = more FT opportunities (favorable for FT shooters)
    fouls_component = fouls_deviation / 2  # Each 2 fouls = 1 score point

    # Combined score (60% points, 40% fouls)
    raw_score = (points_component * 0.6) + (fouls_component * 0.4)

    # Clamp to -5 to +5 range
    final_score = max(-5, min(5, raw_score))

    return round(final_score, 1)
```

### Referee Favorability to Performance Impact

```python
def referee_adjustment(favorability_score, baseline_prediction, player_ft_rate):
    """
    Convert referee favorability to performance adjustment
    Returns: adjustment in points
    """
    # Base adjustment: 0.3% per favorability point
    base_adjustment = baseline_prediction * (favorability_score * 0.003)

    # Amplify for players who draw fouls frequently
    if player_ft_rate >= 0.35:  # High FT rate (35%+ of points from FTs)
        base_adjustment *= 1.3  # 30% more impact
    elif player_ft_rate >= 0.25:
        base_adjustment *= 1.15  # 15% more impact

    return base_adjustment
```

---

## 🎲 Combining Factors into Final Adjustment {#combining-factors}

### Weighted Combination Formula

```python
from shared.utils.player_registry import RegistryReader

def calculate_final_prediction(player_lookup: str, game_date: str,
                              season: str, registry: RegistryReader,
                              system_weights: dict):
    """
    Combine all factor adjustments with system weights

    Args:
        player_lookup: Player identifier
        game_date: Game date
        season: Season string
        registry: RegistryReader instance
        system_weights: Weight configuration dict

    Returns:
        float: Final predicted points
    """
    # Get universal_player_id
    registry.set_default_context(season=season)
    universal_player_id = registry.get_universal_id(player_lookup, required=True)

    # Calculate similarity baseline
    baseline = calculate_similarity_baseline(
        universal_player_id,
        game_date,
        registry
    )

    # Calculate all factor adjustments
    factor_adjustments = {
        'fatigue': calculate_fatigue_adjustment(
            player_lookup, game_date, season, registry
        ),
        'shot_zone': calculate_shot_zone_adjustment(
            player_lookup, game_date, season, registry
        ),
        'referee': calculate_referee_adjustment(
            player_lookup, game_date, season, registry
        ),
        'look_ahead': calculate_look_ahead_adjustment(
            player_lookup, game_date, season, registry
        ),
        'pace': calculate_pace_adjustment(
            player_lookup, game_date, season, registry
        ),
        'usage_spike': calculate_usage_spike_adjustment(
            player_lookup, game_date, season, registry
        ),
        'home_away': calculate_home_away_adjustment(
            player_lookup, game_date, season, registry
        ),
        'matchup_history': calculate_matchup_history_adjustment(
            player_lookup, game_date, season, registry
        ),
        'momentum': calculate_momentum_adjustment(
            player_lookup, game_date, season, registry
        )
    }

    # Calculate weighted adjustment
    total_adjustment = sum(
        factor_adjustments[factor] * system_weights[factor]
        for factor in system_weights.keys()
    )

    # Apply adjustment to baseline
    final_prediction = baseline + total_adjustment

    return final_prediction
```

### Database Storage

**Table:** `player_composite_factors`

```sql
-- Example: Load pre-calculated factors for prediction
SELECT
    universal_player_id,
    player_lookup,  -- Still included for debugging/display
    game_date,
    fatigue_score,
    shot_zone_mismatch_score,
    referee_favorability_score,
    -- ... all other scores and adjustments
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE universal_player_id = @target_universal_player_id
  AND game_date = @target_game_date;
```

**Note:** The table schema has both `universal_player_id` and `player_lookup`. We query by `universal_player_id` (stable identifier) but include `player_lookup` in results for human readability.

---

## 🔗 Related Documentation {#related-docs}

**Phase 5 Algorithm Documentation:**

- **Confidence Scoring:** `02-confidence-scoring-framework.md` - How confidence is calculated
- **Architectural Decisions:** `../design/01-architectural-decisions.md` - Why we use these factors

**Phase 5 ML Documentation:**

- **Model Training:** `../ml-training/01-initial-model-training.md` - How ML uses these features
- **Continuous Retraining:** `../ml-training/02-continuous-retraining.md` - Feature importance tracking

**Phase 4 Dependencies:**

- **Precompute Schema:** See Phase 4 documentation for `player_composite_factors` table structure
- **Feature Store:** Documentation for `ml_feature_store_v2` integration

**Implementation:**

- **Source Code:** `predictions/shared/composite_factors/` - Implementation of all calculations
- **Player Registry:** `shared/utils/player_registry.py` - Universal ID integration

---

**Last Updated:** 2025-11-16
**Next Steps:** Review confidence scoring framework to understand how these factors influence final recommendations
**Status:** ✅ Current

---

## Quick Reference

**Factor Summary:**

| Factor | Range | Purpose |
|--------|-------|---------|
| Fatigue | 0-100 | Player rest and workload |
| Shot Zone Mismatch | -10 to +10 | Offensive vs defensive zone strengths |
| Referee Favorability | -5 to +5 | Scoring environment |
| Look-Ahead Pressure | -5 to +5 | Rest strategy for future games |
| Pace/Environment | -3 to +3 | Game tempo adjustments |
| Usage Spike | -3 to +3 | Role changes |

**All functions require:**
- `player_lookup` (str)
- `game_date` (str)
- `season` (str)
- `registry` (RegistryReader instance)
