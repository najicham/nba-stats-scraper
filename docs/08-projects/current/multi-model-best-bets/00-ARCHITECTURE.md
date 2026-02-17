# Multi-Model Best Bets Architecture

**Session:** 277
**Date:** 2026-02-16
**Status:** Implemented, pending deploy

## Overview

3-layer architecture that leverages all 6 models (V9 MAE, V12 MAE, V9 Q43, V9 Q45, V12 Q43, V12 Q45) for improved best bets selection.

## Architecture Layers

### Layer 1: Per-Model Subsets (Existing + New)

Each model has its own subset definitions tracked in `dynamic_subset_definitions`. The `SubsetMaterializer` handles multi-model via `subsets_by_model` grouping.

**New (Session 277):** Added 4 V12-Quantile subsets (IDs 27-30):
- `v12q43_under_top3` — V12 Q43 UNDER Top 3
- `v12q43_all_picks` — V12 Q43 All Picks
- `v12q45_under_top3` — V12 Q45 UNDER Top 3
- `v12q45_all_picks` — V12 Q45 All Picks

### Layer 2: Cross-Model Observation Subsets (New)

5 meta-subsets that observe cross-model agreement patterns. Written to `current_subset_picks` with `system_id='cross_model'`. Graded automatically by existing `SubsetGradingProcessor`.

| subset_id | Description | Logic |
|-----------|-------------|-------|
| `xm_consensus_3plus` | 3+ models agree, edge >= 3 | Majority direction, all agreeing models have edge >= 3 |
| `xm_consensus_5plus` | 5+ models agree, top 5 | Highest conviction consensus, ranked by avg edge |
| `xm_quantile_agreement_under` | All 4 quantile models agree UNDER | Quantile specialist consensus (edge >= 3 each) |
| `xm_mae_plus_quantile_over` | MAE + quantile agree OVER | Cross-loss-function agreement on OVER |
| `xm_diverse_agreement` | V9 + V12 agree, edge >= 3 | Different feature sets (33 vs 50 features) agree |

### Layer 3: Consensus Scoring in Aggregator (New)

The `BestBetsAggregator` now applies a `consensus_bonus` from `CrossModelScorer`:

```
agreement_base = 0.05 * (n_agreeing - 2) if n >= 3 else 0   # [0.05 - 0.20]
diversity_mult = 1.3 if both_v9_and_v12 else 1.0             # [1.0 - 1.3]
quantile_bonus = 0.10 if UNDER + all_quantile_agree else 0   # [0 - 0.10]
consensus_bonus = agreement_base * diversity_mult + quantile_bonus   # max 0.36
```

Full scoring formula:
```
composite_score = edge_score * signal_multiplier + combo_adjustment + consensus_bonus
```

The consensus bonus (max 0.36) is meaningful but not dominant vs combo bonuses (0.5-2.5).

## Data Flow

```
Daily Pipeline (Phase 6 Export):

1. SubsetMaterializer.materialize()          — per-model subsets
2. CrossModelSubsetMaterializer.materialize() — cross-model observation subsets (NEW)
3. SignalAnnotator.annotate()                — signal evaluation + bridge to best_bets subset
4. AllSubsetsPicksExporter.export()          — picks up all rows including xm_* subsets
5. SignalBestBetsExporter.export()            — top 5 picks with consensus scoring
```

## Files

| File | Purpose |
|------|---------|
| `ml/signals/supplemental_data.py` | V12 CTE for dual_agree/model_consensus signals |
| `ml/signals/cross_model_scorer.py` | Computes per-player consensus factors |
| `ml/signals/aggregator.py` | Applies consensus_bonus to composite_score |
| `shared/config/cross_model_subsets.py` | Definitions for 5 cross-model subsets |
| `shared/config/subset_public_names.py` | Public names for IDs 27-35 |
| `data_processors/publishing/cross_model_subset_materializer.py` | Materializes cross-model subsets |
| `data_processors/publishing/signal_best_bets_exporter.py` | Wires in CrossModelScorer |
| `data_processors/publishing/signal_annotator.py` | Wires in CrossModelScorer for bridge |
| `backfill_jobs/publishing/daily_export.py` | Pipeline integration |

## Model Groups

| Group | Models | Feature Count |
|-------|--------|---------------|
| V9 Feature Set | catboost_v9, v9_q43, v9_q45 | 33 features |
| V12 Feature Set | catboost_v12_noveg, v12_q43, v12_q45 | 50 features |
| MAE Models | catboost_v9, catboost_v12_noveg | MAE loss |
| Quantile Models | v9_q43, v9_q45, v12_q43, v12_q45 | Quantile loss (asymmetric) |

## Verification

```sql
-- Check V12 signals are now firing
SELECT game_date, signal_tags
FROM nba_predictions.pick_signal_tags
WHERE game_date >= '2026-02-19'
  AND ('dual_agree' IN UNNEST(signal_tags) OR 'model_consensus_v9_v12' IN UNNEST(signal_tags))
LIMIT 10;

-- Check cross-model subsets
SELECT subset_id, COUNT(*) as picks
FROM nba_predictions.current_subset_picks
WHERE game_date >= '2026-02-19'
  AND subset_id LIKE 'xm_%'
GROUP BY 1;

-- Check consensus bonus in best bets
SELECT game_date, player_name, consensus_bonus, model_agreement_count, composite_score
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-02-19'
ORDER BY game_date, rank;
```

## Key Design Decisions

1. **V12 CTE uses `LIKE 'catboost_v12_noveg%' AND NOT LIKE '%_q4%'`** to match the MAE V12 model regardless of training date suffix.
2. **Cross-model subsets use `system_id='cross_model'`** to distinguish from per-model subsets.
3. **Consensus bonus only applies when pick direction matches majority direction** — prevents boosting picks that disagree with consensus.
4. **All new components are non-fatal** — failures are caught and logged, pipeline continues without them.
5. **BQ schema changes are additive (nullable columns)** — no migration needed, backward compatible.
