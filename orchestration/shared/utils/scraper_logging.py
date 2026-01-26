"""
File: shared/utils/scraper_logging.py

Simple, noise-free logging system for NBA scrapers.
Usage: from shared.utils.scraper_logging import ScraperLogger
"""

import logging
import json
from datetime import datetime
from google.cloud import storage
from google.cloud.exceptions import NotFound
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class ScraperLogger:
    """Simple, noise-free logging for scrapers"""
    
    def __init__(self, scraper_name, bucket_name="nba-scraper-logs"):
        self.scraper_name = scraper_name
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        
    def _get_log_path(self):
        """Generate daily log file path"""
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        return f"logs/{date_str}/scraper_runs.jsonl"
    
    def _write_log_entry(self, entry):
        """Write a single log entry to Cloud Storage"""
        bucket = self.storage_client.bucket(self.bucket_name)
        blob = bucket.blob(self._get_log_path())
        
        # Append to existing content
        try:
            existing_content = blob.download_as_text()
        except NotFound:
            existing_content = ""
        except Exception as e:
            logger.warning(f"Error reading existing log content: {e}")
            existing_content = ""
        
        log_line = json.dumps(entry) + "\n"
        blob.upload_from_string(existing_content + log_line)
    
    def log_start(self, **metadata):
        """Log scraper start"""
        entry = {
            "scraper": self.scraper_name,
            "event": "START",
            "timestamp": datetime.utcnow().isoformat(),
            **metadata
        }
        self._write_log_entry(entry)
        print(f"✓ {self.scraper_name} started")
    
    def log_end(self, status="SUCCESS", records_processed=None, **metadata):
        """Log scraper end"""
        entry = {
            "scraper": self.scraper_name,
            "event": "END",
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        if records_processed is not None:
            entry["records_processed"] = records_processed
            
        entry.update(metadata)
        self._write_log_entry(entry)
        
        emoji = "✓" if status == "SUCCESS" else "✗"
        print(f"{emoji} {self.scraper_name} finished: {status}")
    
    @contextmanager
    def log_run(self, **start_metadata):
        """Context manager for automatic start/end logging"""
        self.log_start(**start_metadata)
        start_time = datetime.utcnow()
        
        try:
            yield self
            duration = (datetime.utcnow() - start_time).total_seconds()
            self.log_end(status="SUCCESS", duration_seconds=duration)
        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            self.log_end(
                status="FAILED", 
                duration_seconds=duration,
                error=str(e),
                error_type=type(e).__name__
            )
            raise


# Usage Example
def scrape_box_scores(date):
    """Example scraper function"""
    logger = ScraperLogger("bdl_box_scores")
    
    # Option 1: Manual logging
    logger.log_start(date=date)
    try:
        # Your scraping code here
        records = []  # ... scrape data
        logger.log_end(status="SUCCESS", records_processed=len(records))
    except Exception as e:
        logger.log_end(status="FAILED", error=str(e))
        raise
    
    # Option 2: Context manager (cleaner)
    with logger.log_run(date=date):
        # Your scraping code here
        records = []  # ... scrape data
        logger.records_processed = len(records)


# Daily Summary Report Generator
def generate_daily_summary(date_str=None):
    """Generate a daily summary of all scraper runs"""
    if not date_str:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
    
    storage_client = storage.Client()
    bucket = storage_client.bucket("nba-scraper-logs")
    blob = bucket.blob(f"logs/{date_str}/scraper_runs.jsonl")

    try:
        content = blob.download_as_text()
    except NotFound:
        print(f"No logs found for {date_str}")
        return
    except Exception as e:
        print(f"Error reading logs for {date_str}: {e}")
        return
    
    # Parse all log entries
    entries = [json.loads(line) for line in content.strip().split("\n")]
    
    # Group by scraper
    scrapers = {}
    for entry in entries:
        scraper = entry["scraper"]
        if scraper not in scrapers:
            scrapers[scraper] = {"runs": 0, "successes": 0, "failures": 0}
        
        if entry["event"] == "END":
            scrapers[scraper]["runs"] += 1
            if entry["status"] == "SUCCESS":
                scrapers[scraper]["successes"] += 1
            else:
                scrapers[scraper]["failures"] += 1
    
    # Print summary
    print(f"\n📊 Scraper Summary for {date_str}")
    print("=" * 60)
    for scraper, stats in scrapers.items():
        status = "✓" if stats["failures"] == 0 else "✗"
        print(f"{status} {scraper}: {stats['runs']} runs, "
              f"{stats['successes']} success, {stats['failures']} failed")
    print("=" * 60)


if __name__ == "__main__":
    # Test the logger
    logger = ScraperLogger("test_scraper")
    with logger.log_run(test_param="value"):
        # Simulate some work
        import time
        time.sleep(1)
