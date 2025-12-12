# Phase 5C: ML Feedback Loop

**Status:** Scoring Tier Adjustments Implemented & Validated
**Created:** 2025-12-10
**Updated:** 2025-12-11 (Session 124)

## What is this?

Phase 5C creates feedback tables that help ML prediction systems learn from their mistakes. This data flows BACK into Phase 5A to improve future predictions.

## Key Finding

Our bias investigation revealed systematic prediction errors by scoring tier:
- BENCH (0-9 avg): -1.6 bias (under-predict by 1.6 points)
- ROTATION (10-19 avg): -1.3 bias
- STARTER (20-29 avg): -2.1 bias

## Tables

| Table | Purpose | Status |
|-------|---------|--------|
| `scoring_tier_adjustments` | Tier-based bias corrections | **IMPLEMENTED** |
| `player_prediction_bias` | Per-player corrections | Planned |
| `confidence_calibration` | Recalibrate confidence scores | Planned |
| `system_agreement_patterns` | Agreement → confidence | Planned |
| `context_error_correlations` | Context-aware adjustments | Planned |

## Documents

- **DESIGN.md** - Full design specification with schemas and integration code
- **STATUS-AND-RECOMMENDATIONS.md** - Current status and handoff instructions
- **TIER-ADJUSTMENT-IMPLEMENTATION.md** - Implementation details, bug fix, and lessons learned
- **EVALUATION-AND-ITERATION.md** - How to evaluate performance and make improvements

## Current Status

| Component | Status |
|-----------|--------|
| Phase 5B (Grading) | ✅ Complete - 24,931 predictions graded |
| Phase 6.1 (Publishing) | ✅ Complete - JSON exports to GCS |
| Scoring Tier Processor | ✅ Implemented and validated |
| Tier Adjustments | ✅ Improving MAE by 0.055 points |

## Validation Results (Session 124)

```
MAE without adjustments: 4.724
MAE with adjustments:    4.669
Improvement:             -0.055 (adjustments help!)
```

## Important: Session 124 Bug Fix

A critical bug was found and fixed where adjustments were computed using `actual_points` but applied using `season_avg`. This mismatch caused adjustments to make predictions WORSE.

**Read `TIER-ADJUSTMENT-IMPLEMENTATION.md` for full details and lessons learned.**

## Next Steps

1. **Monitor** tier adjustment effectiveness in production
2. **Implement** `player_prediction_bias` for per-player corrections
3. **Consider** context-aware adjustments (home/away, back-to-back)
