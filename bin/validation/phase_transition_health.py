#!/usr/bin/env python3
"""
Phase Transition Health Validator

Validates that data flows correctly through all pipeline phases:
  Phase 2 (Raw) -> Phase 3 (Analytics) -> Phase 4 (Features) -> Phase 5 (Predictions) -> Phase 6 (Export)

For each date, checks:
1. Did Phase 2 scrape boxscores for all scheduled games?
2. Did Phase 3 create analytics for all boxscore games?
3. Did Phase 4 generate features for all analytics players?
4. Did Phase 5 make predictions for players with features?
5. Did Phase 6 export predictions?

Detects:
- Stalled phases (started but never completed)
- Missing data between phases
- Phase timing violations
- Cascading failures

Usage:
    python bin/validation/phase_transition_health.py
    python bin/validation/phase_transition_health.py --date 2026-01-24
    python bin/validation/phase_transition_health.py --days 7

Created: 2026-01-25
Part of: Pipeline Resilience Improvements
"""

import argparse
import os
import sys
from datetime import date, timedelta, datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery

PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')


class TransitionStatus(Enum):
    OK = "ok"
    PARTIAL = "partial"
    MISSING = "missing"
    STALLED = "stalled"


@dataclass
class PhaseTransition:
    """Result of a phase transition check."""
    from_phase: str
    to_phase: str
    status: TransitionStatus
    source_count: int
    target_count: int
    missing_count: int
    conversion_rate: float
    message: str


@dataclass
class DateValidation:
    """Validation results for a single date."""
    game_date: date
    transitions: List[PhaseTransition]
    overall_status: TransitionStatus
    bottleneck_phase: Optional[str]


class PhaseTransitionValidator:
    """
    Validates data flow through pipeline phases.

    The key insight: count-based validation can hide issues when
    data exists but didn't flow through all phases correctly.
    This validator traces data through each transition.
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)

    def validate_date(self, game_date: date) -> DateValidation:
        """Validate all phase transitions for a single date."""
        data = self._query_phase_data(game_date)
        transitions = []

        # Transition 1: Schedule -> Boxscores (Phase 2)
        transitions.append(self._check_schedule_to_boxscores(game_date, data))

        # Transition 2: Boxscores -> Analytics (Phase 3)
        transitions.append(self._check_boxscores_to_analytics(game_date, data))

        # Transition 3: Analytics -> Features (Phase 4)
        transitions.append(self._check_analytics_to_features(game_date, data))

        # Transition 4: Features -> Predictions (Phase 5)
        transitions.append(self._check_features_to_predictions(game_date, data))

        # Transition 5: Predictions -> Grading (Phase 6 indicator)
        transitions.append(self._check_predictions_to_grading(game_date, data))

        # Determine overall status and bottleneck
        overall_status = TransitionStatus.OK
        bottleneck_phase = None

        for t in transitions:
            if t.status == TransitionStatus.MISSING:
                overall_status = TransitionStatus.MISSING
                bottleneck_phase = t.from_phase
                break
            elif t.status == TransitionStatus.STALLED:
                overall_status = TransitionStatus.STALLED
                bottleneck_phase = t.from_phase
            elif t.status == TransitionStatus.PARTIAL and overall_status == TransitionStatus.OK:
                overall_status = TransitionStatus.PARTIAL
                bottleneck_phase = t.from_phase

        return DateValidation(
            game_date=game_date,
            transitions=transitions,
            overall_status=overall_status,
            bottleneck_phase=bottleneck_phase
        )

    def _query_phase_data(self, game_date: date) -> Dict[str, Any]:
        """Query all phase data for a date in one efficient query."""
        query = f"""
        WITH
        -- Phase 1: Schedule (source of truth for games)
        schedule AS (
          SELECT
            COUNT(DISTINCT game_id) as game_count,
            -- Use date+teams to build BDL format for comparison
            ARRAY_AGG(DISTINCT CONCAT(
              FORMAT_DATE('%Y%m%d', game_date), '_',
              away_team_tricode, '_', home_team_tricode
            )) as bdl_game_ids
          FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
          WHERE game_date = '{game_date}' AND game_status = 3
        ),

        -- Phase 2: Boxscores
        boxscores AS (
          SELECT
            COUNT(DISTINCT game_id) as game_count,
            COUNT(DISTINCT player_lookup) as player_count,
            ARRAY_AGG(DISTINCT game_id) as game_ids
          FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
          WHERE game_date = '{game_date}'
        ),

        -- Phase 3: Analytics
        analytics AS (
          SELECT
            COUNT(DISTINCT game_id) as game_count,
            COUNT(DISTINCT player_lookup) as player_count
          FROM `{self.project_id}.nba_analytics.player_game_summary`
          WHERE game_date = '{game_date}'
        ),

        -- Phase 4: Features
        features AS (
          SELECT
            COUNT(DISTINCT game_id) as game_count,
            COUNT(DISTINCT player_lookup) as player_count,
            AVG(feature_quality_score) as avg_quality,
            COUNTIF(feature_quality_score >= 65) as high_quality_count
          FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
          WHERE game_date = '{game_date}'
        ),

        -- Phase 5: Predictions
        predictions AS (
          SELECT
            COUNT(DISTINCT game_id) as game_count,
            COUNT(DISTINCT player_lookup) as player_count,
            COUNT(*) as total_predictions,
            COUNTIF(line_source = 'ACTUAL_PROP') as with_props
          FROM `{self.project_id}.nba_predictions.player_prop_predictions`
          WHERE game_date = '{game_date}'
            AND system_id = 'catboost_v8' AND is_active = TRUE
        ),

        -- Phase 6: Grading (only for past dates)
        grading AS (
          SELECT
            COUNT(*) as graded_count,
            COUNT(DISTINCT player_lookup) as player_count
          FROM `{self.project_id}.nba_predictions.prediction_accuracy`
          WHERE game_date = '{game_date}'
            AND system_id = 'catboost_v8'
        ),

        -- Props available
        props AS (
          SELECT
            COUNT(DISTINCT player_lookup) as player_count
          FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
          WHERE game_date = '{game_date}'
        )

        SELECT
          s.game_count as schedule_games,
          s.bdl_game_ids as schedule_bdl_ids,
          b.game_count as boxscore_games,
          b.player_count as boxscore_players,
          b.game_ids as boxscore_game_ids,
          a.game_count as analytics_games,
          a.player_count as analytics_players,
          f.game_count as feature_games,
          f.player_count as feature_players,
          f.avg_quality as feature_avg_quality,
          f.high_quality_count as feature_high_quality,
          p.game_count as prediction_games,
          p.player_count as prediction_players,
          p.total_predictions as total_predictions,
          p.with_props as predictions_with_props,
          g.graded_count as graded_count,
          g.player_count as graded_players,
          pr.player_count as props_players
        FROM schedule s, boxscores b, analytics a, features f, predictions p, grading g, props pr
        """

        results = list(self.client.query(query).result())
        return dict(results[0]) if results else {}

    def _check_schedule_to_boxscores(self, game_date: date, data: Dict) -> PhaseTransition:
        """Check Schedule -> Boxscores transition."""
        schedule_games = data.get('schedule_games') or 0
        boxscore_games = data.get('boxscore_games') or 0

        if schedule_games == 0:
            return PhaseTransition(
                from_phase="schedule",
                to_phase="boxscores",
                status=TransitionStatus.OK,
                source_count=0,
                target_count=0,
                missing_count=0,
                conversion_rate=100.0,
                message="No games scheduled"
            )

        conversion_rate = (boxscore_games / schedule_games * 100) if schedule_games > 0 else 0
        missing = max(0, schedule_games - boxscore_games)

        if boxscore_games == 0:
            status = TransitionStatus.MISSING
            message = f"MISSING: 0/{schedule_games} games have boxscores"
        elif missing > 0:
            status = TransitionStatus.PARTIAL
            message = f"PARTIAL: {missing} games missing boxscores"
        else:
            status = TransitionStatus.OK
            message = f"OK: All {schedule_games} games have boxscores"

        return PhaseTransition(
            from_phase="schedule",
            to_phase="boxscores",
            status=status,
            source_count=schedule_games,
            target_count=boxscore_games,
            missing_count=missing,
            conversion_rate=conversion_rate,
            message=message
        )

    def _check_boxscores_to_analytics(self, game_date: date, data: Dict) -> PhaseTransition:
        """Check Boxscores -> Analytics transition (Phase 3)."""
        boxscore_games = data.get('boxscore_games') or 0
        boxscore_players = data.get('boxscore_players') or 0
        analytics_games = data.get('analytics_games') or 0
        analytics_players = data.get('analytics_players') or 0

        if boxscore_games == 0:
            return PhaseTransition(
                from_phase="boxscores",
                to_phase="analytics",
                status=TransitionStatus.OK,
                source_count=0,
                target_count=0,
                missing_count=0,
                conversion_rate=100.0,
                message="No boxscores to process"
            )

        # Check both games and players
        game_rate = (analytics_games / boxscore_games * 100) if boxscore_games > 0 else 0
        player_rate = (analytics_players / boxscore_players * 100) if boxscore_players > 0 else 0
        missing_games = max(0, boxscore_games - analytics_games)

        if analytics_games == 0:
            status = TransitionStatus.STALLED
            message = f"STALLED: Boxscores exist but no analytics (Phase 3 failed)"
        elif missing_games > 0:
            status = TransitionStatus.PARTIAL
            message = f"PARTIAL: {missing_games} games missing analytics"
        elif player_rate < 90:
            status = TransitionStatus.PARTIAL
            message = f"PARTIAL: Only {player_rate:.0f}% player coverage"
        else:
            status = TransitionStatus.OK
            message = f"OK: All {boxscore_games} games processed"

        return PhaseTransition(
            from_phase="boxscores",
            to_phase="analytics",
            status=status,
            source_count=boxscore_players,
            target_count=analytics_players,
            missing_count=boxscore_players - analytics_players,
            conversion_rate=player_rate,
            message=message
        )

    def _check_analytics_to_features(self, game_date: date, data: Dict) -> PhaseTransition:
        """Check Analytics -> Features transition (Phase 4)."""
        analytics_players = data.get('analytics_players') or 0
        feature_players = data.get('feature_players') or 0
        avg_quality = data.get('feature_avg_quality') or 0

        if analytics_players == 0:
            return PhaseTransition(
                from_phase="analytics",
                to_phase="features",
                status=TransitionStatus.OK,
                source_count=0,
                target_count=0,
                missing_count=0,
                conversion_rate=100.0,
                message="No analytics to process"
            )

        conversion_rate = (feature_players / analytics_players * 100) if analytics_players > 0 else 0
        missing = max(0, analytics_players - feature_players)

        if feature_players == 0:
            status = TransitionStatus.STALLED
            message = f"STALLED: Analytics exist but no features (Phase 4 failed)"
        elif conversion_rate < 80:
            status = TransitionStatus.PARTIAL
            message = f"PARTIAL: Only {conversion_rate:.0f}% feature coverage"
        elif avg_quality < 65:
            status = TransitionStatus.PARTIAL
            message = f"PARTIAL: Low feature quality ({avg_quality:.1f})"
        else:
            status = TransitionStatus.OK
            message = f"OK: {conversion_rate:.0f}% coverage, {avg_quality:.1f} quality"

        return PhaseTransition(
            from_phase="analytics",
            to_phase="features",
            status=status,
            source_count=analytics_players,
            target_count=feature_players,
            missing_count=missing,
            conversion_rate=conversion_rate,
            message=message
        )

    def _check_features_to_predictions(self, game_date: date, data: Dict) -> PhaseTransition:
        """Check Features -> Predictions transition (Phase 5)."""
        feature_players = data.get('feature_players') or 0
        feature_high_quality = data.get('feature_high_quality') or 0
        prediction_players = data.get('prediction_players') or 0
        props_players = data.get('props_players') or 0

        if feature_players == 0:
            return PhaseTransition(
                from_phase="features",
                to_phase="predictions",
                status=TransitionStatus.OK,
                source_count=0,
                target_count=0,
                missing_count=0,
                conversion_rate=100.0,
                message="No features to process"
            )

        # Predictions are for players with features AND props
        # So we compare against high quality features or props
        expected = min(feature_high_quality, props_players) if props_players > 0 else feature_high_quality
        conversion_rate = (prediction_players / expected * 100) if expected > 0 else 0

        if prediction_players == 0 and props_players > 0:
            status = TransitionStatus.STALLED
            message = f"STALLED: Features/props exist but no predictions (Phase 5 failed)"
        elif conversion_rate < 50:
            status = TransitionStatus.PARTIAL
            message = f"PARTIAL: Only {conversion_rate:.0f}% prediction coverage"
        else:
            status = TransitionStatus.OK
            message = f"OK: {prediction_players} players predicted"

        return PhaseTransition(
            from_phase="features",
            to_phase="predictions",
            status=status,
            source_count=expected,
            target_count=prediction_players,
            missing_count=max(0, expected - prediction_players),
            conversion_rate=conversion_rate,
            message=message
        )

    def _check_predictions_to_grading(self, game_date: date, data: Dict) -> PhaseTransition:
        """Check Predictions -> Grading transition (Phase 6)."""
        predictions_with_props = data.get('predictions_with_props') or 0
        graded_count = data.get('graded_count') or 0

        # Only check grading for past dates
        if game_date >= date.today():
            return PhaseTransition(
                from_phase="predictions",
                to_phase="grading",
                status=TransitionStatus.OK,
                source_count=predictions_with_props,
                target_count=0,
                missing_count=0,
                conversion_rate=0,
                message="Future date - grading not expected"
            )

        if predictions_with_props == 0:
            return PhaseTransition(
                from_phase="predictions",
                to_phase="grading",
                status=TransitionStatus.OK,
                source_count=0,
                target_count=0,
                missing_count=0,
                conversion_rate=100.0,
                message="No predictions to grade"
            )

        conversion_rate = (graded_count / predictions_with_props * 100) if predictions_with_props > 0 else 0
        missing = max(0, predictions_with_props - graded_count)

        if graded_count == 0:
            status = TransitionStatus.STALLED
            message = f"STALLED: {predictions_with_props} predictions not graded"
        elif conversion_rate < 80:
            status = TransitionStatus.PARTIAL
            message = f"PARTIAL: Only {conversion_rate:.0f}% graded"
        else:
            status = TransitionStatus.OK
            message = f"OK: {conversion_rate:.0f}% graded"

        return PhaseTransition(
            from_phase="predictions",
            to_phase="grading",
            status=status,
            source_count=predictions_with_props,
            target_count=graded_count,
            missing_count=missing,
            conversion_rate=conversion_rate,
            message=message
        )


def print_report(validations: List[DateValidation]):
    """Print validation report."""
    print("\n" + "=" * 90)
    print("PHASE TRANSITION HEALTH VALIDATOR")
    print(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 90)

    # Summary
    ok_count = sum(1 for v in validations if v.overall_status == TransitionStatus.OK)
    issues = [v for v in validations if v.overall_status != TransitionStatus.OK]

    print(f"\nDates checked: {len(validations)}")
    print(f"  \U0001F7E2 OK: {ok_count}")
    print(f"  \U0001F7E1 Issues: {len(issues)}")

    # Details by date
    for v in validations:
        status_emoji = {
            TransitionStatus.OK: '\U0001F7E2',
            TransitionStatus.PARTIAL: '\U0001F7E1',
            TransitionStatus.MISSING: '\U0001F534',
            TransitionStatus.STALLED: '\U0001F534'
        }[v.overall_status]

        print(f"\n{'-'*90}")
        print(f"{status_emoji} {v.game_date} - {v.overall_status.value.upper()}")
        if v.bottleneck_phase:
            print(f"   Bottleneck: {v.bottleneck_phase}")

        print(f"\n   {'Phase Transition':<30} {'Status':<10} {'Source':>8} {'Target':>8} {'Rate':>8}")
        print(f"   {'-'*70}")

        for t in v.transitions:
            t_emoji = {
                TransitionStatus.OK: '\U0001F7E2',
                TransitionStatus.PARTIAL: '\U0001F7E1',
                TransitionStatus.MISSING: '\U0001F534',
                TransitionStatus.STALLED: '\U0001F534'
            }[t.status]

            label = f"{t.from_phase} -> {t.to_phase}"
            print(f"   {t_emoji} {label:<28} {t.status.value:<10} {t.source_count:>8} {t.target_count:>8} {t.conversion_rate:>7.1f}%")

    print("\n" + "=" * 90)


def main():
    parser = argparse.ArgumentParser(description="Phase transition health validator")
    parser.add_argument('--date', type=str, help='Specific date (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, default=3, help='Days to check (default: 3)')
    parser.add_argument('--start-date', type=str, help='Start date for range')
    parser.add_argument('--end-date', type=str, help='End date for range')

    args = parser.parse_args()

    validator = PhaseTransitionValidator()

    # Determine dates
    if args.start_date and args.end_date:
        start = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date)
        dates = []
        current = start
        while current <= end:
            dates.append(current)
            current += timedelta(days=1)
    elif args.date:
        dates = [date.fromisoformat(args.date)]
    else:
        dates = [date.today() - timedelta(days=i) for i in range(1, args.days + 1)]

    # Run validation
    validations = []
    for game_date in sorted(dates):
        result = validator.validate_date(game_date)
        validations.append(result)

    print_report(validations)

    # Exit code
    has_critical = any(v.overall_status in [TransitionStatus.MISSING, TransitionStatus.STALLED]
                       for v in validations)
    sys.exit(2 if has_critical else 0)


if __name__ == "__main__":
    main()
