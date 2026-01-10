#!/usr/bin/env python3
"""
Recover registry failures from historical backfills.

This tool identifies registry failures where the player now exists in the
registry (even if for a different season) and marks them as resolved so
they can be reprocessed.

Usage:
    # Dry run - see what would be fixed
    python tools/player_registry/recover_backfill_failures.py --dry-run

    # Actually fix and reprocess
    python tools/player_registry/recover_backfill_failures.py

    # Just mark as resolved (no reprocess)
    python tools/player_registry/recover_backfill_failures.py --skip-reprocessing
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timezone
from typing import List, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BackfillRecovery:
    """Recover registry failures from historical backfills."""

    def __init__(self, project_id: str = "nba-props-platform"):
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)

    def get_recoverable_failures(self) -> Dict:
        """
        Identify failures where the player now exists in registry.

        Returns dict with:
        - in_registry_unresolved: Players in registry but failure not resolved
        - truly_missing: Players not in registry at all
        - already_resolved: Already have resolved_at set
        """
        query = f"""
        WITH failures AS (
            SELECT
                rf.player_lookup,
                rf.season,
                rf.team_abbr,
                rf.game_date,
                rf.resolved_at,
                rf.reprocessed_at
            FROM `{self.project_id}.nba_processing.registry_failures` rf
        ),
        registry AS (
            SELECT DISTINCT player_lookup
            FROM `{self.project_id}.nba_reference.nba_players_registry`
        )
        SELECT
            CASE
                WHEN rf.reprocessed_at IS NOT NULL THEN 'already_reprocessed'
                WHEN rf.resolved_at IS NOT NULL THEN 'resolved_not_reprocessed'
                WHEN r.player_lookup IS NOT NULL THEN 'in_registry_unresolved'
                ELSE 'truly_missing'
            END as status,
            rf.player_lookup,
            rf.season,
            rf.game_date,
            rf.team_abbr
        FROM failures rf
        LEFT JOIN registry r ON rf.player_lookup = r.player_lookup
        ORDER BY status, rf.season, rf.player_lookup
        """

        results = {
            'already_reprocessed': [],
            'resolved_not_reprocessed': [],
            'in_registry_unresolved': [],
            'truly_missing': []
        }

        for row in self.client.query(query).result(timeout=120):
            results[row.status].append({
                'player_lookup': row.player_lookup,
                'season': row.season,
                'game_date': row.game_date,
                'team_abbr': row.team_abbr
            })

        return results

    def mark_in_registry_as_resolved(self, dry_run: bool = False) -> int:
        """
        Mark failures as resolved where player exists in registry.

        This allows them to be reprocessed without needing AI resolution.
        """
        query = f"""
        UPDATE `{self.project_id}.nba_processing.registry_failures` rf
        SET resolved_at = CURRENT_TIMESTAMP()
        WHERE rf.resolved_at IS NULL
          AND EXISTS (
              SELECT 1
              FROM `{self.project_id}.nba_reference.nba_players_registry` r
              WHERE r.player_lookup = rf.player_lookup
          )
        """

        if dry_run:
            # Count what would be affected
            count_query = f"""
            SELECT COUNT(*) as count
            FROM `{self.project_id}.nba_processing.registry_failures` rf
            WHERE rf.resolved_at IS NULL
              AND EXISTS (
                  SELECT 1
                  FROM `{self.project_id}.nba_reference.nba_players_registry` r
                  WHERE r.player_lookup = rf.player_lookup
              )
            """
            result = list(self.client.query(count_query).result())[0]
            return result.count

        # Actually update
        result = self.client.query(query).result(timeout=120)
        return result.num_dml_affected_rows or 0

    def run_recovery(self, dry_run: bool = False, skip_reprocessing: bool = False) -> Dict:
        """
        Run the full recovery process.

        1. Identify recoverable failures
        2. Mark in-registry failures as resolved
        3. Optionally trigger reprocessing
        """
        logger.info("=" * 60)
        logger.info("BACKFILL RECOVERY TOOL")
        logger.info("=" * 60)

        if dry_run:
            logger.info("DRY RUN MODE - No changes will be made")

        # Step 1: Analyze current state
        logger.info("\nStep 1: Analyzing registry failures...")
        failures = self.get_recoverable_failures()

        summary = {
            'already_reprocessed': len(failures['already_reprocessed']),
            'resolved_not_reprocessed': len(failures['resolved_not_reprocessed']),
            'in_registry_unresolved': len(failures['in_registry_unresolved']),
            'truly_missing': len(failures['truly_missing']),
        }

        logger.info(f"\nCurrent State:")
        logger.info(f"  Already reprocessed:        {summary['already_reprocessed']}")
        logger.info(f"  Resolved, not reprocessed:  {summary['resolved_not_reprocessed']}")
        logger.info(f"  In registry but unresolved: {summary['in_registry_unresolved']} <- CAN FIX")
        logger.info(f"  Truly missing (need AI):    {summary['truly_missing']}")

        # Step 2: Mark in-registry failures as resolved
        if summary['in_registry_unresolved'] > 0:
            logger.info(f"\nStep 2: Marking {summary['in_registry_unresolved']} failures as resolved...")
            marked = self.mark_in_registry_as_resolved(dry_run=dry_run)
            logger.info(f"  {'Would mark' if dry_run else 'Marked'} {marked} failures as resolved")
            summary['marked_resolved'] = marked
        else:
            logger.info("\nStep 2: No in-registry failures to mark")
            summary['marked_resolved'] = 0

        # Step 3: Trigger reprocessing
        if not skip_reprocessing and not dry_run:
            logger.info("\nStep 3: Triggering reprocessing...")
            try:
                from tools.player_registry.resolve_unresolved_batch import BatchResolver
                resolver = BatchResolver()
                reprocess_results = resolver.reprocess_after_resolution()
                summary['reprocessing'] = reprocess_results
                logger.info(f"  Games reprocessed: {reprocess_results.get('games_succeeded', 0)}/{reprocess_results.get('games_attempted', 0)}")
            except Exception as e:
                logger.error(f"  Reprocessing failed: {e}")
                summary['reprocessing_error'] = str(e)
        elif skip_reprocessing:
            logger.info("\nStep 3: Skipped reprocessing (--skip-reprocessing)")
        else:
            logger.info("\nStep 3: Would trigger reprocessing")

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("RECOVERY SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Failures marked as resolved: {summary.get('marked_resolved', 0)}")
        if 'reprocessing' in summary:
            logger.info(f"Games reprocessed: {summary['reprocessing'].get('games_succeeded', 0)}")
        logger.info(f"Still need AI resolution: {summary['truly_missing']}")

        # Print truly missing for reference
        if summary['truly_missing'] > 0:
            logger.info(f"\nPlayers needing AI resolution ({summary['truly_missing']} unique):")
            unique_missing = set()
            for f in failures['truly_missing']:
                unique_missing.add(f['player_lookup'])
            for p in sorted(list(unique_missing))[:20]:
                logger.info(f"  - {p}")
            if len(unique_missing) > 20:
                logger.info(f"  ... and {len(unique_missing) - 20} more")

        return summary


def main():
    parser = argparse.ArgumentParser(
        description="Recover registry failures from historical backfills"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--skip-reprocessing',
        action='store_true',
        help='Only mark as resolved, skip reprocessing'
    )

    args = parser.parse_args()

    recovery = BackfillRecovery()
    results = recovery.run_recovery(
        dry_run=args.dry_run,
        skip_reprocessing=args.skip_reprocessing
    )

    return 0


if __name__ == '__main__':
    sys.exit(main())
