# Best Bets V2 Phase A: Multi-Source Candidate Generation

**Session:** 307
**Status:** IMPLEMENTED + DEPLOYED
**Date:** 2026-02-19

---

## What Phase A Does

Best bets now queries ALL CatBoost model families (not just champion V9) and picks the highest-edge prediction per player. On weak V9 days (like Feb 19 with avg edge 0.8), other models surface actionable picks.

## How Best Bets Are Determined (Complete Flow)

```
1. CANDIDATE GENERATION (supplemental_data.py, multi_model=True)
   └─ Query all CatBoost families via build_system_id_sql_filter()
   └─ Dedup: ROW_NUMBER() OVER (PARTITION BY player ORDER BY ABS(edge) DESC)
   └─ Track: source_model_id, n_models_eligible, champion_edge, direction_conflict

2. SUPPLEMENTAL DATA (same query)
   └─ 3PT stats, minutes, usage, FG%, rest days, B2B status
   └─ Streak data (from champion model — most grading history)
   └─ V12 predictions (for cross-model consensus)
   └─ Prop line delta (current vs previous game line)
   └─ Multi-book line std (cross-book disagreement)

3. SIGNAL EVALUATION (registry.py → 17 active signals)
   └─ Each signal returns: qualifies=bool, source_tag=str
   └─ Signals are ANNOTATIONS, not selection criteria (Session 297)
   └─ model_health always counts as 1 signal if HR data exists

4. NEGATIVE FILTERS (aggregator.py, applied in order)
   1. Player blacklist: <40% HR on 8+ picks → skip
   2. Edge floor: edge < 5.0 → skip (57% HR below, 71% above)
   3. UNDER edge 7+ block → skip (40.7% HR)
   4. Avoid familiar: 6+ games vs opponent → skip
   5. Feature quality floor: quality < 85 → skip (24% HR)
   6. Bench UNDER block: UNDER + line < 12 → skip (35.1% HR)
   7. Line jumped UNDER: delta >= 2.0 → skip (38.2% HR)
   8. Line dropped UNDER: delta <= -2.0 → skip (35.2% HR)
   9. Neg +/- streak UNDER: 3+ negative games → skip (13.1% HR)
   10. MIN_SIGNAL_COUNT < 2 → skip (need model_health + 1 real signal)
   11. ANTI_PATTERN combo match → skip

5. RANKING
   └─ Sort by edge descending (edge IS the primary signal)
   └─ Natural sizing: no hard cap on picks (Session 298)

6. ANNOTATION
   └─ Attach signal tags, pick angles, combo matches
   └─ Cross-model consensus data for context

7. EXPORT
   └─ BQ: signal_best_bets_picks (with 5 new attribution columns)
   └─ GCS: v1/signal-best-bets/{date}.json + latest.json
```

## Schema Changes

5 new nullable columns on `signal_best_bets_picks`:
- `source_model_id` — which model's prediction won dedup
- `source_model_family` — family classification (v9_mae, v12_q43, etc.)
- `n_models_eligible` — how many models had edge 5+ for this player
- `champion_edge` — V9 MAE edge for comparison
- `direction_conflict` — True if models disagreed on direction

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/supplemental_data.py` | `multi_model=True` parameter, multi-source CTE |
| `ml/signals/aggregator.py` | `ALGORITHM_VERSION = 'v307_multi_source'` |
| `data_processors/publishing/signal_best_bets_exporter.py` | Passes multi_model=True, writes new columns |
| `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql` | 5 new columns |
| `.claude/skills/best-bets-config/SKILL.md` | New diagnostic skill |

## Monitoring System Architecture

| Table | Purpose | Populated By | Frequency |
|-------|---------|-------------|-----------|
| `signal_best_bets_picks` | Pick provenance (WHY each pick was made) | SignalBestBetsExporter | Daily |
| `pick_signal_tags` | Signal annotations on ALL predictions | SignalAnnotator | Daily |
| `signal_health_daily` | Per-signal HOT/COLD/NORMAL regime | post_grading_export CF | After grading |
| `model_performance_daily` | Per-model decay state machine | post_grading_export CF | After grading |
| `signal_combo_registry` | 13 validated signal combos | Manual seed | Static |
| `prediction_accuracy` | Grading master table (419K+ records) | Phase 5B grading | After games |

## New Model / New Signal Checklists

See `/best-bets-config` skill Section 6 for full checklists.

**New Model:** Pattern in MODEL_FAMILIES → subset definitions → codenames → grading pipeline → auto-discovered by `discover_models()`.

**New Signal:** Class in ml/signals/ → registered in registry.py → documented in CLAUDE.md → appearing in signal_health_daily → firing in pick_signal_tags → combo participation evaluated.
