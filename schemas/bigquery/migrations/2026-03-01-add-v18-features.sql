-- Migration: Add V18 feature columns to ml_feature_store_v2
-- Session 379: Line movement + self-creation features
-- Run ONLY when V18 model is promoted to production
-- DO NOT run during shadow/experimentation phase

-- Feature 60: line_movement_direction (DraftKings closing - opening line)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS feature_60_value FLOAT64 OPTIONS (description='Value for feature 60 (line_movement_direction). closing_line - opening_line (DraftKings). NULL if missing.'),
ADD COLUMN IF NOT EXISTS feature_60_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 60 (line_movement_direction)'),
ADD COLUMN IF NOT EXISTS feature_60_source STRING OPTIONS (description='Source for feature 60 (line_movement_direction): vegas, missing, default');

-- Feature 61: vig_skew (avg over_price - under_price across books)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS feature_61_value FLOAT64 OPTIONS (description='Value for feature 61 (vig_skew). avg(over_price - under_price) across books excluding Bovada. NULL if missing.'),
ADD COLUMN IF NOT EXISTS feature_61_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 61 (vig_skew)'),
ADD COLUMN IF NOT EXISTS feature_61_source STRING OPTIONS (description='Source for feature 61 (vig_skew): vegas, missing, default');

-- Feature 62: self_creation_rate (rolling 10-game avg of unassisted_fg / fg)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS feature_62_value FLOAT64 OPTIONS (description='Value for feature 62 (self_creation_rate). Rolling 10-game avg of unassisted_fg_makes / fg_makes [0-1]. NULL if missing.'),
ADD COLUMN IF NOT EXISTS feature_62_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 62 (self_creation_rate)'),
ADD COLUMN IF NOT EXISTS feature_62_source STRING OPTIONS (description='Source for feature 62 (self_creation_rate): calculated, missing, default');

-- Feature 63: late_line_movement_count (LINE_MOVED events in last 4h before tipoff)
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS feature_63_value FLOAT64 OPTIONS (description='Value for feature 63 (late_line_movement_count). Count of LINE_MOVED events within 240 min before tipoff. NULL if missing.'),
ADD COLUMN IF NOT EXISTS feature_63_quality FLOAT64 OPTIONS (description='Quality 0-100 for feature 63 (late_line_movement_count)'),
ADD COLUMN IF NOT EXISTS feature_63_source STRING OPTIONS (description='Source for feature 63 (late_line_movement_count): vegas, missing, default');
