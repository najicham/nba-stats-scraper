"""
Message handler for decoding and normalizing Pub/Sub messages.

Handles three message formats:
1. GCS Object Finalize (legacy): {"bucket": "...", "name": "..."}
2. Scraper Completion (old): {"scraper_name": "...", "gcs_path": "gs://...", ...}
3. Unified Format (v2): {"processor_name": "...", "phase": "...", "metadata": {"gcs_path": "..."}, ...}
"""

import base64
import json
import logging


logger = logging.getLogger(__name__)


class MessageHandler:
    """Handles decoding and normalization of Pub/Sub messages."""

    def decode_message(self, envelope: dict) -> dict:
        """
        Decode Pub/Sub message from envelope.

        Args:
            envelope: Pub/Sub envelope with 'message' field

        Returns:
            Decoded message as dictionary

        Raises:
            ValueError: If message format is invalid
        """
        if not envelope:
            raise ValueError("No Pub/Sub message received")

        if 'message' not in envelope:
            raise ValueError(
                f"Invalid Pub/Sub message format: missing 'message' field. "
                f"Got keys: {list(envelope.keys())}"
            )

        pubsub_message = envelope['message']

        if 'data' not in pubsub_message:
            raise ValueError(
                f"No data in Pub/Sub message. "
                f"Got keys: {list(pubsub_message.keys())}"
            )

        # Decode base64 message data
        data = base64.b64decode(pubsub_message['data']).decode('utf-8')
        message = json.loads(data)

        return message

    def normalize_format(self, message: dict) -> dict:
        """
        Normalize Pub/Sub message format to be compatible with processor routing.

        Handles three message formats:
        1. GCS Object Finalize (legacy): {"bucket": "...", "name": "..."}
        2. Scraper Completion (old): {"scraper_name": "...", "gcs_path": "gs://...", ...}
        3. Unified Format (v2): {"processor_name": "...", "phase": "...", "metadata": {"gcs_path": "..."}, ...}

        Also handles special cases:
        - Failed scraper events (no gcs_path)
        - No data events (no gcs_path)

        Args:
            message: Raw Pub/Sub message data

        Returns:
            Normalized message with 'bucket' and 'name' fields, or
            a skip_processing dict for events without files

        Raises:
            ValueError: If message format is unrecognized or missing required fields
        """
        # Case 1: GCS Object Finalize format (legacy)
        if 'bucket' in message and 'name' in message:
            logger.info(f"Processing GCS Object Finalize message: gs://{message['bucket']}/{message['name']}")
            return message

        # Case 2: Unified Format (v2) - from UnifiedPubSubPublisher
        # Identifies by: 'processor_name' AND 'phase' fields
        if 'processor_name' in message and 'phase' in message:
            processor_name = message.get('processor_name')
            status = message.get('status', 'unknown')

            # Extract gcs_path from metadata (unified format stores it there)
            metadata = message.get('metadata', {})
            gcs_path = metadata.get('gcs_path')

            logger.info(
                f"Processing Unified Format message from: {processor_name} "
                f"(phase={message.get('phase')}, status={status})"
            )

            # Handle failed or no-data events (no file to process)
            if gcs_path is None or gcs_path == '' or status in ('failed', 'no_data'):
                logger.warning(
                    f"Scraper {processor_name} published event with status={status} "
                    f"but no gcs_path. This is expected for failed or no-data events. Skipping file processing."
                )
                return {
                    'skip_processing': True,
                    'reason': f'No file to process (status={status})',
                    'scraper_name': processor_name,
                    'execution_id': message.get('execution_id'),
                    'status': status,
                    '_original_message': message
                }

            # Parse GCS path into bucket and name
            if not gcs_path.startswith('gs://'):
                raise ValueError(
                    f"Invalid gcs_path format: {gcs_path}. "
                    f"Expected gs://bucket/path format from scraper {processor_name}"
                )

            path_without_protocol = gcs_path[5:]  # Remove 'gs://'
            parts = path_without_protocol.split('/', 1)

            if len(parts) != 2:
                raise ValueError(
                    f"Invalid gcs_path structure: {gcs_path}. "
                    f"Expected gs://bucket/path format from scraper {processor_name}"
                )

            bucket = parts[0]
            name = parts[1]

            # Create normalized message preserving unified metadata
            normalized = {
                'bucket': bucket,
                'name': name,
                '_original_format': 'unified_v2',
                '_scraper_name': processor_name,
                '_execution_id': message.get('execution_id'),
                '_status': status,
                '_record_count': message.get('record_count'),
                '_duration_seconds': message.get('duration_seconds'),
                '_workflow': metadata.get('workflow'),
                '_timestamp': message.get('timestamp'),
                '_game_date': message.get('game_date'),
                '_metadata': metadata  # Preserve full metadata for batch processing
            }

            logger.info(
                f"Normalized unified message: bucket={bucket}, name={name}, "
                f"scraper={processor_name}, status={status}"
            )

            return normalized

        # Case 3: Scraper Completion format (old/v1)
        # Check for 'scraper_name' OR ('name' AND 'gcs_path' without 'bucket')
        if 'scraper_name' in message or ('name' in message and 'gcs_path' in message and 'bucket' not in message):
            # Prefer scraper_name, fallback to name
            scraper_name = message.get('scraper_name') or message.get('name')
            logger.info(f"Processing Scraper Completion message from: {scraper_name}")

            # Get gcs_path (may be None for failed/no-data events)
            gcs_path = message.get('gcs_path')
            status = message.get('status', 'unknown')

            # Handle failed or no-data events (no file to process)
            if gcs_path is None or gcs_path == '':
                logger.warning(
                    f"Scraper {scraper_name} published event with status={status} "
                    f"but no gcs_path. This is expected for failed or no-data events. Skipping file processing."
                )
                return {
                    'skip_processing': True,
                    'reason': f'No file to process (status={status})',
                    'scraper_name': scraper_name,
                    'execution_id': message.get('execution_id'),
                    'status': status,
                    '_original_message': message
                }

            if not gcs_path.startswith('gs://'):
                raise ValueError(
                    f"Invalid gcs_path format: {gcs_path}. "
                    f"Expected gs://bucket/path format from scraper {scraper_name}"
                )

            # Parse GCS path into bucket and name
            path_without_protocol = gcs_path[5:]  # Remove 'gs://'
            parts = path_without_protocol.split('/', 1)

            if len(parts) != 2:
                raise ValueError(
                    f"Invalid gcs_path structure: {gcs_path}. "
                    f"Expected gs://bucket/path format from scraper {scraper_name}"
                )

            bucket = parts[0]
            name = parts[1]

            # Create normalized message preserving scraper metadata
            normalized = {
                'bucket': bucket,
                'name': name,
                '_original_format': 'scraper_completion',
                '_scraper_name': scraper_name,
                '_execution_id': message.get('execution_id'),
                '_status': status,
                '_record_count': message.get('record_count'),
                '_duration_seconds': message.get('duration_seconds'),
                '_workflow': message.get('workflow'),
                '_timestamp': message.get('timestamp')
            }

            logger.info(
                f"Normalized scraper message: bucket={bucket}, name={name}, "
                f"scraper={scraper_name}, status={status}"
            )

            return normalized

        # Case 4: Only gcs_path present (fallback for scrapers with incomplete messages)
        if 'gcs_path' in message:
            gcs_path = message.get('gcs_path')
            logger.warning(f"Processing message with only gcs_path (no scraper_name): {gcs_path}")

            if not gcs_path or not gcs_path.startswith('gs://'):
                raise ValueError(f"Invalid gcs_path format: {gcs_path}. Expected gs://bucket/path format")

            # Parse GCS path into bucket and name
            path_without_protocol = gcs_path[5:]  # Remove 'gs://'
            parts = path_without_protocol.split('/', 1)

            if len(parts) != 2:
                raise ValueError(f"Invalid gcs_path structure: {gcs_path}. Expected gs://bucket/path format")

            bucket = parts[0]
            name = parts[1]

            # Create normalized message
            normalized = {
                'bucket': bucket,
                'name': name,
                '_original_format': 'gcs_path_only',
                '_scraper_name': 'unknown',
                '_status': message.get('status', 'unknown'),
                '_record_count': message.get('record_count'),
            }

            logger.info(f"Normalized gcs_path-only message: bucket={bucket}, name={name}")
            return normalized

        # Case 5: Status/run-history message (should be ignored, not a file trigger)
        # These messages have fields like: game_date, output_table, status, triggered_by, retry_count
        # They come from run history logging and should not be routed to file processors
        if 'status' in message and 'output_table' in message and 'processor_name' not in message:
            logger.warning(
                f"Received run-history status message (not a file trigger). "
                f"Status={message.get('status')}, Table={message.get('output_table')}. "
                f"This message should not be published to the raw processor topic. Skipping."
            )
            return {
                'skip_processing': True,
                'reason': 'Status/run-history message, not a file trigger',
                'status': message.get('status'),
                'output_table': message.get('output_table'),
                '_original_message': message
            }

        # Case 6: Unrecognized format
        available_fields = list(message.keys())
        raise ValueError(
            f"Unrecognized message format. "
            f"Expected 'name' (GCS), 'gcs_path' (Scraper), or 'processor_name' (Unified) field. "
            f"Got fields: {available_fields}"
        )
