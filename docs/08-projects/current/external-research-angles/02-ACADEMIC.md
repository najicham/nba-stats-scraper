# Academic & Research Findings

## Summary

Comprehensive survey of academic papers, arXiv preprints, and formal research on NBA player performance prediction, sports betting ML, and market inefficiency. Searched across Google Scholar, arXiv, PubMed, Springer, and MDPI for 2022-2026 publications. Found 10 unique research-backed angles spanning calibration methods, state detection, travel/circadian features, spatial lineup modeling, conformal prediction intervals, copula-based multivariate modeling, referee features, Bayesian hierarchical models, sharp money detection, and multi-task Gaussian processes.

**Key meta-finding:** The single highest-impact research finding is that **model calibration matters more than accuracy for betting profitability** (Walsh & Joshi 2024: +34.69% ROI calibrated vs -35.17% accuracy-optimized). This is directly actionable and does not overlap with any tested dead end.

---

## Angles Found

### Angle 1: Calibration-Optimized Model Selection (Instead of MAE/Accuracy)

- **Source:** "Machine learning for sports betting: should model selection be based on accuracy or calibration?" — Walsh & Joshi, 2024. [arXiv:2303.06021](https://arxiv.org/abs/2303.06021)
- **Description:** Trained multiple ML models on NBA data across seasons. Instead of selecting models by accuracy or MAE, they selected by calibration (predicted probabilities match actual outcome frequencies). Calibration-optimized models produced +34.69% ROI vs -35.17% ROI for accuracy-optimized models. The best calibration-selected model achieved +36.93% ROI. The insight: a model can be "accurate" in point prediction but poorly calibrated for bet sizing — and calibration determines profitability.
- **Claimed Edge:** +34.69% ROI (vs -35.17% for accuracy-based selection) — 69.86% higher average returns
- **Direction:** BOTH
- **Data Required:** Existing prediction outputs + prop lines. Need to compute calibration scores (Platt scaling, temperature scaling, or Venn-ABERS) on top of existing CatBoost/LightGBM/XGBoost outputs.
- **Have It?** PARTIAL — We have multi-model outputs but select by edge magnitude, not calibration. We have never measured per-model calibration curves.
- **Dead End Overlap:** NONE. Isotonic regression calibration was tested (flat ~51%), but that was calibrating edge->P(win) at the raw prediction level. This angle is about MODEL SELECTION based on calibration scores, not calibrating individual predictions. Different approach entirely. Temperature scaling and Platt scaling are also different calibration methods from isotonic regression.
- **Complexity:** MEDIUM — Need to compute calibration metrics per model (Brier score decomposition, reliability diagrams), then use calibration quality as a model weighting/selection signal in the aggregator. No new data sources needed.
- **Actionability:** HIGH. Could implement per-model Brier score tracking in `model_performance_daily` table and use calibration score as a factor in per-player model selection (alongside HR weighting). Alternatively, use Venn-ABERS predictors to generate calibrated probability intervals from existing CatBoost outputs.

---

### Angle 2: Hidden Markov Model for Hot/Cold Player State Detection

- **Source:** "Can the hot hand phenomenon be modelled? A Bayesian hidden Markov approach" — Maniaci et al., 2024. [arXiv:2303.17863](https://arxiv.org/abs/2303.17863). Published in Computational Statistics (Springer).
- **Description:** Uses a 2-state Bayesian Hidden Markov Model to detect whether a player/team is in a "hot" or "cold" latent state. The model infers hidden states from observed shot sequences, with state-dependent success probabilities. Applied to Miami Heat 2005-06 data. Key finding: the HMM detected genuine streakiness — real data showed significantly larger hot/cold state spreads than randomized simulations. Baseball research (FiveThirtyEight, same methodology) found pitchers average 57 state transitions per season, shifting ~2 mph between hot/cold.
- **Claimed Edge:** Statistically significant detection of real performance states (not random noise). In baseball, ~2 mph velocity difference between states. Basketball: shot probability differences between states are large enough to be actionable.
- **Direction:** BOTH — Hot state = OVER signal, Cold state = UNDER signal
- **Data Required:** Recent game-by-game scoring sequences per player (last 10-20 games). We have this in `player_game_summary`. For richer signal: shot-level play-by-play data from BigDataBall.
- **Have It?** YES — Player game summaries + BigDataBall PBP data. Could compute HMM states from rolling game-by-game points sequences.
- **Dead End Overlap:** NONE. We have `scoring_cold_streak_over` signal but it is a simple threshold (below avg last 5 games). HMM is a fundamentally different statistical framework that estimates latent states with transition probabilities, not arbitrary thresholds.
- **Complexity:** MEDIUM — Implement 2-state HMM per player using `hmmlearn` Python library. Compute state probabilities daily from recent game history. Export as feature or signal (`hmm_hot_state`, `hmm_cold_state`). No new scrapers needed.
- **Actionability:** HIGH. Could add `hmm_player_state` as a signal. Hot state probability > 0.7 = OVER signal, Cold state probability > 0.7 = UNDER signal. Transition probability itself (likelihood of state change) could also be a feature.

---

### Angle 3: Circadian Rhythm / Time Zone Crossing as Predictive Feature

- **Source:** "Investigation of the effect of circadian rhythm on the performances of NBA teams" — Akbulut et al., 2024. Published in Chronobiology International. Also: "Impacts of travel distance and travel direction on back-to-back games" — Charest et al., 2021. [PMC8636381](https://pmc.ncbi.nlm.nih.gov/articles/PMC8636381/). Also: "Eastward Jet Lag is Associated with Impaired Performance" — 2022. [PMC9245584](https://pmc.ncbi.nlm.nih.gov/articles/PMC9245584/).
- **Description:** Analysis of 25,016 NBA games over 21 seasons (2000-2021). Pacific time zone teams hosting Eastern opponents won 63.5% of games vs only 55.0% when Eastern teams hosted Pacific teams — an 8.5 percentage point gap attributable to circadian mismatch. Eastward travel is worse than westward. Every 500km of travel reduces B2B win probability by 4%. Body needs ~24 hours per time zone crossed to adapt. Game sequence matters: Away-Home = 54.4% wins, Home-Away = 36.8% wins.
- **Claimed Edge:** 8.5pp win rate difference based on circadian alignment. 4% win probability reduction per 500km on B2B. Eastward travel significantly worse than westward (P=0.024).
- **Direction:** BOTH — Circadian-disadvantaged player = UNDER, advantaged = OVER
- **Data Required:** Team home timezone, opponent home timezone, travel distance between venues, days since last away game in different timezone, direction of travel (east/west). Schedule data we already have.
- **Have It?** PARTIAL — We have schedule data and home/away status. We attempted `arena_timezone` (C9 feature) but it was ALL NULL in our data. However, we can DERIVE timezone from team tricode (e.g., LAL=Pacific, BOS=Eastern). Travel distance can be computed from arena coordinates (static lookup table). We do NOT currently track time zones crossed or circadian direction.
- **Dead End Overlap:** PARTIAL — `arena_timezone` (C9) was a dead end because the column was NULL. But this angle uses DERIVED timezone from team names (not a scraped field). `rest_advantage_2d` signal exists but was disabled — it measures rest days, NOT circadian/timezone direction. `b2b_boost_over` exists but does not account for travel direction. This is a refinement that adds timezone-awareness to existing rest features.
- **Complexity:** LOW-MEDIUM — Create static lookup table (30 teams -> timezone). Compute `timezone_delta` (home team TZ - away team TZ), `travel_direction` (east/west), `circadian_advantage` per game. Add as feature or signal. No new scrapers needed.
- **Actionability:** HIGH. Could implement as: (1) feature: `circadian_mismatch_hours` = |player_home_tz - game_tz| when away, (2) signal: `circadian_disadvantage_under` when away team crossed 2+ time zones eastward within 48h. Static team-to-timezone mapping is trivial.

---

### Angle 4: Conformal Prediction Intervals for Bet Sizing / Filtering

- **Source:** "A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification" — Angelopoulos & Bates, 2022. [arXiv:2107.07511](https://arxiv.org/abs/2107.07511). Also: "Adaptive Conformal Predictions for Time Series" — Zaffran et al., 2022. [ICML 2022](https://proceedings.mlr.press/v162/zaffran22a/zaffran22a.pdf). Also: "Using Conformal Win Probability to Predict the Winners of the Canceled 2020 NCAA Basketball Tournaments" — 2023. [American Statistician](https://www.tandfonline.com/doi/full/10.1080/00031305.2023.2283199). Also: "Relaxed Quantile Regression: Prediction Intervals for Asymmetric Noise" — 2024. [arXiv:2406.03258](https://arxiv.org/abs/2406.03258).
- **Description:** Conformal prediction wraps ANY point prediction model (including CatBoost) with distribution-free prediction intervals that have guaranteed finite-sample coverage. Unlike CatBoost's virtual ensembles (which we tested and found seed-dependent), conformal prediction is model-agnostic and provides valid coverage guarantees regardless of the underlying model. Key innovation: Adaptive Conformal Inference (ACI) handles non-stationary/time-series data (our 56-day rolling window problem) by dynamically adjusting interval width using online learning. A "Relaxed Quantile Regression" variant handles asymmetric noise (player scoring is right-skewed). For betting: narrow conformal intervals = high confidence = better bet quality. Wide intervals = uncertain = avoid.
- **Claimed Edge:** Guaranteed coverage at specified level (e.g., 90%). NCAA basketball application showed improved win probability calibration. Adaptive version maintains coverage even under distribution shift (our February degradation problem).
- **Direction:** BOTH — Used as a filter/confidence measure, not direction-specific
- **Data Required:** Existing CatBoost/LightGBM/XGBoost predictions + actuals from recent calibration window. No new external data needed.
- **Have It?** YES — We have all prediction history and actuals in `prediction_accuracy`.
- **Dead End Overlap:** PARTIAL — We tested CatBoost virtual ensembles / uncertainty quantiles (Q1-Q4 gap reversed on 4/5 seeds). But conformal prediction is FUNDAMENTALLY DIFFERENT: it is model-agnostic, wraps the model externally, and provides formal coverage guarantees. CatBoost's internal uncertainty was model-specific and unreliable. Conformal prediction works on top of ANY model's point predictions.
- **Complexity:** MEDIUM — Use `mapie` Python library (conformal prediction for sklearn-compatible models). Compute conformal interval width per prediction. Add as feature (`conformal_interval_width`) or filter (reject predictions with interval > threshold). Adaptive variant needs rolling calibration window (we already use 56-day windows).
- **Actionability:** HIGH. Most promising use: `conformal_interval_width` as a signal/filter. Predictions where the conformal interval is narrow relative to the edge = high confidence. Could replace or supplement the edge threshold: instead of "edge >= 3", use "edge >= 3 AND conformal_width < X". Also useful for bet sizing (fractional Kelly based on interval width).

---

### Angle 5: Copula-Based Multivariate Player Stat Modeling

- **Source:** "A Bayesian network to analyse basketball players' performances: a multivariate copula-based approach" — Ince, 2022. Published in Annals of Operations Research (Springer). [Springer Link](https://link.springer.com/article/10.1007/s10479-022-04871-5). Also: "A copula-based multivariate hidden Markov model for modelling momentum in football" — Otting et al., 2021. [Springer Link](https://link.springer.com/article/10.1007/s10182-021-00395-8).
- **Description:** Uses Gaussian copulas to model the JOINT distribution of player performance indicators (points, rebounds, assists, etc.) rather than treating them independently. Captures non-linear dependencies between stats that linear correlations miss. Key insight for props: a player's points, rebounds, and assists are NOT independent — they share common latent factors (minutes, pace, game script, role). When a player's assists are unusually high, their points may be predictably lower (or higher, depending on player archetype). The copula approach models these dependencies to produce better marginal predictions.
- **Claimed Edge:** Better prediction of individual stats by accounting for multivariate structure. Bayesian network structure learning identifies which stats are causally linked for each player.
- **Direction:** BOTH — Improved point predictions in both directions
- **Data Required:** Multiple stat categories per player per game (points, rebounds, assists, minutes, FGA, 3PA). Already have in player_game_summary.
- **Have It?** YES — Full box score data in Phase 3 analytics.
- **Dead End Overlap:** NONE. We have never modeled cross-stat dependencies. All current features treat points prediction in isolation.
- **Complexity:** HIGH — Requires fitting copula models per player archetype, extracting conditional distributions (P(points | assists_trend, rebounds_trend, minutes_trend)). Libraries: `copulas` or `pyvinecopula` in Python. Significant implementation effort.
- **Actionability:** MEDIUM. Most practical application: compute "expected points given other recent stat trends" as a feature. E.g., if a player's assists have spiked last 3 games (indicating facilitator role shift), the copula model would predict lower points — useful UNDER signal. Could start with simple correlation-based proxy before full copula implementation.

---

### Angle 6: Referee Crew Foul/Pace Tendencies as Feature

- **Source:** "Quantifying implicit biases in refereeing using NBA referees as a testbed" — 2023. [PMC10031197](https://pmc.ncbi.nlm.nih.gov/articles/PMC10031197/). Also: "With the Game on the (Betting) Line: NBA Referee Performance in the Last Two Minutes" — Belasen et al., 2025. [SAGE Journals](https://journals.sagepub.com/doi/10.1177/15270025251369447). Also: DonaghyEffect.com (referee betting stats database).
- **Description:** NBA referees show measurable, persistent differences in foul calling rates that affect game pace, free throw volume, and total scoring. Higher-foul refs create slower-paced, more free-throw-heavy games. Star players receive preferential treatment: +0.32 FTA/minute in crucial situations (All-Stars vs non-All-Stars). Referee crews are assigned and publicly available before games. Research from 25,000+ games shows referee tendencies are statistically significant and exploitable — sites like DonaghyEffect.com track referee ATS/total trends.
- **Claimed Edge:** Referee tendencies are persistent and measurable. Referee identity explains variance in game totals that is not captured by team/player features alone.
- **Direction:** BOTH — High-foul refs = more FTA = OVER signal for high-FT players. Low-foul refs = faster pace = OVER for pace-dependent scorers.
- **Data Required:** Referee assignments per game (available pre-game from NBA.com), historical referee stats (foul rates, pace tendencies). We have `nbac_referee_game_assignments` table but it was EMPTY for 2025-26 season (scraper pipeline broken, noted Session 396).
- **Have It?** NO — Scraper is broken. `nbac_referee_game_assignments` is empty for current season. Would need to fix scraper or find alternative data source.
- **Dead End Overlap:** PARTIAL — C10 (referee pace) was listed as dead end because `nbac_referee_game_assignments` was empty. The research angle itself is NOT a dead end — the DATA PIPELINE is broken. If the scraper were fixed, referee features have genuine predictive power per academic research.
- **Complexity:** HIGH — Fix referee scraper first, then compute per-referee historical tendencies (rolling foul rate, pace impact, FTA differential). Feature: `ref_crew_foul_tendency`, `ref_crew_pace_impact`. Alternatively: scrape from DonaghyEffect.com or NBA.com referee page.
- **Actionability:** LOW (blocked by data pipeline). If scraper is fixed: MEDIUM actionability. Worth revisiting when referee data pipeline is repaired.

---

### Angle 7: Bayesian Hierarchical Model for Player-Team Interaction Effects

- **Source:** "Expected Points Above Average: A Novel NBA Player Metric Based on Bayesian Hierarchical Modeling" — Elmore et al., 2024. [arXiv:2405.10453](https://arxiv.org/abs/2405.10453). Published in Annals of Applied Statistics. Also: "Analyzing NBA player positions and interactions with density-functional fluctuation theory" — 2025. [Nature Scientific Reports](https://www.nature.com/articles/s41598-025-04953-x). Also: "Measuring individual worker output in a complementary team setting" — 2020. [PLOS ONE](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0237920).
- **Description:** Bayesian hierarchical models capture that player performance is not independent of team context. The EPAA framework clusters teams and players by shooting propensities using posterior distributions, finding that a player's expected points depend on their team's offensive system and the quality of their teammates. The density-functional approach quantifies "player gravity" — how a specific player attracts defensive attention, which affects teammates' open shot rates. Key finding from RPM research: for each 1-unit improvement in average lineup-teammate RPM, a player gains ~0.664 RPM points. This means teammate quality directly inflates/deflates individual stats.
- **Claimed Edge:** Player-team interaction effects explain variance that individual player features miss. Teammate quality shift (trade, injury, lineup change) should adjust predictions.
- **Direction:** BOTH
- **Data Required:** Lineup data (who is playing with whom), teammate quality metrics (RPM or similar), team offensive rating by lineup. We have team context features but NOT lineup-specific interaction effects.
- **Have It?** PARTIAL — We have team-level features and injury/stars-out data. We do NOT have lineup composition features or teammate quality metrics. BigDataBall PBP has lineup tracking (5v5).
- **Dead End Overlap:** NONE. We have never modeled player-teammate interaction effects. Our `stars_out` feature counts missing players but does not model WHO specifically is missing and how that changes the target player's role/usage.
- **Complexity:** HIGH — Would need to compute lineup-specific metrics, model player-teammate interactions, and update daily as lineups shift. Could start with a simpler proxy: "key teammate out" flag (e.g., if player's primary ball-handler is injured, expect usage shift).
- **Actionability:** MEDIUM. Simplest implementation: for each player, track the PPG/usage of their top 2-3 teammates. When a key teammate is out, compute expected usage/scoring redistribution. Feature: `teammate_usage_redistribution_score`. Could derive from existing injury + roster data without new scrapers.

---

### Angle 8: Sharp Money / Line Movement Velocity as Prediction Feature

- **Source:** "Inefficient Forecasts at the Sportsbook: An Analysis of Real-Time Betting Line Movement" — Berk & Gureckis, 2023. Published in Management Science (INFORMS). [DOI](https://pubsonline.informs.org/doi/abs/10.1287/mnsc.2022.00456). Also: "Finding Inefficiency in Sports Betting Markets" — NYU Stern. [PDF](https://www.stern.nyu.edu/sites/default/files/assets/documents/con_042958.pdf). Also: "Are Betting Markets Inefficient? Evidence From Simulations and Real Data" — Winkelmann et al., 2024. [SAGE](https://journals.sagepub.com/doi/10.1177/15270025231204997).
- **Description:** Research on 3,681 MLB games with detailed line movement from opening to closing across 4 sportsbooks found exploitable inefficiencies in early line movements. "Steam moves" — sudden, uniform line shifts across multiple books — signal sharp/syndicate action. For player props specifically: when a prop line drops 1+ points within hours of game time while public money is on the other side (reverse line movement), this signals sharp money and is predictive of outcome. Closing Line Value (CLV) is the single best predictor of long-term profitability — beating the closing line by 2% consistently yields ~4% ROI.
- **Claimed Edge:** Simple betting strategies based on line movement yielded significant profit in the Management Science study. CLV of 2% = ~4% ROI long-term. Steam moves are the strongest signal of professional betting activity.
- **Direction:** BOTH — Line moving toward OVER = sharp OVER signal, and vice versa
- **Data Required:** Opening lines, closing lines, and line movement timestamps from multiple sportsbooks. Odds API provides snapshots but not continuous movement.
- **Have It?** PARTIAL — We have `odds_api_*` data with prop lines at scrape time. We compute `prop_line_delta` (line change). We do NOT have continuous line movement, multiple sportsbook comparison for the SAME prop, or CLV tracking (we don't record closing lines).
- **Dead End Overlap:** PARTIAL — `prop_line_drop_over` was disabled (39.1% HR Feb). But that signal used a simple threshold on a single snapshot. This angle is about VELOCITY and DIRECTION of movement across MULTIPLE books, which is fundamentally richer data. `line_rising_over` (96.6% HR) already captures one direction and is our best signal — confirming line movement has predictive power.
- **Complexity:** MEDIUM-HIGH — Need to: (1) store multiple prop line snapshots per day (not just one), (2) compare across books for steam detection, (3) compute line movement velocity. Could start with simple "opening vs current" delta from existing data (we already partially have this).
- **Actionability:** MEDIUM. Simplest first step: systematically track CLV by comparing our prediction-time line vs closing line. This is a model quality metric (like calibration) that requires no new features — just recording closing lines. For steam detection: would need additional Odds API polling (multiple scrapes per day for props). `line_rising_over` at 96.6% already validates line movement as signal.

---

### Angle 9: Multi-Task Gaussian Process for Player Performance Trajectories

- **Source:** "MAGMA: inference and prediction using multi-task Gaussian processes with common mean" — Leroy et al., 2022. Published in Machine Learning (Springer). [Springer Link](https://link.springer.com/article/10.1007/s10994-022-06172-1). Also: "Strategy selection and outcome prediction in sport using dynamic learning for stochastic processes" — Baker & McHale, 2015. Published in Journal of the Operational Research Society. [Springer Link](https://link.springer.com/article/10.1057/jors.2014.137).
- **Description:** Multi-task Gaussian Processes (MTGP) model multiple related time series simultaneously (e.g., multiple players on the same team, or multiple stat categories for one player) sharing information through a common mean process. This improves multiple-step-ahead predictions, especially for players with limited recent data (injury returns, rookies, traded players). Unlike CatBoost which treats each prediction independently, GP captures temporal correlation structure. The MAGMA framework specifically handles the "cold start" problem — predicting performance for players returning from absence by borrowing strength from similar players.
- **Claimed Edge:** Improved multi-step-ahead predictions over independent models. Better uncertainty quantification through posterior distributions. Handles missing data and cold starts naturally.
- **Direction:** BOTH — Improved point prediction + uncertainty bands
- **Data Required:** Player game-by-game scoring time series. Already available.
- **Have It?** YES — Full game logs in player_game_summary.
- **Dead End Overlap:** NONE. We have never used Gaussian Processes. Our rolling averages (5-game, 10-game, season) are crude approximations of what a GP models natively with uncertainty.
- **Complexity:** HIGH — GP fitting is O(n^3) in data points, though sparse approximations exist. Would need `GPyTorch` or `GPflow`. Main challenge: fitting one GP per player per day for 400+ players is computationally expensive. Could limit to "players with recent role changes or injury returns" as a targeted supplement.
- **Actionability:** LOW-MEDIUM. Most practical use case: for players returning from injury (where our current features have 0-3 games of data), use MTGP to predict expected scoring by borrowing from similar players' return trajectories. Feature: `gp_predicted_points`, `gp_uncertainty`. Could also detect trend breaks (GP residuals spike when role changes occur).

---

### Angle 10: Prediction Variance as Feature (Heteroskedastic Modeling)

- **Source:** "Relaxed Quantile Regression: Prediction Intervals for Asymmetric Noise" — 2024. [arXiv:2406.03258](https://arxiv.org/abs/2406.03258). Also: "Uncertainty-Aware Machine Learning for NBA Forecasting in Digital Betting Markets" — Agiomyrgiannakis, 2025. [MDPI Information 17(1):56](https://www.mdpi.com/2078-2489/17/1/56). Also: "Evaluating the effectiveness of machine learning models for performance forecasting in basketball" — 2024. Published in Knowledge and Information Systems (Springer). [Springer Link](https://link.springer.com/article/10.1007/s10115-024-02092-9).
- **Description:** Player scoring variance is heteroskedastic — some players are high-variance (streaky scorers, 3PT-dependent) and others are low-variance (consistent volume scorers). The predicted standard deviation of PPG standard deviations is 7.7x less than actual, meaning models dramatically underestimate variance. Research shows OVER bets on high-variance players and UNDER bets on low-variance players have different expected values even at the same edge. Relaxed Quantile Regression handles asymmetric noise (player scoring is right-skewed — blowout games create positive outliers) better than standard quantile regression. The MDPI paper specifically applies uncertainty-aware ML to NBA betting, finding that incorporating prediction uncertainty improves bet selection.
- **Claimed Edge:** Variance-aware filtering improves bet quality. High-variance players' OVER predictions are riskier but have higher upside. Low-variance players' UNDER predictions are more reliable.
- **Direction:** BOTH — Variance profile affects optimal direction
- **Data Required:** Player scoring variance over recent games (std dev, CV, skewness). Already computable from existing data.
- **Have It?** YES — We have `volatile_scoring_over` signal (81.5% HR) which partially captures this. We have scoring trend features. But we do NOT model per-prediction variance explicitly.
- **Complexity:** LOW-MEDIUM — Compute per-player scoring variance metrics (rolling std dev, CV, skewness, kurtosis of last 10 games). Add as features or use as filter modifiers. Could also use CatBoost's quantile predictions (Q10, Q90) to estimate prediction-specific intervals (different from the global Q55 experiments which were about loss function — this is about using intervals per-prediction as a filter).
- **Actionability:** HIGH. Simplest implementation: (1) Feature: `scoring_cv_last_10` = coefficient of variation of points last 10 games, `scoring_skewness_last_10` = skewness of scoring distribution. (2) Filter: For UNDER bets, prefer low-CV players (more predictable, UNDER more reliable). For OVER bets, prefer moderate-CV (enough variance for upside but not chaotic). (3) Already partially captured by `volatile_scoring_over` signal — could enhance with asymmetry (skewness) information.

---

## Cross-Cutting Themes

### Theme 1: Calibration > Accuracy for Betting
Multiple papers converge on this: optimizing for calibration (predicted probabilities match actual outcomes) produces better betting returns than optimizing for accuracy/MAE. Our current system selects by edge magnitude, which is related but not identical to calibration. Adding per-model Brier score tracking would be a low-cost, high-information addition.

### Theme 2: Non-Stationarity is the Core Challenge
The systematic review (Galekwa et al. 2024) identifies non-stationarity as the top challenge. Our February degradation (usage_spike_score collapse, all models past shelf life) is a textbook example. Conformal prediction with adaptive inference and GP-based trajectory modeling both address this explicitly, unlike our current fixed-window retraining.

### Theme 3: Context Features Beat Stat Features
Papers on travel/circadian effects, referee tendencies, lineup interactions, and line movement all point to the same insight: CONTEXTUAL features (who is reffing, how far did the team travel, which teammates are playing, what is the market doing) often matter more than historical stat aggregates. Our current 64 features are heavily weighted toward historical averages. Adding 2-3 contextual features could provide orthogonal signal.

### Theme 4: Multivariate Modeling is Underexplored
Both copula and Bayesian hierarchical approaches model multiple stats jointly. Our system predicts points in isolation. Even a simple proxy (tracking recent assist/rebound trends as predictors of points shifts) could capture cross-stat dependencies without full copula implementation.

---

## Priority Ranking (Effort vs Impact)

| Priority | Angle | Effort | Expected Impact | Recommendation |
|----------|-------|--------|-----------------|----------------|
| 1 | Calibration-Optimized Selection (Angle 1) | LOW | HIGH | **Do first.** Add Brier score to model_performance_daily. |
| 2 | Conformal Prediction Intervals (Angle 4) | MEDIUM | HIGH | **Do second.** `mapie` library, wrap existing models. |
| 3 | Circadian/Timezone Feature (Angle 3) | LOW | MEDIUM | **Quick win.** Static team-to-TZ lookup, derive feature. |
| 4 | HMM Hot/Cold State (Angle 2) | MEDIUM | MEDIUM | **New signal.** `hmmlearn` library, game-by-game data. |
| 5 | Scoring Variance/Heteroskedasticity (Angle 10) | LOW | MEDIUM | **Enhance existing.** Add CV/skewness features. |
| 6 | Sharp Money / CLV Tracking (Angle 8) | MEDIUM | MEDIUM | **Start with CLV tracking** (closing line recording). |
| 7 | Teammate Interaction (Angle 7) | HIGH | MEDIUM | **Simplified version:** key-teammate-out usage shift. |
| 8 | Copula Cross-Stat (Angle 5) | HIGH | LOW-MED | **Defer.** Start with simple correlation proxy. |
| 9 | Multi-Task GP (Angle 9) | HIGH | LOW-MED | **Defer.** Only for injury-return cold start problem. |
| 10 | Referee Features (Angle 6) | HIGH | MEDIUM | **Blocked.** Fix scraper first, then revisit. |

---

## Sources

### Systematic Reviews
- [A Systematic Review of Machine Learning in Sports Betting (2024)](https://arxiv.org/abs/2410.21484)

### Calibration & Model Selection
- [Machine learning for sports betting: should model selection be based on accuracy or calibration? (2024)](https://arxiv.org/abs/2303.06021)

### Bayesian & Hierarchical Models
- [Expected Points Above Average: Bayesian Hierarchical Modeling (2024)](https://arxiv.org/abs/2405.10453)
- [Bayesian network to analyse basketball players: multivariate copula-based approach (2022)](https://link.springer.com/article/10.1007/s10479-022-04871-5)

### Hidden Markov / State Detection
- [Can the hot hand phenomenon be modelled? A Bayesian hidden Markov approach (2024)](https://arxiv.org/abs/2303.17863)

### Conformal Prediction
- [A Gentle Introduction to Conformal Prediction (2022)](https://arxiv.org/abs/2107.07511)
- [Adaptive Conformal Predictions for Time Series (2022)](https://proceedings.mlr.press/v162/zaffran22a/zaffran22a.pdf)
- [Using Conformal Win Probability for NCAA Basketball (2023)](https://www.tandfonline.com/doi/full/10.1080/00031305.2023.2283199)
- [Relaxed Quantile Regression: Prediction Intervals for Asymmetric Noise (2024)](https://arxiv.org/abs/2406.03258)

### Travel / Circadian Effects
- [Time zones and tiredness strongly influence NBA results — 25,000 matches (2024)](https://www.sciencedaily.com/releases/2024/05/240501091642.htm)
- [Impacts of travel distance and direction on B2B games (2021)](https://pmc.ncbi.nlm.nih.gov/articles/PMC8636381/)
- [Eastward Jet Lag and NBA Performance (2022)](https://pmc.ncbi.nlm.nih.gov/articles/PMC9245584/)
- [Negative Influence of Air Travel on NBA Performance (2018)](https://pmc.ncbi.nlm.nih.gov/articles/PMC6162549/)

### Market Efficiency & Line Movement
- [Inefficient Forecasts at the Sportsbook: Real-Time Betting Line Movement (2023)](https://pubsonline.informs.org/doi/abs/10.1287/mnsc.2022.00456)
- [Finding Inefficiency in Sports Betting Markets — NYU Stern](https://www.stern.nyu.edu/sites/default/files/assets/documents/con_042958.pdf)
- [Are Betting Markets Inefficient? (2024)](https://journals.sagepub.com/doi/10.1177/15270025231204997)
- [Optimal sports betting strategies in practice (2021)](https://arxiv.org/pdf/2107.08827)
- [Asset Pricing and Sports Betting — Moskowitz](https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2021/08/AssetPricingandSportsBetting_JF.pdf)

### Player Interactions & Spatial Features
- [NBA player positions and interactions via density-functional fluctuation theory (2025)](https://www.nature.com/articles/s41598-025-04953-x)
- [Offensive Lineup Analysis via Clustering (2024)](https://arxiv.org/html/2403.13821v1)

### Referee Effects
- [Quantifying implicit biases in NBA refereeing (2023)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10031197/)
- [NBA Referee Performance in the Last Two Minutes (2025)](https://journals.sagepub.com/doi/10.1177/15270025251369447)

### Uncertainty & Variance
- [Uncertainty-Aware Machine Learning for NBA Forecasting (2025)](https://www.mdpi.com/2078-2489/17/1/56)
- [Evaluating ML models for performance forecasting in basketball (2024)](https://link.springer.com/article/10.1007/s10115-024-02092-9)

### Gaussian Processes
- [MAGMA: Multi-task Gaussian Processes (2022)](https://link.springer.com/article/10.1007/s10994-022-06172-1)
- [Gaussian processes for time-series modelling (2013)](https://royalsocietypublishing.org/doi/10.1098/rsta.2011.0550)

### Kelly Criterion & Staking
- [Kelly Criterion Extension: Advanced Gambling Strategy (2024)](https://www.mdpi.com/2227-7390/12/11/1725)
- [Optimal Betting Under Parameter Uncertainty (2013)](https://ideas.repec.org/a/inm/ordeca/v10y2013i3p189-199.html)

### Feature Engineering
- [Beyond the Box Score: Feature Engineering for NBA Props (2026)](https://techbuzzireland.com/2026/02/02/beyond-the-box-score-feature-engineering-for-predictive-sports-models-focusing-on-nba-player-props-and-advanced-metrics/)
- [XGBoost + SHAP for NBA game prediction (2024)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11265715/)
- [Key Factors Influencing NBA Game Outcomes (2025)](https://www.preprints.org/manuscript/202504.1348)
