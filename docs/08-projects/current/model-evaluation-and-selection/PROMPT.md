# Model Evaluation & Selection — Session Prompt

## What This Is

You're picking up a research and design project on how we evaluate ML models and select "top picks" in our NBA player props prediction system. Session 393 did the initial data analysis and documented findings. Your job is to investigate the open questions, build missing tooling, and come back with concrete recommendations.

## Read These First

All project docs are in `docs/08-projects/current/model-evaluation-and-selection/`:

1. **`00-OVERVIEW.md`** — Start here. Key findings summary and document index.
2. **`01-CURRENT-PIPELINE.md`** — How picks flow from 1,800 raw predictions → per-player selection → 30+ filters → signal annotation → best bets. Read this carefully — you need to understand the full pipeline before proposing changes.
3. **`02-FINDINGS.md`** — Session 393 data analysis. Edge bands, signal count correlation, per-model best bets performance, monthly trends, winners vs losers profile. This is the empirical foundation.
4. **`03-BLIND-SPOTS.md`** — 7 identified problems with the current approach. Each is a potential investigation area.
5. **`04-OPEN-QUESTIONS.md`** — 12 research questions with investigation approaches and prioritized action items. This is your primary task list.
6. **`05-SHADOW-MONITORING.md`** — Design doc for tracking disabled model performance. Needs an implementation decision (Option A/B/C).
7. **`06-EXPERIMENT-INFRASTRUCTURE.md`** — Assessment of our training/eval tooling (`quick_retrain.py`, `grid_search_weights.py`, `what_if_retrain.py`, replay engine). Lists 6 critical gaps. Read this before building any new tooling so you don't duplicate what exists.

Also read `CLAUDE.md` at the repo root for full system context — model architecture, dead ends, deployment patterns, etc.

## The Core Problem

We have 16+ models but only 6 have ever sourced a best bets pick. Well-calibrated models with 66.7% HR (V16) never break through selection because they produce lower edges (3.7-4.0) than older models (5-7). The per-player selection ranks by raw edge, which rewards over-prediction, not accuracy. Meanwhile, 41% of our picks (signal count = 3) are barely profitable at 55.1% HR.

We need to figure out:
- How to evaluate what a model ACTUALLY contributes to best bets quality
- Whether each model should have its own filter criteria or if one-size-fits-all is correct
- How to compare models fairly when they have different edge distributions
- What the optimal training window is per model architecture
- Whether disabled models should be shadow-monitored so we don't lose information

## How to Use Agents

Use agents liberally — this is a research-heavy session. Recommended pattern:

**Explore agents** for:
- Reading and understanding the codebase (supplemental_data.py, aggregator.py, quick_retrain.py, etc.)
- Finding existing tooling before building new things
- Checking how specific filters or signals are implemented

**General-purpose agents** for:
- Running BQ analysis queries (edge calibration, prediction correlation, filter audits)
- Building new scripts (simulate_best_bets.py, bootstrap_hr.py)
- Implementing training window sweep templates

**Run agents in parallel** when investigating independent questions. For example, you could simultaneously:
- Agent 1: Run edge calibration analysis (Q7) via BQ queries
- Agent 2: Run prediction correlation heatmap (Q8) via BQ queries
- Agent 3: Run filter temporal audit (Q9) via BQ queries

Then synthesize results and decide next steps.

## Priority Order

From `04-OPEN-QUESTIONS.md`, the recommended priority:

### Priority 1: Build Missing Tools
1. **`simulate_best_bets.py`** — Simulate any model through the full best bets pipeline (filters + signals). This is the single most important missing tool. Without it, we can't fairly evaluate models that never win per-player selection. Use the existing `aggregator.py` and `supplemental_data.py` as the foundation.
2. **Training window sweep template** — Add to `grid_search_weights.py`. Sweep [28, 35, 42, 49, 56, 63, 70] day windows across eval periods.
3. **Bootstrap CI utility** — Simple `bin/bootstrap_hr.py` that takes two HR results and outputs p-value + confidence interval.

### Priority 2: Analysis
4. **Edge calibration** (Q7) — Bin edge → empirical HR per model. Are edges calibrated? Do models agree on what edge=5 means?
5. **Prediction correlation** (Q8) — Pairwise correlation of predicted_points across models for same player-games. Are 16 models actually 3?
6. **Filter temporal audit** (Q9) — Which filters have degraded since calibration? Use `post_filter_eval.py` if it works, or query `best_bets_filter_audit` + `prediction_accuracy`.
7. **Per-model quality profiles** — Check `model_profile_daily` table for accumulated data.

### Priority 3: Decisions
8. **SC=3 elimination** — Simulate dropping SC=3 picks. What's the P&L impact?
9. **Expected value ranking prototype** — Compare `edge × P(win)` ranking vs current `edge × hr_weight` on historical data.
10. **Per-model vs uniform filters** — Based on profile data, decide approach.
11. **Shadow monitoring design** — Pick Option A, B, or C from `05-SHADOW-MONITORING.md`.
12. **V16 retrain** — Best-performing family needs fresh 56-day window training.

## Key Files to Know

| File | What It Does |
|------|-------------|
| `ml/signals/supplemental_data.py` | Builds the BQ query for predictions + per-player selection |
| `ml/signals/aggregator.py` | 30+ filter stack + signal annotation + ranking |
| `ml/signals/signal_annotator.py` | Signal evaluation logic |
| `ml/signals/player_blacklist.py` | Per-player season HR blacklist |
| `bin/quick_retrain.py` | Core retraining engine (4,500+ lines) |
| `bin/grid_search_weights.py` | Grid search orchestrator |
| `bin/what_if_retrain.py` | Counterfactual model simulation |
| `bin/post_filter_eval.py` | Filter effectiveness evaluation |
| `bin/replay_engine.py` | Historical backtesting with P&L |
| `shared/config/cross_model_subsets.py` | Model family classification |
| `data_processors/publishing/signal_best_bets_exporter.py` | Orchestrates the export |

## Important Constraints

- **Never deploy a retrained model without governance gates passing** — use `quick_retrain.py` which enforces them automatically.
- **Use `--skip-register` for experiments** — don't pollute the model registry with test models.
- **Edge >= 3 is the minimum** — 73% of predictions have edge < 3 and lose money.
- **BQ partition filters required** — always include `WHERE game_date >= ...` on partitioned tables.
- **Any HR difference < 5pp is within noise** — don't make decisions based on small differences without statistical significance testing.
- **Best bets HR is the metric that matters**, not raw model HR. A model with 50% overall HR can source 80% best bets picks.

## Deliverables

By end of session, we want:
1. **Tooling** — At least `simulate_best_bets.py` built and tested
2. **Analysis results** — Edge calibration, correlation heatmap, filter audit findings
3. **Recommendations** — Concrete proposals for selection strategy changes, filter adjustments, and shadow monitoring
4. **Updated docs** — Add findings to this project directory
5. **V16 retrain** — If time permits, retrain V16 on fresh 56-day window
