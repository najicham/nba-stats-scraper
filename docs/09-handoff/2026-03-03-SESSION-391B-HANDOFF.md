# Session 391B Handoff — Implementation & Deploy

**Date:** 2026-03-03 (late night)
**Status:** All code committed and pushed. Auto-deploy complete. Export working.

## What Was Done

### Fixes Deployed (all committed, pushed, auto-deployed)

1. **`ml/signals/supplemental_data.py`** — Defense-in-depth: disabled_models CTE excludes legacy models. Fixed BQ correlated subquery error by converting `NOT IN (SELECT ...)` → `LEFT JOIN + IS NULL` (2 occurrences, multi-model and single-model paths).

2. **`ml/signals/player_blacklist.py`** — Same BQ fix: CTE + LEFT JOIN instead of correlated subquery. Excludes disabled/blocked models from HR calculation.

3. **`ml/signals/aggregator.py`** — Filter dominance WARNING when any single filter rejects >50% of candidates.

4. **`predictions/worker/worker.py`** — `ENABLE_LEGACY_V9`/`ENABLE_LEGACY_V12` env vars (default `false`). New `_systems_initialized` sentinel. **NOT deployed to worker yet** — takes effect on next worker deploy.

5. **`orchestration/cloud_functions/decay_detection/main.py`** — Consecutive best bets drought detection. Escalates from single-day WARN to multi-day ALERT (red).

6. **`data_processors/publishing/signal_best_bets_exporter.py`** — Filter audit trail writes to `nba_predictions.best_bets_filter_audit` (BQ table created).

7. **`orchestration/cloud_functions/daily_health_check/main.py`** — Model registry consistency check (detects unregistered system_ids producing predictions).

8. **`ml/signals/registry.py`** — Disabled `volatile_scoring_over` signal (50% HR live, coin flip).

9. **`shared/config/cross_model_subsets.py`** — `discover_models()` filters disabled models via registry JOIN.

10. **`CLAUDE.md`** — Updated Cross-Model Monitoring (7→10 layers), added 3 new Common Issues.

### Commits (3 total)
```
a147dcc4 fix: Replace NOT IN subquery with LEFT JOIN in supplemental_data.py (BQ limit)
8847fc47 fix: Blacklist query — CTE+JOIN instead of correlated subquery (BQ limit)
b7b171ea fix: Legacy model selection drain — 0 best bets root cause + monitoring
```

### AWAY Block Assessment
- v12_noveg AWAY: 48.0% HR (N=125) — **block confirmed, no change**
- lgbm/v16: too sparse (N<15) — revisit in 5-7 days

## Current State

### Export Results (Mar 3)
- **16 candidates** (was 0 before fix — legacy models no longer dominate selection)
- **0 picks pass filters** — all 16 legitimately filtered:
  - 8 blacklist, 3 away_noveg, 2 over_edge_floor, 1 line_jumped, 1 signal_count, 1 star_under
- **Blacklist is 113** — this is NOT inflated by legacy models (113 with and without exclusion). It's the natural count of players with <40% HR across enabled models.

### Key Discovery: BQ Correlated Subquery Limitation
`NOT IN (SELECT model_id FROM cte_name)` fails in BigQuery even when referencing a CTE. Must use `LEFT JOIN cte_name ON ... WHERE ... IS NULL` pattern instead. This bit us twice (supplemental_data.py and player_blacklist.py).

### Key Discovery: Export Path
Signal-best-bets export runs via `phase6-export` CF → `backfill_jobs/publishing/daily_export.py` → `SignalBestBetsExporter`, **NOT** the prediction-coordinator. The coordinator handles batch orchestration only. Code in `ml/signals/` and `data_processors/publishing/` must deploy via Cloud Build auto-deploy (push to main), not `deploy-service.sh prediction-coordinator`.

## What's NOT Done

1. **Worker deploy** — `ENABLE_LEGACY_V9`/`ENABLE_LEGACY_V12` code is committed but worker hasn't been redeployed. Legacy models still producing ~200 wasted predictions/day. Will auto-disable on next worker deploy.

2. **Deployment drift check** — Was interrupted. Run `./bin/check-deployment-drift.sh --verbose`.

3. **Blacklist investigation** — 113/327 players (34.6%) blacklisted is very high. May need to adjust `min_picks` threshold or add recency weighting. Currently uses full season data — early-season poor performance permanently blacklists players who improved.

4. **Filter audit backfill** — `best_bets_filter_audit` table is empty, will populate on next export runs.

5. **Tomorrow's export** — Mar 4 has 6 games. The pipeline should generate picks naturally now that legacy model drain is fixed. Monitor to confirm.

## Next Session Priorities

1. **Verify Mar 4 picks** — Check if tomorrow produces non-zero best bets picks
2. **Blacklist analysis** — Investigate if 113 is too aggressive (recency bias, seasonal drift)
3. **Fleet ramp-up monitoring** — Which models reach N=50 governance gate first?
4. **Signal count coverage** — Only 4/55 edge 3+ picks had SC≥3 — structurally limited
