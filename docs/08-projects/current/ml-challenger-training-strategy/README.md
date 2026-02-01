# ML Challenger Training Strategy

**Status:** Active
**Started:** 2026-01-31 (Session 60)
**Goal:** Define training data strategy for V9+ challenger models

---

## Overview

This project tracks the investigation and decisions around ML model training data, specifically:
- What data sources to use for training (DraftKings vs Consensus vs multi-book)
- How to handle bookmaker-specific calibration
- Historical data availability and gaps

---

## Key Findings

### V8 Training Data (Session 60)

V8 was trained on **BettingPros Consensus** lines, NOT DraftKings.

**Implications:**
- Users bet on DraftKings, but model was calibrated to Consensus
- Consensus is an aggregate - may not match DraftKings exactly
- V9+ should consider training on DraftKings-specific lines

**Full Analysis:** [V8-TRAINING-DATA-ANALYSIS.md](./V8-TRAINING-DATA-ANALYSIS.md)

---

## Data Availability

| Source | Bookmaker | Records | Date Range |
|--------|-----------|---------|------------|
| BettingPros | Consensus | 98,512 | Nov 2021 - Jun 2024 |
| BettingPros | DraftKings | 104,196 | May 2022 - Jun 2024 |
| Odds API | DraftKings | 30,296 | May 2023 - Jun 2024 |

**BettingPros DraftKings has 3x more data** than Odds API DraftKings.

---

## V9 Training Options

### Option A: Train on BettingPros DraftKings
- **Pros:** Large dataset, DraftKings-specific calibration
- **Cons:** May miss edge cases covered by Consensus

### Option B: Train on Consensus, grade on DraftKings
- **Pros:** Maximum training data
- **Cons:** Calibration mismatch continues

### Option C: Multi-book training with book indicator feature
- **Pros:** Model learns book-specific patterns
- **Cons:** More complex, needs more data

---

## Action Items

- [ ] Run Consensus vs DraftKings line comparison query
- [ ] Analyze hit rates by bookmaker (using new `line_bookmaker` field)
- [ ] Decide on V9 training strategy
- [ ] Add `training_bookmaker` field to model metadata
- [ ] Consider A/B test: V8 (Consensus) vs V9 (DraftKings)

---

## Related Documents

- [V8 Training Data Analysis](./V8-TRAINING-DATA-ANALYSIS.md)
- [Model Comparison V8 vs Monthly Retrain](../../05-development/model-comparison-v8-vs-monthly-retrain.md)
- [Odds Data Cascade Investigation](../odds-data-cascade-investigation/README.md)
- [CatBoost V9 Experiments](../catboost-v9-experiments/)

---

## Session History

| Session | Date | Work Done |
|---------|------|-----------|
| 60 | 2026-01-31 | V8 training data investigation, DraftKings cascade implementation |

---

*Created: 2026-01-31*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
