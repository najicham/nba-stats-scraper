# shared/utils/storage_client.py
"""
Cloud Storage client utilities for NBA platform

Provides retry-enabled GCS operations with exponential backoff for transient errors.
"""

import json
import gzip
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import io

from google.cloud import storage
from google.api_core import exceptions, retry

logger = logging.getLogger(__name__)


def _is_retryable_gcs_error(exc):
    """
    Predicate to identify retryable GCS errors.

    Retries on:
    - 429 TooManyRequests (rate limiting)
    - 500 InternalServerError
    - 503 ServiceUnavailable
    - 504 DeadlineExceeded
    """
    if isinstance(exc, exceptions.TooManyRequests):
        logger.warning(f"GCS rate limited (429), will retry: {exc}")
        return True
    if isinstance(exc, exceptions.InternalServerError):
        logger.warning(f"GCS internal error (500), will retry: {exc}")
        return True
    if isinstance(exc, exceptions.ServiceUnavailable):
        logger.warning(f"GCS service unavailable (503), will retry: {exc}")
        return True
    if isinstance(exc, exceptions.DeadlineExceeded):
        logger.warning(f"GCS timeout (504), will retry: {exc}")
        return True
    return False


# Retry configuration for GCS operations
# - Initial delay: 1 second
# - Maximum delay: 60 seconds
# - Multiplier: 2.0 (exponential backoff)
# - Total deadline: 300 seconds (5 minutes)
GCS_RETRY = retry.Retry(
    predicate=_is_retryable_gcs_error,
    initial=1.0,
    maximum=60.0,
    multiplier=2.0,
    deadline=300.0,
)


class StorageClient:
    """Centralized Cloud Storage operations for NBA platform"""
    
    def __init__(self, project_id: str):
        self.client = storage.Client(project=project_id)
        self.project_id = project_id
    
    def upload_json(self, bucket_name: str, blob_name: str,
                   data: Dict[str, Any], compress: bool = True) -> bool:
        """
        Upload JSON data to Cloud Storage with retry on transient errors.

        Args:
            bucket_name: GCS bucket name
            blob_name: Object path in bucket
            data: Dictionary to upload as JSON
            compress: Whether to gzip compress the data

        Returns:
            True if successful
        """
        try:
            bucket = self.client.bucket(bucket_name)
            blob = bucket.blob(blob_name)

            json_str = json.dumps(data, ensure_ascii=False, indent=2)

            @GCS_RETRY
            def _upload():
                if compress and len(json_str) > 1024:  # Compress if >1KB
                    json_bytes = json_str.encode('utf-8')
                    compressed_data = gzip.compress(json_bytes)
                    blob.upload_from_string(compressed_data, content_type='application/gzip')
                else:
                    blob.upload_from_string(json_str, content_type='application/json')

            _upload()

            if compress and len(json_str) > 1024:
                logger.info(f"Uploaded compressed JSON to gs://{bucket_name}/{blob_name}")
            else:
                logger.info(f"Uploaded JSON to gs://{bucket_name}/{blob_name}")

            return True

        except Exception as e:
            logger.error(f"Failed to upload to gs://{bucket_name}/{blob_name}: {e}", exc_info=True)
            return False
    
    def download_json(self, bucket_name: str, blob_name: str) -> Optional[Dict[str, Any]]:
        """
        Download and parse JSON from Cloud Storage with retry on transient errors.

        Args:
            bucket_name: GCS bucket name
            blob_name: Object path in bucket

        Returns:
            Parsed JSON data or None if failed
        """
        try:
            bucket = self.client.bucket(bucket_name)
            blob = bucket.blob(blob_name)

            if not blob.exists():
                logger.warning(f"Object gs://{bucket_name}/{blob_name} does not exist")
                return None

            @GCS_RETRY
            def _download():
                return blob.download_as_bytes()

            content = _download()

            # Try to decompress if it's gzipped
            try:
                if blob.content_type == 'application/gzip' or blob_name.endswith('.gz'):
                    content = gzip.decompress(content)
            except gzip.BadGzipFile:
                pass  # Not gzipped, use as-is

            json_str = content.decode('utf-8')
            data = json.loads(json_str)

            logger.info(f"Downloaded JSON from gs://{bucket_name}/{blob_name}")
            return data

        except Exception as e:
            logger.error(f"Failed to download from gs://{bucket_name}/{blob_name}: {e}", exc_info=True)
            return None
    
    def upload_raw_bytes(self, bucket_name: str, blob_name: str,
                        data: bytes, content_type: str = 'application/octet-stream') -> bool:
        """Upload raw bytes to Cloud Storage with retry on transient errors."""
        try:
            bucket = self.client.bucket(bucket_name)
            blob = bucket.blob(blob_name)

            @GCS_RETRY
            def _upload():
                blob.upload_from_string(data, content_type=content_type)

            _upload()

            logger.info(f"Uploaded {len(data)} bytes to gs://{bucket_name}/{blob_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to upload bytes to gs://{bucket_name}/{blob_name}: {e}", exc_info=True)
            return False
    
    def list_objects(self, bucket_name: str, prefix: str = "",
                    max_results: int = 1000) -> List[str]:
        """
        List objects in bucket with optional prefix filter.

        Args:
            bucket_name: GCS bucket name
            prefix: Prefix filter for object names
            max_results: Maximum number of results to return

        Returns:
            List of object names
        """
        try:
            bucket = self.client.bucket(bucket_name)

            @GCS_RETRY
            def _list():
                blobs = bucket.list_blobs(prefix=prefix, max_results=max_results)
                return [blob.name for blob in blobs]

            object_names = _list()
            logger.info(f"Found {len(object_names)} objects in gs://{bucket_name} with prefix '{prefix}'")
            return object_names

        except Exception as e:
            logger.error(f"Failed to list objects in gs://{bucket_name}: {e}", exc_info=True)
            return []
    
    def delete_object(self, bucket_name: str, blob_name: str) -> bool:
        """Delete object from Cloud Storage"""
        try:
            bucket = self.client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            blob.delete()
            
            logger.info(f"Deleted gs://{bucket_name}/{blob_name}")
            return True
            
        except exceptions.NotFound:
            logger.warning(f"Object gs://{bucket_name}/{blob_name} not found")
            return True  # Consider this success
        except Exception as e:
            logger.error(f"Failed to delete gs://{bucket_name}/{blob_name}: {e}")
            return False
    
    def object_exists(self, bucket_name: str, blob_name: str) -> bool:
        """Check if object exists in Cloud Storage"""
        try:
            bucket = self.client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            return blob.exists()
        except Exception as e:
            logger.error(f"Error checking if gs://{bucket_name}/{blob_name} exists: {e}")
            return False
    
    def generate_storage_path(self, service: str, component: str, 
                            run_id: str, timestamp: Optional[datetime] = None) -> str:
        """
        Generate standardized storage path for NBA platform
        
        Args:
            service: Service name (scrapers, processors, reportgen)
            component: Component name (odds_api_events, etc.)
            run_id: Unique run identifier
            timestamp: Optional timestamp (defaults to now)
            
        Returns:
            Standardized path like: scrapers/odds_api_events/2025/01/15/run_id.json
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        date_path = timestamp.strftime('%Y/%m/%d')
        return f"{service}/{component}/{date_path}/{run_id}.json"
