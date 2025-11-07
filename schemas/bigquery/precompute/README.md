# Phase 4: Precompute

**Dataset:** `nba_precompute`  
**Purpose:** Pre-computed aggregations and composite factors for prediction optimization  
**Retention:** 90 days for most tables, 365 days for analysis tables  
**Update Schedule:** Nightly (11 PM - 12:15 AM) + real-time when context changes

## Overview

Phase 4 precompute tables contain pre-calculated data that speeds up predictions and prevents redundant calculations. These tables are the bridge between raw analytics (Phase 3) and predictions (Phase 5).

**Key Concepts:**
- **Composite Factors:** Pre-calculated adjustment scores (fatigue, shot zone, referee, etc.)
- **Player Cache:** Static daily data that won't change when betting lines move
- **Shot Zone Analysis:** Player tendencies and opponent defensive performance by court zone
- **ML Feature Generation:** 25-feature vectors for prediction systems
- **Performance Optimization:** Reduces prediction time from 3-5 seconds to <1 second

## Tables

### Tables in This Dataset (`nba_precompute`)

1. **player_shot_zone_analysis** - Player offensive shot distribution by zone
2. **team_defense_zone_analysis** - Team defensive performance by zone
3. **player_composite_factors** - Pre-calculated adjustment scores ⭐ CRITICAL
4. **player_daily_cache** - Static daily data for performance
5. **similarity_match_cache** - Pre-calculated similarity matches (OPTIONAL)

### Cross-Dataset Table (Written by Phase 4, Stored in Predictions Dataset)

6. **ml_feature_store_v2** ⚠️ SPECIAL CASE
   - **Physical Location:** `nba_predictions.ml_feature_store_v2`
   - **Schema Location:** `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`
   - **Written By:** Phase 4 Precompute Processor (5th processor, runs 12:00 AM)
   - **Read By:** Phase 5 Prediction Systems (all 5 systems)
   - **Purpose:** Caches 25-feature vectors generated nightly
   - **Why Different Dataset?** Tightly coupled with Phase 5 prediction tables

> **Note:** ml_feature_store_v2 is managed by Phase 4 processors but stored in the 
> predictions dataset for Phase 5 consumption. See the Phase 5 README for schema details.

---

## Table Details

### 1. player_shot_zone_analysis
**Purpose:** Player's offensive shot distribution and efficiency by court zone  
**Updated:** Nightly after games complete  
**Used By:** Shot zone mismatch calculations, player reports

**Key Fields:**
- `paint_rate_last_10` - Percentage of shots taken in the paint
- `paint_pct_last_10` - Field goal percentage in the paint
- `mid_range_rate_last_10` - Percentage of mid-range shots
- `three_pt_rate_last_10` - Percentage of three-point attempts
- `primary_scoring_zone` - Player's preferred scoring area

**Sample Query:**
```sql
-- Get paint-dominant players
SELECT 
  player_lookup,
  paint_rate_last_10,
  paint_pct_last_10,
  primary_scoring_zone
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND paint_rate_last_10 >= 45
ORDER BY paint_rate_last_10 DESC;
```

---

### 2. team_defense_zone_analysis
**Purpose:** Team defensive performance by shot zone  
**Updated:** Nightly after games complete  
**Used By:** Shot zone mismatch calculations, opponent analysis

**Key Fields:**
- `paint_pct_allowed_last_15` - FG% allowed in paint (last 15 games)
- `paint_defense_vs_league_avg` - How defense compares to league average
- `weakest_zone` - Team's weakest defensive area
- `strongest_zone` - Team's strongest defensive area

**Sample Query:**
```sql
-- Find teams with weak interior defense
SELECT 
  team_abbr,
  paint_pct_allowed_last_15,
  paint_defense_vs_league_avg,
  weakest_zone
FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
WHERE analysis_date = CURRENT_DATE()
  AND paint_pct_allowed_last_15 >= 58  -- League avg ~55%
ORDER BY paint_pct_allowed_last_15 DESC;
```

---

### 3. player_composite_factors ⭐ CRITICAL TABLE
**Purpose:** Pre-calculated composite scores for all adjustment factors  
**Updated:** Nightly (6 AM) + real-time when context changes  
**Used By:** ALL prediction systems for calculating adjustments

**This is the heart of the prediction adjustments system.**

**Key Fields:**
- **Composite Scores:**
  - `fatigue_score` (0-100, higher = more rested)
  - `shot_zone_mismatch_score` (-10 to +10)
  - `referee_favorability_score` (-5 to +5)
  - `look_ahead_pressure_score` (-5 to +5)
  - And 4 more scores...

- **Point Adjustments:**
  - `fatigue_adjustment` (expected points impact)
  - `shot_zone_adjustment` (expected points impact)
  - Each score converts to actual point impact
  
- **Supporting Details (JSON):**
  - `fatigue_factors` - Breakdown of what contributed to score
  - `shot_zone_matchup` - Detailed matchup analysis
  - `referee_details`, `look_ahead_details`, etc.

**Sample Query:**
```sql
-- Get players with extreme fatigue today
SELECT 
  player_lookup,
  game_id,
  fatigue_score,
  fatigue_adjustment,
  JSON_EXTRACT_SCALAR(fatigue_factors, '$.games_in_last_7_days') as games_7d,
  JSON_EXTRACT_SCALAR(fatigue_factors, '$.minutes_in_last_7_days') as mins_7d
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = CURRENT_DATE()
  AND fatigue_score < 40  -- Extreme fatigue
ORDER BY fatigue_score ASC;
```

**Usage in Predictions:**
```python
# Load composite factors
factors = load_composite_factors(player, game_date)

# Apply to baseline prediction
adjustment = (
    factors.fatigue_adjustment * 0.25 +
    factors.shot_zone_adjustment * 0.20 +
    factors.referee_adjustment * 0.15 +
    # ... other factors
)

final_prediction = baseline + adjustment
```

---

### 4. player_daily_cache
**Purpose:** Player data that won't change throughout the day  
**Updated:** Once daily at 6 AM  
**Used By:** Fast prediction updates when betting lines change

**Performance Optimization:** When a betting line changes from 26.5 to 27.0, you need to regenerate the report. But shot zone preferences, fatigue metrics, and recent form don't change. This cache prevents recalculating static data.

**Key Fields:**
- Shot zone data (cached from `player_shot_zone_analysis`)
- Fatigue metrics (won't change during day)
- Recent form (won't change during day)
- Player characteristics
- `similarity_candidates` - Pre-filtered list of ~100-200 games for similarity matching

**Performance Impact:**
- Without cache: 3-5 seconds per prediction
- With cache: 0.5-1 second per prediction
- **5x speed improvement** for line changes

**Sample Query:**
```sql
-- Get cached data for today's players
SELECT 
  player_lookup,
  paint_rate_last_10,
  games_in_last_7_days,
  points_avg_last_5,
  similarity_candidates_count
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = CURRENT_DATE();
```

---

### 5. similarity_match_cache (OPTIONAL)
**Purpose:** Pre-calculated similarity matches for performance boost  
**Created:** Only if similarity queries take >2 seconds  
**Updated:** Nightly

**When to Create:** Test similarity matching performance first. If queries are fast enough (<2 seconds), you don't need this table. Only create if you need the extra speed.

**Key Fields:**
- `similar_game_ids` - Array of similar game IDs with similarity scores
- `weighted_avg_points` - Pre-calculated baseline prediction
- `avg_similarity_score` - Quality of matches

---

### 6. ml_feature_store_v2 ⚠️ CROSS-DATASET TABLE

**Physical Location:** `nba_predictions.ml_feature_store_v2`  
**Schema File:** `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`  
**Written By:** Phase 4 Precompute Processor (5th processor)  
**Read By:** Phase 5 Prediction Systems

**Purpose:** Caches 25-feature vectors for all prediction systems to use

**Processing Schedule:**
- **12:00 AM (Nightly):** Phase 4 processor generates features
- **6:00 AM (Daily):** Phase 5 systems read cached features
- **9 AM - 7 PM (Real-time):** Phase 5 re-reads same cached features when lines change

**Key Concept:** Features are computed ONCE per night and reused ~2,250 times:
- 450 players × 5 prediction systems = 2,250 predictions
- All using the same cached 25 features per player

**Key Fields:**
- `features` - ARRAY<FLOAT64> with 25 elements (can expand to 47+)
- `feature_names` - ARRAY<STRING> describing each feature
- `feature_version` - 'v1_baseline_25' (version control)
- `feature_quality_score` - 0-100 quality metric
- `data_source` - 'phase4' (confirms Phase 4 generated it)

**Why in Different Dataset?**
- Stored in `nba_predictions` because it's tightly coupled with prediction tables
- Works with `feature_versions` table (also in predictions dataset)
- Exclusively used by prediction systems (not general precompute)

**Sample Query:**
```sql
-- Get cached features for today's players
SELECT 
  player_lookup,
  game_date,
  features,  -- Array of 25 floats
  feature_version,
  feature_quality_score,
  data_source
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE()
  AND feature_version = 'v1_baseline_25'
ORDER BY player_lookup;
```

**Data Flow:**
```
Phase 3 Analytics + Phase 4 Precompute (Tables 1-4)
         ↓
   [12:00 AM - Feature Generation]
         ↓
ml_feature_store_v2 (450 players × 25 features)
         ↓
   [6:00 AM - Phase 5 Reads]
         ↓
All 5 Prediction Systems (same cached features)
```

---

## Helper Views

### todays_composite_factors
Quick view of today's composite factors with alert flags

### shot_zone_mismatches
Shows favorable and unfavorable matchups (score >= 2)

### fatigue_alerts
Players with concerning fatigue levels (score < 65)

---

## Deployment

### Initial Setup

```bash
# Navigate to precompute directory
cd schemas/bigquery/precompute/

# Create dataset (if not exists)
bq mk --dataset \
  --description="Phase 4 precompute aggregations" \
  --default_table_expiration=7776000 \
  nba-props-platform:nba_precompute

# Deploy tables
bq query --use_legacy_sql=false < precompute_tables.sql

# Deploy ml_feature_store_v2 (different dataset)
cd ../predictions/
bq query --use_legacy_sql=false < 04_ml_feature_store_v2.sql

# Verify
bq ls nba_precompute
bq ls nba_predictions | grep ml_feature_store_v2
```

### Updating Schemas

```bash
# If you modify a table schema, drop and recreate
bq rm -t nba_precompute.player_composite_factors
bq query --use_legacy_sql=false < precompute_tables.sql

# For ml_feature_store_v2
bq rm -t nba_predictions.ml_feature_store_v2
cd schemas/bigquery/predictions/
bq query --use_legacy_sql=false < 04_ml_feature_store_v2.sql
```

---

## Data Processors

Processors that populate these tables are located in:
```
data_processors/precompute/
├── team_defense/
│   └── team_defense_zone_analysis_processor.py
├── player_shot_zone/
│   └── player_shot_zone_analysis_processor.py
├── player_composite_factors/
│   └── player_composite_factors_processor.py
├── player_daily_cache/
│   └── player_daily_cache_processor.py
├── ml_feature_store/
│   └── ml_feature_store_processor.py  ✨ NEW (5th processor)
└── similarity_cache/
    └── similarity_cache_builder.py (optional)
```

### Processor Schedule

**Nightly (11:00 PM - 12:15 AM):**
1. `team_defense_zone_analysis` (11:00 PM, ~5 min)
2. `player_shot_zone_analysis` (11:15 PM, ~8 min)
3. `player_composite_factors` (11:30 PM, ~10 min)
4. `player_daily_cache` (11:45 PM, ~5 min)
5. `ml_feature_store_v2` (12:00 AM, ~10 min) ✨ NEW

**Morning (6:00 AM - 7:00 AM):**
- Phase 5 predictions read from cached tables (no Phase 4 work)

**Real-Time (9 AM - Game Time):**
- Update `player_composite_factors` when context changes (injury reports, lineup changes)
- `ml_feature_store_v2` NOT updated (features cached from midnight)

---

## Data Flow

```
Phase 3 Analytics (Raw Performance)
         ↓
   [Nightly Processing 11 PM]
         ↓
player_shot_zone_analysis  +  team_defense_zone_analysis
         ↓
   [11:30 PM - 12 AM]
         ↓
player_composite_factors  +  player_daily_cache
         ↓
   [12:00 AM - 12:15 AM]
         ↓
ml_feature_store_v2 (stored in nba_predictions dataset)
         ↓
   [6 AM - Phase 5 Predictions]
         ↓
All 5 prediction systems read cached features
```

---

## Regeneration

All precompute tables can be regenerated from Phase 3 analytics if needed:

```sql
-- Example: Regenerate shot zone analysis for date range
CALL regenerate_shot_zone_analysis('2024-10-01', '2024-10-31');

-- Regenerate composite factors
CALL regenerate_composite_factors('2024-10-15');

-- Regenerate ml_feature_store_v2 for a specific date
CALL regenerate_ml_features('2024-10-15');
```

See `data_processors/precompute/regeneration/` for scripts.

---

## Monitoring

### Key Metrics to Track

```sql
-- Check data freshness (all Phase 4 tables)
SELECT 
  'player_shot_zone_analysis' as table_name,
  MAX(analysis_date) as latest_date,
  COUNT(*) as total_rows
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

UNION ALL

SELECT 
  'player_composite_factors' as table_name,
  MAX(game_date) as latest_date,
  COUNT(*) as total_rows
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

UNION ALL

SELECT 
  'ml_feature_store_v2' as table_name,
  MAX(game_date) as latest_date,
  COUNT(*) as total_rows
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY);
```

### Alerts to Configure

- ⚠️ **No data for today** - Precompute failed
- ⚠️ **Data >24 hours old** - Processing delay
- ⚠️ **High % of NULL values** - Data quality issue
- ⚠️ **Extreme composite scores** - Calculation error
- ⚠️ **ml_feature_store_v2 missing** - Feature generation failed (blocks Phase 5)

---

## Troubleshooting

### Issue: Missing composite factors for today's games
```sql
-- Check what's missing
SELECT upg.player_lookup, upg.game_id
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context` upg
LEFT JOIN `nba-props-platform.nba_precompute.player_composite_factors` pcf
  ON upg.player_lookup = pcf.player_lookup
  AND upg.game_date = pcf.game_date
WHERE upg.game_date = CURRENT_DATE()
  AND pcf.player_lookup IS NULL;
```

**Solution:** Run `composite_factors_calculator.py` manually

### Issue: Missing ml_feature_store_v2 for today
```sql
-- Check if features generated
SELECT 
  COUNT(DISTINCT player_lookup) as players_with_features
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
-- Expect: ~450 players
```

**Solution:** Run `ml_feature_store_processor.py` manually

**Impact:** Phase 5 CANNOT run without features - this is CRITICAL

### Issue: Stale daily cache
```sql
-- Check cache age
SELECT 
  cache_date,
  COUNT(*) as players_cached
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY cache_date
ORDER BY cache_date DESC;
```

**Solution:** Cache expires automatically. Rebuild runs at 6 AM daily.

### Issue: High variance in shot zone percentages
Indicates small sample sizes. Check `games_in_sample_10` field.

---

## Performance Tips

1. **Partition Pruning:** Always filter by date fields (analysis_date, game_date, cache_date)
2. **Clustering:** Queries filtering by player_lookup are optimized
3. **Cache Usage:** Use `player_daily_cache` for line changes instead of recalculating
4. **JSON Extraction:** Index frequently accessed JSON fields if performance issues
5. **Cross-Dataset Queries:** When joining ml_feature_store_v2 with precompute tables, be explicit about dataset

---

## Related Documentation

- **Phase 5 Predictions README:** Consumer of Phase 4 data (especially ml_feature_store_v2)
- **Document 3:** Composite Factor Calculations - Detailed calculation formulas
- **Document 2:** Similarity Matching Engine - How similarity candidates are used
- **Document 5:** Phase 4 Precompute Schema - Complete table definitions
- **Phase 3 Analytics README:** Source data for precompute tables
- **Feature Store Architecture Decision:** Why ml_feature_store_v2 is in predictions dataset

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2025-01-19 | 1.0 | Initial Phase 4 precompute documentation |
| 2025-11-05 | 1.1 | Added ml_feature_store_v2 cross-reference |

---

## Questions or Issues?

- Check processor logs: `logs/precompute/`
- View data quality dashboard: Cloud Monitoring
- Review calculation logic: `data_processors/precompute/`
- Contact: NBA Props Analytics Team