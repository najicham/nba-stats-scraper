-- File: schemas/bigquery/nba_orchestration/expected_outputs.sql
-- ============================================================================
-- Expected Outputs - Pipeline-as-a-Date-Grid Contract
-- ============================================================================
-- Purpose: ONE row per (sport, season, game_date, phase, output_type).
--          The contract: "for this date, this phase should have produced
--          this output." Replaces ad-hoc, phase-siloed completeness checks
--          that all use different lookback windows and miss historical gaps.
--
-- Why:     The Oct 2025 - Feb 2026 109-day NBA gap and the Dec 27 - Jan 21
--          26-day gap both went unnoticed because monitoring only looked at
--          the last 7-14 days. With this table, every date in the season
--          has a known-expected row; gap_detector flips on stale EXPECTED
--          rows of any age.
--
-- Created: 2026-05-09 (pipeline-state-redesign Phase C)
--
-- Writer:  orchestration/cloud_functions/expected_outputs_planner/  (nightly)
-- Reconciler: orchestration/cloud_functions/phase_completion_reconciler/
-- Reader:  orchestration/cloud_functions/gap_detector/  (every 30 min)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.expected_outputs` (

  -- ==========================================================================
  -- KEY (composite — see clustering for read patterns)
  -- ==========================================================================

  season STRING NOT NULL,
    -- e.g. '2025-26' for NBA, '2026' for MLB. Computed at planner-time
    -- from game_date + sport calendar.

  game_date DATE NOT NULL,
    -- The date this output covers (game_date semantics).

  sport STRING NOT NULL,
    -- 'nba' or 'mlb'.

  phase STRING NOT NULL,
    -- One of:
    --   'phase1_scrape'      — scraper output to GCS
    --   'phase2_raw'         — raw BQ tables in nba_raw / mlb_raw
    --   'phase3_analytics'   — analytics tables in nba_analytics
    --   'phase4_precompute'  — feature store, aggregates
    --   'phase5_predictions' — player_prop_predictions
    --   'phase6_publish'     — Phase 6 GCS JSON

  output_type STRING NOT NULL,
    -- e.g. 'nbac_gamebook_player_stats', 'ml_feature_store_v2',
    -- 'signal-best-bets/{date}.json'. Specific enough to identify ONE
    -- output uniquely within (date, phase). One row per output.

  -- ==========================================================================
  -- STATE MACHINE
  -- ==========================================================================

  status STRING NOT NULL,
    -- 'EXPECTED'  — planner created the row; reconciler hasn't seen actuals
    -- 'RUNNING'   — reconciler observed in-progress write
    -- 'COMPLETE'  — actual partition / file present with row_count > 0
    -- 'EMPTY_OK'  — actual is empty but legitimately so (no games, halt)
    -- 'FAILED'    — backfill attempts exhausted; gap_detector raised alert
    -- 'DEGRADED'  — actuals present but failed validation (low row count, etc.)

  expected_partition STRING,
    -- BQ partition key OR GCS path. Reconciler uses this to find the actual.
    -- e.g. 'game_date=2026-04-15' or 'v1/signal-best-bets/2026-04-15.json'.

  expected_by TIMESTAMP,
    -- SLA: by when should this be COMPLETE? Past this point, EXPECTED rows
    -- become candidates for gap_detector.

  -- ==========================================================================
  -- ACTUALS (filled by reconciler)
  -- ==========================================================================

  attempts INT64 DEFAULT 0,
    -- Number of times the upstream phase tried to produce this output.
    -- Capped at 3 by gap_detector — past that, FAILED + alert.

  last_run_at TIMESTAMP,
    -- Most recent attempt to produce this output (success or fail).

  last_error STRING,
    -- Most recent error string for diagnostic. NULL if last attempt OK.

  row_count INT64,
    -- Actual row count observed. NULL until reconciled.
    -- Zero rows + EXPECTED status = gap.
    -- Zero rows + EMPTY_OK status = legitimate empty (e.g. no games).

  byte_size INT64,
    -- For GCS outputs: file size in bytes. Helps detect zero-byte writes
    -- that look superficially like a successful publish.

  content_hash STRING,
    -- Content hash for idempotency / drift detection. Not always populated.

  -- ==========================================================================
  -- AUDIT
  -- ==========================================================================

  created_at TIMESTAMP NOT NULL,
    -- When the planner first created this row.

  updated_at TIMESTAMP NOT NULL,
    -- Most recent update by reconciler.

  source STRING NOT NULL
    -- Which writer last touched this row. e.g. 'planner', 'reconciler',
    -- 'gap_detector', 'manual_seed', 'backfill_job'.

)
PARTITION BY game_date
CLUSTER BY sport, phase, status
OPTIONS(
  description = "Pipeline-as-date-grid contract. One row per (sport, date, phase, output). Written by planner, reconciled by phase_completion_reconciler, scanned by gap_detector. The replacement for ad-hoc completeness checks.",
  labels = [
    ("project", "pipeline-state-redesign"),
    ("phase", "phase-c")
  ]
);


-- ============================================================================
-- View: gaps — currently-overdue EXPECTED rows
-- ============================================================================
-- Use as the canonical query for "what's missing right now?"
--
--   SELECT * FROM `nba-props-platform.nba_orchestration.expected_outputs_gaps`;
--
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.expected_outputs_gaps` AS
SELECT
  sport,
  game_date,
  phase,
  output_type,
  status,
  attempts,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), expected_by, HOUR) AS hours_overdue,
  last_error,
  expected_partition
FROM `nba-props-platform.nba_orchestration.expected_outputs`
WHERE status IN ('EXPECTED', 'FAILED', 'DEGRADED')
  AND expected_by < CURRENT_TIMESTAMP()
ORDER BY game_date DESC, phase, output_type;


-- ============================================================================
-- View: coverage_summary — daily completion percentage per phase per sport
-- ============================================================================
-- Powers the nba-pipeline-health Cloud Monitoring dashboard.
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.expected_outputs_coverage` AS
SELECT
  sport,
  game_date,
  phase,
  COUNT(*) AS total_outputs,
  COUNTIF(status = 'COMPLETE') AS complete_count,
  COUNTIF(status = 'EMPTY_OK') AS empty_ok_count,
  COUNTIF(status IN ('EXPECTED', 'RUNNING')) AS pending_count,
  COUNTIF(status IN ('FAILED', 'DEGRADED')) AS failed_count,
  ROUND(
    100.0 * (COUNTIF(status IN ('COMPLETE', 'EMPTY_OK'))) / NULLIF(COUNT(*), 0),
    1
  ) AS coverage_pct
FROM `nba-props-platform.nba_orchestration.expected_outputs`
GROUP BY sport, game_date, phase;
