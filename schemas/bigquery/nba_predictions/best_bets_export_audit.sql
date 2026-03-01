-- ============================================================================
-- Best Bets Export Audit Table Schema
-- ============================================================================
-- Dataset: nba_predictions
-- Table: best_bets_export_audit
-- Purpose: Snapshot of every best bets export for auditability. Records what
--          was published, how many picks came from each source, and preserves
--          the full pick list as JSON.
-- Created: 2026-02-28
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.best_bets_export_audit` (
  -- Primary Keys
  export_id STRING NOT NULL,           -- Unique export identifier (timestamp-based)
  game_date DATE NOT NULL,

  -- Export Stats
  total_picks INT64,
  algorithm_picks INT64,               -- Picks from signal pipeline
  manual_picks INT64,                  -- Picks from manual overrides
  locked_picks INT64,                  -- Picks carried over from published table
  new_picks INT64,                     -- Picks appearing for the first time
  dropped_from_signal INT64,           -- Picks in published but no longer in signal

  -- Full Snapshot
  picks_snapshot STRING,               -- JSON string of complete pick list

  -- Provenance
  algorithm_version STRING,
  trigger_source STRING,               -- 'scheduled', 'manual', 'post_grading'

  -- Metadata
  exported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY export_id
OPTIONS (
  require_partition_filter=TRUE,
  description='Audit trail for every best bets export. Each row is a snapshot of what '
              'was published, with source attribution and full pick list for debugging.'
);
