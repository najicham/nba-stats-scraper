"""
Service Error Logger - Usage Examples

Demonstrates how to use the ServiceErrorLogger utility for centralized
error logging across all services.

This script provides examples for:
1. Basic error logging
2. TransformProcessorBase integration
3. Cloud Function integration pattern
4. Batch error logging
5. Error categorization

Note: This is a demonstration script. In production, the ServiceErrorLogger
is automatically integrated into TransformProcessorBase.report_error().

Created: 2026-01-28
"""

import os
import sys
from datetime import datetime, date
from typing import Dict, Any

# Add project root to path using relative path from this file
_current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_current_dir, '..'))

from shared.utils.service_error_logger import ServiceErrorLogger


# =============================================================================
# Example 1: Basic Error Logging
# =============================================================================

def example_1_basic_logging():
    """Example 1: Basic error logging with minimal context."""
    print("\n" + "="*80)
    print("Example 1: Basic Error Logging")
    print("="*80)

    logger = ServiceErrorLogger()

    try:
        # Simulate some processing that fails
        result = 10 / 0
    except Exception as e:
        # Log the error
        success = logger.log_error(
            service_name="ExampleService",
            error=e,
            context={"game_date": "2024-11-15"}
        )
        print(f"Error logged: {success}")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {e}")


# =============================================================================
# Example 2: TransformProcessorBase Integration
# =============================================================================

def example_2_transform_processor_integration():
    """Example 2: How TransformProcessorBase integrates ServiceErrorLogger."""
    print("\n" + "="*80)
    print("Example 2: TransformProcessorBase Integration")
    print("="*80)

    print("""
The ServiceErrorLogger is automatically integrated into TransformProcessorBase.

When you call processor.report_error(exc), it now:
1. Reports to Sentry (as before)
2. Logs to BigQuery service_errors table (NEW)

Example code in TransformProcessorBase:

    def report_error(self, exc: Exception) -> None:
        # Report to Sentry
        sentry_sdk.capture_exception(exc)

        # Report to BigQuery service_errors table
        from shared.utils.service_error_logger import ServiceErrorLogger
        error_logger = ServiceErrorLogger()
        error_logger.log_error(
            service_name=self.processor_name,
            error=exc,
            context={{
                "game_date": self.opts.get("game_date"),
                "phase": self.PHASE,
                "processor_name": self.processor_name,
                "correlation_id": self.correlation_id,
                "stats": self.stats,
            }},
            step=self._get_current_step()
        )

No changes needed in child processors - they automatically get error logging!
    """)


# =============================================================================
# Example 3: Cloud Function Integration Pattern
# =============================================================================

def example_3_cloud_function_pattern():
    """Example 3: Pattern for Cloud Function error logging."""
    print("\n" + "="*80)
    print("Example 3: Cloud Function Integration Pattern")
    print("="*80)

    print("""
For Cloud Functions, wrap your function with error logging:

    from shared.utils.service_error_logger import ServiceErrorLogger

    def my_cloud_function(request):
        error_logger = ServiceErrorLogger()

        try:
            # Cloud Function logic here
            data = request.get_json()
            result = process_data(data)
            return {{'status': 'success', 'result': result}}

        except Exception as e:
            # Log error to BigQuery
            error_logger.log_error(
                service_name="my_cloud_function",
                error=e,
                context={{
                    "game_date": data.get("game_date"),
                    "phase": "phase_3_analytics",
                    "correlation_id": request.headers.get("X-Correlation-ID"),
                }}
            )
            # Re-raise or return error response
            return {{'status': 'error', 'message': str(e)}}, 500

Or create a decorator:

    def with_error_logging(service_name: str):
        def decorator(func):
            def wrapper(*args, **kwargs):
                error_logger = ServiceErrorLogger()
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_logger.log_error(
                        service_name=service_name,
                        error=e,
                        context={{'request': args[0] if args else None}}
                    )
                    raise
            return wrapper
        return decorator

    @with_error_logging("my_function")
    def my_function(request):
        # function logic
        pass
    """)


# =============================================================================
# Example 4: Full Context Error Logging
# =============================================================================

def example_4_full_context():
    """Example 4: Error logging with complete context."""
    print("\n" + "="*80)
    print("Example 4: Full Context Error Logging")
    print("="*80)

    logger = ServiceErrorLogger()

    try:
        # Simulate processing with rich context
        game_date = date(2024, 11, 15)
        raise RuntimeError("Player stats calculation failed: Invalid data format")

    except Exception as e:
        success = logger.log_error(
            service_name="PlayerGameSummaryProcessor",
            error=e,
            context={
                "game_date": game_date,
                "phase": "phase_3_analytics",
                "processor_name": "PlayerGameSummaryProcessor",
                "correlation_id": "abc123-def456",
                "stats": {
                    "players_processed": 42,
                    "games_processed": 8,
                }
            },
            step="transform",
            recovery_attempted=True,
            recovery_successful=False
        )
        print(f"Full context error logged: {success}")
        print(f"Service: PlayerGameSummaryProcessor")
        print(f"Game date: {game_date}")
        print(f"Phase: phase_3_analytics")
        print(f"Recovery attempted: True")
        print(f"Recovery successful: False")


# =============================================================================
# Example 5: Batch Error Logging
# =============================================================================

def example_5_batch_logging():
    """Example 5: Efficient batch error logging."""
    print("\n" + "="*80)
    print("Example 5: Batch Error Logging")
    print("="*80)

    logger = ServiceErrorLogger()

    # Simulate multiple errors from processing
    errors = [
        (ValueError("Invalid score for game 1"), {"game_date": "2024-11-15"}),
        (KeyError("Missing player_id for game 2"), {"game_date": "2024-11-16"}),
        (RuntimeError("Database timeout for game 3"), {"game_date": "2024-11-17"}),
    ]

    count = logger.log_batch_errors(
        service_name="GameDataProcessor",
        errors=errors,
        step="transform"
    )

    print(f"Batch logged: {count}/{len(errors)} errors")
    print("Errors:")
    for i, (error, context) in enumerate(errors, 1):
        print(f"  {i}. {type(error).__name__}: {error} (game_date: {context['game_date']})")


# =============================================================================
# Example 6: Error Categorization
# =============================================================================

def example_6_error_categorization():
    """Example 6: Automatic error categorization."""
    print("\n" + "="*80)
    print("Example 6: Error Categorization")
    print("="*80)

    logger = ServiceErrorLogger()

    # The logger uses failure_categorization.py to categorize errors
    test_errors = [
        (FileNotFoundError("no data available"), "Expected - no data"),
        (ValueError("Invalid data format"), "Real processing error"),
        (TimeoutError("Operation timed out"), "Timeout error"),
    ]

    print("\nError Categorization Examples:")
    for error, description in test_errors:
        try:
            raise error
        except Exception as e:
            # This would log to BigQuery in production
            print(f"\n{description}:")
            print(f"  Error: {type(e).__name__}: {e}")
            print(f"  Category: (automatically categorized by failure_categorization.py)")
            print(f"  - FileNotFoundError('no data') → 'no_data_available' (severity: info)")
            print(f"  - ValueError('invalid data') → 'processing_error' (severity: critical)")
            print(f"  - TimeoutError → 'timeout' (severity: warning)")


# =============================================================================
# Example 7: Testing Mode
# =============================================================================

def example_7_testing_mode():
    """Example 7: Disable logging for tests."""
    print("\n" + "="*80)
    print("Example 7: Testing Mode")
    print("="*80)

    # Disable logging for tests
    logger = ServiceErrorLogger(enabled=False)

    try:
        result = 10 / 0
    except Exception as e:
        success = logger.log_error(
            service_name="TestService",
            error=e
        )
        print(f"Logging enabled: False")
        print(f"Log attempt result: {success}")
        print("(No actual BigQuery insert was made)")


# =============================================================================
# Main: Run all examples
# =============================================================================

def main():
    """Run all examples."""
    print("""
╔════════════════════════════════════════════════════════════════════════════╗
║                                                                            ║
║                    SERVICE ERROR LOGGER - USAGE EXAMPLES                   ║
║                                                                            ║
║  Centralized error logging for all 53+ services across the platform       ║
║  Part of validation-coverage-improvements project                         ║
║                                                                            ║
╚════════════════════════════════════════════════════════════════════════════╝
    """)

    print("\nNOTE: These examples use enabled=False to avoid actual BigQuery inserts.")
    print("In production, errors are automatically logged to:")
    print("  → nba-props-platform.nba_orchestration.service_errors\n")

    # Override to disabled mode for examples
    global ServiceErrorLogger
    original_init = ServiceErrorLogger.__init__

    def disabled_init(self, *args, **kwargs):
        kwargs['enabled'] = False
        original_init(self, *args, **kwargs)

    ServiceErrorLogger.__init__ = disabled_init

    # Run examples
    example_1_basic_logging()
    example_2_transform_processor_integration()
    example_3_cloud_function_pattern()
    example_4_full_context()
    example_5_batch_logging()
    example_6_error_categorization()
    example_7_testing_mode()

    print("\n" + "="*80)
    print("Examples Complete!")
    print("="*80)
    print("\nFor production usage:")
    print("1. TransformProcessorBase: Already integrated (no changes needed)")
    print("2. Cloud Functions: Add ServiceErrorLogger in exception handlers")
    print("3. Other services: Import and use ServiceErrorLogger as shown above")
    print("\nFor more info, see:")
    print("  - shared/utils/service_error_logger.py")
    print("  - docs/08-projects/current/validation-coverage-improvements/05-INVESTIGATION-FINDINGS.md")
    print()


if __name__ == "__main__":
    main()
