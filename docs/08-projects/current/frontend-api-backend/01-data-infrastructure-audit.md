# Data Infrastructure Audit

**Created:** December 17, 2024
**Last Updated:** December 17, 2024
**Purpose:** Complete inventory of what exists vs what needs to be built

---

## Executive Summary

The NBA Props Platform has **excellent data infrastructure** for the frontend requirements. All core BigQuery tables exist with comprehensive schemas, including a complete prediction grading system.

### Key Discovery: Prediction Tracking Infrastructure EXISTS

During this audit, we discovered that **Phase 5B prediction grading is already built** but **not running**:

| Component | Schema | Code | Data |
|-----------|--------|------|------|
| `prediction_accuracy` | :white_check_mark: | :white_check_mark: | :x: **EMPTY** |
| `system_daily_performance` | :white_check_mark: | :white_check_mark: | :x: **EMPTY** |
| `PredictionAccuracyProcessor` | N/A | :white_check_mark: | N/A |
| Phase 6 Exporters | N/A | :white_check_mark: | N/A |

### Actual Gaps

1. **Prediction Grading Not Running** - Jobs exist but aren't scheduled/executing
2. **No API Layer** - This repo is data pipelines only; REST endpoints don't exist
3. **No Multi-Dimensional Summaries** - Need player/archetype/situation aggregates
4. **Derived Computations** - Archetypes, heat scores partially built but need verification

**Estimated effort to production-ready API:** 2-3 weeks (reduced due to existing infrastructure).

---

## Table of Contents

1. [Data Sources - What Exists](#1-data-sources---what-exists)
2. [Data Sources - Gap Analysis](#2-data-sources---gap-analysis)
3. [Derived Computations Needed](#3-derived-computations-needed)
4. [API Layer Requirements](#4-api-layer-requirements)
5. [Background Jobs Needed](#5-background-jobs-needed)
6. [Field-by-Field Mapping](#6-field-by-field-mapping)
7. [Future Considerations](#7-future-considerations)

---

## 1. Data Sources - What Exists

### 1.1 Player Game Summary (PRIMARY)

**Table:** `nba_analytics.player_game_summary`
**Schema:** 79 fields
**Status:** :white_check_mark: Production Ready

This is the **workhorse table** for most frontend data needs.

| Category | Fields Available | Notes |
|----------|------------------|-------|
| **Identifiers** | player_lookup, universal_player_id, game_id, game_date, team_abbr, opponent_team_abbr, season_year | All core identifiers present |
| **Basic Stats** | points, assists, rebounds (off/def), steals, blocks, turnovers, minutes_played, personal_fouls | Complete box score data |
| **Shooting** | fg_makes/attempts, three_pt_makes/attempts, ft_makes/attempts | Standard shooting splits |
| **Shot Zones** | paint_makes/attempts, mid_range_makes/attempts, three_pt blocks by zone | From Big Ball Data or estimated |
| **Advanced** | ts_pct, efg_pct, usage_rate (partial), plus_minus | Efficiency metrics |
| **Prop Betting** | points_line, opening_line, line_movement, over_under_result, margin | Historical prop performance |
| **Game Context** | starter_flag, win_flag, is_active, player_status | Game participation data |
| **Data Quality** | 24 source tracking fields, data_quality_tier, shot_zones_estimated | Comprehensive quality metadata |

**What This Enables:**
- Season averages calculation
- Recent game logs (L5, L10, L20)
- Moving averages
- Hit rate calculations
- Home/away splits
- Win/loss splits
- Margin analysis
- Streak detection

**Coverage:**
- 2021-22 season onwards
- ~500k+ player-game records
- 60-70% have prop lines (star players)
- 85%+ have actual shot zones (vs estimated)

---

### 1.2 BettingPros Player Props

**Table:** `nba_raw.bettingpros_player_points_props`
**Schema:** 27 fields
**Status:** :white_check_mark: Production Ready

| Field | Purpose |
|-------|---------|
| player_lookup | Join key |
| points_line | Current/closing line |
| opening_line | Opening line |
| opening_timestamp | When opening line was set |
| odds_american | Betting odds |
| bookmaker | Sportsbook source |
| is_best_line | Best available line flag |
| validated_team | Team validation |

**What This Enables:**
- Line movement tracking
- Opening vs closing analysis
- Multi-bookmaker comparison
- Historical line trends

**Coverage:**
- 2.2M+ records
- 2021 season onwards
- Points props only (assists/rebounds partial)

---

### 1.3 Player Shot Zone Analysis

**Table:** `nba_precompute.player_shot_zone_analysis`
**Schema:** 45 fields
**Status:** :white_check_mark: Production Ready

| Category | Fields |
|----------|--------|
| **Shot Distribution (L10)** | paint_rate_last_10, mid_range_rate_last_10, three_pt_rate_last_10 |
| **Shot Distribution (L20)** | paint_rate_last_20, mid_range_rate_last_20, three_pt_rate_last_20 |
| **Efficiency** | paint_pct, mid_range_pct, three_pt_pct |
| **Volume** | paint_attempts_per_game, mid_range_attempts_per_game, three_pt_attempts_per_game |
| **Creation** | assisted_rate, unassisted_rate |
| **Classification** | primary_scoring_zone, position |

**What This Enables:**
- Shot profile classification (interior/perimeter/mid_range/balanced)
- Matchup-based analysis
- Style-based comparisons

**Update Frequency:** Nightly at 11:15 PM ET

---

### 1.4 Team Defense Zone Analysis

**Table:** `nba_precompute.team_defense_zone_analysis`
**Schema:** 48 fields
**Status:** :white_check_mark: Production Ready

| Category | Fields |
|----------|--------|
| **Paint Defense** | paint_pct_allowed_last_15, paint_attempts_allowed, paint_points_allowed, paint_blocks |
| **Mid-Range Defense** | mid_range_pct_allowed_last_15, mid_range_attempts_allowed |
| **3PT Defense** | three_pt_pct_allowed_last_15, three_pt_attempts_allowed |
| **Overall** | defensive_rating, opponent_ppg, opponent_pace |
| **Rankings** | strongest_zone, weakest_zone |

**What This Enables:**
- Defense vs shot profile matchup analysis
- Identifying favorable/unfavorable matchups
- Team defense rankings

**Update Frequency:** Nightly at 11:00 PM ET

---

### 1.5 Team Offense Game Summary

**Table:** `nba_analytics.team_offense_game_summary`
**Schema:** 49 fields
**Status:** :white_check_mark: Production Ready

**Critical Field:** `pace` (possessions per 48 minutes)

| Category | Fields |
|----------|--------|
| **Pace** | pace, possessions |
| **Scoring** | points_scored, offensive_rating |
| **Shooting** | team fg/3pt/ft metrics |
| **Context** | home_game, win_flag, margin_of_victory, overtime_periods |

**What This Enables:**
- Pace-based game projections
- Fast/slow team identification
- Game environment context

---

### 1.6 NBA Players Registry

**Table:** `nba_reference.nba_players_registry`
**Schema:** 26 fields
**Status:** :white_check_mark: Production Ready

| Category | Fields |
|----------|--------|
| **Identity** | universal_player_id, player_name, player_lookup, team_abbr, season |
| **Game Participation** | first_game_date, last_game_date, games_played |
| **Roster Info** | jersey_number, position |
| **Quality** | source_priority, confidence_score |

**Critical for Frontend:**
- `first_game_date` enables years-in-league calculation
- `games_played` for experience metrics

**Limitation:**
- Data is per-season, so cross-season years calculation requires joining multiple seasons

---

### 1.7 Player Prop Predictions

**Table:** `nba_predictions.player_prop_predictions`
**Schema:** 65+ fields
**Status:** :white_check_mark: Production Ready

**What Exists:**

| Category | Fields | Notes |
|----------|--------|-------|
| **Core Prediction** | prediction_id, predicted_points, confidence_score, recommendation | All present |
| **Components** | fatigue_adjustment, pace_adjustment, shot_zone_adjustment, etc. | 9 adjustment factors |
| **Metadata** | similar_games_count, current_points_line, line_margin | Context available |
| **Multi-System** | prediction_variance, system_agreement_score, contributing_systems | Consensus metrics |
| **Quality** | completeness_percentage, is_production_ready, data_quality_issues | Data quality tracking |

**Note:** Result tracking is handled by the separate `prediction_accuracy` table (see Section 1.9).

---

### 1.8 NBA Schedule

**Table:** `nba_raw.nbac_schedule`
**Schema:** 42 fields
**Status:** :white_check_mark: Production Ready

| Category | Fields |
|----------|--------|
| **Core** | game_id, game_date, game_status, game_time |
| **Teams** | home_team_tricode, away_team_tricode, home_team_name, away_team_name |
| **Venue** | arena_name, arena_city, arena_timezone |
| **Context** | is_primetime, has_national_tv, day_of_week, is_weekend |
| **Type** | is_regular_season, is_playoffs, is_christmas |
| **Results** | home_team_score, away_team_score, winning_team_tricode |

**What This Enables:**
- Days rest calculation (DATE_DIFF between games)
- Back-to-back detection
- Opponent B2B detection
- National TV game identification

---

### 1.9 Prediction Accuracy (GRADING - KEY DISCOVERY)

**Table:** `nba_predictions.prediction_accuracy`
**Schema:** 20+ fields
**Status:** :yellow_circle: Schema exists, **DATA EMPTY**
**Location:** `schemas/bigquery/nba_predictions/prediction_accuracy.sql`

This table grades predictions against actual results. **The infrastructure is fully built but not running.**

| Category | Fields | Notes |
|----------|--------|-------|
| **Keys** | player_lookup, game_id, game_date, system_id | Per-prediction grading |
| **Prediction Snapshot** | predicted_points, confidence_score, recommendation, line_value | What we predicted |
| **Actual Result** | actual_points, minutes_played | What happened |
| **Accuracy Metrics** | absolute_error, signed_error, prediction_correct | Core grading |
| **Margin Analysis** | predicted_margin, actual_margin | Betting evaluation |
| **Thresholds** | within_3_points, within_5_points | Precision metrics |
| **Context** | team_abbr, opponent_team_abbr, confidence_decile | For analysis |

**Processor:** `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`
**Backfill:** `backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py`

**CRITICAL:** This table is EMPTY. Run the backfill to populate historical data.

---

### 1.10 System Daily Performance (AGGREGATES)

**Table:** `nba_predictions.system_daily_performance`
**Schema:** 25+ fields
**Status:** :yellow_circle: Schema exists, **DATA EMPTY**
**Location:** `schemas/bigquery/nba_predictions/system_daily_performance.sql`

Pre-aggregates prediction_accuracy by system and date.

| Category | Fields |
|----------|--------|
| **Keys** | game_date, system_id |
| **Volume** | predictions_count, recommendations_count, correct_count, pass_count |
| **Accuracy** | win_rate, mae, avg_bias |
| **OVER/UNDER** | over_count, over_correct, over_win_rate, under_count, under_correct |
| **Thresholds** | within_3_count, within_3_pct, within_5_count, within_5_pct |
| **Confidence** | avg_confidence, high_confidence_count, high_confidence_win_rate |

**Populated by:** Same job that populates prediction_accuracy

---

### 1.11 Prediction Performance Summary (NEW - TO BE CREATED)

**Table:** `nba_predictions.prediction_performance_summary`
**Schema:** See `schemas/bigquery/nba_predictions/prediction_performance_summary.sql`
**Status:** :red_circle: New table needed
**Purpose:** Multi-dimensional aggregates for fast API access

This table aggregates by dimensions that `system_daily_performance` doesn't cover:

| Dimension | Purpose |
|-----------|---------|
| `player_lookup` | "Our track record on LeBron" |
| `archetype` | "75% on veteran stars" |
| `confidence_tier` | "High confidence picks hit 72%" |
| `situation` | "Great on bounce-back candidates" |

**Processor:** `data_processors/grading/performance_summary/performance_summary_processor.py`

---

## 2. Data Sources - Gap Analysis

### 2.1 Critical Gaps (Blockers)

| Gap | Impact | Resolution |
|-----|--------|------------|
| **Prediction Grading Not Running** | Cannot show track record | Run backfill + schedule job |
| **No API Layer** | Cannot serve data to frontend | Build FastAPI service |
| **No Multi-Dimensional Summaries** | Slow queries for player/archetype aggregates | Create `prediction_performance_summary` |

### 2.2 Important Gaps (Degrade Experience)

| Gap | Impact | Resolution |
|-----|--------|------------|
| **No Heat Score** | Cannot show player temperature | Implement algorithm |
| **No Bounce-Back Detection** | Missing prediction angle | Implement detection logic |
| **No H2H Precompute** | Slow API response | Create materialized view |
| **No Rest/B2B Fields** | Extra computation per request | Add to schedule or game context |

### 2.3 Nice-to-Have Gaps (Future Enhancement)

| Gap | Impact | Resolution |
|-----|--------|------------|
| **No Ironman Detection** | Incomplete archetype coverage | Complex analysis needed |
| **No Game Context Factors** | Missing foul trouble, blowout detection | Parse play-by-play |
| **No Real-time Props** | Stale lines during games | Live API integration |

### 2.4 Prediction Tracking Architecture (IMPORTANT)

The prediction tracking system has three layers:

```
┌─────────────────────────────────────────┐
│  player_prop_predictions                │  Phase 5A - Raw predictions
│  (predictions made before games)        │  STATUS: Has data
└─────────────────────────────────────────┘
                    │
                    │ PredictionAccuracyProcessor (runs after games)
                    ▼
┌─────────────────────────────────────────┐
│  prediction_accuracy                    │  Phase 5B - Graded results
│  (individual hit/miss tracking)         │  STATUS: EMPTY - needs backfill
└─────────────────────────────────────────┘
                    │
          ┌────────┴────────┐
          ▼                 ▼
┌──────────────────┐  ┌──────────────────────────┐
│ system_daily_    │  │ prediction_performance_  │
│ performance      │  │ summary                  │  NEW
│ (by system+date) │  │ (by player/archetype/    │
│ STATUS: EMPTY    │  │  situation/confidence)   │
└──────────────────┘  └──────────────────────────┘
                                  │
                                  ▼
                      ┌──────────────────────────┐
                      │  Phase 6 JSON Exporters  │  STATUS: Code exists
                      │  (results_exporter,      │  but no data to export
                      │   system_performance)    │
                      └──────────────────────────┘
```

**Key Insight:** The schema and code exist. Only the data is missing because the grading job hasn't been running.

---

## 3. Derived Computations Needed

### 3.1 Archetype Classification

**Algorithm (from frontend spec):**

```sql
CASE
  WHEN years_in_league >= 10 AND usage_rate >= 0.25 AND ppg >= 20 THEN 'veteran_star'
  WHEN years_in_league BETWEEN 5 AND 9 AND usage_rate >= 0.28 AND ppg >= 22 THEN 'prime_star'
  WHEN years_in_league < 5 AND usage_rate >= 0.22 AND ppg >= 18 THEN 'young_star'
  WHEN ABS(rest_3plus_avg - rest_normal_avg) < 1.5 THEN 'ironman'
  ELSE 'role_player'
END as archetype
```

**Data Sources Required:**
- `years_in_league`: Cross-season join of `nba_players_registry.first_game_date`
- `usage_rate`: `player_game_summary.usage_rate` (L30 average)
- `ppg`: `player_game_summary.points` (season average)
- `rest_3plus_avg` / `rest_normal_avg`: Computed from game logs with rest days

**Implementation Options:**

| Option | Pros | Cons |
|--------|------|------|
| **BigQuery View** | Always fresh | Query cost on every API call |
| **Scheduled Materialized View** | Fast reads, fresh enough | Extra maintenance |
| **Precompute Table (Daily)** | Very fast reads | Could be stale for mid-day trades |

**Recommendation:** Scheduled materialized view, refreshed at 6 AM ET daily.

---

### 3.2 Shot Profile Classification

**Algorithm (from frontend spec):**

```sql
CASE
  WHEN paint_rate_last_10 >= 0.50 THEN 'interior'
  WHEN three_pt_rate_last_10 >= 0.50 THEN 'perimeter'
  WHEN mid_range_rate_last_10 >= 0.30 THEN 'mid_range'
  ELSE 'balanced'
END as shot_profile
```

**Data Source:** `nba_precompute.player_shot_zone_analysis`

**Status:** Data exists, just need to add computed column or view.

---

### 3.3 Heat Score Calculation

**Algorithm (from frontend spec):**

```
HeatScore = (0.50 x HitRateScore) + (0.25 x StreakScore) + (0.25 x MarginScore)

Where:
- HitRateScore: % of props hit in L10 (normalized 0-10)
- StreakScore: Consecutive OVER/UNDER hits (capped at 10)
- MarginScore: Average margin over line (normalized 0-10)
```

**Temperature Thresholds:**
| Heat Score | Temperature |
|------------|-------------|
| 8.0+ | hot |
| 6.5-7.9 | warm |
| 4.5-6.4 | neutral |
| 3.0-4.4 | cool |
| <3.0 | cold |

**Data Sources Required:**
- L10 hit rate: `player_game_summary` with points_line
- Streak: Sequential analysis of `over_under_result`
- Margin: `player_game_summary.margin`

**Implementation:**
```sql
WITH player_l10 AS (
  SELECT
    player_lookup,
    -- Hit rate (0-10 scale)
    (SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END) / COUNT(*)) * 10 as hit_rate_score,
    -- Margin (normalized)
    LEAST(GREATEST(AVG(margin) / 5 + 5, 0), 10) as margin_score
  FROM (
    SELECT *
    FROM nba_analytics.player_game_summary
    WHERE points_line IS NOT NULL
    ORDER BY game_date DESC
    LIMIT 10
  )
  GROUP BY player_lookup
),
streak_calc AS (
  -- Complex streak calculation (see full implementation)
)
SELECT
  player_lookup,
  (0.50 * hit_rate_score) + (0.25 * streak_score) + (0.25 * margin_score) as heat_score
FROM player_l10
JOIN streak_calc USING (player_lookup)
```

---

### 3.4 Bounce-Back Detection

**Criteria (from frontend spec):**

A player qualifies if:
1. **Single Significant Miss**: Margin >= 20% of line AND season hit rate >= 60%
2. **Multi-Game Streak**: 2+ consecutive misses OR 3+ of last 5 under
3. **Minimum Baseline**: Season hit rate >= 55%

**Exclusions:**
- Injured or questionable
- Minutes dropped >20% from season average
- Miss margin < 1.5 pts

**Signal Strength:**
- **Strong**: 3+ consecutive misses OR single miss with margin >= 40% of line
- **Moderate**: Meets qualification but not strong criteria

**Data Sources:**
- Recent games: `player_game_summary`
- Season baseline: Aggregated `player_game_summary`
- Tonight's game: `nbac_schedule`
- Injury status: Would need external source (not currently available)

---

### 3.5 Days Rest / Back-to-Back Detection

**Calculation:**

```sql
WITH player_games AS (
  SELECT
    player_lookup,
    game_date,
    LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev_game_date
  FROM nba_analytics.player_game_summary
  WHERE is_active = TRUE
)
SELECT
  player_lookup,
  game_date,
  DATE_DIFF(game_date, prev_game_date, DAY) as days_rest,
  DATE_DIFF(game_date, prev_game_date, DAY) = 1 as is_b2b
FROM player_games
```

**For Opponent B2B:**
Same calculation but for opponent_team_abbr using schedule data.

---

### 3.6 Years in League (Cross-Season)

**Challenge:** `nba_players_registry` is per-season, so finding a player's first NBA game requires:

```sql
SELECT
  player_lookup,
  MIN(first_game_date) as career_start_date,
  DATE_DIFF(CURRENT_DATE(), MIN(first_game_date), YEAR) as years_in_league
FROM nba_reference.nba_players_registry
GROUP BY player_lookup
```

**Limitation:** Only accurate for seasons we have data (2021+). For veteran players who started before 2021, we'd undercount their years.

**Options:**
1. **Accept limitation** - Undercount veterans but algorithm still works (10+ years is 10+ years)
2. **External data source** - Import career start dates from Basketball Reference
3. **Static lookup table** - Manually curate veteran player start years

**Recommendation:** Option 1 for MVP, consider Option 2 later.

---

## 4. API Layer Requirements

### 4.1 Current State

**There is NO API layer in this repository.** This codebase is:
- Data pipelines (scrapers)
- BigQuery loaders (processors)
- Scheduled jobs (Cloud Run)
- Background processing (Pub/Sub)

### 4.2 Options

| Option | Pros | Cons |
|--------|------|------|
| **Add API to this repo** | Single codebase, shared utilities | Mixing concerns, deployment complexity |
| **Separate API repo** | Clean separation, independent scaling | Code duplication, cross-repo coordination |
| **Serverless Functions** | Simple endpoints, auto-scaling | Cold starts, limited compute time |

**Recommendation:** Separate API repo (props-api) with:
- FastAPI framework
- BigQuery client for data access
- Redis/Firestore for caching
- Cloud Run deployment

### 4.3 Endpoints Needed

**Player Modal:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/player/{lookup}/game-report/{date}` | GET | Per-game deep dive |
| `/v1/player/{lookup}/season/{season}` | GET | Season aggregates |

**Trends Page:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/trends/whos-hot` | GET | Hot/cold players |
| `/v1/trends/bounce-back` | GET | Bounce-back candidates |
| `/v1/trends/what-matters` | GET | Archetype patterns |
| `/v1/trends/team-tendencies` | GET | Team analysis |
| `/v1/trends/quick-hits` | GET | Bite-sized stats |

**Predictions:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/predictions/performance` | GET | Track record aggregation |
| `POST /v1/predictions` | POST | Log new prediction (internal) |

---

## 5. Background Jobs Needed

### 5.1 Prediction Result Updater

**Purpose:** After games complete, update predictions with actual results.

**Schedule:** Every 30 minutes during game nights (7 PM - 1 AM ET)

**Logic:**
```python
# Pseudocode
for prediction in get_pending_predictions(today):
    actual = get_player_game_summary(prediction.player_lookup, prediction.game_date)
    if actual.points is not None:
        prediction.result_status = 'final'
        prediction.actual_value = actual.points
        prediction.result_hit = (
            (prediction.recommendation == 'OVER' and actual.points > prediction.current_points_line) or
            (prediction.recommendation == 'UNDER' and actual.points < prediction.current_points_line)
        )
        prediction.result_margin = actual.points - prediction.current_points_line
        update_prediction(prediction)
```

### 5.2 Daily Archetype Refresh

**Purpose:** Recompute player archetypes based on recent performance.

**Schedule:** Daily at 6 AM ET

**Output:** Update `nba_analytics.player_archetypes` table/view

### 5.3 Heat Score / Trends Exporter

**Purpose:** Generate JSON files for Trends page sections.

**Schedule:**
- Who's Hot/Cold: Daily at 6 AM ET
- Bounce-Back: Daily at 6 AM ET
- What Matters Most: Weekly Monday 6 AM ET
- Team Tendencies: Bi-weekly Monday 6 AM ET
- Quick Hits: Weekly Wednesday 8 AM ET

**Output:** Write to Firestore or GCS for CDN distribution

---

## 6. Field-by-Field Mapping

### 6.1 Game Report Response Mapping

| Frontend Field | Source | Available | Notes |
|----------------|--------|-----------|-------|
| `player_lookup` | player_game_summary | :white_check_mark: | Direct |
| `player_full_name` | player_game_summary | :white_check_mark: | Direct |
| `team_abbr` | player_game_summary | :white_check_mark: | Direct |
| `game_date` | player_game_summary | :white_check_mark: | Direct |
| `game_status` | nbac_schedule | :white_check_mark: | Join |
| `game_info.opponent` | player_game_summary.opponent_team_abbr | :white_check_mark: | Direct |
| `game_info.home` | Derived from game_id | :white_check_mark: | Parse game_id |
| `game_info.days_rest` | Derived | :yellow_circle: | Need to compute |
| `game_info.is_b2b` | Derived | :yellow_circle: | Need to compute |
| `player_profile.archetype` | Derived | :red_circle: | Need to build |
| `player_profile.shot_profile` | player_shot_zone_analysis | :white_check_mark: | Simple CASE |
| `player_profile.years_in_league` | nba_players_registry | :yellow_circle: | Cross-season join |
| `player_profile.usage_rate` | player_game_summary | :white_check_mark: | Aggregate |
| `player_stats.season_ppg` | player_game_summary | :white_check_mark: | Aggregate |
| `opponent_context.pace` | team_offense_game_summary | :white_check_mark: | Join |
| `opponent_context.pace_rank` | Derived | :white_check_mark: | RANK() function |
| `opponent_context.defense_rank` | team_defense_zone_analysis | :white_check_mark: | Direct |
| `opponent_context.defense_vs_player_profile` | team_defense_zone_analysis | :white_check_mark: | Join on shot profile |
| `prop_lines.current_line` | bettingpros_player_points_props | :white_check_mark: | Direct |
| `prop_lines.opening_line` | bettingpros_player_points_props | :white_check_mark: | Direct |
| `prop_lines.line_movement` | Derived or player_game_summary | :white_check_mark: | Direct |
| `moving_averages.*` | player_game_summary | :white_check_mark: | Window functions |
| `line_analysis.bounce_back_score` | Derived | :red_circle: | Need to build |
| `prediction.*` | player_prop_predictions | :white_check_mark: | Direct |
| `prediction_angles.*` | Derived from all sources | :yellow_circle: | Need logic |
| `recent_games[]` | player_game_summary | :white_check_mark: | Filter + sort |
| `games_on_same_rest[]` | player_game_summary + days_rest | :yellow_circle: | Need rest calculation |
| `head_to_head.*` | player_game_summary | :white_check_mark: | Filter by opponent |
| `result.*` | player_game_summary | :white_check_mark: | For completed games |

### 6.2 Season Response Mapping

| Frontend Field | Source | Available | Notes |
|----------------|--------|-----------|-------|
| `averages.*` | player_game_summary | :white_check_mark: | Season aggregates |
| `career_averages.*` | player_game_summary | :white_check_mark: | All-time aggregates |
| `shooting.*` | player_game_summary | :white_check_mark: | Shooting percentages |
| `current_form.heat_score` | Derived | :red_circle: | Need to build |
| `current_form.streak.*` | Derived | :yellow_circle: | Sequential analysis |
| `current_form.last_10.*` | player_game_summary | :white_check_mark: | L10 filter |
| `key_patterns[]` | Derived | :yellow_circle: | Need pattern detection |
| `prop_hit_rates.*` | player_game_summary | :white_check_mark: | Aggregates |
| `game_log[]` | player_game_summary | :white_check_mark: | Direct |
| `splits.by_rest[]` | player_game_summary + rest | :yellow_circle: | Need rest calculation |
| `splits.by_location[]` | player_game_summary | :white_check_mark: | Home/away filter |
| `splits.by_month[]` | player_game_summary | :white_check_mark: | Date extraction |
| `monthly_chart_data[]` | player_game_summary | :white_check_mark: | GROUP BY month |

---

## 7. Future Considerations

### 7.1 Premium Gating

The frontend spec includes premium tiers. Backend implications:

| Feature | Free | Pro | Elite | Backend Impact |
|---------|------|-----|-------|----------------|
| Overall hit rate | :white_check_mark: | :white_check_mark: | :white_check_mark: | None |
| Confidence tier breakdown | :x: | :white_check_mark: | :white_check_mark: | Add tier filtering |
| Player-specific track record | :x: | :white_check_mark: | :white_check_mark: | No change |
| Full prediction log | :x: | :x: | :white_check_mark: | Add pagination |
| Export/API access | :x: | :x: | :white_check_mark: | Rate limiting, auth |

**Backend Requirements:**
- User authentication (JWT/OAuth)
- Subscription tier storage
- Endpoint authorization middleware
- Rate limiting by tier

### 7.2 Real-Time Updates

**Current State:** All data is batch-processed (post-game).

**Future State:** Live prop line updates, in-game predictions.

**Requirements:**
- WebSocket infrastructure
- Real-time prop API integration
- In-game prediction system
- Caching layer with invalidation

### 7.3 Additional Prop Types

**Current:** Points props only (bettingpros_player_points_props)

**Future:** Rebounds, assists, threes, PRA, steals+blocks

**Impact:**
- New raw tables for each prop type
- Extended player_game_summary with more result fields
- Multiplied prediction volume

### 7.4 Multi-Sport Expansion

If expanding beyond NBA:

- Schema abstraction (sport-agnostic player/game)
- Separate data pipelines per sport
- Unified API with sport parameter

### 7.5 Caching Strategy

**Recommended Cache Layers:**

| Data Type | Cache Duration | Storage |
|-----------|----------------|---------|
| Historical games | 24 hours | CDN/Redis |
| Today's games (pre-tip) | 5 minutes | Redis |
| Live games | 30 seconds | Redis |
| Season aggregates | 6 hours | Redis |
| Trends data | Until refresh | Firestore |

### 7.6 Performance Considerations

**BigQuery Costs:**
- Partition by game_date on all tables (already done)
- Cluster by common query patterns (already done)
- Use materialized views for expensive aggregations
- Cache frequently-accessed data

**API Response Times:**
- Target: <200ms for cached data, <1s for fresh queries
- Use async queries for complex aggregations
- Implement cursor-based pagination

### 7.7 Data Quality Monitoring

**Alerts to Implement:**
- Prediction result update failures
- Missing prop lines for star players
- Stale archetype classifications
- Heat score calculation errors
- Schedule data gaps (B2B detection breaks)

---

## Appendix A: Table Schemas Quick Reference

### player_game_summary (79 fields)
```
Core: player_lookup, universal_player_id, game_id, game_date, team_abbr, opponent_team_abbr, season_year
Stats: points, assists, rebounds (off/def), steals, blocks, turnovers, minutes_played, personal_fouls
Shooting: fg_makes/attempts, three_pt_makes/attempts, ft_makes/attempts
Shot Zones: paint_makes/attempts, mid_range_makes/attempts
Advanced: ts_pct, efg_pct, usage_rate, plus_minus
Props: points_line, opening_line, line_movement, over_under_result, margin
Quality: 24 source tracking fields, data_quality_tier
```

### player_prop_predictions (65+ fields)
```
Core: prediction_id, system_id, player_lookup, game_date, game_id
Prediction: predicted_points, confidence_score, recommendation
Adjustments: fatigue, pace, shot_zone, referee, look_ahead, usage_spike, home_away
Meta: similar_games_count, current_points_line, line_margin
Multi-system: prediction_variance, system_agreement_score
Quality: completeness_percentage, is_production_ready
MISSING: result_status, actual_value, result_hit, result_margin, result_updated_at
```

### player_shot_zone_analysis (45 fields)
```
Distribution: paint_rate, mid_range_rate, three_pt_rate (L10 and L20)
Efficiency: paint_pct, mid_range_pct, three_pt_pct
Volume: attempts_per_game by zone
Creation: assisted_rate, unassisted_rate
Classification: primary_scoring_zone
```

### team_defense_zone_analysis (48 fields)
```
Paint: pct_allowed, attempts_allowed, points_allowed, blocks
Mid-Range: pct_allowed, attempts_allowed
Three-Point: pct_allowed, attempts_allowed
Overall: defensive_rating, opponent_ppg
Rankings: strongest_zone, weakest_zone
```

---

## Appendix B: Cross-Reference to Frontend Specs

| Frontend Spec Section | Backend Data Status |
|-----------------------|---------------------|
| Game Report Data (lines 98-684) | 85% available, 15% need computation |
| Season Data (lines 688-1077) | 90% available, 10% need computation |
| Prediction Performance (lines 1138-1555) | 70% available, need result tracking |
| Shared Data Definitions (lines 35-95) | Need implementation |
| Trends - Who's Hot/Cold | Need heat score implementation |
| Trends - Bounce-Back | Need detection logic |
| Trends - What Matters Most | Need archetype classification |
| Trends - Team Tendencies | 95% available |
| Trends - Quick Hits | Need ad-hoc queries |
