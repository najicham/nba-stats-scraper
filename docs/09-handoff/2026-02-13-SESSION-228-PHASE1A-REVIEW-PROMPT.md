# Phase 1A Experiment Review Prompt

**Context:** We just completed Phase 1A experiments testing the Vegas-free baseline architecture across 4 eval windows and 6 configuration variants (9 total experiments). Results are documented.

---

## Review Request

I need you to review the Phase 1A experiment results and provide analysis/recommendations.

**Results Document:** `docs/08-projects/current/model-improvement-analysis/21-PHASE1A-RESULTS.md`

## What Was Done

Ran 9 experiments testing Vegas-free V2 architecture (MAE loss, no Vegas features 25-28):

**Experiment 1: Baseline on 4 Eval Windows**
1. VF_BASE_FEB26 — Feb 2026 (problem period): **48.89% HR** (n=135)
2. VF_BASE_FEB25 — Feb 2025 (benchmark): **69.35% HR** (n=186) ✅
3. VF_BASE_JAN26 — Jan 2026 (pre-decay): **64.13% HR** (n=276) ✅
4. VF_BASE_DEC25 — Dec 2025 (early season): **50.85% HR** (n=470)

**Experiment 2: Training Window Variants (Feb 2026 only)**
5. VF_BASE_180D — 180-day training: **48.89% HR** (identical to baseline)
6. VF_BASE_STD — Season-to-date: **47.73% HR** (worse)

**Experiment 3: Loss Function Test (Feb 2026 only)**
7. VF_HUBER — Huber loss: **46.94% HR** (worse, 75% single feature importance)

**Experiment 4: Feature Ablation (Feb 2026 only)**
8. VF_NO_DEAD — Remove 5 dead features: **50.40% HR** (+1.5% marginal gain)
9. VF_LEAN — Remove 10 features: **48.03% HR** (no gain)

## Key Findings Summary

**What Worked:**
- Feb 2025: 69.35% HR with 29% OVER picks (66.7% OVER HR, 70.5% UNDER HR) ✅
- Jan 2026: 64.13% HR with 36.6% OVER picks (74.3% OVER HR, 58.3% UNDER HR) ✅
- MAE loss solves directional bias (vs quantile regression <5% OVER picks)
- Vegas-free architecture is fundamentally viable

**What Failed:**
- Feb 2026: ALL configurations < 50.4% HR (below breakeven 52.4%)
- Training window manipulation useless (90d, 180d, STD all ~48-49% HR)
- Loss function optimization insufficient (Huber worse than MAE)
- Feature ablation marginal (removing dead features only +1.5%)

**Root Cause Hypothesis:**
- Training data quality: 65.7% training-ready (Feb 2026) vs 82.3% (Feb 2025)
- Model over-indexing: 29-36% importance on `points_avg_season` in failed periods vs 14-22% in successful periods
- Walk-forward degradation: Feb 2026 declines from 53.9% → 50.6% → 42.4% over 3 weeks

## Decision Gates

| Gate | Result | Threshold | Status |
|------|--------|-----------|--------|
| Feb 2025 HR | **69.35%** | > 60% | ✅ PASS |
| Feb 2026 HR | **48.89%** | > 50% | ❌ FAIL |
| OVER picks exist | 11-36% | > 10% | ✅ PASS |
| Both OVER/UNDER > 45% | Mixed | > 45% | ⚠️ PARTIAL |

## Your Task

Please review `docs/08-projects/current/model-improvement-analysis/21-PHASE1A-RESULTS.md` and provide:

1. **Analysis of results** — Do you agree with the findings? Any patterns I missed?

2. **Root cause assessment** — Is the training data quality hypothesis plausible? Are there other explanations for Feb 2026 failure?

3. **Decision recommendation** — Should we:
   - **PROCEED** to Phase 1B (add V12 features)?
   - **PAUSE** and investigate data quality issues first?
   - **PIVOT** to a different approach?

4. **Phase 1B design** (if proceeding) — Which V12 features are most likely to help? Should we modify the experiment protocol?

5. **Risk assessment** — What's the probability that V12 features solve Feb 2026? Or is this a data quality problem that feature engineering can't fix?

## Reference: Original Decision Gates

From the original plan:

```
┌─────────────────────────────────────────┬─────────────────────────────────────────────────────────────────┐
│                 Result                  │                            Decision                             │
├─────────────────────────────────────────┼─────────────────────────────────────────────────────────────────┤
│ Feb 2025 HR > 60% AND Feb 2026 HR > 50% │ PROCEED to Phase 1B (add V12 features)                          │
├─────────────────────────────────────────┼─────────────────────────────────────────────────────────────────┤
│ Feb 2025 HR > 60% BUT Feb 2026 HR < 50% │ PROCEED but expect Feb 2026 is hard; new features may help      │ ← WE ARE HERE
├─────────────────────────────────────────┼─────────────────────────────────────────────────────────────────┤
│ Feb 2025 HR < 55%                       │ PAUSE — Vegas-free model can't predict well enough. Re-examine. │
└─────────────────────────────────────────┴─────────────────────────────────────────────────────────────────┘
```

We're in the **"PROCEED but expect Feb 2026 is hard"** scenario.

## Additional Context

- **V12 features available:** 15 new features (opponent matchup, volatility, recent trends, defensive coverage)
- **Implementation status:** V12 feature extractor already exists in codebase
- **Current champion:** Decayed from 71.2% → 39.9% edge 3+ HR (35+ days stale)
- **Urgency:** Champion is below breakeven; we need a solution soon

---

**Please read the full results document and provide your strategic recommendation.**
