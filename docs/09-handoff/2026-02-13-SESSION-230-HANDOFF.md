# Session 230 Handoff — Phase 2 Edge Classifier (Negative Result)

**Date:** 2026-02-13
**Focus:** Phase 2 of V2 Architecture — Edge Classifier (Model 2)

## What Was Done

Built and evaluated an Edge Classifier (Model 2) to filter Model 1's edge predictions:
- Created `ml/experiments/edge_classifier.py` — full experiment script
- Tested LogisticRegression and CatBoost Classifier on 10 features
- Evaluated on Jan 2026 (strong period) and Feb 2026 (harder period)
- Used 5-fold temporal cross-validation for honest OOF training predictions

## Key Finding: Model 2 Does NOT Add Value

| Window | Model 1 HR 3+ | LR AUC | CB AUC | Best Combined | Delta |
|--------|---------------|--------|--------|---------------|-------|
| Jan 2026 | **78.7%** (169) | 0.456 | 0.453 | 75.3% (97) | **-3.4pp** |
| Feb 2026 | **60.0%** (35) | 0.486 | 0.487 | 68.2% (22) | +8.2pp* |

*Feb 2026 improvement is noise (AUC < 0.50, n=22).

**Both classifiers scored below random (AUC < 0.50).** The 10 pre-game features cannot discriminate winning edges from losing ones. Edge outcomes are dominated by game-specific noise.

## Critical Methodology Lesson

**In-sample predictions leak information.** Initial approach used Model 1's predictions on its own training data (88% hit rate) to train Model 2. This produced a misleading LR AUC of 0.5658. Fixed with 5-fold temporal OOF predictions (58% hit rate, matching real-world).

**Rule: Always use OOF predictions when training a model on another model's outputs.**

## Segmented Analysis (Still Valuable)

From Model 1 alone (Jan 2026, edge >= 3):
- **OVER: 84.1%** vs UNDER: 69.4% — OVER consistently outperforms
- **Edge [3-5): 71%** → [5-7): 89% → [7+): 91% — Edge size is the best predictor
- **Starters OVER: 87.8%** is the single best segment

## Recommendation for Next Session

1. **Skip Model 2 development** — use Model 1 with edge thresholds
2. **Consider simple rule-based filters** (OVER-preferred, higher edge floor)
3. **Focus on Model 1 freshness** — monthly retrain is the highest ROI activity
4. **Evaluate production deployment** of V12 Model 1 (Phase 1B results hold)

## Files Changed

| File | Change |
|------|--------|
| `ml/experiments/edge_classifier.py` | NEW — Edge classifier experiment script |
| `docs/08-projects/current/model-improvement-analysis/23-PHASE2-EDGE-CLASSIFIER-RESULTS.md` | NEW — Full results doc |

## V12 Deployment Plan (for next session)

Full deployment plan written to `docs/09-handoff/2026-02-13-SESSION-230-START-PROMPT.md`.

**Approach:** Augment V12 features at prediction time in the worker (same pattern as existing Vegas/opponent enrichment). No feature store schema changes needed initially.

**Steps:**
1. Create `CatBoostV12` prediction system class (50-feature vector, no-vegas)
2. Update feature contract with V12_NOVEG_CONTRACT
3. Wire into worker routing (shadow mode)
4. Upload model to GCS + set env var
5. Shadow test 5+ game days
6. Create V12-specific subset definitions (OVER-preferred, premium edge)
7. Promote to production

**Multi-book coverage note:** User reports we should have multiple books from BettingPros AND Odds API. Currently only 2 bookmakers in odds_api Oct-Jan (5 in Feb). Check BettingPros coverage too — multi_book_line_std feature (index 50) could become useful with better coverage.

## Files Changed

| File | Change |
|------|--------|
| `ml/experiments/edge_classifier.py` | NEW — Edge classifier experiment script |
| `docs/08-projects/current/model-improvement-analysis/23-PHASE2-EDGE-CLASSIFIER-RESULTS.md` | NEW — Full results doc |
| `CLAUDE.md` | Updated with Session 230 lessons (OOF, Edge Classifier dead end, V12 info) |

## Status

- [x] Phase 2 Edge Classifier: Built, tested, negative result documented
- [x] CLAUDE.md updated with lessons learned
- [x] V12 deployment plan written (start prompt for next session)
- [ ] V12 Model 1 production deployment: Planned, not started
- [ ] V12 subset definitions (OVER-preferred, premium edge): After shadow
- [ ] Multi-book line std investigation: Check BettingPros coverage
