# Phase 0 Diagnostic Results - Web Chat Briefing

**Session 228 completed all 6 diagnostic BigQuery queries.** Full results: `docs/08-projects/current/model-improvement-analysis/20-DIAGNOSTIC-RESULTS.md`

---

## Query Results Summary

### Q0: Actual OVER/UNDER Outcome Rates
- **Finding:** Feb 2026 was NOT UNDER-favorable (50.7% OVER / 49.3% UNDER)
- **Gate:** ❌ REJECTED - Q43's edge did NOT come from market bias

### Q1: Vegas Line Sharpness
- **Finding:** Vegas MAE stayed 4.6-4.95 range (Nov 2025: 4.91 → Feb 2026: 4.95)
- **Gate:** ✅ PASSED - Edge pool still exists, Vegas NOT dramatically sharper

### Q2: Trade Deadline Impact
- **Finding:** Traded players: 34.3% HR | Stable players: 27.9% HR (edge 3+ picks)
- **Gate:** ✅ PASSED - Stable players WORSE than traded, trade deadline NOT primary cause

### Q3: Miss Clustering by Tier/Direction
- **Finding:**
  - Role/bench OVER: 55-57% hit rate ✅ PROFITABLE
  - Star OVER: 36% hit rate with 9.6 MAE (vs 6.1 for role players)
  - ALL UNDER picks: 39-49% across all tiers
- **Gate:** ✅ TRIGGERED - Tier-specific filtering required

### Q4: OVER/UNDER Prediction Distribution
- **Finding:** Model ALWAYS had UNDER bias
  - Training: -1.03 avg edge, 45.7% HR, 33.3% OVER picks
  - Post-train: -0.43 avg edge, 38.0% HR, 44.3% OVER
  - Feb 2026: -0.80 avg edge, 25.5% HR, 36.9% OVER
- **Gate:** ✅ CONFIRMED - Gradual decay (45.7% → 25.5%), UNDER bias systemic

### Q5: Feature Drift Detection
- **Finding:** Minimal drift (Vegas: 13.39→13.13, Points L5: 13.68→13.35)
  - Exception: Points std dropped 4.13→3.06 (players MORE consistent)
- **Gate:** ✅ PASSED - NOT a data quality issue, model can't generalize

---

## Critical Discoveries

1. **Model has ALWAYS had UNDER bias** (-1.03 to -0.80 avg edge across all periods)
2. **Decay is gradual, not sudden** (45.7% → 38.0% → 25.5% hit rate over 3 months)
3. **Role/bench OVER picks are the ONLY profitable segment** (55-57% vs 27.9% overall)
4. **Stars are unpredictable** (36-44% HR with 57% higher MAE than role players)
5. **Trade deadline is NOT guilty** (stable players performed worse than traded)
6. **Vegas is still beatable** (4.6-4.95 MAE unchanged, edge pool exists)

---

## Phase 1A Recommendations (Confirmed)

### ✅ Proceed with these approaches:

1. **Vegas-free + MAE loss**
   - Q0/Q4 confirm quantile alpha=0.43 introduced UNDER bias
   - Use standard MAE regression, remove quantile entirely
   - Model architecture is flawed, not just stale data

2. **Tier-based filtering**
   - Q3 proves role/bench OVER picks work (55-57% HR)
   - **Exclude stars (25+ ppg)** from predictions
   - Consider tier-specific confidence thresholds or separate models

3. **Directional bias audit**
   - Q3/Q4 show ALL UNDER picks lose (39-49% across all tiers)
   - Investigate training data OVER/UNDER balance
   - May need asymmetric loss or directional features

### ❌ Deprioritize these:

4. **Trade deadline / structural break features**
   - Q2 shows stable players WORSE than traded (27.9% vs 34.3%)
   - NOT the primary cause of decay
   - Focus on core architecture first

5. **Feature drift fixes**
   - Q5 shows minimal drift, players actually MORE consistent
   - NOT a data quality issue
   - Model overfitting problem, needs better generalization

---

## Target for Phase 1A

**Backtest on Feb 2026 held-out set:**
- Overall hit rate: 53%+ (currently 25.5%)
- Role/bench OVER picks: maintain 55%+
- Stars: excluded or handled separately

**DO NOT proceed to Phase 1B until hitting 53%+ on Feb backtest.**

---

## Next Action

Ready to proceed with V12 model training using:
- Vegas-free architecture (no vegas_points_line in features)
- Standard MAE loss (no quantile alpha)
- 37 features (V9 feature set)
- Tier filtering in postprocessing (exclude stars 25+ ppg)
- Train: 2025-11-02 to 2026-01-31
- Eval: 2026-02-01 to 2026-02-12

Awaiting your approval to begin Phase 1A model training.
