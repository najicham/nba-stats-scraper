"""
Source Blocks Blueprint

Dashboard for monitoring source-blocked resources.

Endpoints:
- GET /api/source-blocks - List active source blocks
- GET /api/source-blocks/patterns - Blocking patterns analysis
- GET /api/source-blocks/coverage - Coverage accounting for blocks
- POST /api/source-blocks/resolve - Mark block as resolved
"""

from flask import Blueprint, jsonify, request, render_template
from datetime import datetime, timedelta
from typing import Dict, List, Any
import logging

from ..services.bigquery_service import BigQueryService
from ..services.auth import require_api_key
from ..services.audit_logger import log_action

logger = logging.getLogger(__name__)

source_blocks_bp = Blueprint('source_blocks', __name__)


@source_blocks_bp.route('/api/source-blocks', methods=['GET'])
@require_api_key
def get_source_blocks():
    """
    Get list of active source blocks.

    Query params:
    - days: Number of days to look back (default: 7)
    - source: Filter by source system
    - type: Filter by resource type
    - resolved: Include resolved (true/false, default: false)
    """
    try:
        days = int(request.args.get('days', 7))
        source_filter = request.args.get('source')
        type_filter = request.args.get('type')
        include_resolved = request.args.get('resolved', 'false').lower() == 'true'

        bq = BigQueryService()

        # Build query with filters
        where_clauses = [
            f"game_date >= CURRENT_DATE() - {days}"
        ]

        if not include_resolved:
            where_clauses.append("is_resolved = FALSE")

        if source_filter:
            where_clauses.append(f"source_system = '{source_filter}'")

        if type_filter:
            where_clauses.append(f"resource_type = '{type_filter}'")

        where_sql = " AND ".join(where_clauses)

        query = f"""
        SELECT
            resource_id,
            resource_type,
            source_system,
            http_status_code,
            block_type,
            game_date,
            source_url,
            first_detected_at,
            last_verified_at,
            verification_count,
            available_from_alt_source,
            alt_source_system,
            is_resolved,
            resolved_at,
            resolution_notes,
            notes,
            TIMESTAMP_DIFF(
                COALESCE(resolved_at, CURRENT_TIMESTAMP()),
                first_detected_at,
                HOUR
            ) as hours_blocked
        FROM `nba-props-platform.nba_orchestration.source_blocked_resources`
        WHERE {where_sql}
        ORDER BY
            is_resolved ASC,
            game_date DESC,
            first_detected_at DESC
        """

        results = bq.execute_query(query)

        # Format results
        blocks = []
        for row in results:
            block = dict(row)

            # Format timestamps
            for ts_field in ['first_detected_at', 'last_verified_at', 'resolved_at']:
                if block.get(ts_field):
                    block[ts_field] = block[ts_field].isoformat()

            # Format date
            if block.get('game_date'):
                block['game_date'] = block['game_date'].isoformat()

            blocks.append(block)

        return jsonify({
            'success': True,
            'blocks': blocks,
            'total': len(blocks),
            'filters': {
                'days': days,
                'source': source_filter,
                'type': type_filter,
                'include_resolved': include_resolved
            }
        })

    except Exception as e:
        logger.error(f"Error fetching source blocks: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@source_blocks_bp.route('/api/source-blocks/patterns', methods=['GET'])
@require_api_key
def get_blocking_patterns():
    """
    Analyze blocking patterns to identify systemic issues.

    Shows which sources/resources are blocked most frequently.
    """
    try:
        days = int(request.args.get('days', 30))

        bq = BigQueryService()

        query = f"""
        SELECT
            source_system,
            resource_type,
            COUNT(DISTINCT resource_id) as unique_resources_blocked,
            COUNT(*) as total_blocks,
            MIN(first_detected_at) as first_seen,
            MAX(last_verified_at) as last_seen,
            COUNTIF(is_resolved) as resolved_count,
            COUNTIF(NOT is_resolved) as active_count,
            ARRAY_AGG(DISTINCT http_status_code ORDER BY http_status_code) as status_codes,
            AVG(TIMESTAMP_DIFF(
                COALESCE(resolved_at, CURRENT_TIMESTAMP()),
                first_detected_at,
                HOUR
            )) as avg_hours_blocked
        FROM `nba-props-platform.nba_orchestration.source_blocked_resources`
        WHERE game_date >= CURRENT_DATE() - {days}
        GROUP BY source_system, resource_type
        ORDER BY total_blocks DESC, last_seen DESC
        """

        results = bq.execute_query(query)

        patterns = []
        for row in results:
            pattern = dict(row)

            # Format timestamps
            if pattern.get('first_seen'):
                pattern['first_seen'] = pattern['first_seen'].isoformat()
            if pattern.get('last_seen'):
                pattern['last_seen'] = pattern['last_seen'].isoformat()

            # Calculate resolution rate
            total = pattern['total_blocks']
            resolved = pattern['resolved_count']
            pattern['resolution_rate'] = (resolved / total * 100) if total > 0 else 0

            patterns.append(pattern)

        return jsonify({
            'success': True,
            'patterns': patterns,
            'total_patterns': len(patterns),
            'days_analyzed': days
        })

    except Exception as e:
        logger.error(f"Error analyzing blocking patterns: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@source_blocks_bp.route('/api/source-blocks/coverage', methods=['GET'])
@require_api_key
def get_coverage_with_blocks():
    """
    Calculate data coverage % accounting for source blocks.

    Shows: total games, blocked games, expected available, actual collected, coverage %.
    """
    try:
        days = int(request.args.get('days', 7))

        bq = BigQueryService()

        query = f"""
        WITH expected AS (
          SELECT game_date, COUNT(*) as total_games
          FROM `nba-props-platform.nba_raw.nbac_schedule`
          WHERE game_date >= CURRENT_DATE() - {days}
            AND game_date < CURRENT_DATE()
          GROUP BY game_date
        ),
        blocked AS (
          SELECT game_date, COUNT(DISTINCT resource_id) as blocked_games
          FROM `nba-props-platform.nba_orchestration.source_blocked_resources`
          WHERE resource_type = 'play_by_play'
            AND game_date >= CURRENT_DATE() - {days}
            AND game_date < CURRENT_DATE()
            AND is_resolved = FALSE
          GROUP BY game_date
        ),
        collected AS (
          SELECT
            DATE(PARSE_TIMESTAMP('%Y%m%d', SPLIT(game_id, '_')[OFFSET(0)])) as game_date,
            COUNT(DISTINCT game_id) as games_collected
          FROM `nba-props-platform.nba_raw.bigdataball_play_by_play`
          WHERE DATE(PARSE_TIMESTAMP('%Y%m%d', SPLIT(game_id, '_')[OFFSET(0)])) >= CURRENT_DATE() - {days}
            AND DATE(PARSE_TIMESTAMP('%Y%m%d', SPLIT(game_id, '_')[OFFSET(0)])) < CURRENT_DATE()
          GROUP BY game_date
        )
        SELECT
          e.game_date,
          e.total_games,
          COALESCE(b.blocked_games, 0) as blocked_games,
          e.total_games - COALESCE(b.blocked_games, 0) as expected_available,
          COALESCE(c.games_collected, 0) as actual_collected,
          SAFE_DIVIDE(
            COALESCE(c.games_collected, 0),
            e.total_games - COALESCE(b.blocked_games, 0)
          ) * 100 as coverage_pct
        FROM expected e
        LEFT JOIN blocked b USING (game_date)
        LEFT JOIN collected c USING (game_date)
        ORDER BY game_date DESC
        """

        results = bq.execute_query(query)

        coverage_data = []
        for row in results:
            data = dict(row)

            # Format date
            if data.get('game_date'):
                data['game_date'] = data['game_date'].isoformat()

            # Round coverage percentage
            if data.get('coverage_pct') is not None:
                data['coverage_pct'] = round(data['coverage_pct'], 1)

            coverage_data.append(data)

        # Calculate overall stats
        total_games = sum(d['total_games'] for d in coverage_data)
        total_blocked = sum(d['blocked_games'] for d in coverage_data)
        total_expected = sum(d['expected_available'] for d in coverage_data)
        total_collected = sum(d['actual_collected'] for d in coverage_data)

        overall_coverage = (total_collected / total_expected * 100) if total_expected > 0 else 0

        return jsonify({
            'success': True,
            'coverage_by_date': coverage_data,
            'summary': {
                'total_games': total_games,
                'blocked_games': total_blocked,
                'expected_available': total_expected,
                'actual_collected': total_collected,
                'overall_coverage_pct': round(overall_coverage, 1)
            },
            'days_analyzed': days
        })

    except Exception as e:
        logger.error(f"Error calculating coverage with blocks: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@source_blocks_bp.route('/api/source-blocks/resolve', methods=['POST'])
@require_api_key
def resolve_source_block():
    """
    Mark a source block as resolved.

    Requires:
    - resource_id: ID of blocked resource
    - resolution_notes: Notes about resolution
    - available_from_alt_source: boolean (optional)
    - alt_source_system: string (optional, if available from alt)
    """
    try:
        data = request.get_json()

        resource_id = data.get('resource_id')
        resolution_notes = data.get('resolution_notes', 'Manually marked as resolved')
        alt_available = data.get('available_from_alt_source', False)
        alt_source = data.get('alt_source_system')

        if not resource_id:
            return jsonify({'success': False, 'error': 'resource_id required'}), 400

        bq = BigQueryService()

        # Update the block
        query = f"""
        UPDATE `nba-props-platform.nba_orchestration.source_blocked_resources`
        SET
            is_resolved = TRUE,
            resolved_at = CURRENT_TIMESTAMP(),
            resolution_notes = @resolution_notes,
            available_from_alt_source = @alt_available,
            alt_source_system = @alt_source
        WHERE resource_id = @resource_id
          AND is_resolved = FALSE
        """

        job_config = bq.client.QueryJobConfig(
            query_parameters=[
                bq.client.ScalarQueryParameter('resource_id', 'STRING', resource_id),
                bq.client.ScalarQueryParameter('resolution_notes', 'STRING', resolution_notes),
                bq.client.ScalarQueryParameter('alt_available', 'BOOL', alt_available),
                bq.client.ScalarQueryParameter('alt_source', 'STRING', alt_source),
            ]
        )

        query_job = bq.client.query(query, job_config=job_config)
        query_job.result()

        # Log action
        log_action(
            action='resolve_source_block',
            resource_type='source_block',
            resource_id=resource_id,
            details={
                'resolution_notes': resolution_notes,
                'available_from_alt_source': alt_available,
                'alt_source_system': alt_source
            }
        )

        logger.info(f"Resolved source block: {resource_id}")

        return jsonify({
            'success': True,
            'message': f'Source block {resource_id} marked as resolved'
        })

    except Exception as e:
        logger.error(f"Error resolving source block: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@source_blocks_bp.route('/source-blocks')
@require_api_key
def source_blocks_dashboard():
    """Render source blocks dashboard page."""
    return render_template('source_blocks.html')
