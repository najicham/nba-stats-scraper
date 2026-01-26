"""
orchestration_loader.py

Provides lazy-loaded orchestration components for the main scraper service.

This module ensures orchestration components (controller, executor, cleanup, locker, config)
are only imported and instantiated when first accessed, reducing startup overhead.

Path: scrapers/services/orchestration_loader.py
"""

from orchestration.master_controller import MasterWorkflowController
from orchestration.workflow_executor import WorkflowExecutor
from orchestration.cleanup_processor import CleanupProcessor
from orchestration.schedule_locker import DailyScheduleLocker
from orchestration.config_loader import WorkflowConfig


# Module-level cached instances
_controller = None
_executor = None
_cleanup = None
_locker = None
_config = None


def get_controller():
    """
    Get or create the MasterWorkflowController instance.

    Lazy loads the controller on first access to avoid startup overhead.
    Subsequent calls return the cached instance.

    Returns:
        MasterWorkflowController: The workflow controller instance
    """
    global _controller
    if _controller is None:
        _controller = MasterWorkflowController()
    return _controller


def get_executor():
    """
    Get or create the WorkflowExecutor instance.

    Lazy loads the executor on first access to avoid startup overhead.
    Subsequent calls return the cached instance.

    Returns:
        WorkflowExecutor: The workflow executor instance
    """
    global _executor
    if _executor is None:
        _executor = WorkflowExecutor()
    return _executor


def get_cleanup():
    """
    Get or create the CleanupProcessor instance.

    Lazy loads the cleanup processor on first access to avoid startup overhead.
    Subsequent calls return the cached instance.

    Returns:
        CleanupProcessor: The cleanup processor instance
    """
    global _cleanup
    if _cleanup is None:
        _cleanup = CleanupProcessor()
    return _cleanup


def get_locker():
    """
    Get or create the DailyScheduleLocker instance.

    Lazy loads the schedule locker on first access to avoid startup overhead.
    Subsequent calls return the cached instance.

    Returns:
        DailyScheduleLocker: The schedule locker instance
    """
    global _locker
    if _locker is None:
        _locker = DailyScheduleLocker()
    return _locker


def get_config():
    """
    Get or create the WorkflowConfig instance.

    Lazy loads the workflow config on first access to avoid startup overhead.
    Subsequent calls return the cached instance.

    Returns:
        WorkflowConfig: The workflow config instance
    """
    global _config
    if _config is None:
        _config = WorkflowConfig()
    return _config
