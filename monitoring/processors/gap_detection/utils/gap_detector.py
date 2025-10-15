"""
File: monitoring/processing_gap_detection/utils/gap_detector.py

Processing Gap Detector

Core logic for detecting unprocessed GCS files by comparing against BigQuery.
Integrates with existing notification_system.py for alerts.

CRITICAL FIX (Oct 4, 2025): Path normalization to match BigQuery storage format
- BigQuery stores: "nba-com/player-list/2025-10-01/file.json"
- GCS returns: "gs://nba-scraped-data/nba-com/player-list/2025-10-01/file.json"
- Solution: Strip gs://bucket/ prefix before querying BigQuery
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from google.cloud import bigquery

from config.processor_config import ProcessorConfig, get_enabled_processors
from utils.gcs_inspector import GCSInspector

# Import notification system from shared utils
import sys
import os
# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import notification_system directly (bypasses __init__.py)
import importlib.util
spec = importlib.util.spec_from_file_location(
    "notification_system",
    os.path.join(project_root, "shared/utils/notification_system.py")
)
notification_system = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notification_system)

notify_error = notification_system.notify_error
notify_warning = notification_system.notify_warning
notify_info = notification_system.notify_info

logger = logging.getLogger(__name__)


class ProcessingGapDetector:
    """Detect gaps between GCS files and BigQuery processing."""
    
    def __init__(self):
        """Initialize detector with clients."""
        self.bq_client = bigquery.Client(project='nba-props-platform')
        self.gcs_inspectors = {}  # Cache inspectors by bucket
    
    def _get_gcs_inspector(self, bucket_name: str) -> GCSInspector:
        """Get or create GCS inspector for bucket."""
        if bucket_name not in self.gcs_inspectors:
            self.gcs_inspectors[bucket_name] = GCSInspector(bucket_name)
        return self.gcs_inspectors[bucket_name]
    
    def check_all_processors(
        self, 
        check_date: date = None, 
        processors: List[str] = None
    ) -> Dict:
        """
        Check all enabled processors for gaps.
        
        Args:
            check_date: Date to check (defaults to today)
            processors: List of specific processors to check (defaults to all enabled)
            
        Returns:
            Dict with results for each processor
        """
        if check_date is None:
            check_date = date.today()
        
        results = {
            'check_date': check_date.isoformat(),
            'check_timestamp': datetime.utcnow().isoformat(),
            'total_processors_checked': 0,
            'gaps_found': 0,
            'processors': {}
        }
        
        # Get enabled processors
        enabled_processors = get_enabled_processors()
        
        for processor_name, processor_config in enabled_processors.items():
            # Skip if filtering and not in list
            if processors and processor_name not in processors:
                continue
            
            try:
                logger.info(f"Checking processor: {processor_name}")
                gap_result = self.check_processor(processor_config, check_date)
                results['processors'][processor_name] = gap_result
                results['total_processors_checked'] += 1
                
                if gap_result['gap_detected']:
                    results['gaps_found'] += 1
                    
            except Exception as e:
                logger.error(f"Error checking {processor_name}: {e}", exc_info=True)
                results['processors'][processor_name] = {
                    'error': str(e),
                    'gap_detected': None
                }
        
        # Send summary notification if gaps found
        if results['gaps_found'] > 0:
            self._send_summary_alert(results)
        else:
            logger.info(f"✅ No processing gaps detected for {check_date}")
            notify_info(
                title=f"Processing Gap Check Complete: {check_date}",
                message=f"All {results['total_processors_checked']} processor(s) validated successfully",
                details={'check_date': check_date.isoformat()}
            )
        
        return results
    
    def check_processor(
        self, 
        processor_config: ProcessorConfig, 
        check_date: date
    ) -> Dict:
        """
        Check single processor for gaps.
        
        Args:
            processor_config: Processor configuration
            check_date: Date to check
        
        Returns:
            Dict with gap detection results
        """
        date_str = check_date.strftime('%Y-%m-%d')
        
        # 1. Find latest GCS file for date
        inspector = self._get_gcs_inspector(processor_config.gcs_bucket)
        gcs_prefix = processor_config.get_gcs_pattern(date_str)
        
        gcs_file, gcs_timestamp = inspector.get_latest_file(gcs_prefix)
        
        # 2. Check if file was processed in BigQuery
        if gcs_file:
            processed = self._check_file_processed(
                table=processor_config.bigquery_table,
                file_path=gcs_file,
                source_field=processor_config.source_file_field
            )
            
            # 3. Check record count if expected range provided
            record_count = None
            record_count_valid = None
            if processed:
                record_count = self._get_record_count(
                    table=processor_config.bigquery_table,
                    file_path=gcs_file,
                    source_field=processor_config.source_file_field
                )
                
                expected = processor_config.expected_record_count
                if expected:
                    record_count_valid = (
                        expected['min'] <= record_count <= expected['max']
                    )
        else:
            processed = None
            record_count = None
            record_count_valid = None
        
        # 4. Check time-based tolerance
        tolerance_exceeded = False
        hours_since_scrape = None
        
        if gcs_file and not processed:
            hours_since_scrape = (datetime.now(gcs_timestamp.tzinfo) - gcs_timestamp).total_seconds() / 3600
            tolerance_exceeded = hours_since_scrape > processor_config.tolerance_hours
        
        # 5. Determine if gap exists
        gap_detected = gcs_file is not None and not processed and tolerance_exceeded
        
        result = {
            'processor_name': processor_config.name,
            'display_name': processor_config.display_name,
            'check_date': date_str,
            'gcs_file_found': gcs_file is not None,
            'gcs_file_path': gcs_file,
            'gcs_timestamp': gcs_timestamp.isoformat() if gcs_timestamp else None,
            'hours_since_scrape': round(hours_since_scrape, 2) if hours_since_scrape else None,
            'processed_in_bigquery': processed,
            'record_count': record_count,
            'record_count_valid': record_count_valid,
            'tolerance_hours': processor_config.tolerance_hours,
            'tolerance_exceeded': tolerance_exceeded,
            'gap_detected': gap_detected,
            'priority': processor_config.priority,
            'revenue_impact': processor_config.revenue_impact
        }
        
        # Send alert if gap detected
        if gap_detected:
            self._send_gap_alert(processor_config, result)
        
        return result
    
    def _normalize_file_path(self, file_path: str) -> str:
        """
        Normalize GCS file path to match BigQuery storage format.
        
        BigQuery stores paths without gs://bucket/ prefix:
          "nba-com/player-list/2025-10-01/file.json"
        
        GCS inspector returns full paths:
          "gs://nba-scraped-data/nba-com/player-list/2025-10-01/file.json"
        
        Args:
            file_path: File path (may include gs://bucket/ prefix)
            
        Returns:
            Normalized path without bucket prefix
        """
        if file_path.startswith('gs://'):
            # Extract path after bucket name
            path_parts = file_path.replace('gs://', '').split('/', 1)
            if len(path_parts) > 1:
                return path_parts[1]
        return file_path
    
    def _check_file_processed(
        self, 
        table: str, 
        file_path: str, 
        source_field: str = 'source_file_path'
    ) -> bool:
        """
        Check if GCS file was processed into BigQuery.
        
        Args:
            table: Fully qualified table name
            file_path: GCS file path (may include gs://bucket/ prefix)
            source_field: Field name storing source path
        
        Returns:
            True if file found in table, False otherwise
        """
        # Normalize path to match BigQuery storage format
        file_path_normalized = self._normalize_file_path(file_path)
        
        query = f"""
        SELECT COUNT(*) as count
        FROM `{table}`
        WHERE {source_field} = @file_path
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("file_path", "STRING", file_path_normalized)
            ]
        )
        
        try:
            result = self.bq_client.query(query, job_config=job_config).result()
            count = list(result)[0]['count']
            logger.info(f"File processing check: {file_path_normalized} found {count} records")
            return count > 0
        except Exception as e:
            logger.error(f"Error checking BigQuery for file '{file_path_normalized}': {e}")
            return False
    
    def _get_record_count(
        self,
        table: str,
        file_path: str,
        source_field: str = 'source_file_path'
    ) -> int:
        """Get count of records for a specific source file."""
        # Normalize path to match BigQuery storage format
        file_path_normalized = self._normalize_file_path(file_path)
        
        query = f"""
        SELECT COUNT(*) as count
        FROM `{table}`
        WHERE {source_field} = @file_path
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("file_path", "STRING", file_path_normalized)
            ]
        )
        
        try:
            result = self.bq_client.query(query, job_config=job_config).result()
            count = list(result)[0]['count']
            return count
        except Exception as e:
            logger.error(f"Error getting record count: {e}")
            return 0
    
    def _send_gap_alert(self, processor_config: ProcessorConfig, result: Dict):
        """Send notification for detected gap."""
        # Build retry pub/sub message structure for logging
        retry_message = {
            'topic': processor_config.pubsub_topic,
            'attributes': processor_config.get_pubsub_attributes(
                file_path=result['gcs_file_path'],
                date_str=result['check_date']
            ),
            'data': {
                'file_path': result['gcs_file_path'],
                'date': result['check_date']
            }
        }
        
        details = {
            'processor': processor_config.name,
            'gcs_file': result['gcs_file_path'],
            'gcs_timestamp': result['gcs_timestamp'],
            'hours_since_scrape': result['hours_since_scrape'],
            'table': processor_config.bigquery_table,
            'tolerance_hours': processor_config.tolerance_hours,
            'priority': processor_config.priority,
            'revenue_impact': 'YES' if processor_config.revenue_impact else 'NO',
            'retry_pubsub_topic': retry_message['topic'],
            'retry_pubsub_attributes': str(retry_message['attributes']),
            'action_needed': 'Investigate processor logs and consider retry'
        }
        
        # Log retry message for Phase 2 implementation
        logger.warning(
            f"RETRY INFO for {processor_config.name}: "
            f"Pub/Sub topic={retry_message['topic']}, "
            f"attributes={retry_message['attributes']}"
        )
        
        try:
            notify_error(
                title=f"Processing Gap Detected: {processor_config.display_name}",
                message=f"GCS file exists but not processed in BigQuery after {result['hours_since_scrape']:.1f} hours",
                details=details,
                processor_name=processor_config.display_name
            )
        except Exception as e:
            logger.error(f"Failed to send gap alert: {e}")
    
    def _send_summary_alert(self, results: Dict):
        """Send summary notification when gaps found."""
        gap_processors = [
            {
                'name': name,
                'display_name': result.get('display_name', name),
                'priority': result.get('priority', 'unknown'),
                'revenue_impact': result.get('revenue_impact', False)
            }
            for name, result in results['processors'].items()
            if result.get('gap_detected', False)
        ]
        
        # Prioritize by revenue impact and priority
        high_priority = [p for p in gap_processors if p['revenue_impact']]
        
        try:
            notify_warning(
                title=f"Processing Gaps Found: {results['gaps_found']} Processor(s)",
                message=f"Found unprocessed GCS files for {results['check_date']}",
                details={
                    'check_date': results['check_date'],
                    'gaps_found': results['gaps_found'],
                    'processors_checked': results['total_processors_checked'],
                    'high_priority_gaps': len(high_priority),
                    'affected_processors': [p['display_name'] for p in gap_processors],
                    'action_needed': 'Review individual processor alerts for retry information'
                }
            )
        except Exception as e:
            logger.error(f"Failed to send summary alert: {e}")


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    from datetime import date
    
    detector = ProcessingGapDetector()
    
    # Test with today's date
    today = date.today()
    print(f"\nChecking for processing gaps on {today}...\n")
    
    results = detector.check_all_processors(check_date=today)
    
    print("\n" + "="*60)
    print("PROCESSING GAP CHECK RESULTS")
    print("="*60)
    print(f"Date: {results['check_date']}")
    print(f"Processors checked: {results['total_processors_checked']}")
    print(f"Gaps found: {results['gaps_found']}")
    print("="*60)
    
    for proc_name, proc_result in results['processors'].items():
        status = "❌ GAP" if proc_result.get('gap_detected') else "✅ OK"
        print(f"{status} {proc_name}: {proc_result}")