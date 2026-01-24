"""
Base Exporter for Phase 6 Publishing

Provides common functionality for exporting BigQuery data to GCS as JSON.
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from google.cloud import bigquery
from google.cloud import storage
from google.api_core.exceptions import ServiceUnavailable, DeadlineExceeded, InternalServerError
from shared.clients.bigquery_pool import get_bigquery_client
from shared.utils.retry_with_jitter import retry_with_jitter

logger = logging.getLogger(__name__)

from shared.config.gcp_config import get_project_id, Buckets
PROJECT_ID = get_project_id()
BUCKET_NAME = Buckets.API
API_VERSION = 'v1'


class BaseExporter(ABC):
    """
    Abstract base class for JSON exporters.

    Subclasses implement generate_json() to produce data,
    then call export() to upload to GCS.
    """

    def __init__(self, project_id: str = PROJECT_ID, bucket_name: str = BUCKET_NAME):
        self.project_id = project_id
        self.bucket_name = bucket_name
        self.bq_client = get_bigquery_client(project_id=project_id)
        self.gcs_client = storage.Client(project=project_id)

    @abstractmethod
    def generate_json(self, **kwargs) -> Dict[str, Any]:
        """Generate JSON content for export. Implemented by subclasses."""
        pass

    def query_to_list(self, query: str, params: Optional[List] = None) -> List[Dict]:
        """
        Execute BigQuery query and return results as list of dicts.

        Args:
            query: SQL query string with @param placeholders
            params: List of bigquery.ScalarQueryParameter objects

        Returns:
            List of dictionaries, one per row
        """
        job_config = None
        if params:
            job_config = bigquery.QueryJobConfig(query_parameters=params)

        try:
            result = self.bq_client.query(query, job_config=job_config).result(timeout=60)
            return [dict(row) for row in result]
        except Exception as e:
            logger.error(f"Query failed: {e}")
            raise

    def upload_to_gcs(
        self,
        json_data: Dict[str, Any],
        path: str,
        cache_control: str = 'public, max-age=300'
    ) -> str:
        """
        Upload JSON data to GCS with cache headers.

        Args:
            json_data: Dictionary to serialize as JSON
            path: Path within bucket (e.g., 'results/2021-11-10.json')
            cache_control: HTTP cache-control header value

        Returns:
            Full GCS path (gs://bucket/v1/path)
        """
        bucket = self.gcs_client.bucket(self.bucket_name)
        full_path = f'{API_VERSION}/{path}'
        blob = bucket.blob(full_path)

        # Serialize with proper handling of dates/decimals
        json_str = json.dumps(
            json_data,
            indent=2,
            default=self._json_serializer,
            ensure_ascii=False
        )

        # Upload with retry for transient GCS errors
        self._upload_blob_with_retry(blob, json_str, cache_control)

        gcs_path = f'gs://{self.bucket_name}/{full_path}'
        logger.info(f"Uploaded {len(json_str)} bytes to {gcs_path}")
        return gcs_path

    @retry_with_jitter(
        max_attempts=3,
        base_delay=1.0,
        max_delay=10.0,
        exceptions=(ServiceUnavailable, DeadlineExceeded, InternalServerError)
    )
    def _upload_blob_with_retry(self, blob, json_str: str, cache_control: str) -> None:
        """Upload blob with retry on transient GCS errors."""
        blob.upload_from_string(
            json_str,
            content_type='application/json'
        )
        blob.cache_control = cache_control
        blob.patch()

    def _json_serializer(self, obj: Any) -> Any:
        """Custom JSON serializer for types not handled by default."""
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        if hasattr(obj, '__float__'):
            return float(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    def get_generated_at(self) -> str:
        """Get current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()
