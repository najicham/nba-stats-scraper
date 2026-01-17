# Phase4 Data Source Explanation

**Date:** 2026-01-16
**Context:** Understanding what "phase4_partial" means in ml_feature_store_v2

---

## What is Phase4?

Based on the codebase analysis, "Phase4" refers to **precomputed NBA data tables** that provide high-quality features:

### Phase4 Data Sources (4 tables in nba_precompute dataset):

1. **player_daily_cache** - Daily player statistics
   - Features 0-4: Recent performance (points avg last 5/10, season avg, std, games in last 7 days)
   - Features 18-20: Shot zones (paint rate, 3pt rate, assisted rate last 10)
   - Features 22-23: Team context (pace, offensive rating last 10)
   - Additional: minutes avg, player age

2. **player_composite_factors** - Composite player analysis
   - Features 5-8: Composite metrics

3. **player_shot_zone_analysis** - Shot zone breakdowns
   - Features 18-20: Shot zone analysis

4. **team_defense_zone_analysis** - Opponent defensive metrics
   - Features 13-14: Team defense zones

### Phase3 Data (fallback):

- **player_game_summary** (nba_analytics dataset)
- Used when Phase4 data is not available
- Lower quality score (75 vs 100)

---

## Data Source Labels

The `data_source` field in ml_feature_store_v2 is determined by **percentage of features using Phase4 data**:

```python
# From quality_scorer.py:
if phase4_pct >= 0.90:
    return 'phase4'          # >90% of features from Phase4
elif phase4_pct >= 0.50:
    return 'phase4_partial'  # 50-89% of features from Phase4
elif phase3_pct >= 0.50:
    return 'phase3'          # >50% of features from Phase3
else:
    return 'mixed'           # Mixed sources
```

### What "phase4_partial" means:

- **50-89% of the 25 features** came from Phase4 precompute tables
- **10-50% of features** came from Phase3 fallback or defaults
- Still high quality (typically 89.8-97.0 quality score)
- Indicates **partial availability** of precompute data

### What "mixed" means:

- **<50% of features from Phase4**
- More reliance on Phase3 or default values
- Lower quality scores (typically 62.8-84.4)
- Indicates **limited precompute data availability**

---

## Quality Score Calculation

```python
# From quality_scorer.py:
SOURCE_WEIGHTS = {
    'phase4': 100,      # Precompute data (best)
    'phase3': 75,       # Analytics fallback (good)
    'default': 40,      # No data available (poor)
    'calculated': 100   # Always-available calculated features (good)
}

quality_score = average(feature weights for all 25 features)
```

### Quality Score Examples:

- **phase4_partial (quality=97):** 24/25 features from phase4, 1 from calculated
  - Score = (24 × 100 + 1 × 100) / 25 = 97

- **phase4_partial (quality=89.8):** 22/25 features from phase4, 3 from phase3
  - Score = (22 × 100 + 3 × 75) / 25 = 89.8

- **mixed (quality=67.6):** 10/25 from phase4, 7 from phase3, 8 from default
  - Score = (10 × 100 + 7 × 75 + 8 × 40) / 25 = 67.6

---

## What Happened on Jan 8, 2026

### Before Jan 8:
- Phase4 precompute tables were being populated daily
- 47% of feature records had >50% phase4 data (labeled "phase4_partial")
- High quality scores (89.8-97.0) available for many players

### After Jan 8:
- Phase4 precompute tables **stopped being populated** or **stopped being queried**
- 0% of feature records had >50% phase4 data
- All records fell back to "mixed" (more phase3/default usage)
- Quality distribution shifted lower

---

## Root Cause Hypothesis

The phase4_partial data source disappeared because:

### Hypothesis 1: Phase4 Precompute Pipeline Stopped Running

**Most likely scenario:**

The daily precompute pipeline that populates these 4 tables stopped running:
- `nba_precompute.player_daily_cache`
- `nba_precompute.player_composite_factors`
- `nba_precompute.player_shot_zone_analysis`
- `nba_precompute.team_defense_zone_analysis`

**Verification queries:**

```sql
-- Check if player_daily_cache is being updated
SELECT
    cache_date,
    COUNT(DISTINCT player_lookup) as players,
    MIN(updated_at) as first_update,
    MAX(updated_at) as last_update
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date BETWEEN '2026-01-05' AND '2026-01-15'
GROUP BY cache_date
ORDER BY cache_date;

-- Check if player_composite_factors is being updated
SELECT
    game_date,
    COUNT(DISTINCT player_lookup) as players,
    MIN(updated_at) as first_update,
    MAX(updated_at) as last_update
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date BETWEEN '2026-01-05' AND '2026-01-15'
GROUP BY game_date
ORDER BY game_date;
```

### Hypothesis 2: Feature Extraction Code Changed

**Less likely but possible:**

The feature extraction code in `ml_feature_store_processor.py` changed to:
- Stop querying Phase4 tables
- Only use Phase3 fallback data
- Changed logic in `extract_phase4_data()` method

**Verification:**

```bash
# Check git history for changes to feature extraction
git log --since="2026-01-06" --until="2026-01-09" --all \
  -- "data_processors/precompute/ml_feature_store/*"

# Look for changes to phase4 extraction
git diff 2026-01-06..2026-01-09 \
  -- data_processors/precompute/ml_feature_store/feature_extractor.py
```

### Hypothesis 3: Cloud Scheduler/Orchestration Failure

**Also possible:**

The Cloud Scheduler or Airflow DAG that triggers the precompute pipeline:
- Stopped running
- Failed silently
- Was disabled/paused

**Verification:**

```bash
# Check Cloud Scheduler status
gcloud scheduler jobs list --project=nba-props-platform

# Check for specific precompute schedulers
gcloud scheduler jobs describe nba-precompute-daily --project=nba-props-platform

# Check logs for scheduler failures
gcloud logging read "
  resource.type=cloud_scheduler_job
  timestamp>='2026-01-07T00:00:00Z'
  timestamp<='2026-01-09T00:00:00Z'
  severity>=ERROR
" --project=nba-props-platform --limit=50
```

---

## Next Steps to Investigate

### 1. Check if Phase4 tables are being updated (CRITICAL)

Run the verification queries above to see if data is flowing into:
- player_daily_cache
- player_composite_factors
- player_shot_zone_analysis
- team_defense_zone_analysis

**Expected result if pipeline stopped:**
- No new rows after Jan 7, 2026
- Or rows exist but updated_at timestamps stopped advancing

### 2. Check Cloud Scheduler status

Look for disabled or failing schedulers related to:
- "precompute"
- "daily_cache"
- "composite_factors"
- "nba-phase4"

### 3. Review git history

Check for code changes to feature extraction between Jan 6-8:
```bash
git log --oneline --since="2026-01-06" --until="2026-01-09" --all
```

### 4. Check monitoring/alerting

See if any alerts fired around Jan 7-8 for:
- BigQuery table update failures
- Cloud Function errors
- Pipeline execution failures

---

## Resolution Paths

### Path A: Pipeline Stopped (Most Likely)

**If Phase4 tables are not being updated:**

1. Identify the failed pipeline/scheduler
2. Check logs for root cause of failure
3. Restart/fix the pipeline
4. Backfill missing dates (Jan 8-15)
5. Verify features return to phase4_partial quality

**Timeline:** Could restore within hours if simple restart

### Path B: Intentional Deprecation

**If Phase4 pipeline was intentionally disabled:**

1. Understand reason for deprecation
2. Retrain ML models on current "mixed" data distribution
3. Update feature quality expectations
4. Document the change

**Timeline:** 1-2 weeks for model retraining and validation

### Path C: Code Change

**If feature extraction code was modified:**

1. Review the commit that changed behavior
2. Determine if change was intentional
3. Revert or fix the code
4. Redeploy feature generation
5. Regenerate features for affected dates

**Timeline:** 1-2 days for code fix and redeployment

---

## Impact on ML Models

### Training/Serving Skew

If models were trained on data when phase4_partial was available:

**Training data (before Jan 8):**
- 47% of records with quality 90+
- Features mostly from Phase4 precompute tables
- High-quality, consistent feature distributions

**Serving data (after Jan 8):**
- 25% of records with quality 90+
- Features mostly from Phase3 fallback
- Different feature distributions (more defaults)

**Result:**
- Models see different input distributions than they were trained on
- Predictions may be less accurate
- Confidence scores may be miscalibrated

### Solution:

Either:
1. **Restore Phase4 pipeline** → serving matches training
2. **Retrain models on current data** → training matches serving

---

## Files Referenced

1. **data_processors/precompute/ml_feature_store/quality_scorer.py**
   - Defines phase4/phase3/mixed logic
   - Calculates quality scores

2. **data_processors/precompute/ml_feature_store/feature_extractor.py**
   - `extract_phase4_data()` method (line 679)
   - Queries the 4 Phase4 precompute tables

3. **data_processors/precompute/ml_feature_store/ml_feature_store_processor.py**
   - Orchestrates feature extraction
   - Calls extract_phase4_data and extract_phase3_data

---

## Summary

**Phase4** = High-quality precomputed data from 4 tables in nba_precompute
**phase4_partial** = Features using 50-89% Phase4 data (quality 89.8-97)
**mixed** = Features using <50% Phase4 data (quality 62.8-84.4)

**Problem:** Phase4 data source disappeared on Jan 8, causing all features to become "mixed" instead of "phase4_partial"

**Most likely cause:** Phase4 precompute pipeline stopped running

**Fix:** Restore the pipeline or retrain models on current data distribution
