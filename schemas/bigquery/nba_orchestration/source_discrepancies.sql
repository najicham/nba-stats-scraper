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

-- BDL Quality Trend View
-- Tracks BDL data quality over time to determine when it's safe to re-enable
-- Added: Session 41 (2026-01-30)
CREATE OR REPLACE VIEW `nba_orchestration.bdl_quality_trend` AS
WITH daily_metrics AS (
    SELECT
        game_date,
        COUNTIF(severity = 'major') as major_count,
        COUNTIF(severity = 'minor') as minor_count,
        COUNTIF(severity = 'info') as summary_count,
        COUNT(*) as total_discrepancies,
        COUNT(DISTINCT CASE WHEN player_lookup != '_SUMMARY_' THEN player_lookup END) as players_affected
    FROM `nba_orchestration.source_discrepancies`
    WHERE backup_source = 'bdl'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    GROUP BY game_date
),
summary_details AS (
    SELECT
        game_date,
        JSON_EXTRACT_SCALAR(discrepancies_json, '$.total_players') as total_players,
        JSON_EXTRACT_SCALAR(discrepancies_json, '$.bdl_coverage') as bdl_coverage,
        JSON_EXTRACT_SCALAR(discrepancies_json, '$.major_discrepancy_pct') as major_discrepancy_pct,
        JSON_EXTRACT_SCALAR(discrepancies_json, '$.accuracy_pct') as accuracy_pct,
        JSON_EXTRACT_SCALAR(discrepancies_json, '$.recommendation') as recommendation
    FROM `nba_orchestration.source_discrepancies`
    WHERE backup_source = 'bdl'
      AND player_lookup = '_SUMMARY_'
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)
SELECT
    d.game_date,
    SAFE_CAST(s.total_players AS INT64) as total_players,
    SAFE_CAST(s.bdl_coverage AS INT64) as bdl_coverage,
    ROUND(SAFE_CAST(s.bdl_coverage AS INT64) / SAFE_CAST(s.total_players AS FLOAT64) * 100, 1) as coverage_pct,
    d.major_count,
    d.minor_count,
    SAFE_CAST(s.major_discrepancy_pct AS FLOAT64) as major_discrepancy_pct,
    SAFE_CAST(s.accuracy_pct AS FLOAT64) as accuracy_pct,
    s.recommendation,
    -- Rolling 7-day average of major discrepancy %
    AVG(SAFE_CAST(s.major_discrepancy_pct AS FLOAT64)) OVER (
        ORDER BY d.game_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) as rolling_7d_major_pct,
    -- Readiness indicator: <5% major discrepancies for 7 consecutive days
    CASE
        WHEN SAFE_CAST(s.major_discrepancy_pct AS FLOAT64) <= 5
         AND LAG(SAFE_CAST(s.major_discrepancy_pct AS FLOAT64), 1) OVER (ORDER BY d.game_date) <= 5
         AND LAG(SAFE_CAST(s.major_discrepancy_pct AS FLOAT64), 2) OVER (ORDER BY d.game_date) <= 5
         AND LAG(SAFE_CAST(s.major_discrepancy_pct AS FLOAT64), 3) OVER (ORDER BY d.game_date) <= 5
         AND LAG(SAFE_CAST(s.major_discrepancy_pct AS FLOAT64), 4) OVER (ORDER BY d.game_date) <= 5
         AND LAG(SAFE_CAST(s.major_discrepancy_pct AS FLOAT64), 5) OVER (ORDER BY d.game_date) <= 5
         AND LAG(SAFE_CAST(s.major_discrepancy_pct AS FLOAT64), 6) OVER (ORDER BY d.game_date) <= 5
        THEN 'READY_TO_ENABLE'
        WHEN SAFE_CAST(s.major_discrepancy_pct AS FLOAT64) <= 10
        THEN 'IMPROVING'
        ELSE 'NOT_READY'
    END as bdl_readiness
FROM daily_metrics d
LEFT JOIN summary_details s ON d.game_date = s.game_date
ORDER BY d.game_date DESC;
