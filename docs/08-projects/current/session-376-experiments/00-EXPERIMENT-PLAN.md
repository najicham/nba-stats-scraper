# Session 376 Experiment Plan & Results

**Date:** 2026-03-01
**Context:** All production models BLOCKED. Feature 41/42 (spread) fixed in Session 375. New retrain deployed as shadow (`catboost_v12_noveg_train0110_0220`). Fleet trimmed from 24 → 13 enabled models.

## System State at Start

- **Season record:** 75-36 (67.6%), +32.25 units
- **Last 7d best bets:** 5-7 (41.7%) — below breakeven
- **Last 30d best bets:** 30-22 (57.7%) — above breakeven
- **All models BLOCKED** except INSUFFICIENT_DATA models still accumulating
- **Feature 41/42 spread data now available** for first time ever
- **New signals deployed** but not yet firing (will fire Mar 1)

## Pre-Experiment Actions (P2-P4)

### P2: Retrain (COMPLETE)
- **Model:** `catboost_v12_noveg_train0110_0220` (V12_NOVEG + vw015, 42d window)
- **Results:** 65.62% edge 3+ HR (N=32), OVER 80.0%, UNDER 59.1%, vegas bias -0.41
- **Status:** Uploaded to GCS, registered, enabled as shadow

### P3: Signal Verification (COMPLETE)
- New signals (fast_pace_over, volatile_scoring_over, low_line_over, line_rising_over) are correctly deployed but Feb 28 predictions were generated before deployment
- Will fire starting Mar 1 predictions

### P4: Fleet Triage (COMPLETE)
- Disabled 11 dead models (all <42% HR with N>=5)
- Fleet reduced from 24 → 13 enabled models

---

## Experiment Results

### E1: Direction-Specific Models — DEAD END

**Hypothesis:** Separate OVER/UNDER regression models can specialize better.

**Finding:** Feature distributions between OVER and UNDER outcomes are nearly identical:
- OVER avg season pts: 14.7 vs UNDER: 16.2
- OVER avg opponent pace: 0.4 vs UNDER: 0.3
- OVER avg usage: 99.44 vs UNDER: 98.93

No meaningful feature divergence. Combined with previous finding that binary OVER/UNDER classifier achieved AUC 0.507 (random), direction-specific models are not viable.

**Additional issue:** Circular dependency — at prediction time, we don't know the direction (the model determines it), so we can't select the right sub-model.

**Verdict:** DEAD END. Do not revisit.

---

### E2: Dynamic Edge Threshold by Model Age — DEAD END

**Hypothesis:** Older models need higher edge thresholds as their edges become miscalibrated.

**Finding:** Model age does NOT drive HR degradation. Calendar date is the true confound.

**V12 HR by weeks since training (edge 3+):**
| Week | HR | N |
|------|-----|-----|
| 0 | 60.5% | 81 |
| 1 | 55.8% | 104 |
| 2 | 51.6% | 186 |
| 3 | 60.5% | 167 |
| 4 | 54.9% | 133 |

No monotonic decline. Week 3 matches week 0 (60.5%).

**Definitive single-model test** (`catboost_v12_train1102_1225`):
- Week 2 (JAN): 59.2%
- Week 3 (JAN): **73.1%** ← improved with age
- Week 4 (JAN): **83.3%** ← continued improvement
- Week 8 (FEB): 54.5% ← February regime shift, not age

**Edge magnitudes stable across age:** avg edge 1.31 at week 0 → 1.75 at week 4. No compression.

**Conclusion:** The February decline is a distributional regime shift (usage_spike_score collapse per Session 370), not model staleness. Existing HR-weighted model selection (Session 365) and retrain cadence already address the real problem.

**Verdict:** DEAD END. Do not implement age-based edge floors.

---

### E3: Post-All-Star-Break Regime Training — BLOCKED

**Hypothesis:** Post-ASB data captures current regime better.

**Finding:** Only 637 training-ready samples post-ASB (Feb 21+). Need 2,000+ minimum.

**Verdict:** BLOCKED by insufficient data. Would need ~3 weeks of post-ASB accumulation (mid-March). By then, standard retrains would capture the same data.

---

### E4: Ensemble of Time Windows — DEAD END

**Hypothesis:** Averaging predictions from 35d/49d/63d models reduces variance.

**Results:**
| Window | Edge 3+ HR | N | OVER | UNDER |
|--------|-----------|---|------|-------|
| 35d (Jan 17-Feb 20) | 64.86% | 37 | 80.0% | 59.3% |
| 42d (Jan 10-Feb 20) | 65.62% | 32 | 80.0% | 59.1% |
| 63d (Dec 19-Feb 20) | 64.00% | 25 | 66.7% | 61.5% |

All three clustered at 64-66% — within noise (<5pp threshold from Session 369). Feature importance nearly identical across all three (points_avg_season dominates at 21-22% in all).

**Why it fails:** Same feature set + heavily overlapping training data = near-identical predictions. Ensemble diversity requires model diversity (different feature sets, algorithms, or fundamentally different training approaches).

**Verdict:** DEAD END. Window-based ensemble adds no value when models share feature set.

---

### E5: Line-Level Segmentation — DEAD END (No Action Needed)

**Hypothesis:** Different line ranges need different edge floors.

**Best bets results by line range (Dec 1+):**
| Line Range | HR | N | Dominant Direction |
|------------|-----|----|--------------------|
| Low (<12.5) | 73.0% | 37 | OVER (100%) |
| Mid (12.5-20.5) | 65.0% | 40 | Mixed (OVER 62.5%) |
| High (>20.5) | 61.5% | 39 | UNDER (79.5%) |

**Key findings:**
- **Low OVER edge 5+ is the best raw segment:** 82.6% HR (N=46)
- **High UNDER edge does NOT scale:** 60.5% at E3-4, then flat at 52-57% at E5+. Higher edge is not a quality signal for high-line UNDER
- **Mid OVER Feb collapse:** 80% → 40% (N=10). Aligns with broader OVER decline
- **Low UNDER already blocked:** Bench UNDER filter catches 33.5% HR segment. Zero Low UNDER in best bets

**Conclusion:** The existing filter stack (bench UNDER block, signal count >= 3, model affinity blocking) already handles line-range differences effectively. All three ranges are above breakeven in best bets (61.5-73.0%). No new line-range-specific edge floors warranted.

**Verdict:** DEAD END. Filter stack is sufficient.

---

## Summary

| Experiment | Status | Finding |
|-----------|--------|---------|
| E1: Direction-specific | DEAD END | Feature distributions identical, circular dependency |
| E2: Dynamic edge by age | DEAD END | Calendar date, not age, drives HR — no monotonic decline |
| E3: Post-ASB training | BLOCKED | Only 637 samples (need 2,000+) |
| E4: Window ensemble | DEAD END | 64-66% across all windows, no diversity to exploit |
| E5: Line segmentation | DEAD END | Filter stack already handles; all segments profitable |

**Key insight from this session:** The system's remaining alpha comes from the filter/signal stack, not from model architecture changes. All five experiments confirm that within the current CatBoost V12 framework, the model produces roughly the same quality predictions regardless of training window, feature engineering, or edge thresholds. The February decline is structural (usage_spike_score distributional shift) and addressable only by retraining on fresh data — which we did in P2.

## Models Saved (Local Only, Not Deployed)

- `models/catboost_v12_50f_noveg_train20260117-20260220_20260228_230121.cbm` (35d, E4)
- `models/catboost_v12_50f_noveg_train20251219-20260220_20260228_230224.cbm` (63d, E4)
