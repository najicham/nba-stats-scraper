-- v_bb_candidate_signal_stream
-- Measurement-infrastructure Component 1 (2026-07). Canonical, deduped stream
-- of every best-bets candidate and its FINAL disposition, graded — the source
-- of truth for the two-tier shadow-signal promotion tracker (C4).
--
-- WHY: at realized volume (~3.4 published picks/day) the published-only
-- promotion gates take 150-430 days to resolve. This view widens the evidence
-- base ~4-6x by unioning published picks with the picks that were filtered or
-- lost the per-model merge — all already evaluated against the FULL signal
-- registry (incl. SHADOW_SIGNALS) before the aggregator ran. C1's aggregator
-- edge (ml/signals/aggregator.py::_record_filtered) makes the filtered leg
-- carry full shadow tags; this view assembles + grades the stream.
--
-- Grain: (game_date, player_lookup, recommendation) — one row per candidate,
-- deduped to its final disposition (published > retracted > merge_rejected >
-- filtered).
--
-- Legs:
--   1. signal_best_bets_picks   -> 'published' | 'retracted' (retracted_at set)
--   2. best_bets_filtered_picks -> 'filtered'  (aggregated across all filter rows)
--   3. model_bb_candidates      -> 'merge_rejected' (was_selected = FALSE)
--
-- block_reason (filtered leg only): a blocking-class filter reason for the
-- candidate. Observation-mode filters (which do NOT drop the pick) are
-- identified by the '_obs' suffix convention plus a small explicit set of
-- known non-suffixed observation filters. all_filter_reasons carries the FULL
-- list unconditionally and is authoritative; block_reason is a convenience
-- field. The rigorous obs/blocking + Class-A/Class-B split is pre-registered
-- in C3 (shared/registry/*.yaml); keep this list in sync when it lands.
--
-- Grading: line-accurate at the stream row's own line_value/recommendation via
-- actual points from COALESCE(leg pre-grade, prediction_accuracy_deduped,
-- player_game_summary). prediction_accuracy_deduped is the Session-493 dedup
-- view; player_game_summary is the actuals fallback. Pushes -> NULL.

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_bb_candidate_signal_stream` AS
WITH
-- Leg 1: published / retracted picks -------------------------------------------
published AS (
  SELECT
    game_date,
    player_lookup,
    recommendation,
    CASE WHEN retracted_at IS NOT NULL THEN 'retracted' ELSE 'published' END AS disposition,
    CASE WHEN retracted_at IS NOT NULL THEN 1 ELSE 0 END AS disp_rank,
    system_id,
    player_name,
    team_abbr,
    opponent_team_abbr,
    CAST(predicted_points AS FLOAT64) AS predicted_points,
    CAST(line_value AS FLOAT64) AS line_value,
    CAST(edge AS FLOAT64) AS edge,
    CAST(signal_count AS INT64) AS signal_count,
    CAST(real_signal_count AS INT64) AS real_signal_count,
    signal_tags,
    CAST(NULL AS STRING) AS block_reason,
    CAST([] AS ARRAY<STRING>) AS all_filter_reasons,
    CAST(actual_points AS FLOAT64) AS leg_actual_points,
    algorithm_version
  FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
),
-- Leg 2: filtered picks, aggregated to grain ----------------------------------
-- (ARRAY_CONCAT_AGG can't be nested in UNNEST, so aggregate first then dedup.)
filtered_agg AS (
  SELECT
    game_date,
    player_lookup,
    recommendation,
    ANY_VALUE(system_id) AS system_id,
    ANY_VALUE(team_abbr) AS team_abbr,
    ANY_VALUE(opponent_team_abbr) AS opponent_team_abbr,
    CAST(ANY_VALUE(predicted_points) AS FLOAT64) AS predicted_points,
    CAST(ANY_VALUE(line_value) AS FLOAT64) AS line_value,
    CAST(MAX(edge) AS FLOAT64) AS edge,
    CAST(MAX(signal_count) AS INT64) AS signal_count,
    ARRAY_CONCAT_AGG(signal_tags) AS signal_tags_raw,
    -- block_reason: a blocking-class (non-observation) filter reason if any
    -- fired, else fall back to any recorded reason.
    COALESCE(
      MIN(IF(
        NOT (filter_reason LIKE '%\\_obs'
             OR filter_reason IN ('low_variance_under_block', 'hse_rescue_floor')),
        filter_reason, NULL)),
      ANY_VALUE(filter_reason)
    ) AS block_reason,
    ARRAY_AGG(DISTINCT filter_reason IGNORE NULLS) AS all_filter_reasons,
    CAST(ANY_VALUE(actual_points) AS FLOAT64) AS leg_actual_points
  FROM `nba-props-platform.nba_predictions.best_bets_filtered_picks`
  GROUP BY game_date, player_lookup, recommendation
),
filtered AS (
  SELECT
    game_date,
    player_lookup,
    recommendation,
    'filtered' AS disposition,
    3 AS disp_rank,
    system_id,
    CAST(NULL AS STRING) AS player_name,
    team_abbr,
    opponent_team_abbr,
    predicted_points,
    line_value,
    edge,
    signal_count,
    CAST(NULL AS INT64) AS real_signal_count,
    ARRAY(SELECT DISTINCT t FROM UNNEST(signal_tags_raw) AS t WHERE t IS NOT NULL) AS signal_tags,
    block_reason,
    all_filter_reasons,
    leg_actual_points,
    CAST(NULL AS STRING) AS algorithm_version
  FROM filtered_agg
),
-- Leg 3: per-model candidates that lost the merge ------------------------------
merge_rejected AS (
  SELECT
    game_date,
    player_lookup,
    recommendation,
    'merge_rejected' AS disposition,
    2 AS disp_rank,
    system_id,
    player_name,
    team_abbr,
    opponent_team_abbr,
    CAST(predicted_points AS FLOAT64) AS predicted_points,
    CAST(line_value AS FLOAT64) AS line_value,
    CAST(edge AS FLOAT64) AS edge,
    CAST(signal_count AS INT64) AS signal_count,
    CAST(real_signal_count AS INT64) AS real_signal_count,
    signal_tags,
    CAST(NULL AS STRING) AS block_reason,
    CAST([] AS ARRAY<STRING>) AS all_filter_reasons,
    CAST(NULL AS FLOAT64) AS leg_actual_points,
    algorithm_version
  FROM `nba-props-platform.nba_predictions.model_bb_candidates`
  WHERE was_selected = FALSE
),
unioned AS (
  SELECT * FROM published
  UNION ALL SELECT * FROM filtered
  UNION ALL SELECT * FROM merge_rejected
),
-- Dedup to final disposition per candidate ------------------------------------
deduped AS (
  SELECT * EXCEPT(rn)
  FROM (
    SELECT *,
      ROW_NUMBER() OVER (
        PARTITION BY game_date, player_lookup, recommendation
        ORDER BY disp_rank, edge DESC
      ) AS rn
    FROM unioned
  )
  WHERE rn = 1
)
-- Grade ------------------------------------------------------------------------
SELECT
  d.game_date,
  d.player_lookup,
  d.recommendation,
  d.disposition,
  d.system_id,
  d.player_name,
  d.team_abbr,
  d.opponent_team_abbr,
  d.predicted_points,
  d.line_value,
  d.edge,
  d.signal_count,
  d.real_signal_count,
  d.signal_tags,
  d.block_reason,
  d.all_filter_reasons,
  d.algorithm_version,
  actual.actual_points,
  actual.grade_source,
  CASE
    WHEN actual.actual_points IS NULL OR d.line_value IS NULL THEN NULL
    WHEN actual.actual_points = d.line_value THEN NULL  -- push
    WHEN d.recommendation = 'OVER'  THEN actual.actual_points > d.line_value
    WHEN d.recommendation = 'UNDER' THEN actual.actual_points < d.line_value
    ELSE NULL
  END AS pick_correct
FROM deduped d
LEFT JOIN (
  SELECT game_date, player_lookup, ANY_VALUE(actual_points) AS actual_points
  FROM `nba-props-platform.nba_predictions.prediction_accuracy_deduped`
  WHERE actual_points IS NOT NULL
  GROUP BY game_date, player_lookup
) pa
  ON pa.game_date = d.game_date AND pa.player_lookup = d.player_lookup
LEFT JOIN (
  SELECT game_date, player_lookup, ANY_VALUE(points) AS points
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE points IS NOT NULL AND (is_dnp IS NULL OR is_dnp = FALSE)
  GROUP BY game_date, player_lookup
) pgs
  ON pgs.game_date = d.game_date AND pgs.player_lookup = d.player_lookup
LEFT JOIN UNNEST([STRUCT(
  COALESCE(d.leg_actual_points, pa.actual_points, pgs.points) AS actual_points,
  CASE
    WHEN d.leg_actual_points IS NOT NULL THEN 'leg'
    WHEN pa.actual_points IS NOT NULL THEN 'prediction_accuracy'
    WHEN pgs.points IS NOT NULL THEN 'player_game_summary'
    ELSE NULL
  END AS grade_source
)]) AS actual
