# Regression-to-Mean Bias Fix Project

**Created:** 2026-02-03 (Session 107)
**Status:** Planning
**Priority:** P0 - Model is losing money on high-edge picks

## Executive Summary

The CatBoost V9 model has a systematic regression-to-mean bias that causes:
- **Under-prediction of stars** by ~9 points (predicted 21.8, actual 30.9)
- **Over-prediction of bench** by ~6 points (predicted 8.4, actual 2.2)
- **High-edge UNDER bets on stars losing** at 69% rate
- **6 consecutive RED signal days** with heavy UNDER skew

This document outlines three fix options with different time horizons and trade-offs.

## Root Causes Identified

| Root Cause | Impact | Evidence |
|------------|--------|----------|
| Training data imbalance | 57% of samples are 0-10 pt scorers | Training mean = 10.7 pts |
| November cold start | 35% wrong defaults, 8 days missing Vegas | Josh Giddey: 10.0 default vs 23.25 actual L10 |
| Feature completeness correlation | Stars have 95% Vegas coverage, bench 15% | Model learns "features = higher scorer" |
| Vegas following + Vegas bias | Model follows Vegas, but Vegas under-predicts stars | Vegas bias: -6 pts for stars |
| L2 regularization | Shrinks predictions toward mean | `l2_leaf_reg=3.8` |

## Fix Options Overview

| Option | Time to Implement | Risk | Expected Impact |
|--------|-------------------|------|-----------------|
| **A: Post-hoc Tier Calibration** | 1-2 hours | Low | +5-10% high-edge hit rate |
| **B: Retrain Without Nov 2-12** | 2-3 hours | Medium | Fix cold start contamination |
| **C: V10 with Tier Features** | 1-2 days | Medium | Permanent fix, +15-20% star accuracy |

## Quick Links

- [Option A: Post-hoc Tier Calibration](./OPTION-A-TIER-CALIBRATION.md)
- [Option B: Retrain Without Cold Start Data](./OPTION-B-RETRAIN-CLEAN.md)
- [Option C: V10 Model with Tier Features](./OPTION-C-V10-TIER-MODEL.md)
- [Investigation Findings](./INVESTIGATION-FINDINGS.md)

## Recommendation

**Staged approach:**

1. **Immediate (Today):** Implement Option A (tier calibration) - stops bleeding
2. **This Week:** Implement Option B (clean retrain) - fixes training data
3. **Next Week:** Design and test Option C (V10) - permanent solution

## Decision Matrix

| If you want... | Choose... | Why |
|----------------|-----------|-----|
| Fastest fix, minimal risk | Option A | Just post-processing, no model changes |
| Fix root cause in training data | Option B | Clean data = better model |
| Permanent architectural fix | Option C | Model explicitly knows about player tiers |
| Maximum improvement | A + B + C | Layered approach |

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| High-edge hit rate | 41.7% | 65%+ |
| Star (25+) prediction bias | -9.1 pts | < ±3 pts |
| Bench (<5) prediction bias | +6.2 pts | < ±3 pts |
| Consecutive RED days | 6 | < 2 |
