# NBA.com Player Movement - Data Quality Issues & Resolutions

**Document Version:** 1.0  
**Last Updated:** October 13, 2025  
**Status:** Active Issues Identified  
**Table:** `nba-props-platform.nba_raw.nbac_player_movement`

---

## Executive Summary

Validation testing of the NBA.com Player Movement processor identified **two data quality issues** requiring attention:

1. **18 Duplicate Records (0.4% of data)** - Processor bug during batch insert
2. **22 Orphaned Trades (~2.5% of trades)** - Incomplete source data from NBA.com

Both issues have known root causes, clear resolution paths, and preventative measures documented below.

**Impact Assessment:**
- 🟡 **Medium Priority** - Does not affect player transaction data (player signings/waives work correctly)
- 🟢 **Low User Impact** - Only affects non-player trade assets and trade completeness validation
- 🔴 **High Data Integrity Concern** - Indicates processor and source data quality issues that need addressing

---

## Issue 1: Duplicate Non-Player Trade Records

### Problem Description

**Count:** 18 duplicate records (out of 4,457 total records = 0.4%)  
**Affected Data:** Non-player trade transactions only (`player_id = 0`, `is_player_transaction = FALSE`)  
**Scope:** Draft picks and cash considerations in trades  
**Discovery Date:** October 13, 2025  
**Detection Method:** `data_quality_checks.sql` validation query

### Evidence

All duplicates share these characteristics:
- `player_id = 0` (non-player transactions)
- `transaction_type = 'Trade'`
- Created at identical microsecond timestamps in pairs
- All created during single batch run: `2025-09-02 03:37:13`

**Example:**
```
Trade 2024036 (MIL):
  Record 1: created_at = 2025-09-02 03:37:13.880328+00
  Record 2: created_at = 2025-09-02 03:37:13.880338+00
                        ↑ Only 10 microseconds apart
```

**Query to Verify:**
```sql
SELECT 
  player_id, team_id, transaction_date, transaction_type, group_sort,
  player_full_name, team_abbr,
  COUNT(*) as duplicate_count,
  STRING_AGG(CAST(created_at AS STRING) ORDER BY created_at) as creation_timestamps
FROM `nba-props-platform.nba_raw.nbac_player_movement`
WHERE season_year >= 2021
GROUP BY player_id, team_id, transaction_date, transaction_type, group_sort, player_full_name, team_abbr
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC, transaction_date DESC;
```

### Root Cause Analysis

**Primary Cause: Processor Logic Error**

The duplicates were created during a single batch execution on September 2, 2025. Three possible explanations:

1. **Non-Player Transaction Processing Bug**
   - Processor has separate logic for non-player trade transactions
   - Logic may iterate twice over draft picks/cash considerations
   - INSERT_NEW_ONLY strategy not properly applied to non-player records

2. **Race Condition in Batch Insert**
   - Multiple records processed in parallel
   - Primary key check executed before all records committed
   - Second insert succeeded before first was visible

3. **Duplicate Source Data**
   - NBA.com API returned duplicate entries for non-player assets
   - Processor accepted duplicates without validation
   - Less likely (same microsecond timestamp suggests processor issue)

**Most Likely:** Option 1 - Non-player transaction logic bug

### Resolution Steps

#### Step 1: Backup Current Data

```bash
# Create backup table with timestamp
bq query --use_legacy_sql=false "
CREATE TABLE \`nba-props-platform.nba_raw.nbac_player_movement_backup_$(date +%Y%m%d)\`
AS SELECT * FROM \`nba-props-platform.nba_raw.nbac_player_movement\`
"
```

#### Step 2: Verify Duplicates Before Deletion

```sql
-- Confirm all duplicates are non-player trades
SELECT 
  COUNT(*) as total_duplicate_records,
  COUNT(DISTINCT player_id) as unique_player_ids,
  COUNT(CASE WHEN player_id = 0 THEN 1 END) as non_player_duplicates,
  COUNT(CASE WHEN player_id != 0 THEN 1 END) as player_duplicates
FROM (
  SELECT player_id, team_id, transaction_date, transaction_type, group_sort
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE season_year >= 2021
  GROUP BY player_id, team_id, transaction_date, transaction_type, group_sort
  HAVING COUNT(*) > 1
);

-- Expected: player_duplicates = 0
```

#### Step 3: Delete Duplicate Records

**Strategy:** Keep the earliest `created_at` timestamp, delete later ones.

```sql
-- Delete duplicates (keeps earliest created_at)
DELETE FROM `nba-props-platform.nba_raw.nbac_player_movement`
WHERE (player_id, team_id, transaction_date, transaction_type, group_sort, created_at) IN (
  -- Subquery finds the later created_at for each duplicate
  SELECT player_id, team_id, transaction_date, transaction_type, group_sort, MAX(created_at)
  FROM `nba-props-platform.nba_raw.nbac_player_movement`
  WHERE season_year >= 2021
  GROUP BY player_id, team_id, transaction_date, transaction_type, group_sort
  HAVING COUNT(*) > 1
);
```

**Expected Result:** 18 rows deleted

#### Step 4: Verify Cleanup

```sql
-- Should return 0 rows
SELECT 
  player_id, team_id, transaction_date, transaction_type, group_sort,
  COUNT(*) as duplicate_count
FROM `nba-props-platform.nba_raw.nbac_player_movement`
WHERE season_year >= 2021
GROUP BY player_id, team_id, transaction_date, transaction_type, group_sort
HAVING COUNT(*) > 1;
```

### Prevention Strategy

#### 1. Fix Processor Logic

**File:** `data_processors/raw/nbacom/nbac_player_movement_processor.py`

**Investigation Steps:**
```python
# Look for these patterns in processor code:

# 1. Separate handling of non-player transactions
if not is_player_transaction:
    # Check if this block processes same record twice
    
# 2. Loop over trade parts
for trade_part in trade_data:
    # Verify non-player assets only processed once
    
# 3. INSERT_NEW_ONLY validation
# Confirm primary key check applies to ALL records, including player_id=0
```

**Recommended Fix:**
```python
# Add explicit deduplication before insert
unique_records = []
seen_keys = set()

for record in records_to_insert:
    key = (
        record['player_id'],
        record['team_id'],
        record['transaction_date'],
        record['transaction_type'],
        record['group_sort']
    )
    
    if key not in seen_keys:
        unique_records.append(record)
        seen_keys.add(key)
    else:
        logger.warning(f"Duplicate detected before insert: {key}")

# Insert only unique records
insert_records(unique_records)
```

#### 2. Add Duplicate Detection in Processor

```python
# After batch insert, check for duplicates
def verify_no_duplicates():
    query = """
    SELECT COUNT(*) as duplicate_count
    FROM (
        SELECT player_id, team_id, transaction_date, transaction_type, group_sort
        FROM `nba-props-platform.nba_raw.nbac_player_movement`
        WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
        GROUP BY player_id, team_id, transaction_date, transaction_type, group_sort
        HAVING COUNT(*) > 1
    )
    """
    result = bq_client.query(query).result()
    duplicate_count = list(result)[0].duplicate_count
    
    if duplicate_count > 0:
        raise DataQualityError(f"Inserted {duplicate_count} duplicates!")
    
    return duplicate_count
```

#### 3. Enhanced Testing

```python
# Unit test for duplicate prevention
def test_no_duplicate_non_player_transactions():
    """Ensure non-player trade transactions are not duplicated"""
    sample_data = {
        'transactions': [
            {'player_id': 0, 'team_id': 123, 'date': '2025-01-01', 'type': 'Trade', 'group': 'Trade001'},
            {'player_id': 0, 'team_id': 123, 'date': '2025-01-01', 'type': 'Trade', 'group': 'Trade001'},  # Duplicate
        ]
    }
    
    processed = processor.process_transactions(sample_data)
    
    # Should deduplicate before insert
    assert len(processed) == 1, "Duplicate non-player transaction not deduplicated"
```

#### 4. Add Processor Run Tracking

See **Document 2** for full processor_runs table architecture.

---

## Issue 2: Orphaned Trade Transactions

### Problem Description

**Count:** 22 orphaned trades (out of ~450 trades = ~4.9%)  
**Affected Data:** Multi-part trade transactions with only one team recorded  
**Scope:** Trades from 2022-2025 (most are recent)  
**Discovery Date:** October 13, 2025  
**Detection Method:** `trade_validation.sql` validation query

### Evidence

Valid trades should have 2+ teams involved. Orphaned trades have only 1 team:

**Example - Trade 2025016 (August 6, 2025):**
```
✅ UTA received Georges Niang from BOS
✅ UTA received draft consideration from BOS
❌ BOS side missing (what did BOS send/receive?)
```

**Query to Identify:**
```sql
SELECT 
  group_sort,
  transaction_date,
  STRING_AGG(DISTINCT team_abbr) as teams,
  COUNT(DISTINCT team_id) as team_count,
  STRING_AGG(player_full_name ORDER BY player_full_name) as players
FROM `nba-props-platform.nba_raw.nbac_player_movement`
WHERE transaction_type = 'Trade'
  AND season_year >= 2021
GROUP BY group_sort, transaction_date
HAVING COUNT(DISTINCT team_id) = 1
ORDER BY transaction_date DESC;
```

### Root Cause Analysis

**Primary Cause: Incomplete Source Data from NBA.com**

The orphaned trades indicate NBA.com's Player Movement API returned partial trade data. Four possible explanations:

1. **Mid-Update Capture**
   - Trade announced/entered into NBA.com system
   - Scraper ran during update window
   - Second team's transactions not yet posted
   - Most likely for recent trades

2. **Future Considerations Trade**
   - Trade completed but includes "future considerations"
   - Other team's obligation disclosed later
   - Legitimate one-sided entry until consideration announced

3. **Voided/Cancelled Trade**
   - Trade announced but later voided
   - Only receiving team logged before cancellation
   - Never updated to remove orphaned entry

4. **NBA.com API Data Quality Issue**
   - Source data genuinely incomplete
   - Bug in NBA.com's transaction logging
   - Missing cross-references between trade parts

**Most Likely:** Options 1 & 2 - Mid-update captures and future considerations

### Resolution Steps

#### Step 1: Export Complete List

```bash
# Export all orphaned trades for investigation
bq query --use_legacy_sql=false --format=csv "
SELECT 
  t.group_sort,
  t.transaction_date,
  t.season_year,
  STRING_AGG(DISTINCT t.team_abbr) as receiving_team,
  COUNT(*) as transaction_parts,
  COUNT(CASE WHEN t.is_player_transaction = TRUE THEN 1 END) as players,
  COUNT(CASE WHEN t.is_player_transaction = FALSE THEN 1 END) as picks_cash,
  STRING_AGG(t.player_full_name, ', ' ORDER BY t.player_full_name) as player_names,
  STRING_AGG(DISTINCT t.transaction_description, ' | ') as descriptions
FROM \`nba-props-platform.nba_raw.nbac_player_movement\` t
WHERE t.transaction_type = 'Trade'
  AND t.group_sort IN (
    SELECT group_sort
    FROM \`nba-props-platform.nba_raw.nbac_player_movement\`
    WHERE transaction_type = 'Trade' AND season_year >= 2021
    GROUP BY group_sort
    HAVING COUNT(DISTINCT team_id) = 1
  )
GROUP BY t.group_sort, t.transaction_date, t.season_year
ORDER BY t.transaction_date DESC
" > docs/data_quality/orphaned_trades_$(date +%Y%m%d).csv

echo "✓ Exported to: docs/data_quality/orphaned_trades_$(date +%Y%m%d).csv"
```

#### Step 2: Manual Investigation

For each orphaned trade, verify against official sources:

**Sources to Check:**
1. **NBA.com Official Transactions Page**
   - https://www.nba.com/stats/transactions
   - Search by date and team
   - Look for complete trade details

2. **ESPN Transaction Log**
   - https://www.espn.com/nba/transactions
   - Cross-reference same trade
   - May have complete information

3. **Team Press Releases**
   - Official team websites
   - Twitter announcements
   - Often have full trade details

**Investigation Template:**
```
Trade ID: [group_sort]
Date: [transaction_date]
Team Recorded: [team_abbr]
Players: [player_names]

NBA.com Status: [Complete / Partial / Voided]
ESPN.com Status: [Complete / Partial / Not Found]
Resolution: [Backfill / Future Consideration / Void / Unknown]

Other Team: [team_abbr]
Missing Players: [names]
Missing Assets: [picks/cash]
```

#### Step 3: Backfill Missing Data (if found)

**Option A: Manual SQL Insert** (for small number of corrections)
```sql
-- Example: Add missing BOS side of Trade 2025016
INSERT INTO `nba-props-platform.nba_raw.nbac_player_movement` (
  player_id, player_full_name, player_lookup,
  team_id, team_abbr,
  transaction_date, transaction_type,
  season_year, group_sort,
  is_player_transaction,
  transaction_description,
  scrape_timestamp, created_at, updated_at
)
VALUES (
  1234567, 'Example Player', 'example_player',
  1610612738, 'BOS',
  '2025-08-06', 'Trade',
  2024, 'Trade 2025016',
  TRUE,
  'Boston Celtics traded forward Georges Niang to Utah Jazz.',
  CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()
);
```

**Option B: Re-run Scraper** (if NBA.com fixed data)
```bash
# Trigger scraper for specific date
curl -X POST https://[your-scraper-endpoint]/nbacom/player-movement \
  -H "Content-Type: application/json" \
  -d '{"force_refresh": true}'

# Then re-run processor
python data_processors/raw/nbacom/nbac_player_movement_processor.py --backfill
```

#### Step 4: Document Status

Create tracking document: `docs/data_quality/orphaned_trades_status.md`

```markdown
# Orphaned Trades - Investigation Status

| Trade ID | Date | Team | Status | Resolution | Notes |
|----------|------|------|--------|------------|-------|
| Trade 2025016 | 2025-08-06 | UTA | 🔍 Investigating | Pending | Missing BOS side |
| Trade 2024037 | 2025-02-06 | HOU | ✅ Resolved | Future Consideration | Legitimate one-sided |
| Trade 2024030 | 2025-02-06 | DET | ❌ Voided | No Action Needed | Trade cancelled |
```

### Prevention Strategy

#### 1. Add Trade Completeness Check to Processor

```python
def validate_trade_completeness(trades_to_insert):
    """Validate all trades have 2+ teams before inserting"""
    from collections import defaultdict
    
    trade_teams = defaultdict(set)
    
    for record in trades_to_insert:
        if record['transaction_type'] == 'Trade':
            trade_teams[record['group_sort']].add(record['team_id'])
    
    orphaned = [
        trade_id for trade_id, teams in trade_teams.items()
        if len(teams) == 1
    ]
    
    if orphaned:
        logger.warning(f"Found {len(orphaned)} potentially orphaned trades: {orphaned}")
        # Don't fail - log for investigation
        # May be legitimate future considerations
    
    return len(orphaned)
```

#### 2. Cross-Validate with ESPN.com

Add secondary source validation:

```python
def cross_validate_trades(nba_trades, espn_trades):
    """Compare NBA.com trades with ESPN.com for completeness"""
    
    for trade in nba_trades:
        # Find matching ESPN trade
        espn_match = find_matching_trade(trade, espn_trades)
        
        if espn_match:
            # Compare team counts
            nba_teams = trade.team_count
            espn_teams = espn_match.team_count
            
            if nba_teams < espn_teams:
                logger.warning(
                    f"Trade {trade.group_sort}: NBA.com has {nba_teams} teams, "
                    f"ESPN has {espn_teams} teams"
                )
```

#### 3. Delayed Processing for Recent Trades

```python
def should_process_trade(trade_date):
    """Wait 24 hours before processing recent trades to avoid mid-update captures"""
    hours_since_trade = (datetime.now() - trade_date).total_seconds() / 3600
    
    if hours_since_trade < 24:
        logger.info(f"Trade from {trade_date} is <24h old, will process tomorrow")
        return False
    
    return True
```

#### 4. Automated Re-Validation

```bash
# Run weekly to check if NBA.com fixed orphaned trades
# Add to cron: 0 3 * * 0  (Every Sunday at 3am)

#!/bin/bash
# File: scripts/recheck-orphaned-trades

echo "Checking NBA.com for updates to orphaned trades..."

# Re-scrape player movement data
curl -X POST https://[scraper-endpoint]/nbacom/player-movement

# Re-run processor (will INSERT_NEW_ONLY, adding missing parts)
python data_processors/raw/nbacom/nbac_player_movement_processor.py

# Check if orphaned count decreased
CURRENT_COUNT=$(bq query --use_legacy_sql=false --format=csv "
  SELECT COUNT(DISTINCT group_sort)
  FROM (
    SELECT group_sort
    FROM \`nba-props-platform.nba_raw.nbac_player_movement\`
    WHERE transaction_type = 'Trade' AND season_year >= 2021
    GROUP BY group_sort
    HAVING COUNT(DISTINCT team_id) = 1
  )
" | tail -1)

echo "Current orphaned trades: $CURRENT_COUNT"

if [ "$CURRENT_COUNT" -lt 22 ]; then
    echo "✓ Some orphaned trades resolved!"
fi
```

---

## Monitoring & Alerts

### Daily Health Check

Run these validation queries daily during the season:

```bash
# Check for new duplicates
./scripts/validate-player-movement quality

# Check for new orphaned trades  
./scripts/validate-player-movement trades

# Alert thresholds:
# - Duplicates > 18: 🔴 NEW duplicates created
# - Orphaned trades > 25: 🟡 More orphaned trades than baseline
```

### Automated Alerts

**BigQuery Scheduled Query** (runs daily at 9am):

```sql
-- File: scheduled_queries/player_movement_quality_alert.sql
-- Schedule: Daily at 09:00
-- Destination: Slack/Email via Pub/Sub

WITH quality_checks AS (
  -- Check 1: Count duplicates
  SELECT 
    'duplicates' as check_type,
    COUNT(*) as issue_count
  FROM (
    SELECT player_id, team_id, transaction_date, transaction_type, group_sort
    FROM `nba-props-platform.nba_raw.nbac_player_movement`
    WHERE season_year >= 2021
    GROUP BY player_id, team_id, transaction_date, transaction_type, group_sort
    HAVING COUNT(*) > 1
  )
  
  UNION ALL
  
  -- Check 2: Count orphaned trades
  SELECT
    'orphaned_trades' as check_type,
    COUNT(*) as issue_count
  FROM (
    SELECT group_sort
    FROM `nba-props-platform.nba_raw.nbac_player_movement`
    WHERE transaction_type = 'Trade' AND season_year >= 2021
    GROUP BY group_sort
    HAVING COUNT(DISTINCT team_id) = 1
  )
)

SELECT
  check_type,
  issue_count,
  CASE
    WHEN check_type = 'duplicates' AND issue_count > 18 THEN 'ALERT'
    WHEN check_type = 'orphaned_trades' AND issue_count > 25 THEN 'WARNING'
    ELSE 'OK'
  END as status
FROM quality_checks
WHERE issue_count > 0;
```

---

## Success Criteria

### Issue 1 Resolution: Duplicates

- ✅ All 18 current duplicates removed
- ✅ Processor code fixed to prevent future duplicates
- ✅ Unit tests added for non-player transaction deduplication
- ✅ Daily monitoring shows 0 new duplicates for 30 days

### Issue 2 Resolution: Orphaned Trades

- ✅ All 22 orphaned trades documented in tracking spreadsheet
- ✅ Investigation completed for each trade
- ⚪ Backfill applied where possible (expected: 30-50% recoverable)
- ✅ ESPN.com cross-validation implemented
- ✅ Delayed processing for recent trades (<24h)
- ✅ Weekly re-check automation in place

---

## Summary

Both data quality issues are well-understood and have clear resolution paths:

1. **Duplicates (18 records):** Processor bug, easily fixed with code update and cleanup query
2. **Orphaned Trades (22 trades):** Source data issue, requires manual investigation and backfill

**Timeline:**
- Deduplication: 1 hour (backup + delete + verify)
- Processor fix: 2-4 hours (code + tests)
- Trade investigation: 1-2 weeks (manual research)
- Backfill: Varies by findings

**Priority:** Medium - Neither issue affects core player transaction data (signings/waives), but both indicate data quality concerns that should be addressed.

---

**Document Owner:** Data Engineering Team  
**Next Review:** After deduplication + processor fix completion  
**Related Docs:** 
- `validation/queries/raw/nbac_player_movement/README.md`
- `docs/PROCESSOR_MONITORING_IDEAS.md`
- Player Movement Daily Operations Guide (Document 2)
