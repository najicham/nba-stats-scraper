# Pipeline Steering Audit — Session 388

**Date:** 2026-03-02
**Period analyzed:** Jan 1 - Mar 2, 2026
**Purpose:** Comprehensive review of how the prediction pipeline selects, filters, and steers model output into best bets picks.

## Executive Summary

The filter stack works well at the top — edge 7+ picks hit at 81.3%, ultra multi-criteria at 93.8%. The system's weakness is **volume into the top tiers**, not the quality of the tiers themselves. Three structural issues limit volume: legacy model domination, SC=3 mediocrity at moderate edge, and OVER collapse in Feb.

## Pipeline Funnel (14-Day Snapshot)

```
Raw Predictions    →  Signal Tagged  →  SC≥3  →  Best Bets
  608 - 3,585          21 - 145        0 - 15     0 - 6 picks/day
```

Typical conversion: **0.06% - 0.28%** of raw predictions become best bets. This is intentionally aggressive — quality over quantity.

### Daily Funnel (Feb 19 - Mar 2)

| Date | Raw Preds | Players | Tagged | SC≥3 | Best Bets |
|------|-----------|---------|--------|------|-----------|
| Feb 22 | 3,585 | 152 | 145 | 15 | 4 |
| Feb 24 | 3,129 | 144 | 139 | 3 | 2 |
| Feb 28 | 2,174 | 71 | 86 | 12 | 6 |
| Mar 1 | 2,081 | 134 | 21 | 3 | 2 |
| Mar 2 | 608 | 40 | 31 | 5 | 0 |

**Anomaly:** Mar 1 had 134 players but only 21 signal-tagged (vs 145 for similar-sized Feb 22). Likely caused by Session 387 signal fixes deployed mid-day — coordinator ran with partial signal evaluation.

## Filter Stack Effectiveness

### By Edge Band (Jan 1 - Mar 2)

| Edge Band | OVER HR (N) | UNDER HR (N) | Combined HR |
|-----------|-------------|--------------|-------------|
| **7+** | **77.8%** (27) | **100%** (5) | **81.3%** (32) |
| 5-7 | 67.5% (40) | 58.5% (41) | 63.0% (81) |
| 3-5 | 25.0% (4) | 100% (1) | 40.0% (5) |

Edge 7+ is elite. Edge 5-7 is solid. Edge 3-5 is effectively empty (only 5 picks ever made it through filters — the edge floor and signal count gate correctly block most).

### By Signal Count

| SC | Picks | HR | OVER (W/N) | UNDER (W/N) |
|----|-------|-----|-----------|-------------|
| 3 | 50 | **56.0%** | 5/11 (45%) | 23/39 (59%) |
| 4 | 25 | **76.0%** | 13/18 (72%) | 6/7 (86%) |
| 5 | 23 | 69.6% | 15/22 (68%) | 1/1 |
| 6 | 11 | **90.9%** | 10/11 (91%) | 0/0 |
| 7 | 6 | 83.3% | 5/6 | 0/0 |

**Key insight:** SC=3 is the weak link at 56%. SC 4+ is consistently 70%+. SC 6+ is 88% (16/18).

### Edge x Signal Count Matrix

| | SC=3 | SC=4 | SC=5 | SC=6+ |
|------|------|------|------|-------|
| **Edge 7+** | 85.7% (7) | 87.5% (8) | 69.2% (13) | 100% (4) |
| **Edge 5-7** | **51.3%** (39) | 70.6% (17) | 70.0% (10) | 90.0% (10) |

**The single worst pocket:** SC=3 at edge 5-7 = 51.3% on 39 picks. This is the largest bucket and barely breakeven. Everything else is profitable.

## Ultra Bets Analysis

| Criteria Count | HR | N | Assessment |
|---------------|-----|---|------------|
| 3 criteria (edge_6+ AND over_5+ AND edge_4.5+) | **93.8%** | 16 | Elite |
| 2 criteria (edge_6+ AND edge_4.5+) | **100%** | 6 | Elite |
| 1 criterion (edge_4.5+ only) | **33.3%** | 9 | **PROBLEM — worse than non-ultra** |
| Non-ultra | 62.7% | 83 | Solid baseline |

**Action needed:** The single-criterion ultra tier (edge_4.5+ only) is a trap at 33.3%. It dilutes ultra credibility. Should require 2+ criteria.

## Model Steering Analysis

### Model Selection Problem

The aggregator selects the highest-edge prediction per player across all models. On Mar 2:
- 31 candidates after aggregation
- 27 blocked by legacy_block (catboost_v9/v12)
- 3 blocked by blacklist
- 1 blocked by away_noveg
- **0 picks passed**

Legacy models (dead champions) generate inflated edges because their predictions are stale — systematically too far from the line. They "win" selection, then get blocked. This creates a massive funnel bottleneck.

### Model Family Performance in Best Bets (Feb+)

| Family | Picks | HR | Notes |
|--------|-------|-----|-------|
| Legacy (v9/v12) | 35 (60%) | 54.8% | Blocked but dominating selection |
| v12_noveg | 13 (22%) | 58.3% | Best active family |
| v9_low_vegas | 5 (9%) | 75.0% | Excellent but tiny N |
| v12_vegas | 2 (3%) | 100% | Tiny N |

### Raw Model Quality at Edge 5+ (Feb 15+)

| Model Type | OVER HR (N) | UNDER HR (N) |
|------------|-------------|--------------|
| noveg | **64.6%** (65) | 52.9% (257) |
| vegas | 48.7% (195) | 52.3% (428) |
| legacy | 57.1% (21) | 52.7% (110) |

**Noveg OVER is the only pocket with real alpha at raw prediction level.** All UNDER models are ~52-53% at edge 5+.

### Shadow Model Edge 5+ HR (Feb 15+, N≥3)

| Model | Direction | HR | N |
|-------|-----------|-----|---|
| v9_low_vegas_train0106_0205 | UNDER | 64.7% | 17 |
| v12_noveg_q43_train1102_0125 | UNDER | 80.0% | 5 |
| v12_noveg_q45_train1102_0125 | UNDER | 62.5% | 8 |

Shadow models are almost entirely UNDER-focused at edge 5+. No shadow model is producing significant OVER picks at high edge — that space is still held by legacy models.

## Direction Analysis

### Monthly Trajectory

| Month | OVER HR | OVER N | UNDER HR | UNDER N | Total HR |
|-------|---------|--------|----------|---------|----------|
| **Jan** | **80.0%** | 40 | 63.0% | 27 | 73.1% |
| **Feb** | 53.3% | 30 | **63.2%** | 19 | 57.1% |

OVER collapsed from 80% → 53% (Jan → Feb). UNDER stayed rock-solid at 63%. The **entire February decline is an OVER problem.**

### Root Causes of OVER Collapse (Session 370 Analysis)
- `usage_spike_score` explains 47% of Dec-Jan → Feb drift (collapsed 1.14 → 0.28)
- Seasonal pattern as rotations stabilize post-All-Star
- Two OVER-targeting signals were dead (line_rising_over, fast_pace_over) — fixed Session 387

## Actionable Recommendations

### 1. SC=3 at Edge 5-7 Tightening (High Impact, Low Risk)
**Problem:** 51.3% HR on 39 picks — biggest bucket, barely breakeven.
**Option A:** Raise SC floor to 4 for edge 5-7 (70.6% HR). Keep SC=3 for edge 7+ (85.7%).
**Option B:** Add an additional filter for SC=3 picks (e.g., require specific "strong" signals).
**Trade-off:** Reduces volume by ~39 picks/period but eliminates the worst-performing tier.

### 2. Ultra Single-Criterion Fix (Quick Win)
**Problem:** edge_4.5+-only ultra picks = 33.3% HR.
**Fix:** Require 2+ ultra criteria. Simple code change in `ml/signals/ultra_bets.py`.

### 3. Retrain with Fresh Data (Addresses Model Staleness)
**Target config:** 56-day window + vw015 (73.9% backtest, cross-season validated).
**Training end:** Feb 27+ data (most recent available).
**Priority:** noveg models, which have the strongest OVER signal.

### 4. Monitor Revived Signals (Wait & Observe)
`line_rising_over` and `fast_pace_over` both confirmed firing on Mar 2. Need 1-2 weeks of data to assess OVER HR impact.

### 5. Legacy Model Selection Investigation (Research)
Why do dead champions consistently produce higher edges? Understanding this could unlock better selection algorithms. Hypothesis: stale models have higher variance in predictions → more extreme edges, but those edges aren't accurate.

## How We Manage Models — Current Process

### Model Lifecycle
1. **Train** via `quick_retrain.py` or `/model-experiment` skill
2. **Gates:** 6 governance gates (duplicates, vegas bias, edge 3+ HR ≥ 60%, sample size ≥ 50, tier bias, MAE)
3. **Upload** to GCS, register in `model_registry`
4. **Shadow** for 2+ days — predictions accumulate alongside production
5. **Promote** to champion (requires explicit user approval)

### Fleet Monitoring
- `model_performance_daily` — rolling 7d/14d HR per model, auto-populated
- `decay-detection` CF — daily 11 AM ET state machine (HEALTHY → WATCH → DEGRADING → BLOCKED)
- `signal_health_daily` — signal regime tracking (HOT/NORMAL/COLD)
- Signal firing canary — detects dead signals (Session 387)
- 7 cross-model monitoring layers (see CLAUDE.md)

### Model Selection in Best Bets
- Per-player: highest edge prediction wins (across all enabled models)
- Model HR-weighted: `effective_edge = edge * min(1.0, hr_14d / 55.0)` (Session 365)
- Models with <10 graded picks default to 50% HR (weight 0.91)
- Legacy models (catboost_v9, catboost_v12) are fully blocked

### Known Gaps
- **BLOCKED models not auto-disabled** — requires manual `deactivate_model.py`
- **Signal firing not monitored** — canary deployed Session 387 but not yet validated in production
- **7-day retrain cadence not enforced** — models regularly run 10-20 days stale
- **No champion model** — all 13 enabled models are shadows since Session 332

---
*Session 388 pipeline audit. Data queries saved in conversation history.*
