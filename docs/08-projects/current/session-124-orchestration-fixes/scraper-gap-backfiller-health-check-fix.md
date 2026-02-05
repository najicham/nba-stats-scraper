# Scraper Gap Backfiller - Health Check Fix

**Session:** 126
**Date:** 2026-02-04
**Status:** Code fixed, ready for deployment

## Problem Summary

The scraper gap backfiller had a critical bug that prevented backfilling of recent gaps for post-game scrapers.

### The Bug

**Original Logic (lines 486-497):**
```python
if oldest_gap == today:
    action["health_check"] = "skipped_same_day"
else:
    if not test_scraper_health(scraper_name, today):
        action["health_check"] = "failed"
        action["backfill"] = "skipped"
        continue
    action["health_check"] = "passed"
```

**Why It Failed:**

1. **Health check tests with TODAY's date** - When backfiller runs at midnight, it tests scrapers with today's date
2. **Post-game scrapers need completed games** - Gamebook PDFs and player boxscores aren't available until games finish
3. **Yesterday's gaps get skipped** - At midnight on Feb 5:
   - Finds Feb 4 gap for `nbac_gamebook_pdf`
   - Gap date (Feb 4) ≠ today (Feb 5), so runs health check
   - Health check tries to scrape Feb 5 games (haven't happened yet)
   - Health check fails → backfill skipped
   - Feb 4 never gets data

### Example Failure Scenario

```
Time: Feb 5 at 00:00 UTC (midnight)
Gap: nbac_gamebook_pdf for 2026-02-04

Old Logic:
  1. oldest_gap = "2026-02-04"
  2. today = "2026-02-05"
  3. oldest_gap != today, so run health check
  4. test_scraper_health("nbac_gamebook_pdf", "2026-02-05")
  5. Scraper tries to get Feb 5 gamebook PDFs → FAIL (games haven't started)
  6. Health check failed → skip backfill
  7. Feb 4 data never scraped
```

## The Fix

### Implementation

**Two-tiered health check skip logic:**

1. **Skip recent gaps (≤ 1 day old)** - Gaps from today or yesterday
2. **Skip post-game scrapers** - Always skip health check for scrapers that need completed games

**New Logic (lines 490-527):**

```python
# Calculate gap age
gap_age_days = (datetime.now(timezone.utc).date() - failure["oldest_gap_date"]).days

if gap_age_days <= 1:
    # Recent gap - skip health check (may be timing issue)
    action["health_check"] = "skipped_recent_gap"
    logger.info(f"Skipping health check for {scraper_name} - gap is only {gap_age_days} day(s) old")

elif scraper_name in POST_GAME_SCRAPERS:
    # Post-game scraper - can't test with today's date
    action["health_check"] = "skipped_post_game_scraper"
    logger.info(f"Skipping health check for {scraper_name} - post-game scraper")

else:
    # Normal health check for older gaps
    if not test_scraper_health(scraper_name, today):
        action["health_check"] = "failed"
        action["backfill"] = "skipped"
        continue
    action["health_check"] = "passed"
```

**Configuration (lines 65-67):**
```python
# Post-game scrapers: Data only available AFTER games complete
POST_GAME_SCRAPERS = {'nbac_gamebook_pdf', 'nbac_player_boxscore'}
```

### Logic Flow

```
For each scraper gap:

  Calculate: gap_age_days = today - gap_date

  Decision Tree:
    ├─ gap_age_days <= 1?
    │  └─ YES → Skip health check (skipped_recent_gap)
    │           Reason: May be timing issue, not scraper failure
    │           Go straight to backfill
    │
    ├─ scraper in POST_GAME_SCRAPERS?
    │  └─ YES → Skip health check (skipped_post_game_scraper)
    │           Reason: Can't test with today's date (games not complete)
    │           Go straight to backfill
    │
    └─ ELSE → Run health check
               Test scraper with today's date
               If pass → backfill
               If fail → skip backfill
```

## Test Results

Created test script: `test_gap_backfiller_logic.py`

**Test Scenario: Midnight run on Feb 5, 2026**

| # | Scraper | Gap Date | Age | Decision | Reason |
|---|---------|----------|-----|----------|--------|
| 1 | nbac_gamebook_pdf | 2026-02-04 | 1 day | skip | skipped_recent_gap |
| 2 | nbac_gamebook_pdf | 2026-02-05 | 0 days | skip | skipped_recent_gap |
| 3 | nbac_gamebook_pdf | 2026-02-02 | 3 days | skip | skipped_post_game_scraper |
| 4 | nbac_schedule | 2026-02-04 | 1 day | skip | skipped_recent_gap |
| 5 | nbac_schedule | 2026-02-02 | 3 days | **run** | normal_health_check |
| 6 | nbac_player_boxscore | 2026-02-04 | 1 day | skip | skipped_recent_gap |
| 7 | nbac_team_data | 2026-02-05 | 0 days | skip | skipped_recent_gap |

All tests pass ✓

## Impact

### Before Fix
- Yesterday's gaps for post-game scrapers were never backfilled
- Data loss for `nbac_gamebook_pdf` and `nbac_player_boxscore`
- Manual intervention required

### After Fix
- Recent gaps (≤1 day) always attempt backfill
- Post-game scrapers skip health check (correct behavior)
- Automatic recovery for yesterday's post-game scraper gaps

## Logging Improvements

Added detailed logging to explain health check decisions:

```python
# Recent gap skip
logger.info(
    f"Skipping health check for {scraper_name} - gap is only {gap_age_days} day(s) old "
    f"(gap_date={oldest_gap}, today={today})"
)

# Post-game scraper skip
logger.info(
    f"Skipping health check for {scraper_name} - post-game scraper cannot be tested "
    f"with today's date (today={today})"
)

# Normal health check
logger.info(f"Running health check for {scraper_name} with date={today}")

# Health check failed
logger.warning(
    f"Health check failed for {scraper_name} - skipping backfill for {oldest_gap}"
)

# Health check passed
logger.info(f"Health check passed for {scraper_name}")
```

## Files Changed

1. **orchestration/cloud_functions/scraper_gap_backfiller/main.py**
   - Lines 65-67: Added `POST_GAME_SCRAPERS` configuration
   - Lines 490-527: Replaced simple same-day check with two-tiered logic

2. **test_gap_backfiller_logic.py** (new)
   - Test script to verify decision logic
   - 7 test cases covering all scenarios

## Next Steps

1. **Deploy the fix:**
   ```bash
   gcloud functions deploy scraper-gap-backfiller \
       --region=us-west2 \
       --source=orchestration/cloud_functions/scraper_gap_backfiller
   ```

2. **Monitor logs** for health check skip messages:
   ```bash
   gcloud logging read "resource.type=cloud_function \
       AND resource.labels.function_name=scraper-gap-backfiller \
       AND textPayload=~'Skipping health check'" \
       --limit 50 --format json
   ```

3. **Verify Feb 4 backfills** after next midnight run (Feb 5):
   ```sql
   SELECT scraper_name, game_date, backfilled, backfilled_at
   FROM nba_orchestration.scraper_failures
   WHERE game_date = '2026-02-04'
     AND scraper_name IN ('nbac_gamebook_pdf', 'nbac_player_boxscore')
   ORDER BY backfilled_at DESC
   ```

## Related Issues

- **Session 125**: Increased LOOKBACK_DAYS from 7 to 14 to catch longer gaps
- This fix ensures those longer gaps can actually be backfilled

## Design Rationale

### Why Skip Recent Gaps (≤1 day)?

**Timing vs. Failure:**
- At midnight, "yesterday's" data may still be processing
- A failed health check for yesterday doesn't mean the scraper is broken
- It might just mean we're running too early
- Better to attempt the backfill and let it succeed/fail on its own

**Example:**
- Midnight Feb 5: Feb 4 games just finished processing
- Health check for Feb 5 would fail (no games yet)
- But backfill for Feb 4 should succeed (data is ready)

### Why Skip Post-Game Scrapers Always?

**Data Availability:**
- Gamebook PDFs aren't available until games complete
- Health check with today's date will always fail
- No point testing - we know it will fail
- Better to skip and go straight to backfill

**Alternative Approaches Considered:**

1. ❌ **Test with yesterday's date** - Complex, requires special test logic
2. ❌ **No health check at all** - Would attempt backfills on broken scrapers
3. ✅ **Skip for recent + post-game** - Simple, handles timing and data availability

## Conclusion

This fix solves the Feb 4 backfill problem by recognizing that:
1. Recent gaps are likely timing issues, not scraper failures
2. Post-game scrapers can't be health-checked with future dates
3. Better to attempt backfill and fail than skip it entirely

The logic is now robust for all scraper types and gap ages.
