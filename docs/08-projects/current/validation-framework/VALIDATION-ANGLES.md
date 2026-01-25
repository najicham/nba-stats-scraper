# Comprehensive Validation Angles

**Created:** 2026-01-25
**Status:** Active
**Purpose:** Validate pipeline health from multiple angles - daily, hourly, and on-demand

---

## Quick Reference: Validation Cadence

| Validation | Frequency | Runtime | Alert On |
|------------|-----------|---------|----------|
| End-to-End Flow Check | Hourly | ~10s | Missing phase data |
| Multi-Angle Validator | Daily AM | ~30s | Discrepancies |
| Prediction Coverage | Daily AM | ~20s | Gaps > 10% |
| Grading Lag Check | Daily AM | ~10s | Lag > 24h |
| Workflow Decision Audit | On-demand | ~10s | Missing decisions |
| Schedule Accuracy | Hourly | ~5s | Stale > 6h |
| Processor Heartbeat | Every 15m | ~5s | Stale > 1h |
| Phase Timing Analysis | Daily | ~15s | Timeouts |

---

## Validation Angle 1: End-to-End Flow Check

**What it validates:** Data flows through all phases without gaps

**Query:**
```sql
SELECT
  'schedule' as source,
  game_date,
  COUNT(DISTINCT game_id) as games,
  0 as players
FROM `nba_raw.v_nbac_schedule_latest`
WHERE game_date = @check_date AND game_status = 3
GROUP BY 1, 2

UNION ALL

SELECT
  'bdl_boxscores',
  game_date,
  COUNT(DISTINCT game_id),
  COUNT(DISTINCT player_lookup)
FROM `nba_raw.bdl_player_boxscores`
WHERE game_date = @check_date
GROUP BY 1, 2

UNION ALL

SELECT
  'player_game_summary',
  game_date,
  COUNT(DISTINCT game_id),
  COUNT(DISTINCT player_lookup)
FROM `nba_analytics.player_game_summary`
WHERE game_date = @check_date
GROUP BY 1, 2

UNION ALL

SELECT
  'predictions',
  game_date,
  COUNT(DISTINCT game_id),
  COUNT(DISTINCT player_lookup)
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = @check_date
  AND system_id = 'catboost_v8' AND is_active = TRUE
GROUP BY 1, 2

UNION ALL

SELECT
  'grading',
  game_date,
  COUNT(DISTINCT game_id),
  COUNT(DISTINCT player_lookup)
FROM `nba_predictions.prediction_accuracy`
WHERE game_date = @check_date
  AND system_id = 'catboost_v8'
GROUP BY 1, 2

ORDER BY game_date, source
```

**Expected Results:**
- Schedule games = BDL games = Analytics games
- Players roughly consistent across phases
- Grading lags by up to 24h

**Script:** `bin/validation/daily_data_completeness.py`

---

## Validation Angle 2: Multi-Angle Cross-Validation

**What it validates:** Related metrics match across sources

**Angles checked:**
1. **LINES:** Lines available vs predictions made
2. **GAMES:** Games played vs games with predictions
3. **PLAYERS:** Players who played vs players predicted
4. **GRADING:** Predictions made vs graded
5. **ANALYTICS:** Box scores vs analytics processed
6. **FEATURES:** Analytics vs features computed

**Script:** `bin/validation/multi_angle_validator.py`

**Usage:**
```bash
# Check yesterday
python bin/validation/multi_angle_validator.py

# Check specific date
python bin/validation/multi_angle_validator.py --date 2026-01-23

# Check date range
python bin/validation/multi_angle_validator.py --start-date 2026-01-20 --end-date 2026-01-25
```

---

## Validation Angle 3: Props vs Predictions Coverage

**What it validates:** We're making predictions for all available prop lines

**Query:**
```sql
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games,
  COUNT(DISTINCT player_lookup) as players_predicted,
  COUNTIF(line_source = 'ACTUAL_PROP') as with_prop_line,
  COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable,
  (SELECT COUNT(DISTINCT player_lookup)
   FROM `nba_raw.odds_api_player_points_props` o
   WHERE o.game_date = p.game_date) as players_with_props
FROM `nba_predictions.player_prop_predictions` p
WHERE game_date = @check_date
  AND system_id = 'catboost_v8' AND is_active = TRUE
GROUP BY 1
```

**Expected:**
- `with_prop_line` >= 80% of `players_with_props`
- `actionable` should be meaningful (not 0)

**Script:** `bin/validation/check_prediction_coverage.py`

---

## Validation Angle 4: Workflow Decision Audit

**What it validates:** Master controller made decisions during critical periods

**Query:**
```sql
SELECT
  decision_time,
  workflow_name,
  action,
  reason
FROM `nba_orchestration.workflow_decisions`
WHERE decision_time >= @start_time
ORDER BY decision_time
```

**Expected:**
- Regular decisions (RUN/SKIP) every hour
- No long gaps indicating controller was blocked
- ABORT decisions should have clear reasons

**When to use:** After outages to understand system behavior

---

## Validation Angle 5: Single Game Trace

**What it validates:** Specific game flows through all phases

**Query:**
```sql
WITH game_pick AS (
  SELECT game_id
  FROM `nba_raw.v_nbac_schedule_latest`
  WHERE game_date = @check_date AND game_status = 3
  LIMIT 1
)
SELECT phase, game_id, record_count FROM (
  SELECT 'schedule' as phase, g.game_id, 1 as record_count
  FROM game_pick g

  UNION ALL

  SELECT 'bdl_boxscores', g.game_id, COUNT(*)
  FROM game_pick g
  JOIN `nba_raw.bdl_player_boxscores` b
    ON g.game_id = b.game_id AND b.game_date = @check_date
  GROUP BY 1, 2

  UNION ALL

  SELECT 'analytics', g.game_id, COUNT(*)
  FROM game_pick g
  JOIN `nba_analytics.player_game_summary` p
    ON g.game_id = p.game_id AND p.game_date = @check_date
  GROUP BY 1, 2

  UNION ALL

  SELECT 'predictions', g.game_id, COUNT(*)
  FROM game_pick g
  JOIN `nba_predictions.player_prop_predictions` pr
    ON g.game_id = pr.game_id AND pr.game_date = @check_date
    AND pr.system_id = 'catboost_v8' AND pr.is_active = TRUE
  GROUP BY 1, 2

  UNION ALL

  SELECT 'grading', g.game_id, COUNT(*)
  FROM game_pick g
  JOIN `nba_predictions.prediction_accuracy` a
    ON g.game_id = a.game_id AND a.game_date = @check_date
    AND a.system_id = 'catboost_v8'
  GROUP BY 1, 2
)
ORDER BY phase
```

**Expected:** All phases present with non-zero records

---

## Validation Angle 6: Schedule Accuracy

**What it validates:** Schedule view reflects current game statuses

**Query:**
```sql
SELECT
  game_date,
  game_status,
  COUNT(*) as games,
  MAX(loaded_at) as last_update
FROM `nba_raw.v_nbac_schedule_latest`
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY 1, 2
ORDER BY 1, 2
```

**Expected:**
- Yesterday's games should all be status=3 (Final)
- `last_update` should be < 6 hours old

---

## Validation Angle 7: Processor Completions

**What it validates:** All expected processors ran for each game date

**Query:**
```sql
SELECT
  game_date,
  processor_name,
  COUNT(*) as run_count,
  MAX(completed_at) as last_run
FROM `nba_orchestration.processor_completions`
WHERE game_date = @check_date
  AND status = 'success'
GROUP BY 1, 2
ORDER BY 1, 2
```

**Expected Processors for Phase 2:**
- BdlPlayerBoxScoresProcessor
- BdlLiveBoxscoresProcessor
- NbacScheduleProcessor
- OddsGameLinesProcessor

---

## Validation Angle 8: Pipeline Event Log Analysis

**What it validates:** Processors are starting and completing without errors

**Query:**
```sql
SELECT
  event_type,
  phase,
  processor_name,
  COUNT(*) as count,
  COUNTIF(event_type = 'error') as errors
FROM `nba_orchestration.pipeline_event_log`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY 1, 2, 3
HAVING errors > 0 OR event_type = 'processor_start'
ORDER BY phase, processor_name, event_type
```

**Expected:**
- `processor_start` count ≈ `processor_complete` count
- `errors` should be 0 or minimal

---

## Validation Angle 9: Failed Processor Queue

**What it validates:** Auto-retry system is working

**Query:**
```sql
SELECT
  status,
  phase,
  COUNT(*) as count,
  MAX(first_failure_at) as most_recent
FROM `nba_orchestration.failed_processor_queue`
GROUP BY 1, 2
```

**Expected:**
- `pending` count should be 0 or decreasing
- `failed_permanent` requires manual intervention
- `succeeded` shows auto-retry working

---

## Validation Angle 10: Phase Timing Analysis

**What it validates:** Phases complete within expected windows

**Query:**
```sql
SELECT
  game_date,
  phase_name,
  status,
  duration_seconds,
  games_processed
FROM `nba_orchestration.phase_execution_log`
WHERE game_date >= @check_date
ORDER BY game_date, phase_name
```

**Expected Timing:**
- Phase 2→3: < 30 min after last game
- Phase 3→4: < 1 hour
- Phase 4→5: < 30 min
- Phase 5→6: < 15 min

---

## Validation Angle 11: Prediction Timing

**What it validates:** Predictions made before game time

**Query:**
```sql
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNTIF(prediction_time < game_time) as before_game,
  COUNTIF(prediction_time >= game_time) as after_game,
  ROUND(COUNTIF(prediction_time < game_time) * 100.0 / COUNT(*), 1) as pct_before
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = @check_date
  AND system_id = 'catboost_v8'
  AND is_active = TRUE
GROUP BY 1
```

**Expected:** 100% predictions before game time

---

## Validation Angle 12: Grading Lag

**What it validates:** Grading keeps up with predictions

**Query:**
```sql
WITH predictions AS (
  SELECT game_date, COUNT(*) as pred_count
  FROM `nba_predictions.player_prop_predictions`
  WHERE game_date >= CURRENT_DATE() - 7
    AND system_id = 'catboost_v8'
    AND is_active = TRUE
    AND has_prop_line = TRUE
  GROUP BY 1
),
graded AS (
  SELECT game_date, COUNT(*) as graded_count
  FROM `nba_predictions.prediction_accuracy`
  WHERE game_date >= CURRENT_DATE() - 7
    AND system_id = 'catboost_v8'
  GROUP BY 1
)
SELECT
  p.game_date,
  p.pred_count,
  COALESCE(g.graded_count, 0) as graded_count,
  ROUND(COALESCE(g.graded_count, 0) * 100.0 / p.pred_count, 1) as grading_pct
FROM predictions p
LEFT JOIN graded g ON p.game_date = g.game_date
ORDER BY p.game_date DESC
```

**Expected:** Games > 24h old should be 90%+ graded

---

## Validation Angle 13: Data Quality Scores

**What it validates:** Feature quality remains high

**Query:**
```sql
SELECT
  game_date,
  COUNT(*) as features,
  AVG(feature_quality_score) as avg_quality,
  COUNTIF(feature_quality_score < 0.7) as low_quality_count
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = @check_date
GROUP BY 1
```

**Expected:**
- `avg_quality` > 0.8
- `low_quality_count` < 10% of total

---

## Validation Angle 14: GCS Export Verification

**What it validates:** Phase 6 exports landed in GCS

**Command:**
```bash
# Check tonight's exports
gsutil ls -l gs://nba-props-platform-api/tonight/ | head -10

# Check export timestamps
gsutil stat gs://nba-props-platform-api/tonight/index.json | grep Updated
```

**Expected:** Files updated within last 4 hours on game days

---

## Validation Angle 15: Firestore State Consistency

**What it validates:** Firestore state matches BigQuery reality

**Command:**
```bash
# Check Firestore phase completion state
python3 -c "
from google.cloud import firestore
db = firestore.Client()
for doc in db.collection('phase2_completion').order_by('__name__', direction='DESCENDING').limit(5).stream():
    print(f'{doc.id}: {doc.to_dict()}')
"
```

**Expected:** States should match processor_completions table

---

## Validation Angle 16: Workflow Decision Gaps

**What it validates:** Master controller is running and making decisions

**Query:**
```sql
WITH decisions_with_gaps AS (
  SELECT
    decision_time,
    LAG(decision_time) OVER (ORDER BY decision_time) as prev_decision,
    TIMESTAMP_DIFF(decision_time, LAG(decision_time) OVER (ORDER BY decision_time), MINUTE) as gap_minutes
  FROM `nba_orchestration.workflow_decisions`
  WHERE decision_time >= CURRENT_TIMESTAMP() - INTERVAL 48 HOUR
)
SELECT
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M', prev_decision) as from_time,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M', decision_time) as to_time,
  gap_minutes,
  ROUND(gap_minutes / 60.0, 1) as gap_hours
FROM decisions_with_gaps
WHERE gap_minutes > 120  -- Gaps > 2 hours
ORDER BY gap_minutes DESC
```

**Expected:** No gaps > 2 hours during business hours (8 AM - 2 AM PT)

**Alert condition:** Gap > 2 hours indicates master controller blocked

---

## Daily Morning Validation Checklist

Run these every morning before 8 AM:

```bash
# 1. Data completeness (last 7 days)
python bin/validation/daily_data_completeness.py --days 7

# 2. Multi-angle validation (yesterday)
python bin/validation/multi_angle_validator.py --date $(date -d yesterday +%Y-%m-%d)

# 3. Prediction coverage (weekly view)
python bin/validation/check_prediction_coverage.py --weeks 4

# 4. Quick BQ health check
bq query --use_legacy_sql=false "
SELECT 'boxscores' as check, game_date, COUNT(*) as records
FROM nba_raw.bdl_player_boxscores
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY 1,2
UNION ALL
SELECT 'analytics', game_date, COUNT(*)
FROM nba_analytics.player_game_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY 1,2
ORDER BY check, game_date DESC"
```

---

## Hourly Validation (Automated)

These should run via Cloud Scheduler:

1. **Schedule Staleness Check** - Alert if > 6h stale
2. **Pipeline Event Errors** - Alert on any new errors
3. **Failed Processor Queue** - Alert on pending items
4. **Memory Usage** - Alert if > 80% on Cloud Functions

---

## On-Demand Investigation Queries

### Find Missing Data

```sql
-- Games with boxscores but no analytics
SELECT b.game_date, b.game_id, COUNT(*) as boxscore_players
FROM `nba_raw.bdl_player_boxscores` b
LEFT JOIN `nba_analytics.player_game_summary` a
  ON b.game_id = a.game_id AND b.game_date = a.game_date
WHERE b.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND a.game_id IS NULL
GROUP BY 1, 2
ORDER BY 1
```

### Find Stale Processors

```sql
-- Processors that haven't run in > 24h
SELECT
  processor_name,
  MAX(completed_at) as last_run,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(completed_at), HOUR) as hours_ago
FROM `nba_orchestration.processor_completions`
WHERE status = 'success'
GROUP BY 1
HAVING hours_ago > 24
ORDER BY hours_ago DESC
```

### Compare Across Systems

```sql
-- Prediction counts by system
SELECT
  game_date,
  system_id,
  COUNT(*) as predictions,
  COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable
FROM `nba_predictions.player_prop_predictions`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND is_active = TRUE
GROUP BY 1, 2
ORDER BY 1 DESC, 2
```

---

---

## Additional Validation Angles

### Validation Angle 17: Prediction-to-Actuals Join Rate

**What it validates:** Are predictions for players who actually played?

```sql
SELECT
  p.game_date,
  COUNT(*) as predictions,
  COUNTIF(a.player_lookup IS NOT NULL) as matched_actuals,
  COUNTIF(a.player_lookup IS NULL) as unmatched,
  ROUND(COUNTIF(a.player_lookup IS NOT NULL) * 100.0 / COUNT(*), 1) as match_rate
FROM `nba_predictions.player_prop_predictions` p
LEFT JOIN `nba_analytics.player_game_summary` a
  ON p.player_lookup = a.player_lookup AND p.game_date = a.game_date
WHERE p.game_date = @check_date
  AND p.system_id = 'catboost_v8' AND p.is_active = TRUE
GROUP BY 1
```

**Expected:** 95%+ match rate (DNPs account for small mismatch)

---

### Validation Angle 18: System Consistency

**What it validates:** Do all prediction systems produce similar counts?

```sql
SELECT
  system_id,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as players
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = @check_date AND is_active = TRUE
GROUP BY 1
ORDER BY 1
```

**Expected:** All systems should have similar player counts (within 5%)

---

### Validation Angle 19: Line Value Sanity

**What it validates:** Are line values reasonable?

```sql
SELECT
  CASE
    WHEN current_points_line < 5 THEN '<5'
    WHEN current_points_line < 15 THEN '5-15'
    WHEN current_points_line < 25 THEN '15-25'
    WHEN current_points_line < 35 THEN '25-35'
    ELSE '35+'
  END as line_bucket,
  COUNT(*) as count
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = @check_date
  AND system_id = 'catboost_v8' AND is_active = TRUE
  AND line_source = 'ACTUAL_PROP'
GROUP BY 1
ORDER BY 1
```

**Expected:** Normal distribution centered around 15-25

---

### Validation Angle 20: Prediction Confidence Distribution

**What it validates:** Is confidence score distribution normal?

```sql
SELECT
  CASE
    WHEN confidence_score < 0.5 THEN '<50%'
    WHEN confidence_score < 0.6 THEN '50-60%'
    WHEN confidence_score < 0.7 THEN '60-70%'
    WHEN confidence_score < 0.8 THEN '70-80%'
    WHEN confidence_score < 0.9 THEN '80-90%'
    ELSE '90%+'
  END as confidence_bucket,
  COUNT(*) as count
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = @check_date
  AND system_id = 'catboost_v8' AND is_active = TRUE
GROUP BY 1
ORDER BY 1
```

**Expected:** Majority in 60-80% range, few at extremes

---

### Validation Angle 21: Historical Accuracy Drift

**What it validates:** Is model accuracy degrading over time?

```sql
SELECT
  FORMAT_DATE('%Y-W%W', game_date) as week,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as hit_rate,
  COUNT(*) as predictions
FROM `nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
  AND system_id = 'catboost_v8'
GROUP BY 1
ORDER BY 1
```

**Expected:** Stable hit rate (50-55%), not declining

---

### Validation Angle 22: Player Registry Coverage

**What it validates:** Are predicted players in the registry?

```sql
SELECT
  CASE WHEN r.universal_player_id IS NOT NULL THEN 'in_registry' ELSE 'missing' END as status,
  COUNT(DISTINCT p.player_lookup) as players
FROM `nba_predictions.player_prop_predictions` p
LEFT JOIN `nba_reference.nba_players_registry` r
  ON p.player_lookup = r.player_lookup
WHERE p.game_date = @check_date
  AND p.system_id = 'catboost_v8' AND p.is_active = TRUE
GROUP BY 1
```

**Expected:** 100% in registry (missing players = data issue)

---

### Validation Angle 23: Game-Level Balance

**What it validates:** Are predictions balanced across games?

```sql
SELECT
  game_id,
  COUNT(DISTINCT player_lookup) as players_predicted,
  MIN(predicted_points) as min_predicted,
  MAX(predicted_points) as max_predicted,
  ROUND(AVG(predicted_points), 1) as avg_predicted
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = @check_date
  AND system_id = 'catboost_v8' AND is_active = TRUE
GROUP BY 1
ORDER BY players_predicted
```

**Expected:** Similar player counts per game (8-15 per team, 16-30 per game)

---

### Validation Angle 24: Recommendation Balance

**What it validates:** Are OVER/UNDER recommendations balanced?

```sql
SELECT
  recommendation,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = @check_date
  AND system_id = 'catboost_v8' AND is_active = TRUE
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY 1
```

**Expected:** Roughly 50/50 split (45-55% each direction)

---

### Validation Angle 25: Voided Predictions Rate

**What it validates:** How many predictions are voided (DNP/injury)?

```sql
SELECT
  void_reason,
  COUNT(*) as count
FROM `nba_predictions.prediction_accuracy`
WHERE game_date = @check_date
  AND system_id = 'catboost_v8'
  AND is_voided = TRUE
GROUP BY 1
```

**Expected:** <10% voided (high void rate = bad injury filtering)

---

## Related Documentation

- [Existing Validation Framework](../../comprehensive-improvements-jan-2026/VALIDATION-FRAMEWORK-GUIDE.md)
- [Pipeline Resilience Plan](../pipeline-resilience-improvements/RESILIENCE-PLAN-2026-01-24.md)
- [Troubleshooting Runbook](../../00-orchestration/troubleshooting.md)
- [Daily Operations](../../02-operations/MORNING-VALIDATION-GUIDE.md)
