# Per-Model Best Bets Pipelines

**Session 443 | Algorithm: `v443_per_model_pipelines`**

## Problem

The current BB pipeline uses winner-take-all per player: one model wins (highest `|edge| * model_hr_weight`), all others discarded. This caused the best model in the fleet (`catboost_v9_train1102_0108`, 88% OVER top-3, 76% UNDER top-3) to be **disabled entirely** because it dominated per-player selection but then got blocked by `LEGACY_MODEL_BLOCKLIST`.

Models have wildly different BB performance profiles (87.5% vs 47% at same edge tier), but the single pipeline can't exploit this. Bad models (lgbm at 40% BB HR, similarity_balanced at 32% top-1) dilute the pool when they win per-player selection on low-edge picks.

## Solution

Replace the single winner-take-all pipeline with **per-model pipelines feeding a pool-and-rank merge layer**.

## Architecture

```
Worker: N models × ~120 players = ~1,320 predictions
         │
    ┌────┴──────────────────────────────────────┐
    │  Shared Context (computed once)           │
    │  signal_health, player_blacklist,         │
    │  combo_registry, regime_context,          │
    │  signal_results, game_times, etc.         │
    └────┬──────────────────────────────────────┘
         │
    ┌────┴──────────────────────────────────────┐
    │  Per-Model Pipeline Runner                │
    │  For each enabled model:                  │
    │    1. Query that model's predictions       │
    │    2. aggregator.aggregate(mode=per_model) │
    │       - All negative filters ✓            │
    │       - Composite scoring ✓               │
    │       - NO team cap (deferred)            │
    │       - NO rescue cap (deferred)          │
    │    → per-model candidate list             │
    │    → ALL saved to model_bb_candidates     │
    └────┬──────────────────────────────────────┘
         │  N independent candidate lists
         ▼
    ┌────┴──────────────────────────────────────┐
    │  Pool & Rank Merge                        │
    │  1. Union all model candidate lists       │
    │  2. Sort by composite_score DESC          │
    │  3. Walk list:                            │
    │     - Skip if player already selected     │
    │     - Skip if team count >= 2             │
    │     - Skip if total >= MAX_MERGED_PICKS   │
    │  4. Apply rescue cap (40% of merged)      │
    │  → signal_best_bets_picks (production)    │
    │  → model_bb_candidates.was_selected=TRUE  │
    └───────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Aggregator gets `mode='per_model'`
The `BestBetsAggregator` already processes any `List[Dict]`. Per-model mode skips team cap and rescue cap (deferred to merge) but keeps all 30+ negative filters and composite scoring. Existing 109 tests unaffected.

### 2. Signals are shared (evaluated once)
Signals depend on player data (3PT%, minutes, line movement), not model identity. Pre-compute once, pass to every model's aggregator run. Exception: `model_health` signal checks the current model's health — pass `system_id` context per model.

### 3. Pool-and-rank merge (no custom merge scoring)
**Review feedback:** Don't invent a new merge scoring formula. Pool all candidates from all models, sort by `composite_score` (already computed by aggregator using validated OVER/UNDER ranking logic), walk list keeping first occurrence per player subject to team cap and volume cap. This reuses existing ranking and eliminates dedup-by-pipeline-HR complexity.

### 4. All candidates saved with full provenance
`model_bb_candidates` records EVERY candidate from EVERY model pipeline — whether selected or not. Rich metadata enables historical study of why picks were made, what signals fired, which models agreed, and how the merge selected.

### 5. No agreement bonus (until validated)
Raw multi-model agreement is anti-correlated with winning. Post-filter agreement MAY behave differently but is unvalidated. Track `pipeline_agreement_count` for study. Add bonus only after backfill data proves positive correlation.

### 6. Direction conflicts tracked, not penalized (yet)
If Model A says OVER and Model B says UNDER for same player, both enter the pool independently. The higher `composite_score` wins naturally. Track `direction_conflict_count` for historical analysis. Query conflict HR after data accumulates before adding penalty.

## Data Flow Detail

### Step 1: Shared Context (computed once)
```python
shared_context = {
    'signal_health': query_signal_health(),
    'player_blacklist': query_player_blacklist(),
    'model_direction_blocks': query_model_direction_affinity(),
    'combo_registry': load_combo_registry(),
    'regime_context': build_regime_context(),
    'games_vs_opponent': query_games_vs_opponent(),
    'runtime_demoted_filters': query_filter_overrides(),
    'game_times': query_game_times(),
    'model_profile_store': query_model_profiles(),
}
```

Signal evaluation is also shared but needs predictions first — evaluate per-player once, keyed by `player_lookup::game_id`, then pass same results to all model aggregator runs.

### Step 2: Per-Model Pipeline
For each enabled model:
```python
predictions, supp_map = query_predictions_with_supplements(
    bq_client, target_date,
    system_id=model_id,
    multi_model=False,
)
# Evaluate signals for any NEW players this model covers
update_signal_results(shared_signal_results, predictions, supp_map)

aggregator = BestBetsAggregator(shared_context..., mode='per_model')
candidates, filter_summary = aggregator.aggregate(predictions, shared_signal_results)

# Tag every candidate with provenance
for pick in candidates:
    pick['source_pipeline'] = model_id
```

### Step 3: Pool & Rank Merge
```python
def merge_model_pipelines(
    model_candidates: Dict[str, List[Dict]],
    max_picks: int = 15,
    max_per_team: int = 2,
    rescue_cap_pct: float = 0.40,
) -> Tuple[List[Dict], Dict]:
    # 1. Pool all candidates
    pool = []
    for model_id, candidates in model_candidates.items():
        pool.extend(candidates)

    # 2. Compute pipeline agreement per player
    player_models = defaultdict(set)
    for pick in pool:
        player_models[pick['player_lookup']].add(pick['source_pipeline'])

    # 3. Sort by composite_score DESC
    pool.sort(key=lambda p: p['composite_score'], reverse=True)

    # 4. Walk list with constraints
    selected = []
    seen_players = set()
    team_counts = defaultdict(int)
    rescue_count = 0

    for pick in pool:
        player = pick['player_lookup']
        if player in seen_players:
            continue
        team = pick.get('team_tricode', '')
        if team_counts[team] >= max_per_team:
            continue
        if len(selected) >= max_picks:
            break
        if pick.get('signal_rescued') and rescue_count >= len(selected) * rescue_cap_pct:
            continue

        # Enrich with merge metadata
        pick['pipeline_agreement_count'] = len(player_models[player])
        pick['pipeline_agreement_models'] = list(player_models[player])

        selected.append(pick)
        seen_players.add(player)
        team_counts[team] += 1
        if pick.get('signal_rescued'):
            rescue_count += 1

    return selected, merge_summary
```

## Bug Fix Required

**SHOWSTOPPER in `supplemental_data.py`:** `source_model_family` is NOT set when `multi_model=False`. The V9 UNDER 7+ filter (`aggregator.py` line 595) checks `source_model_family.startswith('v9')` — silently fails in single-model mode, allowing V9 UNDER 7+ picks (34.1% HR) through.

**Fix:** Set `source_model_family = classify_system_id(system_id)` unconditionally in `_parse_prediction_row()`, not gated by `multi_model`.

## Pick Provenance Schema

Every pick (in `model_bb_candidates` and `signal_best_bets_picks`) stores full decision history:

### Model Context
| Field | Description |
|-------|-------------|
| `source_pipeline` | Which model's pipeline produced this candidate |
| `source_model_family` | Model family classification (v9_mae, v12_noveg, etc.) |
| `pipeline_hr_21d` | That model's pipeline HR at time of pick |
| `pipeline_hr_source` | 'pipeline', 'bb_legacy', or 'raw_fallback' |

### Prediction Context
| Field | Description |
|-------|-------------|
| `predicted_points` | Model's prediction |
| `line_value` | Vegas line at pick time |
| `edge` | predicted - line |
| `recommendation` | OVER/UNDER |
| `confidence_score` | Model confidence |
| `feature_quality_score` | Feature store quality (0-1) |

### Signal Context
| Field | Description |
|-------|-------------|
| `signal_count` | Total signals fired |
| `real_signal_count` | Non-base, non-shadow signals |
| `signal_tags` | List of all fired signal names |
| `signal_rescued` | Whether admitted via rescue pathway |
| `rescue_signal` | Which signal rescued it |
| `combo_classification` | Matched combo pattern |
| `combo_hit_rate` | Historical combo HR |

### Ranking Context
| Field | Description |
|-------|-------------|
| `composite_score` | Aggregator-computed rank score |
| `rank_in_pipeline` | Rank within source model's pipeline |
| `qualifying_subsets` | Dynamic subsets this pick qualifies for |

### Merge Context (final BB picks only)
| Field | Description |
|-------|-------------|
| `pipeline_agreement_count` | How many model pipelines nominated this player |
| `pipeline_agreement_models` | Which pipelines agreed |
| `direction_conflict_count` | How many pipelines disagreed on direction |
| `merge_rank` | Final rank in merged output |
| `was_selected` | TRUE if survived merge into final BB |
| `selection_reason` | Why selected or dropped ('first_occurrence', 'team_cap', 'volume_cap', 'rescue_cap', 'player_dedup') |

### Filter Context
| Field | Description |
|-------|-------------|
| `filters_passed` | List of filters this pick survived |
| `filters_failed` | List of filters that blocked similar picks from this player (observation filters) |
| `observation_flags` | Observation filters that fired but didn't block |

### Player Context (for historical study)
| Field | Description |
|-------|-------------|
| `player_line_tier` | bench/role/starter/star based on line value |
| `home_away` | HOME or AWAY |
| `spread` | Game spread at pick time |
| `over_rate_last_10` | Player's over rate in last 10 games |
| `is_back_to_back` | B2B game |
| `star_teammates_out` | Number of star teammates missing |

## New BQ Table: `model_bb_candidates`

Records every candidate from every model pipeline (before merge). Partitioned by `game_date`.

All fields from Pick Provenance Schema above, plus:
- `game_date` (DATE) — partition key
- `player_lookup` (STRING)
- `game_id` (STRING)
- `created_at` (TIMESTAMP)

## Extended Table: `model_performance_daily`

Add pipeline-level columns (no new table needed):

| Column | Type | Description |
|--------|------|-------------|
| `pipeline_candidates` | INT64 | Picks from this model's pipeline today |
| `pipeline_selected` | INT64 | How many survived merge |
| `pipeline_hr_7d` | FLOAT64 | Post-filter candidate HR, 7d rolling |
| `pipeline_hr_21d` | FLOAT64 | Post-filter candidate HR, 21d rolling |
| `pipeline_over_hr_21d` | FLOAT64 | Direction-specific |
| `pipeline_under_hr_21d` | FLOAT64 | Direction-specific |
| `pipeline_n_graded_21d` | INT64 | Sample size |

## Files

### New Files
| File | Purpose |
|------|---------|
| `ml/signals/per_model_pipeline.py` | Runs aggregator for a single model, shared context |
| `ml/signals/pipeline_merger.py` | Pool-and-rank merge layer |
| `bin/backfill_model_bb_candidates.py` | Backfill script for historical data |
| `schemas/model_bb_candidates.json` | BQ schema |

### Modified Files
| File | Change |
|------|--------|
| `data_processors/publishing/signal_best_bets_exporter.py` | `generate_json()` calls per-model pipelines + merger |
| `ml/signals/supplemental_data.py` | Fix `source_model_family` bug (set unconditionally) |
| `ml/signals/aggregator.py` | Add `mode='per_model'` parameter (skips team_cap, rescue_cap) |
| `ml/analysis/model_performance.py` | Add pipeline-level HR computation from `model_bb_candidates` |

### Unchanged Files
| File | Why |
|------|-----|
| `ml/signals/registry.py` | Signal evaluation is model-agnostic |
| `ml/signals/combo_registry.py` | Combos are player-level |
| `ml/signals/cross_model_scorer.py` | Replaced by post-filter pipeline agreement in merge layer |

## Bootstrap / Cold-Start

**Backfill:** `bin/backfill_model_bb_candidates.py` runs each model through the aggregator for Jan 9 - Mar 8 (~50 game dates × 11 models). Shares context per date, ~30 minutes total. Populates `model_bb_candidates` retroactively.

**Cold-start fallback for new models:**
1. `pipeline_hr_21d` from `model_bb_candidates` (if available)
2. `bb_hr_21d` from `model_performance_daily` (old single-pipeline, directionally valid proxy)
3. `raw_hr_14d / 55.0` from `model_performance_daily`
4. `0.91` default (= 50.0 / 55.0)

Track `pipeline_hr_source` on every pick for audit.

## Re-enabling catboost_v9_train1102_0108

The shadow registry entry `catboost_v9_33f_train20251102-20260108_20260208_170526` is the same model binary. In the per-model pipeline architecture:
1. Set `enabled=TRUE, status='active'` in model_registry
2. It gets its own pipeline automatically (no blocklist — different system_id)
3. Pipeline HR bootstraps from the backfill

## Performance

- Running aggregator N times instead of once: sub-second per model (CPU-bound, ~120 predictions × 30 filters)
- Signal evaluation: shared, run once (the expensive part)
- BQ queries: N single-model prediction queries. Can be batched.
- Total overhead: ~5-10 seconds for 11 models. Current pipeline: 30-60 seconds.

## Volume Control

- `MAX_MERGED_PICKS_PER_DAY = 15` — soft cap on merged output
- Team cap: 2 per team (applied in merge, not per-model)
- Rescue cap: 40% of merged slate (applied in merge, not per-model)
- Natural sizing from signal_count gate still applies per-model

## Future Considerations (NOT building now)

- Pipeline agreement bonus: add if backfill shows post-filter agreement correlates with HR
- Direction conflict penalty: add if query shows conflict picks underperform
- Model-specific filter thresholds: if per-model data shows certain models need different edge floors
- Pipeline HR-weighted dedup: if pool-and-rank underperforms pipeline-HR dedup, revisit
