-- Backfill and Contamination Tracking Schema
-- Part of Data Lineage Integrity project
-- Created: 2026-01-26

-- =============================================================================
-- TABLE 1: BACKFILL EVENT LOG
-- Immutable record of every backfill operation
-- =============================================================================

CREATE TABLE IF NOT EXISTS nba_orchestration.backfill_events (
    -- Primary key
    backfill_id STRING NOT NULL,  -- UUID

    -- What was backfilled
    table_name STRING NOT NULL,   -- e.g., 'nba_raw.bdl_player_boxscores'
    entity_type STRING,           -- 'player', 'game', 'team', or NULL for bulk
    entity_id STRING,             -- player_lookup, game_id, etc. (NULL for bulk)
    game_date DATE NOT NULL,      -- The date of the data that was backfilled

    -- When it happened
    backfilled_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    hours_delayed INT64,          -- How late was this data? (NULL if unknown)

    -- Context
    backfill_source STRING,       -- 'manual', 'scraper_retry', 'backfill_job', 'cascade'
    backfill_job_id STRING,       -- Reference to Cloud Run job execution
    triggered_by STRING,          -- User or system that triggered
    notes STRING,                 -- Free text notes

    -- Computed contamination window (for downstream impact)
    -- These are the END dates of each rolling window that could be affected
    l5_contamination_end DATE,
    l10_contamination_end DATE,
    l15_contamination_end DATE,
    l20_contamination_end DATE,

    -- Downstream impact estimate
    estimated_downstream_records INT64,

    -- Audit
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

-- =============================================================================
-- TABLE 2: CONTAMINATION TRACKING
-- Links backfill events to specific downstream records that were affected
-- Populated when we analyze impact, updated when we remediate
-- =============================================================================

CREATE TABLE IF NOT EXISTS nba_orchestration.contamination_records (
    -- Primary key
    contamination_id STRING NOT NULL,  -- UUID

    -- Link to backfill event
    backfill_id STRING NOT NULL,       -- FK to backfill_events

    -- The affected downstream record
    downstream_table STRING NOT NULL,  -- e.g., 'nba_precompute.player_composite_factors'
    entity_id STRING NOT NULL,         -- player_lookup
    game_date DATE NOT NULL,           -- Date of the contaminated record

    -- Which rolling windows were affected
    affected_windows ARRAY<STRING>,    -- ['L5', 'L10', 'L15', 'L20']

    -- Quality impact
    original_quality_score FLOAT64,    -- Quality score before contamination detected
    contaminated_quality_score FLOAT64,-- Quality score accounting for missing data

    -- Remediation status
    remediation_status STRING DEFAULT 'pending',  -- 'pending', 'in_progress', 'completed', 'skipped'
    remediated_at TIMESTAMP,
    remediation_job_id STRING,
    final_quality_score FLOAT64,       -- Quality score after remediation

    -- Audit
    discovered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    updated_at TIMESTAMP
);

-- =============================================================================
-- TABLE 3: REMEDIATION LOG
-- Detailed log of remediation actions (for audit trail)
-- =============================================================================

CREATE TABLE IF NOT EXISTS nba_orchestration.remediation_log (
    -- Primary key
    remediation_id STRING NOT NULL,  -- UUID

    -- Scope
    remediation_type STRING NOT NULL,  -- 'single_record', 'player_range', 'date_range', 'full_table'
    target_table STRING NOT NULL,

    -- Filter criteria
    player_lookup STRING,
    start_date DATE,
    end_date DATE,

    -- Execution
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    completed_at TIMESTAMP,
    status STRING DEFAULT 'running',  -- 'running', 'completed', 'failed'

    -- Results
    records_processed INT64,
    records_updated INT64,
    records_unchanged INT64,

    -- Quality improvement
    avg_quality_before FLOAT64,
    avg_quality_after FLOAT64,

    -- Link to trigger
    triggered_by_backfill_id STRING,  -- FK to backfill_events (if remediation was triggered by backfill)

    -- Error handling
    error_message STRING,

    -- Audit
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

-- =============================================================================
-- VIEW: PENDING REMEDIATIONS
-- Records that need remediation (contaminated but not yet fixed)
-- =============================================================================

CREATE OR REPLACE VIEW nba_orchestration.v_pending_remediations AS
SELECT
    cr.contamination_id,
    cr.backfill_id,
    be.game_date as source_gap_date,
    be.hours_delayed,
    cr.downstream_table,
    cr.entity_id,
    cr.game_date as contaminated_date,
    cr.affected_windows,
    cr.contaminated_quality_score,
    cr.discovered_at,
    DATE_DIFF(CURRENT_DATE(), cr.game_date, DAY) as days_since_contamination
FROM nba_orchestration.contamination_records cr
JOIN nba_orchestration.backfill_events be ON cr.backfill_id = be.backfill_id
WHERE cr.remediation_status = 'pending'
ORDER BY be.hours_delayed DESC, cr.game_date;

-- =============================================================================
-- VIEW: BACKFILL IMPACT SUMMARY
-- Summary of each backfill and its downstream impact
-- =============================================================================

CREATE OR REPLACE VIEW nba_orchestration.v_backfill_impact_summary AS
SELECT
    be.backfill_id,
    be.table_name as source_table,
    be.game_date,
    be.backfilled_at,
    be.hours_delayed,
    be.backfill_source,
    COUNT(cr.contamination_id) as contaminated_records,
    COUNTIF(cr.remediation_status = 'pending') as pending_remediation,
    COUNTIF(cr.remediation_status = 'completed') as remediated,
    COUNTIF(cr.remediation_status = 'skipped') as skipped,
    AVG(cr.contaminated_quality_score) as avg_contaminated_quality,
    AVG(cr.final_quality_score) as avg_final_quality
FROM nba_orchestration.backfill_events be
LEFT JOIN nba_orchestration.contamination_records cr ON be.backfill_id = cr.backfill_id
GROUP BY 1,2,3,4,5,6;

-- =============================================================================
-- INDEXES (for query performance)
-- =============================================================================

-- Note: BigQuery doesn't support traditional indexes, but we can use
-- clustering and partitioning for performance

-- For backfill_events: Partition by backfilled_at, cluster by table_name, game_date
-- For contamination_records: Partition by discovered_at, cluster by remediation_status, downstream_table
-- For remediation_log: Partition by started_at
