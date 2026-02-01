"""
Experiment Registry for ML Experiments

Tracks ML experiments in BigQuery for reproducibility and analysis.
Integrates with training scripts to log experiment lifecycle.

Schema follows docs/08-projects/current/system-evolution/DESIGN.md

Usage:
    from ml.experiments.experiment_registry import ExperimentRegistry

    registry = ExperimentRegistry()

    # Register experiment at start
    registry.register(
        experiment_id="EXP_001",
        name="Walk-forward training test",
        hypothesis="Recency weighting improves Jan accuracy",
        config={"train_start": "2024-01-01", ...}
    )

    # Update status during training
    registry.update_status("EXP_001", "running")

    # Complete with results
    registry.complete(
        experiment_id="EXP_001",
        results={"mae": 4.2, "sample_size": 10000},
        model_path="path/to/model.cbm"
    )

    # Or mark as failed
    registry.fail("EXP_001", error="Training failed: OOM")
"""

import json
import subprocess
from datetime import datetime
from typing import Optional, Any
from google.cloud import bigquery


PROJECT_ID = "nba-props-platform"
DATASET_ID = "nba_predictions"
TABLE_ID = "experiment_registry"
FULL_TABLE_ID = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"


def get_git_commit() -> Optional[str]:
    """Get current git commit hash, or None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]  # Short hash
    except Exception:
        pass
    return None


def get_git_branch() -> Optional[str]:
    """Get current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


class ExperimentRegistry:
    """
    Registry for tracking ML experiments in BigQuery.

    Experiments go through these statuses:
    - pending: Registered but not started
    - running: Training in progress
    - completed: Successfully finished with results
    - failed: Error during training
    - validated: Results verified
    - promoted: Model deployed to production
    - rejected: Did not meet criteria
    """

    def __init__(self, client: Optional[bigquery.Client] = None):
        """
        Initialize registry.

        Args:
            client: Optional BigQuery client. Creates one if not provided.
        """
        self.client = client or bigquery.Client(project=PROJECT_ID)
        self._ensure_table_exists()

    def _ensure_table_exists(self):
        """Create experiment_registry table if it doesn't exist."""
        schema = [
            bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("name", "STRING"),
            bigquery.SchemaField("hypothesis", "STRING"),
            bigquery.SchemaField("test_type", "STRING"),
            bigquery.SchemaField("config", "JSON"),
            bigquery.SchemaField("status", "STRING"),
            bigquery.SchemaField("git_commit", "STRING"),
            bigquery.SchemaField("git_branch", "STRING"),
            bigquery.SchemaField("model_path", "STRING"),
            bigquery.SchemaField("results", "JSON"),
            bigquery.SchemaField("error_message", "STRING"),
            bigquery.SchemaField("started_at", "TIMESTAMP"),
            bigquery.SchemaField("completed_at", "TIMESTAMP"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
        ]

        table_ref = self.client.dataset(DATASET_ID).table(TABLE_ID)

        try:
            self.client.get_table(table_ref)
        except Exception:
            # Table doesn't exist, create it
            table = bigquery.Table(table_ref, schema=schema)
            table.clustering_fields = ["status", "test_type"]
            self.client.create_table(table)
            print(f"Created table {FULL_TABLE_ID}")

    def register(
        self,
        experiment_id: str,
        name: str,
        hypothesis: str = "",
        test_type: str = "walkforward",
        config: Optional[dict] = None
    ) -> dict:
        """
        Register a new experiment.

        Args:
            experiment_id: Unique identifier for the experiment
            name: Human-readable name
            hypothesis: What we're testing
            test_type: Type of experiment (walkforward, ablation, etc.)
            config: Configuration dict (training params, etc.)

        Returns:
            The registered experiment record
        """
        now = datetime.utcnow().isoformat()
        git_commit = get_git_commit()
        git_branch = get_git_branch()

        record = {
            "experiment_id": experiment_id,
            "name": name,
            "hypothesis": hypothesis,
            "test_type": test_type,
            "config": json.dumps(config or {}),
            "status": "pending",
            "git_commit": git_commit,
            "git_branch": git_branch,
            "model_path": None,
            "results": None,
            "error_message": None,
            "started_at": None,
            "completed_at": None,
            "created_at": now,
            "updated_at": now,
        }

        errors = self.client.insert_rows_json(FULL_TABLE_ID, [record])
        if errors:
            raise RuntimeError(f"Failed to register experiment: {errors}")

        print(f"Registered experiment: {experiment_id}")
        return record

    def update_status(self, experiment_id: str, status: str):
        """
        Update experiment status.

        Args:
            experiment_id: Experiment to update
            status: New status (running, completed, failed, etc.)
        """
        now = datetime.utcnow().isoformat()

        # Use started_at for running status
        if status == "running":
            query = f"""
            UPDATE `{FULL_TABLE_ID}`
            SET status = @status,
                started_at = @now,
                updated_at = @now
            WHERE experiment_id = @experiment_id
            """
        else:
            query = f"""
            UPDATE `{FULL_TABLE_ID}`
            SET status = @status,
                updated_at = @now
            WHERE experiment_id = @experiment_id
            """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("status", "STRING", status),
                bigquery.ScalarQueryParameter("now", "STRING", now),
                bigquery.ScalarQueryParameter("experiment_id", "STRING", experiment_id),
            ]
        )

        self.client.query(query, job_config=job_config).result()
        print(f"Updated experiment {experiment_id} status to: {status}")

    def complete(
        self,
        experiment_id: str,
        results: dict,
        model_path: Optional[str] = None
    ):
        """
        Mark experiment as completed with results.

        Args:
            experiment_id: Experiment to complete
            results: Results dict (mae, sample_size, etc.)
            model_path: Path to saved model file
        """
        now = datetime.utcnow().isoformat()

        query = f"""
        UPDATE `{FULL_TABLE_ID}`
        SET status = 'completed',
            results = @results,
            model_path = @model_path,
            completed_at = @now,
            updated_at = @now
        WHERE experiment_id = @experiment_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("results", "JSON", json.dumps(results)),
                bigquery.ScalarQueryParameter("model_path", "STRING", model_path),
                bigquery.ScalarQueryParameter("now", "STRING", now),
                bigquery.ScalarQueryParameter("experiment_id", "STRING", experiment_id),
            ]
        )

        self.client.query(query, job_config=job_config).result()
        print(f"Completed experiment {experiment_id}")

    def fail(self, experiment_id: str, error: str):
        """
        Mark experiment as failed.

        Args:
            experiment_id: Experiment that failed
            error: Error message
        """
        now = datetime.utcnow().isoformat()

        query = f"""
        UPDATE `{FULL_TABLE_ID}`
        SET status = 'failed',
            error_message = @error,
            completed_at = @now,
            updated_at = @now
        WHERE experiment_id = @experiment_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("error", "STRING", error),
                bigquery.ScalarQueryParameter("now", "STRING", now),
                bigquery.ScalarQueryParameter("experiment_id", "STRING", experiment_id),
            ]
        )

        self.client.query(query, job_config=job_config).result()
        print(f"Marked experiment {experiment_id} as failed")

    def get(self, experiment_id: str) -> Optional[dict]:
        """
        Get experiment by ID.

        Args:
            experiment_id: Experiment to retrieve

        Returns:
            Experiment record or None if not found
        """
        query = f"""
        SELECT *
        FROM `{FULL_TABLE_ID}`
        WHERE experiment_id = @experiment_id
        ORDER BY created_at DESC
        LIMIT 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("experiment_id", "STRING", experiment_id),
            ]
        )

        result = self.client.query(query, job_config=job_config).result()
        rows = list(result)

        if rows:
            return dict(rows[0])
        return None

    def list_experiments(
        self,
        status: Optional[str] = None,
        test_type: Optional[str] = None,
        limit: int = 50
    ) -> list[dict]:
        """
        List experiments with optional filters.

        Args:
            status: Filter by status
            test_type: Filter by test type
            limit: Maximum results to return

        Returns:
            List of experiment records
        """
        conditions = []
        params = []

        if status:
            conditions.append("status = @status")
            params.append(bigquery.ScalarQueryParameter("status", "STRING", status))

        if test_type:
            conditions.append("test_type = @test_type")
            params.append(bigquery.ScalarQueryParameter("test_type", "STRING", test_type))

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
        SELECT *
        FROM `{FULL_TABLE_ID}`
        {where_clause}
        ORDER BY created_at DESC
        LIMIT {limit}
        """

        job_config = bigquery.QueryJobConfig(query_parameters=params)
        result = self.client.query(query, job_config=job_config).result()

        return [dict(row) for row in result]
