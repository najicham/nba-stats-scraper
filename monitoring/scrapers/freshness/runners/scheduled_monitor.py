#!/usr/bin/env python3
"""
File: monitoring/scrapers/freshness/runners/scheduled_monitor.py

Main entry point for scheduled freshness monitoring.
Runs as a Cloud Run job triggered by Cloud Scheduler.
"""

import os
import sys
import logging
import argparse
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import yaml
from google.cloud import storage

from monitoring.scrapers.freshness.core.freshness_checker import FreshnessChecker
from monitoring.scrapers.freshness.core.season_manager import SeasonManager
from monitoring.scrapers.freshness.utils.nba_schedule_api import has_games_today_cached
from monitoring.scrapers.freshness.utils.alert_formatter import AlertFormatter

# Import existing notification system
from shared.utils.notification_system import notify_error, notify_warning, notify_info

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FreshnessMonitor:
    """
    Main freshness monitoring coordinator.
    
    Orchestrates:
    - Loading configuration
    - Checking scrapers
    - Formatting alerts
    - Sending notifications
    """
    
    def __init__(self, config_dir: Path):
        """
        Initialize monitor.
        
        Args:
            config_dir: Path to configuration directory
        """
        self.config_dir = config_dir
        self.monitoring_config = self._load_monitoring_config()
        self.season_manager = SeasonManager(
            str(config_dir / 'nba_schedule_config.yaml')
        )
        self.freshness_checker = FreshnessChecker()
        self.alert_formatter = AlertFormatter()
        
        logger.info("FreshnessMonitor initialized")
    
    def _load_monitoring_config(self) -> dict:
        """Load monitoring configuration."""
        config_path = self.config_dir / 'monitoring_config.yaml'
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"Loaded monitoring config: {len(config.get('scrapers', {}))} scrapers")
            return config
        except Exception as e:
            logger.error(f"Failed to load monitoring config: {e}")
            raise
    
    def run_monitoring_check(self, dry_run: bool = False) -> dict:
        """
        Run complete monitoring check.
        
        Args:
            dry_run: If True, don't send alerts
        
        Returns:
            Dict with results summary
        """
        logger.info("=" * 80)
        logger.info("Starting freshness monitoring check")
        logger.info("=" * 80)
        
        try:
            # Get current season info
            season_summary = self.season_manager.get_summary()
            current_phase = season_summary['current_phase']
            logger.info(f"Current season: {season_summary['season_label']} - {current_phase}")
            
            # Check if in maintenance window
            if season_summary.get('in_maintenance_window'):
                logger.info("In maintenance window - skipping checks")
                return {
                    'status': 'skipped',
                    'reason': 'maintenance_window',
                    'timestamp': datetime.utcnow().isoformat()
                }
            
            # Check if there are games today
            has_games = has_games_today_cached()
            logger.info(f"Games today: {has_games}")
            
            # Run checks on all scrapers
            scrapers_config = self.monitoring_config.get('scrapers', {})
            results = self.freshness_checker.check_all_scrapers(
                scrapers_config=scrapers_config,
                current_season=current_phase,
                has_games_today=has_games
            )
            
            # Summarize results
            summary = self.freshness_checker.summarize_results(results)
            logger.info(f"Check complete: {summary}")
            
            # Format alert
            alert_data = self.alert_formatter.format_for_notification(
                results=results,
                summary=summary,
                season_info=season_summary
            )
            
            # Determine if we should alert
            should_alert = self.alert_formatter.should_send_alert(
                results=results,
                min_severity='warning'
            )
            
            # Send notifications if needed
            if should_alert and not dry_run:
                self._send_notifications(alert_data)
            elif should_alert and dry_run:
                logger.info("DRY RUN: Would send alert")
                logger.info(f"Alert data: {alert_data}")
            else:
                logger.info("No alerts needed - all systems healthy")
            
            return {
                'status': 'success',
                'summary': summary,
                'alert_sent': should_alert and not dry_run,
                'timestamp': datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Monitoring check failed: {e}", exc_info=True)
            
            if not dry_run:
                # Send error notification
                try:
                    notify_error(
                        title="Freshness Monitor Failed",
                        message=f"Monitoring check encountered an error: {str(e)}",
                        details={
                            'error_type': type(e).__name__,
                            'error_message': str(e)
                        },
                        processor_name="Freshness Monitor"
                    )
                except Exception as notify_ex:
                    logger.error(f"Failed to send error notification: {notify_ex}")
            
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }
    
    def _send_notifications(self, alert_data: dict):
        """
        Send notifications using existing notification system.
        
        Args:
            alert_data: Formatted alert data
        """
        severity = alert_data['severity']
        title = alert_data['title']
        message = alert_data['message']
        details = alert_data['details']
        
        try:
            if severity == 'critical':
                notify_error(
                    title=title,
                    message=message,
                    details=details,
                    processor_name="Freshness Monitor"
                )
                logger.info("Sent critical alert")
            
            elif severity == 'warning':
                notify_warning(
                    title=title,
                    message=message,
                    details=details
                    processor_name=self.__class__.__name__
                )
                logger.info("Sent warning alert")
            
            else:
                # Info level
                notify_info(
                    title=title,
                    message=message,
                    details=details
                    processor_name=self.__class__.__name__
                )
                logger.info("Sent info notification")
        
        except Exception as e:
            logger.error(f"Failed to send notification: {e}", exc_info=True)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Scraper Freshness Monitor')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run checks but do not send alerts'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Run in test mode with verbose logging'
    )
    parser.add_argument(
        '--config-dir',
        type=str,
        default=None,
        help='Path to config directory (default: auto-detect)'
    )
    
    args = parser.parse_args()
    
    # Set logging level
    if args.test:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.info("Running in TEST mode")
    
    # Determine config directory
    if args.config_dir:
        config_dir = Path(args.config_dir)
    else:
        # Auto-detect based on script location
        config_dir = Path(__file__).parent.parent / 'config'
    
    if not config_dir.exists():
        logger.error(f"Config directory not found: {config_dir}")
        sys.exit(1)
    
    logger.info(f"Using config directory: {config_dir}")
    
    # Run monitoring
    try:
        monitor = FreshnessMonitor(config_dir)
        result = monitor.run_monitoring_check(dry_run=args.dry_run or args.test)
        
        # Print summary
        logger.info("=" * 80)
        logger.info("Monitoring check complete")
        logger.info(f"Status: {result.get('status')}")
        if 'summary' in result:
            logger.info(f"Health Score: {result['summary'].get('health_score')}%")
            logger.info(f"Critical: {result['summary'].get('critical', 0)}")
            logger.info(f"Warnings: {result['summary'].get('warning', 0)}")
            logger.info(f"OK: {result['summary'].get('ok', 0)}")
        logger.info("=" * 80)
        
        # Exit with appropriate code
        if result['status'] == 'error':
            sys.exit(1)
        elif result.get('summary', {}).get('critical', 0) > 0:
            sys.exit(2)  # Exit code 2 for critical issues
        else:
            sys.exit(0)
    
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
