# Validation System Documentation

**Last Updated:** 2026-01-25
**Purpose:** Document validation chains and data quality checks

## Shot Zones Chain (Updated 2026-01-25)

### Data Flow

```
BigDataBall PBP (Primary)
  ├─> Quality: Gold (94% coverage)
  ├─> Fields: paint/mid-range/three + assisted/unassisted + blocks
  └─> Fallback on failure ↓

NBAC PBP (Fallback)
  ├─> Quality: Silver (100% coverage)
  ├─> Fields: Basic zones only
  └─> Fallback on failure ↓

NULL with Indicator
  ├─> Quality: Bronze
  ├─> has_shot_zone_data = 0.0
  └─> ML handles missingness
```

### Quality Impact

- **Gold (BigDataBall):** +15 points
- **Silver (NBAC):** +10 points  
- **Bronze (NULL):** +0 points, uses missingness indicator

### ML Handling

- Features 18-20 (shot zones): **NULLABLE**
- Feature 33: `has_shot_zone_data` indicator (1.0 = complete, 0.0 = missing)
- CatBoost uses tree splits to handle NaN optimally

### Validation Queries

**Check completeness:**
```sql
SELECT
    COUNT(*) as total,
    COUNTIF(has_shot_zone_data = 1.0) as with_zones,
    ROUND(100.0 * COUNTIF(has_shot_zone_data = 1.0) / COUNT(*), 1) as pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE()
```

**Expected:** ≥80% completeness  
**Alert if:** <70%

**Source distribution:**
```sql
SELECT
    source_shot_zones_source,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM `nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE()
GROUP BY source_shot_zones_source
```

**Expected:**
- bigdataball_pbp: 90-95%
- nbac_play_by_play: 5-10%
- NULL: <1%

## Related Documentation

- [Shot Zone Failures Runbook](../02-operations/runbooks/shot-zone-failures.md)
- [ML Feature Catalog](../05-ml/features/feature-catalog.md)
- [Shot Zone Handling Improvements](../09-handoff/IMPROVE-SHOT-ZONE-HANDLING.md)

