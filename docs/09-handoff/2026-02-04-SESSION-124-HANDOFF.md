# Session 124 Handoff - Model Naming & Subset System Review

**Date:** 2026-02-04
**Duration:** ~3 hours
**Status:** Major findings documented, actionable items identified

---

## Quick Start for Next Session

### Priority Actions

```bash
# 1. Check deployment drift (always first)
./bin/check-deployment-drift.sh --verbose

# 2. Verify new subsets are active
bq query --use_legacy_sql=false "
SELECT subset_id, is_active, recommendation_filter
FROM nba_predictions.dynamic_subset_definitions
WHERE subset_id LIKE '%over%' OR subset_id LIKE '%under%'
ORDER BY created_at DESC LIMIT 5"

# 3. Monitor subset performance (after games complete)
bq query --use_legacy_sql=false "
SELECT
  CASE WHEN recommendation = 'OVER' THEN 'OVER' ELSE 'UNDER' END as direction,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date = CURRENT_DATE() - 1
  AND ABS(predicted_points - line_value) >= 5
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY 1"
```

---

## Session Summary

### Major Discovery: Tier Bias Measurement Was Wrong

**Two methods give vastly different results:**

| Method | Stars Bias | What It Measures |
|--------|------------|------------------|
| Tier by `actual_points` | **-8.7** | Hindsight (WRONG) |
| Tier by `season_avg` | **+0.1** | True calibration (CORRECT) |

**Root cause:** Previous analysis classified a 20 PPG starter who scores 30 as a "star" for that game. This isn't model bias - it's natural variance.

**Documented in:** `docs/08-projects/current/session-124-model-naming-refresh/TIER-BIAS-METHODOLOGY.md`

---

### New Subsets Created

| subset_id | Public ID | Filter | Purpose |
|-----------|-----------|--------|---------|
| `v9_high_edge_over_only` | 10 | edge ≥5, OVER | Exploit OVER advantage |
| `v9_high_edge_under_only` | 11 | edge ≥5, UNDER | Track UNDER performance |
| `v9_high_edge_all_directions` | 12 | edge ≥5, any | Baseline comparison |

Updated `shared/config/subset_public_names.py` with new mappings.

---

### Key Performance Finding: OVER >> UNDER

**30-day high-edge performance by tier:**

| Tier | OVER Hit Rate | UNDER Hit Rate |
|------|---------------|----------------|
| Stars | 90% (n=10) | 65% (n=20) |
| Starters | 87% (n=31) | 73% (n=26) |
| Role/Bench | 76% (n=50) | **47%** (n=17) ⚠️ |

**Critical insight:** UNDER on Role/Bench is losing money. Opus agent analysis found this is due to player volatility (17% breakout rate), not model bias.

---

### Role Player Volatility Analysis (Opus Agent)

**Why UNDER fails on role players:**
- Role players have 17% breakout rate (1.5x+ their average)
- HOT players (L5 > season+3) have 24% breakout rate
- When UNDER misses: predicted 6.7, actual was 16.0

**Recommended filters (improve from 45% to 71% hit rate):**
```python
# Skip role player UNDER when:
if recommendation == 'UNDER' and season_avg between 8-15:
    if points_avg_last_5 - season_avg > 3:  # Player is HOT
        return 'PASS'
    if line_value < 14:  # Low line = high breakout risk
        return 'PASS'
    if edge < 4:  # Need higher edge for role UNDERs
        return 'PASS'
```

**Full analysis:** `docs/08-projects/current/session-124-model-naming-refresh/FINDINGS.md`

---

## Files Modified

| File | Change |
|------|--------|
| `shared/config/subset_public_names.py` | Added IDs 10, 11, 12 for new subsets |
| `ml/calibration/isotonic_calibrator.py` | Created (not deployed yet) |
| `docs/08-projects/current/session-124-model-naming-refresh/` | Project documentation |

---

## Models Trained

| Model | Training Window | Status |
|-------|-----------------|--------|
| `catboost_retrain_V9_20251102_20260131_PROD_*` | Nov 2 → Jan 31 | Saved to `models/` |

**Note:** The "BLOCKED: Critical tier bias" warning is a **false alarm** due to wrong eval methodology in `quick_retrain.py`.

---

## Known Issues

### 1. `quick_retrain.py` Uses Wrong Tier Bias Calculation

**File:** `ml/experiments/quick_retrain.py` line 337
**Bug:** Uses `actuals >= 25` to define stars (hindsight)
**Should be:** Use `points_avg_season` from features
**Impact:** Models flagged as "blocked" when they're actually fine

### 2. Isotonic Calibrator Network Timeout

The calibrator script hit a BigQuery network timeout. Not critical - model doesn't need calibration anyway.

---

## Recommendations for Next Session

### Priority 1: Implement Role Player UNDER Filters

Add volatility filters to avoid losing UNDER bets:
- Skip when player is HOT (L5 > season + 3)
- Skip when line < 14
- Require edge >= 4

**Expected impact:** Improve role UNDER from 47% to ~71%

### Priority 2: Fix `quick_retrain.py` Tier Eval

Update `compute_tier_bias()` to use season average from features, not actual points scored.

### Priority 3: Deploy New Model with Proper Naming

The trained model `V9_20251102_20260131` is ready. Consider:
- Deploying as new system_id
- Or adding `model_artifact_id` field for tracking

### Priority 4: Future - Breakout Prediction Model

The Opus agent designed a full breakout prediction system:
- Track `explosion_ratio`, `days_since_breakout`
- Train classifier for P(breakout)
- Integrate with main prediction system

---

## Key Metrics to Watch

| Metric | Current | Target |
|--------|---------|--------|
| OVER + High Edge hit rate | 81% | Maintain |
| UNDER + High Edge hit rate | 63% | Improve to 70%+ |
| Role UNDER hit rate | 47% | Improve to 70%+ with filters |

---

## Documentation Created

| Document | Purpose |
|----------|---------|
| `FINDINGS.md` | Session findings and learnings |
| `TIER-BIAS-METHODOLOGY.md` | Correct vs wrong bias measurement |
| `MODEL-TRAINING-PLAN.md` | Plan for new named models |

---

## Opus Agent Insights Summary

**3 agents analyzed the system:**

1. **Model Architecture Agent:** Tier bias is minimal (+0.1), no urgent model fixes needed
2. **Betting Strategy Agent:** Create OVER-only subsets, avoid UNDER on role players
3. **Volatility Analysis Agent:** Role player breakouts are predictable - filter by hot streak and line value

**Consensus:** Don't build new model for bias. Focus on filtering role player UNDER bets.

---

*Session 124 - Model Naming & Subset System Review*
