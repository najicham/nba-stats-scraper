# Session 85: NBA Prediction Grading (Phase 6)

**Status**: Ready to Start (independent of alerting work)
**Priority**: High (revenue-impacting feature)
**Estimated Scope**: 4-6 hours
**Prerequisites**: Understanding of MLB grading system (already implemented)

---

## Objective

Implement automated prediction grading for NBA to evaluate model accuracy and track performance over time.

**Success Criteria**:
- [ ] Grading service deployed (Cloud Run or Cloud Function)
- [ ] Predictions graded automatically after games complete
- [ ] Grading results stored in BigQuery
- [ ] Accuracy metrics tracked and queryable
- [ ] Integration with existing orchestration

---

## Context

### Current State (from Session 82 validation)
- **NBA predictions**: Generated successfully for upcoming games
- **Boxscores**: Ingested reliably (BDL + NBA.com)
- **Player game summaries**: Created with actual results
- **Grading**: ❌ **NOT IMPLEMENTED** for NBA

### Why This Matters
From validation report:
> **Phase 6 (Grading)**: ❌ Not yet implemented for NBA
> - Currently MLB-only feature
> - Impact: Cannot auto-evaluate prediction accuracy
> - Workaround: Manual spot-checks

**Business Impact**:
- Cannot measure model ROI
- Cannot identify model drift
- Cannot validate improvements
- Cannot report accuracy to stakeholders

---

## What to Build: NBA Grading System

### Architecture (Mirror MLB Implementation)

**Inputs**:
1. **Predictions**: `nba_predictions.player_prop_predictions`
   - Fields: `player_lookup`, `game_date`, `predicted_points`, `confidence_score`, `recommendation`, `current_points_line`

2. **Actual Results**: `nba_analytics.player_game_summary`
   - Fields: `player_lookup`, `game_date`, `points` (actual)

**Processing**:
1. **Match predictions to actuals** (join on player + game_date)
2. **Calculate grading metrics**:
   - Did player go OVER/UNDER the line?
   - Was prediction correct?
   - Margin of error
   - Confidence calibration

3. **Store results**: `nba_predictions.prediction_grades` (new table)

**Outputs**:
- Grading table with win/loss records
- Aggregate accuracy metrics
- Confidence calibration data

### Key Metrics to Track

1. **Overall Accuracy**: % of correct OVER/UNDER predictions
2. **Accuracy by Confidence**: Calibration (90% confidence → 90% accuracy?)
3. **Average Margin**: How close were point predictions?
4. **ROI Simulation**: If betting $100/game, what's the return?
5. **Accuracy by Player Tier**: Stars vs. bench players
6. **Accuracy by Line Range**: High lines (25+ pts) vs. low lines (10- pts)

---

## Implementation Steps

### Phase 1: Review MLB Implementation (30 min)

1. **Find MLB grading code**:
   ```bash
   find . -name "*grad*" -type f | grep -i mlb
   find . -name "*phase6*" -type f
   ```

2. **Study MLB grading logic**:
   - How are predictions matched to results?
   - What metrics are calculated?
   - How is it triggered (Cloud Scheduler? Pub/Sub?)

3. **Identify reusable components**:
   - SQL queries
   - Grading algorithms
   - BigQuery table schemas

### Phase 2: Design NBA Grading Schema (30 min)

Create table: `nba_predictions.prediction_grades`

**Schema** (adapt from MLB):
```sql
CREATE TABLE `nba-props-platform.nba_predictions.prediction_grades` (
  -- Identifiers
  prediction_id STRING,
  player_lookup STRING,
  game_id STRING,
  game_date DATE,

  -- Prediction details
  predicted_points FLOAT64,
  confidence_score FLOAT64,
  recommendation STRING,  -- OVER, UNDER, PASS
  points_line FLOAT64,

  -- Actual results
  actual_points INT64,
  actual_vs_line STRING,  -- OVER, UNDER, PUSH

  -- Grading results
  prediction_correct BOOL,
  margin_of_error FLOAT64,  -- |predicted - actual|
  line_margin FLOAT64,  -- How far actual was from line

  -- Metadata
  graded_at TIMESTAMP,
  grading_version STRING,
  data_quality_tier STRING,
  has_issues BOOL,
  issues ARRAY<STRING>
)
PARTITION BY game_date
CLUSTER BY player_lookup, prediction_correct, confidence_score;
```

**Indexes/Views** to create:
- `prediction_accuracy_summary` - Daily/weekly accuracy rollups
- `confidence_calibration` - Confidence vs. actual accuracy
- `player_prediction_performance` - Per-player accuracy

### Phase 3: Implement Grading Logic (2 hours)

**Option A: Cloud Function** (Recommended)
```python
# functions/nba_prediction_grader/main.py

def grade_predictions(request):
    """
    Grade NBA predictions for completed games.
    Triggered daily via Cloud Scheduler.
    """
    # 1. Find games completed yesterday
    yesterday = (datetime.now() - timedelta(days=1)).date()

    # 2. Query predictions for those games
    predictions = query_predictions(yesterday)

    # 3. Query actual results from player_game_summary
    actuals = query_actuals(yesterday)

    # 4. Join and grade
    grades = calculate_grades(predictions, actuals)

    # 5. Write to prediction_grades table
    write_grades(grades)

    # 6. Log summary
    accuracy = sum(g['prediction_correct'] for g in grades) / len(grades)
    log(f"Graded {len(grades)} predictions, accuracy: {accuracy:.1%}")

    return {"graded": len(grades), "accuracy": accuracy}
```

**Option B: Cloud Run Service** (if need more control/performance)

**Option C: BigQuery Scheduled Query** (simplest for MVP)
- Create scheduled query that runs daily
- Directly inserts into prediction_grades
- No code deployment needed

**Recommendation**: Start with **Option C** (scheduled query), migrate to **Option A** if more complex logic needed.

### Phase 4: Implement Scheduled Query (1.5 hours)

Create BigQuery scheduled query:

```sql
-- NBA Prediction Grading Query
-- Schedule: Daily at 12:00 PM PT (after boxscores ingested)
-- Destination: nba_predictions.prediction_grades

INSERT INTO `nba-props-platform.nba_predictions.prediction_grades`
SELECT
  p.prediction_id,
  p.player_lookup,
  p.game_id,
  p.game_date,

  -- Prediction details
  p.predicted_points,
  p.confidence_score,
  p.recommendation,
  p.current_points_line as points_line,

  -- Actual results
  a.points as actual_points,
  CASE
    WHEN a.points > p.current_points_line THEN 'OVER'
    WHEN a.points < p.current_points_line THEN 'UNDER'
    ELSE 'PUSH'
  END as actual_vs_line,

  -- Grading results
  CASE
    WHEN p.recommendation = 'PASS' THEN NULL  -- Don't grade PASS predictions
    WHEN p.recommendation = 'OVER' AND a.points > p.current_points_line THEN TRUE
    WHEN p.recommendation = 'UNDER' AND a.points < p.current_points_line THEN TRUE
    WHEN a.points = p.current_points_line THEN NULL  -- PUSH, no win/loss
    ELSE FALSE
  END as prediction_correct,

  ABS(p.predicted_points - a.points) as margin_of_error,
  a.points - p.current_points_line as line_margin,

  -- Metadata
  CURRENT_TIMESTAMP() as graded_at,
  'v1' as grading_version,
  a.data_quality_tier,
  CASE
    WHEN a.points IS NULL THEN TRUE
    WHEN a.data_quality_tier != 'gold' THEN TRUE
    ELSE FALSE
  END as has_issues,
  CASE
    WHEN a.points IS NULL THEN ['missing_actual_points']
    WHEN a.data_quality_tier != 'gold' THEN [CONCAT('quality_tier_', a.data_quality_tier)]
    ELSE []
  END as issues

FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` a
  ON p.player_lookup = a.player_lookup
  AND p.game_date = a.game_date

WHERE
  -- Only grade games from yesterday (configurable)
  p.game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)

  -- Only grade active predictions
  AND p.is_active = TRUE

  -- Only grade catboost_v8 system
  AND p.system_id = 'catboost_v8'

  -- Don't re-grade already graded predictions
  AND p.prediction_id NOT IN (
    SELECT prediction_id FROM `nba-props-platform.nba_predictions.prediction_grades`
  )
```

**Setup**:
```bash
# Create scheduled query via gcloud or BigQuery UI
# Name: nba-prediction-grading-daily
# Schedule: 0 12 * * * (daily at noon PT)
# Timezone: America/Los_Angeles
```

### Phase 5: Create Reporting Views (45 min)

**View 1: Daily Accuracy Summary**
```sql
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.prediction_accuracy_summary` AS
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNTIF(prediction_correct) as correct_predictions,
  COUNTIF(NOT prediction_correct) as incorrect_predictions,
  COUNTIF(prediction_correct IS NULL) as ungradeable,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNTIF(prediction_correct IS NOT NULL), 2) as accuracy_pct,
  ROUND(AVG(margin_of_error), 2) as avg_margin_of_error,
  ROUND(AVG(confidence_score) * 100, 2) as avg_confidence
FROM `nba-props-platform.nba_predictions.prediction_grades`
WHERE has_issues = FALSE
GROUP BY game_date
ORDER BY game_date DESC;
```

**View 2: Confidence Calibration**
```sql
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.confidence_calibration` AS
SELECT
  ROUND(confidence_score * 100) as confidence_bucket,
  COUNT(*) as total_predictions,
  COUNTIF(prediction_correct) as correct_predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 2) as actual_accuracy_pct,
  ROUND(AVG(confidence_score) * 100, 2) as avg_confidence
FROM `nba-props-platform.nba_predictions.prediction_grades`
WHERE
  prediction_correct IS NOT NULL
  AND has_issues = FALSE
GROUP BY confidence_bucket
HAVING COUNT(*) >= 10  -- Min sample size
ORDER BY confidence_bucket DESC;
```

**View 3: Player Performance**
```sql
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.player_prediction_performance` AS
SELECT
  player_lookup,
  COUNT(*) as total_predictions,
  COUNTIF(prediction_correct) as correct,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNTIF(prediction_correct IS NOT NULL), 2) as accuracy_pct,
  ROUND(AVG(margin_of_error), 2) as avg_margin_of_error,
  ROUND(AVG(CASE WHEN prediction_correct THEN confidence_score ELSE NULL END) * 100, 2) as avg_confidence_when_correct,
  MIN(game_date) as first_prediction,
  MAX(game_date) as last_prediction
FROM `nba-props-platform.nba_predictions.prediction_grades`
WHERE has_issues = FALSE
GROUP BY player_lookup
HAVING COUNT(*) >= 5  -- Min sample size
ORDER BY accuracy_pct DESC;
```

### Phase 6: Integration & Testing (1 hour)

1. **Create grading table**:
   ```bash
   bq mk --table nba-props-platform:nba_predictions.prediction_grades [schema_file.json]
   ```

2. **Test grading query manually**:
   ```bash
   # Run for a specific historical date first
   bq query --use_legacy_sql=false '[modified query with specific date]'
   ```

3. **Verify results**:
   ```bash
   bq query --use_legacy_sql=false '
   SELECT * FROM `nba-props-platform.nba_predictions.prediction_grades`
   ORDER BY graded_at DESC LIMIT 10'
   ```

4. **Check accuracy views**:
   ```bash
   bq query --use_legacy_sql=false '
   SELECT * FROM `nba-props-platform.nba_predictions.prediction_accuracy_summary`
   ORDER BY game_date DESC LIMIT 7'
   ```

5. **Set up scheduled query**:
   - Via BigQuery UI or gcloud
   - Test with dry run first

6. **Monitor first few runs**:
   - Check logs
   - Verify data quality
   - Ensure no duplicates

### Phase 7: Documentation (30 min)

Update documentation:

1. **Create grading runbook**: `docs/06-grading/NBA-GRADING-SYSTEM.md`
   - How grading works
   - Query logic
   - Metrics definitions
   - How to troubleshoot

2. **Update IMPLEMENTATION-ROADMAP.md**:
   - Mark NBA grading as complete
   - Note completion date

3. **Create handoff**: `docs/09-handoff/SESSION-85-NBA-GRADING-COMPLETE.md`
   - Implementation summary
   - Table schemas
   - Query schedule
   - How to query results
   - Known limitations

---

## Key Considerations

### Edge Cases to Handle

1. **Games postponed/cancelled**: Predictions exist but no actuals
   - Mark as `has_issues = TRUE`, `issues = ['no_actual_result']`

2. **Players didn't play (DNP)**: Actual points = 0 but unfair to grade
   - Check `minutes_played = 0`
   - Mark as ungradeable

3. **Line pushes**: Actual points exactly equals line
   - `prediction_correct = NULL` (not right or wrong)

4. **Multiple predictions for same game**: Superseded predictions
   - Only grade `is_active = TRUE` predictions
   - Or grade all but track supersession

5. **Data quality issues**: Bronze/silver tier data
   - Track in `has_issues` field
   - Optionally exclude from accuracy calculations

### Data Quality

From Session 82 validation, NBA data is "gold" tier. But still need to handle:
- Missing boxscores (rare)
- Delayed boxscores (grade later)
- Incorrect boxscores (manual correction)

**Recommendation**:
- Grade games 1 day after completion (12 hours buffer)
- Flag low-quality data but still grade
- Allow manual re-grading if needed

### Performance

**Expected volume**:
- ~250 predictions/day
- ~90,000 predictions/year
- Grading query should be fast (<10 seconds)

**Optimization**:
- Use partitioned table (by game_date)
- Cluster by player_lookup
- Scheduled query runs daily, not real-time

---

## Validation Queries

### Check Grading Coverage
```sql
-- Are all completed games being graded?
SELECT
  g.game_date,
  COUNT(DISTINCT g.player_lookup) as players_with_actuals,
  COUNT(DISTINCT p.player_lookup) as players_with_predictions,
  COUNT(DISTINCT grade.player_lookup) as players_graded,
  COUNT(DISTINCT p.player_lookup) - COUNT(DISTINCT grade.player_lookup) as missing_grades
FROM `nba-props-platform.nba_analytics.player_game_summary` g
LEFT JOIN `nba-props-platform.nba_predictions.player_prop_predictions` p
  ON g.player_lookup = p.player_lookup AND g.game_date = p.game_date
LEFT JOIN `nba-props-platform.nba_predictions.prediction_grades` grade
  ON p.prediction_id = grade.prediction_id
WHERE g.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY g.game_date
ORDER BY g.game_date DESC;
```

### Check Calibration
```sql
-- Are our confidence scores well-calibrated?
SELECT * FROM `nba-props-platform.nba_predictions.confidence_calibration`
ORDER BY confidence_bucket DESC;
-- Expected: 90% confidence → ~90% accuracy
```

### Check Recent Performance
```sql
-- Last 7 days accuracy
SELECT
  game_date,
  accuracy_pct,
  total_predictions,
  avg_margin_of_error
FROM `nba-props-platform.nba_predictions.prediction_accuracy_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY game_date DESC;
```

---

## Success Checklist

- [ ] `prediction_grades` table created with proper schema
- [ ] Grading query tested and working
- [ ] Scheduled query configured (daily at noon PT)
- [ ] 3 reporting views created and queryable
- [ ] Historical backfill completed (at least 7 days)
- [ ] Calibration check shows reasonable alignment
- [ ] Documentation created (runbook + handoff)
- [ ] IMPLEMENTATION-ROADMAP.md updated

---

## Optional Enhancements

If time permits or in follow-up session:

1. **Alerting on poor accuracy**:
   - Alert if 7-day accuracy drops below 55%
   - Could indicate model drift

2. **Historical backfill**:
   - Grade all historical predictions (from Jan 14+)
   - Provides baseline metrics

3. **ROI calculator**:
   - Simulate betting strategy
   - Calculate theoretical profit/loss

4. **Grading dashboard**:
   - Looker Studio dashboard with accuracy trends
   - Confidence calibration charts
   - Player performance leaderboard

5. **A/B testing support**:
   - Track multiple model versions
   - Compare accuracy between models

---

## Troubleshooting

**Issue**: Grading query returns 0 rows
- Check: Do actuals exist in player_game_summary?
- Check: Are game_dates matching correctly?
- Check: Is `is_active = TRUE` filtering too aggressively?

**Issue**: Accuracy seems too low (<50%)
- Check: Is recommendation logic inverted?
- Check: Are PUSH cases handled correctly?
- Check: Data quality issues in actuals?

**Issue**: Duplicate grades created
- Check: Is deduplication logic working (prediction_id NOT IN...)?
- May need to add UNIQUE constraint or change to MERGE instead of INSERT

---

## Related Sessions

- **Session 82**: Prediction system validation (context)
- **Session 83/84**: Alerting (could add grading alerts)
- **Future**: Grading dashboard and ROI analysis

---

**Ready to start**: Copy this document content into a new chat to begin implementation.
**Estimated completion**: 4-6 hours for full implementation, testing, and documentation.

**Quick win**: Start with scheduled query approach - can be live in 2-3 hours!
