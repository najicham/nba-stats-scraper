"""
File: shared/utils/smart_alerting.py

Intelligent alert system that batches errors during backfills and rate limits notifications.
Usage: from shared.utils.smart_alerting import SmartAlertManager
"""

import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from google.cloud import storage
from collections import defaultdict

class SmartAlertManager:
    """
    Intelligent alert system that:
    - Batches errors during backfills
    - Rate limits notifications
    - Sends summary reports instead of individual errors
    """
    
    def __init__(self, bucket_name="nba-alerts"):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        
    def _get_alert_state_path(self):
        """Path for tracking alert state"""
        return "alert_state/current.json"
    
    def _load_alert_state(self):
        """Load current alert state from storage"""
        bucket = self.storage_client.bucket(self.bucket_name)
        blob = bucket.blob(self._get_alert_state_path())
        
        try:
            content = blob.download_as_text()
            return json.loads(content)
        except:
            return {
                "last_alert_time": {},
                "pending_errors": [],
                "is_backfill_mode": False
            }
    
    def _save_alert_state(self, state):
        """Save alert state to storage"""
        bucket = self.storage_client.bucket(self.bucket_name)
        blob = bucket.blob(self._get_alert_state_path())
        blob.upload_from_string(json.dumps(state, indent=2))
    
    def should_send_alert(self, error_type, cooldown_minutes=60):
        """
        Check if we should send an alert for this error type.
        Implements rate limiting per error type.
        """
        state = self._load_alert_state()
        
        # If in backfill mode, queue the error instead
        if state.get("is_backfill_mode", False):
            return False
        
        last_alert = state["last_alert_time"].get(error_type)
        
        if not last_alert:
            return True
        
        last_time = datetime.fromisoformat(last_alert)
        cooldown = timedelta(minutes=cooldown_minutes)
        
        return datetime.utcnow() - last_time > cooldown
    
    def record_error(self, error_data):
        """Record an error (either send immediately or queue for batch)"""
        state = self._load_alert_state()
        
        error_entry = {
            **error_data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Add to pending errors
        state["pending_errors"].append(error_entry)
        
        # If not in backfill mode and cooldown passed, send alert
        if not state.get("is_backfill_mode", False):
            error_type = error_data.get("error_type", "unknown")
            
            if self.should_send_alert(error_type):
                self._send_immediate_alert(error_entry)
                state["last_alert_time"][error_type] = datetime.utcnow().isoformat()
                # Clear this error from pending
                state["pending_errors"] = [
                    e for e in state["pending_errors"] 
                    if e["timestamp"] != error_entry["timestamp"]
                ]
        
        self._save_alert_state(state)
    
    def _send_immediate_alert(self, error_data):
        """Send a single error alert via email"""
        subject = f"🚨 {error_data.get('processor', 'NBA Platform')}: {error_data.get('error_type', 'Error')}"
        
        body = f"""
Critical Error Alert

Processor: {error_data.get('processor', 'Unknown')}
Time: {error_data.get('timestamp', 'Unknown')}
Error: {error_data.get('error', 'No details')}

Error Details:
{json.dumps(error_data.get('details', {}), indent=2)}

---
This is an immediate alert. Similar errors within the next 60 minutes will be suppressed.
        """
        
        self._send_email(subject, body)
    
    def enable_backfill_mode(self):
        """Enable backfill mode - queues errors instead of sending"""
        state = self._load_alert_state()
        state["is_backfill_mode"] = True
        state["backfill_start_time"] = datetime.utcnow().isoformat()
        self._save_alert_state(state)
        print("✓ Backfill mode enabled - errors will be batched")
    
    def disable_backfill_mode(self, send_summary=True):
        """Disable backfill mode and optionally send error summary"""
        state = self._load_alert_state()
        state["is_backfill_mode"] = False
        
        if send_summary and state["pending_errors"]:
            self._send_batch_summary(state["pending_errors"])
            state["pending_errors"] = []
        
        self._save_alert_state(state)
        print("✓ Backfill mode disabled")
    
    def _send_batch_summary(self, errors):
        """Send a summary of batched errors"""
        if not errors:
            return
        
        # Group errors by type
        error_groups = defaultdict(list)
        for error in errors:
            error_type = error.get("error_type", "unknown")
            error_groups[error_type].append(error)
        
        subject = f"📊 Backfill Error Summary - {len(errors)} errors"
        
        body = f"""
Backfill Error Summary
Total Errors: {len(errors)}
Time Period: {errors[0]['timestamp']} to {errors[-1]['timestamp']}

Error Breakdown:
"""
        
        for error_type, error_list in error_groups.items():
            body += f"\n{error_type}: {len(error_list)} occurrences\n"
            
            # Show first and last occurrence
            body += f"  First: {error_list[0]['timestamp']}\n"
            body += f"  Last: {error_list[-1]['timestamp']}\n"
            
            # Show unique scrapers affected
            scrapers = set(e.get('scraper', 'unknown') for e in error_list)
            body += f"  Affected scrapers: {', '.join(scrapers)}\n"
        
        body += "\n\nDetailed Errors:\n"
        body += "=" * 60 + "\n"
        
        # Show up to 10 sample errors
        for i, error in enumerate(errors[:10]):
            body += f"\n{i+1}. {error.get('scraper', 'Unknown')}\n"
            body += f"   Time: {error['timestamp']}\n"
            body += f"   Error: {error.get('error', 'No details')}\n"
        
        if len(errors) > 10:
            body += f"\n... and {len(errors) - 10} more errors"
        
        self._send_email(subject, body)
    
    def _send_email(self, subject, body):
        """Send email notification"""
        # This is a placeholder - implement with your actual email settings
        # You can use SendGrid, AWS SES, or Gmail SMTP
        print(f"\n📧 EMAIL ALERT:\nSubject: {subject}\n{body}\n")
        
        # Example implementation:
        # msg = MIMEMultipart()
        # msg['From'] = "alerts@yourapp.com"
        # msg['To'] = "your-email@gmail.com"
        # msg['Subject'] = subject
        # msg.attach(MIMEText(body, 'plain'))
        # 
        # server = smtplib.SMTP('smtp.gmail.com', 587)
        # server.starttls()
        # server.login("your-email@gmail.com", "your-app-password")
        # server.send_message(msg)
        # server.quit()
    
    def get_error_summary(self, hours=24):
        """Get summary of recent errors"""
        state = self._load_alert_state()
        
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        recent_errors = [
            e for e in state["pending_errors"]
            if datetime.fromisoformat(e["timestamp"]) > cutoff_time
        ]
        
        return {
            "total_errors": len(recent_errors),
            "by_type": defaultdict(int),
            "by_scraper": defaultdict(int)
        }


# Integration with your scrapers
def scraper_with_smart_alerts():
    """Example of how to use the smart alert system"""
    alert_mgr = SmartAlertManager()
    
    try:
        # Your scraping code
        pass
    except Exception as e:
        alert_mgr.record_error({
            "processor": "NBA Platform",
            "scraper": "bdl_box_scores",
            "error_type": type(e).__name__,
            "error": str(e),
            "details": {
                "date": "2025-10-14",
                "run_id": "abc123"
            }
        })


# Backfill script wrapper
def run_backfill_with_batched_alerts():
    """Wrapper for backfill scripts"""
    alert_mgr = SmartAlertManager()
    
    # Enable backfill mode
    alert_mgr.enable_backfill_mode()
    
    try:
        # Run your backfill
        dates = ["2025-10-01", "2025-10-02", "2025-10-03"]  # etc.
        
        for date in dates:
            try:
                # scrape_data(date)
                pass
            except Exception as e:
                alert_mgr.record_error({
                    "processor": "Backfill",
                    "scraper": "bdl_box_scores",
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "details": {"date": date}
                })
    
    finally:
        # Always disable backfill mode and send summary
        alert_mgr.disable_backfill_mode(send_summary=True)


if __name__ == "__main__":
    # Test the alert system
    mgr = SmartAlertManager()
    
    # Simulate some errors
    mgr.record_error({
        "processor": "NBA Platform",
        "scraper": "test_scraper",
        "error_type": "ConnectionError",
        "error": "Proxy failed",
        "details": {"proxy": "gate2.proxyfuel.com"}
    })
