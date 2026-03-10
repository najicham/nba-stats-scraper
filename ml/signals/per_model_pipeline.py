"""Per-model pipeline runner for best bets.

Session 443: Each model runs the full BB filter/signal stack independently.
Results feed into the merge layer (pipeline_merger.py).

Architecture:
    1. build_shared_context() — one-time BQ queries for model-independent data
       (~12 queries total: predictions for ALL models, 10 satellite queries,
       model health, regime context, etc.)
    2. run_single_model_pipeline() — pure Python per-model: signals + aggregator
    3. run_all_model_pipelines() — orchestrator: build context, fan out per model

Key optimization: ALL models' predictions are fetched in a single BQ scan
(no ROW_NUMBER dedup), then partitioned by system_id in Python.
Supplemental data (satellite queries) is player-level, not model-specific,
so it's computed once and shared across all model runs.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

from google.cloud import bigquery

from ml.signals.aggregator import BestBetsAggregator
from ml.signals.combo_registry import load_combo_registry
from ml.signals.model_health import BREAKEVEN_HR
from ml.signals.player_blacklist import compute_player_blacklist, compute_player_under_suppression
from ml.signals.model_direction_affinity import compute_model_direction_affinities
from ml.signals.model_profile_loader import load_model_profiles
from ml.signals.regime_context import get_regime_context, get_market_compression
from ml.signals.registry import SignalRegistry, build_default_registry
from ml.signals.signal_health import get_signal_health_summary
from ml.signals.supplemental_data import (
    query_games_vs_opponent,
    query_model_health,
)
from shared.config.cross_model_subsets import (
    build_system_id_sql_filter,
    classify_system_id,
)

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SharedContext:
    """Model-independent data computed once per date.

    Contains all the BQ query results that are shared across every model's
    pipeline run. Built by build_shared_context().
    """

    target_date: str

    # Predictions keyed by system_id -> list of pred dicts
    # (no ROW_NUMBER dedup — every model's predictions preserved)
    all_predictions: Dict[str, List[Dict]] = field(default_factory=dict)

    # Supplemental data keyed by player_lookup -> enrichment dict
    supplemental_map: Dict[str, Dict] = field(default_factory=dict)

    # Per-model 7d hit rate at edge 3+: system_id -> float or None
    model_health_map: Dict[str, Optional[float]] = field(default_factory=dict)

    # Default model health (champion model)
    default_model_health_hr: Optional[float] = None

    # Signal health: signal_tag -> {hr_7d, hr_season, regime, status}
    signal_health: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Combo registry for aggregator
    combo_registry: Optional[Dict] = None

    # Player blacklist: set of player_lookup strings
    player_blacklist: Set[str] = field(default_factory=set)
    blacklist_stats: Dict[str, Any] = field(default_factory=dict)

    # Session 451: Player UNDER suppression — direction-specific poor performers
    player_under_suppression: Set[str] = field(default_factory=set)

    # Model-direction affinity blocks
    model_direction_blocks: Set[tuple] = field(default_factory=set)
    model_direction_affinity_stats: Dict[str, Any] = field(default_factory=dict)

    # Model profile store
    model_profile_store: Any = None

    # Regime context
    regime_context: Dict[str, Any] = field(default_factory=dict)

    # Games vs opponent map: (player_lookup, opponent) -> count
    games_vs_opponent: Dict[tuple, int] = field(default_factory=dict)

    # Runtime demoted filters from filter_overrides table
    runtime_demoted_filters: Set[str] = field(default_factory=set)

    # Direction health (observation-only)
    direction_health: Dict[str, Any] = field(default_factory=dict)

    # Opponent stars out: team_abbr -> count
    opponent_stars_out: Dict[str, int] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Output of a single model's pipeline run."""

    system_id: str
    candidates: List[Dict]  # Picks that survived filters
    all_predictions: List[Dict]  # All predictions for this model (pre-filter)
    filter_summary: Dict  # Per-filter rejection counts
    signal_results: Dict[str, List]  # key -> list of SignalResults


# ---------------------------------------------------------------------------
# Batch prediction query (no ROW_NUMBER dedup)
# ---------------------------------------------------------------------------

def _query_all_model_predictions(
    bq_client: bigquery.Client,
    target_date: str,
    include_disabled: bool = False,
) -> Tuple[Dict[str, List[Dict]], Dict[str, Dict]]:
    """Query predictions for ALL models in a single BQ scan.

    Unlike query_predictions_with_supplements(multi_model=True), this does NOT
    apply ROW_NUMBER per-player dedup. Every model's prediction is preserved
    so each model can be run through the pipeline independently.

    Also runs the 10 satellite queries for supplemental data (player-level,
    model-independent) and returns the supplemental_map.

    Args:
        bq_client: BigQuery client.
        target_date: YYYY-MM-DD date string.
        include_disabled: If True, skip disabled_models filter (for historical replay).

    Returns:
        Tuple of:
            predictions_by_model: Dict[system_id, List[Dict]]
            supplemental_map: Dict[player_lookup, Dict]
    """
    system_filter = build_system_id_sql_filter('p')

    # For replay: skip disabled_models filter so historical models are included
    if include_disabled:
        disabled_cte = "disabled_models AS (SELECT CAST(NULL AS STRING) AS model_id FROM UNNEST([]) AS x)"
        disabled_join = ""
        disabled_where = ""
    else:
        disabled_cte = f"""disabled_models AS (
      SELECT model_id
      FROM `{PROJECT_ID}.nba_predictions.model_registry`
      WHERE enabled = FALSE OR status IN ('blocked', 'disabled')
    )"""
        disabled_join = "LEFT JOIN disabled_models dm ON p.system_id = dm.model_id"
        disabled_where = "AND dm.model_id IS NULL"

    # Build the same CTE structure as multi_model path but WITHOUT QUALIFY
    query = f"""
    -- Session 443: Per-model pipeline — fetch ALL models without dedup
    WITH {disabled_cte},

    model_hr AS (
      SELECT
        model_id,
        rolling_hr_14d AS hr_14d,
        rolling_n_14d AS n_14d,
        best_bets_hr_21d AS bb_hr_21d,
        best_bets_n_21d AS bb_n_21d
      FROM `{PROJECT_ID}.nba_predictions.model_performance_daily`
      WHERE game_date = (
        SELECT MAX(game_date) FROM `{PROJECT_ID}.nba_predictions.model_performance_daily`
        WHERE game_date < @target_date
      )
    ),

    preds AS (
      SELECT
        p.player_lookup,
        p.game_id,
        p.game_date,
        p.system_id,
        CAST(p.predicted_points AS FLOAT64) AS predicted_points,
        CAST(p.current_points_line AS FLOAT64) AS line_value,
        p.recommendation,
        CAST(p.predicted_points - p.current_points_line AS FLOAT64) AS edge,
        CAST(p.confidence_score AS FLOAT64) AS confidence_score,
        COALESCE(p.feature_quality_score, 0) AS feature_quality_score,
        LEAST(1.0, COALESCE(
          CASE WHEN mh.bb_n_21d >= 8 THEN mh.bb_hr_21d ELSE NULL END,
          CASE WHEN mh.n_14d >= 10 THEN mh.hr_14d ELSE NULL END,
          50.0
        ) / 55.0) AS model_hr_weight
      FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions` p
      LEFT JOIN model_hr mh ON mh.model_id = p.system_id
      {disabled_join}
      WHERE p.game_date = @target_date
        AND {system_filter}
        AND p.is_active = TRUE
        AND p.is_actionable = TRUE
        AND p.recommendation IN ('OVER', 'UNDER')
        AND p.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
        {disabled_where}
      -- NO QUALIFY ROW_NUMBER — keep ALL models' predictions
    ),

    -- Rolling stats for 3PT and minutes signals
    game_stats AS (
      SELECT
        player_lookup,
        game_date,
        minutes_played,
        player_full_name,
        team_abbr,
        opponent_team_abbr,
        AVG(SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS three_pct_last_3,
        AVG(SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS three_pct_season,
        STDDEV(SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS three_pct_std,
        AVG(CAST(three_pt_attempts AS FLOAT64))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS three_pa_per_game,
        AVG(minutes_played)
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS minutes_avg_last_3,
        AVG(minutes_played)
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS minutes_avg_season,
        SAFE_DIVIDE(fg_makes, NULLIF(fg_attempts, 0)) AS fg_pct,
        AVG(SAFE_DIVIDE(fg_makes, NULLIF(fg_attempts, 0)))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS fg_pct_last_3,
        AVG(SAFE_DIVIDE(fg_makes, NULLIF(fg_attempts, 0)))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS fg_pct_season,
        STDDEV(SAFE_DIVIDE(fg_makes, NULLIF(fg_attempts, 0)))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS fg_pct_std,
        starter_flag,
        AVG(CAST(points AS FLOAT64))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS points_avg_season,
        AVG(usage_rate)
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS usage_avg_season,
        AVG(CAST(ft_attempts AS FLOAT64))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS fta_season,
        -- Session 463: FTA variance for ft_anomaly signals
        AVG(CAST(ft_attempts AS FLOAT64))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) AS fta_avg_last_10,
        SAFE_DIVIDE(
          STDDEV(CAST(ft_attempts AS FLOAT64))
            OVER (PARTITION BY player_lookup ORDER BY game_date
                  ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING),
          NULLIF(AVG(CAST(ft_attempts AS FLOAT64))
            OVER (PARTITION BY player_lookup ORDER BY game_date
                  ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING), 0)
        ) AS fta_cv_last_10,
        AVG(CAST(unassisted_fg_makes AS FLOAT64))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS unassisted_fg_season,
        STDDEV(CAST(points AS FLOAT64))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS points_std_last_5,
        SAFE_DIVIDE(
          SUM(ft_attempts) OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),
          SUM(fg_attempts) OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
        ) AS ft_rate_season,
        AVG(CAST(starter_flag AS INT64)) OVER (PARTITION BY player_lookup ORDER BY game_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS starter_rate_season,
        AVG(SAFE_DIVIDE(unassisted_fg_makes, NULLIF(fg_makes, 0)))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) AS self_creation_rate_last_10,
        plus_minus,
        LAG(CASE WHEN plus_minus < 0 THEN 1 ELSE 0 END, 1)
          OVER (PARTITION BY player_lookup ORDER BY game_date) AS neg_pm_1,
        LAG(CASE WHEN plus_minus < 0 THEN 1 ELSE 0 END, 2)
          OVER (PARTITION BY player_lookup ORDER BY game_date) AS neg_pm_2,
        LAG(CASE WHEN plus_minus < 0 THEN 1 ELSE 0 END, 3)
          OVER (PARTITION BY player_lookup ORDER BY game_date) AS neg_pm_3
      FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
      WHERE game_date >= '2025-10-22'
        AND minutes_played > 0
    ),

    latest_stats AS (
      SELECT gs.*
      FROM game_stats gs
      INNER JOIN (SELECT DISTINCT player_lookup FROM preds) dp
        ON gs.player_lookup = dp.player_lookup
      WHERE gs.game_date < @target_date
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY gs.player_lookup ORDER BY gs.game_date DESC
      ) = 1
    ),

    -- Streak data: use champion model system_id for prior outcomes.
    -- Per-model streak would require N separate queries — use a single
    -- representative model (any V12 noveg MAE). Signals that use streak
    -- data are contextual, not model-specific.
    streak_source AS (
      SELECT DISTINCT system_id
      FROM preds
      WHERE system_id LIKE 'catboost_v12_noveg_train%'
      LIMIT 1
    ),

    streak_data AS (
      SELECT
        player_lookup,
        game_date,
        LAG(CAST(prediction_correct AS INT64), 1) OVER w AS prev_correct_1,
        LAG(CAST(prediction_correct AS INT64), 2) OVER w AS prev_correct_2,
        LAG(CAST(prediction_correct AS INT64), 3) OVER w AS prev_correct_3,
        LAG(CAST(prediction_correct AS INT64), 4) OVER w AS prev_correct_4,
        LAG(CAST(prediction_correct AS INT64), 5) OVER w AS prev_correct_5,
        LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 1) OVER w AS prev_over_1,
        LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 2) OVER w AS prev_over_2,
        LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 3) OVER w AS prev_over_3,
        LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 4) OVER w AS prev_over_4,
        LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 5) OVER w AS prev_over_5
      FROM (
        SELECT pa.*
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy` pa
        CROSS JOIN streak_source ss
        WHERE pa.game_date >= '2025-10-22'
          AND pa.system_id = ss.system_id
          AND pa.prediction_correct IS NOT NULL
          AND pa.is_voided IS NOT TRUE
          AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY pa.player_lookup, pa.game_id ORDER BY pa.graded_at DESC
        ) = 1
      )
      WINDOW w AS (PARTITION BY player_lookup ORDER BY game_date)
    ),

    latest_streak AS (
      SELECT sd.*
      FROM streak_data sd
      INNER JOIN (SELECT DISTINCT player_lookup FROM preds) dp
        ON sd.player_lookup = dp.player_lookup
      WHERE sd.game_date < @target_date
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY sd.player_lookup ORDER BY sd.game_date DESC
      ) = 1
    ),

    -- V12 noveg MAE predictions for cross-model consensus scoring
    v12_preds AS (
      SELECT
        p2.player_lookup,
        p2.game_id,
        p2.recommendation AS v12_recommendation,
        CAST(p2.predicted_points - p2.current_points_line AS FLOAT64) AS v12_edge,
        CAST(p2.predicted_points AS FLOAT64) AS v12_predicted_points,
        CAST(p2.confidence_score AS FLOAT64) AS v12_confidence
      FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions` p2
      WHERE p2.game_date = @target_date
        AND (p2.system_id LIKE 'catboost_v12_noveg%' AND p2.system_id NOT LIKE '%_q4%' AND p2.system_id NOT LIKE '%_q5%'
            AND p2.system_id NOT LIKE '%_q6%' AND p2.system_id NOT LIKE '%_classify%'
            AND p2.system_id NOT LIKE '%_star%' AND p2.system_id NOT LIKE '%_starter%' AND p2.system_id NOT LIKE '%_role%')
        AND p2.is_active = TRUE
        AND p2.is_actionable = TRUE
        AND p2.recommendation IN ('OVER', 'UNDER')
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY p2.player_lookup, p2.game_id ORDER BY p2.system_id DESC
      ) = 1
    ),

    -- Feature store values (player-level, model-independent)
    book_stats AS (
      SELECT
        player_lookup,
        game_date,
        feature_50_value AS multi_book_line_std,
        feature_50_source AS book_std_source,
        feature_47_value AS teammate_usage_available,
        feature_37_value AS star_teammates_out,
        feature_52_value AS prop_under_streak,
        feature_42_value AS implied_team_total,
        feature_18_value AS opponent_pace,
        feature_3_value AS points_std_last_10,
        feature_0_value AS points_avg_last_5,
        feature_1_value AS points_avg_last_10,
        feature_29_value AS avg_pts_vs_opp,
        feature_30_value AS games_vs_opp,
        feature_40_value AS minutes_load_7d,
        feature_43_value AS pts_avg_last3,
        feature_44_value AS trend_slope,
        feature_48_value AS usage_rate_l5,
        feature_57_value AS blowout_risk,
        feature_41_value AS spread_magnitude,
        feature_53_value AS prop_over_streak,
        feature_55_value AS over_rate_last_10
      FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
      WHERE game_date = @target_date
    ),

    -- Previous game prop line for line delta signal
    prev_prop_lines AS (
      SELECT
        pp.player_lookup,
        CAST(pp.current_points_line AS FLOAT64) AS prev_line_value,
        pp.game_date AS prev_line_date
      FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions` pp
      WHERE pp.game_date >= DATE_SUB(@target_date, INTERVAL 14 DAY)
        AND pp.game_date < @target_date
        AND pp.is_active = TRUE
        AND pp.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY pp.player_lookup ORDER BY pp.game_date DESC
      ) = 1
    ),

    -- DraftKings intra-day line movement
    dk_line_movement AS (
      SELECT
        player_lookup,
        closing_line - opening_line AS dk_line_move_direction
      FROM (
        SELECT
          player_lookup,
          MIN(CASE WHEN rn_asc = 1 THEN points_line END) AS opening_line,
          MIN(CASE WHEN rn_desc = 1 THEN points_line END) AS closing_line
        FROM (
          SELECT
            player_lookup,
            points_line,
            ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY snapshot_timestamp ASC) AS rn_asc,
            ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY snapshot_timestamp DESC) AS rn_desc
          FROM `{PROJECT_ID}.nba_raw.odds_api_player_points_props`
          WHERE game_date = @target_date
            AND LOWER(bookmaker) = 'draftkings'
            AND player_lookup IS NOT NULL
        )
        WHERE rn_asc = 1 OR rn_desc = 1
        GROUP BY player_lookup
      )
      WHERE opening_line IS NOT NULL AND closing_line IS NOT NULL
    ),

    -- Previous game context for bounce-back and streak signals
    prev_game_context AS (
      SELECT
        player_lookup,
        points AS prev_game_points,
        points_line AS prev_game_line,
        SAFE_DIVIDE(points, NULLIF(points_line, 0)) AS prev_game_ratio,
        SAFE_DIVIDE(fg_makes, NULLIF(fg_attempts, 0)) AS prev_game_fg_pct,
        minutes_played AS prev_game_minutes,
        game_date AS prev_game_date
      FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
      WHERE game_date >= DATE_SUB(@target_date, INTERVAL 14 DAY)
        AND game_date < @target_date
        AND points IS NOT NULL AND points > 0
        AND (is_dnp IS NULL OR is_dnp = FALSE)
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY player_lookup ORDER BY game_date DESC
      ) = 1
    )

    SELECT
      p.*,
      ls.player_full_name,
      ls.team_abbr,
      ls.opponent_team_abbr,
      ls.three_pct_last_3,
      ls.three_pct_season,
      ls.three_pct_std,
      ls.three_pa_per_game,
      ls.minutes_avg_last_3,
      ls.minutes_avg_season,
      ls.minutes_played AS prev_minutes,
      ls.fg_pct_last_3,
      ls.fg_pct_season,
      ls.fg_pct_std,
      ls.neg_pm_1,
      ls.neg_pm_2,
      ls.neg_pm_3,
      ls.starter_flag,
      ls.points_avg_season,
      ls.usage_avg_season,
      ls.fta_season,
      ls.fta_avg_last_10,
      ls.fta_cv_last_10,
      ls.unassisted_fg_season,
      ls.points_std_last_5,
      ls.ft_rate_season,
      ls.starter_rate_season,
      ls.self_creation_rate_last_10,
      DATE_DIFF(@target_date, ls.game_date, DAY) AS rest_days,
      lsk.prev_correct_1, lsk.prev_correct_2, lsk.prev_correct_3,
      lsk.prev_correct_4, lsk.prev_correct_5,
      lsk.prev_over_1, lsk.prev_over_2, lsk.prev_over_3,
      lsk.prev_over_4, lsk.prev_over_5,
      v12.v12_recommendation,
      v12.v12_edge,
      v12.v12_predicted_points,
      v12.v12_confidence,
      ppl.prev_line_value,
      ppl.prev_line_date,
      bs.multi_book_line_std,
      bs.book_std_source,
      bs.teammate_usage_available,
      bs.star_teammates_out,
      bs.prop_under_streak,
      bs.implied_team_total,
      bs.opponent_pace,
      bs.points_std_last_10,
      bs.points_avg_last_5,
      bs.points_avg_last_10,
      bs.avg_pts_vs_opp,
      bs.games_vs_opp,
      bs.minutes_load_7d,
      bs.pts_avg_last3,
      bs.trend_slope,
      bs.usage_rate_l5,
      bs.blowout_risk,
      bs.spread_magnitude,
      bs.prop_over_streak,
      bs.over_rate_last_10,
      dlm.dk_line_move_direction,
      pgc.prev_game_points,
      pgc.prev_game_line,
      pgc.prev_game_ratio,
      pgc.prev_game_fg_pct,
      pgc.prev_game_minutes
    FROM preds p
    LEFT JOIN latest_stats ls ON ls.player_lookup = p.player_lookup
    LEFT JOIN latest_streak lsk ON lsk.player_lookup = p.player_lookup
    LEFT JOIN v12_preds v12 ON v12.player_lookup = p.player_lookup AND v12.game_id = p.game_id
    LEFT JOIN prev_prop_lines ppl ON ppl.player_lookup = p.player_lookup
    LEFT JOIN book_stats bs ON bs.player_lookup = p.player_lookup AND bs.game_date = p.game_date
    LEFT JOIN dk_line_movement dlm ON dlm.player_lookup = p.player_lookup
    LEFT JOIN prev_game_context pgc ON pgc.player_lookup = p.player_lookup
    ORDER BY p.system_id, p.player_lookup
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )

    rows = bq_client.query(query, job_config=job_config).result(timeout=120)

    # --- Run satellite queries in parallel with row parsing ---

    # Opponent stars out
    opp_stars_query = f"""
    SELECT
      ir.team AS team_abbr,
      COUNT(DISTINCT ir.player_lookup) AS stars_out
    FROM `{PROJECT_ID}.nba_raw.nbac_injury_report` ir
    INNER JOIN (
      SELECT player_lookup, team_abbr
      FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
      WHERE game_date >= '2025-10-22' AND game_date < @target_date
      GROUP BY player_lookup, team_abbr
      HAVING AVG(points) >= 18 OR AVG(minutes_played) >= 28
    ) stars ON ir.player_lookup = stars.player_lookup AND ir.team = stars.team_abbr
    WHERE ir.game_date = @target_date
      AND ir.injury_status IN ('out', 'doubtful', 'Out', 'Doubtful')
    GROUP BY ir.team
    """
    team_stars_out = {}
    try:
        opp_stars_rows = bq_client.query(opp_stars_query, job_config=job_config).result(timeout=30)
        team_stars_out = {row['team_abbr']: row['stars_out'] for row in opp_stars_rows}
    except Exception as e:
        logger.warning(f"Failed to query opponent stars out: {e}")

    # Mean-median gap (skew) for high_skew_over_block filter
    skew_query = f"""
    WITH player_last_10 AS (
      SELECT
        player_lookup,
        points,
        ROW_NUMBER() OVER (
          PARTITION BY player_lookup ORDER BY game_date DESC
        ) AS rn
      FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
      WHERE game_date >= '2025-10-22'
        AND game_date < @target_date
        AND minutes_played > 0
    )
    SELECT
      player_lookup,
      AVG(points) - APPROX_QUANTILES(points, 100)[OFFSET(50)] AS mean_median_gap
    FROM player_last_10
    WHERE rn <= 10
    GROUP BY player_lookup
    HAVING COUNT(*) >= 5
    """
    skew_map = {}
    try:
        skew_rows = bq_client.query(skew_query, job_config=job_config).result(timeout=30)
        skew_map = {row['player_lookup']: float(row['mean_median_gap']) for row in skew_rows}
    except Exception as e:
        logger.warning(f"Failed to query mean-median gap: {e}")

    # Q4 scoring ratio
    q4_ratio_query = f"""
    WITH player_game_q4 AS (
      SELECT
        REGEXP_REPLACE(player_1_lookup, r'^[0-9]+', '') as player_lookup,
        game_date,
        SAFE_DIVIDE(
          SUM(CASE WHEN period = 4 THEN points_scored ELSE 0 END),
          SUM(points_scored)
        ) as q4_ratio
      FROM `{PROJECT_ID}.nba_raw.bigdataball_play_by_play`
      WHERE game_date >= '2025-10-01'
        AND game_date < @target_date
        AND event_type IN ('shot', 'free throw') AND points_scored > 0
      GROUP BY 1, 2
      HAVING SUM(points_scored) >= 5
    ),
    ranked AS (
      SELECT player_lookup, q4_ratio,
        ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
      FROM player_game_q4
    )
    SELECT
      player_lookup,
      AVG(q4_ratio) as q4_scoring_ratio
    FROM ranked
    WHERE rn <= 5
    GROUP BY 1
    """
    q4_ratio_map = {}
    try:
        q4_rows = bq_client.query(q4_ratio_query, job_config=job_config).result(timeout=30)
        q4_ratio_map = {row['player_lookup']: float(row['q4_scoring_ratio']) for row in q4_rows}
    except Exception as e:
        logger.warning(f"Failed to query Q4 scoring ratios: {e}")

    # Projection consensus (NumberFire + ESPN)
    projection_query = f"""
    WITH nf AS (
      SELECT REPLACE(player_lookup, '-', '') AS player_lookup, projected_points,
        ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY scraped_at DESC) AS rn
      FROM `{PROJECT_ID}.nba_raw.numberfire_projections`
      WHERE game_date = @target_date AND projected_points IS NOT NULL
        AND projected_points BETWEEN 5 AND 60
    ),
    espn AS (
      SELECT REPLACE(player_lookup, '-', '') AS player_lookup, projected_points,
        ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY scraped_at DESC) AS rn
      FROM `{PROJECT_ID}.nba_raw.espn_projections`
      WHERE game_date = @target_date AND projected_points IS NOT NULL
        AND projected_points BETWEEN 5 AND 60
    )
    SELECT
      COALESCE(nf.player_lookup, espn.player_lookup) AS player_lookup,
      nf.projected_points AS nf_projected_points,
      CAST(NULL AS FLOAT64) AS fp_projected_points,
      CAST(NULL AS FLOAT64) AS dm_projected_points,
      espn.projected_points AS espn_projected_points
    FROM nf
    FULL OUTER JOIN espn ON nf.player_lookup = espn.player_lookup AND espn.rn = 1
    WHERE nf.rn = 1 OR (nf.player_lookup IS NULL AND espn.rn = 1)
    """
    projection_map = {}
    try:
        proj_rows = bq_client.query(projection_query, job_config=job_config).result(timeout=30)
        for row in proj_rows:
            projection_map[row['player_lookup']] = {
                'numberfire': float(row['nf_projected_points']) if row['nf_projected_points'] is not None else None,
                'fantasypros': float(row['fp_projected_points']) if row['fp_projected_points'] is not None else None,
                'dailyfantasyfuel': None,
                'dimers': float(row['dm_projected_points']) if row['dm_projected_points'] is not None else None,
                'espn': float(row['espn_projected_points']) if row['espn_projected_points'] is not None else None,
            }
    except Exception as e:
        logger.warning(f"Failed to query projection consensus data: {e}")

    # TeamRankings predicted pace
    pace_query = f"""
    SELECT team, pace
    FROM `{PROJECT_ID}.nba_raw.teamrankings_team_stats`
    WHERE game_date = (
      SELECT MAX(game_date) FROM `{PROJECT_ID}.nba_raw.teamrankings_team_stats`
      WHERE game_date <= @target_date
    )
    AND pace IS NOT NULL
    """
    team_pace_map = {}
    try:
        pace_rows = bq_client.query(pace_query, job_config=job_config).result(timeout=30)
        team_pace_map = {row['team']: float(row['pace']) for row in pace_rows}
    except Exception as e:
        logger.warning(f"Failed to query TeamRankings pace: {e}")

    # DvP data
    dvp_query = f"""
    WITH deduped AS (
      SELECT DISTINCT team, position, points_allowed
      FROM `{PROJECT_ID}.nba_raw.hashtagbasketball_dvp`
      WHERE game_date = (
        SELECT MAX(game_date) FROM `{PROJECT_ID}.nba_raw.hashtagbasketball_dvp`
        WHERE game_date <= @target_date
      )
      AND points_allowed IS NOT NULL
      AND position = 'ALL'
      AND team NOT IN ('PG', 'SG', 'SF', 'PF', 'C')
    )
    SELECT team, position, points_allowed,
      RANK() OVER (ORDER BY points_allowed DESC) AS rank
    FROM deduped
    """
    dvp_map = {}
    try:
        dvp_rows = bq_client.query(dvp_query, job_config=job_config).result(timeout=30)
        for row in dvp_rows:
            team = row['team']
            if team not in dvp_map:
                dvp_map[team] = {}
            dvp_map[team][row['position']] = {
                'points_allowed': float(row['points_allowed']),
                'rank': int(row['rank']) if row['rank'] is not None else None,
            }
    except Exception as e:
        logger.warning(f"Failed to query DvP data: {e}")

    # DvP gamebook fallback
    if len(dvp_map) == 0:
        logger.warning("Hashtag DvP unavailable — falling back to gamebook self-computation")
        dvp_fallback_query = f"""
        WITH opponent_scoring AS (
          SELECT
            g.opponent_team_abbr AS defending_team,
            g.points
          FROM `{PROJECT_ID}.nba_analytics.player_game_summary` g
          WHERE g.game_date >= DATE_SUB(@target_date, INTERVAL 30 DAY)
            AND g.game_date < @target_date
            AND g.minutes > 0
            AND g.points IS NOT NULL
            AND (g.is_dnp IS NULL OR g.is_dnp = FALSE)
        ),
        team_defense AS (
          SELECT
            defending_team AS team,
            'ALL' AS position,
            ROUND(AVG(points), 1) AS points_allowed
          FROM opponent_scoring
          GROUP BY defending_team
          HAVING COUNT(*) >= 30
        )
        SELECT team, position, points_allowed,
          RANK() OVER (ORDER BY points_allowed DESC) AS rank
        FROM team_defense
        """
        try:
            fb_rows = bq_client.query(dvp_fallback_query, job_config=job_config).result(timeout=30)
            for row in fb_rows:
                team = row['team']
                if team not in dvp_map:
                    dvp_map[team] = {}
                dvp_map[team][row['position']] = {
                    'points_allowed': float(row['points_allowed']),
                    'rank': int(row['rank']) if row['rank'] is not None else None,
                }
        except Exception as e:
            logger.warning(f"DvP fallback query also failed: {e}")

    # CLV tracking
    clv_query = f"""
    WITH tagged AS (
      SELECT player_lookup, points_line, snapshot_tag,
        CAST(SUBSTR(snapshot_tag, 6) AS INT64) AS snap_time
      FROM `{PROJECT_ID}.nba_raw.odds_api_player_points_props`
      WHERE game_date = @target_date
        AND player_lookup IS NOT NULL
        AND snapshot_tag IS NOT NULL
        AND points_line IS NOT NULL
    ),
    snap_bounds AS (
      SELECT
        MIN(CASE WHEN snap_time >= 600 THEN snapshot_tag END) as earliest_snap,
        MAX(CASE WHEN snap_time <= 2200 THEN snapshot_tag END) as latest_snap
      FROM tagged
    ),
    opening AS (
      SELECT t.player_lookup, AVG(t.points_line) as opening_line
      FROM tagged t, snap_bounds sb
      WHERE t.snapshot_tag = sb.earliest_snap
      GROUP BY 1
    ),
    closing AS (
      SELECT t.player_lookup, AVG(t.points_line) as closing_line
      FROM tagged t, snap_bounds sb
      WHERE t.snapshot_tag = sb.latest_snap
      GROUP BY 1
    )
    SELECT
      o.player_lookup,
      o.opening_line,
      c.closing_line,
      o.opening_line - c.closing_line AS clv
    FROM opening o
    JOIN closing c ON o.player_lookup = c.player_lookup
    WHERE ABS(o.opening_line - c.closing_line) > 0
    """
    clv_map = {}
    try:
        clv_rows = bq_client.query(clv_query, job_config=job_config).result(timeout=30)
        for row in clv_rows:
            clv_map[row['player_lookup']] = {
                'opening_line': float(row['opening_line']),
                'closing_line': float(row['closing_line']),
                'clv': float(row['clv']),
            }
    except Exception as e:
        logger.warning(f"Failed to query CLV data: {e}")

    # Session 462: BettingPros line movement
    bp_line_move_query = f"""
    SELECT player_lookup,
      AVG(points_line - opening_line) AS bp_line_movement
    FROM `{PROJECT_ID}.nba_raw.bettingpros_player_points_props`
    WHERE game_date = @target_date
      AND market_type = 'points'
      AND opening_line IS NOT NULL
      AND points_line IS NOT NULL
      AND is_best_line = TRUE
    GROUP BY player_lookup
    HAVING ABS(AVG(points_line - opening_line)) > 0
    """
    bp_line_movement_map = {}
    try:
        bp_rows = bq_client.query(bp_line_move_query, job_config=job_config).result(timeout=30)
        bp_line_movement_map = {
            row['player_lookup']: float(row['bp_line_movement'])
            for row in bp_rows if row['bp_line_movement'] is not None
        }
    except Exception as e:
        logger.warning(f"Failed to query BettingPros line movement: {e}")

    # Sharp book lean
    sharp_lean_query = f"""
    WITH latest_lines AS (
      SELECT
        player_lookup, bookmaker, points_line,
        ROW_NUMBER() OVER (
          PARTITION BY player_lookup, bookmaker
          ORDER BY snapshot_timestamp DESC
        ) AS rn
      FROM `{PROJECT_ID}.nba_raw.odds_api_player_points_props`
      WHERE game_date = @target_date
        AND player_lookup IS NOT NULL
        AND points_line IS NOT NULL
    )
    SELECT
      player_lookup,
      AVG(CASE WHEN bookmaker IN ('fanduel', 'draftkings') THEN points_line END)
        - AVG(CASE WHEN bookmaker IN ('betrivers', 'bovada', 'fliff') THEN points_line END)
        AS sharp_lean
    FROM latest_lines
    WHERE rn = 1
    GROUP BY player_lookup
    HAVING COUNT(DISTINCT CASE WHEN bookmaker IN ('fanduel', 'draftkings') THEN bookmaker END) >= 1
       AND COUNT(DISTINCT CASE WHEN bookmaker IN ('betrivers', 'bovada', 'fliff') THEN bookmaker END) >= 1
    """
    sharp_lean_map = {}
    try:
        sharp_lean_rows = bq_client.query(sharp_lean_query, job_config=job_config).result(timeout=30)
        sharp_lean_map = {
            row['player_lookup']: float(row['sharp_lean'])
            for row in sharp_lean_rows if row['sharp_lean'] is not None
        }
    except Exception as e:
        logger.warning(f"Failed to query sharp book lean: {e}")

    # VSiN sharp money
    vsin_query = f"""
    SELECT away_team, home_team,
      over_ticket_pct, under_ticket_pct,
      over_money_pct, under_money_pct
    FROM `{PROJECT_ID}.nba_raw.vsin_betting_splits`
    WHERE game_date = @target_date
      AND over_money_pct IS NOT NULL
      AND over_ticket_pct IS NOT NULL
    """
    vsin_map = {}
    try:
        vsin_rows = bq_client.query(vsin_query, job_config=job_config).result(timeout=30)
        for row in vsin_rows:
            key = (row['away_team'], row['home_team'])
            vsin_map[key] = {
                'over_money_pct': float(row['over_money_pct']),
                'under_money_pct': float(row['under_money_pct']),
                'over_ticket_pct': float(row['over_ticket_pct']),
                'under_ticket_pct': float(row['under_ticket_pct']),
            }
    except Exception as e:
        logger.warning(f"Failed to query VSiN betting splits: {e}")

    # RotoWire projected minutes
    rotowire_query = f"""
    SELECT REPLACE(player_lookup, '-', '') AS player_lookup, projected_minutes
    FROM `{PROJECT_ID}.nba_raw.rotowire_lineups`
    WHERE game_date = @target_date
      AND projected_minutes IS NOT NULL
      AND player_lookup IS NOT NULL
    """
    rotowire_minutes_map = {}
    try:
        rw_rows = bq_client.query(rotowire_query, job_config=job_config).result(timeout=30)
        rotowire_minutes_map = {
            row['player_lookup']: float(row['projected_minutes'])
            for row in rw_rows if row['projected_minutes']
        }
    except Exception as e:
        logger.warning(f"Failed to query RotoWire minutes: {e}")

    # --- Parse main query rows and build predictions + supplemental ---
    predictions_by_model: Dict[str, List[Dict]] = defaultdict(list)
    supplemental_map: Dict[str, Dict] = {}

    for row in rows:
        row_dict = dict(row)
        system_id = row_dict['system_id']

        # Derive team/opponent from game_id
        game_id = row_dict.get('game_id', '')
        parts = game_id.split('_') if game_id else []
        team_abbr = row_dict.get('team_abbr', '')
        if len(parts) >= 3:
            away_team, home_team = parts[1], parts[2]
            is_home = (team_abbr == home_team)
            opponent = away_team if is_home else home_team
        else:
            is_home = False
            opponent = ''

        pred = {
            'player_lookup': row_dict['player_lookup'],
            'game_id': game_id,
            'game_date': row_dict['game_date'],
            'system_id': system_id,
            'player_name': row_dict.get('player_full_name', ''),
            'team_abbr': team_abbr,
            'opponent_team_abbr': opponent,
            'predicted_points': row_dict['predicted_points'],
            'line_value': row_dict['line_value'],
            'recommendation': row_dict['recommendation'],
            'edge': row_dict['edge'],
            'confidence_score': row_dict['confidence_score'],
            'is_home': is_home,
            'rest_days': row_dict.get('rest_days'),
            'feature_quality_score': row_dict.get('feature_quality_score') or 0,
            # Source model attribution
            'source_model_id': system_id,
            'source_model_family': classify_system_id(system_id),
            # Model HR weight from the query
            'model_hr_weight': float(row_dict.get('model_hr_weight') or 0.91),
            # Multi-model fields (populated since we query all models)
            'n_models_eligible': 0,  # Will be set if needed by merger
            'champion_edge': None,
            'direction_conflict': False,
        }

        # Copy player profile fields to prediction dict
        pred['starter_flag'] = row_dict.get('starter_flag')
        pred['points_avg_season'] = float(row_dict.get('points_avg_season') or 0)
        pred['usage_avg_season'] = float(row_dict.get('usage_avg_season') or 0)
        pred['fta_season'] = float(row_dict.get('fta_season') or 0)
        pred['fta_avg_last_10'] = float(row_dict.get('fta_avg_last_10') or 0)
        pred['fta_cv_last_10'] = float(row_dict.get('fta_cv_last_10') or 0)
        pred['unassisted_fg_season'] = float(row_dict.get('unassisted_fg_season') or 0)
        pred['points_std_last_5'] = float(row_dict.get('points_std_last_5') or 0)
        pred['ft_rate_season'] = float(row_dict.get('ft_rate_season') or 0)
        pred['starter_rate_season'] = float(row_dict.get('starter_rate_season') or 0)

        # Feature store values
        tu = row_dict.get('teammate_usage_available')
        pred['teammate_usage_available'] = float(tu) if tu is not None else 0
        sto = row_dict.get('star_teammates_out')
        pred['star_teammates_out'] = float(sto) if sto is not None else 0
        pus = row_dict.get('prop_under_streak')
        pred['prop_under_streak'] = float(pus) if pus is not None else 0
        itt = row_dict.get('implied_team_total')
        pred['implied_team_total'] = float(itt) if itt is not None else 0
        op = row_dict.get('opponent_pace')
        pred['opponent_pace'] = float(op) if op is not None else 0
        pstd = row_dict.get('points_std_last_10')
        pred['points_std_last_10'] = float(pstd) if pstd is not None else 0
        pa5 = row_dict.get('points_avg_last_5')
        pred['points_avg_last_5'] = float(pa5) if pa5 is not None else 0
        pa10 = row_dict.get('points_avg_last_10')
        pred['points_avg_last_10'] = float(pa10) if pa10 is not None else 0
        pred['avg_pts_vs_opp'] = float(row_dict.get('avg_pts_vs_opp') or 0)
        pred['games_vs_opp'] = float(row_dict.get('games_vs_opp') or 0)
        pred['minutes_load_7d'] = float(row_dict.get('minutes_load_7d') or 0)
        pred['pts_avg_last3'] = float(row_dict.get('pts_avg_last3') or 0)
        pred['trend_slope'] = float(row_dict.get('trend_slope') or 0)
        pred['usage_rate_l5'] = float(row_dict.get('usage_rate_l5') or 0)
        pred['blowout_risk'] = float(row_dict.get('blowout_risk') or 0)
        pred['spread_magnitude'] = float(row_dict.get('spread_magnitude') or 0)
        pred['prev_game_ratio'] = float(row_dict.get('prev_game_ratio') or 0)
        pred['prev_game_fg_pct'] = float(row_dict.get('prev_game_fg_pct') or 0)
        pred['prev_game_points'] = float(row_dict.get('prev_game_points') or 0)
        pred['prev_game_line'] = float(row_dict.get('prev_game_line') or 0)
        pred['prev_game_minutes'] = float(row_dict.get('prev_game_minutes') or 0)
        pos = row_dict.get('prop_over_streak')
        pred['prop_over_streak'] = float(pos) if pos is not None else 0
        orl = row_dict.get('over_rate_last_10')
        pred['over_rate_last_10'] = float(orl) if orl is not None else 0
        pred['prev_over_1'] = row_dict.get('prev_over_1')
        pred['prev_over_2'] = row_dict.get('prev_over_2')
        pred['prev_over_3'] = row_dict.get('prev_over_3')
        pred['prev_over_4'] = row_dict.get('prev_over_4')
        pred['prev_over_5'] = row_dict.get('prev_over_5')

        # Opponent stars out
        pred['opponent_stars_out'] = team_stars_out.get(opponent, 0)

        # Multi-book line std
        mbls = row_dict.get('multi_book_line_std')
        pred['multi_book_line_std'] = float(mbls) if mbls is not None else 0

        # Self-creation rate
        scr = row_dict.get('self_creation_rate_last_10')
        pred['self_creation_rate_last_10'] = float(scr) if scr is not None else 0

        # DraftKings intra-day line movement
        dlm_val = row_dict.get('dk_line_move_direction')
        pred['dk_line_move_direction'] = float(dlm_val) if dlm_val is not None else None

        # Prop line delta
        if row_dict.get('prev_line_value') is not None:
            current_line = float(row_dict.get('line_value') or 0)
            prev_line = float(row_dict['prev_line_value'])
            pred['prop_line_delta'] = round(current_line - prev_line, 1)

        # Q4 scoring ratio
        pred['q4_scoring_ratio'] = q4_ratio_map.get(row_dict['player_lookup'], 0)

        # Mean-median gap
        pred['mean_median_gap'] = skew_map.get(row_dict['player_lookup'], 0)

        # Sharp book lean
        sbl = sharp_lean_map.get(row_dict['player_lookup'])
        pred['sharp_book_lean'] = float(sbl) if sbl is not None else None

        # Projection consensus
        proj_data = projection_map.get(row_dict['player_lookup'])
        if proj_data:
            line = float(pred.get('line_value') or 0)
            nf_pts = proj_data.get('numberfire')
            fp_pts = proj_data.get('fantasypros')
            dff_pts = proj_data.get('dailyfantasyfuel')
            dm_pts = proj_data.get('dimers')
            espn_pts = proj_data.get('espn')
            pred['numberfire_projected_points'] = nf_pts
            pred['fantasypros_projected_points'] = fp_pts
            pred['dailyfantasyfuel_projected_points'] = dff_pts
            pred['dimers_projected_points'] = dm_pts
            pred['espn_projected_points'] = espn_pts

            sources_above = 0
            sources_below = 0
            total_sources = 0
            for pts in [nf_pts, fp_pts, dff_pts, dm_pts, espn_pts]:
                if pts is not None and line > 0:
                    total_sources += 1
                    if pts > line:
                        sources_above += 1
                    elif pts < line:
                        sources_below += 1
            pred['projection_sources_above_line'] = sources_above
            pred['projection_sources_below_line'] = sources_below
            pred['projection_sources_total'] = total_sources
        else:
            pred['projection_sources_total'] = 0
            pred['projection_sources_above_line'] = 0
            pred['projection_sources_below_line'] = 0

        # Predicted game pace
        team_pace = team_pace_map.get(pred.get('team_abbr'))
        opp_pace = team_pace_map.get(opponent)
        pred['team_predicted_pace'] = team_pace
        pred['opponent_predicted_pace'] = opp_pace
        if team_pace and opp_pace:
            pred['predicted_game_pace'] = (team_pace + opp_pace) / 2.0
        else:
            pred['predicted_game_pace'] = None

        # DvP data
        opp_dvp = dvp_map.get(opponent, {})
        if opp_dvp:
            best_dvp = opp_dvp.get('ALL', {})
            pred['opponent_dvp_rank'] = best_dvp.get('rank')
            pred['opponent_dvp_points_allowed'] = best_dvp.get('points_allowed')
        else:
            pred['opponent_dvp_rank'] = None
            pred['opponent_dvp_points_allowed'] = None

        # CLV data
        clv_data = clv_map.get(row_dict['player_lookup'])
        if clv_data:
            pred['closing_line_value'] = clv_data['clv']
            pred['opening_line'] = clv_data['opening_line']
            pred['closing_line'] = clv_data['closing_line']
        else:
            pred['closing_line_value'] = None

        # Session 462: BettingPros line movement
        bp_lm = bp_line_movement_map.get(row_dict['player_lookup'])
        pred['bp_line_movement'] = float(bp_lm) if bp_lm is not None else None

        # Session 462: Copy shooting stats to pred dict for new signals/observation filters
        pred['fg_pct_last_3'] = float(row_dict['fg_pct_last_3']) if row_dict.get('fg_pct_last_3') is not None else None
        pred['fg_pct_season'] = float(row_dict['fg_pct_season']) if row_dict.get('fg_pct_season') is not None else None
        pred['three_pct_last_3'] = float(row_dict['three_pct_last_3']) if row_dict.get('three_pct_last_3') is not None else None
        pred['three_pct_season'] = float(row_dict['three_pct_season']) if row_dict.get('three_pct_season') is not None else None

        # Negative +/- streak
        neg_pm_streak = 0
        for lag_val in [row_dict.get('neg_pm_1'), row_dict.get('neg_pm_2'), row_dict.get('neg_pm_3')]:
            if lag_val == 1:
                neg_pm_streak += 1
            else:
                break
        if neg_pm_streak > 0:
            pred['neg_pm_streak'] = neg_pm_streak

        # VSiN sharp money
        if len(parts) >= 3:
            vsin_data = vsin_map.get((parts[1], parts[2]))
            if vsin_data:
                pred['vsin_over_money_pct'] = vsin_data['over_money_pct']
                pred['vsin_under_money_pct'] = vsin_data['under_money_pct']
                pred['vsin_over_ticket_pct'] = vsin_data['over_ticket_pct']
                pred['vsin_under_ticket_pct'] = vsin_data['under_ticket_pct']
            else:
                pred['vsin_over_money_pct'] = None
        else:
            pred['vsin_over_money_pct'] = None

        # RotoWire projected minutes
        rw_minutes = rotowire_minutes_map.get(row_dict['player_lookup'])
        pred['rotowire_projected_minutes'] = rw_minutes

        predictions_by_model[system_id].append(pred)

        # Build supplemental map (player-level, write once per player)
        player_key = row_dict['player_lookup']
        if player_key not in supplemental_map:
            supp: Dict[str, Any] = {}

            supp['player_context'] = {'position': ''}

            if row_dict.get('three_pct_last_3') is not None:
                supp['three_pt_stats'] = {
                    'three_pct_last_3': float(row_dict['three_pct_last_3']),
                    'three_pct_season': float(row_dict.get('three_pct_season') or 0),
                    'three_pct_std': float(row_dict.get('three_pct_std') or 0),
                    'three_pa_per_game': float(row_dict.get('three_pa_per_game') or 0),
                }

            if row_dict.get('minutes_avg_last_3') is not None:
                supp['minutes_stats'] = {
                    'minutes_avg_last_3': float(row_dict['minutes_avg_last_3']),
                    'minutes_avg_season': float(row_dict.get('minutes_avg_season') or 0),
                }

            # Streak stats
            if row_dict.get('prev_over_1') is not None:
                prev_correct = [
                    row_dict.get('prev_correct_1'),
                    row_dict.get('prev_correct_2'),
                    row_dict.get('prev_correct_3'),
                    row_dict.get('prev_correct_4'),
                    row_dict.get('prev_correct_5'),
                ]
                prev_over = [
                    row_dict.get('prev_over_1'),
                    row_dict.get('prev_over_2'),
                    row_dict.get('prev_over_3'),
                    row_dict.get('prev_over_4'),
                    row_dict.get('prev_over_5'),
                ]

                consecutive_beats = 0
                for val in prev_correct:
                    if val == 1:
                        consecutive_beats += 1
                    else:
                        break

                consecutive_misses = 0
                last_miss_direction = None
                for i, val in enumerate(prev_correct):
                    if val == 0:
                        consecutive_misses += 1
                        if i < len(prev_over) and prev_over[i] is not None:
                            last_miss_direction = 'OVER' if prev_over[i] == 1 else 'UNDER'
                    else:
                        break

                supp['streak_stats'] = {
                    'prev_correct': prev_correct,
                    'prev_over': prev_over,
                    'consecutive_line_beats': consecutive_beats,
                    'consecutive_line_misses': consecutive_misses,
                    'last_miss_direction': last_miss_direction,
                }

                player_streak_key = f"{row_dict['player_lookup']}::{row_dict['game_date']}"
                supp['streak_data'] = {
                    player_streak_key: {
                        'consecutive_line_beats': consecutive_beats,
                        'consecutive_line_misses': consecutive_misses,
                        'last_miss_direction': last_miss_direction,
                    }
                }

            # Recovery stats
            if (row_dict.get('prev_minutes') is not None
                    and row_dict.get('minutes_avg_season') is not None):
                supp['recovery_stats'] = {
                    'prev_minutes': float(row_dict['prev_minutes']),
                    'minutes_avg_season': float(row_dict['minutes_avg_season']),
                }

            # FG% stats
            if row_dict.get('fg_pct_last_3') is not None:
                supp['fg_stats'] = {
                    'fg_pct_last_3': float(row_dict['fg_pct_last_3']),
                    'fg_pct_season': float(row_dict.get('fg_pct_season') or 0),
                    'fg_pct_std': float(row_dict.get('fg_pct_std') or 0),
                }

            # Rest stats
            if row_dict.get('rest_days') is not None:
                supp['rest_stats'] = {
                    'rest_days': int(row_dict['rest_days']),
                }

            # Player profile stats
            supp['player_profile'] = {
                'starter_flag': row_dict.get('starter_flag'),
                'points_avg_season': float(row_dict.get('points_avg_season') or 0),
                'usage_avg_season': float(row_dict.get('usage_avg_season') or 0),
                'fta_season': float(row_dict.get('fta_season') or 0),
                'fta_avg_last_10': float(row_dict.get('fta_avg_last_10') or 0),
                'fta_cv_last_10': float(row_dict.get('fta_cv_last_10') or 0),
                'unassisted_fg_season': float(row_dict.get('unassisted_fg_season') or 0),
                'points_std_last_5': float(row_dict.get('points_std_last_5') or 0),
                'ft_rate_season': float(row_dict.get('ft_rate_season') or 0),
                'starter_rate_season': float(row_dict.get('starter_rate_season') or 0),
            }

            # V12 prediction
            if row_dict.get('v12_recommendation'):
                supp['v12_prediction'] = {
                    'recommendation': row_dict['v12_recommendation'],
                    'edge': float(row_dict.get('v12_edge') or 0),
                    'predicted_points': float(row_dict.get('v12_predicted_points') or 0),
                    'confidence': float(row_dict.get('v12_confidence') or 0),
                }

            # Book disagreement stats
            if row_dict.get('multi_book_line_std') is not None:
                supp['book_stats'] = {
                    'multi_book_line_std': float(row_dict['multi_book_line_std']),
                    'book_std_source': row_dict.get('book_std_source', ''),
                }

            # Prop line delta stats
            if row_dict.get('prev_line_value') is not None:
                current_line = float(row_dict.get('line_value') or 0)
                prev_line = float(row_dict['prev_line_value'])
                supp['prop_line_stats'] = {
                    'prev_line_value': prev_line,
                    'current_line_value': current_line,
                    'line_delta': round(current_line - prev_line, 1),
                }

            # RotoWire minutes comparison
            season_minutes = supp.get('minutes_stats', {}).get('minutes_avg_season')
            rw_mins = rotowire_minutes_map.get(row_dict['player_lookup'])
            if rw_mins and season_minutes and season_minutes > 0:
                pred['minutes_projection_delta'] = rw_mins - season_minutes
            else:
                pred['minutes_projection_delta'] = None

            supplemental_map[player_key] = supp

    logger.info(
        f"Batch prediction query: {sum(len(v) for v in predictions_by_model.values())} "
        f"total predictions across {len(predictions_by_model)} models, "
        f"{len(supplemental_map)} unique players"
    )

    return dict(predictions_by_model), supplemental_map


# ---------------------------------------------------------------------------
# Shared context builder
# ---------------------------------------------------------------------------

def _query_all_model_health_map(
    bq_client: bigquery.Client,
    target_date: str,
) -> Dict[str, Optional[float]]:
    """Query 7d hit rate at edge 3+ for ALL models in one scan.

    Returns:
        Dict mapping system_id -> hit_rate_7d_edge3 (float or None).
    """
    system_filter = build_system_id_sql_filter()
    query = f"""
    SELECT
      system_id,
      ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNT(*), 0), 1)
        AS hit_rate_7d_edge3,
      COUNT(*) AS graded_count
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      AND game_date < CURRENT_DATE()
      AND ABS(predicted_points - line_value) >= 3.0
      AND prediction_correct IS NOT NULL
      AND is_voided IS NOT TRUE
      AND {system_filter}
    GROUP BY system_id
    """
    health_map: Dict[str, Optional[float]] = {}
    try:
        rows = bq_client.query(query).result(timeout=30)
        for row in rows:
            if (row['graded_count'] or 0) > 0:
                health_map[row['system_id']] = float(row['hit_rate_7d_edge3'])
            else:
                health_map[row['system_id']] = None
    except Exception as e:
        logger.error(f"All-model health query failed: {e}", exc_info=True)
    return health_map


def _query_filter_overrides(bq_client: bigquery.Client) -> Set[str]:
    """Query runtime filter overrides (auto-demoted filters).

    Returns set of filter names that are currently demoted.
    """
    try:
        query = f"""
        SELECT filter_name
        FROM `{PROJECT_ID}.nba_predictions.filter_overrides`
        WHERE active = TRUE
        """
        rows = list(bq_client.query(query).result(timeout=15))
        demoted = {row.filter_name for row in rows}
        if demoted:
            logger.info(f"Runtime filter overrides active: {sorted(demoted)}")
        return demoted
    except Exception as e:
        logger.warning(f"Failed to query filter_overrides (non-fatal): {e}")
        return set()


def _query_direction_health(
    bq_client: bigquery.Client,
    target_date: str,
) -> Dict[str, Any]:
    """Query 14-day rolling hit rate by direction (OVER vs UNDER).

    Returns dict with over_hr_14d, under_hr_14d, over_n, under_n.
    """
    from shared.config.model_selection import get_best_bets_model_id
    model_id = get_best_bets_model_id()

    query = f"""
    SELECT
        recommendation,
        COUNT(*) AS n,
        ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / COUNT(*), 1) AS hr
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date >= DATE_SUB(@target_date, INTERVAL 14 DAY)
      AND game_date < @target_date
      AND system_id = @model_id
      AND ABS(predicted_points - line_value) >= 3
      AND is_voided = FALSE
      AND recommendation IN ('OVER', 'UNDER')
    GROUP BY recommendation
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('model_id', 'STRING', model_id),
        ]
    )

    health = {'over_hr_14d': None, 'under_hr_14d': None,
              'over_n': 0, 'under_n': 0}
    try:
        result = bq_client.query(query, job_config=job_config).result(timeout=30)
        for row in result:
            if row.recommendation == 'OVER':
                health['over_hr_14d'] = float(row.hr) if row.hr else None
                health['over_n'] = row.n
            elif row.recommendation == 'UNDER':
                health['under_hr_14d'] = float(row.hr) if row.hr else None
                health['under_n'] = row.n
    except Exception as e:
        logger.warning(f"Direction health query failed (non-fatal): {e}")

    return health


def build_shared_context(
    bq_client: bigquery.Client,
    target_date: str,
    **kwargs,
) -> SharedContext:
    """Build all model-independent context. ~12 BQ queries total.

    This is the expensive step: one big prediction query (all models, no dedup),
    10 satellite queries for supplemental data, plus model health, signal health,
    combo registry, player blacklist, model-direction affinity, regime context,
    games vs opponent, and filter overrides.

    Args:
        bq_client: BigQuery client.
        target_date: YYYY-MM-DD date string.
        **kwargs: Optional overrides:
            - signal_registry: Pre-built SignalRegistry (skips build_default_registry).
            - combo_registry: Pre-loaded combo registry.

    Returns:
        SharedContext with all data needed for per-model pipeline runs.
    """
    ctx = SharedContext(target_date=target_date)

    # 1. Batch-query ALL models' predictions + supplemental data (1 big query + 10 satellites)
    include_disabled = kwargs.get('include_disabled', False)
    logger.info(f"Building shared context for {target_date}...")
    predictions_by_model, supplemental_map = _query_all_model_predictions(
        bq_client, target_date, include_disabled=include_disabled,
    )
    ctx.all_predictions = predictions_by_model
    ctx.supplemental_map = supplemental_map

    if not predictions_by_model:
        logger.warning(f"No predictions found for any model on {target_date}")
        return ctx

    # 2. Model health for ALL models (1 query)
    ctx.model_health_map = _query_all_model_health_map(bq_client, target_date)
    # Default model health (champion)
    default_health = query_model_health(bq_client)
    ctx.default_model_health_hr = default_health.get('hit_rate_7d_edge3')

    # 3. Signal health (1 query)
    try:
        ctx.signal_health = get_signal_health_summary(bq_client, target_date)
    except Exception as e:
        logger.warning(f"Signal health query failed (non-fatal): {e}")

    # 4. Combo registry
    ctx.combo_registry = kwargs.get('combo_registry') or load_combo_registry(bq_client=bq_client)

    # 5. Player blacklist (1 query)
    try:
        ctx.player_blacklist, ctx.blacklist_stats = compute_player_blacklist(
            bq_client, target_date
        )
    except Exception as e:
        logger.warning(f"Player blacklist computation failed (non-fatal): {e}")

    # 5b. Player UNDER suppression (1 query, Session 451)
    try:
        ctx.player_under_suppression, _ = compute_player_under_suppression(
            bq_client, target_date
        )
    except Exception as e:
        logger.warning(f"Player UNDER suppression computation failed (non-fatal): {e}")

    # 6. Model-direction affinity (1 query)
    try:
        _, ctx.model_direction_blocks, ctx.model_direction_affinity_stats = \
            compute_model_direction_affinities(bq_client, target_date, PROJECT_ID)
    except Exception as e:
        logger.warning(f"Model-direction affinity failed (non-fatal): {e}")

    # 7. Model profile store (1 query)
    try:
        ctx.model_profile_store = load_model_profiles(bq_client, target_date, PROJECT_ID)
    except Exception as e:
        logger.warning(f"Model profile loading failed (non-fatal): {e}")

    # 8. Regime context (2 queries: yesterday HR + market compression)
    try:
        ctx.regime_context = get_regime_context(bq_client, target_date)
        compression_ctx = get_market_compression(bq_client, target_date)
        ctx.regime_context['market_compression'] = compression_ctx
    except Exception as e:
        logger.warning(f"Regime context query failed (non-fatal): {e}")

    # 9. Games vs opponent (1 query)
    try:
        ctx.games_vs_opponent = query_games_vs_opponent(bq_client, target_date)
    except Exception as e:
        logger.warning(f"Games vs opponent query failed (non-fatal): {e}")

    # 10. Runtime filter overrides (1 query)
    ctx.runtime_demoted_filters = _query_filter_overrides(bq_client)

    # 11. Direction health (1 query)
    try:
        ctx.direction_health = _query_direction_health(bq_client, target_date)
    except Exception as e:
        logger.warning(f"Direction health query failed (non-fatal): {e}")

    logger.info(
        f"Shared context built: {len(predictions_by_model)} models, "
        f"{sum(len(v) for v in predictions_by_model.values())} total predictions, "
        f"{len(ctx.player_blacklist)} blacklisted, "
        f"{len(ctx.player_under_suppression)} UNDER-suppressed players"
    )

    return ctx


# ---------------------------------------------------------------------------
# Single-model pipeline runner
# ---------------------------------------------------------------------------

def run_single_model_pipeline(
    system_id: str,
    shared_ctx: SharedContext,
    signal_registry: Optional[SignalRegistry] = None,
) -> PipelineResult:
    """Run signals + aggregator for one model. Pure Python -- no BQ queries.

    Args:
        system_id: Model system_id to run pipeline for.
        shared_ctx: SharedContext built by build_shared_context().
        signal_registry: Optional pre-built registry (reuse across models).

    Returns:
        PipelineResult with candidates, filter summary, and signal results.
    """
    predictions = shared_ctx.all_predictions.get(system_id, [])
    if not predictions:
        logger.warning(f"No predictions for {system_id} on {shared_ctx.target_date}")
        return PipelineResult(
            system_id=system_id,
            candidates=[],
            all_predictions=[],
            filter_summary={'total_candidates': 0, 'rejected': {}},
            signal_results={},
        )

    # Enrich predictions with games_vs_opponent
    for pred in predictions:
        opp = pred.get('opponent_team_abbr', '')
        pred['games_vs_opponent'] = shared_ctx.games_vs_opponent.get(
            (pred['player_lookup'], opp), 0
        )

    # Get per-model health (use model-specific if available, else default)
    model_hr_7d = shared_ctx.model_health_map.get(
        system_id, shared_ctx.default_model_health_hr
    )

    # Build signal registry if not provided
    if signal_registry is None:
        signal_registry = build_default_registry()

    # Evaluate signals for each prediction
    signal_results_map: Dict[str, List] = {}
    for pred in predictions:
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        supplements = shared_ctx.supplemental_map.get(pred['player_lookup'], {})
        # Inject model health into supplemental
        supplements_copy = dict(supplements)
        supplements_copy['model_health'] = {'hit_rate_7d_edge3': model_hr_7d}

        results_for_pred = []
        for signal in signal_registry.all():
            result = signal.evaluate(pred, features=None, supplemental=supplements_copy)
            results_for_pred.append(result)
        signal_results_map[key] = results_for_pred

    # Run aggregator in per_model mode
    aggregator = BestBetsAggregator(
        combo_registry=shared_ctx.combo_registry,
        signal_health=shared_ctx.signal_health,
        player_blacklist=shared_ctx.player_blacklist,
        player_under_suppression=shared_ctx.player_under_suppression,
        model_direction_blocks=shared_ctx.model_direction_blocks,
        model_direction_affinity_stats=shared_ctx.model_direction_affinity_stats,
        model_profile_store=shared_ctx.model_profile_store,
        regime_context=shared_ctx.regime_context,
        runtime_demoted_filters=shared_ctx.runtime_demoted_filters,
        mode='per_model',
    )

    candidates, filter_summary = aggregator.aggregate(predictions, signal_results_map)

    logger.info(
        f"Pipeline {system_id}: {len(predictions)} predictions -> "
        f"{len(candidates)} candidates (filtered {filter_summary.get('total_rejected', 0)})"
    )

    return PipelineResult(
        system_id=system_id,
        candidates=candidates,
        all_predictions=predictions,
        filter_summary=filter_summary,
        signal_results=signal_results_map,
    )


# ---------------------------------------------------------------------------
# Orchestrator: run all models
# ---------------------------------------------------------------------------

def run_all_model_pipelines(
    bq_client: bigquery.Client,
    target_date: str,
    **kwargs,
) -> Tuple[Dict[str, PipelineResult], SharedContext]:
    """Main entry point. Build context once, run each model, return all results.

    Args:
        bq_client: BigQuery client.
        target_date: YYYY-MM-DD date string.
        **kwargs: Passed to build_shared_context (combo_registry, etc.)

    Returns:
        Tuple of:
            results: Dict[system_id, PipelineResult] for each model.
            shared_ctx: SharedContext (for downstream merger use).
    """
    # Build shared context (all BQ queries happen here)
    shared_ctx = build_shared_context(bq_client, target_date, **kwargs)

    if not shared_ctx.all_predictions:
        logger.warning(f"No predictions for any model on {target_date}")
        return {}, shared_ctx

    # Build signal registry once (stateless — safe to share across models)
    signal_registry = build_default_registry()

    # Run each model through the pipeline
    results: Dict[str, PipelineResult] = {}
    for system_id in sorted(shared_ctx.all_predictions.keys()):
        try:
            result = run_single_model_pipeline(
                system_id, shared_ctx, signal_registry=signal_registry
            )
            results[system_id] = result
        except Exception as e:
            logger.error(
                f"Pipeline failed for {system_id}: {e}", exc_info=True
            )
            results[system_id] = PipelineResult(
                system_id=system_id,
                candidates=[],
                all_predictions=shared_ctx.all_predictions.get(system_id, []),
                filter_summary={'total_candidates': 0, 'rejected': {}, 'error': str(e)},
                signal_results={},
            )

    # Summary
    total_candidates = sum(len(r.candidates) for r in results.values())
    total_predictions = sum(len(r.all_predictions) for r in results.values())
    models_with_picks = sum(1 for r in results.values() if r.candidates)

    logger.info(
        f"All pipelines complete for {target_date}: "
        f"{len(results)} models, {total_predictions} total predictions, "
        f"{total_candidates} total candidates from {models_with_picks} models"
    )

    return results, shared_ctx
