# Schema Changes Required

**Created:** December 17, 2024
**Updated:** December 17, 2024
**Purpose:** All database schema modifications needed for frontend API backend

---

## Overview

This document contains production-ready SQL for all schema changes.

### Key Discovery (December 2024)

**Prediction result tracking already exists!** The `prediction_accuracy` table and `PredictionAccuracyProcessor`
are fully built but the job hasn't been running, leaving the table empty.

**What EXISTS (schema + code, no data):**
- `nba_predictions.prediction_accuracy` - Per-prediction grading
- `nba_predictions.system_daily_performance` - Daily aggregates by system
- `PredictionAccuracyProcessor` - Grading logic
- Phase 6 Exporters - JSON generation for website

**What's NEW (needs to be created):**
- `nba_predictions.prediction_performance_summary` - Multi-dimensional aggregates

---

## 1. Prediction Result Tracking (RUN BACKFILL - Infrastructure Exists)

### 1.1 Tables Already Exist

**NO SCHEMA CHANGES NEEDED** for basic prediction grading. The tables exist:

- `nba_predictions.prediction_accuracy` - See `schemas/bigquery/nba_predictions/prediction_accuracy.sql`
- `nba_predictions.system_daily_performance` - See `schemas/bigquery/nba_predictions/system_daily_performance.sql`

### 1.2 Run the Backfill

```bash
# Backfill prediction accuracy for the current season
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2024-10-22 \
  --end-date 2024-12-16

# Or for a single date
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --date 2024-12-16
```

### 1.3 Verify Data After Backfill

```sql
-- Check prediction_accuracy has data
SELECT
  system_id,
  COUNT(*) as predictions,
  AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as hit_rate,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM nba_predictions.prediction_accuracy
GROUP BY system_id
ORDER BY predictions DESC;

-- Check system_daily_performance
SELECT
  system_id,
  COUNT(*) as days,
  AVG(win_rate) as avg_win_rate
FROM nba_predictions.system_daily_performance
GROUP BY system_id;
```

### 1.4 Create Prediction Performance Summary Table (NEW)

This table provides multi-dimensional aggregates that `system_daily_performance` doesn't cover.

**Schema file:** `schemas/bigquery/nba_predictions/prediction_performance_summary.sql`
**Processor:** `data_processors/grading/performance_summary/performance_summary_processor.py`

```sql
-- =============================================================================
-- Table: prediction_performance_summary
-- Purpose: Pre-aggregated performance by player, archetype, confidence, situation
-- =============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.prediction_performance_summary` (
  -- Primary Key (composite)
  summary_key STRING NOT NULL,              -- Unique key for MERGE operations

  -- System dimension (always required)
  system_id STRING NOT NULL,

  -- Time dimension (always required)
  period_type STRING NOT NULL,              -- 'rolling_7d', 'rolling_30d', 'month', 'season'
  period_value STRING NOT NULL,             -- '2024-12-17', '2024-12', '2024-25'
  period_start_date DATE,
  period_end_date DATE,

  -- Slicing dimensions (NULL = aggregate across all values)
  player_lookup STRING,                     -- Specific player or NULL for all
  archetype STRING,                         -- 'veteran_star', etc. or NULL
  confidence_tier STRING,                   -- 'high', 'medium', 'low', or NULL
  situation STRING,                         -- 'bounce_back', 'home', 'away', etc.

  -- Volume metrics
  total_predictions INT64,
  total_recommendations INT64,
  over_recommendations INT64,
  under_recommendations INT64,
  pass_recommendations INT64,

  -- Accuracy metrics
  hits INT64,
  misses INT64,
  hit_rate FLOAT64,
  over_hit_rate FLOAT64,
  under_hit_rate FLOAT64,

  -- Error metrics
  mae FLOAT64,
  avg_bias FLOAT64,
  within_3_pct FLOAT64,
  within_5_pct FLOAT64,
  avg_confidence FLOAT64,

  -- Sample quality
  unique_players INT64,
  unique_games INT64,

  -- Metadata
  computed_at TIMESTAMP NOT NULL,
  data_hash STRING
)
PARTITION BY DATE(computed_at)
CLUSTER BY system_id, period_type, archetype, player_lookup;
```

**Run processor to populate:**
```bash
PYTHONPATH=. .venv/bin/python data_processors/grading/performance_summary/performance_summary_processor.py \
  --date 2024-12-16
```

---

## 2. Days Rest / Back-to-Back View

```sql
-- =============================================================================
-- View: player_game_rest
-- Purpose: Calculate days of rest between games for each player
-- =============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_analytics.player_game_rest` AS
WITH ordered_games AS (
  SELECT
    player_lookup,
    game_date,
    game_id,
    team_abbr,
    opponent_team_abbr,
    LAG(game_date) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
    ) as prev_game_date
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE is_active = TRUE
)
SELECT
  player_lookup,
  game_date,
  game_id,
  team_abbr,
  opponent_team_abbr,
  prev_game_date,
  DATE_DIFF(game_date, prev_game_date, DAY) as days_rest,
  CASE
    WHEN DATE_DIFF(game_date, prev_game_date, DAY) = 1 THEN TRUE
    ELSE FALSE
  END as is_b2b,
  CASE
    WHEN DATE_DIFF(game_date, prev_game_date, DAY) >= 3 THEN '3+'
    WHEN DATE_DIFF(game_date, prev_game_date, DAY) = 2 THEN '2'
    WHEN DATE_DIFF(game_date, prev_game_date, DAY) = 1 THEN 'B2B'
    ELSE 'unknown'
  END as rest_category
FROM ordered_games;

-- =============================================================================
-- View: team_game_rest
-- Purpose: Calculate days of rest for teams (for opponent B2B detection)
-- =============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_analytics.team_game_rest` AS
WITH team_games AS (
  SELECT DISTINCT
    team_abbr,
    game_date,
    game_id
  FROM `nba-props-platform.nba_analytics.player_game_summary`
),
ordered_games AS (
  SELECT
    team_abbr,
    game_date,
    game_id,
    LAG(game_date) OVER (
      PARTITION BY team_abbr
      ORDER BY game_date
    ) as prev_game_date
  FROM team_games
)
SELECT
  team_abbr,
  game_date,
  game_id,
  DATE_DIFF(game_date, prev_game_date, DAY) as days_rest,
  DATE_DIFF(game_date, prev_game_date, DAY) = 1 as is_b2b
FROM ordered_games;
```

---

## 3. Player Archetypes Table

```sql
-- =============================================================================
-- Table: player_archetypes
-- Purpose: Classify players into archetypes for contextual analysis
-- Refresh: Daily at 6 AM ET via scheduled query
-- =============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.player_archetypes` (
  player_lookup STRING NOT NULL,
  season STRING NOT NULL,

  -- Classification inputs
  years_in_league INT64,
  season_ppg NUMERIC(5,1),
  season_usage_rate NUMERIC(5,3),
  rest_3plus_ppg NUMERIC(5,1),
  rest_normal_ppg NUMERIC(5,1),
  rest_variance NUMERIC(5,2),
  home_ppg NUMERIC(5,1),
  away_ppg NUMERIC(5,1),
  home_away_variance NUMERIC(5,2),
  games_played INT64,

  -- Classification output
  archetype STRING NOT NULL,  -- veteran_star, prime_star, young_star, ironman, role_player
  archetype_label STRING,     -- Human-readable label

  -- Sensitivity ratings
  rest_sensitivity STRING,    -- high, medium, low, none
  home_sensitivity STRING,    -- high, medium, low

  -- Metadata
  computed_at TIMESTAMP NOT NULL,
  data_hash STRING
)
CLUSTER BY player_lookup, archetype
OPTIONS (
  description = 'Player archetype classification based on experience, usage, and scoring patterns'
);

-- =============================================================================
-- Scheduled Query: Refresh player_archetypes daily
-- Schedule: 6:00 AM ET daily
-- =============================================================================

-- Run this as a scheduled query:
MERGE INTO `nba-props-platform.nba_analytics.player_archetypes` target
USING (
  WITH career_start AS (
    SELECT
      player_lookup,
      MIN(first_game_date) as career_start_date
    FROM `nba-props-platform.nba_reference.nba_players_registry`
    GROUP BY player_lookup
  ),
  season_stats AS (
    SELECT
      pgs.player_lookup,
      '2024-25' as season,
      DATE_DIFF(CURRENT_DATE(), cs.career_start_date, YEAR) as years_in_league,
      ROUND(AVG(pgs.points), 1) as season_ppg,
      ROUND(AVG(pgs.usage_rate), 3) as season_usage_rate,
      COUNT(*) as games_played
    FROM `nba-props-platform.nba_analytics.player_game_summary` pgs
    JOIN career_start cs USING (player_lookup)
    WHERE pgs.game_date >= '2024-10-01'  -- Current season
      AND pgs.is_active = TRUE
      AND pgs.minutes_played >= 10
    GROUP BY pgs.player_lookup, cs.career_start_date
    HAVING COUNT(*) >= 5  -- Minimum games for classification
  ),
  rest_impact AS (
    SELECT
      pgs.player_lookup,
      ROUND(AVG(CASE WHEN pgr.days_rest >= 3 THEN pgs.points END), 1) as rest_3plus_ppg,
      ROUND(AVG(CASE WHEN pgr.days_rest < 3 THEN pgs.points END), 1) as rest_normal_ppg
    FROM `nba-props-platform.nba_analytics.player_game_summary` pgs
    JOIN `nba-props-platform.nba_analytics.player_game_rest` pgr
      USING (player_lookup, game_date)
    WHERE pgs.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
      AND pgs.is_active = TRUE
    GROUP BY pgs.player_lookup
  ),
  home_away_impact AS (
    SELECT
      player_lookup,
      ROUND(AVG(CASE WHEN team_abbr = SPLIT(game_id, '_')[OFFSET(2)] THEN points END), 1) as home_ppg,
      ROUND(AVG(CASE WHEN team_abbr != SPLIT(game_id, '_')[OFFSET(2)] THEN points END), 1) as away_ppg
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
      AND is_active = TRUE
    GROUP BY player_lookup
  )
  SELECT
    ss.player_lookup,
    ss.season,
    ss.years_in_league,
    ss.season_ppg,
    ss.season_usage_rate,
    ri.rest_3plus_ppg,
    ri.rest_normal_ppg,
    ROUND(ABS(COALESCE(ri.rest_3plus_ppg, 0) - COALESCE(ri.rest_normal_ppg, 0)), 2) as rest_variance,
    ha.home_ppg,
    ha.away_ppg,
    ROUND(ABS(COALESCE(ha.home_ppg, 0) - COALESCE(ha.away_ppg, 0)), 2) as home_away_variance,
    ss.games_played,

    -- Archetype classification
    CASE
      WHEN ss.years_in_league >= 10 AND ss.season_usage_rate >= 0.25 AND ss.season_ppg >= 20
        THEN 'veteran_star'
      WHEN ss.years_in_league BETWEEN 5 AND 9 AND ss.season_usage_rate >= 0.28 AND ss.season_ppg >= 22
        THEN 'prime_star'
      WHEN ss.years_in_league < 5 AND ss.season_usage_rate >= 0.22 AND ss.season_ppg >= 18
        THEN 'young_star'
      WHEN ABS(COALESCE(ri.rest_3plus_ppg, 0) - COALESCE(ri.rest_normal_ppg, 0)) < 1.5
        AND ss.games_played >= 15
        THEN 'ironman'
      ELSE 'role_player'
    END as archetype,

    CASE
      WHEN ss.years_in_league >= 10 AND ss.season_usage_rate >= 0.25 AND ss.season_ppg >= 20
        THEN 'Veteran Star'
      WHEN ss.years_in_league BETWEEN 5 AND 9 AND ss.season_usage_rate >= 0.28 AND ss.season_ppg >= 22
        THEN 'Prime Star'
      WHEN ss.years_in_league < 5 AND ss.season_usage_rate >= 0.22 AND ss.season_ppg >= 18
        THEN 'Young Star'
      WHEN ABS(COALESCE(ri.rest_3plus_ppg, 0) - COALESCE(ri.rest_normal_ppg, 0)) < 1.5
        AND ss.games_played >= 15
        THEN 'Ironman'
      ELSE 'Role Player'
    END as archetype_label,

    -- Rest sensitivity
    CASE
      WHEN ABS(COALESCE(ri.rest_3plus_ppg, 0) - COALESCE(ri.rest_normal_ppg, 0)) >= 4 THEN 'high'
      WHEN ABS(COALESCE(ri.rest_3plus_ppg, 0) - COALESCE(ri.rest_normal_ppg, 0)) >= 2 THEN 'medium'
      WHEN ABS(COALESCE(ri.rest_3plus_ppg, 0) - COALESCE(ri.rest_normal_ppg, 0)) >= 1 THEN 'low'
      ELSE 'none'
    END as rest_sensitivity,

    -- Home sensitivity
    CASE
      WHEN ABS(COALESCE(ha.home_ppg, 0) - COALESCE(ha.away_ppg, 0)) >= 3 THEN 'high'
      WHEN ABS(COALESCE(ha.home_ppg, 0) - COALESCE(ha.away_ppg, 0)) >= 1.5 THEN 'medium'
      ELSE 'low'
    END as home_sensitivity,

    CURRENT_TIMESTAMP() as computed_at,
    TO_HEX(SHA256(CONCAT(
      ss.player_lookup, '|',
      CAST(ss.years_in_league AS STRING), '|',
      CAST(ss.season_ppg AS STRING), '|',
      CAST(ss.games_played AS STRING)
    ))) as data_hash

  FROM season_stats ss
  LEFT JOIN rest_impact ri USING (player_lookup)
  LEFT JOIN home_away_impact ha USING (player_lookup)
) source
ON target.player_lookup = source.player_lookup AND target.season = source.season
WHEN MATCHED AND target.data_hash != source.data_hash THEN UPDATE SET
  years_in_league = source.years_in_league,
  season_ppg = source.season_ppg,
  season_usage_rate = source.season_usage_rate,
  rest_3plus_ppg = source.rest_3plus_ppg,
  rest_normal_ppg = source.rest_normal_ppg,
  rest_variance = source.rest_variance,
  home_ppg = source.home_ppg,
  away_ppg = source.away_ppg,
  home_away_variance = source.home_away_variance,
  games_played = source.games_played,
  archetype = source.archetype,
  archetype_label = source.archetype_label,
  rest_sensitivity = source.rest_sensitivity,
  home_sensitivity = source.home_sensitivity,
  computed_at = source.computed_at,
  data_hash = source.data_hash
WHEN NOT MATCHED THEN INSERT ROW;
```

---

## 4. Shot Profile View

```sql
-- =============================================================================
-- View: player_shot_profiles
-- Purpose: Classify players by dominant shot zone
-- =============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_analytics.player_shot_profiles` AS
SELECT
  player_lookup,
  analysis_date,
  paint_rate_last_10,
  mid_range_rate_last_10,
  three_pt_rate_last_10,

  CASE
    WHEN paint_rate_last_10 >= 0.50 THEN 'interior'
    WHEN three_pt_rate_last_10 >= 0.50 THEN 'perimeter'
    WHEN mid_range_rate_last_10 >= 0.30 THEN 'mid_range'
    ELSE 'balanced'
  END as shot_profile,

  CASE
    WHEN paint_rate_last_10 >= 0.50 THEN 'Interior Scorer'
    WHEN three_pt_rate_last_10 >= 0.50 THEN 'Perimeter Shooter'
    WHEN mid_range_rate_last_10 >= 0.30 THEN 'Mid-Range Specialist'
    ELSE 'Balanced Scorer'
  END as shot_profile_label

FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = (
  SELECT MAX(analysis_date)
  FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
);
```

---

## 5. Player Current Form Table (Heat Score)

```sql
-- =============================================================================
-- Table: player_current_form
-- Purpose: Track player temperature/heat score for betting analysis
-- Refresh: Daily at 6 AM ET
-- =============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.player_current_form` (
  player_lookup STRING NOT NULL,
  computed_date DATE NOT NULL,

  -- Heat Score Components
  hit_rate_l10 NUMERIC(5,3),
  hit_rate_score NUMERIC(5,2),
  streak_direction STRING,
  streak_count INT64,
  streak_score NUMERIC(5,2),
  avg_margin_l10 NUMERIC(5,2),
  margin_score NUMERIC(5,2),

  -- Final Score
  heat_score NUMERIC(5,2),
  temperature STRING,

  -- Supporting Stats
  games_with_props_l10 INT64,
  overs_l10 INT64,
  unders_l10 INT64,
  pushes_l10 INT64,

  -- L10 Detail
  l10_game_dates ARRAY<DATE>,
  l10_results ARRAY<STRING>,

  -- Metadata
  computed_at TIMESTAMP NOT NULL
)
PARTITION BY computed_date
CLUSTER BY player_lookup, temperature
OPTIONS (
  description = 'Player current form metrics including heat score for betting analysis'
);

-- =============================================================================
-- Scheduled Query: Refresh player_current_form daily
-- Schedule: 6:00 AM ET daily
-- =============================================================================

-- (Complex streak calculation - run as scheduled query)
MERGE INTO `nba-props-platform.nba_analytics.player_current_form` target
USING (
  WITH player_recent AS (
    SELECT
      player_lookup,
      game_date,
      points,
      points_line,
      over_under_result,
      margin,
      ROW_NUMBER() OVER (
        PARTITION BY player_lookup
        ORDER BY game_date DESC
      ) as game_num
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE points_line IS NOT NULL
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 45 DAY)
  ),
  l10_agg AS (
    SELECT
      player_lookup,
      ARRAY_AGG(game_date ORDER BY game_date DESC) as game_dates,
      ARRAY_AGG(over_under_result ORDER BY game_date DESC) as results,
      SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) as overs,
      SUM(CASE WHEN over_under_result = 'UNDER' THEN 1 ELSE 0 END) as unders,
      SUM(CASE WHEN over_under_result = 'PUSH' THEN 1 ELSE 0 END) as pushes,
      COUNT(*) as games,
      SAFE_DIVIDE(
        SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END),
        COUNT(*)
      ) as hit_rate,
      AVG(margin) as avg_margin
    FROM player_recent
    WHERE game_num <= 10
    GROUP BY player_lookup
    HAVING COUNT(*) >= 3
  ),
  streak_detection AS (
    -- Find current streak by detecting first change
    SELECT
      player_lookup,
      FIRST_VALUE(over_under_result) OVER (
        PARTITION BY player_lookup
        ORDER BY game_date DESC
      ) as current_direction,
      game_num
    FROM player_recent
    WHERE game_num <= 10
  ),
  streak_length AS (
    SELECT
      sd.player_lookup,
      sd.current_direction as streak_direction,
      COUNT(*) as streak_count
    FROM streak_detection sd
    JOIN player_recent pr ON sd.player_lookup = pr.player_lookup AND sd.game_num = pr.game_num
    WHERE pr.over_under_result = sd.current_direction
      AND pr.game_num <= 10
    GROUP BY sd.player_lookup, sd.current_direction
  )
  SELECT
    l.player_lookup,
    CURRENT_DATE() as computed_date,
    ROUND(l.hit_rate, 3) as hit_rate_l10,
    ROUND(l.hit_rate * 10, 2) as hit_rate_score,
    COALESCE(s.streak_direction, 'mixed') as streak_direction,
    COALESCE(s.streak_count, 0) as streak_count,
    LEAST(COALESCE(s.streak_count, 0), 10) as streak_score,
    ROUND(l.avg_margin, 2) as avg_margin_l10,
    ROUND(LEAST(GREATEST((l.avg_margin / 5) + 5, 0), 10), 2) as margin_score,

    -- Heat Score
    ROUND(
      (0.50 * (l.hit_rate * 10)) +
      (0.25 * LEAST(COALESCE(s.streak_count, 0), 10)) +
      (0.25 * LEAST(GREATEST((l.avg_margin / 5) + 5, 0), 10)),
      2
    ) as heat_score,

    -- Temperature
    CASE
      WHEN (0.50 * (l.hit_rate * 10)) +
           (0.25 * LEAST(COALESCE(s.streak_count, 0), 10)) +
           (0.25 * LEAST(GREATEST((l.avg_margin / 5) + 5, 0), 10)) >= 8.0 THEN 'hot'
      WHEN (0.50 * (l.hit_rate * 10)) +
           (0.25 * LEAST(COALESCE(s.streak_count, 0), 10)) +
           (0.25 * LEAST(GREATEST((l.avg_margin / 5) + 5, 0), 10)) >= 6.5 THEN 'warm'
      WHEN (0.50 * (l.hit_rate * 10)) +
           (0.25 * LEAST(COALESCE(s.streak_count, 0), 10)) +
           (0.25 * LEAST(GREATEST((l.avg_margin / 5) + 5, 0), 10)) >= 4.5 THEN 'neutral'
      WHEN (0.50 * (l.hit_rate * 10)) +
           (0.25 * LEAST(COALESCE(s.streak_count, 0), 10)) +
           (0.25 * LEAST(GREATEST((l.avg_margin / 5) + 5, 0), 10)) >= 3.0 THEN 'cool'
      ELSE 'cold'
    END as temperature,

    l.games as games_with_props_l10,
    l.overs as overs_l10,
    l.unders as unders_l10,
    l.pushes as pushes_l10,
    l.game_dates as l10_game_dates,
    l.results as l10_results,

    CURRENT_TIMESTAMP() as computed_at

  FROM l10_agg l
  LEFT JOIN streak_length s USING (player_lookup)
) source
ON target.player_lookup = source.player_lookup
  AND target.computed_date = source.computed_date
WHEN NOT MATCHED THEN INSERT ROW;
```

---

## 6. Bounce-Back Candidates Table

```sql
-- =============================================================================
-- Table: bounce_back_candidates
-- Purpose: Identify players due for regression after underperforming
-- Refresh: Daily at 6 AM ET
-- =============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.bounce_back_candidates` (
  player_lookup STRING NOT NULL,
  computed_date DATE NOT NULL,
  prop_type STRING NOT NULL DEFAULT 'points',

  -- Last Game Details
  last_game_date DATE,
  last_game_result NUMERIC(5,1),
  last_game_line NUMERIC(4,1),
  last_game_margin NUMERIC(5,2),
  last_game_opponent STRING,
  last_game_context STRING,

  -- Streak Info
  consecutive_misses INT64,
  misses_of_last_5 INT64,
  avg_miss_margin NUMERIC(5,2),

  -- Baseline
  season_hit_rate NUMERIC(5,3),
  season_avg NUMERIC(5,1),
  season_games INT64,

  -- Tonight's Opportunity
  tonight_opponent STRING,
  tonight_opponent_defense_rank INT64,
  tonight_line NUMERIC(4,1),
  tonight_game_time STRING,
  tonight_home BOOLEAN,
  is_playing_tonight BOOLEAN,

  -- Signal
  signal_strength STRING,
  is_qualified BOOLEAN,
  qualification_reason STRING,

  -- Metadata
  computed_at TIMESTAMP NOT NULL
)
PARTITION BY computed_date
CLUSTER BY player_lookup, signal_strength
OPTIONS (
  description = 'Players identified as bounce-back candidates based on recent underperformance'
);
```

---

## Execution Order

1. **Section 1.1** - Add result tracking columns (ALTER TABLE)
2. **Section 1.1** - Backfill existing predictions (MERGE)
3. **Section 1.2** - Create prediction performance view
4. **Section 2** - Create days rest views
5. **Section 3** - Create archetypes table
6. **Section 4** - Create shot profiles view
7. **Section 5** - Create current form table
8. **Section 6** - Create bounce-back candidates table

---

## Validation Queries

After executing migrations, validate with:

```sql
-- Check prediction result coverage
SELECT
  COUNT(*) as total,
  COUNTIF(result_status = 'final') as with_results,
  COUNTIF(result_status = 'pending') as pending,
  COUNTIF(result_hit = TRUE) as hits,
  COUNTIF(result_hit = FALSE) as misses
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= '2024-10-01';

-- Check archetype distribution
SELECT
  archetype,
  COUNT(*) as player_count,
  AVG(season_ppg) as avg_ppg
FROM `nba-props-platform.nba_analytics.player_archetypes`
WHERE season = '2024-25'
GROUP BY archetype
ORDER BY player_count DESC;

-- Check heat score distribution
SELECT
  temperature,
  COUNT(*) as player_count,
  AVG(heat_score) as avg_heat_score
FROM `nba-props-platform.nba_analytics.player_current_form`
WHERE computed_date = CURRENT_DATE()
GROUP BY temperature
ORDER BY avg_heat_score DESC;
```
