# Processor Execution Monitoring

**Status:** Design Phase  
**Version:** 1.0  
**Last Updated:** October 4, 2025

---

## Overview

Monitors processor execution history to detect missing runs, failures, and staleness. Tracks whether processors execute successfully and on schedule by analyzing execution records in BigQuery.

**What This Monitors:** Processor execution (did it run? did it succeed?)  
**Complements:** File Processing Gap Detection (monitors data flow)

---

## Quick Start

### Prerequisites

- `nba_reference.processor_run_history` table must exist
- Processors must log execution records to this table

### Local Testing

```bash
cd monitoring/processor_execution_monitoring

# Validate configuration
python config/processor_config.py

# Check last 7 days
python execution_monitor_job.py

# Check last 14 days
python execution_monitor_job.py --lookback-days=14

# Dry run (no alerts)
python execution_monitor_job.py --dry-run
```

### Deployment

```bash
cd monitoring/processor_execution_monitoring
./deploy.sh
```

---

## How It Works

### Detection Logic

```
1. Query processor_run_history table for date range
   └─> WHERE processor_name = 'gamebook' 
       AND processing_date >= '2025-10-01'

2. Find gaps (missing dates)
   └─> Dates with no successful run

3. Find failures (failed runs)
   └─> Runs with status = 'failed'

4. Check staleness
   └─> Days since last successful run

5. Alert if issues found
```

### What It Detects

- Missing runs (processor never executed for expected date)
- Failed runs (processor ran but failed)
- Staleness (processor hasn't run successfully in N days)
- Scheduler issues (no recent run records at all)

---

## Configuration

### Add Processor to Monitoring

Edit `config/processor_config.py`:

```python
'my_processor': {
    'display_name': 'My Processor Name',
    'execution_table': 'nba_reference.processor_run_history',
    'processor_filter': "processor_name = 'my_processor'",
    'date_field': 'processing_date',
    'status_field': 'status',
    'expected_frequency': 'daily',
    'staleness_threshold_days': 2,
    'enabled': True,
    'priority': 'high',
    'revenue_impact': True
}
```

### Current Processors

- `gamebook_processor` - Gamebook registry processor
- `roster_processor` - Roster registry processor

---

## Required Processor Instrumentation

For monitoring to work, processors must log execution records:

```python
class MyProcessor:
    def run(self, processing_date):
        # Start run
        run_id = self.record_run_start(
            processor_name='my_processor',
            processing_date=processing_date
        )
        
        try:
            # Process data
            result = self.do_work()
            
            # Record success
            self.record_run_complete(
                run_id=run_id,
                status='success',
                records_processed=result['count']
            )
        except Exception as e:
            # Record failure
            self.record_run_complete(
                run_id=run_id,
                status='failed',
                errors=[{
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                }]
            )
            raise
```

---

## Command Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--date` | End date (YYYY-MM-DD) | Today |
| `--lookback-days` | Number of days to check | 7 |
| `--processors` | Comma-separated processor list | All enabled |
| `--dry-run` | Run without sending alerts | False |
| `--json-output` | Output as JSON | False |

---

## Alert Levels

**CRITICAL:** Processor stale (no success in N days)
- Send to: PagerDuty + Slack
- Action: Investigate scheduler immediately

**ERROR:** Failed runs or missing runs
- Send to: Slack #processor-health
- Action: Review error details, retry if needed

**WARNING:** Multiple processors with issues
- Send to: Slack #processor-health
- Action: Review summary

**INFO:** All processors healthy
- Send to: Console only
- Action: None

---

## Comparison with File Processing Gap Detection

**This System (Execution Monitoring):**
- Monitors: Processor execution
- Detects: Scheduler issues, staleness, execution failures
- Requires: Processor instrumentation
- Best for: Complex processors, health tracking

**File Processing Gap Detection:**
- Monitors: Data flow (files → tables)
- Detects: Pub/Sub failures, processing failures
- Requires: No processor changes
- Best for: File-based pipelines

**Use both for comprehensive monitoring.**

---

## Cloud Run Execution

```bash
# Manual execution
gcloud run jobs execute processor-execution-monitor --region=us-west2

# Check last 14 days
gcloud run jobs execute processor-execution-monitor --region=us-west2 \
  --args="--lookback-days=14"

# View logs
gcloud beta run jobs executions logs read <execution-name> --region=us-west2
```

---

## Development Status

**Phase 1: Core Implementation** (Current)
- [x] Execution monitor logic
- [x] Configuration registry
- [x] Cloud Run job entry point
- [x] Deployment scripts
- [ ] Table schema creation
- [ ] Initial processor instrumentation
- [ ] Testing and validation

**Phase 2: Processor Integration**
- [ ] Update gamebook processor to log runs
- [ ] Update roster processor to log runs
- [ ] Validate monitoring works end-to-end

**Phase 3: Production Deployment**
- [ ] Deploy to Cloud Run
- [ ] Configure Cloud Scheduler
- [ ] Enable alerts

---

## Related Documentation

- **Comparison Guide:** See monitoring systems comparison document
- **File Gap Detection:** `monitoring/processing_gap_detection/`
- **Notification System:** `shared/utils/notification_system.py`

---

## Next Steps

1. Create `processor_run_history` table (see schema DDL)
2. Instrument processors to log execution records
3. Test monitoring with real data
4. Deploy to production

---

**Last Updated:** October 4, 2025  
**Status:** Ready for table creation and processor instrumentation