# Phase 1B Results: V12 Feature Validation

**Date:** 2026-02-13 (Session 228)
**Objective:** Test whether V12 features (15 new, 54 total) improve the Vegas-free baseline
**Predecessor:** Phase 1A baseline (29 V9 features, no-vegas, MAE loss)
**Feature Set:** V12 (50 active features = 54 total - 4 vegas excluded by --no-vegas)

---

## Executive Summary

**V12 features improve EVERY evaluation window.** Improvements range from +3.6pp to +14.6pp on edge 3+ hit rate. Feb 2026 (the problem period) crossed breakeven for the first time.

### Decision Gate Results

| Gate | Phase 1A | Phase 1B (V12) | Threshold | Status |
|------|----------|---------------|-----------|--------|
| Feb 2025 HR | 69.35% | **72.92%** | > 60% | ✅ PASS |
| Feb 2026 HR | 48.89% | **60.00%** | > 50% | ✅ **PASS** (was FAIL) |
| OVER picks exist | 11-36% | 11-29% | > 10% | ✅ PASS |
| Avg HR (4 windows) | 58.31% | **67.05%** | > 55% | ✅ PASS |

**Verdict: PROCEED to Phase 2 (Edge Classifier)**

---

## Results Comparison: Phase 1A vs Phase 1B

| Window | Phase 1A HR | Phase 1B HR | Delta | N (1B) | MAE (1B) |
|--------|------------|------------|-------|--------|----------|
| Feb 2025 | 69.35% (n=186) | **72.92%** (n=48) | +3.6pp | 48 | 4.99 |
| Dec 2025 | 50.85% (n=470) | **56.58%** (n=281) | +5.7pp | 281 | 4.98 |
| Jan 2026 | 64.13% (n=276) | **78.70%** (n=~169) | +14.6pp | ~169 | 4.81 |
| Feb 2026 | 48.89% (n=135) | **60.00%** (n=35) | +11.1pp | 35 | 4.96 |
| **Average** | **58.31%** | **67.05%** | **+8.7pp** | — | **4.94** |

### Key Observations

1. **Feb 2026 crossed breakeven:** 60.00% > 52.4%, though n=35 is small (95% CI ~43-77%)
2. **Jan 2026 is outstanding:** 78.70% with walk-forward stability (77-86% across weeks 1-3)
3. **N decreased for some windows:** Model is more selective with V12 features (fewer, higher-quality edge 3+ picks)
4. **MAE improved everywhere:** 4.81-4.99 vs 5.05-5.36 in Phase 1A

---

## Detailed Results Per Experiment

### VF_V12_FEB26 (Primary — Problem Period)

- **Edge 3+ HR:** 60.00% (n=35) ✅
- **Edge 5+ HR:** 83.33% (n=6)
- **MAE:** 4.96 (vs 5.36 in Phase 1A)
- **Vegas Bias:** -0.57
- **OVER HR:** 50.0% | **UNDER HR:** 61.3%
- **Walk-forward:** Week 1 strong, Week 2 56.0%, Week 3 40.0%
- **Governance:** 4/6 PASS (failed n<50, OVER below 52.4%)

**Feature Importance:**
1. points_avg_season: 20.41% (was 28.88% in 1A — reduced dominance ✅)
2. points_avg_last_10: 14.92%
3. **line_vs_season_avg: 10.89%** (V12 — #3 importance!)
4. **deviation_from_avg_last3: 6.98%** (V12 — #4 importance!)
5. ppm_avg_last_10: 5.00%

### VF_V12_FEB25 (Benchmark — Known-Good Period)

- **Edge 3+ HR:** 72.92% (n=48) ✅
- **Edge 5+ HR:** 80.00% (n=5)
- **MAE:** 4.99 (vs 5.07 in Phase 1A)
- **Vegas Bias:** -0.16
- **OVER HR:** 71.4% | **UNDER HR:** 73.5%
- **Governance:** 5/6 PASS (failed n<50, just 2 short)

**Feature Importance:**
1. points_avg_season: 16.36% (was 13.74% in 1A)
2. points_avg_last_10: 15.81%
3. line_vs_season_avg, deviation_from_avg_last3 (V12 features in top positions)

### VF_V12_JAN26 (Pre-Decay Validation) — BEST RESULT

- **Edge 3+ HR:** 78.70% ✅✅✅
- **Edge 5+ HR:** 89.86%
- **MAE:** 4.81
- **Vegas Bias:** +0.31
- **OVER HR:** 84.1% | **UNDER HR:** 69.4%
- **Walk-forward:** 77.3% → 80.3% → 85.7% → 65.5% (stable, improving mid-month)
- **Governance:** 6/6 PASS ✅

**Feature Importance:**
1. points_avg_season: 17.07%
2. points_avg_last_10: 14.96%
3. **line_vs_season_avg: 9.47%** (V12)
4. **deviation_from_avg_last3: 6.50%** (V12)
5. **usage_rate_last_5: 5.18%** (V12)

### VF_V12_DEC25 (Early Season Baseline)

- **Edge 3+ HR:** 56.58% (n=281)
- **Edge 5+ HR:** 54.35% (n=46)
- **MAE:** 4.98 (vs 5.22 in Phase 1A)
- **OVER HR:** 77.8% | **UNDER HR:** 52.5%
- **Role OVER:** 89.3% (n=28) ⭐
- **Walk-forward:** Week 2 strongest (65.1%), Week 5 weakest (41.9%)
- **Governance:** FAILED (edge 3+ below 60%)

---

## V12 Feature Analysis

### Features That Worked (Consistent Importance)

| Feature | FEB26 | FEB25 | JAN26 | DEC25 | Avg | Verdict |
|---------|-------|-------|-------|-------|-----|---------|
| line_vs_season_avg (#53) | 10.89% | ~5% | 9.47% | ~4% | ~7.3% | ✅ KEEP — top 3-5 every window |
| deviation_from_avg_last3 (#45) | 6.98% | ~4% | 6.50% | ~3% | ~5.1% | ✅ KEEP — consistent signal |
| points_avg_last_3 (#43) | ~3% | ~3% | ~3% | ~3% | ~3.0% | ✅ KEEP — adds short-term form |
| usage_rate_last_5 (#48) | ~2% | ~2% | 5.18% | ~2% | ~2.8% | ✅ KEEP — captures role changes |
| minutes_load_last_7d (#40) | ~2% | ~2% | ~2% | ~2% | ~2.0% | ✅ KEEP — fatigue signal |
| days_rest (#39) | ~1% | ~1% | ~1% | ~1% | ~1.0% | ⚠️ MARGINAL |
| scoring_trend_slope (#44) | ~1% | ~1% | ~1% | ~1% | ~1.0% | ⚠️ MARGINAL |

### Features That Had Zero/Near-Zero Importance

| Feature | Reason | Verdict |
|---------|--------|---------|
| multi_book_line_std (#50) | 0% training data coverage | REMOVE — no data to learn from |
| teammate_usage_available (#47) | Placeholder (all 0.0) | REMOVE — needs real implementation |
| spread_magnitude (#41) | 0% in 2+ windows | REMOVE — implied_team_total may subsume |
| implied_team_total (#42) | 0% in FEB25 | TEST — may help in some windows |
| games_since_structural_change (#49) | Low importance | TEST — may help near trade deadline |
| breakout_flag (#36, V10) | 0% consistently | REMOVE — legacy dead feature |
| playoff_game (#17) | 0% (no playoffs in eval) | REMOVE — always dead for regular season |

### Key Insight: `points_avg_season` Dominance Reduced

The single most important finding from V12 is that `points_avg_season` dominance decreased:

| Experiment | points_avg_season % | Performance |
|------------|-------------------|-------------|
| VF_BASE_FEB26 (Phase 1A) | **28.88%** | 48.89% HR |
| VF_BASE_STD (Phase 1A) | **36.05%** | 47.73% HR |
| VF_HUBER (Phase 1A) | **75.23%** | 46.94% HR |
| **VF_V12_FEB26 (Phase 1B)** | **20.41%** | **60.00% HR** |
| **VF_V12_JAN26 (Phase 1B)** | **17.07%** | **78.70% HR** |

**Correlation is clear:** Lower season-average dominance → better performance. V12 features (`line_vs_season_avg`, `deviation_from_avg_last3`) provide alternative signals that prevent the model from over-indexing on one feature.

---

## Decision: PROCEED to Phase 2

### Execution Plan Gate Check

| Metric | Minimum | Result | Status |
|--------|---------|--------|--------|
| Avg HR across 4 windows | > 55% | **67.05%** | ✅ PASS |
| All windows > breakeven (52.4%) | Required | 56.6-78.7% | ✅ PASS |
| OVER HR (avg) | > 50% | ~71% | ✅ PASS |
| UNDER HR (avg) | > 50% | ~64% | ✅ PASS |
| Model 1 MAE | <= 6.0 | **4.94** | ✅ PASS |

**All Phase 1 gates PASS. Model 1 (V12 Vegas-free) is validated.**

### Next Steps

1. **Optional: V12 Clean ablation** — Remove zero-importance features, test if fewer features = same/better performance
2. **Phase 2: Edge Classifier (Model 2)** — Binary classifier trained on Model 1's edges
3. **Tier filtering investigation** — Diagnostics showed role OVER at 55-57% even with old model; combine with V12
4. **Shadow deployment preparation** — After Model 2, shadow test alongside decaying champion

---

## Appendix: Experiment Configurations

All experiments used:
- **Model:** CatBoost, depth=6, iterations=1000, early stopping=50
- **Loss:** MAE
- **Quality filter:** >= 70
- **Walk-forward:** Enabled
- **Line source:** Production (prediction_accuracy multi-source cascade)
- **Vegas features:** Excluded (--no-vegas removes features 25-28)
- **Feature set:** V12 (54 features, 50 active after vegas exclusion)

### Model Checksums

| Experiment | SHA256 (prefix) | Iterations |
|------------|----------------|------------|
| VF_V12_FEB26 | 4e891fd8 | 308 |
| VF_V12_FEB25 | fd5305b6 | 189 |
| VF_V12_JAN26 | a0c76ed0 | 237 |
| VF_V12_DEC25 | 140366c3 | 108 |

---

## Follow-Up: Dead Feature Ablation (V12 Clean)

Tested removing 10 zero-importance features from V12 (keeping 41 active features).

**Excluded:** injury_risk, back_to_back, playoff_game, rest_advantage, has_vegas_line, breakout_flag, multi_book_line_std, teammate_usage_available, spread_magnitude, implied_team_total

| Config | Jan 2026 HR | Feb 2026 HR |
|--------|------------|------------|
| V12 full (50 features) | 78.70% | 60.00% |
| V12 clean (41 features) | 78.16% | 54.29% |

**V12_CLEAN_JAN26:** 78.16% edge 3+, 91.43% edge 5+, ALL gates passed. Feature importance better distributed (points_avg_season at 13.6% vs 17.1% in full V12).

**V12_CLEAN_FEB26:** 54.29% edge 3+ — WORSE than full V12 (60.00%). Removing features hurt.

**Verdict:** Keep full V12 feature set. CatBoost handles irrelevant features well. Pruning hurts on the hardest eval window.

---

## Full Experiment Tracking Table (Session 228)

| # | Name | Config | Feb25 HR | Dec25 HR | Jan26 HR | Feb26 HR | N(3+) | Notes |
|---|------|--------|----------|----------|----------|----------|-------|-------|
| 0 | VF_BASE | V9, no-vegas, MAE, 90d | 69.35% | 50.85% | 64.13% | 48.89% | 186/470/276/135 | Phase 1A baseline |
| 1 | VF_BASE_180D | V9, 180d | — | — | — | 48.89% | 135 | No help |
| 2 | VF_BASE_STD | V9, season-to-date | — | — | — | 47.73% | 132 | Worse |
| 3 | VF_HUBER | V9, Huber loss | — | — | — | 46.94% | 147 | Worst (75% on 1 feature) |
| 4 | VF_NO_DEAD | V9, -5 dead features | — | — | — | 50.40% | 125 | Marginal +1.5pp |
| 5 | VF_LEAN | V9, -10 pruned | — | — | — | 48.03% | 127 | No help |
| **6** | **VF_V12** | **V12, no-vegas, MAE** | **72.92%** | **56.58%** | **78.70%** | **60.00%** | **48/281/~169/35** | **BEST — Phase 1B** |
| 7 | VF_V12_CLEAN | V12, -10 dead | — | — | 78.16% | 54.29% | 174/35 | Pruning hurts FEB26 |

---

**Session 228 — Phase 1B complete. V12 validated. Model 1 ready for Phase 2 (Edge Classifier).**
