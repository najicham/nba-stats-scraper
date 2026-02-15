# Session 254 Handoff — Signal Discovery Framework Production Integration

**Date:** 2026-02-14
**Model:** Claude Opus 4.6
**Status:** Code complete. NOT deployed. BQ tables not yet created.

---

## What Was Done

Built the complete Signal Discovery Framework production integration in two commits:

### Commit 1: `25c8c254` — Signal framework + Phase 6 integration
- `ml/signals/` — 6 signal classes (model_health gate, high_edge, 3pt_bounce, minutes_surge, dual_agree, pace_up)
- `ml/signals/registry.py` — signal registration with `build_default_registry()`
- `ml/signals/aggregator.py` — `BestBetsAggregator` scores picks by edge * signal overlap multiplier, top 5/day
- `ml/experiments/signal_backtest.py` — backtest harness across 4 eval windows
- `data_processors/publishing/signal_best_bets_exporter.py` — Phase 6 exporter (BQ + GCS)
- `orchestration/cloud_functions/phase5_to_phase6/main.py` — added `signal-best-bets` to `TONIGHT_EXPORT_TYPES`
- `orchestration/cloud_functions/post_grading_export/main.py` — backfills actuals into `signal_best_bets_picks`
- `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql` — BQ schema
- `docs/08-projects/current/signal-discovery-framework/` — full documentation

### Commit 2: `f61423a4` — Signal annotations on all picks + Signal Picks subset
- `ml/signals/supplemental_data.py` — shared BQ queries (DRY between exporter and annotator)
- `data_processors/publishing/signal_annotator.py` — evaluates signals on ALL predictions, writes `pick_signal_tags`, bridges top 5 into `current_subset_picks` as "Signal Picks" subset
- `data_processors/publishing/all_subsets_picks_exporter.py` — LEFT JOINs `pick_signal_tags`, every pick in every subset now has `"signals": [...]` in the JSON API
- `shared/config/subset_public_names.py` — added `signal_picks` (id=26, "Signal Picks")
- `schemas/bigquery/nba_predictions/pick_signal_tags.sql` — BQ schema
- `schemas/bigquery/nba_predictions/v_signal_performance.sql` — per-signal performance view
- Fixed: `signal_best_bets_exporter.py` now uses `load_table_from_json` (batch load) instead of `insert_rows_json` (streaming) to avoid 90-min DML buffer violation

---

## Architecture Summary

**Two-layer design:**

1. **`pick_signal_tags`** — signal annotations on ALL predictions at the prediction grain. Every pick in every subset gets signal badges via LEFT JOIN.

2. **"Signal Picks" subset** (id=26) — aggregator's top 5 picks bridged into `current_subset_picks`. Graded automatically by existing `SubsetGradingProcessor`. Appears in frontend.

**Data flow during `subset-picks` export:**
```
SubsetMaterializer → SignalAnnotator → AllSubsetsPicksExporter
                     ├── pick_signal_tags (all predictions)
                     └── current_subset_picks (top 5 as Signal Picks)
```

**Model health gate:** If champion 7d HR < 52.4%, Signal Picks produces 0 picks. Would have prevented entire W4 crash.

---

## What Is NOT Done — Pre-Production Checklist

**These must be completed before this goes live:**

1. **Create BQ tables** (run the DDL in BigQuery console or via `bq query`):
   ```bash
   bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/pick_signal_tags.sql
   bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/signal_best_bets_picks.sql
   bq query --use_legacy_sql=false < schemas/bigquery/nba_predictions/v_signal_performance.sql
   ```

2. **Add `signal_picks` to `dynamic_subset_definitions`:**
   ```sql
   INSERT INTO `nba-props-platform.nba_predictions.dynamic_subset_definitions`
   (subset_id, subset_name, system_id, is_active, min_edge, top_n, use_ranking)
   VALUES ('signal_picks', 'Signal Picks', 'catboost_v9', TRUE, 0, 5, TRUE);
   ```
   Note: The materializer skips this subset (it's populated by SignalAnnotator's bridge). The definition is needed so the performance view and grading processor recognize it.

3. **Push to main** — triggers Cloud Build auto-deploy for Cloud Run services.

4. **Redeploy Cloud Functions:**
   - `post-grading-export` (added signal backfill)
   - `phase5-to-phase6-orchestrator` (added `signal-best-bets` to export types)

5. **End-to-end test:**
   ```bash
   # Dry-run the annotator
   PYTHONPATH=. python -c "
   from data_processors.publishing.signal_annotator import SignalAnnotator
   a = SignalAnnotator()
   result = a.annotate('2026-02-14')
   print(result)
   "
   ```

6. **Verify after games:** Check `signal_best_bets_picks` has actuals backfilled, check `v_signal_performance` view returns data.

---

## Signal Backtest Results (for context)

| Signal | W2 HR | W3 HR | W4 HR | AVG |
|--------|-------|-------|-------|-----|
| `high_edge` | 82.2% (N=90) | 74.0% (N=50) | 43.9% (N=41) | 66.7% |
| `3pt_bounce` | 85.7% (N=7) | 72.2% (N=18) | 66.7% (N=3) | 74.9% |
| `minutes_surge` | 61.2% (N=98) | 51.2% (N=80) | 48.8% (N=80) | 53.7% |
| **high_edge+minutes_surge overlap** | | | | **87.5%** |
| **Baseline (V9 edge 3+)** | | | | **59.1%** |

W4 crashed across all signals due to model decay (37+ days stale). Model health gate would have blocked W4 entirely.

---

## Exploring New Signals (Next Session)

The framework is designed for easy signal exploration. To test a new signal:

1. **Create signal class** in `ml/signals/` extending `BaseSignal`:
   ```python
   class MySignal(BaseSignal):
       tag = "my_signal"
       description = "Description"

       def evaluate(self, prediction, features=None, supplemental=None):
           # Return SignalResult(qualifies=True/False, confidence=0-1, source_tag=self.tag)
   ```

2. **Add to registry** in `ml/signals/registry.py` inside `build_default_registry()`

3. **If supplemental data needed**, add query to `ml/signals/supplemental_data.py` and wire it through the backtest's `evaluate_signals()` in `ml/experiments/signal_backtest.py`

4. **Run backtest:**
   ```bash
   PYTHONPATH=. python ml/experiments/signal_backtest.py --save
   ```

### Signal Ideas to Explore

| Idea | Data Source | Hypothesis |
|------|-----------|------------|
| `home_dog` | Schedule + odds | Home underdogs with high edge outperform |
| `rest_advantage` | Schedule (days between games) | Players on 2+ days rest vs B2B opponents |
| `revenge_game` | Schedule history | Players facing former teams |
| `blowout_recovery` | `player_game_summary` | Players who had very low minutes in blowout, OVER next game |
| `hot_streak` | `player_game_summary` | Players who beat their line 3+ consecutive games |
| `cold_snap` | `player_game_summary` | Players who missed their line 3+ games, regression to mean (OVER) |
| `injury_opportunity` | `nbac_injury_report` | Teammate OUT → role player minutes/usage increase |

### Key Supplemental Data Available

- `prediction_accuracy` — historical outcomes per player/game
- `player_game_summary` — points, minutes, 3PT, rebounds, assists per game
- `ml_feature_store_v2` — 37 features including pace, matchup history, team context
- `nbac_injury_report` — injury status per player
- `nbac_schedule` — schedule, home/away, rest days
- `odds_api_*` — betting lines, moneylines, totals

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `ml/signals/base_signal.py` | `BaseSignal` abstract class, `SignalResult` dataclass |
| `ml/signals/registry.py` | `SignalRegistry` + `build_default_registry()` |
| `ml/signals/aggregator.py` | `BestBetsAggregator` — top 5 picks/day |
| `ml/signals/supplemental_data.py` | Shared BQ queries for 3PT, minutes, model health |
| `ml/signals/model_health.py` | Gate signal: blocks when HR < 52.4% |
| `ml/signals/high_edge.py` | Edge >= 5.0 |
| `ml/signals/three_pt_bounce.py` | Cold 3PT shooter + OVER |
| `ml/signals/minutes_surge.py` | Minutes last 3 > season avg + 3 |
| `ml/experiments/signal_backtest.py` | 4-window backtest harness |
| `data_processors/publishing/signal_annotator.py` | Annotates all picks + bridges to subsets |
| `data_processors/publishing/signal_best_bets_exporter.py` | Curated top 5 → BQ + GCS |
| `docs/08-projects/current/signal-discovery-framework/` | Full project docs |
