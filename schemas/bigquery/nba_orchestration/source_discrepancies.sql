-- Source Data Discrepancies
-- Tracks differences between primary and backup data sources
-- Created: 2026-01-28

CREATE TABLE IF NOT EXISTS `nba_orchestration.source_discrepancies` (
    game_date DATE NOT NULL,
    player_lookup STRING NOT NULL,
    player_name STRING,
    backup_source STRING NOT NULL,  -- 'basketball_reference', 'bdl', etc.
    severity STRING NOT NULL,       -- 'major', 'minor'
    discrepancies_json STRING,      -- JSON of field differences
    detected_at TIMESTAMP NOT NULL,
    reviewed BOOL DEFAULT FALSE,
    review_notes STRING
)
PARTITION BY game_date
CLUSTER BY severity, backup_source
OPTIONS (
    description = 'Tracks data discrepancies between primary (NBA.com) and backup sources',
    labels = [('purpose', 'data_quality')]
);

-- View for easy analysis
CREATE OR REPLACE VIEW `nba_orchestration.source_discrepancies_summary` AS
SELECT
    game_date,
    backup_source,
    severity,
    COUNT(*) as discrepancy_count,
    COUNT(DISTINCT player_lookup) as players_affected
FROM `nba_orchestration.source_discrepancies`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date, backup_source, severity
ORDER BY game_date DESC, severity;
