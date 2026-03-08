---
name: mlb-autopsy
description: Post-mortem of MLB pitcher strikeout predictions — what went wrong, early hooks, velocity drops, weather effects, biggest misses
---

# MLB Pitcher Strikeout Autopsy

You are performing a comprehensive post-mortem analysis of MLB pitcher strikeout predictions for a specific date. This is a **read-only** diagnostic.

## Your Mission

Produce a thorough autopsy that answers:
1. What did we get wrong, and WHY did the pitcher miss their K line?
2. What went right — what patterns predicted K outcomes well?
3. Who CRUSHED their K line that we did NOT pick?
4. What environmental factors (weather, ballpark, lineup) drove outcomes?
5. What actionable lessons can improve our model or filters?

## Target Date Logic

Default to **yesterday** (most recent completed game day). If the user provides a date argument, use that instead.

```bash
TARGET_DATE=$(date -d "yesterday" +%Y-%m-%d)
echo "MLB Autopsy for: $TARGET_DATE"
```

If the user passes a date argument (e.g., `/mlb-autopsy 2025-09-15`), use that date instead.

**IMPORTANT:** Before proceeding, verify games were played and graded:

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  '$TARGET_DATE' as target_date,
  (SELECT COUNT(*) FROM \`nba-props-platform.mlb_raw.mlb_schedule\`
   WHERE game_date = '$TARGET_DATE' AND is_final = TRUE) as games_final,
  (SELECT COUNT(*) FROM \`nba-props-platform.mlb_predictions.signal_best_bets_picks\`
   WHERE game_date = '$TARGET_DATE') as best_bets_picks,
  (SELECT COUNT(*) FROM \`nba-props-platform.mlb_predictions.prediction_accuracy\`
   WHERE game_date = '$TARGET_DATE' AND prediction_correct IS NOT NULL) as graded_predictions,
  (SELECT COUNT(*) FROM \`nba-props-platform.mlb_analytics.pitcher_game_summary\`
   WHERE game_date = '$TARGET_DATE') as pitcher_summaries
"
```

If `games_final = 0`: Report "No completed MLB games on $TARGET_DATE" and exit.
If `graded_predictions = 0`: Report "Games not yet graded" and exit.
If `best_bets_picks = 0`: Proceed with Section 3 only (biggest misses from raw predictions).

---

## Section 1: Our Picks — What We Got Wrong

### 1A: Full Scorecard

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  bb.player_lookup as pitcher,
  bb.team_abbr,
  bb.opponent_team_abbr as opp,
  bb.recommendation as dir,
  ROUND(bb.edge, 2) as edge,
  ROUND(bb.line_value, 1) as k_line,
  pa.prediction_correct as hit,
  CAST(pa.actual_points AS INT64) as actual_k,
  ROUND(pa.actual_points - bb.line_value, 1) as margin,
  ROUND(pa.predicted_points, 1) as predicted_k,
  pgs.innings_pitched as ip,
  pgs.pitch_count as pitches,
  pgs.walks_allowed as bb_allowed,
  pgs.hits_allowed as hits,
  pgs.earned_runs as er,
  CASE WHEN pgs.innings_pitched < 5.0 THEN 'EARLY_HOOK' ELSE '' END as hook_flag,
  pgs.days_rest
FROM \`nba-props-platform.mlb_predictions.signal_best_bets_picks\` bb
JOIN \`nba-props-platform.mlb_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup
  AND bb.game_date = pa.game_date
  AND bb.system_id = pa.system_id
LEFT JOIN \`nba-props-platform.mlb_analytics.pitcher_game_summary\` pgs
  ON LOWER(REGEXP_REPLACE(NORMALIZE(pgs.player_lookup, NFD), r'[\\\\W_]+', '')) =
     LOWER(REGEXP_REPLACE(NORMALIZE(bb.player_lookup, NFD), r'[\\\\W_]+', ''))
  AND pgs.game_date = bb.game_date
WHERE bb.game_date = '$TARGET_DATE'
  AND pa.prediction_correct IS NOT NULL
  AND pa.is_voided IS NOT TRUE
ORDER BY pa.prediction_correct ASC, bb.edge DESC
"
```

**Present the headline:**

```
MLB BEST BETS SCORECARD: $TARGET_DATE
  Record: W-L (HR%)
  OVER: W-L | UNDER: W-L
  Early hooks: X pitchers pulled before 5 IP
```

### 1B: Loss Deep Dive — WHY Did They Miss?

For each LOSS, categorize the root cause:

**Root Cause Categories:**
1. **EARLY_HOOK** — Pitcher pulled before 5.0 IP (fewer K opportunities)
2. **WALK_FEST** — 4+ walks ate into K opportunities (more pitches on non-K outcomes)
3. **VELOCITY_DROP** — Fastball velocity down 1+ mph vs recent average
4. **EFFICIENT_CONTACT** — Low SwStr% (batters making contact, not swinging through)
5. **BLOWOUT** — Game out of hand, pitcher pulled or eased off
6. **LINE_TOO_HIGH** — Actual Ks were reasonable, but line was inflated
7. **COLD_PITCHER** — Below recent rolling averages across the board

For each loss, join with statcast data:

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH losses AS (
  SELECT bb.player_lookup, bb.recommendation, bb.edge, bb.line_value,
         pa.actual_points as actual_k, pa.predicted_points,
         bb.team_abbr, bb.opponent_team_abbr
  FROM \`nba-props-platform.mlb_predictions.signal_best_bets_picks\` bb
  JOIN \`nba-props-platform.mlb_predictions.prediction_accuracy\` pa
    ON bb.player_lookup = pa.player_lookup
    AND bb.game_date = pa.game_date
    AND bb.system_id = pa.system_id
  WHERE bb.game_date = '$TARGET_DATE'
    AND pa.prediction_correct = FALSE
    AND pa.is_voided IS NOT TRUE
)
SELECT
  l.player_lookup,
  l.recommendation as dir,
  CAST(l.actual_k AS INT64) as actual_k,
  ROUND(l.line_value, 1) as k_line,
  ROUND(l.actual_k - l.line_value, 1) as margin,
  ROUND(l.edge, 2) as edge,
  -- Pitcher game stats
  pgs.innings_pitched as ip,
  pgs.pitch_count as pitches,
  pgs.walks_allowed as walks,
  pgs.hits_allowed as hits,
  pgs.earned_runs as er,
  pgs.quality_start,
  pgs.days_rest,
  -- Rolling context
  ROUND(pgs.k_avg_last_5, 1) as k_avg_5,
  ROUND(pgs.k_avg_last_10, 1) as k_avg_10,
  ROUND(pgs.k_per_9_rolling_10, 1) as k_per_9,
  -- Statcast (if available)
  ROUND(sc.swstr_pct, 3) as swstr_pct,
  ROUND(sc.csw_pct, 3) as csw_pct,
  ROUND(sc.whiff_pct, 3) as whiff_pct,
  ROUND(sc.fb_velocity_avg, 1) as fb_velo,
  -- Root cause classification
  CASE
    WHEN pgs.innings_pitched < 5.0 THEN 'EARLY_HOOK'
    WHEN pgs.walks_allowed >= 4 THEN 'WALK_FEST'
    WHEN sc.fb_velocity_avg IS NOT NULL
      AND sc.fb_velocity_avg < COALESCE(pgs.season_swstr_pct, 0) THEN 'VELOCITY_DROP'
    WHEN sc.swstr_pct IS NOT NULL AND sc.swstr_pct < 0.08 THEN 'EFFICIENT_CONTACT'
    WHEN pgs.earned_runs >= 5 THEN 'BLOWOUT'
    WHEN l.actual_k >= pgs.k_avg_last_5 AND l.actual_k < l.line_value THEN 'LINE_TOO_HIGH'
    ELSE 'COLD_PITCHER'
  END as root_cause
FROM losses l
LEFT JOIN \`nba-props-platform.mlb_analytics.pitcher_game_summary\` pgs
  ON LOWER(REGEXP_REPLACE(NORMALIZE(pgs.player_lookup, NFD), r'[\\\\W_]+', ''))
    = LOWER(REGEXP_REPLACE(NORMALIZE(l.player_lookup, NFD), r'[\\\\W_]+', ''))
  AND pgs.game_date = '$TARGET_DATE'
LEFT JOIN \`nba-props-platform.mlb_raw.statcast_pitcher_game_stats\` sc
  ON REPLACE(pgs.player_lookup, '_', '') = REPLACE(sc.player_lookup, '_', '')
  AND sc.game_date = '$TARGET_DATE'
ORDER BY ABS(l.actual_k - l.line_value) DESC
"
```

**Present each loss as:**

```
LOSS DEEP DIVE:
  X. <pitcher> (<team> vs <opp>) — <OVER/UNDER> <k_line> (edge: X.XX)
     Result: X K in X.X IP (X pitches) | Line: X.5 | Margin: -X.X
     Root cause: <EARLY_HOOK/WALK_FEST/etc.>
     Context: K avg(5): X.X, K/9: X.X | Walks: X, Hits: X, ER: X
     Statcast: SwStr% X.X%, Velo X.X mph, Whiff% X.X%
     Why: <1-2 sentence explanation>
```

### 1C: Loss Pattern Summary

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH losses AS (
  SELECT bb.*, pa.actual_points as actual_k, pa.predicted_points,
    pgs.innings_pitched, pgs.walks_allowed, pgs.earned_runs
  FROM \`nba-props-platform.mlb_predictions.signal_best_bets_picks\` bb
  JOIN \`nba-props-platform.mlb_predictions.prediction_accuracy\` pa
    ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
  LEFT JOIN \`nba-props-platform.mlb_analytics.pitcher_game_summary\` pgs
    ON LOWER(REGEXP_REPLACE(NORMALIZE(pgs.player_lookup, NFD), r'[\\\\W_]+', ''))
      = LOWER(REGEXP_REPLACE(NORMALIZE(bb.player_lookup, NFD), r'[\\\\W_]+', ''))
    AND pgs.game_date = bb.game_date
  WHERE bb.game_date = '$TARGET_DATE'
    AND pa.prediction_correct = FALSE AND pa.is_voided IS NOT TRUE
)
SELECT
  COUNT(*) as total_losses,
  COUNTIF(recommendation = 'OVER') as over_losses,
  COUNTIF(recommendation = 'UNDER') as under_losses,
  COUNTIF(innings_pitched < 5.0) as early_hooks,
  COUNTIF(walks_allowed >= 4) as walk_fests,
  COUNTIF(earned_runs >= 5) as blowout_pulled,
  ROUND(AVG(predicted_points - actual_k), 2) as avg_prediction_bias,
  ROUND(AVG(ABS(predicted_points - actual_k)), 2) as avg_prediction_error,
  ROUND(AVG(innings_pitched), 1) as avg_ip_losses
FROM losses
"
```

---

## Section 2: What We Got Right

### 2A: Win Summary

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  bb.player_lookup as pitcher,
  bb.recommendation as dir,
  CAST(pa.actual_points AS INT64) as actual_k,
  ROUND(bb.line_value, 1) as k_line,
  ROUND(pa.actual_points - bb.line_value, 1) as margin,
  ROUND(bb.edge, 2) as edge,
  pgs.innings_pitched as ip,
  pgs.pitch_count as pitches,
  ROUND(pgs.k_per_9_rolling_10, 1) as k_per_9
FROM \`nba-props-platform.mlb_predictions.signal_best_bets_picks\` bb
JOIN \`nba-props-platform.mlb_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date AND bb.system_id = pa.system_id
LEFT JOIN \`nba-props-platform.mlb_analytics.pitcher_game_summary\` pgs
  ON LOWER(REGEXP_REPLACE(NORMALIZE(pgs.player_lookup, NFD), r'[\\\\W_]+', ''))
    = LOWER(REGEXP_REPLACE(NORMALIZE(bb.player_lookup, NFD), r'[\\\\W_]+', ''))
  AND pgs.game_date = bb.game_date
WHERE bb.game_date = '$TARGET_DATE'
  AND pa.prediction_correct = TRUE AND pa.is_voided IS NOT TRUE
ORDER BY ABS(pa.actual_points - bb.line_value) DESC
"
```

**Present briefly:**
```
WINS:
  - <pitcher> <dir> <k_line>: <actual_k> K in <ip> IP (+<margin> margin, edge <edge>)
```

---

## Section 3: Biggest Misses — Pitchers We Should Have Picked

### 3A: Biggest K Line Covers We Didn't Pick

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH our_picks AS (
  SELECT DISTINCT player_lookup
  FROM \`nba-props-platform.mlb_predictions.signal_best_bets_picks\`
  WHERE game_date = '$TARGET_DATE'
),
all_results AS (
  SELECT
    pa.player_lookup,
    pa.recommendation,
    CAST(pa.actual_points AS INT64) as actual_k,
    pa.line_value as k_line,
    pa.predicted_points,
    ABS(pa.actual_points - pa.line_value) as cover_margin,
    CASE WHEN pa.actual_points > pa.line_value THEN 'OVER' ELSE 'UNDER' END as actual_dir,
    pa.prediction_correct
  FROM \`nba-props-platform.mlb_predictions.prediction_accuracy\` pa
  WHERE pa.game_date = '$TARGET_DATE'
    AND pa.has_prop_line = TRUE
    AND pa.prediction_correct IS NOT NULL
    AND pa.is_voided IS NOT TRUE
  QUALIFY ROW_NUMBER() OVER (PARTITION BY pa.player_lookup ORDER BY ABS(pa.predicted_points - pa.line_value) DESC) = 1
)
SELECT
  ar.player_lookup as pitcher,
  ar.actual_dir,
  ar.actual_k,
  ROUND(ar.k_line, 1) as k_line,
  ROUND(ar.cover_margin, 1) as cover_margin,
  ROUND(ar.predicted_points, 1) as our_predicted,
  ROUND(ABS(ar.predicted_points - ar.k_line), 2) as our_edge,
  ar.recommendation as our_dir,
  CASE WHEN ar.recommendation = ar.actual_dir THEN 'RIGHT' ELSE 'WRONG' END as dir_call,
  -- Game context
  pgs.innings_pitched as ip,
  pgs.pitch_count as pitches,
  pgs.opponent_team_abbr as opp,
  ROUND(pgs.k_per_9_rolling_10, 1) as k_per_9,
  pgs.days_rest
FROM all_results ar
LEFT JOIN our_picks op ON ar.player_lookup = op.player_lookup
LEFT JOIN \`nba-props-platform.mlb_analytics.pitcher_game_summary\` pgs
  ON LOWER(REGEXP_REPLACE(NORMALIZE(pgs.player_lookup, NFD), r'[\\\\W_]+', ''))
    = LOWER(REGEXP_REPLACE(NORMALIZE(ar.player_lookup, NFD), r'[\\\\W_]+', ''))
  AND pgs.game_date = '$TARGET_DATE'
WHERE op.player_lookup IS NULL
ORDER BY ar.cover_margin DESC
LIMIT 10
"
```

**Present as:**
```
BIGGEST MISSES (not picked, covered big):
  X. <pitcher> vs <opp> — <actual_dir> by X.X (actual: X K, line: X.5)
     X.X IP, X pitches | K/9(10): X.X | Rest: Xd
     Our edge: X.XX (<our_dir>) — <RIGHT/WRONG direction>
     Why missed: <not enough edge / wrong direction / filtered out>
```

### 3B: Why We Missed — Edge & Direction Analysis

Analyze the misses:
- **WRONG_DIRECTION**: Model predicted the opposite direction — model blind spot
- **LOW_EDGE**: Right direction but edge below threshold — line was close to fair
- **FILTERED**: Had enough edge but was filtered out
- **NOT_IN_PROPS**: No prop line available for this pitcher

---

## Section 4: Environmental Analysis

### 4A: Weather Impact

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  pgs.player_lookup as pitcher,
  CAST(pgs.strikeouts AS INT64) as actual_k,
  pgs.strikeouts_line as k_line,
  ROUND(gw.temperature_f, 0) as temp_f,
  ROUND(gw.wind_speed_mph, 0) as wind_mph,
  gw.wind_direction,
  ROUND(gw.humidity_pct, 0) as humidity,
  gw.weather_condition,
  ROUND(gw.overall_k_factor, 3) as k_factor,
  pgs.venue
FROM \`nba-props-platform.mlb_analytics.pitcher_game_summary\` pgs
LEFT JOIN \`nba-props-platform.mlb_raw.game_weather\` gw
  ON pgs.game_date = gw.game_date
  AND pgs.team_abbr = gw.team_abbr
WHERE pgs.game_date = '$TARGET_DATE'
  AND gw.temperature_f IS NOT NULL
ORDER BY gw.overall_k_factor DESC
"
```

**Flag extreme conditions:**
- Temperature < 50F or > 95F
- Wind > 15 mph
- K-factor significantly above/below 1.0
- Rain/weather delays

### 4B: Innings Pitched Distribution

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  CASE
    WHEN innings_pitched < 4.0 THEN 'Short (<4 IP)'
    WHEN innings_pitched < 5.0 THEN 'Early Hook (4-5 IP)'
    WHEN innings_pitched < 6.0 THEN 'Normal (5-6 IP)'
    WHEN innings_pitched < 7.0 THEN 'Quality (6-7 IP)'
    ELSE 'Deep (7+ IP)'
  END as ip_bucket,
  COUNT(*) as pitchers,
  ROUND(AVG(strikeouts), 1) as avg_k,
  ROUND(AVG(pitch_count), 0) as avg_pitches
FROM \`nba-props-platform.mlb_analytics.pitcher_game_summary\`
WHERE game_date = '$TARGET_DATE'
GROUP BY 1
ORDER BY MIN(innings_pitched)
"
```

### 4C: Opponent Lineup K Rate

Check if opposing lineups were unusually contact-heavy or K-prone:

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  pgs.player_lookup as pitcher,
  pgs.opponent_team_abbr as opp,
  CAST(pgs.strikeouts AS INT64) as actual_k,
  ROUND(pgs.opponent_team_k_rate, 3) as opp_k_rate,
  CASE
    WHEN pgs.opponent_team_k_rate > 0.25 THEN 'K-PRONE'
    WHEN pgs.opponent_team_k_rate < 0.20 THEN 'CONTACT-HEAVY'
    ELSE 'AVERAGE'
  END as opp_type,
  pgs.innings_pitched as ip
FROM \`nba-props-platform.mlb_analytics.pitcher_game_summary\` pgs
WHERE pgs.game_date = '$TARGET_DATE'
  AND pgs.opponent_team_k_rate IS NOT NULL
ORDER BY pgs.opponent_team_k_rate DESC
"
```

---

## Section 5: Model Performance & Lessons

### 5A: Model Prediction Bias

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  recommendation,
  COUNT(*) as total,
  COUNTIF(prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
  ROUND(AVG(predicted_points - actual_points), 2) as avg_bias,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as avg_mae
FROM \`nba-props-platform.mlb_predictions.prediction_accuracy\`
WHERE game_date = '$TARGET_DATE'
  AND prediction_correct IS NOT NULL
  AND has_prop_line = TRUE
  AND recommendation IN ('OVER', 'UNDER')
  AND is_voided IS NOT TRUE
GROUP BY recommendation
"
```

### 5B: K Environment Check

Was today's K environment unusual?

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH today AS (
  SELECT
    AVG(strikeouts) as avg_k_today,
    AVG(innings_pitched) as avg_ip_today,
    AVG(SAFE_DIVIDE(strikeouts * 9, innings_pitched)) as avg_k9_today,
    COUNT(*) as starters_today
  FROM \`nba-props-platform.mlb_analytics.pitcher_game_summary\`
  WHERE game_date = '$TARGET_DATE'
    AND innings_pitched >= 3.0
),
season AS (
  SELECT
    AVG(strikeouts) as avg_k_season,
    AVG(innings_pitched) as avg_ip_season,
    AVG(SAFE_DIVIDE(strikeouts * 9, innings_pitched)) as avg_k9_season
  FROM \`nba-props-platform.mlb_analytics.pitcher_game_summary\`
  WHERE game_date BETWEEN DATE_SUB('$TARGET_DATE', INTERVAL 30 DAY) AND '$TARGET_DATE'
    AND innings_pitched >= 3.0
)
SELECT
  ROUND(t.avg_k_today, 1) as avg_k_today,
  ROUND(s.avg_k_season, 1) as avg_k_30d,
  ROUND(t.avg_k_today - s.avg_k_season, 1) as k_delta,
  ROUND(t.avg_ip_today, 1) as avg_ip_today,
  ROUND(s.avg_ip_season, 1) as avg_ip_30d,
  ROUND(t.avg_k9_today, 1) as k9_today,
  ROUND(s.avg_k9_season, 1) as k9_30d,
  t.starters_today
FROM today t, season s
"
```

---

## Output Format

```
===============================================
  MLB AUTOPSY: $TARGET_DATE
  Games: X final | Best Bets: W-L (HR%)
===============================================

--- SECTION 1: WHAT WE GOT WRONG ---

SCORECARD:
  W-L (HR%) | OVER: W-L | UNDER: W-L
  Early hooks: X | Walk fests: X | Blowout pulls: X

LOSS DEEP DIVE:
  [For each loss with root cause and stats]

LOSS PATTERNS:
  Avg prediction bias: +/-X.XX K
  Most common root cause: <EARLY_HOOK/WALK_FEST/etc.>

--- SECTION 2: WHAT WE GOT RIGHT ---

  [Brief win summary]

--- SECTION 3: BIGGEST MISSES ---

  [Top 5-10 covers we didn't pick, with why we missed them]

--- SECTION 4: ENVIRONMENT ---

  K Environment: X.X K/game today (vs X.X 30d avg)
  Weather flags: [any extreme conditions]
  IP distribution: X early hooks, X normal, X deep starts

--- SECTION 5: LESSONS ---

  1. <Lesson with specific evidence>
  2. <Lesson with specific evidence>
  ...

  MODEL NOTES:
    [If bias > +0.5 K]: Model overestimating Ks — consider UNDER tilt
    [If bias < -0.5 K]: Model underestimating Ks — consider OVER tilt
    [If multiple early hooks]: EARLY_HOOK filter opportunity — X losses from <5 IP games

  FEATURE IDEAS:
    [If weather drove outcomes]: Consider weather K-factor as model feature
    [If lineup quality mattered]: Track opponent lineup K-rate changes
    [If velocity drops correlated with misses]: Velocity trend signal potential
===============================================
```

## Key Schema Reminders

- `mlb_predictions.prediction_accuracy` — graded predictions. `prediction_correct`, `actual_points` (=K), `predicted_points`, `line_value`, `recommendation`
- `mlb_predictions.signal_best_bets_picks` — our best bets. Has `system_id`, `edge`, `line_value`, `player_lookup`
- `mlb_analytics.pitcher_game_summary` — game stats. `strikeouts`, `innings_pitched`, `pitch_count`, `walks_allowed`, `k_avg_last_5`, `k_per_9_rolling_10`, `vs_opponent_k_per_9`
- `mlb_raw.statcast_pitcher_game_stats` — pitch metrics. `swstr_pct`, `csw_pct`, `whiff_pct`, `fb_velocity_avg`
- `mlb_raw.game_weather` — environment. `temperature_f`, `wind_speed_mph`, `overall_k_factor`
- Player lookup JOIN: `LOWER(REGEXP_REPLACE(NORMALIZE(player_lookup, NFD), r'[\\W_]+', ''))`
- Best bets `system_id` must match on JOIN with prediction_accuracy

## Parameters

- `date`: Specific date to analyze (default: yesterday). Format: YYYY-MM-DD.
