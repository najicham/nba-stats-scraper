"""Mixin for tracking processor and schema versions in processing runs."""
from datetime import datetime, timezone
from typing import Dict
import os
import subprocess


class ProcessorVersionMixin:
    """Mixin providing version tracking for all processors.

    Child classes should override:
        PROCESSOR_VERSION: str = "1.0"  # Semantic versioning
        PROCESSOR_SCHEMA_VERSION: str = "1.0"  # BigQuery schema version

    Usage:
        class MyProcessor(ProcessorVersionMixin, ProcessorBase):
            PROCESSOR_VERSION = "2.1"
            PROCESSOR_SCHEMA_VERSION = "1.5"
    """

    PROCESSOR_VERSION: str = "1.0"
    PROCESSOR_SCHEMA_VERSION: str = "1.0"

    def _get_deployment_info(self) -> Dict[str, str]:
        """Get deployment environment information."""
        # Try to get Cloud Run revision
        revision = os.environ.get('K_REVISION', '')
        if revision:
            return {
                'deployment_type': 'cloud_run',
                'revision_id': revision[:12],  # Truncate for readability
            }

        # Try to get git commit hash for local runs
        try:
            commit = subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'],
                stderr=subprocess.DEVNULL,
                timeout=2
            ).decode().strip()[:8]
            return {
                'deployment_type': 'local',
                'git_commit': commit,
            }
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return {
                'deployment_type': 'unknown',
            }

    def get_processor_metadata(self) -> Dict[str, str]:
        """Get processor version and deployment metadata."""
        metadata = {
            'processor_name': self.__class__.__name__,
            'processor_version': self.PROCESSOR_VERSION,
            'schema_version': self.PROCESSOR_SCHEMA_VERSION,
            'processed_at': datetime.now(timezone.utc).isoformat(),
        }
        metadata.update(self._get_deployment_info())
        return metadata

    def add_version_to_stats(self) -> None:
        """Add version info to self.stats for logging."""
        if hasattr(self, 'stats'):
            self.stats.update(self.get_processor_metadata())
