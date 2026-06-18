# Handoff — MQ / distributional diversity-model experiment

**For:** a fresh session picking up the off-season ML work.
**Status going in:** system healthy, NBA off-season (halted by design), MLB in-season but info-only (betting exhausted). This is a *bounded experiment*, not an open-ended build.

---

## Mission (one line)
Train ONE structurally-different model (MultiQuantile / distributional) and decide — against a pre-registered bar — whether it is **both de-correlated from the CatBoost fleet AND accurate enough** to be worth enabling. If it can't be both, conclude with a clean negative result.

## Why this, and why not the obvious thing
A 2026-06-18 fleet-diversity diagnosis (in `docs/09-handoff/2026-06-17-improvement-backlog.md` + `MEMORY.md`) established, with real correlation data:
- **Feature-set variation does NOT de-correlate models** — `catboost_v12` vs `catboost_v16_noveg` = r **0.99**.
- **GBDT algo-swap does NOT either** — CatBoost↔LGBM **0.958**, CatBoost↔XGB **0.929** (≈ CatBoost↔CatBoost 0.938). All boosted trees converge.
- **Only structurally-different models de-correlate** (`moving_average`/`zone_matchup_v1`/`similarity_balanced_v1`/`ensemble_v1` = r **0.795**) — but those are individually **sub-break-even at edge 5+** (45–49%), so enabling them as-is drags the fleet.
- The current fleet is effectively **64 CatBoost clones**.
- **Gate-check:** `combo_3way` (the one genuine cross-MODEL signal, `is_model_dependent=true`) fired only **38 picks/season at 60.5% HR** — low volume consistent with the clone fleet, but modest value (NOT the 95.5% all-time headline). `book_disagreement` is `is_model_dependent=FALSE` (cross-book) — does NOT depend on fleet diversity.

**So: do NOT train feature-set or GBDT-algo grids (they produce clones). The only lever is a model that is structurally different AND accurate.** The MultiQuantile / distributional approach is the candidate (predicts a distribution rather than a GBDT point estimate → plausibly de-correlated). Prior art: the `MultiQuantile` / `CEIL_UNDER` work (Sessions 521-522). First step: `grep -rniE "multiquantile|quantile|CEIL_UNDER" ml/ scripts/ predictions/` to find the existing path and extend it rather than build from scratch.

## Pre-registered success bar (lock before looking)
A candidate model PASSES only if BOTH hold on clean, held-out / walk-forward data:
1. **De-correlated:** mean `r < 0.85` between its predictions and the CatBoost mass (the existing `moving_average`/`zone_matchup` family sits at 0.795; GBDTs at 0.93–0.99 — so 0.85 is a meaningful threshold).
2. **Accurate:** **≥ 53% HR at edge 5+** (the money zone; CatBoost raw is ~53% at edge 3+).

- PASS → propose adding to the fleet (SHADOW first), then re-measure `combo_3way` volume + HR with it in. Deployment needs governance gates + explicit user sign-off (training ≠ deploying).
- FAIL → conclude "diversity isn't worth chasing this off-season," document, stop. A clean negative result is a valid outcome.

## How to measure de-correlation (reuse this query)
Run the candidate's predictions for a clean window, then:
```sql
WITH preds AS (
  SELECT system_id, player_lookup, game_date, predicted_points,
    CASE WHEN LOWER(system_id) LIKE 'catboost%' THEN 'catboost' ELSE 'candidate' END AS fam
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE game_date BETWEEN '<clean_window_start>' AND '<clean_window_end>' AND predicted_points IS NOT NULL
)
SELECT a.fam, b.fam, ROUND(CORR(a.predicted_points, b.predicted_points),3) r, COUNT(*) n
FROM preds a JOIN preds b
  ON a.player_lookup=b.player_lookup AND a.game_date=b.game_date AND a.system_id < b.system_id
GROUP BY 1,2 HAVING n > 500;
```

## Tooling + data
- **Training:** `ml/experiments/quick_retrain.py` (has `--feature-set` {v9..v19,_noveg}, `--train-start/end`, `--eval-start/end`, `--train-days` default 56, recency/tier weights). Single-shot. NOTE: feature-set is a *dead diversity lever* — the structural difference must come from the model type, not the feature set.
- **Use CLEAN data** (post Session-458 leakage fix). Avoid late-season / TIGHT-market contamination (caps: `cap_to_pre_late_season`, `cap_to_last_loose_market_date`). 56-day window / 7-day retrain is the validated sweet spot.
- **`quick_retrain.py` gotcha:** its production-line eval is hardcoded to `catboost_v9`; use `--no-production-lines` (uses feature-store DK lines; governance still valid).

## Governance (non-negotiable)
- NEVER deploy a retrained model without passing ALL governance gates AND explicit user approval at each step. Train → gates pass → upload → register → shadow 2+ days → promote. Shadow-only for this experiment.

## Environment gotchas
- **Local gcloud/bq default project is WRONG (`jett-prod`).** Always pass `--project[_id]=nba-props-platform`; for scripts that shell out (e.g. `bin/model-registry.sh`), prefix `CLOUDSDK_CORE_PROJECT=nba-props-platform`.
- `prediction_accuracy`: no `edge` column (compute `ABS(predicted_points - line_value)`), use `prediction_correct`, filter `has_prop_line=TRUE AND recommendation IN ('OVER','UNDER')`.
- Always partition-filter `game_date` on raw/prediction tables.

## Pointers
- Diagnosis + full backlog: `docs/09-handoff/2026-06-17-improvement-backlog.md`
- `MEMORY.md` → "FLEET DIVERSITY finding (2026-06-18)" carries the diagnosis, gate result, and this success bar.
- Model dead-ends (don't re-test): `docs/06-reference/model-dead-ends.md`

## System state (so you don't re-investigate)
All current as of 2026-06-18, verified holding:
- `pipeline_event_log` quota incident fixed (streaming); 17 watchdog schedulers OIDC→OAuth (green); 7 DLQ monitor subs; phase2 `emit_metric` lib; `mlb_schedule` planner-prefix fix; off-season min-instances=0.
- Known off-season noise (NOT a bug): `PlayerShotZoneAnalysisProcessor` retry loop (~700 errors/12h) — deferred fix is the `has_regular_season_games()` guard on the precompute entrypoint.
- Open quick wins in the backlog: drop `prediction_grades` + migrate readers (fixes silently-broken `daily_data_quality_check` Checks 4/5); the shot-zone guard; 3 monthly MLB jobs failing PERMISSION_DENIED.
