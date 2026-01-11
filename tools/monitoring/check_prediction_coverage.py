#!/usr/bin/env python3
"""
Check prediction coverage and identify gaps.

This tool identifies players who have betting lines but no predictions,
helping to find name resolution issues and other prediction failures.

Usage:
    # Check today's coverage
    python tools/monitoring/check_prediction_coverage.py

    # Check specific date
    python tools/monitoring/check_prediction_coverage.py --date 2026-01-10

    # Show detailed gaps (not just summary)
    python tools/monitoring/check_prediction_coverage.py --detailed

    # Export gaps to CSV for further analysis
    python tools/monitoring/check_prediction_coverage.py --export gaps.csv
"""

import os
import sys
import argparse
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PredictionCoverageChecker:
    """Check prediction coverage and identify gaps."""

    def __init__(self, project_id: str = "nba-props-platform"):
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)

    def get_coverage_summary(self, game_date: date) -> Dict:
        """Get coverage summary for a specific date.

        NOTE 2026-01-10: Coverage is now calculated based on players who ACTUALLY PLAYED,
        not all betting lines. Players with 0 minutes (DNP/inactive) have their bets voided
        by sportsbooks, so they shouldn't count against our coverage.

        Coverage = predictions for players who played / players who played with betting lines
        """
        query = f"""
        WITH betting_lines AS (
            SELECT DISTINCT
                player_lookup,
                MAX(points_line) as line_value
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date = @game_date
            GROUP BY player_lookup
        ),
        predictions AS (
            SELECT DISTINCT player_lookup
            FROM `{self.project_id}.nba_predictions.player_prop_predictions`
            WHERE game_date = @game_date
        ),
        -- Players who actually played (minutes > 0 in box score)
        played_game AS (
            SELECT DISTINCT player_lookup
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date = @game_date
        ),
        -- Alias resolution: map betting API names to roster names
        aliases AS (
            SELECT alias_lookup, nba_canonical_lookup
            FROM `{self.project_id}.nba_reference.player_aliases`
            WHERE is_active = TRUE
        )
        SELECT
            -- Total betting lines
            COUNT(DISTINCT bl.player_lookup) as total_lines,

            -- Players who actually played (with betting lines)
            COUNT(DISTINCT CASE
                WHEN pg.player_lookup IS NOT NULL OR pg_via_alias.player_lookup IS NOT NULL
                THEN bl.player_lookup
            END) as players_who_played,

            -- Voided bets (had lines but didn't play - DNP/inactive)
            COUNT(DISTINCT CASE
                WHEN pg.player_lookup IS NULL AND pg_via_alias.player_lookup IS NULL
                THEN bl.player_lookup
            END) as voided_dnp,

            -- Predictions for players who played
            COUNT(DISTINCT CASE
                WHEN (p.player_lookup IS NOT NULL OR p_via_alias.player_lookup IS NOT NULL)
                AND (pg.player_lookup IS NOT NULL OR pg_via_alias.player_lookup IS NOT NULL)
                THEN bl.player_lookup
            END) as predictions_for_played,

            -- All predictions (including for DNP - legacy metric)
            COUNT(DISTINCT CASE
                WHEN p.player_lookup IS NOT NULL OR p_via_alias.player_lookup IS NOT NULL
                THEN bl.player_lookup
            END) as total_predictions

        FROM betting_lines bl
        -- Alias resolution
        LEFT JOIN aliases a ON bl.player_lookup = a.alias_lookup
        -- Direct match to predictions
        LEFT JOIN predictions p ON bl.player_lookup = p.player_lookup
        -- Alias-resolved predictions
        LEFT JOIN predictions p_via_alias ON a.nba_canonical_lookup = p_via_alias.player_lookup
        -- Direct match to played game
        LEFT JOIN played_game pg ON bl.player_lookup = pg.player_lookup
        -- Alias-resolved played game
        LEFT JOIN played_game pg_via_alias ON a.nba_canonical_lookup = pg_via_alias.player_lookup
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat())
            ]
        )

        result = list(self.client.query(query, job_config=job_config).result())[0]

        # Effective coverage: predictions / players who played (excludes voided bets)
        effective_coverage = (result.predictions_for_played / result.players_who_played * 100) if result.players_who_played > 0 else 0

        # Real gaps: players who played but no prediction
        real_gaps = result.players_who_played - result.predictions_for_played

        return {
            'game_date': game_date,
            'total_lines': result.total_lines,
            'players_who_played': result.players_who_played,
            'voided_dnp': result.voided_dnp,
            'predictions_for_played': result.predictions_for_played,
            'total_predictions': result.total_predictions,
            'real_gaps': real_gaps,
            'effective_coverage_pct': effective_coverage,
            # Legacy metrics for backwards compatibility
            'with_predictions': result.total_predictions,
            'coverage_gap': result.total_lines - result.total_predictions,
            'coverage_pct': (result.total_predictions / result.total_lines * 100) if result.total_lines > 0 else 0
        }

    def get_coverage_gaps(self, game_date: date) -> List[Dict]:
        """Get detailed gaps for a specific date."""
        # NOTE 2026-01-10: Added comprehensive alias resolution for ALL lookups
        # Betting APIs use legal names (carltoncarrington) but our data stores
        # use roster names (bubcarrington). This query now resolves aliases for:
        # - Registry membership
        # - Player context (team, rest days, etc.)
        # - Features (ml_feature_store_v2)
        # - Predictions
        query = f"""
        WITH betting_lines AS (
            SELECT
                player_lookup,
                game_date,
                MAX(points_line) as line_value,
                MAX(bookmaker) as line_source
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date = @game_date
            GROUP BY player_lookup, game_date
        ),
        predictions AS (
            SELECT DISTINCT player_lookup, game_date
            FROM `{self.project_id}.nba_predictions.player_prop_predictions`
            WHERE game_date = @game_date
        ),
        player_context AS (
            SELECT
                player_lookup,
                team_abbr,
                universal_player_id,
                current_points_line,
                days_rest
            FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
            WHERE game_date = @game_date
        ),
        features AS (
            SELECT DISTINCT player_lookup, feature_quality_score
            FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
            WHERE game_date = @game_date
        ),
        -- Players who actually played (have box score data)
        played_game AS (
            SELECT DISTINCT player_lookup
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date = @game_date
        ),
        -- Alias resolution: map alias_lookup -> canonical player_lookup
        aliases AS (
            SELECT alias_lookup, nba_canonical_lookup
            FROM `{self.project_id}.nba_reference.player_aliases`
            WHERE is_active = TRUE
        ),
        registry AS (
            SELECT DISTINCT player_lookup
            FROM `{self.project_id}.nba_reference.nba_players_registry`
        ),
        unresolved AS (
            SELECT normalized_lookup as player_lookup, status
            FROM `{self.project_id}.nba_reference.unresolved_player_names`
            WHERE status = 'pending'
        )
        SELECT
            bl.player_lookup,
            bl.line_value,
            bl.line_source,
            -- Use alias-resolved context if available
            COALESCE(pc.team_abbr, pc_via_alias.team_abbr) as team_abbr,
            COALESCE(pc.universal_player_id, pc_via_alias.universal_player_id) IS NOT NULL as has_universal_id,
            COALESCE(pc.days_rest, pc_via_alias.days_rest) as days_rest,
            COALESCE(pc.current_points_line, pc_via_alias.current_points_line) as context_line,
            -- Use alias-resolved features if available
            COALESCE(f.feature_quality_score, f_via_alias.feature_quality_score) as feature_quality,
            -- Check if player is in registry directly OR via alias
            (r.player_lookup IS NOT NULL OR r_via_alias.player_lookup IS NOT NULL) as in_registry,
            a.nba_canonical_lookup as resolved_via_alias,
            u.player_lookup IS NOT NULL as is_unresolved,
            -- Check if prediction exists (direct or via alias)
            (p.player_lookup IS NOT NULL OR p_via_alias.player_lookup IS NOT NULL) as has_prediction,
            -- Check if player actually played (has box score data)
            (pg.player_lookup IS NOT NULL OR pg_via_alias.player_lookup IS NOT NULL) as actually_played,
            CASE
                -- FIRST: Check if player didn't play - bet would be voided by sportsbook
                -- This takes priority because if they didn't play, other reasons are moot
                WHEN pg.player_lookup IS NULL AND pg_via_alias.player_lookup IS NULL THEN 'BET_VOIDED_DNP'
                -- Player played but not in registry
                WHEN r.player_lookup IS NULL AND r_via_alias.player_lookup IS NULL THEN 'NOT_IN_REGISTRY'
                -- Player played but name unresolved
                WHEN u.player_lookup IS NOT NULL THEN 'NAME_UNRESOLVED'
                -- Player played but no context
                WHEN pc.player_lookup IS NULL AND pc_via_alias.player_lookup IS NULL THEN 'NOT_IN_PLAYER_CONTEXT'
                -- Player played but no features
                WHEN f.player_lookup IS NULL AND f_via_alias.player_lookup IS NULL THEN 'NO_FEATURES'
                -- Player played but low quality features
                WHEN COALESCE(f.feature_quality_score, f_via_alias.feature_quality_score) < 50 THEN 'LOW_QUALITY_FEATURES'
                -- Player played, has features/context, but still no prediction
                ELSE 'UNKNOWN_REASON'
            END as gap_reason
        FROM betting_lines bl
        -- Alias resolution first
        LEFT JOIN aliases a ON bl.player_lookup = a.alias_lookup
        -- Direct predictions lookup
        LEFT JOIN predictions p
            ON bl.player_lookup = p.player_lookup
            AND bl.game_date = p.game_date
        -- Alias-resolved predictions lookup
        LEFT JOIN predictions p_via_alias
            ON a.nba_canonical_lookup = p_via_alias.player_lookup
            AND bl.game_date = p_via_alias.game_date
        -- Direct player context lookup
        LEFT JOIN player_context pc ON bl.player_lookup = pc.player_lookup
        -- Alias-resolved player context lookup
        LEFT JOIN player_context pc_via_alias ON a.nba_canonical_lookup = pc_via_alias.player_lookup
        -- Direct features lookup
        LEFT JOIN features f ON bl.player_lookup = f.player_lookup
        -- Alias-resolved features lookup
        LEFT JOIN features f_via_alias ON a.nba_canonical_lookup = f_via_alias.player_lookup
        -- Direct registry lookup
        LEFT JOIN registry r ON bl.player_lookup = r.player_lookup
        -- Alias-resolved registry lookup
        LEFT JOIN registry r_via_alias ON a.nba_canonical_lookup = r_via_alias.player_lookup
        LEFT JOIN unresolved u ON bl.player_lookup = u.player_lookup
        -- Direct played game lookup (check if player has box score data)
        LEFT JOIN played_game pg ON bl.player_lookup = pg.player_lookup
        -- Alias-resolved played game lookup
        LEFT JOIN played_game pg_via_alias ON a.nba_canonical_lookup = pg_via_alias.player_lookup
        -- Only show gaps where no prediction exists (direct or via alias)
        WHERE p.player_lookup IS NULL AND p_via_alias.player_lookup IS NULL
        ORDER BY bl.line_value DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat())
            ]
        )

        results = []
        for row in self.client.query(query, job_config=job_config).result():
            results.append({
                'player_lookup': row.player_lookup,
                'line_value': row.line_value,
                'line_source': row.line_source,
                'team_abbr': row.team_abbr,
                'has_universal_id': row.has_universal_id,
                'days_rest': row.days_rest,
                'context_line': row.context_line,
                'feature_quality': row.feature_quality,
                'in_registry': row.in_registry,
                'resolved_via_alias': row.resolved_via_alias,  # Shows canonical player if resolved via alias
                'has_prediction': row.has_prediction,  # True if prediction exists (direct or via alias)
                'actually_played': row.actually_played,  # True if player has box score data
                'is_unresolved': row.is_unresolved,
                'gap_reason': row.gap_reason
            })

        return results

    def get_gap_breakdown(self, gaps: List[Dict]) -> Dict:
        """Get breakdown of gap reasons."""
        breakdown = {}
        for gap in gaps:
            reason = gap['gap_reason']
            if reason not in breakdown:
                breakdown[reason] = []
            breakdown[reason].append(gap['player_lookup'])
        return breakdown

    def print_report(self, game_date: date, detailed: bool = False):
        """Print coverage report."""
        logger.info("=" * 70)
        logger.info(f"PREDICTION COVERAGE REPORT: {game_date}")
        logger.info("=" * 70)

        # Summary
        summary = self.get_coverage_summary(game_date)

        logger.info(f"\nBetting Lines Overview:")
        logger.info(f"  Total betting lines:              {summary['total_lines']}")
        logger.info(f"  Players who actually played:      {summary['players_who_played']}")
        logger.info(f"  Voided (DNP/inactive):            {summary['voided_dnp']}")

        logger.info(f"\nPrediction Coverage:")
        logger.info(f"  Predictions for players who played: {summary['predictions_for_played']}")
        logger.info(f"  Real gaps (played, no prediction):  {summary['real_gaps']}")
        logger.info(f"  Effective coverage:                  {summary['effective_coverage_pct']:.1f}%")

        if summary['real_gaps'] == 0 and summary['voided_dnp'] == 0:
            logger.info("\n✅ Full coverage! No gaps found.")
            return

        if summary['real_gaps'] == 0 and not detailed:
            logger.info(f"\n✅ Full effective coverage! All {summary['voided_dnp']} gaps are voided bets (DNP).")
            return

        if summary['real_gaps'] == 0:
            logger.info(f"\n✅ Full effective coverage! All {summary['voided_dnp']} gaps are voided bets (DNP).")

        # Get detailed gaps
        gaps = self.get_coverage_gaps(game_date)
        breakdown = self.get_gap_breakdown(gaps)

        # Separate voided from real gaps
        voided_count = len(breakdown.get('BET_VOIDED_DNP', []))
        real_gap_reasons = {k: v for k, v in breakdown.items() if k != 'BET_VOIDED_DNP'}

        logger.info(f"\nGap Breakdown:")
        if voided_count > 0:
            logger.info(f"  BET_VOIDED_DNP: {voided_count} players (not counted - bets voided)")

        if real_gap_reasons:
            logger.info(f"\n  Real Gaps (actionable):")
            for reason, players in sorted(real_gap_reasons.items(), key=lambda x: -len(x[1])):
                logger.info(f"    {reason}: {len(players)} players")

        # Name resolution issues (actionable)
        name_issues = breakdown.get('NOT_IN_REGISTRY', []) + breakdown.get('NAME_UNRESOLVED', [])
        if name_issues:
            logger.info(f"\n⚠️  NAME RESOLUTION ISSUES ({len(name_issues)} players):")
            logger.info("   These need AI resolution or manual alias creation:")
            for player in name_issues[:10]:
                gap = next(g for g in gaps if g['player_lookup'] == player)
                logger.info(f"     - {player} (line: {gap['line_value']})")
            if len(name_issues) > 10:
                logger.info(f"     ... and {len(name_issues) - 10} more")

        if detailed:
            # Show real gaps first
            real_gaps = [g for g in gaps if g['gap_reason'] != 'BET_VOIDED_DNP']
            voided_gaps = [g for g in gaps if g['gap_reason'] == 'BET_VOIDED_DNP']

            if real_gaps:
                logger.info(f"\nReal Gaps (sorted by line value):")
                for gap in real_gaps[:20]:
                    logger.info(
                        f"  {gap['player_lookup']:<25} "
                        f"line={gap['line_value']:<6} "
                        f"reason={gap['gap_reason']:<25} "
                        f"team={gap['team_abbr'] or 'N/A'}"
                    )
                if len(real_gaps) > 20:
                    logger.info(f"  ... and {len(real_gaps) - 20} more")

            if voided_gaps:
                logger.info(f"\nVoided Bets (DNP - not counted as gaps):")
                for gap in voided_gaps[:10]:
                    logger.info(
                        f"  {gap['player_lookup']:<25} "
                        f"line={gap['line_value']:<6} "
                        f"team={gap['team_abbr'] or 'N/A'}"
                    )
                if len(voided_gaps) > 10:
                    logger.info(f"  ... and {len(voided_gaps) - 10} more")

    def export_gaps(self, game_date: date, output_file: str):
        """Export gaps to CSV."""
        import csv

        gaps = self.get_coverage_gaps(game_date)

        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'player_lookup', 'line_value', 'line_source', 'team_abbr',
                'gap_reason', 'in_registry', 'resolved_via_alias', 'is_unresolved',
                'has_universal_id', 'days_rest', 'context_line', 'feature_quality'
            ])
            writer.writeheader()
            writer.writerows(gaps)

        logger.info(f"Exported {len(gaps)} gaps to {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Check prediction coverage and identify gaps"
    )
    parser.add_argument(
        '--date',
        type=str,
        help='Game date to check (YYYY-MM-DD). Default: today'
    )
    parser.add_argument(
        '--detailed',
        action='store_true',
        help='Show detailed gap list'
    )
    parser.add_argument(
        '--export',
        type=str,
        help='Export gaps to CSV file'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=1,
        help='Number of days to check (default: 1)'
    )

    args = parser.parse_args()

    # Determine date(s) to check
    if args.date:
        check_dates = [datetime.strptime(args.date, '%Y-%m-%d').date()]
    else:
        check_dates = [date.today() - timedelta(days=i) for i in range(args.days)]

    checker = PredictionCoverageChecker()

    for check_date in check_dates:
        checker.print_report(check_date, detailed=args.detailed)

        if args.export and len(check_dates) == 1:
            checker.export_gaps(check_date, args.export)

    return 0


if __name__ == '__main__':
    sys.exit(main())
