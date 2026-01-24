# shared/utils/storage_client.py
"""
Cloud Storage client utilities for NBA platform
"""

import json
import gzip
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import io

from google.cloud import storage
from google.api_core import exceptions

logger = logging.getLogger(__name__)


class StorageClient:
    """Centralized Cloud Storage operations for NBA platform"""
    
    def __init__(self, project_id: str):
        self.client = storage.Client(project=project_id)
        self.project_id = project_id
    
    def upload_json(self, bucket_name: str, blob_name: str, 
                   data: Dict[str, Any], compress: bool = True) -> bool:
        """
        Upload JSON data to Cloud Storage
        
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
            
            if compress and len(json_str) > 1024:  # Compress if >1KB
                # Compress the JSON string
                json_bytes = json_str.encode('utf-8')
                compressed_data = gzip.compress(json_bytes)
                blob.upload_from_string(compressed_data, content_type='application/gzip')
                logger.info(f"Uploaded compressed JSON to gs://{bucket_name}/{blob_name}")
            else:
                blob.upload_from_string(json_str, content_type='application/json')
                logger.info(f"Uploaded JSON to gs://{bucket_name}/{blob_name}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to upload to gs://{bucket_name}/{blob_name}: {e}", exc_info=True)
            return False
    
    def download_json(self, bucket_name: str, blob_name: str) -> Optional[Dict[str, Any]]:
        """
        Download and parse JSON from Cloud Storage
        
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
            
            content = blob.download_as_bytes()
            
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
        """Upload raw bytes to Cloud Storage"""
        try:
            bucket = self.client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            blob.upload_from_string(data, content_type=content_type)
            
            logger.info(f"Uploaded {len(data)} bytes to gs://{bucket_name}/{blob_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to upload bytes to gs://{bucket_name}/{blob_name}: {e}", exc_info=True)
            return False
    
    def list_objects(self, bucket_name: str, prefix: str = "", 
                    max_results: int = 1000) -> List[str]:
        """
        List objects in bucket with optional prefix filter
        
        Args:
            bucket_name: GCS bucket name
            prefix: Prefix filter for object names
            max_results: Maximum number of results to return
            
        Returns:
            List of object names
        """
        try:
            bucket = self.client.bucket(bucket_name)
            blobs = bucket.list_blobs(prefix=prefix, max_results=max_results)
            
            object_names = [blob.name for blob in blobs]
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
            logger.error(f"Failed to delete gs://{bucket_name}/{blob_name}: {e}", exc_info=True)
            return False
    
    def object_exists(self, bucket_name: str, blob_name: str) -> bool:
        """Check if object exists in Cloud Storage"""
        try:
            bucket = self.client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            return blob.exists()
        except Exception as e:
            logger.error(f"Error checking if gs://{bucket_name}/{blob_name} exists: {e}", exc_info=True)
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
