"""
File: monitoring/processing_gap_detection/utils/gcs_inspector.py

Google Cloud Storage utilities for inspecting scraped data files.
"""

import logging
from datetime import datetime
from typing import Optional, Tuple, List
from google.cloud import storage

logger = logging.getLogger(__name__)


class GCSInspector:
    """Inspect GCS buckets for scraped data files."""
    
    def __init__(self, bucket_name: str):
        """
        Initialize GCS inspector.
        
        Args:
            bucket_name: Name of GCS bucket to inspect
        """
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
    
    def get_latest_file(self, prefix: str) -> Tuple[Optional[str], Optional[datetime]]:
        """
        Find latest JSON file matching prefix pattern.
        
        Args:
            prefix: GCS prefix pattern (e.g., 'nba-com/player-list/2025-10-02/')
        
        Returns:
            Tuple of (file_path, timestamp) or (None, None) if no files found
        """
        try:
            blobs = list(self.bucket.list_blobs(prefix=prefix))
            
            if not blobs:
                logger.info(f"No files found with prefix: {prefix}")
                return None, None
            
            # Filter to JSON files only
            json_blobs = [b for b in blobs if b.name.endswith('.json')]
            
            if not json_blobs:
                logger.warning(f"No JSON files found with prefix: {prefix}")
                return None, None
            
            # Sort by creation time, get latest
            json_blobs.sort(key=lambda b: b.time_created, reverse=True)
            latest_blob = json_blobs[0]
            
            file_path = f"gs://{self.bucket_name}/{latest_blob.name}"
            logger.info(f"Latest file found: {file_path} (created: {latest_blob.time_created})")
            
            return file_path, latest_blob.time_created
            
        except Exception as e:
            logger.error(f"Error listing GCS files with prefix '{prefix}': {e}")
            return None, None
    
    def get_all_files(self, prefix: str) -> List[Tuple[str, datetime]]:
        """
        Get all JSON files matching prefix pattern.
        
        Args:
            prefix: GCS prefix pattern
        
        Returns:
            List of (file_path, timestamp) tuples, sorted by timestamp descending
        """
        try:
            blobs = list(self.bucket.list_blobs(prefix=prefix))
            json_blobs = [b for b in blobs if b.name.endswith('.json')]
            
            files = [
                (f"gs://{self.bucket_name}/{b.name}", b.time_created)
                for b in json_blobs
            ]
            
            # Sort by timestamp, newest first
            files.sort(key=lambda x: x[1], reverse=True)
            
            logger.info(f"Found {len(files)} JSON files with prefix: {prefix}")
            return files
            
        except Exception as e:
            logger.error(f"Error listing GCS files with prefix '{prefix}': {e}")
            return []
    
    def file_exists(self, file_path: str) -> bool:
        """
        Check if specific file exists in GCS.
        
        Args:
            file_path: Full GCS path (gs://bucket/path/to/file.json)
        
        Returns:
            True if file exists, False otherwise
        """
        try:
            # Remove gs://bucket_name/ prefix to get blob name
            if file_path.startswith(f"gs://{self.bucket_name}/"):
                blob_name = file_path[len(f"gs://{self.bucket_name}/"):]
            else:
                logger.error(f"Invalid GCS path format: {file_path}")
                return False
            
            blob = self.bucket.blob(blob_name)
            exists = blob.exists()
            
            logger.debug(f"File exists check: {file_path} = {exists}")
            return exists
            
        except Exception as e:
            logger.error(f"Error checking file existence '{file_path}': {e}")
            return False
    
    def get_file_info(self, file_path: str) -> Optional[dict]:
        """
        Get metadata for a specific file.
        
        Args:
            file_path: Full GCS path
        
        Returns:
            Dictionary with file metadata or None if file doesn't exist
        """
        try:
            if file_path.startswith(f"gs://{self.bucket_name}/"):
                blob_name = file_path[len(f"gs://{self.bucket_name}/"):]
            else:
                logger.error(f"Invalid GCS path format: {file_path}")
                return None
            
            blob = self.bucket.blob(blob_name)
            
            if not blob.exists():
                return None
            
            # Reload to get latest metadata
            blob.reload()
            
            return {
                'name': blob.name,
                'size': blob.size,
                'created': blob.time_created,
                'updated': blob.updated,
                'content_type': blob.content_type,
                'md5_hash': blob.md5_hash
            }
            
        except Exception as e:
            logger.error(f"Error getting file info for '{file_path}': {e}")
            return None
    
    def count_files(self, prefix: str) -> int:
        """
        Count JSON files matching prefix.
        
        Args:
            prefix: GCS prefix pattern
        
        Returns:
            Count of JSON files
        """
        try:
            blobs = list(self.bucket.list_blobs(prefix=prefix))
            json_count = sum(1 for b in blobs if b.name.endswith('.json'))
            
            logger.info(f"Count of JSON files with prefix '{prefix}': {json_count}")
            return json_count
            
        except Exception as e:
            logger.error(f"Error counting files with prefix '{prefix}': {e}")
            return 0


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    
    # Test with nbac_player_list pattern
    inspector = GCSInspector('nba-scraped-data')
    
    # Check latest file for today's date
    from datetime import date
    today = date.today().strftime('%Y-%m-%d')
    prefix = f'nba-com/player-list/{today}/'
    
    file_path, timestamp = inspector.get_latest_file(prefix)
    
    if file_path:
        print(f"✅ Latest file: {file_path}")
        print(f"   Created: {timestamp}")
        
        info = inspector.get_file_info(file_path)
        if info:
            print(f"   Size: {info['size']} bytes")
    else:
        print(f"❌ No files found for {today}")
