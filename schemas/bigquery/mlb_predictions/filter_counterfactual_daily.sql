-- Daily counterfactual hit rate per negative MLB filter.
-- Tracks what would have happened if each filter hadn't blocked picks.
-- Populated daily by mlb-filter-counterfactual-evaluator CF after grading completes.
--
-- MLB-specific: pulls actuals via JOIN of best_bets_filter_audit with
-- prediction_accuracy on (pitcher_lookup, game_date, recommendation, line_value).
-- NBA path uses best_bets_filtered_picks (a pre-joined table that doesn't exist
-- on the MLB side); the JOIN-at-query-time approach was chosen to avoid an
-- intermediate table just for CF computation.
--
-- Created: 2026-05-18

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_predictions.filter_counterfactual_daily` (
  game_date DATE NOT NULL,
  filter_name STRING NOT NULL,
  blocked_count INT64,
  wins INT64,
  losses INT64,
  pushes INT64,
  counterfactual_hr FLOAT64,
  computed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY filter_name;
