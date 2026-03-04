# How Top Picks Are Created Today

## The Full Pipeline

```
Phase 5: Worker generates predictions
  → 16 models × ~120 players = ~1,800 raw predictions per game day

Phase 6: Signal Best Bets Exporter
  │
  ├─ 1. supplemental_data.py: Query predictions + supplemental data
  │     │
  │     ├─ build_system_id_sql_filter(): Only include known model families
  │     │   (catboost v9/v12/v13/v15/v16, lgbm, xgb patterns)
  │     │   This excludes zombie models (ensemble_v1, moving_average, etc.)
  │     │
  │     ├─ disabled_models CTE: Exclude registry-disabled + legacy hardcoded models
  │     │
  │     ├─ model_hr CTE: Get 14d rolling HR and 21d best-bets HR per model
  │     │
  │     ├─ Per-player selection (ROW_NUMBER):
  │     │   PARTITION BY player_lookup, game_id
  │     │   ORDER BY ABS(edge) * model_hr_weight DESC
  │     │   → Picks ONE prediction per player (highest HR-weighted edge wins)
  │     │
  │     └─ LEFT JOINs supplemental data (stats, streaks, book stats, line movement)
  │         → ~76 candidates (one per player with active predictions)
  │
  ├─ 2. aggregator.py: Apply filter stack
  │     │
  │     ├─ Edge floor: ABS(edge) >= 3.0
  │     │   → Reduces ~76 to ~16 candidates (only ~20% have edge 3+)
  │     │
  │     ├─ 30+ negative filters (applied sequentially, first match rejects):
  │     │   ├─ Player blacklist: <40% HR on 8+ edge-3+ picks
  │     │   ├─ Model-direction affinity: Blocks proven bad model+direction+edge combos
  │     │   ├─ AWAY block: v12_noveg/v9 family AWAY games (43-48% HR)
  │     │   ├─ OVER edge floor: OVER picks need edge >= 5.0 (edge 3-5 OVER = 25% HR)
  │     │   ├─ UNDER edge 7+ block: V9 UNDER at edge 7+ = 34% HR
  │     │   ├─ Familiar matchup: 6+ games vs same opponent
  │     │   ├─ Feature quality floor: quality < 85 = 24% HR
  │     │   ├─ Bench UNDER: UNDER + line < 12 = 35% HR
  │     │   ├─ Line jumped/dropped UNDER: 2+ point line movement
  │     │   ├─ Line dropped OVER: 2+ point line drop + OVER = 39% HR
  │     │   ├─ Star UNDER: season avg >= 25 (unless teammate injured)
  │     │   ├─ Opponent UNDER block: MIN/MEM/MIL opponents
  │     │   ├─ Opponent depleted UNDER: 3+ opponent stars out
  │     │   ├─ SC=3 OVER edge restriction: SC=3 + OVER needs edge >= 7
  │     │   └─ ... and more
  │     │
  │     ├─ Signal annotation: Tag each surviving pick with matching signals
  │     │   → 20 active signals evaluated per pick
  │     │
  │     ├─ Signal count floor: signal_count >= 3
  │     │   (bypass if edge >= 7.0 — extreme edge gets through)
  │     │
  │     ├─ Signal density: base-only signals (high_edge + edge_spread_optimal only)
  │     │   → Skip unless edge >= 7.0
  │     │
  │     └─ Final ranking: ORDER BY ABS(edge) DESC
  │         → The highest-edge surviving picks become best bets
  │
  └─ 3. Write to BQ + GCS JSON
```

## Key Design Decisions

### Per-Player Selection: `ABS(edge) * model_hr_weight`

The system picks ONE prediction per player across all models. The selection criterion is:

```sql
ORDER BY ABS(edge) * model_hr_weight DESC
```

Where `model_hr_weight` is:
```
LEAST(1.0, COALESCE(
  best_bets_hr_21d (if N >= 8),
  raw_hr_14d (if N >= 10),
  50.0  -- default for new models
) / 55.0)
```

**This means:**
- A model with 55%+ HR gets weight = 1.0 (no penalty)
- A model with 50% HR gets weight = 0.91
- A model with 44% HR gets weight = 0.80
- New models with <10 graded picks default to 50% → weight 0.91

**The weight is a multiplier on edge, not a standalone score.** A model with edge=4 and weight=1.0 (score=4.0) loses to a model with edge=6 and weight=0.80 (score=4.8). Edge dominates.

### Signal Count as Quality Gate

Signals are ANNOTATIONS, not selection criteria. They fire based on supplemental data patterns (3PT bounce, line movement, rest advantage, etc.). A pick's signal count measures how many confirming signals it has.

- MIN_SIGNAL_COUNT = 3 (raised from 2 in Session 370)
- Edge >= 7.0 bypasses signal density check (extreme edge gets through)
- Signal count does NOT affect ranking — all picks ranked by edge only

### Confidence Score

Currently set to 9.999 for all CatBoost models. It's a vestigial field from early model architectures. **Not used in any selection or filtering logic.** Could be repurposed.

## Files

| File | Role |
|------|------|
| `ml/signals/supplemental_data.py` | Query builder — predictions + supplements + per-player selection |
| `ml/signals/aggregator.py` | Filter stack + signal annotation + ranking |
| `ml/signals/signal_annotator.py` | Signal evaluation logic |
| `ml/signals/player_blacklist.py` | Per-player season HR computation |
| `data_processors/publishing/signal_best_bets_exporter.py` | Orchestrates the export flow |
| `shared/config/cross_model_subsets.py` | Model family classification |
| `shared/config/model_selection.py` | Champion model config |
