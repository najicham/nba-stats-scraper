# Streak & Momentum Signal Backtests

**Session:** 293 (2026-02-18)
**Status:** Discovery phase — strong signals found, implementation pending

## Context

February 2026 model collapse (V9 champion 36.7% HR edge 3+) motivated investigation into streak/momentum patterns that the model isn't capturing. All backtests use properly lagged values (measure streak GOING INTO the game, check outcome OF that game).

## Validated Signals (Strong)

### 1. FG% Cold Streak → OVER Bounce-Back

**Definition:** Player's FG% was 5%+ below their 30-game rolling average for N consecutive games prior to today.

| Incoming Streak | Games | Pct OVER | Avg Over Line |
|----------------|-------|----------|---------------|
| 3+ games cold | 160 | **63.8%** | +1.6 |
| 2 games cold | 255 | **56.9%** | +1.2 |
| 1 game cold | 702 | 53.7% | +1.1 |
| Not cold | 1,945 | 55.1% | +0.9 |

**Our model's HR on cold-streak players: 29-33%** (worse than baseline 32.3%). The model actively gets these wrong.

### 2. 3PT% Cold Streak → OVER Bounce-Back

**Definition:** Player's 3PT% was 8%+ below their 30-game rolling average for N consecutive games (min 3 3PA/game).

| Incoming Streak | Games | Pct OVER | Avg Over Line |
|----------------|-------|----------|---------------|
| 3+ games cold | 82 | **64.6%** | +1.6 |
| 2 games cold | 139 | **62.6%** | +2.4 |
| 1 game cold | 343 | **60.1%** | +1.9 |
| Not cold | 978 | 55.2% | +1.2 |

Strongest single pattern. Effect is monotonic (scales with streak length).

### 3. Double Cold (FG% + 3PT% Both Cold Last Game)

**Definition:** Player had both FG% and 3PT% below threshold in their most recent game.

| Cold Type | Games | Pct OVER | Avg Over Line |
|-----------|-------|----------|---------------|
| Double cold | 494 | **58.5%** | +1.4 |
| 3PT cold only | 358 | **56.4%** | +1.4 |
| Not cold | 1,587 | 54.8% | +0.8 |
| FG cold only | 623 | 53.8% | +1.0 |

Good N (494). Double cold is stronger than either alone.

## Validated Non-Signals (Weak/None)

| Idea | Result | Why |
|------|--------|-----|
| TS% momentum (last 3 vs season) | 47-56% OVER | Too composite — FG+3PT+FT blurs the signal |
| FTA trend (last 3 vs last 10) | ~50% OVER | FTA doesn't predict scoring over line |
| Minutes trend (lagged) | 47-54% OVER | Lines already account for minutes role |
| Points vs line streak | 43-50% OVER | No persistence in beating/missing the line |

## Session 294 Backtests (2026-02-18)

### 4. Prop Line Delta — Market Overreaction

**Definition:** Current game's line minus previous game's line (from `player_prop_predictions`).

| Pattern | Direction | HR (edge 3+) | N | Avg Over Line |
|---------|-----------|-------------|---|---------------|
| Line dropped 3+ | OVER | **72.2%** | **370** | +6.9 |
| Line stable | OVER | 56.6% | 2087 | +1.9 |
| Line stable | UNDER | 56.4% | 5041 | -0.8 |
| Line jumped 3+ | OVER | 64.9% | 77 | +2.7 |
| Line jumped 3+ | UNDER | **46.3%** | 630 | -0.6 |
| Line dropped 3+ | UNDER | **41.0%** | 188 | +2.0 |

**Key finding:** When the market drops a player's line 3+ points (bad last game), OVER is a 72.2% HR signal with the largest N of any signal we've found. The opposite directions are anti-patterns.

**Implemented:**
- Signal: `prop_line_drop_over` (OVER + line dropped 3+ = qualify)
- Pre-filter: Block OVER + line jumped 3+ (anti-signal)
- Pre-filter: Block UNDER + line dropped 3+ (anti-signal)
- Feature: `prop_line_delta` (f54) added to feature store

### 5. Plus/Minus Streak — Negative +/- UNDER Anti-Pattern

**Definition:** Player's plus/minus was negative for N consecutive previous games.

| Pattern | Direction | HR (edge 3+) | N |
|---------|-----------|-------------|---|
| neg_3plus + OVER | OVER | 59.1% | 22 |
| neg_3plus + UNDER | UNDER | **13.1%** | **84** |
| neg_2 + OVER | OVER | 61.0% | 41 |
| neg_2 + UNDER | UNDER | 42.9% | 42 |
| neg_1 + OVER | OVER | 61.1% | 72 |

**Key finding:** The 13.1% HR on neg_3plus + UNDER (N=84) is the most catastrophic anti-pattern we've found. Players on 3+ game losing lineup streaks go OVER by +5.5 points on average. They're bounce-back candidates, not decline candidates.

**Implemented:** Pre-filter blocking UNDER + 3+ neg +/- streak.

### 6. EFG% Cold Streak

| Streak | Overall HR | OVER HR | OVER N |
|--------|-----------|---------|--------|
| 0 (not cold) | 45.5% | 63.7% | 204 |
| 1 game cold | 59.4% | **81.4%** | 43 |
| 2 games cold | 50.0% | 72.7% | 11 |

Bounce-back effect strongest at 1 cold game. Small N at 2+.

### 7. 3PA Volume Drop — Dramatic but Small N

When 3PA dropped 3+ from 10-game avg last game: **82.4% HR both OVER and UNDER** (N=17 each). The model becomes highly accurate on these players. Too small to act on now, monitor.

### 8. Self-Creation Rate — UNDER Anti-Pattern

Low self-creation (low unassisted FG% vs average) + UNDER = **22.2% HR (N=36)**. Players who relied more on teammates last game tend to bounce back. Small N, monitor.

### 9. Turnover Streak — Mild OVER Signal

High TOs (above avg) for 2+ games + OVER = 71.4% HR but N=14. High TO players are still engaged/aggressive. Too small.

### 10. Rebound Streak — Too Small

Low rebounds 3+ games: 100% OVER HR but N=5. Not actionable.

## Untested Ideas (Remaining)

### High Priority (likely signal based on validated patterns)

1. **EFG% streak** — `(FGM + 0.5 * 3PM) / FGA`. More nuanced than FG%, values 3PT makes extra
2. **Shot attempt distribution shift** — 3PA/FGA ratio vs average. More 3PAs than usual = more variance
3. **FG cold + minutes surge combo** — cold shooting BUT played more minutes = stronger bounce?
4. **Back-to-back cold after hot streak** — was the player hot then went cold? Different than chronic cold
5. **Prop line delta game-to-game** — line jumped/dropped 3+ pts. Does market overshoot?
6. **Prop line vs season average** — line set above/below their avg

### Medium Priority (novel ideas)

7. **Assisted vs unassisted FG streak** — high unassisted % = creating own shot = different pattern
8. **Turnover streak** — high TOs = less scoring. Available in player_game_summary?
9. **Plus/minus streak** — team context signal using plus_minus (98.4% coverage)
10. **4th quarter minutes trend** — closing lineup = higher usage. Available: `fourth_quarter_minutes_last_7`

### Lower Priority (speculative)

11. **Points in paint trend** — via play-by-play data
12. **Conference/division opponent** — familiar opponents after cold streaks
13. **Blowout game recovery** — played in blowout (high +/- game) → different next game

## Implementation Decisions

### Features (add to feature store, retrain model)

Best for continuous values where CatBoost can learn thresholds:
- `fg_cold_streak_going_in` (int, 0-10)
- `three_pt_cold_streak_going_in` (int, 0-10)
- `double_cold_going_in` (bool)
- `efg_momentum` (float, last 3 vs season)
- `prop_line_delta` (float, game-to-game)

### Signals (add to signal system for best bets)

Best for binary triggers with strong directional edge:
- `shooting_bounce_back` — trigger when FG% or 3PT% cold streak >= 2, direction: OVER
- Expected: 58-65% HR with decent N

### Backtest Query Template

```sql
-- Template for testing new streak ideas (properly lagged)
WITH player_stat AS (
  SELECT player_lookup, game_date,
    YOUR_STAT_HERE as stat_value
  FROM nba_analytics.player_game_summary
  WHERE game_date >= '2025-11-02' AND NOT is_dnp
    AND YOUR_FILTER_HERE  -- e.g., fg_attempts >= 5
),
with_avg AS (
  SELECT player_lookup, game_date, stat_value,
    AVG(stat_value) OVER (PARTITION BY player_lookup ORDER BY game_date
      ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING) as rolling_avg
  FROM player_stat
),
cold_flag AS (
  SELECT *,
    CASE WHEN stat_value < rolling_avg - YOUR_THRESHOLD THEN 1 ELSE 0 END as was_cold
  FROM with_avg WHERE rolling_avg IS NOT NULL
),
lagged AS (
  SELECT player_lookup, game_date,
    LAG(was_cold, 1) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev1,
    LAG(was_cold, 2) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev2,
    LAG(was_cold, 3) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev3
  FROM cold_flag
),
streak AS (
  SELECT player_lookup, game_date,
    CASE
      WHEN COALESCE(prev1,0)+COALESCE(prev2,0)+COALESCE(prev3,0) >= 3 THEN '3+_cold'
      WHEN COALESCE(prev1,0)+COALESCE(prev2,0) >= 2 THEN '2_cold'
      WHEN COALESCE(prev1,0) = 1 THEN '1_cold'
      ELSE 'not_cold'
    END as incoming
  FROM lagged WHERE prev1 IS NOT NULL
)
SELECT s.incoming,
  COUNT(*) as games,
  ROUND(AVG(pa.actual_points - pa.line_value), 1) as avg_over_line,
  ROUND(100.0 * COUNTIF(pa.actual_points > pa.line_value) / COUNT(*), 1) as pct_over
FROM streak s
JOIN nba_predictions.prediction_accuracy pa
  ON s.player_lookup = pa.player_lookup AND s.game_date = pa.game_date
  AND pa.system_id = 'catboost_v9' AND pa.line_value IS NOT NULL
WHERE s.game_date >= '2025-12-01'
GROUP BY 1 ORDER BY 1
```

## Raw Data Available

| Source | Columns | Notes |
|--------|---------|-------|
| `player_game_summary` | fg_makes, fg_attempts, three_pt_makes, three_pt_attempts, ts_pct, efg_pct, minutes_played, plus_minus, assisted_fg_makes, unassisted_fg_makes, ft_attempts | Primary source for shooting stats |
| `player_daily_cache` | ts_pct_last_10, three_pt_rate_last_10, minutes_avg_last_10, fourth_quarter_minutes_last_7 | Pre-computed rolling stats |
| `odds_api_player_points_props` | points_line, bookmaker, player_lookup, game_date | Prop line history |
