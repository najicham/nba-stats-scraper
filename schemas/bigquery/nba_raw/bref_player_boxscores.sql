-- Basketball Reference Player Box Scores
-- Backup data source for cross-validation
-- Created: 2026-01-28

CREATE TABLE IF NOT EXISTS `nba_raw.bref_player_boxscores` (
    -- Source identification
    source STRING NOT NULL,  -- 'basketball_reference'
    game_date DATE NOT NULL,
    game_id STRING,

    -- Player identification
    player_name STRING,
    player_lookup STRING NOT NULL,
    team_abbr STRING,
    opponent_abbr STRING,

    -- Core stats
    minutes_played INT64,
    points INT64,
    assists INT64,
    offensive_rebounds INT64,
    defensive_rebounds INT64,
    total_rebounds INT64,
    steals INT64,
    blocks INT64,
    turnovers INT64,
    personal_fouls INT64,

    -- Shooting stats
    fg_made INT64,
    fg_attempted INT64,
    three_pt_made INT64,
    three_pt_attempted INT64,
    ft_made INT64,
    ft_attempted INT64,

    -- Additional
    plus_minus INT64,

    -- Metadata
    scraped_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY player_lookup, team_abbr
OPTIONS (
    description = 'Basketball Reference player box scores - backup source for validation',
    labels = [('source', 'basketball_reference'), ('purpose', 'backup_validation')]
);
