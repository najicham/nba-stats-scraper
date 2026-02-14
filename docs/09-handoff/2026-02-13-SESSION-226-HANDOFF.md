# Session 226 Handoff — Plan Review, SQL Diagnostics, Wave 1 Analysis

**Date:** 2026-02-12/13
**Session:** 226
**Status:** Review complete, Wave 1 analyzed, V10+Mono experiments queued

## What This Session Did

1. **Deep review of 4 planning docs** (Sessions 222-224) — found critical issues
2. **Ran 9 diagnostic SQL queries** via Chat 1 — CLV analysis, direction filter sims, decay profiling
3. **V10 code changes** via Chat 3 — `--feature-set v10` and `--monotone-constraints` committed
4. **Wave 1 training (5 experiments)** via Chat 2 — multi-season results analyzed
5. **Produced corrected execution plan** with fixed SQL column names and decision trees
6. **Wrote chat prompts** for next-phase experiments (V10 + Monotonic + Multi-Quantile)

## Critical Discoveries

### 1. CLV Confirms Real Edge (Chat 1 — MOST IMPORTANT)

| Month | Avg CLV | Positive CLV Rate | HR |
|-------|---------|------------------|----|
| **January 2026** | **+3.04 pts** | **67.3%** (206/306) | **68.0%** |
| **February 2026** | **-0.08 pts** | **8.8%** (10/114) | **38.6%** |

**VERDICT: PATH A — Staleness confirmed.** The model had genuine edge in January, completely lost it in February. The trade deadline (Feb 1-8) was the acute trigger (-22pp in one week). Post-processing filters cannot fix negative CLV — retraining is the only fix.

### 2. Direction Filter Insufficient (Chat 1)

Suppressing role player UNDER only improves champion from 38% → 41% (+3pp). Still 11pp below breakeven. **Filtering is deprioritized.**

### 3. Wave 1 Training Overlap Problem (Chat 2 + Our Analysis)

Chat 2 reported multi-season as a "dead end" (50% best HR). **This was wrong.** We discovered:

- Training ended Feb 7 but eval started Feb 2 → **5 days of overlap inflated Week 1 numbers**
- True clean holdout (Week 2 only):
  - 120d recency: **45.0%** (beats champion's 40% in same period)
  - 14d recency: **31.6%** (catastrophic — massively overfits then collapses)
- **120d recency is significantly better than 14d for multi-season** (reverses single-season finding)

### 4. Multi-Season Fixed Role Player UNDER (Hidden in Wave 1 Data)

| Segment | Champion | 2SZN_Q43_R120 | 2SZN_Q43_R14 |
|---------|----------|---------------|---------------|
| Role UNDER (5-14) | **22%** | **68.4%** | **61.1%** |
| Vegas dependency | 29-36% | 23% | 18% |

Multi-season training **fixed the #1 failure mode** and reduced Vegas dependency.

### 5. Schema Corrections (Pre-Flight Check)

All planning docs (01-04) used **wrong column names** for `prediction_accuracy`:

| Docs Used | Actual Column |
|-----------|--------------|
| `edge` | `ABS(predicted_margin)` — column doesn't exist |
| `predicted_direction` | `recommendation` |
| `vegas_line` | `line_value` |
| `is_correct` | `prediction_correct` |

Also: `PASS` and `HOLD` recommendations exist (427 PASS, 1 HOLD in Feb).

### 6. V10 Feature Count Clarified

`V10_CONTRACT` in `feature_contract.py` defines **37 features** (0-36), not 39. Docs 02/03 were correct. Doc 01 was wrong. New features should start at index 37.

## Code Changes

**Committed by Chat 3:**
- `684d8b9` — Added `--feature-set v10` and `--monotone-constraints` to `quick_retrain.py`
- V10 uses `V10_FEATURE_NAMES` (37 features) from `feature_contract.py`
- Monotonic constraints passed directly to CatBoost, with length validation

## Files Created/Modified

| File | What |
|------|------|
| `05-SESSION-225-REVIEW-AND-EXECUTION-PLAN.md` | Full review + execution plan with corrected SQL (in model-improvement-analysis/) |
| `06-SESSION-A-SQL-RESULTS.md` | 9 SQL query results from Chat 1 (in model-improvement-analysis/) |
| `SESSION-225-CHAT-PROMPTS.md` | Original 6 chat prompts (in 09-handoff/) |
| `SESSION-225-CHAT-PROMPTS-V2.md` | Updated Chat 7+8 prompts with corrected configs (in 09-handoff/) |
| `ml/experiments/quick_retrain.py` | --feature-set, --monotone-constraints (Chat 3, committed) |

## What's Queued for Next Session

### Chat 7: V10 + Monotonic Experiments (HIGHEST PRIORITY)

6 experiments testing V10 features and monotonic constraints:
- Group A (3): Single-season configs (apples-to-apples with 55.4% baseline)
- Group B (3): Multi-season configs (build on Wave 1 structural improvements)
- **All train through Jan 31, eval Feb 1-11 (no overlap)**
- Prompt at: `docs/09-handoff/2026-02-12-SESSION-225-CHAT-PROMPTS-V2.md` → Chat 7

### Chat 8: Multi-Quantile Ensemble (Can run in parallel)

Train Q30/Q43/Q57 models, analyze agreement-based filtering.
- Prompt at: same file → Chat 8

### Decision Gate After Chats 7+8

| Result | Action |
|--------|--------|
| Any model > 55% clean holdout, 30+ picks | Shadow deploy candidate |
| 52.4-55% | Combine with post-processing (direction filter on starters) |
| < 52.4% | Pivot to feature engineering (star_teammate_out, game_total_line) |

## Key Strategic Insights

1. **The model architecture works.** January CLV of +3.04 proves the approach is sound when fresh.
2. **Retrain cadence is the #1 operational issue.** 3-week decay → 5-week collapse. Retrain every 2 weeks during volatile periods.
3. **120d recency > 14d for multi-season.** 14d makes extra data useless then collapses on holdout.
4. **Multi-season fixes structural weaknesses** (role player UNDER, Vegas dependency) even if absolute HR isn't yet above breakeven.
5. **V10 features target remaining gaps:** pts_slope_10g for trend blindness, pts_vs_season_zscore for role changes.
6. **CLV should become a monitoring metric.** Leading indicator of decay — degrades before HR does.

## Dead Ends Confirmed This Session

| Approach | Evidence |
|----------|----------|
| 3rd season of training data | Identical results to 2-season (recency zeros it out) |
| 14d recency with multi-season | 31.6% clean holdout — overfits then collapses |
| Direction filter as primary fix | Only +3pp (38→41%), still 11pp below breakeven |
| Ensemble (champion OVER + Q43 UNDER) in Feb | Both failing independently |
| Dynamic edge threshold for stale model | Edge 6+ at 27.3% in Week 4 — inverted |

## Experiments Summary

| Wave | Experiment | E3+ Picks | E3+ HR | Clean Holdout HR | Status |
|------|-----------|-----------|--------|-----------------|--------|
| 1 | 2SZN_Q43_R120 | 44 | 50.0% | **45.0%** | Best structural |
| 1 | 3SZN_Q43_R120 | 44 | 50.0% | 45.0% | 3rd season = no impact |
| 1 | 2SZN_BASE_R120 | 5 | 40.0% | — | Quantile essential |
| 1 | 2SZN_Q43_R14 | 38 | 44.7% | **31.6%** | Overfits, collapses |
| 1 | FEB_FOCUS_Q43 | 38 | 44.7% | 31.6% | Same as 2szn |
| 2 | 6 V10+Mono experiments | — | — | — | QUEUED (Chat 7) |
| 2 | 3 Multi-Quantile experiments | — | — | — | QUEUED (Chat 8) |

## Quick Start for Next Session

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-02-13-SESSION-226-HANDOFF.md

# 2. Read V2 chat prompts — copy Chat 7 prompt into a new chat
cat docs/09-handoff/2026-02-12-SESSION-225-CHAT-PROMPTS-V2.md

# 3. Optionally start Chat 8 (Multi-Quantile) in parallel

# 4. After results: apply decision gate from this doc
```
