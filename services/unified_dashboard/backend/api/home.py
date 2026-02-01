"""
Home Page API

Provides data for the Home/Command Center page:
- System health score
- Critical alerts
- Today's summary
- Pipeline flow status
- Quick actions
"""
import logging
from typing import Dict, Any, List
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from services.firestore_client import FirestoreClient
from services.bigquery_client import BigQueryClient
from utils.health_calculator import HealthScoreCalculator
from utils.cache import cache

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize clients (reuse across requests)
firestore_client = FirestoreClient()
bigquery_client = BigQueryClient()

# Cache TTL in seconds
CACHE_TTL = 300  # 5 minutes


@router.get("/home")
async def get_home_data() -> Dict[str, Any]:
    """
    Get all data for the home/command center page (with caching)

    Returns:
        Comprehensive home page data including health score, alerts, summary
    """
    # Try to get from cache first
    cache_key = "home_data"
    cached_data = cache.get(cache_key, ttl_seconds=CACHE_TTL)
    if cached_data:
        logger.info(f"Returning cached home data (TTL: {CACHE_TTL}s)")
        # Mark as cached and return
        cached_data['metadata']['cached'] = True
        cached_data['timestamp'] = datetime.now(timezone.utc).isoformat()
        return cached_data

    try:
        logger.info("Cache miss - fetching fresh data")

        # Fetch data from multiple sources in parallel (conceptually)
        # In production, consider using asyncio.gather for true parallelism

        # Firestore data (real-time state) - OPTIMIZED: limited to 100 docs
        heartbeats = firestore_client.get_processor_heartbeats(limit=100)
        phase_completions = firestore_client.get_all_phase_completions()
        circuit_breakers = firestore_client.get_circuit_breaker_states()

        # BigQuery data (historical analytics)
        summary = bigquery_client.get_todays_summary()
        processor_stats = bigquery_client.get_processor_run_stats()
        recent_errors = bigquery_client.get_recent_errors(limit=5)
        shot_zone_quality = bigquery_client.get_shot_zone_quality()

        # Calculate health score
        health = HealthScoreCalculator.calculate_overall_health(
            pipeline_data=phase_completions,
            processor_data=processor_stats,
            summary_data=summary,
            shot_zone_quality=shot_zone_quality,
            heartbeats=heartbeats
        )

        # Detect critical alerts
        alerts = _detect_critical_alerts(
            heartbeats=heartbeats,
            recent_errors=recent_errors,
            summary=summary,
            shot_zone_quality=shot_zone_quality,
            circuit_breakers=circuit_breakers
        )

        # Build pipeline flow status
        pipeline_flow = _build_pipeline_flow(
            phase_completions=phase_completions,
            processor_stats=processor_stats
        )

        # Build response
        response_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'health': health,
            'alerts': alerts,
            'summary': summary,
            'pipeline_flow': pipeline_flow,
            'quick_actions': _get_quick_actions(alerts),
            'metadata': {
                'data_sources': {
                    'firestore': 'real-time',
                    'bigquery': 'last 24h'
                },
                'refresh_interval': 60,  # Suggest refresh every 60 seconds
                'cached': False,
                'cache_ttl': CACHE_TTL
            }
        }

        # Cache the response
        cache.set(cache_key, response_data)

        return response_data

    except Exception as e:
        logger.error(f"Error fetching home data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching home data: {str(e)}")


@router.get("/home/health")
async def get_health_score() -> Dict[str, Any]:
    """
    Get just the health score (lightweight endpoint, uses cache)

    Returns:
        Health score and status
    """
    # Use cached home data if available
    cached_data = cache.get("home_data", ttl_seconds=CACHE_TTL)
    if cached_data and 'health' in cached_data:
        return cached_data['health']

    try:
        heartbeats = firestore_client.get_processor_heartbeats(limit=100)
        phase_completions = firestore_client.get_all_phase_completions()
        summary = bigquery_client.get_todays_summary()
        processor_stats = bigquery_client.get_processor_run_stats()
        shot_zone_quality = bigquery_client.get_shot_zone_quality()

        health = HealthScoreCalculator.calculate_overall_health(
            pipeline_data=phase_completions,
            processor_data=processor_stats,
            summary_data=summary,
            shot_zone_quality=shot_zone_quality,
            heartbeats=heartbeats
        )

        return health

    except Exception as e:
        logger.error(f"Error calculating health score: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error calculating health: {str(e)}")


@router.get("/home/cache/stats")
async def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics"""
    return {
        'cache_stats': cache.stats(),
        'ttl_seconds': CACHE_TTL
    }


@router.post("/home/cache/clear")
async def clear_cache() -> Dict[str, Any]:
    """Clear the cache (forces fresh data fetch)"""
    cache.clear("home_data")
    return {'status': 'cache cleared'}


def _detect_critical_alerts(
    heartbeats: List[Dict[str, Any]],
    recent_errors: List[Dict[str, Any]],
    summary: Dict[str, Any],
    shot_zone_quality: Dict[str, Any],
    circuit_breakers: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Detect critical alerts that need operator attention

    Args:
        heartbeats: Processor heartbeat data
        recent_errors: Recent processor errors
        summary: Today's summary
        shot_zone_quality: Shot zone quality data
        circuit_breakers: Circuit breaker states

    Returns:
        List of alert objects with severity, message, action
    """
    alerts = []

    # Check for stale heartbeats
    stale_processors = [hb for hb in heartbeats if hb.get('is_stale', False)]
    if stale_processors:
        alerts.append({
            'severity': 'warning',
            'type': 'stale_heartbeat',
            'message': f'{len(stale_processors)} processor(s) have stale heartbeats',
            'details': [p['processor_name'] for p in stale_processors[:5]],
            'action': 'Check processor logs',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # Check for recent errors
    if recent_errors:
        alerts.append({
            'severity': 'critical' if len(recent_errors) > 5 else 'warning',
            'type': 'processor_errors',
            'message': f'{len(recent_errors)} processor error(s) in last 24h',
            'details': [err.get('processor_type') for err in recent_errors[:3]],
            'action': 'Review error logs',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # Check prediction coverage
    coverage = summary.get('coverage_pct', 0)
    if coverage < 90 and summary.get('total_games', 0) > 0:
        alerts.append({
            'severity': 'warning',
            'type': 'low_coverage',
            'message': f'Prediction coverage is {coverage}% (target: 95%+)',
            'details': f"{summary.get('games_with_predictions', 0)}/{summary.get('total_games', 0)} games covered",
            'action': 'Check prediction worker',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # Check shot zone quality
    shot_zone_completeness = shot_zone_quality.get('completeness_pct', 100)
    if shot_zone_completeness < 80:
        alerts.append({
            'severity': 'warning',
            'type': 'shot_zone_quality',
            'message': f'Shot zones {shot_zone_completeness}% complete',
            'details': f"Paint rate: {shot_zone_quality.get('avg_paint_rate', 0)}%",
            'action': 'Check BDB data availability',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # Check ML performance
    accuracy = summary.get('accuracy_pct', 0)
    if accuracy < 52.4 and summary.get('total_graded', 0) > 10:  # Below breakeven
        alerts.append({
            'severity': 'critical',
            'type': 'low_accuracy',
            'message': f'Prediction accuracy {accuracy}% below breakeven (52.4%)',
            'details': f"{summary.get('correct_predictions', 0)}/{summary.get('total_graded', 0)} correct",
            'action': 'Check model performance',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # Check open circuit breakers
    open_breakers = [cb for cb in circuit_breakers if cb.get('state') == 'open']
    if open_breakers:
        alerts.append({
            'severity': 'warning',
            'type': 'circuit_breaker',
            'message': f'{len(open_breakers)} circuit breaker(s) open',
            'details': [cb['name'] for cb in open_breakers[:3]],
            'action': 'Check external service health',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # Sort by severity (critical first)
    severity_order = {'critical': 0, 'warning': 1, 'info': 2}
    alerts.sort(key=lambda a: severity_order.get(a['severity'], 3))

    return alerts


def _build_pipeline_flow(
    phase_completions: Dict[int, Dict[str, Any]],
    processor_stats: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Build pipeline flow status for visualization

    Args:
        phase_completions: Phase completion states
        processor_stats: Processor run statistics

    Returns:
        Pipeline flow data structure
    """
    # Map processor types to phases
    phase_map = {
        1: ['scraper'],
        2: ['raw'],
        3: ['analytics'],
        4: ['precompute'],
        5: ['prediction'],
        6: ['publishing']
    }

    phases = []

    for phase_num in range(1, 7):
        # Get completion state
        completion = phase_completions.get(phase_num, {})
        completed = completion.get('completed', False)

        # Count processors in this phase
        processor_types = phase_map.get(phase_num, [])
        phase_processors = [
            p for p in processor_stats.get('processors', [])
            if any(pt in p['processor_type'].lower() for pt in processor_types)
        ]

        total_processors = len(phase_processors)
        successful_processors = sum(1 for p in phase_processors if p['success_rate_pct'] == 100)

        # Determine status
        if total_processors == 0:
            status = 'unknown'
        elif successful_processors == total_processors:
            status = 'complete'
        elif successful_processors > 0:
            status = 'partial'
        else:
            status = 'failed'

        phases.append({
            'phase': phase_num,
            'name': f'Phase {phase_num}',
            'status': status,
            'processors': {
                'total': total_processors,
                'successful': successful_processors,
                'failed': total_processors - successful_processors
            }
        })

    return {'phases': phases}


def _get_quick_actions(alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Generate quick action buttons based on alerts

    Args:
        alerts: List of active alerts

    Returns:
        List of quick action objects
    """
    actions = []

    # Always available actions
    actions.append({
        'id': 'trigger_backfill',
        'label': 'Trigger Backfill',
        'type': 'primary',
        'enabled': True
    })

    actions.append({
        'id': 'view_logs',
        'label': 'View Recent Logs',
        'type': 'secondary',
        'enabled': True
    })

    # Alert-specific actions
    alert_types = {alert['type'] for alert in alerts}

    if 'processor_errors' in alert_types:
        actions.append({
            'id': 'retry_failed',
            'label': 'Retry Failed Processors',
            'type': 'warning',
            'enabled': True
        })

    if 'shot_zone_quality' in alert_types:
        actions.append({
            'id': 'check_bdb',
            'label': 'Check BDB Status',
            'type': 'info',
            'enabled': True
        })

    return actions[:4]  # Limit to 4 actions
