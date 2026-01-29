# Workstream 3: Data Quality Prevention

## Mission
Prevent data quality issues from occurring in the first place, rather than detecting them after the fact. Add guardrails that catch issues at commit time, deploy time, and processing time.

## Current State

### What Exists
- Pre-commit hook for schema validation (`.pre-commit-hooks/validate_schema_fields.py`)
- Spot check system (`scripts/spot_check_data_accuracy.py`)
- Golden dataset verification (`scripts/verify_golden_dataset.py`)
- Data quality fields in `player_game_summary` table

### Known Issues Found Today

1. **Minutes fix deployed AFTER data processed**
   - Jan 25, 26, 27 data had 63% minutes coverage
   - Fix was committed but data was processed before deployment
   - Required manual reprocessing of 3 days

2. **Early exit blocked backfill**
   - `ENABLE_GAMES_FINISHED_CHECK` prevented Jan 25 reprocessing
   - Games showed "not finished" due to stale ESPN data
   - **Fix applied**: Skip check when `backfill_mode=True`

3. **Firestore completion not tracked for all processors**
   - `TeamDefenseGameSummaryProcessor` wasn't in `ANALYTICS_TRIGGERS`
   - Phase 3 showed 2/5 complete instead of 5/5

4. **Scraper failures not cleared after backfill**
   - bdb_pbp_scraper showed 3 gaps, but 2 were already backfilled
   - Postponed games counted as failures

## Goals

### 1. Schema Validation Pre-Commit Hook
Enhance existing hook to catch:
- Fields written to BigQuery that don't exist in schema
- Type mismatches (string vs int)
- Missing required fields

### 2. "Stale Code" Detection
Detect when data is processed by outdated code:
- Compare deployment timestamp to processing timestamp
- Warn if code is > 24 hours old
- Add `processor_version` field to output records

### 3. Golden Dataset Nightly Verification
Run `verify_golden_dataset.py` as part of overnight processing:
- Verify rolling averages match expected values
- Alert if any verification fails
- Track accuracy over time

### 4. Fix Early Exit Issues
The `EarlyExitMixin` has several checks that can block processing:
- `ENABLE_GAMES_FINISHED_CHECK` - blocked Jan 25 reprocessing
- `ENABLE_STALE_DATA_CHECK` - can block on stale dependencies
- Need better handling for backfill scenarios

### 5. Automatic Scraper Failure Cleanup
- Verify data exists before counting as gap
- Handle postponed games automatically
- Clear failures after successful backfill

## Key Files

### Pre-Commit Hooks
```
.pre-commit-hooks/
├── validate_schema_fields.py   # Schema validation
├── check_config_drift.sh       # Config drift detection
└── ...
```

### Data Quality Infrastructure
```
scripts/
├── spot_check_data_accuracy.py
├── verify_golden_dataset.py
└── validate_tonight_data.py

shared/processors/patterns/
├── early_exit_mixin.py         # Early exit conditions
├── circuit_breaker_mixin.py    # Circuit breaker pattern
└── ...
```

### Schema Definitions
```
schemas/bigquery/
├── nba_analytics/
│   ├── player_game_summary.sql
│   ├── team_offense_game_summary.sql
│   └── ...
├── nba_predictions/
│   ├── ml_feature_store_v2.sql
│   └── player_prop_predictions.sql
└── nba_orchestration/
    ├── phase_execution_log.sql
    └── scraper_failures.sql
```

## Implementation Details

### 1. Enhanced Schema Validation

Modify `.pre-commit-hooks/validate_schema_fields.py`:
```python
def validate_processor_output(processor_file, schema_file):
    """
    Extract fields written by processor, compare to schema.

    Checks:
    1. All fields written exist in schema
    2. Field types match (inferred from code)
    3. Required fields are always written
    """
    pass
```

### 2. Processor Version Tracking

Add to all processors:
```python
def _get_processor_version(self) -> str:
    """Return git commit hash or deployment timestamp."""
    import subprocess
    try:
        return subprocess.check_output(
            ['git', 'rev-parse', 'HEAD']
        ).decode().strip()[:8]
    except:
        return os.environ.get('K_REVISION', 'unknown')

def process(self, ...):
    record['processor_version'] = self._get_processor_version()
    record['processed_at'] = datetime.utcnow().isoformat()
```

### 3. Golden Dataset Automation

Create `bin/monitoring/verify_golden_dataset.sh`:
```bash
#!/bin/bash
# Run as part of daily health check

python scripts/verify_golden_dataset.py
if [ $? -ne 0 ]; then
    # Send Slack alert
    curl -X POST "$SLACK_WEBHOOK_URL_ERROR" \
        -d '{"text": "Golden dataset verification FAILED"}'
    exit 1
fi
```

### 4. Fix Early Exit for Backfill

Already fixed in Session 8, but need to verify:
```python
# shared/processors/patterns/early_exit_mixin.py
def should_exit_early(self, game_date, **kwargs):
    # Skip games finished check in backfill mode
    if kwargs.get('backfill_mode'):
        return False, "Backfill mode - skipping early exit checks"
    # ... rest of checks
```

### 5. Scraper Failure Auto-Cleanup

Create scheduled job to:
1. Check if data exists in GCS/BigQuery for each failure
2. If data exists, mark failure as backfilled
3. Check game status - if postponed, mark accordingly
4. Alert only for genuine gaps

## Validation Improvements

### Add to validate_tonight_data.py:

```python
def check_processor_version_consistency(self, game_date):
    """Verify all records processed by same code version."""
    query = f"""
    SELECT
        processor_version,
        COUNT(*) as records
    FROM nba_analytics.player_game_summary
    WHERE game_date = '{game_date}'
    GROUP BY processor_version
    """
    # Alert if multiple versions found
```

### Add to daily_health_check.sh:

```bash
# Check for stale deployments
check_deployment_freshness() {
    for service in nba-phase3-analytics-processors nba-phase4-precompute-processors; do
        deployed_at=$(gcloud run services describe $service --region=us-west2 \
            --format="value(status.conditions[0].lastTransitionTime)")
        # Alert if > 24 hours old and commits exist
    done
}
```

## Success Criteria

1. **Pre-commit catches schema mismatches** - Before code is committed
2. **Stale code detection** - Alert if processing with old deployment
3. **Golden dataset runs nightly** - Automatic verification
4. **Backfill works reliably** - No false early exits
5. **Scraper failures auto-cleared** - No manual cleanup needed

## Testing Plan

1. **Schema validation**: Create intentional mismatch, verify hook catches it
2. **Stale code**: Process with old deployment, verify detection
3. **Golden dataset**: Run against last 7 days, verify accuracy
4. **Backfill**: Reprocess a date, verify no early exit
5. **Scraper cleanup**: Create test failure, verify auto-cleanup

## Related Documentation
- `docs/05-development/schema-management.md`
- `docs/06-testing/SPOT-CHECK-SYSTEM.md`
- Session 6 system audit: `docs/09-handoff/2026-01-27-SESSION-6-HANDOFF.md`
