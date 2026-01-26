"""
Firestore Service for Admin Dashboard

Queries Firestore for orchestration state (phase completion tracking).
Supports both NBA and MLB sports via sport parameter.
"""

import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
from google.cloud import firestore

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

# Sport-specific Firestore collection prefixes
SPORT_COLLECTIONS = {
    'nba': {
        'phase3_completion': 'phase3_completion',
        'phase4_completion': 'phase4_completion',
        'run_history': 'run_history',
    },
    'mlb': {
        'phase3_completion': 'mlb_phase3_completion',
        'phase4_completion': 'mlb_phase4_completion',
        'run_history': 'mlb_run_history',
    }
}


class FirestoreService:
    """Service for querying Firestore orchestration state."""

    def __init__(self, sport: str = 'nba'):
        """
        Initialize Firestore service for a specific sport.

        Args:
            sport: 'nba' or 'mlb' (default: 'nba')
        """
        self.db = firestore.Client(project=PROJECT_ID)
        self.sport = sport.lower()
        self.collections = SPORT_COLLECTIONS.get(self.sport, SPORT_COLLECTIONS['nba'])

    def get_phase_completion(self, collection: str, date_key: str) -> Optional[Dict]:
        """
        Get phase completion state from Firestore.

        Args:
            collection: 'phase3_completion' or 'phase4_completion'
            date_key: Date string like '2025-12-29'

        Returns dict with processor completion states and triggered flag.
        """
        try:
            doc_ref = self.db.collection(collection).document(date_key)
            doc = doc_ref.get()

            if doc.exists:
                data = doc.to_dict()

                # Parse processor completions
                processors = {}
                triggered = False
                triggered_at = None
                completed_count = 0

                for key, value in data.items():
                    if key == '_triggered':
                        if isinstance(value, dict):
                            triggered = True
                            triggered_at = value.get('timestamp')
                        else:
                            triggered = bool(value)
                    elif key == '_completed_count':
                        completed_count = value
                    elif key.startswith('_'):
                        # Skip other internal fields
                        continue
                    else:
                        # This is a processor entry
                        processors[key] = {
                            'completed_at': value.get('completed_at') if isinstance(value, dict) else str(value),
                            'name': key
                        }

                return {
                    'date': date_key,
                    'collection': collection,
                    'exists': True,
                    'processors': processors,
                    'completed_count': completed_count or len(processors),
                    'triggered': triggered,
                    'triggered_at': str(triggered_at) if triggered_at else None
                }
            else:
                return {
                    'date': date_key,
                    'collection': collection,
                    'exists': False,
                    'processors': {},
                    'completed_count': 0,
                    'triggered': False,
                    'triggered_at': None
                }

        except Exception as e:
            logger.error(f"Error querying Firestore {collection}/{date_key}: {e}")
            raise

    def get_phase3_status(self, date_key: str) -> Dict:
        """
        Get Phase 3 completion status.

        Phase 3 has 5 required processors:
        - player_game_summary
        - team_defense_game_summary
        - team_offense_game_summary
        - upcoming_player_game_context
        - upcoming_team_game_context
        """
        required_processors = [
            'player_game_summary',
            'team_defense_game_summary',
            'team_offense_game_summary',
            'upcoming_player_game_context',
            'upcoming_team_game_context'
        ]

        state = self.get_phase_completion('phase3_completion', date_key)

        # Calculate completion status
        completed = []
        pending = []

        for proc in required_processors:
            if proc in state.get('processors', {}):
                completed.append(proc)
            else:
                pending.append(proc)

        state['required_processors'] = required_processors
        state['completed_processors'] = completed
        state['pending_processors'] = pending
        state['completion_ratio'] = f"{len(completed)}/{len(required_processors)}"
        state['is_complete'] = len(pending) == 0

        return state

    def get_phase4_status(self, date_key: str) -> Dict:
        """
        Get Phase 4 completion status.

        Phase 4 has key processors:
        - TeamDefenseZoneAnalysis
        - PlayerShotZoneAnalysis
        - PlayerCompositeFactorsProcessor
        - PlayerDailyCacheProcessor
        - MLFeatureStoreProcessor
        """
        state = self.get_phase_completion('phase4_completion', date_key)
        return state

    def get_run_history_stuck(self) -> list:
        """
        Get any stuck processors (status='running' for >30 min).
        """
        try:
            # Query for running processors
            query = self.db.collection('run_history').where('status', '==', 'running')
            docs = query.stream()

            stuck = []
            now = datetime.utcnow()

            for doc in docs:
                data = doc.to_dict()
                started_at = data.get('started_at')

                if started_at:
                    # Check if running for more than 30 minutes
                    if hasattr(started_at, 'timestamp'):
                        started_ts = started_at.timestamp()
                        elapsed_minutes = (now.timestamp() - started_ts) / 60

                        if elapsed_minutes > 30:
                            stuck.append({
                                'run_id': doc.id,
                                'processor': data.get('processor_name'),
                                'started_at': str(started_at),
                                'elapsed_minutes': round(elapsed_minutes, 1)
                            })

            return stuck

        except Exception as e:
            logger.error(f"Error querying stuck processors: {e}")
            return []

    # =========================================================================
    # MLB-specific methods
    # =========================================================================

    def get_mlb_phase3_status(self, date_key: str) -> Dict:
        """
        Get MLB Phase 3 completion status.

        MLB Phase 3 has 2 required processors:
        - pitcher_game_summary
        - batter_game_summary
        """
        required_processors = [
            'pitcher_game_summary',
            'batter_game_summary',
        ]

        state = self.get_phase_completion('mlb_phase3_completion', date_key)

        completed = []
        pending = []

        for proc in required_processors:
            if proc in state.get('processors', {}):
                completed.append(proc)
            else:
                pending.append(proc)

        state['required_processors'] = required_processors
        state['completed_processors'] = completed
        state['pending_processors'] = pending
        state['completion_ratio'] = f"{len(completed)}/{len(required_processors)}"
        state['is_complete'] = len(pending) == 0

        return state

    def get_mlb_phase4_status(self, date_key: str) -> Dict:
        """
        Get MLB Phase 4 completion status.

        MLB Phase 4 has 2 key processors:
        - pitcher_features
        - lineup_k_analysis
        """
        required_processors = [
            'pitcher_features',
            'lineup_k_analysis',
        ]

        state = self.get_phase_completion('mlb_phase4_completion', date_key)

        completed = []
        pending = []

        for proc in required_processors:
            if proc in state.get('processors', {}):
                completed.append(proc)
            else:
                pending.append(proc)

        state['required_processors'] = required_processors
        state['completed_processors'] = completed
        state['pending_processors'] = pending
        state['completion_ratio'] = f"{len(completed)}/{len(required_processors)}"
        state['is_complete'] = len(pending) == 0

        return state

    # =========================================================================
    # Processor Heartbeat Methods
    # =========================================================================

    def get_processor_heartbeats(self, hours: int = 24, include_completed: bool = True) -> List[Dict]:
        """
        Get processor heartbeats from the last N hours.

        Args:
            hours: How many hours back to look (default 24)
            include_completed: Include completed/failed processors (default True)

        Returns:
            List of heartbeat records with status info
        """
        from datetime import timedelta, timezone

        try:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=hours)

            query = self.db.collection('processor_heartbeats')

            if not include_completed:
                query = query.where('status', '==', 'running')

            # Filter by time
            query = query.where('last_heartbeat', '>=', cutoff)
            query = query.order_by('last_heartbeat', direction=firestore.Query.DESCENDING)
            query = query.limit(100)

            docs = query.stream()

            heartbeats = []
            for doc in docs:
                data = doc.to_dict()

                # Calculate age
                last_hb = data.get('last_heartbeat')
                age_seconds = None
                if last_hb:
                    if hasattr(last_hb, 'timestamp'):
                        age_seconds = (now.timestamp() - last_hb.timestamp())
                    elif isinstance(last_hb, datetime):
                        age_seconds = (now - last_hb.replace(tzinfo=timezone.utc)).total_seconds()

                # Determine health state
                status = data.get('status', 'unknown')
                if status == 'running' and age_seconds:
                    if age_seconds > 900:  # 15 min
                        health = 'dead'
                    elif age_seconds > 300:  # 5 min
                        health = 'stale'
                    else:
                        health = 'healthy'
                elif status == 'completed':
                    health = 'completed'
                elif status == 'failed':
                    health = 'failed'
                else:
                    health = status

                heartbeats.append({
                    'doc_id': doc.id,
                    'processor_name': data.get('processor_name'),
                    'run_id': data.get('run_id'),
                    'data_date': data.get('data_date'),
                    'status': status,
                    'health': health,
                    'last_heartbeat': last_hb.isoformat() if hasattr(last_hb, 'isoformat') else str(last_hb) if last_hb else None,
                    'started_at': data.get('started_at').isoformat() if hasattr(data.get('started_at'), 'isoformat') else str(data.get('started_at')) if data.get('started_at') else None,
                    'completed_at': data.get('completed_at').isoformat() if hasattr(data.get('completed_at'), 'isoformat') else str(data.get('completed_at')) if data.get('completed_at') else None,
                    'age_seconds': int(age_seconds) if age_seconds else None,
                    'progress': data.get('progress', 0),
                    'total': data.get('total', 0),
                    'status_message': data.get('status_message', ''),
                    'duration_seconds': data.get('duration_seconds')
                })

            return heartbeats

        except Exception as e:
            logger.error(f"Error querying processor heartbeats: {e}", exc_info=True)
            return []

    def get_heartbeat_summary(self, hours: int = 24) -> Dict:
        """
        Get summary statistics for processor heartbeats.

        Returns:
            Dict with counts by status/health
        """
        heartbeats = self.get_processor_heartbeats(hours=hours, include_completed=True)

        summary = {
            'total': len(heartbeats),
            'healthy': 0,
            'stale': 0,
            'dead': 0,
            'completed': 0,
            'failed': 0,
            'unique_processors': set(),
            'period_hours': hours
        }

        for hb in heartbeats:
            health = hb.get('health', 'unknown')
            if health in summary:
                summary[health] += 1
            summary['unique_processors'].add(hb.get('processor_name'))

        summary['unique_processors'] = len(summary['unique_processors'])

        return summary

    def get_running_processors(self) -> List[Dict]:
        """
        Get all currently running processors.

        Returns:
            List of running processor heartbeats with health status
        """
        return [
            hb for hb in self.get_processor_heartbeats(hours=24, include_completed=False)
            if hb.get('status') == 'running'
        ]

    def get_processor_timeline(self, processor_name: str = None, hours: int = 24) -> List[Dict]:
        """
        Get processor activity timeline, optionally filtered by processor name.

        Args:
            processor_name: Optional filter by processor name
            hours: How many hours back to look

        Returns:
            List of heartbeat events for timeline visualization
        """
        heartbeats = self.get_processor_heartbeats(hours=hours, include_completed=True)

        if processor_name:
            heartbeats = [hb for hb in heartbeats if hb.get('processor_name') == processor_name]

        # Sort by start time for timeline
        heartbeats.sort(key=lambda x: x.get('started_at') or '', reverse=True)

        return heartbeats
