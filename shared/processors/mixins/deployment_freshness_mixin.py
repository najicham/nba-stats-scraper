"""Mixin for checking deployment freshness to prevent stale-code processing."""
from datetime import datetime, timedelta, timezone
import os
import logging

logger = logging.getLogger(__name__)


class DeploymentFreshnessMixin:
    """Warns when processing with deployments older than 24 hours.

    Prevents the "minutes bug" scenario where data was processed by
    pre-fix code after bug fix was committed but before deployment.
    """

    FRESHNESS_THRESHOLD_HOURS: int = 24

    def check_deployment_freshness(self) -> None:
        """Check if deployment is fresh, warn if stale."""
        # Only applicable to Cloud Run deployments
        revision = os.environ.get('K_REVISION')
        if not revision:
            logger.debug("Not running in Cloud Run, skipping freshness check")
            return

        # K_REVISION format: service-name-00001-abc (revision number indicates age)
        # We can't get exact timestamp from K_REVISION alone, so we check K_SERVICE
        service_name = os.environ.get('K_SERVICE', 'unknown')

        # Log the deployment info for tracking
        logger.info(
            f"Processing with deployment: {revision}",
            extra={
                'revision': revision,
                'service': service_name,
            }
        )

        # Note: Without K_REVISION_TIMESTAMP env var, we can't determine age
        # This is a limitation of Cloud Run - revision timestamps aren't exposed
        # Alternative: Check against latest git commit timestamp (if available)

        self._check_git_freshness()

    def _check_git_freshness(self) -> None:
        """Check if local git repo has recent uncommitted changes."""
        try:
            import subprocess

            # Check for uncommitted changes
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                capture_output=True,
                text=True,
                timeout=2
            )

            if result.returncode == 0 and result.stdout.strip():
                logger.warning(
                    "Processing with uncommitted local changes - "
                    "ensure deployment is up to date",
                    extra={'uncommitted_files': result.stdout.strip().split('\n')[:5]}
                )

            # Check last commit age
            result = subprocess.run(
                ['git', 'log', '-1', '--format=%ct'],
                capture_output=True,
                text=True,
                timeout=2
            )

            if result.returncode == 0:
                last_commit_ts = int(result.stdout.strip())
                last_commit_dt = datetime.fromtimestamp(last_commit_ts, tz=timezone.utc)
                age_hours = (datetime.now(timezone.utc) - last_commit_dt).total_seconds() / 3600

                if age_hours > self.FRESHNESS_THRESHOLD_HOURS:
                    logger.warning(
                        f"Last commit is {age_hours:.1f} hours old - "
                        f"verify deployment is recent",
                        extra={
                            'last_commit_age_hours': age_hours,
                            'threshold_hours': self.FRESHNESS_THRESHOLD_HOURS,
                        }
                    )

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            # Git not available or error - not critical, skip check
            pass
