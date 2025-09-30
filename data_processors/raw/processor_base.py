"""
processors/processor_base.py

Base class for all data processors that handles:
 - Loading data from GCS
 - Validating and transforming data
 - Loading to BigQuery
 - Error handling and logging
 - Multi-channel notifications (Email + Slack)
 - Matches ScraperBase patterns
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from google.cloud import bigquery
from google.cloud import storage
import sentry_sdk

# Import notification system
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Configure logging to match scraper_base pattern
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger("processor_base")


class ProcessorBase:
    """
    Base class for data processors - matches ScraperBase patterns.
    
    Lifecycle:
      1) Load data from GCS
      2) Validate loaded data
      3) Transform data for BigQuery
      4) Load to BigQuery
      5) Log stats
    """
    
    # Class-level configs (matching ScraperBase pattern)
    required_opts: List[str] = []
    additional_opts: List[str] = []
    
    # Processing settings
    validate_on_load: bool = True
    save_on_error: bool = True
    
    # BigQuery settings
    dataset_id: str = "nba_raw"
    table_name: str = ""  # Child classes must set
    write_disposition = bigquery.WriteDisposition.WRITE_APPEND
    
    # Time tracking (matching scraper pattern)
    time_markers: Dict = {}
    
    def __init__(self):
        """Initialize processor with same pattern as ScraperBase."""
        self.opts = {}
        self.raw_data = None
        self.validated_data = {}
        self.transformed_data = {}
        self.stats = {}
        
        # Generate run_id like scrapers
        self.run_id = str(uuid.uuid4())[:8]
        self.stats["run_id"] = self.run_id
        
        # GCP clients
        self.bq_client = None
        self.gcs_client = None
        
    def run(self, opts: Optional[Dict] = None) -> bool:
        """
        Main entry point - matches ScraperBase.run() pattern.
        Returns True on success, False on failure.
        Enhanced with notifications.
        """
        if opts is None:
            opts = {}
            
        try:
            # Re-init but preserve run_id (matching scraper pattern)
            saved_run_id = self.run_id
            self.__init__()
            self.run_id = saved_run_id
            self.stats["run_id"] = saved_run_id
            
            self.mark_time("total")
            self.step_info("start", "Processor run starting", extra={"opts": opts})
            
            # Setup
            self.set_opts(opts)
            self.validate_opts()
            self.set_additional_opts()
            self.validate_additional_opts()
            self.init_clients()
            
            # Load from GCS
            self.mark_time("load")
            self.load_data()
            load_seconds = self.get_elapsed_seconds("load")
            self.stats["load_time"] = load_seconds
            self.step_info("load_complete", f"Data loaded in {load_seconds:.1f}s")
            
            # Validate
            if self.validate_on_load:
                self.validate_loaded_data()
            
            # Transform
            self.mark_time("transform")
            self.transform_data()
            transform_seconds = self.get_elapsed_seconds("transform")
            self.stats["transform_time"] = transform_seconds
            
            # Save to BigQuery
            self.mark_time("save")
            self.save_data()
            save_seconds = self.get_elapsed_seconds("save")
            self.stats["save_time"] = save_seconds
            
            # Complete
            total_seconds = self.get_elapsed_seconds("total")
            self.stats["total_runtime"] = total_seconds
            self.step_info("finish", f"Processor completed in {total_seconds:.1f}s")
            
            self.post_process()
            return True
            
        except Exception as e:
            logger.error("ProcessorBase Error: %s", e, exc_info=True)
            sentry_sdk.capture_exception(e)
            
            # Send notification for processor failure
            try:
                notify_error(
                    title=f"Processor Failed: {self.__class__.__name__}",
                    message=f"Processor run failed: {str(e)}",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'error_type': type(e).__name__,
                        'step': self._get_current_step(),
                        'opts': {
                            'date': opts.get('date'),
                            'group': opts.get('group'),
                            'table': self.table_name
                        },
                        'stats': self.stats
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            if self.save_on_error:
                self._save_partial_data(e)
                
            self.report_error(e)
            return False
    
    def _get_current_step(self) -> str:
        """Helper to determine current processing step for error context."""
        if not self.bq_client or not self.gcs_client:
            return "initialization"
        elif not self.raw_data:
            return "load"
        elif not self.transformed_data:
            return "transform"
        else:
            return "save"
    
    def set_opts(self, opts: Dict) -> None:
        """Set options - matches scraper pattern."""
        self.opts = opts
        self.opts["run_id"] = self.run_id
        
    def validate_opts(self) -> None:
        """Validate required options - matches scraper pattern."""
        for required_opt in self.required_opts:
            if required_opt not in self.opts:
                error_msg = f"Missing required option [{required_opt}]"
                
                try:
                    notify_error(
                        title=f"Processor Configuration Error: {self.__class__.__name__}",
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
            project_id = self.opts.get("project_id", "nba-props-platform")
            self.bq_client = bigquery.Client(project=project_id)
            self.gcs_client = storage.Client(project=project_id)
        except Exception as e:
            logger.error(f"Failed to initialize GCP clients: {e}")
            try:
                notify_error(
                    title=f"Processor Client Initialization Failed: {self.__class__.__name__}",
                    message="Unable to initialize BigQuery or GCS clients",
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
    
    # Abstract methods for child classes (matching scraper pattern)
    def load_data(self) -> None:
        """Load data from GCS - child classes must implement."""
        raise NotImplementedError("Child classes must implement load_data()")
    
    def validate_loaded_data(self) -> None:
        """Validate loaded data - child classes override."""
        if not self.raw_data:
            try:
                notify_warning(
                    title=f"Processor Data Validation Warning: {self.__class__.__name__}",
                    message="No data loaded from source",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'opts': self.opts
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise ValueError("No data loaded")
    
    def transform_data(self) -> None:
        """Transform data for BigQuery - child classes must implement."""
        raise NotImplementedError("Child classes must implement transform_data()")
    
    def save_data(self) -> None:
        """Save to BigQuery - base implementation provided with notifications."""
        if not self.transformed_data:
            logger.warning("No transformed data to save")
            try:
                notify_warning(
                    title=f"Processor No Data to Save: {self.__class__.__name__}",
                    message="No transformed data available to save",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'raw_data_exists': bool(self.raw_data),
                        'opts': self.opts
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return
            
        table_id = f"{self.dataset_id}.{self.table_name}"
        
        # Handle different data types
        if isinstance(self.transformed_data, list):
            rows = self.transformed_data
        elif isinstance(self.transformed_data, dict):
            rows = [self.transformed_data]
        else:
            error_msg = f"Unexpected data type: {type(self.transformed_data)}"
            try:
                notify_error(
                    title=f"Processor Data Type Error: {self.__class__.__name__}",
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
                    title=f"Processor Empty Dataset: {self.__class__.__name__}",
                    message="No rows to insert after transformation",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'raw_data_size': len(str(self.raw_data)) if self.raw_data else 0
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return
            
        # Insert to BigQuery
        logger.info(f"Inserting {len(rows)} rows to {table_id}")
        
        try:
            errors = self.bq_client.insert_rows_json(table_id, rows)
            
            if errors:
                error_msg = f"BigQuery insert errors: {errors}"
                try:
                    notify_error(
                        title=f"Processor BigQuery Insert Failed: {self.__class__.__name__}",
                        message=f"Failed to insert {len(rows)} rows",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'table': table_id,
                            'rows_attempted': len(rows),
                            'errors': errors[:5] if len(errors) > 5 else errors,  # Limit error details
                            'error_count': len(errors)
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise Exception(error_msg)
                
        except Exception as e:
            # Catch any other BigQuery errors (network, permissions, etc.)
            if "BigQuery insert errors:" not in str(e):
                try:
                    notify_error(
                        title=f"Processor BigQuery Error: {self.__class__.__name__}",
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
        
        self.stats["rows_inserted"] = len(rows)
        logger.info(f"Successfully inserted {len(rows)} rows")
    
    def post_process(self) -> None:
        """Post-processing - matches scraper's post_export()."""
        summary = {
            "run_id": self.run_id,
            "processor": self.__class__.__name__,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "total_runtime": self.stats.get("total_runtime", 0),
        }
        
        # Merge processor stats
        processor_stats = self.get_processor_stats()
        if isinstance(processor_stats, dict):
            summary.update(processor_stats)
            
        logger.info("PROCESSOR_STATS %s", json.dumps(summary))
    
    def get_processor_stats(self) -> Dict:
        """Get processor stats - child classes override."""
        return {}
    
    # Logging methods (matching scraper_base exactly)
    def step_info(self, step_name: str, message: str, extra: Optional[Dict] = None) -> None:
        """Log structured step - matches scraper pattern."""
        if extra is None:
            extra = {}
        extra.update({
            "run_id": self.run_id,
            "step": step_name,
        })
        logger.info(f"PROCESSOR_STEP {message}", extra=extra)
    
    # Time tracking (matching scraper_base exactly)
    def mark_time(self, label: str) -> str:
        """Mark time - matches scraper implementation."""
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
        """Get elapsed seconds - matches scraper implementation."""
        if label not in self.time_markers:
            return 0.0
        start_time = self.time_markers[label]["start"]
        now_time = datetime.now()
        return (now_time - start_time).total_seconds()
    
    # Error handling (matching scraper pattern)
    def report_error(self, exc: Exception) -> None:
        """Report error to Sentry."""
        sentry_sdk.capture_exception(exc)
    
    def _save_partial_data(self, exc: Exception) -> None:
        """Save partial data on error for debugging."""
        try:
            debug_file = f"/tmp/processor_debug_{self.run_id}.json"
            debug_data = {
                "error": str(exc),
                "opts": self.opts,
                "raw_data_sample": str(self.raw_data)[:1000] if self.raw_data else None,
                "transformed_data_sample": str(self.transformed_data)[:1000] if self.transformed_data else None,
            }
            with open(debug_file, "w") as f:
                json.dump(debug_data, f, indent=2)
            logger.info(f"Saved debug data to {debug_file}")
        except Exception as save_exc:
            logger.warning(f"Failed to save debug data: {save_exc}")