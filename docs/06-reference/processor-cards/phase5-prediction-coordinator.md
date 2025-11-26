# Phase 5 Prediction Coordinator - Quick Reference

**Last Updated**: 2025-11-25
**Verified**: ✅ Code verified against source

---

## Essential Facts

| Attribute | Value |
|-----------|-------|
| **Type** | Phase 5 - ML Predictions (Coordinator-Worker) |
| **Schedule** | Daily at 6:15 AM ET + real-time odds updates |
| **Duration** | 2-5 minutes (initial predictions), <1s (odds updates) |
| **Priority** | **High** - Final phase before publishing |
| **Status** | ✅ Deployed |

---

## Code & Tests

| Component | Location | Size |
|-----------|----------|------|
| **Coordinator** | `predictions/coordinator/coordinator.py` | 388 lines |
| **Worker** | `predictions/worker/worker.py` | 942 lines |
| **Prediction Systems** | `predictions/worker/prediction_systems/` | **2,474 lines total** |
| | - Moving Average Baseline | 349 lines ✅ |
| | - XGBoost V1 | 426 lines ⚠️ (mock model) |
| | - Zone Matchup V1 | 441 lines ✅ |
| | - Similarity Balanced V1 | 543 lines ✅ |
| | - Ensemble V1 | 486 lines ✅ |
| **Tests** | `tests/predictions/` | **11 test files** |

---

## Dependencies (v4.0 Tracking)

```
Phase 4 ML Features:
  └─ ml_feature_store_v2 (CRITICAL) - 25 features per player

Phase 4 Cache (Real-time):
  └─ player_daily_cache (CRITICAL) - Cached for fast lookups

Betting Lines:
  └─ odds_api_player_points_props (CRITICAL) - Prop lines to predict

Consumers (Phase 6):
  └─ Publishing service - Firestore + JSON API (not implemented)
```

---

## What It Does

1. **Primary Function**: Generates player points predictions using 5 ML models with confidence scoring
2. **Key Output**: Ensemble predictions with OVER/UNDER/PASS recommendations and confidence scores
3. **Value**: 55%+ accuracy target on over/under bets, confidence-based filtering eliminates low-quality picks

**Architecture**: Coordinator-worker pattern for scalability (1 coordinator → N workers)

---

## Prediction Systems (5 Models)

### 1. Moving Average Baseline
```python
# Simple average of recent games
prediction = weighted_avg(last_5_games, last_10_games, season_avg)
confidence = 70 - (std_dev * 5)  # Lower for volatile players
```
- **When it's best**: Consistent scorers (stars), stable rotations
- **Confidence range**: 50-85
- **Example**: LeBron averaging 25.2 → predicts 25.0 (confidence: 75)

### 2. XGBoost V1 (Primary ML Model)
```python
# 25-feature ML model with gradient boosting
prediction = xgboost_model.predict(features)
confidence = 60 + quality_boost + consistency_boost  # Max 90
```
- **When it's best**: High feature quality (95+), mid-season data
- **Confidence range**: 60-90 (with quality adjustments)
- **Status**: ⚠️ Using mock model (needs training on real data)
- **Example**: Uses fatigue, matchup, pace, shot zones → predicts 23.5 (confidence: 82)

### 3. Zone Matchup V1
```python
# Player shot zones vs opponent defensive zones
matchup_score = player_zones.compare(opponent_defense_zones)
prediction = base_avg + matchup_adjustment
```
- **When it's best**: Clear zone mismatches (guards vs poor perimeter defense)
- **Confidence range**: 40-75
- **Example**: Three-point shooter vs team allowing 38% from 3 → +2.5 adjustment

### 4. Similarity Balanced V1
```python
# Find 10 similar players in similar contexts
similar_players = find_similar(usage, pace, rest, opponent)
prediction = avg(similar_players.actual_points)
```
- **When it's best**: Rookies, role players, unusual contexts
- **Confidence range**: 35-70
- **Example**: Rookie with 5 games → finds similar rookies → predicts 12.0 (confidence: 55)

### 5. Ensemble V1 (Final Output)
```python
# Confidence-weighted combination of all 4 systems
ensemble_pred = Σ(pred_i × conf_i) / Σ(conf_i)
ensemble_conf = avg(conf_i) + agreement_bonus - disagreement_penalty
```
- **Thresholds**: Confidence ≥ 65, Edge ≥ 1.5 points
- **Confidence range**: 20-95 (clamped)
- **Recommendation**: OVER/UNDER/PASS based on ensemble + system agreement
- **Example**: 4 systems predict 24.2, 23.8, 24.0, 24.5 → ensemble 24.1 (confidence: 78)

---

## Output Schema Summary

**Table**: `nba_predictions.player_points_predictions`
**Total Fields**: ~40

| Category | Count | Examples |
|----------|-------|----------|
| Identifiers | 5 | player_lookup, game_id, prediction_date, prop_line_id |
| Ensemble Results | 4 | ensemble_prediction, ensemble_confidence, recommendation, edge |
| System Predictions | 8 | xgboost_pred, xgboost_conf, moving_avg_pred, moving_avg_conf, ... |
| System Agreement | 3 | prediction_variance, systems_count, systems_agreement_pct |
| Feature Quality | 2 | feature_quality_score, data_source |
| Prop Line | 3 | prop_line, line_source, line_timestamp |
| Metadata | 3 | prediction_timestamp, model_version, coordinator_run_id |

---

## Health Check Query

```sql
-- Run this to verify Phase 5 health
SELECT
  COUNT(*) as predictions_generated,
  COUNT(CASE WHEN recommendation != 'PASS' THEN 1 END) as actionable_picks,
  AVG(ensemble_confidence) as avg_confidence,
  AVG(feature_quality_score) as avg_feature_quality,
  COUNT(CASE WHEN systems_count = 4 THEN 1 END) as all_systems_count
FROM `nba_predictions.player_points_predictions`
WHERE prediction_date = CURRENT_DATE();

-- Expected Results:
-- predictions_generated: 100-450 (depends on games today)
-- actionable_picks: 30-150 (30-50% pass threshold)
-- avg_confidence: 70-80
-- avg_feature_quality: 85-95 (after week 3)
-- all_systems_count: 90%+ (most players have all 4 systems)
```

---

## Common Issues & Quick Fixes

### Issue 1: No Predictions Generated
**Symptom**: predictions table is empty for today
**Diagnosis**:
```sql
-- Check if features exist
SELECT COUNT(*) FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
-- Returns: 0 (should be 100+)
```
**Fix**:
1. Check Phase 4 ML Feature Store ran successfully
2. If Phase 4 incomplete: Run Phase 4 manually first
3. Then trigger Phase 5: `gcloud scheduler jobs run phase5-daily-predictions-trigger --location us-central1`

### Issue 2: All Predictions Are PASS
**Symptom**: 0 actionable picks (all confidence < 65 or edge < 1.5)
**Diagnosis**:
```sql
-- Check confidence distribution
SELECT
  CASE
    WHEN ensemble_confidence >= 65 THEN 'Good (65+)'
    WHEN ensemble_confidence >= 50 THEN 'Medium (50-64)'
    ELSE 'Low (<50)'
  END as confidence_tier,
  COUNT(*) as count
FROM `nba_predictions.player_points_predictions`
WHERE prediction_date = CURRENT_DATE()
GROUP BY confidence_tier;
```
**Fix**:
1. **Early season**: Normal (first 2-3 weeks), quality improves over time
2. **Low feature quality**: Check Phase 4 completeness (should be 85%+)
3. **System disagreement**: Check prediction_variance (>6.0 = high disagreement)

### Issue 3: XGBoost Predictions Missing
**Symptom**: Only 3 systems predicting (missing XGBoost)
**Fix**:
1. Check if XGBoost model file exists in GCS
2. Verify model loading in coordinator logs
3. If mock model: Expected until real model trained (~4 hours work)

### Issue 4: Slow Prediction Updates (<1s expected, seeing >5s)
**Symptom**: Real-time odds updates taking too long
**Diagnosis**:
```bash
# Check worker concurrency
gcloud run services describe phase5-prediction-worker \
  --region us-central1 \
  --format="value(spec.template.spec.containerConcurrency)"
```
**Fix**:
1. Verify player_daily_cache loaded in memory (should be <1s lookups)
2. Check worker auto-scaling (should have 2-5 instances during game time)
3. Increase container concurrency if needed (default: 10)

---

## Processing Flow

```
Phase 4 Feature Store ──┐
Player Daily Cache ─────┤
Prop Lines ─────────────┼─→ COORDINATOR ─┬─→ Worker 1 ─→ System predictions
                                          ├─→ Worker 2 ─→ Ensemble
                                          ├─→ Worker 3 ─→ Recommendations
                                          └─→ Worker N

                                          ↓
                              player_points_predictions table
                                          ↓
                              Phase 6 Publishing (future)
```

**Timing**:
- **6:15 AM**: Daily batch prediction (all players with games today)
- **6:00 AM - 11:00 PM**: Real-time updates when odds change
- **Waits for**: Phase 4 ML Feature Store (runs at 12:00 AM)
- **Duration**: 2-5 min (batch), <1s (real-time updates)

---

## Monitoring Alerts

| Alert | Threshold | Severity |
|-------|-----------|----------|
| Predictions generated | < 50 (on game day) | Critical |
| Actionable picks | 0 | Warning |
| Avg confidence | < 60 | Warning |
| Avg feature quality | < 70 | Warning |
| Avg feature quality | < 85 (after week 3) | Warning |
| Processing time | > 10 min (batch) | Critical |
| Processing time | > 5s (real-time) | Warning |
| XGBoost missing | systems_count < 4 | Warning |

---

## Quick Links

**📚 Complete Documentation (23 docs):** `docs/predictions/README.md`

**🎯 Essential Reading:**
- 📄 **Getting Started**: `docs/predictions/tutorials/01-getting-started.md` ⭐⭐ READ FIRST
- 📄 **Understanding Systems**: `docs/predictions/tutorials/02-understanding-prediction-systems.md`
- 📄 **Worked Examples**: `docs/predictions/tutorials/03-worked-prediction-examples.md`
- 📄 **Command Reference**: `docs/predictions/tutorials/04-operations-command-reference.md`

**🔧 Operations:**
- 📄 **Deployment Guide**: `docs/predictions/operations/01-deployment-guide.md`
- 📄 **Daily Operations**: `docs/predictions/operations/05-daily-operations-checklist.md` (2 min)
- 📄 **Performance Monitoring**: `docs/predictions/operations/06-performance-monitoring.md`
- 📄 **Emergency Procedures**: `docs/predictions/operations/09-emergency-procedures.md`

**🤖 ML & Algorithms:**
- 📄 **ML Training**: `docs/predictions/ml-training/01-initial-model-training.md`
- 📄 **Feature Strategy**: `docs/predictions/ml-training/03-feature-development-strategy.md`
- 📄 **Algorithm Specs**: `docs/predictions/algorithms/01-composite-factor-calculations.md`
- 📄 **Confidence Scoring**: `docs/predictions/algorithms/02-confidence-scoring-framework.md`

**🏗️ Architecture & Design:**
- 📄 **Parallelization Strategy**: `docs/predictions/architecture/01-parallelization-strategy.md`
- 📄 **Design Rationale**: `docs/predictions/design/01-architectural-decisions.md`

**📊 Related:**
- 🗂️ **Schema Definition**: `schemas/bigquery/predictions/`
- 🧪 **Test Suite**: `tests/predictions/`
- 📊 **Related Processors**:
  - ↑ Upstream: Phase 4 ML Feature Store V2
  - → Consumers: Phase 6 Publishing (not implemented)

---

## Notes

- **Coordinator-Worker Pattern**: Scalable architecture (1 coordinator fans out to N workers)
- **Confidence-Weighted Ensemble**: Higher quality systems get more weight dynamically
- **PASS Threshold**: 50-70% of predictions filtered as PASS (intentional for quality)
- **Real-time Updates**: Predictions refresh <1s when odds change (cached player data)
- **Mock XGBoost**: Currently using placeholder model, needs ~4hrs to train real model
- **5 Models Ready**: All code complete and tested, just needs deployment
- **Weekly Retraining**: XGBoost model retrains weekly to adapt to season changes
- **Early Season Handling**: Graceful degradation when <10 games played
- **Quality Scoring**: Confidence adjusts based on feature_quality_score from Phase 4

---

**Card Version**: 1.1
**Created**: 2025-11-15
**Last Updated**: 2025-11-25
**Verified Against**: Code in `predictions/` directory
