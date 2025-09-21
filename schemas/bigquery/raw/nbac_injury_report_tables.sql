-- File: schemas/bigquery/nbac_injury_report_tables.sql
-- NBA.com Injury Reports - Player availability for games

CREATE TABLE IF NOT EXISTS `nba_raw.nbac_injury_report` (
  -- Report Metadata
  report_date DATE,                    -- Date report was issued
  report_hour INT64,                   -- Hour of report (0-23)
  season STRING,                       -- Season identifier
  
  -- Game Information
  game_date DATE,                      -- Game date from report
  game_time STRING,                    -- Game time (ET)
  game_id STRING,                      -- Constructed: "20211123_MIA_DET"
  matchup STRING,                      -- Original: "MIA@DET"
  away_team STRING,                    -- Away team abbreviation
  home_team STRING,                    -- Home team abbreviation
  
  -- Player Information
  team STRING,                         -- Player's team
  player_name_original STRING,         -- Original: "Hayes, Killian"
  player_full_name STRING,             -- Parsed: "Killian Hayes"
  player_lookup STRING,                -- Normalized: "killianhayes"
  
  -- Injury Status
  injury_status STRING,                -- "out", "questionable", "doubtful", "probable", "available"
  reason STRING,                       -- Full reason text
  reason_category STRING,              -- Category: "injury", "g_league", "suspension", etc.
  
  -- Data Quality
  confidence_score FLOAT64,            -- Parsing confidence for this record
  overall_report_confidence FLOAT64,   -- Overall report parsing confidence
  
  -- Processing Metadata
  scrape_time STRING,                  -- Time scraper ran
  run_id STRING,                       -- Scraper run identifier
  source_file_path STRING,
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY report_date
CLUSTER BY player_lookup, game_id, injury_status
OPTIONS(
  description = "NBA injury reports with player availability status per game",
  labels = [("source", "nba-com"), ("type", "injury-report"), ("update_frequency", "multiple-daily")]
);

-- Create view for latest injury status per player
CREATE OR REPLACE VIEW `nba_raw.nbac_injury_report_latest` AS
WITH ranked_reports AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY player_lookup, game_id 
      ORDER BY report_date DESC, report_hour DESC
    ) as rn
  FROM `nba_raw.nbac_injury_report`
)
SELECT * EXCEPT(rn)
FROM ranked_reports
WHERE rn = 1;

-- Create summary view for props impact
CREATE OR REPLACE VIEW `nba_raw.injury_impact_for_props` AS
SELECT 
  game_id,
  player_lookup,
  player_full_name,
  team,
  injury_status,
  reason_category,
  CASE 
    WHEN injury_status = 'out' THEN 'NO_PROPS'
    WHEN injury_status IN ('doubtful', 'questionable') THEN 'RISKY_PROPS'
    WHEN injury_status IN ('probable', 'available') THEN 'SAFE_PROPS'
    ELSE 'CHECK_MANUALLY'
  END as prop_recommendation,
  report_date,
  report_hour
FROM `nba_raw.nbac_injury_report_latest`
WHERE report_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY);