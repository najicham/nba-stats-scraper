# V12 Feature Additions — Implementation Guide

**Date:** 2026-02-13 (Session 227)
**Purpose:** Complete specification for adding 15 new features to the ML feature store
**For:** Another Claude Code session to implement schema changes, feature extraction, and backfill
**Priority:** BLOCKING — must be done before V2 model experiments

---

## Context

We're rebuilding our NBA player props model (V2 architecture). The current V9 model has 33 features and is Vegas-dependent (features 25-28 account for 20-45% of importance). The V2 model removes Vegas features and adds new features to compensate.

**Current feature store:** `nba_predictions.ml_feature_store_v2` with 39 features (V11 contract)
**Target:** V12 contract with 54 features (39 existing + 15 new)

The new features will be appended at indices 39-53. Existing features MUST NOT be reordered (would break all existing models).

---

## Summary of Changes

### New Features (15 total, indices 39-53)

| Index | Name | Category | Source | Complexity |
|-------|------|----------|--------|------------|
| 39 | `days_rest` | Fatigue | UPCG (exists) | LOW |
| 40 | `minutes_load_last_7d` | Fatigue | UPCG (exists) | LOW |
| 41 | `spread_magnitude` | Game Env | UPCG (compute) | LOW |
| 42 | `implied_team_total` | Game Env | UPCG (compute) | LOW |
| 43 | `points_avg_last_3` | Performance | game_summary (query) | MEDIUM |
| 44 | `scoring_trend_slope` | Trend | game_summary (query) | MEDIUM |
| 45 | `deviation_from_avg_last3` | Trend | game_summary (query) | MEDIUM |
| 46 | `consecutive_games_below_avg` | Trend | game_summary (query) | MEDIUM |
| 47 | `teammate_usage_available` | Team | injury_report + game_summary | HIGH |
| 48 | `usage_rate_last_5` | Performance | game_summary (query) | MEDIUM |
| 49 | `games_since_structural_change` | Regime | game_summary + rosters | HIGH |
| 50 | `multi_book_line_std` | Market | odds_api_props (query) | MEDIUM |
| 51 | `prop_over_streak` | Streak | UPCG (exists) | LOW |
| 52 | `prop_under_streak` | Streak | UPCG (exists) | LOW |
| 53 | `line_vs_season_avg` | Market | computed from 25 + 2 | LOW |

### Effort Breakdown
- **LOW (6 features):** Already in UPCG or simple computation from existing features
- **MEDIUM (6 features):** Need BigQuery queries against existing tables
- **HIGH (3 features):** Need new computation logic or multiple data sources

---

## Tier 1: LOW Complexity (Already in UPCG)

These features already exist in `nba_analytics.upcoming_player_game_context` but aren't extracted to the feature store.

### Feature 39: `days_rest`

**Source:** `UPCG.days_rest` (INT64 — days since last game)
**Default:** 1.0
**Replaces:** `rest_advantage` (feature 9, near-zero importance) and partially `back_to_back` (feature 16)
**Why:** Continuous value (1, 2, 3, 7+) is strictly more informative than binary back_to_back. Values >5 signal structural breaks (ASB, injury return).

**Extraction (add to feature_extractor.py):**
```python
def get_days_rest(self, player_lookup: str) -> Optional[float]:
    context = self._player_context_lookup.get(player_lookup, {})
    val = context.get('days_rest')
    return float(val) if val is not None else None
```

### Feature 40: `minutes_load_last_7d`

**Source:** `UPCG.minutes_in_last_7_days` (INT64 — total minutes played in last 7 days)
**Default:** 80.0 (reasonable for ~3 games averaging 27 min)
**Replaces:** `fatigue_score` (feature 5, composite black box)
**Why:** Direct measurement of cumulative fatigue load. Model can learn its own thresholds rather than relying on a hand-crafted composite.

**Extraction:**
```python
def get_minutes_load_7d(self, player_lookup: str) -> Optional[float]:
    context = self._player_context_lookup.get(player_lookup, {})
    val = context.get('minutes_in_last_7_days')
    return float(val) if val is not None else None
```

### Feature 41: `spread_magnitude`

**Source:** `abs(UPCG.game_spread)` (NUMERIC — point spread for the game)
**Default:** 5.0 (average spread)
**Why:** Large spreads indicate expected blowouts where starters play fewer minutes. Captures garbage-time risk.

**Extraction:**
```python
def get_spread_magnitude(self, player_lookup: str) -> Optional[float]:
    context = self._player_context_lookup.get(player_lookup, {})
    spread = context.get('game_spread')
    return abs(float(spread)) if spread is not None else None
```

### Feature 42: `implied_team_total`

**Source:** Computed from `UPCG.game_total` and `UPCG.game_spread`
**Formula:** For home team: `(game_total - game_spread) / 2`. For away team: `(game_total + game_spread) / 2`.
**Note on spread convention:** `game_spread` in UPCG is the HOME team's spread. Negative = home favored. If home spread is -6, home implied total = (220 - (-6)) / 2 = 113, away = 107.
**Default:** 112.0 (average team total)
**Why:** Best single proxy for a player's team scoring environment. A team expected to score 118 vs their average of 112 means elevated scoring opportunity.

**Extraction:**
```python
def get_implied_team_total(self, player_lookup: str) -> Optional[float]:
    context = self._player_context_lookup.get(player_lookup, {})
    game_total = context.get('game_total')
    spread = context.get('game_spread')  # Home team spread
    home_game = context.get('home_game')
    if game_total is None or spread is None or home_game is None:
        return None
    game_total = float(game_total)
    spread = float(spread)
    if home_game:
        return (game_total - spread) / 2  # Home: subtract negative spread = add
    else:
        return (game_total + spread) / 2  # Away: add negative spread = subtract
```

**IMPORTANT — Verify spread convention:** Before implementing, run this query to confirm the sign convention:
```sql
SELECT game_date, game_id,
  home_team_tricode, away_team_tricode,
  game_spread, game_total, game_spread_source
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= CURRENT_DATE() - 3
  AND game_spread IS NOT NULL
GROUP BY 1,2,3,4,5,6,7
ORDER BY 1 DESC, 2
LIMIT 20
```
Check: Does a negative `game_spread` correspond to the home team being favored? If spread is stored differently (e.g., always the player's team perspective), adjust the formula.

### Feature 51: `prop_over_streak`

**Source:** `UPCG.prop_over_streak` (INT64 — consecutive games over the prop line)
**Default:** 0.0
**Why:** Mean-reversion signal. After 3+ consecutive overs, Vegas raises the line. If true ability unchanged, this may create OVER opportunities on the next line adjustment. Primarily for Model 2 (edge classifier).

**Extraction:**
```python
def get_prop_over_streak(self, player_lookup: str) -> Optional[float]:
    context = self._player_context_lookup.get(player_lookup, {})
    val = context.get('prop_over_streak')
    return float(val) if val is not None else None
```

### Feature 52: `prop_under_streak`

**Source:** `UPCG.prop_under_streak` (INT64 — consecutive games under the prop line)
**Default:** 0.0
**Why:** Buy-low signal. After 3+ consecutive unders, if Vegas drops the line but fundamentals unchanged, this is a mean-reversion signal. Primarily for Model 2.

**Extraction:** Same pattern as prop_over_streak.

---

## Tier 2: MEDIUM Complexity (BigQuery Queries Needed)

These features need new queries against existing analytics tables at feature extraction time.

### Feature 43: `points_avg_last_3`

**Source:** `nba_analytics.player_game_summary` — average of last 3 games' points
**Default:** Use `points_avg_last_5` if available, else 10.0
**Why:** Ultra-short-term form indicator. Captures very recent hot/cold streaks better than last_5 or last_10.

**Query (batch for all players on a game date):**
```sql
WITH recent_games AS (
  SELECT
    player_lookup,
    points,
    ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
  FROM nba_analytics.player_game_summary
  WHERE game_date < @target_date
    AND game_date >= DATE_SUB(@target_date, INTERVAL 30 DAY)
    AND points IS NOT NULL
    AND is_dnp = FALSE
)
SELECT
  player_lookup,
  AVG(points) as points_avg_last_3
FROM recent_games
WHERE rn <= 3
GROUP BY player_lookup
HAVING COUNT(*) >= 2  -- Need at least 2 games
```

### Feature 44: `scoring_trend_slope`

**Source:** `nba_analytics.player_game_summary` — OLS regression slope of points over last 7 games
**Default:** 0.0 (flat trend)
**Why:** Captures directional momentum (rising vs falling scoring). More robust than `recent_trend` (feature 11) which is a simple diff.

**Query:**
```sql
WITH recent_games AS (
  SELECT
    player_lookup,
    points,
    ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as game_num
  FROM nba_analytics.player_game_summary
  WHERE game_date < @target_date
    AND game_date >= DATE_SUB(@target_date, INTERVAL 45 DAY)
    AND points IS NOT NULL
    AND is_dnp = FALSE
)
SELECT
  player_lookup,
  -- OLS slope: (n*SUM(xy) - SUM(x)*SUM(y)) / (n*SUM(x^2) - (SUM(x))^2)
  -- x = game_num (1=most recent, 7=oldest), y = points
  -- Positive slope = scoring is INCREASING (recent games higher)
  -- Negative = DECREASING
  SAFE_DIVIDE(
    COUNT(*) * SUM(game_num * points) - SUM(game_num) * SUM(points),
    COUNT(*) * SUM(game_num * game_num) - SUM(game_num) * SUM(game_num)
  ) as scoring_trend_slope
FROM recent_games
WHERE game_num <= 7
GROUP BY player_lookup
HAVING COUNT(*) >= 4  -- Need at least 4 data points for meaningful slope
```

**Note:** Slope is per-game-number, so a slope of +2.0 means scoring increases by ~2 points per game. Sign convention: negative game_num means most recent = 1, so positive slope = upward trend. Double-check sign in testing.

### Feature 45: `deviation_from_avg_last3`

**Source:** Computed from player_game_summary
**Formula:** `(avg_last_3 - season_avg) / season_std`
**Default:** 0.0 (at season average)
**Why:** Z-score showing how hot/cold a player is relative to their baseline. Value of +1.5 means last 3 games averaged 1.5 standard deviations above season average. Mean-reversion signal.

**Query:**
```sql
WITH player_stats AS (
  SELECT
    player_lookup,
    AVG(points) as season_avg,
    STDDEV(points) as season_std
  FROM nba_analytics.player_game_summary
  WHERE game_date >= DATE_SUB(@target_date, INTERVAL 365 DAY)
    AND game_date < @target_date
    AND points IS NOT NULL
    AND is_dnp = FALSE
  GROUP BY player_lookup
  HAVING COUNT(*) >= 10
),
recent AS (
  SELECT
    player_lookup,
    AVG(points) as avg_last_3
  FROM (
    SELECT player_lookup, points,
      ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
    FROM nba_analytics.player_game_summary
    WHERE game_date < @target_date
      AND game_date >= DATE_SUB(@target_date, INTERVAL 30 DAY)
      AND points IS NOT NULL AND is_dnp = FALSE
  ) WHERE rn <= 3
  GROUP BY player_lookup
  HAVING COUNT(*) >= 2
)
SELECT
  r.player_lookup,
  SAFE_DIVIDE(r.avg_last_3 - ps.season_avg, NULLIF(ps.season_std, 0)) as deviation_from_avg_last3
FROM recent r
JOIN player_stats ps ON r.player_lookup = ps.player_lookup
```

### Feature 46: `consecutive_games_below_avg`

**Source:** `nba_analytics.player_game_summary`
**Default:** 0.0
**Why:** Streak counter for games under own season average. After 3+ games below average, mean-reversion becomes more likely. Combined with `deviation_from_avg_last3`, captures both magnitude and persistence of cold streaks.

**Query:**
```sql
WITH player_season AS (
  SELECT player_lookup,
    AVG(points) as season_avg
  FROM nba_analytics.player_game_summary
  WHERE game_date >= DATE_SUB(@target_date, INTERVAL 365 DAY)
    AND game_date < @target_date
    AND points IS NOT NULL AND is_dnp = FALSE
  GROUP BY player_lookup
  HAVING COUNT(*) >= 10
),
recent_games AS (
  SELECT
    g.player_lookup,
    g.points,
    g.game_date,
    ps.season_avg,
    CASE WHEN g.points < ps.season_avg THEN 1 ELSE 0 END as below_avg,
    ROW_NUMBER() OVER (PARTITION BY g.player_lookup ORDER BY g.game_date DESC) as rn
  FROM nba_analytics.player_game_summary g
  JOIN player_season ps ON g.player_lookup = ps.player_lookup
  WHERE g.game_date < @target_date
    AND g.game_date >= DATE_SUB(@target_date, INTERVAL 45 DAY)
    AND g.points IS NOT NULL AND g.is_dnp = FALSE
)
-- Count consecutive below-avg from most recent game
SELECT
  player_lookup,
  -- Count streak from game 1 (most recent) until first game NOT below avg
  COUNTIF(below_avg = 1 AND rn <= streak_break) as consecutive_games_below_avg
FROM (
  SELECT *,
    MIN(CASE WHEN below_avg = 0 THEN rn END) OVER (PARTITION BY player_lookup) as streak_break
  FROM recent_games
  WHERE rn <= 10
)
WHERE rn < COALESCE(streak_break, 11)
GROUP BY player_lookup
```

**Alternative simpler approach (may be clearer):**
```sql
-- For each player, iterate from most recent game backward
-- Count consecutive games with points < season_avg
-- Stop at first game where points >= season_avg
-- This is a classic "streak" calculation using gaps-and-islands
```

### Feature 48: `usage_rate_last_5`

**Source:** `nba_analytics.player_game_summary.usage_rate`
**Default:** 20.0 (league average ~20%)
**Why:** How much of the team's offense runs through this player. High-usage players have more scoring opportunities. Changes in usage signal role changes.

**Query:**
```sql
WITH recent_games AS (
  SELECT
    player_lookup,
    usage_rate,
    ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
  FROM nba_analytics.player_game_summary
  WHERE game_date < @target_date
    AND game_date >= DATE_SUB(@target_date, INTERVAL 30 DAY)
    AND usage_rate IS NOT NULL
    AND is_dnp = FALSE
)
SELECT
  player_lookup,
  AVG(usage_rate) as usage_rate_last_5
FROM recent_games
WHERE rn <= 5
GROUP BY player_lookup
HAVING COUNT(*) >= 3
```

### Feature 50: `multi_book_line_std`

**Source:** `nba_raw.odds_api_player_points_props` — std dev of lines across bookmakers
**Default:** 0.5 (typical market agreement)
**Optional:** Yes (like vegas features — not all players have multi-book data)
**Why:** Market disagreement indicator. High std dev = bookmakers disagree = potential edge. Low std dev = consensus = less opportunity. Primarily for Model 2 (edge classifier).

**Query:**
```sql
WITH latest_snapshots AS (
  SELECT
    player_lookup,
    game_date,
    bookmaker,
    points_line,
    ROW_NUMBER() OVER (
      PARTITION BY player_lookup, game_date, bookmaker
      ORDER BY snapshot_timestamp DESC
    ) as rn
  FROM nba_raw.odds_api_player_points_props
  WHERE game_date = @target_date
)
SELECT
  player_lookup,
  STDDEV(points_line) as multi_book_line_std,
  COUNT(DISTINCT bookmaker) as num_books
FROM latest_snapshots
WHERE rn = 1
GROUP BY player_lookup
HAVING COUNT(DISTINCT bookmaker) >= 3
```

---

## Tier 3: HIGH Complexity (New Logic Required)

### Feature 47: `teammate_usage_available`

**Source:** `nba_raw.nbac_injury_report` + `nba_analytics.player_game_summary`
**Default:** 0.0 (no teammates out)
**Why:** When teammates are OUT, their usage redistributes. A continuous metric capturing HOW MUCH opportunity is freed up (sum of usage rates of inactive teammates). Key improvement over binary `star_teammates_out` (feature 37, V11) which had near-zero importance.

**Computation Logic:**

1. Get the player's team and game info
2. Get all teammates on the same team
3. For each teammate, get their recent `usage_rate` (avg last 5-10 games)
4. Check the latest injury report for the game
5. Sum `usage_rate` of all teammates with status IN ('OUT', 'DOUBTFUL')

**Query:**
```sql
WITH team_usage AS (
  -- Recent usage rates for all players
  SELECT
    player_lookup,
    team_abbr,
    AVG(usage_rate) as avg_usage_rate
  FROM (
    SELECT player_lookup, team_abbr, usage_rate,
      ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
    FROM nba_analytics.player_game_summary
    WHERE game_date >= DATE_SUB(@target_date, INTERVAL 30 DAY)
      AND game_date < @target_date
      AND usage_rate IS NOT NULL
      AND is_dnp = FALSE
  )
  WHERE rn <= 10
  GROUP BY player_lookup, team_abbr
),
injury_status AS (
  -- Latest injury report for the target game date
  SELECT
    player_lookup,
    team,
    injury_status,
    ROW_NUMBER() OVER (
      PARTITION BY player_lookup, game_date
      ORDER BY report_date DESC, report_hour DESC
    ) as rn
  FROM nba_raw.nbac_injury_report
  WHERE game_date = @target_date
    AND injury_status IN ('OUT', 'DOUBTFUL')
),
out_players AS (
  SELECT i.player_lookup, i.team, tu.avg_usage_rate
  FROM injury_status i
  JOIN team_usage tu ON i.player_lookup = tu.player_lookup
  WHERE i.rn = 1
)
-- For each active player, sum the usage of their OUT teammates
SELECT
  active.player_lookup,
  COALESCE(SUM(op.avg_usage_rate), 0) as teammate_usage_available
FROM team_usage active
LEFT JOIN out_players op
  ON active.team_abbr = op.team
  AND active.player_lookup != op.player_lookup  -- Exclude self
GROUP BY active.player_lookup
```

**Note:** The existing `star_teammates_out` (feature 37) counts the number of OUT stars. This new feature captures the MAGNITUDE of the opportunity by summing usage rates. Both should be kept — `star_teammates_out` for the count, `teammate_usage_available` for the continuous signal.

### Feature 49: `games_since_structural_change`

**Source:** `nba_analytics.player_game_summary` (team changes) + hardcoded ASB dates
**Default:** 30.0 (stable context)
**Why:** Signals when rolling averages are unreliable due to: (a) player traded to new team, (b) All-Star break disruption, (c) return from extended injury. Value 0-2 = high uncertainty/stale averages. Value 8+ = stable context.

**Computation Logic:**

1. **Trade detection:** Check if player's `team_abbr` changed between consecutive games in `player_game_summary`
2. **ASB detection:** Hardcode All-Star break dates (Feb 14-19, 2026; Feb 14-19, 2025; etc.)
3. **Injury return:** Check if there's a gap of >14 days between consecutive games (suggesting injury/absence)
4. For each detected structural change, count games played since the most recent one

**Query:**
```sql
WITH player_games AS (
  SELECT
    player_lookup,
    game_date,
    team_abbr,
    LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev_game_date,
    LAG(team_abbr) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev_team,
    ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn_desc
  FROM nba_analytics.player_game_summary
  WHERE game_date >= DATE_SUB(@target_date, INTERVAL 120 DAY)
    AND game_date < @target_date
    AND is_dnp = FALSE
),
structural_changes AS (
  SELECT
    player_lookup,
    game_date as change_date,
    CASE
      WHEN team_abbr != prev_team AND prev_team IS NOT NULL THEN 'trade'
      WHEN DATE_DIFF(game_date, prev_game_date, DAY) > 14 THEN 'extended_absence'
      -- ASB 2026: Feb 14-19
      WHEN prev_game_date < '2026-02-14' AND game_date > '2026-02-19' THEN 'allstar_break'
      -- ASB 2025: Feb 14-19
      WHEN prev_game_date < '2025-02-14' AND game_date > '2025-02-19' THEN 'allstar_break'
      ELSE NULL
    END as change_type
  FROM player_games
  WHERE (team_abbr != prev_team AND prev_team IS NOT NULL)
     OR DATE_DIFF(game_date, prev_game_date, DAY) > 14
)
SELECT
  pg.player_lookup,
  COALESCE(
    -- Count games since most recent structural change
    (SELECT pg.rn_desc
     FROM structural_changes sc
     WHERE sc.player_lookup = pg.player_lookup
       AND sc.change_date <= pg.game_date
     ORDER BY sc.change_date DESC
     LIMIT 1),
    30  -- Default: no structural change detected (stable)
  ) as games_since_structural_change
FROM player_games pg
WHERE pg.rn_desc = 1  -- Most recent game only
```

**IMPORTANT:** The ASB dates should be configurable, not hardcoded in the query. Consider a small reference table or config parameter.

### Feature 53: `line_vs_season_avg`

**Source:** Computed from `vegas_points_line` (feature 25) and `points_avg_season` (feature 2)
**Formula:** `vegas_line - season_avg`
**Default:** 0.0
**Why:** When the line is significantly below a player's season average, it may be a buy-low signal. Primarily for Model 2 (edge classifier). Positive = line above avg (market expects above-average game), negative = below avg.

**Extraction:** Can be computed in the feature store processor directly from features 25 and 2:
```python
def get_line_vs_season_avg(self, player_lookup: str) -> Optional[float]:
    vegas_line = self._get_feature_value(player_lookup, 'vegas_points_line')
    season_avg = self._get_feature_value(player_lookup, 'points_avg_season')
    if vegas_line is not None and season_avg is not None:
        return float(vegas_line) - float(season_avg)
    return None
```

---

## Schema Changes Required

### 1. Feature Contract (`shared/ml/feature_contract.py`)

Add V12 definitions:

```python
# After line 95 (end of FEATURE_STORE_NAMES):
# Append new features starting at index 39:
FEATURE_STORE_NAMES.extend([
    # 39-40: Enhanced Fatigue (replacing composites)
    "days_rest",                    # 39 - From UPCG.days_rest
    "minutes_load_last_7d",        # 40 - From UPCG.minutes_in_last_7_days

    # 41-42: Game Environment
    "spread_magnitude",            # 41 - abs(UPCG.game_spread)
    "implied_team_total",          # 42 - (game_total +/- spread) / 2

    # 43-46: Performance Trends
    "points_avg_last_3",           # 43 - Ultra-short average
    "scoring_trend_slope",         # 44 - OLS slope last 7 games
    "deviation_from_avg_last3",    # 45 - Z-score: (avg_L3 - season_avg) / std
    "consecutive_games_below_avg", # 46 - Cold streak counter

    # 47-48: Team Context
    "teammate_usage_available",    # 47 - SUM(usage_rate) for OUT teammates
    "usage_rate_last_5",           # 48 - Recent usage rate average

    # 49: Regime Change
    "games_since_structural_change", # 49 - Games since trade/ASB/return

    # 50: Market Signal (Model 2)
    "multi_book_line_std",         # 50 - Std dev across sportsbooks

    # 51-53: Streak/Market (Model 2)
    "prop_over_streak",            # 51 - Consecutive games over prop line
    "prop_under_streak",           # 52 - Consecutive games under prop line
    "line_vs_season_avg",          # 53 - vegas_line - season_avg
])

# Update counts
CURRENT_FEATURE_STORE_VERSION = "v3_54features"
FEATURE_STORE_FEATURE_COUNT = 54
```

Add V12 contract:
```python
V12_FEATURE_NAMES: List[str] = V11_FEATURE_NAMES + [
    "days_rest",                      # 39
    "minutes_load_last_7d",           # 40
    "spread_magnitude",               # 41
    "implied_team_total",             # 42
    "points_avg_last_3",              # 43
    "scoring_trend_slope",            # 44
    "deviation_from_avg_last3",       # 45
    "consecutive_games_below_avg",    # 46
    "teammate_usage_available",       # 47
    "usage_rate_last_5",              # 48
    "games_since_structural_change",  # 49
    "multi_book_line_std",            # 50
    "prop_over_streak",               # 51
    "prop_under_streak",              # 52
    "line_vs_season_avg",             # 53
]

V12_CONTRACT = ModelFeatureContract(
    model_version="v12",
    feature_count=54,
    feature_names=V12_FEATURE_NAMES,
    description="CatBoost V12 - 54 features, adds fatigue/trend/team/market signals for V2 architecture"
)
```

Add to CONTRACT_REGISTRY and get_contract().

### 2. Feature Store Schema (`schemas/bigquery/predictions/04_ml_feature_store_v2.sql`)

Add per-feature quality columns for features 39-53:
```sql
-- After existing feature_38_quality/source columns:
feature_39_quality FLOAT64,
feature_39_source STRING,
feature_40_quality FLOAT64,
feature_40_source STRING,
-- ... through feature_53
feature_53_quality FLOAT64,
feature_53_source STRING,
```

**Run ALTER TABLE to add columns (non-breaking):**
```sql
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS feature_39_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_39_source STRING,
-- ... repeat for 40-53
```

### 3. Feature Extractor (`data_processors/precompute/ml_feature_store/feature_extractor.py`)

Add extraction methods for each new feature (code provided above per feature).

**Batch extraction approach:** Add a new batch method `_batch_extract_v12_features()` that runs a single BigQuery query joining:
- `player_game_summary` (for points_avg_last_3, trend_slope, deviation, streak, usage_rate)
- Reuse `_player_context_lookup` (for days_rest, minutes_load, spread, game_total)

This is more efficient than 15 separate queries. Example:

```python
def _batch_extract_v12_features(self, game_date, player_lookups):
    """
    Batch-extract all V12 features in a single query.
    Returns dict of player_lookup -> {feature_name: value}
    """
    query = f"""
    WITH recent_games AS (
      SELECT
        player_lookup, game_date, points, minutes_played, usage_rate,
        team_abbr,
        ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn,
        LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev_game_date,
        LAG(team_abbr) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev_team
      FROM nba_analytics.player_game_summary
      WHERE game_date < '{game_date}'
        AND game_date >= DATE_SUB('{game_date}', INTERVAL 60 DAY)
        AND points IS NOT NULL AND is_dnp = FALSE
    ),
    season_stats AS (
      SELECT player_lookup,
        AVG(points) as season_avg,
        STDDEV(points) as season_std
      FROM nba_analytics.player_game_summary
      WHERE game_date < '{game_date}'
        AND game_date >= DATE_SUB('{game_date}', INTERVAL 365 DAY)
        AND points IS NOT NULL AND is_dnp = FALSE
      GROUP BY player_lookup
      HAVING COUNT(*) >= 10
    ),
    avg_last_3 AS (
      SELECT player_lookup, AVG(points) as points_avg_last_3
      FROM recent_games WHERE rn <= 3
      GROUP BY player_lookup HAVING COUNT(*) >= 2
    ),
    trend AS (
      SELECT player_lookup,
        SAFE_DIVIDE(
          COUNT(*) * SUM(rn * points) - SUM(rn) * SUM(points),
          COUNT(*) * SUM(rn * rn) - SUM(rn) * SUM(rn)
        ) as scoring_trend_slope
      FROM recent_games WHERE rn <= 7
      GROUP BY player_lookup HAVING COUNT(*) >= 4
    ),
    usage AS (
      SELECT player_lookup, AVG(usage_rate) as usage_rate_last_5
      FROM recent_games WHERE rn <= 5 AND usage_rate IS NOT NULL
      GROUP BY player_lookup HAVING COUNT(*) >= 3
    )
    SELECT
      a3.player_lookup,
      a3.points_avg_last_3,
      t.scoring_trend_slope,
      SAFE_DIVIDE(a3.points_avg_last_3 - ss.season_avg, NULLIF(ss.season_std, 0)) as deviation_from_avg_last3,
      u.usage_rate_last_5
    FROM avg_last_3 a3
    LEFT JOIN trend t ON a3.player_lookup = t.player_lookup
    LEFT JOIN season_stats ss ON a3.player_lookup = ss.player_lookup
    LEFT JOIN usage u ON a3.player_lookup = u.player_lookup
    """
    # Execute and return lookup dict
```

### 4. Quality Scorer (`data_processors/precompute/ml_feature_store/quality_scorer.py`)

Update:
- `FEATURE_CATEGORIES` to include new features
- Source classification for features 39-53
- Default values for new features

### 5. Feature Source Map (`shared/ml/feature_contract.py`)

```python
# Add after existing source maps:
FEATURES_FROM_UPCG = [39, 40, 51, 52]  # days_rest, minutes_load, prop_over/under_streak
FEATURES_COMPUTED_V12 = [41, 42, 43, 44, 45, 46, 48, 49, 53]  # Spread, trend, usage, regime
FEATURES_FROM_ODDS = [50]  # multi_book_line_std
FEATURES_FROM_INJURY = [47]  # teammate_usage_available

# Update FEATURE_SOURCE_MAP
for _idx in FEATURES_FROM_UPCG:
    FEATURE_SOURCE_MAP[_idx] = 'phase3'
for _idx in FEATURES_COMPUTED_V12:
    FEATURE_SOURCE_MAP[_idx] = 'calculated'
for _idx in FEATURES_FROM_ODDS:
    FEATURE_SOURCE_MAP[_idx] = 'vegas'
for _idx in FEATURES_FROM_INJURY:
    FEATURE_SOURCE_MAP[_idx] = 'calculated'

# Update FEATURES_OPTIONAL for Model 2 features
# multi_book_line_std, prop_over/under_streak, line_vs_season_avg are optional
FEATURES_OPTIONAL = set(FEATURES_VEGAS) | {38, 50, 51, 52, 53}
```

### 6. Feature Defaults (`shared/ml/feature_contract.py`)

```python
FEATURE_DEFAULTS.update({
    "days_rest": 1.0,
    "minutes_load_last_7d": 80.0,
    "spread_magnitude": 5.0,
    "implied_team_total": 112.0,
    "points_avg_last_3": None,  # Falls back to points_avg_last_5
    "scoring_trend_slope": 0.0,
    "deviation_from_avg_last3": 0.0,
    "consecutive_games_below_avg": 0.0,
    "teammate_usage_available": 0.0,
    "usage_rate_last_5": 20.0,
    "games_since_structural_change": 30.0,
    "multi_book_line_std": None,  # Optional
    "prop_over_streak": 0.0,
    "prop_under_streak": 0.0,
    "line_vs_season_avg": 0.0,
})
```

---

## quick_retrain.py Changes

### Add `--feature-set v12` support

```python
# In parse_args():
parser.add_argument('--feature-set', choices=['v9', 'v10', 'v11', 'v12'], default='v9',
                   help='Feature set to use (v9=33, v10=37, v11=39, v12=54)')

# In main():
elif args.feature_set == 'v12':
    selected_contract = V12_CONTRACT
    selected_feature_names = V12_FEATURE_NAMES
```

### Add `augment_v12_features()` function

Extend the existing `augment_v11_features()` pattern to inject V12 features from BQ into training/eval DataFrames. This is the training-time augmentation that lets us train on historical data that doesn't have V12 features in the feature store yet.

```python
def augment_v12_features(client, df):
    """
    Augment training/eval DataFrame with V12 features from analytics tables.
    Same pattern as augment_v11_features but for features 39-53.
    """
    if df.empty:
        return df

    min_date = df['game_date'].min()
    max_date = df['game_date'].max()

    # Single batch query for all V12 features
    query = f"""
    WITH ... (see batch extraction query above)
    """
    v12_data = client.query(query).to_dataframe()

    # Build lookup and inject into feature arrays
    # (same pattern as augment_v11_features)
    ...
    return df
```

### Add V12 augmentation call

```python
# After V11 augmentation in main():
if args.feature_set == 'v12':
    print("\nAugmenting with V12 features...")
    df_train = augment_v12_features(client, df_train)
    df_eval = augment_v12_features(client, df_eval)
```

---

## Backfill Plan

### Approach: Training-Time Augmentation (Phase 1)

For immediate experimentation, DON'T backfill the entire feature store. Instead:

1. Implement `augment_v12_features()` in quick_retrain.py
2. At training time, the function queries BQ to compute V12 features for the training/eval date range
3. Injects them into the feature arrays on the fly

**Pros:** Fast to implement, no production impact, can start experiments immediately
**Cons:** Features only available during experiments, computation repeated each run

### Approach: Feature Store Backfill (Phase 2)

After V12 features are validated (experiments show they help), do a full backfill:

1. Add columns to `ml_feature_store_v2` schema (ALTER TABLE)
2. Update `feature_extractor.py` to compute V12 features
3. Run backfill script for historical dates:

```bash
# Backfill feature store for V12 features
# Process date range in batches of 7 days
for start_date in $(seq ...); do
  PYTHONPATH=. python data_processors/precompute/ml_feature_store/ml_feature_store_processor.py \
    --game-date $date --backfill
done
```

**Estimated time:** ~2-3 hours for full season backfill (Oct 2024 - Feb 2026)

### Recommended Sequence

1. **Now:** Implement `augment_v12_features()` in quick_retrain.py + V12 contract
2. **After experiments validate features:** Add feature extraction to feature_extractor.py
3. **After production decision:** Backfill feature store, update quality scorer
4. **Never:** Deploy V12 to production without full feature store integration

---

## Testing Checklist

- [ ] V12 contract validates (`python -m shared.ml.feature_contract --validate`)
- [ ] `augment_v12_features()` correctly injects 15 features into training DataFrames
- [ ] Feature values are reasonable (days_rest 0-10, usage_rate 10-35, etc.)
- [ ] `--feature-set v12 --no-vegas` correctly excludes features 25-28 from training
- [ ] Historical data has >80% coverage for Tier 1 features (from UPCG)
- [ ] Historical data has >60% coverage for Tier 2 features (from game_summary)
- [ ] NaN handling works (median fill for missing features)
- [ ] Feature importance report includes all V12 features
- [ ] Quick sanity experiment: V12 Vegas-free on Feb 2026 runs without errors

---

## Files to Modify

| File | Changes |
|------|---------|
| `shared/ml/feature_contract.py` | Add V12 contract, feature names, defaults, source map |
| `ml/experiments/quick_retrain.py` | Add `--feature-set v12`, `augment_v12_features()` |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Add V12 extraction methods (Phase 2) |
| `data_processors/precompute/ml_feature_store/quality_scorer.py` | Add V12 quality scoring (Phase 2) |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Integrate V12 extraction (Phase 2) |
| `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` | Add feature_39-53 quality/source columns (Phase 2) |

---

## UPCG Fields Already Available (No Changes Needed)

These UPCG columns are already populated and just need feature store extraction:

| UPCG Column | Feature | Type | Coverage |
|-------------|---------|------|----------|
| `days_rest` | Feature 39 | INT64 | ~100% |
| `minutes_in_last_7_days` | Feature 40 | INT64 | ~100% |
| `game_spread` | For Feature 41-42 | NUMERIC | ~95% |
| `game_total` | Already Feature 38 | NUMERIC | ~95% |
| `prop_over_streak` | Feature 51 | INT64 | ~60% (prop-line players only) |
| `prop_under_streak` | Feature 52 | INT64 | ~60% (prop-line players only) |
| `star_teammates_out` | Already Feature 37 | INT64 | ~90% |

## UPCG Fields Defined But NOT Populated ("future" markers)

These are in the UPCG schema but return NULL. Could be populated in a future session:

| UPCG Column | Notes |
|-------------|-------|
| `pace_differential` | Team vs opponent pace |
| `opponent_def_rating_last_10` | Recent opponent defense |
| `projected_usage_rate` | Expected usage |
| `avg_usage_rate_last_7_games` | Usage intensity |
| `fourth_quarter_minutes_last_7` | Crunch time load |
| `travel_miles` | Travel distance |
| `time_zone_changes` | Jet lag factor |

These are lower priority but could be added in a future session if the V12 experiments show promise.
