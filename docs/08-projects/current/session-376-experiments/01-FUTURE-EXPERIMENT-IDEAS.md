# Future Experiment Ideas

**Date:** 2026-03-01
**Context:** CatBoost V12 model architecture is exhausted — all configs produce ~65% HR within 5pp. The filter/signal stack provides the remaining alpha. Future gains must come from new data, new algorithms, or system-level innovations.

## What's Been Exhausted (Don't Revisit)

The following dimensions have been thoroughly explored and produce no further gains:
- **Training window:** 35-63d all equivalent (±2pp)
- **Feature sets:** V12 > V13 > V15 > V16 > V17 (adding features consistently hurts)
- **Vegas weight:** 0.15 is optimal (validated cross-season)
- **Quantile loss:** Q43/Q55/Q57 all catastrophic live (<20% HR)
- **Direction-specific models:** Feature distributions identical OVER/UNDER
- **Edge thresholds by model age:** Calendar date, not age, drives HR
- **Ensemble of same-framework models:** No diversity = no benefit
- **Binary classification:** AUC 0.507 = random
- **Feature engineering within existing data:** D11, D12, V15, V16, V17 all <1% importance or hurt

## Tier 1: High-Impact, Feasible Now

### 1. Alternative ML Framework: XGBoost

**Why:** LightGBM showed genuine feature diversity from CatBoost (different top features). XGBoost is the remaining major gradient boosting framework untested.

**Method:** Add XGBoost to `quick_retrain.py` alongside CatBoost/LightGBM. Same training pipeline, same eval. Compare feature importance and prediction correlation with CatBoost.

**Expected value:** If XGBoost predictions are <0.9 correlated with CatBoost, a true ensemble becomes viable (unlike the window-based ensemble which was >0.99 correlated).

**Risk:** LightGBM already failed cross-season (55.8% on N=545). XGBoost may too.

**Effort:** Medium (framework integration exists for LightGBM, XGBoost follows same pattern).

### 2. Adaptive Filter Stack

**Why:** The filter stack (signal count, model affinity, direction blocks, opponent blocks) provides more alpha than the model itself. But filter parameters are static — set once and never adjusted.

**Method:**
1. Build a rolling filter health dashboard that tracks each filter's contribution weekly
2. Auto-disable filters whose pass-through HR drops below breakeven (52.4%) on 30+ samples
3. Auto-tighten filters whose blocked population HR drops significantly
4. Implement as a "filter regime" system similar to signal health regimes

**Expected value:** Catch filter decay early. The `b2b_fatigue_under` signal took weeks to identify as harmful (39.5% Feb HR). Automated detection would catch this in days.

**Risk:** Over-fitting filters to recent noise. Need minimum sample sizes.

**Effort:** Medium. Infrastructure exists in `signal_health_daily` — extend pattern to filters.

### 3. Closing Line Value (CLV) Integration

**Why:** CLV (how the line moves between prediction time and game time) is the gold standard for prediction quality in sports betting. A positive CLV means the market moved in your direction, confirming your edge was real.

**Method:**
1. Capture final lines at game time (scraper already runs pre-game)
2. Calculate CLV = final_line - prediction_time_line
3. Use CLV as a post-hoc filter: only count predictions where CLV > 0 as "real edges"
4. Eventually use CLV as a feature for the model itself

**Expected value:** Separate real edges from noise. Predictions with positive CLV should have significantly higher HR.

**Risk:** Data availability — need reliable final lines. The Odds API may not provide closing lines.

**Effort:** Medium-High. Scraper changes + new pipeline.

### 4. Player Tracking Data Features

**Why:** All current features are box-score derived. Player tracking data (speed, distance, touches, contested shots) is a genuinely different data source that could break the feature importance ceiling.

**Method:**
1. Scrape NBA.com player tracking data (hustle stats, shooting zones, drives, catch-and-shoot)
2. Build rolling averages (last 5/10 games)
3. Add as V18 feature set
4. Test if any feature achieves >2% importance (the threshold where features start mattering)

**Expected value:** Player tracking captures information that box scores miss — effort level, shot quality, defensive attention. These are orthogonal to current features.

**Risk:** Data may not be consistently available. NBA.com tracking endpoints change frequently.

**Effort:** High. New scraper + feature engineering + feature store expansion.

## Tier 2: Medium-Impact, Worth Investigating

### 5. Regime-Aware Model Selection

**Why:** February's structural decline (usage_spike_score collapse, OVER HR crash) is a known regime shift. If we can detect regime changes in real-time, we can switch model selection strategies.

**Method:**
1. Build a regime classifier using the adversarial validation approach from Session 370
2. Monitor `usage_spike_score` distribution daily — when it drops below 0.5 (from 1.14 baseline), declare "late-season regime"
3. In late-season regime: raise edge floor to 5+, favor UNDER, increase signal count minimum
4. In early-season regime: standard parameters

**Expected value:** Could have prevented the Feb OVER disaster if implemented in early February.

**Risk:** Overfitting to one season's pattern. Regime classification is easy in hindsight, hard in real-time.

**Effort:** Medium. Monitoring infrastructure exists; regime rules need research.

### 6. Transfer Learning from Previous Seasons

**Why:** We have full feature store data from 2024-25 season. Cross-season validation showed 56d window is stable. But we've never tried pre-training on last season and fine-tuning on current season.

**Method:**
1. Train a base model on 2024-25 season data (all of it)
2. Fine-tune on current season data (standard 42-49d window)
3. CatBoost doesn't natively support fine-tuning, but we can: use previous season's model as initialization, or use its predictions as a feature

**Expected value:** If seasonal patterns are stable, the base model provides a prior that reduces variance.

**Risk:** Seasonal patterns may shift (rule changes, pace evolution). Cross-season validation already showed limited value (LightGBM 55.8%).

**Effort:** Medium. Need to design the transfer mechanism for tree-based models.

### 7. Opponent-Adjusted Predictions

**Why:** Current features include `avg_points_vs_opponent` and `opponent_pace`, but don't capture opponent defensive efficiency against specific positions. A guard-heavy defense matters differently for guards vs forwards.

**Method:**
1. Build opponent defensive profiles by position (PG/SG/SF/PF/C)
2. Match player position to opponent's positional defensive rating
3. Add as position-adjusted opponent features (3-5 new features)

**Expected value:** More specific opponent context than the current generic `opponent_pace`.

**Risk:** Position data may be inconsistent (modern NBA positions are fluid).

**Effort:** Medium. Position data available from box scores.

### 8. Prop Line Market Inefficiency Detection

**Why:** The `line_rising_over` signal (96.6% HR) shows that market movement is highly predictive. Extending this to detect systematic market inefficiencies could be powerful.

**Method:**
1. Track line movements across multiple books (DraftKings, FanDuel, BetMGM, etc.)
2. Build a "market consensus shift" feature: when 3+ books move in the same direction
3. Build a "contrarian" feature: when our model disagrees with market consensus
4. Track which books are leading indicators vs lagging

**Expected value:** Market microstructure provides real-time information not captured in features.

**Risk:** Already somewhat captured by `multi_book_line_std` (2.77% feature importance). May be incremental.

**Effort:** Medium. Odds API data already collected; need new feature engineering.

## Tier 3: Speculative / Long-Term

### 9. Neural Network Ensemble Member

**Why:** Tree-based models (CatBoost, LightGBM, XGBoost) all partition feature space similarly. A neural network learns fundamentally different patterns (continuous functions, interactions).

**Method:**
1. Simple feedforward NN with same features as V12
2. Use as one vote in a diverse ensemble (CatBoost + NN)
3. Focus on whether NN predictions are decorrelated from CatBoost (<0.85 correlation)

**Expected value:** True model diversity for ensemble. If correlation is low, even a mediocre NN improves the ensemble.

**Risk:** NNs typically underperform gradient boosting on tabular data with <10K samples. May need hyperparameter tuning.

**Effort:** Medium. PyTorch/TF implementation is straightforward with existing feature pipeline.

### 10. Dynamic Bankroll / Kelly Criterion

**Why:** Currently all picks are flat 1-unit bets. Kelly criterion sizes bets proportional to edge, maximizing long-term growth rate.

**Method:**
1. Calibrate edge → win probability mapping (requires >200 graded picks per edge bucket)
2. Implement fractional Kelly (0.25-0.5 Kelly for safety)
3. Size bets: `bet_size = (p * odds - 1) / (odds - 1)` where p = calibrated win probability

**Expected value:** Same picks, better sizing. High-edge picks get more capital. Could significantly improve unit profit.

**Risk:** Calibration requires large sample. Miscalibration leads to overbetting.

**Effort:** Low (analytics only, no pipeline changes). But needs enough graded data per edge bucket.

### 11. Live/In-Game Predictions

**Why:** Pre-game predictions miss information available after tipoff (early foul trouble, hot/cold shooting, injury during game). First-quarter performance is predictive of full-game totals.

**Method:**
1. Build Q1 scoring rate features (points/minute in Q1 vs season average)
2. Update predictions at end of Q1 with live performance data
3. Target "live" prop markets that remain open through Q1

**Expected value:** First-quarter performance is a strong signal for full-game outcome. Could identify in-game over/under opportunities.

**Risk:** Requires real-time data pipeline. Latency matters. Live betting odds adjust quickly.

**Effort:** Very high. New infrastructure (real-time scraping, sub-minute predictions).

### 12. Multi-Sport Expansion (MLB Strikeouts)

**Why:** The entire pipeline architecture (scrapers → feature store → CatBoost → signal filtering → best bets) is sport-agnostic. MLB pitcher strikeouts have similar dynamics to NBA points props.

**Method:**
1. Adapt scrapers for MLB data sources
2. Build pitcher-specific feature store (K rate, opponent lineup quality, park factors)
3. Same CatBoost MAE + signal filter architecture

**Expected value:** Revenue diversification. MLB season runs Apr-Oct when NBA is off. Same infrastructure investment.

**Risk:** Different sport, different dynamics. MLB props may be more efficient (deeper markets).

**Effort:** High. Full pipeline build for new sport.

## Prioritized Roadmap

| Priority | Experiment | Effort | Expected Value | When |
|----------|-----------|--------|----------------|------|
| 1 | Adaptive Filter Stack (#2) | Medium | High | Now |
| 2 | XGBoost Framework (#1) | Medium | Medium-High | Next session |
| 3 | Prop Line Market Inefficiency (#8) | Medium | Medium | Next 2 sessions |
| 4 | CLV Integration (#3) | Medium-High | High | When data available |
| 5 | Regime-Aware Selection (#5) | Medium | Medium | After more Feb data |
| 6 | Player Tracking (#4) | High | High | When bandwidth allows |
| 7 | Dynamic Bankroll (#10) | Low | Medium | After 200+ graded picks per edge bucket |
| 8 | Opponent-Adjusted (#7) | Medium | Low-Medium | Low priority |
| 9 | Neural Network (#9) | Medium | Low-Medium | Speculative |
| 10 | Transfer Learning (#6) | Medium | Low | Speculative |
| 11 | Live Predictions (#11) | Very High | High | Long-term |
| 12 | Multi-Sport (#12) | High | High | Off-season |
