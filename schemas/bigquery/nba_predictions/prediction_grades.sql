-- ============================================================================
-- Table: prediction_grades
-- File: prediction_grades.sql
-- Purpose: Grades NBA predictions against actual results
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.prediction_grades` (
  -- Identifiers
  prediction_id STRING NOT NULL,                    -- FK to player_prop_predictions
  player_lookup STRING NOT NULL,
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,                          -- Partition key
  system_id STRING NOT NULL,                        -- Which system made this prediction

  -- Prediction details (captured at time of grading)
  predicted_points NUMERIC(5,1) NOT NULL,           -- What was predicted
  confidence_score NUMERIC(5,2) NOT NULL,           -- Confidence (0-1)
  recommendation STRING NOT NULL,                   -- OVER, UNDER, PASS
  points_line NUMERIC(4,1),                         -- The betting line used

  -- Actual results
  actual_points INT64,                              -- What actually happened
  actual_vs_line STRING,                            -- OVER, UNDER, PUSH

  -- Grading results
  prediction_correct BOOL,                          -- TRUE if correct, FALSE if wrong, NULL if PUSH/ungradeable
  margin_of_error NUMERIC(5,2),                     -- |predicted - actual|
  line_margin NUMERIC(5,2),                         -- actual - line (how far from line)

  -- Data quality and metadata
  graded_at TIMESTAMP NOT NULL,                     -- When grading occurred
  grading_version STRING NOT NULL,                  -- Grading algorithm version
  data_quality_tier STRING,                         -- gold, silver, bronze from actuals
  has_issues BOOL NOT NULL,                         -- TRUE if grading had problems
  issues ARRAY<STRING>,                             -- List of issues (missing_actuals, dnp, etc)

  -- Additional context
  minutes_played INT64,                             -- NULL if player DNP
  player_dnp BOOL,                                  -- TRUE if player did not play

  -- Indexing notes:
  -- Partitioned by game_date for efficient date range queries
  -- Clustered by player_lookup, prediction_correct, confidence_score for accuracy analysis
)
PARTITION BY game_date
CLUSTER BY player_lookup, prediction_correct, confidence_score;
