#!/usr/bin/env python3
"""
Batch resolve unresolved player names using AI.

This CLI tool processes all pending unresolved player names, using:
1. AI resolution to determine matches
2. Automatic alias creation for matches
3. Caching to avoid repeated API calls

Usage:
    # Process all pending unresolved names
    python tools/player_registry/resolve_unresolved_batch.py

    # Dry run (show what would be done)
    python tools/player_registry/resolve_unresolved_batch.py --dry-run

    # Limit to specific count
    python tools/player_registry/resolve_unresolved_batch.py --limit 10

    # Process specific names
    python tools/player_registry/resolve_unresolved_batch.py --names marcusmorris kevinknox
"""

import os
import sys
import argparse
import logging
from typing import List, Dict, Optional
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BatchResolver:
    """
    Batch process unresolved player names.
    """

    def __init__(self, project_id: str = None):
        self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.client = bigquery.Client(project=self.project_id)
        self.bq_client = self.client  # Alias for compatibility

        # Import components
        from shared.utils.player_registry.ai_resolver import AINameResolver, ResolutionContext
        from shared.utils.player_registry.alias_manager import AliasManager, AliasRecord
        from shared.utils.player_registry.resolution_cache import ResolutionCache

        self.ai_resolver = AINameResolver()
        self.alias_manager = AliasManager(project_id=self.project_id)
        self.cache = ResolutionCache(project_id=self.project_id)

        self.ResolutionContext = ResolutionContext
        self.AliasRecord = AliasRecord

    def get_pending_unresolved(self, limit: int = None, names: List[str] = None) -> List[Dict]:
        """Get pending unresolved player names."""
        query = f"""
        SELECT DISTINCT
            normalized_lookup,
            original_name,
            team_abbr,
            season,
            source,
            occurrences
        FROM `{self.project_id}.nba_reference.unresolved_player_names`
        WHERE status = 'pending'
        """

        if names:
            query += f" AND normalized_lookup IN UNNEST(@names)"

        query += " ORDER BY occurrences DESC"

        if limit:
            query += f" LIMIT {limit}"

        job_config = bigquery.QueryJobConfig()
        if names:
            job_config.query_parameters = [
                bigquery.ArrayQueryParameter("names", "STRING", names)
            ]

        results = self.client.query(query, job_config=job_config).result(timeout=60)
        return [dict(row) for row in results]

    def get_team_roster(self, team_abbr: str, season: str) -> List[str]:
        """Get team roster from registry."""
        if not team_abbr or not season:
            return []

        query = f"""
        SELECT DISTINCT player_lookup, player_name
        FROM `{self.project_id}.nba_reference.nba_players_registry`
        WHERE team_abbr = @team
        AND season = @season
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("team", "STRING", team_abbr),
                bigquery.ScalarQueryParameter("season", "STRING", season)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result(timeout=60)
            return [f"{row.player_lookup} ({row.player_name})" for row in results]
        except Exception as e:
            logger.warning(f"Error getting roster for {team_abbr}/{season}: {e}")
            return []

    def get_similar_names(self, unresolved_lookup: str) -> List[str]:
        """Get similar names from registry using fuzzy matching."""
        # Get first 5 chars for LIKE matching
        prefix = unresolved_lookup[:5] if len(unresolved_lookup) >= 5 else unresolved_lookup

        query = f"""
        SELECT DISTINCT player_lookup
        FROM `{self.project_id}.nba_reference.nba_players_registry`
        WHERE player_lookup LIKE @pattern
        OR player_lookup LIKE CONCAT(@lookup, '%')
        OR player_lookup LIKE CONCAT('%', @lookup)
        LIMIT 20
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("pattern", "STRING", f"%{prefix}%"),
                bigquery.ScalarQueryParameter("lookup", "STRING", unresolved_lookup)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result(timeout=60)
            return [row.player_lookup for row in results if row.player_lookup != unresolved_lookup]
        except Exception as e:
            logger.warning(f"Error getting similar names for {unresolved_lookup}: {e}")
            return []

    def get_canonical_display_name(self, canonical_lookup: str) -> str:
        """Get display name for canonical lookup."""
        query = f"""
        SELECT player_name
        FROM `{self.project_id}.nba_reference.nba_players_registry`
        WHERE player_lookup = @lookup
        LIMIT 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("lookup", "STRING", canonical_lookup)
            ]
        )

        try:
            results = list(self.client.query(query, job_config=job_config).result(timeout=60))
            if results:
                return results[0].player_name
            return canonical_lookup
        except Exception:
            return canonical_lookup

    def mark_resolved(self, normalized_lookup: str, resolution_type: str,
                     resolved_to: str = None, notes: str = None):
        """Mark unresolved name as resolved."""
        query = f"""
        UPDATE `{self.project_id}.nba_reference.unresolved_player_names`
        SET
            status = 'resolved',
            resolution_type = @resolution_type,
            resolved_to_name = @resolved_to,
            notes = @notes,
            reviewed_by = 'ai_resolver',
            reviewed_at = CURRENT_TIMESTAMP()
        WHERE normalized_lookup = @lookup
        AND status = 'pending'
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("lookup", "STRING", normalized_lookup),
                bigquery.ScalarQueryParameter("resolution_type", "STRING", resolution_type),
                bigquery.ScalarQueryParameter("resolved_to", "STRING", resolved_to),
                bigquery.ScalarQueryParameter("notes", "STRING", notes)
            ]
        )

        try:
            self.client.query(query, job_config=job_config).result(timeout=60)
            logger.debug(f"Marked {normalized_lookup} as resolved")
        except Exception as e:
            logger.error(f"Error marking {normalized_lookup} as resolved: {e}")

    def mark_registry_failures_resolved(self, player_lookup: str) -> int:
        """Mark all registry failures for this player as resolved."""
        query = f"""
        UPDATE `{self.project_id}.nba_processing.registry_failures`
        SET resolved_at = CURRENT_TIMESTAMP()
        WHERE player_lookup = @player_lookup
          AND resolved_at IS NULL
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup)
            ]
        )
        result = self.bq_client.query(query, job_config=job_config).result(timeout=60)
        return result.num_dml_affected_rows or 0

    def process_single(self, unresolved: Dict, dry_run: bool = False) -> Dict:
        """
        Process a single unresolved name.

        Returns:
            Dict with resolution details
        """
        lookup = unresolved['normalized_lookup']
        display = unresolved.get('original_name', lookup)
        team = unresolved.get('team_abbr')
        season = unresolved.get('season')
        source = unresolved.get('source', 'unknown')

        logger.info(f"Processing: {lookup} ({team}/{season})")

        # Check cache first
        cached = self.cache.get_cached(lookup)
        if cached:
            logger.info(f"  Using cached decision: {cached.resolution_type}")
            resolution = cached
        else:
            # Build context
            roster = self.get_team_roster(team, season)
            similar = self.get_similar_names(lookup)

            context = self.ResolutionContext(
                unresolved_lookup=lookup,
                unresolved_display=display,
                team_abbr=team,
                season=season,
                team_roster=roster,
                similar_names=similar,
                source=source
            )

            # Resolve with AI
            resolution = self.ai_resolver.resolve_single(context)

            # Cache the result
            if not dry_run:
                self.cache.cache_resolution(resolution, {
                    'team_abbr': team,
                    'season': season,
                    'candidates': similar
                })

        result = {
            'lookup': lookup,
            'resolution_type': resolution.resolution_type,
            'canonical_lookup': resolution.canonical_lookup,
            'confidence': resolution.confidence,
            'reasoning': resolution.reasoning
        }

        if dry_run:
            logger.info(f"  [DRY RUN] Would resolve as: {resolution.resolution_type}")
            return result

        # Take action based on resolution
        if resolution.resolution_type == 'MATCH' and resolution.canonical_lookup:
            # Create alias
            canonical_display = self.get_canonical_display_name(resolution.canonical_lookup)

            alias = self.AliasRecord(
                alias_lookup=lookup,
                nba_canonical_lookup=resolution.canonical_lookup,
                alias_display=display,
                nba_canonical_display=canonical_display,
                alias_type='ai_resolved',
                alias_source='ai_resolver',
                confidence=resolution.confidence,
                ai_model=resolution.ai_model,
                notes=resolution.reasoning
            )

            if self.alias_manager.create_alias(alias):
                logger.info(f"  Created alias: {lookup} -> {resolution.canonical_lookup}")
                result['alias_created'] = True

                # Mark registry failures as resolved
                failures_resolved = self.mark_registry_failures_resolved(lookup)
                if failures_resolved > 0:
                    logger.info(f"  Marked {failures_resolved} registry_failures record(s) as resolved")
                result['failures_resolved'] = failures_resolved
            else:
                logger.warning(f"  Failed to create alias for {lookup}")
                result['alias_created'] = False
                result['failures_resolved'] = 0

            self.mark_resolved(lookup, 'alias_created', resolution.canonical_lookup, resolution.reasoning)

        elif resolution.resolution_type == 'NEW_PLAYER':
            self.mark_resolved(lookup, 'new_player_detected', None, resolution.reasoning)
            logger.info(f"  Marked as new player")

        elif resolution.resolution_type == 'DATA_ERROR':
            self.mark_resolved(lookup, 'data_error', None, resolution.reasoning)
            logger.info(f"  Marked as data error")

        return result

    def process_all(self, limit: int = None, names: List[str] = None,
                   dry_run: bool = False) -> Dict:
        """
        Process all pending unresolved names.

        Returns:
            Summary of processing results
        """
        pending = self.get_pending_unresolved(limit=limit, names=names)

        if not pending:
            logger.info("No pending unresolved names to process")
            return {
                'total': 0, 'processed': 0, 'matches': 0,
                'new_players': 0, 'data_errors': 0, 'aliases_created': 0
            }

        logger.info(f"Found {len(pending)} pending unresolved names")

        results = {
            'total': len(pending),
            'processed': 0,
            'matches': 0,
            'new_players': 0,
            'data_errors': 0,
            'aliases_created': 0,
            'details': []
        }

        for i, unresolved in enumerate(pending, 1):
            logger.info(f"\n[{i}/{len(pending)}] Processing...")

            try:
                result = self.process_single(unresolved, dry_run=dry_run)
                results['processed'] += 1
                results['details'].append(result)

                if result['resolution_type'] == 'MATCH':
                    results['matches'] += 1
                    if result.get('alias_created'):
                        results['aliases_created'] += 1
                elif result['resolution_type'] == 'NEW_PLAYER':
                    results['new_players'] += 1
                elif result['resolution_type'] == 'DATA_ERROR':
                    results['data_errors'] += 1

            except Exception as e:
                logger.error(f"Error processing {unresolved['normalized_lookup']}: {e}")

        return results


def main():
    parser = argparse.ArgumentParser(
        description="Batch resolve unresolved player names using AI"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of names to process'
    )
    parser.add_argument(
        '--names',
        nargs='+',
        help='Process specific names only'
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("BATCH AI NAME RESOLUTION")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    resolver = BatchResolver()
    results = resolver.process_all(
        limit=args.limit,
        names=args.names,
        dry_run=args.dry_run
    )

    logger.info("\n" + "=" * 60)
    logger.info("RESULTS SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total pending:    {results['total']}")
    logger.info(f"Processed:        {results['processed']}")
    logger.info(f"Matches:          {results['matches']}")
    logger.info(f"New players:      {results['new_players']}")
    logger.info(f"Data errors:      {results['data_errors']}")
    if not args.dry_run:
        logger.info(f"Aliases created:  {results['aliases_created']}")

    # Print cache stats
    cache_stats = resolver.cache.get_stats()
    if cache_stats:
        logger.info(f"\nCache stats:")
        logger.info(f"  Total entries: {cache_stats.get('total_entries', 0)}")
        logger.info(f"  Total cost:    ${cache_stats.get('total_cost', 0):.4f}")

    logger.info("=" * 60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
