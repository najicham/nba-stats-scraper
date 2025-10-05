# Adding Processors to Gap Detection System

**Version:** 1.0  
**Last Updated:** October 4, 2025

This guide walks through adding a new data processor to the gap detection monitoring system.

---

## Prerequisites

Before adding a processor to monitoring, ensure:

1. **Processor is deployed and working**
   - Data is being scraped to GCS
   - Processor successfully transforms data to BigQuery
   - Pub/Sub integration is functional

2. **BigQuery table has required field**
   - Table must store `source_file_path` (or configurable alternative)
   - Path should be stored WITHOUT `gs://bucket/` prefix
   - Example: `nba-com/player-list/2025-10-01/file.json`

3. **GCS path pattern is known**
   - Determine if it follows simple_date, date_nested, or season_based pattern
   - Test that pattern with actual GCS files

---

## Step-by-Step Guide

### Step 1: Identify Your Processor Pattern

**Pattern Types:**

**Simple Date Pattern** (Most Common)
```
GCS Path: gs://bucket/source/data-type/{date}/file.json
Example:  gs://nba-scraped-data/nba-com/player-list/2025-10-01/20251001_220717.json
Pattern:  'nba-com/player-list/{date}/'
```

**Date + Nested Pattern** (Advanced)
```
GCS Path: gs://bucket/source/data-type/{date}/subdir/file.json
Example:  gs://nba-scraped-data/nba-com/injury-report-data/2025-10-01/17/file.json
Pattern:  'nba-com/injury-report-data/{date}/'
Note:     Requires enhanced GCS inspector (future)
```

**Season-Based Pattern** (Special)
```
GCS Path: gs://bucket/source/data-type/{season}/file.json
Example:  gs://nba-scraped-data/basketball-ref/season-rosters/2024-25/LAL.json
Pattern:  'basketball-ref/season-rosters/{season}/'
Note:     Requires season-to-date mapping (future)
```

### Step 2: Gather Required Information

Create a checklist of information needed:

```
[ ] Processor Name: _______________________
[ ] Display Name: _______________________
[ ] GCS Bucket: _______________________
[ ] GCS Pattern: _______________________
[ ] Pattern Type: simple_date / date_nested / season_based
[ ] BigQuery Dataset: _______________________
[ ] BigQuery Table: _______________________
[ ] Source File Field: _______________________
[ ] Processor Class: _______________________
[ ] Update Frequency: daily / hourly / per_game
[ ] Expected Runs per Day: _______
[ ] Tolerance Hours: _______
[ ] Pub/Sub Topic: _______________________
[ ] Pub/Sub Attributes: { key: value }
[ ] Expected Record Count: min=___ max=___
[ ] Priority: critical / high / medium / low
[ ] Revenue Impact: Yes / No
```

### Step 3: Add Configuration to processor_config.py

Open `monitoring/processing_gap_detection/config/processor_config.py` and add your processor:

```python
'your_processor_name': {
    'display_name': 'Human Readable Name',
    'gcs_bucket': 'nba-scraped-data',
    'gcs_pattern': 'source/data-type/{date}/',
    'gcs_pattern_type': 'simple_date',
    'bigquery_dataset': 'nba_raw',
    'bigquery_table': 'your_table_name',
    'source_file_field': 'source_file_path',
    'processor_class': 'your_module.YourProcessor',
    
    # Scheduling and frequency
    'frequency': 'daily',
    'expected_runs_per_day': 1,
    'tolerance_hours': 6,
    
    # Pub/Sub configuration for retries (Phase 2)
    'pubsub_topic': 'nba-data-processing',
    'pubsub_attributes': {
        'processor': 'your_processor_name',
        'source': 'your_source'
    },
    
    # Validation expectations (optional but recommended)
    'expected_record_count': {
        'min': 100,
        'max': 1000
    },
    
    # Monitoring settings
    'enabled': True,  # Set to False initially for testing
    'priority': 'high',
    'revenue_impact': True,
    'notes': 'Optional notes about implementation'
}
```

### Step 4: Validate Configuration

Run configuration validation:

```bash
cd monitoring/processing_gap_detection
python config/processor_config.py
```

Expected output:
```
✅ Configuration validation passed

PROCESSOR MONITORING CONFIGURATION SUMMARY
============================================================

✅ ENABLED PROCESSORS: 6
  🔴 💰 Your Processor Name
      Pattern: simple_date
      Tolerance: 6h
      Expected records: 100-1000
```

### Step 5: Test with Dry Run

Test the monitor with your processor on a date that has data:

```bash
# Find a date with data in GCS
gsutil ls gs://nba-scraped-data/your-path/2025-*/

# Test monitoring for that date
python processing_gap_monitor_job.py --date=2025-10-01 --processors=your_processor_name --dry-run
```

**Expected Output for Success (No Gap):**
```
INFO - Checking processor: your_processor_name
INFO - Latest file found: gs://nba-scraped-data/your-path/2025-10-01/file.json
INFO - File processing check: your-path/2025-10-01/file.json found 615 records
INFO - ✅ No processing gaps detected for 2025-10-01
```

**Expected Output for Gap Detected:**
```
WARNING - RETRY INFO for your_processor_name: Pub/Sub topic=nba-data-processing...
ERROR - [PROCESSING_ERROR] Processing Gap Detected: Your Processor Name
WARNING - ⚠️  1 processing gap(s) detected - review alerts
```

### Step 6: Test Path Normalization

Verify BigQuery path matching works:

```bash
# Check what's in BigQuery
bq query --use_legacy_sql=false "
SELECT DISTINCT source_file_path 
FROM \`nba-props-platform.nba_raw.your_table_name\`
WHERE source_file_path LIKE '%2025-10-01%'
LIMIT 5
"

# Confirm paths don't have gs://bucket/ prefix
# Good: "nba-com/player-list/2025-10-01/file.json"
# Bad:  "gs://nba-scraped-data/nba-com/player-list/2025-10-01/file.json"
```

If paths include bucket prefix, update your processor to strip it during insert.

### Step 7: Test Record Count Validation

If you set `expected_record_count`, verify it triggers correctly:

```bash
# Set unrealistic counts temporarily
'expected_record_count': {
    'min': 999999,  # Too high
    'max': 999999
}

# Run test - should detect invalid count
python processing_gap_monitor_job.py --date=2025-10-01 --processors=your_processor_name --dry-run
```

### Step 8: Enable in Production

Once testing passes:

1. **Set enabled to True**
   ```python
   'enabled': True,
   ```

2. **Commit configuration**
   ```bash
   git add config/processor_config.py
   git commit -m "feat: add your_processor_name to gap monitoring"
   git push
   ```

3. **Redeploy monitoring job**
   ```bash
   cd monitoring/processing_gap_detection
   ./deploy.sh
   ```

4. **Verify deployment**
   ```bash
   gcloud run jobs execute processing-gap-monitor \
     --region=us-west2 \
     --args="--date=$(date -d yesterday +%Y-%m-%d)"
   ```

---

## Pattern-Specific Guidance

### Simple Date Pattern (Recommended Starting Point)

**Best For:**
- Daily scrapes with one file per date
- Straightforward date-based organization
- Most NBA data processors

**Example Configuration:**
```python
'bdl_player_boxscores': {
    'gcs_pattern': 'ball-dont-lie/boxscores/{date}/',
    'gcs_pattern_type': 'simple_date',
    'tolerance_hours': 4,  # Games should process quickly
    'expected_record_count': {
        'min': 200,   # ~10 games * 20 players
        'max': 1000   # ~15 games * 65 players
    }
}
```

**Common Issues:**
- Date format mismatch: Use YYYY-MM-DD in pattern
- Multiple files per date: GCS inspector returns latest only
- No files for date: Not treated as gap (expected missing data)

### Date + Nested Pattern (Advanced)

**Best For:**
- Hourly snapshots within a date
- Event-specific subdirectories
- Complex data organization

**Example Configuration:**
```python
'nbac_injury_report': {
    'gcs_pattern': 'nba-com/injury-report-data/{date}/',
    'gcs_pattern_type': 'date_nested',
    'nested_structure': 'hourly',  # Metadata for future enhancement
    'tolerance_hours': 3,
    'enabled': False,  # Requires enhanced GCS inspector
    'notes': 'FUTURE: Needs nested path support'
}
```

**Current Limitation:**
- GCS inspector searches top level only
- Enhancement needed to traverse subdirectories
- Temporarily disable these processors

**Future Enhancement:**
```python
# Planned feature
if config.gcs_pattern_type == 'date_nested':
    files = inspector.get_latest_file_recursive(prefix)
```

### Season-Based Pattern (Special Case)

**Best For:**
- Historical roster data by season
- Season-wide statistics
- Non-daily update schedules

**Example Configuration:**
```python
'br_season_rosters': {
    'gcs_pattern': 'basketball-ref/season-rosters/{season}/',
    'gcs_pattern_type': 'season_based',
    'tolerance_hours': 168,  # 7 days (not urgent)
    'enabled': False,  # Requires season-to-date mapping
    'notes': 'FUTURE: Needs season year handling'
}
```

**Current Limitation:**
- Monitoring designed for date-based checks
- Season patterns need date conversion logic
- Temporarily disable these processors

---

## Tolerance Hours Guidelines

Choose tolerance based on data urgency and processing characteristics:

| Data Type | Example | Tolerance | Rationale |
|-----------|---------|-----------|-----------|
| Game Results | Box Scores | 4 hours | Critical for prop settlement |
| Player Lists | Rosters | 6 hours | Important but not urgent |
| Injury Reports | Status Updates | 3 hours | Affects prop availability |
| Historical Data | Season Stats | 24 hours | Can wait longer |
| Analytics | Standings | 12 hours | Not time-sensitive |

**Formula:**
```
tolerance_hours = typical_processing_time + buffer_for_retries + business_urgency_factor

Example:
- Typical: 30 minutes
- Buffer: 2 hours (allows 4 retries at 30 min each)
- Urgency: High (revenue impact) = 1 hour minimum
- Total: 3-4 hours tolerance
```

---

## Expected Record Count Guidelines

Set realistic ranges based on data characteristics:

**Box Scores:**
```python
'expected_record_count': {
    'min': 200,   # Minimum: 10 games * 20 players
    'max': 1000   # Maximum: 15 games * 65 players  
}
```

**Player Lists:**
```python
'expected_record_count': {
    'min': 500,   # Active NBA players minimum
    'max': 700    # Including G-League call-ups
}
```

**Injury Reports:**
```python
'expected_record_count': {
    'min': 10,    # At least a few injured players
    'max': 200    # Many players with various statuses
}
```

**Skip Count Validation:**
```python
'expected_record_count': None  # When counts vary widely
```

---

## Common Issues and Solutions

### Issue: Path Mismatch (Most Common)

**Symptom:**
```
INFO - File processing check: gs://bucket/path/file.json found 0 records
ERROR - Processing Gap Detected (but file IS in BigQuery!)
```

**Diagnosis:**
```bash
# Check what's stored in BigQuery
bq query --use_legacy_sql=false "
SELECT DISTINCT source_file_path FROM \`your.table.name\` LIMIT 5
"
```

**Solution:**
- If paths include `gs://bucket/`, fix your processor to strip prefix
- Gap detector automatically normalizes, but data must match

### Issue: Multiple Files Per Date

**Symptom:**
```
INFO - Latest file found: gs://bucket/path/2025-10-01/file_v2.json
INFO - File processing check: path/2025-10-01/file_v2.json found 0 records
(But file_v1.json WAS processed)
```

**Solution:**
- Ensure processor handles all files for a date
- Or use timestamp-based latest file selection
- Or aggregate multiple files in BigQuery query

### Issue: Wrong Pattern Type

**Symptom:**
```
INFO - Checking processor: your_processor
ERROR - No files found matching pattern
```

**Solution:**
```bash
# Test GCS pattern manually
gsutil ls gs://nba-scraped-data/your-pattern/2025-10-01/

# Adjust pattern if needed:
# Wrong: 'source/type/2025-10-01/'  # Hard-coded date
# Right: 'source/type/{date}/'      # Template variable
```

### Issue: Tolerance Too Short

**Symptom:**
```
WARNING - Processing Gap Detected after 2.5 hours
(But processor normally takes 3 hours)
```

**Solution:**
- Increase `tolerance_hours` based on actual processing time
- Add buffer for retries and network delays
- Monitor processor logs to determine typical duration

---

## Testing Checklist

Before enabling in production, verify:

- [ ] Configuration validates: `python config/processor_config.py`
- [ ] GCS pattern matches actual files: `gsutil ls gs://...`
- [ ] BigQuery paths don't include bucket prefix
- [ ] Dry run succeeds with no gaps: `--dry-run` on known good date
- [ ] Dry run detects gaps: `--dry-run` on known missing data
- [ ] Record count validation works (if configured)
- [ ] Tolerance window is appropriate for processor
- [ ] Priority and revenue_impact are set correctly
- [ ] Pub/Sub attributes match processor expectations
- [ ] Documentation updated with processor details

---

## Multiple Processors at Once

To add several processors efficiently:

1. **Batch configuration**
   - Add all configs to `processor_config.py` at once
   - Set all to `enabled: False` initially

2. **Validate batch**
   ```bash
   python config/processor_config.py
   ```

3. **Test individually**
   ```bash
   for proc in proc1 proc2 proc3; do
     echo "Testing $proc..."
     python processing_gap_monitor_job.py \
       --date=2025-10-01 \
       --processors=$proc \
       --dry-run
   done
   ```

4. **Enable successful ones**
   - Set `enabled: True` for processors that pass testing
   - Leave problematic ones disabled with notes

5. **Deploy once**
   ```bash
   ./deploy.sh
   ```

---

## Getting Help

**Configuration Issues:**
- Check processor reference documentation
- Review existing similar processors
- Verify GCS paths with `gsutil ls`

**Detection Issues:**
- Run with `--dry-run` and examine logs
- Query BigQuery directly to check data
- Test path normalization separately

**Alert Issues:**
- Check Cloud Logging for delivery status
- Verify webhook URLs in environment variables
- Test notification system independently

**File-specific Issues:**
```bash
# Share these details when asking for help:
echo "Processor: your_processor_name"
echo "GCS Pattern: $(gsutil ls gs://your-path/2025-10-01/)"
echo "BigQuery Paths: $(bq query --use_legacy_sql=false 'SELECT DISTINCT source_file_path FROM your.table LIMIT 5')"
echo "Expected vs Actual: min=X max=Y actual=Z"
```

---

## Appendix: Full Example

Here's a complete example adding a new processor:

```python
# config/processor_config.py

'espn_team_rosters': {
    # Basic identification
    'display_name': 'ESPN Team Rosters',
    'processor_class': 'espn_team_roster_processor.EspnTeamRosterProcessor',
    
    # GCS configuration
    'gcs_bucket': 'nba-scraped-data',
    'gcs_pattern': 'espn/rosters/{date}/team_{team_abbr}/',
    'gcs_pattern_type': 'simple_date',
    
    # BigQuery configuration
    'bigquery_dataset': 'nba_raw',
    'bigquery_table': 'espn_team_rosters',
    'source_file_field': 'source_file_path',
    
    # Scheduling
    'frequency': 'daily',
    'expected_runs_per_day': 1,
    'tolerance_hours': 8,  # Backup data, not urgent
    
    # Pub/Sub for retries
    'pubsub_topic': 'nba-data-processing',
    'pubsub_attributes': {
        'processor': 'espn_team_rosters',
        'source': 'espn',
        'data_type': 'rosters'
    },
    
    # Validation
    'expected_record_count': {
        'min': 15,   # One team minimum
        'max': 500   # All 30 teams maximum
    },
    
    # Monitoring settings
    'enabled': True,
    'priority': 'medium',
    'revenue_impact': False,  # Backup source only
    'docs_url': 'https://docs.example.com/processors/espn-rosters',
    'notes': 'Backup validation source for player rosters'
}
```

**Test Commands:**
```bash
# Validate config
python config/processor_config.py

# Test on known good date
python processing_gap_monitor_job.py \
  --date=2025-08-22 \
  --processors=espn_team_rosters \
  --dry-run

# Deploy
./deploy.sh

# Verify in production
gcloud run jobs execute processing-gap-monitor \
  --region=us-west2 \
  --args="--date=2025-08-22,--processors=espn_team_rosters"
```

---

**Questions? Found a bug?** Update this guide or consult the Architecture documentation.