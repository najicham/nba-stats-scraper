-- File: validation/queries/raw/espn_rosters/check_registry_tables.sql
-- ============================================================================
-- Purpose: Check if player registry tables exist and have data
-- Usage: Run first to verify registry system is set up
-- ============================================================================

SELECT
  table_name,
  CASE 
    WHEN table_name LIKE '%registry%' THEN '📋 Registry table'
    WHEN table_name LIKE '%alias%' THEN '🔗 Alias table'
    ELSE '📊 Other'
  END as table_type
FROM `nba-props-platform.INFORMATION_SCHEMA.TABLES`
WHERE table_schema IN ('nba_raw', 'nba_players', 'nba_analytics')
  AND (
    table_name LIKE '%registry%' 
    OR table_name LIKE '%alias%'
    OR table_name LIKE '%player%'
  )
ORDER BY table_schema, table_name;
