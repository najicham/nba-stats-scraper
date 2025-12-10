# PCF Failure Cleanup Script

## Overview

This script cleans up stale/obsolete failure records from `nba_processing.precompute_failures` table for the PlayerCompositeFactorsProcessor (PCF).

## Background

During Dec 1-6, 2021, there were 847 failure records with:
- `failure_category='calculation_error'`
- `failure_reason` containing 'No module named shared.utils.hash_utils'

However, the PCF table (`nba_warehouse.player_composite_factors`) DOES have data for these dates:
- Dec 1: 174 players
- Dec 2: 100 players
- Dec 3: 182 players
- Dec 4: 131 players
- Dec 5: 78 players
- Dec 6: 182 players

These failure records are stale - they were created during a failed run that was later successfully re-run after fixing the import error.

## What the Script Does

1. **Verifies** PCF table has data for the date range (Dec 1-6, 2021)
2. **Counts** stale failure records matching the criteria
3. **Deletes** the stale failure records
4. **Verifies** the deletion was successful

## Usage

### Dry Run (Recommended First)

```bash
python scripts/cleanup_stale_pcf_failures.py --dry-run
```

This will show you:
- How many PCF records exist for each date
- How many failure records will be deleted
- Sample of the records to be deleted
- NO actual deletions will be made

### Actual Cleanup

```bash
python scripts/cleanup_stale_pcf_failures.py
```

This will execute the DELETE query and remove the stale records.

### Custom Date Range

```bash
python scripts/cleanup_stale_pcf_failures.py --start-date 2021-12-01 --end-date 2021-12-10
```

## Prerequisites

1. Google Cloud credentials configured (via `GOOGLE_APPLICATION_CREDENTIALS` env var)
2. BigQuery access to:
   - `nba_warehouse.player_composite_factors` (read)
   - `nba_processing.precompute_failures` (read/write)
3. Python packages:
   - `google-cloud-bigquery`

## Safety Features

- Dry run mode to preview changes
- Verifies PCF data exists before deletion
- Shows sample records before deletion
- Post-deletion verification
- Detailed logging of all operations

## SQL Query Used

```sql
DELETE FROM nba_processing.precompute_failures
WHERE processor_name = 'PlayerCompositeFactorsProcessor'
  AND failure_category = 'calculation_error'
  AND failure_reason LIKE '%hash_utils%'
  AND analysis_date >= '2021-12-01'
  AND analysis_date <= '2021-12-06';
```

## Expected Results

**Before:**
- 847 stale failure records for Dec 1-6, 2021

**After:**
- 0 failure records matching the criteria
- PCF table data remains unchanged (847 records in `player_composite_factors`)

## Troubleshooting

### Authentication Error

If you get authentication errors, ensure:
```bash
export GOOGLE_APPLICATION_CREDENTIALS=/home/naji/code/nba-stats-scraper/keys/service-account-dev.json
```

### No Data Found

If the script reports no PCF data found, check:
- Date range is correct
- You have read access to `nba_warehouse.player_composite_factors`
- The table actually has data for those dates

### Import Errors

If you get import errors, ensure you're running from the project root:
```bash
cd /home/naji/code/nba-stats-scraper
python scripts/cleanup_stale_pcf_failures.py --dry-run
```

## Script Location

`/home/naji/code/nba-stats-scraper/scripts/cleanup_stale_pcf_failures.py`
