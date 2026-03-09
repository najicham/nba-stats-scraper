-- MLB Umpire Assignments
-- Source: MLB Stats API (schedule endpoint with officials hydration)
-- Processor: MlbUmpireAssignmentsProcessor
-- Updated: daily before game time

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.mlb_umpire_assignments` (
  game_pk INT64 NOT NULL,
  game_date DATE NOT NULL,
  umpire_name STRING NOT NULL,
  umpire_id INT64,
  umpire_link STRING,
  home_team_abbr STRING NOT NULL,
  away_team_abbr STRING NOT NULL,
  game_status STRING,
  source_file_path STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY game_pk, umpire_name
OPTIONS (
  description = "MLB home plate umpire assignments per game. Source: MLB Stats API.",
  require_partition_filter = true
);
