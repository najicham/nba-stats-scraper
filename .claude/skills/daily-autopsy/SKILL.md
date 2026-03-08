---
name: daily-autopsy
description: Comprehensive post-mortem of yesterday's predictions — what we got wrong, what we got right, biggest misses we didn't pick, injury impacts, and actionable lessons
---

# Daily Autopsy

You are performing a comprehensive post-mortem analysis of a single day's predictions. This is a **read-only** diagnostic — no writes, no deployments, no code changes.

## Your Mission

Produce a thorough autopsy report that answers:
1. What did we get wrong, and WHY?
2. What did we get right, and what patterns were on the winning side?
3. Who COVERED big that we did NOT pick? Why did we miss them?
4. Did injuries create opportunities we missed or traps we fell into?
5. What actionable lessons can we extract for signal/filter improvements?

## Target Date Logic

Default to **yesterday** (most recent completed game day). If the user provides a date argument, use that instead. Set the date variable early and use it throughout.

```bash
# Default to yesterday, or use user-provided date
TARGET_DATE=$(date -d "yesterday" +%Y-%m-%d)
echo "Daily Autopsy for: $TARGET_DATE"
```

If the user passes a date argument (e.g., `/daily-autopsy 2026-03-05`), use that date instead.

**IMPORTANT:** Before proceeding, verify games were played and graded on this date:

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  '$TARGET_DATE' as target_date,
  (SELECT COUNT(*) FROM \`nba-props-platform.nba_reference.nba_schedule\`
   WHERE game_date = '$TARGET_DATE' AND game_status = 3) as games_final,
  (SELECT COUNT(*) FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\`
   WHERE game_date = '$TARGET_DATE') as best_bets_picks,
  (SELECT COUNT(*) FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
   WHERE game_date = '$TARGET_DATE' AND prediction_correct IS NOT NULL) as graded_predictions
"
```

If `games_final = 0`: Report "No completed games on $TARGET_DATE" and exit.
If `graded_predictions = 0`: Report "Games not yet graded for $TARGET_DATE — run grading first" and exit.
If `best_bets_picks = 0`: Report "No best bets picks found for $TARGET_DATE" and proceed with Section 3 only (biggest misses).

---

## Section 1: Our Picks -- What We Got Wrong

### 1A: Full Best Bets Scorecard

Pull all best bets picks for the day with outcomes, game context, and signal details.

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH game_scores AS (
  SELECT
    game_id,
    away_team_tricode,
    home_team_tricode,
    home_team_score,
    away_team_score,
    ABS(home_team_score - away_team_score) as score_diff,
    CASE
      WHEN ABS(home_team_score - away_team_score) >= 20 THEN 'BLOWOUT'
      WHEN ABS(home_team_score - away_team_score) >= 10 THEN 'COMFORTABLE'
      ELSE 'COMPETITIVE'
    END as game_type
  FROM \`nba-props-platform.nba_raw.nbac_schedule\`
  WHERE game_date = '$TARGET_DATE' AND game_status = 3
)
SELECT
  bb.player_lookup,
  bb.team_abbr,
  bb.opponent_team_abbr,
  bb.recommendation,
  ROUND(bb.edge, 1) as edge,
  ROUND(bb.line_value, 1) as line,
  bb.signal_count,
  bb.real_signal_count,
  bb.signal_rescued,
  bb.rescue_signal,
  bb.ultra_tier,
  pa.prediction_correct as hit,
  pa.actual_points as actual,
  ROUND(pa.actual_points - bb.line_value, 1) as margin,
  ROUND(pa.predicted_points, 1) as predicted,
  bb.source_model_family,
  gs.game_type,
  gs.score_diff as game_score_diff,
  CONCAT(gs.away_team_tricode, ' ', gs.away_team_score, '-', gs.home_team_score, ' ', gs.home_team_tricode) as final_score,
  bb.pick_angles,
  bb.signal_tags,
  bb.matched_combo_id,
  bb.player_tier,
  bb.algorithm_version
FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup
  AND bb.game_date = pa.game_date
  AND bb.system_id = pa.system_id
LEFT JOIN game_scores gs
  ON bb.game_id = gs.game_id
WHERE bb.game_date = '$TARGET_DATE'
  AND pa.prediction_correct IS NOT NULL
  AND pa.is_voided IS NOT TRUE
ORDER BY pa.prediction_correct ASC, bb.edge DESC
"
```

**Present the headline first:**

```
BEST BETS SCORECARD: $TARGET_DATE
  Record: W-L (HR%)
  OVER: W-L (HR%) | UNDER: W-L (HR%)
  Rescued: W-L | Normal: W-L
  Ultra: W-L (if any)
```

### 1B: Loss Deep Dive

For each LOSS from the query above, present a detailed breakdown. Pull the player's game stats to understand what happened.

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH losses AS (
  SELECT bb.player_lookup, bb.team_abbr, bb.recommendation, bb.edge,
         bb.line_value, bb.signal_tags, bb.signal_rescued, bb.rescue_signal,
         bb.signal_count, bb.real_signal_count, bb.source_model_family,
         bb.pick_angles, bb.matched_combo_id, bb.player_tier,
         pa.actual_points, pa.predicted_points
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
  JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
    ON bb.player_lookup = pa.player_lookup
    AND bb.game_date = pa.game_date
    AND bb.system_id = pa.system_id
  WHERE bb.game_date = '$TARGET_DATE'
    AND pa.prediction_correct = FALSE
    AND pa.is_voided IS NOT TRUE
)
SELECT
  l.player_lookup,
  l.recommendation,
  ROUND(l.edge, 1) as edge,
  ROUND(l.line_value, 1) as line,
  l.actual_points as actual,
  ROUND(l.predicted_points, 1) as predicted,
  ROUND(l.actual_points - l.line_value, 1) as margin_vs_line,
  l.signal_tags,
  l.signal_rescued,
  l.rescue_signal,
  l.signal_count,
  l.real_signal_count,
  l.source_model_family,
  l.player_tier,
  l.pick_angles,
  -- Player game stats for context
  pgs.points,
  ROUND(pgs.minutes_played, 1) as minutes,
  pgs.fg_makes || '/' || pgs.fg_attempts as fg,
  ROUND(SAFE_DIVIDE(pgs.fg_makes, pgs.fg_attempts) * 100, 1) as fg_pct,
  pgs.three_pt_makes || '/' || pgs.three_pt_attempts as threes,
  pgs.ft_makes || '/' || pgs.ft_attempts as ft,
  pgs.plus_minus,
  pgs.starter_flag
FROM losses l
LEFT JOIN \`nba-props-platform.nba_analytics.player_game_summary\` pgs
  ON l.player_lookup = pgs.player_lookup
  AND pgs.game_date = '$TARGET_DATE'
  AND (pgs.is_dnp IS NULL OR pgs.is_dnp = FALSE)
ORDER BY ABS(l.actual_points - l.line_value) DESC
"
```

### 1C: Loss Pattern Analysis

After reviewing the individual losses, identify common patterns. Run this aggregation:

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH losses AS (
  SELECT bb.*, pa.actual_points, pa.predicted_points,
    CASE
      WHEN bb.line_value >= 22 THEN 'Star'
      WHEN bb.line_value >= 14 THEN 'Starter'
      WHEN bb.line_value >= 6 THEN 'Rotation'
      ELSE 'Bench'
    END as tier
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
  JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
    ON bb.player_lookup = pa.player_lookup
    AND bb.game_date = pa.game_date
    AND bb.system_id = pa.system_id
  WHERE bb.game_date = '$TARGET_DATE'
    AND pa.prediction_correct = FALSE
    AND pa.is_voided IS NOT TRUE
)
SELECT
  -- Game concentration: were losses from same game?
  COUNT(DISTINCT game_id) as games_with_losses,
  COUNT(*) as total_losses,
  -- Direction split
  COUNTIF(recommendation = 'OVER') as over_losses,
  COUNTIF(recommendation = 'UNDER') as under_losses,
  -- Tier split
  COUNTIF(tier = 'Star') as star_losses,
  COUNTIF(tier = 'Starter') as starter_losses,
  COUNTIF(tier = 'Rotation') as rotation_losses,
  COUNTIF(tier = 'Bench') as bench_losses,
  -- Edge band
  COUNTIF(edge < 4) as low_edge_losses,
  COUNTIF(edge >= 4 AND edge < 6) as mid_edge_losses,
  COUNTIF(edge >= 6) as high_edge_losses,
  -- Rescue picks
  COUNTIF(signal_rescued = TRUE) as rescued_losses,
  -- Model family
  STRING_AGG(DISTINCT source_model_family, ', ') as loss_model_families,
  -- Avg prediction error
  ROUND(AVG(ABS(predicted_points - actual_points)), 1) as avg_prediction_error,
  ROUND(AVG(predicted_points - actual_points), 1) as avg_prediction_bias
FROM losses
"
```

**Present the pattern analysis as:**

```
LOSS PATTERNS:
  Game concentration: X losses from Y games [flag if 2+ losses from same game]
  Direction: X OVER, Y UNDER
  Tier: X Star, Y Starter, Z Rotation, W Bench
  Edge: X low (<4), Y mid (4-6), Z high (6+)
  Rescued picks that lost: X
  Prediction bias: +/-X.X (positive = model overestimated)
  [If 2+ losses from same game]: GAME CONCENTRATION — {matchup} accounted for N losses
  [If all losses OVER or all UNDER]: DIRECTIONAL FAILURE — all losses were {direction}
  [If rescued losses > 0]: RESCUE CONCERN — {N} rescued picks lost, review rescue signals
```

Also check if losses were from blowout games:

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH game_scores AS (
  SELECT game_id, ABS(home_team_score - away_team_score) as score_diff,
    CASE WHEN ABS(home_team_score - away_team_score) >= 20 THEN 'BLOWOUT'
         WHEN ABS(home_team_score - away_team_score) >= 10 THEN 'COMFORTABLE'
         ELSE 'COMPETITIVE' END as game_type
  FROM \`nba-props-platform.nba_raw.nbac_schedule\`
  WHERE game_date = '$TARGET_DATE' AND game_status = 3
)
SELECT gs.game_type,
  COUNT(*) as losses_in_game_type,
  ROUND(AVG(gs.score_diff), 0) as avg_score_diff
FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
JOIN game_scores gs ON bb.game_id = gs.game_id
WHERE bb.game_date = '$TARGET_DATE'
  AND pa.prediction_correct = FALSE AND pa.is_voided IS NOT TRUE
GROUP BY 1
"
```

---

## Section 2: Our Picks -- What We Got Right

### 2A: Win Summary

For each WIN, show a brief summary of what worked.

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  bb.player_lookup,
  bb.recommendation,
  ROUND(bb.edge, 1) as edge,
  ROUND(bb.line_value, 1) as line,
  pa.actual_points as actual,
  ROUND(pa.actual_points - bb.line_value, 1) as margin_vs_line,
  bb.signal_count,
  bb.real_signal_count,
  bb.signal_rescued,
  bb.rescue_signal,
  bb.ultra_tier,
  bb.source_model_family,
  bb.player_tier,
  bb.signal_tags,
  bb.matched_combo_id
FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup
  AND bb.game_date = pa.game_date
  AND bb.system_id = pa.system_id
WHERE bb.game_date = '$TARGET_DATE'
  AND pa.prediction_correct = TRUE
  AND pa.is_voided IS NOT TRUE
ORDER BY ABS(pa.actual_points - bb.line_value) DESC
"
```

### 2B: Winning Signal Frequency

Identify which signals appeared most on winning picks.

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH winning_signals AS (
  SELECT signal_tag
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
  JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
    ON bb.player_lookup = pa.player_lookup
    AND bb.game_date = pa.game_date
    AND bb.system_id = pa.system_id,
  UNNEST(bb.signal_tags) as signal_tag
  WHERE bb.game_date = '$TARGET_DATE'
    AND pa.prediction_correct = TRUE
    AND pa.is_voided IS NOT TRUE
),
losing_signals AS (
  SELECT signal_tag
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
  JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
    ON bb.player_lookup = pa.player_lookup
    AND bb.game_date = pa.game_date
    AND bb.system_id = pa.system_id,
  UNNEST(bb.signal_tags) as signal_tag
  WHERE bb.game_date = '$TARGET_DATE'
    AND pa.prediction_correct = FALSE
    AND pa.is_voided IS NOT TRUE
)
SELECT
  COALESCE(w.signal_tag, l.signal_tag) as signal_tag,
  COALESCE(w.win_count, 0) as on_winners,
  COALESCE(l.loss_count, 0) as on_losers,
  ROUND(100.0 * COALESCE(w.win_count, 0) /
    NULLIF(COALESCE(w.win_count, 0) + COALESCE(l.loss_count, 0), 0), 1) as win_pct
FROM (SELECT signal_tag, COUNT(*) as win_count FROM winning_signals GROUP BY 1) w
FULL OUTER JOIN (SELECT signal_tag, COUNT(*) as loss_count FROM losing_signals GROUP BY 1) l
  ON w.signal_tag = l.signal_tag
ORDER BY COALESCE(w.win_count, 0) + COALESCE(l.loss_count, 0) DESC
"
```

**Present as:**

```
SIGNAL SCORECARD (today's picks):
  | Signal          | On Winners | On Losers | Today's Win% |
  |-----------------|------------|-----------|--------------|
  | high_edge       | 4          | 1         | 80.0%        |
  | combo_he_ms     | 2          | 0         | 100.0%       |
  | ...             | ...        | ...       | ...          |
  [Flag signals that appeared only on losers — potential anti-signals for today]
```

---

## Section 3: Biggest Misses -- Players We Should Have Picked

### 3A: Biggest Covers We Missed

Find the 10 players who COVERED their line by the largest margin that we did NOT pick as best bets. This reveals opportunities the system missed.

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH our_picks AS (
  SELECT DISTINCT player_lookup
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\`
  WHERE game_date = '$TARGET_DATE'
),
all_results AS (
  SELECT
    pa.player_lookup,
    pa.system_id,
    pa.recommendation,
    pa.actual_points,
    pa.line_value,
    pa.predicted_points,
    pa.prediction_correct,
    ABS(pa.actual_points - pa.line_value) as cover_margin,
    CASE
      WHEN pa.actual_points > pa.line_value THEN 'OVER'
      WHEN pa.actual_points < pa.line_value THEN 'UNDER'
      ELSE 'PUSH'
    END as actual_direction
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  WHERE pa.game_date = '$TARGET_DATE'
    AND pa.has_prop_line = TRUE
    AND pa.prediction_correct IS NOT NULL
    AND pa.system_id LIKE 'catboost_v12%'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY pa.player_lookup ORDER BY ABS(pa.predicted_points - pa.line_value) DESC) = 1
)
SELECT
  ar.player_lookup,
  ar.actual_direction,
  ar.actual_points,
  ROUND(ar.line_value, 1) as line,
  ROUND(ar.cover_margin, 1) as cover_margin,
  ROUND(ar.predicted_points, 1) as predicted,
  ROUND(ABS(ar.predicted_points - ar.line_value), 1) as our_edge,
  ar.recommendation as our_direction,
  CASE
    WHEN ar.recommendation = ar.actual_direction THEN 'RIGHT_DIRECTION'
    ELSE 'WRONG_DIRECTION'
  END as direction_call,
  pgs.points,
  ROUND(pgs.minutes_played, 1) as minutes,
  pgs.fg_makes || '/' || pgs.fg_attempts as fg,
  pgs.team_abbr,
  pgs.opponent_team_abbr,
  pgs.starter_flag,
  pgs.plus_minus
FROM all_results ar
LEFT JOIN our_picks op ON ar.player_lookup = op.player_lookup
LEFT JOIN \`nba-props-platform.nba_analytics.player_game_summary\` pgs
  ON ar.player_lookup = pgs.player_lookup
  AND pgs.game_date = '$TARGET_DATE'
  AND (pgs.is_dnp IS NULL OR pgs.is_dnp = FALSE)
WHERE op.player_lookup IS NULL  -- NOT in our picks
ORDER BY ar.cover_margin DESC
LIMIT 10
"
```

### 3B: Why We Missed Them -- Signal & Edge Analysis

For the biggest misses, check what signals they had and why they were filtered.

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH our_picks AS (
  SELECT DISTINCT player_lookup
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\`
  WHERE game_date = '$TARGET_DATE'
),
big_covers AS (
  SELECT pa.player_lookup, ABS(pa.actual_points - pa.line_value) as cover_margin,
    CASE WHEN pa.actual_points > pa.line_value THEN 'OVER' ELSE 'UNDER' END as actual_dir
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  LEFT JOIN our_picks op ON pa.player_lookup = op.player_lookup
  WHERE pa.game_date = '$TARGET_DATE'
    AND pa.has_prop_line = TRUE
    AND pa.prediction_correct IS NOT NULL
    AND op.player_lookup IS NULL
    AND pa.system_id LIKE 'catboost_v12%'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY pa.player_lookup ORDER BY ABS(pa.predicted_points - pa.line_value) DESC) = 1
  ORDER BY cover_margin DESC
  LIMIT 10
)
SELECT
  bc.player_lookup,
  bc.actual_dir,
  ROUND(bc.cover_margin, 1) as cover_margin,
  -- Check if they were in signal_best_bets_picks annotation
  pst.signal_tags as available_signals,
  pst.signal_count,
  pst.recommendation as annotated_direction,
  ROUND(pst.edge, 1) as annotated_edge,
  pst.signal_rescued
FROM big_covers bc
LEFT JOIN \`nba-props-platform.nba_predictions.pick_signal_tags\` pst
  ON bc.player_lookup = pst.player_lookup
  AND pst.game_date = '$TARGET_DATE'
ORDER BY bc.cover_margin DESC
"
```

### 3C: Were Any Blocked by Filters?

Check if any of the biggest misses were explicitly filtered out.

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH our_picks AS (
  SELECT DISTINCT player_lookup
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\`
  WHERE game_date = '$TARGET_DATE'
),
big_covers AS (
  SELECT pa.player_lookup
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  LEFT JOIN our_picks op ON pa.player_lookup = op.player_lookup
  WHERE pa.game_date = '$TARGET_DATE'
    AND pa.has_prop_line = TRUE
    AND pa.prediction_correct IS NOT NULL
    AND op.player_lookup IS NULL
    AND pa.system_id LIKE 'catboost_v12%'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY pa.player_lookup ORDER BY ABS(pa.actual_points - pa.line_value) DESC) = 1
  ORDER BY ABS(pa.actual_points - pa.line_value) DESC
  LIMIT 10
)
SELECT
  fp.player_lookup,
  fp.recommendation,
  ROUND(fp.edge, 1) as edge,
  ROUND(fp.line_value, 1) as line,
  fp.filter_reason,
  fp.signal_count,
  fp.signal_tags,
  fp.actual_points,
  fp.prediction_correct as would_have_hit,
  ROUND(fp.actual_points - fp.line_value, 1) as margin
FROM \`nba-props-platform.nba_predictions.best_bets_filtered_picks\` fp
JOIN big_covers bc ON fp.player_lookup = bc.player_lookup
WHERE fp.game_date = '$TARGET_DATE'
ORDER BY ABS(fp.actual_points - fp.line_value) DESC
"
```

**Present as:**

```
BIGGEST MISSES (not in our picks, covered big):
  #1: <player> — OVER/UNDER by X.X pts (actual: X, line: X.X)
      Stats: X pts, X min, X/X FG (X%)
      Our edge: X.X (direction: OVER/UNDER) [RIGHT/WRONG direction]
      Signals: [list] | Why missed: <reason>
      [If filtered]: BLOCKED by <filter_reason> -- WOULD HAVE HIT
  ...

  FILTER FAILURES (blocked picks that would have won):
    <filter_reason>: blocked X picks, Y would have won (Z% CF HR today)
    [Flag any filter that blocked 2+ winners today]
```

---

## Section 4: Injury Impact Analysis

### 4A: Who Was Injured/Out Yesterday?

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  player_name,
  LOWER(REGEXP_REPLACE(player_name, r'[^a-zA-Z]', '')) as player_lookup,
  team_tricode,
  injury_status,
  injury_description
FROM \`nba-props-platform.nba_raw.nbac_injury_report\`
WHERE game_date = '$TARGET_DATE'
  AND UPPER(injury_status) IN ('OUT', 'DOUBTFUL')
ORDER BY team_tricode, player_name
"
```

### 4B: Did Our Picks Have Teammates Injured?

Cross-reference our picks with injury list to check if missing teammates affected outcomes.

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH injuries AS (
  SELECT
    LOWER(REGEXP_REPLACE(player_name, r'[^a-zA-Z]', '')) as injured_player,
    team_tricode,
    injury_status
  FROM \`nba-props-platform.nba_raw.nbac_injury_report\`
  WHERE game_date = '$TARGET_DATE'
    AND UPPER(injury_status) IN ('OUT', 'DOUBTFUL')
),
our_picks AS (
  SELECT bb.player_lookup, bb.team_abbr, bb.recommendation,
         bb.edge, bb.line_value,
         pa.prediction_correct, pa.actual_points
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
  JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
    ON bb.player_lookup = pa.player_lookup
    AND bb.game_date = pa.game_date
    AND bb.system_id = pa.system_id
  WHERE bb.game_date = '$TARGET_DATE'
    AND pa.is_voided IS NOT TRUE
    AND pa.prediction_correct IS NOT NULL
)
SELECT
  op.player_lookup,
  op.recommendation,
  op.prediction_correct as hit,
  op.actual_points,
  ROUND(op.line_value, 1) as line,
  STRING_AGG(i.injured_player, ', ') as injured_teammates,
  COUNT(i.injured_player) as n_teammates_out
FROM our_picks op
JOIN injuries i
  ON op.team_abbr = i.team_tricode
  AND op.player_lookup != i.injured_player
GROUP BY op.player_lookup, op.recommendation, op.prediction_correct,
         op.actual_points, op.line_value
HAVING n_teammates_out > 0
ORDER BY n_teammates_out DESC
"
```

### 4C: Volume Boost Detection -- Big Covers with Injured Teammates

Check if any big covers were by players whose teammates were injured (usage/volume boost opportunity).

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH injuries AS (
  SELECT
    LOWER(REGEXP_REPLACE(player_name, r'[^a-zA-Z]', '')) as injured_player,
    team_tricode
  FROM \`nba-props-platform.nba_raw.nbac_injury_report\`
  WHERE game_date = '$TARGET_DATE'
    AND UPPER(injury_status) = 'OUT'
),
big_covers AS (
  SELECT
    pgs.player_lookup,
    pgs.team_abbr,
    pgs.points,
    pgs.points_line,
    pgs.points - pgs.points_line as margin,
    ROUND(pgs.minutes_played, 1) as minutes,
    pgs.usage_rate,
    pgs.starter_flag
  FROM \`nba-props-platform.nba_analytics.player_game_summary\` pgs
  WHERE pgs.game_date = '$TARGET_DATE'
    AND pgs.points_line IS NOT NULL
    AND pgs.points - pgs.points_line > 5
    AND (pgs.is_dnp IS NULL OR pgs.is_dnp = FALSE)
)
SELECT
  bc.player_lookup,
  bc.team_abbr,
  bc.points,
  bc.points_line as line,
  bc.margin,
  bc.minutes,
  ROUND(bc.usage_rate, 1) as usage_rate,
  bc.starter_flag,
  STRING_AGG(i.injured_player, ', ') as teammates_out,
  COUNT(i.injured_player) as n_out
FROM big_covers bc
JOIN injuries i
  ON bc.team_abbr = i.team_tricode
  AND bc.player_lookup != i.injured_player
GROUP BY bc.player_lookup, bc.team_abbr, bc.points, bc.points_line,
         bc.margin, bc.minutes, bc.usage_rate, bc.starter_flag
ORDER BY bc.margin DESC
LIMIT 10
"
```

### 4D: Opponent Injury Impact

Check if any of our UNDER picks were on teams facing depleted opponents (opponent stars out = easier defense = lower scoring = UNDER should hit more). And vice versa for OVER.

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH injuries AS (
  SELECT
    LOWER(REGEXP_REPLACE(player_name, r'[^a-zA-Z]', '')) as injured_player,
    team_tricode
  FROM \`nba-props-platform.nba_raw.nbac_injury_report\`
  WHERE game_date = '$TARGET_DATE'
    AND UPPER(injury_status) = 'OUT'
),
opponent_injuries AS (
  SELECT team_tricode, COUNT(*) as players_out,
    STRING_AGG(injured_player, ', ') as who_out
  FROM injuries
  GROUP BY 1
)
SELECT
  bb.player_lookup,
  bb.recommendation,
  pa.prediction_correct as hit,
  pa.actual_points,
  ROUND(bb.line_value, 1) as line,
  bb.opponent_team_abbr,
  oi.players_out as opponent_players_out,
  oi.who_out as opponent_who_out
FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` bb
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup
  AND bb.game_date = pa.game_date
  AND bb.system_id = pa.system_id
JOIN opponent_injuries oi
  ON bb.opponent_team_abbr = oi.team_tricode
WHERE bb.game_date = '$TARGET_DATE'
  AND pa.prediction_correct IS NOT NULL
  AND pa.is_voided IS NOT TRUE
ORDER BY oi.players_out DESC
"
```

**Present Section 4 as:**

```
INJURY IMPACT:
  Players OUT/DOUBTFUL: X across Y teams
  Our picks with injured teammates: X (won Y, lost Z)
    [If losses correlate with injuries]: WARNING — N losses had N+ teammates out
  Volume boost covers (OVER by 5+ with teammates out):
    <player>: X pts (line X.X, +X.X margin), N teammates out (<names>)
    [If we missed any of these]: OPPORTUNITY MISSED — injury volume boost not captured
  Opponent depletion:
    <player> <direction>: opponent had N players out — <hit/miss>
    [If UNDER picks vs depleted opponents missed]: NOTE — depleted opponent ≠ automatic UNDER
```

---

## Section 5: Lessons & Patterns

This section synthesizes findings from Sections 1-4. Do NOT run additional queries -- analyze the data already collected.

### 5A: Filter Audit

Summarize all filter-blocked picks that would have won:

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  fp.filter_reason,
  COUNT(*) as total_blocked,
  COUNTIF(fp.prediction_correct = TRUE) as would_have_won,
  COUNTIF(fp.prediction_correct = FALSE) as would_have_lost,
  COUNTIF(fp.prediction_correct IS NULL) as ungraded,
  ROUND(100.0 * COUNTIF(fp.prediction_correct = TRUE) /
    NULLIF(COUNTIF(fp.prediction_correct IS NOT NULL), 0), 1) as cf_hr_today
FROM \`nba-props-platform.nba_predictions.best_bets_filtered_picks\` fp
WHERE fp.game_date = '$TARGET_DATE'
GROUP BY 1
ORDER BY would_have_won DESC
"
```

### 5B: All Filtered Picks That Would Have Won (Detail)

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
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
WHERE fp.game_date = '$TARGET_DATE'
  AND fp.prediction_correct = TRUE
ORDER BY ABS(fp.actual_points - fp.line_value) DESC
LIMIT 15
"
```

### 5C: Model Prediction Bias Check

Was the model systematically over- or under-predicting today?

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  recommendation,
  COUNT(*) as total,
  ROUND(AVG(predicted_points - actual_points), 2) as avg_bias,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as avg_mae,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date = '$TARGET_DATE'
  AND system_id LIKE 'catboost_v12%'
  AND prediction_correct IS NOT NULL
  AND has_prop_line = TRUE
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY recommendation
"
```

---

## Output Format

Assemble the full report in this structure:

```
===============================================
  DAILY AUTOPSY: $TARGET_DATE
  Games: X completed | Best Bets: W-L (HR%)
===============================================

--- SECTION 1: WHAT WE GOT WRONG ---

SCORECARD:
  W-L (HR%) | OVER: W-L | UNDER: W-L
  Rescued: W-L | Ultra: W-L

LOSS DEEP DIVE:
  [For each loss:]
  X. <player> <team> — <OVER/UNDER> <line> (edge: X.X)
     Result: <actual> pts (<margin> vs line)
     Stats: X pts, X min, X/X FG (X%), +/- X
     Signals: [list] | Model: <family>
     Game: <matchup> <score> (<game_type>)
     Why it missed: <analysis>

LOSS PATTERNS:
  <synthesized patterns>

--- SECTION 2: WHAT WE GOT RIGHT ---

WIN HIGHLIGHTS:
  [For each win, brief:]
  - <player> <direction> <line>: actual X (+X.X margin) | signals: [list]

WINNING SIGNALS: <table>

--- SECTION 3: BIGGEST MISSES ---

TOP MISSED COVERS:
  [For each miss:]
  X. <player> — <actual_dir> by X.X pts (actual: X, line: X.X)
     Our edge: X.X (<direction>) — <RIGHT/WRONG direction>
     Why missed: <not enough edge / filtered / wrong direction / no signals>
     [If blocked]: FILTER: <filter_reason> blocked this — WOULD HAVE WON

FILTER FAILURES TODAY:
  <filter_reason>: blocked X winners today (CF HR: X%)
  [Actionable if a filter blocked 2+ winners]

--- SECTION 4: INJURY IMPACT ---

  <injury analysis>

--- SECTION 5: LESSONS & ACTIONABLE INSIGHTS ---

  1. <Lesson with specific evidence from today>
  2. <Lesson with specific evidence>
  ...

  FILTER RECOMMENDATIONS:
    [If any filter blocked 2+ winners]: INVESTIGATE <filter> — blocked N winners today
    [If a filter blocked 0 losers and N winners]: CONSIDER DEMOTING <filter>

  SIGNAL OBSERVATIONS:
    [If a signal was 100% on losers today]: MONITOR <signal> — 0-N today
    [If a signal was 100% on winners today]: VALIDATED <signal> — N-0 today

  MODEL NOTES:
    [If bias > +2]: Model overestimating by X.X pts — may need retrain soon
    [If bias < -2]: Model underestimating by X.X pts — UNDER-heavy predictions expected

===============================================
```

## Key Schema Reminders

- `prediction_accuracy` has NO `edge` column — compute: `ABS(predicted_points - line_value)`
- `prediction_accuracy` has NO `hit` column — use: `prediction_correct`
- `prediction_accuracy` uses `recommendation` (NOT `predicted_direction`)
- Filter: `has_prop_line = TRUE AND recommendation IN ('OVER', 'UNDER') AND prediction_correct IS NOT NULL`
- `signal_best_bets_picks` has its own `system_id` — join on `bb.system_id = pa.system_id`
- `player_game_summary.win_flag` is ALWAYS FALSE — use `plus_minus > 0` as win proxy
- `is_dnp` can be NULL for older records — use `(is_dnp IS NULL OR is_dnp = FALSE)`
- `nba_raw.nbac_schedule` requires partition filter: add `game_date = '$TARGET_DATE'`
- `best_bets_filtered_picks.filter_reason` is a STRING describing which filter blocked the pick

## Parameters

- `date`: Specific date to analyze (default: yesterday). Format: YYYY-MM-DD.
