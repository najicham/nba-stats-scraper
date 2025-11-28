# NBA Props Platform - Source Coverage System Design
## Part 2: Schema Reference

**Created:** 2025-11-26
**Parent Document:** [Part 1: Core Design & Architecture](01-core-design.md)

---

## Table of Contents

1. [Schema Overview](#schema-overview)
2. [Primary Table: source_coverage_log](#primary-table-source_coverage_log)
3. [Standard Quality Columns](#standard-quality-columns)
4. [Game Summary View](#game-summary-view)
5. [Event Type Reference](#event-type-reference)
6. [Partitioning & Clustering](#partitioning--clustering)
7. [Migration Scripts](#migration-scripts)

---

## Schema Overview

### Database Organization

```
nba_reference (reference data)
+-- source_coverage_log          [NEW] Event log for all coverage events
+-- game_source_coverage_summary [NEW] View for game-level queries
+-- (existing reference tables...)

nba_analytics (Phase 3)
+-- player_game_summary          [MODIFIED] Add quality columns
+-- team_offense_game_summary    [MODIFIED] Add quality columns
+-- team_defense_game_summary    [MODIFIED] Add quality columns
+-- upcoming_team_game_context   [MODIFIED] Add quality columns
+-- upcoming_player_game_context [MODIFIED] Add quality columns

nba_precompute (Phase 4)
+-- player_daily_cache           [MODIFIED] Add quality columns
+-- player_shot_zone_analysis    [MODIFIED] Add quality columns
+-- team_defense_zone_analysis   [MODIFIED] Add quality columns
+-- player_composite_factors     [MODIFIED] Add quality columns

nba_predictions (Phase 5)
+-- ml_feature_store_v2          [MODIFIED] Add quality columns
+-- player_prop_predictions      [MODIFIED] Add quality columns
```

### Schema Design Principles

1. **Append-only event log** - Never UPDATE events, only INSERT
2. **Partitioned by date** - Efficient time-range queries
3. **Clustered by common filters** - Severity, type, resolution status
4. **Standard quality columns** - Same schema across all tables
5. **Views for convenience** - Derive state from events

---

## Primary Table: source_coverage_log

### Full DDL

```sql
-- ============================================================================
-- SOURCE COVERAGE LOG
-- ============================================================================
-- Purpose: Comprehensive audit log of all source coverage events
-- Grain: One row per event (game, player, or field-level)
-- Volume: Normal: ~50 game-level events/day
--         Source outage: ~500+ player-level events (15 games × 26 players)
--         Use batch_id to group related events from same processor run
-- Retention: 2 years (auto-expire via partition_expiration_days)
-- ============================================================================

CREATE TABLE IF NOT EXISTS nba_reference.source_coverage_log (

  -- ==========================================================================
  -- IDENTITY & CLASSIFICATION
  -- ==========================================================================
  event_id STRING NOT NULL,
    -- UUID for this event, PRIMARY KEY
    -- Format: '550e8400-e29b-41d4-a716-446655440000'

  batch_id STRING,
    -- Groups related events from same processor run
    -- Example: All 26 player fallback events from one game share a batch_id
    -- Enables: "1 batch affected 26 players" vs "26 separate alerts"
    -- Format: '{processor_name}_{game_id}_{timestamp}'

  event_timestamp TIMESTAMP NOT NULL,
    -- When event occurred (UTC)
    -- Used for partitioning

  event_type STRING NOT NULL,
    -- Type of coverage event (see SourceCoverageEventType enum)
    -- Examples: 'source_missing', 'fallback_used', 'reconstruction'

  severity STRING NOT NULL,
    -- Impact severity (see SourceCoverageSeverity enum)
    -- Values: 'critical', 'warning', 'info'

  is_synthetic BOOL DEFAULT FALSE,
    -- TRUE if created by audit job (not by processor directly)
    -- Indicates silent failure detection

  -- ==========================================================================
  -- LOCATION & CONTEXT
  -- ==========================================================================
  phase STRING,
    -- Which pipeline phase: 'phase_2', 'phase_3', 'phase_4', 'phase_5'

  table_name STRING,
    -- Affected table: 'nba_analytics.player_game_summary'

  processor_name STRING,
    -- Processor that logged event: 'player_game_summary'

  -- Entity identifiers (nullable - not all events have all identifiers)
  game_id STRING,
    -- NBA game ID: '0022400001'

  game_date DATE,
    -- Date of game (used for partitioning queries)

  season STRING,
    -- Season: '2024-25'

  player_id STRING,
    -- universal_player_id for player-level events

  team_abbr STRING,
    -- Team abbreviation: 'LAL'

  -- ==========================================================================
  -- EVENT DETAILS
  -- ==========================================================================
  description STRING,
    -- Human-readable description
    -- Example: "Primary source NBA.com unavailable, used ESPN fallback"

  -- Source information
  primary_source STRING,
    -- What source was expected: 'nbac_team_boxscore'

  primary_source_status STRING,
    -- Status of primary: 'missing', 'partial', 'timeout', 'error'

  fallback_sources_tried ARRAY<STRING>,
    -- Which fallbacks attempted: ['espn_team_boxscore', 'bdl_box_scores']

  -- Resolution
  resolution STRING,
    -- How event was resolved: 'used_fallback', 'reconstructed', 'skipped', 'failed'

  resolution_details STRING,
    -- Additional resolution context
    -- Example: "Reconstructed team totals from 10/10 player boxscores"

  -- ==========================================================================
  -- QUALITY IMPACT
  -- ==========================================================================
  quality_tier_before STRING,
    -- Quality tier before this event: 'gold'

  quality_tier_after STRING,
    -- Quality tier after this event: 'silver'
    -- Shows degradation: gold -> silver due to fallback

  quality_score_before FLOAT64,
    -- Numeric score before: 100.0

  quality_score_after FLOAT64,
    -- Numeric score after: 85.0

  downstream_impact STRING,
    -- Impact description: 'predictions_degraded', 'features_partial', 'predictions_blocked'

  -- ==========================================================================
  -- ALERT TRACKING
  -- ==========================================================================
  requires_alert BOOL,
    -- Should this event trigger an alert?
    -- TRUE for severity='critical' or first-time warnings

  alert_sent BOOL,
    -- Has alert been sent?

  alert_channel STRING,
    -- Where alert sent: 'slack', 'email', 'both'

  alert_sent_at TIMESTAMP,
    -- When alert was sent

  -- ==========================================================================
  -- RESOLUTION TRACKING
  -- ==========================================================================
  is_resolved BOOL DEFAULT FALSE,
    -- Has the underlying issue been fixed?
    -- Example: Backfill completed, source recovered

  resolved_at TIMESTAMP,
    -- When issue was resolved

  resolution_method STRING,
    -- How resolved: 'backfill', 'source_recovered', 'manual_entry', 'accepted_gap'

  resolved_by STRING,
    -- Who/what resolved: 'system', 'manual', or username

  -- ==========================================================================
  -- METADATA
  -- ==========================================================================
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    -- When row inserted

  processor_run_id STRING,
    -- Link to processor execution (for debugging)

  environment STRING
    -- Environment: 'prod', 'dev', 'test'

)
PARTITION BY DATE(event_timestamp)
CLUSTER BY severity, event_type, game_id
OPTIONS(
  description = "Audit log of all source coverage events - gaps, fallbacks, reconstructions",
  partition_expiration_days = 730,  -- 2 years
  require_partition_filter = true   -- Force partition filtering for cost control
);
```

**Note:** BigQuery does not support `CREATE INDEX` statements. Use partitioning and clustering instead.

---

## Standard Quality Columns

### Column Definitions

Every Phase 3+ table should have these columns:

```sql
-- ============================================================================
-- STANDARD QUALITY COLUMNS
-- ============================================================================
-- Add to every table in: nba_analytics.*, nba_precompute.*, nba_predictions.*
-- ============================================================================

-- Core quality fields (always present)
quality_tier STRING,
  -- Categorical quality level: 'gold', 'silver', 'bronze', 'poor', 'unusable'

quality_score FLOAT64,
  -- Numeric quality score: 0-100

quality_issues ARRAY<STRING>,
  -- Specific problems detected
  -- Format: 'prefix:detail' (e.g., 'thin_sample:3/10', 'missing_optional:plus_minus')
  -- Standard prefixes: thin_sample, missing_required, missing_optional,
  --   high_null_rate, backup_source_used, reconstructed, early_season, stale_data

data_sources ARRAY<STRING>,
  -- Which sources were used for this row
  -- Examples: ['primary'], ['espn_backup'], ['reconstructed']

-- Commonly-queried fields (extracted from metadata for query performance)
-- IMPORTANT: These avoid slow JSON queries like:
--   WHERE CAST(JSON_VALUE(quality_metadata, '$.sample_size') AS INT64) < 5
quality_sample_size INT64,
  -- Number of games in sample (for rolling calculations)
  -- Enables: WHERE quality_sample_size >= 5 (much cheaper than JSON query)

quality_used_fallback BOOL DEFAULT FALSE,
  -- TRUE if any fallback source was used
  -- Enables: WHERE quality_used_fallback = FALSE for primary-only data

quality_reconstructed BOOL DEFAULT FALSE,
  -- TRUE if data was reconstructed/derived
  -- Enables: WHERE quality_reconstructed = FALSE for original data

quality_calculated_at TIMESTAMP,
  -- When quality was assessed/calculated
  -- CRITICAL for detecting stale quality after upstream backfills
  -- If upstream Phase 3 data is backfilled, downstream Phase 4 quality becomes stale
  -- Use this to identify rows needing quality recalculation

-- Flexible metadata (for less common queries)
quality_metadata JSON
  -- Additional context not commonly queried
  -- Examples:
  -- {"expected_sample": 10, "games_missing": [2, 5]}
  -- {"reconstruction_method": "sum_from_players", "player_count": 10}
  -- {"fallback_reason": "primary_timeout", "latency_ms": 30000}
```

**Query Performance Note:** Querying `WHERE quality_sample_size < 5` is much cheaper than
`WHERE CAST(JSON_VALUE(quality_metadata, '$.sample_size') AS INT64) < 5`.

### Example: Adding to Existing Table

```sql
-- ============================================================================
-- EXAMPLE: Add quality columns to player_game_summary
-- ============================================================================

ALTER TABLE nba_analytics.player_game_summary
ADD COLUMN IF NOT EXISTS quality_tier STRING,
ADD COLUMN IF NOT EXISTS quality_score FLOAT64,
ADD COLUMN IF NOT EXISTS quality_issues ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS data_sources ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS quality_sample_size INT64,
ADD COLUMN IF NOT EXISTS quality_used_fallback BOOL,
ADD COLUMN IF NOT EXISTS quality_reconstructed BOOL,
ADD COLUMN IF NOT EXISTS quality_calculated_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS quality_metadata JSON;

-- Backfill existing rows with CONSERVATIVE defaults
-- IMPORTANT: We can't know the true quality of historical data,
-- so we default to 'silver' rather than falsely claiming 'gold'
UPDATE nba_analytics.player_game_summary
SET
  quality_tier = 'silver',  -- Conservative: unknown historical quality
  quality_score = 80.0,
  quality_issues = ['historical_data'],
  data_sources = ['unknown'],
  quality_sample_size = NULL,  -- Unknown
  quality_used_fallback = NULL,  -- Unknown
  quality_reconstructed = NULL,  -- Unknown
  quality_calculated_at = CURRENT_TIMESTAMP(),
  quality_metadata = JSON '{"backfilled": true, "backfill_date": "2025-11-26", "note": "Conservative default for historical data"}'
WHERE quality_tier IS NULL;
```

### Quality Column Usage Patterns

**Filtering by quality:**
```sql
-- High quality only
SELECT * FROM player_game_summary
WHERE quality_tier IN ('gold', 'silver')
  AND quality_score >= 80;

-- Exclude unusable
SELECT * FROM player_game_summary
WHERE quality_tier != 'unusable';
```

**Quality-weighted aggregations:**
```sql
-- Weight by quality score
SELECT
  player_id,
  AVG(points * quality_score / 100.0) as quality_weighted_avg_points
FROM player_game_summary
WHERE game_date >= '2024-12-01'
GROUP BY player_id;
```

---

## Game Summary View

### View DDL

```sql
-- ============================================================================
-- GAME SOURCE COVERAGE SUMMARY VIEW
-- ============================================================================
-- Purpose: Convenient game-level summary of source coverage
-- Method: Aggregates events from source_coverage_log
-- Performance: Views are computed on query (no materialization)
-- ============================================================================

CREATE OR REPLACE VIEW nba_reference.game_source_coverage_summary AS

SELECT
  -- Game identification
  game_id,
  game_date,
  season,

  -- Event summary
  ARRAY_AGG(DISTINCT event_type IGNORE NULLS) as event_types,
  COUNT(*) as total_events,
  COUNT(DISTINCT player_id) as players_affected,

  -- Audit flags
  LOGICAL_OR(is_synthetic) as has_synthetic_events,

  -- Severity tracking
  MAX(
    CASE severity
      WHEN 'critical' THEN 4
      WHEN 'warning' THEN 3
      WHEN 'info' THEN 2
      ELSE 1
    END
  ) as worst_severity_rank,

  MAX(severity) as worst_severity,
  COUNTIF(severity = 'critical') as critical_event_count,
  COUNTIF(severity = 'warning') as warning_event_count,
  COUNTIF(severity = 'info') as info_event_count,

  -- Resolution status
  LOGICAL_OR(NOT is_resolved) as has_unresolved_issues,
  COUNTIF(NOT is_resolved AND severity = 'critical') as unresolved_critical_count,

  -- Quality summary
  MIN(quality_score_after) as min_quality_score,
  MAX(quality_score_after) as max_quality_score,
  AVG(quality_score_after) as avg_quality_score,

  -- Overall tier (worst tier wins)
  CASE
    WHEN LOGICAL_OR(quality_tier_after = 'unusable') THEN 'unusable'
    WHEN LOGICAL_OR(quality_tier_after = 'poor') THEN 'poor'
    WHEN LOGICAL_OR(quality_tier_after = 'bronze') THEN 'bronze'
    WHEN LOGICAL_OR(quality_tier_after = 'silver') THEN 'silver'
    ELSE 'gold'
  END as overall_quality_tier,

  -- Source information
  ARRAY_AGG(DISTINCT primary_source IGNORE NULLS) as primary_sources_checked,
  ARRAY_AGG(DISTINCT
    CASE WHEN resolution = 'used_fallback' THEN primary_source END
    IGNORE NULLS
  ) as fallback_sources_used,

  LOGICAL_OR(resolution = 'reconstructed') as has_reconstruction,

  -- Timing
  MIN(event_timestamp) as first_event_at,
  MAX(event_timestamp) as last_event_at,
  MAX(resolved_at) as last_resolved_at

FROM nba_reference.source_coverage_log
GROUP BY game_id, game_date, season;
```

---

## Event Type Reference

### Event Type Constants

```python
# File: /shared_services/constants/source_coverage.py

class SourceCoverageEventType:
    """Standardized event types for source coverage log."""

    # Source availability
    SOURCE_MISSING = 'source_missing'
    SOURCE_DEGRADED = 'source_degraded'
    SOURCE_TIMEOUT = 'source_timeout'
    SOURCE_ERROR = 'source_error'

    # Fallback handling
    FALLBACK_USED = 'fallback_used'
    FALLBACK_FAILED = 'fallback_failed'

    # Reconstruction
    RECONSTRUCTION = 'reconstruction'
    RECONSTRUCTION_FAILED = 'reconstruction_failed'

    # Sample size
    INSUFFICIENT_SAMPLE = 'insufficient_sample'
    THIN_SAMPLE = 'thin_sample'

    # Player-specific
    NEW_PLAYER = 'new_player_no_history'
    TRADED_PLAYER = 'traded_player_context'

    # Quality
    QUALITY_DEGRADATION = 'quality_degradation'

    # Validation
    VALIDATION_FAILURE = 'validation_failure'

    # Audit
    SILENT_FAILURE = 'silent_failure'


class SourceCoverageSeverity:
    """Severity levels for coverage events."""
    CRITICAL = 'critical'  # Blocks predictions, immediate alert
    WARNING = 'warning'    # Degrades quality, digest alert
    INFO = 'info'          # Notable but acceptable, log only


class QualityTier:
    """Quality tier constants"""
    GOLD = 'gold'
    SILVER = 'silver'
    BRONZE = 'bronze'
    POOR = 'poor'
    UNUSABLE = 'unusable'
```

---

## Partitioning & Clustering

### Partitioning Strategy

```sql
PARTITION BY DATE(event_timestamp)
```

**Why:**
1. Most queries filter by date range
2. Enables partition pruning (huge cost savings)
3. Auto-expiration works on partitions (730 days)
4. Required partition filter prevents full scans

### Clustering Strategy

```sql
CLUSTER BY severity, event_type, game_id
```

**Cluster order rationale:**
1. `severity` - Most filtered field (critical vs warning vs info)
2. `event_type` - Second most filtered (type of event)
3. `game_id` - Common drill-down field

**Important:** BigQuery does not support traditional indexes. Use clustering for similar benefits.

### Query Performance Tips

**1. Always include partition filter:**
```sql
-- Even if you want "all time", limit to reasonable range
WHERE DATE(event_timestamp) >= '2024-01-01'
```

**2. Use clustered columns first in filters:**
```sql
-- Optimal order
WHERE severity = 'critical'  -- Cluster key 1
  AND event_type = 'source_missing'  -- Cluster key 2
  AND game_id = 'XXX'  -- Cluster key 3
```

---

## Migration Scripts

### Script 1: Create Source Coverage Log

```sql
-- ============================================================================
-- MIGRATION: Create source_coverage_log table
-- File: schemas/bigquery/nba_reference/source_coverage_log.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS nba_reference.source_coverage_log (
  event_id STRING NOT NULL,
  event_timestamp TIMESTAMP NOT NULL,
  event_type STRING NOT NULL,
  severity STRING NOT NULL,
  is_synthetic BOOL DEFAULT FALSE,
  phase STRING,
  table_name STRING,
  processor_name STRING,
  game_id STRING,
  game_date DATE,
  season STRING,
  player_id STRING,
  team_abbr STRING,
  description STRING,
  primary_source STRING,
  primary_source_status STRING,
  fallback_sources_tried ARRAY<STRING>,
  resolution STRING,
  resolution_details STRING,
  quality_tier_before STRING,
  quality_tier_after STRING,
  quality_score_before FLOAT64,
  quality_score_after FLOAT64,
  downstream_impact STRING,
  requires_alert BOOL,
  alert_sent BOOL,
  alert_channel STRING,
  alert_sent_at TIMESTAMP,
  is_resolved BOOL DEFAULT FALSE,
  resolved_at TIMESTAMP,
  resolution_method STRING,
  resolved_by STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  processor_run_id STRING,
  environment STRING
)
PARTITION BY DATE(event_timestamp)
CLUSTER BY severity, event_type, game_id
OPTIONS(
  description = "Audit log of all source coverage events",
  partition_expiration_days = 730,
  require_partition_filter = true
);
```

### Script 2: Add Quality Columns

```sql
-- ============================================================================
-- MIGRATION: Add quality columns to Phase 3+ tables
-- File: schemas/bigquery/analytics/source_coverage_quality_columns.sql
-- ============================================================================

-- Phase 3: player_game_summary
ALTER TABLE nba_analytics.player_game_summary
ADD COLUMN IF NOT EXISTS quality_tier STRING,
ADD COLUMN IF NOT EXISTS quality_score FLOAT64,
ADD COLUMN IF NOT EXISTS quality_issues ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS data_sources ARRAY<STRING>,
ADD COLUMN IF NOT EXISTS quality_metadata JSON;

-- Repeat for other tables:
-- - nba_analytics.team_offense_game_summary
-- - nba_analytics.team_defense_game_summary
-- - nba_precompute.player_daily_cache
-- - nba_predictions.ml_feature_store_v2
```

### Script 3: Create Game Summary View

```sql
-- ============================================================================
-- MIGRATION: Create game_source_coverage_summary view
-- File: schemas/bigquery/nba_reference/source_coverage_log.sql (view included)
-- ============================================================================

CREATE OR REPLACE VIEW nba_reference.game_source_coverage_summary AS
SELECT
  game_id,
  game_date,
  season,
  ARRAY_AGG(DISTINCT event_type IGNORE NULLS) as event_types,
  COUNT(*) as total_events,
  LOGICAL_OR(is_synthetic) as has_synthetic_events,
  MAX(severity) as worst_severity,
  LOGICAL_OR(NOT is_resolved) as has_unresolved_issues,
  MIN(quality_score_after) as min_quality_score,
  CASE
    WHEN LOGICAL_OR(quality_tier_after = 'unusable') THEN 'unusable'
    WHEN LOGICAL_OR(quality_tier_after = 'poor') THEN 'poor'
    WHEN LOGICAL_OR(quality_tier_after = 'bronze') THEN 'bronze'
    WHEN LOGICAL_OR(quality_tier_after = 'silver') THEN 'silver'
    ELSE 'gold'
  END as overall_quality_tier,
  MIN(event_timestamp) as first_event_at,
  MAX(event_timestamp) as last_event_at
FROM nba_reference.source_coverage_log
GROUP BY game_id, game_date, season;
```

### Script 4: Historical Backfill

```sql
-- ============================================================================
-- MIGRATION: Backfill Historical Quality Scores
-- File: schemas/bigquery/analytics/source_coverage_quality_columns.sql (backfill section)
-- Run: Once after tables have quality columns added
--
-- IMPORTANT: We use CONSERVATIVE defaults (silver, not gold) because:
-- 1. We cannot retroactively determine true source quality
-- 2. Claiming "gold" for unknown data creates false confidence
-- 3. Silver is honest: "data exists but quality is unverified"
-- ============================================================================

DECLARE backfill_start_date DATE DEFAULT '2021-10-01';
DECLARE backfill_reason STRING DEFAULT 'initial_rollout_v2';

-- Phase 3: player_game_summary
UPDATE nba_analytics.player_game_summary
SET
  quality_tier = 'silver',  -- Conservative default
  quality_score = 80.0,     -- Reflects uncertainty
  quality_issues = ['historical_data'],
  data_sources = ['unknown'],
  quality_calculated_at = CURRENT_TIMESTAMP(),
  quality_metadata = JSON_OBJECT(
    'backfilled', true,
    'backfill_date', CAST(CURRENT_DATE() AS STRING),
    'backfill_reason', backfill_reason,
    'note', 'Conservative default - true quality unknown'
  )
WHERE quality_tier IS NULL
  AND game_date >= backfill_start_date;

-- Repeat for other tables...

-- Final verification
SELECT
  'player_game_summary' as table_name,
  COUNT(*) as total_rows,
  COUNTIF(quality_tier IS NOT NULL) as rows_with_quality,
  ROUND(COUNTIF(quality_tier IS NOT NULL) * 100.0 / COUNT(*), 2) as coverage_pct
FROM nba_analytics.player_game_summary
WHERE game_date >= backfill_start_date;
```

---

## Summary

This schema reference provides:

- **Complete DDL** for source_coverage_log table
- **Standard quality columns** for all Phase 3+ tables
- **Game summary view** for convenient queries
- **Event type reference** with constants
- **Performance optimization** via partitioning and clustering
- **Migration scripts** ready to execute

**Note:** BigQuery does not support traditional indexes - use partitioning and clustering instead.

**Next:** See [Part 3: Implementation Guide](03-implementation-guide.md) for Python code and processor integration.

---

*End of Part 2: Schema Reference*
