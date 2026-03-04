# Model Evaluation & Selection — How Top Picks Are Created

**Created:** 2026-03-03 (Session 393)
**Status:** Research complete, action plan ready for next session
**Goal:** Understand how the system selects "top picks," identify blind spots, and design a framework for comparing models on what actually matters — best bets pick quality.

## The Core Question

> How should we evaluate models? Overall hit rate doesn't tell the full story. A model with 55% overall HR might source 80% best bets picks. A model with 75% overall HR might source zero. What we care about is: **which models produce solid, high-percentage picks after the full filter stack is applied?**

## Documents

| File | Contents |
|------|----------|
| `01-CURRENT-PIPELINE.md` | How picks flow from raw predictions to best bets today |
| `02-FINDINGS.md` | Data analysis from Session 393 — what predicts winning picks |
| `03-BLIND-SPOTS.md` | 7 problems with the current approach |
| `04-OPEN-QUESTIONS.md` | 12 research questions + prioritized action items for next session |
| `05-SHADOW-MONITORING.md` | Design: tracking disabled model performance in shadow mode |
| `06-EXPERIMENT-INFRASTRUCTURE.md` | Assessment of training/eval tooling — strengths and gaps |

## Key Findings (Summary)

1. **Edge is the #1 predictor** of best bets success (7+: 81.3% HR, 5-7: 63.4%)
2. **Signal count is #2** (SC=4+: 76.1% HR vs SC=3: 55.1%)
3. **Confidence score is useless** — all picks have 9.999
4. **Only 6 of 16+ models have EVER sourced a best bets pick** since Dec 1
5. **V16 models (66.7% HR) never win selection** because their edges are lower (3.7-4.0 avg)
6. **The per-player selection favors high-edge models**, which penalizes well-calibrated models that predict closer to the actual line
7. **SC=3 picks (41% of volume) are barely profitable** at 55.1% HR — they drag down overall performance
