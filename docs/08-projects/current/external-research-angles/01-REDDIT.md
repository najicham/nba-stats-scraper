# Reddit & Community Player Props Research

**Date:** 2026-03-03
**Methodology:** Web searches targeting r/sportsbook, r/PrizePicks, r/sportsbetting, and sports betting analytics blogs. Direct Reddit access was blocked by crawler restrictions, so findings were gathered from community-adjacent sources: betting strategy sites, academic papers, analytics blogs, and sports data science articles that reference and synthesize Reddit/Discord community strategies.

## Summary

Eight actionable angles were identified from community discussions and analytics sources. The strongest quantified angles center on: (1) backup-to-starter usage boosts after injuries, (2) blowout risk / large spread UNDER for starters, (3) pace-up spots for OVER, (4) early-season Week 1 UNDER totals bias, (5) age-stratified B2B fatigue, (6) post-trade-deadline role adjustment lag, (7) closing line value as meta-signal, and (8) secondary stat (steals/blocks) UNDER value. Most angles align with existing data sources but some require new features or data.

## Angles Found

---

### Angle 1: Backup-to-Starter Usage Boost (Injury Replacement OVER)

- **Source:** Multiple betting strategy sites (nba-prop-bets.com, bettoredge.com, betnow.eu), synthesizing common r/sportsbook and r/PrizePicks advice
- **Description:** When a starter is ruled out, the backup who inherits the role sees a 4-7% usage rate increase and 6-10 additional minutes. Sportsbooks set the replacement player's line based on their historical bench role averages, creating a systematic lag. A backup center averaging 6 rebounds in 18 minutes might get a line of 7.5 when starting, but 32 minutes gives realistic upside to 10+. The pricing inefficiency is largest in the first 1-2 games of the absence before books adjust.
- **Claimed Edge:** Usage rate increase of 4-7%, minutes increase of ~50% (e.g., 20 to 30 min). No specific HR% claimed, but described as "some of the most profitable opportunities in NBA prop betting." Assists adjustment is reportedly slower than scoring line adjustment, creating wider OVER value on assists props.
- **Direction:** OVER
- **Data Required:** Injury report data (who is out), player minutes history, usage rate data, starter/bench role classification, per-minute production rates
- **Have It?** PARTIAL -- We have injury data (`nba_raw.nbac_injury_report`), player game logs, and minutes. We do NOT currently track per-minute production rates or compute "expected minutes given injury context" as a feature. We have `stars_out` count but not granular "who replaces whom" logic.
- **Dead End Overlap:** NONE -- This is distinct from our tested angles. Our `opponent_depleted_under` filter blocks UNDER when 3+ opponent stars are out (different direction and player focus).
- **Complexity:** HIGH -- Requires new feature engineering: (1) identify replacement player per injury, (2) compute per-minute production rate, (3) estimate expected minutes given rotation change, (4) compute line-vs-expected gap. Would need a "role change detector" and per-minute normalization.
- **Assessment:** Strong conceptual angle. The key question is whether the edge persists after sportsbook adjustments (usually 1-2 games). For a daily system like ours, this means we need rapid injury detection + fast feature computation. Worth investigating with our existing data before building new features.

---

### Angle 2: Blowout Risk / Large Spread Starters UNDER

- **Source:** Covers.com NBA prop betting guide, OddsIndex NBA player props guide, LSports blowout analysis, Bleacher Report garbage time analysis
- **Description:** When the game spread is 10+ points, starters on the favored team are at risk of sitting the entire fourth quarter in a blowout. Starters who normally log 36 minutes might only play 28-30 if the game is out of reach by Q4. This systematically depresses their counting stats below props lines that assume full minutes. The market "often prices in full minutes" for stars even in lopsided games.
- **Claimed Edge:** No specific HR% quantified, but described as a "profitable angle" across multiple sources. One source notes that "in most blowout games, significant amounts of props for starters will hit the under." Quantitative framework: if a star plays 28 min instead of 36 min, that is a 22% reduction in opportunity.
- **Direction:** UNDER
- **Data Required:** Pre-game spread (available via odds API), player tier/role, average minutes, historical minutes in blowout games
- **Have It?** YES -- We have `spread_magnitude` (feature 41, though it was recently fixed for the zeros bug in Session 374b), implied total, and player tier classification. We already have the `blowout_recovery` signal (disabled at 50% HR) which looks at the OPPOSITE direction (OVER after being blown out). This angle is the complementary UNDER play.
- **Dead End Overlap:** PARTIAL -- `blowout_recovery` (OVER after blowout) was tested and disabled at 50% HR. But this angle is the INVERSE: UNDER *during* expected blowout (pre-game, based on spread). Different trigger, different timing, different direction. The `extended_rest_4d_over_block` dead end used wrong feature column -- not related.
- **Complexity:** LOW -- Could be implemented as a signal/filter. Logic: `IF spread >= 10 AND player_tier IN ('star', 'starter') AND direction = 'UNDER' THEN boost signal`. We already have spread data in the feature store.
- **Assessment:** Promising and low-complexity. The spread is available pre-game and directly predicts minutes reduction. Worth validating with our `prediction_accuracy` data: filter to games where spread >= 10, starters, and check UNDER HR vs baseline. Could become a signal or negative filter.

---

### Angle 3: Pace-Up Spot OVER

- **Source:** FantasyTeamAdvice game pace data, DraftEdge projections, Unabated NBA strategy guide, WagerTalk NBA props analysis, community consensus from betting forums
- **Description:** When a player's team faces an opponent with significantly higher pace than their own, the game environment produces more possessions, more shot attempts, and more counting stats. "Pace is the single most important environmental factor" for individual stats. A specific example: LeBron James recorded 6+ assists in 15 of 18 games against teams ranked above average in pace. High-usage stars with strong efficiency profiles "often clear point lines when pace is up and the defense is thin."
- **Claimed Edge:** No aggregate HR% available, but individual case studies show 83%+ hit rate on specific player+pace combos (e.g., LeBron 15/18 = 83.3% for assists OVER vs high-pace teams). Pace-up adjustments of 5-10% more possessions translate to proportional stat increases.
- **Direction:** OVER
- **Data Required:** Team pace rankings (possessions per game), opponent pace, expected game pace (average of both teams), player usage rate
- **Have It?** YES -- We have `opponent_pace_mismatch` (attempted as V17 feature, <1% importance), and our `fast_pace_over` signal (81.5% HR, PRODUCTION). However, the V17 attempt was dismissed as dead end. The signal version is working but uses normalized 0-1 values. We also have the `high_scoring_environment_over` signal (70.2% HR).
- **Dead End Overlap:** PARTIAL -- V17 `opponent_pace_mismatch` as a MODEL FEATURE was a dead end (<1% importance). But the SIGNAL version (`fast_pace_over`) works at 81.5% HR. This suggests pace works as a filter/signal but not as a predictive feature inside the model. The community angle aligns with our existing signal architecture.
- **Complexity:** LOW -- Already implemented as `fast_pace_over` signal. Potential enhancement: make it more granular (e.g., pace delta thresholds, combine with player usage rate). The community emphasizes per-player pace sensitivity, not just raw pace.
- **Assessment:** Already captured in our system. The community angle validates our `fast_pace_over` signal. Possible enhancement: compute per-player pace sensitivity (how much does Player X's scoring change in pace-up vs pace-down spots) rather than using a blanket pace threshold.

---

### Angle 4: Early-Season Week 1 UNDER Totals Bias

- **Source:** Journal of Prediction Markets (academic paper, Wang et al.), "Early Season NBA Over/Under Bias," analyzing 2009-2012 seasons
- **Description:** The NBA game total market is systematically inefficient in Week 1 of the season. 58.2% of first-week games finish UNDER the total line. Betting UNDER total lines on all first-week games yielded average returns of 11.1% per game over the study period. The required breakeven rate is 52.38%. The bias gradually corrects as the season progresses, with books adjusting over the first 17 weeks.
- **Claimed Edge:** 58.2% UNDER hit rate in Week 1 (vs 52.38% breakeven), 11.1% average return per game. Statistically significant. 2009-2012 sample.
- **Direction:** UNDER (game totals, but implies player props UNDER too)
- **Data Required:** Schedule (game week number), game totals, season start date
- **Have It?** YES -- We have schedule data and can compute week number. However, this is a GAME TOTAL angle, not directly player props. The implication for player props: if game totals systematically hit UNDER in Week 1, individual player scoring props may also lean UNDER.
- **Dead End Overlap:** NONE -- We have not tested early-season bias. Our calendar regime analysis (Session 395) focused on trade deadline/ASB toxic window (Jan 30 - Feb 25), not season-opening bias.
- **Complexity:** LOW -- Simple calendar-based signal: `IF season_week <= 2 THEN boost UNDER signal`. Could be a seasonal overlay on existing predictions.
- **Assessment:** Academically validated but from 2009-2012 data. Market efficiency may have improved since then. Worth backtesting on recent seasons with our data. If the pattern persists, it is a trivial signal to implement. Only fires ~10-15 games per season (Week 1), so limited volume. Could pair with our existing calendar regime framework.

---

### Angle 5: Age-Stratified B2B Fatigue

- **Source:** HeatCheck HQ analysis, citing NBA SportVU tracking data and team medical staff research
- **Description:** Back-to-back performance decline is NOT uniform across ages. The data shows age-stratified fatigue effects on the second night of B2B: Under 25: 1-3% scoring decline. Age 25-30: 3-5% decline (most predictable and exploitable). Over 30: 5-10% decline. Additionally, three-point shooting drops 1.0-1.5 percentage points on B2B (from ~37% to 35.5-36%), and teams commit 0.5-1.0 additional turnovers per game. Coast-to-coast travel amplifies the effect to 5-7% for all ages. The 25-30 age bracket is described as "most predictable" because younger players recover faster and older players have load management buffers.
- **Claimed Edge:** Age 25-30 shows 3-5% scoring decline on B2B (most consistent). Age 30+ shows 5-10% decline. Three-point shooting drops 1.0-1.5pp. Rested home teams vs B2B opponents cover spreads above 55% historically.
- **Direction:** UNDER (for B2B team's players, especially age 25-30 and 30+)
- **Data Required:** Player age/DOB, B2B schedule detection, team travel distance, three-point shooting rates
- **Have It?** PARTIAL -- We have B2B detection (days_rest feature), but NOT player age as a feature. We have 3PT data in box scores. We do NOT compute travel distance. Our `b2b_fatigue_under` signal was disabled at 39.5% HR in Session 373, and our calendar regime analysis (Session 395) found B2B is actually +4-7pp BETTER than rested -- opposite of conventional wisdom.
- **Dead End Overlap:** HIGH -- `b2b_fatigue_under` was tested and disabled at 39.5% HR (Session 373). Calendar regime (Session 395) found B2B is counter-intuitively positive in our system. HOWEVER, the community angle adds a nuance we did NOT test: age stratification. Our test was blanket B2B, not age-segmented. The 30+ cohort might show the expected decline while younger players mask it.
- **Complexity:** MEDIUM -- Need to add player age/DOB to feature store (data available from player registry), then segment B2B analysis by age bracket. Query: `SELECT age_bracket, direction, COUNT(*), AVG(prediction_correct) FROM prediction_accuracy WHERE days_rest = 0 GROUP BY 1, 2`.
- **Assessment:** The blanket B2B angle is confirmed dead in our system. But age-stratified B2B has NOT been tested. Given the strong community consensus and SportVU data, worth running one targeted BQ query to check if 30+ players on B2B show UNDER edge even though the aggregate doesn't. If age 30+ B2B UNDER shows 55%+ HR on meaningful sample, it is a refined signal. If not, this confirms our existing finding that B2B doesn't matter for our pipeline.

---

### Angle 6: Post-Trade-Deadline Role Adjustment Lag

- **Source:** TheLines.com post-trade deadline analysis, ESPN trade grades, community consensus from sports betting forums
- **Description:** In the 1-2 weeks following the trade deadline, sportsbooks are slow to adjust player props for traded players and their new/former teammates. The market adjusts game spreads and totals quickly, but individual player props lag behind because: (1) role changes need time to manifest, (2) shot distribution shifts are unpredictable, (3) coaching staff adjustments are not immediately visible. Specific opportunities: (a) OVER on players whose new team has higher usage opportunity, (b) UNDER on players joining teams with established ball-dominant stars, (c) OVER on remaining teammates who inherit usage from traded players.
- **Claimed Edge:** No specific HR% quantified. Described as a "particularly unique opportunity" where "props can really shine while books are still catching up." The adjustment window is described as 1-2 weeks post-deadline.
- **Direction:** BOTH (OVER for usage inheritors, UNDER for role-diminished players)
- **Data Required:** Trade deadline date, trade transaction data, player team changes, pre/post-trade usage rates, roster composition
- **Have It?** PARTIAL -- We have the schedule and can compute "days since trade deadline." We have player game logs that would show usage shifts. We do NOT currently track trade transactions or roster changes as features. Our calendar regime analysis identifies the Jan 30 - Feb 25 toxic window which overlaps the trade deadline period, but from a model degradation perspective, not a betting angle perspective.
- **Dead End Overlap:** PARTIAL -- Our calendar regime toxic window (Jan 30 - Feb 25) captures the same period, but from a "model accuracy degrades" lens, not a "specific traded-player props are mispriced" lens. These are complementary findings: the model degrades because trades create unpredictable role changes, which is exactly what this angle exploits.
- **Complexity:** HIGH -- Requires: (1) trade transaction data source (manual or scraped), (2) pre/post-trade role classification, (3) usage reallocation model, (4) time-decay logic (edge shrinks as books adjust). Would need a new scraper or manual input for trade data.
- **Assessment:** Conceptually compelling and aligns with our observed calendar regime degradation. However, the trade deadline happens once per season, so the volume is very limited (maybe 20-40 affected players over 2 weeks). The high complexity and low volume make this a poor ROI for engineering effort. Better to acknowledge the toxic window via our existing calendar regime and reduce betting volume during that period, which we already do.

---

### Angle 7: Closing Line Value (CLV) as Meta-Signal

- **Source:** Unabated, VSiN, OddsShopper, BoydsBets, multiple professional betting education sources
- **Description:** Systematically beating the closing line (getting a better number than the market's final price before tip-off) is the strongest predictor of long-term profitability. If you bet Player X OVER 22.5 and the line closes at 21.5, you got +CLV. Research shows that bettors who maintain positive CLV over large samples "almost always turn a profit." For player props specifically, CLV may be MORE exploitable because prop markets have lower limits, less sharp action, and wider line variation across books. The 5:30-9 PM ET window is when lineup/injury news breaks before books fully adjust -- this is the optimal betting window.
- **Claimed Edge:** Positive CLV over large samples correlates strongly with long-term profit. No specific HR% but described as the single best predictor of betting profitability by professional bettors. Props have wider CLV opportunities due to market inefficiency.
- **Direction:** BOTH
- **Data Required:** Opening lines, closing lines, line timestamps, multi-book line comparison
- **Have It?** PARTIAL -- We have prop lines from Odds API at a single snapshot time. We do NOT track opening vs closing lines over time. We have `multi_book_line_std` (feature 50, with Bovada excluded) which captures cross-book disagreement at one point in time. We have `prop_line_delta` which tracks line movement from previous games, but not intra-day movement.
- **Dead End Overlap:** NONE -- We have never specifically tested CLV tracking. Our `line_rising_over` and `line_dropped_under` signals capture directional movement but not CLV magnitude.
- **Complexity:** MEDIUM -- Would need: (1) multiple daily odds snapshots (morning + pre-game), (2) compute delta between our bet timing and closing line, (3) use CLV as a post-hoc validation metric and potentially as a real-time signal for late-day bets. The Odds API supports historical odds but we would need additional API calls.
- **Assessment:** CLV is not really a "signal" for picking bets -- it is a META-METRIC for evaluating whether our system is getting good numbers. We should implement CLV tracking as a diagnostic tool: if our predictions consistently beat the closing line, our edge is real. If not, our apparent edge may be noise. This is a monitoring improvement, not a prediction improvement. HIGH VALUE for system validation, LOW VALUE as a pick signal.

---

### Angle 8: Secondary Stats (Steals/Blocks) UNDER Value

- **Source:** Unabated NBA strategy guide, Covers.com prop betting tips, SportsMemo prop strategies, community consensus
- **Description:** Steals and blocks are inherently high-variance stats -- most players cluster in the 0-2 range per game. The public tends to bet OVER on props (natural positive bias/"rooting interest"), which means sportsbooks shade steals/blocks lines slightly higher to capture public money. Additionally, because of the natural positive outlook on props, "there is value to be found in selecting under props, with more value and line discrepancies found in the under selections across sportsbooks." Steals and blocks props are described as "categorically more in the random territory" compared to points/rebounds/assists.
- **Claimed Edge:** No specific HR% quantified, but multiple professional sources describe UNDER on secondary stats as systematically underbet by the public. The Wizard of Odds analysis warns that 5-game samples for steals/blocks have confidence intervals of +/-43.8%, making recent trends unreliable -- yet the public overweights these small samples.
- **Direction:** UNDER
- **Data Required:** Steals/blocks prop lines, player steals/blocks averages, public betting percentages (ideal but not required)
- **Have It?** NO -- Our system currently only predicts POINTS props. We do not scrape or model rebounds, assists, steals, or blocks prop lines. We do not have public betting percentage data.
- **Dead End Overlap:** NONE -- We have never tested non-points prop markets.
- **Complexity:** HIGH -- Would require: (1) new scrapers for steals/blocks/rebounds/assists prop lines, (2) new feature engineering for non-points stats, (3) new model training for each stat type, (4) new evaluation pipeline. Essentially a parallel system for each stat category.
- **Assessment:** Valid angle but outside our current scope (points-only system). Expanding to rebounds/assists would be a significant project. Steals/blocks specifically have very high variance, making them hard to model even with good data. The community consensus that UNDER on secondary stats is underbet by the public is plausible but unquantified. NOT recommended for near-term work. Could be revisited if the points model stabilizes above 55% HR and we want to expand coverage.

---

## Additional Observations (Not Full Angles)

### Contrarian / Fade the Public
- **Data:** Sports Insights reported contrarian plays (betting against 75%+ public consensus) went 1,414-1,228 ATS (53.52%) over 13 seasons, and 56-41 ATS (57.7%) in one specific season.
- **Relevance:** Potentially applicable to our system if we had public betting percentages. We do NOT have this data. Would require a new data source (e.g., Action Network, Sports Insights API). Not actionable without it.

### Sample Size Neglect by the Public
- **Data:** Wizard of Odds shows that with 10 games sample, the 95% CI width is +/-31.0%. Testing 20 splits on 10-game samples yields 3.44 false patterns by chance alone.
- **Relevance:** Validates our existing approach of requiring 50+ graded picks before making model decisions. The public overweights small samples, creating market inefficiency that our model (trained on thousands of games) exploits implicitly.

### Q4 Shooting Efficiency Decline
- **Data:** Garcia et al. (2020) found an effect size of -1.27 for shooting efficiency from Q1 to Q4. Wang et al. (2024) found 19% of NBA games decided in Q4.
- **Relevance:** Our Q4 scorer features (Session 397) already capture this. The `q4_scorer_under_block` filter uses Q4 ratio >= 0.35 to block UNDER at 34.0% HR. This community finding validates our existing implementation.

### Assists Adjustment Lag After Injuries
- **Data:** Multiple sources note that "the adjustment on assists is often slower than on scoring lines" when starters are injured.
- **Relevance:** Only relevant if we expand to assists props. Not actionable for points-only system.

## Priority Ranking for Investigation

| Priority | Angle | Effort | Potential |
|----------|-------|--------|-----------|
| 1 | Blowout Risk / Large Spread UNDER (#2) | LOW | HIGH -- easy BQ validation, aligns with existing data |
| 2 | Age-Stratified B2B Fatigue (#5) | LOW | MEDIUM -- one BQ query to validate/kill |
| 3 | CLV Tracking (#7) | MEDIUM | HIGH -- system validation meta-metric |
| 4 | Early-Season Week 1 UNDER (#4) | LOW | LOW -- very limited volume (1 week/season) |
| 5 | Backup-to-Starter Usage Boost (#1) | HIGH | HIGH -- conceptually strong but complex |
| 6 | Post-Trade-Deadline Lag (#6) | HIGH | LOW -- limited volume, overlaps calendar regime |
| 7 | Pace-Up OVER (#3) | LOW | LOW -- already implemented as signal |
| 8 | Secondary Stats UNDER (#8) | HIGH | MEDIUM -- outside current scope |

## Recommended Next Steps

1. **BQ validation for Angle #2 (Blowout/Spread UNDER):** Query `prediction_accuracy` filtering spread >= 8, 10, 12 for starters and check UNDER HR vs baseline. This is a 10-minute investigation.

2. **BQ validation for Angle #5 (Age-Stratified B2B):** Join player age data with `prediction_accuracy` where `days_rest = 0`, segment by age bracket (under 25, 25-30, 30+), check if 30+ B2B UNDER shows profitable HR. Another 10-minute investigation.

3. **CLV tracking design (Angle #7):** Investigate adding a second daily Odds API snapshot (pre-game, ~6 PM ET) alongside the existing morning pull. Compute open-to-close delta as a diagnostic metric. Medium-term project.

4. **Kill or promote after BQ validation.** If angles #2 and #5 show signal, implement as signals/filters (LOW complexity). If not, document as dead ends with data.
