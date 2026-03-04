# Session 395 — Model Evaluation Execution

## Context

Session 394 completed the research phase for model evaluation & selection. All findings, tools, and recommendations are documented. Your job is to execute on the top priorities.

## Read These First

1. **`docs/08-projects/current/model-evaluation-and-selection/07-SESSION-394-FINDINGS.md`** — Full analysis results and recommendations
2. **`docs/09-handoff/2026-03-03-SESSION-394-HANDOFF.md`** — What was done, what's next
3. **`docs/08-projects/current/model-evaluation-and-selection/00-OVERVIEW.md`** — Project overview (if you need background)

Also read `CLAUDE.md` at repo root for system context.

## Key Findings You're Building On

1. **12 enabled models are functionally 2** — 11 CatBoost clones (r>0.97) + 1 LightGBM (r≈0.95). Fleet provides near-zero diversity.
2. **SC=3 OVER block was implemented** in aggregator.py (Session 394). Blocks all OVER + SC=3 picks (45.5% HR net loser). Needs deployment.
3. **OVER edge is well-calibrated** (56%→69% monotonic). UNDER edge breaks at 10+ (overconfident).
4. **V16 models have "latent quality"** — 66.7% HR but never win per-player selection due to lower edges (3.7-4.0 avg).
5. **`simulate_best_bets.py` is built but untested on real data.** Must validate before relying on it.

## Priority Tasks

### 1. Deploy Session 394 Changes

Push to main to deploy the SC=3 OVER block. Verify with:
```bash
git push origin main
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
./bin/check-deployment-drift.sh --verbose
```

The aggregator change auto-deploys. prediction-coordinator needs manual deploy if `ml/signals/` changes are included in the build trigger.

### 2. Validate simulate_best_bets.py on Real Data

This is the most important task. Run simulations on models with known outcomes to verify the tool produces trustworthy results:

```bash
# First: validate against known production results
# Production best bets in Jan had 71.4% HR. Does the simulator agree?
python bin/simulate_best_bets.py --multi-model \
    --start-date 2026-01-01 --end-date 2026-01-31 --verbose

# Then: test the "latent quality" models that never win selection
python bin/simulate_best_bets.py --model catboost_v16_noveg_train1201_0215 \
    --start-date 2026-02-01 --end-date 2026-02-28

python bin/simulate_best_bets.py --model catboost_v12_noveg_60d_vw025_train1222_0219 \
    --start-date 2026-02-01 --end-date 2026-02-28

# Compare V16 vs best V12 variant
python bin/simulate_best_bets.py --model catboost_v16_noveg_train1201_0215 \
    --compare catboost_v12_noveg_train0110_0220 \
    --start-date 2026-02-01 --end-date 2026-02-28
```

If the simulator's multi-model results roughly match historical production BB HR, it's validated. If they diverge significantly, investigate why before using it for decisions.

### 3. V16 Fresh Retrain

V16 showed promise (66.7% HR, good calibration) but is trained on old data (Dec 1 - Feb 15). Use the new training window sweep:

```bash
PYTHONPATH=. python ml/experiments/grid_search_weights.py \
    --template training_window_v16 \
    --train-start 2025-12-01 --train-end 2026-02-28 \
    --eval-start 2026-03-01 --eval-end 2026-03-03
```

If the eval window is too short (only 2-3 days), extend --train-end back and use a wider eval window:
```bash
PYTHONPATH=. python ml/experiments/grid_search_weights.py \
    --template training_window_v16 \
    --train-start 2025-12-01 --train-end 2026-02-20 \
    --eval-start 2026-02-21 --eval-end 2026-03-03
```

Best window from Session 369 was 56 days. Check if that holds for V16.

### 4. Fleet Rationalization

Disable redundant CatBoost clones. The correlation analysis showed all V12 variants are r>0.97. Keep only:
- **Freshest V12 noveg** (most recent training window)
- **Freshest V12 with vegas** (if distinctly different from noveg)
- **V16 noveg** (slightly different features)
- **LightGBM** (only genuine diversity)

Use `python bin/deactivate_model.py MODEL_ID` for each model to disable. This cascades through registry, predictions, and signal picks.

Check the current fleet first:
```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  'SELECT model_id, status, enabled FROM nba_predictions.model_registry WHERE enabled = true ORDER BY model_id'
```

### 5. UNDER Edge 10+ Cap (If Time Permits)

Session 394 found UNDER edge 10+ drops to 58.4% (vs 61.3% at 7-10). Test the impact:

```bash
# Simulate with current pipeline
python bin/simulate_best_bets.py --multi-model \
    --start-date 2026-01-01 --end-date 2026-02-28 --verbose
```

Then check the verbose output for UNDER picks with edge 10+ — are they losing disproportionately?

## Tools Available

| Tool | Purpose |
|------|---------|
| `bin/simulate_best_bets.py` | Simulate best bets for any model (NEW, Session 394) |
| `bin/bootstrap_hr.py` | Statistical significance testing (NEW, Session 394) |
| `ml/experiments/grid_search_weights.py --template training_window_v16` | V16 training window sweep (NEW, Session 394) |
| `bin/deactivate_model.py MODEL_ID` | Disable a model (cascades) |
| `bin/post_filter_eval.py` | Evaluate filter effectiveness |
| `./bin/check-deployment-drift.sh --verbose` | Check deployment status |

## Important Constraints

- **Never deploy without governance gates** — use `quick_retrain.py` which enforces them
- **Use `--skip-register` for experiments** — don't pollute the registry
- **Any HR difference < 5pp is within noise** — use `bootstrap_hr.py` to check significance
- **prediction-coordinator trigger only watches `predictions/coordinator/**`**, NOT `ml/signals/` — manual deploy needed after signal changes
- **Worker uses `requirements-lock.txt`**, not `requirements.txt` — update the lock file for deps
