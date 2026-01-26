"""
FILE: orchestration/workflow_timing.py

Utilities for calculating and validating workflow timing windows.

Used by validation scripts to determine if workflows have started yet,
avoiding false alarm failures when checking data availability.

Usage:
    from orchestration.workflow_timing import calculate_workflow_window, is_within_workflow_window

    window_start, window_end = calculate_workflow_window('betting_lines', game_times)
    if current_time < window_start:
        print("Workflow hasn't started yet - check back later")
"""

from datetime import datetime, timedelta
from typing import List, Tuple, Optional
import yaml
import os


def load_workflow_config(config_path: Optional[str] = None) -> dict:
    """
    Load workflow configuration from YAML file.

    Args:
        config_path: Path to workflows.yaml (default: config/workflows.yaml relative to project root)

    Returns:
        Parsed workflow configuration dictionary
    """
    if config_path is None:
        # Default to config/workflows.yaml relative to this file
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(project_root, 'config', 'workflows.yaml')

    with open(config_path) as f:
        return yaml.safe_load(f)


def calculate_workflow_window(
    workflow_name: str,
    game_times: List[datetime],
    config_path: Optional[str] = None
) -> Tuple[datetime, datetime]:
    """
    Calculate the start and end times for a workflow window.

    Args:
        workflow_name: Name of the workflow (e.g., 'betting_lines')
        game_times: List of game commence times as datetime objects
        config_path: Optional path to workflows.yaml

    Returns:
        (window_start, window_end) as datetime objects

    Raises:
        ValueError: If workflow not found or game_times is empty
    """
    if not game_times:
        raise ValueError("game_times cannot be empty")

    config = load_workflow_config(config_path)

    if workflow_name not in config['workflows']:
        raise ValueError(f"Workflow '{workflow_name}' not found in config")

    workflow = config['workflows'][workflow_name]
    schedule = workflow['schedule']

    # Calculate window start based on first game
    first_game = min(game_times)
    window_hours = schedule.get('window_before_game_hours', 6)
    window_start = first_game - timedelta(hours=window_hours)

    # Apply business hours constraints if present
    if 'business_hours' in schedule:
        bh_start = schedule['business_hours']['start']
        bh_end = schedule['business_hours']['end']

        # Clamp to business hours start
        bh_start_time = window_start.replace(hour=bh_start, minute=0, second=0, microsecond=0)
        if window_start < bh_start_time:
            window_start = bh_start_time

        # Window end is business hours end or last game time, whichever is earlier
        bh_end_time = first_game.replace(hour=bh_end, minute=0, second=0, microsecond=0)
        window_end = min(max(game_times), bh_end_time)
    else:
        # Window end is typically last game time
        window_end = max(game_times)

    return window_start, window_end


def get_expected_run_times(
    workflow_name: str,
    game_times: List[datetime],
    config_path: Optional[str] = None
) -> List[datetime]:
    """
    Calculate all expected run times for a workflow given game schedule.

    Args:
        workflow_name: Name of the workflow (e.g., 'betting_lines')
        game_times: List of game commence times as datetime objects
        config_path: Optional path to workflows.yaml

    Returns:
        List of datetime objects representing when workflow should run
    """
    window_start, window_end = calculate_workflow_window(workflow_name, game_times, config_path)

    config = load_workflow_config(config_path)
    workflow = config['workflows'][workflow_name]
    frequency_hours = workflow['schedule'].get('frequency_hours', 1)

    # Generate run times
    run_times = []
    current = window_start
    while current <= window_end:
        run_times.append(current)
        current += timedelta(hours=frequency_hours)

    return run_times


def is_within_workflow_window(
    workflow_name: str,
    check_time: datetime,
    game_times: List[datetime],
    config_path: Optional[str] = None
) -> bool:
    """
    Check if a given time is within the workflow's operating window.

    Args:
        workflow_name: Name of the workflow (e.g., 'betting_lines')
        check_time: Time to check
        game_times: List of game commence times as datetime objects
        config_path: Optional path to workflows.yaml

    Returns:
        True if check_time is within the workflow window, False otherwise
    """
    try:
        window_start, window_end = calculate_workflow_window(workflow_name, game_times, config_path)
        return window_start <= check_time <= window_end
    except (ValueError, KeyError):
        # If we can't determine the window, assume we're within it to avoid false alarms
        return True


def get_workflow_status_message(
    workflow_name: str,
    check_time: datetime,
    game_times: List[datetime],
    data_exists: bool,
    config_path: Optional[str] = None
) -> Tuple[str, str]:
    """
    Get a status message explaining workflow timing and data availability.

    Args:
        workflow_name: Name of the workflow (e.g., 'betting_lines')
        check_time: Current time
        game_times: List of game commence times
        data_exists: Whether data was found
        config_path: Optional path to workflows.yaml

    Returns:
        (status, message) where status is one of:
        - 'TOO_EARLY': Before workflow window
        - 'WITHIN_LAG': Within expected collection lag
        - 'DATA_FOUND': Data exists as expected
        - 'FAILURE': Data missing after expected collection time
        - 'UNKNOWN': Cannot determine status
    """
    try:
        window_start, window_end = calculate_workflow_window(workflow_name, game_times, config_path)
    except (ValueError, KeyError) as e:
        return ('UNKNOWN', f"Cannot determine workflow timing: {e}")

    # Format times for display
    window_start_str = window_start.strftime('%I:%M %p')
    first_game_str = min(game_times).strftime('%I:%M %p')

    # Before window starts
    if check_time < window_start:
        hours_until_start = (window_start - check_time).total_seconds() / 3600
        return (
            'TOO_EARLY',
            f"Workflow '{workflow_name}' window opens at {window_start_str} "
            f"({hours_until_start:.1f}h from now, for game at {first_game_str}). "
            f"Check again after window opens."
        )

    # Within expected lag (2 hours after window start)
    lag_threshold = window_start + timedelta(hours=2)
    if check_time < lag_threshold:
        if data_exists:
            return (
                'DATA_FOUND',
                f"Data available (workflow started at {window_start_str})"
            )
        else:
            minutes_since_start = (check_time - window_start).total_seconds() / 60
            return (
                'WITHIN_LAG',
                f"Workflow '{workflow_name}' started at {window_start_str} "
                f"({minutes_since_start:.0f} minutes ago). "
                f"Data may still be collecting - wait up to 2 hours after window start."
            )

    # After lag threshold
    if data_exists:
        return (
            'DATA_FOUND',
            f"Data available as expected (workflow window: {window_start_str} - {window_end.strftime('%I:%M %p')})"
        )
    else:
        hours_since_start = (check_time - window_start).total_seconds() / 3600
        return (
            'FAILURE',
            f"Workflow '{workflow_name}' window opened at {window_start_str} "
            f"({hours_since_start:.1f}h ago) but no data found. "
            f"Check scraper logs and workflow execution status."
        )


def get_expected_data_lag_hours(workflow_name: str, config_path: Optional[str] = None) -> float:
    """
    Get the expected data lag in hours for a workflow.

    This is how long after the workflow window opens we should wait before
    considering missing data a failure.

    Args:
        workflow_name: Name of the workflow
        config_path: Optional path to workflows.yaml

    Returns:
        Expected lag in hours (default: 2.0)
    """
    # Default lag: 2 hours (allows for workflow run + data processing)
    # This could be made configurable in the future
    return 2.0


if __name__ == '__main__':
    # Example usage / self-test
    from datetime import datetime, timezone

    print("Workflow Timing Utilities - Self Test\n")

    # Test with 7 PM game
    game_times_evening = [datetime(2026, 1, 27, 19, 0, tzinfo=timezone.utc)]
    window_start, window_end = calculate_workflow_window('betting_lines', game_times_evening)

    print(f"7 PM game:")
    print(f"  Window: {window_start.strftime('%I:%M %p')} - {window_end.strftime('%I:%M %p')}")

    run_times = get_expected_run_times('betting_lines', game_times_evening)
    print(f"  Expected runs: {[t.strftime('%I:%M %p') for t in run_times]}")

    # Test with 12 PM game
    game_times_noon = [datetime(2026, 1, 27, 12, 0, tzinfo=timezone.utc)]
    window_start, window_end = calculate_workflow_window('betting_lines', game_times_noon)

    print(f"\n12 PM game:")
    print(f"  Window: {window_start.strftime('%I:%M %p')} - {window_end.strftime('%I:%M %p')}")

    run_times = get_expected_run_times('betting_lines', game_times_noon)
    print(f"  Expected runs: {[t.strftime('%I:%M %p') for t in run_times]}")

    # Test status messages
    print(f"\nStatus Message Examples:")

    # Too early
    check_time = datetime(2026, 1, 27, 6, 0, tzinfo=timezone.utc)
    status, message = get_workflow_status_message('betting_lines', check_time, game_times_evening, False)
    print(f"\n  {status}: {message}")

    # Within lag
    check_time = datetime(2026, 1, 27, 8, 30, tzinfo=timezone.utc)
    status, message = get_workflow_status_message('betting_lines', check_time, game_times_evening, False)
    print(f"\n  {status}: {message}")

    # Failure
    check_time = datetime(2026, 1, 27, 11, 0, tzinfo=timezone.utc)
    status, message = get_workflow_status_message('betting_lines', check_time, game_times_evening, False)
    print(f"\n  {status}: {message}")
