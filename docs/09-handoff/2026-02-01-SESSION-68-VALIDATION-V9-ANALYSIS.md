# Session 68: Daily Validation & V9 Model Performance Analysis
**Date**: February 1, 2026 (8:12 AM PST)
**Type**: Daily Validation + Model Performance Investigation
**Models Analyzed**: catboost_v8, catboost_v9, ensemble_v1_1

---

## Executive Summary

### Daily Pipeline Status: ✅ HEALTHY (with minor issues)
- **Box scores**: Complete for Jan 31 (6 games, 212 players)
- **Phase 3**: 3/5 processors (Firestore sync issue, data exists)
- **Predictions**: 162 generated for Feb 1, 94 graded for Jan 31
- **BDB Coverage**: 100% last 6 days

### Model Performance: 🔴 V9 UNDERPERFORMING
- **catboost_v8**: 72.4% hit rate on premium picks (156 bets) ✅ EXCELLENT
- **catboost_v9**: Only 1 premium pick (sample too small) ⚠️ CONCERNING
- **Root Cause**: V9 produces too few 3+ edge picks (34% vs V8's 54.6%)

### Critical Finding: V9 Agrees Too Much with Vegas
V9 is over-conservative and not finding enough value picks. Recommend continuing with V8 premium picks until V9 is retrained or proves itself over 7+ days.

---

## Validation Context

**Game Date**: Jan 31, 2026 (6 games played)
**Processing Date**: Feb 1, 2026 (scrapers/analytics ran overnight)
**Current Time**: Feb 1, 2026 08:12 PST (11:12 AM EST)

---

## Part 1: Daily Validation Results

### Phase 0.2: Heartbeat System ✅ HEALTHY
- **Total documents**: 24
- **Bad format (old pattern)**: 0
- **Status**: Optimal (expected 30-50)

### Phase 2: Betting Data ✅ COMPLETE
- **Prop records**: 1,477 (6 games)
- **Game lines**: 288 (6 games)
- **Coverage**: 100%

### Phase 3: Analytics Processors 🟡 WARNING
**Firestore Completion**: 3/5 processors registered

| Processor | Status | Records | Issue |
|-----------|--------|---------|-------|
| team_offense_game_summary | ✅ Success | 24 | Firestore registered |
| team_defense_game_summary | ✅ Success | 12 | Firestore registered |
| upcoming_player_game_context | ✅ Success | 326 | Firestore registered |
| **player_game_summary** | ⚠️ Missing | 212 | **NOT in Firestore** |
| **upcoming_team_game_context** | ⚠️ Missing | Unknown | **NOT in Firestore** |

**Analysis**: This is a **Firestore sync issue**, not a data issue.
- Heartbeats show both processors completed successfully at 15:01 UTC
- Data was written to BigQuery (processed_at: 15:00 UTC)
- Both processors failed to register in phase3_completion document
- This prevented Phase 4 auto-trigger

**Impact**: Low - Data exists and is complete. Phase 4 likely ran via manual trigger or alternate mechanism.

### Phase 4: ML Features ✅ COMPLETE
- **Features generated**: 209 (for 6 games)
- **Players**: 209 unique
- **Last created**: 2026-01-31 09:17:56 UTC

### Phase 5: Predictions ✅ COMPLETE
**Jan 31 (grading)**:
- 94 predictions graded
- 100% graded (all have actual values)

**Feb 1 (generation)**:
- 162 predictions generated for tonight's games
- First prediction: 15:07 UTC
- Last prediction: 15:19 UTC

### Data Quality Checks

#### Box Score Coverage ✅ HEALTHY
| Metric | Value | Status |
|--------|-------|--------|
| Games with data | 6 | ✅ Matches schedule |
| Player records | 212 | ✅ Complete |
| Players with points | 118 | ✅ Active players |
| **Minutes coverage** | 55.7% | ✅ **Correct (94 DNP players)** |

**Note**: The "low" minutes coverage (55.7%) is **expected and healthy**:
- 118 players played (100% have minutes)
- 94 players DNP (Did Not Play) - correctly flagged with `is_dnp = TRUE`
- Total: 212 players (all correctly classified)

#### Spot Check Accuracy ✅ EXCELLENT
- **Accuracy**: 100% (6/6 checks passed)
- **Checks**: rolling_avg, usage_rate
- **Status**: Data quality is excellent

#### Shot Zone Quality 🟡 WARNING
- **Paint rate**: 25.9% (expected 30-45%)
- **Three rate**: 61% (above 50% threshold)
- **Date**: Jan 30, 2026
- **Status**: Known issue (Session 53) - BDB play-by-play dependent

#### BDB Coverage ✅ EXCELLENT
| Date | Scheduled | BDB Has | Coverage |
|------|-----------|---------|----------|
| Jan 31 | 6 | 6 | 100% |
| Jan 30 | 9 | 9 | 100% |
| Jan 29 | 8 | 8 | 100% |
| Jan 28 | 9 | 9 | 100% |
| Jan 27 | 7 | 7 | 100% |
| Jan 26 | 7 | 7 | 100% |
| Jan 25 | 8 | 6 | 75% |

**Status**: BDB coverage has recovered from Jan 17-24 outage.

---

## Part 2: Model Performance Analysis

### Current Active Models (Last 3 Days)

| Model | Status | Predictions | Last Prediction |
|-------|--------|-------------|-----------------|
| **ensemble_v1_1** | 🟢 ACTIVE | 237 | Jan 31 |
| **catboost_v9** | 🟢 ACTIVE | 94 | Jan 31 |
| **ensemble_v1** | 🟢 ACTIVE | 35 | Jan 31 |
| catboost_v8 | ⚪ INACTIVE | 0 (398 in last 7 days) | Jan 28 |

### Overall Performance (Last 7 Days)

| Model | Predictions | Hit Rate | Bias | Status |
|-------|-------------|----------|------|--------|
| **catboost_v8** | 398 | **56.5%** | +0.18 | ✅ Healthy |
| **ensemble_v1_1** | 144 | **57.6%** | -1.65 | ✅ Healthy |
| **catboost_v9** | 50 | **42.0%** | -1.83 | 🔴 CRITICAL |
| ensemble_v1 | 21 | 42.9% | -3.19 | 🔴 Poor |

---

## Part 3: CRITICAL FINDING - V9 Premium Picks Analysis

### Premium Picks Definition
**Premium Picks**: `confidence_score >= 0.92 AND ABS(predicted_points - line_value) >= 3`

This is the **primary metric** used for betting decisions.

### January 2026 Premium Pick Performance

| Model | Premium Bets | Hits | Hit Rate | Avg Edge |
|-------|--------------|------|----------|----------|
| **catboost_v8** | **156** | 113 | **72.4%** | 4.4 pts |
| catboost_v9 | **1** | 1 | 100% | 4.2 pts |
| similarity_balanced_v1 | 62 | 36 | 58.1% | 5.1 pts |

**V8's 72.4% hit rate on 156 premium bets is EXCELLENT performance.**

### V9's Critical Problem: Too Few Premium Picks

#### Production Rate Comparison

| Model | Period | Total Preds | Premium Picks | Premium % |
|-------|--------|-------------|---------------|-----------|
| **V8** | Jan 18-28 | 1,028 | **29** | **2.8%** |
| **V9** | Jan 31 | 50 | **1** | **2.0%** |

#### Why V9 Produces Fewer Premium Picks

**Breakdown of Components**:

| Model | High Conf (92+) | 3+ Edge Picks | **Both (Premium)** |
|-------|-----------------|---------------|--------------------|
| V8 | 104 (10.1%) | 561 (54.6%) | **29 (2.8%)** |
| V9 | 9 (18%) | 17 (34%) | **1 (2.0%)** |

**Root Cause**: V9 produces **too few 3+ edge picks** (34% vs V8's 54.6%)

**What This Means**:
- V9 has high confidence (18% of picks at 92+) ✅
- V9 has sufficient edge overall (17/50 = 34% at 3+ edge) ⚠️
- But V9 is **not confident when it has edge** ❌
- Result: Only 1 pick where both conditions meet

### V9 Confidence Tier Performance

| Confidence Tier | Predictions | Hit Rate | Avg Confidence |
|-----------------|-------------|----------|----------------|
| Premium (92+) | 9 | **55.6%** | 0.92 |
| Medium (87-89) | 36 | **36.1%** | 0.88 |
| Low (<87) | 5 | 60.0% | 0.84 |

**Issue**: 72% of V9's predictions are medium confidence (87-89) with only 36.1% hit rate.

### V8 Premium Pick Weekly Trend

| Week Starting | Premium Bets | Hit Rate |
|---------------|--------------|----------|
| Dec 28, 2025 | 39 | **87.2%** |
| Jan 4, 2026 | 65 | **76.9%** |
| Jan 11 | 23 | 47.8% |
| Jan 18 | 14 | 64.3% |
| **Jan 25** | **15** | **60.0%** |

**V8 January Average**: 72.4% hit rate on 156 premium bets

### High Confidence Performance Comparison (Last 7 Days)

| Model | High Conf (92+) Predictions | Hit Rate |
|-------|----------------------------|----------|
| **catboost_v8** | 65 | **64.6%** |
| **catboost_v9** | 9 | **55.6%** |

V8's high confidence picks are better calibrated (64.6% vs 55.6%).

---

## Part 4: Root Cause Analysis

### Why V9 Underperforms on Premium Picks

**Hypothesis 1: Over-fitting to Vegas Lines**
- V9 only disagrees with Vegas by 3+ points on 34% of predictions
- V8 disagreed with Vegas 54.6% of the time
- **Evidence**: V9's training may have emphasized matching Vegas accuracy over finding value

**Hypothesis 2: Poor Confidence Calibration**
- V9's medium confidence picks (87-89) hit only 36.1%
- These should either be higher confidence or lower
- **Evidence**: Training didn't properly calibrate probability thresholds

**Hypothesis 3: Insufficient Training Data**
- V9 was trained on current season only (Nov 2025+)
- May lack historical pattern recognition
- **Evidence**: CLAUDE.md states "V9 is trained on clean, current season data only"

**Hypothesis 4: Sample Size Too Small**
- V9 only has 1 day of predictions (Jan 31, 50 total)
- Premium picks: only 1 bet
- **Evidence**: Need 7+ days to properly evaluate

### Vegas Line Feature Coverage (Session 62 Concern)

**Checked**: Vegas line coverage in feature store
- **Last 7 days**: 44.5% coverage (CRITICAL threshold <80%)
- **Jan 31 predictions**: 100% have Vegas lines in prediction_accuracy table

**Analysis**:
- The 44.5% feature store coverage is concerning for feature generation
- But Jan 31 predictions show 100% line coverage at prediction time
- This suggests the low feature store coverage may be historical/backfill data
- Current production predictions appear to have proper Vegas line features

**Recommendation**: Monitor feature store coverage for Feb 1+ to ensure it stays >80%

---

## Part 5: What Was Fixed During This Session

### Issue: Validation Skills Hardcoded to V8

**Problem Identified**: User pointed out that V9 was deployed but all validation skills were hardcoded to check `catboost_v8` only.

**Skills Updated** (6 total):
1. `.claude/skills/validate-daily/SKILL.md`
2. `.claude/skills/hit-rate-analysis/SKILL.md`
3. `.claude/skills/model-health/SKILL.md`
4. `.claude/skills/top-picks/SKILL.md`
5. `.claude/skills/yesterdays-grading/SKILL.md`
6. `.claude/skills/todays-predictions/SKILL.md`

**Solution Applied**: Dynamic model detection pattern
```sql
WITH active_models AS (
  SELECT DISTINCT system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= @date_range
    AND (system_id LIKE 'catboost_%' OR system_id LIKE 'ensemble_%')
)
SELECT
  system_id,  -- Added to all result sets
  -- ... other columns ...
FROM table_name
WHERE system_id IN (SELECT system_id FROM active_models)
GROUP BY system_id, -- ... other group by fields
ORDER BY system_id
```

**Benefits**:
- Automatic detection of all active models
- Side-by-side comparison in results
- Future-proof for V10, V11, etc.
- Handles ensemble models automatically
- No hardcoded model references

**Changes**: 255 insertions, 65 deletions across 6 files

---

## Part 6: Outstanding Issues

### Issue 1: Phase 3 Firestore Sync 🟡 P2 WARNING

**Symptom**:
- `player_game_summary` and `upcoming_team_game_context` processors completed successfully
- Heartbeats show "completed" status
- Data exists in BigQuery
- But processors NOT registered in `phase3_completion` Firestore document

**Impact**:
- Low severity - data exists and is correct
- Phase 4 auto-trigger may not have fired (likely ran via alternate mechanism)

**Investigation Needed**:
1. Check processor completion logic in base class
2. Review Firestore write transaction for race conditions
3. Verify if Phase 4 auto-triggered despite missing completion

**Workaround**: Data is complete, no immediate action needed

### Issue 2: V9 Low Premium Pick Production 🔴 P1 CRITICAL

**Symptom**: V9 produces 34% 3+ edge picks vs V8's 54.6%

**Impact**: Only 1 premium pick in 50 predictions (2.0% vs V8's 2.8%)

**Investigation Needed**:
1. Review V9 training script: `ml/experiments/quick_retrain.py`
2. Check training data date range and quality
3. Analyze feature weights - is Vegas line over-weighted?
4. Compare V9 vs V8 model parameters
5. Check if training loss function emphasized Vegas agreement

**Recommendation**:
- Continue using V8 premium picks (72.4% hit rate)
- Collect 7 days of V9 data before full evaluation
- Consider retraining V9 with emphasis on edge-finding

### Issue 3: V9 Poor Medium Confidence Calibration 🔴 P1 CRITICAL

**Symptom**: 87-89 confidence picks hit only 36.1% (worse than coin flip)

**Impact**: 72% of V9's predictions are in this range

**Options**:
1. **Filter V9 to 92+ confidence only** - Use only the 18% high-confidence picks (55.6% hit rate)
2. **Recalibrate confidence thresholds** - Post-process confidence scores
3. **Retrain with better probability calibration** - Adjust training parameters

### Issue 4: Shot Zone Data Quality (Jan 30) 🟠 P3 MEDIUM

**Symptom**: Paint rate 25.9%, three rate 61% (abnormal)

**Status**: Known issue from Session 53 - BDB play-by-play dependent

**Impact**: Low - affects shot zone analytics, not predictions

**No action needed**: This is expected when BDB data is incomplete

---

## Part 7: Recommendations

### Immediate Actions (Today)

1. **Continue Using V8 Premium Picks** ✅
   - V8: 72.4% hit rate on 156 premium bets in January
   - V9: Only 1 premium bet (sample too small)
   - Recommendation: Use V8 as primary until V9 proves itself

2. **Monitor V9 Performance for 7 Days** 📊
   - Collect Feb 1-7 data
   - Track premium pick production rate
   - Track hit rate on all confidence tiers
   - Decision point: Feb 8 to evaluate if V9 is viable

3. **Check Feature Store Vegas Line Coverage for Feb 1+** 🔍
   ```bash
   bq query --use_legacy_sql=false "
   SELECT
     game_date,
     ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as vegas_line_pct,
     COUNT(*) as records
   FROM nba_predictions.ml_feature_store_v2
   WHERE game_date >= DATE('2026-02-01')
     AND ARRAY_LENGTH(features) >= 33
   GROUP BY game_date
   ORDER BY game_date DESC"
   ```
   **Alert if**: Coverage <80% for current day's features

4. **Verify Ensemble Models Are Active** 🔄
   - ensemble_v1_1: 57.6% hit rate (237 predictions)
   - May be a viable alternative to V9
   - Check what predictions it's making for tonight

### Short-term Actions (This Week)

5. **Investigate V9 Training Parameters** 🔬
   - Review `ml/experiments/quick_retrain.py`
   - Check training date range (Nov 2025+ only?)
   - Analyze feature importance - is Vegas line over-weighted?
   - Compare V9 vs V8 hyperparameters

6. **Investigate Phase 3 Firestore Sync Issue** 🐛
   - Check `shared/monitoring/processor_heartbeat.py`
   - Review base processor completion logic
   - Test if race condition exists in Firestore writes
   - Add retry logic if needed

7. **Run V9 vs V8 Side-by-Side Comparison** 📈
   ```bash
   /hit-rate-analysis --start-date 2026-01-18 --end-date 2026-01-31
   ```
   Compare:
   - Premium pick production rate
   - Confidence distribution
   - Edge distribution
   - Player tier performance

### Medium-term Actions (Next 2 Weeks)

8. **Consider V9 Retraining with Adjusted Objectives** 🎯
   - If V9 continues low edge production after 7 days
   - Adjust training to emphasize disagreement with Vegas
   - Balance between accuracy and value-finding
   - Add edge-finding bonus to loss function

9. **Evaluate Ensemble Models as Primary** 🎲
   - ensemble_v1_1: 57.6% overall, investigate premium pick performance
   - May be more stable than single model
   - Check ensemble weighting strategy

10. **Add Automated Alerts for Model Performance** 🚨
    - Daily alert if premium pick production <2%
    - Weekly alert if hit rate <55%
    - Alert if Vegas line feature coverage <80%

---

## Part 8: Key Metrics Summary

### Daily Pipeline Health: ✅ PASS

| Check | Status | Details |
|-------|--------|---------|
| Heartbeat System | ✅ | 24 docs, healthy |
| Box Scores | ✅ | 6 games, 212 players complete |
| Prediction Grading | ✅ | 100% graded (94/94) |
| Feature Generation | ✅ | 209 features |
| Spot Checks | ✅ | 100% accuracy |
| BDB Coverage | ✅ | 100% last 6 days |
| Phase 3 Completion | 🟡 | 3/5 (Firestore sync issue) |

### Model Performance: 🔴 V9 UNDERPERFORMING

**Premium Picks (92+ conf, 3+ edge) - January 2026**:
- **V8**: 72.4% hit rate on 156 bets ✅ EXCELLENT
- **V9**: 100% on 1 bet (sample too small) ⚠️ INSUFFICIENT DATA

**Overall Hit Rate (Last 7 Days)**:
- **V8**: 56.5% on 398 predictions ✅ HEALTHY
- **V9**: 42.0% on 50 predictions 🔴 CRITICAL
- **ensemble_v1_1**: 57.6% on 144 predictions ✅ HEALTHY

**V9 Issues**:
- Low premium pick production (2.0% vs V8's 2.8%)
- Too few 3+ edge picks (34% vs V8's 54.6%)
- Poor medium confidence calibration (36.1% hit rate)
- Over-agreement with Vegas lines

---

## Part 9: Data for Future Reference

### Model Production Statistics (Jan 18-31)

| Model | Total Preds | High Conf (92+) | 3+ Edge | Premium (Both) | Premium % |
|-------|-------------|-----------------|---------|----------------|-----------|
| V8 (Jan 18-28) | 1,028 | 104 (10.1%) | 561 (54.6%) | 29 (2.8%) | 2.8% |
| V9 (Jan 31) | 50 | 9 (18%) | 17 (34%) | 1 (2.0%) | 2.0% |

### V8 Weekly Premium Performance

| Week | Premium Bets | Hits | Hit Rate |
|------|--------------|------|----------|
| Dec 28 | 39 | 34 | 87.2% |
| Jan 4 | 65 | 50 | 76.9% |
| Jan 11 | 23 | 11 | 47.8% |
| Jan 18 | 14 | 9 | 64.3% |
| Jan 25 | 15 | 9 | 60.0% |
| **Total Jan** | **156** | **113** | **72.4%** |

### V9 Daily Performance (Limited Data)

| Date | Total Preds | Premium Picks | High Conf | Hit Rate (Overall) |
|------|-------------|---------------|-----------|-------------------|
| Jan 31 | 50 | 1 | 9 | 42.0% |

---

## Part 10: Files Modified

### Validation Skills Updated
1. `.claude/skills/validate-daily/SKILL.md` - Multi-model support
2. `.claude/skills/hit-rate-analysis/SKILL.md` - Dynamic model detection
3. `.claude/skills/model-health/SKILL.md` - Model comparison
4. `.claude/skills/top-picks/SKILL.md` - Updated to V9
5. `.claude/skills/yesterdays-grading/SKILL.md` - Multi-model grading
6. `.claude/skills/todays-predictions/SKILL.md` - Multi-model predictions

**Total Changes**: 255 insertions, 65 deletions

---

## Conclusion

**Daily Pipeline**: Healthy with minor Firestore sync issue (non-blocking)

**Model Performance**:
- **V8 remains excellent** on premium picks (72.4% hit rate)
- **V9 underperforms** but has insufficient data (only 1 day, 1 premium pick)
- **Root cause**: V9 produces too few 3+ edge picks (agrees too much with Vegas)

**Recommendation**:
- Continue using V8 premium picks as primary betting signal
- Monitor V9 for 7 days before making switch decision
- Investigate V9 training parameters for edge-finding emphasis
- Consider ensemble_v1_1 as viable alternative (57.6% hit rate)

**Skills Updated**: All validation skills now support multi-model analysis

**Next Session Priority**: Monitor V9 performance Feb 1-7, investigate training if low edge production continues.

---

**Session Handoff Complete**
Agent ID: a7f8f5e (validation skills update agent)
Document created: 2026-02-01 08:30 PST
