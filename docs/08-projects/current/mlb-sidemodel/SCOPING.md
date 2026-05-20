# MLB binary side-model — scoping (2026-05-19)

Path B from the 5/18-3 strategic plan. The regressor's `edge → sigmoid → p_over`
has near-zero binary predictive power (45.2% HR at edge 1.0-1.5 OVER, sigmoid claims
67%). Calibrators can't add signal — a separate side-model with the actual feature
vector might. This document is the spec; nothing here trains a model yet.

## SLICE 2 EXECUTION RESULT — DEAD END (2026-05-19)

**Slice 2 trained the artifact and it did NOT pass governance. No side-model was
deployed. `MLB_SIDEMODEL_PATH` stays unset; `pitcher_strikeouts.p_sidemodel`
stays NULL.** The two training scripts are committed; no artifact was produced.

### What ran
- `scripts/mlb/training/build_sidemodel_training_set.py` → `/tmp/mlb_sidemodel_training.csv`
  - 753 graded `catboost_v2_regressor` picks queried (Apr 2 → May 18, 2026)
  - 0 skipped (pitcher_lookup formats matched cleanly), 22 dropped (a predictor
    core feature was null on reconstruction) → **731 training rows**
  - Win rate 51.0% (OVER 461 @ 49.9%, UNDER 270 @ 53.0%) — clean class balance
- `scripts/mlb/training/train_sidemodel_v1.py`
  - Chronological 75/25 split: train 505 rows (Apr 2 → May 7), test 226 rows
    (May 8 → May 18)
  - 17 features: 15 raw `load_batch_features` columns + `recommendation_OVER/_UNDER`

### Feature-set deviation from the Step 2 spec (and why)
The Step 2 shortlist named `edge`, `fip`, `gb_pct`. None are in the model:
- **`edge` / `predicted_strikeouts` excluded** — the slice-1 worker calls
  `sidemodel.score(features, recommendation)` where `features` is *only* the
  `load_batch_features` dict; it never passes regressor outputs. A model needing
  `edge` would return `None` for every pick. `edge` is still loaded into the CSV
  and used to compute the sigmoid baseline.
- **`fip` / `gb_pct` excluded** — 95.9% coverage. `binary_v1.score()` returns
  `None` on *any* missing feature, so a sub-100% feature silently drops shadow
  rows. The deployed set is restricted to the regressor's zero-tolerance CORE
  features (all 100% coverage on the 731 rows).

### Results (test set, N=226)

| Model | Brier | LogLoss | AUC | OVER Brier | UNDER Brier |
|---|---|---|---|---|---|
| Sigmoid baseline | 0.2610 | 0.7158 | 0.517 | 0.250 | 0.283 |
| Logistic | 0.2742 | 0.7452 | 0.419 | 0.258 | 0.306 |
| LightGBM | 0.2531 | 0.6994 | 0.511 | 0.248 | 0.263 |

### Governance verdict — DEAD END
- **Brier-improvement gate (≥0.01 vs sigmoid): FAILED by both.** LightGBM came
  closest (+0.0079); logistic was *worse* than sigmoid (−0.0132).
- **AUC gate (≥0.55): FAILED by both.** LightGBM 0.511, logistic 0.419. Both
  have essentially zero ranking power. Logistic's sub-0.5 AUC means it overfit
  the 505-row train set into anti-signal.
- LightGBM passed direction-stability and calibration; logistic failed all four
  non-trivial gates.

**Interpretation.** The feature vector carries no extractable binary signal
about "will this pick win" beyond what the (already weak) edge captures.
LightGBM's marginal Brier edge is pure calibration — it predicts near the 51%
base rate instead of the sigmoid's overconfident ~67% — not discrimination.
~500 training rows against a sharp market line is too thin for a side-model to
find residual signal.

### Open questions from the spec — resolved
1. `load_batch_features` is called **once per game_date** (one BQ query
   returning all pitchers), exactly as the worker calls it. The training-set
   builder loops dates with one call each — no extra caching needed.
2. LightGBM hyperparameters used: `n_estimators=100, num_leaves=15,
   learning_rate=0.05`, early stopping (20 rounds) on the last 15% of train
   dates. Not worth tuning further given the AUC ≈ 0.50 floor.
3. `sidemodel_version` — moot; no artifact shipped.

### Revisit trigger
Re-run `build_sidemodel_training_set.py` + `train_sidemodel_v1.py` (idempotent,
no code changes needed) when **either**:
- graded `catboost_v2_regressor` volume reaches **N ≥ 1500** (roughly end of the
  2026 season — ~2× the current 731), giving the models a real chance at weak
  signal; **or**
- `pitcher_loader.load_batch_features` starts serving genuinely new feature
  families (weather, batter-level K-rate) the regressor does not already
  consume — those, not re-slicing the existing vector, are the only plausible
  source of new binary signal.

Until then: no artifact, `MLB_SIDEMODEL_PATH` unset, and the slice-3 CF analysis
script is NOT built (it needs ≥100 graded shadow rows, which cannot accrue
without an artifact).

## Verified data ground truth (as of 2026-05-19)

Source: `nba-props-platform.mlb_predictions.prediction_accuracy`
- Date range: 2026-04-01 → 2026-05-18 (regressor was the only enabled production
  system for this window after the V1 classifier decommission)
- Total graded picks: **753** (`has_prop_line = TRUE AND prediction_correct IS NOT NULL
  AND recommendation IN ('OVER','UNDER') AND system_id = 'catboost_v2_regressor'`)
- Wins/losses: **383 / 370** (50.86% raw HR — well balanced for a binary target)
- OVER: 482 picks @ 49.6% HR, avg edge +0.51 K
- UNDER: 271 picks @ 53.1% HR, avg edge -0.38 K
- Voided: 0 (the MIN_IP=0.33 grading change in `2026-05-18-2` left no voids in this
  window)

Class balance is excellent. N=753 is small but workable for logistic regression /
shallow LightGBM with 8-12 features.

## Feature inventory — what `pitcher_loader.load_batch_features` actually serves

This is the prediction-time feature set used by `catboost_v2_regressor_predictor.py`
today. The training set will reconstruct it point-in-time per (game_date, pitcher_lookup).

From `predictions/mlb/pitcher_loader.py:load_batch_features` (the function called by
the worker at prediction time):

**Core rolling/season (always present, zero-tolerance in current predictor):**
- `k_avg_last_3`, `k_avg_last_5`, `k_avg_last_10`, `k_std_last_10`, `ip_avg_last_5`
- `season_k_per_9` (cross-season-guarded, see Session 523), `era_rolling_10`,
  `whip_rolling_10`, `season_games_started`, `season_strikeouts`, `season_innings`
- `is_home`, `is_postseason`, `is_day_game`, `days_rest`
- `opponent_team_k_rate`, `ballpark_k_factor`
- `month_of_season`, `days_into_season`
- `avg_k_vs_opponent`, `games_vs_opponent`
- `games_last_30_days`, `pitch_count_avg_last_5`

**Statcast rolling (NaN-tolerant in predictor, frequently null early-season):**
- `swstr_pct_last_3`, `fb_velocity_last_3`, `swstr_trend`, `velocity_change`
- `season_swstr_pct`, `season_csw_pct`

**Line-derived (joined from `bp_pitcher_props` with `oddsa_pitcher_props` fallback):**
- `k_avg_vs_line` (`k_avg_last_5 - line_level`)
- `bp_projection`, `projection_diff`
- `strikeouts_line` (line_level), `over_implied_prob`

**FanGraphs advanced (NaN-tolerant, NULL until ~May per memory):**
- `o_swing_pct`, `z_contact_pct`, `fip`, `gb_pct`

**Pitcher matchup / workload derived:**
- `vs_opp_k_per_9`, `vs_opp_games`, `k_per_pitch`, `recent_workload_ratio`

The training set reconstructs all of these via the existing loader. No new BQ
plumbing required for inputs — but see the "Training-set reconstruction" section
below for the per-date loop.

### Spec called for some extras we do not have

The 5/18-3 spec mentioned `weather` and `batter_k_rate`. `pitcher_loader` does
not serve either today:
- **Weather**: `mlb_raw.mlb_weather` exists (operational since 2026-05-17 per
  memory) but is not joined in `load_batch_features`. Adding it is plumbing
  work — out of scope for the first side-model pass.
- **Batter-level `batter_k_rate`**: would require lineup data
  (`mlb_raw.mlb_lineup_batters`) which is spotty (8/14 days in recent sample)
  and the lineup_k_analysis processor table is empty (memory entry, 2026-05-13
  diagnostic). Skip for v1.
- **`opponent_k_rate`**: already covered by `opponent_team_k_rate` above.

First side-model uses ONLY features `pitcher_loader` already serves. No new
upstream pipelines.

## Smallest shippable thing (the actual ask)

**Goal**: emit a shadow `p_sidemodel` per pick, alongside today's `p_over`,
without changing pick generation. Once N≥100 graded picks accumulate, compare
side-model probability against actual outcomes via Brier / reliability /
top-K rerank simulation. If side-model wins, *then* talk about wiring it into
the filter pipeline or rank step.

The "smallest shippable" version is three pieces:

### 1. BQ column add (one DDL)
Add to `nba-props-platform.mlb_predictions.pitcher_strikeouts`:
- `p_sidemodel FLOAT NULLABLE`
- `sidemodel_version STRING NULLABLE`

The worker (`predictions/mlb/worker.py` row-build at ~L905) starts writing
both. NULL when no side-model is loaded — safe rollout.

### 2. Side-model artifact + loader

Mirror the existing predictor pattern:
- New file: `predictions/mlb/sidemodel/binary_v1.py`
- Loads a pickle from GCS at `MLB_SIDEMODEL_PATH` env var (unset → no-op)
- Single public method: `score(features: dict, recommendation: str) -> float | None`
  - Returns `P(prediction_correct=True | features, recommendation)`
  - Returns `None` if any feature is missing OR if the side-model isn't loaded
- Symmetric to `CatBoostV2RegressorPredictor` in shape but trained on a
  different target

The worker (around L130-200 where each system is initialized) instantiates
the side-model once at startup, then in the prediction loop:
```python
p_sm = sidemodel.score(features, pred['recommendation']) if sidemodel else None
pred['p_sidemodel'] = p_sm
pred['sidemodel_version'] = sidemodel.version if sidemodel else None
```

The BB exporter is **not modified** in this slice — `p_sidemodel` is purely
written-through to BQ.

### 3. Shadow CF analysis script

New file: `scripts/mlb/sidemodel_cf_analysis.py`
- Joins `pitcher_strikeouts` (has `p_sidemodel`) with `prediction_accuracy`
  (has `prediction_correct`) on (game_date, pitcher_lookup, system_id) once
  N≥100 graded shadow picks exist
- Computes Brier(`p_sidemodel`) vs Brier(today's sigmoid `p_over`)
- Reliability diagram at 10 bins
- Rerank simulation: if BB had picked top-N by `p_sidemodel` instead of by
  edge magnitude, what would HR have been?
- Filter simulation: requiring `p_sidemodel ≥ T` for various T, how many BB
  picks remain and at what HR?

This is the gate that decides whether to wire the side-model into BB.

## Training pipeline (executed in next session, not this one)

### Step 1 — Build training CSV

`scripts/mlb/training/build_sidemodel_training_set.py`:
1. Query `prediction_accuracy` for the graded-pick keys (game_date,
   pitcher_lookup, system_id, recommendation, edge, line_value,
   predicted_strikeouts, prediction_correct).
2. Group by `game_date`. For each date, call
   `pitcher_loader.load_batch_features(date, pitcher_lookups)` and join
   the feature dicts back to the picks by `pitcher_lookup`.
3. Drop rows where any "core" feature is null (mirror predictor's
   zero-tolerance for inputs).
4. Write to `/tmp/mlb_sidemodel_training.csv` with columns:
   - meta: `game_date, pitcher_lookup, system_id, recommendation`
   - target: `outcome` (1 if prediction_correct else 0)
   - features: all features served by `load_batch_features` listed above
   - regressor outputs as features: `edge, predicted_strikeouts, line_value`

Approx run time: 49 game-dates × one BQ query/date ≈ 4-6 min. Cacheable.

### Step 2 — Train (single file)

`scripts/mlb/training/train_sidemodel_v1.py`:
1. Load CSV.
2. **Chronological split**: train = first 75% of dates, test = last 25%.
   With dates Apr 1 → May 18, train ≈ Apr 1 → May 5, test ≈ May 6 → May 18.
3. Reuse `brier_score`, `log_loss`, `reliability_bins` from
   `isotonic_calibration_analysis.py` for evaluation.
4. **Two candidate models**, both fit on train, evaluated on test:
   - Logistic regression with the ~12 strongest hand-picked features
     (k_avg_last_5, k_std_last_10, edge, line_level, k_avg_vs_line,
     opponent_team_k_rate, ballpark_k_factor, days_rest,
     pitch_count_avg, season_k_per_9, fip, gb_pct), one-hot
     `recommendation`, NaN imputed by per-feature median.
   - Small LightGBM (n_estimators=100, num_leaves=15, learning_rate=0.05,
     early_stopping by 20 rounds on a 15% validation slice carved from
     train). Handles NaN natively.
5. Report Brier / log-loss / AUC / reliability for both, **plus** the
   today's-sigmoid baseline computed from `edge` via SIGMOID_SCALE=0.7
   (so we have a head-to-head against what the system actually does today).
6. If best candidate's test Brier improves over sigmoid baseline by ≥0.01,
   pickle it to `gs://nba-props-platform-ml-models/mlb/sidemodel/binary_v1_{date}.pkl`
   with metadata (training rows, date span, feature list, val/test metrics).
7. If neither candidate beats sigmoid on test — **stop**. Document the
   dead end and revisit when more data accumulates or with a different
   feature set.

### Governance gates (must pass before shadow deploy)

These adapt the NBA gates from `quick_retrain.py` to the side-model:

| Gate | Threshold | Why |
|---|---|---|
| Class balance | 0.4 ≤ train win-rate ≤ 0.6 | We've already verified this (50.9%) but re-check after any feature filter that drops rows |
| Test Brier improvement | ≥ 0.01 better than sigmoid baseline | Smaller and the side-model is noise |
| Test AUC | ≥ 0.55 | Below this and ranking by p_sidemodel is no better than random |
| OVER and UNDER stability | Each direction's test Brier improves OR is within 0.005 | If side-model helps one direction and hurts the other equally, no net signal |
| Calibration (reliability) | No bin with N≥10 deviates >15pp from diagonal | Don't deploy a confidently miscalibrated probability |

If the model passes, it ships behind the env-var flag (still NULL until
`MLB_SIDEMODEL_PATH` is set on the worker).

## Promotion criterion — when does shadow become real?

After **≥100 graded shadow picks** (N=100 from `pitcher_strikeouts` rows
with `p_sidemodel IS NOT NULL` joined to `prediction_accuracy` with
`prediction_correct IS NOT NULL`):

1. `sidemodel_cf_analysis.py` must show: actual-Brier(p_sidemodel) ≤
   actual-Brier(sigmoid-from-edge), with the gap ≥ 0.01 and consistent
   across OVER/UNDER splits.
2. Rerank simulation: if BB top-K is rebuilt sorting by p_sidemodel
   instead of |edge|, HR improves by ≥3pp at equal pick volume.
3. If both pass, propose adding `p_sidemodel >= T` as an observation-mode
   filter in `ml/signals/mlb/best_bets_exporter.py`. CF Phase 1 then
   tracks it the same way the existing filters get tracked. Promotion to
   active block requires the standard observation-period evidence
   (N≥10 over 5 days at the MLB-tuned eligibility bar from Path B in
   the 5/18-3 plan — TBD by that work).

## What this scoping pass intentionally does NOT decide

- Whether to add weather/lineup features (deferred — out of scope until
  `pitcher_loader` serves them natively)
- Whether to use a side-model for UNDER-only or OVER-only (decided post-hoc
  from the per-direction Brier breakdown)
- The exact LightGBM hyperparameters beyond "small" (left for the training
  session to tune by val curve)
- Whether to ever wire the side-model into pick ranking (gated on
  promotion-criterion data)

## Open questions for the executing session

1. Does the worker call `load_batch_features` once per worker invocation
   or per pitcher? Confirm before the training-set builder loops — if
   per-date is already cached, the builder is cleaner.
2. The 5/18-3 handoff mentioned 729 graded picks; today shows 753. Likely
   the spec was written before the most recent grading run. Just a sanity
   note — N is still in the same ballpark.
3. Should `sidemodel_version` follow the NBA model registry pattern
   (`bin/model-registry.sh`)? Probably not — NBA registry is wired into
   prediction_worker and a lot of orchestration. Side-model is a single
   binary classifier; the env-var pointer is fine for v1.

## File list for the next session

Files this session created (you're reading one of them):
- `docs/08-projects/current/mlb-sidemodel/SCOPING.md` — this doc

Files the next session needs to create:
- `predictions/mlb/sidemodel/__init__.py` (empty)
- `predictions/mlb/sidemodel/binary_v1.py` (loader + `score()`)
- `scripts/mlb/training/build_sidemodel_training_set.py`
- `scripts/mlb/training/train_sidemodel_v1.py`
- `scripts/mlb/sidemodel_cf_analysis.py` (CF after N≥100)

Files the next session needs to edit:
- `predictions/mlb/worker.py` — init side-model at L130-200, attach
  `p_sidemodel` in prediction loop, add to BQ row dict at L905
- BQ DDL for the two new columns on `pitcher_strikeouts`
