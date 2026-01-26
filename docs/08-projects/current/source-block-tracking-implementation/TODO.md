# Source-Block Tracking Implementation TODO

**Date:** 2026-01-26
**Status:** 🟡 In Progress
**Estimated Time:** 4-5 hours total

---

## Overview

Implement the approved resource-level source block tracking system to distinguish between infrastructure failures and source-unavailable data.

**Goal:** Validation shows 100% of available data collected, not false failures for source-blocked resources.

---

## Task Breakdown

### Phase 1: Foundation (60 min)

#### Task #14: Fix validation script game_id mismatch bug ⏱️ 30 min
**Status:** Created
**Priority:** P2 (blocking correct validation)

**Problem:**
- Schedule table: `0022500661` (NBA official format)
- Player context table: `20260126_MEM_HOU` (date format)
- JOIN fails, shows 0 players even when data exists

**Fix:**
- Option A: Use game_date to match instead of game_id
- Option B: Add game_id conversion function
- Option C: Use mapping table if exists

**Steps:**
1. Read check_game_context() function
2. Identify correct JOIN approach
3. Test with 2026-01-26 data (should show 239 players)
4. Commit fix

---

#### Task #15: Create source_blocked_resources table ⏱️ 15 min
**Status:** Created
**Dependencies:** None

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS nba_orchestration.source_blocked_resources (
  -- Resource Identification
  resource_id STRING NOT NULL,
  resource_type STRING NOT NULL,
  game_date DATE,

  -- Source Information
  source_system STRING NOT NULL,
  source_url STRING,

  -- Block Status
  http_status_code INT64,
  block_type STRING NOT NULL,

  -- Verification Tracking
  first_detected_at TIMESTAMP NOT NULL,
  last_verified_at TIMESTAMP NOT NULL,
  verification_count INT64 DEFAULT 1,

  -- Alternative Source
  available_from_alt_source BOOL,
  alt_source_system STRING,
  alt_source_verified_at TIMESTAMP,

  -- Metadata
  notes STRING,
  created_by STRING,

  -- Resolution
  is_resolved BOOL DEFAULT FALSE,
  resolved_at TIMESTAMP,
  resolution_notes STRING
)
PARTITION BY game_date
CLUSTER BY resource_type, source_system, block_type;
```

**Steps:**
1. Create SQL file with schema
2. Run bq query to create table
3. Verify table created with correct schema
4. Document table in schema docs

---

#### Task #16: Create source_block_tracker.py module ⏱️ 45 min
**Status:** Created
**Dependencies:** Task #15 complete

**Functions:**
1. `record_source_block()` - MERGE to insert/update
2. `get_source_blocked_resources()` - Query with filters
3. `classify_block_type()` - HTTP status → block type
4. `mark_block_resolved()` - Update resolution status

**Steps:**
1. Create shared/utils/source_block_tracker.py
2. Implement record_source_block() with MERGE query
3. Implement get_source_blocked_resources() with filters
4. Implement helper functions
5. Add error handling and logging
6. Write docstrings
7. Test with manual calls

---

### Phase 2: Integration (90 min)

#### Task #17: Insert 2026-01-25 blocked games ⏱️ 10 min
**Status:** Created
**Dependencies:** Task #15, #16 complete

**Data:**
```python
# Game 1
resource_id='0022500651'
resource_type='play_by_play'
game_date='2026-01-25'
source_system='nba_com_cdn'
http_status_code=403
notes='DEN @ MEM - Blocked by NBA.com CDN, also unavailable from BDB'

# Game 2
resource_id='0022500652'
resource_type='play_by_play'
game_date='2026-01-25'
source_system='nba_com_cdn'
http_status_code=403
notes='DAL @ MIL - Blocked by NBA.com CDN, also unavailable from BDB'
```

**Steps:**
1. Create script to insert historical blocks
2. Run for 2026-01-25 games
3. Query to verify insertion
4. Check verification_count = 1

---

#### Task #18: Update validation script ⏱️ 30 min
**Status:** Created
**Dependencies:** Task #16, #17 complete

**Changes:**
1. Import get_source_blocked_resources()
2. Modify check_game_context():
   - Query blocked games for date
   - Subtract from expected count
   - Show blocked games separately
3. Modify check_predictions():
   - Query blocked games
   - Adjust expected count
4. Update summary output

**Example:**
```python
def check_game_context(self):
    expected_games = get_games_for_date(self.target_date)
    blocked_games = get_source_blocked_resources(
        game_date=self.target_date,
        resource_type='play_by_play'
    )
    expected_available = len(expected_games) - len(blocked_games)
    actual_games = get_actual_games(self.target_date)

    # Check if actual >= expected_available
    if actual_games >= expected_available:
        print(f"✓ Game Context: {actual_games}/{expected_available} available games")
        if blocked_games:
            print(f"  ℹ️  {len(blocked_games)} games source-blocked (not counted as failures)")
    else:
        self.add_issue('game_context', f'Missing {expected_available - actual_games} games')
```

---

#### Task #19: Integrate with PBP scraper ⏱️ 30 min
**Status:** Created
**Dependencies:** Task #16 complete

**Changes to scrapers/nbacom/nbac_play_by_play.py:**
```python
from shared.utils.source_block_tracker import record_source_block

def handle_http_error(self, response, url):
    # Existing proxy health logging
    log_proxy_result(...)

    # NEW: Resource-level tracking
    if response.status_code in [403, 404, 410]:
        game_id = self.extract_game_id(url)
        if game_id:
            record_source_block(
                resource_id=game_id,
                resource_type='play_by_play',
                source_system='nba_com_cdn',
                source_url=url,
                http_status_code=response.status_code,
                game_date=self.opts.get('game_date')
            )
```

**Steps:**
1. Read nba.com PBP scraper
2. Find error handling code
3. Add source_block_tracker import
4. Add record_source_block() call
5. Test with known blocked game

---

### Phase 3: Testing & Documentation (80 min)

#### Task #20: Test end-to-end ⏱️ 20 min
**Status:** Created
**Dependencies:** All previous tasks complete

**Test Scenarios:**
1. Query blocked resources → Should show 2 games for 2026-01-25
2. Run validation for 2026-01-25 → Should show 100% of available (6/6 not 6/8)
3. Simulate scraper 403 → Should auto-record block
4. Re-run validation → Should account for new block

**Steps:**
1. Query source_blocked_resources for 2026-01-25
2. Run validate_tonight_data.py --date 2026-01-25
3. Verify output shows 100% completion
4. Test scraper integration (if possible)
5. Document test results

---

#### Task #21: Create monitoring queries ⏱️ 30 min
**Status:** Created
**Dependencies:** Task #15 complete

**Queries to Create:**

1. **Active Source Blocks by Date**
```sql
SELECT
  game_date,
  resource_type,
  COUNT(*) as blocked_count,
  STRING_AGG(resource_id, ', ') as blocked_resources
FROM nba_orchestration.source_blocked_resources
WHERE is_resolved = FALSE
  AND game_date >= CURRENT_DATE() - 7
GROUP BY game_date, resource_type
ORDER BY game_date DESC;
```

2. **Coverage % Including Blocks**
```sql
WITH expected AS (
  SELECT game_date, COUNT(*) as total_games
  FROM schedule
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY game_date
),
blocked AS (
  SELECT game_date, COUNT(*) as blocked_count
  FROM nba_orchestration.source_blocked_resources
  WHERE resource_type = 'play_by_play'
    AND is_resolved = FALSE
  GROUP BY game_date
),
actual AS (
  SELECT game_date, COUNT(DISTINCT game_id) as actual_count
  FROM nba_raw.bigdataball_play_by_play
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY game_date
)
SELECT
  e.game_date,
  e.total_games,
  COALESCE(b.blocked_count, 0) as blocked,
  e.total_games - COALESCE(b.blocked_count, 0) as expected_available,
  COALESCE(a.actual_count, 0) as actual_collected,
  ROUND(100.0 * COALESCE(a.actual_count, 0) /
        (e.total_games - COALESCE(b.blocked_count, 0)), 1) as coverage_pct
FROM expected e
LEFT JOIN blocked b ON e.game_date = b.game_date
LEFT JOIN actual a ON e.game_date = a.game_date
ORDER BY e.game_date DESC;
```

3. **Block Patterns Over Time**
4. **Resolution Tracking**

**Steps:**
1. Create SQL files for each query
2. Test queries with 2026-01-25 data
3. Add to monitoring dashboard
4. Document in monitoring guide

---

#### Task #22: Document system ⏱️ 30 min
**Status:** Created
**Dependencies:** All tasks complete

**Documentation to Create:**

1. **User Guide:** `docs/guides/source-block-tracking.md`
   - What is source-block tracking?
   - When to use it
   - How to query blocked resources
   - How to manually record blocks
   - How validation uses it
   - Examples

2. **API Reference:** `docs/api/source_block_tracker.md`
   - Function signatures
   - Parameters
   - Return values
   - Examples

3. **Runbook Update:** `docs/runbooks/data-validation.md`
   - Add section on source blocks
   - How to interpret validation results
   - When blocks are expected vs concerning

**Steps:**
1. Create user guide
2. Create API reference
3. Update runbooks
4. Add examples
5. Link from main docs

---

## Execution Order

### Critical Path (Sequential)
```
START
  ↓
Task #14: Fix game_id mismatch (30 min)
  ↓
Task #15: Create table (15 min)
  ↓
Task #16: Create tracker module (45 min)
  ↓
Task #17: Insert historical data (10 min)
  ↓
Task #18: Update validation (30 min)
  ↓
Task #19: Integrate scraper (30 min)
  ↓
Task #20: Test end-to-end (20 min)
  ↓
Task #21: Monitoring queries (30 min) [Can be parallel with #22]
Task #22: Documentation (30 min) [Can be parallel with #21]
  ↓
COMPLETE (4 hours)
```

### Parallelization Opportunities
- Tasks #21 and #22 can run in parallel (saves 30 min)
- **Total with parallelization: 3.5 hours**

---

## Success Criteria

### After Task #14 (game_id fix)
- ✅ Validation shows 239 players for 2026-01-26
- ✅ check_game_context() JOIN works correctly

### After Task #17 (historical data)
- ✅ 2 blocked games in source_blocked_resources table
- ✅ Query returns correct game details

### After Task #18 (validation update)
- ✅ Validation for 2026-01-25 shows 100% (6/6 available, 2 blocked)
- ✅ No false failures for source-blocked games

### After Task #19 (scraper integration)
- ✅ Scraper auto-records blocks on 403/404
- ✅ Blocks appear in table within seconds

### After Task #20 (testing)
- ✅ All scenarios pass
- ✅ End-to-end flow works correctly

### After Task #21 (monitoring)
- ✅ Queries return correct data
- ✅ Dashboard shows accurate coverage

### After Task #22 (docs)
- ✅ Users can understand and use system
- ✅ Examples work as documented

---

## Time Budget

**Phase 1: Foundation**
- Task #14: 30 min
- Task #15: 15 min
- Task #16: 45 min
- Subtotal: 90 min

**Phase 2: Integration**
- Task #17: 10 min
- Task #18: 30 min
- Task #19: 30 min
- Subtotal: 70 min

**Phase 3: Testing & Docs**
- Task #20: 20 min
- Task #21: 30 min (parallel)
- Task #22: 30 min (parallel)
- Subtotal: 50 min (30 min with parallelization)

**Total: 3.5 - 4 hours**

---

## Risks & Mitigations

### Risk: BigQuery permissions
**Mitigation:** User has proven ability to create tables

### Risk: Complex scraper integration
**Mitigation:** Start simple, iterate. Can always add more scrapers later.

### Risk: Validation script changes break existing logic
**Mitigation:** Test thoroughly with 2026-01-25 and 2026-01-26 data

### Risk: Time overrun
**Mitigation:** Tasks #21-22 can be done later if needed (core functionality in #14-20)

---

## Next Steps

**START HERE:**

1. Begin Task #14 (game_id mismatch fix)
2. Move through phases sequentially
3. Test after each phase
4. Document as you go

Let's go! 🚀

---

**Document Status:** Ready for execution
**Next Update:** After each task completion
**Owner:** Implementation Team
