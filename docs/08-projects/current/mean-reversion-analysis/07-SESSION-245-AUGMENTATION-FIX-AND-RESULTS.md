# Session 245: V12 Augmentation Fix, Model Experiments, 3PT Cold Filter

**Date:** 2026-02-13
**Training:** 2025-11-02 to 2026-01-31 (91 days)
**Evaluation:** 2026-02-01 to 2026-02-12 (12 days)
**Previous Sessions:** 243-244 (V12 RSM50 was winner at 57.1% edge 3+ HR — but with broken augmentation)

## Executive Summary

1. **Fixed the V12 augmentation bug** that affected ALL experiments across Sessions 243-244. The root cause was dual: (a) date format mismatch in lookup keys (`str(game_date)` producing timestamps vs `strftime('%Y-%m-%d')`) and (b) the feature store now pre-populates V11/V12 feature name slots, causing the "skip if already present" logic to skip augmentation entirely. Fixed by switching to index-based replacement mode.
2. **V12 RSM50 with real augmentation: 71.43% edge 3+ HR** (up from 57.14% with broken augmentation). +14.29pp improvement.
3. **RSM50_HUBER_V2 passes ALL 6 governance gates** — 62.5% HR edge 3+ with 88 samples. First model to pass all gates.
4. **3PT cold streak is a powerful post-prediction filter** — OVER predictions on 3PT-cold players (last 5 games < 28%) hit at 77.5% (40 picks, +48% ROI). Hot shooters (>50%) hit at only 51.3% (-2.1% ROI).
5. **V14 engineered FG% features provide zero signal** — all 5 features at 0.00 importance across all experiments. The raw V12 features are sufficient.

---

## Bug Fix: V12 Augmentation

### Root Cause (Two Issues)

**Issue 1: Date format mismatch (minor)**
- UPCG lookup keys: `pd.to_datetime(row['game_date']).strftime('%Y-%m-%d')` → `"2025-11-02"`
- DataFrame merge keys: `str(row['game_date'])` → `"2025-11-02 00:00:00"`
- Fix: Standardize all to `pd.to_datetime().strftime('%Y-%m-%d')`

**Issue 2: Feature store pre-populates V12 slots (major)**
- The feature store (`ml_feature_store_v2`) now stores all 54 V12 features
- Feature names like `star_teammates_out`, `days_rest` are already in `feature_names` array
- The augmentation code checked `if 'days_rest' in feature_names: continue` — always true
- Values were defaults/zeros (e.g., `game_total_line=0.0` when it should be ~220)
- Fix: Switch from append-only mode to replace-at-index mode when features already exist

### Impact

All V11/V12 augmentation across Sessions 243-244 was silently skipped. Every "V12" experiment was actually training on V9 base features (33) + `line_vs_season_avg` (from feature store). The 15 V12-specific features from runtime augmentation were all default values.

### Files Changed

- `ml/experiments/quick_retrain.py`: Fixed V11, V12, V13, V14 augmentation functions
  - All lookup key date formatting: `pd.to_datetime().strftime('%Y-%m-%d')`
  - All augmentation injection: append mode (for V9-only data) OR replace mode (for pre-populated feature store)

---

## Experiment Results (All With Fixed Augmentation)

| # | Name | Features | Loss | MAE | HR 3+ (n) | OVER | UNDER | Gates |
|---|------|----------|------|-----|-----------|------|-------|-------|
| N | V12_RSM50_FIXED | V12 (50) | MAE | 4.84 | **71.43% (35)** | 71.4% | 71.4% | **5/6** |
| **O** | **RSM50_HUBER_V2** | **V12 (50)** | **Huber:5** | **4.95** | **62.50% (88)** | **53.3%** | **64.4%** | **6/6 PASS** |
| P | V14_RSM50_V2 | V14 (61) | MAE | 4.85 | 62.79% (43) | 50.0% | 65.7% | 4/6 |
| Q | V14_RSM50_HUBER_V2 | V14 (61) | Huber:5 | 5.12 | 55.75% (174) | 28.6% | 56.9% | 2/6 |

### Governance Gate Detail

| Experiment | MAE | HR 3+ | Sample | Vegas Bias | Tier Bias | Direction | Overall |
|-----------|-----|-------|--------|------------|-----------|-----------|---------|
| V12_RSM50_FIXED | PASS | PASS (71.4%) | FAIL (35) | PASS (+0.00) | PASS | PASS | 5/6 |
| **RSM50_HUBER_V2** | **PASS** | **PASS (62.5%)** | **PASS (88)** | **PASS (-0.92)** | **PASS** | **PASS** | **6/6** |
| V14_RSM50_V2 | PASS | PASS (62.8%) | FAIL (43) | PASS (-0.32) | PASS | FAIL (OVER 50%) | 4/6 |
| V14_RSM50_HUBER_V2 | PASS | FAIL (55.8%) | PASS (174) | FAIL (-1.73) | PASS | FAIL (OVER 28.6%) | 2/6 |

### Key Findings

1. **RSM50_HUBER_V2 is the first model to pass ALL 6 governance gates.** 62.5% HR with 88 edge 3+ samples is solid. The Huber loss generates 2.5x more edge 3+ picks than MAE loss (88 vs 35), making it governance-viable.

2. **V12 RSM50 MAE loss has the highest raw HR (71.4%)** but insufficient samples (35 < 50 threshold). The MAE loss produces tighter predictions with fewer high-edge picks.

3. **V14 features provide zero additional signal.** All 5 engineered FG% features (fg_cold_z_score, expected_pts_from_shooting, fg_pct_acceleration, fatigue_cold_signal, three_pct_std_last_5) scored 0.00 importance across all experiments. The V13 FG% features (fg_pct_last_3/5, three_pct_last_3/5, fg_cold_streak) also contributed nothing. CatBoost does not find predictive value in shooting efficiency features for points prediction.

4. **Huber loss + V14 creates severe UNDER bias.** V14_RSM50_HUBER_V2 had -1.73 vegas bias and only 28.6% OVER HR. The extra features + Huber combination is pathological.

5. **Feature importance shift with fixed augmentation:**
   - `deviation_from_avg_last3` (V12 feature) now appears at 2.25-2.40% importance
   - `avg_points_vs_opponent` jumps to 25.15% in Huber (was ~1% before fix)
   - V12 features `minutes_load_last_7d`, `usage_rate_last_5` contribute meaningfully

---

## 3PT Cold Streak Post-Prediction Filter

### Methodology

Joined `prediction_accuracy` (catboost_v9, OVER predictions, edge >= 3) with trailing 3PT% from `player_game_summary`. Tested 2-game and 5-game lookback windows.

### Results (5-Game Window — Best Signal)

| 3PT Streak | N | Hit Rate | 95% CI | ROI @-110 | Avg Actual vs Line |
|-----------|---|----------|--------|-----------|-------------------|
| **VERY COLD (<28%)** | **40** | **77.5%** | 64.6%-90.4% | **+48.0%** | **+4.9** |
| COLD (28-32%) | 20 | 60.0% | — | +14.5% | +0.8 |
| NORMAL (33-40%) | 76 | 63.2% | — | +21.5% | +3.5 |
| WARM (41-50%) | 73 | 64.4% | — | +22.9% | +3.0 |
| **HOT (>50%)** | **39** | **51.3%** | 35.6%-67.0% | **-2.1%** | **-0.5** |

### Mean Reversion Check

Cold shooters do NOT shoot better on game day — they stay cold (trailing 20.4% → game-day 24.7%). Yet the OVER still hits at 77.5%. This is NOT classic mean reversion. It's a **market mispricing**: prop lines are anchored on the cold streak, depressing the line, making the OVER easier to hit even without shooting improvement.

Hot shooters DO regress hard (trailing 58.2% → game-day 39.9%, -18.3pp), which explains the 51.3% OVER HR.

### Actionable Rules

1. **BOOST** OVER predictions when player's last-5-game 3PT% < 28% (77.5% HR, +48% ROI)
2. **FLAG/SKIP** OVER predictions when player's last-5-game 3PT% > 50% (51.3% HR, below breakeven)
3. 2-game window is too noisy (small N, non-monotonic). Use 5-game window.
4. **Caveat:** n=40 per bucket. Needs out-of-sample validation before production use.

---

## Decision Matrix

| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| **Deploy RSM50_HUBER_V2** | 6/6 gates, 88 samples, proven governance | 62.5% HR (not spectacular) | **Shadow test 2+ days, then promote** |
| Deploy V12_RSM50_FIXED | 71.4% HR (best raw quality) | Only 35 samples (fails governance) | Wait for more eval data |
| Add 3PT cold filter | 77.5% OVER HR on cold streaks | n=40, needs validation | Implement as post-prediction rule, not model feature |
| Use V14 features | More features = more data | 0.00 importance, zero signal | **Dead end — drop V14** |

---

## Dead Ends (Don't Revisit)

- **V14 engineered FG% features** — zero importance across all experiments
- **V13 raw FG% features** — also zero importance when V12 features are working
- **V14 + Huber combination** — creates severe UNDER bias (-1.73 vegas bias)
- **Combining features + Huber + quantile** — techniques don't stack (Session 243-244 finding confirmed)

---

## Next Steps

1. **Shadow deploy RSM50_HUBER_V2** — first model to pass all 6 gates
2. **Extend eval window to 2026-02-20** — V12_RSM50_FIXED needs 15 more edge 3+ picks to pass sample gate
3. **Implement 3PT cold filter** as post-prediction rule (not model feature)
4. **Validate 3PT cold filter out-of-sample** — test on Feb 13-20 predictions
5. **Consider removing V13/V14 from feature contract** — they add complexity with zero value

---

## Model Artifact

**RSM50_HUBER_V2 (ALL GATES PASSED):**
- File: `models/catboost_v9_50f_noveg_train20251102-20260131_20260213_213149.cbm`
- SHA256: `27d213a82308215ea40560e6c6973f227f486080cdfad1daadc201d20f0bc916`
- Size: 940,336 bytes
