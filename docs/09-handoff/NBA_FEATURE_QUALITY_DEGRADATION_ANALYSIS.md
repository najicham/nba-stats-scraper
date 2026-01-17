# NBA Feature Quality Degradation Analysis
**Analysis Date:** 2026-01-16
**Table:** `nba-props-platform.nba_predictions.ml_feature_store_v2`
**Date Range:** December 20, 2025 - January 15, 2026

## Executive Summary

Analysis of the ML feature store reveals **modest quality degradation** starting January 8, 2026, with **January 10 showing the most severe drop**. However, the degradation is less severe than initially expected, with most features remaining functional.

### Key Finding: The Expected 90+ → 80-89 Drop Did NOT Occur

**The hypothesis that avg_quality drops from 90+ to 80-89 is INCORRECT.**

- **Healthy Period (Dec 20 - Jan 7):** Average quality score = **84.3** (not 90+)
- **Broken Period (Jan 8 - Jan 15):** Average quality score = **81.3** (not 80-89)
- **Actual Degradation:** Only **3 points** (84.3 → 81.3)

### Critical Anomaly: January 10, 2026

January 10 stands out as the worst day with quality score of **62.6** - a significant drop from the baseline.

---

## Query 1: Daily Feature Quality Comparison

### Overall Trends

| Period | Avg Quality | Min Quality | Max Quality | Total Records |
|--------|-------------|-------------|-------------|---------------|
| Healthy (Dec 20 - Jan 7) | 84.3 | 58.6 | 97.0 | 4,781 |
| Broken (Jan 8 - Jan 15) | 81.3 | 58.6 | 97.0 | 1,939 |

### Quality Score Distribution

**Healthy Period:**
- 90+ quality: 2,426 records (50.7%)
- 80-89 quality: 446 records (9.3%)
- 70-79 quality: 772 records (16.1%)
- 60-69 quality: 1,132 records (23.7%)
- <60 quality: 5 records (0.1%)

**Broken Period:**
- 90+ quality: 492 records (25.4%) ⬇️ **-50% shift**
- 80-89 quality: 593 records (30.6%) ⬆️ **+224% increase**
- 70-79 quality: 442 records (22.8%)
- 60-69 quality: 399 records (20.6%)
- <60 quality: 13 records (0.7%) ⬆️ **+160% increase**

### Daily Breakdown - Notable Dates

| Date | Avg Quality | Records | Notes |
|------|-------------|---------|-------|
| 2025-12-23 | **93.5** | 315 | Best day in healthy period |
| 2025-12-21 | 75.7 | 512 | Worst day in healthy period |
| 2026-01-09 | **86.2** | 456 | Best day in broken period |
| **2026-01-10** | **62.6** | 290 | **WORST DAY - Major anomaly** |
| 2026-01-08 | 83.1 | 115 | First day of broken period |

---

## Query 2: Feature Completeness Analysis

### Source Data Completeness

The feature store includes metadata about upstream data sources. Analysis reveals:

**Healthy Period:**
- All source completeness percentages: **NULL** (metadata not tracked)
- NULL count for all sources: 537 unique players

**Broken Period:**
- All source completeness percentages: **100%** (metadata now tracked!)
- NULL count for all sources: 559 unique players

**Finding:** The broken period actually has BETTER metadata tracking, with 100% completeness scores for:
- `source_daily_cache_completeness_pct`
- `source_composite_completeness_pct`
- `source_shot_zones_completeness_pct`
- `source_team_defense_completeness_pct`

### Data Quality Issues Breakdown

| Issue Type | Healthy Period | Broken Period | Change |
|------------|----------------|---------------|--------|
| upstream_player_daily_cache_incomplete | 2,247 | 1,442 | ⬇️ -36% |
| upstream_player_composite_factors_incomplete | 1,601 | 1,387 | ⬇️ -13% |
| upstream_player_shot_zone_incomplete | 1,394 | 632 | ⬇️ -55% **IMPROVED** |
| upstream_team_defense_zone_incomplete | 1,190 | 290 | ⬇️ -76% **GREATLY IMPROVED** |

**Key Insight:** Data quality issues actually DECREASED during the "broken" period, particularly for shot zone and team defense data.

---

## Query 3: Sample Player Analysis (Jan 15, 2026)

### Sample Players

**Player 1: Lindy Waters III**
- Team: vs MIL (home)
- Quality Score: 74.8 (Bronze tier)
- Days Rest: 2
- Feature Count: 33/33
- Issues: upstream_player_daily_cache_incomplete, upstream_player_composite_factors_incomplete
- Key Features:
  - Points avg (last 5): 1.8
  - Shot zones: Paint 0%, Mid 0%, Three 100%, FT 5.3%
  - Fatigue: 50.0 (neutral/default)
  - Minutes avg: 7.6

**Player 2: Jaren Jackson Jr.**
- Team: @ ORL
- Quality Score: 74.8 (Bronze tier)
- Days Rest: 4
- Feature Count: 33/33
- Issues: upstream_player_daily_cache_incomplete, upstream_player_composite_factors_incomplete
- Key Features:
  - Points avg (last 5): 20.0
  - Shot zones: Paint 0%, Mid 0%, Three 100%, FT 16.3%
  - Vegas line: 19.5 points (has_vegas_line: 1.0)
  - Minutes avg: 32.3
  - PPM: 0.647

**Player 3: Anthony Davis**
- Team: vs UTA (home)
- Quality Score: 74.8 (Bronze tier)
- Days Rest: 3
- Feature Count: 33/33
- Issues: upstream_player_daily_cache_incomplete, upstream_player_composite_factors_incomplete
- Key Features:
  - Points avg (last 5): 14.6
  - Shot zones: Paint 57.8%, Mid 26.7%, Three 15.6%, FT 14.0%
  - Fatigue: 50.0
  - Minutes avg: 30.2
  - Historical vs opponent: 21.7 points (9 games)

### Observations

1. **All three players have identical quality scores: 74.8** - suggesting systematic scoring
2. **Feature count is consistent: 33/33** - all features are being populated
3. **Shot zone data varies** - some players show realistic distributions (Anthony Davis), others show unrealistic 100% three-point shooting (Waters, Jackson)
4. **Common issues**: All players missing daily cache and composite factors
5. **All marked as production_ready: false, quality_tier: bronze**

---

## Detailed Feature Analysis

### Critical Features That Changed

#### 1. Shot Zone Mismatch Score
- **Healthy Period:** 
  - Average: 0.108
  - Non-zero values: 1,560 records (32.6%)
  - Zero values: 1,948 records (40.7%)
- **Broken Period:**
  - Average: 0.274 ⬆️ **+154% increase**
  - Non-zero values: 648 records (33.4%)
  - Zero values: 865 records (44.6%)

**Jan 10 Anomaly:** All 290 records had shot_zone_mismatch_score = 0.0

#### 2. Fatigue Score
- **Healthy Period:**
  - Average: 77.8
  - Records at exactly 50.0: 1,601 (33.5%)
  - Records with varying scores: 3,180 (66.5%)
- **Broken Period:**
  - Average: 81.3 ⬆️ **+4.5% increase**
  - Records at exactly 50.0: 638 (32.9%)
  - Records with varying scores: 1,301 (67.1%)

**Jan 10 Anomaly:** ALL 290 records had fatigue = 50.0 (100% default value)

**Jan 8-9 Healthy Pattern:** 0% records at default 50.0, all had calculated fatigue scores (avg 94.6 and 98.5)

#### 3. Pace Score & Usage Spike Score
- **Both Periods:** 100% of records have value = 0.0
- **Finding:** These features appear to be non-functional in BOTH healthy and broken periods

#### 4. Shot Zone Distribution Features

| Feature | Healthy Avg | Broken Avg | Change |
|---------|-------------|------------|--------|
| pct_paint | 32.6% | 28.3% | ⬇️ -13.4% |
| pct_mid_range | 20.3% | 15.8% | ⬇️ -22.2% |
| pct_three | 42.2% | 51.1% | ⬆️ +21.0% |
| pct_free_throw | 14.7% | 14.3% | ⬇️ -2.7% |

**Pattern:** Broken period shows shift toward three-point shooting, away from paint and mid-range.

**Reality Check:** This could reflect actual NBA trends OR data degradation causing unrealistic shot distributions (as seen in sample players).

---

## January 10 Deep Dive: The Worst Day

### Anomaly Characteristics

| Metric | Jan 10 | Healthy Avg | Difference |
|--------|--------|-------------|------------|
| Quality Score | 62.6 | 84.3 | -21.7 points |
| Fatigue at 50.0 | 100% | 33.5% | Complete default |
| Shot Zone Mismatch = 0 | 100% | 40.7% | Complete zero |
| Pace Score = 0 | 100% | 100% | Same (always broken) |
| Usage Spike = 0 | 100% | 100% | Same (always broken) |

### What Broke on Jan 10?

1. **Fatigue calculation completely failed** - all players defaulted to 50.0
2. **Shot zone mismatch calculation failed** - all values = 0.0
3. **Shot zone distributions remained reasonable** - suggesting base data was present
4. **Quality score dropped to 62.6** - reflecting these calculation failures

### Recovery Pattern

- **Jan 11:** Quality recovered to 81.9, fatigue calculations resumed (avg 97.1)
- **Jan 12-15:** Quality stabilized in 79-86 range
- **Jan 8-9:** Showed strongest performance with quality 83-86 and full fatigue calculations

---

## Specific Features That Degraded

### ✅ Features That Work Consistently

1. **Points averages** (last 5, last 10, season) - all periods
2. **Games counts** - all periods
3. **Rest advantage** - all periods
4. **Opponent data** (def rating, pace) - all periods
5. **Team data** (pace, off rating, win pct) - all periods
6. **Vegas lines** - when available
7. **Minutes and PPM** - all periods

### ⚠️ Features With Degradation

1. **shot_zone_mismatch_score**
   - Increased zero values from 41% → 45%
   - Jan 10: 100% zeros
   - Average increased (possibly spurious)

2. **fatigue_score**
   - Slightly more default values
   - Jan 10: 100% defaults
   - Jan 8-9: Excellent calculation
   - Jan 11-15: Partial defaults (11-48% of records)

3. **Shot zone percentages**
   - Some players showing unrealistic distributions (100% three-pointers)
   - Overall shift toward three-point shooting
   - May indicate upstream shot zone data quality issues

### ❌ Features That Never Work (Both Periods)

1. **pace_score** - 100% zeros in all periods
2. **usage_spike_score** - 100% zeros in all periods

### 📊 Metadata Improvements

1. **Source completeness tracking** - added in broken period
2. **Data quality issue logging** - improved in broken period
3. **Quality tier classification** - present in broken period

---

## Root Cause Analysis

### What Actually Happened?

The data does NOT support the hypothesis of a 90+ → 80-89 quality drop. Instead:

1. **Baseline was already 84.3**, not 90+
2. **Degradation was only 3 points** (84.3 → 81.3)
3. **Main issue: Quality TIER distribution changed**
   - 90+ tier records dropped from 51% to 25%
   - 80-89 tier records increased from 9% to 31%
   - This is a distribution shift, not an average catastrophe

4. **January 10 was an outlier**, not representative of the period
   - If we exclude Jan 10: Broken period avg = **83.8** (only -0.5 points!)

### Likely Causes

1. **Fatigue calculation instability**
   - Works perfectly some days (Jan 8-9)
   - Completely fails other days (Jan 10)
   - Partially fails remaining days (Jan 11-15)

2. **Shot zone mismatch calculation issues**
   - Complete failure on Jan 10
   - Increased zero rates overall
   - May be related to upstream shot zone data

3. **Data quality issue tracking improved**
   - System is now DETECTING issues better
   - May be flagging more records as lower quality
   - Doesn't mean data is worse, just better monitored

4. **Quality scoring algorithm may have changed**
   - Distribution shift suggests scoring methodology changed
   - Records that would have been 90+ are now 80-89
   - Could be intentional recalibration

---

## Conclusions

### Primary Findings

1. **Expected degradation (90+ → 80-89) did NOT occur**
   - Actual: 84.3 → 81.3 (3 points)
   - Quality distribution shifted, not average

2. **January 10 is a clear outlier requiring investigation**
   - Complete failure of fatigue and shot zone mismatch calculations
   - Quality score: 62.6 (worst in dataset)
   - 290 records affected

3. **Most features remain functional**
   - 33/33 features populated for all players
   - Core statistics (points, games, minutes) working
   - Vegas lines integrated properly

4. **Some features never worked**
   - pace_score and usage_spike_score are 100% zeros in ALL periods
   - These should be investigated or removed

5. **Monitoring improved during "broken" period**
   - Source completeness tracking added
   - Data quality issues better detected
   - May explain perceived degradation

### Recommendations

1. **Investigate January 10 specifically**
   - What caused complete failure of fatigue calculation?
   - What caused shot zone mismatch to zero out?
   - Was there an upstream data outage?

2. **Fix or remove non-functional features**
   - pace_score: Always 0.0
   - usage_spike_score: Always 0.0

3. **Stabilize fatigue calculation**
   - Works on some days (Jan 8-9: excellent)
   - Fails on others (Jan 10: complete failure)
   - Partial failures on Jan 11-15

4. **Investigate shot zone data quality**
   - Some players showing unrealistic distributions
   - Increased zero rates for shot_zone_mismatch_score
   - May need upstream data source review

5. **Review quality scoring methodology**
   - Distribution shift suggests algorithm change
   - Clarify if this was intentional recalibration
   - Document expected quality score ranges

---

## Evidence Summary

### Data Sources

- **Table:** `nba-props-platform.nba_predictions.ml_feature_store_v2`
- **Healthy Period:** Dec 20, 2025 - Jan 7, 2026 (4,781 records, 537 players)
- **Broken Period:** Jan 8-15, 2026 (1,939 records, 559 players)
- **Sample Date:** Jan 15, 2026 (3 random players analyzed)

### Quality Metrics

- Average quality degradation: **3.0 points** (84.3 → 81.3)
- Worst day: **January 10** (62.6 quality score)
- Best day in broken period: **January 9** (86.2 quality score)
- 90+ quality tier shift: **-50%** (from 51% to 25% of records)

### Feature Impact

- **Working:** 28+ features remain functional
- **Degraded:** 3 features (fatigue_score, shot_zone_mismatch_score, shot zone percentages)
- **Never worked:** 2 features (pace_score, usage_spike_score)
- **Improved:** Metadata tracking (source completeness, quality issues)

---

**Analysis Completed:** 2026-01-16
**Analyst:** Claude Code
**Next Steps:** Investigate Jan 10 outage, stabilize fatigue calculation, review quality scoring methodology
