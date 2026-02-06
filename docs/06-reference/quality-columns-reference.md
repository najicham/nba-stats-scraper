# Quality Columns Reference

Quick reference for the standardized quality tracking columns across NBA Props Platform tables.

## Standard Columns (All Phase 3+ Tables)

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `quality_tier` | STRING | Yes | Quality tier: 'gold', 'silver', 'bronze', 'poor', 'unusable' |
| `quality_score` | FLOAT64 | Yes | Numeric quality score 0-100 |
| `quality_issues` | ARRAY<STRING> | Yes | List of issues detected during processing |
| `is_production_ready` | BOOL | Yes | Whether data can be used for predictions |
| `data_sources` | ARRAY<STRING> | Optional | List of data sources that contributed |

## Sample Size Columns (Phase 3 Analytics)

These columns track how many games were actually used in rolling average calculations, enabling downstream processors to assess data reliability.

| Column | Type | Description |
|--------|------|-------------|
| `l5_games_used` | INT64 | Number of games used in last-5 average (0-5) |
| `l5_sample_quality` | STRING | Sample quality: 'excellent', 'good', 'limited', 'insufficient' |
| `l10_games_used` | INT64 | Number of games used in last-10 average (0-10) |
| `l10_sample_quality` | STRING | Sample quality assessment |

### Sample Quality Thresholds

| Quality | Threshold | Example (L5) | Example (L10) |
|---------|-----------|--------------|---------------|
| excellent | >= 100% of target | 5 games | 10 games |
| good | >= 70% of target | 4 games | 7 games |
| limited | >= 50% of target | 3 games | 5 games |
| insufficient | < 50% of target | 0-2 games | 0-4 games |

### Tables with Sample Size Columns

| Table | Has sample size columns |
|-------|------------------------|
| upcoming_player_game_context | Yes |
| player_shot_zone_analysis | Yes (games_in_sample_10, games_in_sample_20) |

## Completeness Columns (Phase 3-4)

| Column | Type | Description |
|--------|------|-------------|
| `expected_games_count` | INT64 | Expected games in lookback window |
| `actual_games_count` | INT64 | Actual games found |
| `completeness_percentage` | FLOAT64 | Percentage complete (0-100) |
| `missing_games_count` | INT64 | Number of missing games |
| `l5_completeness_pct` | FLOAT64 | Last 5 games completeness percentage |
| `l5_is_complete` | BOOL | Whether L5 window is fully complete |
| `l10_completeness_pct` | FLOAT64 | Last 10 games completeness percentage |
| `l10_is_complete` | BOOL | Whether L10 window is fully complete |

## Quality Tiers

| Tier | Score Range | Confidence Ceiling | Production Eligible |
|------|-------------|-------------------|---------------------|
| gold | 95-100 | 1.00 (100%) | Yes |
| silver | 75-94 | 0.95 (95%) | Yes |
| bronze | 50-74 | 0.80 (80%) | Yes |
| poor | 25-49 | 0.60 (60%) | **No** |
| unusable | 0-24 | 0.00 (0%) | **No** |

## Standard Quality Issues

### Blocking Issues (Prevent Production Readiness)

| Issue | Description |
|-------|-------------|
| `all_sources_failed` | No data source returned valid data |
| `missing_required` | Required fields are missing |
| `placeholder_created` | Record is a placeholder, not real data |

### Warning Issues (Don't Block Production)

| Issue | Description |
|-------|-------------|
| `backup_source_used` | Fallback data source was used |
| `reconstructed` | Data was reconstructed from other sources |
| `thin_sample:N/M` | Sample size thin (N of M expected) |
| `high_null_rate:X%` | High null rate in column |
| `stale_data` | Data is older than ideal |
| `early_season` | Early season, limited history |
| `shot_zones_unavailable` | Optional shot zone data missing |
| `missing_defensive_actions` | Optional defensive stats missing |

## Production Ready Logic

```
is_production_ready = (
    quality_tier IN ('gold', 'silver', 'bronze') AND
    quality_score >= 50.0 AND
    NOT ANY(issue IN ['all_sources_failed', 'missing_required', 'placeholder_created'])
)
```

## Tables with Quality Columns

### Phase 3 Analytics

| Table | Has quality_tier | Has quality_score | Has is_production_ready |
|-------|-----------------|-------------------|------------------------|
| player_game_summary | Yes | Yes | Yes |
| team_defense_game_summary | Yes | Yes | Yes |
| team_offense_game_summary | Yes | Yes | Yes |
| upcoming_player_game_context | Yes | Yes | Yes |
| upcoming_team_game_context | Yes | Yes | Yes |

### Phase 4 Precompute

| Table | Has quality_tier | Has quality_score | Has completeness |
|-------|-----------------|-------------------|------------------|
| player_daily_cache | Yes | Yes | No |
| player_shot_zone_analysis | Yes* | No | No |
| team_defense_zone_analysis | Yes* | No | No |
| ml_feature_store_v2 | Yes | Yes** | No |

*Uses `data_quality_tier` (legacy)
**Uses `feature_quality_score`

### Phase 5 Predictions

| Table | Has quality_tier | Has is_production_ready |
|-------|-----------------|------------------------|
| player_prop_predictions | No | Yes |
| current_ml_predictions | Yes* | No |

*Uses `data_quality_tier` (legacy)

## Prediction Timing Columns (Session 139)

| Column | Type | Table | Description |
|--------|------|-------|-------------|
| `prediction_made_before_game` | BOOL | `player_prop_predictions` | Whether the prediction was generated before the game start time |
| `is_quality_ready` | BOOL | `ml_feature_store_v2` | Whether feature quality meets the hard floor for prediction generation |

The `prediction_made_before_game` field enables accurate grading by distinguishing pre-game predictions (made with uncertain data) from backfill predictions (made after game results are known). Only pre-game predictions should be used for hit rate and ROI calculations.

The `is_quality_ready` field is set by the quality gate system (Session 139) and indicates whether a player's feature row passes the minimum quality thresholds required for prediction generation.

## Legacy Columns (Deprecated)

These columns are still populated for backward compatibility but should not be used in new code:

| Legacy Column | Use Instead |
|--------------|-------------|
| `data_quality_tier` | `quality_tier` |
| `data_quality_issues` | `quality_issues` |

## BigQuery Queries

### Check Quality Distribution

```sql
SELECT
  quality_tier,
  COUNT(*) as record_count,
  AVG(quality_score) as avg_score,
  COUNTIF(is_production_ready) as production_ready
FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY quality_tier
ORDER BY
  CASE quality_tier
    WHEN 'gold' THEN 1
    WHEN 'silver' THEN 2
    WHEN 'bronze' THEN 3
    WHEN 'poor' THEN 4
    WHEN 'unusable' THEN 5
  END
```

### Find Non-Production-Ready Records

```sql
SELECT
  game_date,
  game_id,
  quality_tier,
  quality_score,
  quality_issues,
  is_production_ready
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE NOT is_production_ready
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY game_date DESC
```

### Check Issue Frequency

```sql
SELECT
  issue,
  COUNT(*) as occurrences
FROM `nba-props-platform.nba_analytics.player_game_summary`,
  UNNEST(quality_issues) as issue
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY issue
ORDER BY occurrences DESC
```

## Code Reference

```python
# Import quality column helpers
from shared.processors.patterns.quality_columns import (
    build_standard_quality_columns,
    build_quality_columns_with_legacy,
    build_completeness_columns,
    determine_production_ready,
    ISSUE_BACKUP_SOURCE_USED,
    ISSUE_RECONSTRUCTED,
)

# Build columns
cols = build_quality_columns_with_legacy(
    tier='silver',
    score=85.0,
    issues=['backup_source_used'],
    sources=['bdl_player_boxscores'],
)
```

See `docs/05-development/guides/quality-tracking-system.md` for detailed usage.
