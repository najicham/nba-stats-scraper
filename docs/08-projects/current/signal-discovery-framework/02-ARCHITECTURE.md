# Signal Discovery Framework — Architecture

**Sessions:** 253-254
**Date:** 2026-02-14
**Status:** Code complete, pending BQ table creation + deployment

## Pipeline Integration

Signals are computed in Phase 6 during the subset-picks export step. No new Cloud Run service required.

```
Phase 5 (predictions) → Phase 5→6 Orchestrator → Phase 6 Export
                                                    ├── subset-picks (existing)
                                                    │   ├── Step 1: SubsetMaterializer (existing)
                                                    │   ├── Step 2: SignalAnnotator (NEW)
                                                    │   │   ├── Evaluates signals on ALL predictions
                                                    │   │   ├── Writes pick_signal_tags (BQ)
                                                    │   │   └── Bridges top 5 → current_subset_picks as "Signal Picks"
                                                    │   └── Step 3: AllSubsetsPicksExporter (modified)
                                                    │       └── LEFT JOINs signal tags → every pick has signals
                                                    ├── signal-best-bets (NEW) — curated JSON to GCS
                                                    └── ...other exports
```

## Two-Layer Architecture

### Layer 1: Signal Annotations on ALL Picks — `pick_signal_tags`

Every active prediction gets signal-evaluated. Tags stored at the **prediction grain** (not subset grain):

```
(game_date, player_lookup, system_id) → signal_tags[], signal_count, model_health_status
```

Signals are a property of a prediction, not a subset. LeBron's `high_edge + minutes_surge` tags don't change whether he's in "Top Pick" or "All Picks". One evaluation per prediction, JOINed to any subset at export time.

**Schema:** `schemas/bigquery/nba_predictions/pick_signal_tags.sql`

### Layer 2: "Best Bets" Subset — Curated Top 5

The `BestBetsAggregator` selects top 5 picks (scored by edge * signal overlap multiplier) and bridges them into `current_subset_picks` as subset_id `best_bets` (public id=26, name="Best Bets").

- Graded automatically via existing `SubsetGradingProcessor`
- Appears in frontend alongside Top Pick, Top 3, etc.
- Same API endpoint (`picks/{date}.json`)
- Model health gate blocks all signal picks when HR < 52.4%

### `signal_best_bets_picks` Table — Detailed Signal Analysis

Parallel table with signal-specific columns (`signal_tags`, `composite_score`, `rank`) for debugging and iterating on the framework. Post-grading backfill updates actuals.

**Schema:** `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql`

## Signal Roster

### Production Signals

| Signal | Type | Class | File |
|--------|------|-------|------|
| `model_health` | **GATE** | `ModelHealthSignal` | `ml/signals/model_health.py` |
| `high_edge` | Pick signal | `HighEdgeSignal` | `ml/signals/high_edge.py` |
| `3pt_bounce` | Pick signal | `ThreePtBounceSignal` | `ml/signals/three_pt_bounce.py` |
| `minutes_surge` | Pick signal | `MinutesSurgeSignal` | `ml/signals/minutes_surge.py` |

### Deferred/Dropped Signals

| Signal | Status | Reason |
|--------|--------|--------|
| `dual_agree` | DEFER | V12 needs 30+ days of data |
| `consensus` | DEFER | Need independent models |
| `pace_up` | DROP | 0 qualifying picks — thresholds too restrictive |

### Adding a New Signal

1. Create `ml/signals/my_signal.py` extending `BaseSignal`
2. Add to `ml/signals/registry.py` `build_default_registry()`
3. If it needs supplemental data, add the query to `ml/signals/supplemental_data.py`
4. Run backtest: `PYTHONPATH=. python ml/experiments/signal_backtest.py`

## Performance Monitoring

**Per-signal hit rates:** `v_signal_performance` view (JOINs `pick_signal_tags` x `prediction_accuracy`)

```sql
SELECT * FROM nba_predictions.v_signal_performance;
-- signal_tag | total_picks | wins | hit_rate | roi | avg_edge
```

**Signal Picks W-L record:** Via existing `SubsetGradingProcessor` → `subset_grading_results`

## Data Flow

```
daily_export.py 'subset-picks' handler:
  1. SubsetMaterializer.materialize()           → current_subset_picks (existing subsets)
  2. SignalAnnotator.annotate()                  → pick_signal_tags (ALL predictions)
     └── _bridge_signal_picks()                  → current_subset_picks (Best Bets subset)
  3. AllSubsetsPicksExporter.export()            → picks/{date}.json (LEFT JOIN signal tags)

daily_export.py 'signal-best-bets' handler:
  4. SignalBestBetsExporter.export()              → signal_best_bets_picks (BQ) + GCS JSON

Post-grading:
  5. Re-export picks/{date}.json with actuals    (existing)
  6. Backfill signal_best_bets_picks actuals      (UPDATE, safe — batch load initial write)
```

## Key Files

| File | Purpose |
|------|---------|
| `ml/signals/` | Signal framework (base, registry, aggregator, all signals) |
| `ml/signals/supplemental_data.py` | Shared BQ queries for signal evaluation |
| `data_processors/publishing/signal_annotator.py` | Annotates ALL picks + bridges Signal Picks subset |
| `data_processors/publishing/signal_best_bets_exporter.py` | Curated top 5 → BQ + GCS |
| `data_processors/publishing/all_subsets_picks_exporter.py` | Modified: LEFT JOINs signal tags |
| `backfill_jobs/publishing/daily_export.py` | Wiring: materializer → annotator → exporter |
| `shared/config/subset_public_names.py` | Signal Picks = id 26 |
| `schemas/bigquery/nba_predictions/pick_signal_tags.sql` | Signal annotation table schema |
| `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql` | Detailed signal picks schema |
| `schemas/bigquery/nba_predictions/v_signal_performance.sql` | Per-signal performance view |

## Pre-Production Checklist

- [x] Create `pick_signal_tags` table in BigQuery (Session 255)
- [x] Create `signal_best_bets_picks` table in BigQuery (Session 255)
- [x] Create `v_signal_performance` view in BigQuery (Session 255)
- [x] Add `best_bets` row to `dynamic_subset_definitions` table (Session 255)
- [x] Backfill 35 dates of signal annotations (Session 255)
- [ ] Push to main (triggers Cloud Build auto-deploy)
- [ ] Redeploy Cloud Functions (post_grading_export, phase5_to_phase6)
- [ ] Trigger Phase 6 manually, verify signal badges in `picks/{date}.json`
- [ ] After games complete, verify grading backfill works
