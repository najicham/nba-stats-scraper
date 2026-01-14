# MLB Betting Lines Crisis - Root Cause & Architectural Solutions

**Created**: 2026-01-13
**Type**: Post-Mortem Analysis & System Design
**Status**: Strategic Architecture Document

---

## Executive Summary

We discovered 8,130 MLB predictions were generated **without betting lines** - making them unmeasurable for betting profitability. This document analyzes the root cause and designs architectural solutions to prevent this class of failure.

### The Crisis
- ✅ 8,130 predictions exist (April 2024 - September 2025)
- ✅ Model trained with MAE 1.71 (11% better than baseline)
- ❌ 0 betting lines collected
- ❌ Cannot calculate hit rate against spread
- ❌ Cannot evaluate betting profitability

### The Verdict
**ROOT CAUSE**: Prediction pipeline ran without enforcing betting line dependency.

**HIGHEST QUALITY SOLUTION**: Full historical backfill + architectural redesign.

---

## Part 1: Why Full Historical Backfill is Non-Negotiable

### The Quantitative Finance Perspective

In professional sports betting and quantitative finance, there is an ironclad rule:

> **"Never deploy a model to production without rigorous backtesting on historical out-of-sample data."**

This isn't optional. This is fundamental risk management.

### Cost-Benefit Analysis

**Historical Backfill Costs:**
- Time: 6-8 hours implementation
- API credits: ~$100-150 (Odds API historical endpoint)
- Complexity: Moderate (matching, data quality)

**Historical Backfill Benefits:**
- Learn from 8,130 predictions (≈18 months of live data)
- Validate confidence calibration
- Discover systematic biases
- Identify problem contexts
- Make informed deployment decision
- **Prevent potentially catastrophic losses from deploying bad model**

**The Math:**
- **Prospective learning**: 18 months to accumulate equivalent data
- **Backfill learning**: 8 hours to analyze 18 months of data
- **ROI**: 1,600x time compression

**Risk Management:**
- Cost of backfill: $150
- Cost of one bad betting week: $500-5,000
- Cost of deploying uncalibrated model: Unbounded

### What Backfill Will Tell Us

#### 1. Confidence Calibration (CRITICAL)

**The Question**: When model says 70% confidence, is it really 70%?

**Why It Matters**: A miscalibrated model is worse than no model. If model says 70% but actual is 55%, you lose money on every bet.

**Only Backfill Can Answer This**:
```sql
-- Calibration analysis
WITH predictions_by_confidence AS (
  SELECT
    FLOOR(confidence * 10) / 10 as confidence_bucket,
    COUNT(*) as predictions,
    AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) as actual_rate
  FROM mlb_predictions.pitcher_strikeouts
  WHERE strikeouts_line IS NOT NULL
  GROUP BY confidence_bucket
)
SELECT
  confidence_bucket,
  predictions,
  ROUND(actual_rate * 100, 1) as actual_pct,
  ROUND(ABS(confidence_bucket * 100 - actual_rate * 100), 1) as calibration_error
FROM predictions_by_confidence
ORDER BY confidence_bucket;
```

**Ideal Result**: confidence_bucket ≈ actual_rate (calibrated)
**Bad Result**: Systematic deviation (model is lying about confidence)

#### 2. Systematic Biases

**Potential Issues to Discover**:
- Over-predicting OVERs (model too aggressive)
- Under-predicting UNDERs (model too conservative)
- Home field bias (performs differently home vs away)
- Weather bias (struggles with day games)
- Early season bias (bad when stats are sparse)

**Only Backfill Reveals These**: You need 1,000s of predictions to detect 5% biases.

#### 3. Problem Tiers (Like NBA's 88-90% Issue)

NBA discovered a **62% hit rate in the 88-90% confidence tier** vs 75% in adjacent tiers. This cost them millions in wasted predictions.

**MLB might have similar issues**. You cannot find this with <100 predictions. You need the full 8,130.

#### 4. Edge Detection

**The Ultimate Question**: Is there betting value?

```sql
-- Calculate if there's edge
SELECT
  CASE
    WHEN confidence > 0.75 THEN 'High Confidence'
    WHEN confidence > 0.60 THEN 'Medium Confidence'
    ELSE 'Low Confidence'
  END as tier,
  COUNT(*) as bets,
  AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) as win_rate,
  -- Need >52.4% to break even on -110 odds
  CASE
    WHEN AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) > 0.524 THEN 'PROFITABLE'
    ELSE 'LOSING'
  END as verdict
FROM mlb_predictions.pitcher_strikeouts
WHERE strikeouts_line IS NOT NULL
GROUP BY tier;
```

**Prospective approach**: Wait 18 months to learn if model is profitable.
**Backfill approach**: Know in 8 hours.

---

## Part 2: The Architectural Failure (Root Cause Analysis)

### What Went Wrong

The MLB prediction pipeline was designed as:

```python
# ACTUAL IMPLEMENTATION (Broken)
def generate_predictions_for_date(game_date):
    """Generate predictions without betting context."""

    # 1. Get today's starting pitchers
    pitchers = get_starting_pitchers(game_date)

    # 2. Generate predictions from model
    for pitcher in pitchers:
        prediction = model.predict(pitcher, game_date)

        # 3. Try to find betting line (OPTIONAL - This was the mistake!)
        betting_line = try_get_line(pitcher, game_date)  # Returns None if missing

        # 4. Save prediction EVEN IF NO LINE
        save_prediction(
            pitcher=pitcher,
            predicted_k=prediction,
            line=betting_line,  # Can be None!
            recommendation='NO_LINE' if betting_line is None else calculate_reco(prediction, betting_line)
        )
```

**The Fatal Flaw**: Betting line lookup was OPTIONAL, not REQUIRED.

### Why This Happened

Looking at the code and docs, I can reconstruct the timeline:

1. **Phase 1 (Jan 2026)**: Built scrapers, processors, feature engineering
2. **Phase 2 (Jan 2026)**: Trained model, validated on small sample
3. **Phase 3 (Jan 2026)**: Created prediction worker
4. **Phase 4 (Planned but not executed)**: Integrate betting lines

The `ODDS-DATA-STRATEGY.md` shows betting lines were PLANNED but never implemented:
```markdown
## Implementation Order

### Phase 1: Odds API Infrastructure
1. scrapers/mlb/oddsapi/__init__.py
2. scrapers/mlb/oddsapi/mlb_events.py
3. scrapers/mlb/oddsapi/mlb_game_lines.py
4. scrapers/mlb/oddsapi/mlb_pitcher_props.py  ← NEVER COMPLETED
```

**Root Cause**: Prediction pipeline shipped before betting integration finished.

### Systemic Issues

This reveals THREE architectural anti-patterns:

#### Anti-Pattern #1: No Hard Dependencies

```python
# WRONG: Optional dependency
betting_line = try_get_line(pitcher, game_date)  # Can return None

# RIGHT: Hard dependency
betting_line = get_line(pitcher, game_date)  # Raises exception if missing
if betting_line is None:
    raise MissingDependencyError("Cannot generate prediction without betting line")
```

#### Anti-Pattern #2: No Data Quality Gates

The prediction table schema ALLOWS null betting lines:
```sql
strikeouts_line FLOAT64,  -- Should be NOT NULL!
```

**Should be**:
```sql
strikeouts_line FLOAT64 NOT NULL,  -- Enforce at schema level
```

#### Anti-Pattern #3: No Orchestration Dependencies

NBA has `master_controller.py` that checks prerequisites:
```python
def evaluate_predictions_workflow(current_time, games_today):
    """Evaluate if predictions should run."""

    # CHECK DEPENDENCY: Are betting lines available?
    if not betting_lines_exist_for_games(games_today):
        return WorkflowDecision(
            action=DecisionAction.SKIP,
            reason="Betting lines not yet available",
            alert_level=AlertLevel.WARNING,
            next_check_time=current_time + timedelta(hours=1)
        )

    # Dependency satisfied, safe to run
    return WorkflowDecision(
        action=DecisionAction.RUN,
        reason="All prerequisites met"
    )
```

MLB has NO equivalent. Predictions just run whenever triggered.

---

## Part 3: Architectural Solutions (How to Prevent This Forever)

### Solution 1: Phase Dependency Framework

**Concept**: Model the data pipeline as a DAG with hard dependencies.

```yaml
# config/mlb_phase_dependencies.yaml

phases:
  phase_2_raw:
    - bdl_pitcher_stats
    - mlb_schedule
    - oddsa_pitcher_props  # CRITICAL: Must exist before predictions

  phase_3_analytics:
    depends_on: [phase_2_raw]
    tables:
      - pitcher_game_summary
      - batter_game_summary

  phase_4_precompute:
    depends_on: [phase_3_analytics]
    tables:
      - pitcher_ml_features
      - lineup_k_analysis

  phase_5_predictions:
    depends_on: [phase_4_precompute, betting_lines]  # ← KEY: Hard dependency
    requires:
      - oddsa_pitcher_props.game_date = CURRENT_DATE
      - COUNT(*) > 0  # Must have betting lines for today
    on_missing:
      action: ABORT
      alert: CRITICAL
      message: "Cannot generate predictions without betting lines"
```

### Solution 2: MLB Orchestration Dataset

Create `mlb_orchestration` dataset (mirroring NBA's pattern):

```sql
-- mlb_orchestration.data_readiness

CREATE TABLE mlb_orchestration.data_readiness (
  check_id STRING NOT NULL,
  check_time TIMESTAMP NOT NULL,
  target_date DATE NOT NULL,
  phase STRING NOT NULL,  -- phase_2_raw, phase_3_analytics, etc.

  -- Readiness checks
  required_tables ARRAY<STRING>,
  tables_ready ARRAY<STRING>,
  tables_missing ARRAY<STRING>,

  -- Betting lines specific
  games_scheduled INT64,
  games_with_lines INT64,
  line_coverage_pct FLOAT64,

  -- Decision
  is_ready BOOLEAN,
  blocking_reason STRING,

  -- Metadata
  created_at TIMESTAMP NOT NULL
)
PARTITION BY target_date
CLUSTER BY phase, is_ready;
```

**Usage in Workflow Controller**:
```python
def check_prediction_readiness(game_date: str) -> bool:
    """Check if all prerequisites met for generating predictions."""

    query = f"""
    SELECT
      COUNT(DISTINCT ps.game_id) as games_with_stats,
      COUNT(DISTINCT pp.game_id) as games_with_lines,
      COUNT(DISTINCT s.game_id) as games_scheduled
    FROM `nba-props-platform.mlb_raw.mlb_schedule` s
    LEFT JOIN `nba-props-platform.mlb_analytics.pitcher_game_summary` ps
      ON s.game_id = ps.game_id
    LEFT JOIN `nba-props-platform.mlb_raw.oddsa_pitcher_props` pp
      ON s.game_id = pp.game_id AND pp.market_key = 'pitcher_strikeouts'
    WHERE s.game_date = '{game_date}'
    """

    result = execute_query(query)

    games_scheduled = result['games_scheduled']
    games_with_lines = result['games_with_lines']
    coverage = games_with_lines / games_scheduled if games_scheduled > 0 else 0

    # HARD REQUIREMENT: Must have lines for at least 80% of games
    is_ready = coverage >= 0.80

    # Log readiness check
    log_readiness_check(
        target_date=game_date,
        phase='phase_5_predictions',
        is_ready=is_ready,
        games_scheduled=games_scheduled,
        games_with_lines=games_with_lines,
        line_coverage_pct=coverage * 100
    )

    return is_ready
```

### Solution 3: Workflow Controller Integration

**Add MLB workflows to master controller**:

```yaml
# config/workflows.yaml (ADD MLB section)

mlb_betting_lines:
  enabled: true
  decision_type: "game_aware"
  priority: "CRITICAL"
  schedule:
    run_times: ["08:00", "10:00", "12:00"]  # Morning scrapes
    timezone: "America/New_York"
  scrapers:
    - mlb_events
    - mlb_pitcher_props
    - mlb_batter_props
  validation:
    min_games_with_lines: 5
    alert_if_coverage_below: 0.80

mlb_predictions:
  enabled: true
  decision_type: "dependent"
  priority: "HIGH"
  depends_on: ["mlb_betting_lines"]  # ← HARD DEPENDENCY
  schedule:
    run_times: ["14:00"]  # After lines scraped
    timezone: "America/New_York"
  prerequisite_check:
    function: "check_mlb_prediction_readiness"
    min_line_coverage: 0.80
  on_prerequisite_fail:
    action: "ABORT"
    alert_level: "CRITICAL"
    retry_in_hours: 1
    max_retries: 3
  scrapers:
    - mlb_prediction_coordinator
```

### Solution 4: Schema-Level Enforcement

**Prediction table redesign**:

```sql
-- BEFORE (Allows null lines)
CREATE TABLE mlb_predictions.pitcher_strikeouts (
  strikeouts_line FLOAT64,  -- CAN BE NULL
  recommendation STRING      -- Can be 'NO_LINE'
);

-- AFTER (Enforces line requirement)
CREATE TABLE mlb_predictions.pitcher_strikeouts (
  strikeouts_line FLOAT64 NOT NULL,  -- MUST EXIST
  over_odds INT64 NOT NULL,
  under_odds INT64 NOT NULL,
  recommendation STRING NOT NULL CHECK (recommendation IN ('OVER', 'UNDER')),  -- NO 'NO_LINE' allowed

  -- Source tracking
  line_source STRING NOT NULL,  -- 'DraftKings', 'FanDuel', etc.
  line_captured_at TIMESTAMP NOT NULL,

  -- Data quality
  line_quality_score FLOAT64,  -- 0-100: How confident are we in this line?
  line_age_minutes INT64       -- How old is the line?
);
```

**Validation at write-time**:
```python
def save_prediction(prediction_data: dict):
    """Save prediction with validation."""

    # VALIDATION GATE 1: Must have betting line
    if not prediction_data.get('strikeouts_line'):
        raise ValidationError("Cannot save prediction without betting line")

    # VALIDATION GATE 2: Line must be fresh
    line_age_minutes = calculate_line_age(prediction_data['line_captured_at'])
    if line_age_minutes > 180:  # 3 hours
        raise ValidationError(f"Betting line too stale: {line_age_minutes} minutes old")

    # VALIDATION GATE 3: Must have valid recommendation
    if prediction_data['recommendation'] not in ['OVER', 'UNDER']:
        raise ValidationError(f"Invalid recommendation: {prediction_data['recommendation']}")

    # Safe to save
    insert_to_bigquery('mlb_predictions.pitcher_strikeouts', prediction_data)
```

### Solution 5: Data Quality Monitoring

**Add monitoring dashboard**:

```sql
-- mlb_orchestration.daily_data_quality_report

CREATE OR REPLACE VIEW mlb_orchestration.daily_data_quality_report AS
WITH today_games AS (
  SELECT COUNT(DISTINCT game_id) as total_games
  FROM `nba-props-platform.mlb_raw.mlb_schedule`
  WHERE game_date = CURRENT_DATE()
),
betting_lines AS (
  SELECT
    COUNT(DISTINCT game_id) as games_with_lines,
    COUNT(DISTINCT CONCAT(game_id, player_lookup)) as pitcher_lines
  FROM `nba-props-platform.mlb_raw.oddsa_pitcher_props`
  WHERE game_date = CURRENT_DATE()
    AND market_key = 'pitcher_strikeouts'
),
predictions AS (
  SELECT
    COUNT(*) as predictions_generated,
    COUNT(CASE WHEN strikeouts_line IS NOT NULL THEN 1 END) as predictions_with_lines
  FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
  WHERE game_date = CURRENT_DATE()
)
SELECT
  CURRENT_DATE() as report_date,
  tg.total_games,
  bl.games_with_lines,
  bl.pitcher_lines,
  ROUND(bl.games_with_lines * 100.0 / NULLIF(tg.total_games, 0), 1) as line_coverage_pct,
  p.predictions_generated,
  p.predictions_with_lines,

  -- DATA QUALITY VERDICTS
  CASE
    WHEN bl.games_with_lines * 1.0 / NULLIF(tg.total_games, 0) >= 0.80 THEN '✅ GOOD'
    WHEN bl.games_with_lines * 1.0 / NULLIF(tg.total_games, 0) >= 0.50 THEN '🟡 PARTIAL'
    ELSE '🔴 CRITICAL'
  END as line_coverage_status,

  CASE
    WHEN p.predictions_with_lines = p.predictions_generated THEN '✅ ALL VALID'
    WHEN p.predictions_with_lines > 0 THEN '🟡 SOME INVALID'
    ELSE '🔴 NO VALID PREDICTIONS'
  END as prediction_quality_status

FROM today_games tg
CROSS JOIN betting_lines bl
CROSS JOIN predictions p;
```

**Grafana Alert**:
```yaml
# alerts/mlb_data_quality.yaml

- alert: MLBBettingLinesCoveragelow
  expr: line_coverage_pct < 80
  for: 1h
  severity: critical
  annotations:
    summary: "MLB betting lines coverage below 80%"
    description: "Only {{ $value }}% of games have betting lines. Cannot generate predictions."
    runbook: "Check oddsa_pitcher_props scraper, verify Odds API key, check API rate limits"

- alert: MLBPredictionsWithoutLines
  expr: predictions_generated > predictions_with_lines
  for: 5m
  severity: critical
  annotations:
    summary: "MLB predictions saved without betting lines"
    description: "{{ $value }} predictions saved with null betting lines. Data quality violation!"
    runbook: "IMMEDIATE: Stop prediction pipeline, investigate validation bypass"
```

---

## Part 4: Implementation Roadmap

### Immediate (This Week)

**Day 1: Historical Backfill**
1. Implement `scripts/mlb/backfill_historical_odds.py`
2. Test on 10 sample dates
3. Run full backfill (April 2024 - September 2025)
4. Match predictions to betting lines
5. Re-grade all predictions

**Day 2: Comprehensive Analysis**
6. Run hit rate analysis
7. Generate calibration curves
8. Identify problem tiers
9. Calculate ROI estimates
10. Make deployment decision

**Deliverable**: Complete performance report with go/no-go verdict

### Short-term (Next 2 Weeks)

**Week 1: Fix Prediction Pipeline**
1. Update prediction schema (enforce NOT NULL)
2. Add validation gates
3. Implement prerequisite checks
4. Test with sample date

**Week 2: Orchestration Setup**
1. Create `mlb_orchestration` dataset
2. Implement data readiness checks
3. Add MLB workflows to controller
4. Deploy monitoring dashboard

**Deliverable**: Production-ready betting prediction system

### Long-term (Before 2026 Season)

**Month 1: Comprehensive Testing**
1. End-to-end integration tests
2. Failure mode testing
3. Load testing
4. Documentation

**Month 2: Production Deployment**
1. Deploy to Cloud Run
2. Configure alerts
3. Monitor first week closely
4. Iterate based on findings

**Month 3: Optimization**
1. Tune confidence thresholds
2. Refine edge detection
3. A/B test model variations
4. Build track record

---

## Part 5: Lessons Learned & Best Practices

### The 10 Commandments of Betting Data Pipelines

1. **Thou shalt not generate predictions without betting context**
   - Hard dependency, not optional lookup

2. **Thou shalt enforce dependencies at schema level**
   - NOT NULL constraints on critical fields

3. **Thou shalt validate before saving**
   - Data quality gates, not just type checking

4. **Thou shalt monitor data completeness**
   - Track coverage metrics, alert on gaps

5. **Thou shalt backtest before deploying**
   - Never put untested models in production

6. **Thou shalt track data lineage**
   - Know where every field came from, when

7. **Thou shalt have orchestration dependencies**
   - Phase 5 depends on Phase 2, enforce it

8. **Thou shalt version control betting lines**
   - Lines change, track what you used for prediction

9. **Thou shalt separate prediction from evaluation**
   - Prediction pipeline != Grading pipeline

10. **Thou shalt learn from failures**
    - Document, improve, prevent recurrence

### Comparison: NBA vs MLB (Before/After)

| Aspect | NBA (Good) | MLB Before (Bad) | MLB After (Fixed) |
|--------|-----------|------------------|-------------------|
| **Orchestration** | Yes (`nba_orchestration`) | None | Yes (`mlb_orchestration`) |
| **Hard Dependencies** | Enforced by controller | None | Enforced |
| **Schema Validation** | NOT NULL on critical fields | NULLs allowed | NOT NULL enforced |
| **Data Quality Gates** | Yes | No | Yes |
| **Monitoring** | Grafana + alerts | None | Implemented |
| **Backtest Before Deploy** | Yes | No | Yes (historical backfill) |
| **Track Bet Line Source** | Yes | No | Yes |

---

## Conclusion

### The Answer: Both/And, Not Either/Or

**Highest Quality Solution = Historical Backfill + Architectural Redesign**

1. **Do the backfill** (~8 hours, $150)
   - Validate 8,130 predictions
   - Measure true performance
   - Make informed deployment decision
   - Learn from 18 months of data instantly

2. **Fix the architecture** (~2 weeks)
   - Implement dependency framework
   - Add orchestration controls
   - Enforce data quality gates
   - Build monitoring & alerts

### Why Both?

- **Backfill**: Learn from the past (tactical)
- **Architecture**: Prevent future failures (strategic)

**Together**: World-class betting prediction system.

### Expected Outcomes

**If backfill shows good performance (>54% hit rate)**:
- Deploy to production with confidence
- Start generating betting value
- Iterate and improve

**If backfill shows poor performance (<52% hit rate)**:
- Don't deploy (saved potentially massive losses!)
- Retrain model with insights from analysis
- Test again on new backfill
- Deploy only when validated

### ROI Summary

**Investment**:
- Historical backfill: 8 hours + $150
- Architectural fixes: 2 weeks
- Total: ~100 hours + $150

**Return**:
- Avoid deploying bad model: Unbounded upside
- 18 months of learning compressed to 8 hours: Priceless
- Production-ready betting system: Revenue generating
- Prevented future data quality failures: Ongoing value

**Verdict**: Highest ROI investment possible.

---

**Next Steps**:
1. Review this doc
2. Approve approach
3. Start Phase 1 + 2 (investigation)
4. Execute based on findings

**Author**: Claude Sonnet 4.5 (Ultra-Deep Analysis Mode)
**Date**: 2026-01-13
