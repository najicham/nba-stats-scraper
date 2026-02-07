-- Session 152: Subset pick snapshots for history tracking
--
-- Records subset picks at each export, enabling:
-- - Seeing how subsets changed throughout the day
-- - Future subset locking (freeze snapshot at a cutoff time)
-- - Audit trail of what picks were shown to consumers at what time
--
-- Usage:
--   bq query --use_legacy_sql=false < schemas/bigquery/predictions/05_subset_pick_snapshots.sql

CREATE TABLE IF NOT EXISTS nba_predictions.subset_pick_snapshots (
    snapshot_id STRING NOT NULL,          -- Unique ID per export (all groups share same ID)
    snapshot_at TIMESTAMP NOT NULL,       -- When this snapshot was recorded
    game_date DATE NOT NULL,              -- Game date for these picks

    trigger_source STRING,                -- What triggered: 'overnight', 'same_day', 'line_check', 'manual'
    batch_id STRING,                      -- Prediction batch that triggered this snapshot

    -- Subset-level data
    subset_id STRING NOT NULL,            -- Subset definition ID
    subset_name STRING,                   -- Human-readable subset name
    pick_count INT64,                     -- Number of picks in this subset at snapshot time

    -- Individual picks in this subset at snapshot time
    picks JSON,                           -- Array of {player, team, opponent, prediction, line, direction}

    -- Future: Subset locking
    is_locked BOOL DEFAULT FALSE,         -- TRUE when subset is locked/finalized
    locked_at TIMESTAMP,                  -- When the lock was applied
    lock_reason STRING                    -- Why it was locked (e.g., '2h_before_tip')
)
PARTITION BY game_date
CLUSTER BY subset_id;
