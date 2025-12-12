"""
Pub/Sub Topics Configuration - Centralized topic definitions.

All topic names and subscriptions for the event-driven pipeline.

Version: 1.0
Created: 2025-11-28
"""


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
    PHASE1_SCRAPERS_COMPLETE = 'nba-phase1-scrapers-complete'

    # Legacy topic (dual publishing during migration)
    LEGACY_SCRAPER_COMPLETE = 'nba-scraper-complete'

    # =========================================================================
    # PHASE 2: RAW PROCESSORS
    # =========================================================================

    # Published by: Phase 2 raw processors
    # Consumed by: Phase 2→3 orchestrator
    PHASE2_RAW_COMPLETE = 'nba-phase2-raw-complete'

    # =========================================================================
    # PHASE 2→3 ORCHESTRATION
    # =========================================================================

    # Published by: Phase 2→3 orchestrator (when all 21 processors complete)
    # Consumed by: Phase 3 analytics processors
    PHASE3_TRIGGER = 'nba-phase3-trigger'

    # =========================================================================
    # PHASE 3: ANALYTICS PROCESSORS
    # =========================================================================

    # Published by: Phase 3 analytics processors
    # Consumed by: Phase 3→4 orchestrator
    PHASE3_ANALYTICS_COMPLETE = 'nba-phase3-analytics-complete'

    # =========================================================================
    # PHASE 3→4 ORCHESTRATION
    # =========================================================================

    # Published by: Phase 3→4 orchestrator (when all 5 processors complete)
    # Consumed by: Phase 4 precompute processors
    PHASE4_TRIGGER = 'nba-phase4-trigger'

    # =========================================================================
    # PHASE 4: PRECOMPUTE PROCESSORS
    # =========================================================================

    # Published by: Phase 4 precompute processors
    # Consumed by: Phase 4 internal orchestrator
    PHASE4_PROCESSOR_COMPLETE = 'nba-phase4-processor-complete'

    # Published by: ml_feature_store_v2 (final Phase 4 processor)
    # Consumed by: Phase 5 prediction coordinator
    PHASE4_PRECOMPUTE_COMPLETE = 'nba-phase4-precompute-complete'

    # =========================================================================
    # PHASE 5: PREDICTIONS
    # =========================================================================

    # Published by: Phase 5 prediction coordinator
    # Consumed by: Phase 5→6 orchestrator
    PHASE5_PREDICTIONS_COMPLETE = 'nba-phase5-predictions-complete'

    # =========================================================================
    # PHASE 6: PUBLISHING
    # =========================================================================

    # Published by: Phase 5→6 orchestrator OR Cloud Scheduler
    # Consumed by: Phase 6 export Cloud Function
    PHASE6_EXPORT_TRIGGER = 'nba-phase6-export-trigger'

    # Published by: Phase 6 export Cloud Function
    # Consumed by: Monitoring, alerting
    PHASE6_EXPORT_COMPLETE = 'nba-phase6-export-complete'

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    @classmethod
    def get_all_topics(cls) -> dict:
        """
        Get all topic definitions.

        Returns:
            Dictionary of {name: topic_path}
        """
        return {
            'PHASE1_SCRAPERS_COMPLETE': cls.PHASE1_SCRAPERS_COMPLETE,
            'LEGACY_SCRAPER_COMPLETE': cls.LEGACY_SCRAPER_COMPLETE,
            'PHASE2_RAW_COMPLETE': cls.PHASE2_RAW_COMPLETE,
            'PHASE3_TRIGGER': cls.PHASE3_TRIGGER,
            'PHASE3_ANALYTICS_COMPLETE': cls.PHASE3_ANALYTICS_COMPLETE,
            'PHASE4_TRIGGER': cls.PHASE4_TRIGGER,
            'PHASE4_PROCESSOR_COMPLETE': cls.PHASE4_PROCESSOR_COMPLETE,
            'PHASE4_PRECOMPUTE_COMPLETE': cls.PHASE4_PRECOMPUTE_COMPLETE,
            'PHASE5_PREDICTIONS_COMPLETE': cls.PHASE5_PREDICTIONS_COMPLETE,
            'PHASE6_EXPORT_TRIGGER': cls.PHASE6_EXPORT_TRIGGER,
            'PHASE6_EXPORT_COMPLETE': cls.PHASE6_EXPORT_COMPLETE,
        }

    @classmethod
    def get_topic_for_phase(cls, phase: str) -> str:
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
            'phase_1_scrapers': cls.PHASE1_SCRAPERS_COMPLETE,
            'phase_2_raw': cls.PHASE2_RAW_COMPLETE,
            'phase_3_analytics': cls.PHASE3_ANALYTICS_COMPLETE,
            'phase_4_precompute': cls.PHASE4_PRECOMPUTE_COMPLETE,
            'phase_5_predictions': cls.PHASE5_PREDICTIONS_COMPLETE,
            'phase_6_publishing': cls.PHASE6_EXPORT_COMPLETE,
        }

        if phase not in mapping:
            raise ValueError(
                f"Unknown phase: {phase}. Valid phases: {list(mapping.keys())}"
            )

        return mapping[phase]


# Singleton instance for easy import
TOPICS = PubSubTopics()
