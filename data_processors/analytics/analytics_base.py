"""
File: analytics_processors/analytics_base.py

Base class for analytics processors that handles:
 - Querying raw BigQuery tables
 - Calculating analytics metrics
 - Loading to analytics tables
 - Error handling and quality tracking
 - Multi-channel notifications (Email + Slack)
 - Matches ProcessorBase patterns
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery
import sentry_sdk

# Import notification system
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

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
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
    def run(self, opts: Optional[Dict] = None) -> bool:
        """
        Main entry point - matches ProcessorBase.run() pattern.
        Returns True on success, False on failure.
        Enhanced with notifications.
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
            
            # Send notification for analytics processor failure
            try:
                notify_error(
                    title=f"Analytics Processor Failed: {self.__class__.__name__}",
                    message=f"Analytics calculation failed: {str(e)}",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'error_type': type(e).__name__,
                        'step': self._get_current_step(),
                        'date_range': f"{opts.get('start_date')} to {opts.get('end_date')}",
                        'table': self.table_name,
                        'stats': self.stats
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            # Log failed processing run
            self.log_processing_run(success=False, error=str(e))
            
            if self.save_on_error:
                self._save_partial_data(e)
                
            self.report_error(e)
            return False
    
    def _get_current_step(self) -> str:
        """Helper to determine current processing step for error context."""
        if not self.bq_client:
            return "initialization"
        elif not self.raw_data:
            return "extract"
        elif not self.transformed_data:
            return "calculate"
        else:
            return "save"
    
    def set_opts(self, opts: Dict) -> None:
        """Set options - matches processor pattern."""
        self.opts = opts
        self.opts["run_id"] = self.run_id
        
    def validate_opts(self) -> None:
        """Validate required options - matches processor pattern."""
        for required_opt in self.required_opts:
            if required_opt not in self.opts:
                error_msg = f"Missing required option [{required_opt}]"
                
                try:
                    notify_error(
                        title=f"Analytics Processor Configuration Error: {self.__class__.__name__}",
                        message=f"Missing required option: {required_opt}",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'missing_option': required_opt,
                            'required_opts': self.required_opts,
                            'provided_opts': list(self.opts.keys())
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                raise ValueError(error_msg)
    
    def set_additional_opts(self) -> None:
        """Add additional options - child classes override and call super()."""
        # Add timestamp for tracking
        if "timestamp" not in self.opts:
            self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    def validate_additional_opts(self) -> None:
        """Validate additional options - child classes override."""
        pass
    
    def init_clients(self) -> None:
        """Initialize GCP clients with error notification."""
        try:
            self.project_id = self.opts.get("project_id", "nba-props-platform")
            self.bq_client = bigquery.Client(project=self.project_id)
        except Exception as e:
            logger.error(f"Failed to initialize BigQuery client: {e}")
            try:
                notify_error(
                    title=f"Analytics Processor Client Initialization Failed: {self.__class__.__name__}",
                    message="Unable to initialize BigQuery client",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'project_id': self.opts.get('project_id', 'nba-props-platform'),
                        'error_type': type(e).__name__,
                        'error': str(e)
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
    
    # Abstract methods for child classes (matching processor pattern)
    def extract_raw_data(self) -> None:
        """Extract data from raw BigQuery tables - child classes must implement."""
        raise NotImplementedError("Child classes must implement extract_raw_data()")
    
    def validate_extracted_data(self) -> None:
        """Validate extracted data - child classes override."""
        if self.raw_data is None or (hasattr(self.raw_data, 'empty') and self.raw_data.empty):
            try:
                notify_warning(
                    title=f"Analytics Processor No Data Extracted: {self.__class__.__name__}",
                    message="No data extracted from raw tables",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'date_range': f"{self.opts.get('start_date')} to {self.opts.get('end_date')}"
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise ValueError("No data extracted")
    
    def calculate_analytics(self) -> None:
        """Calculate analytics metrics - child classes must implement."""
        raise NotImplementedError("Child classes must implement calculate_analytics()")
    
    def save_analytics(self) -> None:
        """Save to analytics BigQuery table - base implementation provided with notifications."""
        if not self.transformed_data:
            logger.warning("No transformed data to save")
            try:
                notify_warning(
                    title=f"Analytics Processor No Data to Save: {self.__class__.__name__}",
                    message="No analytics data calculated to save",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'raw_data_exists': self.raw_data is not None,
                        'date_range': f"{self.opts.get('start_date')} to {self.opts.get('end_date')}"
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return
            
        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
        
        # Handle different data types
        if isinstance(self.transformed_data, list):
            rows = self.transformed_data
        elif isinstance(self.transformed_data, dict):
            rows = [self.transformed_data]
        else:
            error_msg = f"Unexpected data type: {type(self.transformed_data)}"
            try:
                notify_error(
                    title=f"Analytics Processor Data Type Error: {self.__class__.__name__}",
                    message=error_msg,
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'data_type': str(type(self.transformed_data)),
                        'expected_types': ['list', 'dict']
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise ValueError(error_msg)
        
        if not rows:
            logger.warning("No rows to insert")
            try:
                notify_warning(
                    title=f"Analytics Processor Empty Dataset: {self.__class__.__name__}",
                    message="No rows to insert after analytics calculation",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'raw_data_size': len(str(self.raw_data)) if self.raw_data is not None else 0
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return
        
        # Apply processing strategy
        if self.processing_strategy == 'MERGE_UPDATE':
            try:
                self._delete_existing_data(rows)
            except Exception as e:
                logger.error(f"Failed to delete existing data: {e}")
                try:
                    notify_error(
                        title=f"Analytics Processor Delete Failed: {self.__class__.__name__}",
                        message=f"Failed to delete existing data for MERGE_UPDATE: {str(e)}",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'table': table_id,
                            'strategy': self.processing_strategy,
                            'date_range': f"{self.opts.get('start_date')} to {self.opts.get('end_date')}",
                            'error_type': type(e).__name__,
                            'error': str(e)
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise
            
        # Insert to BigQuery
        logger.info(f"Inserting {len(rows)} rows to {table_id}")
        
        try:
            errors = self.bq_client.insert_rows_json(table_id, rows)
            
            if errors:
                error_msg = f"BigQuery insert errors: {errors}"
                try:
                    notify_error(
                        title=f"Analytics Processor BigQuery Insert Failed: {self.__class__.__name__}",
                        message=f"Failed to insert {len(rows)} analytics rows",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'table': table_id,
                            'rows_attempted': len(rows),
                            'errors': errors[:5] if len(errors) > 5 else errors,
                            'error_count': len(errors),
                            'date_range': f"{self.opts.get('start_date')} to {self.opts.get('end_date')}"
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise Exception(error_msg)
                
        except Exception as e:
            # Catch any other BigQuery errors
            if "BigQuery insert errors:" not in str(e):
                try:
                    notify_error(
                        title=f"Analytics Processor BigQuery Error: {self.__class__.__name__}",
                        message=f"BigQuery operation failed: {str(e)}",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'table': table_id,
                            'rows_attempted': len(rows),
                            'error_type': type(e).__name__,
                            'error': str(e)
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            raise
            
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
        """
        Log data quality issues for review.
        Enhanced to send notifications for CRITICAL and HIGH severity issues.
        """
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
            
            # Send notification for high-severity quality issues
            if severity in ['CRITICAL', 'HIGH']:
                try:
                    notify_func = notify_error if severity == 'CRITICAL' else notify_warning
                    notify_func(
                        title=f"Analytics Data Quality Issue: {self.__class__.__name__}",
                        message=f"{severity} severity {issue_type} detected for {identifier}",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'issue_type': issue_type,
                            'severity': severity,
                            'identifier': identifier,
                            'issue_details': details,
                            'table': self.table_name
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                    
        except Exception as e:
            logger.warning(f"Failed to log quality issue: {e}")
            # Also try to notify on logging failure for critical issues
            if severity == 'CRITICAL':
                try:
                    notify_error(
                        title=f"Analytics Quality Issue Logging Failed: {self.__class__.__name__}",
                        message=f"Failed to log CRITICAL quality issue: {str(e)}",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'issue_type': issue_type,
                            'severity': severity,
                            'identifier': identifier,
                            'logging_error': str(e)
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
    
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