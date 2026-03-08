# Season Autopsy — Cross-Day Pattern Mining

You are performing a comprehensive cross-day analysis of best bets performance over a date range. This is a **read-only** diagnostic — no writes, no deployments, no code changes.

## Your Mission

Mine historical data for structural patterns that a single-day autopsy can't see:
1. Which players consistently cover? Which are traps?
2. Which filters are consistently destroying or saving value?
3. How does performance shift across game types, days of week, edge bands?
4. Where is the system leaving the most profit on the table?
5. What specific, actionable changes would improve profitability?

## Parameters

- `start`: Start date (default: `2026-01-09` — season start for best bets)
- `end`: End date (default: yesterday)
- `focus`: Optional focus area — `players`, `filters`, `signals`, `trends`, `profit` (default: all)

Parse arguments early:
```bash
START_DATE="${1:-2026-01-09}"
END_DATE="${2:-$(date -d yesterday +%Y-%m-%d)}"
FOCUS="${3:-all}"
echo "Season Autopsy: $START_DATE to $END_DATE (focus: $FOCUS)"
```

---

## Section 1: System Performance Overview

### 1A: Monthly Performance Trajectory

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  FORMAT_DATE('%Y-%m', bb.game_date) as month,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr,
  ROUND(COUNTIF(pa.prediction_correct) * 0.91 - COUNTIF(NOT pa.prediction_correct) * 1.0, 2) as profit,
  -- Direction split
  COUNTIF(bb.recommendation = 'OVER') as over_picks,
  ROUND(100.0 * COUNTIF(bb.recommendation = 'OVER' AND pa.prediction_correct) /
    NULLIF(COUNTIF(bb.recommendation = 'OVER'), 0), 1) as over_hr,
  COUNTIF(bb.recommendation = 'UNDER') as under_picks,
  ROUND(100.0 * COUNTIF(bb.recommendation = 'UNDER' AND pa.prediction_correct) /
    NULLIF(COUNTIF(bb.recommendation = 'UNDER'), 0), 1) as under_hr,
  -- Edge stats
  ROUND(AVG(bb.edge), 1) as avg_edge,
  ROUND(AVG(CASE WHEN pa.prediction_correct THEN bb.edge END), 1) as winning_avg_edge,
  ROUND(AVG(CASE WHEN NOT pa.prediction_correct THEN bb.edge END), 1) as losing_avg_edge,
  -- Rescued
  COUNTIF(bb.signal_rescued) as rescued_picks,
  ROUND(100.0 * COUNTIF(bb.signal_rescued AND pa.prediction_correct) /
    NULLIF(COUNTIF(bb.signal_rescued), 0), 1) as rescued_hr
FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date BETWEEN '$START_DATE' AND '$END_DATE'
  AND pa.prediction_correct IS NOT NULL AND pa.is_voided IS NOT TRUE
GROUP BY 1 ORDER BY 1
"
```

### 1B: Weekly Performance with Rolling Trend

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  DATE_TRUNC(bb.game_date, WEEK(MONDAY)) as week_start,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr,
  ROUND(COUNTIF(pa.prediction_correct) * 0.91 - COUNTIF(NOT pa.prediction_correct) * 1.0, 2) as profit,
  ROUND(AVG(bb.edge), 1) as avg_edge,
  COUNTIF(bb.recommendation = 'OVER') as overs,
  COUNTIF(bb.recommendation = 'UNDER') as unders
FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date BETWEEN '$START_DATE' AND '$END_DATE'
  AND pa.prediction_correct IS NOT NULL AND pa.is_voided IS NOT TRUE
GROUP BY 1 ORDER BY 1
"
```

**Present as:**
```
PERFORMANCE TRAJECTORY:
  [Month/Week] | [Picks] | [HR%] | [Profit] | [Trend arrow]
  Flag: "DECLINING" if 3+ consecutive weeks below 55%
  Flag: "EDGE COMPRESSION" if avg_edge dropping > 1.0 from peak
```

---

## Section 2: Cover Kings & Trap Players

### 2A: Biggest Missed Covers — Players Who Beat Lines by 5+ That We Didn't Pick

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH our_picks AS (
  SELECT DISTINCT player_lookup, game_date
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\`
  WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'
),
big_covers AS (
  SELECT
    pa.player_lookup,
    pa.game_date,
    pa.actual_points,
    pa.line_value,
    pa.actual_points - pa.line_value as margin,
    pa.recommendation as model_direction,
    ABS(pa.predicted_points - pa.line_value) as model_edge,
    pa.prediction_correct,
    CASE WHEN op.player_lookup IS NOT NULL THEN TRUE ELSE FALSE END as was_picked
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  LEFT JOIN our_picks op ON pa.player_lookup = op.player_lookup AND pa.game_date = op.game_date
  WHERE pa.game_date BETWEEN '$START_DATE' AND '$END_DATE'
    AND pa.has_prop_line = TRUE AND pa.prediction_correct IS NOT NULL
    AND pa.system_id LIKE 'catboost_v12%'
    AND ABS(pa.actual_points - pa.line_value) >= 5
  QUALIFY ROW_NUMBER() OVER (PARTITION BY pa.player_lookup, pa.game_date ORDER BY ABS(pa.predicted_points - pa.line_value) DESC) = 1
)
SELECT
  player_lookup,
  COUNT(*) as big_covers,
  COUNTIF(NOT was_picked) as missed,
  COUNTIF(was_picked) as picked,
  COUNTIF(margin > 0) as over_covers,
  COUNTIF(margin < 0) as under_covers,
  ROUND(AVG(ABS(margin)), 1) as avg_margin,
  ROUND(AVG(model_edge), 1) as avg_model_edge,
  -- Direction accuracy: did model get the direction right?
  ROUND(100.0 * COUNTIF(
    (model_direction = 'OVER' AND margin > 0) OR
    (model_direction = 'UNDER' AND margin < 0)
  ) / COUNT(*), 1) as direction_accuracy
FROM big_covers
GROUP BY 1
HAVING big_covers >= 3
ORDER BY missed DESC, big_covers DESC
LIMIT 25
"
```

### 2B: Player Model Accuracy — Who Does the Model Read Best/Worst?

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  pa.player_lookup,
  COUNT(*) as predictions,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr,
  ROUND(AVG(ABS(pa.predicted_points - pa.line_value)), 1) as avg_edge,
  ROUND(AVG(pa.predicted_points - pa.actual_points), 1) as avg_bias,
  ROUND(AVG(ABS(pa.predicted_points - pa.actual_points)), 1) as avg_mae,
  ROUND(STDDEV(pa.actual_points), 1) as scoring_std,
  COUNTIF(pa.recommendation = 'OVER' AND pa.prediction_correct) as over_wins,
  COUNTIF(pa.recommendation = 'OVER') as over_total,
  COUNTIF(pa.recommendation = 'UNDER' AND pa.prediction_correct) as under_wins,
  COUNTIF(pa.recommendation = 'UNDER') as under_total
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
WHERE pa.game_date BETWEEN '$START_DATE' AND '$END_DATE'
  AND pa.has_prop_line = TRUE AND pa.prediction_correct IS NOT NULL
  AND pa.system_id LIKE 'catboost_v12%'
  AND pa.recommendation IN ('OVER', 'UNDER')
GROUP BY 1
HAVING predictions >= 10
ORDER BY hr DESC
LIMIT 30
"
```

### 2C: Our Best and Worst BB Picks by Player

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  bb.player_lookup,
  COUNT(*) as times_picked,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr,
  ROUND(COUNTIF(pa.prediction_correct) * 0.91 - COUNTIF(NOT pa.prediction_correct) * 1.0, 2) as profit,
  COUNTIF(bb.recommendation = 'OVER') as over_picks,
  COUNTIF(bb.recommendation = 'UNDER') as under_picks,
  ROUND(AVG(bb.edge), 1) as avg_edge,
  ROUND(AVG(pa.predicted_points - pa.actual_points), 1) as avg_bias,
  ROUND(AVG(ABS(pa.actual_points - pa.line_value)), 1) as avg_margin,
  STRING_AGG(
    CONCAT(
      CASE WHEN pa.prediction_correct THEN 'W' ELSE 'L' END,
      '(', CAST(ROUND(bb.edge, 0) AS STRING), ')'
    ),
    ' ' ORDER BY bb.game_date
  ) as pick_history
FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date BETWEEN '$START_DATE' AND '$END_DATE'
  AND pa.prediction_correct IS NOT NULL AND pa.is_voided IS NOT TRUE
GROUP BY 1
HAVING times_picked >= 2
ORDER BY profit DESC
"
```

**Present as:**
```
COVER KINGS (missed opportunities):
  1. <player> — X big covers missed (Y over, Z under), avg margin X.X
     Model edge: X.X | Direction accuracy: X%
     [If direction_accuracy > 70%]: MODEL READS THIS PLAYER WELL — edge too low to pick
     [If direction_accuracy < 50%]: MODEL MISREADS THIS PLAYER — structural blind spot

BEST BB PICKS (profit leaders):
  <player>: W-L (HR%), +X.XX units | History: W(6) W(5) L(4) W(8)

WORST BB PICKS (profit losers):
  <player>: W-L (HR%), -X.XX units | Avg bias: X.X
  [Flag players with avg_bias > +3 or < -3 as "MODEL MISCALIBRATED"]

BLACKLIST CANDIDATES (3+ picks, HR < 40%, bias > |3|):
  <player>: W-L, bias X.X — CONSIDER ADDING TO BLACKLIST
```

---

## Section 3: Edge Band & Tier Analysis

### 3A: Edge Band Performance by Direction

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  CASE
    WHEN bb.edge >= 8 THEN 'edge_8plus'
    WHEN bb.edge >= 6 THEN 'edge_6_8'
    WHEN bb.edge >= 5 THEN 'edge_5_6'
    WHEN bb.edge >= 4 THEN 'edge_4_5'
    WHEN bb.edge >= 3 THEN 'edge_3_4'
    ELSE 'edge_below_3'
  END as edge_band,
  bb.recommendation,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr,
  ROUND(COUNTIF(pa.prediction_correct) * 0.91 - COUNTIF(NOT pa.prediction_correct) * 1.0, 2) as profit,
  ROUND(AVG(ABS(pa.actual_points - pa.line_value)), 1) as avg_cover_margin
FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date BETWEEN '$START_DATE' AND '$END_DATE'
  AND pa.prediction_correct IS NOT NULL AND pa.is_voided IS NOT TRUE
GROUP BY 1, 2
ORDER BY 1, 2
"
```

### 3B: Player Tier Performance

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  bb.player_tier,
  bb.recommendation,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr,
  ROUND(COUNTIF(pa.prediction_correct) * 0.91 - COUNTIF(NOT pa.prediction_correct) * 1.0, 2) as profit,
  ROUND(AVG(bb.edge), 1) as avg_edge,
  COUNTIF(bb.signal_rescued) as rescued
FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date BETWEEN '$START_DATE' AND '$END_DATE'
  AND pa.prediction_correct IS NOT NULL AND pa.is_voided IS NOT TRUE
GROUP BY 1, 2
ORDER BY 1, 2
"
```

### 3C: Game Type Performance (Blowout vs Competitive)

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH game_types AS (
  SELECT game_id,
    CASE
      WHEN ABS(home_team_score - away_team_score) >= 20 THEN 'BLOWOUT'
      WHEN ABS(home_team_score - away_team_score) >= 10 THEN 'COMFORTABLE'
      ELSE 'COMPETITIVE'
    END as game_type,
    ABS(home_team_score - away_team_score) as score_diff
  FROM \`nba-props-platform.nba_raw.nbac_schedule\`
  WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE' AND game_status = 3
)
SELECT
  gt.game_type,
  bb.recommendation,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr,
  ROUND(COUNTIF(pa.prediction_correct) * 0.91 - COUNTIF(NOT pa.prediction_correct) * 1.0, 2) as profit,
  ROUND(AVG(gt.score_diff), 0) as avg_score_diff
FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
JOIN game_types gt ON bb.game_id = gt.game_id
WHERE bb.game_date BETWEEN '$START_DATE' AND '$END_DATE'
  AND pa.prediction_correct IS NOT NULL AND pa.is_voided IS NOT TRUE
GROUP BY 1, 2
ORDER BY 1, 2
"
```

### 3D: Day of Week Performance

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  FORMAT_DATE('%A', bb.game_date) as day_of_week,
  EXTRACT(DAYOFWEEK FROM bb.game_date) as dow_num,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr,
  ROUND(COUNTIF(pa.prediction_correct) * 0.91 - COUNTIF(NOT pa.prediction_correct) * 1.0, 2) as profit
FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date BETWEEN '$START_DATE' AND '$END_DATE'
  AND pa.prediction_correct IS NOT NULL AND pa.is_voided IS NOT TRUE
GROUP BY 1, 2
ORDER BY 2
"
```

**Present cross-cutting findings:**
```
PROFITABLE ZONES:
  Edge X+, <direction>: XX% HR, +X.XX units — [size of opportunity]
  <tier> <direction>: XX% HR — [if different from overall]

DANGER ZONES:
  Edge X-Y, <direction>: XX% HR, -X.XX units — [size of problem]
  <game_type> <direction>: XX% HR — [if significantly below average]

DAY-OF-WEEK:
  Best: <day> (XX% HR)
  Worst: <day> (XX% HR) — [if < 50%, flag as potential filter candidate]
```

---

## Section 4: Filter Effectiveness Deep Dive

### 4A: Overall Filter Value Ranking

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  filter_reason,
  COUNT(*) as total_blocked,
  COUNTIF(prediction_correct = TRUE) as winners_blocked,
  COUNTIF(prediction_correct = FALSE) as losers_blocked,
  COUNTIF(prediction_correct IS NULL) as ungraded,
  ROUND(100.0 * COUNTIF(prediction_correct = TRUE) /
    NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as cf_hr,
  -- Net value: each loser blocked saves 1.0 unit, each winner blocked costs 0.91 units
  ROUND(COUNTIF(prediction_correct = FALSE) * 1.0 - COUNTIF(prediction_correct = TRUE) * 0.91, 1) as net_value,
  -- Average edge of blocked picks
  ROUND(AVG(CASE WHEN prediction_correct IS NOT NULL THEN edge END), 1) as avg_edge_blocked,
  -- How many at high edge?
  COUNTIF(edge >= 4 AND prediction_correct IS NOT NULL) as high_edge_blocked
FROM \`nba-props-platform.nba_predictions.best_bets_filtered_picks\`
WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'
GROUP BY 1
ORDER BY net_value DESC
"
```

### 4B: Filter Consistency Over Time (Monthly)

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH monthly AS (
  SELECT
    filter_reason,
    FORMAT_DATE('%Y-%m', game_date) as month,
    COUNTIF(prediction_correct = TRUE) as wins,
    COUNTIF(prediction_correct IS NOT NULL) as total,
    ROUND(100.0 * COUNTIF(prediction_correct = TRUE) /
      NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as cf_hr
  FROM \`nba-props-platform.nba_predictions.best_bets_filtered_picks\`
  WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'
    AND prediction_correct IS NOT NULL
  GROUP BY 1, 2
  HAVING total >= 2
)
SELECT
  filter_reason,
  STRING_AGG(
    CONCAT(month, ': ', CAST(cf_hr AS STRING), '% (', CAST(total AS STRING), ')'),
    ' | ' ORDER BY month
  ) as monthly_cf_hr,
  COUNT(DISTINCT month) as months_active,
  -- Consistency: is CF HR always above or below breakeven?
  COUNTIF(cf_hr > 52.4) as months_above_breakeven,
  COUNTIF(cf_hr <= 52.4) as months_below_breakeven
FROM monthly
GROUP BY 1
ORDER BY months_active DESC, filter_reason
"
```

### 4C: Filtered Picks That Would Have Won — Detail

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  fp.game_date,
  fp.player_lookup,
  fp.recommendation,
  ROUND(fp.edge, 1) as edge,
  ROUND(fp.line_value, 1) as line,
  fp.actual_points,
  ROUND(fp.actual_points - fp.line_value, 1) as margin,
  fp.filter_reason,
  fp.signal_count,
  fp.signal_tags
FROM \`nba-props-platform.nba_predictions.best_bets_filtered_picks\` fp
WHERE fp.game_date BETWEEN '$START_DATE' AND '$END_DATE'
  AND fp.prediction_correct = TRUE
ORDER BY fp.edge DESC
LIMIT 25
"
```

**Present as:**
```
FILTER VALUE RANKING (positive = saving money):
  | Filter | Blocked | Winners | Losers | CF HR | Net Value | Verdict |
  |--------|---------|---------|--------|-------|-----------|---------|
  | <name> | N       | N       | N      | XX%   | +/-X.X    | KEEP/INVESTIGATE/DEMOTE |

  KEEP: CF HR < 45% and N >= 10
  INVESTIGATE: CF HR 45-55% or N < 10
  DEMOTE: CF HR > 55% and N >= 10

CONSISTENCY CHECK:
  <filter>: Jan XX%, Feb XX%, Mar XX%
  [If CF HR varies > 20pp across months]: INCONSISTENT — may be regime-dependent
  [If CF HR consistently > 55% every month]: STRONG DEMOTE CANDIDATE

TOP FILTERED WINNERS (picks we should have made):
  1. <player> <date> — <direction> edge X.X, line X.X, actual X (+X.X margin)
     Blocked by: <filter>
```

---

## Section 5: Signal Effectiveness

### 5A: Signal Win Rate on BB Picks

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH signal_outcomes AS (
  SELECT
    signal_tag,
    pa.prediction_correct,
    bb.recommendation
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
  JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
    ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id,
  UNNEST(bb.signal_tags) as signal_tag
  WHERE bb.game_date BETWEEN '$START_DATE' AND '$END_DATE'
    AND pa.prediction_correct IS NOT NULL AND pa.is_voided IS NOT TRUE
)
SELECT
  signal_tag,
  COUNTIF(prediction_correct) as on_winners,
  COUNT(*) - COUNTIF(prediction_correct) as on_losers,
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as bb_hr,
  -- Direction split
  ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'OVER') /
    NULLIF(COUNTIF(recommendation = 'OVER'), 0), 1) as over_hr,
  COUNTIF(recommendation = 'OVER') as over_n,
  ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'UNDER') /
    NULLIF(COUNTIF(recommendation = 'UNDER'), 0), 1) as under_hr,
  COUNTIF(recommendation = 'UNDER') as under_n
FROM signal_outcomes
GROUP BY 1
HAVING total >= 5
ORDER BY bb_hr DESC
"
```

### 5B: Rescue Signal Performance

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  bb.rescue_signal,
  bb.recommendation,
  COUNT(*) as picks,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hr,
  ROUND(COUNTIF(pa.prediction_correct) * 0.91 - COUNTIF(NOT pa.prediction_correct) * 1.0, 2) as profit,
  ROUND(AVG(bb.edge), 1) as avg_edge
FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
WHERE bb.game_date BETWEEN '$START_DATE' AND '$END_DATE'
  AND bb.signal_rescued = TRUE
  AND pa.prediction_correct IS NOT NULL AND pa.is_voided IS NOT TRUE
GROUP BY 1, 2
ORDER BY 1, 2
"
```

### 5C: Signal Combinations — Which Pairs Win Together?

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH pick_signals AS (
  SELECT
    bb.player_lookup,
    bb.game_date,
    pa.prediction_correct,
    bb.signal_tags
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
  JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
    ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
  WHERE bb.game_date BETWEEN '$START_DATE' AND '$END_DATE'
    AND pa.prediction_correct IS NOT NULL AND pa.is_voided IS NOT TRUE
),
signal_pairs AS (
  SELECT
    s1 as signal_a,
    s2 as signal_b,
    ps.prediction_correct
  FROM pick_signals ps,
  UNNEST(ps.signal_tags) as s1,
  UNNEST(ps.signal_tags) as s2
  WHERE s1 < s2  -- avoid duplicates and self-pairs
    AND s1 NOT IN ('model_health', 'high_edge', 'edge_spread_optimal')  -- skip base
    AND s2 NOT IN ('model_health', 'high_edge', 'edge_spread_optimal')
)
SELECT
  signal_a,
  signal_b,
  COUNT(*) as co_occurrences,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as pair_hr
FROM signal_pairs
GROUP BY 1, 2
HAVING co_occurrences >= 5
ORDER BY pair_hr DESC
LIMIT 20
"
```

**Present as:**
```
SIGNAL SCOREBOARD (BB level):
  | Signal | On Winners | On Losers | BB HR | OVER HR (N) | UNDER HR (N) |
  [Sort by BB HR descending]
  [Flag signals with BB HR < 50% and N >= 10 as "ANTI-SIGNAL"]
  [Flag signals with BB HR > 75% and N >= 10 as "VALIDATED"]

RESCUE PERFORMANCE:
  | Rescue Signal | Dir | W-L | HR | Profit | Avg Edge |
  [Flag rescue signals with HR < 50% as "RESCUE CONCERN"]

WINNING COMBINATIONS (top signal pairs):
  <signal_a> + <signal_b>: XX% HR (N=XX) — [if > 80%: "STRONG SYNERGY"]
```

---

## Section 6: Profit Leakage Analysis

### 6A: Where Is Value Being Left on the Table?

```bash
bq query --use_legacy_sql=false --format=pretty "
-- Compare BB vs model-level HR by edge band and direction
WITH model_level AS (
  SELECT
    recommendation,
    CASE
      WHEN ABS(predicted_points - line_value) >= 6 THEN 'edge_6plus'
      WHEN ABS(predicted_points - line_value) >= 4 THEN 'edge_4_6'
      WHEN ABS(predicted_points - line_value) >= 3 THEN 'edge_3_4'
      ELSE 'edge_below_3'
    END as edge_band,
    COUNT(*) as model_total,
    COUNTIF(prediction_correct) as model_wins,
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as model_hr
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
  WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'
    AND has_prop_line = TRUE AND prediction_correct IS NOT NULL
    AND system_id LIKE 'catboost_v12%'
    AND recommendation IN ('OVER', 'UNDER')
  GROUP BY 1, 2
),
bb_level AS (
  SELECT
    bb.recommendation,
    CASE
      WHEN bb.edge >= 6 THEN 'edge_6plus'
      WHEN bb.edge >= 4 THEN 'edge_4_6'
      WHEN bb.edge >= 3 THEN 'edge_3_4'
      ELSE 'edge_below_3'
    END as edge_band,
    COUNT(*) as bb_total,
    COUNTIF(pa.prediction_correct) as bb_wins,
    ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as bb_hr
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
  JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
    ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
  WHERE bb.game_date BETWEEN '$START_DATE' AND '$END_DATE'
    AND pa.prediction_correct IS NOT NULL AND pa.is_voided IS NOT TRUE
  GROUP BY 1, 2
)
SELECT
  m.recommendation,
  m.edge_band,
  m.model_total,
  m.model_hr,
  COALESCE(b.bb_total, 0) as bb_total,
  b.bb_hr,
  m.model_total - COALESCE(b.bb_total, 0) as filtered_out,
  ROUND(m.model_hr - COALESCE(b.bb_hr, 0), 1) as hr_gap
FROM model_level m
LEFT JOIN bb_level b ON m.recommendation = b.recommendation AND m.edge_band = b.edge_band
ORDER BY m.recommendation, m.edge_band
"
```

### 6B: Concentration Risk — How Many Unique Players Do We Pick?

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  FORMAT_DATE('%Y-%m', bb.game_date) as month,
  COUNT(*) as total_picks,
  COUNT(DISTINCT bb.player_lookup) as unique_players,
  ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT bb.player_lookup), 1) as avg_picks_per_player,
  COUNT(DISTINCT bb.game_id) as games_covered,
  ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT bb.game_date), 1) as avg_picks_per_day
FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
WHERE bb.game_date BETWEEN '$START_DATE' AND '$END_DATE'
GROUP BY 1 ORDER BY 1
"
```

---

## Section 7: Synthesis — Actionable Recommendations

Do NOT run additional queries. Synthesize findings from Sections 1-6 into specific recommendations.

**Present as:**

```
===============================================
  SEASON AUTOPSY SYNTHESIS
  Period: $START_DATE to $END_DATE
  Total: W-L (HR%), +XX.XX units
===============================================

TOP 5 ACTIONABLE FINDINGS:

1. [MOST IMPACTFUL FINDING]
   Evidence: <specific data from queries>
   Recommendation: <specific action>
   Expected Impact: <quantified if possible>

2. [SECOND FINDING]
   ...

FILTER RECOMMENDATIONS:
  DEMOTE (CF HR > 55%, N >= 10):
    <filter>: XX% CF HR, N=XX — destroying X.X units
  KEEP (CF HR < 45%, N >= 10):
    <filter>: XX% CF HR — saving X.X units
  INVESTIGATE (insufficient data or borderline):
    <filter>: XX% CF HR, N=XX — need more data

SIGNAL RECOMMENDATIONS:
  PROMOTE (BB HR > 70%, N >= 15):
    <signal>: XX% BB HR — add to weighted signals
  MONITOR (BB HR 50-70%, N >= 10):
    <signal>: XX% BB HR — keep tracking
  SUPPRESS (BB HR < 50%, N >= 10):
    <signal>: XX% BB HR — remove from real_sc / rescue

PLAYER WATCHLIST:
  BLACKLIST CANDIDATES: <player> (W-L, bias X.X)
  EDGE THRESHOLD CANDIDATES: <player> (model HR XX%, avg edge X.X)

STRUCTURAL INSIGHTS:
  <Any cross-cutting patterns from game type, day of week, tier analysis>
===============================================
```

## Key Schema Reminders

- `prediction_accuracy` has NO `edge` column — compute: `ABS(predicted_points - line_value)`
- `prediction_accuracy` has NO `hit` column — use: `prediction_correct`
- `prediction_accuracy` uses `recommendation` (NOT `predicted_direction`)
- Filter: `has_prop_line = TRUE AND recommendation IN ('OVER', 'UNDER') AND prediction_correct IS NOT NULL`
- `signal_best_bets_picks` has its own `system_id` — join on `bb.system_id = pa.system_id`
- `player_game_summary.win_flag` is ALWAYS FALSE — use `plus_minus > 0` as win proxy
- `is_dnp` can be NULL — use `(is_dnp IS NULL OR is_dnp = FALSE)`
- `best_bets_filtered_picks` started recording ~Mar 3, 2026 — limited data window
- `best_bets_filtered_picks.filter_reason` is a STRING describing which filter blocked the pick

## Parameters

- `start`: Start date for analysis (default: 2026-01-09). Format: YYYY-MM-DD.
- `end`: End date for analysis (default: yesterday). Format: YYYY-MM-DD.
- `focus`: Optional focus — `players`, `filters`, `signals`, `trends`, `profit` (default: all sections).
