"""
Environment Variable Monitoring for NBA Prediction Worker

Monitors critical environment variables and detects unexpected changes.
Prevents incidents like the CatBoost CATBOOST_V8_MODEL_PATH deletion.

Usage:
    monitor = EnvVarMonitor(project_id="nba-props-platform")
    monitor.check_for_changes()  # Raises alert if changes detected
"""

import os
import json
import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from google.cloud import storage
from google.cloud import bigquery
import logging

logger = logging.getLogger(__name__)


class EnvVarMonitor:
    """Monitors critical environment variables for unexpected changes."""

    # Critical environment variables to monitor
    CRITICAL_ENV_VARS = [
        "XGBOOST_V1_MODEL_PATH",
        "CATBOOST_V8_MODEL_PATH",
        "NBA_ACTIVE_SYSTEMS",
        "NBA_MIN_CONFIDENCE",
        "NBA_MIN_EDGE"
    ]

    # GCS bucket and path for storing baseline snapshots
    BASELINE_BUCKET = "nba-scraped-data"
    BASELINE_PATH = "env-snapshots/nba-prediction-worker-env.json"

    # Deployment grace period (minutes) - don't alert during planned deployments
    DEPLOYMENT_GRACE_PERIOD_MINUTES = 30

    def __init__(self, project_id: str):
        """
        Initialize environment variable monitor.

        Args:
            project_id: GCP project ID
        """
        self.project_id = project_id
        self.storage_client = storage.Client(project=project_id)
        self.bigquery_client = bigquery.Client(project=project_id)

    def get_current_env_vars(self) -> Dict[str, Optional[str]]:
        """
        Get current values of critical environment variables.

        Returns:
            Dictionary mapping env var names to their current values (or None if not set)
        """
        env_vars = {}
        for var_name in self.CRITICAL_ENV_VARS:
            env_vars[var_name] = os.environ.get(var_name)
        return env_vars

    def compute_env_hash(self, env_vars: Dict[str, Optional[str]]) -> str:
        """
        Compute SHA256 hash of environment variables.

        Args:
            env_vars: Dictionary of environment variable name -> value

        Returns:
            SHA256 hash of the env vars (deterministic)
        """
        # Sort keys for deterministic hashing
        sorted_items = sorted(env_vars.items())
        env_string = json.dumps(sorted_items, sort_keys=True)
        return hashlib.sha256(env_string.encode()).hexdigest()

    def load_baseline(self) -> Optional[Dict[str, Any]]:
        """
        Load baseline environment snapshot from GCS.

        Returns:
            Baseline snapshot dict with 'env_vars', 'hash', 'timestamp', 'deployment_started_at'
            or None if no baseline exists
        """
        try:
            bucket = self.storage_client.bucket(self.BASELINE_BUCKET)
            blob = bucket.blob(self.BASELINE_PATH)

            if not blob.exists():
                logger.warning(f"No baseline snapshot found at gs://{self.BASELINE_BUCKET}/{self.BASELINE_PATH}")
                return None

            baseline_json = blob.download_as_text()
            baseline = json.loads(baseline_json)

            logger.info(f"✓ Loaded baseline snapshot from {baseline.get('timestamp', 'unknown time')}")
            return baseline

        except Exception as e:
            logger.error(f"Failed to load baseline snapshot: {e}")
            return None

    def save_baseline(self, env_vars: Dict[str, Optional[str]], deployment_started_at: Optional[str] = None):
        """
        Save current environment snapshot as new baseline to GCS.

        Args:
            env_vars: Current environment variables
            deployment_started_at: ISO timestamp when deployment started (for grace period)
        """
        try:
            snapshot = {
                "env_vars": env_vars,
                "hash": self.compute_env_hash(env_vars),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "deployment_started_at": deployment_started_at
            }

            bucket = self.storage_client.bucket(self.BASELINE_BUCKET)
            blob = bucket.blob(self.BASELINE_PATH)
            blob.upload_from_string(
                json.dumps(snapshot, indent=2),
                content_type="application/json"
            )

            logger.info(f"✓ Saved new baseline snapshot to gs://{self.BASELINE_BUCKET}/{self.BASELINE_PATH}")

        except Exception as e:
            logger.error(f"Failed to save baseline snapshot: {e}")
            raise

    def is_in_deployment_window(self, baseline: Dict[str, Any]) -> bool:
        """
        Check if we're currently in a deployment grace period.

        Args:
            baseline: Baseline snapshot

        Returns:
            True if within deployment grace period, False otherwise
        """
        deployment_started_at = baseline.get("deployment_started_at")
        if not deployment_started_at:
            return False

        try:
            deployment_time = datetime.fromisoformat(deployment_started_at.replace("Z", "+00:00"))
            time_since_deployment = datetime.utcnow().replace(tzinfo=deployment_time.tzinfo) - deployment_time

            if time_since_deployment < timedelta(minutes=self.DEPLOYMENT_GRACE_PERIOD_MINUTES):
                remaining = self.DEPLOYMENT_GRACE_PERIOD_MINUTES - int(time_since_deployment.total_seconds() / 60)
                logger.info(f"⏳ In deployment grace period ({remaining} minutes remaining)")
                return True

        except Exception as e:
            logger.warning(f"Failed to parse deployment_started_at: {e}")

        return False

    def detect_changes(self, current: Dict[str, Optional[str]], baseline: Dict[str, Optional[str]]) -> List[Dict[str, Any]]:
        """
        Detect changes between current and baseline environment variables.

        Args:
            current: Current environment variables
            baseline: Baseline environment variables

        Returns:
            List of change dictionaries with 'var_name', 'change_type', 'old_value', 'new_value'
        """
        changes = []

        for var_name in self.CRITICAL_ENV_VARS:
            current_value = current.get(var_name)
            baseline_value = baseline.get(var_name)

            if current_value != baseline_value:
                if baseline_value is None and current_value is not None:
                    change_type = "ADDED"
                elif baseline_value is not None and current_value is None:
                    change_type = "REMOVED"
                else:
                    change_type = "MODIFIED"

                changes.append({
                    "var_name": var_name,
                    "change_type": change_type,
                    "old_value": baseline_value,
                    "new_value": current_value
                })

        return changes

    def log_to_bigquery(self,
                       change_type: str,
                       changes: List[Dict[str, Any]],
                       reason: str = None,
                       deployment_started_at: str = None,
                       in_deployment_window: bool = False,
                       alert_triggered: bool = False,
                       alert_reason: str = None):
        """
        Log environment variable change to BigQuery audit table.

        Args:
            change_type: Type of change (ADDED, REMOVED, MODIFIED, DEPLOYMENT_START, BASELINE_INIT)
            changes: List of change dictionaries
            reason: Reason for change
            deployment_started_at: Deployment start timestamp
            in_deployment_window: Whether change occurred during deployment window
            alert_triggered: Whether this change triggered an alert
            alert_reason: Reason for alert
        """
        try:
            table_id = f"{self.project_id}.nba_orchestration.env_var_audit"

            # Prepare changed_vars array
            changed_vars = []
            for change in changes:
                changed_vars.append({
                    "var_name": change.get("var_name"),
                    "old_value": change.get("old_value"),
                    "new_value": change.get("new_value")
                })

            # Get current env vars and compute hash
            current_env = self.get_current_env_vars()
            env_hash = self.compute_env_hash(current_env)

            # Prepare row
            row = {
                "change_id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "change_type": change_type,
                "changed_vars": changed_vars,
                "deployer": os.environ.get("K_SERVICE", "unknown"),  # Cloud Run service name
                "reason": reason,
                "deployment_started_at": deployment_started_at,
                "in_deployment_window": in_deployment_window,
                "service_name": "prediction-worker",
                "service_revision": os.environ.get("K_REVISION", "unknown"),
                "environment": "prod",  # Could be made configurable
                "env_hash": env_hash,
                "alert_triggered": alert_triggered,
                "alert_reason": alert_reason
            }

            # Insert row
            errors = self.bigquery_client.insert_rows_json(table_id, [row])

            if errors:
                logger.error(f"❌ Failed to log to BigQuery: {errors}")
            else:
                logger.info(f"✓ Logged change to BigQuery audit table: {change_type}")

        except Exception as e:
            # Don't fail the whole check if BigQuery logging fails
            logger.error(f"Error logging to BigQuery: {e}")

    def check_for_changes(self) -> Dict[str, Any]:
        """
        Check for environment variable changes and alert if detected.

        Returns:
            Status dictionary with 'status', 'changes', 'message'

        Raises:
            Logs structured error (for log-based metric) if unauthorized changes detected
        """
        current_env = self.get_current_env_vars()
        current_hash = self.compute_env_hash(current_env)

        # Load baseline
        baseline = self.load_baseline()

        # If no baseline, create one and return
        if baseline is None:
            logger.warning("⚠️  No baseline found - creating initial snapshot")
            self.save_baseline(current_env)

            # Log baseline initialization to BigQuery
            self.log_to_bigquery(
                change_type="BASELINE_INIT",
                changes=[],
                reason="Initial baseline snapshot created",
                in_deployment_window=False,
                alert_triggered=False
            )

            return {
                "status": "INITIALIZED",
                "changes": [],
                "message": "Created initial baseline snapshot"
            }

        baseline_hash = baseline.get("hash")
        baseline_env = baseline.get("env_vars", {})

        # Check if hash matches (no changes)
        if current_hash == baseline_hash:
            logger.info("✓ Environment variables match baseline (no changes)")
            return {
                "status": "OK",
                "changes": [],
                "message": "No changes detected"
            }

        # Detect specific changes
        changes = self.detect_changes(current_env, baseline_env)

        if not changes:
            # Hash mismatch but no changes detected (shouldn't happen)
            logger.warning("⚠️  Hash mismatch but no changes detected")
            return {
                "status": "OK",
                "changes": [],
                "message": "Hash mismatch but no changes (possible hash collision)"
            }

        # Check if in deployment window
        if self.is_in_deployment_window(baseline):
            logger.info(f"⏳ Changes detected but in deployment grace period: {len(changes)} changes")
            # Update baseline with new values (planned deployment)
            self.save_baseline(current_env, deployment_started_at=baseline.get("deployment_started_at"))

            # Log to BigQuery (no alert)
            self.log_to_bigquery(
                change_type="MODIFIED",
                changes=changes,
                reason="Planned deployment",
                deployment_started_at=baseline.get("deployment_started_at"),
                in_deployment_window=True,
                alert_triggered=False
            )

            return {
                "status": "DEPLOYMENT_IN_PROGRESS",
                "changes": changes,
                "message": f"{len(changes)} changes detected during deployment window (expected)"
            }

        # ALERT: Unexpected changes detected outside deployment window
        change_summary = ", ".join([f"{c['var_name']} ({c['change_type']})" for c in changes])

        # Log structured error for log-based metric to capture
        logger.error(
            f"🚨 ALERT: Unexpected environment variable changes detected: {change_summary}",
            extra={
                "json_fields": {
                    "alert_type": "ENV_VAR_CHANGE",
                    "severity": "WARNING",
                    "changes": changes,
                    "change_count": len(changes),
                    "baseline_timestamp": baseline.get("timestamp"),
                    "deployment_started_at": baseline.get("deployment_started_at")
                }
            }
        )

        # Log to BigQuery audit table
        self.log_to_bigquery(
            change_type="MODIFIED",  # Could be ADDED/REMOVED/MODIFIED based on changes
            changes=changes,
            reason="Unexpected change detected outside deployment window",
            deployment_started_at=baseline.get("deployment_started_at"),
            in_deployment_window=False,
            alert_triggered=True,
            alert_reason=change_summary
        )

        # Update baseline to prevent repeated alerts
        self.save_baseline(current_env)

        return {
            "status": "ALERT",
            "changes": changes,
            "message": f"Unexpected changes detected: {change_summary}"
        }

    def mark_deployment_started(self):
        """
        Mark that a deployment has started - sets deployment grace period.
        Call this from /internal/deployment-started endpoint during planned deployments.
        """
        current_env = self.get_current_env_vars()
        deployment_started_at = datetime.utcnow().isoformat() + "Z"

        self.save_baseline(current_env, deployment_started_at=deployment_started_at)

        # Log deployment start to BigQuery
        self.log_to_bigquery(
            change_type="DEPLOYMENT_START",
            changes=[],
            reason="Deployment grace period activated",
            deployment_started_at=deployment_started_at,
            in_deployment_window=True,
            alert_triggered=False
        )

        logger.info(f"✓ Deployment started at {deployment_started_at} - grace period: {self.DEPLOYMENT_GRACE_PERIOD_MINUTES} minutes")

        return {
            "status": "OK",
            "deployment_started_at": deployment_started_at,
            "grace_period_minutes": self.DEPLOYMENT_GRACE_PERIOD_MINUTES,
            "message": "Deployment grace period activated"
        }
