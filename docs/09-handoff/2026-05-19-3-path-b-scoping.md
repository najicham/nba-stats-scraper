# Session Handoff — 2026-05-19-3 — Path B scoping (MLB binary side-model)

**Predecessor:** [`2026-05-19-2-path-a-closeout.md`](2026-05-19-2-path-a-closeout.md) — NBA grading audit closed, Path B left as the only open strategic thread.

This session was a single-deliverable scoping pass. No code shipped. The next session executes from the spec.

## TL;DR

- **Path B (MLB binary side-model)** is now scoped end-to-end. Spec lives at [`docs/08-projects/current/mlb-sidemodel/SCOPING.md`](../08-projects/current/mlb-sidemodel/SCOPING.md).
- **Graded data verified**: 753 picks (Apr 1 → May 18, 2026), 383W/370L = **50.86% raw HR**. Class balance is clean. N is small but workable for logistic regression or a shallow LightGBM.
- **Feature inventory done**: `pitcher_loader.load_batch_features` serves ~30 features (rolling K, season, Statcast rolling, line-derived, FanGraphs advanced, matchup/workload). The 5/18-3 spec mentioned `weather` + `batter_k_rate` — **neither is served today**. First side-model uses only what the loader already produces. No new upstream pipelines.
- **Smallest shippable thing identified**: one BQ DDL (add `p_sidemodel` + `sidemodel_version` columns to `pitcher_strikeouts`), a new `predictions/mlb/sidemodel/binary_v1.py` loader behind an unset `MLB_SIDEMODEL_PATH` env var (no-op until artifact ships), and a CF analysis script that runs once N≥100 shadow rows have been graded. **No filter/exporter changes in slice 1** — `p_sidemodel` is written-through to BQ only.
- **Training pipeline sketched but not executed**: per-date loop over `load_batch_function` to reconstruct point-in-time features, chronological 75/25 split, logistic regression head-to-head with a small LightGBM, 5 governance gates (Brier improvement ≥0.01, AUC ≥0.55, OVER/UNDER stability, calibration sanity).

## What changed (no commits)

This session produced one document. Nothing was committed; nothing was deployed.

| File | What |
|---|---|
| `docs/08-projects/current/mlb-sidemodel/SCOPING.md` | Full spec — data verification, feature inventory, smallest-shippable plan, training pipeline, governance gates, promotion criterion |

## Data verification (BQ queries actually run)

```sql
-- Graded pick count for the regressor since the V2-regressor-only window opened
SELECT MIN(game_date), MAX(game_date), COUNT(*),
       COUNTIF(prediction_correct) AS wins,
       COUNTIF(NOT prediction_correct) AS losses,
       COUNTIF(is_voided) AS voided
FROM `nba-props-platform.mlb_predictions.prediction_accuracy`
WHERE game_date BETWEEN '2026-03-01' AND '2026-05-19'
  AND system_id = 'catboost_v2_regressor'
  AND has_prop_line = TRUE
  AND prediction_correct IS NOT NULL
  AND recommendation IN ('OVER','UNDER');
-- 2026-04-01 → 2026-05-18, 753 graded, 383W/370L, 0 voided
```

```sql
-- Direction split
SELECT recommendation, COUNT(*),
       ROUND(AVG(CAST(prediction_correct AS INT64)) * 100, 1) AS hr_pct,
       ROUND(AVG(edge), 2) AS avg_edge
FROM `nba-props-platform.mlb_predictions.prediction_accuracy`
WHERE game_date BETWEEN '2026-03-01' AND '2026-05-19'
  AND system_id = 'catboost_v2_regressor'
  AND has_prop_line = TRUE
  AND prediction_correct IS NOT NULL
  AND recommendation IN ('OVER','UNDER')
GROUP BY 1;
-- OVER 482 @ 49.6% HR, avg edge +0.51
-- UNDER 271 @ 53.1% HR, avg edge -0.38
```

The 5/18-3 spec said 729 picks; today's count is 753. That handoff was written before the most recent grading run — no real discrepancy.

## Key findings from the scoping pass

### Features the spec asked for but `pitcher_loader` doesn't serve
- **Weather** — `mlb_raw.mlb_weather` is operational (since 2026-05-17 per MEMORY) but is **not joined in `load_batch_features`**. Plumbing work, out of scope for v1.
- **Batter-level `batter_k_rate`** — would require `mlb_raw.mlb_lineup_batters` (spotty, 8/14 days) plus `lineup_k_analysis` (table empty per MEMORY entry 2026-05-13). Skip for v1.
- **`opponent_k_rate`** — already covered by `opponent_team_k_rate`.

### Integration seam in the worker
`predictions/mlb/worker.py:130-200` is where each predictor is initialized at startup. Side-model loads there if `MLB_SIDEMODEL_PATH` is set. The prediction row build at `worker.py:905` attaches `p_sidemodel` + `sidemodel_version` to the BQ insert dict. BB exporter (`ml/signals/mlb/best_bets_exporter.py`) is **untouched** in slice 1 — write-through to BQ only.

### Why the predictor's existing `p_over` isn't persisted
`mlb_predictions.pitcher_strikeouts` has `confidence` (which is `abs(edge) * 35` clamped to 100) but no `p_over` column. Today's sigmoid p_over is derived in-memory by the exporter from `edge` at signal time. Side-model needs its own dedicated column — there's no existing slot to repurpose.

### The training-time data reconstruction trick
`load_batch_features(game_date, pitcher_lookups)` filters `pgs.game_date < @game_date` and picks the most recent row per pitcher. That's exactly the point-in-time feature snapshot a prediction would have used. Looping over the ~49 graded dates and calling this function once per date with that day's pitcher list reconstructs the training set at the exact same feature contract the predictor uses. ~4-6 min total runtime.

## First message for the next session

```
Read docs/09-handoff/2026-05-19-3-path-b-scoping.md and the linked SCOPING.md.

Execute Path B slice 1 (shadow-only, no pick generation changes). Order:

1. BQ DDL: add p_sidemodel FLOAT NULLABLE and sidemodel_version STRING NULLABLE
   to `nba-props-platform.mlb_predictions.pitcher_strikeouts`. Single ALTER TABLE.

2. Create predictions/mlb/sidemodel/binary_v1.py with:
     class BinaryV1SideModel:
       def __init__(self, model_path: str | None): ...
       def score(self, features: dict, recommendation: str) -> float | None: ...
       version: str
   Loads pickle from GCS at MLB_SIDEMODEL_PATH. Returns None if env unset OR if
   any required feature is missing. Mirror the GCS load pattern from
   catboost_v2_regressor_predictor.load_model() — that's the right reference.

3. Edit predictions/mlb/worker.py:
   - At L130-200 system-init block, instantiate the side-model once at startup
     (only if MLB_SIDEMODEL_PATH is set)
   - In the prediction loop, after each predictor returns, call
     sidemodel.score(features, pred['recommendation']) and attach the result as
     pred['p_sidemodel'] / pred['sidemodel_version']
   - At L905 row build, write both new fields to the BQ row dict
   - Do NOT touch the BB exporter

4. Verify the worker still passes its unit tests with MLB_SIDEMODEL_PATH unset
   (both columns should be written as NULL). No new test required for slice 1 —
   side-model is no-op without an artifact.

5. Commit + push as a SEPARATE commit. This deploys mlb-prediction-worker via
   the existing cloudbuild-mlb-worker.yaml auto-deploy. Verify the build and
   that today's predictions still write to BQ with both new columns as NULL.

Stop after step 5. Training the actual side-model is the next session — slice 1
just plumbs the column. Do NOT start the training-set builder in the same
session as the worker plumbing; we want one slice landed and verified before
introducing the artifact.

Defers and revisit triggers from the predecessor and the SCOPING doc.
```

## Slice 2 (the session after this next one)

Once slice 1 is in main + deployed and worker still healthy:

- Build `scripts/mlb/training/build_sidemodel_training_set.py` → produces `/tmp/mlb_sidemodel_training.csv`
- Build `scripts/mlb/training/train_sidemodel_v1.py` → fits logistic + LightGBM, evaluates against sigmoid baseline, gates on 5 governance criteria from the SCOPING doc
- If either model passes gates: upload pickle to `gs://nba-props-platform-ml-models/mlb/sidemodel/binary_v1_{date}.pkl`, set `MLB_SIDEMODEL_PATH` on the worker (via `--update-env-vars`, not `--set-env-vars` per MEMORY)
- If both fail: document the dead end in the SCOPING doc and move on

## Slice 3 (after N≥100 shadow rows accumulate)

- Build `scripts/mlb/sidemodel_cf_analysis.py` — joins `pitcher_strikeouts.p_sidemodel` ↔ `prediction_accuracy.prediction_correct`, computes Brier head-to-head, reliability bins, rerank simulation, filter-threshold simulation
- If the side-model wins on the 3 promotion criteria in SCOPING, propose adding `p_sidemodel ≥ T` as an observation-mode filter in `best_bets_exporter.py`. Standard observation-period evidence applies after that.

## Open questions left for the executing session

These three are flagged in the SCOPING doc and don't block slice 1 but want answering during slice 2:

1. Is `load_batch_features` already cached per worker invocation, or per pitcher? Affects whether the training-set builder needs its own caching.
2. Brand-name LightGBM hyperparameters beyond "small" — left for the training session to tune by val curve.
3. Whether `sidemodel_version` should follow the NBA model registry pattern. Recommendation in the SCOPING doc: no, the env-var pointer is fine for a single binary classifier in v1.

## Defers (still active from the predecessor handoff)

Carrying these forward unchanged from 2026-05-19-2:

| Item | Revisit trigger |
|---|---|
| `halt_overrides` writer fix | An incident requires a manual override that gets clobbered |
| MPD recovery lag (24h+ floor) | After binary side-model lands; current mitigations work |
| Frontend nav fix | 3+ Sentry `nav_stuck:*` events with consistent payload |
| Isotonic calibration | N≥2000 graded AND a regressor retrain that targets calibration |
| Phase 2 CF auto-demote enablement | After MLB eligibility bar fix (which itself is deferred behind Path B execution) |
| `away_over_blocked_policy` double-audit-row | When AOB becomes a Phase 2 auto-demote candidate |
| NBA work (broader) | Off-season; out of scope per project memory |
| Orphan scrapers (`mlb_ballpark_factors`, `mlb_statcast_pitcher`) | A model experiment actually wants their features |

## Active background routines

- `mlb-regressor-halt-check-2026-05-23` — fires automatically on its own at 8 AM EDT 2026-05-23 to check whether `catboost_mlb_v2_regressor_36f_20260517` has accumulated passing MPD rows before the `fleet_in_transition` grace expires. No action needed before then.

## Session totals

0 commits. 1 spec document. The whole pass was about getting the next session enough concrete material to execute without re-deciding scope.
