# Session 443 Handoff — MLB 2026 Season Strategy

**Date:** 2026-03-08
**Focus:** MLB pre-season strategy validation via 11 parallel research agents
**Commits:** 3 (regressor v2, cross-season filters, project docs)
**Tests:** 15 passing

## What Was Done

Ran 11 parallel research agents analyzing 3,869+ walk-forward predictions (Apr 2024 - Sep 2025) to build a cross-season validated MLB strategy. Built and committed:

1. **CatBoost v2 Regressor Predictor** — production predictor using real K-unit edges instead of probability-based classifier edges
2. **Cross-season validated filter stack** — whole-number line filter (p<0.001), expanded pitcher blacklist (10→18), demoted opponent/venue filters to observation
3. **Full project documentation** at `docs/08-projects/current/mlb-2026-season-strategy/`

### Key Findings

- **Model:** CatBoost Regressor, defaults, 120d window, 14d retrain. Hyperparameters/ensembles/features all tested and rejected.
- **Whole-line filter:** 49% vs 58.6% HR on whole vs half-line (p<0.001). Structural push risk. Biggest new filter.
- **2-tier system:** Best Bets (top-3/day, 1u, ~64.6% HR) + Ultra (home + proj agrees + edge≥1.0, 2u, ~72.9% HR)
- **Pure edge ranking confirmed** — composite scoring fails cross-season validation
- **Static opponent/venue lists anti-correlated cross-season** (r=-0.29) — demoted to observation

## What Was NOT Done (Next Session TODO)

### Priority 1: Implement Ultra Tier in Exporter (1-2 hours)

The ultra tier logic needs to be added to `ml/signals/mlb/best_bets_exporter.py`:

```python
# After ranking and selecting top-3, tag ultra picks:
# Ultra = OVER + half-line + not-blacklisted + edge >= 1.0 + is_home + projection_agrees
# Ultra picks get: ultra_tier = True, staking_multiplier = 2
# Ultra picks NOT in top-3 should still be published
```

Key decisions:
- Ultra picks in top-3 → stake 2u instead of 1u (overlay)
- Ultra picks NOT in top-3 → still publish as additional picks at 2u
- Need `ultra_tier` and `ultra_criteria` fields in BQ schema (same pattern as NBA ultra bets)
- Algorithm version should update to `mlb_v5_ultra_tiered_top3`

Files to modify:
- `ml/signals/mlb/best_bets_exporter.py` — add ultra tagging after ranking
- `ml/signals/mlb/signals.py` — possibly add an `UltraQualificationSignal`
- Tests — add ultra tier test cases

### Priority 2: Remove Dead Features from Walk-Forward (30 min)

Feature analysis found 5 dead/duplicate features. Update `scripts/mlb/training/walk_forward_simulation.py`:
- Remove: `f17_month_of_season`, `f18_days_into_season`, `f24_is_postseason`
- Remove: `f67_season_starts` (duplicate of `f08_season_games`)
- Remove: `f69_recent_workload_ratio` (duplicate of `f21_games_last_30_days / 6.0`)

Also update `scripts/mlb/training/train_regressor_v2.py` to exclude these.

### Priority 3: Train Final Model (Mar 18-20)

```bash
PYTHONPATH=. python scripts/mlb/training/train_regressor_v2.py \
    --training-end 2026-03-20 --window 120
gsutil cp models/mlb/catboost_mlb_v2_regressor_*.cbm \
    gs://nba-props-platform-ml-models/mlb/
```

### Priority 4: Deploy MLB Worker (Mar 21-22)

Full checklist at `docs/08-projects/current/mlb-2026-season-strategy/03-DEPLOY-CHECKLIST.md`.

```bash
gcloud builds submit --config cloudbuild-mlb-worker.yaml
gcloud run services update-traffic mlb-prediction-worker --region=us-west2 --to-latest
gcloud run services update mlb-prediction-worker --region=us-west2 \
    --update-env-vars="MLB_ACTIVE_SYSTEMS=catboost_v1,catboost_v2_regressor"
```

### Priority 5: Resume Schedulers (Mar 24)

```bash
./bin/mlb-season-resume.sh
```

### Priority 6: UNDER Enablement (May 1 decision point)

UNDER is viable with strict gates (62.6% HR in walk-forward) but deferred until OVER system is validated live:
- Gate: `edge >= 1.5 AND projection < line AND (cold_form OR line >= 6.0)`
- Max 1 per day
- Enable via `MLB_UNDER_ENABLED=true` env var

### Priority 7: Lean Model Shadow Experiment (Optional)

Feature analysis showed top-5 features get 55.2% HR (+1.5pp over 41f). Consider running a 15-feature shadow model to validate in production.

## Uncommitted Files

```
results/mlb_walkforward_v4_regression/      # Regressor walk-forward results
results/mlb_walkforward_v4_rich/            # Rich metadata walk-forward
results/mlb_walkforward_retrain_strategy/   # 7d/14d/21d/28d retrain comparison
results/mlb_walkforward_ensemble/           # Ensemble model comparison
results/mlb_walkforward_v4_regression_windows/  # 56/90/120/180d window sweep
scripts/mlb/analysis/                       # Analysis scripts from agents
scripts/mlb/training/train_regressor_v2.py  # Training script (committed)
```

These results directories contain CSVs and analysis scripts from the 11 agents. Keep for reference but don't need to be committed.

## Season Goals (from 04-SEASON-GOALS.md)

| Tier | Floor | Target | Stretch |
|------|-------|--------|---------|
| Best Bets HR | 58% | 62% | 66% |
| Ultra HR | 63% | 70% | 75% |
| Combined profit | +60u | +200u | +300u |

## Key Files Changed

```
ml/signals/mlb/best_bets_exporter.py     # Unified v5, DOW removed, whole-line added
ml/signals/mlb/signals.py                # 18-pitcher blacklist, whole-line filter, obs filters
ml/signals/mlb/registry.py               # Updated signal/filter registration
predictions/mlb/prediction_systems/catboost_v2_regressor_predictor.py  # NEW
predictions/mlb/prediction_systems/__init__.py  # v2 export
predictions/mlb/worker.py                # v2 opt-in via env var
scripts/mlb/training/walk_forward_simulation.py  # Rich metadata output
scripts/mlb/training/train_regressor_v2.py  # NEW — regressor training
tests/mlb/test_catboost_v2_regressor.py   # NEW — 7 tests
tests/mlb/test_exporter_with_regressor.py # Updated — 8 tests
docs/08-projects/current/mlb-2026-season-strategy/  # NEW — 5 docs
```

## What NOT To Revisit (Dead Ends)

Full list at `docs/08-projects/current/mlb-2026-season-strategy/05-DEAD-ENDS.md`. Key items:
- Ensemble models (CatBoost solo wins)
- Composite scoring (fails cross-season)
- Static opponent/venue lists (r=-0.29)
- Hyperparameter tuning (defaults optimal)
- Derived features (all noise)
- DOW/seasonal phases (noise)
