-- Ball Don't Lie Standings Table
-- Daily team standings with comprehensive record splits and rankings

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.bdl_standings` (
  -- Core identifiers
  season_year          INT64        NOT NULL,    -- Starting year (2024 for 2024-25)
  season_display       STRING       NOT NULL,    -- Calculated "2024-25" 
  date_recorded        DATE         NOT NULL,    -- Date standings were captured
  team_id              INT64        NOT NULL,    -- BDL team ID
  team_abbr            STRING       NOT NULL,    -- Three-letter code (CLE, OKC, BOS)
  team_city            STRING,                   -- "Cleveland", "Oklahoma City"
  team_name            STRING,                   -- "Cavaliers", "Thunder"
  team_full_name       STRING,                   -- "Cleveland Cavaliers"

  -- Conference/Division
  conference           STRING       NOT NULL,    -- "East", "West"  
  division             STRING       NOT NULL,    -- "Central", "Northwest", etc.
  conference_rank      INT64        NOT NULL,    -- Rank within conference
  division_rank        INT64        NOT NULL,    -- Rank within division

  -- Overall record
  wins                 INT64        NOT NULL,    -- Total wins
  losses               INT64        NOT NULL,    -- Total losses
  win_percentage       FLOAT64      NOT NULL,    -- Calculated wins/(wins+losses)
  games_played         INT64        NOT NULL,    -- Calculated wins+losses

  -- Conference record (parsed)
  conference_record    STRING,                   -- Original "41-11"
  conference_wins      INT64,                    -- Parsed from conference_record
  conference_losses    INT64,                    -- Parsed from conference_record

  -- Division record (parsed)  
  division_record      STRING,                   -- Original "12-4"
  division_wins        INT64,                    -- Parsed from division_record
  division_losses      INT64,                    -- Parsed from division_record

  -- Home/Road splits (parsed)
  home_record          STRING,                   -- Original "34-7"
  home_wins            INT64,                    -- Parsed from home_record
  home_losses          INT64,                    -- Parsed from home_record
  road_record          STRING,                   -- Original "30-11" 
  road_wins            INT64,                    -- Parsed from road_record
  road_losses          INT64,                    -- Parsed from road_record

  -- Processing metadata
  scrape_timestamp     TIMESTAMP,               -- When data was scraped
  source_file_path     STRING       NOT NULL,   -- GCS path
  created_at           TIMESTAMP    NOT NULL,   -- When record first created
  processed_at         TIMESTAMP    NOT NULL    -- When record last updated
)
PARTITION BY date_recorded
CLUSTER BY team_abbr, conference, conference_rank
OPTIONS (
  description = "Ball Don't Lie daily NBA team standings with comprehensive record splits",
  labels = [
    ("source", "ball_dont_lie"),
    ("processor", "bdl_standings_processor"),
    ("data_type", "team_standings")
  ]
);