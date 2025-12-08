# Data Availability Logic - Understanding Missing Data

**Created:** 2025-11-30
**Purpose:** Distinguish between "never ran" vs "ran but no data" vs "needs fallback"
**Applies to:** All phases (Phase 2 Scrapers, Phase 3 Analytics, Phase 4 Precompute)

---

## The Core Question

When validation shows **"missing data"**, we need to know:
1. **Did the processor never run?** → Need to run it
2. **Did it run but fail?** → Need to investigate/retry
3. **Did it run successfully but find no data?** → Use fallback or accept gap
4. **Did it run and produce partial data?** → May need rerun or accept

---

## The Decision Tree

```
Missing Data Detected
    ↓
Check processor_run_history
    ↓
    ├─→ No record found
    │   Status: NEVER RAN
    │   Action: RUN the processor/scraper
    │
    ├─→ Record found, status = 'failed'
    │   Status: RAN BUT FAILED
    │   Action: Investigate logs, fix issue, RETRY
    │
    ├─→ Record found, status = 'success', 0 rows in table
    │   Status: RAN, NO DATA AVAILABLE
    │   Action: Use fallback OR accept gap
    │
    └─→ Record found, status = 'success', some rows in table
        Status: RAN, PARTIAL DATA
        Action: Determine if acceptable or need rerun
```

---

## Phase-by-Phase Application

### Phase 2: Scrapers (Raw Data)

**Example: nbac_team_boxscore missing for Oct 15, 2021**

#### Step 1: Check Data
```sql
SELECT COUNT(*) FROM nba_raw.nbac_team_boxscore
WHERE game_date = '2021-10-15'
-- Result: 0 rows
```

#### Step 2: Check Run History
```sql
SELECT status FROM processor_run_history
WHERE processor_name = 'nbac_team_boxscore'
  AND data_date = '2021-10-15'
```

#### Possible Outcomes:

| Run History | Meaning | Action |
|-------------|---------|--------|
| No record | Scraper never ran | **Run scraper backfill** |
| status='failed' | Scraper ran but failed | Investigate error, retry |
| status='success', 0 rows | Scraper ran, NBA.com had no data | Accept gap OR try alternative source |
| status='success', partial rows | Scraper ran, got some data | Determine if acceptable |

**Key Insight:** For scrapers, "never ran" is the most common case for historical dates that weren't backfilled.

---

### Phase 3: Analytics

**Example: player_game_summary missing for Oct 15, 2021**

#### Step 1: Check Data
```sql
SELECT COUNT(*) FROM nba_analytics.player_game_summary
WHERE game_date = '2021-10-15'
-- Result: 0 rows
```

#### Step 2: Check Run History
```sql
SELECT status, errors FROM processor_run_history
WHERE processor_name = 'PlayerGameSummaryProcessor'
  AND data_date = '2021-10-15'
```

#### Possible Outcomes:

| Run History | Meaning | Action |
|-------------|---------|--------|
| No record | Analytics never ran | **Run Phase 3 backfill** |
| status='failed' | Ran but failed (missing deps?) | Check Phase 2 complete, retry |
| status='success', 0 rows | Ran but produced nothing | Investigate why (missing Phase 2 data?) |
| status='success', partial rows | Ran with fallbacks | May be acceptable with fallbacks |

**Key Insight:** Analytics failures usually mean Phase 2 dependencies missing. Check Phase 2 first!

---

### Phase 4: Precompute

**Example: player_composite_factors missing for Oct 22, 2021**

#### Step 1: Check if Bootstrap
```python
if is_bootstrap_date('2021-10-22'):  # False (day 8)
    # Not bootstrap, should have data
```

#### Step 2: Check Data
```sql
SELECT COUNT(*) FROM nba_precompute.player_composite_factors
WHERE game_date = '2021-10-22'
-- Result: 0 rows
```

#### Step 3: Check Run History
```sql
SELECT status FROM processor_run_history
WHERE processor_name = 'PlayerCompositeFactorsProcessor'
  AND data_date = '2021-10-22'
```

#### Possible Outcomes:

| Run History | Meaning | Action |
|-------------|---------|--------|
| No record | Precompute never ran | **Run Phase 4 backfill** |
| status='failed' | Ran but failed (deps?) | Check Phase 3 complete, check dependencies |
| status='success', 0 rows | Ran but no output | Investigate (quality threshold? missing Phase 3?) |
| status='success', partial rows | Ran with some data | May be acceptable |

**Key Insight:** Phase 4 has strict dependencies. Always verify Phase 3 complete first!

---

## Validation Tool Integration

The enhanced `validate_and_plan.py` now checks run history automatically:

### Old Output (Before Enhancement):
```
  ✗ nbac_team_boxscore    0/1 (0.0%) [CRITICAL]
```
**Problem:** Doesn't tell you WHY it's missing!

### New Output (After Enhancement):
```
  ○ nbac_team_boxscore    0/1 (0.0%) [CRITICAL] (NEVER RAN)

  → Phase 2: ⚠ Missing critical data
     • 4 scrapers NEVER RAN - need to run scraper backfill
       - nbac_team_boxscore
```
**Better:** Clear action - run the scraper!

### Other Possible Statuses:
```
  ✗ some_processor   0/1 (0.0%) (ran but FAILED)
  ○ some_processor   0/1 (0.0%) (ran, no data found)
  ⚠ some_processor   5/10 (50%) (ran, partial data)
```

---

## Practical Implications

### Scenario 1: First 14 Days of 2021-22 Season

**Validation shows:**
- Phase 2: 71-79% coverage
- Run history: No records for missing dates

**Conclusion:** Scrapers never ran (not a data availability issue)
**Action:** Run scraper backfills for missing dates
**Expected Result:** ~95-100% coverage after scraping

---

### Scenario 2: Early Season Date with Complete Runs

**Validation shows:**
- Phase 2: 71-79% coverage
- Run history: All scrapers ran successfully

**Conclusion:** Some sources genuinely didn't have data
**Action:** Use fallbacks (bdl_player_boxscores, etc.)
**Expected Result:** 90-95% coverage with fallbacks

---

### Scenario 3: Analytics Showing Zeros

**Validation shows:**
- Phase 3: 0% for all tables
- Run history: PlayerGameSummaryProcessor ran and failed

**Conclusion:** Phase 3 attempted but failed (likely Phase 2 incomplete)
**Action:** Complete Phase 2 first, then retry Phase 3
**Expected Result:** Phase 3 succeeds after Phase 2 complete

---

## Implementation in Validation Tool

### Code Logic:
```python
# Check if data exists
has_data = (row_count > 0)

# Check run history
run_status = get_run_status(run_history, date, phase, processor_name)

# Determine action
if not has_data and run_status is None:
    action = "NEVER RAN - need to run backfill"
elif not has_data and run_status == 'failed':
    action = "RAN BUT FAILED - investigate and retry"
elif not has_data and run_status == 'success':
    action = "RAN BUT NO DATA - use fallback or accept gap"
elif has_data and run_status == 'success':
    action = "SUCCESS - data exists"
```

---

## When to Use Fallbacks vs Retry

### Use Fallbacks When:
- ✓ Processor ran successfully (`status='success'`)
- ✓ No data in output table
- ✓ Retry would likely have same result
- ✓ Fallback source exists (e.g., bdl_player_boxscores)

**Example:** BettingPros had no props for a specific date → Use Odds API fallback

### Run/Retry When:
- ✓ Processor never ran (`run_history` has no record)
- ✓ Processor failed (`status='failed'`)
- ✓ Dependencies are now available (Phase 2 was completed)
- ✓ Bug was fixed that caused failure

**Example:** Team boxscore scraper never ran → Run it now

---

## Monitoring Run History

### Check Run History for Date:
```sql
SELECT
  processor_name,
  phase,
  status,
  started_at,
  duration_seconds,
  TO_JSON_STRING(errors) as errors
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date = '2021-10-15'
ORDER BY phase, processor_name
```

### Find All Failed Runs:
```sql
SELECT
  processor_name,
  data_date,
  TO_JSON_STRING(errors) as error_msg
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'failed'
  AND data_date >= '2021-10-15'
ORDER BY data_date, processor_name
```

### Find Dates Never Processed:
```sql
WITH expected_dates AS (
  SELECT date
  FROM UNNEST(GENERATE_DATE_ARRAY('2021-10-15', '2021-10-28')) AS date
)
SELECT
  date,
  'PlayerGameSummaryProcessor' as processor
FROM expected_dates
WHERE date NOT IN (
  SELECT data_date
  FROM processor_run_history
  WHERE processor_name = 'PlayerGameSummaryProcessor'
)
ORDER BY date
```

---

## Key Takeaways

1. **Always check run history** before deciding on fallback vs retry
2. **"NEVER RAN" means run it** - don't assume data unavailable
3. **"RAN BUT FAILED" means investigate** - check logs and dependencies
4. **"RAN BUT NO DATA" means fallback** - source genuinely didn't have it
5. **Validation tool now shows this automatically** - trust its guidance

---

## See Also

- [VALIDATION-TOOL-GUIDE.md](./VALIDATION-TOOL-GUIDE.md) - Tool usage
- [FALLBACK-ANALYSIS.md](./FALLBACK-ANALYSIS.md) - Fallback strategies
- [BACKFILL-EXECUTION-AND-TROUBLESHOOTING.md](./BACKFILL-EXECUTION-AND-TROUBLESHOOTING.md) - Error handling
