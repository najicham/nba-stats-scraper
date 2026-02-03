# CRITICAL: Data Pipeline Bug - 40% of Player Data Corrupted

**Date:** 2026-02-03
**Priority:** P0 - BLOCKING MODEL TRAINING
**Status:** IDENTIFIED, NEEDS FIX

## Summary

35-45% of player boxscore data in `nba_raw.bdl_player_boxscores` is corrupted with 0 points and "00" minutes. This includes major star players like:
- Jayson Tatum
- Bradley Beal
- Chris Paul
- Fred VanVleet
- Damian Lillard
- Kyrie Irving

## Impact

| Layer | Impact |
|-------|--------|
| Raw (bdl_player_boxscores) | 40% records have points=0, minutes='00' |
| Analytics (player_game_summary) | 40% records have NULL points, is_dnp=true |
| Feature Store | 40% records have 0.0 for points_avg_l5/l10/season |
| Model Training | Model learning from corrupted features |

## Evidence

### BDL Raw Data
```sql
SELECT game_date, COUNT(*), COUNTIF(points = 0 AND minutes = '00') as zero_all
FROM nba_raw.bdl_player_boxscores
WHERE game_date >= '2026-01-15'
GROUP BY 1 ORDER BY 1 DESC
```
Result: 37-45% of records have corrupted data

### Player Game Summary
Stars like Tatum have `points = NULL, is_dnp = true` for games they clearly played.

### Feature Store
```sql
SELECT player_lookup, AVG(features[OFFSET(2)]) as avg_pts_season
FROM nba_predictions.ml_feature_store_v2
WHERE player_lookup IN ('jaysontatum', 'damianlillard', 'kyrieirving')
  AND game_date >= '2026-01-01'
GROUP BY 1
```
Result: All show 0.0 for season averages

## Root Cause (Investigation Needed)

The BDL (Ball Don't Lie) API scraper is returning 0 points and "00" minutes for many players. Possible causes:
1. API rate limiting/blocking
2. API schema change
3. Scraper bug introduced recently
4. Players being incorrectly flagged as DNP

## Immediate Actions Needed

1. **Stop model training** until data is fixed
2. **Investigate BDL scraper** - check logs, API responses
3. **Cross-validate with other sources** - ESPN, Basketball Reference
4. **Backfill corrupted data** once source is fixed

## Training Data Quality

Until fixed, model training must:
- Filter out records with `feature_quality_score < 70`
- Filter out records where `features[OFFSET(0)] = 0` (zero points_avg_l5)
- Use `/spot-check-features` to validate before training

## Files to Investigate

| File | Purpose |
|------|---------|
| `scrapers/bdl/` | BDL API scraper code |
| `data_processors/analytics/player_game_summary/` | Where NULL points come from |
| `data_processors/precompute/ml_feature_store/` | Where 0.0 features come from |

## Temporary Workaround

For model training, add filter:
```python
# Filter out corrupted data
df = df[df['features'].apply(lambda x: x[0] > 0)]  # points_avg_l5 > 0
```
