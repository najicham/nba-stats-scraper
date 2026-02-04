# Session 111 Handoff - 2026-02-03

## Session Summary

**Major investigation into model bias and hit rate optimization.** Discovered that the perceived "regression-to-mean" problem is actually about **betting scenarios**, not model architecture. Identified optimal filtering strategies that can achieve **87%+ hit rates**.

## Key Accomplishments

### 1. Created Canonical Feature Contract
- `shared/ml/feature_contract.py` - Single source of truth for feature definitions
- Training now uses name-based extraction (not position-based slicing)
- `shared/ml/validate_feature_alignment.py` - Validation script
- **Why it matters:** Prevents silent feature misalignment between training and prediction

### 2. Full Feature Store Audit
- Only **15 bad records** in entire season (not thousands as feared)
- Added filter to `ml/experiments/quick_retrain.py` to exclude bad defaults
- Updated `/spot-check-features` skill with full season audit query

### 3. Deep Investigation into Model Bias (5 Parallel Agents)
- **Training data:** 57% low scorers, mean = 10.7 pts
- **Star bias:** -9 pts (under-predicts stars)
- **Critical finding:** This bias does NOT hurt hit rate in optimal scenarios!

### 4. Discovered Optimal Betting Scenarios

| Scenario | Hit Rate | ROI | Volume |
|----------|----------|-----|--------|
| **OVER + Line <12 + Edge ≥5** | **87.3%** | +66.8% | 1-2/day |
| OVER + Any Line + Edge ≥7 | **90.0%** | +80%+ | 1/day |
| UNDER + Line ≥25 + Edge ≥3 | **65.9%** | +25.8% | 1-2/day |

### 5. Identified Anti-Patterns

| Avoid | Why | Hit Rate |
|-------|-----|----------|
| UNDER on lines <20 | Breakout risk | 0-52% |
| Any pick with edge <3 | No signal | 51% |
| OVER on high lines (25+) | Priced correctly | 48% |
| UNDER on: Luka, Maxey, Sharpe, Harden, Randle | High variance | 20-45% |

### 6. Bias Fix Experiments
- Created `ml/experiments/bias_fix_experiments.py`
- Tested: sample weighting, quantile regression, residual modeling, calibration
- **Winner:** Quantile 0.53 gives +1.4% hit rate improvement

## Critical Insight

**The star under-prediction bias (-9 pts) is NOT the problem.**

The model's conservative predictions help find value on OVER bets for low-line players:
- When we bet OVER on low lines for 25+ scorers: **100% hit rate**
- When we bet UNDER on high lines (25+): **65-72% hit rate**

**The problem is:** Betting UNDER on players who might explode (breakout games).

**The solution is:** Scenario-based filtering, not fixing the model bias.

## Files Created/Modified

| File | Change |
|------|--------|
| `shared/ml/feature_contract.py` | NEW - Canonical feature definitions |
| `shared/ml/validate_feature_alignment.py` | NEW - Validation script |
| `shared/ml/__init__.py` | NEW - Package init |
| `ml/experiments/quick_retrain.py` | Name-based extraction, bad record filter |
| `ml/experiments/bias_fix_experiments.py` | NEW - Test different bias fixes |
| `.claude/skills/spot-check-features/SKILL.md` | Added full season audit |
| `docs/08-projects/current/regression-to-mean-fix/` | Investigation docs (6 files) |

## Commits

| Commit | Description |
|--------|-------------|
| 3d45395c | feat: Add canonical feature contract and regression-to-mean fix planning |
| 0554004c | feat: Add bad record filter and full season audit capability |

## Next Session: Implementation Plan

### Phase 1: Implement Optimal Scenario Filters (P0)

1. **Create subset definitions** in Phase 6:
   ```python
   OPTIMAL_OVER = {
       'recommendation': 'OVER',
       'line_max': 12,
       'edge_min': 5
   }
   OPTIMAL_UNDER = {
       'recommendation': 'UNDER',
       'line_min': 25,
       'edge_min': 3
   }
   ULTRA_HIGH_EDGE = {
       'edge_min': 7
   }
   ```

2. **Update daily signal** to show optimal vs non-optimal breakdown

3. **Add player blacklist** for UNDER bets (5 high-variance players)

### Phase 2: Model Improvement (P1)

4. **Deploy Quantile 0.53** as V9.1 variant for A/B testing

### Phase 3: Infrastructure (P2)

5. **Add scenario flags** to prediction output
6. **Create alerts** for high-risk days (many low-line UNDERs)

## Verification Commands

```bash
# Check deployments
./bin/check-deployment-drift.sh --verbose

# Validate feature contract
PYTHONPATH=. python -m shared.ml.feature_contract --validate

# Run bias fix experiments (dry run)
PYTHONPATH=. python ml/experiments/bias_fix_experiments.py --approach all --dry-run

# Check today's picks by scenario
bq query --use_legacy_sql=false "
SELECT
  CASE
    WHEN recommendation = 'OVER' AND current_points_line < 12
         AND ABS(predicted_points - current_points_line) >= 5 THEN 'OPTIMAL_OVER'
    WHEN recommendation = 'UNDER' AND current_points_line >= 25
         AND ABS(predicted_points - current_points_line) >= 3 THEN 'OPTIMAL_UNDER'
    WHEN ABS(predicted_points - current_points_line) >= 7 THEN 'ULTRA_HIGH_EDGE'
    ELSE 'STANDARD'
  END as scenario,
  COUNT(*) as picks
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE
GROUP BY 1"
```

## Key Documents

| Document | Location |
|----------|----------|
| Investigation Findings | `docs/08-projects/current/regression-to-mean-fix/INVESTIGATION-FINDINGS.md` |
| Feature Contract Architecture | `docs/08-projects/current/regression-to-mean-fix/FEATURE-CONTRACT-ARCHITECTURE.md` |
| Option A: Calibration | `docs/08-projects/current/regression-to-mean-fix/OPTION-A-TIER-CALIBRATION.md` |
| Option B: Clean Retrain | `docs/08-projects/current/regression-to-mean-fix/OPTION-B-RETRAIN-CLEAN.md` |
| Option C: V10 with Tiers | `docs/08-projects/current/regression-to-mean-fix/OPTION-C-V10-TIER-MODEL.md` |

## Deployment Status

All services up to date as of session start. No deployment drift detected.

---

**End of Session 111** - 2026-02-03 ~5:30 PM PT
