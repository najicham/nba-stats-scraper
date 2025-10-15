# Monitoring Scripts

**Location:** `monitoring/scripts/`

Command-line tools for monitoring NBA Props Platform scrapers, workflows, and data pipelines.

## Quick Start

```bash
# Check today's status
./monitoring/scripts/nba-monitor status

# Check yesterday
./monitoring/scripts/nba-monitor status yesterday

# View recent errors
./monitoring/scripts/nba-monitor errors

# View workflow executions
./monitoring/scripts/nba-monitor workflows
```

## Tools

### `nba-monitor`
**Main monitoring CLI tool** with colored output and multiple commands.

**Commands:**
- `status [date]` - Daily status summary (workflows + errors)
- `workflows [hours]` - Recent workflow executions
- `errors [hours]` - Recent error logs
- `summary [date]` - Full detailed summary

**Examples:**
```bash
# Today's status
nba-monitor status

# Yesterday's status  
nba-monitor status yesterday

# Specific date
nba-monitor status 2025-10-14

# Last 48 hours of workflows
nba-monitor workflows 48

# Last 12 hours of errors
nba-monitor errors 12
```

**Output includes:**
- ✓/✗ Status indicators
- Color-coded results (green=success, red=errors)
- Workflow execution times and durations
- Error grouping and counts
- Execution IDs for debugging

### `check-scrapers.py`
**Simpler status checker** for daily scraper runs.

```bash
python monitoring/scripts/check-scrapers.py today
python monitoring/scripts/check-scrapers.py yesterday
python monitoring/scripts/check-scrapers.py 2025-10-14
```

**Output:**
- Workflow execution summary
- Scraper activity (if structured logging is enabled)
- Error summary with timestamps

### `workflow_monitoring.py`
**Python library** for programmatic monitoring access.

```python
from monitoring.scripts.workflow_monitoring import WorkflowMonitor

monitor = WorkflowMonitor("nba-props-platform")

# Get workflow executions
executions = monitor.get_all_workflow_executions(hours=24)

# Get scraper logs
logs = monitor.get_scraper_logs(hours=24, severity="ERROR")

# Generate daily summary
summary = monitor.generate_daily_summary("2025-10-14")
print(summary)
```

**Classes:**
- `WorkflowMonitor` - Main monitoring class
- `StructuredLogger` - For adding structured logging to scrapers
- `ScraperRun` - Data class for scraper runs
- `WorkflowRun` - Data class for workflow executions

## Other Monitoring Scripts

### `system_status.sh`
Quick system health check.

```bash
./monitoring/scripts/system_status.sh
```

Shows:
- Cloud Run service status
- Recent workflow executions
- BigQuery table row counts
- GCS bucket status

### `scraper_debug.sh`
Debug specific scraper issues.

```bash
./monitoring/scripts/scraper_debug.sh bdl_box_scores
```

### `tomorrow_morning_checklist.sh`
Pre-emptive checks before the next day's operations.

```bash
./monitoring/scripts/tomorrow_morning_checklist.sh
```

Verifies:
- All scheduled jobs are enabled
- Recent executions were successful
- No pending errors
- Data is up to date

### `monitoring_dashboard.sh`
Generate a comprehensive monitoring dashboard.

```bash
./monitoring/scripts/monitoring_dashboard.sh
```

## Setting Up Daily Monitoring

### Option 1: Cron Job
```bash
# Add to crontab (runs at 9am daily)
0 9 * * * cd ~/code/nba-stats-scraper && ./monitoring/scripts/nba-monitor status yesterday | mail -s "NBA Scrapers Daily Report" your-email@gmail.com
```

### Option 2: Cloud Scheduler
```bash
# Create a Cloud Function that calls nba-monitor
# Schedule it to run daily and send reports
```

### Option 3: Manual Morning Routine
```bash
# Add to your ~/.bashrc or create an alias
alias nba-check='cd ~/code/nba-stats-scraper && ./monitoring/scripts/nba-monitor status yesterday'

# Then just run:
nba-check
```

## Adding to PATH

For system-wide access:

```bash
# Add to ~/.bashrc or ~/.zshrc
export PATH="$PATH:$HOME/code/nba-stats-scraper/monitoring/scripts"

# Reload shell
source ~/.bashrc

# Now you can run from anywhere:
nba-monitor status
```

Or create a symlink:

```bash
sudo ln -s ~/code/nba-stats-scraper/monitoring/scripts/nba-monitor /usr/local/bin/nba-monitor
```

## Integration with Existing Monitoring

### With Email Alerts
The monitoring tools complement your existing email alerting system:
- Email alerts notify you of issues in real-time
- Monitoring tools help you investigate and understand patterns

### With Structured Logging
Enable structured logging in your scrapers for better monitoring:

```python
from monitoring.scripts.workflow_monitoring import StructuredLogger

logger = StructuredLogger("nba-scrapers")

# In your scraper
logger.log_scraper_start("bdl_box_scores", date="2025-10-14")
try:
    data = scrape()
    logger.log_scraper_end("bdl_box_scores", status="SUCCESS", records_processed=len(data))
except Exception as e:
    logger.log_error("bdl_box_scores", e)
    raise
```

This enables the monitoring tools to show per-scraper status.

## Troubleshooting

### "No executions found"
- Check that workflows ran on that date
- Verify the workflow names match (use `gcloud workflows list`)
- Check the date format (YYYY-MM-DD)

### "Permission denied"
```bash
chmod +x monitoring/scripts/nba-monitor
chmod +x monitoring/scripts/check-scrapers.py
```

### "Module not found"
Ensure you're in the project root or have proper PYTHONPATH:
```bash
cd ~/code/nba-stats-scraper
export PYTHONPATH=$PYTHONPATH:$(pwd)
```

### Empty error messages
This happens when errors are in text_payload instead of json_payload. The monitoring tools handle both formats.

## Development

To add a new monitoring command:

1. Add function to `nba-monitor`:
```python
def cmd_my_command():
    """My new command"""
    # Implementation
```

2. Update main():
```python
elif cmd == "my-command":
    cmd_my_command()
```

3. Update docstring with usage
4. Update this README

## Related Documentation

- [Workflow Monitoring Guide](../../docs/WORKFLOW_MONITORING.md) (wiki)
- [Troubleshooting Guide](../../docs/TROUBLESHOOTING.md) (wiki)
- [System Architecture](../../docs/ARCHITECTURE.md) (wiki)
