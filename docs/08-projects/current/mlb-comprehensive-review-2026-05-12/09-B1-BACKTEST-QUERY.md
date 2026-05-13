# B1 — Early-Warning Regime Detector Backtest

**Status:** DESIGN ONLY (Session 2). Build deferred to Session 4.
**Purpose:** Validate that B1 triggers fire ≤ 3 times/season on 2024 and 2025 walk-forward data before deploying. Lane 19 only validated against the May 2026 event; April/June low-N false-positives are a real risk (Agent B caveat).

## Stop condition (from `05-REVISED-PLAN.md`)

If T1 fires > 3 times per season on 2024 OR 2025 historical data → recalibrate thresholds before deploying B1.

## Data prerequisites

`mlb_predictions.prediction_accuracy` does NOT contain 2024/2025 rows (verified 2026-05-13: earliest grade is 2026-04-01). The 4-season replay data exists as CSV output from `scripts/mlb/training/walk_forward_simulation.py` — not currently checked into git, not in BigQuery.

**Required first step (Session 4 morning):** Run walk-forward for 2024 + 2025 seasons, then upload the CSV to a temp BQ table:

```bash
# Step 1 — produce CSVs (uses the same regressor that generates live picks)
PYTHONPATH=. .venv/bin/python3 scripts/mlb/training/walk_forward_simulation.py \
  --start 2024-04-01 --end 2024-10-01 \
  --output-dir results/mlb_walkforward_2024/ \
  --edge-thresholds 0.5,0.75,1.0,1.25

PYTHONPATH=. .venv/bin/python3 scripts/mlb/training/walk_forward_simulation.py \
  --start 2025-04-01 --end 2025-10-01 \
  --output-dir results/mlb_walkforward_2025/ \
  --edge-thresholds 0.5,0.75,1.0,1.25

# Step 2 — combine the per-edge-threshold prediction CSVs into one canonical file
#   (pick the edge tier that matches today's pipeline: --edge >= 0.75 home, >= 1.25 away)
#   resulting CSV columns must include: game_date, recommendation, prediction_correct,
#   edge, line_value, predicted_strikeouts.

# Step 3 — upload to a session-scoped BQ temp table
bq load --replace --source_format=CSV --skip_leading_rows=1 \
  --schema=game_date:DATE,recommendation:STRING,prediction_correct:BOOL,edge:NUMERIC,line_value:NUMERIC,predicted_strikeouts:NUMERIC \
  nba-props-platform:test_mlb_predictions.b1_backtest_wf_2024_2025 \
  results/mlb_walkforward_combined.csv
```

## Backtest query

```sql
-- B1 backtest: simulate T1, T3, T4, and the combined trigger over 2024/2025 walk-forward UNDER picks.
-- Stop condition: combined trigger fires more than 3 times per season → recalibrate before deploy.

WITH daily_under AS (
  SELECT
    game_date,
    EXTRACT(YEAR FROM game_date) AS season,
    COUNTIF(recommendation = 'UNDER') AS daily_n,
    COUNTIF(recommendation = 'UNDER' AND prediction_correct) AS daily_hits
  FROM `nba-props-platform.test_mlb_predictions.b1_backtest_wf_2024_2025`
  WHERE recommendation = 'UNDER'
  GROUP BY game_date
),
-- Rolling 7d window (today + prior 6 calendar days)
rolling_7d AS (
  SELECT
    game_date,
    season,
    SUM(daily_n) OVER w7  AS n_7d,
    SUM(daily_hits) OVER w7 AS hits_7d,
    SAFE_DIVIDE(SUM(daily_hits) OVER w7, SUM(daily_n) OVER w7) AS hr_7d
  FROM daily_under
  WINDOW w7 AS (
    ORDER BY UNIX_DATE(game_date)
    RANGE BETWEEN 6 PRECEDING AND CURRENT ROW
  )
),
-- Rolling 28d mean + stddev for z-score (T4)
rolling_28d AS (
  SELECT
    game_date,
    AVG(hr_7d) OVER w28    AS mean_28d,
    STDDEV(hr_7d) OVER w28 AS std_28d
  FROM rolling_7d
  WINDOW w28 AS (
    ORDER BY UNIX_DATE(game_date)
    RANGE BETWEEN 28 PRECEDING AND 1 PRECEDING
  )
),
-- 1-day-lagged hr_7d for slope (T3 needs 2 days of 7d HR to compute Δ)
lagged AS (
  SELECT
    r.game_date,
    r.season,
    r.n_7d,
    r.hits_7d,
    r.hr_7d,
    LAG(r.hr_7d) OVER (ORDER BY r.game_date) AS hr_7d_prev,
    r28.mean_28d,
    r28.std_28d
  FROM rolling_7d r
  LEFT JOIN rolling_28d r28 USING (game_date)
),
triggered AS (
  SELECT
    game_date,
    season,
    n_7d,
    hr_7d,
    hr_7d_prev,
    mean_28d,
    std_28d,
    -- T1: 7d HR < 50% with N >= 25
    (n_7d >= 25 AND hr_7d < 0.50) AS t1_fired,
    -- T3: 7d slope < -2pp/day (Δhr_7d < -0.02 vs yesterday)
    (hr_7d_prev IS NOT NULL AND (hr_7d - hr_7d_prev) < -0.02) AS t3_fired,
    -- T4: z-score vs 28d baseline < -2
    (std_28d IS NOT NULL AND std_28d > 0
      AND SAFE_DIVIDE(hr_7d - mean_28d, std_28d) < -2.0) AS t4_fired
  FROM lagged
),
deduped AS (
  -- Edge-detect: only count a fire on the FIRST day the combined trigger is TRUE
  -- after at least one prior false day. Avoids counting a multi-day cluster as N fires.
  SELECT
    season,
    game_date,
    (t1_fired OR (t3_fired AND t4_fired))      AS combined_fired,
    LAG(t1_fired OR (t3_fired AND t4_fired)) OVER (ORDER BY game_date) AS prev_fired,
    t1_fired,
    t3_fired AND t4_fired AS t3t4_fired
  FROM triggered
)
SELECT
  season,
  COUNTIF(combined_fired AND NOT IFNULL(prev_fired, FALSE)) AS combined_fires,
  COUNTIF(t1_fired AND NOT IFNULL(LAG(t1_fired) OVER (PARTITION BY season ORDER BY game_date), FALSE)) AS t1_fires,
  COUNTIF(t3t4_fired AND NOT IFNULL(LAG(t3t4_fired) OVER (PARTITION BY season ORDER BY game_date), FALSE)) AS t3t4_fires
FROM deduped
GROUP BY season
ORDER BY season;
```

## Expected output shape

```
+--------+----------------+----------+-------------+
| season | combined_fires | t1_fires | t3t4_fires  |
+--------+----------------+----------+-------------+
|   2024 |              ? |        ? |           ? |
|   2025 |              ? |        ? |           ? |
+--------+----------------+----------+-------------+
```

**Pass:** Both seasons show `combined_fires ≤ 3` → deploy B1 as designed.
**Fail:** Either season > 3 → recalibrate. Likely options:
- Tighten T1 N floor (25 → 35) — April/June games are sparse, 25 is too thin
- Tighten T3 slope (-2pp → -3pp) — daily HR noise can produce a -2pp swing by chance at N≤30
- Require BOTH T1 AND (T3 OR T4) instead of T1 OR (T3 AND T4) — Lane 19's "belt-and-suspenders" combined trigger is OR-based; AND-based combined trigger is stricter

## Spot-check query (for Session 4)

For each season, list the dates where the combined trigger fired and dump the surrounding 7d HR sequence:

```sql
WITH /* same CTE chain as above */
SELECT
  game_date,
  season,
  ROUND(100.0 * hr_7d, 1)        AS hr_7d_pct,
  ROUND(100.0 * hr_7d_prev, 1)   AS hr_7d_prev_pct,
  ROUND(100.0 * mean_28d, 1)     AS mean_28d_pct,
  ROUND(std_28d, 4)              AS std_28d,
  n_7d,
  t1_fired, t3_fired, t4_fired
FROM triggered
WHERE t1_fired OR (t3_fired AND t4_fired)
ORDER BY game_date;
```

Visual inspection: do the fires line up with periods we KNOW (from MLB history) were rough for UNDER picks? June 2024 had a notable hot-bat stretch; April 2025 was cold for K-overs. Both should fire SOMETHING. If the trigger NEVER fires, thresholds are too loose, not too tight.

## What gets built (Session 4, not now)

- `bin/monitoring/mlb_daily_performance.py` gets a `direction_regime_monitor()` function that runs the same trigger logic on yesterday's `prediction_accuracy` rows and writes to Slack `#mlb-betting-signals`.
- Cloud Scheduler entry: `mlb-regime-monitor-daily` at 09:00 UTC (post-grading).
- State machine: trigger STATE persists in a new `mlb_orchestration.direction_regime_state` table so we don't double-alert on consecutive days.

## Why not build this in Session 2

The roadmap explicitly defers B1 build to Session 4. The reason: the trigger thresholds were calibrated on RMSE+sigmoid output (current regressor). A4 (Poisson model, Session 3) may shift the underlying HR distribution, which would force a re-calibration anyway. Backtesting BEFORE A4 ships locks in thresholds that may need re-tuning. Backtesting AFTER A4 ships uses the post-Poisson output and produces stable thresholds.

Session 2's job is just to write down the backtest design so Session 4 can execute it without re-deriving.
