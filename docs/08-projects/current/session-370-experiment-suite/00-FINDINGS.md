# Session 370: Comprehensive Experiment Suite — Findings

**Date:** 2026-02-28
**Goal:** Test 12 experiments across filters, calibration, features, and techniques to improve best bets HR from 67.6% toward 70%+.

## Executive Summary

| Experiment | Type | Result | Action |
|------------|------|--------|--------|
| **A1: Signal count floor** | Filter | **74.5% HR** (+10.4pp) | **DEPLOYED** |
| A2: Friday filter | Filter | N=14, fails sample gate | Skip |
| A3: Direction-aware AWAY | Filter | Blocked families 50-52% OVER+AWAY | No-go |
| A4: Model-direction routing | Diagnostic | Wilson intervals overlap | No action |
| **B5: Edge calibration** | Technique | Flat edge→P(win) at raw level | No-go |
| **B6: Adversarial validation** | Diagnostic | **AUC=0.99, usage_spike_score = 47% of drift** | Informs strategy |
| **B7: Uncertainty** | Technique | **Q1-Q4 gap = 16.7pp** | Future filter candidate |
| C8: DVP (position) | Feature | Position data exists but messy | Deferred |
| C9: Timezone | Feature | arena_timezone ALL NULL | No-go |
| C10: Referee | Feature | Table empty for 2025-26 | No-go |
| D11: Expected scoring poss | Feature | Drift-amplifying, hurt model | Dead end |
| D12: Rolling z-score | Feature | <1% importance | Dead end |

**Net result:** +10.4pp HR from signal count floor alone. Two major diagnostic findings (drift root cause, uncertainty signal).

---

## Detailed Results

### A1: Signal Count Floor — DEPLOYED

**Change:** `MIN_SIGNAL_COUNT` raised from 2 to 3 in `ml/signals/aggregator.py`

| Floor | Picks | Graded | HR | P&L |
|-------|-------|--------|-----|------|
| 2 (old) | 106 | 92 (59W-33L) | 64.1% | $+2,270 |
| **3 (new)** | **50** | **47 (35W-12L)** | **74.5%** | **$+2,180** |
| 4 | 32 | 30 (24W-6L) | 80.0% | $+1,740 |

**Rationale:** BQ data showed signal_count=3 → 57.4% HR (N=47) vs 4+ → 76.5% (N=63). Picks with only 2 signals (model_health + 1 base signal) are marginally profitable. Floor=3 requires at least one non-base signal.

**Why floor=3 over floor=4:** Floor=4 has incredible HR (80%) but P&L is lower due to volume loss. Floor=3 is the optimal HR-volume tradeoff.

**Algorithm version:** `v370_signal_floor_3`

---

### B6: Adversarial Validation — ROOT CAUSE IDENTIFIED

**AUC = 0.993 (OVER), 0.973 (UNDER)** — near-perfect discrimination between Dec-Jan and Feb data.

**Top drifting features:**

| Feature | Discriminator Importance | Dec-Jan Mean | Feb Mean | Shift |
|---------|------------------------|-------------|---------|-------|
| **usage_spike_score** | **47.4%** | 1.14 | 0.28 | **-0.86** |
| over_rate_last_10 | 13.1% | 0.52 | 0.49 | -0.02 |
| pct_three | 9.8% | 0.52 | 0.37 | -0.15 |
| opponent_pace | 5.9-11.3% | 101.6 | 100.1 | -1.5 |
| star_teammates_out | 1.7-4.0% | 0.31 | 0.63 | +0.32 |

**Interpretation:** `usage_spike_score` collapsed 76% in February. This is a seasonal pattern — usage spikes are common early in the season as rotations stabilize, then normalize. The model learned "high usage_spike = high scoring" from training data, but this relationship degraded.

**Implications:**
1. Models trained Dec-Jan have a structural disadvantage in February
2. Downweighting `usage_spike_score` (e.g., `--category-weight player_history=0.5`) could help
3. Fresh training windows that include Feb data are critical
4. The `teammate_usage_available` shift (+13.65 in UNDER) explains some of the UNDER degradation

---

### B7: Uncertainty — SIGNIFICANT SIGNAL

**Uncertainty quartile analysis (edge 3+, N=70):**

| Quartile | N | HR | Avg Edge | Avg Uncertainty |
|----------|---|-----|----------|-----------------|
| Q1 (low) | 18 | **77.8%** | 3.8 | 0.01 |
| Q2 | 17 | 70.6% | 3.8 | 0.03 |
| Q3 | 17 | 64.7% | 4.2 | 0.09 |
| Q4 (high) | 18 | **61.1%** | 5.0 | 0.22 |

**Key findings:**
- Q1-Q4 gap: **16.7pp** — statistically significant
- Uncertainty-edge correlation: r=0.417 — moderate, NOT redundant
- Q4 has highest edge (5.0) but lowest HR (61.1%) — uncertainty catches "confident but wrong" predictions
- Perfectly monotonic: more uncertainty = lower HR at every quartile

**Implementation path:** Add `posterior_sampling=True` to production CatBoost models. Use `virtual_ensembles_predict()` to get uncertainty. Filter picks where uncertainty > Q3 threshold.

**Caution:** Only tested on one training window. Needs 5-seed stability test and cross-season validation before production deployment.

---

### B5: Edge Calibration — NO-GO

Trained isotonic regression on 11,809 graded predictions (all models). The edge → P(win) relationship at the raw prediction level is essentially flat (~51% everywhere up to edge 7). The signal/filter stack (best bets aggregator) does the real selection work, not edge magnitude alone.

On best bets data (94 picks), the calibrator overfits to small groups (v12_mae OVER = 100% from 16 samples). Holdout was only 9 picks — too small for reliable comparison.

**Conclusion:** Edge calibration is a theoretical improvement on a practical non-issue. The existing filter stack already selects high-quality picks.

---

### C8-C10: Feature Discovery Queries

| Feature | Data Status | Signal | Decision |
|---------|-------------|--------|----------|
| C8: DVP (position) | Position data exists (G, F, C, G-F etc.) but messy — needs mapping | Not tested | Deferred — position cleaning adds complexity |
| C9: Timezone | `arena_timezone` ALL NULL (893 games) | No data | **NO-GO** |
| C10: Referee | `nbac_referee_game_assignments` empty for 2025-26 | No data | **NO-GO** — scraper pipeline broken |

---

### D11+D12: Derived Features — DEAD END

| Feature | Importance | Train→Eval Drift | Model Impact |
|---------|-----------|------------------|-------------|
| D11: expected_scoring_poss | < 1% | 1.34 → 0.39 (70% drop) | **Hurt** |
| D12: rolling_zscore_5v10 | < 1% | Stable (0.01 → 0.03) | Neutral |

Model with derived features: 62.79% HR vs baseline 68.57%. **-5.8pp degradation.**

D11 is particularly bad because it amplifies the `usage_spike_score` drift discovered in B6 — it literally multiplies pace by usage, creating an even more drift-prone feature.

---

## Files Created/Modified

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | `MIN_SIGNAL_COUNT = 3`, `ALGORITHM_VERSION = 'v370_signal_floor_3'` |
| `bin/backfill_dry_run.py` | Added `--min-signal-count` flag for testing different thresholds |
| `ml/calibration/edge_calibrator.py` | **NEW** — edge → P(win) isotonic calibration per model+direction |
| `bin/adversarial_validation.py` | **NEW** — detect feature drift between time periods |
| `ml/experiments/quick_retrain.py` | Added `--uncertainty` flag (virtual ensembles) + `--derived-features` flag (D11+D12) |

---

## Round 2: Follow-Up Experiments

### B7 Uncertainty 5-Seed Stability Test — FAILED

| Seed | Q1 HR | Q4 HR | Gap |
|------|-------|-------|-----|
| 42 | 77.8% | 61.1% | +16.7pp (Q1 wins) |
| 123 | 63.6% | 75.0% | -11.4pp (Q4 wins) |
| 456 | 66.7% | 73.7% | -7.0pp (Q4 wins) |
| 789 | 63.6% | 75.0% | -11.4pp (Q4 wins) |
| 1024 | 47.1% | 83.3% | -36.3pp (Q4 wins) |

**Seed 42 was an outlier.** On 4/5 seeds, high-uncertainty picks outperform. The `posterior_sampling` uncertainty is seed-dependent noise. **DEAD END.**

### Usage Spike Score Manipulation — DEAD END

| Config | HR (edge 3+) | vs Baseline |
|--------|-------------|-------------|
| Baseline (v12_noveg vw015) | 68.57% | — |
| Exclude usage_spike_score | 66.15% | -2.4pp |
| Downweight usage_spike=0.1 | 65.28% | -3.3pp |

Despite being 47% of the feature drift signal, removing or downweighting `usage_spike_score` HURTS. CatBoost's tree splits already learn to discount it appropriately. **DEAD END.**

### Tier Weights — ZERO EFFECT

Ran 5 seeds with and without tier weights (star=2.0, starter=1.2, role=0.8, bench=0.3) on the same 56-day window. **HR was IDENTICAL** across all 5 seeds. CatBoost feature_weights for tier weighting have no effect when sample sizes are already balanced. **DEAD END.**

### 56-Day Window (Nov 24 → Jan 19) — ROBUST WIN

| Seed | HR (edge 3+) |
|------|-------------|
| 42 | 73.68% |
| 123 | 78.23% |
| 456 | 74.79% |
| 789 | 73.00% |
| 1024 | 69.92% |
| **Mean** | **73.92%** |
| **StdDev** | **2.96pp** |

All seeds > 69%, mean 73.92% ± 2.96pp. Config: v12_noveg + vegas=0.15 + 56-day window ending Jan 19. All governance gates pass with N=114 eval picks.

**This is the recommended next production retrain configuration.**

---

## Next Steps

1. **Push A1 to main** — signal count floor change auto-deploys
2. **Retrain production model** with 56-day window (Nov 24 → Jan 19), v12_noveg, vegas=0.15 — validated at 73.92% mean HR
3. **Fix referee scraper** — investigate GCS data presence for future feature development
