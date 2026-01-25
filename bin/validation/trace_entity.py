#!/usr/bin/env python3
"""
Entity Tracing Script

Traces a player or game through all pipeline phases for debugging.

Usage:
    python bin/validation/trace_entity.py --player "LeBron James" --date 2026-01-24
    python bin/validation/trace_entity.py --game 0022500644

Created: 2026-01-25
Part of: Validation Framework Improvements
"""

import argparse
import logging
from typing import Dict, Optional
from datetime import datetime

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class EntityTracer:
    """Traces entities through the pipeline."""

    def __init__(self, project_id: str = 'nba-props-platform'):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)

    def trace_player(self, player_lookup: str, game_date: str) -> Dict:
        """
        Trace a player through all phases.

        Args:
            player_lookup: Player identifier (lowercase name)
            game_date: Game date (YYYY-MM-DD)

        Returns:
            Dict with phase information
        """
        logger.info(f"Tracing player: {player_lookup} on {game_date}")

        results = {
            'player': player_lookup,
            'date': game_date,
            'phases': {}
        }

        # Phase 1: Schedule
        results['phases']['schedule'] = self._check_schedule(player_lookup, game_date)

        # Phase 2: Boxscore
        results['phases']['boxscore'] = self._check_boxscore(player_lookup, game_date)

        # Phase 3: Analytics
        results['phases']['analytics'] = self._check_analytics(player_lookup, game_date)

        # Phase 4: Features
        results['phases']['features'] = self._check_features(player_lookup, game_date)

        # Phase 5: Prediction
        results['phases']['prediction'] = self._check_prediction(player_lookup, game_date)

        # Phase 6: Grading
        results['phases']['grading'] = self._check_grading(player_lookup, game_date)

        # Analyze root cause
        results['root_cause'] = self._analyze_root_cause(results)

        return results

    def trace_game(self, game_id: str) -> Dict:
        """
        Trace a game through all phases.

        Args:
            game_id: Game identifier (NBA format or BDL format)

        Returns:
            Dict with phase information
        """
        logger.info(f"Tracing game: {game_id}")

        results = {
            'game_id': game_id,
            'phases': {}
        }

        # Phase 1: Schedule
        results['phases']['schedule'] = self._check_game_schedule(game_id)

        # Phase 2: Boxscore
        results['phases']['boxscore'] = self._check_game_boxscore(game_id)

        # Phase 3: Analytics
        results['phases']['analytics'] = self._check_game_analytics(game_id)

        # Phase 4: Features
        results['phases']['features'] = self._check_game_features(game_id)

        # Phase 5: Prediction
        results['phases']['prediction'] = self._check_game_predictions(game_id)

        return results

    # Player tracing methods
    def _check_schedule(self, player_lookup: str, game_date: str) -> Dict:
        """Check if player's team had a game scheduled."""
        query = """
        SELECT game_id, away_team_name, home_team_name, game_status
        FROM `nba_raw.v_nbac_schedule_latest`
        WHERE game_date = @game_date
        """

        results = self._run_query(query, {"game_date": game_date})

        if results:
            return {
                'status': 'exists',
                'games': [
                    {
                        'game_id': r.game_id,
                        'matchup': f"{r.away_team_name} @ {r.home_team_name}",
                        'status': r.game_status
                    }
                    for r in results
                ]
            }
        else:
            return {'status': 'missing', 'message': 'No games scheduled'}

    def _check_boxscore(self, player_lookup: str, game_date: str) -> Dict:
        """Check if player boxscore exists."""
        query = """
        SELECT game_id, points, assists, rebounds, minutes, player_name
        FROM `nba_raw.bdl_player_boxscores`
        WHERE game_date = @game_date AND player_lookup = @player_lookup
        """

        results = self._run_query(query, {
            "game_date": game_date,
            "player_lookup": player_lookup
        })

        if results:
            r = results[0]
            return {
                'status': 'exists',
                'player_name': r.player_name,
                'game_id': r.game_id,
                'stats': {
                    'points': r.points,
                    'assists': r.assists,
                    'rebounds': r.rebounds,
                    'minutes': r.minutes
                }
            }
        else:
            return {'status': 'missing', 'message': 'Boxscore not found'}

    def _check_analytics(self, player_lookup: str, game_date: str) -> Dict:
        """Check if player analytics exists."""
        query = """
        SELECT game_id, points, usage_rate, ts_pct, source_coverage_pct, player_name
        FROM `nba_analytics.player_game_summary`
        WHERE game_date = @game_date AND player_lookup = @player_lookup
        """

        results = self._run_query(query, {
            "game_date": game_date,
            "player_lookup": player_lookup
        })

        if results:
            r = results[0]
            return {
                'status': 'exists',
                'player_name': r.player_name,
                'game_id': r.game_id,
                'metrics': {
                    'points': r.points,
                    'usage_rate': f"{r.usage_rate:.1f}%" if r.usage_rate else None,
                    'ts_pct': f"{r.ts_pct:.1f}%" if r.ts_pct else None,
                    'coverage': f"{r.source_coverage_pct:.1f}%" if r.source_coverage_pct else None
                }
            }
        else:
            return {'status': 'missing', 'message': 'Analytics not computed'}

    def _check_features(self, player_lookup: str, game_date: str) -> Dict:
        """Check if player features exists."""
        query = """
        SELECT
            feature_quality_score,
            is_production_ready,
            points_rolling_avg,
            minutes_rolling_avg,
            created_at,
            player_name
        FROM `nba_precompute.ml_feature_store`
        WHERE game_date = @game_date AND player_lookup = @player_lookup
        """

        results = self._run_query(query, {
            "game_date": game_date,
            "player_lookup": player_lookup
        })

        if results:
            r = results[0]
            return {
                'status': 'exists',
                'player_name': r.player_name,
                'quality_score': r.feature_quality_score,
                'production_ready': r.is_production_ready,
                'features': {
                    'points_avg': r.points_rolling_avg,
                    'minutes_avg': r.minutes_rolling_avg
                },
                'freshness': str(r.created_at) if r.created_at else None
            }
        else:
            return {'status': 'missing', 'message': 'Features not generated'}

    def _check_prediction(self, player_lookup: str, game_date: str) -> Dict:
        """Check if player prediction exists."""
        query = """
        SELECT
            predicted_points,
            confidence_score,
            model_version,
            player_name
        FROM `nba_predictions.player_prop_predictions`
        WHERE game_date = @game_date AND player_lookup = @player_lookup
        """

        results = self._run_query(query, {
            "game_date": game_date,
            "player_lookup": player_lookup
        })

        if results:
            r = results[0]
            return {
                'status': 'exists',
                'player_name': r.player_name,
                'predicted_points': r.predicted_points,
                'confidence': r.confidence_score,
                'model_version': r.model_version
            }
        else:
            return {'status': 'missing', 'message': 'Prediction not generated'}

    def _check_grading(self, player_lookup: str, game_date: str) -> Dict:
        """Check if prediction grading exists."""
        query = """
        SELECT
            actual_points,
            prediction_result,
            margin,
            player_name
        FROM `nba_predictions.prediction_accuracy`
        WHERE game_date = @game_date AND player_lookup = @player_lookup
        """

        results = self._run_query(query, {
            "game_date": game_date,
            "player_lookup": player_lookup
        })

        if results:
            r = results[0]
            return {
                'status': 'exists',
                'player_name': r.player_name,
                'actual_points': r.actual_points,
                'result': r.prediction_result,
                'margin': r.margin
            }
        else:
            return {'status': 'missing', 'message': 'Grading not performed'}

    # Game tracing methods (simplified)
    def _check_game_schedule(self, game_id: str) -> Dict:
        """Check if game is in schedule."""
        query = """
        SELECT game_id, game_date, away_team_name, home_team_name, game_status
        FROM `nba_raw.v_nbac_schedule_latest`
        WHERE game_id = @game_id
        """

        results = self._run_query(query, {"game_id": game_id})

        if results:
            r = results[0]
            return {
                'status': 'exists',
                'game_date': str(r.game_date),
                'matchup': f"{r.away_team_name} @ {r.home_team_name}",
                'game_status': r.game_status
            }
        else:
            return {'status': 'missing', 'message': 'Game not in schedule'}

    def _check_game_boxscore(self, game_id: str) -> Dict:
        """Check if game boxscore exists."""
        query = """
        SELECT COUNT(DISTINCT player_lookup) as player_count
        FROM `nba_raw.bdl_player_boxscores`
        WHERE game_id = @game_id
        """

        results = self._run_query(query, {"game_id": game_id})

        if results and results[0].player_count > 0:
            return {
                'status': 'exists',
                'player_count': results[0].player_count
            }
        else:
            return {'status': 'missing', 'message': 'Boxscore not found'}

    def _check_game_analytics(self, game_id: str) -> Dict:
        """Check if game analytics exists."""
        query = """
        SELECT COUNT(DISTINCT player_lookup) as player_count
        FROM `nba_analytics.player_game_summary`
        WHERE game_id = @game_id
        """

        results = self._run_query(query, {"game_id": game_id})

        if results and results[0].player_count > 0:
            return {
                'status': 'exists',
                'player_count': results[0].player_count
            }
        else:
            return {'status': 'missing', 'message': 'Analytics not computed'}

    def _check_game_features(self, game_id: str) -> Dict:
        """Check if game features exists."""
        query = """
        SELECT
            COUNT(DISTINCT player_lookup) as player_count,
            AVG(feature_quality_score) as avg_quality
        FROM `nba_precompute.ml_feature_store`
        WHERE game_id = @game_id
        """

        results = self._run_query(query, {"game_id": game_id})

        if results and results[0].player_count > 0:
            return {
                'status': 'exists',
                'player_count': results[0].player_count,
                'avg_quality': results[0].avg_quality
            }
        else:
            return {'status': 'missing', 'message': 'Features not generated'}

    def _check_game_predictions(self, game_id: str) -> Dict:
        """Check if game predictions exist."""
        query = """
        SELECT COUNT(DISTINCT player_lookup) as player_count
        FROM `nba_predictions.player_prop_predictions`
        WHERE game_id = @game_id
        """

        results = self._run_query(query, {"game_id": game_id})

        if results and results[0].player_count > 0:
            return {
                'status': 'exists',
                'player_count': results[0].player_count
            }
        else:
            return {'status': 'missing', 'message': 'Predictions not generated'}

    def _analyze_root_cause(self, trace_results: Dict) -> str:
        """Analyze trace results to determine root cause of issues."""
        phases = trace_results['phases']

        # Check where the pipeline stops
        if phases['schedule']['status'] == 'missing':
            return "No games scheduled for this date"

        if phases['boxscore']['status'] == 'missing':
            return "Boxscore not collected - check scraper logs"

        if phases['analytics']['status'] == 'missing':
            return "Analytics not computed - check Phase 3 processor"

        if phases['features']['status'] == 'missing':
            return "Features not generated - check Phase 4 processor"

        if phases['features']['status'] == 'exists':
            quality = phases['features'].get('quality_score', 0)
            production_ready = phases['features'].get('production_ready', False)

            if quality < 70:
                return f"Feature quality too low ({quality:.1f}) - filtered from predictions"

            if not production_ready:
                return "Features marked as not production ready - filtered from predictions"

        if phases['prediction']['status'] == 'missing':
            return "Prediction not generated - check prediction coordinator"

        if phases['grading']['status'] == 'missing':
            return "Grading not performed - check grading processor"

        return "All phases complete"

    def _run_query(self, query: str, params: Dict) -> list:
        """Execute BigQuery query with parameters."""
        try:
            job_config = bigquery.QueryJobConfig()
            job_config.query_parameters = [
                bigquery.ScalarQueryParameter(k, 'STRING', str(v))
                for k, v in params.items()
            ]

            query_job = self.bq_client.query(query, job_config=job_config)
            return list(query_job.result())

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []


def print_player_trace(results: Dict):
    """Print player trace results."""
    print("\n" + "=" * 70)
    print(f"🔍 Tracing: {results['player']} on {results['date']}")
    print("=" * 70)

    phases = results['phases']

    # Phase 1: Schedule
    print("\n📅 Phase 1 (Schedule):")
    schedule = phases['schedule']
    if schedule['status'] == 'exists':
        print(f"  ✅ Games scheduled: {len(schedule['games'])}")
        for game in schedule['games']:
            print(f"     • {game['matchup']} (status: {game['status']})")
    else:
        print(f"  ❌ {schedule['message']}")

    # Phase 2: Boxscore
    print("\n📊 Phase 2 (Boxscore):")
    boxscore = phases['boxscore']
    if boxscore['status'] == 'exists':
        stats = boxscore['stats']
        print(f"  ✅ Boxscore exists: {boxscore['player_name']}")
        print(f"     • Points: {stats['points']}, Assists: {stats['assists']}, "
              f"Rebounds: {stats['rebounds']}, Minutes: {stats['minutes']}")
    else:
        print(f"  ❌ {boxscore['message']}")

    # Phase 3: Analytics
    print("\n📈 Phase 3 (Analytics):")
    analytics = phases['analytics']
    if analytics['status'] == 'exists':
        metrics = analytics['metrics']
        print(f"  ✅ Analytics computed: {analytics['player_name']}")
        print(f"     • Usage Rate: {metrics.get('usage_rate', 'N/A')}, "
              f"TS%: {metrics.get('ts_pct', 'N/A')}, "
              f"Coverage: {metrics.get('coverage', 'N/A')}")
    else:
        print(f"  ❌ {analytics['message']}")

    # Phase 4: Features
    print("\n🎯 Phase 4 (Features):")
    features = phases['features']
    if features['status'] == 'exists':
        print(f"  ✅ Features generated: {features['player_name']}")
        print(f"     • Quality Score: {features['quality_score']:.1f}")
        print(f"     • Production Ready: {'Yes' if features['production_ready'] else 'No'}")
        print(f"     • Points Avg: {features['features'].get('points_avg', 'N/A')}")
    else:
        if features['status'] == 'missing':
            print(f"  ❌ {features['message']}")
        else:
            print(f"  ⚠️  Feature quality degraded")
            print(f"     • Quality Score: {features.get('quality_score', 0):.1f} (expected: >70)")

    # Phase 5: Prediction
    print("\n🔮 Phase 5 (Prediction):")
    prediction = phases['prediction']
    if prediction['status'] == 'exists':
        print(f"  ✅ Prediction generated: {prediction['player_name']}")
        print(f"     • Predicted Points: {prediction['predicted_points']:.1f}")
        print(f"     • Confidence: {prediction['confidence']:.1f}")
    else:
        print(f"  ❌ {prediction['message']}")

    # Phase 6: Grading
    print("\n📝 Phase 6 (Grading):")
    grading = phases['grading']
    if grading['status'] == 'exists':
        print(f"  ✅ Grading performed: {grading['player_name']}")
        print(f"     • Actual Points: {grading['actual_points']}")
        print(f"     • Result: {grading['result']}, Margin: {grading['margin']}")
    else:
        print(f"  ❌ {grading['message']}")

    # Root cause
    print(f"\n🔍 Root Cause: {results['root_cause']}")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description='Trace entity through pipeline')
    parser.add_argument('--player', help='Player name or lookup')
    parser.add_argument('--game', help='Game ID (NBA or BDL format)')
    parser.add_argument('--date', help='Game date (YYYY-MM-DD)', required='--player' in ' '.join(__import__('sys').argv))
    parser.add_argument('--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    tracer = EntityTracer()

    if args.player:
        # Convert player name to lookup format (lowercase, hyphens)
        player_lookup = args.player.lower().replace(' ', '-')
        results = tracer.trace_player(player_lookup, args.date)
        print_player_trace(results)
    elif args.game:
        results = tracer.trace_game(args.game)
        print(f"\n🔍 Game Trace: {args.game}")
        print(f"Results: {results}")
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
