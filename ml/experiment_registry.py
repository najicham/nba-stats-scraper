"""
ML Experiment Registry

Tracks ML experiments in BigQuery for reproducibility and comparison.
Provides methods to register, update, query, and promote experiments.

Usage:
    from ml.experiment_registry import ExperimentRegistry

    # Register a new experiment
    registry = ExperimentRegistry()
    experiment_id = registry.register_experiment({
        "name": "CatBoost v10 with trajectory features",
        "experiment_type": "training",
        "config": {
            "model_type": "catboost",
            "feature_count": 37,
            "train_start": "2021-11-01",
            "train_end": "2024-06-01",
        },
        "tags": ["catboost", "v10", "trajectory-features"],
    })

    # Start experiment
    registry.start_experiment(experiment_id)

    # Complete with results
    registry.complete_experiment(
        experiment_id,
        results={"mae": 3.35, "hit_rate": 0.52},
        model_path="gs://bucket/models/catboost_v10.cbm"
    )

    # Query experiments
    experiments = registry.list_experiments(status="completed", tags=["catboost"])

    # Find best experiment
    best = registry.get_best_experiment(metric="hit_rate", eval_start=date(2024, 10, 1))
"""

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import logging
import subprocess
import uuid

from google.cloud import bigquery
import yaml

logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"
DATASET_ID = "nba_predictions"
TABLE_ID = "ml_experiments"
FULL_TABLE_ID = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"


# Schema for ml_experiments table
EXPERIMENTS_SCHEMA = [
    bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("experiment_type", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("config", "JSON"),
    bigquery.SchemaField("tags", "STRING", mode="REPEATED"),
    bigquery.SchemaField("git_commit", "STRING"),
    bigquery.SchemaField("git_branch", "STRING"),
    bigquery.SchemaField("train_start", "DATE"),
    bigquery.SchemaField("train_end", "DATE"),
    bigquery.SchemaField("eval_start", "DATE"),
    bigquery.SchemaField("eval_end", "DATE"),
    bigquery.SchemaField("results", "JSON"),
    bigquery.SchemaField("model_path", "STRING"),
    bigquery.SchemaField("error_message", "STRING"),
    bigquery.SchemaField("is_promoted", "BOOL"),
    bigquery.SchemaField("promoted_at", "TIMESTAMP"),
    bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("started_at", "TIMESTAMP"),
    bigquery.SchemaField("completed_at", "TIMESTAMP"),
    bigquery.SchemaField("created_by", "STRING"),
    bigquery.SchemaField("notes", "STRING"),
]


@dataclass
class ExperimentConfig:
    """Configuration for an experiment"""
    model_type: str
    feature_count: int
    train_start: str
    train_end: str
    hyperparameters: Dict[str, Any] = field(default_factory=dict)
    feature_list: List[str] = field(default_factory=list)
    eval_start: Optional[str] = None
    eval_end: Optional[str] = None
    min_edge: Optional[float] = None
    recency_weighting: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for BigQuery storage"""
        return {k: v for k, v in asdict(self).items() if v is not None}


def _get_git_commit() -> Optional[str]:
    """Get current git commit hash"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.debug(f"Could not get git commit: {e}")
    return None


def _get_git_branch() -> Optional[str]:
    """Get current git branch name"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.debug(f"Could not get git branch: {e}")
    return None


class ExperimentRegistry:
    """
    Registry for ML experiments stored in BigQuery.

    Provides methods to:
    - Register new experiments
    - Update experiment status (pending -> running -> completed/failed)
    - Query experiments by filters
    - Find best performing experiments
    - Promote experiments to production
    """

    def __init__(self, project_id: str = PROJECT_ID):
        """
        Initialize the experiment registry.

        Args:
            project_id: GCP project ID
        """
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)
        self._ensure_table_exists()

    def _ensure_table_exists(self) -> None:
        """Create experiments table if it doesn't exist"""
        try:
            self.client.get_table(FULL_TABLE_ID)
            logger.debug(f"Table {FULL_TABLE_ID} exists")
        except Exception:
            logger.info(f"Creating table {FULL_TABLE_ID}")
            table = bigquery.Table(FULL_TABLE_ID, schema=EXPERIMENTS_SCHEMA)
            table.description = "ML experiment tracking for reproducibility and comparison"
            self.client.create_table(table)
            logger.info(f"Created table {FULL_TABLE_ID}")

    def register_experiment(self, config: dict) -> str:
        """
        Register a new experiment.

        Args:
            config: Experiment configuration with required fields:
                - name: Display name for the experiment
                - experiment_type: Type (training, evaluation, comparison, etc.)
                - config: Nested configuration dict
                Optional fields:
                - tags: List of string tags for filtering
                - train_start, train_end: Training date range
                - eval_start, eval_end: Evaluation date range
                - notes: Free-form notes
                - created_by: Who created this experiment

        Returns:
            Unique experiment_id (UUID)

        Raises:
            ValueError: If required fields are missing
        """
        # Validate required fields
        required_fields = ["name", "experiment_type"]
        for field_name in required_fields:
            if field_name not in config:
                raise ValueError(f"Missing required field: {field_name}")

        experiment_id = str(uuid.uuid4())

        # Build the row
        row = {
            "experiment_id": experiment_id,
            "name": config["name"],
            "experiment_type": config["experiment_type"],
            "status": "pending",
            "config": json.dumps(config.get("config", {})),
            "tags": config.get("tags", []),
            "git_commit": config.get("git_commit") or _get_git_commit(),
            "git_branch": config.get("git_branch") or _get_git_branch(),
            "train_start": config.get("train_start"),
            "train_end": config.get("train_end"),
            "eval_start": config.get("eval_start"),
            "eval_end": config.get("eval_end"),
            "is_promoted": False,
            "created_at": datetime.utcnow().isoformat(),
            "created_by": config.get("created_by"),
            "notes": config.get("notes"),
        }

        # Remove None values to let BigQuery use defaults
        row = {k: v for k, v in row.items() if v is not None}

        errors = self.client.insert_rows_json(FULL_TABLE_ID, [row])

        if errors:
            logger.error(f"Error inserting experiment: {errors}")
            raise RuntimeError(f"Failed to register experiment: {errors}")

        logger.info(f"Registered experiment {experiment_id}: {config['name']}")
        return experiment_id

    def start_experiment(self, experiment_id: str) -> None:
        """
        Mark experiment as running.

        Args:
            experiment_id: The experiment ID to update

        Raises:
            ValueError: If experiment not found or not in pending status
        """
        # Verify experiment exists and is pending
        experiment = self.get_experiment(experiment_id)
        if experiment is None:
            raise ValueError(f"Experiment not found: {experiment_id}")

        if experiment["status"] != "pending":
            raise ValueError(
                f"Experiment {experiment_id} is not pending "
                f"(current status: {experiment['status']})"
            )

        query = f"""
        UPDATE `{FULL_TABLE_ID}`
        SET
            status = 'running',
            started_at = CURRENT_TIMESTAMP()
        WHERE experiment_id = @experiment_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("experiment_id", "STRING", experiment_id)
            ]
        )

        self.client.query(query, job_config=job_config).result()
        logger.info(f"Started experiment {experiment_id}")

    def complete_experiment(
        self,
        experiment_id: str,
        results: dict,
        model_path: Optional[str] = None
    ) -> None:
        """
        Mark experiment as completed with results.

        Args:
            experiment_id: The experiment ID to update
            results: Dictionary of results (MAE, hit_rate, ROI, etc.)
            model_path: Path to saved model file (local or GCS)

        Raises:
            ValueError: If experiment not found or not in running status
        """
        # Verify experiment exists and is running
        experiment = self.get_experiment(experiment_id)
        if experiment is None:
            raise ValueError(f"Experiment not found: {experiment_id}")

        if experiment["status"] not in ("pending", "running"):
            raise ValueError(
                f"Experiment {experiment_id} cannot be completed "
                f"(current status: {experiment['status']})"
            )

        query = f"""
        UPDATE `{FULL_TABLE_ID}`
        SET
            status = 'completed',
            results = @results,
            model_path = @model_path,
            completed_at = CURRENT_TIMESTAMP()
        WHERE experiment_id = @experiment_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("experiment_id", "STRING", experiment_id),
                bigquery.ScalarQueryParameter("results", "STRING", json.dumps(results)),
                bigquery.ScalarQueryParameter("model_path", "STRING", model_path),
            ]
        )

        self.client.query(query, job_config=job_config).result()
        logger.info(f"Completed experiment {experiment_id}")

    def fail_experiment(self, experiment_id: str, error: str) -> None:
        """
        Mark experiment as failed with error message.

        Args:
            experiment_id: The experiment ID to update
            error: Error message describing the failure

        Raises:
            ValueError: If experiment not found
        """
        experiment = self.get_experiment(experiment_id)
        if experiment is None:
            raise ValueError(f"Experiment not found: {experiment_id}")

        query = f"""
        UPDATE `{FULL_TABLE_ID}`
        SET
            status = 'failed',
            error_message = @error,
            completed_at = CURRENT_TIMESTAMP()
        WHERE experiment_id = @experiment_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("experiment_id", "STRING", experiment_id),
                bigquery.ScalarQueryParameter("error", "STRING", error[:4000]),  # Truncate
            ]
        )

        self.client.query(query, job_config=job_config).result()
        logger.info(f"Failed experiment {experiment_id}: {error[:100]}...")

    def get_experiment(self, experiment_id: str) -> Optional[dict]:
        """
        Get experiment by ID.

        Args:
            experiment_id: The experiment ID to retrieve

        Returns:
            Dictionary with experiment data, or None if not found
        """
        query = f"""
        SELECT *
        FROM `{FULL_TABLE_ID}`
        WHERE experiment_id = @experiment_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("experiment_id", "STRING", experiment_id)
            ]
        )

        result = self.client.query(query, job_config=job_config).result()
        rows = list(result)

        if not rows:
            return None

        row = dict(rows[0])

        # Parse JSON fields
        if row.get("config"):
            try:
                row["config"] = json.loads(row["config"])
            except (json.JSONDecodeError, TypeError):
                pass

        if row.get("results"):
            try:
                row["results"] = json.loads(row["results"])
            except (json.JSONDecodeError, TypeError):
                pass

        return row

    def list_experiments(
        self,
        status: Optional[str] = None,
        experiment_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50
    ) -> List[dict]:
        """
        Query experiments with filters.

        Args:
            status: Filter by status (pending, running, completed, failed)
            experiment_type: Filter by experiment type
            tags: Filter by tags (experiments must have ALL specified tags)
            limit: Maximum number of results (default 50)

        Returns:
            List of experiment dictionaries
        """
        conditions = []
        params = []

        if status:
            conditions.append("status = @status")
            params.append(bigquery.ScalarQueryParameter("status", "STRING", status))

        if experiment_type:
            conditions.append("experiment_type = @experiment_type")
            params.append(bigquery.ScalarQueryParameter(
                "experiment_type", "STRING", experiment_type
            ))

        if tags:
            # All tags must be present
            for i, tag in enumerate(tags):
                conditions.append(f"@tag_{i} IN UNNEST(tags)")
                params.append(bigquery.ScalarQueryParameter(f"tag_{i}", "STRING", tag))

        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        query = f"""
        SELECT *
        FROM `{FULL_TABLE_ID}`
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT @limit
        """

        params.append(bigquery.ScalarQueryParameter("limit", "INT64", limit))

        job_config = bigquery.QueryJobConfig(query_parameters=params)
        result = self.client.query(query, job_config=job_config).result()

        experiments = []
        for row in result:
            exp = dict(row)
            # Parse JSON fields
            if exp.get("config"):
                try:
                    exp["config"] = json.loads(exp["config"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if exp.get("results"):
                try:
                    exp["results"] = json.loads(exp["results"])
                except (json.JSONDecodeError, TypeError):
                    pass
            experiments.append(exp)

        return experiments

    def get_best_experiment(
        self,
        metric: str = "hit_rate",
        eval_start: Optional[date] = None,
        eval_end: Optional[date] = None,
        experiment_type: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> Optional[dict]:
        """
        Find best performing experiment by a metric.

        Args:
            metric: Metric to rank by (from results JSON).
                    Common metrics: hit_rate, mae, roi, accuracy
            eval_start: Only consider experiments with eval_start >= this date
            eval_end: Only consider experiments with eval_end <= this date
            experiment_type: Filter by experiment type
            tags: Filter by tags

        Returns:
            Best experiment dictionary, or None if no matches

        Note:
            For metrics like MAE where lower is better, the query uses ASC ordering.
            For metrics like hit_rate where higher is better, it uses DESC.
        """
        conditions = ["status = 'completed'"]
        params = []

        if eval_start:
            conditions.append("eval_start >= @eval_start")
            params.append(bigquery.ScalarQueryParameter(
                "eval_start", "DATE", eval_start
            ))

        if eval_end:
            conditions.append("eval_end <= @eval_end")
            params.append(bigquery.ScalarQueryParameter(
                "eval_end", "DATE", eval_end
            ))

        if experiment_type:
            conditions.append("experiment_type = @experiment_type")
            params.append(bigquery.ScalarQueryParameter(
                "experiment_type", "STRING", experiment_type
            ))

        if tags:
            for i, tag in enumerate(tags):
                conditions.append(f"@tag_{i} IN UNNEST(tags)")
                params.append(bigquery.ScalarQueryParameter(f"tag_{i}", "STRING", tag))

        where_clause = " AND ".join(conditions)

        # Determine sort order based on metric
        # Lower is better for: mae, mse, error, loss
        lower_is_better = metric.lower() in ("mae", "mse", "rmse", "error", "loss")
        sort_order = "ASC" if lower_is_better else "DESC"

        params.append(bigquery.ScalarQueryParameter("metric", "STRING", metric))

        query = f"""
        SELECT *,
            CAST(JSON_EXTRACT_SCALAR(results, CONCAT('$.', @metric)) AS FLOAT64) as metric_value
        FROM `{FULL_TABLE_ID}`
        WHERE {where_clause}
            AND JSON_EXTRACT_SCALAR(results, CONCAT('$.', @metric)) IS NOT NULL
        ORDER BY metric_value {sort_order}
        LIMIT 1
        """

        job_config = bigquery.QueryJobConfig(query_parameters=params)
        result = self.client.query(query, job_config=job_config).result()
        rows = list(result)

        if not rows:
            return None

        exp = dict(rows[0])

        # Parse JSON fields
        if exp.get("config"):
            try:
                exp["config"] = json.loads(exp["config"])
            except (json.JSONDecodeError, TypeError):
                pass
        if exp.get("results"):
            try:
                exp["results"] = json.loads(exp["results"])
            except (json.JSONDecodeError, TypeError):
                pass

        return exp

    def promote_experiment(self, experiment_id: str) -> None:
        """
        Mark experiment as promoted (deployed to production).

        This does not actually deploy the model - it only marks the experiment
        as promoted for tracking purposes. Use the model_path from the experiment
        to update the ml_model_registry for actual deployment.

        Args:
            experiment_id: The experiment ID to promote

        Raises:
            ValueError: If experiment not found or not completed
        """
        experiment = self.get_experiment(experiment_id)
        if experiment is None:
            raise ValueError(f"Experiment not found: {experiment_id}")

        if experiment["status"] != "completed":
            raise ValueError(
                f"Experiment {experiment_id} cannot be promoted "
                f"(status must be 'completed', got '{experiment['status']}')"
            )

        query = f"""
        UPDATE `{FULL_TABLE_ID}`
        SET
            is_promoted = TRUE,
            promoted_at = CURRENT_TIMESTAMP()
        WHERE experiment_id = @experiment_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("experiment_id", "STRING", experiment_id)
            ]
        )

        self.client.query(query, job_config=job_config).result()
        logger.info(f"Promoted experiment {experiment_id}")

    @staticmethod
    def load_config(yaml_path: str) -> dict:
        """
        Load experiment config from YAML file.

        Args:
            yaml_path: Path to YAML configuration file

        Returns:
            Configuration dictionary ready for register_experiment()

        Example YAML:
            name: CatBoost v10 Walk-Forward
            experiment_type: training
            tags:
              - catboost
              - v10
              - walk-forward
            train_start: "2021-11-01"
            train_end: "2024-06-01"
            eval_start: "2024-10-01"
            eval_end: "2025-01-31"
            config:
              model_type: catboost
              feature_count: 37
              hyperparameters:
                depth: 6
                learning_rate: 0.07
                l2_leaf_reg: 3.8
        """
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {yaml_path}")

        with open(path) as f:
            config = yaml.safe_load(f)

        # Validate required fields
        required = ["name", "experiment_type"]
        for field_name in required:
            if field_name not in config:
                raise ValueError(f"Missing required field in config: {field_name}")

        return config

    def update_experiment(self, experiment_id: str, updates: dict) -> None:
        """
        Update experiment fields.

        Args:
            experiment_id: The experiment ID to update
            updates: Dictionary of fields to update. Supported fields:
                - notes: Free-form notes
                - tags: List of tags
                - eval_start, eval_end: Evaluation date range

        Raises:
            ValueError: If experiment not found
        """
        experiment = self.get_experiment(experiment_id)
        if experiment is None:
            raise ValueError(f"Experiment not found: {experiment_id}")

        # Build SET clause from updates
        set_clauses = []
        params = [bigquery.ScalarQueryParameter("experiment_id", "STRING", experiment_id)]

        if "notes" in updates:
            set_clauses.append("notes = @notes")
            params.append(bigquery.ScalarQueryParameter("notes", "STRING", updates["notes"]))

        if "eval_start" in updates:
            set_clauses.append("eval_start = @eval_start")
            params.append(bigquery.ScalarQueryParameter(
                "eval_start", "DATE", updates["eval_start"]
            ))

        if "eval_end" in updates:
            set_clauses.append("eval_end = @eval_end")
            params.append(bigquery.ScalarQueryParameter(
                "eval_end", "DATE", updates["eval_end"]
            ))

        if not set_clauses:
            logger.warning("No valid updates provided")
            return

        query = f"""
        UPDATE `{FULL_TABLE_ID}`
        SET {', '.join(set_clauses)}
        WHERE experiment_id = @experiment_id
        """

        job_config = bigquery.QueryJobConfig(query_parameters=params)
        self.client.query(query, job_config=job_config).result()
        logger.info(f"Updated experiment {experiment_id}")

    def get_experiment_summary(
        self,
        days: int = 30,
        group_by: str = "experiment_type"
    ) -> List[dict]:
        """
        Get summary statistics of recent experiments.

        Args:
            days: Number of days to look back (default 30)
            group_by: Field to group by (experiment_type, status)

        Returns:
            List of summary dictionaries
        """
        valid_group_by = {"experiment_type", "status"}
        if group_by not in valid_group_by:
            raise ValueError(f"group_by must be one of: {valid_group_by}")

        query = f"""
        SELECT
            {group_by},
            COUNT(*) as count,
            COUNTIF(status = 'completed') as completed,
            COUNTIF(status = 'failed') as failed,
            COUNTIF(status = 'running') as running,
            COUNTIF(status = 'pending') as pending,
            AVG(CASE
                WHEN status = 'completed'
                THEN CAST(JSON_EXTRACT_SCALAR(results, '$.mae') AS FLOAT64)
            END) as avg_mae,
            AVG(CASE
                WHEN status = 'completed'
                THEN CAST(JSON_EXTRACT_SCALAR(results, '$.hit_rate') AS FLOAT64)
            END) as avg_hit_rate
        FROM `{FULL_TABLE_ID}`
        WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
        GROUP BY {group_by}
        ORDER BY count DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("days", "INT64", days)
            ]
        )

        result = self.client.query(query, job_config=job_config).result()
        return [dict(row) for row in result]


# Convenience function for quick registration
def register_experiment(
    name: str,
    experiment_type: str,
    config: Optional[dict] = None,
    tags: Optional[List[str]] = None,
    **kwargs
) -> str:
    """
    Convenience function to quickly register an experiment.

    Args:
        name: Experiment name
        experiment_type: Type of experiment
        config: Configuration dictionary
        tags: List of tags
        **kwargs: Additional fields (train_start, train_end, etc.)

    Returns:
        experiment_id
    """
    registry = ExperimentRegistry()

    exp_config = {
        "name": name,
        "experiment_type": experiment_type,
        "config": config or {},
        "tags": tags or [],
        **kwargs
    }

    return registry.register_experiment(exp_config)
