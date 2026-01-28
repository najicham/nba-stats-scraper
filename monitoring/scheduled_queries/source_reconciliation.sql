-- ============================================================================
-- Scheduled Query: source_reconciliation
-- Purpose: Daily cross-source reconciliation check (NBA.com vs BDL)
-- ============================================================================
-- Schedule: Daily at 8:00 AM (after overnight processing completes)
-- Destination: `nba-props-platform.nba_monitoring.source_reconciliation_results`
-- Retention: 90 days
--
-- This scheduled query runs daily to compare NBA.com official stats against
-- Ball Don't Lie (BDL) stats for yesterday's games. Results are written to
-- a table for historical tracking and alerting.
--
-- Setup Instructions:
--   1. Create destination table (run once):
--      bq mk --table \
--        nba-props-platform:nba_monitoring.source_reconciliation_results \
--        monitoring/scheduled_queries/source_reconciliation_schema.json
--
--   2. Create scheduled query via Cloud Console or gcloud:
--      gcloud scheduler jobs create bigquery source-reconciliation \
--        --schedule="0 8 * * *" \
--        --time-zone="America/New_York" \
--        --location=us-west2 \
--        --query-file=monitoring/scheduled_queries/source_reconciliation.sql \
--        --destination-table=nba-props-platform.nba_monitoring.source_reconciliation_results \
--        --write-disposition=WRITE_APPEND
--
--   3. Monitor via /validate-daily skill (Phase 3C)
-- ============================================================================

-- Use the view we created (it always checks yesterday)
SELECT
  CURRENT_TIMESTAMP() as run_timestamp,
  game_date,
  game_id,
  player_lookup,
  player_name,
  team_abbr,
  starter,
  presence_status,

  -- Stats from both sources
  nbac_points,
  nbac_assists,
  nbac_rebounds,
  bdl_points,
  bdl_assists,
  bdl_rebounds,

  -- Differences
  point_diff,
  assist_diff,
  rebound_diff,

  -- Health assessment
  health_status,
  discrepancy_summary,
  stat_comparison,

  -- Metadata
  checked_at

FROM `nba-props-platform.nba_monitoring.source_reconciliation_daily`

-- Only store records with issues or a sample of matches (for trend analysis)
WHERE health_status IN ('CRITICAL', 'WARNING', 'MINOR_DIFF')
   OR MOD(ABS(FARM_FINGERPRINT(player_lookup)), 10) = 0  -- Keep 10% sample of matches

ORDER BY
  FIELD(health_status, 'CRITICAL', 'WARNING', 'MINOR_DIFF', 'MATCH'),
  point_diff DESC;

-- ============================================================================
-- DESTINATION TABLE SCHEMA (for reference)
-- ============================================================================
-- Create with: bq mk --table nba-props-platform:nba_monitoring.source_reconciliation_results
--
-- Fields:
--   run_timestamp: TIMESTAMP (when scheduled query ran)
--   game_date: DATE (game date being reconciled)
--   game_id: STRING
--   player_lookup: STRING
--   player_name: STRING
--   team_abbr: STRING
--   starter: BOOLEAN
--   presence_status: STRING (in_both, nbac_only, bdl_only)
--   nbac_points: INT64
--   nbac_assists: INT64
--   nbac_rebounds: INT64
--   bdl_points: INT64
--   bdl_assists: INT64
--   bdl_rebounds: INT64
--   point_diff: INT64
--   assist_diff: INT64
--   rebound_diff: INT64
--   health_status: STRING (CRITICAL, WARNING, MINOR_DIFF, MATCH)
--   discrepancy_summary: STRING
--   stat_comparison: STRING
--   checked_at: TIMESTAMP
--
-- Partitioning: PARTITION BY DATE(run_timestamp)
-- Clustering: CLUSTER BY health_status, game_date, team_abbr
-- Retention: 90 days (set via table expiration policy)
-- ============================================================================

-- ============================================================================
-- ALERTING QUERIES (run separately or via monitoring script)
-- ============================================================================

-- Alert #1: Critical discrepancies detected
-- WITH latest_run AS (
--   SELECT MAX(run_timestamp) as last_run
--   FROM `nba-props-platform.nba_monitoring.source_reconciliation_results`
-- ),
-- critical_issues AS (
--   SELECT
--     COUNT(*) as critical_count,
--     STRING_AGG(CONCAT(player_name, ' (', team_abbr, '): ', discrepancy_summary), '\n' LIMIT 10) as details
--   FROM `nba-props-platform.nba_monitoring.source_reconciliation_results`
--   WHERE run_timestamp = (SELECT last_run FROM latest_run)
--     AND health_status = 'CRITICAL'
-- )
-- SELECT
--   critical_count,
--   details,
--   CASE WHEN critical_count > 0 THEN 'ALERT: Critical source discrepancies found' ELSE 'OK' END as alert_message
-- FROM critical_issues;

-- Alert #2: Match rate below threshold (should be >95%)
-- WITH latest_run AS (
--   SELECT MAX(run_timestamp) as last_run
--   FROM `nba-props-platform.nba_monitoring.source_reconciliation_results`
-- ),
-- match_rate AS (
--   SELECT
--     COUNTIF(health_status = 'MATCH') as match_count,
--     COUNT(*) as total_count,
--     ROUND(COUNTIF(health_status = 'MATCH') * 100.0 / COUNT(*), 1) as match_pct
--   FROM `nba-props-platform.nba_monitoring.source_reconciliation_results`
--   WHERE run_timestamp = (SELECT last_run FROM latest_run)
-- )
-- SELECT
--   match_count,
--   total_count,
--   match_pct,
--   CASE WHEN match_pct < 95.0 THEN 'ALERT: Match rate below 95% threshold' ELSE 'OK' END as alert_message
-- FROM match_rate;

-- Alert #3: Players missing from either source
-- WITH latest_run AS (
--   SELECT MAX(run_timestamp) as last_run
--   FROM `nba-props-platform.nba_monitoring.source_reconciliation_results`
-- )
-- SELECT
--   presence_status,
--   COUNT(*) as player_count,
--   STRING_AGG(CONCAT(player_name, ' (', team_abbr, ')'), ', ' LIMIT 10) as players
-- FROM `nba-props-platform.nba_monitoring.source_reconciliation_results`
-- WHERE run_timestamp = (SELECT last_run FROM latest_run)
--   AND presence_status != 'in_both'
-- GROUP BY presence_status;
