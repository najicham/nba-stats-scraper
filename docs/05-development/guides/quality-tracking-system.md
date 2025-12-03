# Quality Tracking System Developer Guide

This guide covers the NBA Props Platform's quality tracking system, including data source fallback logic, quality column standardization, and production readiness determination.

## Overview

The quality tracking system ensures:
1. **Graceful fallback** when primary data sources are unavailable
2. **Consistent quality tracking** across all Phase 3+ tables
3. **Production readiness gating** to prevent low-quality data from affecting predictions

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     CONFIGURATION LAYER                              │
├─────────────────────────────────────────────────────────────────────┤
│  shared/config/source_coverage/__init__.py  ← Tier definitions      │
│  shared/config/data_sources/fallback_config.yaml  ← Fallback chains │
│  shared/config/data_sources/loader.py  ← Config accessor            │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        MIXIN LAYER                                   │
├─────────────────────────────────────────────────────────────────────┤
│  shared/processors/patterns/quality_columns.py  ← Column builders   │
│  shared/processors/patterns/fallback_source_mixin.py  ← Fallback    │
│  shared/processors/patterns/quality_mixin.py  ← Quality assessment  │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       PROCESSOR LAYER                                │
│  Phase 3+ processors inherit mixins and output quality columns      │
└─────────────────────────────────────────────────────────────────────┘
```

## Quality Tiers

| Tier | Score Range | Confidence Ceiling | Production Eligible |
|------|-------------|-------------------|---------------------|
| gold | 95-100 | 1.00 | Yes |
| silver | 75-94 | 0.95 | Yes |
| bronze | 50-74 | 0.80 | Yes |
| poor | 25-49 | 0.60 | No |
| unusable | 0-24 | 0.00 | No |

## Standard Quality Columns

All Phase 3+ tables should have these columns:

| Column | Type | Description |
|--------|------|-------------|
| `quality_tier` | STRING | 'gold', 'silver', 'bronze', 'poor', 'unusable' |
| `quality_score` | FLOAT64 | Numeric score 0-100 |
| `quality_issues` | ARRAY<STRING> | List of detected issues |
| `is_production_ready` | BOOL | Safe for predictions? |
| `data_sources` | ARRAY<STRING> | Which sources contributed (optional) |

### Legacy Columns (Deprecated)

During migration, these legacy columns are also populated:
- `data_quality_tier` → Use `quality_tier` instead
- `data_quality_issues` → Use `quality_issues` instead

## Using the Quality System

### Basic Usage in Processors

```python
from shared.processors.patterns.fallback_source_mixin import FallbackSourceMixin
from shared.processors.patterns.quality_mixin import QualityMixin
from shared.processors.patterns.quality_columns import build_quality_columns_with_legacy


class MyProcessor(FallbackSourceMixin, QualityMixin, AnalyticsProcessorBase):

    def extract_raw_data(self):
        # Use fallback chain for data extraction
        result = self.try_fallback_chain(
            chain_name='team_boxscores',
            extractors={
                'nbac_team_boxscore': lambda: self._query_primary(),
                'reconstructed_team_from_players': lambda: self._reconstruct(),
            },
            context={'game_date': start_date},
        )

        if result.should_skip:
            self.raw_data = []
            return

        self.raw_data = result.data

        # Store quality for later use
        self._fallback_quality_tier = result.quality_tier
        self._fallback_quality_score = result.quality_score
        self._fallback_quality_issues = result.quality_issues
        self._source_used = result.source_used

    def calculate_analytics(self):
        for row in self.raw_data.iterrows():
            # Build quality columns
            quality_columns = build_quality_columns_with_legacy(
                tier=self._fallback_quality_tier,
                score=self._fallback_quality_score,
                issues=self._fallback_quality_issues,
                sources=[self._source_used],
            )

            record = {
                # ... your fields ...
                **quality_columns,  # Spreads all quality columns
            }
```

### Using the Column Builder Directly

```python
from shared.processors.patterns.quality_columns import (
    build_standard_quality_columns,
    build_quality_columns_with_legacy,
    build_completeness_columns,
    determine_production_ready,
)

# Standard columns only
cols = build_standard_quality_columns(
    tier='silver',
    score=85.0,
    issues=['backup_source_used'],
    sources=['bdl_player_boxscores'],
)
# Returns: {'quality_tier': 'silver', 'quality_score': 85.0, ...}

# With legacy columns for backward compatibility
cols = build_quality_columns_with_legacy(
    tier='silver',
    score=85.0,
    issues=['backup_source_used'],
    sources=['bdl_player_boxscores'],
)
# Also includes: {'data_quality_tier': 'silver', 'data_quality_issues': [...]}

# Completeness columns (Phase 4 only)
completeness = build_completeness_columns(expected=10, actual=7)
# Returns: {'expected_games_count': 10, 'actual_games_count': 7, ...}

# Check production readiness
is_ready = determine_production_ready('silver', 85.0, ['backup_source_used'])
# Returns: True
```

## Fallback Chain Configuration

Fallback chains are defined in `shared/config/data_sources/fallback_config.yaml`:

```yaml
fallback_chains:
  team_boxscores:
    description: "Team game statistics"
    phase: 3
    consumers:
      - TeamDefenseGameSummaryProcessor
      - TeamOffenseGameSummaryProcessor
    sources:
      - nbac_team_boxscore           # Primary (gold, 100)
      - reconstructed_team_from_players  # Fallback 1 (silver, 85)
      - espn_team_boxscore           # Fallback 2 (silver, 80)
    on_all_fail:
      action: placeholder
      quality_tier: unusable
      quality_score: 0
      severity: critical
      message: "No team boxscore data available"
```

### on_all_fail Actions

| Action | Behavior | Use Case |
|--------|----------|----------|
| `skip` | Don't process entity, continue to next | Player without props |
| `placeholder` | Create record with unusable quality | Track that we tried |
| `fail` | Raise exception | Critical data (schedule) |
| `continue_without` | Process with degraded quality | Optional data (shot zones) |

## Production Readiness Logic

Data is considered production ready when ALL of these are true:
1. Tier is gold, silver, or bronze (not poor/unusable)
2. Score is >= 50.0
3. No blocking issues present

### Blocking Issues

These issues make data NOT production ready:
- `all_sources_failed` - No data source returned data
- `missing_required` - Required fields are missing
- `placeholder_created` - Record is a placeholder, not real data

### Non-Blocking Issues

These issues are warnings but don't block production:
- `backup_source_used` - Fallback source was used
- `reconstructed` - Data was reconstructed from other sources
- `thin_sample:3/10` - Sample size is thin but acceptable
- `stale_data` - Data is older than ideal
- `shot_zones_unavailable` - Optional enhancement missing

## Quality Issue Constants

Use these constants for consistency:

```python
from shared.processors.patterns.quality_columns import (
    ISSUE_BACKUP_SOURCE_USED,      # 'backup_source_used'
    ISSUE_RECONSTRUCTED,           # 'reconstructed'
    ISSUE_ALL_SOURCES_FAILED,      # 'all_sources_failed'
    ISSUE_PLACEHOLDER_CREATED,     # 'placeholder_created'
    ISSUE_MISSING_REQUIRED,        # 'missing_required'
    ISSUE_THIN_SAMPLE,             # 'thin_sample'
    ISSUE_HIGH_NULL_RATE,          # 'high_null_rate'
    ISSUE_STALE_DATA,              # 'stale_data'
    ISSUE_EARLY_SEASON,            # 'early_season'
    format_issue_with_detail,      # Helper: 'thin_sample:3/10'
)
```

## Sample Size Tracking (Phase 3 Analytics)

When calculating rolling averages (e.g., `points_avg_last_5`, `points_avg_last_10`), track how many games were actually used. This enables downstream processors to filter or weight data based on sample reliability.

### Implementation Pattern

```python
def _calculate_performance_metrics(self, historical_data: pd.DataFrame) -> Dict:
    """Calculate rolling averages with sample size tracking."""
    last_5 = historical_data.head(5)
    last_10 = historical_data.head(10)

    l5_games_used = len(last_5)
    l10_games_used = len(last_10)

    return {
        'points_avg_last_5': round(last_5['points'].mean(), 1) if l5_games_used > 0 else None,
        'points_avg_last_10': round(last_10['points'].mean(), 1) if l10_games_used > 0 else None,
        'l5_games_used': l5_games_used,
        'l5_sample_quality': self._determine_sample_quality(l5_games_used, 5),
        'l10_games_used': l10_games_used,
        'l10_sample_quality': self._determine_sample_quality(l10_games_used, 10),
    }

def _determine_sample_quality(self, games_count: int, target_window: int) -> str:
    """
    Assess sample quality relative to target window.

    Returns: 'excellent', 'good', 'limited', or 'insufficient'
    """
    if games_count >= target_window:
        return 'excellent'
    elif games_count >= int(target_window * 0.7):
        return 'good'
    elif games_count >= int(target_window * 0.5):
        return 'limited'
    else:
        return 'insufficient'
```

### Sample Quality Thresholds

| Quality | Threshold | L5 Example | L10 Example |
|---------|-----------|------------|-------------|
| excellent | >= 100% | 5 games | 10 games |
| good | >= 70% | 4 games | 7 games |
| limited | >= 50% | 3 games | 5 games |
| insufficient | < 50% | 0-2 games | 0-4 games |

### Where Sample Size Tracking is Used

- `upcoming_player_game_context`: `l5_games_used`, `l5_sample_quality`, `l10_games_used`, `l10_sample_quality`
- `player_shot_zone_analysis`: `games_in_sample_10`, `sample_quality_10`, `games_in_sample_20`, `sample_quality_20`

## Completeness Tracking (Phase 3-4)

Phase 3-4 tables that aggregate multiple games should include completeness columns:

```python
from shared.processors.patterns.quality_columns import build_completeness_columns

# When building a 10-game rolling average
completeness = build_completeness_columns(expected=10, actual=7)

record = {
    # ... your fields ...
    **completeness,
}
# Adds: expected_games_count=10, actual_games_count=7,
#       completeness_percentage=70.0, missing_games_count=3
```

## Testing

Run quality system tests:

```bash
pytest tests/test_quality_system.py -v
```

Tests verify:
- YAML/Python config consistency
- Quality column builders
- Production readiness logic
- Fallback chain configuration

## Migration Notes

### From Old Columns to New

| Old Column | New Column |
|------------|------------|
| `data_quality_tier` | `quality_tier` |
| `data_quality_issues` | `quality_issues` |
| N/A | `quality_score` |
| N/A | `is_production_ready` |

### Migration Timeline

1. **Phase 1 (now)**: Both old and new columns populated
2. **Phase 2 (2 weeks)**: Update downstream consumers
3. **Phase 3 (1 month)**: Stop populating old columns
4. **Phase 4 (3 months)**: Drop old columns

## Related Files

- `shared/config/data_sources/fallback_config.yaml` - Fallback chain definitions
- `shared/config/data_sources/loader.py` - Config accessor
- `shared/config/source_coverage/__init__.py` - Tier enums and thresholds
- `shared/processors/patterns/quality_columns.py` - Column builders
- `shared/processors/patterns/fallback_source_mixin.py` - Fallback logic
- `shared/processors/patterns/quality_mixin.py` - Quality assessment
- `tests/test_quality_system.py` - Quality system tests
