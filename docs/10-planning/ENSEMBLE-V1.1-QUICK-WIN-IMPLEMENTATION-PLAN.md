# Ensemble V1.1 - Quick Win Implementation Plan

**Created:** 2026-01-18
**Status:** Ready to implement
**Estimated Time:** 2-3 hours
**Expected Impact:** MAE improves from 5.41 → 4.9-5.1 (6-9% improvement)

---

## 🎯 Executive Summary

**Problem:** Ensemble V1 (5.41 MAE) performs 12.5% worse than CatBoost V8 (4.81 MAE) because:
- It EXCLUDES the best system (CatBoost V8)
- It INCLUDES a poor system with extreme bias (Zone Matchup: 6.50 MAE, -4.25 bias)
- It uses equal confidence-weighted averaging instead of performance-based weights

**Solution:** Create Ensemble V1.1 with performance-based fixed weights:
- **Add** CatBoost V8 (45% weight - best system)
- **Reduce** Zone Matchup weight (10% - was dragging down performance)
- **Keep** Similarity (25%) and Moving Average (20%) for complementarity

**Deployment:** Shadow mode alongside existing systems, promote if MAE ≤ 5.0

---

## 📋 Implementation Checklist

### Phase 1: Code Modifications (1 hour)
- [ ] Create `ensemble_v1_1.py` (copy of `ensemble_v1.py` with modifications)
- [ ] Add CatBoost V8 as 5th system in `__init__`
- [ ] Implement fixed performance-based weights
- [ ] Update system_id to `ensemble_v1_1`
- [ ] Update version to `1.1`
- [ ] Add metadata tracking for weights used

### Phase 2: Local Testing (30 minutes)
- [ ] Create test script to validate predictions
- [ ] Test with sample data (5 players)
- [ ] Verify all 5 systems are called
- [ ] Verify weights are applied correctly
- [ ] Verify MAE calculation is reasonable

### Phase 3: Integration (30 minutes)
- [ ] Update worker to instantiate Ensemble V1.1
- [ ] Add system to coordinator's system list
- [ ] Update database schema if needed (unlikely)
- [ ] Test end-to-end locally

### Phase 4: Deployment (30 minutes)
- [ ] Deploy to Cloud Run (shadow mode)
- [ ] Verify system runs in production
- [ ] Check logs for errors
- [ ] Validate predictions are being generated

### Phase 5: Monitoring (ongoing)
- [ ] Create monitoring queries
- [ ] Track MAE daily (Jan 20-24)
- [ ] Compare to CatBoost V8 and Ensemble V1
- [ ] Make promotion decision on Jan 24

---

## 🔧 Detailed Implementation Steps

### Step 1: Create Ensemble V1.1 File

```bash
# Copy existing ensemble
cp predictions/worker/prediction_systems/ensemble_v1.py \
   predictions/worker/prediction_systems/ensemble_v1_1.py
```

### Step 2: Modify `ensemble_v1_1.py`

**Change 1: Update class name and metadata**
```python
# Line 45-67
class EnsembleV1_1:
    """Ensemble V1.1 - Performance-based weighted ensemble with CatBoost V8"""

    def __init__(
        self,
        moving_average_system,
        zone_matchup_system,
        similarity_system,
        xgboost_system,
        catboost_system  # NEW: Add CatBoost V8
    ):
        """
        Initialize Ensemble V1.1 system

        Args:
            moving_average_system: Instance of MovingAverageBaseline
            zone_matchup_system: Instance of ZoneMatchupV1
            similarity_system: Instance of SimilarityBalancedV1
            xgboost_system: Instance of XGBoostV1
            catboost_system: Instance of CatBoostV8  # NEW
        """
        self.system_id = 'ensemble_v1_1'  # CHANGED
        self.system_name = 'Ensemble V1.1'  # CHANGED
        self.version = '1.1'  # CHANGED

        # Component systems
        self.moving_average = moving_average_system
        self.zone_matchup = zone_matchup_system
        self.similarity = similarity_system
        self.xgboost = xgboost_system
        self.catboost = catboost_system  # NEW

        # NEW: Performance-based fixed weights (based on historical MAE)
        self.system_weights = {
            'catboost': 0.45,      # Best system (4.81 MAE)
            'similarity': 0.25,    # Good complementarity (5.45 MAE)
            'moving_average': 0.20, # Momentum signal (5.55 MAE)
            'zone_matchup': 0.10,   # Reduced weight (6.50 MAE, extreme bias)
            'xgboost': 0.00         # Skip for now (mock model)
        }

        # Ensemble parameters (keep existing)
        self.high_agreement_threshold = 2.0
        self.good_agreement_threshold = 3.0
        self.moderate_agreement_threshold = 6.0

        # Confidence adjustments (keep existing)
        self.high_agreement_bonus = 10
        self.good_agreement_bonus = 5
        self.all_systems_bonus = 5

        # Recommendation thresholds (keep existing)
        self.edge_threshold = 1.5
        self.confidence_threshold = 65.0

        logger.info(f"Initialized {self.system_name} (v{self.version}) with 5 systems")
        logger.info(f"System weights: {self.system_weights}")
```

**Change 2: Add CatBoost V8 prediction collection**

After line 194 (after XGBoost section), add:

```python
        # System 5: CatBoost V8 (NEW)
        try:
            cb_result = self.catboost.predict(
                player_lookup=player_lookup,
                features=features,
                betting_line=prop_line
            )

            if cb_result['predicted_points'] is not None:
                predictions.append({
                    'system': 'catboost',
                    'prediction': cb_result['predicted_points'],
                    'confidence': cb_result['confidence_score'],
                    'recommendation': cb_result['recommendation']
                })
            else:
                predictions.append(None)
        except Exception as e:
            logger.warning(f"CatBoost V8 failed: {e}")
            predictions.append(None)
```

**Change 3: Replace `_calculate_weighted_prediction` method**

Replace the method at line 253-266 with:

```python
    def _calculate_weighted_prediction(self, predictions: List[Dict]) -> float:
        """
        Calculate weighted average using FIXED performance-based weights

        V1.1 Change: Uses fixed weights based on historical performance
        instead of confidence-weighted averaging

        Args:
            predictions: List of valid prediction dicts

        Returns:
            Weighted average prediction
        """
        weighted_sum = 0.0
        total_weight = 0.0

        for pred in predictions:
            system_name = pred['system']
            weight = self.system_weights.get(system_name, 0.0)

            if weight > 0:
                weighted_sum += pred['prediction'] * weight
                total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 0.0
```

**Change 4: Update metadata to include weights used**

In the `predict` method around line 232-241, update metadata:

```python
        # Build metadata
        metadata = {
            'systems_used': len(valid_predictions),
            'predictions': predictions,
            'agreement': agreement_metrics,
            'weights_used': {  # NEW
                p['system']: self.system_weights.get(p['system'], 0.0)
                for p in valid_predictions
            },
            'ensemble': {
                'prediction': ensemble_pred,
                'confidence': ensemble_conf,
                'recommendation': ensemble_rec
            }
        }
```

---

## 🧪 Testing Script

Create `test_ensemble_v1_1.py`:

```python
#!/usr/bin/env python3
"""Test Ensemble V1.1 with sample data"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from google.cloud import bigquery
from predictions.worker.prediction_systems.moving_average_baseline import MovingAverageBaseline
from predictions.worker.prediction_systems.zone_matchup_v1 import ZoneMatchupV1
from predictions.worker.prediction_systems.similarity_balanced_v1 import SimilarityBalancedV1
from predictions.worker.prediction_systems.xgboost_v1 import XGBoostV1
from predictions.worker.prediction_systems.catboost_v8 import CatBoostV8
from predictions.worker.prediction_systems.ensemble_v1_1 import EnsembleV1_1

PROJECT_ID = "nba-props-platform"

print("=" * 80)
print("ENSEMBLE V1.1 TEST")
print("=" * 80)
print()

# Initialize all systems
print("Initializing systems...")
ma_sys = MovingAverageBaseline()
zm_sys = ZoneMatchupV1()
sim_sys = SimilarityBalancedV1()
xgb_sys = XGBoostV1()
cb_sys = CatBoostV8()

ensemble = EnsembleV1_1(
    moving_average_system=ma_sys,
    zone_matchup_system=zm_sys,
    similarity_system=sim_sys,
    xgboost_system=xgb_sys,
    catboost_system=cb_sys
)
print("✓ All systems initialized")
print()

# Get sample data
client = bigquery.Client(project=PROJECT_ID)
query = """
SELECT
  mf.player_lookup,
  mf.game_date,
  mf.features,
  pgs.points as actual_points
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
  ON mf.player_lookup = pgs.player_lookup
  AND mf.game_date = pgs.game_date
WHERE mf.game_date = '2024-01-15'
  AND mf.feature_count = 33
  AND pgs.points IS NOT NULL
LIMIT 5
"""

print("Fetching 5 test samples...")
df = client.query(query).to_dataframe()
print(f"✓ Loaded {len(df)} samples")
print()

# Feature names
feature_names = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct",
    "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line",
    "avg_points_vs_opponent", "games_vs_opponent",
    "minutes_avg_last_10", "ppm_avg_last_10"
]

# Test predictions
print("Testing Ensemble V1.1 predictions...")
print("-" * 80)

errors = []
for idx, row in df.iterrows():
    features = dict(zip(feature_names, row['features']))
    prop_line = features.get('vegas_points_line', None)

    try:
        pred, conf, rec, metadata = ensemble.predict(
            features=features,
            player_lookup=row['player_lookup'],
            game_date=row['game_date'],
            prop_line=prop_line,
            historical_games=None  # Skip similarity for this test
        )

        actual = row['actual_points']
        error = abs(pred - actual)

        print(f"{row['player_lookup']:20s} | Pred: {pred:5.1f} | Actual: {actual:5.1f} | Error: {error:5.1f} | Conf: {conf:.2f}")
        print(f"  Systems used: {metadata['systems_used']}")
        print(f"  Weights: {metadata.get('weights_used', {})}")
        print()

        errors.append(error)

    except Exception as e:
        print(f"✗ {row['player_lookup']:20s} | ERROR: {e}")
        print()

if errors:
    avg_error = sum(errors) / len(errors)
    print("=" * 80)
    print(f"Average Error (MAE): {avg_error:.2f} points")
    print(f"Successful predictions: {len(errors)}/{len(df)}")
    print()
    print("✓ Ensemble V1.1 is working!" if len(errors) == len(df) else "⚠ Some predictions failed")
else:
    print("✗ All predictions failed!")
```

Run with:
```bash
PYTHONPATH=. python test_ensemble_v1_1.py
```

---

## 🚀 Deployment Steps

### 1. Update Worker to Use Ensemble V1.1

In `predictions/worker/worker.py`, add Ensemble V1.1 to the system instantiation:

```python
# Import the new ensemble
from predictions.worker.prediction_systems.ensemble_v1_1 import EnsembleV1_1

# In the worker initialization, after existing systems:
catboost_v8_sys = CatBoostV8()
ensemble_v1_1_sys = EnsembleV1_1(
    moving_average_system=moving_average_sys,
    zone_matchup_system=zone_matchup_sys,
    similarity_system=similarity_sys,
    xgboost_system=xgboost_sys,
    catboost_system=catboost_v8_sys
)

# Add to systems dict
systems = {
    'moving_average': moving_average_sys,
    'zone_matchup_v1': zone_matchup_sys,
    'similarity_balanced': similarity_sys,
    'xgboost_v1': xgboost_sys,
    'ensemble_v1': ensemble_v1_sys,  # Keep existing
    'catboost_v8': catboost_v8_sys,
    'ensemble_v1_1': ensemble_v1_1_sys  # NEW
}
```

### 2. Update Coordinator

In `predictions/coordinator/coordinator.py`, add `ensemble_v1_1` to the list of systems to run.

### 3. Deploy to Cloud Run

```bash
# Deploy prediction worker with new ensemble
cd /home/naji/code/nba-stats-scraper
./bin/predictions/deploy/deploy_prediction_worker.sh
```

### 4. Verify Deployment

```bash
# Check worker logs
gcloud run services logs read prediction-worker \
  --region=us-west2 \
  --limit=50 \
  --project=nba-props-platform

# Look for: "Initialized Ensemble V1.1 (v1.1) with 5 systems"
```

---

## 📊 Monitoring Queries

### Query 1: Daily MAE Comparison (All Systems)

```sql
SELECT
  system_id,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNT(*)) * 100, 1) as win_rate_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2026-01-20'
  AND recommendation IN ('OVER', 'UNDER')
  AND has_prop_line = TRUE
  AND system_id IN ('ensemble_v1', 'ensemble_v1_1', 'catboost_v8', 'xgboost_v1')
GROUP BY system_id
ORDER BY mae ASC
```

**Success Criteria:**
- Ensemble V1.1 MAE ≤ 5.0 (6-9% improvement from 5.41)
- Ensemble V1.1 MAE closer to CatBoost V8 (4.81) than Ensemble V1 (5.41)

### Query 2: Head-to-Head Comparison

```sql
WITH predictions AS (
  SELECT
    game_date,
    player_lookup,
    MAX(CASE WHEN system_id = 'ensemble_v1' THEN absolute_error END) as v1_error,
    MAX(CASE WHEN system_id = 'ensemble_v1_1' THEN absolute_error END) as v1_1_error,
    MAX(CASE WHEN system_id = 'catboost_v8' THEN absolute_error END) as cb_error
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= '2026-01-20'
    AND recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
  GROUP BY game_date, player_lookup
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
  ROUND(AVG(cb_error), 2) as cb_avg_error
FROM predictions
```

**Success Criteria:**
- V1.1 win rate > 55% vs V1
- V1.1 avg error < V1 avg error by 0.3-0.5 points

### Query 3: System Weight Analysis

```sql
-- Check if all 5 systems are contributing
SELECT
  game_date,
  COUNT(DISTINCT CASE WHEN system_id = 'ensemble_v1_1' THEN player_lookup END) as ensemble_predictions,
  COUNT(DISTINCT CASE WHEN system_id = 'catboost_v8' THEN player_lookup END) as catboost_predictions,
  COUNT(DISTINCT CASE WHEN system_id = 'moving_average' THEN player_lookup END) as ma_predictions,
  COUNT(DISTINCT CASE WHEN system_id = 'zone_matchup_v1' THEN player_lookup END) as zm_predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= '2026-01-20'
  AND is_active = TRUE
GROUP BY game_date
ORDER BY game_date DESC
```

**Success Criteria:**
- Ensemble V1.1 predictions ≈ CatBoost V8 predictions (same coverage)
- All component systems running

---

## ✅ Decision Criteria (Jan 24)

### Promote to Production if:
1. ✅ 5-day average MAE ≤ 5.0 (improved from 5.41)
2. ✅ Win rate vs Ensemble V1 > 55%
3. ✅ No system crashes or errors
4. ✅ Prediction coverage ≥ 95% of CatBoost V8

### Keep in Shadow Mode if:
- 5.0 < MAE < 5.2 (marginal improvement, needs more data)
- System unstable (errors, crashes)

### Rollback if:
- MAE > 5.2 (no improvement or worse)
- Prediction coverage < 80%
- System reliability issues

---

## 📝 Daily Monitoring Checklist (Jan 20-24)

**Each morning (5 minutes):**

1. Run Query 1 (Daily MAE Comparison)
2. Record results:
   | Date | V1 MAE | V1.1 MAE | CatBoost MAE | V1.1 Status |
   |------|--------|----------|--------------|-------------|
   | Jan 20 | ___ | ___ | ___ | ✅/⚠️/🚨 |
   | Jan 21 | ___ | ___ | ___ | ✅/⚠️/🚨 |
   | Jan 22 | ___ | ___ | ___ | ✅/⚠️/🚨 |
   | Jan 23 | ___ | ___ | ___ | ✅/⚠️/🚨 |
   | Jan 24 | ___ | ___ | ___ | ✅/⚠️/🚨 |

3. Check for errors:
   ```bash
   gcloud logging read \
     'resource.labels.service_name:prediction-worker AND severity>=ERROR AND jsonPayload.system_id:ensemble_v1_1' \
     --limit=10 \
     --project=nba-props-platform \
     --freshness=24h
   ```

4. **Decision on Jan 24:** Run Query 2 (head-to-head) and apply decision criteria

---

## 🎯 Success Metrics Summary

| Metric | Current (V1) | Target (V1.1) | Stretch Goal |
|--------|-------------|---------------|--------------|
| **MAE** | 5.41 | ≤ 5.0 | ≤ 4.9 |
| **vs CatBoost Gap** | +12.5% worse | +4% worse | +2% worse |
| **Win Rate** | 39.0% | ≥ 48% | ≥ 50% |
| **Prediction Coverage** | 902 (Jan 1-17) | ≥ 1000 | ≥ 1100 |

**Expected Outcome:** 85% chance of success (MAE ≤ 5.0)

---

## 🚨 Troubleshooting

### Issue 1: CatBoost V8 not found
**Error:** `ImportError: cannot import name 'CatBoostV8'`

**Solution:**
```python
# Ensure CatBoost V8 is imported in ensemble_v1_1.py
from predictions.worker.prediction_systems.catboost_v8 import CatBoostV8
```

### Issue 2: All predictions fail
**Error:** `Insufficient valid predictions (0/5)`

**Solution:**
- Check that all 5 systems are properly initialized
- Verify features dict has all 33 required features
- Check logs for individual system failures

### Issue 3: MAE worse than expected
**Symptom:** V1.1 MAE > 5.2

**Investigation:**
1. Check if all 5 systems are running:
   ```sql
   SELECT system_id, COUNT(*)
   FROM prediction_accuracy
   WHERE game_date >= '2026-01-20'
   GROUP BY system_id
   ```

2. Check weight distribution:
   - Verify `self.system_weights` values are correct
   - Check metadata to see which systems contributed

3. Compare individual system performance:
   - If CatBoost V8 is performing poorly, investigate model issues
   - If Zone Matchup is still dominating, reduce weight further

---

## 📅 Timeline

| Day | Activity | Duration | Status |
|-----|----------|----------|--------|
| **Jan 18 (Today)** | Create implementation plan | 30 min | ✅ Complete |
| **Jan 19** | Implement V1.1 code | 1 hour | Pending |
| **Jan 19** | Test locally | 30 min | Pending |
| **Jan 19** | Deploy to Cloud Run | 30 min | Pending |
| **Jan 19** | Verify production | 30 min | Pending |
| **Jan 20-24** | Daily monitoring | 5 min/day | Pending |
| **Jan 24** | Promotion decision | 1 hour | Pending |

**Total Time Investment:** ~3.5 hours + 25 minutes monitoring = **~4 hours total**

---

## 🎉 Expected Outcome

**If successful (85% probability):**
- Ensemble V1.1 achieves 4.9-5.1 MAE (6-9% improvement)
- Closes gap with CatBoost V8 from 12.5% → 2-4%
- Win rate improves from 39% → 48-50%
- System runs reliably in production
- **Ready to promote on Jan 24**

**Next steps after V1.1:**
- Consider adding XGBoost V1 V2 if it performs well (Jan 24 decision)
- Revisit Ridge meta-learner training for further optimization (optional)
- Implement automated retraining pipeline (Track B, future)

---

**Document Status:** ✅ Ready for Implementation
**Next Action:** Begin Phase 1 (Code Modifications)
**Owner:** Naji
**Estimated Completion:** Jan 19, 2026
