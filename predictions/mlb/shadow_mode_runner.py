#!/usr/bin/env python3
"""
MLB Shadow Mode Runner

Runs V1.4 and V1.6 models in parallel for historical comparison analysis.
V1.6 is now the production champion (deployed 2026-01-15 after shadow testing showed 60% win rate).

Features:
- Loads pitchers with games on a given date
- Runs both V1.4 (champion) and V1.6 (challenger) predictions
- Logs results to BigQuery for performance comparison
- Generates daily accuracy report

Usage:
    # Run shadow mode for today
    PYTHONPATH=. python predictions/mlb/shadow_mode_runner.py

    # Run for specific date
    PYTHONPATH=. python predictions/mlb/shadow_mode_runner.py --date 2025-06-15

    # Dry run (no BigQuery writes)
    PYTHONPATH=. python predictions/mlb/shadow_mode_runner.py --dry-run

Created: 2026-01-15
"""

import argparse
import logging
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from google.cloud import bigquery

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

# Model paths
V1_4_MODEL_PATH = 'gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456.json'
V1_6_MODEL_PATH = 'gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json'


@dataclass
class ShadowPrediction:
    """Result from shadow mode comparison"""
    pitcher_lookup: str
    game_date: str
    game_id: str
    team_abbr: str
    opponent_team_abbr: str
    strikeouts_line: Optional[float]
    # V1.4 (Champion) prediction
    v1_4_predicted: float
    v1_4_confidence: float
    v1_4_recommendation: str
    v1_4_edge: Optional[float]
    # V1.6 (Challenger) prediction
    v1_6_predicted: float
    v1_6_confidence: float
    v1_6_recommendation: str
    v1_6_edge: Optional[float]
    # Comparison
    prediction_diff: float  # v1_6 - v1_4
    recommendation_agrees: bool
    # Metadata
    v1_4_model_version: str
    v1_6_model_version: str
    timestamp: str


def load_pitchers_for_date(client: bigquery.Client, game_date: date) -> List[Dict]:
    """Load pitchers with games on the specified date from pitcher_game_summary

    Includes V1.6 features:
    - Season swing metrics (f19, f19b, f19c) from fangraphs
    - Line-relative features (f30, f31, f32) calculated from line + k_avg
    - BettingPros features (f40-f44) from bp_pitcher_props
    - Rolling statcast (f50-f53) from pitcher_rolling_statcast
    """
    query = """
    WITH
    -- Get pitchers scheduled for the date from game summary
    pitchers AS (
        SELECT DISTINCT
            pgs.player_lookup as pitcher_lookup,
            pgs.game_id,
            pgs.team_abbr,
            pgs.opponent_team_abbr,
            pgs.is_home,
            -- Rolling stats for features
            pgs.k_avg_last_3,
            pgs.k_avg_last_5,
            pgs.k_avg_last_10,
            pgs.k_std_last_10,
            pgs.ip_avg_last_5,
            pgs.era_rolling_10,
            pgs.whip_rolling_10,
            pgs.season_games_started as games_started,
            pgs.rolling_stats_games,  -- For red flag checks
            pgs.season_strikeouts as strikeouts_total,
            pgs.season_k_per_9,
            pgs.days_rest,
            pgs.games_last_30_days,
            pgs.pitch_count_avg_last_5 as pitch_count_avg,
            pgs.season_innings as season_ip_total,
            pgs.opponent_team_k_rate,
            pgs.ballpark_k_factor,
            pgs.month_of_season,
            pgs.days_into_season,
            -- Bottom-up features (V1.4)
            NULL as bottom_up_k_expected,
            NULL as lineup_k_vs_hand,
            pgs.vs_opponent_k_per_9 as avg_k_vs_opponent,
            pgs.vs_opponent_games as games_vs_opponent,
            NULL as lineup_weak_spots
        FROM `{project}.mlb_analytics.pitcher_game_summary` pgs
        WHERE pgs.game_date = @game_date
    ),
    -- Get betting lines from odds API
    -- Note: oddsa uses 'kylebradish' format, pitcher_game_summary uses 'kyle_bradish'
    -- We normalize by removing underscores from pitcher_game_summary for joining
    lines AS (
        SELECT
            player_lookup,
            -- Also create normalized version for joining
            LOWER(REPLACE(player_lookup, '_', '')) as player_lookup_normalized,
            point as strikeouts_line,
            over_price as over_odds,
            under_price as under_odds,
            snapshot_time,
            minutes_before_tipoff,
            ROW_NUMBER() OVER (
                PARTITION BY player_lookup
                ORDER BY snapshot_time DESC
            ) as rn
        FROM `{project}.mlb_raw.oddsa_pitcher_props`
        WHERE game_date = @game_date
          AND market_key = 'pitcher_strikeouts'
    ),
    -- Get rolling statcast features (for V1.6: f50-f53)
    statcast_rolling AS (
        SELECT
            player_lookup,
            swstr_pct_last_3,
            fb_velocity_last_3,
            swstr_pct_season_prior,
            fb_velocity_season_prior,
            -- Calculate swstr_trend (recent vs season baseline)
            SAFE_SUBTRACT(swstr_pct_last_3, swstr_pct_season_prior) as swstr_trend,
            -- Calculate velocity_change (season vs recent)
            SAFE_SUBTRACT(fb_velocity_season_prior, fb_velocity_last_3) as velocity_change,
            statcast_games_count
        FROM `{project}.mlb_analytics.pitcher_rolling_statcast`
        WHERE game_date = @game_date
    ),
    -- Get BettingPros features (for V1.6: f40-f44)
    bettingpros AS (
        SELECT
            player_lookup,
            projection_value as bp_projection,
            -- Performance percentages
            SAFE_DIVIDE(perf_last_5_over, perf_last_5_over + perf_last_5_under) as perf_last_5_pct,
            SAFE_DIVIDE(perf_last_10_over, perf_last_10_over + perf_last_10_under) as perf_last_10_pct,
            -- Calculate implied probability from American odds
            CASE
                WHEN over_odds < 0 THEN ABS(over_odds) / (ABS(over_odds) + 100.0)
                ELSE 100.0 / (over_odds + 100.0)
            END as over_implied_prob,
            ROW_NUMBER() OVER (
                PARTITION BY player_lookup
                ORDER BY game_date DESC
            ) as rn
        FROM `{project}.mlb_raw.bp_pitcher_props`
        WHERE game_date = @game_date
          AND market_name = 'pitcher-strikeouts'
    ),
    -- Get season swing metrics from Fangraphs (for V1.6: f19, f19b, f19c)
    fangraphs AS (
        SELECT
            player_lookup,
            swstr_pct as season_swstr_pct,
            csw_pct as season_csw_pct,
            o_swing_pct as season_chase_pct  -- chase = swing at pitches outside zone
        FROM `{project}.mlb_raw.fangraphs_pitcher_season_stats`
        WHERE season_year = EXTRACT(YEAR FROM @game_date)
    )

    SELECT
        p.*,
        l.strikeouts_line,
        l.over_odds,
        l.under_odds,
        l.minutes_before_tipoff,
        -- Line-relative features (f30-f32)
        SAFE_SUBTRACT(p.k_avg_last_5, l.strikeouts_line) as k_avg_vs_line,
        SAFE_SUBTRACT(COALESCE(bp.bp_projection, p.k_avg_last_5), l.strikeouts_line) as projected_vs_line,
        l.strikeouts_line as line_level,
        -- Season swing metrics (f19, f19b, f19c)
        fg.season_swstr_pct,
        fg.season_csw_pct,
        fg.season_chase_pct,
        -- BettingPros features (f40-f44)
        bp.bp_projection,
        SAFE_SUBTRACT(bp.bp_projection, l.strikeouts_line) as projection_diff,
        bp.perf_last_5_pct,
        bp.perf_last_10_pct,
        bp.over_implied_prob,
        -- Rolling statcast (f50-f53)
        sr.swstr_pct_last_3,
        sr.fb_velocity_last_3,
        sr.swstr_trend,
        sr.velocity_change,
        sr.swstr_pct_season_prior,
        sr.statcast_games_count
    FROM pitchers p
    -- Join using normalized lookup (remove underscores from pitcher_game_summary format)
    LEFT JOIN lines l ON LOWER(REPLACE(p.pitcher_lookup, '_', '')) = l.player_lookup_normalized AND l.rn = 1
    LEFT JOIN statcast_rolling sr ON p.pitcher_lookup = sr.player_lookup
    LEFT JOIN bettingpros bp ON LOWER(REPLACE(p.pitcher_lookup, '_', '')) = bp.player_lookup AND bp.rn = 1
    LEFT JOIN fangraphs fg ON LOWER(REPLACE(p.pitcher_lookup, '_', '')) = fg.player_lookup
    """.format(project=PROJECT_ID)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    result = client.query(query, job_config=job_config).result()
    return [dict(row) for row in result]


def build_features_dict(pitcher_data: Dict, include_v1_6_features: bool = False) -> Dict:
    """Build features dictionary from pitcher data

    V1.4 features: 25 total (rolling, season, context, workload, bottom-up)
    V1.6 features: 35 total (adds swing metrics, line-relative, BettingPros, rolling statcast)
    """
    # Base features (V1.4 compatible)
    features = {
        # Rolling stats (f00-f04)
        'f00_k_avg_last_3': pitcher_data.get('k_avg_last_3'),
        'f01_k_avg_last_5': pitcher_data.get('k_avg_last_5'),
        'f02_k_avg_last_10': pitcher_data.get('k_avg_last_10'),
        'f03_k_std_last_10': pitcher_data.get('k_std_last_10'),
        'f04_ip_avg_last_5': pitcher_data.get('ip_avg_last_5'),
        # Season stats (f05-f09)
        'f05_season_k_per_9': pitcher_data.get('season_k_per_9'),
        'f06_season_era': pitcher_data.get('era_rolling_10'),
        'f07_season_whip': pitcher_data.get('whip_rolling_10'),
        'f08_season_games': pitcher_data.get('games_started'),
        'f09_season_k_total': pitcher_data.get('strikeouts_total'),
        # Game context (f10)
        'f10_is_home': 1 if pitcher_data.get('is_home') else 0,
        # Opponent/Ballpark (f15-f16)
        'f15_opponent_team_k_rate': pitcher_data.get('opponent_team_k_rate'),
        'f16_ballpark_k_factor': pitcher_data.get('ballpark_k_factor'),
        # Temporal (f17-f18)
        'f17_month_of_season': pitcher_data.get('month_of_season'),
        'f18_days_into_season': pitcher_data.get('days_into_season'),
        # Workload (f20-f23)
        'f20_days_rest': pitcher_data.get('days_rest'),
        'f21_games_last_30_days': pitcher_data.get('games_last_30_days'),
        'f22_pitch_count_avg': pitcher_data.get('pitch_count_avg'),
        'f23_season_ip_total': pitcher_data.get('season_ip_total'),
        # Context (f24)
        'f24_is_postseason': 0,  # Default to regular season
        # Bottom-up (f25-f28, f33) - V1.4 specific
        'f25_bottom_up_k_expected': pitcher_data.get('bottom_up_k_expected'),
        'f26_lineup_k_vs_hand': pitcher_data.get('lineup_k_vs_hand'),
        'f27_avg_k_vs_opponent': pitcher_data.get('avg_k_vs_opponent'),
        'f28_games_vs_opponent': pitcher_data.get('games_vs_opponent'),
        'f33_lineup_weak_spots': pitcher_data.get('lineup_weak_spots'),
    }

    # Add V1.6 features if requested (35 total features)
    if include_v1_6_features:
        features.update({
            # Season swing metrics (f19, f19b, f19c)
            'f19_season_swstr_pct': pitcher_data.get('season_swstr_pct') or pitcher_data.get('swstr_pct_season_prior'),
            'f19b_season_csw_pct': pitcher_data.get('season_csw_pct'),
            'f19c_season_chase_pct': pitcher_data.get('season_chase_pct'),
            # Line-relative features (f30-f32)
            'f30_k_avg_vs_line': pitcher_data.get('k_avg_vs_line'),
            'f31_projected_vs_line': pitcher_data.get('projected_vs_line'),
            'f32_line_level': pitcher_data.get('line_level') or pitcher_data.get('strikeouts_line'),
            # BettingPros features (f40-f44)
            'f40_bp_projection': pitcher_data.get('bp_projection'),
            'f41_projection_diff': pitcher_data.get('projection_diff'),
            'f42_perf_last_5_pct': pitcher_data.get('perf_last_5_pct'),
            'f43_perf_last_10_pct': pitcher_data.get('perf_last_10_pct'),
            'f44_over_implied_prob': pitcher_data.get('over_implied_prob'),
            # Rolling statcast (f50-f53)
            'f50_swstr_pct_last_3': pitcher_data.get('swstr_pct_last_3'),
            'f51_fb_velocity_last_3': pitcher_data.get('fb_velocity_last_3'),
            'f52_swstr_trend': pitcher_data.get('swstr_trend'),
            'f53_velocity_change': pitcher_data.get('velocity_change'),
        })

    # Add raw feature names for red flag checks (predictor expects these)
    features.update({
        'season_games_started': pitcher_data.get('games_started'),
        'rolling_stats_games': pitcher_data.get('rolling_stats_games'),
        'ip_avg_last_5': pitcher_data.get('ip_avg_last_5'),
        'k_std_last_10': pitcher_data.get('k_std_last_10'),
        'days_rest': pitcher_data.get('days_rest'),
        'games_last_30_days': pitcher_data.get('games_last_30_days'),
        'season_swstr_pct': pitcher_data.get('season_swstr_pct') or pitcher_data.get('swstr_pct_season_prior'),
        'swstr_trend': pitcher_data.get('swstr_trend'),
        'strikeouts_line': pitcher_data.get('strikeouts_line'),
        'team_abbr': pitcher_data.get('team_abbr'),
        'player_lookup': pitcher_data.get('pitcher_lookup'),
        'k_avg_last_5': pitcher_data.get('k_avg_last_5'),  # For confidence calc
    })

    return features


def run_shadow_predictions(pitchers: List[Dict], game_date: date) -> List[ShadowPrediction]:
    """Run both V1.4 and V1.6 predictions for all pitchers"""
    from predictions.mlb.pitcher_strikeouts_predictor import PitcherStrikeoutsPredictor

    # Initialize both models
    logger.info(f"Loading V1.4 champion from: {V1_4_MODEL_PATH}")
    v1_4_predictor = PitcherStrikeoutsPredictor(model_path=V1_4_MODEL_PATH)
    v1_4_predictor.load_model()
    logger.info(f"V1.4 loaded: {v1_4_predictor.model_metadata.get('model_id', 'unknown')}")

    logger.info(f"Loading V1.6 challenger from: {V1_6_MODEL_PATH}")
    v1_6_predictor = PitcherStrikeoutsPredictor(model_path=V1_6_MODEL_PATH)
    v1_6_predictor.load_model()
    logger.info(f"V1.6 loaded: {v1_6_predictor.model_metadata.get('model_id', 'unknown')}")

    results = []
    skipped = 0

    for pitcher_data in pitchers:
        pitcher_lookup = pitcher_data['pitcher_lookup']
        strikeouts_line = pitcher_data.get('strikeouts_line')

        # Skip pitchers without betting lines
        if strikeouts_line is None:
            logger.debug(f"Skipping {pitcher_lookup}: No betting line")
            skipped += 1
            continue

        # Build features for V1.4
        features_v1_4 = build_features_dict(pitcher_data, include_v1_6_features=False)

        # Build features for V1.6 (includes rolling statcast)
        features_v1_6 = build_features_dict(pitcher_data, include_v1_6_features=True)

        # Run V1.4 prediction
        try:
            v1_4_result = v1_4_predictor.predict(
                pitcher_lookup=pitcher_lookup,
                features=features_v1_4,
                strikeouts_line=strikeouts_line
            )
        except Exception as e:
            logger.warning(f"V1.4 prediction failed for {pitcher_lookup}: {e}")
            continue

        # Run V1.6 prediction
        try:
            v1_6_result = v1_6_predictor.predict(
                pitcher_lookup=pitcher_lookup,
                features=features_v1_6,
                strikeouts_line=strikeouts_line
            )
        except Exception as e:
            logger.warning(f"V1.6 prediction failed for {pitcher_lookup}: {e}")
            continue

        # Extract predictions
        v1_4_pred = v1_4_result.get('predicted_strikeouts', 0) or 0
        v1_6_pred = v1_6_result.get('predicted_strikeouts', 0) or 0

        results.append(ShadowPrediction(
            pitcher_lookup=pitcher_lookup,
            game_date=str(game_date),
            game_id=pitcher_data.get('game_id', ''),
            team_abbr=pitcher_data.get('team_abbr', ''),
            opponent_team_abbr=pitcher_data.get('opponent_team_abbr', ''),
            strikeouts_line=strikeouts_line,
            # V1.4 results
            v1_4_predicted=v1_4_pred,
            v1_4_confidence=v1_4_result.get('confidence', 0),
            v1_4_recommendation=v1_4_result.get('recommendation', 'PASS'),
            v1_4_edge=v1_4_result.get('edge'),
            # V1.6 results
            v1_6_predicted=v1_6_pred,
            v1_6_confidence=v1_6_result.get('confidence', 0),
            v1_6_recommendation=v1_6_result.get('recommendation', 'PASS'),
            v1_6_edge=v1_6_result.get('edge'),
            # Comparison
            prediction_diff=v1_6_pred - v1_4_pred,
            recommendation_agrees=(
                v1_4_result.get('recommendation') == v1_6_result.get('recommendation')
            ),
            # Metadata
            v1_4_model_version=v1_4_result.get('model_version', 'unknown'),
            v1_6_model_version=v1_6_result.get('model_version', 'unknown'),
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))

    logger.info(f"Generated {len(results)} shadow predictions")
    logger.info(f"Skipped {skipped} pitchers (no betting line)")

    return results


def write_to_bigquery(
    client: bigquery.Client,
    predictions: List[ShadowPrediction],
    dry_run: bool = False
) -> int:
    """Write shadow predictions to BigQuery"""
    if dry_run:
        logger.info(f"DRY RUN: Would write {len(predictions)} predictions")
        return len(predictions)

    if not predictions:
        logger.info("No predictions to write")
        return 0

    # Convert to rows
    rows = [asdict(p) for p in predictions]

    table_id = f"{PROJECT_ID}.mlb_predictions.shadow_mode_predictions"

    # Define schema (must match table definition exactly)
    schema = [
        bigquery.SchemaField("pitcher_lookup", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("game_date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("game_id", "STRING"),
        bigquery.SchemaField("team_abbr", "STRING"),
        bigquery.SchemaField("opponent_team_abbr", "STRING"),
        bigquery.SchemaField("strikeouts_line", "FLOAT64"),
        # V1.4
        bigquery.SchemaField("v1_4_predicted", "FLOAT64"),
        bigquery.SchemaField("v1_4_confidence", "FLOAT64"),
        bigquery.SchemaField("v1_4_recommendation", "STRING"),
        bigquery.SchemaField("v1_4_edge", "FLOAT64"),
        # V1.6
        bigquery.SchemaField("v1_6_predicted", "FLOAT64"),
        bigquery.SchemaField("v1_6_confidence", "FLOAT64"),
        bigquery.SchemaField("v1_6_recommendation", "STRING"),
        bigquery.SchemaField("v1_6_edge", "FLOAT64"),
        # Comparison
        bigquery.SchemaField("prediction_diff", "FLOAT64"),
        bigquery.SchemaField("recommendation_agrees", "BOOLEAN"),
        # Metadata
        bigquery.SchemaField("v1_4_model_version", "STRING"),
        bigquery.SchemaField("v1_6_model_version", "STRING"),
        bigquery.SchemaField("timestamp", "TIMESTAMP"),
    ]

    # Create table if not exists
    table = bigquery.Table(table_id, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="game_date",
    )

    try:
        client.create_table(table)
        logger.info(f"Created table {table_id}")
    except Exception:
        pass  # Table already exists

    # Insert rows using batch load (more reliable than streaming)
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )

    load_job = client.load_table_from_json(rows, table_id, job_config=job_config)
    load_job.result(timeout=60)

    if load_job.errors:
        logger.error(f"BigQuery load errors: {load_job.errors}")
        return 0

    logger.info(f"Wrote {len(rows)} predictions to {table_id}")
    return len(rows)


def print_summary(predictions: List[ShadowPrediction]):
    """Print summary statistics"""
    if not predictions:
        print("\nNo predictions generated")
        return

    print("\n" + "=" * 70)
    print("MLB SHADOW MODE SUMMARY - V1.4 vs V1.6")
    print("=" * 70)

    # Basic stats
    print(f"\nTotal predictions: {len(predictions)}")

    # Prediction differences
    diffs = [p.prediction_diff for p in predictions]
    print(f"\nPrediction Differences (V1.6 - V1.4):")
    print(f"  Mean: {sum(diffs) / len(diffs):+.2f} K")
    print(f"  Min:  {min(diffs):+.2f} K")
    print(f"  Max:  {max(diffs):+.2f} K")

    # Recommendation comparison
    agree = sum(1 for p in predictions if p.recommendation_agrees)
    print(f"\nRecommendation Agreement:")
    print(f"  Same:      {agree} ({100 * agree / len(predictions):.1f}%)")
    print(f"  Different: {len(predictions) - agree} ({100 * (len(predictions) - agree) / len(predictions):.1f}%)")

    # OVER/UNDER breakdown
    v1_4_overs = sum(1 for p in predictions if p.v1_4_recommendation == 'OVER')
    v1_6_overs = sum(1 for p in predictions if p.v1_6_recommendation == 'OVER')
    v1_4_unders = sum(1 for p in predictions if p.v1_4_recommendation == 'UNDER')
    v1_6_unders = sum(1 for p in predictions if p.v1_6_recommendation == 'UNDER')

    print(f"\nRecommendation Breakdown:")
    print(f"  V1.4: {v1_4_overs} OVER, {v1_4_unders} UNDER, {len(predictions) - v1_4_overs - v1_4_unders} PASS")
    print(f"  V1.6: {v1_6_overs} OVER, {v1_6_unders} UNDER, {len(predictions) - v1_6_overs - v1_6_unders} PASS")

    # Confidence comparison
    avg_v1_4_conf = sum(p.v1_4_confidence for p in predictions) / len(predictions)
    avg_v1_6_conf = sum(p.v1_6_confidence for p in predictions) / len(predictions)
    print(f"\nAverage Confidence:")
    print(f"  V1.4: {avg_v1_4_conf:.1f}")
    print(f"  V1.6: {avg_v1_6_conf:.1f}")

    # Edge analysis
    with_edge = [p for p in predictions if p.v1_4_edge is not None and p.v1_6_edge is not None]
    if with_edge:
        v1_4_edges = [abs(p.v1_4_edge) for p in with_edge]
        v1_6_edges = [abs(p.v1_6_edge) for p in with_edge]
        print(f"\nAverage |Edge|:")
        print(f"  V1.4: {sum(v1_4_edges) / len(v1_4_edges):.2f}")
        print(f"  V1.6: {sum(v1_6_edges) / len(v1_6_edges):.2f}")

    print("\n" + "=" * 70)


def run_shadow_mode(game_date: date, dry_run: bool = False) -> Dict:
    """
    Run shadow mode for a given date.

    This is the main entry point that can be called from both CLI and API.

    Args:
        game_date: Date to run predictions for
        dry_run: If True, don't write to BigQuery

    Returns:
        Dict with summary statistics
    """
    logger.info(f"Running MLB shadow mode for {game_date}")

    # Initialize BigQuery client
    client = bigquery.Client(project=PROJECT_ID)

    # Load pitchers
    logger.info("Loading pitchers...")
    pitchers = load_pitchers_for_date(client, game_date)
    logger.info(f"Found {len(pitchers)} starting pitchers")

    if not pitchers:
        logger.warning("No pitchers found for this date")
        return {
            'game_date': game_date.isoformat(),
            'predictions_count': 0,
            'pitchers_found': 0,
            'status': 'no_pitchers'
        }

    # Run predictions
    logger.info("Running shadow predictions...")
    predictions = run_shadow_predictions(pitchers, game_date)

    # Calculate summary stats
    summary = {
        'game_date': game_date.isoformat(),
        'predictions_count': len(predictions),
        'pitchers_found': len(pitchers),
        'dry_run': dry_run,
        'status': 'success'
    }

    if predictions:
        # Prediction differences
        diffs = [p.prediction_diff for p in predictions]
        summary['mean_prediction_diff'] = round(sum(diffs) / len(diffs), 2)

        # Recommendation agreement
        agree = sum(1 for p in predictions if p.recommendation_agrees)
        summary['recommendation_agreement_pct'] = round(100 * agree / len(predictions), 1)

        # OVER/UNDER counts
        summary['v1_4_overs'] = sum(1 for p in predictions if p.v1_4_recommendation == 'OVER')
        summary['v1_4_unders'] = sum(1 for p in predictions if p.v1_4_recommendation == 'UNDER')
        summary['v1_6_overs'] = sum(1 for p in predictions if p.v1_6_recommendation == 'OVER')
        summary['v1_6_unders'] = sum(1 for p in predictions if p.v1_6_recommendation == 'UNDER')

        # Average confidence
        summary['v1_4_avg_confidence'] = round(sum(p.v1_4_confidence for p in predictions) / len(predictions), 1)
        summary['v1_6_avg_confidence'] = round(sum(p.v1_6_confidence for p in predictions) / len(predictions), 1)

    # Print summary (for CLI visibility)
    print_summary(predictions)

    # Write to BigQuery
    rows_written = 0
    if predictions:
        rows_written = write_to_bigquery(client, predictions, dry_run=dry_run)

    summary['rows_written'] = rows_written

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Run MLB shadow mode predictions (V1.4 vs V1.6)"
    )
    parser.add_argument(
        "--date", type=str,
        help="Date to run (YYYY-MM-DD), default: today"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Don't write to BigQuery"
    )
    args = parser.parse_args()

    # Parse date
    if args.date:
        game_date = date.fromisoformat(args.date)
    else:
        game_date = date.today()

    # Run shadow mode
    result = run_shadow_mode(game_date, dry_run=args.dry_run)

    # Print final status
    logger.info(f"Shadow mode complete: {result['predictions_count']} predictions, {result.get('rows_written', 0)} written")


if __name__ == "__main__":
    main()
