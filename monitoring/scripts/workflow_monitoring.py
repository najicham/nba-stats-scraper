"""
File: monitoring/scripts/workflow_monitoring.py

Comprehensive monitoring system for NBA Props Platform.
Tracks workflow executions, scraper runs, and provides clean logging.

Usage:
    python monitoring/scripts/workflow_monitoring.py summary [date]
    python monitoring/scripts/workflow_monitoring.py workflows [hours]
"""

from google.cloud import logging as cloud_logging
from google.cloud import workflows_v1
from google.cloud import storage
from datetime import datetime, timedelta
import json
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from enum import Enum

class ExecutionStatus(Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RUNNING = "RUNNING"
    TIMEOUT = "TIMEOUT"

@dataclass
class ScraperRun:
    """Simple data class for scraper run tracking"""
    timestamp: str
    scraper_name: str
    status: str
    duration_seconds: Optional[float] = None
    records_processed: Optional[int] = None
    error_message: Optional[str] = None
    workflow_execution_id: Optional[str] = None

@dataclass
class WorkflowRun:
    """Data class for workflow execution tracking"""
    timestamp: str
    workflow_name: str
    execution_id: str
    status: str
    duration_seconds: Optional[float] = None
    scrapers_triggered: List[str] = None
    error_message: Optional[str] = None

class WorkflowMonitor:
    """Monitor workflow executions and scraper runs"""
    
    def __init__(self, project_id: str, location: str = "us-west2"):
        self.project_id = project_id
        self.location = location
        self.workflows_client = workflows_v1.WorkflowsClient()
        self.executions_client = workflows_v1.ExecutionsClient()
        self.logging_client = cloud_logging.Client(project=project_id)
        self.storage_client = storage.Client(project=project_id)
        
    def get_workflow_executions(self, workflow_name: str, hours: int = 24) -> List[WorkflowRun]:
        """Get recent workflow executions"""
        parent = f"projects/{self.project_id}/locations/{self.location}/workflows/{workflow_name}"
        
        executions = []
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        try:
            request = workflows_v1.ListExecutionsRequest(parent=parent)
            page_result = self.executions_client.list_executions(request=request)
            
            for execution in page_result:
                exec_time = execution.start_time
                if exec_time.timestamp() < cutoff_time.timestamp():
                    continue
                
                status = str(execution.state.name)
                duration = None
                
                if execution.end_time:
                    duration = (execution.end_time.timestamp() - execution.start_time.timestamp())
                
                executions.append(WorkflowRun(
                    timestamp=execution.start_time.isoformat(),
                    workflow_name=workflow_name,
                    execution_id=execution.name.split('/')[-1],
                    status=status,
                    duration_seconds=duration,
                    error_message=execution.error.payload if execution.error else None
                ))
        except Exception as e:
            print(f"Error fetching executions for {workflow_name}: {e}")
        
        return executions
    
    def get_all_workflow_executions(self, hours: int = 24) -> Dict[str, List[WorkflowRun]]:
        """Get executions for all workflows"""
        workflows = [
            "morning-operations",
            "early-morning-final-check", 
            "late-night-recovery",
            "post-game-collection",
            "real-time-business"
        ]
        
        all_executions = {}
        for workflow in workflows:
            all_executions[workflow] = self.get_workflow_executions(workflow, hours)
        
        return all_executions
    
    def get_scraper_logs(self, hours: int = 24, severity: str = "DEFAULT") -> List[ScraperRun]:
        """Parse Cloud Run logs to extract scraper runs"""
        filter_str = f"""
        resource.type="cloud_run_revision"
        resource.labels.service_name="nba-scrapers"
        severity>={severity}
        timestamp>="{(datetime.utcnow() - timedelta(hours=hours)).isoformat()}Z"
        """
        
        scraper_runs = []
        
        for entry in self.logging_client.list_entries(filter_=filter_str, max_results=1000):
            # Parse structured logs for scraper start/end events
            if hasattr(entry, 'json_payload'):
                payload = dict(entry.json_payload)
                
                # Look for structured scraper log entries
                if 'event' in payload and payload.get('event') in ['START', 'END']:
                    scraper_runs.append(ScraperRun(
                        timestamp=entry.timestamp.isoformat(),
                        scraper_name=payload.get('scraper', 'unknown'),
                        status=payload.get('status', 'UNKNOWN'),
                        duration_seconds=payload.get('duration_seconds'),
                        records_processed=payload.get('records_processed'),
                        error_message=payload.get('error'),
                        workflow_execution_id=payload.get('workflow_execution_id')
                    ))
        
        return scraper_runs
    
    def generate_daily_summary(self, date_str: Optional[str] = None) -> str:
        """Generate a clean daily summary report"""
        if not date_str:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
        
        # Get workflow executions
        workflows = self.get_all_workflow_executions(hours=24)
        
        # Generate report
        report = f"\n{'='*70}\n"
        report += f"📊 NBA Props Platform - Daily Summary for {date_str}\n"
        report += f"{'='*70}\n\n"
        
        # Workflow Summary
        report += "🔄 WORKFLOW EXECUTIONS\n"
        report += "-" * 70 + "\n"
        
        total_runs = 0
        total_success = 0
        total_failed = 0
        
        for workflow_name, executions in workflows.items():
            if not executions:
                continue
            
            success = sum(1 for e in executions if e.status == "SUCCEEDED")
            failed = sum(1 for e in executions if e.status == "FAILED")
            running = sum(1 for e in executions if e.status == "ACTIVE")
            
            total_runs += len(executions)
            total_success += success
            total_failed += failed
            
            status_emoji = "✓" if failed == 0 else "✗"
            report += f"{status_emoji} {workflow_name:30s} | "
            report += f"Runs: {len(executions):2d} | Success: {success:2d} | Failed: {failed:2d}"
            
            if running > 0:
                report += f" | Running: {running}"
            
            report += "\n"
            
            # Show recent failures
            if failed > 0:
                for execution in executions:
                    if execution.status == "FAILED":
                        report += f"  └─ Failed at {execution.timestamp}: {execution.error_message}\n"
        
        report += "-" * 70 + "\n"
        report += f"Total: {total_runs} executions | ✓ {total_success} | ✗ {total_failed}\n\n"
        
        # Scraper Summary (if structured logging is implemented)
        scraper_runs = self.get_scraper_logs(hours=24)
        if scraper_runs:
            report += "🔍 SCRAPER RUNS\n"
            report += "-" * 70 + "\n"
            
            # Group by scraper name
            scrapers = {}
            for run in scraper_runs:
                if run.scraper_name not in scrapers:
                    scrapers[run.scraper_name] = {'success': 0, 'failed': 0}
                
                if run.status == 'SUCCESS':
                    scrapers[run.scraper_name]['success'] += 1
                else:
                    scrapers[run.scraper_name]['failed'] += 1
            
            for scraper, stats in scrapers.items():
                status_emoji = "✓" if stats['failed'] == 0 else "✗"
                report += f"{status_emoji} {scraper:30s} | "
                report += f"Success: {stats['success']:2d} | Failed: {stats['failed']:2d}\n"
            
            report += "-" * 70 + "\n"
        
        report += "\n" + "="*70 + "\n"
        
        return report

class StructuredLogger:
    """
    Drop-in replacement for print() that creates structured logs
    Compatible with Cloud Run's structured logging
    """
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.logging_client = cloud_logging.Client()
        self.logger = self.logging_client.logger(service_name)
    
    def log_scraper_start(self, scraper_name: str, **metadata):
        """Log scraper start"""
        log_data = {
            'event': 'START',
            'scraper': scraper_name,
            'timestamp': datetime.utcnow().isoformat(),
            'service': self.service_name,
            **metadata
        }
        
        # Print for Cloud Run stdout (will be captured in logs)
        print(json.dumps(log_data))
        
        # Also send to Cloud Logging
        self.logger.log_struct(log_data, severity='INFO')
    
    def log_scraper_end(self, scraper_name: str, status: str = "SUCCESS", **metadata):
        """Log scraper end"""
        log_data = {
            'event': 'END',
            'scraper': scraper_name,
            'status': status,
            'timestamp': datetime.utcnow().isoformat(),
            'service': self.service_name,
            **metadata
        }
        
        severity = 'INFO' if status == 'SUCCESS' else 'ERROR'
        
        # Print for Cloud Run stdout
        print(json.dumps(log_data))
        
        # Send to Cloud Logging
        self.logger.log_struct(log_data, severity=severity)
    
    def log_error(self, scraper_name: str, error: Exception, **metadata):
        """Log an error"""
        log_data = {
            'event': 'ERROR',
            'scraper': scraper_name,
            'error': str(error),
            'error_type': type(error).__name__,
            'timestamp': datetime.utcnow().isoformat(),
            'service': self.service_name,
            **metadata
        }
        
        print(json.dumps(log_data))
        self.logger.log_struct(log_data, severity='ERROR')


# Usage in your scrapers
def example_scraper_with_structured_logging():
    """Example of how to use structured logging in your scrapers"""
    logger = StructuredLogger("nba-scrapers")
    scraper_name = "bdl_box_scores"
    
    start_time = datetime.utcnow()
    logger.log_scraper_start(scraper_name, date="2025-10-13")
    
    try:
        # Your scraping code here
        records = []  # ... scrape data
        
        duration = (datetime.utcnow() - start_time).total_seconds()
        logger.log_scraper_end(
            scraper_name,
            status="SUCCESS",
            duration_seconds=duration,
            records_processed=len(records)
        )
    except Exception as e:
        duration = (datetime.utcnow() - start_time).total_seconds()
        logger.log_error(scraper_name, e, duration_seconds=duration)
        raise


# CLI tool for daily summaries
if __name__ == "__main__":
    import sys
    
    project_id = "nba-props-platform"
    monitor = WorkflowMonitor(project_id)
    
    # Generate and print daily summary
    if len(sys.argv) > 1 and sys.argv[1] == "summary":
        date_str = sys.argv[2] if len(sys.argv) > 2 else None
        print(monitor.generate_daily_summary(date_str))
    
    # List recent workflow executions
    elif len(sys.argv) > 1 and sys.argv[1] == "workflows":
        hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
        executions = monitor.get_all_workflow_executions(hours)
        
        for workflow, runs in executions.items():
            print(f"\n{workflow}:")
            for run in runs[:5]:  # Show last 5
                print(f"  {run.timestamp} | {run.status} | {run.execution_id}")
    
    else:
        print("Usage:")
        print("  python workflow_monitoring.py summary [date]")
        print("  python workflow_monitoring.py workflows [hours]")
