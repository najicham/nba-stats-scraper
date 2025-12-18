# Implementation Plan

**Created:** December 17, 2024
**Last Updated:** December 17, 2024
**Purpose:** Phased approach to building frontend API backend

---

## Overview

This document outlines the implementation strategy for delivering the backend infrastructure needed by the Props Web frontend. The plan is organized into phases based on dependencies and priority.

---

## Phase Summary

| Phase | Focus | Dependencies | Deliverables |
|-------|-------|--------------|--------------|
| **Phase 1** | Foundation | None | Schema changes, prediction results |
| **Phase 2** | Derived Data | Phase 1 | Archetypes, shot profiles, heat scores |
| **Phase 3** | API Layer | Phase 2 | REST endpoints for Player Modal |
| **Phase 4** | Trends | Phase 3 | Trends page data and endpoints |
| **Phase 5** | Polish | Phase 4 | Caching, monitoring, optimization |

---

## Phase 1: Foundation (Week 1)

**Goal:** Establish prediction result tracking and core derived fields.

### 1.1 Add Result Tracking to Predictions Table

**Priority:** :red_circle: Critical (must do first)

**Rationale:** Every day without result tracking is lost track record history.

**Changes:**
```sql
ALTER TABLE `nba-props-platform.nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS result_status STRING
  OPTIONS (description='pending, final, or cancelled'),
ADD COLUMN IF NOT EXISTS actual_value NUMERIC(5,1)
  OPTIONS (description='Actual points scored'),
ADD COLUMN IF NOT EXISTS result_hit BOOLEAN
  OPTIONS (description='TRUE if prediction was correct'),
ADD COLUMN IF NOT EXISTS result_margin NUMERIC(5,2)
  OPTIONS (description='actual_value - current_points_line'),
ADD COLUMN IF NOT EXISTS result_updated_at TIMESTAMP
  OPTIONS (description='When result was recorded');
```

**Deliverables:**
- [ ] SQL migration script
- [ ] Backfill script for past predictions (join to player_game_summary)
- [ ] Documentation update

### 1.2 Create Prediction Result Updater Job

**Priority:** :red_circle: Critical

**Purpose:** Automatically update predictions with actual results after games.

**Implementation:**

```python
# processors/prediction_result_updater.py

class PredictionResultUpdater:
    """
    Updates pending predictions with actual game results.

    Schedule: Every 30 minutes during game nights (7 PM - 1 AM ET)
    """

    def process(self, game_date: date) -> dict:
        # 1. Get pending predictions for date
        pending = self.get_pending_predictions(game_date)

        # 2. Get actual results from player_game_summary
        actuals = self.get_actual_results(game_date)

        # 3. Match and update
        updated = 0
        for pred in pending:
            if pred.player_lookup in actuals:
                actual = actuals[pred.player_lookup]

                # Determine if hit
                hit = None
                if pred.recommendation == 'OVER':
                    hit = actual.points > pred.current_points_line
                elif pred.recommendation == 'UNDER':
                    hit = actual.points < pred.current_points_line
                # PASS predictions don't have hit/miss

                self.update_prediction(
                    prediction_id=pred.prediction_id,
                    result_status='final',
                    actual_value=actual.points,
                    result_hit=hit,
                    result_margin=actual.points - pred.current_points_line,
                    result_updated_at=datetime.utcnow()
                )
                updated += 1

        return {'updated': updated, 'pending': len(pending)}
```

**Deliverables:**
- [ ] Processor class implementation
- [ ] Cloud Scheduler job configuration
- [ ] Pub/Sub trigger (optional - or cron-based)
- [ ] Monitoring/alerting for failures

### 1.3 Create Days Rest / B2B Computation

**Priority:** :yellow_circle: High

**Options:**

**Option A: Add to player_game_summary**
```sql
-- Add computed fields to existing table
ALTER TABLE nba_analytics.player_game_summary
ADD COLUMN IF NOT EXISTS days_rest INT64,
ADD COLUMN IF NOT EXISTS is_b2b BOOLEAN;

-- Update via processor pass
```

**Option B: Create helper view**
```sql
CREATE VIEW nba_analytics.player_game_rest AS
WITH ordered_games AS (
  SELECT
    player_lookup,
    game_date,
    LAG(game_date) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
    ) as prev_game_date
  FROM nba_analytics.player_game_summary
  WHERE is_active = TRUE
)
SELECT
  player_lookup,
  game_date,
  DATE_DIFF(game_date, prev_game_date, DAY) as days_rest,
  DATE_DIFF(game_date, prev_game_date, DAY) = 1 as is_b2b
FROM ordered_games;
```

**Recommendation:** Option B for immediate use, migrate to Option A when refactoring processor.

**Deliverables:**
- [ ] View creation SQL
- [ ] Documentation
- [ ] Validate against sample games

---

## Phase 2: Derived Data (Week 2)

**Goal:** Build archetype classification, shot profiles, and heat scores.

### 2.1 Create Player Archetypes Table

**Priority:** :yellow_circle: High

**Schema:**
```sql
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
  games_played INT64,

  -- Classification output
  archetype STRING NOT NULL,  -- veteran_star, prime_star, young_star, ironman, role_player
  archetype_confidence NUMERIC(5,2),  -- 0-100 confidence in classification

  -- Impact factors (from historical analysis)
  rest_sensitivity STRING,  -- high, medium, low, none
  home_sensitivity STRING,  -- high, medium, low

  -- Metadata
  computed_at TIMESTAMP NOT NULL,
  data_hash STRING
)
PARTITION BY DATE(computed_at)
CLUSTER BY player_lookup, archetype;
```

**Classification Logic:**
```sql
-- Materialized query for archetype classification
WITH career_start AS (
  SELECT
    player_lookup,
    MIN(first_game_date) as career_start_date
  FROM nba_reference.nba_players_registry
  GROUP BY player_lookup
),
season_stats AS (
  SELECT
    pgs.player_lookup,
    DATE_DIFF(CURRENT_DATE(), cs.career_start_date, YEAR) as years_in_league,
    AVG(pgs.points) as season_ppg,
    AVG(pgs.usage_rate) as season_usage_rate,
    COUNT(*) as games_played
  FROM nba_analytics.player_game_summary pgs
  JOIN career_start cs USING (player_lookup)
  WHERE pgs.game_date >= DATE_TRUNC(CURRENT_DATE(), YEAR)  -- Current season
    AND pgs.is_active = TRUE
    AND pgs.minutes_played >= 10
  GROUP BY pgs.player_lookup, cs.career_start_date
  HAVING COUNT(*) >= 10  -- Minimum games
),
rest_impact AS (
  SELECT
    pgs.player_lookup,
    AVG(CASE WHEN pgr.days_rest >= 3 THEN pgs.points END) as rest_3plus_ppg,
    AVG(CASE WHEN pgr.days_rest < 3 THEN pgs.points END) as rest_normal_ppg
  FROM nba_analytics.player_game_summary pgs
  JOIN nba_analytics.player_game_rest pgr USING (player_lookup, game_date)
  WHERE pgs.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
    AND pgs.is_active = TRUE
  GROUP BY pgs.player_lookup
)
SELECT
  ss.player_lookup,
  FORMAT_DATE('%Y-%y', CURRENT_DATE()) as season,
  ss.years_in_league,
  ss.season_ppg,
  ss.season_usage_rate,
  ri.rest_3plus_ppg,
  ri.rest_normal_ppg,
  ABS(COALESCE(ri.rest_3plus_ppg, 0) - COALESCE(ri.rest_normal_ppg, 0)) as rest_variance,
  ss.games_played,

  CASE
    WHEN ss.years_in_league >= 10 AND ss.season_usage_rate >= 0.25 AND ss.season_ppg >= 20
      THEN 'veteran_star'
    WHEN ss.years_in_league BETWEEN 5 AND 9 AND ss.season_usage_rate >= 0.28 AND ss.season_ppg >= 22
      THEN 'prime_star'
    WHEN ss.years_in_league < 5 AND ss.season_usage_rate >= 0.22 AND ss.season_ppg >= 18
      THEN 'young_star'
    WHEN ABS(COALESCE(ri.rest_3plus_ppg, 0) - COALESCE(ri.rest_normal_ppg, 0)) < 1.5
      AND ss.games_played >= 20
      THEN 'ironman'
    ELSE 'role_player'
  END as archetype,

  -- Confidence based on sample size
  LEAST(ss.games_played * 2, 100) as archetype_confidence,

  CASE
    WHEN ABS(COALESCE(ri.rest_3plus_ppg, 0) - COALESCE(ri.rest_normal_ppg, 0)) >= 4 THEN 'high'
    WHEN ABS(COALESCE(ri.rest_3plus_ppg, 0) - COALESCE(ri.rest_normal_ppg, 0)) >= 2 THEN 'medium'
    WHEN ABS(COALESCE(ri.rest_3plus_ppg, 0) - COALESCE(ri.rest_normal_ppg, 0)) >= 1 THEN 'low'
    ELSE 'none'
  END as rest_sensitivity,

  -- Home sensitivity (simplified)
  'medium' as home_sensitivity,  -- TODO: Compute from home/away splits

  CURRENT_TIMESTAMP() as computed_at,
  TO_HEX(SHA256(CONCAT(
    ss.player_lookup,
    CAST(ss.years_in_league AS STRING),
    CAST(ss.season_ppg AS STRING)
  ))) as data_hash

FROM season_stats ss
LEFT JOIN rest_impact ri USING (player_lookup);
```

**Refresh Schedule:** Daily at 6 AM ET

**Deliverables:**
- [ ] Table creation SQL
- [ ] Scheduled query for daily refresh
- [ ] Backfill for current season
- [ ] Validation queries

### 2.2 Add Shot Profile Classification

**Priority:** :yellow_circle: High

**Approach:** Add computed column to existing `player_shot_zone_analysis` or create view.

```sql
CREATE VIEW nba_analytics.player_shot_profiles AS
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
  END as shot_profile

FROM nba_precompute.player_shot_zone_analysis
WHERE analysis_date = (
  SELECT MAX(analysis_date)
  FROM nba_precompute.player_shot_zone_analysis
);
```

**Deliverables:**
- [ ] View creation SQL
- [ ] Documentation

### 2.3 Create Heat Score Calculator

**Priority:** :yellow_circle: High

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.player_current_form` (
  player_lookup STRING NOT NULL,
  computed_date DATE NOT NULL,

  -- Heat Score Components
  hit_rate_l10 NUMERIC(5,3),      -- 0-1
  hit_rate_score NUMERIC(5,2),    -- 0-10 normalized

  streak_direction STRING,         -- 'over', 'under', 'mixed'
  streak_count INT64,              -- Consecutive hits
  streak_score NUMERIC(5,2),       -- 0-10 capped

  avg_margin_l10 NUMERIC(5,2),
  margin_score NUMERIC(5,2),       -- 0-10 normalized

  -- Final Score
  heat_score NUMERIC(5,2),         -- 0-10
  temperature STRING,              -- 'hot', 'warm', 'neutral', 'cool', 'cold'

  -- Supporting Stats
  games_with_props_l10 INT64,
  overs_l10 INT64,
  unders_l10 INT64,
  pushes_l10 INT64,

  -- Metadata
  computed_at TIMESTAMP NOT NULL
)
PARTITION BY computed_date
CLUSTER BY player_lookup, temperature;
```

**Heat Score Logic:**
```sql
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
  FROM nba_analytics.player_game_summary
  WHERE points_line IS NOT NULL
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),
l10_stats AS (
  SELECT
    player_lookup,

    -- Hit Rate
    SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) as overs,
    SUM(CASE WHEN over_under_result = 'UNDER' THEN 1 ELSE 0 END) as unders,
    SUM(CASE WHEN over_under_result = 'PUSH' THEN 1 ELSE 0 END) as pushes,
    COUNT(*) as games,
    SAFE_DIVIDE(
      SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END),
      NULLIF(COUNT(*), 0)
    ) as hit_rate,

    -- Margin
    AVG(margin) as avg_margin

  FROM player_recent
  WHERE game_num <= 10
  GROUP BY player_lookup
  HAVING COUNT(*) >= 3  -- Minimum 3 games
),
streak_calc AS (
  -- Calculate consecutive streak
  SELECT
    player_lookup,
    over_under_result as streak_direction,
    COUNT(*) as streak_count
  FROM (
    SELECT
      player_lookup,
      over_under_result,
      game_date,
      ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
    FROM player_recent
    WHERE game_num <= 10
  )
  WHERE rn <= (
    -- Find first break in streak
    SELECT COALESCE(MIN(inner_rn) - 1, 10)
    FROM (
      SELECT
        ROW_NUMBER() OVER (ORDER BY game_date DESC) as inner_rn,
        over_under_result,
        LAG(over_under_result) OVER (ORDER BY game_date DESC) as prev_result
      FROM player_recent pr2
      WHERE pr2.player_lookup = player_recent.player_lookup
        AND pr2.game_num <= 10
    ) inner_q
    WHERE over_under_result != prev_result
  )
  GROUP BY player_lookup, over_under_result
)
SELECT
  l.player_lookup,
  CURRENT_DATE() as computed_date,

  -- Hit Rate Component
  l.hit_rate as hit_rate_l10,
  l.hit_rate * 10 as hit_rate_score,

  -- Streak Component
  COALESCE(s.streak_direction, 'mixed') as streak_direction,
  COALESCE(s.streak_count, 0) as streak_count,
  LEAST(COALESCE(s.streak_count, 0), 10) as streak_score,

  -- Margin Component
  l.avg_margin as avg_margin_l10,
  LEAST(GREATEST((l.avg_margin / 5) + 5, 0), 10) as margin_score,

  -- Heat Score Calculation
  (0.50 * (l.hit_rate * 10)) +
  (0.25 * LEAST(COALESCE(s.streak_count, 0), 10)) +
  (0.25 * LEAST(GREATEST((l.avg_margin / 5) + 5, 0), 10)) as heat_score,

  -- Temperature Classification
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

  -- Supporting Stats
  l.games as games_with_props_l10,
  l.overs as overs_l10,
  l.unders as unders_l10,
  l.pushes as pushes_l10,

  CURRENT_TIMESTAMP() as computed_at

FROM l10_stats l
LEFT JOIN streak_calc s USING (player_lookup);
```

**Refresh Schedule:** Daily at 6 AM ET

**Deliverables:**
- [ ] Table creation SQL
- [ ] Scheduled query for daily refresh
- [ ] Streak calculation refinement
- [ ] Validation against manual calculations

### 2.4 Create Bounce-Back Detection

**Priority:** :orange_circle: Medium

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.bounce_back_candidates` (
  player_lookup STRING NOT NULL,
  computed_date DATE NOT NULL,
  prop_type STRING NOT NULL,  -- 'points', 'rebounds', 'assists'

  -- Last Game Details
  last_game_date DATE,
  last_game_result NUMERIC(5,1),
  last_game_line NUMERIC(4,1),
  last_game_margin NUMERIC(5,2),
  last_game_opponent STRING,
  last_game_context STRING,  -- 'foul trouble', 'blowout', etc.

  -- Streak Info
  consecutive_misses INT64,
  misses_of_last_5 INT64,
  avg_miss_margin NUMERIC(5,2),

  -- Baseline
  season_hit_rate NUMERIC(5,3),
  season_avg NUMERIC(5,1),

  -- Tonight's Opportunity (if playing)
  tonight_opponent STRING,
  tonight_opponent_defense_rank INT64,
  tonight_line NUMERIC(4,1),
  tonight_game_time STRING,
  tonight_home BOOLEAN,

  -- Signal
  signal_strength STRING,  -- 'strong', 'moderate'
  is_qualified BOOLEAN,

  -- Metadata
  computed_at TIMESTAMP NOT NULL
)
PARTITION BY computed_date
CLUSTER BY player_lookup, signal_strength;
```

**Deliverables:**
- [ ] Table creation SQL
- [ ] Detection logic implementation
- [ ] Signal strength calculation
- [ ] Integration with schedule for "tonight" data

---

## Phase 3: API Layer (Week 3)

**Goal:** Build REST API endpoints for Player Modal.

### 3.1 API Service Setup

**Technology Stack:**
- FastAPI (Python)
- Google Cloud Run (deployment)
- BigQuery Python client
- Redis (caching - optional for MVP)

**Project Structure:**
```
props-api/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── player.py
│   │   ├── trends.py
│   │   └── predictions.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── bigquery.py
│   │   ├── player_service.py
│   │   ├── trends_service.py
│   │   └── prediction_service.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── player.py
│   │   ├── trends.py
│   │   └── predictions.py
│   └── utils/
│       ├── __init__.py
│       └── cache.py
├── tests/
├── Dockerfile
├── requirements.txt
└── cloudbuild.yaml
```

**Deliverables:**
- [ ] Repository setup
- [ ] FastAPI boilerplate
- [ ] BigQuery client configuration
- [ ] Docker configuration
- [ ] Cloud Run deployment

### 3.2 Player Game Report Endpoint

**Endpoint:** `GET /v1/player/{player_lookup}/game-report/{date}`

**Implementation Approach:**
1. Multiple BigQuery queries (parallelized)
2. Transform to response schema
3. Cache historical games (24h)

**Query Breakdown:**

| Data | Query |
|------|-------|
| Player profile + game info | Single query joining player_game_summary + archetypes + shot_profiles |
| Opponent context | team_offense_game_summary + team_defense_zone_analysis |
| Prop lines | bettingpros_player_points_props |
| Moving averages | Window functions on player_game_summary |
| Recent games | Filter + sort player_game_summary |
| Head-to-head | Filter player_game_summary by opponent |
| Prediction | player_prop_predictions for date |

**Deliverables:**
- [ ] Endpoint implementation
- [ ] Response model (Pydantic)
- [ ] Query optimization
- [ ] Caching strategy
- [ ] Error handling

### 3.3 Player Season Endpoint

**Endpoint:** `GET /v1/player/{player_lookup}/season/{season}`

**Simpler than Game Report - mostly aggregations.**

**Deliverables:**
- [ ] Endpoint implementation
- [ ] Response model
- [ ] Aggregation queries

---

## Phase 4: Trends (Week 4)

**Goal:** Build Trends page data generation and endpoints.

### 4.1 Who's Hot/Cold Endpoint

**Endpoint:** `GET /v1/trends/whos-hot`

**Data Source:** `nba_analytics.player_current_form`

**Query:**
```sql
SELECT
  player_lookup,
  heat_score,
  temperature,
  streak_direction,
  streak_count,
  hit_rate_l10,
  avg_margin_l10
FROM nba_analytics.player_current_form
WHERE computed_date = (SELECT MAX(computed_date) FROM nba_analytics.player_current_form)
ORDER BY heat_score DESC
LIMIT 10;  -- Hot players

-- Cold players: ORDER BY heat_score ASC
```

**Deliverables:**
- [ ] Endpoint implementation
- [ ] Time period filtering (7d, 14d, 30d, season)
- [ ] "Playing tonight" enrichment

### 4.2 Bounce-Back Watch Endpoint

**Endpoint:** `GET /v1/trends/bounce-back`

**Data Source:** `nba_analytics.bounce_back_candidates`

**Deliverables:**
- [ ] Endpoint implementation
- [ ] Tonight's games enrichment
- [ ] Signal strength filtering

### 4.3 What Matters Most Endpoint

**Endpoint:** `GET /v1/trends/what-matters`

**Requires:** Archetype-based aggregations

**Deliverables:**
- [ ] Rest impact by archetype query
- [ ] Home/away impact by archetype query
- [ ] B2B impact by archetype query
- [ ] Endpoint implementation

### 4.4 Team Tendencies Endpoint

**Endpoint:** `GET /v1/trends/team-tendencies`

**Data Sources:**
- `team_offense_game_summary` (pace)
- `team_defense_zone_analysis` (defense by zone)

**Deliverables:**
- [ ] Pace kings/grinders query
- [ ] Defense by shot profile queries
- [ ] B2B vulnerability query
- [ ] Endpoint implementation

---

## Phase 5: Polish (Week 5+)

### 5.1 Caching Implementation

**Strategy:**

| Data | Cache | TTL |
|------|-------|-----|
| Historical game reports | Redis/CDN | 24 hours |
| Today's pre-game data | Redis | 5 minutes |
| Season aggregates | Redis | 6 hours |
| Trends data | Firestore | Until refresh |

**Deliverables:**
- [ ] Redis integration
- [ ] Cache invalidation logic
- [ ] CDN configuration for static data

### 5.2 Monitoring & Alerting

**Metrics:**
- API response times (p50, p95, p99)
- BigQuery query costs
- Cache hit rates
- Prediction result update success rate
- Data freshness checks

**Alerts:**
- Prediction result updater failures
- API error rate > 1%
- Response time p95 > 2s
- Stale data (>24h since last refresh)

**Deliverables:**
- [ ] Cloud Monitoring dashboards
- [ ] PagerDuty/Slack integration
- [ ] Health check endpoints

### 5.3 Performance Optimization

**Query Optimization:**
- Materialized views for expensive aggregations
- Query caching at BigQuery level
- Partition pruning validation

**API Optimization:**
- Connection pooling for BigQuery
- Async query execution
- Response compression

**Deliverables:**
- [ ] Query performance audit
- [ ] Materialized view candidates
- [ ] Load testing results

### 5.4 Documentation

**Deliverables:**
- [ ] API documentation (OpenAPI/Swagger)
- [ ] Integration guide for frontend
- [ ] Runbook for operations
- [ ] Architecture diagrams

---

## Dependencies Graph

```
Phase 1.1 (Prediction Results Schema)
    └── Phase 1.2 (Result Updater Job)
            └── Phase 3.2 (Game Report - includes prediction track record)
                    └── Phase 5.1 (Caching)

Phase 1.3 (Days Rest View)
    └── Phase 2.1 (Archetypes - uses rest data)
            ├── Phase 2.3 (Heat Score)
            │       └── Phase 4.1 (Who's Hot/Cold)
            └── Phase 3.2 (Game Report - uses archetype)

Phase 2.2 (Shot Profiles)
    └── Phase 3.2 (Game Report - uses shot profile)
            └── Phase 4.4 (Team Tendencies - defense vs profile)

Phase 2.4 (Bounce-Back)
    └── Phase 4.2 (Bounce-Back Watch)
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| BigQuery costs spike | Implement query budgets, use cached views |
| Prediction result updates fail | Retry logic, manual backfill capability |
| API performance issues | Aggressive caching, async queries |
| Data staleness | Monitoring alerts, automatic refresh |
| Archetype classification errors | Confidence scores, manual override capability |

---

## Success Criteria

### Phase 1 Complete When:
- [ ] Predictions table has result columns
- [ ] Result updater runs successfully for 3 consecutive game nights
- [ ] Days rest view returns accurate data

### Phase 2 Complete When:
- [ ] Archetype classification covers 95%+ of active players
- [ ] Heat scores calculated for all players with props
- [ ] Bounce-back detection matches manual review

### Phase 3 Complete When:
- [ ] Game Report endpoint returns valid data for any player/date
- [ ] Season endpoint returns valid data
- [ ] Response times < 1s (uncached), < 200ms (cached)

### Phase 4 Complete When:
- [ ] All 5 Trends sections have working endpoints
- [ ] Data refreshes on schedule
- [ ] Frontend successfully consumes all endpoints

### Phase 5 Complete When:
- [ ] 95%+ cache hit rate for historical data
- [ ] Monitoring dashboards operational
- [ ] Documentation complete
