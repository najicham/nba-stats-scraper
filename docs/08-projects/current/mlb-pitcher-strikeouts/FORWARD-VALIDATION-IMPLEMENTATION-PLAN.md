# MLB Forward Validation Implementation Plan

**Created**: 2026-01-13
**Status**: READY TO IMPLEMENT
**Priority**: HIGH (Synthetic hit rate: 78.04% - PROMISING)
**Prerequisites**: Synthetic analysis complete, model validated

---

## Executive Summary

Based on synthetic hit rate analysis showing **78.04% hit rate (+25.64% vs breakeven)**, we have HIGH confidence the model detects betting value. This plan outlines implementation of forward validation to:

1. Collect real betting lines daily
2. Generate predictions with real betting context
3. Build 50+ prediction track record
4. Validate synthetic estimates with real performance
5. Make production deployment decision

**Timeline**: 2-3 weeks implementation + 2-4 weeks data collection

---

## Phase 1: Daily Betting Line Collection (Week 1)

### Goal
Implement daily scraping and processing of pitcher strikeout prop betting lines.

### 1.1 Scraper Implementation

**Status**: Scraper exists but not in use

**File**: `/home/naji/code/nba-stats-scraper/scrapers/oddsapi/oddsa_pitcher_props.py`

**Actions Required**:
1. Review existing scraper code
2. Test scraper with current Odds API key
3. Verify data mapping to BigQuery schema
4. Add error handling for missing data
5. Test with live data for upcoming games

**Validation**:
```bash
# Test scraper manually
python scrapers/oddsapi/oddsa_pitcher_props.py --date 2026-01-14

# Verify data in BigQuery
bq query --use_legacy_sql=false '
SELECT
  player_lookup,
  point as strikeout_line,
  over_price,
  under_price,
  bookmaker
FROM `nba-props-platform.mlb_raw.oddsa_pitcher_props`
WHERE game_date = "2026-01-14"
LIMIT 10
'
```

**Success Criteria**:
- ✅ Scraper runs without errors
- ✅ Data appears in `mlb_raw.oddsa_pitcher_props` table
- ✅ 80%+ of scheduled starting pitchers have lines
- ✅ Lines from multiple bookmakers captured

### 1.2 Data Processor Implementation

**File**: Create `/home/naji/code/nba-stats-scraper/data_processors/raw/mlb/oddsa_pitcher_props_processor.py`

**Purpose**: Clean, normalize, and enrich betting line data

**Key Features**:
- Deduplicate lines by bookmaker
- Calculate consensus line (median across bookmakers)
- Calculate implied probabilities
- Link to pitcher_lookup (normalized player names)
- Handle line movements (track first/last line)

**Schema Updates**:
```sql
-- Add to mlb_raw.oddsa_pitcher_props if not exists
consensus_line FLOAT64,  -- Median line across bookmakers
implied_over_prob FLOAT64,  -- Implied probability of over
implied_under_prob FLOAT64,  -- Implied probability of under
line_timestamp TIMESTAMP,  -- When line was captured
```

**Success Criteria**:
- ✅ Processor runs after scraper
- ✅ Consensus lines calculated correctly
- ✅ Player name matching works (pitcher_lookup)
- ✅ No duplicate entries per pitcher per game

### 1.3 Orchestration Integration

**File**: `/home/naji/code/nba-stats-scraper/orchestration/cloud_functions/mlb_phase4_to_phase5/main.py`

**Current State**: Orchestrator exists but doesn't check for betting lines

**Changes Required**:
```python
# Add to EXPECTED_PROCESSORS list
EXPECTED_PROCESSORS = [
    'pitcher_features',
    'lineup_k_analysis',
    'oddsa_pitcher_props',  # NEW: Add betting lines processor
]

# Add validation before triggering predictions
def validate_betting_lines(game_date: str) -> bool:
    """Ensure betting lines exist before predictions."""
    query = f"""
    SELECT COUNT(DISTINCT player_lookup) as pitchers_with_lines
    FROM `nba-props-platform.mlb_raw.oddsa_pitcher_props`
    WHERE game_date = '{game_date}'
    """
    result = bq_client.query(query).result()
    count = list(result)[0].pitchers_with_lines

    if count < 5:  # At least 5 games worth of lines
        logger.error(f"Insufficient betting lines for {game_date}: {count} pitchers")
        send_slack_alert(
            level='CRITICAL',
            message=f'Cannot run MLB predictions - only {count} betting lines for {game_date}',
            game_date=game_date
        )
        return False

    return True

# Call before triggering predictions
if not validate_betting_lines(game_date):
    # Abort predictions, update Firestore
    doc_ref.update({
        '_prediction_triggered': False,
        '_prediction_abort_reason': 'insufficient_betting_lines'
    })
    return
```

**Success Criteria**:
- ✅ Orchestrator waits for betting lines processor
- ✅ Validation prevents predictions without lines
- ✅ Slack alert sent if lines missing
- ✅ Predictions never run with insufficient data

### 1.4 Daily Schedule Setup

**File**: Create `config/mlb_daily_schedule.yaml` or update existing

**Schedule**:
```yaml
# Morning: Scrape betting lines (games start around 1 PM ET earliest)
08:00 AM ET: mlb_pitcher_props_scraper
  → Scrape today's pitcher props from Odds API
  → Populate mlb_raw.oddsa_pitcher_props

# Mid-Morning: Process and validate
09:00 AM ET: oddsa_pitcher_props_processor
  → Clean and normalize betting lines
  → Calculate consensus lines
  → Link to pitcher_lookup

# Afternoon: Phase 4 analytics
01:00 PM ET: Phase 4 processors
  → pitcher_features
  → lineup_k_analysis
  → Wait for all to complete

# Late Afternoon: Generate predictions
02:30 PM ET: Phase 4→5 orchestrator
  → Validate betting lines exist
  → Trigger prediction generation
  → Predictions WITH betting lines

# Evening: Grade predictions (after games complete)
11:00 PM ET: Grading processor
  → Match predictions to actual results
  → Calculate is_correct
  → Update prediction tables
```

**Implementation**:
- Cloud Scheduler jobs for each time slot
- Pub/Sub topics for triggering
- Idempotent functions (handle retries)

**Success Criteria**:
- ✅ Runs daily without manual intervention
- ✅ Each step waits for previous to complete
- ✅ Failures trigger alerts
- ✅ Predictions generated by 3 PM ET

---

## Phase 2: Prediction Pipeline Hardening (Week 2)

### Goal
Ensure predictions ALWAYS have betting lines and NEVER run without them.

### 2.1 Prediction Worker Updates

**File**: `/home/naji/code/nba-stats-scraper/predictions/mlb/pitcher_strikeouts_predictor.py`

**Current Issue**: `strikeouts_line` is optional parameter

**Fix**:
```python
def predict(self, pitcher_lookup: str, game_date: str,
            features: Dict, strikeouts_line: float) -> Dict:  # NO LONGER OPTIONAL
    """
    Generate prediction with REQUIRED betting line.

    Args:
        pitcher_lookup: Pitcher identifier
        game_date: Game date
        features: Model features
        strikeouts_line: Betting line (REQUIRED - will raise if None)

    Raises:
        MissingDependencyError: If strikeouts_line is None
    """
    if strikeouts_line is None:
        raise MissingDependencyError(
            f"Cannot generate prediction without betting line for {pitcher_lookup} on {game_date}"
        )

    # Generate prediction
    predicted_k = self.model.predict(features)

    # Calculate edge
    edge = predicted_k - strikeouts_line

    # Make recommendation based on edge
    if edge > 0.5:
        recommendation = 'OVER'
        confidence = self._calculate_confidence(features, edge)
    elif edge < -0.5:
        recommendation = 'UNDER'
        confidence = self._calculate_confidence(features, abs(edge))
    else:
        recommendation = 'PASS'  # Not 'NO_LINE'
        confidence = None

    return {
        'pitcher_lookup': pitcher_lookup,
        'game_date': game_date,
        'predicted_strikeouts': predicted_k,
        'strikeouts_line': strikeouts_line,  # ALWAYS populated
        'recommendation': recommendation,  # OVER, UNDER, or PASS
        'edge': edge,
        'confidence': confidence
    }
```

**Worker Service Updates**:

**File**: `/home/naji/code/nba-stats-scraper/predictions/mlb/worker.py`

**Fix**:
```python
def load_betting_lines(game_date: str) -> Dict[str, float]:
    """Load betting lines for all pitchers on game_date."""
    query = f"""
    SELECT DISTINCT
        player_lookup,
        consensus_line as strikeout_line
    FROM `nba-props-platform.mlb_raw.oddsa_pitcher_props`
    WHERE game_date = '{game_date}'
    """
    results = bq_client.query(query).result()
    return {row['player_lookup']: row['strikeout_line'] for row in results}

def predict_for_date(game_date: str) -> List[Dict]:
    """Generate predictions for all pitchers with betting lines."""
    # Load betting lines FIRST
    betting_lines = load_betting_lines(game_date)

    if not betting_lines:
        raise NoBettingLinesError(f"No betting lines available for {game_date}")

    # Load starting pitchers
    pitchers = get_starting_pitchers(game_date)

    predictions = []
    for pitcher in pitchers:
        # Skip if no betting line
        if pitcher['pitcher_lookup'] not in betting_lines:
            logger.warning(f"No betting line for {pitcher['pitcher_name']} - skipping")
            continue

        # Load features
        features = load_features(pitcher['pitcher_lookup'], game_date)

        # Get betting line
        strikeout_line = betting_lines[pitcher['pitcher_lookup']]

        # Generate prediction (will raise if line is None)
        prediction = predictor.predict(
            pitcher_lookup=pitcher['pitcher_lookup'],
            game_date=game_date,
            features=features,
            strikeouts_line=strikeout_line  # REQUIRED
        )

        predictions.append(prediction)

    return predictions
```

**Success Criteria**:
- ✅ All predictions have non-NULL `strikeouts_line`
- ✅ Predictions fail gracefully if no lines
- ✅ Worker logs missing lines clearly
- ✅ No 'NO_LINE' recommendations generated

### 2.2 Schema Enforcement

**File**: `/home/naji/code/nba-stats-scraper/schemas/bigquery/mlb_predictions/strikeout_predictions_tables.sql`

**Current Schema**:
```sql
strikeouts_line NUMERIC(4,1),  -- Currently nullable
```

**Updated Schema**:
```sql
strikeouts_line NUMERIC(4,1) NOT NULL,  -- Enforce NOT NULL
```

**Migration Strategy**:
1. Create new table version with NOT NULL constraint
2. Backfill existing data (set NULL → -1 for old predictions)
3. Switch application to new table
4. Drop old table after validation

**Validation**:
```sql
-- Verify no NULL lines after migration
SELECT COUNT(*) as null_count
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE strikeouts_line IS NULL
AND game_date >= '2026-01-14'  -- After forward validation starts
```

**Success Criteria**:
- ✅ Schema enforces NOT NULL on new predictions
- ✅ Old predictions (without lines) marked clearly
- ✅ No NULL lines in forward validation period

### 2.3 Health Monitoring

**File**: Create `/home/naji/code/nba-stats-scraper/orchestration/cloud_functions/mlb_prediction_health_alert/main.py`

**Purpose**: Monitor prediction health and alert on issues

**Checks**:
```python
def check_prediction_health(game_date: str) -> Dict:
    """Check health of predictions for game_date."""

    # 1. Check prediction count
    pred_count = count_predictions(game_date)
    expected_count = count_expected_games(game_date) * 2  # 2 starters per game

    # 2. Check for NO_LINE recommendations (should be 0%)
    no_line_count = count_no_line_predictions(game_date)
    no_line_ratio = no_line_count / pred_count if pred_count > 0 else 0

    # 3. Check for NULL betting lines (should be 0%)
    null_line_count = count_null_lines(game_date)

    # 4. Check recommendation distribution
    over_count = count_recommendations(game_date, 'OVER')
    under_count = count_recommendations(game_date, 'UNDER')
    pass_count = count_recommendations(game_date, 'PASS')

    # 5. Check average confidence
    avg_confidence = get_avg_confidence(game_date)

    health = {
        'game_date': game_date,
        'prediction_count': pred_count,
        'expected_count': expected_count,
        'no_line_count': no_line_count,
        'no_line_ratio': no_line_ratio,
        'null_line_count': null_line_count,
        'over_count': over_count,
        'under_count': under_count,
        'pass_count': pass_count,
        'avg_confidence': avg_confidence
    }

    # Determine alert level
    if null_line_count > 0:
        alert_level = 'CRITICAL'
        message = f'SCHEMA VIOLATION: {null_line_count} predictions with NULL lines'
    elif no_line_ratio > 0.10:
        alert_level = 'CRITICAL'
        message = f'BETTING LINE GAP: {no_line_ratio:.1%} predictions have NO_LINE'
    elif pred_count < expected_count * 0.8:
        alert_level = 'WARNING'
        message = f'Low prediction count: {pred_count}/{expected_count} expected'
    elif pass_count == pred_count:
        alert_level = 'WARNING'
        message = 'All predictions are PASS - no actionable bets'
    else:
        alert_level = 'HEALTHY'
        message = f'{pred_count} predictions, {over_count+under_count} actionable'

    if alert_level in ['CRITICAL', 'WARNING']:
        send_slack_alert(alert_level, message, health)

    return health
```

**Schedule**: Run daily at 3 PM ET (after predictions generated)

**Success Criteria**:
- ✅ Alerts sent for critical issues
- ✅ Dashboard shows daily health
- ✅ Historical health tracked in BigQuery

---

## Phase 3: Testing & Validation (Week 2-3)

### Goal
Test end-to-end pipeline before MLB season starts.

### 3.1 Integration Testing

**Test Scenarios**:

1. **Happy Path**: Full pipeline with betting lines
   - Mock betting lines for 10 games
   - Run scraper → processor → predictions
   - Verify all have lines and recommendations

2. **Missing Betting Lines**: Orchestrator aborts
   - Empty betting lines table
   - Trigger predictions
   - Verify abort + alert

3. **Partial Betting Lines**: Predictions only for available
   - Lines for 5/10 games
   - Trigger predictions
   - Verify 5 predictions generated, 5 skipped

4. **Line Updates**: Handle line movements
   - Initial lines scraped
   - Later lines scraped (different values)
   - Verify latest lines used

5. **Grading**: Predictions graded correctly
   - Predictions with OVER/UNDER
   - Mock actual results
   - Verify is_correct calculated

**Test Data**:
```sql
-- Create test data in dev environment
INSERT INTO `nba-props-platform-dev.mlb_raw.oddsa_pitcher_props` (...)
VALUES
  ('verlander-justin', '2026-01-20', 6.5, -110, -110, 'draftkings'),
  ('lopez-pablo', '2026-01-20', 5.5, -115, -105, 'fanduel'),
  ...
```

**Success Criteria**:
- ✅ All test scenarios pass
- ✅ Alerts triggered correctly
- ✅ No predictions with NULL lines
- ✅ End-to-end works without errors

### 3.2 Manual Testing (Pre-Season)

**When**: 2-3 days before MLB season (late March 2026)

**Steps**:
1. Enable daily schedule in staging
2. Monitor for 3 days of real scraping
3. Verify betting lines collected correctly
4. Verify predictions generated with lines
5. Manually verify 10 random predictions

**Checklist**:
- [ ] Scraper runs at 8 AM ET
- [ ] Lines appear in BigQuery by 9 AM ET
- [ ] Predictions generated by 3 PM ET
- [ ] All predictions have `strikeouts_line` populated
- [ ] Recommendations are OVER/UNDER/PASS (not NO_LINE)
- [ ] Health check runs and reports healthy
- [ ] No critical alerts

**Success Criteria**:
- ✅ 3 consecutive days successful
- ✅ 80%+ of expected pitchers have lines
- ✅ 80%+ of pitchers with lines get predictions
- ✅ System ready for production

---

## Phase 4: Forward Validation Tracking (Weeks 3-6)

### Goal
Build 50+ prediction track record with real betting lines.

### 4.1 Tracking Infrastructure

**Dashboard**: Create Grafana dashboard or BigQuery views

**Metrics to Track Daily**:
1. Predictions generated (count)
2. Actionable predictions (OVER/UNDER count)
3. Pass recommendations (count)
4. Predictions graded (count)
5. Hit rate (cumulative)
6. Hit rate by edge size
7. Hit rate vs synthetic estimate
8. ROI (if tracking units)

**Query for Daily Tracking**:
```sql
CREATE OR REPLACE VIEW mlb_predictions.forward_validation_tracking AS
WITH daily_metrics AS (
  SELECT
    game_date,
    COUNT(*) as predictions,
    SUM(CASE WHEN recommendation IN ('OVER', 'UNDER') THEN 1 ELSE 0 END) as actionable,
    SUM(CASE WHEN is_correct IS TRUE THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN is_correct IS FALSE THEN 1 ELSE 0 END) as losses,
    AVG(ABS(predicted_strikeouts - strikeouts_line)) as avg_edge
  FROM mlb_predictions.pitcher_strikeouts
  WHERE game_date >= '2026-03-28'  -- Season start
    AND strikeouts_line IS NOT NULL
  GROUP BY game_date
)
SELECT
  game_date,
  predictions,
  actionable,
  wins,
  losses,
  SAFE_DIVIDE(wins, wins + losses) * 100 as hit_rate,
  avg_edge,
  SUM(wins) OVER (ORDER BY game_date) as cumulative_wins,
  SUM(losses) OVER (ORDER BY game_date) as cumulative_losses,
  SAFE_DIVIDE(
    SUM(wins) OVER (ORDER BY game_date),
    SUM(wins) OVER (ORDER BY game_date) + SUM(losses) OVER (ORDER BY game_date)
  ) * 100 as cumulative_hit_rate
FROM daily_metrics
ORDER BY game_date DESC
```

**Success Criteria**:
- ✅ Dashboard updates daily
- ✅ Cumulative hit rate visible
- ✅ Easy to compare vs synthetic (78.04%)

### 4.2 Weekly Reviews

**Schedule**: Every Monday morning

**Review Checklist**:
- [ ] Total predictions this week: ____
- [ ] Actionable predictions: ____
- [ ] Hit rate this week: ____
- [ ] Cumulative hit rate: ____
- [ ] vs Synthetic (78.04%): ____
- [ ] Issues encountered: ____
- [ ] Action items: ____

**Red Flags** (trigger investigation):
- Hit rate < 50% (below random)
- Hit rate < 65% (>10% below synthetic)
- Large discrepancy between OVER and UNDER performance
- Edge size not correlating with win rate
- Systematic bias in errors

**Success Criteria**:
- ✅ 50+ actionable predictions tracked
- ✅ Weekly reviews documented
- ✅ Issues identified and resolved quickly

### 4.3 Decision Criteria (After 50 Predictions)

**Go/No-Go Decision Matrix**:

| Real Hit Rate | Synthetic (78%) | Decision |
|--------------|----------------|----------|
| > 54% | Within -24% | ✅ DEPLOY - Model validated |
| 52-54% | Within -24% to -26% | ⚠️ CONTINUE - Extend to 100 predictions |
| 50-52% | -26% to -28% | ⚠️ INVESTIGATE - Large gap vs synthetic |
| < 50% | > -28% | ❌ STOP - Model not performing |

**Additional Factors**:
- **Edge Calibration**: Does hit rate increase with edge size?
- **OVER/UNDER Balance**: Are both performing reasonably?
- **Sample Quality**: Were there unusual market conditions?
- **Comparison to Baseline**: Is model better than naive strategies?

**Next Steps by Decision**:
1. **DEPLOY**: Implement production pipeline, start with small stakes
2. **CONTINUE**: Extend validation to 100 predictions, deeper analysis
3. **INVESTIGATE**: Analyze discrepancy, potential model retraining
4. **STOP**: Root cause analysis, model improvement required

---

## Phase 5: Production Deployment (Week 7+)

### Goal (if approved)
Deploy validated model to production betting pipeline.

### 5.1 Production Readiness Checklist

- [ ] Forward validation complete (50+ predictions)
- [ ] Hit rate meets criteria (> 54%)
- [ ] Edge calibration validated
- [ ] All systems tested and stable
- [ ] Monitoring and alerting in place
- [ ] Runbooks documented
- [ ] Stakeholder approval obtained

### 5.2 Production Pipeline

**Components**:
1. Daily betting line collection (8 AM ET)
2. Feature computation (1 PM ET)
3. Prediction generation (2:30 PM ET)
4. Bet placement (3-6 PM ET) - **NEW**
5. Grading and tracking (11 PM ET)

**Bet Placement Logic**:
```python
def should_place_bet(prediction: Dict) -> bool:
    """Determine if bet should be placed."""
    # Only actionable recommendations
    if prediction['recommendation'] not in ['OVER', 'UNDER']:
        return False

    # Only if edge > threshold
    if abs(prediction['edge']) < 0.5:
        return False

    # Only if confidence > threshold (when calibrated)
    if prediction['confidence'] and prediction['confidence'] < 0.70:
        return False

    return True

def calculate_stake(prediction: Dict, bankroll: float) -> float:
    """Calculate stake using Kelly Criterion (fractional)."""
    edge = abs(prediction['edge'])
    hit_rate = get_historical_hit_rate_for_edge(edge)

    # Kelly fraction: f = (p * b - q) / b
    # Where p = win prob, b = odds multiplier, q = lose prob
    p = hit_rate / 100
    b = 1.91  # -110 odds ≈ 1.91 decimal
    q = 1 - p

    kelly_fraction = (p * b - q) / b

    # Use fractional Kelly (0.25 = quarter Kelly) for safety
    fractional_kelly = kelly_fraction * 0.25

    # Cap at 2% of bankroll per bet
    stake = min(fractional_kelly * bankroll, 0.02 * bankroll)

    return stake
```

**Success Criteria**:
- ✅ Production pipeline runs daily
- ✅ Bets placed automatically
- ✅ Performance tracked
- ✅ Alerts on issues
- ✅ Profitability validated over time

---

## Risk Management

### Technical Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Odds API downtime | HIGH | MEDIUM | Backup scraper (secondary source), cache recent lines |
| BigQuery failure | HIGH | LOW | Regional failover, local caching |
| Prediction service crash | HIGH | LOW | Auto-restart, health checks, redundancy |
| Schema drift | MEDIUM | LOW | Strict validation, schema versioning |
| Data quality issues | MEDIUM | MEDIUM | Validation checks, alerts, manual review |

### Model Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Real hit rate < synthetic | HIGH | MEDIUM | Forward validation required before deployment |
| Market efficiency (lines too sharp) | HIGH | MEDIUM | Monitor line quality, edge calibration |
| Model degradation over time | MEDIUM | MEDIUM | Continuous monitoring, periodic retraining |
| Overfitting to historical data | MEDIUM | LOW | Diverse test periods, cross-validation |
| Line movement against us | LOW | HIGH | Use opening lines, fast execution |

### Operational Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Manual intervention required | MEDIUM | MEDIUM | Automation, runbooks, on-call |
| Alerts not monitored | HIGH | LOW | Multiple channels, escalation |
| Budget overrun | MEDIUM | LOW | Cost monitoring, limits, alerts |
| Compliance issues | HIGH | LOW | Legal review, responsible betting practices |

---

## Success Metrics

### Week 1 (Implementation)
- ✅ Betting line scraper operational
- ✅ Processor running daily
- ✅ Orchestration updated with validation
- ✅ No predictions without lines

### Week 2 (Hardening)
- ✅ Prediction pipeline hardened
- ✅ Schema enforcement in place
- ✅ Health monitoring deployed
- ✅ All tests passing

### Week 3 (Testing)
- ✅ Integration tests complete
- ✅ Manual testing successful
- ✅ 3 consecutive days without issues
- ✅ Ready for season start

### Weeks 4-6 (Validation)
- ✅ 50+ predictions tracked
- ✅ Hit rate measured vs synthetic
- ✅ Edge calibration validated
- ✅ Go/no-go decision made

### Week 7+ (Production - if approved)
- ✅ Production pipeline live
- ✅ Bets placed daily
- ✅ Profitability tracking
- ✅ Continuous improvement

---

## Resource Requirements

### Development Time
- Phase 1: 40 hours (1 week, 1 engineer)
- Phase 2: 40 hours (1 week, 1 engineer)
- Phase 3: 20 hours (0.5 week, 1 engineer)
- Phase 4: 10 hours/week × 3 weeks = 30 hours (monitoring/review)
- **Total**: ~130 hours (~3 weeks)

### Infrastructure Costs
- BigQuery: ~$100/month (queries + storage)
- Cloud Functions: ~$50/month (executions)
- Cloud Scheduler: ~$10/month (jobs)
- Odds API: ~$100/month (quota)
- **Total**: ~$260/month

### Ongoing Maintenance
- Daily monitoring: 15 min/day
- Weekly reviews: 1 hour/week
- Issue resolution: 2-4 hours/month
- **Total**: ~10 hours/month

---

## Timeline Summary

```
Week 1: Betting line collection implementation
  Day 1-2: Scraper testing and deployment
  Day 3-4: Processor implementation
  Day 5: Orchestration updates
  Weekend: Integration testing

Week 2: Pipeline hardening
  Day 1-2: Prediction worker updates
  Day 3: Schema migration
  Day 4-5: Health monitoring deployment
  Weekend: End-to-end testing

Week 3: Pre-season testing
  Day 1-3: Manual testing with real data
  Day 4-5: Bug fixes and refinement
  Weekend: Final validation

Weeks 4-6: Forward validation
  Daily: Predictions generated and tracked
  Weekly: Performance reviews
  End of Week 6: Go/no-go decision

Week 7+: Production (if approved)
  Day 1: Production deployment
  Ongoing: Live betting and monitoring
```

---

## Conclusion

Based on synthetic hit rate of **78.04%** (+25.64% vs breakeven), we have HIGH confidence this model detects betting value. This implementation plan provides a structured approach to:

1. **Safely** collect real betting lines
2. **Rigorously** validate model performance
3. **Confidently** deploy to production (if validated)

**Recommended Next Step**: Begin Phase 1 implementation immediately to be ready for 2026 MLB season start (late March).

**Expected Outcome**: If forward validation confirms synthetic estimates, we'll have a highly profitable MLB pitcher strikeout betting model ready for production deployment.

---

**Document Version**: 1.0
**Created**: 2026-01-13
**Author**: Claude Code Analysis
**Status**: READY FOR IMPLEMENTATION
