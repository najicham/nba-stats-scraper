# Session 385: Per-Model Profile Filtering & Signal Effectiveness Investigation

**Date:** 2026-03-02
**Status:** Complete — No interventions warranted
**Prerequisite:** Session 384 deployed model_profile_daily (Phase 0+1, observation mode)

## Executive Summary

Investigated whether per-model (or per-group) profile blocking, group-specific signal exclusions, star tier blocks, or direction-aware model selection would improve best bets performance. **All 5 decision gates returned NO-GO.** The current filter stack is already highly effective at screening out weak slices before they reach best bets.

The most important finding: the AWAY profile block — which looked correct at the raw prediction level — would have **removed profitable picks** (66.7% HR) from best bets. This validates the decision to deploy profiling in observation mode first.

## Key Insight: 4 Affinity Groups, Not 33 Models

Within each affinity group, models make identical predictions on the same players:

| Group | Models | Best Bets N | Best Bets HR |
|-------|--------|-------------|--------------|
| v9 | catboost_v9_* (excl. low_vegas) | 66 | 63.6% |
| v12_vegas | catboost_v12_* (with vegas) | 35 | 74.3% |
| v12_noveg | v12_noveg, v16_noveg, lgbm_v12_noveg | 12 | 58.3% |
| v9_low_vegas | catboost_v9_low_vegas_* | 4 | 75.0% |

Per-model filtering is the wrong abstraction. Per-group filtering (4 groups) is the correct granularity — but even group-level interventions lack sample size to justify activation.

## Diagnostic Queries & Results

### Q1: Signal Effectiveness by Affinity Group

**Question:** Do signals perform differently across groups? If gap >10pp on N>=15, add group-specific signal exclusions.

| Signal | v9 HR (N) | v12_noveg HR (N) | v12_vegas HR (N) | Gap |
|--------|-----------|-------------------|-------------------|-----|
| book_disagreement | — | **14.3% (7)** | — | Dramatic but N<15 |
| edge_spread_optimal | 64.6% (65) | 60.0% (10) | **20.0% (5)** | 40pp+ but N=5 |
| high_edge | 64.6% (65) | 60.0% (10) | **20.0% (5)** | 40pp+ but N=5 |
| combo_3way | 85.7% (14) | — | — | Only v9 data |
| combo_he_ms | 84.6% (13) | — | — | Only v9 data |

**Verdict: NO-GO.** The gaps are dramatic but no signal meets the >10pp threshold with N>=15 on both sides. v12_noveg's `book_disagreement` at 14.3% (1/7) is the strongest candidate — monitor until N>=15.

### Q2: Profile Blocking Counterfactual

**Question:** If we had activated profile blocking, what HR would the blocked picks have had? If <45%, activate. If >52.4%, don't.

| Dimension | Blocked HR | N | Assessment |
|-----------|-----------|---|------------|
| tier=bench | 0.0% | 1 | Correct to block, tiny N |
| direction=OVER | 0.0% | 2 | Correct to block, tiny N |
| tier=role | 33.3% | 3 | Correct to block, tiny N |
| direction=UNDER | 50.0% | 2 | Borderline |
| tier=starter | 50.0% | 6 | Borderline |
| **home_away=AWAY** | **66.7%** | **12** | **WRONG — blocks profitable picks** |

**Verdict: NO-GO.** The AWAY dimension dominates blocked volume (12/26 picks) and those picks are winning at 66.7%. Activating blocking wholesale would hurt performance. Direction and tier blocks trend correct but sample sizes are too small (N=1-6).

### Q3: Group x Direction x Tier Cross-Tab

**Question:** Any group+direction+tier combo with HR <45% and N>=10?

| Combo | HR | N |
|-------|-----|---|
| v9 OVER starter | 45.5% | 11 |
| v9 OVER role | 50.0% | 8 |
| v12_noveg UNDER star | 60.0% | 5 |
| v12_vegas UNDER star | 66.7% | 12 |
| v9 OVER bench | 72.7% | 22 |
| v9 UNDER starter | 75.0% | 16 |
| v12_vegas OVER starter | 87.5% | 8 |
| v12_vegas OVER bench | 100.0% | 7 |

**Verdict: NO-GO.** v9 OVER starter at 45.5% (N=11) is 0.5pp above the 45% threshold. Close but not actionable. All other combos are above breakeven.

### Q4: Selection Swap Analysis

**Question:** For best bets losses, would another group's prediction have won? If net_swap_benefit >5, implement direction-aware model selection.

| Selected → Alt | N | Swap Would Win | Swap Would Lose | Net Benefit |
|----------------|---|----------------|-----------------|-------------|
| v9 → v12_vegas | 14 | 1 | 0 | +1 |
| v12_vegas → v9 | 39 | 0 | 1 | -1 |

**Verdict: NO-GO.** Maximum net benefit is ±1. Current model selection via `edge * model_hr_weight` in ROW_NUMBER is already effectively optimal.

### Q5: Star Tier Monthly Trend

**Question:** Is star UNDER consistently <45%? If so, add universal star UNDER block.

| Month | Direction | HR | N |
|-------|-----------|-----|---|
| 2026-01 | UNDER | 63.6% | 11 |
| 2026-02 | OVER | 66.7% | 3 |
| 2026-02 | UNDER | 55.6% | 9 |

**Verdict: NO-GO.** Star UNDER is above breakeven in all months (63.6% Jan, 55.6% Feb). The profile system flagged star weakness at the raw prediction level (41-48%), but the filter stack screens out the losers before they reach best bets.

## Monthly Trend by Group

All groups declined in February — this is the known structural Feb degradation, not a group-specific problem.

| Group | Jan HR (N) | Feb HR (N) | Delta |
|-------|-----------|-----------|-------|
| v9 | 67.5% (40) | 57.7% (26) | -9.8pp |
| v12_vegas | 81.5% (27) | 50.0% (8) | -31.5pp |
| v12_noveg | — | 50.0% (10) | Feb only |
| v9_low_vegas | — | 75.0% (4) | Feb only, tiny N |

v12_noveg's weak 58.3% overall HR is explained by having all its picks in Feb. v12_vegas declined the most (-31.5pp) but from a very high Jan base.

## Why the Filter Stack Already Works

The investigation confirms that raw prediction weakness doesn't reach best bets because existing filters are layered:

1. **Signal count >= 3** — low-quality predictions don't accumulate enough supporting signals
2. **Edge >= 3** — low-conviction predictions are excluded
3. **Player blacklist** — chronic losers are caught at the player level
4. **Direction blocks** (v9 UNDER 5+, v12_noveg/v9 AWAY) — worst model-direction combos already filtered
5. **Tier blocks** (bench UNDER < 12) — structural losers excluded
6. **Model HR weighting** — stale/weak models get downweighted in ROW_NUMBER selection

The profile system identifies the same weaknesses as these hardcoded filters — it's validating that the existing stack is correct, not finding new gaps.

## Items to Monitor

| Item | Current | Threshold to Act | Expected Timeline |
|------|---------|-------------------|-------------------|
| book_disagreement for v12_noveg | 14.3% (N=7) | N>=15 and HR <40% | ~3 weeks |
| v12_noveg group overall | 58.3% (N=12) | N>=30 and HR <50% | ~4 weeks |
| v9 OVER starter | 45.5% (N=11) | N>=20 and HR <45% | ~2 weeks |
| Profile blocking direction/tier | Mixed (N=14) | N>=30 aggregate | ~4 weeks |

## Recommendations

1. **Keep profile blocking in observation mode.** Insufficient data to activate, and AWAY blocks are actively harmful.
2. **No new filters or signal exclusions.** All candidates fail sample size thresholds.
3. **Re-evaluate in 3-4 weeks** when monitoring items reach sample thresholds.
4. **Focus March effort on retraining** — the Feb decline is structural (all configs drop -10 to -30pp). Fresh models trained on Dec-Jan data with the 56-day window are the highest-leverage improvement.

## Decision Gates Summary

| Gate | Threshold | Actual | Verdict |
|------|-----------|--------|---------|
| Q1: Signal gap >10pp, N>=15 | N>=15 both sides | Max N=7 | **NO-GO** |
| Q2: Blocked HR <45% | <45% aggregate | AWAY=66.7% (profitable) | **NO-GO** |
| Q3: Combo HR <45%, N>=10 | <45% | 45.5% (0.5pp above) | **NO-GO** |
| Q4: Net swap >5 | >5 | ±1 | **NO-GO** |
| Q5: Star UNDER <45% all months | <45% | 55.6-63.6% | **NO-GO** |
