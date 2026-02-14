# Session 245 Handoff: V12 Augmentation Bug Fix, 6/6 Gate Model, 3PT Cold Filter

**Date:** 2026-02-13
**Focus:** Fix V12 augmentation bug, re-run experiments with real features, 3PT cold filter analysis
**Status:** Bug fixed, experiments complete, results documented, code uncommitted

---

## What Was Done

### 1. Fixed V12 Augmentation Bug (CRITICAL)

**All experiments across Sessions 243-244 had broken augmentation.** Every "V12" model was actually training on V9 base features (33) with default/zero values in V11/V12 slots.

**Dual root cause:**

1. **Date format mismatch (minor):** Lookup keys used `pd.to_datetime().strftime('%Y-%m-%d')` producing `"2025-11-02"`, but the merge loop used `str(row['game_date'])` producing `"2025-11-02 00:00:00"`. Fixed by standardizing all to `strftime('%Y-%m-%d')`.

2. **Feature store pre-populates V12 slots (major):** `ml_feature_store_v2` now stores all 54 feature names. The augmentation code checked `if 'days_rest' in feature_names: continue` — always true, so augmentation was entirely skipped. Values were defaults/zeros (e.g., `game_total_line=0.0` when it should be ~220). Fixed by switching from append-only mode to **replace-at-index** mode when features already exist.

**Files changed:** `ml/experiments/quick_retrain.py` — fixed V11, V12, V13, V14 augmentation functions (6 lookup key fixes + 4 append→replace conversions).

### 2. Re-ran Experiments With Fixed Augmentation

| # | Name | Features | Loss | MAE | HR 3+ (n) | OVER | UNDER | Gates |
|---|------|----------|------|-----|-----------|------|-------|-------|
| N | V12_RSM50_FIXED | V12 (50) | MAE | 4.84 | **71.43% (35)** | 71.4% | 71.4% | 5/6 |
| **O** | **RSM50_HUBER_V2** | **V12 (50)** | **Huber:5** | **4.95** | **62.50% (88)** | **53.3%** | **64.4%** | **6/6 PASS** |
| P | V14_RSM50_V2 | V14 (61) | MAE | 4.85 | 62.79% (43) | 50.0% | 65.7% | 4/6 |
| Q | V14_RSM50_HUBER_V2 | V14 (61) | Huber:5 | 5.12 | 55.75% (174) | 28.6% | 56.9% | 2/6 |

**RSM50_HUBER_V2 is the first model to pass ALL 6 governance gates.**

### 3. 3PT Cold Streak Post-Prediction Filter

Joined `prediction_accuracy` with trailing 3PT% from `player_game_summary`. 5-game window results:

| 3PT Streak | N | Hit Rate | ROI @-110 |
|-----------|---|----------|-----------|
| **VERY COLD (<28%)** | **40** | **77.5%** | **+48.0%** |
| COLD (28-32%) | 20 | 60.0% | +14.5% |
| NORMAL (33-40%) | 76 | 63.2% | +21.5% |
| WARM (41-50%) | 73 | 64.4% | +22.9% |
| **HOT (>50%)** | **39** | **51.3%** | **-2.1%** |

This is **market mispricing**, not mean reversion — cold shooters stay cold but prop lines over-discount.

### 4. V14 Features Are Dead

All 5 engineered FG% features scored 0.00 importance across all experiments. V13 raw FG% features also contributed nothing. CatBoost doesn't find signal in shooting efficiency for points prediction.

---

## Key Artifacts

- **Results doc:** `docs/08-projects/current/mean-reversion-analysis/07-SESSION-245-AUGMENTATION-FIX-AND-RESULTS.md`
- **Model file:** `models/catboost_v9_50f_noveg_train20251102-20260131_20260213_213149.cbm`
- **Model SHA256:** `27d213a82308215ea40560e6c6973f227f486080cdfad1daadc201d20f0bc916`

---

## Code Changes (uncommitted)

| File | Change |
|------|--------|
| `ml/experiments/quick_retrain.py` | +483/-24: V12 augmentation fix (date formatting + append→replace), V13/V14 augmentation functions, `--feature-set v14` flag |
| `shared/ml/feature_contract.py` | V14/V14_NOVEG contracts (65/61 features), registry entries |
| Other modified files | Pre-existing from earlier sessions (publishing, grading, coordinator changes) |
| `docs/08-projects/current/mean-reversion-analysis/` | Sessions 243-245 results docs |

---

## What the Next Session Should Do

### Priority 1: Shadow Deploy RSM50_HUBER_V2

First model to pass all 6 governance gates. Upload to GCS, register, shadow test 2+ days.

```bash
# Upload model
gsutil cp models/catboost_v9_50f_noveg_train20251102-20260131_20260213_213149.cbm \
  gs://nba-props-platform-models/catboost_v9/

# Register in manifest + sync
./bin/model-registry.sh sync
```

### Priority 2: Extend Eval Window

V12_RSM50_FIXED has 71.4% HR but only 35 samples. Extend to get past 50-sample gate:

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
  --name "V12_RSM50_EXTENDED" \
  --feature-set v12 --no-vegas \
  --rsm 0.5 --grow-policy Depthwise \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-20 \
  --walkforward --include-no-line --force --skip-register
```

### Priority 3: Implement 3PT Cold Filter

As a post-prediction rule (not model feature):
- **BOOST** OVER predictions when player's last-5-game 3PT% < 28% (77.5% HR)
- **FLAG/SKIP** OVER predictions when player's 3PT% > 50% (51.3% HR, below breakeven)
- Validate out-of-sample on Feb 13-20 predictions

### Priority 4: Consider Removing V13/V14 from Feature Contract

They add complexity with zero value. V12 (50 features) is the sweet spot.

---

## Dead Ends (Don't Revisit)

- **V14 engineered FG% features** — zero importance across all experiments
- **V13 raw FG% features** — zero importance when V12 features work
- **V14 + Huber combination** — severe UNDER bias (-1.73 vegas bias)
- **Removing `line_vs_season_avg`** — crashes HR from 57.1% to 51.85%
- **RSM50 + quantile** — too UNDER-biased
- **Edge Classifier (Model 2)** — AUC < 0.50 (Session 230)

---

## Schema Reminders

- `prediction_accuracy`: `line_value` (not prop_line), `actual_points` (not actual_stat), no `stat_type` column
- `nbac_gamebook_player_stats`: `minutes_decimal` (not minutes_played), `field_goals_made/attempted`
- Feature store JOIN key: `(player_lookup, game_date)` — use `pd.to_datetime().strftime('%Y-%m-%d')`
