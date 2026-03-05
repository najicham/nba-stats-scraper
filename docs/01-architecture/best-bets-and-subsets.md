# Best Bets & Subset System Architecture

**Last updated:** Session 412 (2026-03-05)
**Algorithm version:** `v314_consolidated`

## Overview

The subset system creates **observation groups** of predictions at export time, enabling performance tracking across different selection strategies. The best bets system selects **top daily picks** using edge-first filtering with signal annotations.

### Three Key Tables

| Table | Purpose | Who Writes | algorithm_version |
|-------|---------|------------|-------------------|
| `current_subset_picks` | All subset picks (39 subset_ids) | SubsetMaterializer, CrossModelSubsetMaterializer, SignalSubsetMaterializer, SignalAnnotator bridge | Only on `best_bets` subset rows |
| `signal_best_bets_picks` | Best bets for GCS export + grading (rows LOCKED after write) | SignalBestBetsExporter (System 2) | Yes, always |
| `pick_signal_tags` | Signal evaluations per prediction | SignalAnnotator | No (has version_id) |
| `best_bets_published_picks` | Lock metadata (signal_status, first_published_at) | BestBetsAllExporter | No |

### True Pick Locking (Session 412)

Once a pick is written to `signal_best_bets_picks`, it is **never deleted** (only upserted).
Re-exports only delete rows for players being refreshed. Picks dropped by the signal
pipeline on subsequent runs are preserved in the table for grading.

```
Export 1: Signal → 8 picks → all written
Export 2: Signal → 6 returning + 2 new (2 dropped)
    DELETE only 8 player_lookups in new output
    INSERT 8 rows
    2 dropped picks STAY (locked for grading)
    Result: 10 picks total
```

**Published picks in `best_bets_published_picks`** always get `signal_status='active'`.
Only `game_started` (game in progress/final) and `model_disabled` get special statuses.
The old `signal_status='dropped'` is eliminated — published = active.

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

### Negative Filters (14 active, applied in order)

| # | Filter | Threshold | HR Without | Session |
|---|--------|-----------|------------|---------|
| 1 | Player blacklist | <40% HR on 8+ edge-3+ picks (multi-model) | N/A | 284, 365 |
| 2 | Edge floor | edge < 3.0 | N/A | 352 |
| 3 | Familiar matchup | 6+ games vs opponent | regresses | 284 |
| 4 | Feature quality floor | quality < 85 | 24.0% | 278 |
| 5 | Bench UNDER block | UNDER + line < 12 | 35.1% | 278 |
| 6 | UNDER + line jumped 2+ | UNDER + prop_line_delta >= 2.0 | 38.2% | 306 |
| 7 | UNDER + line dropped 2+ | UNDER + prop_line_delta <= -2.0 | 35.2% | 306 |
| 8 | AWAY block | v12_noveg/v9 family + AWAY game | 43-48% HR | 365 |
| 9 | Model-direction affinity | model+direction+edge combo HR < 45% on 15+ picks | varies | 343 |
| 10 | Signal density | base-only signals → skip unless edge >= 7.0 | N/A | 352 |
| 11 | Opponent UNDER block | UNDER + opponent in {MIN, MEM, MIL} | 43-49% HR | 372 |
| 12 | SC=3 OVER edge gate | OVER + signal_count == 3 + edge < 7.0 | 33.3% | 374b |
| 13 | OVER + line dropped 2+ | OVER + prop_line_delta <= -2.0 | 39.1% | 374b |
| 14 | Opponent depleted UNDER | UNDER + 3+ opponent stars out | 44.4% HR | 374b |
| — | Legacy model block | catboost_v9, catboost_v12 (dead champions) | 54.8% | 365 |

**Min signal count:** >= 3 qualifying signals (raised from 2, Session 370).

After filtering, picks are ranked by `abs(edge)` descending with model HR-weighted selection (Session 365). No max picks cap (natural sizing).

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

11 SYNERGISTIC combos. ANTI_PATTERN entries removed (Session 314).

Used by the aggregator to detect known-good signal combinations and boost their visibility in pick angles.

## Model Discovery

**File:** `shared/config/cross_model_subsets.py`

6 model families classified by pattern matching:
- `v9_mae`: exact match `catboost_v9`
- `v12_mae`: prefix `catboost_v12` (but not q43/q45 variants)
- `v9_q43`, `v9_q45`: prefix `catboost_v9_q43_*`, `catboost_v9_q45_*`
- `v12_q43`, `v12_q45`: prefix `catboost_v12_noveg_q43_*`, `catboost_v12_noveg_q45_*`

Survives retrains automatically — new model names are classified by pattern.

## Signal System (21 Active)

See CLAUDE.md [SIGNALS] for the full signal table. Key signals by Feb+ HR in best bets:

| Signal | HR (Feb+) | N | Role |
|--------|-----------|---|------|
| combo_3way | 83.3% | 7 | Top combo |
| combo_he_ms | 83.3% | 7 | Top combo |
| edge_spread_optimal | 61.7% | 53 | Workhorse |
| high_edge | 61.7% | 53 | Workhorse |
| rest_advantage_2d | 57.1% | 14 | Conditional |
| book_disagreement | 57.1% | 7 | Watch |
| line_rising_over | N/A | N/A | Revived Session 387 (96.6% historical) |
| fast_pace_over | N/A | N/A | Revived Session 387 (81.5% historical) |

## Live Performance (Jan 1 - Mar 2, 2026)

### Weekly Trend

| Week | Picks | Graded | HR | Notes |
|------|-------|--------|-----|-------|
| Jan 4 | 11 | 11 | **81.8%** | Peak performance |
| Jan 11 | 26 | 26 | 53.8% | |
| Jan 18 | 17 | 17 | **88.2%** | |
| Jan 25 | 15 | 13 | **84.6%** | |
| Feb 1 | 17 | 17 | 70.6% | |
| Feb 8 | 14 | 10 | **40.0%** | Model decay begins |
| Feb 15 | 6 | 6 | 50.0% | Low volume |
| Feb 22 | 19 | 16 | 56.3% | Recovering |
| Mar 1 | 2 | 2 | 100% | Too few to judge |

### Monthly by Direction

| Month | OVER HR | OVER N | UNDER HR | UNDER N |
|-------|---------|--------|----------|---------|
| **Jan** | **80.0%** | 40 | 63.0% | 27 |
| **Feb** | 53.3% | 30 | **63.2%** | 19 |

**Key insight:** OVER collapsed from 80% → 53% in Feb. UNDER stayed constant at 63%. The entire Feb decline is an OVER problem.

### Filter Stack Effectiveness by Edge Band

| Edge Band | OVER HR (N) | UNDER HR (N) | Combined |
|-----------|-------------|--------------|----------|
| **7+** | **77.8%** (27) | **100%** (5) | **81.3%** (32) |
| 5-7 | 67.5% (40) | 58.5% (41) | 63.0% (81) |
| 3-5 | 25.0% (4) | 100% (1) | 40.0% (5) |

### Signal Count x Edge (Sweet Spots)

| Edge | SC=3 | SC=4 | SC=5 | SC=6+ |
|------|------|------|------|-------|
| **7+** | 85.7% (7) | **87.5%** (8) | 69.2% (13) | **100%** (4) |
| 5-7 | **51.3%** (39) | 70.6% (17) | 70.0% (10) | 90.0% (10) |

**SC=3 at edge 5-7 is the weak link:** 51.3% HR on the largest bucket (39 picks). Everything SC 4+ is 70%+.

### Ultra Bets

| Criteria Count | HR | N | Status |
|---------------|-----|---|--------|
| 3 criteria | **93.8%** | 16 | Elite |
| 2 criteria | **100%** | 6 | Elite |
| 1 criterion (edge_4.5+ only) | **33.3%** | 9 | Weak — needs tightening |
| Non-ultra | 62.7% | 83 | Solid |

### Model Family Contribution (Feb+)

| Family | Picks | HR | Notes |
|--------|-------|-----|-------|
| Legacy (v9/v12) | 35 | 54.8% | Blocked but still winning selection for 60% of candidates |
| v12_noveg | 13 | 58.3% | |
| v9_low_vegas | 5 | 75.0% | Best but tiny N |
| v12_vegas | 2 | 100% | Tiny N |

## Known Issues & Improvement Areas

### 1. Legacy Model Domination (Critical)
Dead champion models (catboost_v9, catboost_v12) still win the per-player model selection for ~87% of candidates because they generate inflated edges (stale models drift from the line). They then get blocked by the legacy filter. This is the biggest funnel bottleneck — on thin slates (4 games), it can produce 0 picks. Newer models need to generate competitive edges.

### 2. SC=3 at Edge 5-7 (Actionable)
51.3% HR on 39 picks — the largest single bucket and barely breakeven. Consider raising SC floor to 4 for edge 5-7 (70.6% HR) while keeping SC=3 for edge 7+ (85.7%).

### 3. Ultra Single-Criterion Gate (Actionable)
edge_4.5+-only ultra picks are 33.3% HR — worse than non-ultra. Should require 2+ criteria for ultra classification.

### 4. OVER Collapse (In Progress)
Session 387-388 revived two OVER-targeting signals (`line_rising_over` 96.6% HR, `fast_pace_over` 81.5% HR). Both confirmed firing on March 2. Impact data accumulating.

### 5. Model Freshness
7-day retrain cadence recommended but not consistently followed. Most models 10-20 days stale as of March 2. Noveg OVER at 64.6% (edge 3+) is the strongest raw signal — prioritize noveg models for retraining.

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
*Created: Session 314C. Updated: Session 388 (Mar 2, 2026) with live performance data and pipeline audit findings.*
