# Handoff — 2026-05-20 — MLB Strikeout Stage 1.1 (Poisson P(over) + model-market blend)

**Branch:** `main`. **Nothing committed** — files are modified on disk, awaiting review.
**Project folder:** `docs/08-projects/current/mlb-lineup-early-hook/`
**Prior handoff:** `2026-05-20-MLB-STRIKEOUT-PLANNING-HANDOFF.md` (planning + Wave 0 start).
**Start here:** `docs/08-projects/current/mlb-lineup-early-hook/02-EXECUTION-PLAN.md`.

---

## 1. What this session did

Built **Stage 1.1 — Poisson loss + real `P(over)` + model-market blend** (the
execution plan's "FIRST SHIP"). Code only — no retrain, no deploy.

### Predictor — `predictions/mlb/prediction_systems/catboost_v2_regressor_predictor.py`
- **Real `P(over)`.** Replaced the hand-tuned `p_over = sigmoid(0.7 × edge)` (never
  fit to outcomes; its edge→hit-rate curve was non-monotonic) with the honest Poisson
  tail `p_over = 1 − PoissonCDF(floor(line), λ)`. New module-level helpers
  `_poisson_cdf()` / `poisson_p_over()` — stdlib `math` only, no scipy. Integer lines
  correctly treat `K == line` as a push (not an over).
- **Model-market blend.** New `_get_blend_weight()` resolves `w` from
  `MLB_BLEND_WEIGHT` env → model metadata `blend_weight` → `1.0`, clamped `[0.3, 1.0]`.
  `predict()` now computes `blended_K = w·model + (1−w)·line`, derives `edge` and
  `p_over` from the blend, and reports the blended K as `predicted_strikeouts`. Added
  `blend_weight` to the output dict for provenance.
- `SIGMOID_SCALE` is **kept** in the module (with a comment) — the shadow
  `lightgbm_v1` / `xgboost_v1` regressor predictors import it; catboost_v2 no longer
  uses it.

### Training — `scripts/mlb/training/train_regressor_v2.py`
- New `fit_blend_weight()` — grid-searches `w ∈ [0.3, 1.0]` to minimise **holdout**
  MAE (the holdout is genuinely out-of-sample; the model trained only on `train_df`).
  Falls back to `w = 1.0` if the holdout has `< 30` rows.
- Wired into `main()`, the training summary printout, and metadata: top-level
  `blend_weight` (the key the predictor reads) + a full `blend` detail block.
- The `--loss-function` flag (RMSE / Poisson / Quantile) already existed — untouched.

### Tests
- Rewrote `tests/mlb/test_catboost_v2_regressor.py` — **19 tests** (Poisson helpers,
  blend metadata / env override / clamping / edge-shrink, Poisson `p_over`). All pass.
- `tests/mlb/test_exporter_with_regressor.py` (**46 tests**) still passes — the
  exporter feeds prediction dicts directly, doesn't go through the predictor.
- Smoke-tested `fit_blend_weight()` on synthetic decorrelated-error data: `w = 0.65`,
  blended MAE `1.01` vs model-only `1.27`; small-holdout fallback returns `w = 1.0`.

### Docs / memory
- Updated `02-EXECUTION-PLAN.md` (Stage 1.1 row → `[~]`, "Where we are" note).
- Updated memory `mlb-strikeout-project.md`.

**Files modified:** `catboost_v2_regressor_predictor.py`, `train_regressor_v2.py`,
`test_catboost_v2_regressor.py`, `02-EXECUTION-PLAN.md`, this handoff.

---

## 2. Key decisions / scope calls

- **The blend ships INERT.** The predictor defaults `w = 1.0` (pure model) when model
  metadata lacks `blend_weight` — and the current production model predates Stage 1.1,
  so it has no `blend_weight`. The blend does **nothing** until a model is retrained.
  This is deliberate: the blend shrinks `edge` by factor `w`, and shipping it against
  the unrefitted `0.75 / 1.25` edge floors would drought the pipeline. Activate it in a
  retrain **paired with Stage 1.3** (threshold refit) + **Stage 1.4** (gate) — not
  standalone. (`MLB_BLEND_WEIGHT` env var can force-activate it for testing, and is the
  incident rollback: set `1.0` to revert.)
- **Poisson `p_over` IS live now** — it's a pure function of `(λ, line)` and is valid
  for an RMSE-trained model (the model output is a conditional mean ≈ `λ`). Safe,
  pure-improvement; no retrain needed.
- **Poisson *training* loss stays a `--loss-function` flag** (default still `RMSE`).
  The spec calls for A/B-ing it via the Stage 1.4 framework before flipping the default.
- `predicted_strikeouts` now reports the **blended** K — consistent with `edge` and
  improves grading MAE (the point of the blend). Raw model output is not persisted.
- `p_over` is **not** in BigQuery — it flows in-memory predictor → exporter only — so
  no schema change. `predicted_strikeouts` / `edge` / `confidence` / `recommendation`
  keep their column names; only values change.

---

## 3. Data state — nothing to scrape

Four full seasons of graded pitcher-strikeout props already exist in
`mlb_raw.bp_pitcher_props` (`market_id = 285`):

| Season | Graded starts |
|--------|---------------|
| 2022 | 3,804 |
| 2023 | 3,661 |
| 2024 | 3,136 |
| 2025 (last full) | 3,603 |
| 2026 (partial) | 346 |

~14K graded starts — well above the spec's ~5K-start paired-bootstrap target.
Features (`mlb_analytics.pitcher_game_summary`) are populated back to 2022. PA/Statcast
features (f50–f53, f70–f73) only exist 2025+, but they're NaN-tolerant. **No new
scraping is needed to backtest Stage 1.1 on prior seasons.**

---

## 4. What's next (see `02-EXECUTION-PLAN.md`)

1. **Stage 1.4 — validation framework.** This is what unblocks "running tests on last
   season." **Catch:** `scripts/mlb/training/season_replay.py` carries its *own*
   hardcoded `SIGMOID_SCALE` and computes `p_over` the old way (~line 1151) — it does
   not import from the predictor, so a replay today still measures the old sigmoid and
   applies no blend. Stage 1.4 work:
   - Wire the blend + Poisson `p_over` into the backtest — call `fit_blend_weight()` at
     each walk-forward retrain, apply the blend in the prediction step.
   - Paired-bootstrap **MAE** (model-only vs blended), 95% CI lower bound > 0.
   - Calibration: **Brier / reliability**, old sigmoid vs new Poisson `p_over`.
   - Multi-seed, 2022–2025.
   - This also A/Bs the Poisson training loss (`--loss-function Poisson` vs `RMSE`).
2. **Stage 1.3 — selection/staking fix** (replace fixed top-5 with a quality gate).
3. **Then** a Poisson-loss retrain that also activates the blend (upload + register +
   shadow the artifact first; the MLB worker auto-deploys). Re-fit edge thresholds.

---

## 5. State / gotchas

- **Nothing is committed.** Modified files are on disk only.
- The repo still has the large pre-existing uncommitted diff (~850 reformatted files)
  noted in prior handoffs — untouched.
- Tests run with `.venv/bin/python -m pytest <file> -p no:cacheprovider -o addopts=""`
  — `pytest.ini` injects `--cov` flags that the bare run rejects.
- `bq` CLI: pass `--project_id=nba-props-platform` (the shell default billing project
  is something else). `rows` is a reserved word — alias it in `SELECT`.
- Predictor output gained one new key: `blend_weight`. The worker's BQ row mapping
  (`write_predictions_to_bigquery`) does not map it — harmless, just not persisted.
