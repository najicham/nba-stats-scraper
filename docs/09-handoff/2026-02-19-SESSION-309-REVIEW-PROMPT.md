# Session 310 Prompt — Best Bets System Review + Model Transition Strategy

## Your Mission

You are reviewing our NBA player props best bets system. Read all the referenced docs and code, then produce a written analysis with concrete recommendations. Do NOT make code changes — this is a research and analysis session.

## Context

We have a profitable best bets system (71%+ HR at edge 5+) that:
- Uses CatBoost models to predict player points, compares to sportsbook prop lines
- Selects bets via edge-first filtering (edge >= 5.0) + negative filters + signal minimum
- Runs 4+ models in parallel (V9 MAE champion + V12 MAE + quantile variants)
- Retrains the champion weekly on a 42-day rolling window

The system works well but has open questions about what happens during **model transitions** — when a retrained model replaces the current champion.

## What To Review

### Part 1: End-to-End Best Bets System Health Check

Read these files and verify the system is sound:

**Architecture docs:**
- `docs/08-projects/current/best-bets-v2/04-HOW-BEST-BETS-WORK.md` — Full system explanation
- `docs/08-projects/current/best-bets-v2/00-ARCHITECTURE-PLAN.md` — Multi-model architecture
- `docs/08-projects/current/best-bets-v2/01-REVISED-STRATEGY.md` — Strategy revisions
- `docs/08-projects/current/best-bets-v2/03-SESSION-308-REVIEW.md` — Most recent system review
- `docs/08-projects/current/best-bets-v2/05-FUTURE-EDGE-EXPLORATION.md` — Future research ideas

**Core code (read all of these):**
- `ml/signals/aggregator.py` — Edge-first selection + negative filters (THE key file)
- `ml/signals/supplemental_data.py` — Multi-model prediction query (`multi_model=True`)
- `data_processors/publishing/signal_best_bets_exporter.py` — Orchestrates the export
- `shared/config/cross_model_subsets.py` — Model family definitions + classification
- `shared/config/model_selection.py` — Champion model ID + config
- `ml/analysis/model_performance.py` — Daily model performance + decay state machine
- `ml/signals/cross_model_scorer.py` — Cross-model consensus computation

**Questions to answer:**
1. Are the negative filters in `aggregator.py` still justified? Any that should be added/removed based on the data patterns?
2. Is the `MIN_SIGNAL_COUNT = 2` requirement still correct, or does it filter out good high-edge picks unnecessarily?
3. Is the multi-model candidate generation (`multi_model=True` in supplemental_data.py) working as intended — picking the highest-edge prediction per player across all models?
4. Are there any code paths where a pick could bypass the negative filters?

### Part 2: Model Transition Strategy (THE HARD PROBLEM)

When we retrain the champion (weekly, 42-day rolling window), the new model immediately replaces the old one. The system_id stays `catboost_v9` — predictions seamlessly flow into best bets. But this creates several problems:

**Problem 1: Trust — Use existing model until new one is proven, or switch immediately?**

Currently, `retrain.sh --promote` swaps the model instantly. The new model has passed governance gates (60%+ HR at edge 3+, N>=50, no bias, MAE improvement) on its eval window, but:
- Those gates test on the eval period BEFORE deployment, not on live data
- The old model's negative filters were tuned to ITS behavior — a new model may have different failure modes
- A decaying old model (HR dropping) might still be better than a brand new model with no live track record

**Investigate and recommend ONE of these strategies:**
- **A. Instant switch (current):** Retrain → gates pass → promote immediately. Risk: new model fails in ways gates didn't catch.
- **B. Shadow period:** New model runs in shadow for N days alongside old model. Only promote after live HR confirms. Risk: if old model is decaying, you're losing money during the shadow period.
- **C. Hybrid/gradual:** Use new model only for high-edge picks (edge 7+) initially, expand to edge 5+ after N days of live validation. Old model handles the rest. Risk: complexity.
- **D. Edge-conditional:** If old model is in DEGRADING/BLOCKED state (from `model_performance_daily`), switch to new model immediately. If old model is HEALTHY, shadow the new model first. Risk: state machine accuracy.

Consider: the decay detection system (`ml/analysis/model_performance.py`) tracks HEALTHY/WATCH/DEGRADING/BLOCKED states. How should this interact with retraining decisions?

**Problem 2: Do the negative filters transfer to a new model?**

The negative filters in `aggregator.py` were discovered from backtesting the V9 champion:
- UNDER edge 7+ block (40.7% HR) — is this a property of ALL CatBoost models or specific to V9?
- Bench UNDER block (line < 12, 35.1% HR) — market-structural, probably transfers
- Player blacklist (<40% HR) — computed from champion's history, but a new model might predict differently for those players
- Line movement UNDER blocks — market-structural, probably transfers

The key question: **which filters are model-specific vs market-structural?** Market-structural filters (bench UNDER, line movement) should transfer. Model-specific filters (UNDER edge 7+ block) need re-validation after each retrain.

**Problem 3: What happens to shadow models during champion retrain?**

Currently 4+ models run in parallel. When the champion retrains:
- Do shadow model performance histories reset?
- Does cross-model consensus break if the champion's predictions shift significantly?
- Should shadow models retrain on the same schedule, or staggered?

Read `shared/config/cross_model_subsets.py` (families, `classify_system_id`), `ml/signals/cross_model_scorer.py`, and the retrain script (`bin/retrain.sh`) to understand the full picture.

### Part 3: Layer 2 Cross-Model Subsets + Signal Subsets

**Cross-model subsets** (Layer 2, defined in `shared/config/cross_model_subsets.py`):
- `xm_consensus_3plus`, `xm_consensus_4plus`, `xm_quantile_agreement_under`, `xm_mae_plus_quantile_over`, `xm_diverse_agreement`
- These are observation-only — graded but don't influence pick selection

**Questions:**
1. How are these subset definitions decided? Read `CROSS_MODEL_SUBSETS` dict in `cross_model_subsets.py` and evaluate whether the thresholds make sense.
2. Should any of them graduate from observation-only to active filtering? Check their grading performance:
```sql
SELECT subset_id,
       COUNT(*) as n,
       ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 1) as hr
FROM nba_predictions.v_dynamic_subset_performance
WHERE subset_id LIKE 'xm_%'
  AND game_date >= '2025-12-01'
GROUP BY 1
ORDER BY hr DESC
```
3. The signal subsets — how are signals used in the current system? Read `ml/signals/registry.py` to see the 18 active signals. Are they truly annotation-only (Session 297 change), or do some still influence selection via `MIN_SIGNAL_COUNT = 2`?

**Also read:**
- `docs/08-projects/current/multi-model-best-bets/00-ARCHITECTURE.md`
- `ml/signals/combo_registry.py` — Signal combination tracking
- `data_processors/publishing/cross_model_subset_materializer.py` — How subsets are materialized

## Deliverables

Write your findings to `docs/08-projects/current/best-bets-v2/06-SESSION-310-REVIEW.md` with these sections:

1. **System Health Check** — Is the best bets pipeline sound? Any bugs or gaps found?
2. **Model Transition Recommendation** — Pick ONE strategy (A/B/C/D or propose a new one) with justification
3. **Filter Transferability Analysis** — Classify each negative filter as model-specific or market-structural
4. **Cross-Model Subset Assessment** — Are the Layer 2 subsets working? Should any graduate?
5. **Signal System Assessment** — Is the annotation-only + MIN_SIGNAL_COUNT=2 approach optimal?
6. **Concrete Next Steps** — Ordered list of what to implement

## Important Notes

- This is a RESEARCH session — read code and data, write analysis, do NOT change code
- Run BQ queries to validate claims (use `bq query --project_id=nba-props-platform --use_legacy_sql=false`)
- The model performance data was just backfilled (Session 309) — `model_performance_daily` now has data for all 4 models
- Use `PYTHONPATH=. python` prefix for any Python scripts
- Read `CLAUDE.md` for full system context
