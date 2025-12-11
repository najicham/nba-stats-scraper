# Phase 5C: ML Feedback Loop

**Status:** Ready to Implement (Phase 6.1 Complete)
**Created:** 2025-12-10
**Updated:** 2025-12-10

## What is this?

Phase 5C creates feedback tables that help ML prediction systems learn from their mistakes. This data flows BACK into Phase 5A to improve future predictions.

## Key Finding

Our bias investigation revealed we severely under-predict high scorers:
- 30+ point scorers: predicted 21.2, actual 33.8 (**-12.6 bias!**)
- Bench players: predicted 5.7, actual 4.1 (+1.6 bias)

## Proposed Tables

| Table | Purpose | Priority |
|-------|---------|----------|
| `scoring_tier_adjustments` | Fix -12.6 star bias | **HIGH - START HERE** |
| `player_prediction_bias` | Per-player corrections | HIGH |
| `confidence_calibration` | Recalibrate confidence scores | MEDIUM |
| `system_agreement_patterns` | Agreement → confidence | MEDIUM |
| `context_error_correlations` | Context-aware adjustments | LOW |

## Documents

- **DESIGN.md** - Full design specification with schemas and integration code
- **STATUS-AND-RECOMMENDATIONS.md** - Current status and handoff instructions

## Current Status

| Dependency | Status |
|------------|--------|
| Phase 5B (Grading) | ✅ Complete - 47,355 predictions graded |
| Phase 6.1 (Publishing) | ✅ Complete - JSON exports to GCS |
| Phase 5C (ML Feedback) | ⏳ Ready to implement |

## Next Steps for Phase 5C Chat

1. **Read** `STATUS-AND-RECOMMENDATIONS.md` for full handoff
2. **Implement** `scoring_tier_adjustments` table and processor
3. **Integrate** with Phase 5A prediction pipeline
4. **Validate** bias reduction (target: -12.6 → < -3.0)
