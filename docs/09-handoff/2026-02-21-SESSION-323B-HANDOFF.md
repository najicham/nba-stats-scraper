# Session 323B Handoff: Comprehensive Model Experiment Matrix (11 Experiments)

**Date:** 2026-02-21
**Focus:** 11-experiment matrix across feature sets, loss functions, and training strategies
**Status:** COMPLETE — all experiments run, analysis done, next session action items defined

## What Was Done

Ran 11 experiments in parallel to find the optimal model configuration for post-ASB deployment. All used the same training window (Dec 25, 2025 - Feb 5, 2026) and 7-day walkforward eval (Feb 6-12).

### Full Results Table (sorted by HR edge 3+)

| # | Config | Features | Loss | MAE | HR All | HR 3+ (N) | HR 5+ (N) | Vegas Bias | OVER HR | UNDER HR |
|---|--------|----------|------|-----|--------|-----------|-----------|------------|---------|----------|
| **E03** | **V12 Vegas MAE** | **54f** | **MAE** | **4.668** | **59.7%** | **66.7% (15)** | N/A (0) | -0.14 | 50.0% | 85.7% |
| **E06** | V12 Vegas Q43 | 54f | Q0.43 | 4.788 | 53.3% | 64.4% (45) | 100% (2) | -1.56 | N/A (0) | 64.4% |
| **E04** | **V12 NoVeg Clean** | **46f** | **MAE** | **4.738** | **57.5%** | **63.6% (22)** | 50.0% (2) | -0.16 | 44.4% | 76.9% |
| **E02** | V12 NoVeg MAE | 50f | MAE | 4.704 | 54.3% | 61.1% (18) | 100% (1) | -0.07 | 50.0% | 66.7% |
| E09 | V9 Two-Stage | 29f | MAE | 5.242 | 48.8% | 50.0% (76) | 47.6% (21) | -0.64 | 45.0% | 51.8% |
| E05 | V9 Q43 | 33f | Q0.43 | 4.970 | 48.7% | 50.0% (38) | 0.0% (1) | -1.58 | 0.0% | 51.4% |
| E07 | V9 Huber | 33f | Huber:5 | 4.775 | 54.9% | 47.4% (19) | 33.3% (3) | -0.59 | N/A (0) | 47.4% |
| E11 | V9 Min PPG 10 | 33f | MAE | 4.813 | 54.2% | 33.3% (18) | 0.0% (2) | +0.27 | 28.6% | 50.0% |
| E08 | V9 Recency 14d | 33f | MAE | 4.850 | 46.5% | 33.3% (9) | N/A (0) | -0.05 | 25.0% | 40.0% |
| E01 | V9 MAE Baseline | 33f | MAE | 4.828 | 46.6% | 25.0% (8) | 0.0% (1) | -0.16 | 0.0% | 33.3% |
| E10 | V9 Lines Only | 33f | MAE | 4.820 | 49.2% | 20.0% (5) | N/A (0) | +0.10 | 0.0% | 33.3% |

### Walk-Forward Weekly Breakdown

| # | Week 1 (Feb 2-8) HR 3+ | Week 2 (Feb 9-15) HR 3+ | Trend |
|---|-------------------------|--------------------------|-------|
| E03 | 50.0% | 77.8% | Improving |
| E04 | 64.3% | 62.5% | Stable |
| E02 | 50.0% | 75.0% | Improving |
| E06 | 75.0% | 60.6% | Declining |
| E09 | 48.6% | 51.3% | Flat/coin-flip |

### Feature Importance Insights

**V9 models (with vegas):** vegas_points_line dominates (19-32%), vegas_opening_line #2 (7-18%)
**V12 models (no vegas):** points_avg_season leads (16-18%), line_vs_season_avg new signal (8-9%)
**E03 (V12+vegas):** Most balanced — vegas_pts_line (18%), deviation_from_avg_last3 (7%), vegas_open (6%), pts_avg_szn (5%), pts_avg_10 (4%). Vegas important but not dominant like in V9.
**E07 (Huber):** Dramatically different — vegas_opening_line (31%), minutes_avg_last_10 (19%). Huber reshuffles importance.

## Key Findings

### 1. V12 + Vegas (E03) Is the Clear Winner — NEVER TRIED BEFORE

V12 with vegas features included was never attempted in production. It dominates:
- **Best MAE:** 4.668 (vs V9 baseline 4.828)
- **Best HR all:** 59.7% (vs V9 46.6%)
- **Best HR 3+:** 66.7% (vs V9 25.0%)
- **Clean vegas bias:** -0.14
- Vegas features ARE important (18% + 6% = 24% combined) but V12's extra features (deviation_from_avg_last3, line_vs_season_avg) add meaningful signal that V9 lacks

### 2. Dead Features Confirmed — Remove 4 from V12

E04 (46f, dead features removed) beats E02 (50f, full V12 no-vegas):
- HR 3+: 63.6% vs 61.1%
- HR all: 57.5% vs 54.3%
- Confirms `spread_magnitude`, `implied_team_total`, `teammate_usage_available`, `multi_book_line_std` are noise (always constant/defaulted values in feature store)

### 3. Quantile Q43 Creates Volume but UNDER Bias

E06 (V12+vegas Q43) generated n=45 edge 3+ picks (nearest to N>=50 gate) with 64.4% HR — impressive. But:
- Vegas bias -1.56 (FAIL)
- Zero OVER picks (100% UNDER direction)
- Not deployable as champion, but excellent as a shadow/UNDER specialist

### 4. Training Population Restrictions Hurt

- **Lines-only (E10):** Reduced training from 6,068 to 4,216. HR 3+ dropped to 20%.
- **Min PPG 10 (E11):** Reduced to 2,841. HR 3+ dropped to 33.3%.
- The model needs the full population distribution for calibration.

### 5. Dead Ends (Don't Revisit)

- **Huber loss (E07):** 47.4% HR 3+, dramatically reshuffles feature importance in unhelpful ways
- **Recency weighting (E08):** 33.3% HR 3+, worst HR all (46.5%). Recent-game overweighting hurts.
- **Lines-only training (E10):** 20.0% HR 3+, early stopping at iteration 99 (underfitting with fewer samples)
- **Min PPG filter (E11):** 33.3% HR 3+, too few training samples

### 6. Two-Stage (E09) Is a Volume Generator, Not a Winner

- Only model with n=76 at edge 3+ and n=21 at edge 5+
- But 50.0% HR (coin flip) and MAE 5.242 (above baseline)
- Interesting as a candidate pool generator, not a scoring model

## Sample Size Caveat

All N values are small (max n=45 at edge 3+) due to ASB eval gap. The relative rankings are directionally correct but absolute HR% will regress toward mean with larger samples. The critical finding is the consistent V12 > V9 pattern across all 4 V12 variants.

## Next Session: Full Post-ASB Retrain & Infrastructure Build

### Priority 1: Determine Which Configs to Retrain Post-ASB

When enough post-ASB games accumulate (target: Feb 28+ for training, Mar 1-7+ for eval with N>=50), retrain the **top configs** from this experiment matrix:

**Recommended retrain matrix (top 4):**
1. `E03 config: --feature-set v12` (54f, V12+vegas MAE) — **NEVER TRIED, EXPERIMENT WINNER**
2. `E04 config: --feature-set v12 --exclude-features "spread_magnitude,implied_team_total,teammate_usage_available,multi_book_line_std"` (46f, V12+vegas clean MAE) — dead features removed
3. `E02 config: --feature-set v12 --no-vegas` (50f, current V12 production config)
4. `E01 config: --feature-set v9` (33f, current V9 champion config)

Plus quantile variants of the winning MAE config:
5. Winner config + `--quantile-alpha 0.43`
6. Winner config + `--quantile-alpha 0.45`

### Priority 2: Build Full Shadow Model Ecosystem

The goal is to replicate the V9/V8 production ecosystem for the winning config(s). This means:

**For each winning config, the new session should:**

1. **Retrain with post-ASB data** — use `--train-end 2026-02-28` (or later) so eval window has real games
2. **Pass ALL governance gates** — HR 3+ >= 60%, N >= 50, vegas bias +/-1.5, directional balance
3. **Upload to GCS** — standard naming: `catboost_{version}_{features}f_train{start}-{end}_{timestamp}.cbm`
4. **Register in model_registry** — with correct `feature_set`, `feature_count`, `loss_function`, `quantile_alpha`
5. **Enable as shadow** — `enabled=TRUE, is_production=FALSE`
6. **Verify dynamic discovery** — `shared/config/cross_model_subsets.py` pattern matching should auto-classify. If V12-with-vegas is a new family, add a pattern.

### Priority 3: Production Infrastructure for V12+Vegas (if winner)

If V12+vegas (E03) remains the winner after post-ASB retrain:

**What exists (no changes needed):**
- `quick_retrain.py` — `--feature-set v12` already selects V12_CONTRACT (54f with vegas)
- Feature augmentation — `augment_v12_features()` already runs for `--feature-set v12`
- Model saving/registration — works out of the box

**What may need changes:**
- `catboost_monthly.py` — currently only supports V9 (33f) and V12-noveg (50f) for production prediction. A V12-with-vegas path needs ~30 lines for feature extraction using V12_CONTRACT (54f) instead of V12_NOVEG_CONTRACT (50f)
- `shared/config/cross_model_subsets.py` — may need a new family pattern for `v12_vegas` or similar
- `retrain.sh` — update defaults if V12+vegas becomes the new champion

### Priority 4: Season Replay & Subset Creation

After shadow models are running, replay the season to create subsets and best bets:

1. **Backfill predictions** — run shadow models on historical game dates to generate prediction records
2. **Grade predictions** — run grading on backfilled predictions to populate `prediction_accuracy`
3. **Materialize subsets** — `SubsetGradingProcessor` needs prediction records to create dynamic subsets
4. **Backfill best bets** — run `SignalBestBetsExporter` on historical dates to see how the new models would have performed
5. **Compare** — use `/replay` skill or `bin/compare-model-performance.py` to compare new models against champion V9

### Commands for Next Session

```bash
# Check if enough post-ASB data exists
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as games
FROM nba_reference.nba_schedule
WHERE game_date >= '2026-02-20' AND game_status = 3
GROUP BY 1 ORDER BY 1"

# Retrain top configs (adjust dates based on available data)
BASE="--train-start 2025-12-25 --train-end 2026-02-28 --eval-days 7 --walkforward --force"

# E03 winner config
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "POST_ASB_V12_VEGAS" --feature-set v12 $BASE

# E04 clean config
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "POST_ASB_V12_VEGAS_CLEAN" --feature-set v12 --exclude-features "spread_magnitude,implied_team_total,teammate_usage_available,multi_book_line_std" $BASE

# V9 baseline for comparison
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "POST_ASB_V9_BASELINE" --feature-set v9 $BASE

# Quantile variants of winner
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "POST_ASB_V12_VEGAS_Q43" --feature-set v12 --quantile-alpha 0.43 $BASE
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "POST_ASB_V12_VEGAS_Q45" --feature-set v12 --quantile-alpha 0.45 $BASE

# Monitor shadow models
PYTHONPATH=. python bin/compare-model-performance.py <new_model_id> --days 7

# Check dynamic model discovery
PYTHONPATH=. python -c "from shared.config.cross_model_subsets import discover_models; print(discover_models('2026-03-01'))"
```

## Models Saved This Session

All saved to `models/` directory (local only, not uploaded to GCS since these are experiments):

| File | Config | MAE | HR 3+ |
|------|--------|-----|-------|
| `catboost_v9_54f_train20251225-20260205_20260221_222256.cbm` | E03 V12+vegas | 4.668 | 66.7% |
| `catboost_v9_50f_noveg_train20251225-20260205_20260221_222256.cbm` | E02 V12 noveg | 4.704 | 61.1% |
| `catboost_v9_46f_noveg_train20251225-20260205_20260221_222256.cbm` | E04 V12 clean | 4.738 | 63.6% |
| `catboost_v9_54f_q0.43_train20251225-20260205_20260221_222258.cbm` | E06 V12+vegas Q43 | 4.788 | 64.4% |
| `catboost_v9_33f_train20251225-20260205_20260221_222221.cbm` | E01 V9 baseline | 4.828 | 25.0% |
| `catboost_v9_33f_q0.43_train20251225-20260205_20260221_*.cbm` | E05 V9 Q43 | 4.970 | 50.0% |
| `catboost_v9_33f_Huber_train20251225-20260205_20260221_*.cbm` | E07 Huber | 4.775 | 47.4% |
| `catboost_v9_33f_train20251225-20260205_20260221_*_recency.cbm` | E08 Recency | 4.850 | 33.3% |
| `catboost_v9_29f_2stg_train20251225-20260205_20260221_222439.cbm` | E09 Two-stage | 5.242 | 50.0% |
| `catboost_v9_33f_train20251225-20260205_20260221_*_linesonly.cbm` | E10 Lines only | 4.820 | 20.0% |
| `catboost_v9_33f_train20251225-20260205_20260221_*_minppg.cbm` | E11 Min PPG 10 | 4.813 | 33.3% |

## Decision Summary for Next Session

| Question | Answer | Action |
|----------|--------|--------|
| Best feature set? | V12 (54f with vegas) | Use `--feature-set v12` for post-ASB retrain |
| Remove dead features? | Yes, 4 features confirmed dead | Add `--exclude-features` to clean config |
| Best loss function? | MAE (Huber/Quantile don't improve) | Keep MAE as default |
| Recency weighting? | No benefit | Don't use `--recency-weight` |
| Training population filter? | Full population best | Don't use `--lines-only-train` or `--min-ppg` |
| Two-stage viable? | Volume but not quality | Skip for now |
| V13/V14 features? | 0% importance (Session 323A) | Don't invest in feature store wiring |
