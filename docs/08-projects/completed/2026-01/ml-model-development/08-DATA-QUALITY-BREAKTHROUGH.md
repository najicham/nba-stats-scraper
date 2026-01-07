# Data Quality Breakthrough - Jan 3, 2026

**Time**: 2:00 PM ET
**Status**: 🎯 ROOT CAUSE IDENTIFIED
**Impact**: Explains why ML models underperform baseline

---

## 🔍 The Discovery

Ran diagnostic query on `nba_analytics.player_game_summary`:

```sql
SELECT season, COUNT(*) as records,
  ROUND(AVG(CASE WHEN minutes_played IS NOT NULL THEN 1 ELSE 0 END) * 100, 1) as pct_complete
FROM player_game_summary
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01'
GROUP BY season
```

**Results**:
```
Season 2021-22: 28,516 records | 98.3% complete ✅ EXCELLENT
Season 2022-23: 27,776 records | 34.3% complete ⚠️  PARTIAL
Season 2023-24: 27,242 records |  0.0% complete ❌ BROKEN
────────────────────────────────────────────────────────────
Total:          83,534 records | 45.0% complete ⚠️  MIXED
```

---

## 💡 Why This Matters

**Current training approach** (ml/train_real_xgboost.py):
1. Loads all 83,534 records (2021-2024)
2. Fills missing values with defaults (minutes_played=0, usage_rate=25, etc.)
3. Trains on **55% fake data**

**Result**: Model learns patterns from fake defaults, not real NBA gameplay!

**This explains**:
- Why v4 (21 features) performs worse than v2 (14 features) → More features = more NULLs = more fake data
- Why XGBoost can't beat hand-coded baseline (4.88 vs 4.27 MAE) → Training on garbage
- Why feature importance is skewed (55% on points_avg_last_10) → Only feature with real values

---

## ✅ The Solution

### Option 1: Train on Clean 2021 Data Only

**What**: Use only 2021-22 season (28,516 games with 98.3% real data)

**Change needed** (ml/train_real_xgboost.py line 74):
```python
# Before
WHERE game_date >= '2021-10-01' AND game_date < '2024-05-01'

# After
WHERE game_date >= '2021-10-01' AND game_date < '2022-10-01'
```

**Expected outcome**:
- 28,516 samples (down from 83,534)
- 98.3% real data (up from 45%)
- Model learns real patterns
- Test MAE: 4.0-4.2 (BEATS 4.27 baseline!)

**Time**: 30 minutes to retrain

---

### Option 2: Fix Data Quality (Long-term)

**Root causes identified**:
1. 2022-23: Partial backfill (34.3% complete)
2. 2023-24: No backfill (0% complete)

**Data exists in raw tables**, just not processed to analytics layer.

**To fix**:
1. Run Phase 3 analytics backfill for 2022-23 season (missing dates)
2. Run Phase 3 analytics backfill for 2023-24 season (entire season)
3. Verify minutes_played populated
4. Retrain model on full 83,534 records

**Time**: 2-4 hours (too long for today, schedule for next week)

---

## 🎯 Recommendation

**SHORT-TERM** (Today): Use Option 1 - train on clean 2021 data
- Quick (30 min)
- High confidence (98.3% real data)
- Expected to beat baseline
- Validates that ML CAN work with good data

**LONG-TERM** (Next week): Fix data quality properly
- Backfill 2022-23 and 2023-24 seasons
- Retrain on full dataset
- Expected: Even better performance (more training data)

---

## 📊 Impact Analysis

### Current Model Performance (Training on 55% Fake Data)

| Model | Test MAE | Issue |
|-------|----------|-------|
| v1 | 4.79 | Too simple + fake data |
| v2 | 4.63 | Best so far, but still fake data |
| v4 | 4.88 | More features = more NULLs = worse |

### Expected Performance (Training on 98% Real Data)

| Model | Test MAE | Basis |
|-------|----------|-------|
| v5 (clean 2021) | 4.0-4.2 | Real patterns, less samples |
| v6 (fixed data) | 3.8-4.0 | Real patterns, more samples |

---

## 🚀 Next Steps

1. **Immediate**: Train v5 on clean 2021 data (30 min)
2. **After tonight's test**: Schedule data quality fix
3. **Next week**: Backfill 2022-23 and 2023-24 seasons
4. **Future**: Retrain v6 on complete dataset

---

## 📝 Key Files

**Training script**: `ml/train_real_xgboost.py`
**Line to change**: 74 (WHERE clause)
**Current models**: `models/xgboost_real_v1-v4_*.json`
**Next model**: `models/xgboost_real_v5_20260103.json`

---

**Status**: ✅ Root cause identified, solution clear
**Owner**: Next session
**Created**: 2026-01-03 2:15 PM ET
