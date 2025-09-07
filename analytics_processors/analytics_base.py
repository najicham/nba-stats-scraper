"""
File: analytics_processors/analytics_base.py

Base class for analytics processors that handles:
 - Querying raw BigQuery tables
 - Calculating analytics metrics
 - Loading to analytics tables
 - Error handling and quality tracking
 - Matches ProcessorBase patterns
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone, date
from typing import Dict, List, Optional, Any
from google.cloud import bigquery
import pandas as pd
import sentry_sdk

# Configure logging to match processor_base pattern
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger("analytics_base")


class AnalyticsProcessorBase:
    """
    Base class for analytics processors - matches ProcessorBase patterns.
    
    Lifecycle:
      1) Extract data from raw BigQuery tables
      2) Validate extracted data
      3) Transform/calculate analytics
      4) Load to analytics BigQuery tables
      5) Log processing run
    """
    
    # Class-level configs (matching ProcessorBase pattern)
    required_opts: List[str] = ['start_date', 'end_date']
    additional_opts: List[str] = []
    
    # Processing settings
    validate_on_extract: bool = True
    save_on_error: bool = True
    
    # BigQuery settings
    dataset_id: str = "nba_analytics"
    table_name: str = ""  # Child classes must set
    processing_strategy: str = "MERGE_UPDATE"  # Default for analytics
    
    # Time tracking (matching processor pattern)
    time_markers: Dict = {}
    
    def __init__(self):
        """Initialize analytics processor with same pattern as ProcessorBase."""
        self.opts = {}
        self.raw_data = None
        self.validated_data = {}
        self.transformed_data = {}
        self.stats = {}
        
        # Generate run_id like processors
        self.run_id = str(uuid.uuid4())[:8]
        self.stats["run_id"] = self.run_id
        
        # GCP clients - match processor init pattern
        self.project_id = None
        self.bq_client = None
        
    def run(self, opts: Optional[Dict] = None) -> bool:
        """
        Main entry point - matches ProcessorBase.run() pattern.
        Returns True on success, False on failure.
        """
        if opts is None:
            opts = {}
            
        try:
            # Re-init but preserve run_id (matching processor pattern)
            saved_run_id = self.run_id
            self.__init__()
            self.run_id = saved_run_id
            self.stats["run_id"] = saved_run_id
            
            self.mark_time("total")
            self.step_info("start", "Analytics processor run starting", extra={"opts": opts})
            
            # Setup
            self.set_opts(opts)
            self.validate_opts()
            self.set_additional_opts()
            self.validate_additional_opts()
            self.init_clients()
            
            # Extract from raw tables
            self.mark_time("extract")
            self.extract_raw_data()
            extract_seconds = self.get_elapsed_seconds("extract")
            self.stats["extract_time"] = extract_seconds
            self.step_info("extract_complete", f"Data extracted in {extract_seconds:.1f}s")
            
            # Validate
            if self.validate_on_extract:
                self.validate_extracted_data()
            
            # Transform/calculate analytics
            self.mark_time("transform")
            self.calculate_analytics()
            transform_seconds = self.get_elapsed_seconds("transform")
            self.stats["transform_time"] = transform_seconds
            
            # Save to analytics tables
            self.mark_time("save")
            self.save_analytics()
            save_seconds = self.get_elapsed_seconds("save")
            self.stats["save_time"] = save_seconds
            
            # Complete
            total_seconds = self.get_elapsed_seconds("total")
            self.stats["total_runtime"] = total_seconds
            self.step_info("finish", f"Analytics processor completed in {total_seconds:.1f}s")
            
            # Log processing run
            self.log_processing_run(success=True)
            self.post_process()
            return True
            
        except Exception as e:
            logger.error("AnalyticsProcessorBase Error: %s", e, exc_info=True)
            sentry_sdk.capture_exception(e)
            
            # Log failed processing run
            self.log_processing_run(success=False, error=str(e))
            
            if self.save_on_error:
                self._save_partial_data(e)
                
            self.report_error(e)
            return False
    
    def set_opts(self, opts: Dict) -> None:
        """Set options - matches processor pattern."""
        self.opts = opts
        self.opts["run_id"] = self.run_id
        
    def validate_opts(self) -> None:
        """Validate required options - matches processor pattern."""
        for required_opt in self.required_opts:
            if required_opt not in self.opts:
                raise ValueError(f"Missing required option [{required_opt}]")
    
    def set_additional_opts(self) -> None:
        """Add additional options - child classes override and call super()."""
        # Add timestamp for tracking
        if "timestamp" not in self.opts:
            self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    def validate_additional_opts(self) -> None:
        """Validate additional options - child classes override."""
        pass
    
    def init_clients(self) -> None:
        """Initialize GCP clients."""
        self.project_id = self.opts.get("project_id", "nba-props-platform")
        self.bq_client = bigquery.Client(project=self.project_id)
    
    # Abstract methods for child classes (matching processor pattern)
    def extract_raw_data(self) -> None:
        """Extract data from raw BigQuery tables - child classes must implement."""
        raise NotImplementedError("Child classes must implement extract_raw_data()")
    
    def validate_extracted_data(self) -> None:
        """Validate extracted data - child classes override."""
        if self.raw_data is None or (hasattr(self.raw_data, 'empty') and self.raw_data.empty):
            raise ValueError("No data extracted")
    
    def calculate_analytics(self) -> None:
        """Calculate analytics metrics - child classes must implement."""
        raise NotImplementedError("Child classes must implement calculate_analytics()")
    
    def save_analytics(self) -> None:
        """Save to analytics BigQuery table - base implementation provided."""
        if not self.transformed_data:
            logger.warning("No transformed data to save")
            return
            
        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
        
        # Handle different data types
        if isinstance(self.transformed_data, list):
            rows = self.transformed_data
        elif isinstance(self.transformed_data, dict):
            rows = [self.transformed_data]
        else:
            raise ValueError(f"Unexpected data type: {type(self.transformed_data)}")
        
        if not rows:
            logger.warning("No rows to insert")
            return
        
        # Apply processing strategy
        if self.processing_strategy == 'MERGE_UPDATE':
            self._delete_existing_data(rows)
            
        # Insert to BigQuery
        logger.info(f"Inserting {len(rows)} rows to {table_id}")
        errors = self.bq_client.insert_rows_json(table_id, rows)
        
        if errors:
            raise Exception(f"BigQuery insert errors: {errors}")
            
        self.stats["rows_processed"] = len(rows)
        logger.info(f"Successfully inserted {len(rows)} rows")
    
    def _delete_existing_data(self, rows: List[Dict]) -> None:
        """Delete existing data for MERGE_UPDATE strategy."""
        if not rows:
            return
            
        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
        
        # Get date range from rows for deletion
        start_date = self.opts.get('start_date')
        end_date = self.opts.get('end_date')
        
        if start_date and end_date:
            delete_query = f"""
            DELETE FROM `{table_id}`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            """
            self.bq_client.query(delete_query).result()
            logger.info(f"Deleted existing data for date range {start_date} to {end_date}")
    
    def log_processing_run(self, success: bool, error: str = None) -> None:
        """Log processing run to monitoring table."""
        run_record = {
            'processor_name': self.__class__.__name__,
            'run_id': self.run_id,
            'run_date': datetime.now(timezone.utc).isoformat(),
            'success': success,
            'date_range_start': self.opts.get('start_date'),
            'date_range_end': self.opts.get('end_date'),
            'records_processed': self.stats.get('rows_processed', 0),
            'duration_seconds': self.stats.get('total_runtime', 0),
            'errors_json': json.dumps([error] if error else []),
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        
        try:
            table_id = f"{self.project_id}.nba_processing.analytics_processor_runs"
            self.bq_client.insert_rows_json(table_id, [run_record])
        except Exception as e:
            logger.warning(f"Failed to log processing run: {e}")
    
    def log_quality_issue(self, issue_type: str, severity: str, identifier: str, details: Dict):
        """Log data quality issues for review."""
        issue_record = {
            'issue_id': str(uuid.uuid4()),
            'processor_name': self.__class__.__name__,
            'run_id': self.run_id,
            'issue_type': issue_type,
            'severity': severity,
            'identifier': identifier,
            'issue_description': json.dumps(details),
            'resolved': False,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        
        try:
            table_id = f"{self.project_id}.nba_processing.analytics_data_issues"
            self.bq_client.insert_rows_json(table_id, [issue_record])
        except Exception as e:
            logger.warning(f"Failed to log quality issue: {e}")
    
    # Time tracking methods (copied exactly from ProcessorBase)
    def mark_time(self, label: str) -> str:
        """Mark time - matches processor implementation."""
        now = datetime.now()
        if label not in self.time_markers:
            self.time_markers[label] = {
                "start": now,
                "last": now
            }
            return "0.0"
        else:
            last_time = self.time_markers[label]["last"]
            delta = (now - last_time).total_seconds()
            self.time_markers[label]["last"] = now
            return f"{delta:.1f}"
    
    def get_elapsed_seconds(self, label: str) -> float:
        """Get elapsed seconds - matches processor implementation."""
        if label not in self.time_markers:
            return 0.0
        start_time = self.time_markers[label]["start"]
        now_time = datetime.now()
        return (now_time - start_time).total_seconds()
    
    # Logging methods (matching processor_base exactly)
    def step_info(self, step_name: str, message: str, extra: Optional[Dict] = None) -> None:
        """Log structured step - matches processor pattern."""
        if extra is None:
            extra = {}
        extra.update({
            "run_id": self.run_id,
            "step": step_name,
        })
        logger.info(f"ANALYTICS_STEP {message}", extra=extra)
    
    def post_process(self) -> None:
        """Post-processing - matches processor's post_process()."""
        summary = {
            "run_id": self.run_id,
            "processor": self.__class__.__name__,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "total_runtime": self.stats.get("total_runtime", 0),
        }
        
        # Merge analytics stats
        analytics_stats = self.get_analytics_stats()
        if isinstance(analytics_stats, dict):
            summary.update(analytics_stats)
            
        logger.info("ANALYTICS_STATS %s", json.dumps(summary))
    
    def get_analytics_stats(self) -> Dict:
        """Get analytics stats - child classes override."""
        return {}
    
    # Error handling (matching processor pattern)
    def report_error(self, exc: Exception) -> None:
        """Report error to Sentry."""
        sentry_sdk.capture_exception(exc)
    
    def _save_partial_data(self, exc: Exception) -> None:
        """Save partial data on error for debugging."""
        try:
            debug_file = f"/tmp/analytics_debug_{self.run_id}.json"
            debug_data = {
                "error": str(exc),
                "opts": self.opts,
                "raw_data_sample": str(self.raw_data)[:1000] if self.raw_data is not None else None,
                "transformed_data_sample": str(self.transformed_data)[:1000] if self.transformed_data else None,
            }
            with open(debug_file, "w") as f:
                json.dump(debug_data, f, indent=2)
            logger.info(f"Saved debug data to {debug_file}")
        except Exception as save_exc:
            logger.warning(f"Failed to save debug data: {save_exc}")