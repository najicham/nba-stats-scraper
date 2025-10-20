# Phase 4: Precompute

**Dataset:** `nba_precompute`  
**Purpose:** Pre-computed aggregations and composite factors for prediction optimization  
**Retention:** 90 days for most tables, 365 days for analysis tables  
**Update Schedule:** Nightly (11 PM - 6 AM) + real-time when context changes

## Overview

Phase 4 precompute tables contain pre-calculated data that speeds up predictions and prevents redundant calculations. These tables are the bridge between raw analytics (Phase 3) and predictions (Phase 5).

**Key Concepts:**
- **Composite Factors:** Pre-calculated adjustment scores (fatigue, shot zone, referee, etc.)
- **Player Cache:** Static daily data that won't change when betting lines move
- **Shot Zone Analysis:** Player tendencies and opponent defensive performance by court zone
- **Performance Optimization:** Reduces prediction time from 3-5 seconds to <1 second

## Tables

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

# Verify
bq ls nba_precompute
```

### Updating Schemas

```bash
# If you modify a table schema, drop and recreate
bq rm -t nba_precompute.player_composite_factors
bq query --use_legacy_sql=false < precompute_tables.sql
```

---

## Data Processors

Processors that populate these tables are located in:
```
data_processors/precompute/
├── shot_zone_analyzer.py
├── defense_zone_analyzer.py
├── composite_factors_calculator.py
├── daily_cache_builder.py
└── similarity_cache_builder.py (optional)
```

### Processor Schedule

**Nightly (11 PM - 2 AM):**
1. Process completed games from Phase 3
2. Update `player_shot_zone_analysis` 
3. Update `team_defense_zone_analysis`

**Morning (6 AM - 7 AM):**
4. Calculate `player_composite_factors` for today's games
5. Build `player_daily_cache` for today's games
6. (Optional) Build `similarity_match_cache`

**Real-Time (9 AM - Game Time):**
7. Update `player_composite_factors` when context changes (injury reports, lineup changes)

---

## Data Flow

```
Phase 3 Analytics (Raw Performance)
         ↓
   [Nightly Processing]
         ↓
player_shot_zone_analysis  +  team_defense_zone_analysis
         ↓
   [Morning Processing]
         ↓
player_composite_factors  +  player_daily_cache
         ↓
   [Used by Phase 5 Predictions]
```

---

## Regeneration

All precompute tables can be regenerated from Phase 3 analytics if needed:

```sql
-- Example: Regenerate shot zone analysis for date range
CALL regenerate_shot_zone_analysis('2024-10-01', '2024-10-31');

-- Regenerate composite factors
CALL regenerate_composite_factors('2024-10-15');
```

See `data_processors/precompute/regeneration/` for scripts.

---

## Monitoring

### Key Metrics to Track

```sql
-- Check data freshness
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
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY);
```

### Alerts to Configure

- ⚠️ **No data for today** - Precompute failed
- ⚠️ **Data >24 hours old** - Processing delay
- ⚠️ **High % of NULL values** - Data quality issue
- ⚠️ **Extreme composite scores** - Calculation error

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

---

## Related Documentation

- **Document 3:** Composite Factor Calculations - Detailed calculation formulas
- **Document 2:** Similarity Matching Engine - How similarity candidates are used
- **Document 5:** Phase 4 Precompute Schema - Complete table definitions
- **Phase 3 Analytics README:** Source data for precompute tables

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2025-01-19 | 1.0 | Initial Phase 4 precompute documentation |

---

## Questions or Issues?

- Check processor logs: `logs/precompute/`
- View data quality dashboard: Cloud Monitoring
- Review calculation logic: `data_processors/precompute/`
- Contact: NBA Props Analytics Team
