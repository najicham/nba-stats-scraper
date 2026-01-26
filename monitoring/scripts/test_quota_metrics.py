#!/usr/bin/env python3
"""
Test script for pipeline quota usage metrics.

This script generates test events to verify:
1. Metrics are being tracked correctly
2. Batching is working as expected
3. Flush latency is reasonable
4. No flush failures occur

Usage:
    python test_quota_metrics.py [--events 100] [--dry-run]

Example:
    # Generate 100 test events
    python test_quota_metrics.py --events 100

    # Dry run (no BigQuery writes)
    python test_quota_metrics.py --events 50 --dry-run
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.utils.pipeline_logger import (
    log_pipeline_event,
    PipelineEventType,
    get_buffer_metrics,
    flush_event_buffer,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_basic_metrics(num_events: int = 100, dry_run: bool = False) -> bool:
    """
    Test basic metrics collection.

    Generates events and verifies metrics are tracked correctly.
    """
    logger.info("=" * 60)
    logger.info("Test 1: Basic Metrics Collection")
    logger.info("=" * 60)

    # Get initial metrics
    initial_metrics = get_buffer_metrics()
    logger.info(f"Initial metrics: {initial_metrics}")

    # Generate test events
    logger.info(f"Generating {num_events} test events...")
    start_time = time.time()

    for i in range(num_events):
        log_pipeline_event(
            event_type=PipelineEventType.PROCESSOR_START,
            phase='test_phase',
            processor_name='test_processor',
            game_date='2026-01-26',
            correlation_id=f'test-{i}',
            metadata={'test_run': True, 'event_num': i},
            dry_run=dry_run
        )

        # Log progress every 25 events
        if (i + 1) % 25 == 0:
            logger.info(f"Generated {i + 1}/{num_events} events...")

    elapsed_time = time.time() - start_time
    logger.info(f"Generated {num_events} events in {elapsed_time:.2f}s")

    # Force flush to ensure all events are written
    logger.info("Flushing buffer...")
    flush_success = flush_event_buffer()
    logger.info(f"Flush {'succeeded' if flush_success else 'failed'}")

    # Get final metrics
    time.sleep(1)  # Give buffer time to update
    final_metrics = get_buffer_metrics()
    logger.info(f"Final metrics: {final_metrics}")

    # Verify metrics
    logger.info("\nVerifying metrics...")
    events_added = final_metrics['events_buffered_count'] - initial_metrics['events_buffered_count']
    flushes_added = final_metrics['batch_flush_count'] - initial_metrics['batch_flush_count']

    success = True

    # Check events buffered
    if events_added == num_events:
        logger.info(f"✓ Events buffered: {events_added} (expected: {num_events})")
    else:
        logger.error(f"✗ Events buffered: {events_added} (expected: {num_events})")
        success = False

    # Check batch flushes occurred
    if flushes_added > 0:
        logger.info(f"✓ Batch flushes: {flushes_added}")
    else:
        logger.warning(f"✗ No batch flushes occurred (expected > 0)")
        success = False

    # Check no failures
    if final_metrics['failed_flush_count'] == 0:
        logger.info(f"✓ No flush failures")
    else:
        logger.error(f"✗ Flush failures: {final_metrics['failed_flush_count']}")
        success = False

    # Check avg batch size is reasonable
    if final_metrics['avg_batch_size'] > 0:
        logger.info(f"✓ Average batch size: {final_metrics['avg_batch_size']}")
    else:
        logger.warning(f"✗ Invalid average batch size: {final_metrics['avg_batch_size']}")
        success = False

    # Check flush latency is reasonable (< 10s)
    if 0 < final_metrics['avg_flush_latency_ms'] < 10000:
        logger.info(f"✓ Average flush latency: {final_metrics['avg_flush_latency_ms']}ms")
    elif final_metrics['avg_flush_latency_ms'] == 0:
        logger.warning(f"✗ No flush latency recorded")
    else:
        logger.warning(f"⚠ High flush latency: {final_metrics['avg_flush_latency_ms']}ms")

    logger.info("")
    return success


def test_batching_efficiency(batch_size: int = 50) -> bool:
    """
    Test that batching reduces partition modifications.

    Compares single-write vs batch-write partition modifications.
    """
    logger.info("=" * 60)
    logger.info("Test 2: Batching Efficiency")
    logger.info("=" * 60)

    # Calculate expected efficiency
    num_events = 200
    expected_batches = (num_events + batch_size - 1) // batch_size  # Ceiling division

    logger.info(f"Testing with {num_events} events, batch_size={batch_size}")
    logger.info(f"Expected batches: {expected_batches}")
    logger.info(f"Expected partition mods savings: {num_events - expected_batches} "
                f"({(1 - expected_batches/num_events)*100:.1f}%)")

    # Run test
    initial_metrics = get_buffer_metrics()

    logger.info(f"Generating {num_events} events...")
    for i in range(num_events):
        log_pipeline_event(
            event_type=PipelineEventType.PROCESSOR_COMPLETE,
            phase='batch_test',
            processor_name='batch_test_processor',
            game_date='2026-01-26',
            duration_seconds=0.1,
            records_processed=10,
            dry_run=True  # Use dry run to avoid actual BigQuery writes
        )

    # Flush and measure
    flush_event_buffer()
    time.sleep(1)

    final_metrics = get_buffer_metrics()
    actual_batches = final_metrics['batch_flush_count'] - initial_metrics['batch_flush_count']
    actual_avg_batch_size = final_metrics['avg_batch_size']

    logger.info(f"\nActual batches: {actual_batches}")
    logger.info(f"Actual avg batch size: {actual_avg_batch_size}")

    # Verify efficiency
    success = True
    if abs(actual_batches - expected_batches) <= 1:  # Allow 1 batch difference
        logger.info(f"✓ Batching efficiency: ~{expected_batches} batches instead of {num_events} individual writes")
    else:
        logger.warning(f"⚠ Batching may not be optimal: {actual_batches} batches (expected ~{expected_batches})")
        success = False

    logger.info("")
    return success


def test_concurrent_logging() -> bool:
    """
    Test thread-safety with concurrent logging.
    """
    logger.info("=" * 60)
    logger.info("Test 3: Concurrent Logging (Thread Safety)")
    logger.info("=" * 60)

    import threading

    num_threads = 5
    events_per_thread = 20
    total_events = num_threads * events_per_thread

    logger.info(f"Testing {num_threads} threads, {events_per_thread} events each")

    initial_metrics = get_buffer_metrics()

    def log_events(thread_id: int):
        for i in range(events_per_thread):
            log_pipeline_event(
                event_type=PipelineEventType.PROCESSOR_START,
                phase='thread_test',
                processor_name=f'thread_{thread_id}_processor',
                game_date='2026-01-26',
                correlation_id=f'thread-{thread_id}-{i}',
                dry_run=True
            )

    # Start threads
    logger.info("Starting threads...")
    threads = []
    start_time = time.time()

    for t in range(num_threads):
        thread = threading.Thread(target=log_events, args=(t,))
        threads.append(thread)
        thread.start()

    # Wait for completion
    for thread in threads:
        thread.join()

    elapsed = time.time() - start_time
    logger.info(f"All threads completed in {elapsed:.2f}s")

    # Flush and verify
    flush_event_buffer()
    time.sleep(1)

    final_metrics = get_buffer_metrics()
    events_added = final_metrics['events_buffered_count'] - initial_metrics['events_buffered_count']

    # Verify all events logged
    success = True
    if events_added == total_events:
        logger.info(f"✓ All events logged: {events_added}/{total_events}")
    else:
        logger.error(f"✗ Events logged: {events_added}/{total_events} (some lost!)")
        success = False

    # Check for failures
    if final_metrics['failed_flush_count'] == 0:
        logger.info(f"✓ No flush failures in concurrent scenario")
    else:
        logger.error(f"✗ Flush failures: {final_metrics['failed_flush_count']}")
        success = False

    logger.info("")
    return success


def print_summary(results: dict):
    """Print test summary."""
    logger.info("=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)

    total_tests = len(results)
    passed_tests = sum(1 for r in results.values() if r)

    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.info(f"{status} - {test_name}")

    logger.info("")
    logger.info(f"Results: {passed_tests}/{total_tests} tests passed")

    if passed_tests == total_tests:
        logger.info("✓ All tests passed!")
        return 0
    else:
        logger.error(f"✗ {total_tests - passed_tests} test(s) failed")
        return 1


def main():
    parser = argparse.ArgumentParser(description='Test pipeline quota usage metrics')
    parser.add_argument('--events', type=int, default=100,
                        help='Number of test events to generate (default: 100)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Run in dry-run mode (no BigQuery writes)')
    parser.add_argument('--test', choices=['basic', 'batching', 'concurrent', 'all'],
                        default='all', help='Which test to run (default: all)')

    args = parser.parse_args()

    logger.info("Starting Pipeline Quota Metrics Tests")
    logger.info(f"Configuration: events={args.events}, dry_run={args.dry_run}")
    logger.info("")

    results = {}

    # Run selected tests
    if args.test in ['basic', 'all']:
        results['Basic Metrics'] = test_basic_metrics(args.events, args.dry_run)

    if args.test in ['batching', 'all']:
        results['Batching Efficiency'] = test_batching_efficiency()

    if args.test in ['concurrent', 'all']:
        results['Concurrent Logging'] = test_concurrent_logging()

    # Print summary
    exit_code = print_summary(results)
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
