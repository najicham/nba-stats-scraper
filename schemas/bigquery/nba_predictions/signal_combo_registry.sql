-- ============================================================================
-- Signal Combo Registry Table Schema
-- ============================================================================
-- Dataset: nba_predictions
-- Table: signal_combo_registry
-- Purpose: Registry of validated signal combinations with classification,
--          performance stats, and scoring weights. Drives combo-aware
--          scoring in the aggregator (replaces hardcoded bonuses).
-- Created: 2026-02-15 (Session 259)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.signal_combo_registry` (
  combo_id STRING NOT NULL,              -- Canonical sorted key: "high_edge+minutes_surge"
  display_name STRING,                   -- Human-readable: "High Edge + Minutes Surge"
  signals ARRAY<STRING>,                 -- Component signals: ["high_edge", "minutes_surge"]
  cardinality INT64,                     -- Number of component signals
  classification STRING NOT NULL,        -- SYNERGISTIC | ANTI_PATTERN | NEUTRAL
  status STRING NOT NULL,                -- PRODUCTION | CONDITIONAL | WATCH | BLOCKED
  direction_filter STRING,               -- OVER_ONLY | UNDER_ONLY | BOTH
  conditional_filters STRING,            -- JSON: {"is_home": true, "exclude_positions": ["C"]}
  hit_rate FLOAT64,                      -- Aggregate hit rate (e.g., 79.4)
  roi FLOAT64,                           -- Return on investment (e.g., 58.8)
  sample_size INT64,                     -- Number of graded picks
  synergy_bonus FLOAT64,                 -- HR above best individual component
  score_weight FLOAT64,                  -- Weight used in aggregator composite score
  notes STRING,                          -- Free text context
  last_validated DATE,                   -- Date combo stats were last validated
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
OPTIONS (
  description='Registry of validated signal combinations. Drives combo-aware scoring in aggregator. '
              'Classification: SYNERGISTIC (bonus), ANTI_PATTERN (block/penalty), NEUTRAL (no effect). '
              'Status: PRODUCTION (active), CONDITIONAL (with filters), WATCH (tracking), BLOCKED (excluded).'
);

-- ============================================================================
-- Seed data from Session 257 comprehensive signal testing
-- ============================================================================

INSERT INTO `nba-props-platform.nba_predictions.signal_combo_registry`
  (combo_id, display_name, signals, cardinality, classification, status,
   direction_filter, conditional_filters, hit_rate, roi, sample_size,
   synergy_bonus, score_weight, notes, last_validated)
VALUES
  -- Premium 3-way combo: 88.9% HR
  ('edge_spread_optimal+high_edge+minutes_surge',
   'Edge Spread + High Edge + Minutes Surge (3-Way)',
   ['edge_spread_optimal', 'high_edge', 'minutes_surge'], 3,
   'SYNERGISTIC', 'PRODUCTION', 'BOTH', NULL,
   88.9, NULL, 17, 31.2, 2.5,
   'Session 257: Premium combo. ESO gate filters false positives from 2-way combo.',
   '2026-02-14'),

  -- High Edge + Minutes Surge: 79.4% HR
  ('high_edge+minutes_surge',
   'High Edge + Minutes Surge',
   ['high_edge', 'minutes_surge'], 2,
   'SYNERGISTIC', 'PRODUCTION', 'OVER_ONLY', NULL,
   79.4, 58.8, 34, 20.0, 2.0,
   'Session 257: Minutes surge confirms edge backed by real playing time increase.',
   '2026-02-14'),

  -- Cold Snap (standalone + home): 93.3% HR
  ('cold_snap',
   'Cold Snap (Home Only)',
   ['cold_snap'], 1,
   'SYNERGISTIC', 'CONDITIONAL', 'OVER_ONLY',
   '{"is_home": true}',
   93.3, NULL, 15, NULL, 1.5,
   'Session 257: 93.3% home vs 31.3% away. HOME filter already in signal code.',
   '2026-02-14'),

  -- 3PT Bounce (guards + home): 69.0% HR
  ('3pt_bounce',
   '3PT Bounce (Guards + Home)',
   ['3pt_bounce'], 1,
   'SYNERGISTIC', 'CONDITIONAL', 'OVER_ONLY',
   '{"is_home": true, "positions": ["G", "G-F", "F-G"]}',
   69.0, NULL, 29, NULL, 1.0,
   'Session 257: Guards+home conditional. Filters in signal code.',
   '2026-02-14'),

  -- Blowout Recovery (no centers, no B2B): 58.0% HR
  ('blowout_recovery',
   'Blowout Recovery (No C, No B2B)',
   ['blowout_recovery'], 1,
   'SYNERGISTIC', 'WATCH', 'OVER_ONLY',
   '{"exclude_positions": ["C"], "min_rest_days": 2}',
   58.0, NULL, 50, NULL, 0.5,
   'Session 258: -3.6% delta within best bets. Tracking for improvement. C exclusion + B2B exclusion applied.',
   '2026-02-14'),

  -- ANTI-PATTERN: Edge Spread + High Edge (no minutes surge): 31.3% HR
  ('edge_spread_optimal+high_edge',
   'Edge Spread + High Edge (Redundancy Trap)',
   ['edge_spread_optimal', 'high_edge'], 2,
   'ANTI_PATTERN', 'BLOCKED', 'BOTH', NULL,
   31.3, NULL, 16, NULL, -2.0,
   'Session 257: Redundancy trap. Both signals measure same thing (edge magnitude). No minutes surge = no real confirmation.',
   '2026-02-14'),

  -- ANTI-PATTERN: High Edge standalone (no other signals): 43.8% HR
  ('high_edge',
   'High Edge (Standalone)',
   ['high_edge'], 1,
   'ANTI_PATTERN', 'BLOCKED', 'BOTH', NULL,
   43.8, NULL, 16, NULL, -1.0,
   'Session 257: 1-signal picks hit 43.8%. High edge alone below breakeven without confirmation.',
   '2026-02-14');
