"""
Roster History Analytics Module

Provides:
- RosterHistoryProcessor: Tracks roster changes over time
"""

from .roster_history_processor import (
    RosterHistoryProcessor,
    RosterChangeType,
    DetectedRosterChange,
)

__all__ = [
    "RosterHistoryProcessor",
    "RosterChangeType",
    "DetectedRosterChange",
]
