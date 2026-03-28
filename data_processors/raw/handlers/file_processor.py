"""
File processor for routing and processing individual files.

Handles standard single-file processing for files that don't require batch mode.
"""

import logging

from shared.config.gcp_config import get_project_id


logger = logging.getLogger(__name__)


# Paths that are intentionally not processed (event IDs, metadata, etc.)
# These files are saved to GCS for reference but don't need BigQuery processing
SKIP_PROCESSING_PATHS = [
    'odds-api/events',      # OddsAPI event IDs - used by scrapers, not processed
    'bettingpros/events',   # BettingPros event IDs - used by scrapers, not processed
]


class FileProcessor:
    """Routes and processes individual files based on processor registry."""

    def process(
        self,
        normalized_message: dict,
        processor_registry: dict,
        extract_opts_func,
        pubsub_message: dict
    ) -> dict:
        """
        Route to appropriate processor and execute.

        Args:
            normalized_message: Normalized message from MessageHandler
            processor_registry: Dict mapping path patterns to processor classes
            extract_opts_func: Function to extract options from file path
            pubsub_message: Original Pub/Sub message for metadata

        Returns:
            Response dict with status and details
        """
        # Extract file info from normalized message
        bucket = normalized_message.get('bucket', 'nba-scraped-data')
        file_path = normalized_message['name']

        # Enhanced logging with scraper context
        if normalized_message.get('_original_format') == 'scraper_completion':
            logger.info(
                f"📥 Processing scraper output: gs://{bucket}/{file_path} "
                f"(scraper={normalized_message.get('_scraper_name')}, "
                f"status={normalized_message.get('_status')}, "
                f"records={normalized_message.get('_record_count')}, "
                f"execution_id={normalized_message.get('_execution_id')})"
            )
        else:
            logger.info(f"📥 Processing file: gs://{bucket}/{file_path}")

        # Determine processor(s) based on file path
        # Registry values may be a single class or a list of classes (for multi-table files)
        matched_entry = None
        for path_prefix, proc_entry in processor_registry.items():
            if path_prefix in file_path:
                matched_entry = proc_entry
                break

        if not matched_entry:
            # Check if this is an intentionally skipped path (events, metadata, etc.)
            is_skip_path = any(skip_path in file_path for skip_path in SKIP_PROCESSING_PATHS)

            if is_skip_path:
                logger.info(f"Skipping file (no processing needed): {file_path}")
                return {
                    "status": "skipped",
                    "reason": "Intentionally not processed",
                    "file": file_path
                }

            logger.warning(f"No processor found for file: {file_path}")
            return {
                "status": "skipped",
                "reason": "No processor for file type",
                "file": file_path,
                "registered_patterns": list(processor_registry.keys())
            }

        # Normalize to list so we can handle single or multiple processors uniformly
        processor_classes = matched_entry if isinstance(matched_entry, list) else [matched_entry]

        # Extract metadata from file path
        try:
            opts = extract_opts_func(file_path)
        except Exception as e:
            logger.error(f"Failed to extract opts from path: {file_path}", exc_info=True)
            # Continue with empty opts rather than failing
            opts = {}

        opts['bucket'] = bucket
        opts['file_path'] = file_path
        opts['project_id'] = get_project_id()

        # Add trigger context for error notifications
        opts['trigger_source'] = normalized_message.get('_original_format', 'unknown')
        opts['trigger_message_id'] = pubsub_message.get('messageId', 'N/A')
        opts['parent_processor'] = normalized_message.get('_scraper_name', 'N/A')
        opts['workflow'] = normalized_message.get('_workflow', 'N/A')
        opts['execution_id'] = normalized_message.get('_execution_id', 'N/A')

        # Process the file through each registered processor
        all_stats = []
        any_error = False
        for processor_class in processor_classes:
            processor = processor_class()
            success = processor.run(opts)

            if success:
                stats = processor.get_processor_stats()
                logger.info(f"✅ Successfully processed {file_path} via {processor_class.__name__}: {stats}")
                all_stats.append(stats)
            else:
                # Note: ProcessorBase already sent detailed error notification
                logger.error(f"❌ Failed to process {file_path} via {processor_class.__name__}")
                any_error = True

        if any_error:
            return {
                "status": "error",
                "file": file_path
            }

        return {
            "status": "success",
            "file": file_path,
            "stats": all_stats[0] if len(all_stats) == 1 else all_stats
        }
