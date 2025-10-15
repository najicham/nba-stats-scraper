#!/usr/bin/env python3
"""
File: monitoring/scripts/check-scrapers.py

Simple CLI tool to check scraper status.

Usage: 
    python monitoring/scripts/check-scrapers.py [today|yesterday|2025-10-14]

Installation:
    chmod +x monitoring/scripts/check-scrapers.py
"""

import sys
from datetime import datetime, timedelta
from google.cloud import logging as cloud_logging
from google.cloud import workflows_v1
from collections import defaultdict
import json

PROJECT_ID = "nba-props-platform"
LOCATION = "us-west2"

WORKFLOWS = [
    "morning-operations",
    "early-morning-final-check",
    "late-night-recovery", 
    "post-game-collection",
    "real-time-business"
]

def get_date_range(date_arg):
    """Parse date argument and return start/end datetime"""
    if date_arg == "today":
        date = datetime.utcnow().date()
    elif date_arg == "yesterday":
        date = (datetime.utcnow() - timedelta(days=1)).date()
    else:
        try:
            date = datetime.strptime(date_arg, "%Y-%m-%d").date()
        except:
            print(f"Invalid date format: {date_arg}. Use YYYY-MM-DD, 'today', or 'yesterday'")
            sys.exit(1)
    
    start = datetime.combine(date, datetime.min.time())
    end = datetime.combine(date, datetime.max.time())
    return start, end, date

def check_workflows(start_time, end_time):
    """Check workflow executions for the time period"""
    executions_client = workflows_v1.ExecutionsClient()
    
    results = {}
    
    for workflow_name in WORKFLOWS:
        parent = f"projects/{PROJECT_ID}/locations/{LOCATION}/workflows/{workflow_name}"
        
        try:
            request = workflows_v1.ListExecutionsRequest(parent=parent)
            page_result = executions_client.list_executions(request=request)
            
            workflow_runs = []
            for execution in page_result:
                exec_time = execution.start_time
                
                # Filter by date range
                if exec_time < start_time or exec_time > end_time:
                    continue
                
                workflow_runs.append({
                    'time': exec_time.strftime("%H:%M:%S"),
                    'status': str(execution.state.name),
                    'id': execution.name.split('/')[-1],
                    'error': execution.error.payload if execution.error else None
                })
            
            results[workflow_name] = sorted(workflow_runs, key=lambda x: x['time'])
        
        except Exception as e:
            results[workflow_name] = {'error': str(e)}
    
    return results

def check_scraper_logs(start_time, end_time):
    """Check Cloud Run logs for scraper activity"""
    logging_client = cloud_logging.Client(project=PROJECT_ID)
    
    # Query logs for the nba-scrapers service
    filter_str = f"""
    resource.type="cloud_run_revision"
    resource.labels.service_name="nba-scrapers"
    timestamp>="{start_time.isoformat()}Z"
    timestamp<="{end_time.isoformat()}Z"
    """
    
    scraper_activity = defaultdict(list)
    errors = []
    
    try:
        for entry in logging_client.list_entries(filter_=filter_str, max_results=2000):
            timestamp = entry.timestamp.strftime("%H:%M:%S")
            
            # Check for structured logs
            if hasattr(entry, 'json_payload'):
                payload = dict(entry.json_payload)
                
                if payload.get('event') in ['START', 'END']:
                    scraper_name = payload.get('scraper', 'unknown')
                    scraper_activity[scraper_name].append({
                        'time': timestamp,
                        'event': payload['event'],
                        'status': payload.get('status', 'N/A'),
                        'records': payload.get('records_processed')
                    })
            
            # Check for errors
            if entry.severity == 'ERROR':
                message = entry.payload if isinstance(entry.payload, str) else str(entry.json_payload)
                errors.append({
                    'time': timestamp,
                    'message': message[:200]  # Truncate long messages
                })
    
    except Exception as e:
        print(f"Warning: Could not fetch scraper logs: {e}")
    
    return dict(scraper_activity), errors

def print_summary(date, workflows, scraper_activity, errors):
    """Print a clean summary"""
    print(f"\n{'='*80}")
    print(f"  NBA Scrapers Status - {date.strftime('%A, %B %d, %Y')}")
    print(f"{'='*80}\n")
    
    # Workflow Summary
    print("🔄 WORKFLOWS")
    print("-" * 80)
    
    total_runs = 0
    total_success = 0
    total_failed = 0
    
    for workflow_name, runs in workflows.items():
        if isinstance(runs, dict) and 'error' in runs:
            print(f"✗ {workflow_name:30s} | Error: {runs['error']}")
            continue
        
        if not runs:
            print(f"○ {workflow_name:30s} | No executions")
            continue
        
        success = sum(1 for r in runs if r['status'] == 'SUCCEEDED')
        failed = sum(1 for r in runs if r['status'] == 'FAILED')
        
        total_runs += len(runs)
        total_success += success
        total_failed += failed
        
        status = "✓" if failed == 0 else "✗"
        print(f"{status} {workflow_name:30s} | Runs: {len(runs):2d} | ✓ {success:2d} | ✗ {failed:2d}")
        
        # Show execution times
        times = [r['time'] for r in runs]
        print(f"  └─ Execution times: {', '.join(times)}")
        
        # Show errors
        if failed > 0:
            for run in runs:
                if run['status'] == 'FAILED':
                    error_msg = run['error'] if run['error'] else "Unknown error"
                    print(f"     └─ Failed at {run['time']}: {error_msg[:100]}")
    
    print("-" * 80)
    print(f"Total: {total_runs} executions | ✓ {total_success} success | ✗ {total_failed} failed\n")
    
    # Scraper Activity
    if scraper_activity:
        print("🔍 SCRAPER ACTIVITY")
        print("-" * 80)
        
        for scraper_name, events in sorted(scraper_activity.items()):
            success_count = sum(1 for e in events if e['event'] == 'END' and e['status'] == 'SUCCESS')
            failed_count = sum(1 for e in events if e['event'] == 'END' and e['status'] != 'SUCCESS')
            
            status = "✓" if failed_count == 0 else "✗"
            print(f"{status} {scraper_name:30s} | ✓ {success_count:2d} | ✗ {failed_count:2d}")
            
            # Show execution times
            end_events = [e for e in events if e['event'] == 'END']
            if end_events:
                times = [e['time'] for e in end_events[:5]]  # Show first 5
                print(f"  └─ Completion times: {', '.join(times)}")
        
        print("-" * 80 + "\n")
    
    # Errors
    if errors:
        print(f"⚠️  ERRORS ({len(errors)})")
        print("-" * 80)
        
        # Show first 10 errors
        for i, error in enumerate(errors[:10], 1):
            print(f"{i}. [{error['time']}] {error['message']}")
        
        if len(errors) > 10:
            print(f"\n... and {len(errors) - 10} more errors")
        
        print("-" * 80 + "\n")
    else:
        print("✓ No errors found\n")
    
    print("="*80 + "\n")

def main():
    if len(sys.argv) < 2:
        date_arg = "today"
    else:
        date_arg = sys.argv[1]
    
    start_time, end_time, date = get_date_range(date_arg)
    
    print(f"Checking scraper status for {date}...")
    
    # Check workflows
    workflows = check_workflows(start_time, end_time)
    
    # Check scraper logs
    scraper_activity, errors = check_scraper_logs(start_time, end_time)
    
    # Print summary
    print_summary(date, workflows, scraper_activity, errors)

if __name__ == "__main__":
    main()
