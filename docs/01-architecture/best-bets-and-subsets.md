# Best Bets & Subset System Architecture

**Last updated:** Session 314C (2026-02-20)
**Algorithm version:** `v314_consolidated`

## Overview

The subset system creates **observation groups** of predictions at export time, enabling performance tracking across different selection strategies. The best bets system selects **top daily picks** using edge-first filtering with signal annotations.

### Three Key Tables

| Table | Purpose | Who Writes | algorithm_version |
|-------|---------|------------|-------------------|
| `current_subset_picks` | All subset picks (39 subset_ids) | SubsetMaterializer, CrossModelSubsetMaterializer, SignalSubsetMaterializer, SignalAnnotator bridge | Only on `best_bets` subset rows |
| `signal_best_bets_picks` | Best bets for GCS export + grading | SignalBestBetsExporter (System 2) | Yes, always |
| `pick_signal_tags` | Signal evaluations per prediction | SignalAnnotator | No (has version_id) |

### Two Best Bets Systems (consolidated Session 314)

```
Predictions (all CatBoost families, multi_model=True)
    │
    ├─ System 2: SignalBestBetsExporter
    │   ├─ Queries all models, picks highest-edge per player
    │   ├─ Evaluates signals → runs BestBetsAggregator
    │   ├─ Writes to signal_best_bets_picks (BQ)
    │   ├─ Exports to v1/signal-best-bets/{date}.json (GCS)
    │   └─ Writes 4 signal subsets to current_subset_picks
    │
    └─ System 3: SignalAnnotator bridge
        ├─ Queries all models (multi_model=True, Session 314C)
        ├─ Evaluates signals → runs SAME BestBetsAggregator
        ├─ Writes to current_subset_picks (subset_id='best_bets')
        └─ Writes signal tags to pick_signal_tags

Legacy System 1 (BestBetsExporter) was REMOVED in Session 314.
```

Both systems share:
- Same `BestBetsAggregator` with same negative filters
- Same `player_blacklist` (from `compute_player_blacklist`)
- Same `games_vs_opponent` (from shared `query_games_vs_opponent`)
- Multi-model: queries all CatBoost families, picks highest edge per player

System 2 additionally:
- Materializes 4 signal subsets
- Exports to GCS for the frontend
- Writes multi-source attribution columns (source_model_id, etc.)

## Data Flow (Phase 6 Export)

```
daily_export.py --only subset-picks,signal-best-bets
    │
    ├─ 1. SubsetMaterializer.materialize()
    │      30 regular subsets (V9, V12, quantile, etc.)
    │      Written to current_subset_picks
    │
    ├─ 2. CrossModelSubsetMaterializer.materialize()
    │      5 cross-model observation subsets (xm_*)
    │      Written to current_subset_picks (same version_id)
    │
    ├─ 3. SignalAnnotator.annotate()
    │      Evaluates signals on all predictions
    │      Writes pick_signal_tags
    │      Bridges top picks to current_subset_picks (subset_id='best_bets')
    │
    ├─ 4. SignalBestBetsExporter.export()
    │      Evaluates signals, runs aggregator
    │      Writes signal_best_bets_picks
    │      Writes 4 signal subsets to current_subset_picks
    │      Exports GCS JSON
    │
    └─ 5. AllSubsetsPicksExporter.export()
           Reads current_subset_picks + pick_signal_tags
           Exports all-subsets/{date}.json for frontend
```

## BestBetsAggregator — Selection Pipeline

**File:** `ml/signals/aggregator.py`

The aggregator is **edge-first** (Session 297): picks ranked by prediction edge, not signal scores.

### Negative Filters (applied in order, cheapest first)

| # | Filter | Threshold | HR Without | Session |
|---|--------|-----------|------------|---------|
| 1 | Player blacklist | <40% HR on 8+ edge-3+ picks | N/A | 284 |
| 2 | Edge floor | edge < 5.0 | 57% | 297 |
| 3 | UNDER edge 7+ block | UNDER + edge >= 7 | 40.7% | 297 |
| 4 | Familiar matchup | 6+ games vs opponent | regresses | 284 |
| 5 | Feature quality floor | quality < 85 | 24.0% | 278 |
| 6 | Bench UNDER block | UNDER + line < 12 | 35.1% | 278 |
| 7 | Line jumped UNDER | UNDER + delta >= 2.0 | 38.2% | 306 |
| 8 | Line dropped UNDER | UNDER + delta <= -2.0 | 35.2% | 306 |
| 9 | Neg +/- streak | streak >= 3 + UNDER | 13.1% | 294 |
| 10 | Min signal count | < 2 qualifying signals | N/A | 259 |
| 11 | Confidence floor | model-specific (V12: 0.90) | N/A | — |
| 12 | ANTI_PATTERN combo | combo classification | varies | 259 |

After filtering, picks are ranked by `abs(edge)` descending. No max picks cap (natural sizing).

### Return Value

```python
top_picks, filter_summary = aggregator.aggregate(predictions, signal_results)
# filter_summary = {
#     'total_candidates': 85,
#     'passed_filters': 4,
#     'rejected': {'edge_floor': 68, 'under_edge_7plus': 1, ...}
# }
```

## Subset Categories

### Regular Subsets (30, SubsetMaterializer)

Per-model subsets with edge/direction filters. Each model family gets its own set.

| Pattern | Example subset_ids | Filters |
|---------|-------------------|---------|
| Top Pick | `top_pick`, `nova_top_pick` | Top 1 by edge, quality >= 85 |
| Top 3/5 | `top_3`, `nova_top_5` | Top N by edge |
| High Edge | `high_edge_over`, `nova_high_edge_all` | edge >= 7, OVER or ALL |
| Ultra High Edge | `ultra_high_edge` | edge >= 10 |
| Green Light | `green_light` | edge >= 5, quality >= 85 |
| All Picks | `all_picks`, `nova_all_picks` | edge >= 3, quality >= 85 |
| All Predictions | `v9_all_predictions` | edge >= 3, NO quality filter |
| Quantile UNDER | `q43_under_top3` | UNDER only, top 3 |

### Cross-Model Subsets (5, CrossModelSubsetMaterializer)

Observation-only. Track when multiple models agree.

| subset_id | What it means |
|-----------|---------------|
| `xm_consensus_3plus` | 3+ models agree on direction, all edge >= 3 |
| `xm_consensus_4plus` | 4+ models agree |
| `xm_quantile_agreement_under` | All quantile models agree UNDER |
| `xm_mae_plus_quantile_over` | MAE + quantile agree OVER |
| `xm_diverse_agreement` | V9 + V12 (different features) agree |

### Signal Subsets (4, SignalSubsetMaterializer)

Based on which signals fired for each prediction.

| subset_id | Signals Required | HR |
|-----------|-----------------|-----|
| `signal_combo_he_ms` | high_edge + minutes_surge | 94.9% |
| `signal_combo_3way` | ESO + HE + MS (OVER only) | 95.5% |
| `signal_bench_under` | bench_under (UNDER only) | 76.9% |
| `signal_high_count` | 4+ qualifying signals | 85.7% |

### Best Bets (special)

subset_id=`best_bets` — written by SignalAnnotator bridge. Uses BestBetsAggregator with full filter pipeline.

## Key Fields in current_subset_picks

| Field | Description |
|-------|-------------|
| `game_date` | Game date (partition key) |
| `subset_id` | Which subset (e.g., 'top_pick', 'best_bets') |
| `player_lookup` | Canonical player identifier |
| `version_id` | Export batch identifier (v_YYYYMMDD_HHMMSS) |
| `system_id` | Which model produced the prediction |
| `trigger_source` | What triggered this write ('export', 'signal_annotator') |
| `edge` | abs(predicted - line) |
| `composite_score` | Ranking score (= edge in edge-first mode) |
| `recommendation` | 'OVER' or 'UNDER' |
| `signal_tags` | Array of qualifying signal names |
| `signal_count` | Number of qualifying signals |
| `algorithm_version` | Which aggregator version (only on best_bets rows) |
| `pick_angles` | Human-readable reasoning for the pick |
| `qualifying_subsets` | Which other subsets this player appears in |

## Key Fields in signal_best_bets_picks

All fields from current_subset_picks, plus:

| Field | Description |
|-------|-------------|
| `source_model_id` | Which specific model was the source (multi-model) |
| `source_model_family` | Model family (v9_mae, v12_q43, etc.) |
| `n_models_eligible` | How many models had edge 5+ for this player |
| `champion_edge` | What the champion model's edge was |
| `direction_conflict` | True if champion disagrees with source model |
| `actual_points` | Graded actual (filled by SubsetGradingProcessor) |
| `prediction_correct` | Graded result (filled by SubsetGradingProcessor) |

## Combo Registry

**Table:** `nba_predictions.signal_combo_registry`
**Fallback:** `ml/signals/combo_registry.py` `_FALLBACK_REGISTRY`

11 SYNERGISTIC combos (Session 295). ANTI_PATTERN entries removed (Session 314).

Used by the aggregator to detect known-good signal combinations and boost their visibility in pick angles.

## Model Discovery

**File:** `shared/config/cross_model_subsets.py`

6 model families classified by pattern matching:
- `v9_mae`: exact match `catboost_v9`
- `v12_mae`: prefix `catboost_v12` (but not q43/q45 variants)
- `v9_q43`, `v9_q45`: prefix `catboost_v9_q43_*`, `catboost_v9_q45_*`
- `v12_q43`, `v12_q45`: prefix `catboost_v12_noveg_q43_*`, `catboost_v12_noveg_q45_*`

Survives retrains automatically — new model names are classified by pattern.

## Performance (Backfill Simulation, v314_consolidated)

| Period | Picks | W-L | HR | P&L |
|--------|-------|-----|-----|-----|
| Jan 1-31 | 97 | 74-16 | **82.2%** | +$5,640 |
| Feb 1-7 | 16 | 11-5 | 69% | +$550 |
| Feb 8-14 (stale model) | 14 | 4-6 | 40% | -$260 |
| Feb 15-19 (post-retrain) | 4 | 2-2 | 50% | -$20 |
| **Total** | **131** | **91-29** | **75.8%** | **+$5,910** |

## Future Improvements Being Considered

1. **UNDER day detection** — Identify game-day attributes that predict UNDER-favorable conditions. Feb 19 showed V9 UNDER at any edge went 12-0 while high-edge OVER failed. Possible indicators: league-wide scoring trends, back-to-back density, schedule context.

2. **Direction-aware model selection** — Instead of highest edge, consider which model is best for OVER vs UNDER on a given day. V12 High Edge OVER went 0-4 on Feb 19 while quantile UNDERs went 8-0.

3. **Backfill all historical subsets** — Re-materialize Jan 1 - Feb 19 with consolidated code. Skill: `/backfill-subsets`.

4. **Fill algorithm_version on all materializers** — Currently only best_bets rows have it. Adding to SubsetMaterializer and CrossModelSubsetMaterializer would give full version traceability.

5. **Threshold governance gate** — Add post-retrain validation of edge bucket HRs to `bin/retrain.sh`. Static thresholds, monitoring-only (not auto-adjust).

## Key Files

| File | Purpose |
|------|---------|
| `ml/signals/aggregator.py` | BestBetsAggregator — core selection logic |
| `data_processors/publishing/signal_best_bets_exporter.py` | System 2 — GCS export + BQ |
| `data_processors/publishing/signal_annotator.py` | System 3 — signal tags + bridge |
| `data_processors/publishing/subset_materializer.py` | Regular subset materialization |
| `data_processors/publishing/cross_model_subset_materializer.py` | Cross-model subsets |
| `data_processors/publishing/signal_subset_materializer.py` | Signal-based subsets |
| `ml/signals/combo_registry.py` | Combo registry (SYNERGISTIC/ANTI_PATTERN) |
| `ml/signals/supplemental_data.py` | Shared BQ queries for signals |
| `ml/signals/player_blacklist.py` | Player blacklist computation |
| `shared/config/cross_model_subsets.py` | Model family classification |
| `shared/config/subset_definitions.py` | Subset definition configs |
| `shared/config/subset_public_names.py` | Internal ID → public name mapping |
| `bin/backfill_dry_run.py` | Backfill simulation script |

---
*Created: Session 314C. See handoff: `docs/09-handoff/2026-02-20-SESSION-314B-HANDOFF.md`*
