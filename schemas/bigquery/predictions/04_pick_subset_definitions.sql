-- ============================================================================
-- Pick Subset Definitions Table
-- ============================================================================
-- Purpose: Define different subsets of picks for performance tracking
--
-- Each subset has a clear name, description, and SQL filter criteria.
-- This allows tracking performance for:
--   - Different confidence tiers
--   - Filtered vs unfiltered picks
--   - Website-published picks (best bets)
--   - Custom analysis subsets
--
-- Usage: Join with prediction_accuracy using the filter_sql criteria
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.pick_subset_definitions` (
  -- Identification
  subset_id STRING NOT NULL,                    -- Unique identifier (e.g., 'high_conf_filtered')
  subset_name STRING NOT NULL,                  -- Human-readable name for display
  subset_description STRING NOT NULL,           -- Detailed explanation of what's included/excluded

  -- Model/System Tracking (for multi-model support)
  system_id STRING,                             -- Which model this applies to (NULL = all models)
                                                -- e.g., 'catboost_v8', 'catboost_v9', 'ensemble_v2'

  -- Categorization
  subset_category STRING NOT NULL,              -- Category: 'confidence', 'publication', 'custom'
  display_order INT64,                          -- Order for UI display (1 = first)

  -- Filter Definition
  filter_sql STRING NOT NULL,                   -- SQL WHERE clause to apply
  filter_explanation STRING NOT NULL,           -- Plain English explanation of the filter

  -- Metadata
  is_active BOOL DEFAULT TRUE,                  -- Whether to include in reports
  is_primary BOOL DEFAULT FALSE,                -- Primary subset for headline metrics
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  created_by STRING DEFAULT 'system'
);

-- ============================================================================
-- Standard Subset Definitions
-- ============================================================================

-- Primary subset: What we actually recommend (filtered)
INSERT INTO `nba-props-platform.nba_predictions.pick_subset_definitions` VALUES (
  'actionable_filtered',
  'Actionable Picks (Filtered)',
  'All OVER/UNDER picks with real Vegas lines, excluding the known problem 88-90% confidence tier. This is what we actually recommend to users.',
  'confidence',
  1,
  "recommendation IN ('OVER', 'UNDER') AND has_prop_line = TRUE AND NOT (confidence_score >= 0.88 AND confidence_score < 0.90)",
  'OVER or UNDER picks with real lines, excluding 88-90% problem tier',
  TRUE,
  TRUE,  -- This is the primary metric
  CURRENT_TIMESTAMP(),
  CURRENT_TIMESTAMP(),
  'system'
);

-- All actionable (unfiltered for comparison)
INSERT INTO `nba-props-platform.nba_predictions.pick_subset_definitions` VALUES (
  'actionable_all',
  'All Actionable Picks (Unfiltered)',
  'All OVER/UNDER picks with real Vegas lines, including ALL confidence levels. Used as baseline for comparison.',
  'confidence',
  2,
  "recommendation IN ('OVER', 'UNDER') AND has_prop_line = TRUE",
  'All OVER or UNDER picks with real lines (no filtering)',
  TRUE,
  FALSE,
  CURRENT_TIMESTAMP(),
  CURRENT_TIMESTAMP(),
  'system'
);

-- Very high confidence (90%+)
INSERT INTO `nba-props-platform.nba_predictions.pick_subset_definitions` VALUES (
  'very_high_confidence',
  'Very High Confidence (90%+)',
  'Only picks where model confidence is 90% or higher. Historically the most reliable tier.',
  'confidence',
  3,
  "recommendation IN ('OVER', 'UNDER') AND has_prop_line = TRUE AND confidence_score >= 0.90",
  '90%+ confidence picks only',
  TRUE,
  FALSE,
  CURRENT_TIMESTAMP(),
  CURRENT_TIMESTAMP(),
  'system'
);

-- High confidence (70-90%, excluding problem tier)
INSERT INTO `nba-props-platform.nba_predictions.pick_subset_definitions` VALUES (
  'high_confidence_safe',
  'High Confidence (70-90%, Safe)',
  'Picks with 70-90% confidence, excluding the problematic 88-90% band that historically underperforms.',
  'confidence',
  4,
  "recommendation IN ('OVER', 'UNDER') AND has_prop_line = TRUE AND confidence_score >= 0.70 AND confidence_score < 0.90 AND NOT (confidence_score >= 0.88 AND confidence_score < 0.90)",
  '70-90% confidence, excluding 88-90% problem tier',
  TRUE,
  FALSE,
  CURRENT_TIMESTAMP(),
  CURRENT_TIMESTAMP(),
  'system'
);

-- Problem tier (for monitoring)
INSERT INTO `nba-props-platform.nba_predictions.pick_subset_definitions` VALUES (
  'problem_tier_88_90',
  'Problem Tier (88-90%) - Shadow',
  'The 88-90% confidence band that historically underperforms (~62% vs expected 74%+). Tracked for monitoring but NOT recommended.',
  'confidence',
  10,
  "recommendation IN ('OVER', 'UNDER') AND has_prop_line = TRUE AND confidence_score >= 0.88 AND confidence_score < 0.90",
  '88-90% confidence picks (known to underperform)',
  TRUE,
  FALSE,
  CURRENT_TIMESTAMP(),
  CURRENT_TIMESTAMP(),
  'system'
);

-- Website best bets (will be populated via published_picks table)
INSERT INTO `nba-props-platform.nba_predictions.pick_subset_definitions` VALUES (
  'website_best_bets',
  'Website Best Bets (Top 15)',
  'The top 15 picks shown on the website each day, ranked by composite score (confidence * edge * agreement). These are the picks users actually see.',
  'publication',
  5,
  "prediction_id IN (SELECT prediction_id FROM `nba-props-platform.nba_predictions.published_picks` WHERE publication_type = 'best_bets')",
  'Top 15 daily picks published to website',
  TRUE,
  FALSE,
  CURRENT_TIMESTAMP(),
  CURRENT_TIMESTAMP(),
  'system'
);

-- OVER picks only
INSERT INTO `nba-props-platform.nba_predictions.pick_subset_definitions` VALUES (
  'over_picks_only',
  'OVER Picks Only',
  'All OVER recommendations. Useful for analyzing if model performs differently on over vs under predictions.',
  'custom',
  20,
  "recommendation = 'OVER' AND has_prop_line = TRUE AND NOT (confidence_score >= 0.88 AND confidence_score < 0.90)",
  'OVER picks only (filtered)',
  TRUE,
  FALSE,
  CURRENT_TIMESTAMP(),
  CURRENT_TIMESTAMP(),
  'system'
);

-- UNDER picks only
INSERT INTO `nba-props-platform.nba_predictions.pick_subset_definitions` VALUES (
  'under_picks_only',
  'UNDER Picks Only',
  'All UNDER recommendations. UNDER picks in the 88-90% tier are particularly problematic.',
  'custom',
  21,
  "recommendation = 'UNDER' AND has_prop_line = TRUE AND NOT (confidence_score >= 0.88 AND confidence_score < 0.90)",
  'UNDER picks only (filtered)',
  TRUE,
  FALSE,
  CURRENT_TIMESTAMP(),
  CURRENT_TIMESTAMP(),
  'system'
);
