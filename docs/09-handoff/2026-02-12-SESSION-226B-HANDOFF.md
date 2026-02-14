# Session 226B Handoff — V2 Model Architecture Plan

**Date:** 2026-02-12
**Focus:** Multi-season training experiments, February decay investigation, V2 architecture planning
**Next Session:** Implement V2 model architecture (diagnostics + Vegas-free model)

---

## What Was Done This Session

### 1. Fixed Critical Date Parameter Bug
**File:** `ml/experiments/quick_retrain.py` — `get_dates()` at line 254

The `--train-start`/`--train-end` parameters were **silently ignored** unless `--eval-start`/`--eval-end` were also provided. Every previous "multi-season" experiment actually trained on 60-day windows. Fixed by adding an intermediate case that auto-calculates eval dates when only train dates are given. Added warning when partial dates fall through to auto-calculation.

**Status:** Fixed, not yet committed.

### 2. Ran Data Quality Validation (Phase 1)
- 2,000-3,000 trainable rows/month across 3 seasons
- Hidden default contamination < 1.5% (negligible)
- Data quality is NOT the bottleneck for multi-season training

### 3. Ran 9 Experiments Across 4 Phases

**Phase 2: Multi-Season Training (5 experiments, eval Feb 1-11 2026)**

| Exp | Config | Edge 3+ HR | N | OVER HR | UNDER HR | MAE | Gates |
|-----|--------|-----------|---|---------|----------|-----|-------|
| 2E | 1-szn Q43 | **56.8%** | 74 | 0% (1) | 57.5% (73) | 5.12 | FAIL |
| 2C | 2-szn Q43 R120 | 53.3% | 60 | 0% (1) | 54.2% (59) | 5.11 | FAIL |
| 2D | 2-szn Base | 51.9% | 54 | 45.2% (31) | 60.9% (23) | **5.02** | FAIL |
| 2B | 3-szn Q43 | 50.0% | 170 | 47.8% (23) | 50.3% (147) | 5.32 | FAIL |
| 2A | 2-szn Q43 | 49.5% | 91 | 33.3% (3) | 50.0% (88) | 5.12 | FAIL |

**Phase 3: Cross-Season Backtesting (2 experiments)**

| Exp | Config | Edge 3+ HR | N | Gates |
|-----|--------|-----------|---|-------|
| 3A | Train→Jan'25, Eval **Feb 2025** (DK lines) | **79.5%** | **415** | **ALL PASS** |
| 3B | Train→Jan'26, Eval **Feb 2026** | 53.8% | 132 | FAIL |

**Phase 4: Micro-Retrains (2 experiments, eval Feb 8-12 2026)**

| Exp | Config | Edge 3+ HR | N | Gates |
|-----|--------|-----------|---|-------|
| 4A | 14-day micro Q43 | 50.0% | 24 | FAIL |
| 4B | Hybrid 14d+2szn | 50.0% | 16 | FAIL |

### 4. Key Findings

1. **Model architecture is valid** — 79.5% on Feb 2025 proves CatBoost Q43 works
2. **February 2026 is uniquely hostile** — every config fails (0 out of 8 pass gates)
3. **More training data makes it WORSE** — 1-szn (56.8%) > 2-szn (49.5%) > 3-szn (50.0%)
4. **Universal OVER collapse** — consistent across all configurations
5. **Micro-retraining doesn't help** — even freshest data gets 50%
6. **Vegas dependency is the root cause** — `vegas_points_line` at 15-30% importance, Q43 creates structural UNDER bias

### 5. Expert Reviews (3 Independent Opus Web Chats)

Sent comprehensive briefing to 3 independent Opus conversations. All converged on:

- **#1 Priority: Build Vegas-free points predictor** (unanimous)
- **Kill quantile regression** (unanimous) — source of OVER collapse
- **Run diagnostics before building** — understand Feb 2026 before changing anything
- **Two-model architecture:** Model 1 (points, no Vegas) + Model 2 (edge classifier, uses Vegas)
- **New features:** streak indicators, teammate usage vacuum, game total + spread, structural break detection
- **Drop 5 dead features:** injury_risk, back_to_back, playoff_game, rest_advantage, has_vegas_line

---

## What to Do Next Session

### START HERE: Read the Master Plan

**`docs/08-projects/current/model-improvement-analysis/16-MASTER-IMPLEMENTATION-PLAN.md`**

This synthesizes all 3 expert reviews into a concrete execution plan.

### Execution Order

1. **Phase 0: Run 5 diagnostic queries** (~1 hour)
   - Vegas sharpness comparison (Feb 2025 vs Feb 2026)
   - Trade deadline miss clustering
   - OVER/UNDER asymmetry deep dive
   - Miss clustering by player tier/context
   - Feature drift detection
   - **See:** Chat 1 Section 1.1-1.5, Chat 3 Part 1 for exact queries

2. **Phase 1A: Quick Vegas-free baseline** (~30 min)
   - Train existing CatBoost with features 25-28 removed, MAE loss, no quantile
   - Eval on Feb 2025 AND Feb 2026
   - Validates approach before feature engineering

3. **Phase 1B-D: New features + Model 1** (~1-2 days)
   - Add P0 features first (game_total_line, days_since_last_game, minutes_load_7d)
   - Then P1 (scoring_trend_slope, teammate_usage_available)
   - Then P2 (games_since_structural_change, opp_pts_allowed_to_position)
   - Train and evaluate after each batch

4. **Phase 2: Edge Finder (Model 2)** (~1 day)
   - Binary classifier on Model 1's edges
   - Logistic regression first, then CatBoost if needed

5. **Phase 3: Integration + Backtest** (~1 day)
   - Full pipeline across multiple eval periods

---

## Important Context

### Modified Files (Not Committed)
- `ml/experiments/quick_retrain.py` — `get_dates()` bug fix (lines 254-285)

### Staged Changes (from previous session)
- `data_processors/precompute/ml_feature_store/feature_extractor.py`
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- `data_processors/precompute/ml_feature_store/quality_scorer.py`
- `data_processors/publishing/tonight_player_exporter.py`
- `shared/ml/feature_contract.py`

### New Untracked Files
- `docs/08-projects/current/model-improvement-analysis/11-SESSION-226B-FEATURE-RETHINK.md`
- `docs/08-projects/current/model-improvement-analysis/12-WEB-CHAT-BRIEFING.md`
- `docs/08-projects/current/model-improvement-analysis/13-OPUS-CHAT-1-ANALYSIS.md`
- `docs/08-projects/current/model-improvement-analysis/14-OPUS-CHAT-2-ARCHITECTURE.md`
- `docs/08-projects/current/model-improvement-analysis/15-OPUS-CHAT-3-STRATEGY.md`
- `docs/08-projects/current/model-improvement-analysis/16-MASTER-IMPLEMENTATION-PLAN.md`
- `docs/09-handoff/2026-02-12-SESSION-226B-HANDOFF.md`

### Model Files Generated (local only, not deployed)
9 experiment models saved in `models/` directory — none deployed, all for analysis only.

### Key Dead Ends (Do NOT Revisit)
- Monotonic constraints, V10/V11 features as-is, multi-quantile ensemble
- Alpha fine-tuning, residual mode, two-stage sequential pipeline
- More training seasons (without Vegas removal), neural networks
- Micro-retraining alone

### Quick Reference for New Session
```bash
# Read this session's work
cat docs/08-projects/current/model-improvement-analysis/16-MASTER-IMPLEMENTATION-PLAN.md

# Read expert reviews
ls docs/08-projects/current/model-improvement-analysis/1[3-5]*.md

# Run diagnostics (Phase 0) — see queries in Chat 1 (doc 13) and Chat 3 (doc 15)
# Then start Vegas-free model experiment (Phase 1A)
```
