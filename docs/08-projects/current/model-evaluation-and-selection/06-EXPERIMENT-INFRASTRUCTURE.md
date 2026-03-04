# Experiment Infrastructure Assessment

## What Exists Today

### Training (`quick_retrain.py` — 4,500+ lines)
- Flexible training/eval window specification (explicit dates or `--train-days` rolling)
- Multi-feature-set support (V9 through V18, with/without Vegas)
- Custom loss functions: MAE, Quantile (alpha 0.43-0.55), Huber, LogCosh, RMSE
- Advanced CatBoost controls: RSM, grow policies, bootstrap types, min-data-in-leaf
- Recency weighting (exponential decay half-lives)
- Tier-based sample weighting (star/starter/role/bench multipliers)
- Category feature weighting (vegas, derived, composite weight multipliers)
- Alternative frameworks: LightGBM, XGBoost, binary classifiers
- `--machine-output FILE` for grid search JSON parsing
- `--skip-register` for experiments that shouldn't persist
- Auto SHA256 + GCS upload + registry insertion when gates pass

### Evaluation
- **`quick_retrain.py` eval:** HR at multiple edge thresholds, directional breakdown, vegas/tier bias checks, MAE vs baseline
- **`what_if_retrain.py`:** Counterfactual simulation, in-memory training OR load saved models, compare two models side-by-side, sandbox mode (no BQ writes)
- **`compare-model-performance.py`:** Production vs backtest comparison, segment analysis (direction, tier, line range, edge bands)

### Grid Search (`grid_search_weights.py`)
- Template-based sweeps: tier weights, recency, feature set shootout
- Custom grid: `param=val1,val2` specification
- Auto-generates combinations, submits to `quick_retrain.py --skip-register`
- Results table ranked by HR edge 3+ with CSV export
- Timeout/failure handling

### Backtesting (`replay_engine.py` + `replay_strategies.py`)
- Pluggable decision strategies (ThresholdStrategy, etc.)
- Per-date model metrics (rolling 7d/14d/30d HR)
- Daily P&L computation at -110 odds
- Model switching logic with state machine
- Cumulative P&L tracking

### Governance Gates (enforced in `quick_retrain.py`)
1. Hit rate (3+) >= 60%
2. Sample size >= 25 edge 3+ bets
3. Vegas bias within +/- 1.5
4. No critical tier bias (> +/- 5 points)
5. Directional balance (OVER + UNDER >= 52.4%)
6. MAE improvement vs baseline (soft gate)

### Drift Detection (`adversarial_validation.py`)
- Trains classifier to distinguish time periods
- Reports AUC + top drifting features
- Separate by direction (OVER vs UNDER drift patterns)

## Critical Gaps

### Gap 1: No Cross-Validation Framework (CRITICAL)

**Current:** Single eval window per experiment. The 56-day window was tested on ONE eval period (Feb 1-27).

**Need:** Walk-forward temporal CV — train on sliding windows, eval on multiple non-overlapping periods. At minimum 3-5 folds.

**Risk:** All our "optimal" findings (56-day window, vegas weight 0.15, v12_noveg > v16) could be overfit to the single eval period used. Session 369 already showed StdDev of 2.5pp across seeds — we need CV across TIME not just seeds.

**Suggested implementation:** Wrapper around `quick_retrain.py` that:
```
For each fold in [(train: Dec 1-Jan 15, eval: Jan 16-31),
                  (train: Dec 15-Jan 31, eval: Feb 1-14),
                  (train: Jan 1-Feb 14, eval: Feb 15-28)]:
    Run quick_retrain.py --train-start ... --train-end ... --machine-output
    Collect results
Report: mean HR ± std across folds
```

### Gap 2: No Statistical Significance Testing (HIGH)

**Current:** HR differences judged by eyeball. CLAUDE.md says "< 5pp is within noise" but there's no formal test.

**Need:**
- Bootstrap confidence intervals on HR differences
- Two-proportion z-test or McNemar's test for paired model comparisons
- Minimum detectable effect size given sample size (power analysis)

**Example:** Is 73.9% (N=23) significantly better than 68.7% (N=23)? At N=23, the 95% CI is roughly ±18pp. So NO, these are not distinguishable. We need ~200+ picks per condition to detect 5pp differences.

### Gap 3: No Best Bets Pipeline Simulation (HIGH)

**Current:** `what_if_retrain.py` tests raw model predictions. Can't simulate through the filter stack.

**Need:** Given a model's predictions for a date range, run them through `aggregator.py` (filters + signals) and report: how many would have been best bets? What would the BB HR have been?

**This is the most important gap** because best bets HR is our actual success metric. Without this, we can't fairly evaluate new models before deployment.

**Suggested implementation:** `bin/simulate_best_bets.py` that:
1. Loads predictions from `prediction_accuracy` (or generates new ones from model)
2. For each game_date, simulates per-player selection with ONLY this model
3. Runs through `aggregator.generate_picks()`
4. Grades against actuals
5. Reports: BB picks, BB HR, ultra picks, ultra HR, avg edge, avg signal count

### Gap 4: No Automated Training Window Search (MEDIUM)

**Current:** Manual `--train-start` / `--train-end` experiments.

**Need:** Grid search over windows like `grid_search_weights.py` does for tier weights.

**Suggested:** Add `--template training_window_sweep` to `grid_search_weights.py`:
```
Windows: [28, 35, 42, 49, 56, 63, 70] days
Eval period: last 14 days before target_date
Models: v12_noveg, v16_noveg (or specified via --feature-set)
Output: ranked table of window × HR × MAE × OVER_HR × UNDER_HR
```

### Gap 5: No Hyperparameter Tuning (MEDIUM)

**Current:** Manual `--rsm 0.5 --depth 5` etc. No systematic search.

**Need:** Optuna or similar Bayesian optimization integrated into `quick_retrain.py --tune`.

**This is lower priority** because CatBoost is relatively robust to hyperparameters, and the main variance comes from training data selection, not HPO. But for new architectures (LightGBM, XGBoost), HPO matters more.

### Gap 6: No Feature Importance Drift Monitoring (MEDIUM)

**Current:** `adversarial_validation.py` can diagnose drift post-hoc, but no continuous monitoring.

**Need:** After each retrain, store feature importance vector. Alert if top-5 features change between consecutive retrains. Track feature importance evolution over time.

## Ease of Use Summary

| Task | Ease | Notes |
|------|:----:|-------|
| Try different training windows | Medium | Manual `--train-start`/`--train-end`, no grid search |
| Try different feature sets | **Easy** | `--feature-set v12_noveg --no-vegas` works cleanly |
| Try different loss functions | **Easy** | `--loss quantile --quantile-alpha 0.55` |
| Try different hyperparameters | Medium | Manual CLI flags, no automated search |
| Compare two models | Medium | `what_if_retrain.py` works but requires manual SQL |
| Run grid search | **Easy** | `grid_search_weights.py --template` with ranked output |
| Measure statistical significance | **Hard** | No built-in tool |
| Simulate best bets pipeline | **Hard** | Would need new script |
| Deploy to production | **Easy** | `retrain.sh --promote` handles everything |

## Recommendations for Next Session

1. **Build `simulate_best_bets.py`** — highest impact tool missing. Lets us fairly evaluate any model's best bets quality without deploying it.
2. **Add training window sweep template** to `grid_search_weights.py` — easy extension of existing tooling.
3. **Add bootstrap CI utility** — even a simple `bin/bootstrap_hr.py` that takes two HR results and reports significance.
4. **Store feature importance in experiments table** — add to `quick_retrain.py` output.
5. **Document the full experiment workflow** — currently scattered across CLAUDE.md, skill definitions, and tribal knowledge.
