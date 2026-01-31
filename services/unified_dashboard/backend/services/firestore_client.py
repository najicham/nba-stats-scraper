"""
Firestore Client - Real-time state access

Provides access to:
- Processor heartbeats
- Phase completion states
- Circuit breaker states
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from google.cloud import firestore

logger = logging.getLogger(__name__)


class FirestoreClient:
    """Client for accessing Firestore real-time state"""

    def __init__(self, project_id: str = "nba-props-platform"):
        self.db = firestore.Client(project=project_id)
        self.project_id = project_id

    def get_processor_heartbeats(self) -> List[Dict[str, Any]]:
        """
        Get all processor heartbeats

        Returns:
            List of heartbeat records with processor name, last_heartbeat, status
        """
        try:
            heartbeats = []
            collection_ref = self.db.collection('processor_heartbeats')

            for doc in collection_ref.stream():
                data = doc.to_dict()
                heartbeats.append({
                    'processor_name': doc.id,
                    'last_heartbeat': data.get('last_heartbeat'),
                    'status': data.get('status', 'unknown'),
                    'last_run_duration_seconds': data.get('last_run_duration_seconds'),
                    'is_stale': self._is_heartbeat_stale(data.get('last_heartbeat'))
                })

            return heartbeats
        except Exception as e:
            logger.error(f"Error fetching processor heartbeats: {e}")
            return []

    def get_phase_completion(self, phase_number: int) -> Optional[Dict[str, Any]]:
        """
        Get phase completion state

        Args:
            phase_number: Phase number (2, 3, 4, etc.)

        Returns:
            Phase completion state or None
        """
        try:
            collection_name = f'phase{phase_number}_completion'
            # Get the most recent completion state (there should be one doc per game date)
            docs = (self.db.collection(collection_name)
                   .order_by('timestamp', direction=firestore.Query.DESCENDING)
                   .limit(1)
                   .stream())

            for doc in docs:
                data = doc.to_dict()
                return {
                    'phase': phase_number,
                    'completed': data.get('completed', False),
                    'timestamp': data.get('timestamp'),
                    'game_date': data.get('game_date'),
                    'processors_complete': data.get('processors_complete', []),
                    'processors_failed': data.get('processors_failed', [])
                }

            return None
        except Exception as e:
            logger.error(f"Error fetching phase {phase_number} completion: {e}")
            return None

    def get_all_phase_completions(self) -> Dict[int, Dict[str, Any]]:
        """
        Get completion state for all phases

        Returns:
            Dict mapping phase number to completion state
        """
        phases = {}
        for phase_num in [2, 3, 4]:  # Main data processing phases
            completion = self.get_phase_completion(phase_num)
            if completion:
                phases[phase_num] = completion

        return phases

    def get_circuit_breaker_states(self) -> List[Dict[str, Any]]:
        """
        Get all circuit breaker states

        Returns:
            List of circuit breaker states
        """
        try:
            states = []
            collection_ref = self.db.collection('circuit_breaker_state')

            for doc in collection_ref.stream():
                data = doc.to_dict()
                states.append({
                    'name': doc.id,
                    'state': data.get('state', 'unknown'),
                    'failure_count': data.get('failure_count', 0),
                    'last_failure_time': data.get('last_failure_time'),
                    'last_success_time': data.get('last_success_time')
                })

            return states
        except Exception as e:
            logger.error(f"Error fetching circuit breaker states: {e}")
            return []

    @staticmethod
    def _is_heartbeat_stale(last_heartbeat, stale_threshold_minutes: int = 5) -> bool:
        """
        Check if a heartbeat is stale (older than threshold)

        Args:
            last_heartbeat: Timestamp of last heartbeat
            stale_threshold_minutes: Minutes before considering stale

        Returns:
            True if stale, False otherwise
        """
        if not last_heartbeat:
            return True

        try:
            # Handle both datetime objects and Firestore timestamps
            if hasattr(last_heartbeat, 'timestamp'):
                last_heartbeat = datetime.fromtimestamp(last_heartbeat.timestamp(), tz=timezone.utc)

            threshold = datetime.now(timezone.utc) - timedelta(minutes=stale_threshold_minutes)
            return last_heartbeat < threshold
        except Exception as e:
            logger.error(f"Error checking heartbeat staleness: {e}")
            return True
