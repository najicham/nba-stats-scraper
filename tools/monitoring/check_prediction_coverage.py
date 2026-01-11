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
        """Get coverage summary for a specific date."""
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
        )
        SELECT
            COUNT(DISTINCT bl.player_lookup) as total_lines,
            COUNT(DISTINCT p.player_lookup) as with_predictions,
            COUNT(DISTINCT bl.player_lookup) - COUNT(DISTINCT p.player_lookup) as gap
        FROM betting_lines bl
        LEFT JOIN predictions p ON bl.player_lookup = p.player_lookup
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat())
            ]
        )

        result = list(self.client.query(query, job_config=job_config).result())[0]
        coverage_pct = (result.with_predictions / result.total_lines * 100) if result.total_lines > 0 else 0

        return {
            'game_date': game_date,
            'total_lines': result.total_lines,
            'with_predictions': result.with_predictions,
            'coverage_gap': result.gap,
            'coverage_pct': coverage_pct
        }

    def get_coverage_gaps(self, game_date: date) -> List[Dict]:
        """Get detailed gaps for a specific date."""
        # NOTE 2026-01-10: Added alias resolution to properly check registry membership
        # Previously, players like vincentwilliamsjr would show NOT_IN_REGISTRY even though
        # an alias existed mapping them to vincewilliamsjr (the canonical player)
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
            pc.team_abbr,
            pc.universal_player_id IS NOT NULL as has_universal_id,
            pc.days_rest,
            pc.current_points_line as context_line,
            f.feature_quality_score as feature_quality,
            -- Check if player is in registry directly OR via alias
            (r.player_lookup IS NOT NULL OR r_via_alias.player_lookup IS NOT NULL) as in_registry,
            a.nba_canonical_lookup as resolved_via_alias,
            u.player_lookup IS NOT NULL as is_unresolved,
            CASE
                -- Check both direct registry match and alias-resolved match
                WHEN r.player_lookup IS NULL AND r_via_alias.player_lookup IS NULL THEN 'NOT_IN_REGISTRY'
                WHEN u.player_lookup IS NOT NULL THEN 'NAME_UNRESOLVED'
                WHEN pc.player_lookup IS NULL THEN 'NOT_IN_PLAYER_CONTEXT'
                WHEN f.player_lookup IS NULL THEN 'NO_FEATURES'
                WHEN f.feature_quality_score < 50 THEN 'LOW_QUALITY_FEATURES'
                ELSE 'UNKNOWN_REASON'
            END as gap_reason
        FROM betting_lines bl
        LEFT JOIN predictions p
            ON bl.player_lookup = p.player_lookup
            AND bl.game_date = p.game_date
        LEFT JOIN player_context pc ON bl.player_lookup = pc.player_lookup
        LEFT JOIN features f ON bl.player_lookup = f.player_lookup
        -- Direct registry lookup
        LEFT JOIN registry r ON bl.player_lookup = r.player_lookup
        -- Alias-resolved registry lookup
        LEFT JOIN aliases a ON bl.player_lookup = a.alias_lookup
        LEFT JOIN registry r_via_alias ON a.nba_canonical_lookup = r_via_alias.player_lookup
        LEFT JOIN unresolved u ON bl.player_lookup = u.player_lookup
        WHERE p.player_lookup IS NULL
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
                'resolved_via_alias': row.resolved_via_alias,  # New: shows canonical player if resolved via alias
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
        logger.info(f"\nSummary:")
        logger.info(f"  Total players with betting lines: {summary['total_lines']}")
        logger.info(f"  Players with predictions:         {summary['with_predictions']}")
        logger.info(f"  Coverage gap:                     {summary['coverage_gap']}")
        logger.info(f"  Coverage percentage:              {summary['coverage_pct']:.1f}%")

        if summary['coverage_gap'] == 0:
            logger.info("\n✅ Full coverage! No gaps found.")
            return

        # Get detailed gaps
        gaps = self.get_coverage_gaps(game_date)
        breakdown = self.get_gap_breakdown(gaps)

        logger.info(f"\nGap Breakdown by Reason:")
        for reason, players in sorted(breakdown.items(), key=lambda x: -len(x[1])):
            logger.info(f"  {reason}: {len(players)} players")

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
            logger.info(f"\nAll Gaps (sorted by line value):")
            for gap in gaps[:30]:
                logger.info(
                    f"  {gap['player_lookup']:<25} "
                    f"line={gap['line_value']:<6} "
                    f"reason={gap['gap_reason']:<25} "
                    f"team={gap['team_abbr'] or 'N/A'}"
                )
            if len(gaps) > 30:
                logger.info(f"  ... and {len(gaps) - 30} more")

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
