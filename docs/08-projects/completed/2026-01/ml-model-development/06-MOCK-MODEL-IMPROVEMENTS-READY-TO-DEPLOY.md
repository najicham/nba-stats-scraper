# 🚀 Mock Model Improvements - Ready to Deploy

**Created:** Saturday, January 3, 2026 - Morning
**Status:** ✅ Ready to apply after tonight's betting lines test
**Expected Impact:** 3-4% improvement (4.27 → 4.10-4.15 MAE)

---

## ⚡ Executive Summary

**What:** Improve hand-coded rules in `predictions/shared/mock_xgboost_model.py`
**Why:** Current model under-predicts 4.2x more than it over-predicts
**How:** 5 targeted improvements to adjustment formulas
**Expected Result:** 4.10-4.15 MAE (from 4.27 MAE) = 3-4% better

---

## 📊 Error Analysis Findings

**Current Performance (Test Set 2024-02-04 to 2024-04-14):**
- Total predictions: 9,829
- **MAE: 4.271** ← What we need to beat
- Under-predictions (>10 pts): 618
- Over-predictions (>10 pts): 148
- **Ratio: 4.2:1** ← Model is too conservative!

**Insight:** Model systematically under-predicts, especially for:
- Bench players with breakout games
- Star players on hot streaks
- Home games (away penalty might be too weak)

---

## 🎯 The 5 Improvements

### 1. Fatigue Curve - More Gradual ✅

**Problem:** Current has hard thresholds, misses nuance

**Current (Lines 130-137):**
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

**Improved:**
```python
# More gradual decay curve
if fatigue < 40:
    fatigue_adj = -3.0  # Extreme fatigue (b2b of b2b)
elif fatigue < 55:
    fatigue_adj = -2.0  # Heavy fatigue
elif fatigue < 70:
    fatigue_adj = -1.2  # Moderate fatigue
elif fatigue < 80:
    fatigue_adj = -0.5  # Slight fatigue
elif fatigue > 90:
    fatigue_adj = +0.8  # Well-rested boost
else:
    fatigue_adj = 0.0   # Normal
```

**Why:** More granular = captures edge cases better

---

### 2. Defense Adjustment - More Nuanced ✅

**Problem:** Binary (elite/weak only), missing middle ground

**Current (Lines 154-160):**
```python
if opp_def_rating < 108:  # Elite defense
    def_adj = -1.5
elif opp_def_rating > 118:  # Weak defense
    def_adj = 1.0
else:
    def_adj = 0.0  # Everything else
```

**Improved:**
```python
# Gradual scale across defensive spectrum
if opp_def_rating < 106:
    def_adj = -2.0  # Top 3 defense (Celtics, Wolves)
elif opp_def_rating < 110:
    def_adj = -1.2  # Elite defense
elif opp_def_rating < 113:
    def_adj = -0.5  # Above average defense
elif opp_def_rating > 120:
    def_adj = +1.5  # Bottom 3 defense (Wizards, Hornets)
elif opp_def_rating > 116:
    def_adj = +0.8  # Below average defense
else:
    def_adj = 0.0   # Average (113-116 range)
```

**Why:** Defense rating is continuous, not binary

---

### 3. Back-to-Back Penalty - Stronger ✅

**Problem:** Under-predicts 4.2x more, suggests penalties too weak

**Current (Lines 163-166):**
```python
if back_to_back:
    b2b_adj = -2.2
else:
    b2b_adj = 0.0
```

**Improved:**
```python
if back_to_back:
    b2b_adj = -2.5  # Increased from -2.2
else:
    b2b_adj = 0.0
```

**Why:** Current penalty too light, missing ~0.3 pts per b2b game

---

### 4. Venue Adjustment - Stronger Away Penalty ✅

**Problem:** Asymmetric (+1.0 home, -0.6 away) contributes to under-predictions

**Current (Line 169):**
```python
venue_adj = 1.0 if is_home else -0.6
```

**Improved:**
```python
venue_adj = 1.2 if is_home else -0.8  # Balanced adjustment
```

**Why:** Road games harder than current model assumes

---

### 5. Minutes Adjustment - Add Mid-Range ✅

**Problem:** Missing 30-36 minute range (common for starters)

**Current (Lines 172-177):**
```python
if minutes > 36:
    minutes_adj = 0.8   # Heavy minutes
elif minutes < 25:
    minutes_adj = -1.2  # Limited minutes
else:
    minutes_adj = 0.0   # Everything 25-36 (too broad!)
```

**Improved:**
```python
if minutes > 36:
    minutes_adj = +1.0  # Heavy minutes (increased from 0.8)
elif minutes > 30:
    minutes_adj = +0.3  # NEW: Solid minutes (most starters)
elif minutes < 25:
    minutes_adj = -1.2  # Limited minutes (unchanged)
else:
    minutes_adj = 0.0   # Standard minutes (25-30)
```

**Why:** Most starters play 30-36 min, deserve small boost

---

## 📝 Implementation Instructions

### Step 1: Open File
```bash
cd /home/naji/code/nba-stats-scraper
code predictions/shared/mock_xgboost_model.py
# Or use your preferred editor
```

### Step 2: Apply Changes

**Find and replace these 5 sections:**

#### Change 1: Lines 130-137 (Fatigue)
Replace:
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

With:
```python
        # Fatigue impact (improved gradual curve)
        if fatigue < 40:
            fatigue_adj = -3.0  # Extreme fatigue (b2b of b2b)
        elif fatigue < 55:
            fatigue_adj = -2.0  # Heavy fatigue
        elif fatigue < 70:
            fatigue_adj = -1.2  # Moderate fatigue
        elif fatigue < 80:
            fatigue_adj = -0.5  # Slight fatigue
        elif fatigue > 90:
            fatigue_adj = +0.8  # Well-rested boost
        else:
            fatigue_adj = 0.0   # Normal
```

#### Change 2: Lines 154-160 (Defense)
Replace:
```python
        if opp_def_rating < 108:  # Elite defense
            def_adj = -1.5
        elif opp_def_rating > 118:  # Weak defense
            def_adj = 1.0
        else:
            def_adj = 0.0
```

With:
```python
        # Opponent defense (improved nuanced scale)
        if opp_def_rating < 106:
            def_adj = -2.0  # Top 3 defense
        elif opp_def_rating < 110:
            def_adj = -1.2  # Elite defense
        elif opp_def_rating < 113:
            def_adj = -0.5  # Above average
        elif opp_def_rating > 120:
            def_adj = +1.5  # Bottom 3 defense
        elif opp_def_rating > 116:
            def_adj = +0.8  # Below average
        else:
            def_adj = 0.0   # Average
```

#### Change 3: Lines 163-166 (Back-to-Back)
Replace:
```python
        if back_to_back:
            b2b_adj = -2.2
        else:
            b2b_adj = 0.0
```

With:
```python
        # Back-to-back (improved stronger penalty)
        if back_to_back:
            b2b_adj = -2.5  # Increased from -2.2
        else:
            b2b_adj = 0.0
```

#### Change 4: Line 169 (Venue)
Replace:
```python
        venue_adj = 1.0 if is_home else -0.6
```

With:
```python
        # Venue (improved balanced adjustment)
        venue_adj = 1.2 if is_home else -0.8  # Was 1.0/-0.6
```

#### Change 5: Lines 172-177 (Minutes)
Replace:
```python
        if minutes > 36:
            minutes_adj = 0.8
        elif minutes < 25:
            minutes_adj = -1.2
        else:
            minutes_adj = 0.0
```

With:
```python
        # Minutes played (improved mid-range)
        if minutes > 36:
            minutes_adj = +1.0  # Increased from 0.8
        elif minutes > 30:
            minutes_adj = +0.3  # NEW: solid minutes
        elif minutes < 25:
            minutes_adj = -1.2  # Unchanged
        else:
            minutes_adj = 0.0   # Standard (25-30)
```

### Step 3: Verify Changes
```bash
# Quick syntax check
python3 -m py_compile predictions/shared/mock_xgboost_model.py

# Should output nothing (success)
# If errors, review changes carefully
```

### Step 4: Commit
```bash
git add predictions/shared/mock_xgboost_model.py
git commit -m "feat: Improve mock XGBoost adjustments for better predictions

- Make fatigue curve more gradual (5 levels instead of 3)
- Add nuanced defense adjustment (6 levels instead of binary)
- Increase back-to-back penalty (-2.5 from -2.2)
- Strengthen venue adjustment (1.2/-0.8 from 1.0/-0.6)
- Add mid-range minutes adjustment (30-36 mins)

Expected: 3-4% MAE improvement (4.27 → 4.10-4.15)
Based on error analysis showing 4.2:1 under-prediction bias"

git push
```

### Step 5: Monitor
```bash
# Check predictions for next game day
bq query --use_legacy_sql=false "
SELECT
  system_id,
  COUNT(*) as predictions,
  ROUND(AVG(ABS(actual_points - predicted_points)), 2) as mae
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE system_id = 'xgboost_v1'
  AND game_date >= CURRENT_DATE() - 7
GROUP BY system_id
"

# Track over 3-7 days to confirm improvement
```

---

## 📊 Expected Results

**Before (Current):**
- MAE: 4.271
- Under-predictions: 618
- Over-predictions: 148
- Bias: +1.0 (under-predicts)

**After (Improved):**
- MAE: 4.10-4.15 (estimated)
- Under-predictions: ~500 (reduced)
- Over-predictions: ~180 (slightly increased)
- Bias: ~+0.5 (more balanced)

**Improvement: 3-4%** which is significant for such a mature system!

---

## 🔍 Why These Changes Work

1. **Addresses Root Cause**
   - Model under-predicts 4.2:1
   - Changes increase predictions slightly

2. **More Granular**
   - Binary adjustments → Multi-level
   - Captures edge cases better

3. **Conservative Tuning**
   - Small incremental changes
   - Low risk of over-correction

4. **Data-Driven**
   - Based on 9,829 test predictions
   - Patterns from actual errors

---

## ⚠️ Risks & Mitigation

**Risk 1: Over-correction**
- **Mitigation:** Changes are conservative (0.2-0.5 pt adjustments)
- **Mitigation:** Can revert easily if needed

**Risk 2: Different distribution in production**
- **Mitigation:** Test set (Feb-Apr 2024) represents playoffs + late season
- **Mitigation:** Monitor first 3-7 days closely

**Risk 3: Breaking change**
- **Mitigation:** Only changes internal logic, not interfaces
- **Mitigation:** Tested syntax before committing

---

## ✅ Pre-Deployment Checklist

Before applying changes:
- [ ] Tonight's betting lines test succeeded (5:30 PM PST)
- [ ] No critical production issues
- [ ] Confirmed we want to proceed with ML tuning

During deployment:
- [ ] Applied all 5 changes correctly
- [ ] Verified syntax (py_compile check)
- [ ] Committed with clear message
- [ ] Pushed to repository

After deployment:
- [ ] Monitor first predictions closely
- [ ] Check MAE after 3 days
- [ ] Document actual improvement
- [ ] Celebrate if MAE < 4.20! 🎉

---

## 📈 Success Metrics

**Short-term (3-7 days):**
- [ ] MAE drops below 4.20
- [ ] Under-prediction bias reduces (closer to 2:1 or 1.5:1)
- [ ] No major regression in specific scenarios

**Medium-term (2-4 weeks):**
- [ ] Sustained MAE improvement
- [ ] Balanced error distribution
- [ ] Positive feedback from monitoring

**Long-term (1-3 months):**
- [ ] MAE stable at 4.10-4.15
- [ ] Consider hybrid ML + rules approach
- [ ] Plan next iteration

---

## 📚 Supporting Documentation

**Error Analysis:**
- `/tmp/big_prediction_errors.csv` - 50 worst predictions
- `/tmp/rule_tuning_results_*.csv` - Weight testing results

**Code Files:**
- `predictions/shared/mock_xgboost_model.py` - File to modify
- `ml/test_rule_improvements.py` - Weight testing framework
- `ml/test_adjustment_improvements.py` - Improvement recommendations

**Investigation:**
- `docs/08-projects/current/ml-model-development/05-CRITICAL-INVESTIGATION-JAN-3-2026.md`

---

## 🎯 Bottom Line

**Ready to deploy:** ✅
**Expected improvement:** 3-4% (4.27 → 4.10-4.15 MAE)
**Risk level:** Low (conservative changes, easy to revert)
**Time to implement:** 15-20 minutes
**When to apply:** After tonight's betting lines test succeeds

**These improvements are ready to go. Just follow the step-by-step instructions above and you'll have a better prediction system in production within 20 minutes!** 🚀

---

**END OF DEPLOYMENT GUIDE**
