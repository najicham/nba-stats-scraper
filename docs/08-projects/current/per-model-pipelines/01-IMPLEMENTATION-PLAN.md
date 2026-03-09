# Implementation Plan — Per-Model Best Bets Pipelines (Revised)

## Key Review Findings That Changed the Plan

1. **Signals CANNOT be shared** — nearly every signal gates on `recommendation` (OVER/UNDER) which is model-specific. Edge-dependent signals (high_edge, combo_3way, etc.) also differ per model. Signals must evaluate per-model.
2. **Batch query optimization** — the `multi_model=True` query already scans all models. Remove the `ROW_NUMBER` dedup, partition in Python. Reduces N×11 BQ queries to ~12.
3. **10 satellite queries ARE model-agnostic** — pace, DVP, projections, CLV, etc. only depend on player/date. Run once, share supplemental_map.
4. **Streak data** — uses `system_id` filter but actual outcomes are player-level. Run once without model filter.
5. **`aggregate()` mode on `__init__` not `aggregate()`** — avoids breaking calling convention.
6. **Skip `solo_game_pick_obs` in per_model mode** — meaningless with single model's predictions.
7. **Ultra bets, pick angles, signal subset materializer, 1-pick-day** — must run post-merge.
8. **`_filter_started_games()` and `query_games_vs_opponent()`** — shared context, not per-model.

## Execution Order

### Step 1: Fix `source_model_family` bug [~5 lines]
**File:** `ml/signals/supplemental_data.py`
Move `source_model_id` and `source_model_family` assignment outside `if multi_model:` block.

### Step 2: Add `mode` to aggregator `__init__` [~15 lines]
**File:** `ml/signals/aggregator.py`
- Add `mode='production'` param to `__init__()`
- When `mode='per_model'`: skip team_cap, rescue_cap, solo_game_pick_obs
- Existing 109 tests pass unchanged + 2 new tests

### Step 3: Build `per_model_pipeline.py` [~250 lines]
**File:** `ml/signals/per_model_pipeline.py` (NEW)

```python
@dataclass
class SharedContext:
    """Model-independent data computed once per date."""
    signal_health: Dict
    player_blacklist: Set[str]
    model_direction_blocks: Dict
    combo_registry: Dict
    regime_context: Dict
    games_vs_opponent: Dict
    runtime_demoted_filters: Set[str]
    game_times: Dict
    model_profile_store: Dict
    started_game_ids: Set[str]
    supplemental_map: Dict[str, Dict]  # player_lookup → supplemental data
    all_predictions: Dict[str, List[Dict]]  # system_id → predictions (from batch query)

@dataclass
class PipelineResult:
    system_id: str
    candidates: List[Dict]
    filter_summary: Dict
    signal_results: Dict[str, List]

def build_shared_context(bq_client, target_date) -> SharedContext:
    """One-time setup: batch query all models, run satellite queries once."""

def run_single_model_pipeline(system_id, shared_ctx) -> PipelineResult:
    """Run signals + aggregator for one model. No BQ queries — all data from shared_ctx."""

def run_all_model_pipelines(bq_client, target_date) -> Tuple[Dict[str, PipelineResult], SharedContext]:
    """Main entry: build context, loop models, return all results."""
```

**Key optimization:** `build_shared_context()` runs the batch prediction query (reuse `multi_model=True` SQL without `ROW_NUMBER` dedup) + 10 satellite queries = ~12 BQ queries total. Then `run_single_model_pipeline()` is pure Python — no BQ.

### Step 4: Build `pipeline_merger.py` [~150 lines]
**File:** `ml/signals/pipeline_merger.py` (NEW)

```python
def merge_model_pipelines(
    model_results: Dict[str, PipelineResult],
    max_picks: int = 15,
    max_per_team: int = 2,
    rescue_cap_pct: float = 0.40,
) -> Tuple[List[Dict], Dict]:
    """Pool all candidates, sort by composite_score, first-occurrence dedup."""
```

- Pool all model candidates into one list
- Compute `pipeline_agreement_count` per player (how many models nominated them)
- Sort by `composite_score` DESC
- Walk: skip player dupes, enforce team cap, volume cap, rescue cap
- Tag every pick with merge provenance
- Return selected + merge summary

### Step 5: Wire into exporter [~100 lines changed]
**File:** `data_processors/publishing/signal_best_bets_exporter.py`

Replace `generate_json()` internals:
```python
# OLD:
predictions = query_predictions_with_supplements(multi_model=True)  # ROW_NUMBER dedup
signal_results = evaluate_signals(predictions)
picks = aggregator.aggregate(predictions, signal_results)

# NEW:
model_results, shared_ctx = run_all_model_pipelines(bq_client, target_date)
picks, merge_summary = merge_model_pipelines(model_results)
# Then: pick_angles, ultra, subset materializer, JSON format, BQ write (unchanged)
```

Post-merge steps (keep as-is): pick_angles, ultra bets, 1-pick-day, signal subset materializer, BQ write to `signal_best_bets_picks`, GCS JSON.

Add: BQ write to `model_bb_candidates` (all candidates from all models).

### Step 6: BQ table + schema
**File:** `schemas/model_bb_candidates.json` (NEW)
**Action:** Create table in BQ with full provenance schema from architecture doc.

### Step 7: Extend model_performance.py [~30 lines]
**File:** `ml/analysis/model_performance.py`
Add `pipeline_stats` CTE reading from `model_bb_candidates`. Add 6 columns to output.

### Step 8: Re-enable v9_train1102_0108
**Action:** BQ UPDATE on model_registry.

## Parallel Execution Strategy

```
Step 1 ─┐
        ├─► Step 3 ─┐
Step 2 ─┘            ├─► Step 5 ─► Step 6 ─► Step 7 ─► Step 8
         Step 4 ─────┘
```

Steps 1+2 are independent → parallelize.
Steps 3+4 depend on 1+2 but are independent of each other → parallelize.
Step 5 depends on 3+4.
Steps 6-8 are sequential after 5.
