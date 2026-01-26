"""
Extractor registry for routing paths to appropriate extractors.

The registry maintains an ordered list of extractors and tries them in sequence
until one matches the given path.
"""

import logging
from typing import List

from .base import PathExtractor


logger = logging.getLogger(__name__)


class ExtractorRegistry:
    """Registry for managing path extractors."""

    def __init__(self):
        """Initialize empty registry."""
        self._extractors: List[PathExtractor] = []

    def register(self, extractor: PathExtractor) -> None:
        """
        Register a path extractor.

        Args:
            extractor: PathExtractor instance to register
        """
        self._extractors.append(extractor)

    def extract_opts(self, path: str) -> dict:
        """
        Extract options from path using registered extractors.

        Tries each extractor in order until one matches.

        Args:
            path: GCS file path

        Returns:
            Dictionary of extracted options

        Raises:
            ValueError: If no extractor matches the path
        """
        for extractor in self._extractors:
            if extractor.matches(path):
                try:
                    return extractor.extract(path)
                except Exception as e:
                    logger.error(
                        f"Extractor {extractor.__class__.__name__} matched path "
                        f"but failed to extract: {e}",
                        exc_info=True
                    )
                    raise

        # No extractor matched
        raise ValueError(f"No extractor found for path: {path}")
