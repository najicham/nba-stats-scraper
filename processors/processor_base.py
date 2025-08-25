"""
processors/processor_base.py

Base class for all data processors that handles:
 - Loading data from GCS
 - Validating and transforming data
 - Loading to BigQuery
 - Error handling and logging
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
            
            if self.save_on_error:
                self._save_partial_data(e)
                
            self.report_error(e)
            return False
    
    def set_opts(self, opts: Dict) -> None:
        """Set options - matches scraper pattern."""
        self.opts = opts
        self.opts["run_id"] = self.run_id
        
    def validate_opts(self) -> None:
        """Validate required options - matches scraper pattern."""
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
        project_id = self.opts.get("project_id", "nba-props-platform")
        self.bq_client = bigquery.Client(project=project_id)
        self.gcs_client = storage.Client(project=project_id)
    
    # Abstract methods for child classes (matching scraper pattern)
    def load_data(self) -> None:
        """Load data from GCS - child classes must implement."""
        raise NotImplementedError("Child classes must implement load_data()")
    
    def validate_loaded_data(self) -> None:
        """Validate loaded data - child classes override."""
        if not self.raw_data:
            raise ValueError("No data loaded")
    
    def transform_data(self) -> None:
        """Transform data for BigQuery - child classes must implement."""
        raise NotImplementedError("Child classes must implement transform_data()")
    
    def save_data(self) -> None:
        """Save to BigQuery - base implementation provided."""
        if not self.transformed_data:
            logger.warning("No transformed data to save")
            return
            
        table_id = f"{self.dataset_id}.{self.table_name}"
        
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
            
        # Insert to BigQuery
        logger.info(f"Inserting {len(rows)} rows to {table_id}")
        errors = self.bq_client.insert_rows_json(table_id, rows)
        
        if errors:
            raise Exception(f"BigQuery insert errors: {errors}")
            
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