"""
Base path extractor class.

All path extractors must inherit from this base class and implement
the matches() and extract() methods.
"""

from abc import ABC, abstractmethod


class PathExtractor(ABC):
    """Base class for path extractors."""

    @abstractmethod
    def matches(self, path: str) -> bool:
        """
        Check if this extractor handles the given path.

        Args:
            path: GCS file path

        Returns:
            True if this extractor can handle the path, False otherwise
        """
        pass

    @abstractmethod
    def extract(self, path: str) -> dict:
        """
        Extract options from the path.

        Args:
            path: GCS file path

        Returns:
            Dictionary of extracted options

        Raises:
            ValueError: If path cannot be parsed
        """
        pass
