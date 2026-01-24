# Feature Store Change Analysis: January 7-8, 2026

**Analysis Date:** 2026-01-16
**Analysis Scope:** NBA ML Feature Store v2 (Jan 1-15, 2026)
**Critical Finding:** Major data source transition occurred on Jan 8, 2026

---

## Executive Summary

A significant change occurred in the NBA ML feature store on **January 8, 2026**, when the `phase4_partial` data source completely disappeared and all records switched to `mixed` data source. This transition correlates with the model performance degradation observed around the same time.

**Key Finding:** Features are NOT broken - they just changed quality and source. The features still have valid values, but the distribution and quality characteristics shifted significantly.

---

## 1. Feature Quality Over Time (Jan 1-15, 2026)

### Daily Statistics

| Date | Avg Quality | Min | Max | StdDev | Records |
|------|-------------|-----|-----|--------|---------|
| 2026-01-01 | 77.3 | 62.8 | 97.0 | 14.1 | 133 |
| 2026-01-02 | 81.7 | 62.8 | 97.0 | 16.1 | 341 |
| 2026-01-03 | 81.1 | 62.8 | 97.0 | 15.5 | 253 |
| 2026-01-04 | 79.2 | 62.8 | 97.0 | 15.7 | 255 |
| 2026-01-05 | 81.4 | 62.8 | 97.0 | 14.9 | 240 |
| 2026-01-06 | 81.4 | 62.8 | 97.0 | 15.0 | 189 |
| **2026-01-07** | **89.4** | 62.8 | 97.0 | **10.5** | 263 |
| **2026-01-08** | **83.1** | **77.2** | **84.4** | **2.8** | 115 |
| 2026-01-09 | 86.2 | 73.0 | 97.0 | 6.9 | 456 |
| 2026-01-10 | 62.6 | 58.6 | 62.8 | 0.9 | 290 |
| 2026-01-11 | 81.9 | 73.0 | 84.4 | 4.0 | 268 |
| 2026-01-12 | 79.1 | 67.6 | 84.4 | 4.6 | 98 |
| 2026-01-13 | 85.9 | 63.4 | 97.0 | 12.5 | 236 |
| 2026-01-14 | 85.6 | 63.4 | 97.0 | 12.5 | 234 |
| 2026-01-15 | 84.9 | 63.4 | 97.0 | 12.9 | 242 |

### Key Observations:

1. **Jan 7** had the HIGHEST average quality (89.4) with lowest stddev (10.5) - most consistent day
2. **Jan 8** shows dramatic change:
   - Max quality dropped from 97.0 → 84.4 (no high-quality features!)
   - Min quality increased from 62.8 → 77.2 (no low-quality features!)
   - StdDev collapsed to 2.8 (very uniform quality)
   - Record count dropped from 263 → 115 (56% reduction!)
3. **Jan 10** is anomalous with very LOW quality (62.6 avg, 58.6-62.8 range)

---

## 2. Data Source Distribution Change

### Critical Transition on Jan 8, 2026

| Date | Data Source | Records | Avg Quality | Min | Max |
|------|-------------|---------|-------------|-----|-----|
| **Jan 6** | mixed | 107 | 69.5 | 62.8 | 84.4 |
| **Jan 6** | phase4_partial | 82 | 96.9 | 89.8 | 97.0 |
| **Jan 7** | mixed | 97 | 76.5 | 62.8 | 84.4 |
| **Jan 7** | phase4_partial | 166 | 96.9 | 89.8 | 97.0 |
| **→ Jan 8** | **mixed** | **115** | **83.1** | **77.2** | **84.4** |
| **→ Jan 8** | **phase4_partial** | **0** | **—** | **—** | **—** |
| **Jan 9** | mixed | 456 | 86.2 | 73.0 | 97.0 |
| **Jan 10** | mixed | 290 | 62.6 | 58.6 | 62.8 |

### Analysis:

**Before Jan 8:**
- Dual data sources: `phase4_partial` (high quality ~97) + `mixed` (medium quality ~70)
- phase4_partial provided the best features (quality scores 89.8-97)
- Roughly 60-70% of records were phase4_partial

**After Jan 8:**
- ONLY `mixed` data source remains
- No phase4_partial records AT ALL
- Quality distribution completely changed
- Jan 8-15: 100% mixed data source (1,939 records, 0 phase4_partial)

**This is the smoking gun!** The phase4_partial pipeline stopped producing features on Jan 8.

---

## 3. Before vs After Comparison

### Jan 1-7 (Before) vs Jan 8-15 (After)

| Metric | Jan 1-7 (Before) | Jan 8-15 (After) | Change |
|--------|------------------|------------------|--------|
| **Total Records** | 1,674 | 1,939 | +16% |
| **Avg Quality** | 82.0 | 81.3 | -0.9% |
| **StdDev Quality** | 15.1 | 11.8 | -22% (more uniform) |
| **Min Quality** | 62.8 | 58.6 | -4.2 points |
| **Max Quality** | 97.0 | 97.0 | No change |
| | | | |
| **phase4_partial** | 783 (47%) | **0 (0%)** | **-100%** |
| **mixed** | 891 (53%) | 1,939 (100%) | +118% |
| | | | |
| **Quality 90+** | 770 (46%) | 492 (25%) | **-46% records** |
| **Quality 80-89** | 123 (7%) | 593 (31%) | +382% records |
| **Quality 70-79** | 237 (14%) | 442 (23%) | +87% records |
| **Quality <70** | 544 (33%) | 412 (21%) | -24% records |

### Key Insights:

1. **Loss of High-Quality Features:** 46% of records had quality 90+ before Jan 8, only 25% after
2. **Quality Shifted to Middle:** 80-89 quality band went from 7% → 31%
3. **More Uniform Distribution:** StdDev dropped 22%, indicating less variance
4. **Complete Loss of phase4_partial:** 783 → 0 records

---

## 4. Feature Completeness Analysis

### Source Metadata Fields

All source completeness fields are **NULL for ALL records** across Jan 1-15:
- `source_daily_cache_completeness_pct`: NULL for all records
- `source_composite_completeness_pct`: NULL for all records
- `source_shot_zones_completeness_pct`: NULL for all records
- `source_team_defense_completeness_pct`: NULL for all records

**Exception:** Jan 15 has 2 records (out of 242) with completeness values of 100% for all fields.

**Implication:** The metadata tracking fields are not being populated properly, making it impossible to track data quality at the source level through these fields.

---

## 5. Feature Array Health Check

### All records have valid feature arrays:
- ✅ NO null feature arrays
- ✅ NO empty feature arrays
- ✅ ALL records have exactly 33 features
- ✅ NO records with wrong feature count
- ✅ feature_version = "v2_33features" for ALL records

### Feature Value Patterns:

| Date | Source | Avg Feature[0] | Avg Feature[5] | Avg Feature[10] | First 3 Zeros Count |
|------|--------|----------------|----------------|-----------------|---------------------|
| Jan 6 | mixed | 5.84 | 57.98 | 0.0 | 13 (12%) |
| Jan 6 | phase4 | 10.96 | 95.66 | 0.0 | 0 (0%) |
| Jan 7 | mixed | 8.61 | 62.97 | 0.0 | 0 (0%) |
| Jan 7 | phase4 | 11.26 | 89.08 | 0.0 | 0 (0%) |
| **Jan 8** | **mixed** | **7.74** | **94.62** | **0.0** | **10 (9%)** |
| **Jan 9** | **mixed** | **8.22** | **98.54** | **0.0** | **27 (6%)** |
| **Jan 10** | **mixed** | **8.11** | **50.00** | **0.0** | **22 (8%)** |

### Observations:

1. **Feature[10] is ALWAYS 0.0** across all dates/sources - potentially a dead feature
2. **Some players have first 3 features = 0** (5-12% of records)
3. **Feature[5] values:** phase4_partial had higher values (89-96) vs mixed (50-63) before Jan 8
4. After Jan 8, **mixed source shows Feature[5] = 94-98** (similar to old phase4), but Jan 10 drops to 50
5. **Feature values are NOT null** - they have real numeric values

---

## 6. Sample Feature Inspection

### Jan 7 - phase4_partial (High Quality = 97)
```
Player: matasbuzelis
Features: [20.6, 17.7, 14.9, ..., feature[5]=78.0, ..., feature[20]=0.79, feature[30]=6.0]
Quality: 97.0
```

### Jan 7 - mixed (Low Quality = 67.6)
```
Player: hugogonzalez
Features: [4.8, 6.13, 6.12, ..., feature[5]=50.0, ..., feature[20]=0.35, feature[30]=0.0]
Quality: 67.6
```

### Jan 8 - mixed (Medium Quality = 77.2)
```
Player: tyresehaliburton
Features: [0.0, 0.0, 0.0, ..., feature[5]=95.0, ..., feature[20]=0.35, feature[30]=9.0]
Quality: 77.2
```

### Jan 9 - mixed (High Quality = 97)
```
Player: tristandasilva
Features: [8.8, 8.6, 9.8, ..., feature[5]=100.0, ..., feature[20]=0.53, feature[30]=12.0]
Quality: 97.0
```

### Key Pattern Differences:

**phase4_partial vs mixed (before Jan 8):**
- phase4: Higher feature[0-2] values, higher feature[5] (78-100), quality 89.8-97
- mixed: Lower feature[0-2] values, feature[5] = 50, quality 62.8-84.4

**mixed after Jan 8:**
- Mixed behavior: some players with zeros in first features, feature[5] = 95-100
- Quality range narrower (77.2-97 vs previous 62.8-97)
- Feature[30] has higher values (9-12 vs 0-6 in old mixed)

---

## 7. Quality Score Distribution (Jan 6-10)

### Jan 6 (Pre-transition)
- 62.8: 60 records
- 74.8: 26 records
- 84.4: 17 records
- 97.0: 81 records ← **High quality from phase4_partial**

### Jan 7 (Pre-transition)
- 74.8: 55 records
- 84.4: 27 records
- 97.0: 164 records ← **Highest count of quality=97**

### Jan 8 (Transition day)
- 77.2: 21 records ← **New minimum**
- 84.4: 94 records ← **Only two discrete values!**
- **NO 97.0 records!**

### Jan 9 (Post-transition)
- 77.2: 71 records
- 84.4: 261 records
- 97.0: 114 records ← **High quality returns**

### Jan 10 (Anomaly)
- 58.6: 13 records ← **Lowest quality ever**
- 62.8: 276 records ← **Almost all records at this quality**

---

## 8. Root Cause Analysis

### What Happened:

1. **Phase4_partial pipeline stopped** producing features on Jan 8, 2026
2. **Mixed pipeline** became the sole data source
3. **Feature quality distribution shifted:**
   - Lost the high-quality tier (phase4_partial 90-97)
   - Gained more mid-quality features (80-89)
   - Overall average quality similar, but variance reduced

### Why Model Performance Degraded:

1. **Training/Serving Skew:**
   - Models were likely trained on phase4_partial features (quality 90-97)
   - Now serving predictions with mixed features (quality 70-85)
   - Feature distributions don't match training data

2. **Loss of Critical Features:**
   - phase4_partial may have included features not available in mixed
   - Different feature generation logic between the two pipelines
   - Feature[5] pattern suggests different data sources/calculations

3. **Data Quality Issues:**
   - Jan 10 shows catastrophic quality drop (avg 62.6)
   - Suggests upstream data pipeline instability
   - Some players have zero values in critical features (first 3 features)

### Are Features Broken?

**NO - features are not broken, but they ARE different:**
- ✅ All records have 33 features
- ✅ No NULL arrays
- ✅ Features have valid numeric values
- ⚠️ Feature VALUE DISTRIBUTIONS changed
- ⚠️ Feature QUALITY changed
- ❌ phase4_partial pipeline completely stopped

---

## 9. Recommendations

### Immediate Actions (P0):

1. **Investigate phase4_partial pipeline failure:**
   - Check logs for Jan 7-8 timeframe
   - Identify why phase4_partial stopped producing features
   - Determine if this was intentional or a bug

2. **Assess Training/Serving Skew:**
   - Check what data source was used for model training
   - If trained on phase4_partial, retrain on mixed data
   - Or fix phase4_partial pipeline to restore high-quality features

3. **Investigate Jan 10 anomaly:**
   - Why did quality drop to 58.6-62.8?
   - Check upstream data sources for that date
   - Verify if data corruption occurred

### Short-term Fixes (P1):

4. **Enable Source Completeness Tracking:**
   - Fix metadata fields (source_*_completeness_pct)
   - These are all NULL but should provide quality signals
   - Would help detect future pipeline failures earlier

5. **Add Data Quality Monitoring:**
   - Alert when phase4_partial record count = 0
   - Alert when max quality < 90 (indicating loss of high-quality tier)
   - Alert when quality stddev < 5 (indicating lack of variance)
   - Alert when feature distributions shift beyond threshold

6. **Feature Engineering Analysis:**
   - Investigate Feature[10] (always 0.0) - potentially dead feature
   - Analyze why some players have first 3 features = 0
   - Compare feature importance between phase4 and mixed sources

### Long-term Improvements (P2):

7. **Pipeline Redundancy:**
   - Don't rely on single data source
   - Implement fallback logic if phase4_partial fails
   - Graceful degradation instead of silent quality loss

8. **Model Retraining Strategy:**
   - Retrain models on current mixed data distribution
   - Or restore phase4_partial and retrain on that
   - Consider ensemble of models trained on different sources

9. **Schema Documentation:**
   - Document what phase4_partial vs mixed means
   - Document feature generation logic for each source
   - Document expected quality score ranges

---

## 10. Data Quality Summary

### Jan 1-7 (Healthy Period)
- ✅ Dual data sources (phase4 + mixed)
- ✅ High quality tier available (97.0)
- ✅ 46% of records with quality 90+
- ✅ Good variance in quality (stddev 15)

### Jan 8 (Transition)
- ⚠️ phase4_partial disappeared
- ⚠️ Only 2 quality scores (77.2, 84.4)
- ⚠️ No high-quality features (max 84.4)
- ⚠️ Record count dropped 56%

### Jan 9-15 (New Normal)
- ⚠️ Only mixed data source
- ⚠️ Quality variance reduced (stddev 11.8 vs 15.1)
- ⚠️ 25% quality 90+ (vs 46% before)
- ❌ Jan 10 anomaly (quality 58.6-62.8)

---

## Conclusion

The model performance degradation starting Jan 7-8 directly correlates with the **complete loss of the phase4_partial data pipeline**. Features are not "broken" in the sense of being NULL or malformed, but they fundamentally changed in distribution and quality when the high-quality phase4_partial source stopped producing data.

The root cause is a **data pipeline failure**, not a feature engineering problem. Restoring the phase4_partial pipeline OR retraining models on the current mixed-only distribution should restore performance.

**Critical Next Step:** Determine if phase4_partial loss was intentional (pipeline deprecation) or accidental (pipeline failure). This will inform whether to restore the old pipeline or adapt to the new one.
