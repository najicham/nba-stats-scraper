"""
processors/processor_base.py

Base class for all data processors that handles:
 - Loading data from GCS or databases
 - Validating and transforming data
 - Loading to BigQuery
 - Error handling and logging
 - Multi-channel notifications (Email + Slack)
 
UPDATED: 2025-10-01
 - Added load_json_from_gcs() helper for raw processors
 - Fixed duplicate error notifications
 - Improved documentation
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
    
    There are two types of processors:
    1. Raw Processors: Load JSON from GCS → Transform → Save to BigQuery
    2. Reference Processors: Load from BigQuery → Transform → Save back to BigQuery
    
    Lifecycle:
      1) load_data() - Load data from source (GCS or BigQuery)
      2) validate_loaded_data() - Validate the loaded data
      3) transform_data() - Transform data for target schema
      4) save_data() - Save to BigQuery
      5) post_process() - Log stats and cleanup
    
    Child classes must implement:
      - load_data(): Load self.raw_data from source
      - transform_data(): Transform self.raw_data → self.transformed_data
      
    Child classes can override:
      - validate_loaded_data(): Custom validation logic
      - save_data(): Custom save logic (MERGE, DELETE, etc.)
      - get_processor_stats(): Return custom statistics
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
            
            # Load from source
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
            
            # Send notification for processor failure (only place we notify errors)
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
        """
        Add additional options computed from required_opts.
        
        Child classes override this to set computed options like:
        - Derive season_year from a date parameter
        - Set default values
        - Calculate derived parameters
        
        Always call super().set_additional_opts() first.
        """
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
    
    # ================================================================
    # HELPER METHOD FOR RAW PROCESSORS
    # ================================================================
    def load_json_from_gcs(self, bucket: str = None, file_path: str = None) -> Dict:
        """
        Helper method for raw processors loading JSON from GCS.
        
        Reference processors loading from BigQuery don't need this.
        
        Args:
            bucket: GCS bucket name (defaults to self.opts['bucket'])
            file_path: Path to file in bucket (defaults to self.opts['file_path'])
            
        Returns:
            Dict: Parsed JSON data
            
        Raises:
            ValueError: If bucket or file_path missing
            FileNotFoundError: If file doesn't exist in GCS
            
        Example:
            def load_data(self) -> None:
                self.raw_data = self.load_json_from_gcs()
        """
        bucket = bucket or self.opts.get('bucket')
        file_path = file_path or self.opts.get('file_path')
        
        if not bucket or not file_path:
            raise ValueError("Missing 'bucket' or 'file_path' in opts")
        
        logger.info(f"Loading JSON from gs://{bucket}/{file_path}")
        
        bucket_obj = self.gcs_client.bucket(bucket)
        blob = bucket_obj.blob(file_path)
        
        if not blob.exists():
            raise FileNotFoundError(f"File not found: gs://{bucket}/{file_path}")
        
        json_string = blob.download_as_string()
        data = json.loads(json_string)
        
        logger.info(f"Successfully loaded {len(json_string)} bytes from GCS")
        return data
    
    # ================================================================
    # ABSTRACT METHODS - CHILD CLASSES MUST IMPLEMENT
    # ================================================================
    def load_data(self) -> None:
        """
        Load data from source into self.raw_data.
        
        Raw processors: Load from GCS using load_json_from_gcs()
        Reference processors: Load from BigQuery using SQL queries
        
        Must set self.raw_data with the loaded data.
        
        Example (Raw Processor):
            def load_data(self) -> None:
                self.raw_data = self.load_json_from_gcs()
                
        Example (Reference Processor):
            def load_data(self) -> None:
                query = "SELECT * FROM `dataset.table` WHERE date = @date"
                self.raw_data = list(self.bq_client.query(query).result())
        """
        raise NotImplementedError("Child classes must implement load_data()")
    
    def transform_data(self) -> None:
        """
        Transform self.raw_data into self.transformed_data.
        
        Must set self.transformed_data as either:
        - List[Dict]: Multiple rows for BigQuery
        - Dict: Single row for BigQuery
        
        Example:
            def transform_data(self) -> None:
                rows = []
                for item in self.raw_data['results']:
                    rows.append({
                        'id': item['id'],
                        'name': item['name'],
                        'processed_at': datetime.utcnow().isoformat()
                    })
                self.transformed_data = rows
        """
        raise NotImplementedError("Child classes must implement transform_data()")
    
    # ================================================================
    # OPTIONAL OVERRIDE METHODS
    # ================================================================
    def validate_loaded_data(self) -> None:
        """
        Validate self.raw_data after loading.
        
        Override to add custom validation logic.
        Default implementation just checks data exists.
        
        Raise ValueError or other exceptions if validation fails.
        """
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
    
    def save_data(self) -> None:
        """
        Save self.transformed_data to BigQuery.
        
        Default implementation uses insert_rows_json (append).
        
        Override for custom save strategies:
        - MERGE operations (upserts)
        - DELETE operations
        - Query-based transformations
        
        If overriding, set self.stats["rows_inserted"] for tracking.
        
        Example (Custom MERGE):
            def save_data(self) -> None:
                query = '''
                    MERGE `dataset.table` T
                    USING UNNEST(@rows) S
                    ON T.id = S.id
                    WHEN MATCHED THEN UPDATE SET ...
                    WHEN NOT MATCHED THEN INSERT ...
                '''
                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ArrayQueryParameter("rows", "STRUCT", self.transformed_data)
                    ]
                )
                self.bq_client.query(query, job_config=job_config).result()
                self.stats["rows_inserted"] = len(self.transformed_data)
        """
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
            raise ValueError(error_msg)
        
        if not rows:
            logger.warning("No rows to insert")
            return
            
        # Insert to BigQuery
        logger.info(f"Inserting {len(rows)} rows to {table_id}")
        
        # Don't notify here - let run() catch exceptions and notify
        errors = self.bq_client.insert_rows_json(table_id, rows)
        
        if errors:
            # Just raise - run() will catch and notify
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
        """
        Get processor-specific statistics.
        
        Override to return custom stats like:
        - Number of records processed
        - Number of errors
        - Custom metrics
        
        Example:
            def get_processor_stats(self) -> Dict:
                return {
                    'players_processed': self.players_processed,
                    'players_failed': self.players_failed,
                    'rows_transformed': len(self.transformed_data)
                }
        """
        return {}
    
    # ================================================================
    # LOGGING METHODS (matching scraper_base pattern)
    # ================================================================
    def step_info(self, step_name: str, message: str, extra: Optional[Dict] = None) -> None:
        """Log structured step - matches scraper pattern."""
        if extra is None:
            extra = {}
        extra.update({
            "run_id": self.run_id,
            "step": step_name,
        })
        logger.info(f"PROCESSOR_STEP {message}", extra=extra)
    
    # ================================================================
    # TIME TRACKING (matching scraper_base exactly)
    # ================================================================
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
    
    # ================================================================
    # ERROR HANDLING (matching scraper pattern)
    # ================================================================
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
            