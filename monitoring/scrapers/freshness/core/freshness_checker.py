#!/usr/bin/env python3
"""
File: monitoring/scrapers/freshness/core/freshness_checker.py

Core freshness checking logic for scraper data in GCS.
Checks file existence, age, and size against configured thresholds.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

from google.cloud import storage

logger = logging.getLogger(__name__)


class CheckStatus(Enum):
    """Status of a freshness check."""
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class CheckResult:
    """Result of a single freshness check."""
    scraper_name: str
    status: CheckStatus
    message: str
    details: Dict[str, Any]
    timestamp: datetime
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging/alerts."""
        return {
            'scraper_name': self.scraper_name,
            'status': self.status.value,
            'message': self.message,
            'details': self.details,
            'timestamp': self.timestamp.isoformat()
        }


class FreshnessChecker:
    """
    Checks freshness of scraper data files in GCS.
    
    Integrates with:
    - GCS for file inspection
    - Season Manager for threshold adjustments
    - NBA Schedule API for game-day awareness
    """
    
    def __init__(self, gcs_client: storage.Client = None):
        """
        Initialize freshness checker.
        
        Args:
            gcs_client: Google Cloud Storage client (or None to create default)
        """
        self.gcs_client = gcs_client or storage.Client()
        logger.info("FreshnessChecker initialized")
    
    def check_scraper(
        self,
        scraper_name: str,
        config: Dict,
        current_season: str,
        has_games_today: bool
    ) -> CheckResult:
        """
        Check freshness for a single scraper.
        
        Args:
            scraper_name: Name of the scraper
            config: Scraper configuration from monitoring_config.yaml
            current_season: Current NBA season phase (regular_season, playoffs, etc.)
            has_games_today: Whether there are NBA games scheduled today
        
        Returns:
            CheckResult with status and details
        """
        logger.info(f"Checking scraper: {scraper_name}")
        
        try:
            # Check if scraper should be active
            if not self._should_check_scraper(config, current_season, has_games_today):
                return CheckResult(
                    scraper_name=scraper_name,
                    status=CheckStatus.SKIPPED,
                    message=f"Scraper not active during {current_season} or no games today",
                    details={
                        'reason': 'inactive_for_season',
                        'current_season': current_season,
                        'has_games_today': has_games_today
                    },
                    timestamp=datetime.utcnow()
                )
            
            # Get GCS configuration
            bucket_name = config.get('gcs', {}).get('bucket')
            path_pattern = config.get('gcs', {}).get('path_pattern')
            
            if not bucket_name or not path_pattern:
                return CheckResult(
                    scraper_name=scraper_name,
                    status=CheckStatus.ERROR,
                    message="Missing GCS configuration",
                    details={'config': config.get('gcs', {})},
                    timestamp=datetime.utcnow()
                )
            
            # Find most recent file
            most_recent_file = self._find_most_recent_file(bucket_name, path_pattern)
            
            if not most_recent_file:
                # No files found
                severity = config.get('alerting', {}).get('severity_missing', 'warning')
                return CheckResult(
                    scraper_name=scraper_name,
                    status=CheckStatus.CRITICAL if severity == 'critical' else CheckStatus.WARNING,
                    message=f"No files found matching pattern",
                    details={
                        'bucket': bucket_name,
                        'path_pattern': path_pattern,
                        'expected_schedule': config.get('schedule', {}).get('cron', 'unknown')
                    },
                    timestamp=datetime.utcnow()
                )
            
            # Check file age
            file_age_hours = (datetime.utcnow() - most_recent_file['updated']).total_seconds() / 3600
            max_age_hours = self._get_max_age_hours(config, current_season)
            
            # Check file size
            file_size_mb = most_recent_file['size'] / (1024 * 1024)
            min_size_mb = config.get('validation', {}).get('min_file_size_mb', 0)
            max_size_mb = config.get('validation', {}).get('max_file_size_mb', float('inf'))
            
            # Determine status
            details = {
                'file_path': most_recent_file['path'],
                'file_age_hours': round(file_age_hours, 2),
                'max_age_hours': max_age_hours,
                'file_size_mb': round(file_size_mb, 3),
                'updated_at': most_recent_file['updated'].isoformat(),
                'current_season': current_season
            }
            
            # Check for critical issues
            if file_size_mb == 0:
                return CheckResult(
                    scraper_name=scraper_name,
                    status=CheckStatus.CRITICAL,
                    message=f"File is empty (0 bytes)",
                    details=details,
                    timestamp=datetime.utcnow()
                )
            
            if file_size_mb < min_size_mb:
                return CheckResult(
                    scraper_name=scraper_name,
                    status=CheckStatus.WARNING,
                    message=f"File too small: {file_size_mb:.3f} MB < {min_size_mb} MB",
                    details=details,
                    timestamp=datetime.utcnow()
                )
            
            if file_size_mb > max_size_mb:
                return CheckResult(
                    scraper_name=scraper_name,
                    status=CheckStatus.WARNING,
                    message=f"File too large: {file_size_mb:.3f} MB > {max_size_mb} MB",
                    details=details,
                    timestamp=datetime.utcnow()
                )
            
            # Check age
            if file_age_hours > max_age_hours * 2:
                # Critical: Way too old
                severity = config.get('alerting', {}).get('severity_stale', 'warning')
                return CheckResult(
                    scraper_name=scraper_name,
                    status=CheckStatus.CRITICAL if severity == 'critical' else CheckStatus.WARNING,
                    message=f"Data critically stale: {file_age_hours:.1f}h old (max: {max_age_hours}h)",
                    details=details,
                    timestamp=datetime.utcnow()
                )
            
            elif file_age_hours > max_age_hours:
                # Warning: Too old
                return CheckResult(
                    scraper_name=scraper_name,
                    status=CheckStatus.WARNING,
                    message=f"Data stale: {file_age_hours:.1f}h old (max: {max_age_hours}h)",
                    details=details,
                    timestamp=datetime.utcnow()
                )
            
            # All checks passed
            return CheckResult(
                scraper_name=scraper_name,
                status=CheckStatus.OK,
                message=f"Data fresh: {file_age_hours:.1f}h old",
                details=details,
                timestamp=datetime.utcnow()
            )
        
        except Exception as e:
            logger.error(f"Error checking {scraper_name}: {e}", exc_info=True)
            return CheckResult(
                scraper_name=scraper_name,
                status=CheckStatus.ERROR,
                message=f"Check failed: {str(e)}",
                details={'error': str(e), 'error_type': type(e).__name__},
                timestamp=datetime.utcnow()
            )
    
    def _should_check_scraper(
        self,
        config: Dict,
        current_season: str,
        has_games_today: bool
    ) -> bool:
        """
        Determine if scraper should be checked right now.
        
        Args:
            config: Scraper configuration
            current_season: Current season phase
            has_games_today: Whether there are games today
        
        Returns:
            True if scraper should be checked, False to skip
        """
        # Check if enabled
        if not config.get('enabled', True):
            return False
        
        # Check if active during current season
        active_during = config.get('seasonality', {}).get('active_during', [])
        if active_during and current_season not in active_during:
            logger.info(f"Skipping - not active during {current_season}")
            return False
        
        # Check if games are required
        requires_games = config.get('seasonality', {}).get('requires_games_today', False)
        if requires_games and not has_games_today:
            logger.info(f"Skipping - no games today and scraper requires games")
            return False
        
        return True
    
    def _find_most_recent_file(
        self,
        bucket_name: str,
        path_pattern: str
    ) -> Optional[Dict]:
        """
        Find most recent file matching path pattern in GCS.
        
        Args:
            bucket_name: GCS bucket name
            path_pattern: Path pattern with variables like {date}
        
        Returns:
            Dict with file details or None if no files found
        """
        try:
            bucket = self.gcs_client.bucket(bucket_name)
            
            # Convert pattern to search prefix
            # Look at today and yesterday to account for timezone differences
            today = datetime.utcnow().strftime('%Y-%m-%d')
            yesterday = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
            
            # Replace {date} with today and yesterday for searching
            prefixes = []
            if '{date}' in path_pattern:
                prefixes.append(path_pattern.split('{date}')[0])
            else:
                # If no {date} in pattern, use the whole pattern as prefix
                prefixes.append(path_pattern.rstrip('*'))
            
            most_recent = None
            
            for prefix in prefixes:
                # Remove trailing wildcards
                prefix = prefix.rstrip('*')
                
                logger.debug(f"Searching GCS: gs://{bucket_name}/{prefix}")
                
                # List blobs with prefix
                blobs = bucket.list_blobs(prefix=prefix, max_results=1000)
                
                for blob in blobs:
                    # Skip directories
                    if blob.name.endswith('/'):
                        continue
                    
                    # Check if this is newer than current most_recent
                    if most_recent is None or blob.updated > most_recent['updated']:
                        most_recent = {
                            'path': f"gs://{bucket_name}/{blob.name}",
                            'name': blob.name,
                            'updated': blob.updated,
                            'size': blob.size
                        }
            
            if most_recent:
                logger.info(f"Found most recent file: {most_recent['name']} "
                          f"(updated: {most_recent['updated']})")
            else:
                logger.warning(f"No files found in gs://{bucket_name} with prefix: {prefix}")
            
            return most_recent
        
        except Exception as e:
            logger.error(f"Error searching GCS: {e}", exc_info=True)
            return None
    
    def _get_max_age_hours(self, config: Dict, current_season: str) -> float:
        """
        Get maximum age threshold for current season.
        
        Args:
            config: Scraper configuration
            current_season: Current season phase
        
        Returns:
            Maximum age in hours
        """
        freshness_config = config.get('freshness', {}).get('max_age_hours', {})
        
        # Try season-specific threshold first
        max_age = freshness_config.get(current_season)
        
        # Fall back to default if not specified
        if max_age is None:
            max_age = freshness_config.get('regular_season', 24)
        
        return float(max_age)
    
    def check_all_scrapers(
        self,
        scrapers_config: Dict,
        current_season: str,
        has_games_today: bool
    ) -> List[CheckResult]:
        """
        Check all configured scrapers.
        
        Args:
            scrapers_config: Dictionary of scraper configurations
            current_season: Current season phase
            has_games_today: Whether there are games today
        
        Returns:
            List of CheckResult objects
        """
        results = []
        
        for scraper_name, config in scrapers_config.items():
            result = self.check_scraper(
                scraper_name=scraper_name,
                config=config,
                current_season=current_season,
                has_games_today=has_games_today
            )
            results.append(result)
        
        return results
    
    def summarize_results(self, results: List[CheckResult]) -> Dict:
        """
        Summarize check results for reporting.
        
        Args:
            results: List of check results
        
        Returns:
            Summary dictionary
        """
        summary = {
            'total_checked': len(results),
            'ok': 0,
            'warning': 0,
            'critical': 0,
            'skipped': 0,
            'error': 0,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        for result in results:
            if result.status == CheckStatus.OK:
                summary['ok'] += 1
            elif result.status == CheckStatus.WARNING:
                summary['warning'] += 1
            elif result.status == CheckStatus.CRITICAL:
                summary['critical'] += 1
            elif result.status == CheckStatus.SKIPPED:
                summary['skipped'] += 1
            elif result.status == CheckStatus.ERROR:
                summary['error'] += 1
        
        # Add health score (percentage OK out of non-skipped)
        active_checks = summary['total_checked'] - summary['skipped']
        if active_checks > 0:
            summary['health_score'] = round((summary['ok'] / active_checks) * 100, 1)
        else:
            summary['health_score'] = 100.0
        
        return summary
