# Root Cause Analysis: V8 Model Collapse (January 7-9, 2026)

**Date:** 2026-01-30
**Status:** Root causes identified
**Severity:** P1 CRITICAL

---

## Executive Summary

The CatBoost V8 model's performance collapsed starting January 7-9, 2026 due to a **perfect storm of 6 concurrent issues**:

1. **V8 deployment with feature version mismatch** (Jan 8-9)
2. **Missing betting data** for Jan 6 and Jan 8
3. **BigDataBall lineup data gap** on Jan 9
4. **External API failures** (Ball Don't Lie 502 errors)
5. **Confidence scoring logic change** (max dropped from 0.95 to 0.92)
6. **Prediction worker OOM crashes** (Jan 7)

The combined effect was a drop from **67.9% hit rate to 48.3%** and decile 10 picks collapsing from **124/day to 7/day**.

---

## Timeline of Failure

| Date | Event | Impact |
|------|-------|--------|
| **Jan 6** | Missing betting data | 0 lines available, predictions affected |
| **Jan 7** | Prediction worker OOM crashes | Reduced prediction volume |
| **Jan 7** | 124 decile 10 picks, 58.9% hit rate | Last "good" day |
| **Jan 8** | V8 deployed, feature version = v2_33features | Model expects 33 features |
| **Jan 8** | Missing betting data | 0 lines, 0 graded predictions |
| **Jan 8** | Ball Don't Lie API 502 errors | Scraper failures |
| **Jan 9** | Feature version switched to v1_baseline_25 | **MISMATCH: Model expects 33, gets 25** |
| **Jan 9** | Feature version switched back to v2_33features | Inconsistent state |
| **Jan 9** | BigDataBall lineup data missing | No players found for feature generation |
| **Jan 9** | Only 7 decile 10 picks, 57% hit rate | Volume collapsed 94% |
| **Jan 9** | minutes_avg_last_10 bug discovered | Historical features incorrect |
| **Jan 10+** | Sustained low volume, poor accuracy | 16-50% hit rates |

---

## Root Cause #1: V8 Deployment with Feature Mismatch

### What Happened
CatBoost V8 was deployed on Jan 8-9 expecting **33 features**, but the feature store was producing **25 features** during a transition period.

### Evidence
```
Commit e2a5b544 (Jan 8): "Replace XGBoostV1 with CatBoost V8 in production"
Commit a3e6e940 (Jan 9): "V8 feature version mismatch" - Changed default BACK to v1_baseline_25
Commit b30c8e2b (Jan 9): "Correct feature version" - Changed BACK to v2_33features
```

### Impact
Predictions made during the mismatch window received **wrong features**:
- Model trained on 33 features
- Received 25 features (8 missing)
- Missing features: vegas_points_line, vegas_opening_line, vegas_line_move, has_vegas_line, avg_points_vs_opponent, games_vs_opponent, minutes_avg_last_10, ppm_avg_last_10

---

## Root Cause #2: Missing Betting Data

### What Happened
BettingPros data was completely missing for Jan 6 and Jan 8.

### Evidence
| Date | Betting Players | Lines |
|------|-----------------|-------|
| Jan 5 | 128 | 31,167 |
| **Jan 6** | **0** | **0** |
| Jan 7 | 211 | 50,169 |
| **Jan 8** | **0** | **0** |
| Jan 9 | 162 | 43,704 |

### Impact
- Jan 6: 303 predictions graded without proper lines
- Jan 8: **0 predictions graded** (all had `current_points_line = NULL`)
- Confidence calibration affected by missing market data

---

## Root Cause #3: BigDataBall Lineup Data Gap

### What Happened
BigDataBall lineup data was missing for January 9, 2026.

### Evidence
```
Feature store processor errors:
- "ValueError: No players found with games on 2026-01-09"
- "No prediction requests created for 2026-01-09"
```

### Impact
- Feature generation failed for Jan 9 games
- Prediction coordinator couldn't find players
- Forced fallback to incomplete data

---

## Root Cause #4: External API Failures

### What Happened
Ball Don't Lie API returned 502 errors on Jan 8.

### Evidence
```
HTTPSConnectionPool(host='api.balldontlie.io', port=443):
Max retries exceeded with url: /v1/box_scores/live
(Caused by ResponseError('too many 502 error responses'))
```

### Impact
- Live box score scraping failed
- Player stats potentially incomplete
- Rolling averages may have stale data

---

## Root Cause #5: Confidence Scoring Change

### What Happened
The confidence score distribution changed dramatically starting Jan 9.

### Evidence
| Metric | Jan 7 | Jan 9 |
|--------|-------|-------|
| Max Confidence | **0.95** | **0.92** |
| Avg Confidence | 0.901 | 0.875 |
| Decile 10 Count | 124 | 7 |

**The 0.95 and 0.90 confidence scores completely disappeared.**

### Root Cause in Code
CatBoost V8 confidence calculation (`catboost_v8.py` lines 681-715):
```python
confidence = 75.0  # Base
# +10 if feature_quality_score >= 90
# +10 if points_std_last_10 < 4
# Maximum = 95%
```

After Jan 9:
- Fewer players had `feature_quality_score >= 90` (due to missing features)
- `points_std_last_10` values were affected by the bug fix
- Maximum achievable confidence dropped to 92%

### Impact
- 94% fewer decile 10 picks
- Predictions shifted from decile 10 to decile 9
- Decile 9 volume increased from 71 (Jan 7) to 102 (Jan 9)

---

## Root Cause #6: Prediction Worker OOM Crashes

### What Happened
Prediction worker experienced Out of Memory crashes on Jan 7.

### Evidence
```
Worker (pid:7) was sent SIGKILL! Perhaps out of memory? (16:40:29)
Worker (pid:2) was sent SIGKILL! Perhaps out of memory? (16:35:24)
```

### Impact
- Reduced prediction volume on Jan 7
- Potential data corruption or incomplete batches
- Set stage for subsequent failures

---

## Combined Effect Analysis

### Why OVER Picks Collapsed

| Period | OVER Margin | Interpretation |
|--------|-------------|----------------|
| Jan 5-7 | +0.91 to +2.12 | Players beating lines |
| Jan 9-12 | **-0.05 to -2.07** | Players UNDER lines |

The model continued predicting players would beat lines, but actual performance inverted.

**Cause:** The 8 missing features included:
- `vegas_points_line` - Market consensus
- `vegas_line_move` - Line movement signal
- `avg_points_vs_opponent` - Historical matchup data

Without these, the model couldn't detect when Vegas had already priced in factors.

### Why Low-Line Players Hit Hardest

| Line Bucket | Jan 7 Hit Rate | Jan 9 Hit Rate |
|-------------|----------------|----------------|
| <12 pts | 43.8% | **28.3%** |
| 12-18 pts | 48.2% | 35.4% |
| 18-25 pts | 58.8% | 39.0% |
| 25+ pts | 66.7% | 44.4% |

Role players with <12 pt lines had the worst degradation because:
- Higher variance in minutes/playing time
- More affected by missing `minutes_avg_last_10` feature
- Less historical data for opponent matchups

---

## Feature-Level Impact Analysis

### Features That Were Missing or Incorrect

| Feature | Status | Impact |
|---------|--------|--------|
| vegas_points_line | Missing (not in 25-feature set) | No market consensus signal |
| vegas_line_move | Missing | No line movement detection |
| minutes_avg_last_10 | Buggy (global ROW_NUMBER) | Incorrect playing time prediction |
| injury_risk | Zero until Jan 11 | No injury context |
| avg_points_vs_opponent | Missing | No matchup history |

### minutes_avg_last_10 Bug Details

**Bug:** ROW_NUMBER was computed globally instead of per-player-date
```sql
-- BUGGY (before fix)
ROW_NUMBER() OVER (ORDER BY game_date DESC)

-- CORRECT (after fix)
ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC)
```

**Impact:**
- Feature values were completely wrong for all players
- MAE before fix: 8.14
- MAE after fix: 4.05

---

## Recovery Timeline

| Date | Fix Applied | Result |
|------|-------------|--------|
| Jan 9 | minutes_avg_last_10 bug fixed | Feature accuracy improved |
| Jan 9 | Feature version corrected to v2_33features | Model got correct features |
| Jan 11 | injury_risk feature started working | Additional signal available |
| Jan 15+ | Performance remained poor | **Damage already done** |

The fixes were applied, but:
1. Historical predictions already made with bad data
2. Confidence calibration remained broken
3. Model learned patterns may have drifted

---

## Summary: The Perfect Storm

```
Day 1 (Jan 6-7):
├── Missing betting data (Jan 6)
├── Prediction worker OOM crashes
└── Last good day: 124 decile 10 picks, 58.9% hit rate

Day 2 (Jan 8):
├── V8 deployed expecting 33 features
├── Missing betting data
├── Ball Don't Lie API failures
└── 0 predictions graded

Day 3 (Jan 9):
├── Feature version mismatch (switched 3 times!)
├── BigDataBall lineup data missing
├── minutes_avg_last_10 bug discovered
├── Confidence scores capped at 0.92
└── Only 7 decile 10 picks (94% drop)

Day 4+ (Jan 10-28):
├── Sustained poor performance
├── OVER picks inverted (now losing)
├── Model confidence miscalibrated
└── Hit rate dropped to 30-40%
```

---

## Recommended Fixes

### Immediate (P1)

1. **Recalibrate confidence scoring**
   - Current max = 92%, needs to reach 95%+ for true high-confidence picks
   - Review `feature_quality_score` calculation

2. **Validate feature completeness**
   - Add fail-fast check: if features < 33, don't predict
   - Log feature counts with every prediction

3. **Backfill missing betting data**
   - Jan 6 and Jan 8 data gaps need filling or marking

### Short-term (P2)

4. **Retrain model with correct features**
   - Training data may have used buggy `minutes_avg_last_10`
   - Need clean feature data from Nov 2025+

5. **Add feature version validation**
   - Prediction worker should verify feature version matches model expectation
   - Reject predictions if mismatch detected

6. **Improve external API resilience**
   - Add fallback data sources
   - Better retry logic with exponential backoff

### Medium-term (P3)

7. **Implement shadow mode testing**
   - Don't deploy new models directly to production
   - Run challenger alongside champion for 1 week

8. **Add data quality gates**
   - Block predictions if betting data missing
   - Block predictions if lineup data incomplete

---

## Files to Modify

| File | Change Needed |
|------|---------------|
| `predictions/worker/prediction_systems/catboost_v8.py` | Recalibrate confidence scoring |
| `predictions/worker/data_loaders.py` | Add feature version validation |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Add feature count logging |
| `shared/config/orchestration_config.py` | Add data quality gate settings |

---

## Lessons Learned

1. **Never deploy model + feature changes separately** - Must be atomic
2. **Feature version mismatches are silent killers** - Add explicit validation
3. **External API failures cascade** - Need better resilience
4. **Confidence calibration is fragile** - Small feature changes have big impact
5. **Multiple small issues compound** - 6 issues × minor impact = major failure

---

*Root cause analysis complete. The January 7-9 collapse was a multi-factor failure requiring both immediate fixes and architectural improvements to prevent recurrence.*
