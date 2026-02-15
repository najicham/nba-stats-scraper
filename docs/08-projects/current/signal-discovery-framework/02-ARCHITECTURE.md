# Signal Discovery Framework — Architecture

**Session:** 253-254
**Date:** 2026-02-14

## Pipeline Integration

Signals are computed in Phase 6 during the export step. No new Cloud Run service required.

```
Phase 5 (predictions) → Phase 5→6 Orchestrator → Phase 6 Export
                                                    ├── tonight        (existing)
                                                    ├── best-bets      (existing)
                                                    ├── subset-picks   (existing)
                                                    ├── daily-signals  (existing)
                                                    ├── signal-best-bets (NEW) ← signals computed here
                                                    └── ...other exports
```

**Why Phase 6:**
- Runs after Phase 5 predictions complete (all data available)
- Signal computation is filtering/tagging, not ML inference
- No new infrastructure needed — existing Cloud Function handles routing
- All data available: predictions in BQ, features in feature store, rolling stats via SQL

## Storage Design

### `signal_best_bets_picks` Table (Dedicated)

**Decision:** Signals stored in their own table, NOT added to `player_prop_predictions`.

| Field | Type | Purpose |
|-------|------|---------|
| `player_lookup` | STRING | Primary key |
| `game_id` | STRING | Primary key |
| `game_date` | DATE | Partition key |
| `system_id` | STRING | Model reference |
| `signal_tags` | ARRAY<STRING> | Qualifying signals |
| `signal_count` | INT64 | Number of signals |
| `composite_score` | NUMERIC | Aggregator ranking score |
| `rank` | INT64 | 1-based daily rank |
| `actual_points` | INT64 | Populated after grading |
| `prediction_correct` | BOOLEAN | Populated after grading |

**Rationale:**
- `player_prop_predictions` stays pure ML output
- Signals are business logic overlays — separate concern
- Append-only writes avoid 90-min DML locks
- Can iterate on signals without touching prediction table

**Schema:** `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql`

## Signal Roster

### Production Signals

| Signal | Type | Class | File |
|--------|------|-------|------|
| `model_health` | **GATE** | `ModelHealthSignal` | `ml/signals/model_health.py` |
| `high_edge` | Pick signal | `HighEdgeSignal` | `ml/signals/high_edge.py` |
| `3pt_bounce` | Pick signal | `ThreePtBounceSignal` | `ml/signals/three_pt_bounce.py` |
| `minutes_surge` | Pick signal | `MinutesSurgeSignal` | `ml/signals/minutes_surge.py` |

### Deferred Signals

| Signal | Class | Reason |
|--------|-------|--------|
| `dual_agree` | `DualAgreeSignal` | V12 needs 30+ days of data |
| `consensus` | (not built) | Need independent models |
| `pace_up` | `PaceMismatchSignal` | 0 qualifying picks — thresholds too restrictive |

## Grading Integration

After games complete, the existing grading pipeline grades `prediction_accuracy`. The `post-grading-export` Cloud Function then:

1. Re-exports `picks/{date}.json` with actuals (existing behavior)
2. **NEW:** Updates `signal_best_bets_picks` with `actual_points` and `prediction_correct`

```sql
UPDATE signal_best_bets_picks sbp
SET actual_points = pa.actual_points,
    prediction_correct = pa.prediction_correct
FROM prediction_accuracy pa
WHERE sbp.player_lookup = pa.player_lookup
  AND sbp.game_id = pa.game_id
  AND sbp.game_date = pa.game_date
  AND pa.system_id = sbp.system_id
  AND sbp.game_date = @target_date
```

## GCS Export

Output path: `v1/signal-best-bets/{date}.json`

```json
{
  "date": "2026-02-14",
  "generated_at": "2026-02-14T18:30:00Z",
  "model_health": {
    "status": "healthy",
    "hit_rate_7d": 65.2,
    "graded_count": 45
  },
  "picks": [
    {
      "rank": 1,
      "player": "LeBron James",
      "player_lookup": "lebron_james",
      "team": "LAL",
      "opponent": "BOS",
      "prediction": 26.1,
      "line": 24.5,
      "direction": "OVER",
      "edge": 1.6,
      "signals": ["high_edge", "minutes_surge"],
      "signal_count": 2,
      "composite_score": 0.75,
      "actual": null,
      "result": null
    }
  ],
  "total_picks": 3,
  "signals_evaluated": ["model_health", "high_edge", "3pt_bounce", "minutes_surge"]
}
```

## Data Requirements Per Signal

| Signal | Data Source | Query |
|--------|-----------|-------|
| `model_health` | `prediction_accuracy` | Rolling 7d HR for edge 3+ picks |
| `high_edge` | Prediction dict | `abs(edge) >= 5.0` (no external data) |
| `3pt_bounce` | `player_game_summary` | Rolling 3PT%, season avg, std dev, attempts |
| `minutes_surge` | `player_game_summary` | Rolling minutes last 3, season avg |

## Key Files

| File | Purpose |
|------|---------|
| `ml/signals/model_health.py` | Model health gate signal |
| `ml/signals/registry.py` | Signal registration |
| `ml/signals/aggregator.py` | Top-5 pick selection |
| `data_processors/publishing/signal_best_bets_exporter.py` | Phase 6 exporter |
| `backfill_jobs/publishing/daily_export.py` | Export type routing |
| `orchestration/cloud_functions/phase5_to_phase6/main.py` | Tonight export types list |
| `orchestration/cloud_functions/post_grading_export/main.py` | Grading backfill |
| `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql` | BQ schema |
