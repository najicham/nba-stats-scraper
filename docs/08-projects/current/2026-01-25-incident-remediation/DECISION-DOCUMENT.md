# Decision Document: Resource-Level Source Block Tracking

**Date:** 2026-01-26
**Purpose:** Decision on implementing resource-level tracking for source data unavailability
**Status:** 🟡 Awaiting Decision
**Estimated Effort:** 4-5 hours implementation
**Recommended:** ✅ Yes - Implement

---

## TL;DR

**Problem:** Validation tools can't distinguish between "scraper broken" and "data unavailable from source"
**Solution:** Add resource-level tracking table to record specific unavailable resources
**Benefit:** Accurate validation + monitoring, no false alerts, permanent solution
**Cost:** 4-5 hours implementation
**Recommendation:** Implement - high value, reasonable effort, solves permanently

---

## What We Discovered

### Investigation of 2026-01-25 Missing PBP Games

**Initial belief:** NBA.com blocking our IP
**Actual finding:** Data unavailable from **all sources** (BDB + NBA.com)

```
2026-01-25 PBP Data:
✅ BDB (primary):     6 games (3,517 events)
✅ NBA.com (backup):  6 games (3,517 events)
❌ Both missing:      Games 0022500651 (DEN@MEM), 0022500652 (DAL@MIL)
```

**Key Evidence:**
- NBA.com returns HTTP 200 for all 6 successful games ✅
- NBA.com returns HTTP 403 for both missing games ❌
- BDB (completely different source) also missing same 2 games
- Perfect correlation: If in GCS → accessible from source, If missing → blocked/unavailable

**Conclusion:** Not an infrastructure issue. Data genuinely unavailable from sources (likely games postponed/cancelled or upstream data issue).

---

## The Problem

### Current State

We **do** track proxy issues in `nba_orchestration.proxy_health_metrics`:
```sql
-- Tracks host-level requests
SELECT * FROM nba_orchestration.proxy_health_metrics
WHERE target_host = 'cdn.nba.com' AND http_status_code = 403;

-- Shows: cdn.nba.com returned 403 (20+ times during retries)
```

**But it only tracks HOST level, not RESOURCE level:**
- ✅ Knows: `cdn.nba.com` returned 403
- ❌ Doesn't know: **Which specific game** returned 403
- ❌ Can't tell validation: "This specific game is unavailable"

### The Gap

When validation checks data completeness:

**Today (without resource tracking):**
```
2026-01-25 PBP Check:
- Expected: 8 games
- Found: 6 games
- Result: ❌ FAIL (75% - something's broken!)
- Action: Alert fires, manual investigation required
- Monitoring: Shows 75% success (looks bad)
```

**Problem:** Can't distinguish:
1. Infrastructure failure (scraper broken, needs fixing)
2. Source block (specific resource blocked by source)
3. Source unavailable (data doesn't exist anywhere)

All three look the same to validation tools.

---

## The Solution

### Add Resource-Level Tracking

**New Table:** `nba_orchestration.source_blocked_resources`

**Tracks:**
- Specific resource IDs (game_id, player_id, etc.)
- Which source system blocked it (nba_com_cdn, bdb, etc.)
- HTTP status code (403, 404, 410)
- When first detected and last verified
- Whether available from alternative source

**Example Data:**
```sql
INSERT INTO nba_orchestration.source_blocked_resources VALUES
('0022500651', 'play_by_play', '2026-01-25', 'nba_com_cdn', 403,
 'DEN@MEM - Blocked by NBA.com CDN, also unavailable from BDB');
```

### Integration

**1. Validation (most important):**
```python
# Updated completeness check
def check_pbp_completeness(game_date):
    expected_games = get_games_for_date(game_date)  # 8 games
    blocked_games = get_source_blocked_resources(game_date, 'play_by_play')  # 2 games
    actual_games = get_pbp_games_from_storage(game_date)  # 6 games

    expected_available = 8 - 2  # = 6
    actual_available = 6

    return {
        'complete': actual_available >= expected_available,  # TRUE ✅
        'coverage_pct': 100.0  # 6/6 available = 100%
    }
```

**2. Monitoring:**
```sql
-- Dashboard shows accurate metrics
SELECT
  game_date,
  8 as total_games,
  2 as source_blocked,
  6 as expected_available,
  6 as actual_collected,
  '100%' as coverage_of_available  -- Not 75%!
FROM ...
```

**3. Scrapers (automatic):**
```python
# When scraper gets 403/404, automatically record
if response.status_code in [403, 404, 410]:
    record_source_block(
        resource_id=game_id,
        resource_type='play_by_play',
        source_system='nba_com_cdn',
        http_status_code=403
    )
```

---

## Benefits vs Costs

### Benefits

**1. Accurate Validation**
- ✅ No false positives (2026-01-25 shows as complete)
- ✅ Only alerts on real infrastructure failures
- ✅ Clear distinction between broken scrapers and unavailable data

**2. Better Monitoring**
- ✅ Dashboards show true success rates (100% not 75%)
- ✅ Historical tracking of source issues
- ✅ Pattern detection (e.g., "Every DEN game blocked lately")

**3. Reduced Operations Burden**
- ✅ Less manual investigation required
- ✅ Clear documentation of what's unavailable
- ✅ No need to explain "why is this showing as failed?"

**4. Future-Proof**
- ✅ Handles next source block automatically
- ✅ Works for any data type (not just PBP)
- ✅ Scales to multiple sources

### Costs

**Implementation Time: 4-5 hours**
```
1. Create table schema              30 min
2. Build helper functions           1 hour
3. Update validation logic          1 hour
4. Update monitoring dashboards     30 min
5. Integrate with scrapers          1 hour
6. Testing & documentation          1 hour
-------------------------------------------
Total:                              4-5 hours
```

**Ongoing Maintenance:** Minimal
- Table is append-only, auto-partitioned
- No manual updates needed (scrapers auto-populate)
- Optional: Weekly job to re-verify blocks (~15 min to set up)

---

## Alternative Options

### Option A: Do Nothing (Not Recommended)
**Pros:**
- Zero effort

**Cons:**
- ❌ 2026-01-25 shows as failed forever
- ❌ Next incident requires same manual investigation
- ❌ False alerts continue
- ❌ Monitoring shows incorrect metrics

**When to choose:** Never

---

### Option B: Implement Tracking System (Recommended) ⭐
**Pros:**
- ✅ Solves problem permanently
- ✅ Reasonable effort (4-5 hours)
- ✅ High value for operations
- ✅ Clean architecture

**Cons:**
- ⚠️ Requires 4-5 hours dev time
- ⚠️ New table to maintain (minimal)

**When to choose:** If you want accurate validation and monitoring going forward

---

### Option C: Manual Documentation Only
**Approach:** Just document in a text file that these 2 games are blocked

**Pros:**
- ✅ Quick (15 minutes)

**Cons:**
- ❌ Validation still shows as failed
- ❌ Monitoring still shows 75%
- ❌ Doesn't help future incidents
- ❌ No systematic solution

**When to choose:** If you absolutely can't spare 4-5 hours

---

## Real-World Examples

### Before Implementation

**Scenario:** It's 2026-02-15, validation checks PBP data for yesterday

```
❌ ALERT: PBP Data Incomplete for 2026-02-14
- Expected: 10 games
- Found: 8 games
- Coverage: 80%
- Action Required: Investigate missing games

Engineer Response:
1. Checks logs (30 min)
2. Tests scraper manually (15 min)
3. Checks source availability (15 min)
4. Discovers: Games cancelled due to weather
5. Documents in Slack
6. Updates validation... oh wait, can't update without code change
Total time: 60+ minutes
```

### After Implementation

**Scenario:** Same situation

```
✅ PBP Data Complete for 2026-02-14
- Total games: 10
- Source blocked: 2 (weather cancellations - auto-detected)
- Expected available: 8
- Collected: 8
- Coverage: 100%
- No action required

Engineer Response:
1. Reviews dashboard, sees 100% of available
2. Checks source_blocked_resources table (optional)
3. Moves on
Total time: 2 minutes
```

---

## Comparison: Current vs Proposed

| Aspect | Without Tracking | With Tracking |
|--------|-----------------|---------------|
| **2026-01-25 Status** | ❌ Failed (75%) | ✅ Complete (100% available) |
| **Validation Accuracy** | False positives | True state |
| **Monitoring Metrics** | Misleading (75%) | Accurate (100%) |
| **Investigation Time** | 30-60 min per incident | 2-5 min (or zero) |
| **False Alerts** | Yes (every blocked resource) | No (only real failures) |
| **Pattern Detection** | Manual | Automatic |
| **Historical Record** | None | Full tracking |
| **Future Incidents** | Same manual work | Auto-handled |

---

## Risk Assessment

### Implementation Risks: LOW ✅

**Why low risk:**
- Additive only (new table, doesn't modify existing)
- No breaking changes to current systems
- Validation tools have fallback (if table empty, works like today)
- Can roll out gradually (test with one scraper first)

**Mitigation:**
- Test thoroughly with 2026-01-25 data before production
- Roll out to PBP scraper first, expand later
- Keep existing proxy_health_metrics unchanged

### Operational Risks: VERY LOW ✅

**Why very low:**
- Table is partitioned and clustered (scalable)
- Scrapers do async writes (no performance impact)
- Validation queries cached (no slow-down)
- No external dependencies

---

## Recommendation

### ✅ Implement Resource-Level Tracking System

**Reasoning:**

1. **High Value**
   - Solves operational pain point (false alerts)
   - Improves data quality monitoring
   - Reduces manual investigation time

2. **Reasonable Cost**
   - 4-5 hours is small investment
   - One-time effort, permanent benefit
   - Already designed (just needs implementation)

3. **Low Risk**
   - Additive only
   - Doesn't modify existing systems
   - Gradual rollout possible

4. **Architectural Soundness**
   - Clean separation: host-level + resource-level
   - Extends existing patterns (like proxy_health_metrics)
   - Scalable to other data types

5. **Immediate Payoff**
   - 2026-01-25 validates correctly immediately
   - Next source block handled automatically
   - Less noise in monitoring

### Suggested Timeline

**Phase 1: Core Implementation (3 hours)**
- Create table schema (30 min)
- Build helper functions (1 hour)
- Update validation logic (1 hour)
- Manual insert for 2026-01-25 games (30 min)
- **Test: 2026-01-25 should validate as 100% complete**

**Phase 2: Monitoring & Automation (2 hours)**
- Update monitoring dashboards (30 min)
- Integrate with PBP scraper (1 hour)
- Test with manual retry (30 min)
- **Test: New blocks auto-recorded**

**Phase 3: Polish (optional, later)**
- Roll out to other scrapers
- Add periodic re-verification job
- Enhance dashboards

---

## Decision Criteria

### Choose "Implement" If:
- ✅ You want accurate validation going forward
- ✅ You have 4-5 hours available this week
- ✅ False alerts are causing operational overhead
- ✅ You value clean architecture

### Choose "Don't Implement" If:
- ❌ You're okay with 2026-01-25 showing as failed
- ❌ You don't mind manual investigation each time
- ❌ You prefer living with false alerts
- ❌ You can't spare 4-5 hours

---

## Questions to Answer

### Q1: Will this prevent all false alerts?
**A:** For source unavailability issues, yes. Infrastructure failures (scraper bugs, network issues) will still alert correctly.

### Q2: What if we need to track other data types?
**A:** System is designed for that. Same table handles PBP, box scores, player stats, etc. Just change `resource_type` field.

### Q3: Do we need to backfill historical data?
**A:** No, not required. Can start fresh. Historical audit showed no systematic issues. But you *could* backfill if desired.

### Q4: What if a blocked resource becomes available later?
**A:** Optional periodic job re-checks and marks as resolved. Or manual update. Not required for core functionality.

### Q5: Does this add complexity?
**A:** Minimal. One new table, one new module. Validation gets *simpler* (clearer logic). Monitoring gets more accurate.

### Q6: Can we implement partially (just validation, not scrapers)?
**A:** Yes! Phase 1 (validation only) gives immediate value. Phase 2 (scraper integration) adds automation. Can do Phase 1 first, Phase 2 later.

---

## Supporting Documentation

**For detailed technical design:**
- `SOURCE-BLOCK-TRACKING-DESIGN.md` - Full schema, code examples, integration points

**For investigation details:**
- `FINDINGS-SUMMARY.md` - Complete investigation results
- `SOURCE-BLOCKED-GAMES-ANALYSIS.md` - Strategic analysis and options

**For context:**
- `STATUS.md` - Incident status (updated with findings)
- `REMAINING-WORK.md` - Outstanding work (all data recovered)

---

## Next Steps

### If Decision is "Yes, Implement"

1. **Review technical design** (SOURCE-BLOCK-TRACKING-DESIGN.md)
2. **Allocate 4-5 hours** this week
3. **Start with Phase 1** (core implementation)
4. **Test with 2026-01-25** data
5. **Roll out Phase 2** (automation)

### If Decision is "No, Don't Implement"

1. **Document 2026-01-25** blocked games in text file
2. **Accept validation shows as failed**
3. **Plan for manual investigation** next time
4. **Consider revisiting** if false alerts become problem

### If Decision is "Need More Info"

**Key questions to resolve:**
- What's the biggest concern? (Time? Risk? Complexity?)
- What would change your decision?
- Would partial implementation (just validation) be acceptable?

---

## Summary

**Problem:** Validation can't tell if scraper broken or data unavailable
**Solution:** Track unavailable resources at granular level
**Benefit:** Accurate validation, no false alerts, less manual work
**Cost:** 4-5 hours one-time implementation
**Risk:** Low (additive only, thoroughly designed)
**Recommendation:** ✅ Implement - high value, reasonable effort

**Bottom line:** This is a permanent solution to an operational pain point. The design is ready, the effort is reasonable, and the value is high. Recommend implementing.

---

**Author:** Claude Code
**Date:** 2026-01-26
**Status:** Awaiting Decision
**Contact:** Review full technical design in SOURCE-BLOCK-TRACKING-DESIGN.md
