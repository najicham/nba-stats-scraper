# Backfill Guide

Complete guide to safely running backfills on the NBA Props Platform.

**Last Updated:** 2025-10-14

---

## Table of Contents
- [Overview](#overview)
- [Before You Start](#before-you-start)
- [Backfill Checklist](#backfill-checklist)
- [Running a Backfill](#running-a-backfill)
- [Monitoring Progress](#monitoring-progress)
- [Common Issues](#common-issues)
- [Best Practices](#best-practices)

---

## Overview

### What is a Backfill?

A backfill is the process of retroactively collecting and processing historical data that was:
- Never collected (new data source)
- Collected but not processed
- Collected with errors and needs retry
- Outdated and needs refresh

### Why Backfills Need Special Care

**Risks:**
- 📧 **Email floods** - Hundreds of error emails can overwhelm Gmail
- 💰 **Cost spikes** - Processing large volumes quickly can be expensive
- 🚫 **Rate limits** - APIs may block you for too many requests
- ⏱️ **Long runtime** - Backfills can take hours or days
- 💥 **Service disruption** - Can interfere with live data collection

**This guide helps you avoid these issues.**

---

## Before You Start

### 1. Understand the Scope

```bash
# Calculate how much data you'll process
# Example: Backfill 2024-25 season (82 games per team, 30 teams)
TOTAL_GAMES = 82 * 30 / 2  # = 1,230 games
ITEMS_PER_GAME = 20        # players per game
TOTAL_ITEMS = TOTAL_GAMES * ITEMS_PER_GAME  # = 24,600 items
```

**Questions to answer:**
- How many dates? (90 days? 1 year?)
- How many items per date? (10 games? 300 players?)
- Total items to process? (1,000? 100,000?)
- Estimated runtime? (1 hour? 12 hours?)

### 2. Check API Rate Limits

| API | Rate Limit | Backfill Strategy |
|-----|------------|-------------------|
| Ball Don't Lie | 60 req/min | Add 1s delay between requests |
| The Odds API | 500 req/month | Spread backfill over multiple days |
| NBA.com | ~100 req/min | Use proxy rotation |
| Big Ball Data | No limit | Can run full speed |

### 3. Test with Small Range First

**ALWAYS start with a small test:**

```python
# ❌ DON'T start with this
backfill_box_scores(
    start_date="2024-10-01",
    end_date="2025-04-30"  # 6 months!
)

# ✅ DO test with this first
backfill_box_scores(
    start_date="2025-10-01",
    end_date="2025-10-03"  # 3 days only
)
```

### 4. Choose the Right Time

**Best times to run backfills:**
- ✅ **Off-season** (May - September)
- ✅ **Weekdays** during business hours (easier to monitor)
- ✅ **After verifying daily workflows are working**

**Avoid:**
- ❌ Game nights (6pm-11pm PT)
- ❌ Right before important deadlines
- ❌ When you can't monitor progress

---

## Backfill Checklist

Before starting a large backfill, check off these items:

### Pre-Flight Checklist

- [ ] **Scope calculated** - Know exactly how many items
- [ ] **Test completed** - Tested with 2-3 days successfully
- [ ] **Alert batching enabled** - Won't flood email
- [ ] **Rate limiting configured** - Won't hit API limits  
- [ ] **Progress logging added** - Can track progress
- [ ] **Resumable** - Can restart if interrupted
- [ ] **Time allocated** - Have time to monitor
- [ ] **Dependencies verified** - Scrapers/processors ready
- [ ] **Notification plan** - Team knows you're running it

### During Backfill

- [ ] **Monitor logs** - Check progress every 15-30 min
- [ ] **Watch for errors** - Look for patterns
- [ ] **Check API quotas** - Ensure not hitting limits
- [ ] **Monitor costs** - BigQuery/GCS usage
- [ ] **Keep team informed** - Update on progress

### Post-Backfill

- [ ] **Validate data** - Run validation queries
- [ ] **Review errors** - Investigate any failures
- [ ] **Update documentation** - Note any issues found
- [ ] **Send summary** - Email team with results

---

## Running a Backfill

### Option 1: Using Smart Alert Batching (Recommended)

This prevents email floods automatically.

```python
"""
File: backfill_jobs/raw/bdl_boxscores/backfill_box_scores.py
"""

from datetime import datetime, timedelta
from shared.utils.smart_alerting import SmartAlertManager
from scrapers.balldontlie.bdl_box_scores import BdlBoxScoresScraper
import time

def backfill_box_scores(start_date: str, end_date: str):
    """
    Backfill BDL box scores with alert batching
    
    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
    """
    
    # Initialize alert manager
    alert_mgr = SmartAlertManager()
    
    # Enable batch mode (no email flood!)
    alert_mgr.enable_backfill_mode()
    
    # Initialize scraper
    scraper = BdlBoxScoresScraper()
    
    # Generate date range
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    current = start
    
    # Track stats
    total_dates = 0
    successful = 0
    failed = 0
    
    print(f"Starting backfill from {start_date} to {end_date}")
    print(f"Estimated dates: {(end - start).days + 1}")
    print("-" * 60)
    
    try:
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            total_dates += 1
            
            try:
                # Run scraper for this date
                result = scraper.scrape(date=date_str)
                
                print(f"✓ {date_str}: {result.get('record_count', 0)} records")
                successful += 1
                
                # Rate limiting (if needed)
                time.sleep(1)  # 1 second between requests
                
            except Exception as e:
                # Queue error (doesn't send email yet)
                alert_mgr.record_error({
                    "scraper": "bdl_box_scores",
                    "date": date_str,
                    "error_type": type(e).__name__,
                    "error": str(e)
                })
                
                print(f"✗ {date_str}: {str(e)[:80]}")
                failed += 1
            
            # Progress update every 10 dates
            if total_dates % 10 == 0:
                success_rate = (successful / total_dates) * 100
                print(f"\nProgress: {total_dates} dates | "
                      f"✓ {successful} | ✗ {failed} | "
                      f"Success rate: {success_rate:.1f}%\n")
            
            current += timedelta(days=1)
    
    finally:
        # Send ONE summary email with all errors
        alert_mgr.disable_backfill_mode(send_summary=True)
    
    # Final summary
    print("\n" + "=" * 60)
    print("BACKFILL COMPLETE")
    print("=" * 60)
    print(f"Total dates: {total_dates}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Success rate: {(successful/total_dates)*100:.1f}%")
    
    return {
        "total": total_dates,
        "successful": successful,
        "failed": failed
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 3:
        print("Usage: python backfill_box_scores.py START_DATE END_DATE")
        print("Example: python backfill_box_scores.py 2025-01-01 2025-03-31")
        sys.exit(1)
    
    start = sys.argv[1]
    end = sys.argv[2]
    
    result = backfill_box_scores(start, end)
```

**Run it:**
```bash
# Test with small range first
python backfill_jobs/raw/bdl_boxscores/backfill_box_scores.py 2025-10-01 2025-10-03

# After test succeeds, run full range
python backfill_jobs/raw/bdl_boxscores/backfill_box_scores.py 2024-10-01 2025-04-30
```

### Option 2: Resumable Backfill

For very long backfills, make it resumable:

```python
import json
from pathlib import Path

def backfill_with_checkpoint(start_date: str, end_date: str):
    """Backfill that can be resumed if interrupted"""
    
    checkpoint_file = "backfill_checkpoint.json"
    
    # Load checkpoint if exists
    if Path(checkpoint_file).exists():
        with open(checkpoint_file, 'r') as f:
            checkpoint = json.load(f)
            last_date = checkpoint['last_processed']
            start = datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)
            print(f"Resuming from {start.strftime('%Y-%m-%d')}")
    else:
        start = datetime.strptime(start_date, "%Y-%m-%d")
    
    end = datetime.strptime(end_date, "%Y-%m-%d")
    current = start
    
    alert_mgr = SmartAlertManager()
    alert_mgr.enable_backfill_mode()
    
    try:
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            
            try:
                scrape_data(date_str)
                
                # Save checkpoint after each successful date
                with open(checkpoint_file, 'w') as f:
                    json.dump({
                        'last_processed': date_str,
                        'timestamp': datetime.now().isoformat()
                    }, f)
                
            except Exception as e:
                alert_mgr.record_error({
                    "date": date_str,
                    "error": str(e)
                })
            
            current += timedelta(days=1)
    
    finally:
        alert_mgr.disable_backfill_mode(send_summary=True)
        
        # Clean up checkpoint when done
        if Path(checkpoint_file).exists():
            Path(checkpoint_file).unlink()
```

### Option 3: Parallel Backfill

For faster backfills (use with caution):

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def backfill_parallel(dates: list, max_workers: int = 5):
    """
    Backfill multiple dates in parallel
    
    CAUTION: Only use if:
    - API has high rate limits
    - You have quota for parallel requests
    - You're monitoring closely
    """
    
    alert_mgr = SmartAlertManager()
    alert_mgr.enable_backfill_mode()
    
    results = {"success": 0, "failed": 0}
    
    def process_date(date_str):
        try:
            scrape_data(date_str)
            return ("success", date_str)
        except Exception as e:
            alert_mgr.record_error({
                "date": date_str,
                "error": str(e)
            })
            return ("failed", date_str)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_date, d): d for d in dates}
        
        for future in as_completed(futures):
            status, date = future.result()
            results[status] += 1
            
            # Progress update
            total = results["success"] + results["failed"]
            print(f"Progress: {total}/{len(dates)} | "
                  f"✓ {results['success']} | "
                  f"✗ {results['failed']}")
    
    alert_mgr.disable_backfill_mode(send_summary=True)
    
    return results
```

---

## Monitoring Progress

### During Backfill

**Terminal output:**
```bash
Starting backfill from 2025-01-01 to 2025-03-31
Estimated dates: 90
------------------------------------------------------------
✓ 2025-01-01: 12 records
✓ 2025-01-02: 15 records
✗ 2025-01-03: ConnectionError: Proxy failed
✓ 2025-01-04: 10 records
...

Progress: 10 dates | ✓ 9 | ✗ 1 | Success rate: 90.0%
```

**In another terminal:**
```bash
# Watch for new files in GCS
watch -n 30 'gsutil ls gs://nba-props-platform-raw/bdl_box_scores/2025/01/ | tail -5'

# Monitor error logs
python monitoring/scripts/nba-monitor errors 1
```

### After Backfill

**Validation queries:**

```sql
-- Check data was loaded
SELECT 
  DATE(game_date) as date,
  COUNT(*) as records
FROM `nba-props-platform.raw.bdl_box_scores`
WHERE game_date BETWEEN '2025-01-01' AND '2025-03-31'
GROUP BY date
ORDER BY date;

-- Look for gaps
WITH date_range AS (
  SELECT DATE('2025-01-01') + INTERVAL day DAY as date
  FROM UNNEST(GENERATE_ARRAY(0, 89)) as day
)
SELECT dr.date
FROM date_range dr
LEFT JOIN (
  SELECT DISTINCT DATE(game_date) as date
  FROM `nba-props-platform.raw.bdl_box_scores`
) bq ON dr.date = bq.date
WHERE bq.date IS NULL;
```

---

## Common Issues

### Issue 1: Too Many Errors

**Symptoms:**
- Error rate > 10%
- Same error for multiple dates

**Diagnosis:**
```bash
# Check error patterns
python monitoring/scripts/nba-monitor errors 24
```

**Solutions:**
- **Rate limiting:** Add delays between requests
- **API down:** Wait and retry later
- **Data format changed:** Update scraper/processor
- **Invalid date range:** Check if data exists for those dates

### Issue 2: Slow Progress

**Symptoms:**
- Processing < 10 dates per minute
- Backfill taking much longer than estimated

**Diagnosis:**
```python
# Add timing
import time
start_time = time.time()
scrape_data(date)
elapsed = time.time() - start_time
print(f"Took {elapsed:.2f}s")
```

**Solutions:**
- **Slow API:** Normal, can't fix
- **Slow processing:** Optimize processor code
- **Rate limiting:** Expected if delays added
- **Network issues:** Check connection

### Issue 3: Running Out of Memory

**Symptoms:**
- Script crashes after processing many dates
- "Memory limit exceeded" errors

**Solutions:**
```python
# Process in batches
def backfill_in_batches(start, end, batch_size=10):
    current = start
    
    while current <= end:
        batch_end = min(current + timedelta(days=batch_size-1), end)
        
        # Process one batch
        backfill_box_scores(
            current.strftime("%Y-%m-%d"),
            batch_end.strftime("%Y-%m-%d")
        )
        
        # Clear memory between batches
        import gc
        gc.collect()
        
        current = batch_end + timedelta(days=1)
```

---

## Best Practices

### 1. Start Small, Then Scale

```python
# Day 1: Test with 3 days
backfill(start="2025-10-01", end="2025-10-03")

# Day 2: If successful, try 1 week
backfill(start="2025-10-01", end="2025-10-07")

# Day 3: If successful, run full range
backfill(start="2024-10-01", end="2025-04-30")
```

### 2. Run During Off-Peak Hours

**Best:** Weekdays 9am-5pm PT (you can monitor)  
**Okay:** Weeknights 11pm-6am PT (automated)  
**Avoid:** Game nights 6pm-11pm PT (interferes with live data)

### 3. Document Your Backfill

Create a record in `docs/investigations/`:

```markdown
# Backfill: BDL Box Scores 2024-25 Season

**Date:** 2025-10-14  
**Scope:** 2024-10-01 to 2025-04-30 (212 days)  
**Reason:** New season data not collected

## Results
- Total: 212 dates
- Success: 210 (99.1%)
- Failed: 2

## Failed Dates
- 2024-12-25: No games (Christmas)
- 2025-02-20: API timeout (retried later ✓)

## Lessons Learned
- Need to skip known no-game dates
- API sometimes times out, retry works
```

### 4. Use Progress Indicators

```python
from tqdm import tqdm  # pip install tqdm

for date in tqdm(date_range, desc="Backfilling"):
    scrape_data(date)
```

### 5. Set Realistic Expectations

**Estimated times (for reference):**
- 10 dates: 5-10 minutes
- 100 dates: 1-2 hours
- 365 dates (1 year): 4-8 hours

**Plan accordingly:**
- Short backfill (< 1 hour): Can do anytime
- Medium backfill (1-4 hours): Need to monitor
- Long backfill (> 4 hours): Run overnight or weekend

---

## Backfill Templates

### Template 1: Simple Scraper Backfill

```python
# Copy to: backfill_jobs/raw/{source}/{scraper}_backfill.py
```

### Template 2: Processor Backfill

```python
# Copy to: backfill_jobs/raw/{source}/{processor}_backfill.py
```

### Template 3: Multi-Step Backfill

```python
# For backfills that require scraper → processor → analytics
```

---

## Summary

**Golden Rules:**
1. ✅ **Test first** with 2-3 days
2. ✅ **Enable alert batching** to prevent email floods
3. ✅ **Add rate limiting** to respect API limits
4. ✅ **Make it resumable** for long backfills
5. ✅ **Monitor progress** actively
6. ✅ **Validate results** after completion
7. ✅ **Document issues** for next time

**Red Flags (Stop and Debug):**
- 🚩 Error rate > 20%
- 🚩 Same error on every date
- 🚩 Taking 10x longer than expected
- 🚩 API returning errors about rate limits
- 🚩 Running out of memory

---

## Related Documentation

- [Alert System](./ALERT_SYSTEM.md) - How to prevent email floods
- [Troubleshooting](./TROUBLESHOOTING.md) - Common issues and fixes
- [Monitoring Tools](../monitoring/scripts/README.md) - Progress monitoring

---

**Last Updated:** 2025-10-14
