-- MLB Stadium Weather
-- Source: OpenWeatherMap API
-- Processor: MlbWeatherProcessor
-- Updated: daily (pre-game snapshot)

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.mlb_weather` (
  scrape_date DATE NOT NULL,
  team_abbr STRING NOT NULL,
  stadium_name STRING,
  is_dome BOOL,
  temperature_f FLOAT64,
  feels_like_f FLOAT64,
  humidity_pct INT64,
  wind_speed_mph FLOAT64,
  wind_direction_deg INT64,
  wind_gust_mph FLOAT64,
  conditions STRING,
  description STRING,
  clouds_pct INT64,
  pressure_hpa FLOAT64,
  visibility_m INT64,
  k_weather_factor FLOAT64,
  source_file_path STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY scrape_date
CLUSTER BY team_abbr
OPTIONS (
  description = "MLB stadium weather snapshots. Source: OpenWeatherMap.",
  require_partition_filter = true
);
