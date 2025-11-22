-- Ball Don't Lie Injuries Table Schema
-- File: schemas/bigquery/bdl_injuries_table.sql

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.bdl_injuries` (
  -- Core identifiers
  scrape_date          DATE         NOT NULL OPTIONS(description="Date data was scraped"),
  season_year          INT64        NOT NULL OPTIONS(description="Current NBA season (2024 for 2024-25)"),
  
  -- Player identification
  bdl_player_id        INT64        NOT NULL OPTIONS(description="Ball Don't Lie unique player ID"),
  player_full_name     STRING       NOT NULL OPTIONS(description="Full player name: 'Jacob Toppin'"),
  player_lookup        STRING       NOT NULL OPTIONS(description="Normalized name for matching: 'jacobtoppin'"),
  
  -- Team assignment
  bdl_team_id          INT64        OPTIONS(description="Ball Don't Lie team ID"),
  team_abbr            STRING       NOT NULL OPTIONS(description="Standard team abbreviation: 'ATL', 'LAL'"),
  
  -- Injury details
  injury_status        STRING       NOT NULL OPTIONS(description="Original status: 'Day-To-Day', 'Out', 'Questionable'"),
  injury_status_normalized STRING   NOT NULL OPTIONS(description="Standardized: 'out', 'questionable', 'doubtful', 'probable'"),
  return_date          DATE         OPTIONS(description="Parsed return date: 'Jul 17' → 2024-07-17"),
  return_date_original STRING       OPTIONS(description="Original return date text: 'Jul 17', 'TBD', 'Unknown'"),
  injury_description   STRING       OPTIONS(description="Full injury description text"),
  reason_category      STRING       NOT NULL OPTIONS(description="Categorized reason: 'injury', 'g_league', 'rest', 'personal', 'suspension'"),
  
  -- Data quality tracking
  parsing_confidence   FLOAT64      NOT NULL OPTIONS(description="Data extraction confidence: 0.0-1.0"),
  data_quality_flags   STRING       OPTIONS(description="Parsing issues: 'unparseable_date,unknown_status'"),
  return_date_parsed   BOOLEAN      NOT NULL OPTIONS(description="TRUE if return_date successfully parsed"),
  
  -- Processing metadata
  scrape_timestamp     TIMESTAMP    OPTIONS(description="When scraper ran (for intraday tracking)"),
  source_file_path     STRING       NOT NULL OPTIONS(description="GCS path to source JSON file"),

  -- Smart Idempotency (Pattern #14)
  data_hash            STRING       OPTIONS(description="SHA256 hash of meaningful fields: player_lookup, team_abbr, injury_status_normalized, return_date, reason_category"),

  processed_at         TIMESTAMP    NOT NULL OPTIONS(description="When processed to BigQuery")
)
PARTITION BY scrape_date
CLUSTER BY player_lookup, team_abbr, injury_status_normalized
OPTIONS(
  description="Ball Don't Lie injury reports - backup/validation source for NBA.com injury data. APPEND_ALWAYS strategy tracks intraday status changes. Uses smart idempotency to skip redundant writes.",
  labels=[("source", "ball_dont_lie"), ("category", "injuries"), ("strategy", "append_always"), ("pattern", "smart-idempotency")]
);

-- Create helpful views for common queries

-- Latest injury status per player per day
CREATE OR REPLACE VIEW `nba-props-platform.nba_raw.bdl_injuries_latest_daily` AS
SELECT * FROM (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY scrape_date, bdl_player_id 
      ORDER BY scrape_timestamp DESC
    ) as rn
  FROM `nba-props-platform.nba_raw.bdl_injuries`
) WHERE rn = 1;

-- High-confidence records only (for production use)
CREATE OR REPLACE VIEW `nba-props-platform.nba_raw.bdl_injuries_high_confidence` AS
SELECT *
FROM `nba-props-platform.nba_raw.bdl_injuries`
WHERE parsing_confidence >= 0.8;

-- Data quality monitoring view
CREATE OR REPLACE VIEW `nba-props-platform.nba_raw.bdl_injuries_quality_metrics` AS
SELECT 
  scrape_date,
  COUNT(*) as total_records,
  ROUND(AVG(parsing_confidence), 3) as avg_confidence,
  COUNT(CASE WHEN parsing_confidence < 0.8 THEN 1 END) as low_confidence_count,
  COUNT(CASE WHEN data_quality_flags IS NOT NULL THEN 1 END) as flagged_records,
  COUNT(CASE WHEN return_date_parsed = FALSE AND return_date_original IS NOT NULL THEN 1 END) as unparseable_dates,
  COUNT(CASE WHEN team_abbr = 'UNK' THEN 1 END) as unknown_teams,
  COUNT(DISTINCT bdl_player_id) as unique_players,
  COUNT(DISTINCT team_abbr) as unique_teams
FROM `nba-props-platform.nba_raw.bdl_injuries`
GROUP BY scrape_date
ORDER BY scrape_date DESC;

-- Cross-validation comparison with NBA.com injury reports
CREATE OR REPLACE VIEW `nba-props-platform.nba_raw.injury_report_comparison` AS
SELECT 
  COALESCE(n.game_date, b.scrape_date) as report_date,
  COALESCE(n.player_lookup, b.player_lookup) as player_lookup,
  n.player_full_name as nba_name,
  b.player_full_name as bdl_name,
  n.injury_status as nba_status,
  b.injury_status_normalized as bdl_status,
  CASE 
    WHEN n.player_lookup IS NULL THEN 'BDL_ONLY'
    WHEN b.player_lookup IS NULL THEN 'NBA_ONLY' 
    WHEN n.injury_status != b.injury_status_normalized THEN 'STATUS_MISMATCH'
    ELSE 'MATCH'
  END as comparison_status,
  n.team as nba_team,
  b.team_abbr as bdl_team,
  b.parsing_confidence
FROM `nba-props-platform.nba_raw.nbac_injury_report` n
FULL OUTER JOIN `nba-props-platform.nba_raw.bdl_injuries_latest_daily` b
  ON n.player_lookup = b.player_lookup 
  AND DATE(n.game_date) = b.scrape_date
WHERE COALESCE(n.game_date, b.scrape_date) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- Index recommendations (BigQuery will auto-optimize, but good for documentation)
-- PRIMARY KEY: (scrape_date, bdl_player_id) - enforced by APPEND_ALWAYS strategy
-- PARTITION KEY: scrape_date - enables efficient date range queries  
-- CLUSTER KEYS: player_lookup, team_abbr, injury_status_normalized - optimizes joins and filters