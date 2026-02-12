# New Features Deep Dive — Implementation Designs

**Date:** 2026-02-12
**Sessions:** 222-224 (planning)
**Status:** Research complete, implementation-ready designs
**Related:** `02-MASTER-EXPERIMENT-PLAN.md`, `04-MULTI-SEASON-DATA-AUDIT.md`

---

## Overview

This document contains **implementation-ready designs** for 16 new ML features, organized by the failure mode they address. Each feature includes:
- Exact data source and field names
- SQL/Python implementation
- Files to modify
- Effort estimate
- Expected signal strength

### Feature Index Map (Proposed V10-V12)

| Index | Feature | Group | Status |
|-------|---------|-------|--------|
| 0-32 | V9 production features | Current | ACTIVE |
| 33 | `dnp_rate` | V10 | Computed, unused |
| 34 | `pts_slope_10g` | V10 | Computed, unused |
| 35 | `pts_vs_season_zscore` | V10 | Computed, unused |
| 36 | `breakout_flag` | V10 | Computed, unused |
| 37 | `star_teammates_out` | V11 - Injury | Already in Phase 3 |
| 38 | `teammate_ppg_missing` | V11 - Injury | Needs computation |
| 39 | `opponent_star_out` | V11 - Injury | Needs computation |
| 40 | `fg_pct_last_3` | V11 - Shooting | Trivial to add |
| 41 | `ts_pct_last_5` | V11 - Shooting | Trivial to add |
| 42 | `opponent_b2b` | V11 - Context | One-line addition |
| 43 | `game_total_line` | V11 - Context | Data exists, extract |
| 44 | `days_since_2day_rest` | V11 - Context | Already in Phase 3 |
| 45 | `scoring_cv_season` | V11 - Profile | Simple calculation |
| 46 | `minutes_cv_last_10` | V11 - Profile | Needs minutes_std |
| 47 | `player_age` | V11 - Profile | Already in Phase 3 |
| 48 | `career_games_estimate` | V11 - Profile | Join to BR rosters |
| 49 | `ref_crew_avg_total_pts` | V12 - Referee | Pipeline exists, processor missing |
| 50 | `ref_crew_foul_rate` | V12 - Referee | Same as above |
| 51 | `game_spread` | V12 - Lines | Data exists |
| 52 | `game_total_movement` | V12 - Lines | Snapshot diff |

---

## Part 1: V10 Activation (Features 33-36)

### Status: ALREADY COMPUTED — Just Not Used

All four features are populated at **96-100% coverage** across 3 seasons. The only change needed is extending the model's feature slice.

### Code Change

**File:** `ml/experiments/quick_retrain.py`

```python
# CURRENT (line ~1180):
X_train = np.array([row[:33] for row in features])

# CHANGE TO:
feature_count = args.feature_count if hasattr(args, 'feature_count') else 33
X_train = np.array([row[:feature_count] for row in features])
```

Add argparse option:
```python
parser.add_argument('--feature-count', type=int, default=33,
                    help='Number of features to use (33=V9, 37=V10)')
```

### Feature Details

#### Feature 33: `dnp_rate`
- **What:** Did-Not-Play frequency over last 10 games
- **Signal:** Load management risk. High DNP rate = unreliable minutes
- **Range:** 0.0-1.0 (0 = never DNPs, 0.5 = DNPs half the games)
- **Source:** Gamebook analysis in `player_daily_cache`
- **Expected importance:** LOW — secondary signal for bench/role players

#### Feature 34: `pts_slope_10g`
- **What:** Linear regression slope of points over last 10 games
- **Signal:** Hot/cold streak momentum. Positive slope = trending up
- **Range:** -5.0 to +5.0 (points per game trend)
- **Source:** Calculated from `player_daily_cache` rolling data
- **Expected importance:** **HIGH** — directly addresses "model doesn't see trends" failure
- **Example:** Player going 15, 18, 20, 22, 25 → slope ~+2.5. Model currently treats this as "averaging 20" but misses the upward trajectory.

#### Feature 35: `pts_vs_season_zscore`
- **What:** Z-score of last-5 average vs season average
- **Signal:** Role change detection. High z-score = performing well above baseline
- **Range:** -3.0 to +3.0 (standard deviations from season mean)
- **Source:** Calculated: `(points_avg_last_5 - points_avg_season) / points_std_season`
- **Expected importance:** **HIGH** — catches mid-season breakouts (Trey Murphy type)
- **Example:** Player averaging 12 PPG season but 18 PPG last 5 games → z-score +1.5. Signals expanded role.

#### Feature 36: `breakout_flag`
- **What:** Binary: 1.0 if last-5 avg > season_avg + 1.5 * std
- **Signal:** Binary version of z-score. Easier for tree to split on.
- **Range:** 0 or 1
- **Source:** Derived from features 0, 2, 3
- **Expected importance:** MEDIUM — redundant with feature 35 but provides a clean split point

---

## Part 2: Injury Context Features (Group A)

### Failure Mode Addressed

**Role Player UNDER collapse (22% HR).** When a star teammate is injured, role players see +3-8 PPG usage boosts. The model predicts UNDER based on historical average, but the player goes OVER because of increased opportunity.

### Feature 37: `star_teammates_out` (ALREADY COMPUTED)

**Data source:** `nba_analytics.upcoming_player_game_context.star_teammates_out`

**Current computation** (in `data_processors/analytics/upcoming_player_game_context/team_context.py`):

```python
# Star criteria (dynamic, not hardcoded):
# - Last 10 games average >= 18 PPG, OR
# - Last 10 games average >= 28 MPG, OR
# - Last 10 games usage rate >= 25%
# Status filter: 'out' or 'doubtful'
```

**What to do:** Extract from Phase 3 into feature store. Zero new computation needed.

**Files to modify:**
1. `data_processors/precompute/ml_feature_store/feature_extractor.py` — add extraction from `upcoming_player_game_context`
2. `shared/ml/feature_contract.py` — add to `FEATURE_STORE_NAMES`
3. `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` — include in feature vector

**Extraction query:**
```sql
SELECT player_lookup, game_date, star_teammates_out
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = @target_date
```

**Effort:** LOW (1-2 hours)

### Feature 38: `teammate_ppg_missing` (NEEDS COMPUTATION)

**What:** Sum of PPG (last 10 games average) of all OUT teammates who meet star criteria.

**Data sources:**
- `nba_raw.nbac_injury_report` — who is OUT (`player_lookup`, `injury_status`, `team`, `game_date`)
- `nba_analytics.player_game_summary` — their PPG

**Implementation:**

```sql
WITH team_star_ppg AS (
  SELECT
    ir.game_date,
    ir.team as team_abbr,
    ir.player_lookup as injured_player,
    AVG(pgs.points) as injured_player_ppg
  FROM nba_raw.nbac_injury_report ir
  JOIN nba_analytics.player_game_summary pgs
    ON ir.player_lookup = pgs.player_lookup
    AND pgs.game_date >= DATE_SUB(ir.game_date, INTERVAL 30 DAY)
    AND pgs.game_date < ir.game_date
  WHERE ir.injury_status IN ('out', 'doubtful')
    AND ir.game_date = @target_date
  GROUP BY 1, 2, 3
  HAVING AVG(pgs.points) >= 18  -- Star threshold
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY ir.player_lookup, ir.game_date
    ORDER BY ir.report_hour DESC
  ) = 1  -- Latest report
)
SELECT
  team_abbr,
  game_date,
  ROUND(SUM(injured_player_ppg), 1) as teammate_ppg_missing
FROM team_star_ppg
GROUP BY 1, 2
```

**Range:** 0-50 (0 = full team, 25 = one star out, 50 = multiple stars out)

**Files to modify:**
1. Create: `data_processors/precompute/ml_feature_store/injury_context_features.py`
2. Modify: `feature_extractor.py` — call new module
3. Modify: `feature_contract.py` — add feature
4. Modify: `ml_feature_store_processor.py` — include in vector

**Effort:** MEDIUM (4-6 hours)

### Feature 39: `opponent_star_out` (NEEDS COMPUTATION)

**What:** Count of opponent's star players who are OUT (same star criteria).

**Why it matters differently than `star_teammates_out`:** Opponent missing a star means WEAKER defense → player's team scores MORE → OVER becomes more likely. This is the offensive counterpart.

**Implementation:** Same query pattern as Feature 38 but filtered by opponent team.

**Effort:** MEDIUM (2-3 hours, reuses Feature 38 code)

---

## Part 3: Shooting Efficiency Features (Group B)

### Failure Mode Addressed

**Streak blindness.** The model uses `points_avg_last_5/10` but doesn't see shooting efficiency. A player averaging 20 PPG on 55% shooting (hot) vs 20 PPG on 38% shooting (cold, high volume) are treated identically.

### Feature 40: `fg_pct_last_3`

**Data source:** `nba_analytics.player_game_summary` — fields `fg_makes`, `fg_attempts` already exist.

**Current pattern (in `stats_aggregator.py`):**
```python
# Existing:
points_avg_last_5 = round(float(last_5_games['points'].mean()), 4)
points_avg_last_10 = round(float(last_10_games['points'].mean()), 4)

# ADD:
last_3_games = played_games.head(3)
fg_pct_last_3 = None
if len(last_3_games) >= 3:
    total_fgm = last_3_games['fg_makes'].sum()
    total_fga = last_3_games['fg_attempts'].sum()
    if total_fga > 0:
        fg_pct_last_3 = round(float(total_fgm / total_fga), 4)
```

**Range:** 0.0-1.0 (typical: 0.35-0.55)

**Why last 3 (not 5 or 10):** Shooting streaks are short-lived. A 3-game window is more reactive to hot/cold streaks than the existing 5/10 game averages.

**Files to modify:**
1. `data_processors/precompute/player_daily_cache/aggregators/stats_aggregator.py` — add calculation
2. `schemas/bigquery/precompute/player_daily_cache.sql` — add column
3. `feature_extractor.py` — extract from cache
4. `feature_contract.py` — add feature

**Effort:** LOW (2-3 hours)

### Feature 41: `ts_pct_last_5`

**Data source:** `nba_analytics.player_game_summary.ts_pct` — **already computed per game.**

**Formula (already in Phase 3):**
```python
ts_pct = points / (2 * (field_goals_attempted + 0.44 * free_throws_attempted))
```

**What to add:**
```python
# In stats_aggregator.py:
ts_pct_last_5 = round(float(last_5_games['ts_pct'].mean()), 4) if len(last_5_games) >= 3 else None
```

**Note:** `ts_pct_last_10` already exists in `player_daily_cache`. This adds a shorter, more reactive window.

**Range:** 0.0-1.0 (typical: 0.45-0.65)

**Files to modify:** Same as Feature 40.

**Effort:** LOW (1 hour, same change as fg_pct)

---

## Part 4: Game Context Features (Group C)

### Failure Mode Addressed

**Environment blindness.** The model knows the player's pace and opponent defense, but not the game-level context (expected tempo, opponent fatigue, cumulative rest impact).

### Feature 42: `opponent_b2b`

**Data source:** `nba_analytics.upcoming_player_game_context` — `opponent_days_rest` **already computed** in Phase 3 `schedule_context_calculator.py`.

**Implementation:**
```python
# In schedule_context_calculator.py (line ~170), add:
opponent_back_to_back = 1.0 if opponent_days_rest == 1 else 0.0
```

Or compute in feature calculator:
```python
# In feature_calculator.py:
opponent_b2b = 1.0 if phase3_data.get('opponent_days_rest') == 1 else 0.0
```

**Signal:** When opponent is on a back-to-back, they play worse defense. Historical data shows +2-4 points per player in opponent-B2B games.

**Range:** 0 or 1

**Files to modify:**
1. `feature_calculator.py` — add calculation from existing phase3 data
2. `feature_contract.py` — add feature

**Effort:** LOW (1 hour)

### Feature 43: `game_total_line`

**Data source:** `nba_raw.odds_api_game_lines` (market_key='totals')

**Coverage:** 99.52% (DraftKings), utility functions already exist.

**Implementation:**

```python
# In feature_extractor.py, add new batch extraction:
def _batch_extract_game_totals(self, game_date, game_ids):
    query = f"""
    WITH game_totals AS (
        SELECT DISTINCT
            game_id,
            FIRST_VALUE(outcome_point) OVER (
                PARTITION BY game_id
                ORDER BY
                    CASE WHEN bookmaker_key = 'draftkings' THEN 0
                         WHEN bookmaker_key = 'fanduel' THEN 1
                         ELSE 2 END,
                    snapshot_timestamp DESC
            ) as game_total_line
        FROM `nba-props-platform.nba_raw.odds_api_game_lines`
        WHERE game_date = '{game_date}'
          AND market_key = 'totals'
          AND outcome_name = 'Over'
          AND outcome_point IS NOT NULL
    )
    SELECT game_id, game_total_line
    FROM game_totals
    """
    # Populate lookup dict
```

**Existing utility (can also use):**
```python
from shared.utils.odds_preference import get_preferred_game_lines
totals = get_preferred_game_lines(game_date, market_keys=['totals'])
```

**Signal:** Game with total 230 = high-pace shootout (all players score more). Total 205 = defensive grind. This is the strongest game-level environment signal available.

**Range:** 195-245 (typical NBA game totals)

**Files to modify:**
1. `feature_extractor.py` — add `_batch_extract_game_totals()`
2. `ml_feature_store_processor.py` — include in feature vector
3. `feature_contract.py` — add feature

**Effort:** LOW-MEDIUM (3-4 hours)

### Feature 44: `days_since_2day_rest`

**Data source:** Already computed in Phase 3.

**Location:** `data_processors/analytics/upcoming_player_game_context/player_stats.py` (lines 106-115)

**Already available as:** `days_since_2_plus_days_rest` in `upcoming_player_game_context`

**What to do:** Just extract into feature store. Zero computation needed.

**Effort:** LOW (1 hour)

---

## Part 5: Player Profile Features (Group D)

### Failure Mode Addressed

**Player-type blindness.** The model treats a volatile 23-year-old and a consistent 34-year-old identically if their recent stats match. No awareness of scoring consistency, career stage, or role stability.

### Feature 45: `scoring_cv_season`

**What:** Coefficient of Variation = std(points) / mean(points). Higher = more volatile scorer.

**Data source:** Both components already exist in `player_daily_cache`:
- `points_std_last_10` (feature index 3) — standard deviation
- `points_avg_season` (feature index 2) — season mean

**Implementation:**
```python
# In feature_calculator.py or ml_feature_store_processor.py:
points_std = features[3]   # points_std_last_10
points_avg = features[2]   # points_avg_season
scoring_cv = (points_std / points_avg) * 100 if points_avg > 0 else 0.0
```

**Range:** 0-100+ (typical: 30-80. Stars ~30-40, role players ~50-80)

**Signal:** High CV players are harder to predict. The model could learn to require higher edge for high-CV players (more noise = need more signal).

**Effort:** LOW (30 minutes — pure calculation from existing features)

### Feature 46: `minutes_cv_last_10`

**What:** Coefficient of Variation for minutes played over last 10 games.

**Data source:** `minutes_avg_last_10` exists but `minutes_std_last_10` does **NOT** exist.

**Implementation:**

Step 1: Add `minutes_std_last_10` to stats aggregator:
```python
# In stats_aggregator.py, alongside existing std calculation:
minutes_std_last_10 = round(float(last_10_games['minutes_played'].std()), 4) if len(last_10_games) > 1 else None
```

Step 2: Calculate CV:
```python
minutes_cv = (minutes_std_last_10 / minutes_avg_last_10) * 100 if minutes_avg_last_10 > 0 else 0.0
```

**Range:** 0-100+ (typical: 5-30. Starters ~5-15, bench ~20-50)

**Signal:** High minutes CV = unstable role (coach rotating, foul trouble, blowout benching). Low CV = locked-in rotation spot. Players with stable minutes are more predictable.

**Files to modify:**
1. `stats_aggregator.py` — add `minutes_std_last_10` calculation
2. `player_daily_cache` schema — add column
3. `feature_calculator.py` — compute CV
4. `feature_contract.py` — add feature

**Effort:** MEDIUM (3-4 hours)

### Feature 47: `player_age`

**Data source:** Already in `nba_analytics.upcoming_player_game_context.player_age` AND `nba_precompute.player_daily_cache.player_age`.

**What to do:** Extract into feature store. Zero computation.

**Signal:** Age captures career stage:
- 19-22: Developing (trending up, high variance)
- 23-28: Prime (most stable, most predictable)
- 29-32: Maintaining (slight decline, still consistent)
- 33+: Declining (load management, minutes reduction)

**Range:** 19-42

**Effort:** LOW (1 hour)

### Feature 48: `career_games_estimate`

**Data source:** `nba_raw.br_rosters_current.experience_years` — parsed from text format (e.g., "5 years").

**Implementation:**
```python
# Estimate: 82 games/season * experience_years (adjusted for typical availability)
career_games = experience_years * 72  # 72 = ~88% availability rate
```

**Alternative:** Count actual rows in `player_game_summary` across all seasons:
```sql
SELECT player_lookup, COUNT(*) as career_games
FROM nba_analytics.player_game_summary
WHERE game_date >= '2021-10-01'
GROUP BY 1
```

This gives 4 seasons of actual game counts (2021-22 through 2024-25).

**Signal:** Experienced players are more predictable (established roles, known ceilings). Rookies/sophomores have higher variance and breakout potential.

**Range:** 0-1200+ (typical range in our data: 0-400)

**Effort:** MEDIUM (2-3 hours, needs roster join)

---

## Part 6: Referee Features (Group E) — Untapped Gold Mine

### Discovery Summary

The referee data pipeline is **90% built but 0% utilized:**

| Component | Status |
|-----------|--------|
| Scraper (`nbac_referee_assignments.py`) | Running daily |
| Raw processor | Working |
| BigQuery table (`nbac_referee_game_assignments`) | Populated, 5+ seasons |
| Pivot view (one row per game) | Built |
| Validation queries | 9 queries, all passing |
| Analytics processor | **NOT BUILT** |
| Feature integration | **`referee_adj = 0.0` HARDCODED** |
| Implementation plan | **817 lines, COMPLETE but never executed** |

**Location of implementation plan:** `docs/08-projects/current/data-source-enhancements/REFEREE-TENDENCIES-IMPLEMENTATION-PLAN.md`

### Feature 49: `ref_crew_avg_total_pts`

**What:** Average total game points in games officiated by this crew (60-day rolling window).

**Data sources:**
- `nba_raw.nbac_referee_game_assignments` — who refs which game
- `nba_raw.nbac_referee_game_pivot` — one row per game (chief + crew)
- `nba_raw.nbac_scoreboard_v2` — game results (home_score + away_score)

**Implementation:**

```sql
-- Step 1: Build referee tendencies (analytics processor)
WITH ref_games AS (
  SELECT
    r.official_code,
    r.official_name,
    r.game_date,
    s.home_score + s.away_score as total_points
  FROM nba_raw.nbac_referee_game_assignments r
  JOIN nba_raw.nbac_scoreboard_v2 s
    ON r.game_id = s.game_id AND s.game_state = 'post'
  WHERE r.game_date >= DATE_SUB(@target_date, INTERVAL 60 DAY)
    AND r.game_date < @target_date
)
SELECT
  official_code,
  COUNT(*) as games_worked,
  ROUND(AVG(total_points), 1) as avg_total_points,
  ROUND(AVG(total_points) - 220, 1) as vs_league_avg  -- 220 = approx league avg
FROM ref_games
GROUP BY official_code
HAVING COUNT(*) >= 10  -- Minimum sample

-- Step 2: For target game, get assigned crew
SELECT chief_referee_code, crew_referee_1_code, crew_referee_2_code
FROM nba_raw.nbac_referee_game_pivot
WHERE game_date = @target_date AND game_id = @game_id

-- Step 3: Weighted crew average (chief 40%, crew 60% split)
-- chief_weight = 0.4, each crew member = 0.3 (or 0.2 if 3 crew)
```

**Signal strength (from research):** 5-10 point variance between high-foul and low-foul crews. Example: Scott Foster games average -2.1 points vs league average. This directly affects player scoring totals.

**Range:** 210-230 (total points per game, varies by crew)

**Effort:** MEDIUM-HIGH (6-8 hours total):
1. Create `referee_tendencies_processor.py` (4 hours)
2. Add to feature store extraction (2 hours)
3. Backfill historical data (2 hours)

### Feature 50: `ref_crew_foul_rate`

**What:** Average personal fouls per game called by this crew.

**Data sources:** Same as Feature 49 + `nbac_gamebook_player_stats.personal_fouls`

**Implementation:**
```sql
SELECT
  r.official_code,
  AVG(game_fouls.total_fouls) as avg_fouls_per_game
FROM nba_raw.nbac_referee_game_assignments r
JOIN (
  SELECT game_id, game_date, SUM(personal_fouls) as total_fouls
  FROM nba_raw.nbac_gamebook_player_stats
  GROUP BY game_id, game_date
) game_fouls ON r.game_id = game_fouls.game_id AND r.game_date = game_fouls.game_date
WHERE r.game_date >= DATE_SUB(@target_date, INTERVAL 60 DAY)
GROUP BY r.official_code
```

**Signal:** More fouls → more free throws → more scoring opportunities. Star players with 80%+ FT rate benefit most from high-foul crews (+1-2 PPG).

**Range:** 35-55 (total fouls per game)

**Effort:** Built alongside Feature 49 (same processor).

---

## Part 7: Game Lines Features (Group F)

### Feature 51: `game_spread`

**Data source:** `nba_raw.odds_api_game_lines` (market_key='spreads')

**Implementation:** Same pattern as `game_total_line` (Feature 43) but for spreads.

```sql
SELECT game_id, outcome_point as spread
FROM nba_raw.odds_api_game_lines
WHERE game_date = @target_date
  AND market_key = 'spreads'
  AND outcome_name = @home_team  -- Spread from home team perspective
  AND bookmaker_key = 'draftkings'
ORDER BY snapshot_timestamp DESC LIMIT 1
```

**Signal:** Large spread (home team -10) = blowout expected = starters may rest Q4 = lower scoring. Close spread (-2) = competitive game = starters play full minutes.

**Range:** -15 to +15

**Effort:** LOW (1-2 hours, same extraction pattern as game_total_line)

### Feature 52: `game_total_movement`

**What:** Opening total minus closing total (positive = total went up, negative = went down).

**Data source:** Historical snapshots in `odds_api_game_lines` with `snapshot_timestamp`.

**Implementation:**
```sql
WITH ordered AS (
  SELECT game_id, outcome_point,
    ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY snapshot_timestamp ASC) as first_rn,
    ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY snapshot_timestamp DESC) as last_rn
  FROM nba_raw.odds_api_game_lines
  WHERE game_date = @target_date AND market_key = 'totals' AND outcome_name = 'Over'
    AND bookmaker_key = 'draftkings'
)
SELECT
  game_id,
  MAX(CASE WHEN last_rn = 1 THEN outcome_point END) -
  MAX(CASE WHEN first_rn = 1 THEN outcome_point END) as total_movement
FROM ordered
WHERE first_rn = 1 OR last_rn = 1
GROUP BY game_id
```

**Signal:** Total moving up (+3 points) = sharp money expects more scoring. Could indicate lineup news, injury updates, or weather (outdoor events).

**Range:** -5 to +5 (typical: -2 to +2)

**Effort:** MEDIUM (3-4 hours)

---

## Part 8: Implementation Priority Matrix

| Priority | Feature | Failure Mode | Effort | Data Ready? | Expected Impact |
|----------|---------|-------------|--------|-------------|-----------------|
| **1** | V10 activation (33-36) | Trend blindness | 1 line change | YES (96-100%) | HIGH |
| **2** | `star_teammates_out` (37) | Role UNDER collapse | Extract only | YES (Phase 3) | HIGH |
| **3** | `opponent_b2b` (42) | Context blindness | 1 calculation | YES (Phase 3) | MEDIUM |
| **4** | `game_total_line` (43) | Environment blindness | Query + extract | YES (99.5%) | MEDIUM-HIGH |
| **5** | `fg_pct_last_3` (40) | Streak blindness | 2 lines in aggregator | YES | MEDIUM |
| **6** | `ts_pct_last_5` (41) | Streak blindness | 2 lines in aggregator | YES | MEDIUM |
| **7** | `scoring_cv_season` (45) | Player-type blindness | 1 calculation | YES (derived) | MEDIUM |
| **8** | `player_age` (47) | Career-stage blindness | Extract only | YES (Phase 3) | LOW-MEDIUM |
| **9** | `days_since_2day_rest` (44) | Fatigue depth | Extract only | YES (Phase 3) | LOW-MEDIUM |
| **10** | `teammate_ppg_missing` (38) | Role UNDER collapse | New query | YES | HIGH |
| **11** | `minutes_cv_last_10` (46) | Role stability | Add std calculation | Partial | MEDIUM |
| **12** | `opponent_star_out` (39) | Matchup blindness | New query | YES | MEDIUM |
| **13** | `career_games_estimate` (48) | Experience proxy | Roster join | YES | LOW |
| **14** | `ref_crew_avg_total_pts` (49) | Ref signal (untapped) | New processor | YES | UNKNOWN |
| **15** | `ref_crew_foul_rate` (50) | Ref signal | Same processor | YES | UNKNOWN |
| **16** | `game_spread` (51) | Blowout prediction | Query + extract | YES | LOW-MEDIUM |

### Quick Wins (Features 1-9): Can be done in a SINGLE session
- All data already exists or is trivially computed
- Total new code: ~50 lines
- Total files modified: 4-5 files

### Medium Effort (Features 10-13): 1-2 sessions
- Need new SQL queries but data sources are available
- Backfill required for training period

### Larger Effort (Features 14-16): 2-3 sessions
- Referee features need a new analytics processor
- Implementation plan already exists (817 lines, ready to execute)

---

## Part 9: Backfill Strategy

New features need historical data for training. Strategy varies by feature:

### Features Already in Phase 3 (37, 42, 44, 47)
- **No backfill needed** — data already exists in `upcoming_player_game_context` for all historical dates
- Just need to extract into `ml_feature_store_v2`

### Features Computable from Existing Data (40, 41, 45, 46)
- Can compute retroactively from `player_game_summary` / `player_daily_cache`
- Run a one-time backfill query for training date range

### Features Requiring New Queries (38, 39, 43, 48)
- Need to run historical queries against raw tables
- `game_total_line` from `odds_api_game_lines` — data exists for all 3 seasons
- `teammate_ppg_missing` from injury + stats join — data exists but query is complex

### Referee Features (49, 50)
- Need to build analytics processor first
- Then backfill historical referee tendencies
- Data goes back 5+ seasons so training coverage is excellent

### Backfill Command Pattern

```python
# Example backfill for a new feature
PYTHONPATH=. python bin/backfill_feature.py \
    --feature star_teammates_out \
    --start-date 2023-12-01 \
    --end-date 2026-02-12
```

(This script doesn't exist yet — would need to be created as part of feature implementation.)

---

## Part 10: Feature Store Schema Changes

### Adding Features to `feature_contract.py`

```python
# Append to FEATURE_STORE_NAMES (NEVER insert, only append):
FEATURE_STORE_NAMES = [
    # ... existing 0-36 ...
    'star_teammates_out',         # 37
    'teammate_ppg_missing',       # 38
    'opponent_star_out',          # 39
    'fg_pct_last_3',              # 40
    'ts_pct_last_5',              # 41
    'opponent_b2b',               # 42
    'game_total_line',            # 43
    'days_since_2day_rest',       # 44
    'scoring_cv_season',          # 45
    'minutes_cv_last_10',         # 46
    'player_age',                 # 47
    'career_games_estimate',      # 48
    'ref_crew_avg_total_pts',     # 49
    'ref_crew_foul_rate',         # 50
    'game_spread',                # 51
    'game_total_movement',        # 52
]

# Update version:
FEATURE_STORE_VERSION = 'v2_53features'
FEATURE_STORE_FEATURE_COUNT = 53
```

### Key Constraint

Models specify their feature count at training time:
- V9 = 33 features (indices 0-32)
- V10 = 37 features (indices 0-36)
- V11 = 49 features (indices 0-48)
- V12 = 53 features (indices 0-52)

Old models continue working because they only read their slice of the feature array. New features added to the end never break existing models.

---

## Part 11: Files Reference

### Core Files to Modify (All Features)

| File | Purpose |
|------|---------|
| `shared/ml/feature_contract.py` | Feature definitions, names, indices |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Batch data extraction |
| `data_processors/precompute/ml_feature_store/feature_calculator.py` | On-the-fly calculations |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Feature vector assembly |
| `ml/experiments/quick_retrain.py` | Training feature count |
| `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` | BigQuery schema |

### Feature-Specific Files

| Feature Group | Additional Files |
|---------------|-----------------|
| Shooting (B) | `data_processors/precompute/player_daily_cache/aggregators/stats_aggregator.py` |
| Context (C) | `data_processors/analytics/upcoming_player_game_context/calculators/schedule_context_calculator.py` |
| Profile (D) | `stats_aggregator.py`, roster schemas |
| Referee (E) | New: `referee_tendencies_processor.py`. Existing plan: `docs/08-projects/current/data-source-enhancements/REFEREE-TENDENCIES-IMPLEMENTATION-PLAN.md` |
| Lines (F) | `shared/utils/odds_preference.py` (existing utilities) |
