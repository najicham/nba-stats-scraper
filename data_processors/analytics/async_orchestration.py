"""
Path: data_processors/analytics/async_orchestration.py

Async Orchestration Utilities for Phase 3 Analytics Processors.

This module provides utilities for running analytics processors with async
support, enabling the orchestration layer to take advantage of async processors
when available.

Key Features:
- Auto-detection of async-capable processors
- Fallback to sync execution for non-async processors
- Parallel execution of multiple processors with async support
- Performance monitoring and logging

Usage:
    from data_processors.analytics.async_orchestration import (
        run_processor_with_async_support,
        run_processors_concurrently
    )

    # Run a single processor (auto-detects async capability)
    result = run_processor_with_async_support(
        UpcomingPlayerGameContextProcessor,
        opts={'start_date': '2026-01-23', 'end_date': '2026-01-23'}
    )

    # Run multiple processors concurrently
    results = run_processors_concurrently(
        [Processor1, Processor2, Processor3],
        opts={'start_date': '2026-01-23', 'end_date': '2026-01-23'},
        use_async=True
    )

Version: 1.0
Created: January 2026
"""

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


# Registry of async processor alternatives
# Maps sync processor class to its async counterpart
ASYNC_PROCESSOR_REGISTRY: Dict[str, Type] = {}


def register_async_processor(sync_class_name: str, async_class: Type) -> None:
    """
    Register an async processor as the alternative for a sync processor.

    Args:
        sync_class_name: Name of the sync processor class
        async_class: The async processor class to use instead
    """
    ASYNC_PROCESSOR_REGISTRY[sync_class_name] = async_class
    logger.debug(f"Registered async processor: {sync_class_name} -> {async_class.__name__}")


def get_async_processor(processor_class: Type) -> Optional[Type]:
    """
    Get the async version of a processor if available.

    Args:
        processor_class: The sync processor class

    Returns:
        The async processor class if registered, None otherwise
    """
    return ASYNC_PROCESSOR_REGISTRY.get(processor_class.__name__)


def is_async_processor(processor_class: Type) -> bool:
    """
    Check if a processor class is async-capable.

    A processor is considered async-capable if:
    1. It inherits from AsyncAnalyticsProcessorBase, OR
    2. It has an extract_raw_data_async method

    Args:
        processor_class: The processor class to check

    Returns:
        True if the processor supports async execution
    """
    # Check for async method
    if hasattr(processor_class, 'extract_raw_data_async'):
        return True

    # Check parent classes
    try:
        from data_processors.analytics.async_analytics_base import AsyncAnalyticsProcessorBase
        return issubclass(processor_class, AsyncAnalyticsProcessorBase)
    except ImportError:
        return False


def run_processor_with_async_support(
    processor_class: Type,
    opts: Dict[str, Any],
    prefer_async: bool = True
) -> Dict[str, Any]:
    """
    Run a processor, using async version if available and preferred.

    This function provides a unified interface for running processors that
    automatically uses async execution when beneficial.

    Args:
        processor_class: The processor class to run
        opts: Options dict passed to processor.run()
        prefer_async: If True, use async version when available

    Returns:
        Dict with processing results:
        {
            'processor': str (processor name),
            'status': str ('success', 'error', 'exception'),
            'stats': dict (processor stats if available),
            'error': str (error message if failed),
            'async_used': bool (whether async execution was used),
            'elapsed_seconds': float
        }
    """
    start_time = time.time()
    processor_name = processor_class.__name__
    async_used = False

    try:
        # Check if we should use async version
        effective_class = processor_class

        if prefer_async:
            # Check for registered async alternative
            async_class = get_async_processor(processor_class)
            if async_class:
                effective_class = async_class
                async_used = True
                logger.info(f"Using registered async processor: {async_class.__name__}")
            elif is_async_processor(processor_class):
                async_used = True
                logger.info(f"Processor {processor_name} is natively async-capable")

        # Instantiate and run the processor
        logger.info(f"Running {effective_class.__name__} for {opts.get('start_date')} (async={async_used})")
        processor = effective_class()
        success = processor.run(opts)

        elapsed = time.time() - start_time

        if success:
            stats = {}
            if hasattr(processor, 'get_analytics_stats'):
                stats = processor.get_analytics_stats()

            logger.info(f"Successfully ran {processor_name} in {elapsed:.2f}s: {stats}")
            return {
                "processor": processor_name,
                "status": "success",
                "stats": stats,
                "async_used": async_used,
                "elapsed_seconds": round(elapsed, 2)
            }
        else:
            logger.error(f"Failed to run {processor_name}")
            return {
                "processor": processor_name,
                "status": "error",
                "async_used": async_used,
                "elapsed_seconds": round(elapsed, 2)
            }

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"Exception running {processor_name}: {e}", exc_info=True)
        return {
            "processor": processor_name,
            "status": "exception",
            "error": str(e),
            "async_used": async_used,
            "elapsed_seconds": round(elapsed, 2)
        }


def run_processors_concurrently(
    processor_classes: List[Type],
    opts: Dict[str, Any],
    max_workers: int = 5,
    timeout_seconds: int = 600,
    prefer_async: bool = True
) -> List[Dict[str, Any]]:
    """
    Run multiple processors concurrently using ThreadPoolExecutor.

    This function runs multiple processors in parallel, with each processor
    potentially using async execution internally for its data extraction.

    Args:
        processor_classes: List of processor classes to run
        opts: Options dict passed to each processor.run()
        max_workers: Maximum number of concurrent processors
        timeout_seconds: Timeout per processor in seconds
        prefer_async: If True, use async versions when available

    Returns:
        List of result dicts, one per processor
    """
    if not processor_classes:
        return []

    logger.info(
        f"Running {len(processor_classes)} processors concurrently "
        f"(max_workers={max_workers}, prefer_async={prefer_async})"
    )

    results = []
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all processors
        futures = {
            executor.submit(
                run_processor_with_async_support,
                processor_class,
                opts,
                prefer_async
            ): processor_class
            for processor_class in processor_classes
        }

        # Collect results as they complete
        for future in as_completed(futures, timeout=timeout_seconds):
            processor_class = futures[future]

            try:
                result = future.result(timeout=timeout_seconds)
                results.append(result)
            except TimeoutError:
                logger.error(f"Processor {processor_class.__name__} timed out")
                results.append({
                    "processor": processor_class.__name__,
                    "status": "timeout",
                    "error": f"Timed out after {timeout_seconds}s"
                })
            except Exception as e:
                logger.error(f"Error getting result from {processor_class.__name__}: {e}")
                results.append({
                    "processor": processor_class.__name__,
                    "status": "exception",
                    "error": str(e)
                })

    total_elapsed = time.time() - start_time
    successes = sum(1 for r in results if r.get('status') == 'success')
    async_count = sum(1 for r in results if r.get('async_used'))

    logger.info(
        f"Completed {len(results)} processors in {total_elapsed:.2f}s "
        f"({successes} succeeded, {async_count} used async)"
    )

    return results


async def run_processors_async(
    processor_classes: List[Type],
    opts: Dict[str, Any],
    max_concurrent: int = 5
) -> List[Dict[str, Any]]:
    """
    Run multiple processors using native async concurrency.

    This is an async alternative to run_processors_concurrently that uses
    asyncio directly instead of ThreadPoolExecutor. Useful when called
    from an async context.

    Args:
        processor_classes: List of processor classes to run
        opts: Options dict passed to each processor.run()
        max_concurrent: Maximum number of concurrent processors

    Returns:
        List of result dicts, one per processor
    """
    if not processor_classes:
        return []

    logger.info(f"[ASYNC] Running {len(processor_classes)} processors (max_concurrent={max_concurrent})")

    semaphore = asyncio.Semaphore(max_concurrent)

    async def run_single(processor_class: Type) -> Dict[str, Any]:
        async with semaphore:
            # Run in executor since processor.run() is sync
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                run_processor_with_async_support,
                processor_class,
                opts,
                True  # prefer_async
            )

    tasks = [run_single(pc) for pc in processor_classes]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Convert exceptions to error results
    final_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            final_results.append({
                "processor": processor_classes[i].__name__,
                "status": "exception",
                "error": str(result)
            })
        else:
            final_results.append(result)

    return final_results


# Auto-register async processors
def _auto_register_async_processors():
    """
    Auto-register known async processor alternatives.

    This is called on module import to populate ASYNC_PROCESSOR_REGISTRY.
    """
    try:
        from data_processors.analytics.upcoming_player_game_context.async_upcoming_player_game_context_processor import (
            AsyncUpcomingPlayerGameContextProcessor
        )
        register_async_processor(
            'UpcomingPlayerGameContextProcessor',
            AsyncUpcomingPlayerGameContextProcessor
        )
        logger.debug("Auto-registered AsyncUpcomingPlayerGameContextProcessor")
    except ImportError as e:
        logger.debug(f"Could not auto-register async processors: {e}")


# Run auto-registration on import
_auto_register_async_processors()
