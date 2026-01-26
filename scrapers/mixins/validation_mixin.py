"""
validation_mixin.py

A mixin class for ScraperBase that handles validation and schema checks.

This mixin provides:
- Scraper output validation (Layer 1 validation)
- Schema-based validation using YAML configs
- Phase 1→2 boundary validation
- Download data validation
- BigQuery logging of validation results
- Alert notifications for critical validation failures

The validation methods ensure data quality at various stages:
1. After scraping (source validation)
2. During schema checks (structural validation)
3. At phase boundaries (handoff validation)
4. After download (completeness validation)
"""

import logging
from datetime import datetime, timezone

# Initialize logger for this module
logger = logging.getLogger(__name__)


class ValidationMixin:
    """
    Mixin for validation and schema checking functionality.

    Handles all validation-related operations including:
    - Output validation with row counts and file size checks
    - Schema validation using YAML configurations
    - Phase boundary validation
    - Download data validation
    - BigQuery logging and alerting
    """

    def _validate_scraper_output(self) -> None:
        """
        LAYER 1: Validate scraper output to catch data gaps at source.

        Performs checks:
        - File successfully exported to GCS
        - File size is reasonable (not 0 bytes)
        - Row count matches expectations
        - Data structure is valid
        - Schema validation (if YAML config exists)

        Logs all validations to BigQuery and sends alerts for critical issues.
        """
        try:
            # Get output file path
            # FIX #1: Check opts['gcs_output_path'] first (where it's actually set in line 1887)
            file_path = self.opts.get('gcs_output_path') or self.opts.get('file_path', '')
            if not file_path:
                logger.warning("LAYER1_VALIDATION: No file_path found - skipping validation")
                return

            # Extract row count from self.data
            actual_rows = self._count_scraper_rows()

            # Get expected rows (for comparison)
            expected_rows = actual_rows  # For scrapers, actual = expected (no filtering yet)

            # Determine validation status
            validation_status = 'OK'
            issues = []
            reason = None
            is_acceptable = True

            # Check 1: Zero rows scraped
            if actual_rows == 0:
                reason = self._diagnose_zero_scraper_rows()
                is_acceptable = self._is_acceptable_zero_scraper_rows(reason)

                if not is_acceptable:
                    validation_status = 'CRITICAL'
                    issues.append('zero_rows')
                else:
                    validation_status = 'INFO'
                    issues.append('zero_rows_acceptable')

            # Check 2: File size (if we can get it)
            file_size = getattr(self, 'export_file_size', 0)
            if file_size == 0 and actual_rows > 0:
                validation_status = 'WARNING'
                issues.append('file_size_zero')
                reason = f"File exported {actual_rows} rows but size is 0 bytes"

            # Check 3: Schema-based validation (if config exists)
            schema_result = self._validate_with_schema()
            if schema_result:
                if not schema_result.passed:
                    if schema_result.errors > 0:
                        validation_status = 'ERROR'
                    elif schema_result.warnings > 0 and validation_status == 'OK':
                        validation_status = 'WARNING'

                    # Add schema issues to the list
                    for issue in schema_result.issues:
                        issues.append(f"schema:{issue.check_name}")

                    if not reason and schema_result.issues:
                        reason = schema_result.issues[0].message

            # Create validation result
            validation_result = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'scraper_name': self.__class__.__name__,
                'run_id': getattr(self, 'run_id', None),
                'file_path': file_path,
                'file_size': file_size,
                'row_count': actual_rows,
                'expected_rows': expected_rows,
                'validation_status': validation_status,
                'issues': ','.join(issues) if issues else None,
                'reason': reason,
                'is_acceptable': is_acceptable,
                'schema_validated': schema_result is not None,
                'schema_errors': schema_result.errors if schema_result else 0,
                'schema_warnings': schema_result.warnings if schema_result else 0,
            }

            # Log to BigQuery monitoring table
            self._log_scraper_validation(validation_result)

            # Send alert if critical or error
            if validation_status in ('CRITICAL', 'ERROR'):
                self._send_scraper_alert(validation_result)

        except Exception as e:
            # Don't fail scraper if validation fails
            # FIX #3: Change to ERROR level with stack trace for visibility
            logger.error(f"LAYER1_VALIDATION: Validation failed - {e}", exc_info=True)

    def _validate_with_schema(self):
        """
        Validate scraper output using YAML schema configuration.

        Returns:
            ValidationResult or None if no schema config exists
        """
        try:
            from validation.validators.scrapers import ScraperOutputValidator
        except ImportError:
            logger.debug("Schema validation module not available")
            return None

        # Derive scraper name from class name for schema lookup
        scraper_name = self._get_schema_name()

        try:
            validator = ScraperOutputValidator(scraper_name)

            # If no config was loaded, skip validation
            if not validator.config:
                logger.debug(f"No schema config for {scraper_name}")
                return None

            # Run validation
            result = validator.validate(self.data, self.opts)

            # Log results
            if result.passed:
                logger.info(f"SCHEMA_VALIDATION: Passed for {scraper_name} ({result.row_count} rows)")
            else:
                logger.warning(
                    f"SCHEMA_VALIDATION: Issues for {scraper_name} - "
                    f"{result.errors} errors, {result.warnings} warnings"
                )
                for issue in result.issues[:5]:  # Log first 5 issues
                    logger.warning(f"  - {issue.check_name}: {issue.message}")

            return result

        except Exception as e:
            logger.debug(f"Schema validation skipped for {scraper_name}: {e}")
            return None

    def _get_schema_name(self) -> str:
        """
        Get the schema name for this scraper.

        Converts class name to schema config name:
        - GetEspnBoxscore -> espn_boxscore
        - GetNbaComScoreboardV2 -> nbac_scoreboard_v2
        - BettingProsPlayerProps -> bettingpros_player_props
        """
        import re

        class_name = self.__class__.__name__

        # Remove 'Get' prefix if present
        if class_name.startswith('Get'):
            class_name = class_name[3:]

        # Convert CamelCase to snake_case
        name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', class_name)
        name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

        # Apply standard source prefixes
        name = name.replace('nba_com_', 'nbac_')
        name = name.replace('odds_api_', 'oddsa_')
        name = name.replace('ball_dont_lie_', 'bdl_')
        name = name.replace('big_data_ball_', 'bdb_')
        name = name.replace('betting_pros_', 'bettingpros_')

        return name

    def _count_scraper_rows(self) -> int:
        """Count rows in scraper output data."""
        if not hasattr(self, 'data') or not self.data:
            return 0

        # Try different patterns to find record count
        # Pattern 1: Direct list
        if isinstance(self.data, list):
            return len(self.data)

        # Pattern 2: dict with 'records' key
        if isinstance(self.data, dict):
            if 'records' in self.data:
                return len(self.data['records']) if isinstance(self.data['records'], list) else 0
            if 'games' in self.data:
                return len(self.data['games']) if isinstance(self.data['games'], list) else 0
            if 'players' in self.data:
                return len(self.data['players']) if isinstance(self.data['players'], list) else 0
            if 'rowCount' in self.data:  # OddsAPI pattern
                return self.data['rowCount']
            if 'rows' in self.data:
                return len(self.data['rows']) if isinstance(self.data['rows'], list) else 0

        return 0

    def _diagnose_zero_scraper_rows(self) -> str:
        """Diagnose why scraper returned 0 rows."""
        reasons = []

        # Check if API returned empty response
        if not hasattr(self, 'decoded_data') or not self.decoded_data:
            reasons.append("API returned empty response")

        # Check if this is expected (no games scheduled)
        game_date = self.opts.get('game_date') or self.opts.get('date')
        if game_date:
            # For game-based scrapers, check if games expected
            if 'game' in self.__class__.__name__.lower() or 'boxscore' in self.__class__.__name__.lower():
                reasons.append(f"No games returned by API for {game_date}")

        # Check if this is a known pattern
        if hasattr(self, 'data') and isinstance(self.data, dict):
            if self.data.get('is_empty_report'):
                reasons.append("Empty report flag set (intentional)")

        return " | ".join(reasons) if reasons else "API returned 0 records - may not have data yet"

    def _is_acceptable_zero_scraper_rows(self, reason: str) -> bool:
        """Determine if 0 rows from scraper is acceptable."""
        acceptable_patterns = [
            "is_empty_report",
            "Empty report flag",
            "No games scheduled",
            "Off-season",
            "may not have data yet",
            "API delay"
        ]

        reason_lower = reason.lower()
        return any(pattern.lower() in reason_lower for pattern in acceptable_patterns)

    def _log_scraper_validation(self, validation_result: dict) -> None:
        """Log scraper validation to BigQuery monitoring table."""
        try:
            from google.cloud import bigquery

            # Only log if we have valid credentials
            # FIX #2: Add error logging instead of silent return
            try:
                bq_client = bigquery.Client()
            except Exception as e:
                logger.error(f"LAYER1_VALIDATION: Cannot create BigQuery client - {e}")
                return

            # Use batch loading to avoid streaming buffer issues
            from shared.utils.bigquery_utils import insert_bigquery_rows
            from shared.config.sport_config import get_orchestration_dataset
            orchestration_dataset = get_orchestration_dataset()
            table_id = f"{orchestration_dataset}.scraper_output_validation"

            success = insert_bigquery_rows(table_id, [validation_result])
            if not success:
                logger.warning(f"LAYER1_VALIDATION: Failed to insert to BigQuery")
            else:
                # FIX #4: Add success logging for visibility
                logger.info(f"LAYER1_VALIDATION: Successfully logged to BigQuery - status: {validation_result.get('validation_status')}, rows: {validation_result.get('row_count')}")

        except Exception as e:
            # FIX #3: Change to ERROR level for visibility
            logger.error(f"LAYER1_VALIDATION: Could not log to BigQuery - {e}", exc_info=True)

    def _send_scraper_alert(self, validation_result: dict) -> None:
        """Send alert for critical scraper validation issues."""
        try:
            from shared.utils.notification_system import notify_warning

            notify_warning(
                title=f"⚠️ {validation_result['scraper_name']}: Zero Rows Scraped",
                message=f"Scraper returned 0 rows from API",
                details={
                    'scraper': validation_result['scraper_name'],
                    'reason': validation_result['reason'],
                    'file_path': validation_result['file_path'],
                    'run_id': validation_result['run_id'],
                    'validation_status': validation_result['validation_status'],
                    'detection_layer': 'Layer 1: Scraper Output Validation',
                    'detection_time': validation_result['timestamp']
                }
            )
        except Exception as e:
            logger.warning(f"Failed to send scraper alert: {e}")

    def _validate_phase1_boundary(self) -> None:
        """
        LIGHTWEIGHT Phase 1→2 boundary validation.

        Performs basic sanity checks before data flows to Phase 2:
        - Data is non-empty
        - Expected schema fields present (if applicable)
        - Game count reasonable (> 0, < 30 for NBA)

        Mode: WARNING (logs issues but doesn't block export)

        This catches obvious data quality issues before Phase 2 processors
        start work, preventing wasted processing time.
        """
        try:
            # Skip if no data
            if not hasattr(self, 'data') or self.data is None:
                logger.warning("PHASE1_BOUNDARY: No data to validate")
                return

            validation_issues = []

            # Check 1: Non-empty data
            row_count = self._count_scraper_rows()
            if row_count == 0:
                validation_issues.append("Data is empty (0 rows)")

            # Check 2: Reasonable game count (if applicable)
            if isinstance(self.data, dict):
                # Check for game-related data structures
                if 'games' in self.data:
                    games = self.data['games']
                    if isinstance(games, list):
                        game_count = len(games)
                        if game_count > 30:  # NBA has max ~15 games per day
                            validation_issues.append(
                                f"Unusual game count: {game_count} (expected < 30)"
                            )

                # Check 3: Expected schema fields present (lightweight)
                # Only check for very basic fields to avoid false positives
                scraper_name = self.__class__.__name__.lower()

                if 'game' in scraper_name:
                    # Game-related scrapers should have either 'games' or 'records'
                    if 'games' not in self.data and 'records' not in self.data and 'rows' not in self.data:
                        validation_issues.append(
                            "Game scraper missing expected fields (games/records/rows)"
                        )

                elif 'player' in scraper_name:
                    # Player-related scrapers should have player data
                    if 'players' not in self.data and 'records' not in self.data and 'rows' not in self.data:
                        validation_issues.append(
                            "Player scraper missing expected fields (players/records/rows)"
                        )

            # Log validation results
            if validation_issues:
                logger.warning(
                    f"PHASE1_BOUNDARY: Validation found {len(validation_issues)} issues "
                    f"for {self.__class__.__name__}: {validation_issues}"
                )

                # Send notification for critical issues (but don't block)
                try:
                    from shared.utils.notification_system import notify_warning
                    notify_warning(
                        title=f"Phase 1→2 Boundary Validation Warning",
                        message=f"{self.__class__.__name__} has data quality concerns",
                        details={
                            'scraper': self.__class__.__name__,
                            'issues': validation_issues,
                            'row_count': row_count,
                            'run_id': self.run_id,
                            'detection_layer': 'Phase 1→2 Boundary Validation',
                            'severity': 'warning',
                            'action': 'Data exported to Phase 2, but may cause processing issues'
                        }
                    )
                except Exception as notify_error:
                    logger.warning(f"Failed to send Phase 1 boundary validation notification: {notify_error}")
            else:
                logger.debug(f"PHASE1_BOUNDARY: Validation passed for {self.__class__.__name__}")

        except Exception as e:
            # Don't fail scraper if validation framework has issues
            logger.error(f"PHASE1_BOUNDARY: Validation framework error (non-blocking): {e}", exc_info=True)

    def validate_download_data(self):
        """
        Validate the downloaded and decoded data before transformation.

        Subclasses should override this method to add custom validation logic
        specific to their data format (e.g., check required fields, verify
        data structure, validate date ranges).

        Skips validation for "no data" success cases (when API returns 403
        but scraper is configured to treat this as valid).

        Raises:
            DownloadDataException: If validation fails (empty data, etc.)

        Example:
            def validate_download_data(self):
                super().validate_download_data()
                if 'scoreboard' not in self.decoded_data:
                    raise DownloadDataException("Missing 'scoreboard' key")
        """
        # NEW: Skip validation if this is a "no data" success case
        if hasattr(self, '_no_data_success') and self._no_data_success:
            logger.info("✅ Skipping validation for 'no data' success case")
            return

        # EXISTING validation logic:
        if not self.decoded_data:
            try:
                from shared.utils.notification_system import notify_warning
                notify_warning(
                    title=f"Scraper Validation Warning: {self.__class__.__name__}",
                    message="Downloaded data is empty",
                    details={
                        'scraper': self.__class__.__name__,
                        'run_id': self.run_id,
                        'url': getattr(self, 'url', 'unknown'),
                        'decoded_data': str(self.decoded_data)[:200]
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            from scrapers.utils.exceptions import DownloadDataException
            raise DownloadDataException("Downloaded data is empty or None.")
