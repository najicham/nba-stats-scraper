"""
Pub/Sub Topics Configuration - Centralized topic definitions.

All topic names and subscriptions for the event-driven pipeline.

Version: 2.0
Created: 2025-11-28
Updated: 2026-01-06 - Added multi-sport support via SportConfig
"""

from shared.config.sport_config import get_current_sport, get_topic


def _topic(phase: str) -> str:
    """Generate sport-specific topic name."""
    return get_topic(phase)


class PubSubTopics:
    """
    Centralized Pub/Sub topic definitions.

    Usage:
        from shared.config.pubsub_topics import TOPICS

        publisher.publish(topic=TOPICS.PHASE2_RAW_COMPLETE, message=...)
    """

    # =========================================================================
    # PHASE 1: SCRAPERS
    # =========================================================================

    # Published by: Scrapers
    # Consumed by: Phase 2 raw processors
    @property
    def PHASE1_SCRAPERS_COMPLETE(self) -> str:
        return _topic('phase1-scrapers-complete')

    # =========================================================================
    # PHASE 2: RAW PROCESSORS
    # =========================================================================

    # Published by: Phase 2 raw processors
    # Consumed by: Phase 2→3 orchestrator
    @property
    def PHASE2_RAW_COMPLETE(self) -> str:
        return _topic('phase2-raw-complete')

    # =========================================================================
    # PHASE 2→3 ORCHESTRATION
    # =========================================================================

    # Published by: Phase 2→3 orchestrator (when all 21 processors complete)
    # Consumed by: Phase 3 analytics processors
    @property
    def PHASE3_TRIGGER(self) -> str:
        return _topic('phase3-trigger')

    # =========================================================================
    # PHASE 3: ANALYTICS PROCESSORS
    # =========================================================================

    # Published by: Phase 3 analytics processors
    # Consumed by: Phase 3→4 orchestrator
    @property
    def PHASE3_ANALYTICS_COMPLETE(self) -> str:
        return _topic('phase3-analytics-complete')

    # =========================================================================
    # PHASE 3→4 ORCHESTRATION
    # =========================================================================

    # Published by: Phase 3→4 orchestrator (when all 5 processors complete)
    # Consumed by: Phase 4 precompute processors
    @property
    def PHASE4_TRIGGER(self) -> str:
        return _topic('phase4-trigger')

    # =========================================================================
    # PHASE 4: PRECOMPUTE PROCESSORS
    # =========================================================================

    # Published by: Phase 4 precompute processors
    # Consumed by: Phase 4 internal orchestrator
    @property
    def PHASE4_PROCESSOR_COMPLETE(self) -> str:
        return _topic('phase4-processor-complete')

    # Published by: ml_feature_store_v2 (final Phase 4 processor)
    # Consumed by: Phase 5 prediction coordinator
    @property
    def PHASE4_PRECOMPUTE_COMPLETE(self) -> str:
        return _topic('phase4-precompute-complete')

    # =========================================================================
    # PHASE 5: PREDICTIONS
    # =========================================================================

    # Published by: Phase 5 prediction coordinator
    # Consumed by: Phase 5→6 orchestrator
    @property
    def PHASE5_PREDICTIONS_COMPLETE(self) -> str:
        return _topic('phase5-predictions-complete')

    # =========================================================================
    # PHASE 6: PUBLISHING
    # =========================================================================

    # Published by: Phase 5→6 orchestrator OR Cloud Scheduler
    # Consumed by: Phase 6 export Cloud Function
    @property
    def PHASE6_EXPORT_TRIGGER(self) -> str:
        return _topic('phase6-export-trigger')

    # Published by: Phase 6 export Cloud Function
    # Consumed by: Monitoring, alerting
    @property
    def PHASE6_EXPORT_COMPLETE(self) -> str:
        return _topic('phase6-export-complete')

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def get_all_topics(self) -> dict:
        """
        Get all topic definitions.

        Returns:
            Dictionary of {name: topic_path}
        """
        return {
            'PHASE1_SCRAPERS_COMPLETE': self.PHASE1_SCRAPERS_COMPLETE,
            'PHASE2_RAW_COMPLETE': self.PHASE2_RAW_COMPLETE,
            'PHASE3_TRIGGER': self.PHASE3_TRIGGER,
            'PHASE3_ANALYTICS_COMPLETE': self.PHASE3_ANALYTICS_COMPLETE,
            'PHASE4_TRIGGER': self.PHASE4_TRIGGER,
            'PHASE4_PROCESSOR_COMPLETE': self.PHASE4_PROCESSOR_COMPLETE,
            'PHASE4_PRECOMPUTE_COMPLETE': self.PHASE4_PRECOMPUTE_COMPLETE,
            'PHASE5_PREDICTIONS_COMPLETE': self.PHASE5_PREDICTIONS_COMPLETE,
            'PHASE6_EXPORT_TRIGGER': self.PHASE6_EXPORT_TRIGGER,
            'PHASE6_EXPORT_COMPLETE': self.PHASE6_EXPORT_COMPLETE,
        }

    def get_topic_for_phase(self, phase: str) -> str:
        """
        Get completion topic for a phase.

        Args:
            phase: Phase identifier (phase_1_scrapers, phase_2_raw, etc.)

        Returns:
            Topic name

        Raises:
            ValueError if phase not recognized
        """
        mapping = {
            'phase_1_scrapers': self.PHASE1_SCRAPERS_COMPLETE,
            'phase_2_raw': self.PHASE2_RAW_COMPLETE,
            'phase_3_analytics': self.PHASE3_ANALYTICS_COMPLETE,
            'phase_4_precompute': self.PHASE4_PRECOMPUTE_COMPLETE,
            'phase_5_predictions': self.PHASE5_PREDICTIONS_COMPLETE,
            'phase_6_publishing': self.PHASE6_EXPORT_COMPLETE,
        }

        if phase not in mapping:
            raise ValueError(
                f"Unknown phase: {phase}. Valid phases: {list(mapping.keys())}"
            )

        return mapping[phase]

    @staticmethod
    def for_sport(sport: str) -> 'PubSubTopics':
        """
        Get PubSubTopics configured for a specific sport.

        Note: This creates a new instance that will use the specified sport's
        topic names. The sport is determined at call time, not import time.

        Args:
            sport: Sport identifier ('nba', 'mlb', etc.)

        Returns:
            PubSubTopics instance for specified sport
        """
        import os
        original_sport = os.environ.get('SPORT', 'nba')
        os.environ['SPORT'] = sport
        topics = PubSubTopics()
        os.environ['SPORT'] = original_sport
        return topics


# Singleton instance for easy import
TOPICS = PubSubTopics()
