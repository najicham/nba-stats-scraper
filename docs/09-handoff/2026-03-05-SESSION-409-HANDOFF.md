# Session 409 Handoff — Experiment Harness, Data Source Canary, Auto-Disable Docs

**Date:** 2026-03-05
**Type:** Infrastructure tooling, monitoring, documentation
**Commits:** (pending)

---

## What This Session Did

### 1. Experiment Harness (`ml/experiments/experiment_harness.py`)

Built a one-command multi-seed experiment runner that replaces the manual loop + manual JSON collection + manual analysis workflow.

**Before:** 30-45 min per experiment — manual bash loop, manual JSON parsing, manual stats.
**After:** Single command runs N seeds (experiment + baseline), aggregates, z-tests, auto-classifies.

```bash
PYTHONPATH=. python ml/experiments/experiment_harness.py \
  --name pace_v1 \
  --hypothesis "TeamRankings pace adds signal" \
  --experiment-features pace_v1
```

**Features:**
- Runs 5 experiment + 5 baseline seeds by default (configurable via `--seeds`)
- Aggregates mean/std of hr_edge3, hr_edge5, mae across seeds
- Two-proportion pooled z-test for statistical significance
- Auto-verdict: DEAD_END (<1pp), NOISE (1-2pp), PROMISING (2-3pp + N≥50), PROMOTE (≥3pp + significant)
- `--persist` flag writes to BQ `experiment_grid_results` table
- `--no-baseline` to skip baseline when already have one
- `--extra-args` pass-through to quick_retrain.py
- Uses existing `--machine-output` JSON contract — no changes to quick_retrain.py

**BQ Schema:** `schemas/bigquery/experiment_grid_results.json`

### 2. Auto-Disable BLOCKED Models — Already Done (Docs Updated)

Discovered that Session 389/405 already fully implemented `auto_disable_blocked_models()` in `decay_detection/main.py`. The full cascade exists: registry disable → prediction deactivation → signal picks removal → audit trail → Slack alert.

**Only change:** Updated CLAUDE.md — replaced "KNOWN GAP: BLOCKED models not auto-disabled" with accurate documentation about the auto-disable feature (requires `AUTO_DISABLE_ENABLED=true` env var, 3+ model safety floor).

### 3. Data Source Health Canary (`bin/monitoring/data_source_health_canary.py`)

Daily automated check that critical data sources are producing data.

```bash
PYTHONPATH=. python bin/monitoring/data_source_health_canary.py --dry-run
PYTHONPATH=. python bin/monitoring/data_source_health_canary.py --date 2026-03-04
```

**Sources monitored (7):**

| Source | Severity | Min Rows | Notes |
|--------|----------|----------|-------|
| numberfire_projections | CRITICAL | 50 | Only working projection source |
| teamrankings_team_stats | WARNING | 10 | Pace/efficiency for shadow signals |
| hashtagbasketball_dvp | WARNING | 10 | DVP signal |
| rotowire_lineups | WARNING | 20 | Expected lineups |
| vsin_betting_splits | WARNING | 3 | Sharp money signal |
| covers_referee_stats | WARNING | 3 | Referee tendencies |
| nba_tracking_stats | WARNING | 10 | Player tracking data |

**Status classification:**
- DEAD: 2+ consecutive days with 0 rows (baseline > 0)
- DEGRADING: >70% drop from 7-day baseline
- MISSING_TODAY: 0 today but baseline exists
- HEALTHY: within expected range

**Alerting:** CRITICAL → `#nba-alerts`, WARNING → `#canary-alerts`. Skips no-game days.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `ml/experiments/experiment_harness.py` | CREATE | Multi-seed experiment runner |
| `schemas/bigquery/experiment_grid_results.json` | CREATE | BQ schema for experiment results |
| `bin/monitoring/data_source_health_canary.py` | CREATE | Data source freshness monitor |
| `CLAUDE.md` | MODIFY | Replaced KNOWN GAP note with auto-disable docs |

### 4. Full Experiment Grid (Session 409b — Experiment Feature Infrastructure + Execution)

**Schema fix:** Dropped WIDE-format experiment table, recreated as LONG (player_lookup, game_date, experiment_id, feature_name, feature_value). Deleted orphaned `bin/experiment/populate_experiment_features.py`.

**3 new derived-feature experiments added to backfill script:**
- `derived_v1`: Player volatility (pts_std_last_5/10, form_ratio, over_rate_weighted)
- `interactions_v1`: Cross-feature products (fatigue*minutes, pace*usage, rest*b2b, spread*home)
- `line_history_v1`: Line-derived features (line_vs_avg, opening_vs_current, line_range)

**Combo experiment support:** `augment_experiment_features()` now accepts comma-separated IDs (e.g., `derived_v1,interactions_v1`).

**Data leakage fix:** Initial derived_v1 used `CURRENT ROW` in window functions (included target game's actual points). Fixed to `1 PRECEDING`. Caught by MAE dropping from 5.4 to 3.2 — obvious leakage signal.

**Full grid results (7 experiments, 5 seeds each, all persisted to BQ):**

| Experiment | Features | Delta HR(3+) | Verdict |
|-----------|----------|-------------|---------|
| tracking_v1 | 6 tracking stats | -1.3pp | DEAD_END |
| pace_v1 | 5 pace/efficiency | +8.2pp (N=12) | NOISE |
| interactions_v1 | 4 cross-feature products | +0.5pp | DEAD_END |
| line_history_v1 | 3 line-derived | -3.5pp | DEAD_END |
| derived_v1 | 4 volatility/form | +4.2pp (N=14) | NOISE |
| derived_all | All 11 derived | -0.6pp | DEAD_END |
| kitchen_sink | All 22 features | +3.2pp (N=12) | NOISE |

**Conclusion:** V12_noveg remains best. Adding features consistently hurts or is noise. Next opportunity: daily-varying features (projections_v1, sharp_money_v1) after ~30 days data accumulation (~Apr 5).

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `ml/experiments/experiment_harness.py` | CREATE | Multi-seed experiment runner |
| `schemas/bigquery/experiment_grid_results.json` | CREATE | BQ schema for experiment results |
| `bin/monitoring/data_source_health_canary.py` | CREATE | Data source freshness monitor |
| `bin/backfill_experiment_features.py` | MODIFY | Added derived_v1, interactions_v1, line_history_v1; fixed leakage in window functions |
| `bin/experiment/populate_experiment_features.py` | DELETE | Orphaned WIDE-format script |
| `ml/experiments/quick_retrain.py` | MODIFY | augment_experiment_features() supports comma-separated IDs |
| `docs/08-projects/current/model-evaluation-and-selection/EXPERIMENT-GRID.md` | MODIFY | Full Session 409 results |
| `CLAUDE.md` | MODIFY | Replaced KNOWN GAP note with auto-disable docs |

## What's NOT Done

1. **Cloud Scheduler job** — Data source canary should be scheduled (10 AM ET daily). Not yet configured.
2. **`AUTO_DISABLE_ENABLED=true`** — Verify this env var is set on the decay-detection Cloud Function. If not, auto-disable is still gated off.
3. **Daily experiment feature population** — No automated daily run of backfill for projections/sharp_money/dvp. Manual backfill when ready.

## Next Session Priorities

1. **~Apr 5:** Run projections_v1 + sharp_money_v1 experiments (30 days of daily data)
2. **Set up Cloud Scheduler** for data source canary
3. **Continue with P1 from Session 409 prompt** — investigate combo signals stopped firing Feb 11
