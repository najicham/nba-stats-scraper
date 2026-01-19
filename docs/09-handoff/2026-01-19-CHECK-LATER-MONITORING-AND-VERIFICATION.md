# Check Later - Monitoring & Verification Tasks

**Created:** 2026-01-18 10:30 PM PST
**Context:** Post Session 110 - Ensemble V1.1 Deployed
**Type:** Ongoing monitoring, scheduled checks, and optional enhancements
**Priority:** MEDIUM to LOW - Not blocking but important

---

## 📊 DAILY MONITORING: Ensemble V1.1 Performance (Jan 20-24)

### Timeline
- **Start:** Jan 20, 2026 (Monday)
- **End:** Jan 24, 2026 (Friday)
- **Frequency:** Once daily (5 minutes per day)
- **Decision Day:** Jan 24, 2026

### Daily Query (Run Each Morning)

```sql
-- Query 1: Daily MAE Comparison
SELECT
  game_date,
  system_id,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(predicted_points - actual_points), 2) as mean_bias,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNT(*)) * 100, 1) as win_rate_pct,
  ROUND(STDDEV(absolute_error), 2) as mae_stddev
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2026-01-20'
  AND game_date <= CURRENT_DATE()
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
  AND system_id IN ('ensemble_v1', 'ensemble_v1_1', 'catboost_v8', 'xgboost_v1_v2')
GROUP BY game_date, system_id
ORDER BY game_date DESC, mae ASC;
```

### Tracking Table

| Date | V1 MAE | V1.1 MAE | CatBoost MAE | V1.1 Status | Notes |
|------|--------|----------|--------------|-------------|-------|
| Jan 20 | ___ | ___ | ___ | ✅/⚠️/🚨 | |
| Jan 21 | ___ | ___ | ___ | ✅/⚠️/🚨 | |
| Jan 22 | ___ | ___ | ___ | ✅/⚠️/🚨 | |
| Jan 23 | ___ | ___ | ___ | ✅/⚠️/🚨 | |
| Jan 24 | ___ | ___ | ___ | ✅/⚠️/🚨 | **DECISION DAY** |

**Status Legend:**
- ✅ Green: MAE ≤ 5.0, on track for promotion
- ⚠️ Yellow: 5.0 < MAE < 5.2, marginal
- 🚨 Red: MAE > 5.2, investigate issues

### Head-to-Head Comparison (Run on Jan 24)

```sql
-- Query 2: 5-Day Aggregate Performance
WITH predictions AS (
  SELECT
    player_lookup,
    game_date,
    MAX(CASE WHEN system_id = 'ensemble_v1' THEN absolute_error END) as v1_error,
    MAX(CASE WHEN system_id = 'ensemble_v1_1' THEN absolute_error END) as v1_1_error,
    MAX(CASE WHEN system_id = 'catboost_v8' THEN absolute_error END) as cb_error
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date BETWEEN '2026-01-20' AND '2026-01-24'
    AND recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
  GROUP BY player_lookup, game_date
  HAVING v1_error IS NOT NULL AND v1_1_error IS NOT NULL
)
SELECT
  COUNT(*) as total_matchups,
  COUNTIF(v1_1_error < v1_error) as v1_1_wins,
  COUNTIF(v1_error < v1_1_error) as v1_wins,
  COUNTIF(v1_1_error = v1_error) as ties,
  ROUND(SAFE_DIVIDE(COUNTIF(v1_1_error < v1_error), COUNT(*)) * 100, 1) as v1_1_win_rate,
  ROUND(AVG(v1_error), 2) as v1_avg_error,
  ROUND(AVG(v1_1_error), 2) as v1_1_avg_error,
  ROUND(AVG(cb_error), 2) as cb_avg_error,
  ROUND(AVG(v1_error) - AVG(v1_1_error), 2) as improvement
FROM predictions;
```

### Decision Criteria (Jan 24)

**PROMOTE to production if:**
- ✅ 5-day average MAE ≤ 5.0
- ✅ Win rate vs Ensemble V1 > 55%
- ✅ No system crashes or errors
- ✅ Prediction volume ≥ 95% of CatBoost V8
- ✅ Mean bias < |1.0| (not systematically OVER or UNDER)

**SHADOW MODE (continue monitoring) if:**
- 5.0 < MAE < 5.2 (marginal improvement, needs more data)
- System occasionally unstable
- Win rate 50-55% vs V1

**ROLLBACK if:**
- MAE > 5.2 (no improvement or worse than V1)
- Prediction coverage < 80%
- System reliability issues (crashes, errors)

### Error Monitoring

```bash
# Check for errors in Ensemble V1.1 predictions
gcloud logging read \
  'resource.labels.service_name:prediction-worker AND severity>=ERROR AND jsonPayload.system_id:ensemble_v1_1' \
  --limit=50 \
  --project=nba-props-platform \
  --freshness=24h
```

**Action if errors found:** Investigate immediately, may need to rollback.

---

## 🔍 VERIFICATION: Sessions 102-105 Metrics (30 minutes)

### Background
Multiple sessions (102-105) implemented various features. Need to verify they're all actually deployed and working.

### Verification Script

There's a script mentioned in Session 107: `verify_sessions_102_103_104_105.sh`

**Location to check:** `bin/` or `scripts/` directory

**What to verify:**
- Session 102: Coordinator batch loading
- Session 103: 4 opponent metrics (pace_differential, opponent_pace_last_10, opponent_ft_rate_allowed, opponent_def_rating_last_10)
- Session 104: 2 opponent metrics (opponent_off_rating_last_10, opponent_rebounding_rate)
- Session 105: opponent_pace_variance

### Manual Verification Query

```sql
-- Check which opponent metrics exist
SELECT
  column_name,
  data_type,
  'EXISTS' as status
FROM `nba-props-platform.nba_analytics.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'upcoming_player_game_context'
  AND column_name IN (
    'pace_differential',
    'opponent_pace_last_10',
    'opponent_ft_rate_allowed',
    'opponent_def_rating_last_10',
    'opponent_off_rating_last_10',
    'opponent_rebounding_rate',
    'opponent_pace_variance'
  )
ORDER BY column_name;

-- Check data population
SELECT
  COUNTIF(pace_differential IS NOT NULL) as pace_diff_pct,
  COUNTIF(opponent_pace_last_10 IS NOT NULL) as pace_pct,
  COUNTIF(opponent_ft_rate_allowed IS NOT NULL) as ft_rate_pct,
  COUNTIF(opponent_def_rating_last_10 IS NOT NULL) as def_rating_pct,
  COUNTIF(opponent_off_rating_last_10 IS NOT NULL) as off_rating_pct,
  COUNTIF(opponent_rebounding_rate IS NOT NULL) as reb_rate_pct,
  COUNTIF(opponent_pace_variance IS NOT NULL) as pace_var_pct,
  COUNT(*) as total
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date >= CURRENT_DATE() - 7;
```

**Expected:** All fields should exist and have >90% population

**If missing:** Similar to Session 107 issue - need to deploy

---

## 🔧 OPTIONAL: Phase 3 Retry Logic for Weekend Games (2-3 hours)

### Background
**Issue:** Weekend games (Friday→Sunday) have 21-hour delay, causing missing predictions.

**Root Cause (70% confidence):**
- Friday evening: Phase 3 scheduler tries to create Sunday game contexts
- Betting lines for Sunday games don't exist yet (published Saturday)
- NBA schedule might not be finalized
- Scheduler runs once, fails, never retries

**Evidence:**
- Jan 17 (Friday): Phase 3 created only 1 record instead of 156
- Session 106 Data Freshness Validator would block predictions (good)
- But we still lose the opportunity to predict

### Solution Options

**Option 1: Add Retry Logic to Phase 3 Scheduler** (Simple, 1 hour)
```python
# In Phase 3 scheduler Cloud Function
MAX_RETRIES = 3
RETRY_DELAY_HOURS = 6

if records_created < expected_games * 0.5:  # Less than 50% created
    # Schedule retry in 6 hours
    scheduler.schedule_retry(delay=RETRY_DELAY_HOURS)
```

**Option 2: Weekend-Specific Scheduler** (Medium, 2 hours)
- Create separate scheduler for Friday evening
- Runs Friday at 8 PM, Saturday at 8 AM, Saturday at 2 PM
- Keeps trying until betting lines available

**Option 3: Event-Driven Pipeline** (Complex, 4-6 hours)
- Trigger Phase 3 when betting lines API updates
- Subscribe to Pub/Sub topic from odds scraper
- Run Phase 3 automatically when new lines detected

**Recommended:** Option 1 (simple retry logic)

**When to implement:** After higher priority items (Session 107, analytics metrics)

---

## 🧪 OPTIONAL: Ridge Meta-Learner Training (4-8 hours)

### Background
Currently have `ml/train_ensemble_v2_meta_learner.py` at 90% complete.

**Purpose:** Train Ridge regression to learn optimal ensemble weights instead of using fixed weights.

**Expected Performance:**
- Current (V1.1 fixed weights): MAE 4.9-5.1
- Target (Ridge learned weights): MAE 4.5-4.7
- Would beat CatBoost V8 (4.81 MAE)

### Status
**Script:** 90% complete, needs debugging

**Known Issues:**
- BigQuery schema differences (33 features vs expected 25)
- Historical games query complexity
- Prediction system integration issues
- All 77K predictions failing silently during training loop

### When to Implement
**Only if:**
- Ensemble V1.1 validates successfully (MAE ≤ 5.0)
- Want to push performance below 4.9 MAE
- Have 4-8 hours for debugging and testing

**Priority:** LOW - V1.1 fixed weights already provide significant improvement

**Alternative:** Wait to see if adding XGBoost V1 V2 to V1.1 is sufficient

---

## 📅 SCHEDULED CHECKS

### Week of Jan 20-24
- **Daily (5 min):** Monitor Ensemble V1.1 performance
- **Friday Jan 24 (1 hour):** Promotion decision
  - Run head-to-head comparison
  - Review error logs
  - Make promote/shadow/rollback decision

### Week of Jan 27+
- **Once:** Verify Sessions 102-105 metrics (30 min)
- **As needed:** Phase 3 retry logic (if weekend games continue to fail)

### Future Sessions
- **Opponent Asymmetry Metrics** (45-60 min) - 3 fields
  - opponent_days_rest
  - opponent_games_in_next_7_days
  - opponent_next_game_days_rest
  - Use case: Detect fatigue mismatches

- **Position-Specific Star Impact** (90-120 min) - 3 fields
  - star_guards_out
  - star_forwards_out
  - star_centers_out
  - Data: espn_team_rosters.position field

---

## 📊 Health Metrics to Monitor

### Prediction Worker Health
```bash
# Check Cloud Run service health
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(status.conditions[0].status,status.latestReadyRevisionName)"

# Should show: True prediction-worker-00072-cz2
```

### Prediction Volume Trends
```sql
-- Check daily prediction counts by system
SELECT
  DATE(created_at) as prediction_date,
  system_id,
  COUNT(*) as predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY prediction_date, system_id
ORDER BY prediction_date DESC, predictions DESC;
```

**Look for:**
- Ensemble V1.1 should have similar volume to Ensemble V1
- No sudden drops in prediction counts
- Consistent daily patterns

### Model Version NULL Check
```sql
-- Verify model_version fix is working
SELECT
  system_id,
  model_version,
  COUNT(*) as predictions,
  ROUND(COUNTIF(model_version IS NULL) * 100.0 / COUNT(*), 1) as null_pct
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE created_at >= '2026-01-18T22:00:00'  -- After fix deployed
GROUP BY system_id, model_version
ORDER BY system_id, null_pct DESC;
```

**Expected:** 0% NULL for all systems (was 62.5% before fix)

---

## 🎯 Success Criteria Summary

### By Jan 24 (5 days)
- ✅ Ensemble V1.1 MAE ≤ 5.0 (promotion decision made)
- ✅ All systems have model_version tracking
- ✅ No major production issues

### By End of January
- ✅ Session 107 metrics deployed (if not already)
- ✅ Forward-looking schedule metrics deployed
- ✅ Sessions 102-105 verified
- ✅ Optional: Opponent asymmetry metrics

### Future (February+)
- ✅ Position-specific star impact
- ✅ Phase 3 retry logic (if needed)
- ✅ Ridge meta-learner (if want <4.9 MAE)

---

## 📝 Notes

**Remember:**
- Don't let perfect be the enemy of good
- Ensemble V1.1 already provides 6-9% improvement
- Focus on high-value features (Session 107, schedule metrics)
- Monitor and validate before adding more complexity

**Quick Wins First:**
1. Deploy Session 107 (closes critical gap)
2. Verify V1.1 working (confirms deployment)
3. Forward-looking metrics (high value, medium effort)
4. Then consider other enhancements

---

**This document is for ongoing monitoring and lower-priority tasks. See NEXT-SESSION-IMMEDIATE-PRIORITIES.md for what to work on NOW.**
