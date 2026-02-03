# Session 96 Handoff - ML Feature Quality Investigation

**Date:** 2026-02-03
**Model:** Claude Opus 4.5
**Focus:** Root cause analysis of poor ML feature quality and prevention strategies

---

## Executive Summary

Session 96 investigated why Feb 2 predictions had poor hit rate (49.1%) despite having "high-edge" picks. The root cause was **timing misalignment** between Phase 4 data generation and ML feature store updates, causing predictions to use stale/default feature values.

---

## Key Findings

### 1. The Feb 2 Failure Pattern

All 9 missed high-edge picks on Feb 2 were **UNDER bets** for players with **low feature quality (71.38%)**:

| Player | Edge | Predicted | Actual | Result |
|--------|------|-----------|--------|--------|
| treymurphyiii | 11.4 | 11.1 | 27 | MISS |
| jarenjacksonjr | 8.7 | 13.8 | 30 | MISS |
| jabarismithjr | 8.1 | 9.4 | 19 | MISS |
| kobesanders | 6.5 | 5.0 | 17 | MISS |
| kellyoubrejr | 6.2 | 8.3 | 15 | MISS |
| vincewilliamsjr | 4.7 | 3.8 | 16 | MISS |

**Pattern:** Low-quality features cause **underprediction** (predicting fewer points than actual), creating **false high-edge UNDER signals**.

### 2. Root Cause: Timing Misalignment

The Feb 2 data pipeline had a critical timing issue:

| Event | Time (ET) | Issue |
|-------|-----------|-------|
| ML Features Feb 2 | Feb 2, 6:00 AM | Created BEFORE Phase 4 |
| Predictions Feb 2 | Feb 2, 4:38 PM | Used stale features |
| Phase 4 Feb 2 | Feb 3, 2:00 AM | Created AFTER predictions |

**The ML feature store ran 20+ hours BEFORE Phase 4 completed**, causing:
- Features used default values (40 points) instead of Phase 4 data (100 points)
- Quality score dropped to 71.38% (vs expected 85%+)
- Model systematically underpredicted

### 3. Quality Score Calculation

From `data_processors/precompute/ml_feature_store/quality_scorer.py`:

| Data Source | Quality Points |
|-------------|----------------|
| Phase 4 | 100 |
| Phase 3 | 87 |
| Default (missing) | 40 |
| Calculated | 100 |

A quality score of 71.38% indicates ~40% of features used default values.

### 4. Current Schedule (Session 95)

| Time (ET) | Job | Purpose |
|-----------|-----|---------|
| 6:00 AM | overnight-phase4 | Generate Phase 4 precompute |
| 7:00 AM | ml-feature-store-7am-et | Refresh features AFTER Phase 4 |
| 8:00 AM | overnight-predictions | FIRST mode (85%+ quality) |
| 9-12 PM | predictions-Xam | RETRY mode (85%+ quality) |
| 1:00 PM | predictions-final-retry | 80%+ quality |
| 4:00 PM | predictions-last-call | Force all remaining |

This schedule should prevent the Feb 2 issue going forward.

---

## Prevention Strategies

### Already Implemented (Session 95)

1. **Quality Gate System** - Only predict when feature quality >= 85%
2. **Multiple Feature Store Refreshes** - 7 AM, 10 AM, 1 PM ET
3. **LAST_CALL Mode** - Force predictions at 4 PM with `forced_prediction` flag
4. **Quality Tracking** - `low_quality_flag` and `feature_quality_score` in predictions

### Recommended Additional Improvements

#### P0: Critical - Implement Now

1. **Feature Quality Dashboard Alert**
   - Alert when avg feature quality < 80% for upcoming games
   - Trigger: After each ML feature store run
   - Action: Slack notification to #nba-alerts

2. **Phase 4 Completion Gate**
   - Don't run ML feature store until Phase 4 confirms completion
   - Add dependency check in ml-feature-store scheduler
   - Query: `SELECT COUNT(*) FROM nba_precompute.player_composite_factors WHERE game_date = CURRENT_DATE()`

3. **Pre-Prediction Quality Check**
   - Before making any prediction, verify feature quality
   - If quality < 85% and mode != LAST_CALL, skip and log
   - Already partially implemented in quality_gate.py

#### P1: Important - This Week

4. **Historical Quality Tracking Table**
   ```sql
   CREATE TABLE nba_predictions.feature_quality_history (
     game_date DATE,
     check_time TIMESTAMP,
     total_players INT,
     high_quality_pct FLOAT,
     avg_quality FLOAT,
     phase4_coverage FLOAT,
     prediction_mode STRING
   )
   ```

5. **Quality-Aware Recommendation System**
   - Don't recommend OVER/UNDER for low-quality predictions
   - Set recommendation = 'LOW_QUALITY_SKIP' instead
   - Add to prediction output for transparency

6. **Automated Backfill Trigger**
   - If Phase 4 data missing for >20% of players at 10 AM, trigger backfill
   - Monitor completion and retry ML feature store

#### P2: Nice to Have - Future

7. **ML Model Quality Calibration**
   - Train separate model on low-quality features
   - Use appropriate model based on feature quality tier

8. **Real-time Feature Quality Monitoring**
   - Prometheus metrics for feature quality
   - Grafana dashboard with quality trends

---

## Verification Queries

### Check Feature Quality Distribution
```sql
SELECT
  game_date,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  COUNTIF(feature_quality_score >= 85) as high,
  COUNTIF(feature_quality_score >= 80 AND feature_quality_score < 85) as medium,
  COUNTIF(feature_quality_score < 80) as low
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date
ORDER BY game_date DESC;
```

### Check Timing Sequence
```sql
SELECT
  'Phase 4' as source,
  game_date,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M ET', MAX(created_at), 'America/New_York') as created
FROM nba_precompute.player_composite_factors
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY game_date
UNION ALL
SELECT
  'ML Features' as source,
  game_date,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M ET', MAX(created_at), 'America/New_York') as created
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY game_date
ORDER BY game_date DESC, source;
```

### Check Quality Gate Logs
```bash
gcloud logging read 'resource.labels.service_name="prediction-coordinator" AND textPayload=~"QUALITY_GATE"' --limit=20
```

### Verify Hit Rate by Quality Tier
```sql
SELECT
  CASE
    WHEN f.feature_quality_score >= 85 THEN 'High (85+)'
    WHEN f.feature_quality_score >= 80 THEN 'Medium (80-85)'
    ELSE 'Low (<80)'
  END as quality_tier,
  COUNT(*) as predictions,
  COUNTIF(a.prediction_correct) as wins,
  ROUND(100.0 * COUNTIF(a.prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy a
JOIN nba_predictions.ml_feature_store_v2 f
  ON a.player_lookup = f.player_lookup AND a.game_date = f.game_date
WHERE a.system_id = 'catboost_v9'
  AND a.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND a.recommendation IN ('OVER', 'UNDER')
GROUP BY quality_tier
ORDER BY quality_tier;
```

---

## Commits This Session

```
eec1cf65 fix(deploy): Pass CATBOOST_V8_MODEL_PATH to Docker test
```

---

## Deployments This Session

| Service | Status | Commit |
|---------|--------|--------|
| prediction-worker | DEPLOYED | b18aa475 |

---

## Reminders Updated

| ID | Status | Description |
|----|--------|-------------|
| rem_009 | COMPLETED | Feb 2 games graded (49.1% hit rate) |
| rem_008 | PENDING | Verify model attribution after next prediction run |

---

## Next Session Checklist

### Verify Quality Gate Working
- [ ] Check tomorrow's (Feb 4) predictions have `prediction_attempt` populated
- [ ] Verify `model_file_name` is NOT NULL for new predictions
- [ ] Check quality gate logs show correct thresholds being applied

### Implement P0 Prevention
- [ ] Add feature quality alert after ML feature store runs
- [ ] Add Phase 4 completion check before ML feature store
- [ ] Test quality gate behavior at LAST_CALL mode

### Monitor Hit Rates
- [ ] Track Feb 4 predictions by quality tier
- [ ] Compare high-quality vs low-quality hit rates
- [ ] Verify edge filtering still works (5+ edge should be ~60%+)

---

## Key Files

| File | Purpose |
|------|---------|
| `predictions/coordinator/quality_gate.py` | Quality gate logic |
| `predictions/coordinator/quality_alerts.py` | Alerting system |
| `data_processors/precompute/ml_feature_store/quality_scorer.py` | Quality score calculation |
| `bin/deploy-service.sh` | Deploy script (fixed Docker test) |

---

## Summary

**Root cause:** ML feature store ran before Phase 4 completed, causing predictions to use default feature values (40 points) instead of real data (100 points).

**Impact:** Low-quality features caused systematic underprediction, creating false high-edge UNDER signals that had ~40% hit rate.

**Solution:** Session 95's quality gate system should prevent this by waiting for 85%+ quality features before predicting. Verify it's working tomorrow.

**Prevention:** Add Phase 4 completion gate, feature quality alerts, and historical quality tracking.

---

## Session 96 Complete
