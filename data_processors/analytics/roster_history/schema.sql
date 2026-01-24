-- Schema for nba_analytics.roster_history table
-- Tracks roster changes over time for historical analysis

-- Create table if not exists
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.roster_history` (
    -- Change identification
    change_date DATE NOT NULL,
    player_lookup STRING NOT NULL,
    player_full_name STRING,
    team_abbr STRING NOT NULL,

    -- Change details
    change_type STRING NOT NULL,  -- 'added', 'removed', 'status_change', 'team_change', 'jersey_change'
    previous_value STRING,
    new_value STRING,

    -- Trade details (for team_change type)
    from_team STRING,
    to_team STRING,

    -- Transaction details (from player movement data)
    transaction_type STRING,
    transaction_description STRING,

    -- Metadata
    season_year INT64,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),

    -- Primary key equivalent for deduplication
    -- Unique on: change_date, player_lookup, team_abbr, change_type
)
PARTITION BY change_date
CLUSTER BY team_abbr, player_lookup
OPTIONS (
    description = 'Historical roster changes for NBA teams',
    labels = [
        ('data_source', 'espn_rosters'),
        ('data_type', 'analytics'),
        ('update_frequency', 'daily')
    ]
);

-- Create view for recent roster activity
CREATE OR REPLACE VIEW `nba-props-platform.nba_analytics.v_recent_roster_activity` AS
SELECT
    change_date,
    player_lookup,
    player_full_name,
    team_abbr,
    change_type,
    COALESCE(transaction_description,
             CONCAT(change_type, ': ', COALESCE(previous_value, 'N/A'), ' -> ', COALESCE(new_value, 'N/A'))) as description,
    from_team,
    to_team,
    season_year
FROM `nba-props-platform.nba_analytics.roster_history`
WHERE change_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY change_date DESC, team_abbr;

-- Create view for trades/team changes
CREATE OR REPLACE VIEW `nba-props-platform.nba_analytics.v_player_trades` AS
SELECT
    change_date as trade_date,
    player_lookup,
    player_full_name,
    from_team,
    to_team,
    transaction_description,
    season_year
FROM `nba-props-platform.nba_analytics.roster_history`
WHERE change_type = 'team_change'
  AND from_team IS NOT NULL
  AND to_team IS NOT NULL
ORDER BY change_date DESC;

-- Create view for roster stability metrics by team
CREATE OR REPLACE VIEW `nba-props-platform.nba_analytics.v_roster_stability` AS
WITH changes_by_team AS (
    SELECT
        team_abbr,
        season_year,
        DATE_TRUNC(change_date, WEEK) as week_start,
        COUNT(*) as changes_count,
        COUNT(DISTINCT player_lookup) as players_affected,
        COUNTIF(change_type = 'added') as additions,
        COUNTIF(change_type = 'removed') as removals,
        COUNTIF(change_type = 'team_change') as trades
    FROM `nba-props-platform.nba_analytics.roster_history`
    GROUP BY team_abbr, season_year, DATE_TRUNC(change_date, WEEK)
)
SELECT
    team_abbr,
    season_year,
    week_start,
    changes_count,
    players_affected,
    additions,
    removals,
    trades,
    -- Stability score (lower is more stable)
    (changes_count * 1.0 + trades * 2.0) / 15.0 as instability_score
FROM changes_by_team
ORDER BY week_start DESC, team_abbr;
