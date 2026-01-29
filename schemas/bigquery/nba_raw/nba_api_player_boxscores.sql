-- NBA API BoxScoreTraditionalV3 Player Box Scores
-- Backup source via nba_api library (different endpoint than gamebook)
-- Created: 2026-01-28

CREATE TABLE IF NOT EXISTS `nba_raw.nba_api_player_boxscores` (
    -- Source identification
    source STRING NOT NULL,  -- 'nba_api_boxscore_v3'
    game_id STRING NOT NULL,
    game_date DATE NOT NULL,

    -- Player identification
    player_id INT64,
    player_name STRING,
    player_lookup STRING NOT NULL,
    team_abbr STRING,
    team_id INT64,
    starter BOOL,

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
    description = 'NBA API BoxScoreTraditionalV3 - backup source for validation',
    labels = [('source', 'nba_api'), ('purpose', 'backup_validation')]
);
