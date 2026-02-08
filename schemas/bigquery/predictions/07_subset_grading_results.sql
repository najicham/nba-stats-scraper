-- Session 153: Subset grading results table
--
-- Stores grading results per subset per game date, using materialized subset
-- membership from current_subset_picks. This grades what was ACTUALLY in
-- each subset at game time, not retroactive recomputation.
--
-- Populated by SubsetGradingProcessor after PredictionAccuracyProcessor runs.
--
-- Usage:
--   bq query --use_legacy_sql=false < schemas/bigquery/predictions/07_subset_grading_results.sql

CREATE TABLE IF NOT EXISTS nba_predictions.subset_grading_results (
    game_date DATE NOT NULL,
    subset_id STRING NOT NULL,
    subset_name STRING,
    graded_at TIMESTAMP NOT NULL,
    version_id STRING,                  -- Which version of the subset was graded

    -- Volume
    total_picks INT64,
    graded_picks INT64,                 -- Picks with actual results (excludes pushes/DNP)
    voided_picks INT64,                 -- DNP/voided picks

    -- Win/Loss
    wins INT64,
    losses INT64,
    pushes INT64,
    hit_rate FLOAT64,                   -- wins / graded_picks * 100

    -- ROI (at -110 odds)
    roi FLOAT64,                        -- (wins * 0.909 - losses) / graded_picks * 100
    units_won FLOAT64,                  -- wins * 0.909 - losses

    -- Quality
    avg_edge FLOAT64,
    avg_confidence FLOAT64,
    mae FLOAT64,                        -- Mean absolute error

    -- Directional breakdown
    over_picks INT64,
    over_wins INT64,
    under_picks INT64,
    under_wins INT64
)
PARTITION BY game_date
CLUSTER BY subset_id;
