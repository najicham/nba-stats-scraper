"""
Pub/Sub Topic Name Configuration - Single Source of Truth

This file defines all Pub/Sub topic names used across the NBA stats pipeline.
All phases should import from this file to ensure consistency.

Usage:
    from shared.config.pubsub_topics import TOPICS

    # Publishing
    publisher.publish(TOPICS.PHASE2_RAW_COMPLETE, message)

    # Subscribing
    subscriber.subscribe(TOPICS.PHASE2_RAW_COMPLETE, callback)

Last Updated: 2025-11-16
Topic Naming Convention: nba-phase{N}-{content}-{type}
"""

from typing import Dict


class PubSubTopics:
    """
    Centralized Pub/Sub topic name constants.

    Topic Naming Convention:
        nba-phase{N}-{content}-complete      Main event topics
        nba-phase{N}-{content}-complete-dlq  Dead Letter Queues
        nba-phase{N}-fallback-trigger        Time-based fallbacks

    Sport Prefix: 'nba-' (future: 'mlb-', 'nfl-', etc.)
    Phase Number: Indicates pipeline position (1-6)
    Content Type: Describes data type (scrapers, raw, analytics, etc.)
    """

    # =========================================================================
    # PHASE 1 → PHASE 2 (Scrapers → Raw Processors)
    # =========================================================================
    PHASE1_SCRAPERS_COMPLETE = "nba-phase1-scrapers-complete"
    PHASE1_SCRAPERS_COMPLETE_DLQ = "nba-phase1-scrapers-complete-dlq"

    # Legacy name (for migration reference only - DO NOT USE)
    _LEGACY_SCRAPER_COMPLETE = "nba-scraper-complete"

    # =========================================================================
    # PHASE 2 → PHASE 3 (Raw Processors → Analytics Processors)
    # =========================================================================
    PHASE2_RAW_COMPLETE = "nba-phase2-raw-complete"
    PHASE2_RAW_COMPLETE_DLQ = "nba-phase2-raw-complete-dlq"
    PHASE3_FALLBACK_TRIGGER = "nba-phase3-fallback-trigger"

    # =========================================================================
    # PHASE 3 → PHASE 4 (Analytics → Precompute)
    # =========================================================================
    PHASE3_ANALYTICS_COMPLETE = "nba-phase3-analytics-complete"
    PHASE3_ANALYTICS_COMPLETE_DLQ = "nba-phase3-analytics-complete-dlq"
    PHASE4_FALLBACK_TRIGGER = "nba-phase4-fallback-trigger"

    # =========================================================================
    # PHASE 4 → PHASE 5 (Precompute → Predictions)
    # =========================================================================
    PHASE4_PRECOMPUTE_COMPLETE = "nba-phase4-precompute-complete"
    PHASE4_PRECOMPUTE_COMPLETE_DLQ = "nba-phase4-precompute-complete-dlq"
    PHASE5_FALLBACK_TRIGGER = "nba-phase5-fallback-trigger"

    # =========================================================================
    # PHASE 5 → PHASE 6 (Predictions → Publishing)
    # =========================================================================
    PHASE5_PREDICTIONS_COMPLETE = "nba-phase5-predictions-complete"
    PHASE5_PREDICTIONS_COMPLETE_DLQ = "nba-phase5-predictions-complete-dlq"
    PHASE6_FALLBACK_TRIGGER = "nba-phase6-fallback-trigger"

    # =========================================================================
    # FALLBACK TRIGGERS (Time-based safety nets)
    # =========================================================================
    # Note: Named for the phase they TRIGGER, not the phase that publishes
    PHASE2_FALLBACK_TRIGGER = "nba-phase2-fallback-trigger"

    # Phase 3 fallback already defined above in Phase 2→3 section
    # Phase 4 fallback already defined above in Phase 3→4 section
    # Phase 5 fallback already defined above in Phase 4→5 section
    # Phase 6 fallback already defined above in Phase 5→6 section

    # =========================================================================
    # MANUAL OPERATIONS
    # =========================================================================
    MANUAL_REPROCESS = "nba-manual-reprocess"

    @classmethod
    def get_all_topics(cls) -> Dict[str, str]:
        """
        Get all topic names as a dictionary.
        Useful for validation and documentation.

        Returns:
            Dict mapping topic description to topic name
        """
        return {
            # Phase 1 → 2
            "phase1_scrapers_complete": cls.PHASE1_SCRAPERS_COMPLETE,
            "phase1_scrapers_complete_dlq": cls.PHASE1_SCRAPERS_COMPLETE_DLQ,

            # Phase 2 → 3
            "phase2_raw_complete": cls.PHASE2_RAW_COMPLETE,
            "phase2_raw_complete_dlq": cls.PHASE2_RAW_COMPLETE_DLQ,
            "phase2_fallback_trigger": cls.PHASE2_FALLBACK_TRIGGER,
            "phase3_fallback_trigger": cls.PHASE3_FALLBACK_TRIGGER,

            # Phase 3 → 4
            "phase3_analytics_complete": cls.PHASE3_ANALYTICS_COMPLETE,
            "phase3_analytics_complete_dlq": cls.PHASE3_ANALYTICS_COMPLETE_DLQ,
            "phase4_fallback_trigger": cls.PHASE4_FALLBACK_TRIGGER,

            # Phase 4 → 5
            "phase4_precompute_complete": cls.PHASE4_PRECOMPUTE_COMPLETE,
            "phase4_precompute_complete_dlq": cls.PHASE4_PRECOMPUTE_COMPLETE_DLQ,
            "phase5_fallback_trigger": cls.PHASE5_FALLBACK_TRIGGER,

            # Phase 5 → 6
            "phase5_predictions_complete": cls.PHASE5_PREDICTIONS_COMPLETE,
            "phase5_predictions_complete_dlq": cls.PHASE5_PREDICTIONS_COMPLETE_DLQ,
            "phase6_fallback_trigger": cls.PHASE6_FALLBACK_TRIGGER,

            # Manual
            "manual_reprocess": cls.MANUAL_REPROCESS,
        }

    @classmethod
    def get_phase_topics(cls, phase: int) -> Dict[str, str]:
        """
        Get all topics for a specific phase.

        Args:
            phase: Phase number (1-6)

        Returns:
            Dict of topic types to topic names for that phase

        Example:
            >>> TOPICS.get_phase_topics(2)
            {
                'complete': 'nba-phase2-raw-complete',
                'complete_dlq': 'nba-phase2-raw-complete-dlq',
                'next_fallback': 'nba-phase3-fallback-trigger'
            }
        """
        phase_map = {
            1: {
                'complete': cls.PHASE1_SCRAPERS_COMPLETE,
                'complete_dlq': cls.PHASE1_SCRAPERS_COMPLETE_DLQ,
                'next_fallback': cls.PHASE2_FALLBACK_TRIGGER,
            },
            2: {
                'complete': cls.PHASE2_RAW_COMPLETE,
                'complete_dlq': cls.PHASE2_RAW_COMPLETE_DLQ,
                'fallback': cls.PHASE2_FALLBACK_TRIGGER,
                'next_fallback': cls.PHASE3_FALLBACK_TRIGGER,
            },
            3: {
                'complete': cls.PHASE3_ANALYTICS_COMPLETE,
                'complete_dlq': cls.PHASE3_ANALYTICS_COMPLETE_DLQ,
                'fallback': cls.PHASE3_FALLBACK_TRIGGER,
                'next_fallback': cls.PHASE4_FALLBACK_TRIGGER,
            },
            4: {
                'complete': cls.PHASE4_PRECOMPUTE_COMPLETE,
                'complete_dlq': cls.PHASE4_PRECOMPUTE_COMPLETE_DLQ,
                'fallback': cls.PHASE4_FALLBACK_TRIGGER,
                'next_fallback': cls.PHASE5_FALLBACK_TRIGGER,
            },
            5: {
                'complete': cls.PHASE5_PREDICTIONS_COMPLETE,
                'complete_dlq': cls.PHASE5_PREDICTIONS_COMPLETE_DLQ,
                'fallback': cls.PHASE5_FALLBACK_TRIGGER,
                'next_fallback': cls.PHASE6_FALLBACK_TRIGGER,
            },
            6: {
                'fallback': cls.PHASE6_FALLBACK_TRIGGER,
            },
        }

        return phase_map.get(phase, {})


# Singleton instance for easy imports
TOPICS = PubSubTopics()


# Backward compatibility aliases (for migration period only)
# TODO: Remove these after all code migrated to TOPICS.* pattern
SCRAPER_COMPLETE_TOPIC = TOPICS.PHASE1_SCRAPERS_COMPLETE
RAW_DATA_COMPLETE_TOPIC = TOPICS.PHASE2_RAW_COMPLETE
ANALYTICS_COMPLETE_TOPIC = TOPICS.PHASE3_ANALYTICS_COMPLETE
