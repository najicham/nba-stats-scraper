#!/usr/bin/env python3
"""
Batch resolve unresolved player names using AI.

This CLI tool processes all pending unresolved player names, using:
1. AI resolution to determine matches
2. Automatic alias creation for matches
3. Caching to avoid repeated API calls
4. Auto-reprocessing of affected games (v2.0)

Usage:
    # Process all pending unresolved names (with auto-reprocessing)
    python tools/player_registry/resolve_unresolved_batch.py

    # Dry run (show what would be done)
    python tools/player_registry/resolve_unresolved_batch.py --dry-run

    # Skip auto-reprocessing
    python tools/player_registry/resolve_unresolved_batch.py --skip-reprocessing

    # Limit to specific count
    python tools/player_registry/resolve_unresolved_batch.py --limit 10

    # Process specific names
    python tools/player_registry/resolve_unresolved_batch.py --names marcusmorris kevinknox
"""

import os
import sys
import argparse
import logging
import uuid
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone

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

    # =========================================================================
    # Auto-Reprocessing (v2.0)
    # =========================================================================

    def reprocess_after_resolution(self) -> Dict:
        """
        Automatically reprocess games for players that were just resolved.

        This runs AFTER AI resolution completes and aliases are created.
        Uses circuit breaker pattern to prevent runaway failures.

        Returns:
            Dict with reprocessing summary:
            - players_attempted: Number of players we tried to reprocess
            - players_succeeded: Number fully reprocessed
            - players_failed: Number with at least one game failure
            - games_attempted: Total games attempted
            - games_succeeded: Total games successfully reprocessed
            - games_failed: Total games that failed
            - failures: List of failure details
            - circuit_breaker_triggered: Whether we stopped early
        """
        run_id = str(uuid.uuid4())[:8]
        start_time = datetime.now(timezone.utc)
        logger.info(f"\n{'='*60}")
        logger.info(f"AUTO-REPROCESSING [run_id={run_id}]")
        logger.info(f"{'='*60}")

        results = {
            'run_id': run_id,
            'players_attempted': 0,
            'players_succeeded': 0,
            'players_failed': 0,
            'games_attempted': 0,
            'games_succeeded': 0,
            'games_failed': 0,
            'failures': [],
            'circuit_breaker_triggered': False
        }

        # Circuit breaker settings
        CONSECUTIVE_FAILURE_LIMIT = 5
        consecutive_failures = 0

        # Get players ready to reprocess
        players = self._get_players_to_reprocess()
        if not players:
            logger.info("No players need reprocessing")
            self._log_reprocessing_run(results, start_time)
            return results

        logger.info(f"Found {len(players)} players to reprocess")

        # Import processor (lazy to avoid circular imports)
        try:
            from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
            processor = PlayerGameSummaryProcessor()
        except Exception as e:
            logger.error(f"Failed to import PlayerGameSummaryProcessor: {e}")
            results['failures'].append({
                'type': 'import_error',
                'error': str(e)
            })
            self._log_reprocessing_run(results, start_time)
            return results

        # Process each player
        for player_data in players:
            player_lookup = player_data['player_lookup']
            game_dates = player_data.get('game_dates', [])

            if not game_dates:
                logger.warning(f"No game dates for {player_lookup}, skipping")
                continue

            results['players_attempted'] += 1
            player_success = True

            logger.info(f"\nReprocessing {player_lookup} ({len(game_dates)} games)")

            for game_date in game_dates:
                # Check circuit breaker
                if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                    logger.warning(f"Circuit breaker triggered after {CONSECUTIVE_FAILURE_LIMIT} consecutive failures")
                    results['circuit_breaker_triggered'] = True
                    break

                results['games_attempted'] += 1

                try:
                    # Get game_id for this player/date
                    game_info = self._get_game_for_player_date(player_lookup, game_date)
                    if not game_info:
                        logger.warning(f"  No game found for {player_lookup} on {game_date}")
                        results['games_failed'] += 1
                        player_success = False
                        consecutive_failures += 1
                        continue

                    game_id = game_info['game_id']
                    season = game_info['season']
                    game_date_str = game_date.isoformat() if hasattr(game_date, 'isoformat') else str(game_date)

                    # Reprocess this game
                    success = processor.process_single_game(game_id, game_date_str, season)

                    if success:
                        results['games_succeeded'] += 1
                        consecutive_failures = 0  # Reset on success
                        logger.info(f"  ✓ {game_id}")

                        # Mark this specific failure as reprocessed
                        self._mark_failure_reprocessed(player_lookup, game_date)
                    else:
                        results['games_failed'] += 1
                        player_success = False
                        consecutive_failures += 1
                        logger.warning(f"  ✗ {game_id} - processor returned False")
                        results['failures'].append({
                            'player_lookup': player_lookup,
                            'game_id': game_id,
                            'game_date': str(game_date),
                            'error': 'processor returned False'
                        })

                except Exception as e:
                    results['games_failed'] += 1
                    player_success = False
                    consecutive_failures += 1
                    logger.error(f"  ✗ Error reprocessing {player_lookup}/{game_date}: {e}")
                    results['failures'].append({
                        'player_lookup': player_lookup,
                        'game_date': str(game_date),
                        'error': str(e)
                    })

            # Track player-level success
            if player_success:
                results['players_succeeded'] += 1
            else:
                results['players_failed'] += 1

            # Check circuit breaker at player level too
            if results['circuit_breaker_triggered']:
                break

        # Log run to BigQuery for observability
        self._log_reprocessing_run(results, start_time)

        # Send notification if there were failures
        if results['games_failed'] > 0 or results['circuit_breaker_triggered']:
            self._send_reprocessing_alert(results)

        logger.info(f"\n{'='*60}")
        logger.info("REPROCESSING SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"Players: {results['players_succeeded']}/{results['players_attempted']} succeeded")
        logger.info(f"Games:   {results['games_succeeded']}/{results['games_attempted']} succeeded")
        if results['circuit_breaker_triggered']:
            logger.warning("Circuit breaker was triggered - some games not attempted")
        logger.info(f"{'='*60}")

        return results

    def _get_players_to_reprocess(self) -> List[Dict]:
        """Get players that have been resolved but not yet reprocessed."""
        query = f"""
        SELECT
            player_lookup,
            ARRAY_AGG(DISTINCT game_date ORDER BY game_date) as game_dates,
            COUNT(*) as game_count
        FROM `{self.project_id}.nba_processing.registry_failures`
        WHERE resolved_at IS NOT NULL
          AND reprocessed_at IS NULL
        GROUP BY player_lookup
        ORDER BY game_count DESC
        LIMIT 100
        """
        try:
            result = self.bq_client.query(query).result(timeout=60)
            return [dict(row) for row in result]
        except Exception as e:
            logger.error(f"Error getting players to reprocess: {e}")
            return []

    def _get_game_for_player_date(self, player_lookup: str, game_date) -> Optional[Dict]:
        """Get game_id and season for a player on a specific date."""
        game_date_str = game_date.isoformat() if hasattr(game_date, 'isoformat') else str(game_date)

        query = f"""
        SELECT DISTINCT
            game_id,
            CONCAT(CAST(season_year AS STRING), '-',
                   RIGHT(CAST(season_year + 1 AS STRING), 2)) as season
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
        LIMIT 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date_str)
            ]
        )

        try:
            results = list(self.bq_client.query(query, job_config=job_config).result(timeout=60))
            if results:
                return {'game_id': results[0].game_id, 'season': results[0].season}
            return None
        except Exception as e:
            logger.error(f"Error getting game for {player_lookup}/{game_date}: {e}")
            return None

    def _mark_failure_reprocessed(self, player_lookup: str, game_date) -> None:
        """Mark a specific registry failure as reprocessed."""
        game_date_str = game_date.isoformat() if hasattr(game_date, 'isoformat') else str(game_date)

        query = f"""
        UPDATE `{self.project_id}.nba_processing.registry_failures`
        SET reprocessed_at = CURRENT_TIMESTAMP()
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
          AND reprocessed_at IS NULL
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date_str)
            ]
        )

        try:
            self.bq_client.query(query, job_config=job_config).result(timeout=60)
        except Exception as e:
            logger.error(f"Error marking failure reprocessed: {e}")

    def _log_reprocessing_run(self, results: Dict, start_time: datetime) -> None:
        """Log reprocessing run to BigQuery for observability."""
        end_time = datetime.now(timezone.utc)
        duration_seconds = (end_time - start_time).total_seconds()

        record = {
            'run_id': results['run_id'],
            'run_type': 'auto_after_resolution',
            'started_at': start_time.isoformat(),
            'completed_at': end_time.isoformat(),
            'duration_seconds': duration_seconds,
            'players_attempted': results['players_attempted'],
            'players_succeeded': results['players_succeeded'],
            'players_failed': results['players_failed'],
            'games_attempted': results['games_attempted'],
            'games_succeeded': results['games_succeeded'],
            'games_failed': results['games_failed'],
            'circuit_breaker_triggered': results['circuit_breaker_triggered'],
            'failure_count': len(results.get('failures', [])),
            'success_rate': (results['games_succeeded'] / results['games_attempted'] * 100) if results['games_attempted'] > 0 else 100.0
        }

        try:
            table_id = f"{self.project_id}.nba_processing.reprocessing_runs"
            errors = self.bq_client.insert_rows_json(table_id, [record])
            if errors:
                logger.warning(f"Error logging reprocessing run: {errors}")
        except Exception as e:
            # Don't fail if logging fails - just warn
            logger.warning(f"Could not log reprocessing run (table may not exist): {e}")

    def _send_reprocessing_alert(self, results: Dict) -> None:
        """Send alert about reprocessing issues."""
        try:
            from shared.utils.notification_system import notify_warning, notify_error

            if results['circuit_breaker_triggered']:
                notify_error(
                    title="Registry Reprocessing: Circuit Breaker Triggered",
                    message=f"Stopped after {results['games_failed']} consecutive failures",
                    details={
                        'run_id': results['run_id'],
                        'players_attempted': results['players_attempted'],
                        'games_succeeded': results['games_succeeded'],
                        'games_failed': results['games_failed'],
                        'recent_failures': results['failures'][-5:] if results['failures'] else []
                    },
                    processor_name='registry_reprocessing'
                )
            elif results['games_failed'] > 0:
                failure_rate = results['games_failed'] / results['games_attempted'] * 100 if results['games_attempted'] > 0 else 0
                if failure_rate > 20:
                    notify_warning(
                        title=f"Registry Reprocessing: {failure_rate:.0f}% Failure Rate",
                        message=f"{results['games_failed']}/{results['games_attempted']} games failed",
                        details={
                            'run_id': results['run_id'],
                            'players_attempted': results['players_attempted'],
                            'players_succeeded': results['players_succeeded'],
                            'games_succeeded': results['games_succeeded'],
                            'games_failed': results['games_failed'],
                            'recent_failures': results['failures'][-5:] if results['failures'] else []
                        }
                    )
        except Exception as e:
            logger.warning(f"Could not send reprocessing alert: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Batch resolve unresolved player names using AI (with auto-reprocessing)"
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
    parser.add_argument(
        '--skip-reprocessing',
        action='store_true',
        help='Skip auto-reprocessing after resolution (just resolve names)'
    )
    parser.add_argument(
        '--reprocess-only',
        action='store_true',
        help='Skip resolution, only run reprocessing for already-resolved names'
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("BATCH AI NAME RESOLUTION (v2.0 with auto-reprocessing)")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    resolver = BatchResolver()

    # Phase 1: AI Resolution (unless --reprocess-only)
    resolution_results = None
    if not args.reprocess_only:
        resolution_results = resolver.process_all(
            limit=args.limit,
            names=args.names,
            dry_run=args.dry_run
        )

        logger.info("\n" + "=" * 60)
        logger.info("RESOLUTION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total pending:    {resolution_results['total']}")
        logger.info(f"Processed:        {resolution_results['processed']}")
        logger.info(f"Matches:          {resolution_results['matches']}")
        logger.info(f"New players:      {resolution_results['new_players']}")
        logger.info(f"Data errors:      {resolution_results['data_errors']}")
        if not args.dry_run:
            logger.info(f"Aliases created:  {resolution_results['aliases_created']}")

        # Print cache stats
        cache_stats = resolver.cache.get_stats()
        if cache_stats:
            logger.info(f"\nCache stats:")
            logger.info(f"  Total entries: {cache_stats.get('total_entries', 0)}")
            logger.info(f"  Total cost:    ${cache_stats.get('total_cost', 0):.4f}")

    # Phase 2: Auto-Reprocessing (unless --dry-run or --skip-reprocessing)
    reprocess_results = None
    should_reprocess = (
        not args.dry_run
        and not args.skip_reprocessing
        and (args.reprocess_only or (resolution_results and resolution_results.get('aliases_created', 0) > 0))
    )

    if should_reprocess:
        try:
            reprocess_results = resolver.reprocess_after_resolution()
        except Exception as e:
            # Isolate reprocessing failures - don't affect overall job status
            logger.error(f"Reprocessing failed (isolated): {e}")
            reprocess_results = {'error': str(e)}
    elif args.dry_run:
        logger.info("\n[DRY RUN] Would run auto-reprocessing for resolved names")
    elif args.skip_reprocessing:
        logger.info("\n[SKIPPED] Auto-reprocessing disabled via --skip-reprocessing")
    elif resolution_results and resolution_results.get('aliases_created', 0) == 0:
        logger.info("\n[SKIPPED] No aliases created, skipping reprocessing")

    # Final summary
    logger.info("\n" + "=" * 60)
    logger.info("FINAL SUMMARY")
    logger.info("=" * 60)
    if resolution_results:
        logger.info(f"Resolution: {resolution_results.get('aliases_created', 0)} aliases created")
    if reprocess_results and 'error' not in reprocess_results:
        logger.info(f"Reprocessing: {reprocess_results.get('games_succeeded', 0)}/{reprocess_results.get('games_attempted', 0)} games succeeded")
    elif reprocess_results and 'error' in reprocess_results:
        logger.warning(f"Reprocessing: FAILED - {reprocess_results['error']}")
    logger.info("=" * 60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
