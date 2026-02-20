# How the Best Bets System Works

**Date:** 2026-02-19 (Session 309)
**Audience:** Anyone who wants to understand the system end-to-end

---

## The One-Sentence Version

Every day, the system predicts how many points each NBA player will score, compares that to sportsbook prop lines, and recommends the bets where the model most disagrees with Vegas — filtered to remove historically losing patterns.

---

## The Pipeline (6 Phases)

The system runs daily starting ~6 AM ET, flowing through 6 phases connected by Pub/Sub triggers:

```
Phase 1: SCRAPE        → 30+ scrapers pull NBA stats, injuries, betting lines, play-by-play
Phase 2: RAW PROCESS   → Raw JSON → BigQuery tables
Phase 3: ANALYTICS     → Player/team game summaries (rolling averages, matchup stats)
Phase 4: PRECOMPUTE    → 37 ML features per player (matchup, history, vegas, context)
Phase 5: PREDICT       → CatBoost model predicts points → compare to prop line → compute "edge"
Phase 6: PUBLISH       → Export best bets to GCS API + BigQuery
```

**Edge** is the core concept: `edge = predicted_points - prop_line`. If the model predicts 28 points and the line is 22.5, the edge is +5.5 (bet OVER). If the model predicts 18, the edge is -4.5 (bet UNDER).

---

## Best Bets Selection (Phase 6)

The system runs ~75 predictions per game day. Most aren't worth betting. The selection logic is **edge-first** — the model's disagreement with Vegas IS the signal.

### Step 1: Candidate Pool (Multi-Source)

The exporter queries predictions from **all active CatBoost models** (not just the champion). For each player, it picks the prediction with the highest absolute edge across all models. This means a shadow model can surface a pick the champion missed.

**Key file:** `ml/signals/supplemental_data.py` — `query_predictions_with_supplements(multi_model=True)`

### Step 2: Edge Floor

Only consider picks where `|edge| >= 5.0`. Historical performance:

| Edge Range | Hit Rate | Verdict |
|------------|----------|---------|
| < 3 | ~50% | Coin flip, lose to vig |
| 3-5 | 57% | Barely profitable |
| **5-7** | **69.4%** | **Sweet spot** |
| **7+ OVER** | **84.5%** | **Excellent** |
| 7+ UNDER | 40.7% | Catastrophic — blocked |

### Step 3: Negative Filters

Remove picks that historically lose money. Each filter was discovered from backtesting:

| Filter | What It Catches | Historical HR | Session |
|--------|-----------------|---------------|---------|
| Player blacklist | Players with <40% HR on 8+ past picks | Varies | 284 |
| UNDER edge 7+ block | Model over-predicts UNDERs at extremes | 40.7% | 297 |
| Avoid familiar | 6+ games vs same opponent → regression | Varies | 284 |
| Feature quality < 85 | Bad input data → bad predictions | 24.0% | 278 |
| Bench UNDER | UNDER + line < 12 points | 35.1% | 278 |
| UNDER + line jumped 2+ | Prop moved up 2+ pts, model says under | 38.2% | 306 |
| UNDER + line dropped 2+ | Prop moved down 2+ pts, model says under | 35.2% | 306 |
| Neg +/- streak UNDER | Player in 3+ game negative streak | 13.1% | 294 |
| ANTI_PATTERN combos | Signal combos that anti-correlate with winning | Varies | 295 |

**Key file:** `ml/signals/aggregator.py` — `BestBetsAggregator.aggregate()`

### Step 4: Signal Minimum

At least 2 signals must fire for the player (out of 18 active signals). `model_health` always counts as 1, so you need at least 1 real signal (e.g., `bench_under`, `3pt_bounce`, `prop_line_drop_over`). This ensures the system has context beyond just edge.

### Step 5: Rank by Edge

All surviving picks are sorted by edge descending. **No composite scoring, no signal weighting.** The model's edge IS the ranking.

### Step 6: Natural Sizing

No hard cap on daily picks. Some days produce 2 picks, some 8. The edge floor + filters determine how many.

---

## What Signals Do (Annotations, Not Selection)

18 signals evaluate each prediction. They detect patterns like:
- `bench_under` — bench player likely to go under (76.9% HR)
- `3pt_bounce` — guard at home likely to bounce back on 3PT scoring
- `prop_line_drop_over` — player's line dropped 2+ points from last game (71.6% HR)
- `combo_he_ms` — high edge + minutes surge together (94.9% HR)

**Signals don't determine which picks are chosen — edge does that.** Signals provide **pick angles** — human-readable explanations attached to each pick explaining why it looks good. They're also used for negative filtering (ANTI_PATTERN combos are blocked).

**Key files:** `ml/signals/registry.py`, `ml/signals/pick_angle_builder.py`

---

## Model Families and Retraining

### How Families Work

Models are classified into 6 **families** based on naming patterns:

| Family | Pattern | Loss | Features | Example Runtime ID |
|--------|---------|------|----------|--------------------|
| `v9_mae` | `catboost_v9` (exact or `catboost_v9_33f_*` fallback) | MAE | 33 (V9) | `catboost_v9` |
| `v9_q43` | `catboost_v9_q43_*` | Quantile 0.43 | 33 (V9) | `catboost_v9_q43_train1102_0131` |
| `v9_q45` | `catboost_v9_q45_*` | Quantile 0.45 | 33 (V9) | `catboost_v9_q45_train1102_0131` |
| `v12_mae` | `catboost_v12*` | MAE | 50 (V12) | `catboost_v12` |
| `v12_q43` | `catboost_v12_noveg_q43_*` | Quantile 0.43 | 50 (V12) | `catboost_v12_noveg_q43_train1102_0125` |
| `v12_q45` | `catboost_v12_noveg_q45_*` | Quantile 0.45 | 50 (V12) | `catboost_v12_noveg_q45_train1102_0125` |

Families let us treat a retrained model as a **continuation** of the same model line. A model trained on Jan 1-Feb 5 data with V9 features and MAE loss is the "same model" as one trained on Jan 15-Feb 19 data with the same setup — just updated. This matters for:

- **Performance tracking:** `model_performance_daily` groups by runtime system_id but maps training dates via family
- **Cross-model scoring:** Consensus detection knows V9 MAE and V12 MAE use different feature sets
- **Decay detection:** Tracks health per family lineage, not per individual training run

**Key file:** `shared/config/cross_model_subsets.py`

### What Happens When You Retrain

When you run `./bin/retrain.sh --promote`:

1. **Train** — New model trained on a 42-day rolling window (e.g., Jan 8 → Feb 19)
2. **Governance gates** — Must pass ALL 6 gates (duplicates, vegas bias, 60%+ HR at edge 3+, N≥50, no tier bias, MAE improvement)
3. **Upload** — Model file uploaded to GCS with naming convention `catboost_v9_33f_train{start}-{end}_{timestamp}.cbm`
4. **Register** — Added to BigQuery `model_registry` with training dates, SHA256, status
5. **Promote** — `CATBOOST_V9_MODEL_PATH` env var on prediction-worker updated to point to new GCS path

**The runtime system_id stays `catboost_v9`.** The prediction worker always writes predictions with `system_id = 'catboost_v9'` regardless of which specific `.cbm` file is loaded. The model file changes, but the identity doesn't. This means:

- Best bets automatically use the new model — no code change needed
- Grading continues seamlessly — all V9 predictions share the same system_id
- Performance tracking sees it as continuous (the `days_since_training` resets)

### Does a Retrained Model Automatically Drive Best Bets?

**Yes, for the champion family (V9 MAE).** When `retrain.sh --promote` runs:
1. It updates `CATBOOST_V9_MODEL_PATH` → prediction-worker loads the new model file
2. Predictions are still written as `system_id = 'catboost_v9'`
3. Best bets queries `catboost_v9` predictions by default (via `CHAMPION_MODEL_ID` in `model_selection.py`)
4. Multi-model mode also includes it since `catboost_v9` matches the V9 MAE family filter

**No manual switch is needed.** The retrain updates the model file behind the same system_id.

For **shadow models** (V12, quantile variants), retraining requires updating their respective env vars, but they already participate in best bets via multi-model candidate generation — if a shadow model has a higher edge for a player, that prediction can be selected.

---

## Data Flow Summary

```
Scrapers → Raw BQ Tables → Analytics → Features → Predictions → Best Bets
                                           │
                                    37 features per player
                                    (rolling stats, matchup,
                                     vegas, team context)
                                           │
                                    CatBoost predicts points
                                    edge = prediction - prop line
                                           │
                              ┌─────────────┴─────────────┐
                              │                           │
                         Edge >= 5.0?              Negative filters
                              │                    (blacklist, quality,
                              │                     UNDER blocks, etc.)
                              │                           │
                              └─────────────┬─────────────┘
                                            │
                                     2+ signals fire?
                                            │
                                     Rank by edge
                                            │
                                   Output: Best Bets JSON
                                   + BQ table for grading
```

---

## Key Files

| File | What It Does |
|------|-------------|
| `data_processors/publishing/signal_best_bets_exporter.py` | Orchestrates the entire best bets export |
| `ml/signals/aggregator.py` | Edge-first selection + negative filters |
| `ml/signals/supplemental_data.py` | Queries predictions (multi-model) + supplemental data |
| `ml/signals/registry.py` | Signal registry (18 active signals) |
| `ml/signals/pick_angle_builder.py` | Human-readable pick reasoning |
| `ml/signals/cross_model_scorer.py` | Cross-model consensus computation |
| `shared/config/cross_model_subsets.py` | Model family definitions + classification |
| `shared/config/model_selection.py` | Champion model ID + per-model config |
| `ml/analysis/model_performance.py` | Daily model performance + decay state machine |

---

## Key Numbers

| Metric | Value |
|--------|-------|
| Edge 5+ hit rate | 71.1% |
| Edge 7+ OVER hit rate | 84.5% |
| Post-cleanup aggregator simulation | 73.9% avg HR |
| Breakeven threshold | 52.4% |
| Active signals | 18 |
| Active models | 4 (V9 champion + V12 + 2 quantile shadows) |
| Predictions per game day | ~75 |
| Best bets per game day | 2-8 (natural sizing) |
