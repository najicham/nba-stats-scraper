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
