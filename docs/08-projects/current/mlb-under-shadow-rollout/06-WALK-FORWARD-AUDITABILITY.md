# Walk-forward auditability — `mlb_predictions.walk_forward_results`

**Status:** PROPOSAL — not implemented. Decision deferred.
**Surfaced by:** Agent 1 (`02-AGENT-FINDINGS.md`), promoted to a project-level requirement in `03-DECISIONS.md` D6.
**Trigger:** The walk-forward UNDER claims that disabled `MLB_UNDER_ENABLED` (52.4% / 48.1% / -6.8% ROI) cannot be reproduced from BigQuery or from disk. They exist only in narrative.

---

## The problem in one paragraph

`scripts/mlb/training/walk_forward_simulation.py` writes its results to `--output-dir results/mlb_walkforward_2025/` as CSV + JSON. No such directory exists in the current working tree, and `results/` is not gitignored (we'd see them if they were ever committed). The numbers that triggered the original UNDER disable are therefore unauditable — there is no row in BigQuery, no file on disk, no commit history showing the simulation that produced them. Any future strategic decision about MLB direction filters, training cadence, or model loss function will hit the same wall. Thread 2's fix: make walk-forward output a first-class BQ artifact partitioned by `game_date`, queryable like `prediction_accuracy`.

## Scope

Every walk-forward run writes one row per (simulation, game_date, pitcher_lookup) to `mlb_predictions.walk_forward_results`. Same shape as `prediction_accuracy`, plus simulation-identity columns so multiple simulations coexist without colliding.

## Schema proposal

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_predictions.walk_forward_results` (
  -- Simulation identity (every row tagged so runs don't collide)
  simulation_id STRING NOT NULL,
    -- Convention: '{model_type}_w{window}_r{retrain_interval}_{strategy}_{loss}_{run_timestamp}'
    -- Example: 'catboost_w56_r14_fixed_rmse_2026-05-12T19:34:00Z'
  simulation_date TIMESTAMP NOT NULL,       -- When the run executed (for run-level ordering)

  -- Pick identity (mirrors prediction_accuracy keys)
  game_date DATE NOT NULL,                  -- Partition key
  pitcher_lookup STRING,
  team_abbr STRING,
  opponent_team_abbr STRING,
  venue STRING,

  -- Model identity
  system_id STRING,                         -- e.g. 'catboost_v2' (matches prediction_accuracy.system_id)
  model_version STRING,                     -- arbitrary tag from CLI
  model_type STRING,                        -- 'xgboost' | 'catboost'
  loss_function STRING,                     -- 'RMSE' | 'Quantile:alpha=0.5' (for Thread 1 A/B)
  feature_set_version STRING,               -- e.g. 'v4_36features' (anchor analysis when feature list changes)

  -- Simulation config (denormalized per row — keeps BQ scans single-table)
  model_window_days INT64,
  retrain_strategy STRING,                  -- 'fixed' | 'triggered'
  retrain_cadence_days INT64,
  filter_nan_predictions BOOL,
  simulation_config_json STRING,            -- Full kwargs JSON for full provenance (CLI args verbatim)

  -- Prediction snapshot
  recommendation STRING,                    -- 'OVER' | 'UNDER' (derived from predicted_over)
  predicted_strikeouts NUMERIC(5, 1),
  proba NUMERIC(5, 4),                      -- Classifier probability that pick wins
  edge NUMERIC(5, 2),                       -- ABS(proba - 0.5) * 10 in current script. Store raw.
  line_value NUMERIC(4, 1),

  -- Actual result
  actual_strikeouts INTEGER,
  prediction_correct BOOL,                  -- predicted_over == actual_over
  signed_error NUMERIC(5, 1),               -- predicted - actual (for bias direction)

  -- Game context (already collected by script)
  is_home BOOL,
  is_day_game BOOL,
  days_rest NUMERIC(4, 1),
  k_avg_last_5 NUMERIC(5, 2),               -- Optional — quick joins for archetype slicing
  season_k_per_9 NUMERIC(5, 2),

  -- Metadata
  graded_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY simulation_id, system_id
OPTIONS (
  require_partition_filter=TRUE,
  partition_expiration_days=365,
  description='Walk-forward simulation pick-level results. One row per (simulation_id, game_date, pitcher_lookup). '
              'Mirrors prediction_accuracy schema with simulation identity columns so multiple runs coexist. '
              'Replaces unauditable JSON/CSV output from scripts/mlb/training/walk_forward_simulation.py.'
);
```

### Why these specific extra columns

| Column | Why it matters |
|---|---|
| `simulation_id` | Two simulations can ship the same `game_date + pitcher_lookup` row with different edges/predictions. Without this, every join collides. |
| `loss_function` | Thread 1 (Quantile retrain) will produce A/B runs from the same script with only this flag flipped. Must be in the row to slice. |
| `feature_set_version` | Adding/removing features changes predictions but not script identity. Already a known gotcha — Session 444 removed 5 features mid-experiment. |
| `simulation_config_json` | Full kwargs serialized. Even when the explicit columns above miss a knob (e.g. `--trigger-threshold`), JSON catches it. Lets future agents reproduce by `python walk_forward_simulation.py {json}`. |
| `signed_error` | `predicted - actual`. Necessary to detect direction bias (Agent 3's RMSE diagnosis depends on it). Already trivially computable from collected fields. |

## Per-pick-once, not per-threshold

The current CSV layout writes one file per edge threshold, with the same pick duplicated across thresholds when its edge clears multiple. The right BQ shape is **one row per (simulation_id, game_date, pitcher_lookup), with `edge` as a column.** Queries filter `WHERE edge >= 0.75`. This is a script artifact, not a schema decision — drop it in the BQ write path.

## Write-path options

### (a) Live writes in `walk_forward_simulation.py`

Modify the existing save-results block (line ~649). After building the per-pick dicts from `all_results`, call `client.load_table_from_dataframe(picks_df, 'mlb_predictions.walk_forward_results', job_config=...)` instead of (or in addition to) `to_csv`. Build a `simulation_id` from CLI args at the top of `main()` and propagate.

**Pros:** Every future run lands in BQ automatically. No extra step.
**Cons:** Modifies a working script. Need careful idempotency (re-running the same simulation_id should overwrite, not duplicate).

**Idempotency pattern:** scoped DELETE before insert, keyed on `simulation_id` (same pattern as `_write_shadow_picks` in `best_bets_exporter.py`):

```python
client.query(f"""
DELETE FROM `nba-props-platform.mlb_predictions.walk_forward_results`
WHERE simulation_id = @sim_id
  AND game_date BETWEEN @start AND @end
""", job_config=...).result()
client.load_table_from_dataframe(picks_df, ...).result()
```

### (b) Post-hoc loader `bin/load_walk_forward_to_bq.py`

Read an output dir of CSVs, derive `simulation_id` from filenames, write to BQ.

**Pros:** Lets us ingest old runs if any CSVs are ever recovered. Decouples write path from simulation logic.
**Cons:** Two-step workflow. Inevitable drift between "simulation finished" and "BQ has the data."

### Recommended

**Ship (a) for going-forward runs. Skip (b) for now** — no recoverable historical CSVs exist locally (verified: no `results/mlb_walkforward_*/` directory). If old simulation outputs surface later (e.g. on a different machine), build (b) then.

## Backfill what's still reproducible

Even without old CSVs, we can backfill historical walk-forward windows by re-running:

```bash
PYTHONPATH=. .venv/bin/python scripts/mlb/training/walk_forward_simulation.py \
  --start-date 2024-04-01 --end-date 2025-09-30 \
  --training-windows 56 \
  --edge-thresholds 0.75 \
  --retrain-interval 14 \
  --model-type catboost \
  --retrain-strategy fixed
```

Once the script writes to BQ, one re-run reproduces the 2024+2025 history. Estimated runtime: ~2-3 hours per (window, retrain cadence, model) tuple. The 4 windows × 2 models × 2 strategies grid from the original simulation: ~32 hours total. Probably run a curated subset overnight (~4-6 canonical configs).

## Sanity checks before adopting

- **Schema drift:** When `walk_forward_simulation.py` query changes (new features added/removed), bump `feature_set_version`. Existing rows are not invalidated — queries can filter `WHERE feature_set_version = 'v4_36features'`.
- **Cost:** ~5,000 picks/day × 180 days × ~10 typical configs ≈ 9M rows/run-grid. Partition pruning + clustering on `simulation_id` keeps query costs trivial. Storage cost negligible (rounding error on the BQ bill).
- **Pre-commit hook (optional, future):** validate that any new field added to the in-memory pick dict (line 408-429) is also added to the BQ schema. Same pattern as `validate_schema_fields.py` at the repo root.

## What this unblocks

- Re-verifying the original UNDER walk-forward claims (52.4% / 48.1%) against the same BQ table that grades live picks
- Thread 1 (Quantile-loss feasibility) — A/B query becomes `WHERE loss_function IN ('RMSE', 'Quantile:alpha=0.5') GROUP BY loss_function`
- Day 30 ranker discovery (`05-RANKING-REDESIGN.md`) — can join shadow UNDER picks with the historical walk-forward training set for cross-validation
- Every future "what would have happened if we'd trained with window X" question

## What this does NOT do

- Doesn't speak to whether the original 48.1% UNDER claim was correct — just makes it re-checkable next time
- Doesn't change `walk_forward_simulation.py`'s logic, feature list, or model definitions
- Doesn't address Thread 3 (`model_raw_predictions`) — that captures live predictions; this captures backtests. Different table, different purpose. They complement each other.

## Open questions deferred

1. **Should the table include the held-out training row counts per retrain?** `retrain_log` is currently a separate CSV. Could go into a sibling `walk_forward_retrain_log` table or be denormalized as `train_samples` on every pick row.
2. **Edge proxy or true edge?** Current script computes `edge = ABS(proba - 0.5) * 10`. Live MLB uses `predicted_strikeouts - line_value`. Store both — the proxy is the script's actual selection criterion; the true edge is what comparisons against `prediction_accuracy` need.
3. **Do we need a `simulation_metadata` table?** One row per simulation_id with config, runtime, success/failure. Useful for cleanup ("delete all failed runs"). Probably YAGNI until we have >100 simulations.

## Effort estimate if this ships

- Schema file at `schemas/bigquery/mlb_predictions/walk_forward_results.sql` — 30 min
- Modify `walk_forward_simulation.py` to build `simulation_id`, dedup via scoped DELETE, write via `load_table_from_dataframe` — ~3h including testing
- One canonical re-run against the live BQ table to bootstrap (overnight, no human time)
- Documentation in `docs/02-operations/useful-queries.md` for the standard walk-forward inspection queries — 30 min

**Total active dev time: ~4h. Calendar: 1 day including the overnight backfill run.**

## Related

- `03-DECISIONS.md` D6 — surfaced this requirement
- Thread 3 (`model_raw_predictions`) — `docs/08-projects/current/mlb-improvements-2026-05/PLAN.md:90` — sibling auditability work for live predictions
- NBA precedent: none — `ml/experiments/season_walkforward.py` reads BQ but doesn't write back. This would be the first walk-forward-to-BQ table in the repo.
