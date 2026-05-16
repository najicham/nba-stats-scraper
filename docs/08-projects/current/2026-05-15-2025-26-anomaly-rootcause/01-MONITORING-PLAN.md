# Monitoring + Prevention Plan — 2025-26 Anomaly Follow-up

**Date:** 2026-05-15
**Status:** v2 — Tier 1 implemented + recalibrated after false-positive validation.
**Companion to:** [00-FINDINGS.md](00-FINDINGS.md) (the diagnosis)

> **v2 update (2026-05-15 evening):** Initial 1.5 K `pred_bias_7d` alert threshold
> failed false-positive validation — would fire on ~60% of healthy 2024-25 days
> due to chronic ~2 K bias. Switched primary trigger to `mae_gap_7d` which
> cleanly separates anomalous (median 1.44 K) from healthy (0.39 K). `pred_bias`
> columns retained as diagnostics only.

## 1. What we observed (the season-level facts)

The 2025-26 NBA collapse was the result of three converging factors. Each one is now a thing we plan to detect and prevent independently.

### Observation 1 — Scoring regimes drift between seasons

League scoring rose ~1 K per player between 2024-25 and 2025-26.

| Window | avg_actual | avg_line |
|---|---|---|
| 2024-11 to 2025-04 | 12.0–12.5 K | 11.9–12.6 K |
| 2025-11 to 2026-02 | 13.2–13.8 K | 13.1–13.6 K |

Vegas adjusted lines accordingly (line_bias stayed near 0). Our model did not (pred_bias went to -2.23 K in Nov 2025).

**Implication:** Pre-season retraining is mandatory. A fleet trained on April data is structurally biased going into October of the next season.

### Observation 2 — The model has a persistent under-prediction bias

`pred_bias` (avg of `predicted_points - actual_points`) has been negative every month back to Oct 2024. Magnitude:

| Period | Avg pred_bias |
|---|---|
| 2024-25 mid-season | -1.0 to -1.7 K |
| 2024-25 late season | -1.8 to -2.0 K |
| **2025-11 (worst)** | **-2.23 K** |
| 2025-26 mid-season | -0.7 to -1.1 K |

This is a chronic, fleet-wide bias — not a per-model bug. Likely from training-data construction (player-game samples skew toward complete games, missing tail of high-scoring outbursts), but the root mechanism isn't necessary to fix it.

**Implication:** Bias is detectable from `prediction_accuracy` data day-of. We can monitor it and alert before HR collapses.

### Observation 3 — Vegas can tighten faster than us

`vegas_mae_7d` reached a 2-year low of **4.33 K** in Nov 2025, vs 5.00 K in Nov 2024.

| Window | vegas_mae_7d |
|---|---|
| 2024-11 | 5.00 |
| 2024-12 to 2025-04 | 4.61–4.77 |
| **2025-11** | **4.33** |
| 2025-12 to 2026-02 | 4.71–4.97 |

When Vegas tightens by ~0.7 K, our edge versus Vegas vanishes even at constant model accuracy. The `mae_gap` (model_mae − vegas_mae) flipped from -0.51 (Nov 2024) to +1.10 (Nov 2025) — a 1.61 K swing, of which ~42% came from Vegas tightening.

**Implication:** The market-efficiency signal (`mae_gap`) is the right early-warning indicator. The edge-based auto-halt (Session 515) already uses average edge; we should add a Vegas-quality dimension.

### Observation 4 — The fleet has no built-in adaptation

Until 2026-03-09, no automated retrain mechanism existed:
- `monthly-retrain` was deprecated with no replacement
- `weekly-retrain` CF didn't exist
- Manual `./bin/retrain.sh` was the only path

Result: the Nov-Dec 2025 fleet stayed on training data ending around April 2025 (the previous season's end). When Jan 2026 hit, fleet expansion via experimental shadow models couldn't compensate — every model degraded simultaneously (`catboost_v8` HR: 66.9% → 47.8% across Dec-Feb, same code, same weights).

**Implication:** `weekly-retrain` is necessary but not sufficient. We need a season-start cold boot and explicit guarantees about training-data recency.

## 2. Future plans (ranked by leverage)

### Tier 1 — Required before next NBA season (Oct 2026)

These are deal-breakers. Without them, we will repeat the 2025-26 collapse.

#### 1.1 Pre-season cold-boot retrain (target: 2026-10-15)
- New one-shot cron: trigger a full fleet retrain on Oct 15 using preseason + first-week regular season data
- Use `weekly_retrain` CF infrastructure with a one-time `--training-end auto` override
- Acceptance: all enabled models have `training_end_date >= 2026-10-08` by Oct 18

#### 1.2 Verify `weekly-retrain` runs year-round (no in-season gating)
- Inspect Cloud Scheduler entry for `weekly-retrain`. Confirm cron `0 10 * * 1` (Monday 5 AM ET) has no month restriction
- Acceptance: scheduler config + last 4 weeks of successful runs (or a test run if off-season)

#### 1.3 `pred_bias_7d` per-model monitoring
- Add columns to `model_performance_daily`: `pred_bias_7d`, `pred_bias_14d`, `pred_bias_30d`
- Slack alert to `#nba-betting-signals` when `|pred_bias_7d| > 1.5 K` for any enabled model with `rolling_n_7d >= 20`
- Acceptance: backfilled across 2025-26 season; Nov 2025 fleet trips the alert in the historical replay

### Tier 2 — Highly recommended (Q3 2026)

These add resilience and catch failure modes earlier.

#### 2.1 `mae_gap_7d` model-vs-Vegas monitoring
- Already partially exists in `league_macro_daily` (Vegas vs fleet aggregate). Promote to per-model:
- Add columns to `model_performance_daily`: `model_mae_7d`, `model_mae_14d`, `vegas_mae_7d`, `vegas_mae_14d`, `mae_gap_7d`, `mae_gap_14d`
- Alert when `mae_gap_7d > 0.5 K` for 7 consecutive days (per-model). This generalizes the existing edge-based auto-halt to a continuous metric.

#### 2.2 Daily Bayesian calibration layer
- For each model, learn a single bias correction `c_t` from the last N=10 days of (predicted, actual) pairs: `c_t = mean(actual - predicted)`
- Apply post-prediction: `corrected_pred = raw_pred + c_t`. Use corrected value for edge computation
- Re-fit nightly. Doesn't fix variance; neutralizes drift while waiting for retrains
- Estimated effort: ~1 day. Implementation in `predictions/worker.py` post-prediction hook

#### 2.3 Training-data recency gate
- Reject any model from the active fleet if `training_end_date < (today - 21 days)`
- Currently models can stay live indefinitely. The 21-day floor would have flagged Nov 2025 models within 3 weeks of season start
- Implementation: enforce in `model_registry sync` or in the worker's model-loading path

#### 2.4 Fleet-diversity monitor (catches Phase 2 of the 2025-26 collapse)
The bias/mae_gap monitor catches the Nov 2025 regime-shift phase. It does **not**
catch the Jan/Feb 2026 collapse phase, which was driven by fleet diversity
collapse (Session 487 finding: enabled fleet was all LGBM clones at r >= 0.95)
plus edge compression. To close this gap, add a separate monitor:

- New CF: `bin/monitoring/fleet_diversity_monitor.py`
- Inputs:
  - `model_registry` (enabled fleet)
  - `prediction_accuracy` last 21 days (per-prediction predicted_points)
- Per-pair correlation: compute Pearson r between every pair of enabled models'
  predicted_points on common (player, game) keys
- Alert thresholds:
  - **WATCH**: max-pair r >= 0.95 AND fleet size >= 3
  - **DEGRADED**: median-pair r >= 0.95 (most of fleet is clones)
- Mitigation playbook in alert: "Promote 1 non-LGBM model from shadow", or
  "Disable N-1 of the high-r cluster to force diversity"
- Estimated effort: 0.5 day

This explicitly addresses the second mechanism behind 2026-Jan/Feb HR collapse
(per 00-FINDINGS.md updated narrative: "fleet diversity collapse + edge
compression").

### Tier 3 — Nice to have

#### 3.1 Auto-disable on bias drift
- Currently `decay-detection` auto-disables on HR < 52.4%. Add a parallel trigger: auto-disable on `|pred_bias_7d| > 2.0 K` for 7 consecutive days
- Captures models that are diverging from the regime even before HR catches up

#### 3.2 Pre-season scoring-environment validation
- New CF/script that runs Oct 1: compute `avg_actual` of preseason games (Sep-Oct), compare to training data `avg_actual`. Alert if difference > 0.5 K
- Catches regime shifts before they hit production picks

## 3. What to monitor — operational spec

This is the spec for the Tier 1 implementation. Designed to fit the existing pattern in `ml/analysis/model_performance.py` (which runs daily after grading, populated by `post-grading-export` CF per Session 474).

### 3.1 New columns in `model_performance_daily`

```sql
-- Per-model bias metrics (computed from prediction_accuracy where ABS(predicted - line) >= 3,
--  same edge filter as existing rolling_hr_*)
pred_bias_7d        FLOAT  -- AVG(predicted_points - actual_points), last 7 days
pred_bias_14d       FLOAT
pred_bias_30d       FLOAT

-- Per-model accuracy metrics
model_mae_7d        FLOAT  -- AVG(ABS(predicted_points - actual_points))
model_mae_14d       FLOAT
model_mae_30d       FLOAT

-- Per-model Vegas comparison (line is identical across models for a given player/game, so vegas_mae
--  computed only over (player, game_date, line_value) tuples this model predicted on)
vegas_mae_7d        FLOAT  -- AVG(ABS(line_value - actual_points))
vegas_mae_14d       FLOAT
vegas_mae_30d       FLOAT

-- Derived: model_mae - vegas_mae. Positive = model worse than Vegas
mae_gap_7d          FLOAT
mae_gap_14d         FLOAT
mae_gap_30d         FLOAT
```

All NULLABLE. All FLOAT. No new partitioning/clustering changes — table is already partitioned by `game_date`.

### 3.2 Computation logic (additions to existing daily_results CTE)

```sql
-- Add to model_date_stats CTE in compute_for_date():
AVG(CASE WHEN game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)
         THEN predicted_points - actual_points END) AS pred_bias_7d,
AVG(CASE WHEN game_date > DATE_SUB(@target_date, INTERVAL 14 DAY)
         THEN predicted_points - actual_points END) AS pred_bias_14d,
AVG(predicted_points - actual_points) AS pred_bias_30d,

AVG(CASE WHEN game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)
         THEN ABS(predicted_points - actual_points) END) AS model_mae_7d,
AVG(CASE WHEN game_date > DATE_SUB(@target_date, INTERVAL 14 DAY)
         THEN ABS(predicted_points - actual_points) END) AS model_mae_14d,
AVG(ABS(predicted_points - actual_points)) AS model_mae_30d,

AVG(CASE WHEN game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)
         THEN ABS(line_value - actual_points) END) AS vegas_mae_7d,
AVG(CASE WHEN game_date > DATE_SUB(@target_date, INTERVAL 14 DAY)
         THEN ABS(line_value - actual_points) END) AS vegas_mae_14d,
AVG(ABS(line_value - actual_points)) AS vegas_mae_30d
```

The `daily_results` CTE already pulls all needed columns (`predicted_points`, `actual_points`, `line_value`) — no source query changes needed. **Schema update first, then code update**; the daily CF will populate forward from the next run.

### 3.3 Backfill plan

```bash
# After schema additions are deployed:
PYTHONPATH=. .venv/bin/python3 ml/analysis/model_performance.py --backfill --start 2025-11-02
```

The existing backfill path re-computes for every `game_date` in range. ~6 months of data, ~6,000 (model × date) rows. Should run in 5-10 minutes.

Acceptance: query `model_performance_daily` for `game_date >= 2025-11-02` and confirm `pred_bias_7d` is non-NULL for at least 90% of rows. Validate the Nov 2025 fleet shows `pred_bias_7d ≈ -2.0 to -2.5 K`.

### 3.4 Alert spec (v2 — recalibrated)

**New monitor:** `bin/monitoring/bias_decay_monitor.py` (mirrors `signal_decay_monitor.py`).

**Primary trigger:** `mae_gap_7d` (model_mae_7d − vegas_mae_7d). Validated against
5 seasons:

| Period | Median `mae_gap_7d` |
|---|---|
| 2024-25 healthy | 0.39 K |
| 2025-11 anomaly | 1.44 K |
| 2025-12 recovery | 0.69 K |
| 2026 collapse | 1.26 K |

Trigger conditions (most severe wins):
- `LOSING_BAD`: `mae_gap_7d > 2.0 K` on >=3 of last 5 days → urgent Slack
- `LOST_EDGE`:  `mae_gap_7d > 1.0 K` on >=5 of last 7 days → standard Slack
- `WATCH`:      `mae_gap_7d > 0.5 K` single day (no Slack, report only)
- `HEALTHY`:    everything below
- `INSUFFICIENT_DATA`: `rolling_n_7d < 20` OR `mae_gap_7d IS NULL`

**Not used for alerts:** `pred_bias_7d`. Per-model bias is structurally noisy
(2024-25 healthy median |pred_bias_7d| = 2.19 K, p90 = 4.99 K — chronic).
`pred_bias_*` columns are still persisted in `model_performance_daily` as
diagnostic metrics surfaced in the admin dashboard and useful for
investigation, but they do not by themselves trigger Slack.

Slack message template (auto-formatted in `build_slack_message()`):
```
:warning: Bias Decay Monitor — 2026-05-15

:chart_with_downwards_trend: LOST_EDGE (2)
  • `catboost_v12_noveg_train1205_0403`: LOST_EDGE: mae_gap_7d=+1.45 K
    (model_mae − vegas_mae) on 5 of last 7 days — Vegas is sharper
  • `lgbm_v12_noveg_train0206_0402`: ...

_Recommended action: `./bin/retrain.sh MODEL_ID --enable` or
`python bin/deactivate_model.py MODEL_ID`._
```

Channel: `#nba-betting-signals` (same as `signal_decay_monitor`).

Cadence: daily 11:30 AM ET (post-grading). Reuse the existing
`filter-counterfactual-evaluator` Cloud Function pattern — same scheduler
infrastructure, separate CF wrapping `http_handler` in
`bin/monitoring/bias_decay_monitor.py`. **Scheduler not yet provisioned**;
provision next.

### 3.5 Dashboards / queries (no extra infra)

After implementation, these queries become useful for ad-hoc inspection. Document in `docs/02-operations/useful-queries.md`:

```sql
-- Daily bias check across enabled models
SELECT model_id, pred_bias_7d, model_mae_7d, vegas_mae_7d, mae_gap_7d, rolling_n_7d, state
FROM `nba-props-platform.nba_predictions.model_performance_daily`
WHERE game_date = CURRENT_DATE() - 1
  AND model_id IN (SELECT model_id FROM `nba-props-platform.nba_predictions.model_registry` WHERE enabled)
ORDER BY ABS(pred_bias_7d) DESC;

-- Historical bias trajectory for a single model
SELECT game_date, pred_bias_7d, model_mae_7d, vegas_mae_7d, mae_gap_7d
FROM `nba-props-platform.nba_predictions.model_performance_daily`
WHERE model_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
ORDER BY game_date;
```

## 4. Design decisions (resolved)

All decisions below are resolved as of 2026-05-15 evening.

1. ~~**Threshold value (|pred_bias_7d| > 1.5 K)**~~ — **REJECTED after validation.**
   Per-model `pred_bias_7d` is too noisy (chronic ~2 K bias in healthy 2024-25).
   Primary alert now uses `mae_gap_7d` instead. `pred_bias_*` retained as
   diagnostics in BQ. (Section 3.4 v2.)

2. **Min N for alert (rolling_n_7d >= 20):** kept. Below this is too noisy.

3. **Edge filter inclusion (`ABS(predicted_points - line_value) >= 3`):** kept.
   Bias on actionable predictions is what matters.

4. **Tier 2.2 calibration layer:** deferred to follow-up — kept this batch
   monitor-only. Calibration changes live predictions (interacts with edge-based
   auto-halt and OVER edge 6.0 floor); separate decision.

5. **Alert auto-disable:** alert-only, no auto-disable in this batch. Matches
   `signal_decay_monitor` pattern.

6. **(New) Fleet-diversity monitor:** added as Tier 2.4 to catch Jan/Feb-style
   collapse. Separate follow-up implementation (0.5 day est.).

## 5. Estimated effort

| Item | Effort |
|---|---|
| Tier 1.1 — pre-season retrain trigger | 0.5 day (clone weekly_retrain config) |
| Tier 1.2 — verify weekly-retrain schedule | 15 min |
| Tier 1.3 — pred_bias monitoring (this batch) | 1 day total: 2h schema + code, 1h backfill, 2h monitor script + Slack, 1h test |
| Tier 2.1 — mae_gap monitoring | +2h (alongside 1.3 if combined) |
| Tier 2.2 — calibration layer | 1-2 days |
| Tier 2.3 — recency gate | 0.5 day |

Tier 1 total (the right-now ask): **~1.5 days** including backfill verification.
