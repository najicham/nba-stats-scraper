# ML Challenger Training Strategy

**Status:** Active - CRITICAL FINDINGS
**Started:** 2026-01-31 (Session 60)
**Updated:** 2026-02-01 (Session 62) - Major distribution mismatch discovered
**Goal:** Define training data strategy for V9+ challenger models

---

## Overview

This project tracks the investigation and decisions around ML model training data, specifically:
- What data sources to use for training (DraftKings vs Consensus vs multi-book)
- How to handle bookmaker-specific calibration
- Historical data availability and gaps
- **NEW:** Training/inference distribution mismatches causing V8 degradation

---

## Critical Finding: V8 Degradation Root Cause (Session 62)

V8 hit rate collapsed from **72.8%** (Jan 2025) to **55.5%** (Jan 2026).

### Root Causes Identified

| Issue | Severity | Description |
|-------|----------|-------------|
| **team_win_pct bug** | MAJOR | V8 trained on constant 0.5, but Jan 2026 has realistic 0.2-0.9 values |
| **Vegas line coverage** | MEDIUM | 99% → 43% (backfill includes all players, not just props) |
| **Vegas imputation** | MEDIUM | Training uses season_avg, inference uses np.nan |

### Key Insight

**V8 was trained on broken data** where `team_win_pct = 0.5` for ALL records. When this bug was fixed (Nov 2025+), the model started seeing feature values it was never trained on, causing the collapse.

**Full Analysis:** [V8-TRAINING-DISTRIBUTION-MISMATCH.md](./V8-TRAINING-DISTRIBUTION-MISMATCH.md)

---

## Key Findings

### V8 Training Data (Session 60)

V8 was trained on **BettingPros Consensus** lines, NOT DraftKings.

**Implications:**
- Users bet on DraftKings, but model was calibrated to Consensus
- Consensus is an aggregate - may not match DraftKings exactly
- V9+ should consider training on DraftKings-specific lines

**Full Analysis:** [V8-TRAINING-DATA-ANALYSIS.md](./V8-TRAINING-DATA-ANALYSIS.md)

### V8 Training Distribution Issues (Session 62)

V8 was trained on data with several quality issues:

| Feature | Training Value | Correct Value |
|---------|----------------|---------------|
| team_win_pct | Always 0.5 | 0.2-0.9 |
| Vegas coverage | 99% | ~50% typical |
| Records/day | ~150 (props-only) | ~300 (all players) |

**Full Analysis:** [V8-TRAINING-DISTRIBUTION-MISMATCH.md](./V8-TRAINING-DISTRIBUTION-MISMATCH.md)

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

### Option A: Train on Recent Data Only (Nov 2025+) - RECOMMENDED
- **Pros:** Uses fixed team_win_pct, fixed has_vegas_flag, realistic distributions
- **Cons:** Less training data (~40K records vs 77K)
- **Why recommended:** Avoids all distribution mismatch issues

### Option B: Train on BettingPros DraftKings (Historical)
- **Pros:** Large dataset, DraftKings-specific calibration
- **Cons:** Has broken team_win_pct (always 0.5), may not match inference distribution

### Option C: Train on Consensus, grade on DraftKings
- **Pros:** Maximum training data
- **Cons:** Calibration mismatch continues, broken features

### Option D: Fix Historical Data + Train
- **Pros:** Maximum data with correct features
- **Cons:** Requires significant reprocessing, complex

---

## Action Items

### Immediate (Session 62+)
- [x] Identify root cause of V8 degradation
- [x] Document training distribution mismatches
- [ ] Re-run feature store backfill with vegas fix
- [ ] Verify team_win_pct is realistic in training data

### Before Training
- [ ] Decide: Recent data only vs fix historical
- [ ] Verify vegas_line coverage after backfill
- [ ] Create training data validation checklist

### Experiment Prep
- [ ] Run Consensus vs DraftKings line comparison query
- [ ] Analyze hit rates by bookmaker (using new `line_bookmaker` field)
- [ ] Add `training_bookmaker` field to model metadata
- [ ] Consider A/B test: V8 (Consensus) vs V9 (DraftKings)

---

## Related Documents

- [Experiment Plan](./EXPERIMENT-PLAN.md) - **NEW** Specific experiments to run with commands
- [Experiment Variables](./EXPERIMENT-VARIABLES.md) - All configurable training variables
- [V8 Training Distribution Mismatch](./V8-TRAINING-DISTRIBUTION-MISMATCH.md) - Critical root cause analysis
- [V8 Training Data Analysis](./V8-TRAINING-DATA-ANALYSIS.md) - Bookmaker analysis
- [Data Gaps 2025-26 Season](./DATA-GAPS-2025-26-SEASON.md) - Data availability
- [Vegas Line Root Cause](../feature-quality-monitoring/2026-02-01-VEGAS-LINE-ROOT-CAUSE-ANALYSIS.md)
- [ML Challenger Experiments](../ml-challenger-experiments/EXPERIMENT-PLAN.md)
- [Odds Data Cascade Investigation](../odds-data-cascade-investigation/README.md)

---

## Session History

| Session | Date | Work Done |
|---------|------|-----------|
| 60 | 2026-01-31 | V8 training data investigation, DraftKings cascade implementation |
| 62 | 2026-02-01 | **MAJOR:** Discovered team_win_pct bug, vegas coverage drop, training/inference mismatch |
| 68 | 2026-02-01 | Added experiment variables doc, fixed line source in quick_retrain.py |

---

*Created: 2026-01-31*
*Updated: 2026-02-01 Session 62*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
