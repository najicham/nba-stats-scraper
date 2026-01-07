# 🌙 Evening Session Plan - Jan 3, 2026

**Created:** Jan 3, 2026 - Afternoon
**Session 1:** Tonight 8:30 PM ET (Betting Lines Test)
**Session 2:** Tomorrow Morning (ML Tuning)

---

## ⚡ TONIGHT'S CRITICAL TEST (8:30 PM ET)

### 🎯 Objective
**Verify betting lines flow through entire pipeline after Phase 3 fix**

### ⏰ Timeline

```
7:00 PM ET: NBA games start
8:00 PM ET: betting_lines workflow auto-collects lines
8:30 PM ET: YOU RUN FULL PIPELINE TEST ← START HERE
8:45 PM ET: Verify betting lines in all layers
9:00 PM ET: Check frontend API
9:15 PM ET: Either celebrate 🎉 or debug 🔧
```

### 📋 Step-by-Step Commands

#### Step 1: Run Full Pipeline (8:30 PM ET)
```bash
cd /home/naji/code/nba-stats-scraper

# Trigger full pipeline
./bin/pipeline/force_predictions.sh 2026-01-03

# This will:
# - Phase 1→2: Process raw data
# - Phase 3: Merge betting lines into analytics ← THE FIX
# - Phase 4→5: Precompute & predictions
# - Phase 6: Publish to frontend API
```

#### Step 2: Verify Betting Lines in ALL Layers (8:45 PM ET)
```bash
# Check Raw layer (should have ~14,000 lines)
bq query --use_legacy_sql=false "
SELECT COUNT(*) as betting_lines
FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
WHERE game_date = '2026-01-03'"

# Check Analytics layer (should have 100-150 players)
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_players,
  COUNTIF(has_prop_line) as players_with_lines
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = '2026-01-03'"

# Check Predictions layer (should have 100-150 players)
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_predictions,
  COUNTIF(current_points_line IS NOT NULL) as predictions_with_lines
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2026-01-03' AND system_id = 'ensemble_v1'"

# Expected results:
# Raw: 12,000-15,000 lines ✅
# Analytics: 100-150 with has_prop_line=true ✅
# Predictions: 100-150 with current_points_line ✅
```

#### Step 3: Check Frontend API (9:00 PM ET)
```bash
# Fetch tonight's data from public API
curl "https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json" | jq '{
  game_date: .game_date,
  total_players: (.players | length),
  total_with_lines: [.players[] | select(.betting_line != null)] | length
}'

# Expected:
# {
#   "game_date": "2026-01-03",
#   "total_players": 200-300,
#   "total_with_lines": 100-150  ← THIS IS THE WIN!
# }
```

### ✅ Success Criteria

- [ ] Raw table: 12,000+ betting lines
- [ ] Analytics: 100+ players with `has_prop_line = TRUE`
- [ ] Predictions: 100+ players with `current_points_line IS NOT NULL`
- [ ] Frontend API: `total_with_lines > 100`

**If ALL pass:** Betting lines pipeline is COMPLETE! 🎉

### 🚨 If Something Fails

#### Analytics layer has 0 players with lines
```bash
# Check if Phase 3 ran
bq query --use_legacy_sql=false "
SELECT processor_name, status, triggered_at, error_message
FROM \`nba-props-platform.nba_orchestration.processor_execution_log\`
WHERE processor_name = 'UpcomingPlayerGameContextProcessor'
  AND DATE(triggered_at) = '2026-01-03'
ORDER BY triggered_at DESC LIMIT 5"

# Check for AttributeError in logs
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors"
  AND severity=ERROR
  AND timestamp>="2026-01-03T00:00:00Z"' \
  --limit=10
```

#### Predictions layer has 0 lines
```bash
# Verify betting lines made it to analytics first
# Then check Phase 5 logs
gcloud logging read 'resource.labels.service_name="prediction-coordinator"
  AND timestamp>="2026-01-03T20:00:00Z"' \
  --limit=20
```

#### Frontend API shows 0 lines
```bash
# Check Phase 6 execution
bq query --use_legacy_sql=false "
SELECT triggered_at, status, records_published
FROM \`nba-props-platform.nba_orchestration.processor_execution_log\`
WHERE processor_name = 'TonightPublisher'
  AND DATE(triggered_at) = '2026-01-03'
ORDER BY triggered_at DESC LIMIT 5"
```

---

## 🌅 TOMORROW MORNING SESSION (Jan 4)

### 🎯 Objective
**Improve hand-coded rules in mock_xgboost_model.py to beat 4.27 MAE baseline**

### 📋 Background (From Today's Investigation)

**Discovery:** Production "xgboost_v1" is actually hand-coded rules, not ML!

**Current Performance:**
- Hand-coded rules: 4.27 MAE
- Our trained ML: 4.94 MAE (16% worse due to 95% NULL data)

**Strategy:** Tune the existing hand-coded rules to ~4.0 MAE (quick win!)

### ⏱️ Time Required: 1-2 hours

### 📝 Step-by-Step Plan

#### Step 1: Analyze Recent Errors (30 min)
```bash
cd /home/naji/code/nba-stats-scraper

# Find games where mock model performed poorly
bq query --use_legacy_sql=false --format=csv "
SELECT
  player_lookup,
  game_date,
  actual_points,
  predicted_points,
  ABS(actual_points - predicted_points) as error,
  -- Try to join context to understand why
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE system_id = 'xgboost_v1'
  AND game_date >= '2024-03-01' AND game_date < '2024-05-01'
  AND ABS(actual_points - predicted_points) > 8  -- Big errors only
ORDER BY error DESC
LIMIT 100
" > /tmp/big_errors.csv

# Analyze patterns:
# - Are errors clustered in back-to-back games?
# - Do errors happen more on road games?
# - Are high-usage players over/under-predicted?
# - Does fatigue adjustment need tuning?
```

#### Step 2: Tune Baseline Weights (20 min)

**File:** `predictions/shared/mock_xgboost_model.py:120`

**Current:**
```python
baseline = (
    points_last_5 * 0.35 +
    points_last_10 * 0.40 +
    points_season * 0.25
)
```

**Test variations:**
```python
# Option A: Weight recent form more
baseline = (
    points_last_5 * 0.38 +
    points_last_10 * 0.42 +
    points_season * 0.20
)

# Option B: Weight last_10 more (more stable)
baseline = (
    points_last_5 * 0.30 +
    points_last_10 * 0.50 +
    points_season * 0.20
)

# Option C: Season average less reliable in playoffs
baseline = (
    points_last_5 * 0.40 +
    points_last_10 * 0.45 +
    points_season * 0.15
)
```

#### Step 3: Add Injury-Aware Adjustment (20 min)

**File:** `predictions/shared/mock_xgboost_model.py:185` (after shot_adj)

**Add:**
```python
# Check if player was recently injured (from injury data)
# This would require integration with injury table
# For now, proxy: sudden drop in minutes
if minutes < 20 and minutes_last_10 > 30:
    injury_adj = -1.8  # Returning from injury, limited minutes
elif minutes > 20 and minutes_last_10 < 15:
    injury_adj = 1.2   # Increased role after recovery
else:
    injury_adj = 0.0
```

#### Step 4: Improve Fatigue Curve (15 min)

**File:** `predictions/shared/mock_xgboost_model.py:129`

**Current:**
```python
if fatigue < 50:
    fatigue_adj = -2.5  # Heavy fatigue
elif fatigue < 70:
    fatigue_adj = -1.0  # Moderate fatigue
elif fatigue > 85:
    fatigue_adj = 0.5   # Well-rested boost
else:
    fatigue_adj = 0.0   # Neutral
```

**Improved (more gradual):**
```python
if fatigue < 40:
    fatigue_adj = -3.0  # Extreme fatigue (back-to-back of back-to-back)
elif fatigue < 55:
    fatigue_adj = -2.0  # Heavy fatigue
elif fatigue < 70:
    fatigue_adj = -1.2  # Moderate fatigue
elif fatigue < 80:
    fatigue_adj = -0.5  # Slight fatigue
elif fatigue > 90:
    fatigue_adj = 0.8   # Well-rested boost
else:
    fatigue_adj = 0.0   # Neutral
```

#### Step 5: Test on Validation Set (15 min)

**Create test script:** `ml/test_improved_rules.py`

```python
#!/usr/bin/env python3
"""Test improved mock model rules"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from predictions.shared.mock_xgboost_model import load_mock_model
from google.cloud import bigquery
import numpy as np

# Load data
client = bigquery.Client(project='nba-props-platform')
query = """
SELECT
    player_lookup,
    game_date,
    actual_points,
    -- features...
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'xgboost_v1'
  AND game_date >= '2024-02-04'  -- Test set
  AND game_date <= '2024-04-14'
"""
df = client.query(query).to_dataframe()

# Test current model
model = load_mock_model(seed=42)
current_preds = model.predict(features)
current_mae = np.mean(np.abs(df['actual_points'] - current_preds))

print(f"Current MAE: {current_mae:.2f}")
print(f"Target: < 4.20")
print(f"Improvement needed: {current_mae - 4.20:.2f} points")
```

**Run:**
```bash
PYTHONPATH=. python3 ml/test_improved_rules.py
```

#### Step 6: Deploy if Successful (10 min)

**If new MAE < 4.20:**
```bash
# No deployment needed - mock_xgboost_model.py is already in use!
# Just need to commit the changes

git add predictions/shared/mock_xgboost_model.py
git commit -m "feat: Improve hand-coded rules - tune weights and fatigue curve

- Adjust baseline weights (0.35/0.40/0.25 → 0.38/0.42/0.20)
- Improve fatigue curve (more gradual decay)
- Add injury-aware adjustment
- Test MAE: 4.XX (improved from 4.27)

Improves prediction accuracy by X.X% without requiring ML training
or data quality fixes."

git push
```

**Service auto-deploys:** Changes will be picked up on next prediction run

---

## 📊 Expected Outcomes

### Tonight (Betting Lines Test)

**Best Case (90% probability):**
- ✅ All layers have betting lines
- ✅ Frontend API shows 100+ players with lines
- ✅ Pipeline fix is COMPLETE
- 🎉 **Celebrate and document success**

**Worst Case (10% probability):**
- ❌ Something fails
- 🔧 Debug using commands above
- 📝 Document issue and fix

### Tomorrow (Rule Tuning)

**Expected Result:**
- Current: 4.27 MAE
- Target: 4.0-4.1 MAE
- Improvement: 4-6%

**Time:** 1-2 hours

**Risk:** Low (can revert if worse)

---

## 📚 Key Documentation References

**Tonight:**
- `docs/09-handoff/START-HERE-JAN-3.md` - Betting lines test guide
- `docs/09-handoff/2026-01-03-CRITICAL-FIXES-SESSION-HANDOFF.md` - Phase 3 fix details

**Tomorrow:**
- `docs/08-projects/current/ml-model-development/05-CRITICAL-INVESTIGATION-JAN-3-2026.md` - Investigation findings
- `predictions/shared/mock_xgboost_model.py` - File to edit

---

## ✅ Success Checklist

### Tonight
- [ ] Pipeline runs successfully
- [ ] Betting lines in raw table (12,000+)
- [ ] Betting lines in analytics (100+ players)
- [ ] Betting lines in predictions (100+ players)
- [ ] Betting lines in frontend API (total_with_lines > 100)
- [ ] Document results

### Tomorrow
- [ ] Analyze error patterns
- [ ] Tune baseline weights
- [ ] Improve fatigue curve
- [ ] Add injury adjustment (if time)
- [ ] Test on validation set
- [ ] Deploy if MAE < 4.20
- [ ] Document improvement

---

## 🎯 Bottom Line

**Tonight:** Validate that Phase 3 betting lines fix works in production

**Tomorrow:** Quick win - tune hand-coded rules to beat 4.27 MAE baseline

**Next Week:** Consider hybrid ML + rules approach for 3.8-4.0 MAE

---

**Good luck tonight! 🍀**

Remember: 8:30 PM ET is the critical test time. Everything is ready!
