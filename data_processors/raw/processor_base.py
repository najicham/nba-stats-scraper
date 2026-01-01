"""
processors/processor_base.py

Base class for all data processors that handles:
 - Loading data from GCS or databases
 - Validating and transforming data
 - Loading to BigQuery
 - Error handling and logging
 - Multi-channel notifications (Email + Slack)
 - Run history logging (via RunHistoryMixin)

UPDATED: 2025-11-27
 - Added RunHistoryMixin for processor run history logging
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

# Import run history mixin
from shared.processors.mixins import RunHistoryMixin

# Configure logging to match scraper_base pattern
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger("processor_base")


class ProcessorBase(RunHistoryMixin):
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

    Run History:
      Automatically logs runs to processor_run_history table via RunHistoryMixin.
      Child classes can set OUTPUT_TABLE and OUTPUT_DATASET for better tracking.
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

    # Run history settings (from RunHistoryMixin)
    PHASE: str = 'phase_2_raw'
    OUTPUT_TABLE: str = ''  # Set to table_name in run()
    OUTPUT_DATASET: str = 'nba_raw'
    
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
        Enhanced with notifications and run history logging.
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

            # DEDUPLICATION CHECK - Skip if already processed
            data_date = opts.get('date') or opts.get('game_date')
            if data_date:
                # Check if already processed (prevents duplicate processing on Pub/Sub retries)
                already_processed = self.check_already_processed(
                    processor_name=self.__class__.__name__,
                    data_date=data_date,
                    stale_threshold_hours=2  # Retry if stuck for > 2 hours
                )

                if already_processed:
                    logger.info(
                        f"⏭️  Skipping {self.__class__.__name__} for {data_date} - already processed"
                    )
                    # Don't start run tracking - this isn't a real run
                    return True  # Return success (not an error)

            # Start run history tracking (writes 'running' status immediately for deduplication)
            self.OUTPUT_TABLE = self.table_name
            self.OUTPUT_DATASET = self.dataset_id
            self.start_run_tracking(
                data_date=data_date,
                trigger_source=opts.get('trigger_source', 'manual'),
                trigger_message_id=opts.get('trigger_message_id'),
                parent_processor=opts.get('parent_processor')
            )

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

            # LAYER 5: Validate save result (catch 0-row bugs immediately)
            self._validate_and_log_save_result()

            # Publish Phase 2 completion event (triggers Phase 3)
            self._publish_completion_event()

            # Complete
            total_seconds = self.get_elapsed_seconds("total")
            self.stats["total_runtime"] = total_seconds
            self.step_info("finish", f"Processor completed in {total_seconds:.1f}s")

            self.post_process()

            # Record successful run to history
            self.record_run_complete(
                status='success',
                records_processed=self.stats.get('rows_inserted', 0),
                records_created=self.stats.get('rows_inserted', 0),
                summary=self.stats
            )

            return True

        except Exception as e:
            logger.error("ProcessorBase Error: %s", e, exc_info=True)
            sentry_sdk.capture_exception(e)

            # Send notification for processor failure (only place we notify errors)
            alert_sent = False
            try:
                # Detect backfill mode from opts
                backfill_mode = self.opts.get('skip_downstream_trigger', False)

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
                    processor_name=self.__class__.__name__,
                    backfill_mode=backfill_mode  # Suppress alerts during backfill
                )
                alert_sent = True
                self.set_alert_sent('error')
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            if self.save_on_error:
                self._save_partial_data(e)

            self.report_error(e)

            # Record failed run to history
            self.record_run_complete(
                status='failed',
                error=e,
                summary=self.stats
            )

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
                    # Configuration errors are critical even in backfill
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
                        processor_name=self.__class__.__name__,
                        backfill_mode=False  # Always alert for config errors
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
                # Client initialization errors are critical even in backfill
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
                    processor_name=self.__class__.__name__,
                    backfill_mode=False  # Always alert for client init errors
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
                self.raw_data = list(self.bq_client.query(query).result(timeout=60))
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

    def _validate_and_log_save_result(self) -> None:
        """
        LAYER 5: Validate processor output to catch silent failures.

        Detects suspicious patterns like:
        - Expected data but got 0 rows (gamebook bug scenario)
        - Partial writes (some rows failed silently)
        - Stats mismatch (processor returned different count than self.stats)

        Logs all results to monitoring table and sends alerts for critical issues.
        """
        try:
            # Get actual rows inserted from stats
            actual_rows = self.stats.get('rows_inserted', 0)

            # Estimate expected rows based on input data
            expected_rows = self._estimate_expected_rows()

            # Validate result
            validation_result = {
                'processor_name': self.__class__.__name__,
                'file_path': self.opts.get('file_path', ''),
                'game_date': str(self.opts.get('game_date', '')),
                'expected_rows': expected_rows,
                'actual_rows': actual_rows,
                'is_valid': True,
                'severity': 'OK',
                'issue_type': None,
                'reason': None,
            }

            # CASE 1: Zero rows when we expected data
            if actual_rows == 0 and expected_rows > 0:
                reason = self._diagnose_zero_rows()
                is_acceptable = self._is_acceptable_zero_rows(reason)

                validation_result.update({
                    'is_valid': is_acceptable,
                    'severity': 'INFO' if is_acceptable else 'CRITICAL',
                    'issue_type': 'zero_rows',
                    'reason': reason
                })

                # Alert if unexpected
                if not is_acceptable:
                    self._send_zero_row_alert(validation_result)

            # CASE 2: Partial write (significant data loss)
            elif 0 < actual_rows < expected_rows * 0.9:  # >10% loss
                validation_result.update({
                    'is_valid': False,
                    'severity': 'WARNING',
                    'issue_type': 'partial_write',
                    'reason': f'{((expected_rows - actual_rows) / expected_rows * 100):.1f}% of data lost'
                })

                notify_warning(
                    title=f"{self.__class__.__name__}: Partial Data Loss",
                    message=f"Expected {expected_rows} rows but only saved {actual_rows}",
                    details=validation_result
                )

            # Log all validations to monitoring table (for trending)
            self._log_processor_metrics(validation_result)

        except Exception as e:
            # Don't fail processor if validation fails
            logger.warning(f"Output validation failed: {e}")

    def _estimate_expected_rows(self) -> int:
        """Estimate expected output rows based on input data."""
        # If we have transformed data, that's our expectation
        if hasattr(self, 'transformed_data'):
            if isinstance(self.transformed_data, list):
                return len(self.transformed_data)
            elif isinstance(self.transformed_data, dict):
                return 1

        # Fallback: check raw_data size as rough estimate
        if hasattr(self, 'raw_data'):
            if isinstance(self.raw_data, list):
                return len(self.raw_data)
            elif isinstance(self.raw_data, dict):
                # Check for common patterns
                if 'stats' in self.raw_data:
                    return len(self.raw_data.get('stats', []))
                if 'players' in self.raw_data:
                    return len(self.raw_data.get('players', []))
                return 1

        return 0

    def _diagnose_zero_rows(self) -> str:
        """Diagnose why 0 rows were saved."""
        reasons = []

        # Check if data was loaded
        if not hasattr(self, 'raw_data') or not self.raw_data:
            reasons.append("No raw data loaded")

        # Check if transform produced output
        if not hasattr(self, 'transformed_data') or not self.transformed_data:
            reasons.append("Transform produced empty dataset")
        elif len(self.transformed_data) == 0:
            reasons.append("Transformed data is empty array")

        # Check for idempotency/deduplication
        if hasattr(self, 'idempotency_stats'):
            skipped = self.idempotency_stats.get('rows_skipped', 0)
            if skipped > 0:
                reasons.append(f"Smart idempotency: {skipped} duplicates skipped")

        # Check run history
        if self.stats.get('rows_skipped_by_run_history'):
            reasons.append("Skipped by run history (already processed)")

        return " | ".join(reasons) if reasons else "Unknown - needs investigation"

    def _is_acceptable_zero_rows(self, reason: str) -> bool:
        """Determine if 0-row result is expected/acceptable."""
        acceptable_patterns = [
            "Smart idempotency",
            "duplicates skipped",
            "Preseason",
            "All-Star",
            "No games scheduled",
            "Already processed",
            "Off season"
        ]
        return any(pattern.lower() in reason.lower() for pattern in acceptable_patterns)

    def _send_zero_row_alert(self, validation_result: dict) -> None:
        """Send immediate alert for unexpected 0-row result."""
        try:
            notify_warning(
                title=f"⚠️ {self.__class__.__name__}: Zero Rows Saved",
                message=f"Expected {validation_result['expected_rows']} rows but saved 0",
                details={
                    'processor': validation_result['processor_name'],
                    'reason': validation_result['reason'],
                    'file_path': validation_result['file_path'],
                    'game_date': validation_result['game_date'],
                    'severity': validation_result['severity'],
                    'run_id': getattr(self, 'run_id', None),
                    'detection_layer': 'Layer 5: Processor Output Validation',
                    'detection_time': datetime.now(timezone.utc).isoformat()
                }
            )
        except Exception as e:
            logger.warning(f"Failed to send zero-row alert: {e}")

    def _log_processor_metrics(self, validation_result: dict) -> None:
        """Log processor output validation to monitoring table."""
        try:
            # Only log if we have project_id
            if not hasattr(self, 'project_id') or not self.project_id:
                return

            table_id = f"{self.project_id}.nba_orchestration.processor_output_validation"

            row = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'processor_name': validation_result['processor_name'],
                'file_path': validation_result['file_path'],
                'game_date': validation_result['game_date'] or None,
                'expected_rows': validation_result['expected_rows'],
                'actual_rows': validation_result['actual_rows'],
                'issue_type': validation_result['issue_type'],
                'severity': validation_result['severity'],
                'reason': validation_result['reason'],
                'is_acceptable': validation_result['is_valid'],
                'run_id': getattr(self, 'run_id', None)
            }

            # Insert to monitoring table (non-blocking)
            errors = self.bq_client.insert_rows_json(table_id, [row])
            if errors:
                logger.warning(f"Failed to log processor metrics: {errors}")

        except Exception as e:
            # Don't fail processor if logging fails
            logger.debug(f"Could not log processor metrics: {e}")

    def save_data(self) -> None:
        """
        Save self.transformed_data to BigQuery using batch loading (not streaming).
        
        Default implementation uses load_table_from_json with schema enforcement.
        
        Override for custom save strategies:
        - MERGE operations (upserts)
        - DELETE operations
        - Query-based transformations
        
        If overriding, set self.stats["rows_inserted"] for tracking.
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
        
        # Insert to BigQuery using batch loading (not streaming)
        logger.info(f"Batch loading {len(rows)} rows to {table_id}")
        
        try:
            import io
            import json
            
            # Get target table schema for enforcement
            try:
                table = self.bq_client.get_table(table_id)
                table_schema = table.schema
            except Exception as schema_e:
                logger.warning(f"Could not get table schema, proceeding without enforcement: {schema_e}")
                table_schema = None
            
            # Convert rows to NDJSON
            ndjson_data = "\n".join(json.dumps(row) for row in rows)
            ndjson_bytes = ndjson_data.encode('utf-8')
            
            # Configure load job with schema enforcement
            job_config = bigquery.LoadJobConfig(
                schema=table_schema,  # Enforce exact schema
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=self.write_disposition,
                autodetect=False
            )
            
            # Load to target table
            load_job = self.bq_client.load_table_from_file(
                io.BytesIO(ndjson_bytes),
                table_id,
                job_config=job_config
            )
            
            # Wait for completion with graceful failure
            try:
                load_job.result(timeout=60)
                self.stats["rows_inserted"] = len(rows)
                logger.info(f"✅ Successfully batch loaded {len(rows)} rows")
                
            except Exception as load_e:
                # Graceful failure for streaming buffer
                if "streaming buffer" in str(load_e).lower():
                    logger.warning(f"⚠️ Load blocked by streaming buffer - {len(rows)} rows skipped")
                    logger.info("Records will be processed on next run")
                    self.stats["rows_skipped"] = len(rows)
                    return  # Graceful failure
                else:
                    raise load_e
            
        except Exception as e:
            error_msg = f"BigQuery batch load failed: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def _publish_completion_event(self) -> None:
        """
        Publish Phase 2 completion event using unified message format.

        This method is called after save_data() successfully completes.
        Publishing is non-blocking - failures are logged but don't fail the processor.

        Can be disabled with skip_downstream_trigger flag for backfills.

        Version: 2.0 - Uses UnifiedPubSubPublisher
        """
        # Check if downstream triggering should be skipped (for backfills)
        skip_downstream = self.opts.get('skip_downstream_trigger', False)

        if skip_downstream:
            logger.info(
                f"⏸️  Skipping downstream trigger (backfill mode) - "
                f"Phase 3 will not be auto-triggered for {self.table_name}"
            )
            # Still need to return - UnifiedPubSubPublisher handles skip_downstream flag
            # but we can short-circuit here to avoid unnecessary work

        try:
            from shared.publishers import UnifiedPubSubPublisher
            from shared.config.pubsub_topics import TOPICS

            # Extract game_date from opts
            game_date = self.opts.get('date') or self.opts.get('game_date')
            if not game_date:
                logger.debug(
                    f"No game_date in opts for {self.__class__.__name__}, skipping publish"
                )
                return

            # Get correlation_id (traces back to scraper)
            correlation_id = self.opts.get('correlation_id') or self.opts.get('execution_id') or self.run_id

            # Get parent processor from trigger message
            parent_processor = self.opts.get('processor_name') or self.opts.get('scraper_name')

            # Get trigger info
            trigger_source = self.opts.get('trigger_source', 'pubsub')
            trigger_message_id = self.opts.get('trigger_message_id')

            # Initialize publisher
            project_id = self.bq_client.project
            publisher = UnifiedPubSubPublisher(project_id=project_id)

            # Publish using unified format
            message_id = publisher.publish_completion(
                topic=TOPICS.PHASE2_RAW_COMPLETE,
                processor_name=self.__class__.__name__,
                phase='phase_2_raw',
                execution_id=self.run_id,
                correlation_id=correlation_id,
                game_date=str(game_date),
                output_table=self.table_name,
                output_dataset=self.dataset_id,
                status='success',
                record_count=self.stats.get('rows_inserted', 0),
                records_failed=0,
                duration_seconds=self.stats.get('total_runtime', 0),
                parent_processor=parent_processor,
                trigger_source=trigger_source,
                trigger_message_id=trigger_message_id,
                metadata={
                    'rows_updated': self.stats.get('rows_updated', 0),
                    'processing_strategy': 'INSERT'  # Or 'MERGE' depending on processor
                },
                skip_downstream=skip_downstream
            )

            if message_id:
                logger.info(
                    f"✅ Published Phase 2 completion: {self.table_name} "
                    f"for {game_date} (message_id={message_id})"
                )
            else:
                if not skip_downstream:
                    logger.warning(
                        f"⚠️ Publish returned None for {self.table_name} (non-fatal)"
                    )

        except Exception as e:
            # Log but DON'T fail the processor - publishing is non-critical
            logger.warning(
                f"Failed to publish Phase 2 completion for {self.table_name}: {e}",
                exc_info=True
            )

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
            