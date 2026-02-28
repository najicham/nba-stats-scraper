---
name: daily-steering
description: Daily morning report — model health, signal health, best bets performance, and actionable recommendations
---

# Daily Steering Report

You are generating a concise daily steering report for the NBA prediction system. This is a **read-only** diagnostic — no writes, no deployments.

## Your Mission

Produce a single, actionable morning report that answers:
1. Is the model healthy enough to bet today?
2. Are signals working or degraded?
3. How are best bets performing recently?
4. What action (if any) should the user take?
5. Are there any upcoming risk factors (trade deadline, All-Star break, schedule gaps)?

## Step 1: Model Health State

Query `model_performance_daily` for the latest date. Show each model's decay state, rolling HR, and staleness.

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  model_id,
  state,
  ROUND(rolling_hr_7d, 1) AS hr_7d,
  ROUND(rolling_hr_14d, 1) AS hr_14d,
  rolling_n_7d AS n_7d,
  -- Session 366: Directional splits
  ROUND(rolling_hr_over_7d, 1) AS over_7d,
  rolling_n_over_7d AS n_over,
  ROUND(rolling_hr_under_7d, 1) AS under_7d,
  rolling_n_under_7d AS n_under,
  -- Session 366: Best-bets post-filter HR
  ROUND(best_bets_hr_21d, 1) AS bb_hr_21d,
  best_bets_n_21d AS bb_n,
  days_since_training,
  consecutive_days_below_watch AS days_below_watch,
  consecutive_days_below_alert AS days_below_alert
FROM \`nba-props-platform.nba_predictions.model_performance_daily\`
WHERE game_date = (
  SELECT MAX(game_date) FROM \`nba-props-platform.nba_predictions.model_performance_daily\`
)
ORDER BY rolling_hr_7d DESC
"
```

Also check which model is currently driving best bets:

```bash
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)" 2>/dev/null | tr ',' '\n' | grep -E 'BEST_BETS|MODEL'
```

**Present this as:**

```
MODEL HEALTH (as of YYYY-MM-DD):
  <model_id>: <STATE>  <hr_7d>% HR 7d (N=<n_7d>, <days_since_training> days stale) <icon>
    OVER: <over_7d>% (N=<n_over>), UNDER: <under_7d>% (N=<n_under>)
    Best Bets: <bb_hr_21d>% (N=<bb_n>) [if available]
  ...
  Best Bets Model: <current_best_bets_model>
```

State icons: HEALTHY -> OK, WATCH -> eye, DEGRADING -> warning, BLOCKED -> stop, INSUFFICIENT_DATA -> question

## Step 1.5: Edge 5+ Model Health — Best Bets Eligible (Session 335)

Overall model health (edge 3+ HR) can diverge from high-edge performance. A model may be BLOCKED overall but still profitable at edge 5+, or vice versa. This check specifically monitors the best-bets-eligible population.

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH edge5_health AS (
  SELECT
    system_id,
    COUNTIF(prediction_correct) AS wins,
    COUNTIF(NOT prediction_correct) AS losses,
    COUNT(*) AS total,
    ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNT(*), 0), 1) AS hr_edge5_14d,
    ROUND(AVG(ABS(predicted_points - line_value)), 2) AS avg_edge
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
    AND ABS(predicted_points - line_value) >= 5.0
    AND prediction_correct IS NOT NULL
    AND is_voided IS NOT TRUE
    AND (system_id LIKE 'catboost_v9%' OR system_id LIKE 'catboost_v12%')
  GROUP BY 1
  HAVING COUNT(*) >= 5
),
model_state AS (
  SELECT model_id, state, ROUND(rolling_hr_7d, 1) AS overall_hr_7d
  FROM \`nba-props-platform.nba_predictions.model_performance_daily\`
  WHERE game_date = (
    SELECT MAX(game_date) FROM \`nba-props-platform.nba_predictions.model_performance_daily\`
  )
  QUALIFY ROW_NUMBER() OVER (PARTITION BY model_id ORDER BY rolling_n_7d DESC) = 1
),
replacements AS (
  SELECT model_family, COUNT(*) AS family_models,
    MAX(created_at) AS newest_created
  FROM \`nba-props-platform.nba_predictions.model_registry\`
  WHERE enabled = TRUE AND model_family IS NOT NULL
  GROUP BY 1
)
SELECT
  e.system_id,
  ms.state AS overall_state,
  ms.overall_hr_7d,
  e.hr_edge5_14d,
  ROUND(e.hr_edge5_14d - COALESCE(ms.overall_hr_7d, 0), 1) AS edge5_premium,
  e.total AS edge5_n,
  e.avg_edge,
  CASE
    WHEN e.hr_edge5_14d >= 60 THEN 'PROFITABLE'
    WHEN e.hr_edge5_14d >= 52.4 THEN 'MARGINAL'
    ELSE 'LOSING'
  END AS edge5_status
FROM edge5_health e
LEFT JOIN model_state ms ON e.system_id = ms.model_id
ORDER BY e.hr_edge5_14d DESC
"
```

**Present as:**

```
EDGE 5+ MODEL HEALTH (14d, best-bets eligible):
  <system_id>: <edge5_status> <hr_edge5_14d>% (N=<n>, avg edge <avg_edge>) | Overall: <overall_state> <overall_hr_7d>% | Premium: <+/- edge5_premium>pp
  ...
  [If any model is LOSING at edge 5+:]
    WARNING: <model> edge 5+ HR below breakeven — high-edge picks are actively losing money
  [If edge5_premium is negative by 5+ points:]
    NOTE: <model> performs WORSE at high edge than overall — edge magnitude is not a quality signal for this model
```

**Thresholds:**

| Edge 5+ HR | Status | Interpretation |
|------------|--------|---------------|
| >= 60% | PROFITABLE | High-edge picks making money, model safe for best bets |
| 52.4-60% | MARGINAL | Barely profitable, monitor closely |
| < 52.4% | LOSING | High-edge picks losing money, consider excluding from multi-model selection |

**Key insight:** If a model is BLOCKED overall but PROFITABLE at edge 5+, the best-bets filters are working. If a model is LOSING at edge 5+, no amount of filtering will save it — it should be excluded from multi-model selection once a replacement exists.

## Step 2: Signal Health Summary

Query `signal_health_daily` for the latest date. Count regimes and flag COLD model-dependent signals (these are zeroed to 0.0x weight).

```bash
bq query --use_legacy_sql=false --format=pretty "
SELECT
  signal_tag,
  regime,
  ROUND(hr_7d, 1) AS hr_7d,
  ROUND(hr_season, 1) AS hr_season,
  ROUND(divergence_7d_vs_season, 1) AS divergence,
  picks_7d,
  is_model_dependent,
  days_in_current_regime,
  status
FROM \`nba-props-platform.nba_predictions.signal_health_daily\`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
ORDER BY game_date DESC, regime DESC, signal_tag
"
```

Note: Use `game_date >= DATE_SUB(...)` not a subquery — `signal_health_daily` requires a literal partition filter. Results will include multiple dates; use only the most recent game_date rows.

**Present as:**

```
SIGNAL HEALTH:
  N signals tracked: X HOT, Y NORMAL, Z COLD
  COLD: <signal_tag> (model-dependent, zeroed at 0.0x) [if any]
  HOT: <signal_tag> (1.2x), ... [if any]
```

Flag COLD model-dependent signals specifically since they're effectively disabled (0.0x weight per Session 264).

## Step 2.5: Market Regime Early Warning (Session 318)

Detect market compression, edge distribution shifts, and directional imbalances BEFORE they show up in W-L record. This is the leading indicator; best bets HR is the lagging indicator.

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH daily_edge_stats AS (
  SELECT
    game_date,
    MAX(ABS(edge)) AS max_edge,
    COUNTIF(ABS(edge) >= 5.0) AS edge_5plus_count,
    COUNTIF(ABS(edge) >= 3.0) AS edge_3plus_count,
    COUNT(*) AS total_predictions
  FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 35 DAY)
    AND system_id = 'catboost_v12'
    AND is_active = TRUE
  GROUP BY game_date
),
-- Market compression: 7d avg max edge / 30d avg max edge
compression AS (
  SELECT
    ROUND(AVG(CASE WHEN game_date > DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) THEN max_edge END), 2) AS avg_max_edge_7d,
    ROUND(AVG(CASE WHEN game_date > DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) THEN max_edge END), 2) AS avg_max_edge_30d,
    ROUND(
      SAFE_DIVIDE(
        AVG(CASE WHEN game_date > DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) THEN max_edge END),
        AVG(CASE WHEN game_date > DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) THEN max_edge END)
      ), 3
    ) AS market_compression,
    -- Pick volume trend
    ROUND(AVG(CASE WHEN game_date > DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) THEN edge_5plus_count END), 1) AS avg_picks_7d,
    ROUND(AVG(CASE WHEN game_date > DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) THEN edge_5plus_count END), 1) AS avg_picks_30d
  FROM daily_edge_stats
),
-- Directional HR split: trailing 14d
direction_hr AS (
  SELECT
    ROUND(100.0 * COUNTIF(pa.prediction_correct AND p.recommendation = 'OVER')
      / NULLIF(COUNTIF(p.recommendation = 'OVER' AND pa.prediction_correct IS NOT NULL), 0), 1) AS over_hr_14d,
    ROUND(100.0 * COUNTIF(pa.prediction_correct AND p.recommendation = 'UNDER')
      / NULLIF(COUNTIF(p.recommendation = 'UNDER' AND pa.prediction_correct IS NOT NULL), 0), 1) AS under_hr_14d,
    COUNTIF(p.recommendation = 'OVER' AND pa.prediction_correct IS NOT NULL) AS over_n,
    COUNTIF(p.recommendation = 'UNDER' AND pa.prediction_correct IS NOT NULL) AS under_n
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` p
  LEFT JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
    ON p.player_lookup = pa.player_lookup
    AND p.game_date = pa.game_date
    AND p.system_id = pa.system_id
  WHERE p.game_date > DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
),
-- Model residual bias: avg(predicted - actual) over 7d
residual AS (
  SELECT
    ROUND(AVG(pa.predicted_points - pa.actual_points), 2) AS residual_bias_7d,
    COUNT(*) AS residual_n
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  WHERE pa.game_date > DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND pa.system_id = 'catboost_v12'
    AND pa.predicted_points IS NOT NULL
    AND pa.actual_points IS NOT NULL
),
-- 3d rolling HR (best bets)
rolling_3d AS (
  SELECT
    ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNT(*), 0), 1) AS hr_3d,
    COUNT(*) AS n_3d
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\` p
  LEFT JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
    ON p.player_lookup = pa.player_lookup
    AND p.game_date = pa.game_date
    AND p.system_id = pa.system_id
  WHERE p.game_date > DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
    AND pa.prediction_correct IS NOT NULL
)
SELECT
  c.market_compression,
  c.avg_max_edge_7d,
  c.avg_max_edge_30d,
  c.avg_picks_7d,
  c.avg_picks_30d,
  d.over_hr_14d,
  d.under_hr_14d,
  d.over_n,
  d.under_n,
  ABS(COALESCE(d.over_hr_14d, 0) - COALESCE(d.under_hr_14d, 0)) AS direction_divergence,
  r.residual_bias_7d,
  r.residual_n,
  r3.hr_3d,
  r3.n_3d
FROM compression c, direction_hr d, residual r, rolling_3d r3
"
```

**Present as:**

```
MARKET REGIME:
  Compression: <ratio> (<GREEN/YELLOW/RED>)  — 7d avg max edge: <val> / 30d: <val>
  Edge 5+ supply: <7d avg> picks/day (30d: <val>) <GREEN/YELLOW/RED>
  3d rolling HR: <val>% (N=<n>) <GREEN/YELLOW/RED>
  Direction split: OVER <val>% (N=<n>) | UNDER <val>% (N=<n>) — divergence: <val>pp <GREEN/YELLOW/RED>
  Residual bias: <val> pts (7d, N=<n>)
```

**Thresholds:**

| Metric | GREEN | YELLOW | RED |
|--------|-------|--------|-----|
| Market compression | >= 0.85 | 0.65-0.85 | < 0.65 |
| 7d avg max edge | >= 7.0 | 5.0-7.0 | < 5.0 |
| 3d rolling HR | >= 65% | 55-65% | < 55% |
| Daily pick count (7d avg) | >= 3 | 1-3 | < 1 |
| OVER/UNDER HR divergence | <= 15pp | 15-25pp | > 25pp |

**Interpretation:**
- Multiple RED = market is compressed, consider pausing or reducing activity
- Compression RED + HR still GREEN = leading indicator, prepare for downturn
- Direction divergence RED = one direction carrying all the weight, fragile
- Residual bias > +2 or < -2 = model systematically over/under-predicting, may need retrain

## Step 3: Best Bets Performance

Check recent best bets results from `signal_best_bets_picks` joined with `prediction_accuracy`.

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH best_bets AS (
  SELECT game_date, player_lookup, system_id
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
)
SELECT
  bb.game_date,
  COUNT(*) AS picks,
  COUNTIF(pa.prediction_correct) AS wins,
  COUNTIF(NOT pa.prediction_correct) AS losses,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNT(*), 0), 1) AS hr
FROM best_bets bb
LEFT JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup
  AND bb.game_date = pa.game_date
  AND bb.system_id = pa.system_id
WHERE pa.prediction_correct IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC
"
```

Also get a rolling summary:

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH best_bets AS (
  SELECT game_date, player_lookup, system_id
  FROM \`nba-props-platform.nba_predictions.signal_best_bets_picks\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)
SELECT
  'Last 7d' AS period,
  COUNT(*) AS picks,
  COUNTIF(pa.prediction_correct) AS wins,
  COUNTIF(NOT pa.prediction_correct) AS losses,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNT(*), 0), 1) AS hr
FROM best_bets bb
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup
  AND bb.game_date = pa.game_date
  AND bb.system_id = pa.system_id
WHERE pa.prediction_correct IS NOT NULL
  AND bb.game_date > DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

UNION ALL

SELECT
  'Last 14d' AS period,
  COUNT(*) AS picks,
  COUNTIF(pa.prediction_correct) AS wins,
  COUNTIF(NOT pa.prediction_correct) AS losses,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNT(*), 0), 1) AS hr
FROM best_bets bb
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup
  AND bb.game_date = pa.game_date
  AND bb.system_id = pa.system_id
WHERE pa.prediction_correct IS NOT NULL
  AND bb.game_date > DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)

UNION ALL

SELECT
  'Last 30d' AS period,
  COUNT(*) AS picks,
  COUNTIF(pa.prediction_correct) AS wins,
  COUNTIF(NOT pa.prediction_correct) AS losses,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / NULLIF(COUNT(*), 0), 1) AS hr
FROM best_bets bb
JOIN \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
  ON bb.player_lookup = pa.player_lookup
  AND bb.game_date = pa.game_date
  AND bb.system_id = pa.system_id
WHERE pa.prediction_correct IS NOT NULL
"
```

**Present as:**

```
BEST BETS TRACK RECORD:
  Last 7d:  W-L (HR%)
  Last 14d: W-L (HR%)
  Last 30d: W-L (HR%)
```

If no data, note "No best bets data yet — backfill needed or data not graded yet."

## Step 4: Decision Recommendation

Based on the data gathered, recommend ONE of these actions. Reference the steering playbook at `docs/02-operations/runbooks/model-steering-playbook.md` for full decision logic.

### Decision Tree

1. **Is the best bets model BLOCKED?**
   - Yes: Is there a HEALTHY challenger with 56%+ HR 7d and N >= 30?
     - Yes -> **SWITCH** recommendation + command
     - No -> **BLOCKED** — all picks auto-blocked, consider retrain

2. **Is the best bets model DEGRADING?**
   - Yes: Is there a viable challenger?
     - Yes -> **SWITCH** recommendation
     - No -> **RETRAIN** if 30+ days stale, else **WATCH**

3. **Is the best bets model in WATCH?**
   - Yes -> **WATCH** — monitor 2-3 more days, WATCH often self-corrects

4. **Is the best bets model HEALTHY?**
   - Yes, but 30+ days stale -> **RETRAIN** recommended (monthly freshness)
   - Yes, fresh -> **ALL CLEAR**

5. **Cross-model crash?** (2+ models below 40% on same day)
   - Yes -> **MARKET DISRUPTION** — do NOT switch, pause 1 day

### Output Format

```
RECOMMENDATION: <icon> <ACTION>
  <1-2 sentence explanation>
  [If SWITCH:]
    gcloud run services update prediction-worker --region=us-west2 \
      --update-env-vars="BEST_BETS_MODEL_ID=<challenger_id>"
    To validate first: /replay --compare (last 30 days)
  [If RETRAIN:]
    PYTHONPATH=. python ml/experiments/quick_retrain.py \
      --name "V9_<MONTH>_RETRAIN" \
      --train-start 2025-11-02 \
      --train-end <today>
```

## Step 5: Upcoming Risk Factors

Check for schedule gaps, All-Star break, or trade deadline proximity.

```bash
bq query --use_legacy_sql=false --format=pretty "
-- Check upcoming game schedule (next 7 days)
SELECT
  game_date,
  COUNT(*) AS games
FROM \`nba-props-platform.nba_reference.nba_schedule\`
WHERE game_date BETWEEN CURRENT_DATE() AND DATE_ADD(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1
ORDER BY 1
"
```

**Risk factors to flag:**
- No games scheduled for 2+ consecutive days -> break/off-day
- Games resuming after break -> first-day variance may be higher
- Trade deadline proximity (check if within 5 days of mid-February)
- Model staleness approaching 30 days

**Present as:**

```
RISK FACTORS:
  <risk description or "None detected">
  Games schedule: <next 7 days summary>
```

## Step 6: Assemble Final Report

Combine all sections into a clean, scannable report:

```
=== Daily Steering Report ===

MODEL HEALTH (as of YYYY-MM-DD):
  <model lines>
  Best Bets Model: <model_id>

EDGE 5+ MODEL HEALTH (14d):
  <per-model edge-5+ status, premium, warnings>

MARKET REGIME:
  <compression, edge supply, direction split, bias>

RECOMMENDATION: <icon> <ACTION>
  <explanation>
  <commands if applicable>

SIGNAL HEALTH:
  <summary>

BEST BETS TRACK RECORD:
  <W-L summary>

RISK FACTORS:
  <risks or "None detected">

NEXT STEPS:
  1. <primary action>
  2. Run /validate-daily for full pipeline check
  3. <additional context-specific step>
```

## Key Reference

- **Steering playbook:** `docs/02-operations/runbooks/model-steering-playbook.md`
- **Thresholds:** WATCH < 58%, DEGRADING < 55%, BLOCKED < 52.4%
- **Challenger viability:** 56%+ HR 7d, N >= 30
- **Retrain staleness:** 30+ days since training
- **Signal weights:** HOT=1.2x, NORMAL=1.0x, COLD behavioral=0.5x, COLD model-dependent=0.0x
