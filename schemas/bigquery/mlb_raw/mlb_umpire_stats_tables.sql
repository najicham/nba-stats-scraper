-- MLB Umpire Stats
-- Source: UmpScorecards (umpscorecards.com)
-- Processor: MlbUmpireStatsProcessor
-- Updated: periodically (weekly or as needed)

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.mlb_umpire_stats` (
  umpire_name STRING NOT NULL,
  season INT64 NOT NULL,
  scrape_date DATE NOT NULL,
  games INT64,
  accuracy FLOAT64,
  consistency FLOAT64,
  favor FLOAT64,
  k_zone_tendency STRING,
  source_file_path STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
CLUSTER BY umpire_name, season
OPTIONS (
  description = "MLB umpire accuracy and K zone tendency stats. Source: UmpScorecards."
);
