# Open Questions — Research Agenda

## Q1: Should Models Have Per-Model Filter Criteria?

**Current state:** All models go through the same filter stack (30+ filters). Filters were calibrated on V9/V12 historical data.

**Hypothesis:** Different models have different failure modes. A filter that's critical for V9 (e.g., AWAY block) might not apply to V16. Applying V9-calibrated filters to V16 is either:
- (a) Unnecessarily restrictive (blocking good V16 picks)
- (b) Insufficiently restrictive (missing V16-specific failure modes)

**Investigation approach:**
1. For each model with sufficient graded data (N >= 30 edge 3+), compute HR by:
   - Direction (OVER/UNDER)
   - Home/Away
   - Edge band (3-5, 5-7, 7+)
   - Line range (low <15, mid 15-25, high 25+)
   - Player tier (star/starter/role/bench)
2. Compare profiles across models
3. Identify where one-size-fits-all filters hurt

**The model_profile_daily system (Session 384-385) already collects this data** but is in observation mode only. Check if enough data has accumulated for per-model decisions.

**Comparison framework:** Even with per-model criteria, we need a common evaluation metric. Candidates:
- Best bets HR (only works if model sources picks)
- Simulated best bets HR (compute as if model won selection)
- Expected value = edge × P(win) — combines edge and accuracy
- Profit contribution = sum of (wins × unit - losses × 1.1 unit)

## Q2: How Should We Evaluate a Model's "Top Pick" Quality?

**The problem:** We currently evaluate models by:
1. Overall HR (edge 3+) — raw prediction quality
2. Best bets HR — quality after filter stack
3. Monthly HR trends — decay detection

**What's missing:**
- **Simulated filter pass-through rate:** If we applied filters to ALL of a model's predictions (not just the one that won selection), what % would pass? What would the HR be?
- **Edge-adjusted HR:** Instead of raw HR, compute `expected_profit = Σ (edge × correct) - Σ (edge × incorrect)`. A model that's right at high edge and wrong at low edge is more valuable than the reverse.
- **Marginal contribution:** What does each model ADD to the best bets pool that no other model provides? If model A and model B agree 95% of the time, one is redundant.

**Proposed "Top Pick Score":**
```
top_pick_score = edge_3plus_hr × filter_pass_rate × diversity_bonus
```
Where:
- `edge_3plus_hr` = graded hit rate on edge 3+ predictions
- `filter_pass_rate` = % of edge 3+ predictions that would pass the filter stack
- `diversity_bonus` = 1.0 + (0.1 × pct_unique_picks) — bonus for picking players others miss

## Q3: How to Find the Best Training Window Per Model?

**Current knowledge:**
- 56-day window is optimal for CatBoost V12_noveg (Session 369)
- 42-day window is the default
- 21-day window is too short (68.5% HR)
- 87-day window is too long (dilutes signal)
- Dec 15 - Jan 14 start date performed best (Session 369)

**What we don't know:**
- Is 56-day optimal for V16? For LightGBM? For vegas-weighted models?
- Does the optimal window change as the season progresses?
- Should we use sliding window validation (train on rolling 56d, eval on next 14d)?
- Does the training end date matter more than the window size? (recency vs volume)

**Investigation approach:**
1. **Grid search across model × window × start_date:**
   ```
   Models: v12_noveg, v12_vegas025, v16_noveg, v16_noveg_rec14
   Windows: 35d, 42d, 49d, 56d, 63d
   Start dates: Dec 1, Dec 15, Jan 1, Jan 7, Jan 14
   Eval: Feb 15 - Mar 2
   ```
2. **Cross-validation:** For each config, train 3 times with different seeds and report mean ± std
3. **Metric:** Edge 3+ HR on eval period (primary), also report MAE, OVER HR, UNDER HR

**Tools:** `quick_retrain.py --dry-run --machine-output` produces JSON results. `grid_search_weights.py` can orchestrate.

## Q4: Should Selection Use Expected Value Instead of Raw Edge?

**Current:** Rank by `ABS(edge)` after filters. Highest edge wins.

**Alternative:** Rank by `expected_value = ABS(edge) × P(win)`, where `P(win)` is the model's historical HR at that edge band and direction.

**Example:**
- V9 OVER at edge 6.0: P(win) ≈ 0.65 → EV = 3.9
- V16 OVER at edge 3.8: P(win) ≈ 0.70 → EV = 2.66
- V9 UNDER at edge 6.0: P(win) ≈ 0.50 → EV = 3.0
- V16 UNDER at edge 4.0: P(win) ≈ 0.65 → EV = 2.6

In this case, V9 OVER still wins (EV 3.9 > 2.66). But the comparison is now on expected profit, not raw edge.

**Concern:** This requires enough graded data per model × direction × edge band to estimate P(win). Most newer models don't have this yet.

## Q5: Can We Run A/B Testing on Selection Strategies?

**Idea:** Instead of one selection strategy, run two in parallel:
- **Strategy A (current):** Highest edge × HR weight
- **Strategy B (candidate):** Expected value ranking

Both produce picks daily. Grade both. Compare after 2-4 weeks.

**Implementation:**
- `supplemental_data.py` could run two selection queries
- `aggregator.py` could produce two pick sets
- Both written to BQ with different `algorithm_version` tags
- Grading happens on both

**Risk:** Doubles BQ query costs. Also, Strategy B might select different players than Strategy A, making direct comparison hard (different player pools).

**Alternative:** Simulated A/B — run Strategy B on historical data and compare outcomes retroactively. Cheaper and faster, but doesn't capture the stochasticity of live markets.

## Q6: What's the Minimum Viable Fleet?

**Current fleet:** 16 models, but only 4 have graded edge 3+ picks in Feb+. Many models exist but contribute nothing to best bets.

**Questions:**
- What's the minimum number of models needed for profitable best bets?
- Should we prune models that never win selection (reduce compute cost)?
- Or should we keep diverse models for the marginal contribution argument?

**Data needed:** For each enabled model, compute:
- % of days it wins selection for at least 1 player
- When it does win, is it for unique players (no other model would have picked)?
- Its best bets HR when it does win

## Q7: Edge Calibration — Are Edges Meaningful Probabilities?

**The problem:** Edge (predicted_points - line) is used as a proxy for P(win), but there's no evidence it's calibrated. A model predicting edge=4 may have a true win probability of 55% or 75% — the raw number doesn't tell you.

**Investigation:**
1. For each model, bin predictions by edge (1-2, 2-3, 3-5, 5-7, 7+) and compute empirical HR per bin. Do the curves slope monotonically? Do they agree across models?
2. Apply isotonic regression or Platt scaling per model to convert raw edge into calibrated P(win).
3. If two models both show edge=4 but Model A has empirical 58% HR at that edge and Model B has 71%, Model B's pick is worth ~2x as much. The current system treats them identically.

**Note:** Session 370 tried isotonic regression on edge→P(win) at the raw prediction level and found ~51% everywhere (flat). But this was BEFORE the filter stack. The question is whether calibration works AFTER filtering, where the population is more selective.

## Q8: Prediction Correlation — Are 16 Models Actually 3?

**The problem:** If CatBoost V12_noveg and V12_vegas produce r=0.97 correlated predictions on the same players, the "multi-model" fleet has near-zero ensemble benefit — it's one model wearing different hats.

**Investigation:**
1. Compute pairwise prediction agreement rate (same player, same direction) across all models on the same game dates.
2. Compute per-player correlation of predicted_points between model pairs (not just direction).
3. Build a correlation heatmap. Identify true diversity clusters vs redundant variants.

**We already know** from CLAUDE.md: "V9+V12 agreement is ANTI-correlated with winning. diversity_mult removed." This suggests models are correlated enough that agreement means nothing new. But we haven't systematically measured HOW correlated.

**Key data source:** `prediction_accuracy` has predictions from all models on the same player-games. Join on (player_lookup, game_id) across system_ids to compute correlations.

## Q9: Filter Temporal Stationarity — When Were Filters Last Validated?

**The problem:** The filter stack was built over 50+ sessions spanning 3 months. Filters calibrated on Nov-Dec data may not apply post-ASB. We already disabled `b2b_fatigue_under` (39.5% Feb HR after being profitable in Jan) and `prop_line_drop_over` (conceptually backward). What other filters have degraded?

**Investigation:**
For each of the 14 negative filters:
1. Compute HR in three periods: Nov-Dec, Jan, Feb
2. Rank filters by HR degradation from Jan to Feb
3. For each filter, compute: N_removed_last_30d, N_would_have_won, effective_HR_if_kept

**Data source:** `best_bets_filter_audit` table has per-game-date rejection counts. Cross-reference with `prediction_accuracy` to determine if removed picks would have won.

**`post_filter_eval.py` already exists** for this — run it on a rolling 14d window.

## Q10: Kelly Criterion / Position Sizing

**Current:** All best bets are flat 1-unit bets. With a known edge structure (7+: 81.3% HR, 5-7: 63.4%), variable position sizing based on edge band could significantly improve long-run returns.

**Investigation:**
1. At -110 odds (implied 52.4%), compute fractional Kelly for each edge band using empirical P(win)
2. Simulate historical returns using flat vs quarter-Kelly sizing on graded best bets data
3. Determine if variance is acceptable

**Prerequisite:** Edge calibration (Q7) — Kelly requires reliable P(win) estimates. Using raw edge as P(win) without calibration produces overbetting and ruin risk.

## Q11: Feature Importance Drift Between Retrains

**The problem:** When we retrain, we check backtest HR but don't systematically track feature importance evolution. A feature that was #1 in the Nov retrain might be #8 in the Feb retrain — that's a signal about market regime change.

**Investigation:**
1. After each retrain, store the feature importance vector in `ml_experiments` table
2. Compare top-5 features between consecutive retrains
3. Alert if any feature's importance drops >50% (data quality issue?) or a new feature jumps into top-5 (regime change?)
4. Specifically check: does `usage_spike_score` (47% of drift per adversarial validation) still appear as important post-ASB, or has its variance collapsed?

## Q12: Shadow Monitoring for Disabled Models

See `05-SHADOW-MONITORING.md` for full design. Key question: should disabled models continue generating predictions in shadow mode so we can track how their best bets / ultra bets would have performed? This prevents information loss and catches regime changes where a disabled model would have recovered.

## Summary: Next Session Action Items

### Priority 1: Build Missing Tools
1. **Build `simulate_best_bets.py`** — simulate any model through the full best bets pipeline. Highest-impact missing tool.
2. **Add training window sweep template** to `grid_search_weights.py`
3. **Add bootstrap CI utility** — `bin/bootstrap_hr.py` for statistical significance

### Priority 2: Analysis
4. **Run simulated filter pass-through** for each model — "if this model won selection, how would its picks perform after filters?"
5. **Edge calibration analysis** — bin edge → empirical HR per model. Are edges calibrated?
6. **Prediction correlation heatmap** — how correlated are models? Is the fleet actually diverse?
7. **Filter temporal audit** — which filters have degraded since calibration?
8. **Compute per-model quality profiles** from `model_profile_daily` data

### Priority 3: Decisions
9. **Training window grid search** for V16 specifically (best family, needs fresh data)
10. **Evaluate SC=3 elimination** impact on P&L and volume
11. **Prototype expected value ranking** vs current edge ranking on historical data
12. **Decide on per-model vs uniform filters** based on profile data
13. **Design shadow monitoring** approach (Option A/B/C) for disabled models
