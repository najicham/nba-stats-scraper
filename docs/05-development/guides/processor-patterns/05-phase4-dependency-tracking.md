# Pattern 05: Phase 4 Dependency Tracking

**Created:** 2025-11-21 18:05:00 PST
**Last Updated:** 2025-11-21 18:05:00 PST
**Version:** 4.0 (Streamlined)

Quick reference for Phase 4 precompute processor dependency tracking.

---

## Overview

**Purpose:** Track data quality and lineage by recording metadata about source tables.

**Philosophy:** Start simple, iterate based on real needs. Add fields later via ALTER TABLE when proven necessary.

**Scope:** Phase 4 (Precompute) processors

**Key Difference from Phase 3:** 3 fields per source (vs 4 in Phase 3 - removed `data_hash` for historical ranges)

---

## Field Structure

### Per-Source Fields (3 fields)

```sql
source_{prefix}_last_updated TIMESTAMP           -- When source last processed
source_{prefix}_rows_found INT64                 -- How many rows returned
source_{prefix}_completeness_pct NUMERIC(5,2)    -- % of expected rows found
```

### Processing Metadata (always included)

```sql
processed_at TIMESTAMP NOT NULL
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
```

### Optional Fields

```sql
early_season_flag BOOLEAN                  -- Insufficient data?
insufficient_data_reason STRING            -- Why insufficient
```

---

## Field Count Examples

| Sources | Per-Source | Optional | Metadata | Total |
|---------|-----------|----------|----------|-------|
| 1 | 3 | 2 | 2 | 7 |
| 2 | 6 | 2 | 2 | 10 |
| 3 | 9 | 2 | 2 | 13 |
| 4 | 12 | 2 | 2 | 16 |

**Typical processor (3 sources):** 13 tracking fields + ~15 business fields = ~28 total

**Reduction from v3.1:** 48% fewer fields

---

## Schema Examples

### Simple (1 Source)

```sql
CREATE TABLE `nba_precompute.team_defense_zone_analysis` (
  -- Business keys
  team_abbr STRING NOT NULL,
  analysis_date DATE NOT NULL,

  -- Business metrics
  paint_pct_allowed_last_15 NUMERIC(5,3),
  mid_range_pct_allowed_last_15 NUMERIC(5,3),
  three_pt_pct_allowed_last_15 NUMERIC(5,3),
  games_in_sample INT64,

  -- SOURCE TRACKING: 1 source = 3 fields
  source_team_defense_last_updated TIMESTAMP,
  source_team_defense_rows_found INT64,
  source_team_defense_completeness_pct NUMERIC(5,2),

  -- Optional (2 fields)
  early_season_flag BOOLEAN,
  insufficient_data_reason STRING,

  -- Processing metadata (2 fields)
  processed_at TIMESTAMP NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY analysis_date
CLUSTER BY analysis_date, team_abbr;
```

### Complex (4 Sources)

```sql
CREATE TABLE `nba_precompute.player_composite_factors` (
  -- Business keys
  player_lookup STRING NOT NULL,
  game_date DATE NOT NULL,

  -- Business metrics
  zone_matchup_advantage NUMERIC(6,3),
  volume_projection NUMERIC(5,1),
  confidence_score NUMERIC(5,3),

  -- SOURCE TRACKING: Source 1
  source_upcoming_game_last_updated TIMESTAMP,
  source_upcoming_game_rows_found INT64,
  source_upcoming_game_completeness_pct NUMERIC(5,2),

  -- SOURCE TRACKING: Source 2
  source_team_defense_last_updated TIMESTAMP,
  source_team_defense_rows_found INT64,
  source_team_defense_completeness_pct NUMERIC(5,2),

  -- SOURCE TRACKING: Source 3
  source_player_shot_last_updated TIMESTAMP,
  source_player_shot_rows_found INT64,
  source_player_shot_completeness_pct NUMERIC(5,2),

  -- SOURCE TRACKING: Source 4
  source_player_game_last_updated TIMESTAMP,
  source_player_game_rows_found INT64,
  source_player_game_completeness_pct NUMERIC(5,2),

  -- Processing metadata
  processed_at TIMESTAMP NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY game_date, player_lookup;
```

---

## Adding Fields to Existing Tables

```sql
-- Template
ALTER TABLE `{project}.{dataset}.{table_name}`
  ADD COLUMN IF NOT EXISTS source_{prefix}_last_updated TIMESTAMP,
  ADD COLUMN IF NOT EXISTS source_{prefix}_rows_found INT64,
  ADD COLUMN IF NOT EXISTS source_{prefix}_completeness_pct NUMERIC(5,2),
  ADD COLUMN IF NOT EXISTS early_season_flag BOOLEAN,
  ADD COLUMN IF NOT EXISTS insufficient_data_reason STRING;

-- Example
ALTER TABLE `nba-props-platform.nba_precompute.team_defense_zone_analysis`
  ADD COLUMN IF NOT EXISTS source_team_defense_last_updated TIMESTAMP,
  ADD COLUMN IF NOT EXISTS source_team_defense_rows_found INT64,
  ADD COLUMN IF NOT EXISTS source_team_defense_completeness_pct NUMERIC(5,2),
  ADD COLUMN IF NOT EXISTS early_season_flag BOOLEAN,
  ADD COLUMN IF NOT EXISTS insufficient_data_reason STRING;
```

---

## Dependency Configuration

### Basic (1 Source)

```python
class TeamDefenseZoneAnalysisProcessor(PrecomputeProcessorBase):

    def get_dependencies(self) -> dict:
        return {
            'nba_analytics.team_defense_game_summary': {
                'field_prefix': 'source_team_defense',
                'description': 'Team defensive stats (last 15 games)',
                'check_type': 'per_team_game_count',

                # Requirements
                'min_games_required': 15,
                'min_teams_with_data': 25,
                'entity_field': 'defending_team_abbr',

                # Freshness thresholds
                'max_age_hours_warn': 72,
                'max_age_hours_fail': 168,

                # Early season
                'early_season_days': 14,
                'early_season_behavior': 'WRITE_PLACEHOLDER',

                'critical': True
            }
        }
```

### Multiple Sources

```python
class PlayerCompositeFactorsProcessor(PrecomputeProcessorBase):

    def get_dependencies(self) -> dict:
        return {
            'nba_analytics.upcoming_player_game_context': {
                'field_prefix': 'source_upcoming_game',
                'check_type': 'date_match',
                'expected_count_min': 100,
                'max_age_hours_warn': 12,
                'max_age_hours_fail': 48,
                'critical': True
            },
            'nba_precompute.team_defense_zone_analysis': {
                'field_prefix': 'source_team_defense',
                'check_type': 'date_match',
                'expected_count_min': 30,
                'max_age_hours_warn': 6,
                'max_age_hours_fail': 24,
                'critical': True
            },
            'nba_precompute.player_shot_zone_analysis': {
                'field_prefix': 'source_player_shot',
                'check_type': 'date_match',
                'expected_count_min': 100,
                'max_age_hours_warn': 6,
                'max_age_hours_fail': 24,
                'critical': True
            },
            'nba_analytics.player_game_summary': {
                'field_prefix': 'source_player_game',
                'check_type': 'lookback_days',
                'lookback_days': 30,
                'expected_count_min': 1000,
                'max_age_hours_warn': 24,
                'max_age_hours_fail': 72,
                'critical': False
            }
        }
```

---

## Base Class Implementation

### track_source_usage()

```python
def track_source_usage(self, dep_check: dict) -> None:
    """Populate source tracking attributes from dependency check."""

    for table_name, dep_result in dep_check['details'].items():
        config = self.get_dependencies()[table_name]
        prefix = config['field_prefix']

        if not dep_result.get('exists', False):
            # Source missing - NULL for all fields
            setattr(self, f'{prefix}_last_updated', None)
            setattr(self, f'{prefix}_rows_found', None)
            setattr(self, f'{prefix}_completeness_pct', None)
            continue

        # Store raw values
        setattr(self, f'{prefix}_last_updated', dep_result.get('last_updated'))
        setattr(self, f'{prefix}_rows_found', dep_result.get('row_count', 0))

        # Calculate completeness
        rows_found = dep_result.get('row_count', 0)
        rows_expected = self._calculate_expected_count(config, dep_result)

        if rows_expected > 0:
            completeness_pct = (rows_found / rows_expected) * 100
            completeness_pct = min(completeness_pct, 100.0)  # Cap at 100%
        else:
            completeness_pct = 100.0

        setattr(self, f'{prefix}_completeness_pct', round(completeness_pct, 2))
```

### _calculate_expected_count()

```python
def _calculate_expected_count(self, config: dict, dep_result: dict) -> int:
    """Calculate expected row count based on check_type."""

    check_type = config['check_type']

    if check_type == 'per_team_game_count':
        teams_active = dep_result.get('teams_found', 30)
        return config['min_games_required'] * teams_active

    elif check_type == 'date_match':
        return config.get('expected_count_min', 1)

    elif check_type == 'lookback_days':
        return config.get('expected_count_min', 1)

    elif check_type == 'existence':
        return config.get('expected_count_min', 1)

    else:
        raise ValueError(f"Unknown check_type: {check_type}")
```

### build_source_tracking_fields()

```python
def build_source_tracking_fields(self) -> dict:
    """Build dict of all source tracking fields for output records."""

    fields = {}

    # Per-source fields
    for table_name, config in self.get_dependencies().items():
        prefix = config['field_prefix']
        fields[f'{prefix}_last_updated'] = getattr(self, f'{prefix}_last_updated', None)
        fields[f'{prefix}_rows_found'] = getattr(self, f'{prefix}_rows_found', None)
        fields[f'{prefix}_completeness_pct'] = getattr(self, f'{prefix}_completeness_pct', None)

    # Optional early season fields
    if hasattr(self, 'early_season_flag'):
        fields['early_season_flag'] = self.early_season_flag
        if self.early_season_flag:
            fields['insufficient_data_reason'] = getattr(self, 'insufficient_data_reason', None)

    return fields
```

---

## Complete Example

```python
class TeamDefenseZoneAnalysisProcessor(PrecomputeProcessorBase):
    """Aggregate team defensive performance by court zone."""

    def __init__(self):
        super().__init__()
        self.table_name = 'team_defense_zone_analysis'
        self.entity_type = 'team'
        self.entity_field = 'team_abbr'
        self.min_games_required = 15

    def get_dependencies(self) -> dict:
        return {
            'nba_analytics.team_defense_game_summary': {
                'field_prefix': 'source_team_defense',
                'description': 'Team defensive stats (last 15 games)',
                'check_type': 'per_team_game_count',
                'min_games_required': 15,
                'min_teams_with_data': 25,
                'entity_field': 'defending_team_abbr',
                'max_age_hours_warn': 72,
                'max_age_hours_fail': 168,
                'early_season_days': 14,
                'early_season_behavior': 'WRITE_PLACEHOLDER',
                'critical': True
            }
        }

    def extract_raw_data(self) -> None:
        """Extract with dependency checking."""

        # Check dependencies
        dep_check = self.check_dependencies(self.opts['analysis_date'])

        # Early season handling
        if dep_check.get('is_early_season'):
            self._write_placeholder_rows(dep_check)
            return

        # Handle failures
        if not dep_check['all_critical_present']:
            raise DependencyError(f"Missing: {dep_check['missing']}")

        if dep_check.get('has_stale_fail'):
            raise DataTooStaleError(f"Stale: {dep_check['stale_fail']}")

        # Extract data
        query = f"""
        WITH ranked_games AS (
            SELECT *,
              ROW_NUMBER() OVER (
                PARTITION BY defending_team_abbr
                ORDER BY game_date DESC
              ) as game_rank
            FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
            WHERE game_date <= '{self.opts['analysis_date']}'
              AND game_date >= '{self.season_start_date}'
        )
        SELECT * FROM ranked_games WHERE game_rank <= 15
        """

        self.raw_data = self.bq_client.query(query).to_dataframe()
        self.track_source_usage(dep_check)
        logger.info(f"Extracted {len(self.raw_data)} game records")

    def calculate_precompute(self) -> None:
        """Calculate metrics with source tracking."""

        successful = []
        failed = []

        for team_abbr in self.raw_data['defending_team_abbr'].unique():
            try:
                team_data = self.raw_data[self.raw_data['defending_team_abbr'] == team_abbr]

                if len(team_data) < self.min_games_required:
                    failed.append({
                        'entity_id': team_abbr,
                        'reason': f"Only {len(team_data)} games, need {self.min_games_required}",
                        'category': 'INSUFFICIENT_DATA',
                        'can_retry': True
                    })
                    continue

                # Calculate zone defense metrics
                paint_pct = team_data['opp_paint_makes'].sum() / team_data['opp_paint_attempts'].sum()
                mid_pct = team_data['opp_mid_range_makes'].sum() / team_data['opp_mid_range_attempts'].sum()
                three_pct = team_data['opp_three_pt_makes'].sum() / team_data['opp_three_pt_attempts'].sum()

                # Build record with source tracking
                record = {
                    'team_abbr': team_abbr,
                    'analysis_date': self.opts['analysis_date'].isoformat(),
                    'paint_pct_allowed_last_15': float(paint_pct),
                    'mid_range_pct_allowed_last_15': float(mid_pct),
                    'three_pt_pct_allowed_last_15': float(three_pct),
                    'games_in_sample': int(len(team_data)),

                    # Source tracking (one line!)
                    **self.build_source_tracking_fields(),

                    'processed_at': datetime.utcnow().isoformat()
                }

                successful.append(record)

            except Exception as e:
                logger.error(f"Failed to process {team_abbr}: {e}")
                failed.append({
                    'entity_id': team_abbr,
                    'reason': str(e),
                    'category': 'PROCESSING_ERROR',
                    'can_retry': False
                })

        self.transformed_data = successful
        self.failed_entities = failed
```

---

## Query Patterns

### Check Freshness

```sql
-- How old is each source?
SELECT
  analysis_date,
  team_abbr,
  TIMESTAMP_DIFF(
    CURRENT_TIMESTAMP(),
    source_team_defense_last_updated,
    HOUR
  ) as source_age_hours,
  source_team_defense_completeness_pct
FROM team_defense_zone_analysis
WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND TIMESTAMP_DIFF(
    CURRENT_TIMESTAMP(),
    source_team_defense_last_updated,
    HOUR
  ) > 72
ORDER BY source_age_hours DESC;
```

### Check Completeness

```sql
-- Overall data quality
SELECT
  analysis_date,
  AVG(source_team_defense_completeness_pct) as avg_completeness,
  MIN(source_team_defense_completeness_pct) as min_completeness,
  COUNT(*) as teams
FROM team_defense_zone_analysis
WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY analysis_date
HAVING MIN(source_team_defense_completeness_pct) < 85
ORDER BY analysis_date DESC;
```

### Multi-Source Health Check

```sql
-- Find bottleneck source
SELECT
  analysis_date,
  player_lookup,

  -- Worst completeness
  LEAST(
    source_upcoming_game_completeness_pct,
    source_team_defense_completeness_pct,
    source_player_shot_completeness_pct
  ) as worst_source_completeness,

  -- Stalest source
  GREATEST(
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_upcoming_game_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_defense_last_updated, HOUR),
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_player_shot_last_updated, HOUR)
  ) as stalest_source_hours,

  -- Problem source
  CASE
    WHEN source_upcoming_game_completeness_pct < 85 THEN 'upcoming_game'
    WHEN source_team_defense_completeness_pct < 85 THEN 'team_defense'
    WHEN source_player_shot_completeness_pct < 85 THEN 'player_shot'
    ELSE 'all_good'
  END as problem_source

FROM player_composite_factors
WHERE analysis_date = CURRENT_DATE()
  AND LEAST(
    source_upcoming_game_completeness_pct,
    source_team_defense_completeness_pct,
    source_player_shot_completeness_pct
  ) < 85;
```

---

## Design Decisions

### What We Kept

✅ **3 core fields per source:**
- `last_updated` - Can't recalculate later
- `rows_found` - Can't recalculate, essential for NULL vs 0 debugging
- `completeness_pct` - Key metric

✅ **MERGE-only strategy** - Simpler queries, less storage

✅ **Base class helpers** - `track_source_usage()`, `build_source_tracking_fields()`

### What We Dropped

❌ **data_hash field** - Not useful for historical ranges (Phase 4 uses sliding windows)

❌ **rows_expected field** - Can calculate on-demand from config

❌ **processing_age_hours field** - Can calculate: `TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), last_updated, HOUR)`

❌ **Summary fields** - Easy to calculate with `AVG()`, `MIN()`, `MAX()` in queries

---

## Future Enhancements

Can add later via simple ALTER TABLE:

**Processing Age Field:**
```sql
ALTER TABLE ... ADD COLUMN source_{prefix}_processing_age_hours NUMERIC(6,2);
```

**Rows Expected Field:**
```sql
ALTER TABLE ... ADD COLUMN source_{prefix}_rows_expected INT64;
```

**Summary Fields:**
```sql
ALTER TABLE ...
  ADD COLUMN data_completeness_avg_pct NUMERIC(5,2),
  ADD COLUMN data_completeness_min_pct NUMERIC(5,2),
  ADD COLUMN upstream_processing_age_avg_hours NUMERIC(6,2),
  ADD COLUMN upstream_processing_age_max_hours NUMERIC(6,2);
```

---

## Field Semantics

**last_updated:**
- Type: TIMESTAMP
- Meaning: When source processor last ran
- NULL means: Source doesn't exist
- Use for: Calculating freshness/age

**rows_found:**
- Type: INT64
- Meaning: Rows returned from query
- NULL means: Source doesn't exist
- 0 means: Source exists but query returned nothing
- Use for: Debugging availability

**completeness_pct:**
- Type: NUMERIC(5,2)
- Meaning: `(rows_found / rows_expected) × 100`
- NULL means: Source doesn't exist
- 0.0 means: Source exists, found 0% of expected data
- 100.0 means: Found all expected data
- Use for: Primary quality metric

---

## Related Patterns

- [Pattern 02: Dependency Tracking (Phase 3)](./02-dependency-tracking.md) - Analytics version with 4 fields
- [Pattern 04: Smart Reprocessing](./04-smart-reprocessing.md) - Uses dependency data

---

## Summary

Phase 4 dependency tracking provides:
- ✅ 3 tracking fields per source (48% reduction from Phase 3)
- ✅ Complete debugging visibility
- ✅ Clean queries (MERGE-only)
- ✅ Easy iteration (add fields later)

**Philosophy:** Start simple, iterate based on real needs.
