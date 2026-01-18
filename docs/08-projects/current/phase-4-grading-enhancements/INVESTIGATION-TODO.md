# Phase 4 Investigation Todo List

**Created:** 2026-01-17
**Status:** Ready to investigate
**Priority:** High-value insights before Phase 4 implementation

---

## Player-Level Anomalies

### 🔴 Critical: Why Are Star Players So Unpredictable?

**Issue:** LeBron James (6.25% accuracy, 1/16) and Donovan Mitchell (7.02% accuracy, 4/57) are among the least accurate predictions despite being high-volume, well-known players.

**Investigation Tasks:**
- [ ] Analyze LeBron James's 16 predictions
  - What were the predicted vs actual point totals?
  - Which systems predicted him? (all failed equally or some worse?)
  - What features were input? (usage, rest, opponent, etc.)
  - Were lines consistently over/under his actual performance?

- [ ] Compare LeBron to other stars (Giannis, Curry, Durant)
  - Do all superstars have low accuracy? Or just LeBron?
  - Is there a "superstar penalty" in the models?

- [ ] Investigate Donovan Mitchell's pattern (4/57 = 7.02%)
  - Are his misses random or systematic?
  - Does he outperform when fresh, underperform when tired?
  - Opponent-specific patterns?

- [ ] Hypothesis Testing
  - **H1:** Load management makes stars unpredictable (random rest games)
  - **H2:** Stars see best defenses, making them harder to predict
  - **H3:** Models overfit to season averages, miss game-to-game variance
  - **H4:** Betting lines account for star power, creating tough benchmarks

**SQL Query:**
```sql
-- LeBron James investigation
SELECT
  player_lookup,
  game_date,
  system_id,
  predicted_points,
  actual_points,
  confidence,
  predicted_result,
  actual_result,
  betting_line,
  opponent
FROM `nba-props-platform.nba_predictions.prediction_grades`
WHERE player_lookup = 'lebronjames'
ORDER BY game_date;
```

**Expected Outcome:** Identify if stars need special handling or different prediction strategy

**Priority:** 🔴 High (affects betting decisions on biggest names)

---

### 🟢 Opportunity: What Makes 100% Accuracy Players Predictable?

**Issue:** 4 players achieved 100% accuracy with 15+ predictions. Understanding why could improve other predictions.

**Investigation Tasks:**
- [ ] Identify the 4 players with 100% accuracy
  - jaserichardson (17/17)
  - dorianfinneysmith (reported in dashboard)
  - ??? (2 more to identify)

- [ ] Common characteristics analysis
  - Role (starters vs bench?)
  - Usage rate (high vs low?)
  - Team (specific teams more predictable?)
  - Playing style (3-and-D, post-up, pick-and-roll?)

- [ ] Feature analysis
  - Which features are most stable for these players?
  - Low variance in recent averages?
  - Consistent minutes played?
  - Matchup-independent performance?

- [ ] System analysis
  - Did all systems predict them well? Or just one?
  - Which system is best for this player archetype?

- [ ] Expand the cohort
  - Find players with 85%+ accuracy
  - What's the sample size needed for confidence?
  - Can we predict which players will be predictable?

**SQL Query:**
```sql
-- Find 100% accuracy players with 15+ predictions
SELECT
  player_lookup,
  COUNT(*) as total_predictions,
  SUM(CASE WHEN actual_result = predicted_result THEN 1 ELSE 0 END) as correct,
  AVG(CASE WHEN actual_result = predicted_result THEN 100.0 ELSE 0.0 END) as accuracy,
  AVG(confidence) as avg_confidence,
  STRING_AGG(DISTINCT system_id) as systems_used
FROM `nba-props-platform.nba_predictions.prediction_grades`
GROUP BY player_lookup
HAVING total_predictions >= 15 AND accuracy = 100.0
ORDER BY total_predictions DESC;
```

**Expected Outcome:** Identify "predictable player archetype" for confidence boosting

**Priority:** 🟢 High (can improve overall accuracy immediately)

---

## System-Level Anomalies

### 🟡 Investigation: Why Did zone_matchup_v1 Have Lowest ROI?

**Issue:** zone_matchup_v1 had 4.41% ROI before the bug fix. We fixed the inverted defense logic, but need to verify improvement.

**Investigation Tasks:**
- [ ] Validate fix is working (after 2-3 days of new data)
  ```sql
  -- Compare pre-fix vs post-fix accuracy
  SELECT
    CASE
      WHEN game_date < '2026-01-18' THEN 'pre_fix'
      ELSE 'post_fix'
    END as period,
    COUNT(*) as predictions,
    AVG(CASE WHEN actual_result = predicted_result THEN 100.0 ELSE 0.0 END) as accuracy,
    AVG(confidence) as avg_confidence
  FROM `nba-props-platform.nba_predictions.prediction_grades`
  WHERE system_id = 'zone_matchup_v1'
  GROUP BY period;
  ```

- [ ] Analyze pre-fix pattern
  - Did it consistently predict OVER against elite defenses?
  - Did it consistently predict UNDER against weak defenses?
  - Quantify the inversion impact

- [ ] Compare to other systems
  - Is zone_matchup_v1 now competitive with ensemble_v1 or moving_average?
  - Does it excel in specific matchups (paint-heavy vs perimeter-heavy)?

- [ ] Feature importance
  - Which zones matter most? (paint, mid-range, 3pt, FT)
  - Should we weight zones differently?
  - Do we need opponent zone defense data?

**Expected Outcome:** zone_matchup_v1 ROI improves to 8-12% range (comparable to other systems)

**Priority:** 🟡 Medium (fix already deployed, just need validation)

---

### 🟡 Investigation: similarity_balanced_v1 Recalibration Impact

**Issue:** Reduced confidence from 88% to ~61% to match actual accuracy. Need to verify it doesn't break the system.

**Investigation Tasks:**
- [ ] Monitor new confidence values
  ```sql
  SELECT
    DATE(game_date) as date,
    AVG(confidence) as avg_confidence,
    COUNT(*) as predictions
  FROM `nba-props-platform.nba_predictions.predictions`
  WHERE system_id = 'similarity_balanced_v1'
    AND game_date >= '2026-01-18'
  GROUP BY date
  ORDER BY date;
  ```

- [ ] Verify accuracy still ~60%
  - Confidence calibration should not affect prediction quality
  - Just makes confidence score more honest

- [ ] Check recommendation changes
  - With lower confidence, does it PASS more often?
  - Does this improve ROI (fewer bad bets)?

- [ ] Compare to pre-calibration
  - Old: 88% confidence, 60.6% accuracy (27 pts overconfident)
  - New: Should be 61% confidence, 60% accuracy (1 pt error)

**Expected Outcome:** Confidence matches accuracy, ROI improves due to fewer overconfident bad bets

**Priority:** 🟡 Medium (fix already deployed, verification only)

---

## Data Quality Issues

### 🔴 Critical: Missing Actuals / DNP Investigation

**Issue:** Grading data shows 0 missing actuals and 0 DNP, which seems suspiciously perfect.

**Investigation Tasks:**
- [ ] Verify we're actually getting DNP data
  ```sql
  SELECT
    game_date,
    COUNT(DISTINCT player_lookup) as players_graded,
    SUM(missing_actuals) as missing,
    SUM(dnp_count) as dnp
  FROM `nba-props-platform.nba_predictions.prediction_grades`
  GROUP BY game_date
  ORDER BY game_date DESC;
  ```

- [ ] Check if DNP detection is working
  - Are we checking boxscores correctly?
  - Do we have "Did Not Play" status in source data?
  - Are we marking predictions as ungradeable when player sits?

- [ ] Investigate "missing actuals" logic
  - When do we increment this counter?
  - Are we only grading players who played?
  - Should we grade predictions where player sat (as WRONG)?

- [ ] Sample validation
  - Pick a known DNP game (injury report + boxscore confirms)
  - Verify our grading system marks it correctly

**Expected Outcome:** Fix DNP detection if broken, or confirm it's working correctly

**Priority:** 🔴 High (affects data quality metrics)

---

## ROI Optimization Opportunities

### 🟢 Opportunity: Optimal Betting Strategy Analysis

**Issue:** We have 6 profitable systems but don't know the optimal way to combine them.

**Investigation Tasks:**
- [ ] Single-system strategies
  - Best system only (catboost_v8 high-conf: 19.99% ROI)
  - Second-best system (ensemble_v1 high-conf: 11.77% ROI)
  - Most consistent (moving_average: 13.29% ROI)

- [ ] Combination strategies
  - Unanimous agreement (all 6 systems agree): What's ROI?
  - Majority vote (4+ systems agree): What's ROI?
  - Ensemble of top 3: catboost_v8 + ensemble_v1 + moving_average

- [ ] Confidence thresholding
  - Current: >70% = high-confidence
  - What if we use >75%? >80%?
  - Trade-off: fewer bets but higher win rate?

- [ ] Player filtering
  - Avoid LeBron and Donovan Mitchell: How much does ROI improve?
  - Only bet on 85%+ accuracy players: ROI vs volume trade-off?
  - Avoid low-sample players (<15 predictions): Impact?

- [ ] Risk analysis
  - What's max drawdown for each strategy?
  - Sharpe ratio (return per unit of risk)
  - Longest losing streak
  - Kelly Criterion bankroll recommendations

**SQL Query:**
```sql
-- Unanimous agreement analysis
WITH unanimous AS (
  SELECT
    player_lookup,
    game_date,
    betting_line,
    actual_points,
    COUNT(DISTINCT system_id) as systems_count,
    COUNT(DISTINCT recommendation) as unique_recommendations
  FROM `nba-props-platform.nba_predictions.predictions`
  WHERE recommendation IN ('OVER', 'UNDER')
  GROUP BY player_lookup, game_date, betting_line, actual_points
  HAVING systems_count >= 5 AND unique_recommendations = 1
)
SELECT
  COUNT(*) as unanimous_bets,
  SUM(CASE
    WHEN (recommendation = 'OVER' AND actual_points > betting_line) OR
         (recommendation = 'UNDER' AND actual_points < betting_line)
    THEN 1 ELSE 0
  END) as wins,
  AVG(CASE
    WHEN (recommendation = 'OVER' AND actual_points > betting_line) OR
         (recommendation = 'UNDER' AND actual_points < betting_line)
    THEN 100.0 ELSE 0.0
  END) as win_rate
FROM unanimous;
```

**Expected Outcome:** Identify optimal betting strategy for maximum ROI with acceptable risk

**Priority:** 🟢 High (direct impact on profitability)

---

## Dashboard Enhancement Ideas

### 🟡 Investigation: What Additional Metrics Would Be Valuable?

**Current Dashboard Tabs:**
1. Status Cards
2. Coverage Metrics
3. Grading by System
4. Calibration
5. ROI Analysis
6. Player Insights
7. Reliability

**Investigation Tasks:**
- [ ] User feedback
  - What questions can't be answered with current dashboard?
  - What requires manual SQL queries?
  - What takes too long to load?

- [ ] Missing visualizations
  - ROI over time (time series chart)
  - System comparison (radar chart)
  - Confidence distribution (histogram)
  - Win/loss streak tracking
  - Bankroll simulation (Monte Carlo)

- [ ] Mobile optimization
  - Does dashboard work on mobile?
  - Do we need a mobile-specific view?
  - Progressive Web App (PWA) for notifications?

- [ ] Performance optimization
  - Which queries are slowest?
  - Can we precompute more views?
  - Add caching layer?

**Expected Outcome:** Prioritized list of dashboard enhancements for Phase 4

**Priority:** 🟡 Medium (nice-to-have, not critical)

---

## Next Steps

### Week 1: Quick Wins (Immediate Value)
1. 🔴 Investigate LeBron James / Donovan Mitchell accuracy issue
2. 🟢 Identify and analyze 100% accuracy players
3. 🟢 Run optimal betting strategy analysis

### Week 2: Validation (Verify Session 91 Fixes)
1. 🟡 Validate zone_matchup_v1 ROI improvement
2. 🟡 Verify similarity_balanced_v1 recalibration
3. 🔴 Check DNP detection is working

### Week 3: Data Quality
1. Comprehensive data quality audit
2. Fix any issues found
3. Document investigation findings

### Week 4: Phase 4 Kickoff
1. Review investigation results
2. Reprioritize Phase 4 roadmap based on findings
3. Start Priority 1 (Automated Recalibration Pipeline)

---

## Investigation Tracking

### Completed Investigations
- None yet (todo list created 2026-01-17)

### In Progress
- None yet

### Blocked
- Most investigations blocked on 2-3 days of new data post-fix

---

**Next Action:** Wait 2-3 days for new grading data, then start Week 1 investigations
