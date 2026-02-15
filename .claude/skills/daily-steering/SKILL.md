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
  ...
  Best Bets Model: <current_best_bets_model>
```

State icons: HEALTHY -> OK, WATCH -> eye, DEGRADING -> warning, BLOCKED -> stop, INSUFFICIENT_DATA -> question

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
WHERE game_date = (
  SELECT MAX(game_date) FROM \`nba-props-platform.nba_predictions.signal_health_daily\`
)
ORDER BY regime DESC, signal_tag
"
```

**Present as:**

```
SIGNAL HEALTH:
  N signals tracked: X HOT, Y NORMAL, Z COLD
  COLD: <signal_tag> (model-dependent, zeroed at 0.0x) [if any]
  HOT: <signal_tag> (1.2x), ... [if any]
```

Flag COLD model-dependent signals specifically since they're effectively disabled (0.0x weight per Session 264).

## Step 3: Best Bets Performance

Check recent best bets results from `current_subset_picks` joined with `prediction_accuracy`.

```bash
bq query --use_legacy_sql=false --format=pretty "
WITH best_bets AS (
  SELECT game_date, player_lookup, system_id
  FROM \`nba-props-platform.nba_predictions.current_subset_picks\`
  WHERE subset_id = 'best_bets'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
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
  FROM \`nba-props-platform.nba_predictions.current_subset_picks\`
  WHERE subset_id = 'best_bets'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
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
