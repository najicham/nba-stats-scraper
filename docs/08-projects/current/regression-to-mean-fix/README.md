# Regression-to-Mean Bias Fix Project

**Created:** 2026-02-03 (Session 107)
**Updated:** 2026-02-03 (Session 111) - Major pivot based on new findings
**Status:** Ready for Implementation
**Priority:** P0 - Implement optimal scenario filters

## Executive Summary

### Original Understanding (Session 107)
The CatBoost V9 model has a systematic regression-to-mean bias:
- Under-prediction of stars by ~9 points
- Over-prediction of bench by ~6 points

### New Understanding (Session 111) ⚠️ KEY INSIGHT

**The star under-prediction bias is NOT hurting hit rate!**

Deep analysis revealed:
- OVER picks on low lines (<12) with edge ≥5: **87.3% hit rate**
- UNDER picks on high lines (≥25) with edge ≥3: **65.9% hit rate**
- The model's conservative predictions help find value on OVER bets

**The real problem:** Betting UNDER on players who might have breakout games.

**The solution:** Scenario-based filtering, not fixing the model bias.

## Optimal Scenarios (Session 111 Discovery)

| Scenario | Hit Rate | ROI | Volume |
|----------|----------|-----|--------|
| **OVER + Line <12 + Edge ≥5** | **87.3%** | +66.8% | 1-2/day |
| **OVER + Any Line + Edge ≥7** | **90.0%** | +80%+ | 0-1/day |
| **UNDER + Line ≥25 + Edge ≥3** | **65.9%** | +25.8% | 1-2/day |

## Anti-Patterns to AVOID

| Avoid | Hit Rate | Why |
|-------|----------|-----|
| UNDER on lines <20 | 0-52% | Breakout risk |
| Any pick with edge <3 | 51% | No signal |
| OVER on high lines (25+) | 48% | Priced correctly |
| UNDER on: Luka, Maxey, Sharpe, Harden, Randle | 20-45% | High variance |

## Quick Links

### Session 111 (New - Implement These First)
- [Optimal Scenarios](./SESSION-111-OPTIMAL-SCENARIOS.md) ⭐ **START HERE**
- [Feature Contract Architecture](./FEATURE-CONTRACT-ARCHITECTURE.md)

### Session 107 (Original Investigation)
- [Investigation Findings](./INVESTIGATION-FINDINGS.md)
- [Option A: Post-hoc Tier Calibration](./OPTION-A-TIER-CALIBRATION.md)
- [Option B: Retrain Without Cold Start Data](./OPTION-B-RETRAIN-CLEAN.md)
- [Option C: V10 Model with Tier Features](./OPTION-C-V10-TIER-MODEL.md)

## Updated Recommendation

### Priority 1: Implement Scenario Filters (High Impact, Low Risk)
1. Create subset definitions for optimal scenarios
2. Add player blacklist for UNDER bets
3. Update Phase 6 to highlight optimal picks

### Priority 2: Model Improvement (Moderate Impact)
4. Deploy Quantile 0.53 as V9.1 (gives +1.4% hit rate)

### Priority 3: Original Options (Lower Priority Now)
- Option A (Calibration) - Testing showed it hurts hit rate
- Option B (Clean Retrain) - Only 15 bad records, minimal impact
- Option C (Tier Features) - Model already handles tiers implicitly

## Success Metrics (Updated)

| Metric | Current | Target | Method |
|--------|---------|--------|--------|
| Optimal scenario hit rate | N/A | 80%+ | Scenario filters |
| High-edge hit rate | 55-65% | 70%+ | Better pick selection |
| Daily optimal picks | 0 | 3-5 | New subsets |
| Blacklist compliance | N/A | 100% | Player filters |

## Key Files

| File | Purpose |
|------|---------|
| `shared/ml/feature_contract.py` | Canonical feature definitions |
| `ml/experiments/bias_fix_experiments.py` | Test different approaches |
| `ml/experiments/quick_retrain.py` | Training with bad record filter |
