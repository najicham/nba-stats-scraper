# Pre-registration — Retrain CADENCE experiment (7-day vs 14-day)

**Date:** 2026-06-18
**Status:** PRE-REGISTERED (written before any HR result was looked at).
**Author:** off-season ML session (fleet-diversity thread now CLOSED — see `2026-06-18-mq-diversity-RESULT.md`).
**Decision being settled:** Should the `weekly-retrain` CF stay 7-day, or move to 14-day? 14-day halves
retrain compute/cost — adopt it **iff** it is HR-equivalent (within noise) to 7-day on clean data.

This is a **read-only walk-forward experiment**. No model is deployed. Any deploy needs governance gates +
explicit user sign-off. Training ≠ deploying.

---

## Question

Holding the training window fixed at **56 days** (the validated sweet spot), is a **14-day** retrain
cadence within noise of a **7-day** cadence on best-bets-quality (edge 5+) hit rate?

## Reduction (why this is a clean paired test, not a full policy simulation)

A retrain-cadence policy differs from another ONLY in **how stale** the served model is on a given day.
With window fixed at 56d:
- **7d cadence:** model is 0–6 days stale.
- **14d cadence:** model is 0–13 days stale.

Over any 14-day cycle, BOTH policies serve the *same* freshly-retrained model in **week 1** (days 0–6).
They diverge ONLY in **week 2** (days 7–13): 7d retrains again (served model 0–6d stale), 14d keeps the
week-1 model (now 7–13d stale). **Week-1 contributions are identical and cancel.** Therefore the entire
policy-level HR difference is concentrated in week-2 windows and equals:

> HR( fresh model on week 2 )  vs  HR( 7-day-staler model on the same week 2 )

This is directly measurable as a **paired** comparison on identical eval windows and player sets.

## Design (7-day stride, double-duty models — maximizes N)

Train one CatBoost model at every 7-day boundary `b` across each clean window (window = `[b-55, b]`, 56d).
Evaluate each model on the 14 days forward `[b+1, b+14]`. Then each model serves double duty:
- **FRESH** arm for week `W=[d, d+6]`  = predictions from model trained to `b=d-1` (age 0–6 on that week).
- **STALE** arm for the same week `W`   = predictions from model trained to `b=d-8` (age 7–13 on that week).

(Equivalently: for week boundary `d`, FRESH = model whose `train_end = d-1`; STALE = model whose
`train_end = d-8`, i.e. one cadence-step staler.) Both arms are evaluated on the **same** `[d, d+6]` window
and the **same** players → fully paired. FRESH = what 7d-cadence serves in week 2; STALE = what 14d serves.

Pool FRESH rows across all weeks/seasons; pool STALE likewise. Compare HR.

## Model / data

- **Model:** CatBoost regressor, feature set **V12_NOVEG** (validated production base), quick_retrain
  production hyperparams. Engine: `ml/experiments/quick_retrain.py --feature-set v12 --no-vegas
  --no-production-lines --dump-eval-predictions` with `--skip-register --skip-auto-upload
  --skip-auto-register` (no GCS/registry writes).
- **Lines:** DraftKings via `nba_raw.odds_api_player_points_props` (full coverage 2023-24, 2024-25,
  2025-26). Grade vs `player_game_summary.points` actuals (quick_retrain eval path).
- **Edge:** `|predicted_points − line|`. Recommendation: OVER if pred>line else UNDER.

## Clean eval universe (contamination guards)

- **2023-24:** week boundaries Dec 2023 – Mar 2024 (prior seasons are healthy late-season — Session 514).
- **2024-25:** week boundaries Dec 2024 – Mar 2025.
- **2025-26:** week boundaries **Dec 30 2025 – Jan 18 2026 ONLY** (eval ends ≤ Jan 31). Avoids the
  2025-26 late-season anomaly / TIGHT market / collapse (Feb+). Pre-late-season + loose-market only.
- Avoid Nov ramp-up (need 56d of prior data) and April+ playoffs.

## Metrics

- **PRIMARY:** Hit rate at **edge ≥ 5**, pooled across all week-2 windows & seasons, FRESH vs STALE.
  (Edge 5+ = best-bets money zone per CLAUDE.md.)
- **Secondary:** edge ≥ 3 HR (well-powered); OVER/UNDER split at edge5+; HR after production UNDER
  negative filters (pipeline-lite: edge7+ UNDER block, line<12 UNDER block, line-Δ ±2 UNDER block);
  MAE delta; **per-season** edge5+ HR (consistency).

## Note on "BB-pipeline HR" vs raw edge5+ HR

The cadence effect flows **entirely through `predicted_points`** → edge magnitude & direction. The rest of
the BB pipeline (signal health, blacklist, regime, combos, negative filters) is computed from the broader
data/fleet context for a given date and is **cadence-invariant** (same eval date ⇒ same context regardless
of which cadence produced the point estimate). So edge5+ raw HR (+ the UNDER negative filters applied as
pipeline-lite) is the cadence-sensitive driver of BB HR. If the primary result is **borderline**, escalate
to a full BB-pipeline measurement by injecting counterfactual predictions into `player_prop_predictions`
under a synthetic `system_id` and running `bin/simulate_best_bets.py`. Otherwise the raw edge5+ contrast
settles it.

## Pre-registered decision rule (non-inferiority of 14d)

Let **Δ = HR_fresh − HR_stale** (percentage points) at edge5+ pooled. Two-proportion z-test p-value `p`.

- **14d WITHIN NOISE → adopt-eligible:** `Δ < 2.0pp` AND `p > 0.05`
  (staleness costs <2pp and is statistically indistinguishable).
- **7d JUSTIFIED → keep 7-day:** `Δ ≥ 2.0pp` AND `p ≤ 0.05` (stale significantly worse).
- **INCONCLUSIVE:** anything else → report, recommend more windows; do not change cadence.

**Directional-consistency guard (anti-pooling-artifact):** even if pooled says "within noise," if **≥ 2 of
3 seasons** independently show STALE worse than FRESH by **≥ 2pp** at edge5+, downgrade to INCONCLUSIVE.

**Margin justification:** BB edge5+ HR ≈ 65%; −110 break-even = 52.4%. 2pp at 65% is operationally small
vs month-to-month noise (Jan 73.8% → Feb 63.3%) and equals the repo's `experiment_harness` NOISE_THRESHOLD
(2.0pp). Power note: edge5+ is sparse for a single noveg model (~1–2% of eval rows), so N may be modest;
the directional-consistency guard protects against an underpowered pooled "within-noise" false-negative.

## What would change the recommendation

- STALE clearly worse at edge5+ AND edge3+ AND in ≥2 seasons → 7d justified, keep weekly-retrain.
- STALE within noise across the board → recommend 14d (halves compute); still requires user sign-off to
  change the CF schedule (this experiment does not deploy anything).
