# Session 311 — P0 Quality Fix, Signal Subsets, Filter Validation, Decay-Gated Promotion

**Date:** 2026-02-20
**Focus:** Fix P0 quality regression, implement signal subsets, add retrain filter validation, decay-gated promotion, verify Phase A multi-model

---

## Changes Made

### 1. P0 FIX: Quality Filter Regression (Blocks ALL Best Bets)

**Root cause:** Session 310 changed the quality filter in `aggregator.py` from `if quality > 0 and quality < 85:` to `if quality < 85:`. The intent was correct (block missing quality scores), but `feature_quality_score` was never included in the supplemental data query (`supplemental_data.py`). Since `pred.get('feature_quality_score')` returns `None`, quality evaluates to 0, and `0 < 85` blocks ALL picks.

**Impact:** Zero best bets generated for Feb 19-20 (first post-ASB game days). The fix was deployed but the quality data was never in the query.

**Fix:** Added `COALESCE(p.feature_quality_score, 0) AS feature_quality_score` to both the multi-model and single-model CTEs in `supplemental_data.py`, and added `'feature_quality_score'` to the pred dict construction.

**Files:** `ml/signals/supplemental_data.py` (lines 97, 152, 417)

### 2. Signal Subsets (4 curated subsets)

Created `SignalSubsetMaterializer` — a new materializer that filters on pick-level signal tags (not market-level daily_signal). Runs after signal evaluation in the best bets exporter flow.

**4 signal subsets:**

| Subset ID | Signals Required | Min Edge | Direction | Historical HR |
|-----------|-----------------|----------|-----------|---------------|
| `signal_combo_he_ms` | `combo_he_ms` | 5.0 | ANY | 94.9% |
| `signal_combo_3way` | `combo_3way` | 5.0 | OVER | 95.5% |
| `signal_bench_under` | `bench_under` | 5.0 | UNDER | 76.9% |
| `signal_high_count` | 4+ any signals | 5.0 | ANY | 85.7% |

**Graduation path:** When a signal subset hits N>=50 and HR>=65% at edge 5+, it becomes eligible for direct best bets inclusion (independent of the aggregator).

**Files:**
- `data_processors/publishing/signal_subset_materializer.py` (NEW)
- `data_processors/publishing/signal_best_bets_exporter.py` (integration)
- `shared/config/subset_public_names.py` (IDs 36-39)

### 3. Filter Validation (`--validate-filters` flag)

Added `--validate-filters` flag to `retrain.sh` that runs validation queries for model-specific negative filters against the eval window after training.

**Validated filters:**
- UNDER edge 7+ block (model-specific) — checks HR on eval window
- Feature quality < 85 block (model-specific) — checks HR on eval window
- Market-structural filters (edge floor, line movement, bench UNDER, avoid familiar) — always inherited, no validation needed
- Player blacklist — auto-recomputes from data

**Output:** Report with HR per filter vs 52.4% breakeven threshold. Status: CONFIRMED (pattern holds) or REVIEW_NEEDED (pattern may not hold for new model).

**File:** `bin/retrain.sh`

### 4. Decay-Gated Promotion

Modified `retrain.sh --promote` to check `model_performance_daily` for champion's current decay state before promoting.

**Logic:**
- BLOCKED/DEGRADING: Promote immediately (urgency — current model is failing)
- HEALTHY/WATCH: Promote immediately (standard promotion)
- UNKNOWN/INSUFFICIENT_DATA: Proceed with promotion

Added `--force-promote` flag for overriding any future gating logic.

**File:** `bin/retrain.sh`

### 5. Phase A Multi-Model Sourcing Verified

**Finding:** Phase A multi-model sourcing is working correctly. On Feb 19:
- V9 champion wins highest-edge contest for only **1 of 74 players**
- V9 alone produces **zero** edge 5+ picks
- Multi-model sourcing unlocks **all 6** edge 5+ candidates
- Non-V9 models (V12, Q43, Q45, low_vegas) dominate edge contests

The zero best bets on Feb 19-20 was caused by the quality filter regression (fix #1), not a multi-model problem.

### 6. xm_* Materialization Confirmed Working

The Session 310 `classify_system_id` fallback fix is working. Feb 19 data shows:
- `xm_consensus_3plus`: 7 rows
- `xm_consensus_4plus`: 3 rows
- `xm_diverse_agreement`: 3 rows
- `xm_quantile_agreement_under`: 1 row

7 model families discovered (v9_mae, v9_q43, v9_q45, v9_low_vegas, v12_mae, v12_q43, v12_q45).

---

## Key Data Points

### Multi-Model Edge Distribution (Feb 19)

| Model | Times Selected as Highest Edge |
|-------|-------------------------------|
| catboost_v12 | 18 |
| v9_q43 | 16 |
| v9_low_vegas | 16 |
| v9_q45 | 11 |
| v12_q45 | 5 |
| v12_q43 | 5 |
| v12_noveg | 2 |
| **catboost_v9 (champion)** | **1** |

### Edge Unlock from Multi-Model

| Metric | Count |
|--------|-------|
| Players with edge 5+ from ANY model | 6 |
| Players with edge 5+ from V9 only | 0 |
| Players unlocked by multi-model | 6 |

---

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/supplemental_data.py` | Add feature_quality_score to both query CTEs + pred dict |
| `data_processors/publishing/signal_subset_materializer.py` | NEW — signal-based subset materialization |
| `data_processors/publishing/signal_best_bets_exporter.py` | Integrate signal subset materializer |
| `shared/config/subset_public_names.py` | Add 4 signal subset public names (IDs 36-39) |
| `bin/retrain.sh` | --validate-filters, --force-promote, decay-gated promotion |
| `docs/08-projects/current/best-bets-v2/07-SESSION-311-CHANGES.md` | This document |
| `docs/09-handoff/2026-02-20-SESSION-311-HANDOFF.md` | Session handoff |

---

## Architecture After Session 311

```
Phase 5 (Predictions)
        |
Phase 6 (Publishing)
    |
    +-- SubsetMaterializer        --> current_subset_picks (L1: model subsets)
    +-- CrossModelSubsetMaterializer --> current_subset_picks (L2: xm_* subsets) [FIXED]
    |
    +-- SignalBestBetsExporter
    |   +-- query_predictions(multi_model=True)  [with feature_quality_score]
    |   +-- registry.evaluate() --> signal_results
    |   +-- SignalSubsetMaterializer --> current_subset_picks (L3: signal subsets) [NEW]
    |   +-- BestBetsAggregator.aggregate() --> edge-first selection
    |   +-- build_pick_angles()
    |   +-- write BQ + GCS
    |
    [Grading Phase - next day]
    +-- SubsetGradingProcessor grades ALL subsets (L1 + L2 + L3)
```

### Retrain Workflow After Session 311

```
./bin/retrain.sh --promote --validate-filters
    |
    +-- Train model(s) via quick_retrain.py
    |   +-- 6 governance gates
    |
    +-- Filter Validation Report (--validate-filters)
    |   +-- UNDER edge 7+ block: CONFIRMED/REVIEW_NEEDED
    |   +-- Quality < 85 block: CONFIRMED/REVIEW_NEEDED
    |   +-- Market-structural: INHERITED
    |   +-- Player blacklist: AUTO-RECOMPUTES
    |
    +-- Decay-Gated Promotion (--promote)
        +-- Query champion state from model_performance_daily
        +-- BLOCKED/DEGRADING: promote immediately (urgency)
        +-- HEALTHY/WATCH: promote immediately (standard)
```
