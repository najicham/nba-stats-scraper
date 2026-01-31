# Shot Zone Data Quality Fix - Operational Handoff

**Date:** 2026-01-31  
**Session:** 53  
**Status:** ✅ Production Ready  
**Priority:** HIGH - Affects ML model training and analytics

---

## What Changed

### Problem Fixed
Shot zone data was mixing sources causing corrupted rates:
- **Before:** Paint 25.9%, Three 61% ❌
- **After:** Paint 41.5%, Three 32.7% ✅

### Root Cause
```
paint_attempts     → from play-by-play (50-90% coverage)
three_pt_attempts  → from box score (100% coverage)
                   = Corrupted rates when PBP missing
```

### Solution
All zone fields now from same play-by-play source. When PBP unavailable, all zones = NULL (no mixed sources).

---

## Code Changes

### Files Modified (4)
1. `shot_zone_analyzer.py` - Extract three_pt from PBP
2. `player_game_summary_processor.py` - Use PBP three_pt, add completeness flag
3. `player_shot_zone_analysis_processor.py` - Documentation update
4. `player_game_summary_tables.sql` - Schema updates

### Schema Changes
```sql
-- Added to nba_analytics.player_game_summary
three_attempts_pbp         INT64    -- Three-point attempts from PBP
three_makes_pbp           INT64    -- Three-point makes from PBP
has_complete_shot_zones   BOOLEAN  -- TRUE = all zones from same source
```

### Data Backfilled
- **Dates:** Jan 17-30, 2026
- **Records:** 3,538 reprocessed
- **Complete zones:** 1,134 (32.1%)

---

## Verification

### Daily Health Check
```sql
-- Run this daily - expect 50-90% complete, rates 30-45% paint, 20-50% three
SELECT game_date,
  COUNTIF(has_complete_shot_zones = TRUE) * 100.0 / COUNT(*) as pct_complete,
  ROUND(AVG(CASE WHEN has_complete_shot_zones = TRUE
    THEN SAFE_DIVIDE(paint_attempts * 100.0, 
         paint_attempts + mid_range_attempts + three_attempts_pbp) END), 1) as paint_rate,
  ROUND(AVG(CASE WHEN has_complete_shot_zones = TRUE
    THEN SAFE_DIVIDE(three_attempts_pbp * 100.0, 
         paint_attempts + mid_range_attempts + three_attempts_pbp) END), 1) as three_rate
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= CURRENT_DATE() - 3 AND minutes_played > 0
GROUP BY 1 ORDER BY 1 DESC;
```

**Expected:**
- `pct_complete`: 50-90%
- `paint_rate`: 30-45%
- `three_rate`: 20-50%

**Red flags:**
- Paint < 25% or Three > 55% = **DATA CORRUPTION**
- Completeness < 20% for 3+ days = **BDB ISSUE**

### Regression Check
```sql
-- Verify three_pt_attempts matches three_attempts_pbp (should be 100%)
SELECT
  COUNTIF(three_pt_attempts = three_attempts_pbp) as matching,
  COUNTIF(three_pt_attempts != three_attempts_pbp) as mismatched
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= CURRENT_DATE() - 3
  AND has_complete_shot_zones = TRUE;
```

**Expected:** `mismatched = 0`  
**If mismatched > 0:** CODE REGRESSION - Escalate immediately

---

## Using the Fix

### In Analytics Queries
```sql
-- ALWAYS filter for complete zones when using shot zone data
SELECT player_lookup, 
  AVG(SAFE_DIVIDE(paint_attempts, paint_attempts + mid_range_attempts + three_attempts_pbp)) as paint_rate
FROM player_game_summary
WHERE has_complete_shot_zones = TRUE  -- THIS IS CRITICAL
  AND game_date >= '2026-01-17'
GROUP BY 1;
```

### In ML Training
```python
# Filter training data for reliable shot zones
query = """
SELECT * FROM player_game_summary
WHERE has_complete_shot_zones = TRUE
  AND game_date >= '2024-10-22'  -- 2024-25 season
"""
```

### In Phase 4 Processors
No changes needed - existing safeguards now work correctly.

---

## Troubleshooting

### Issue: Low Shot Zone Completeness (<50%)

**Diagnosis:**
```sql
-- Check if BigDataBall PBP data exists
SELECT game_date, COUNT(DISTINCT game_id) as bdb_games
FROM `nba-props-platform.nba_raw.bigdataball_play_by_play`
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1 DESC;

-- Compare to scheduled games
SELECT game_date, COUNT(*) as scheduled
FROM `nba-props-platform.nba_reference.nba_schedule`
WHERE game_date >= CURRENT_DATE() - 3
  AND game_status = 3  -- Final
GROUP BY 1 ORDER BY 1 DESC;
```

**Fix:**
- If BDB games < scheduled: BigDataBall scraper issue
- If BDB games = scheduled: Normal - some players didn't have PBP data
- Action: Use `has_complete_shot_zones = TRUE` filter in queries

### Issue: Wrong Shot Zone Rates

**Diagnosis:**
```sql
-- Check a specific date
SELECT 
  COUNT(*) as total,
  COUNTIF(has_complete_shot_zones = TRUE) as complete,
  COUNTIF(three_pt_attempts = three_attempts_pbp) as matching
FROM player_game_summary
WHERE game_date = '2026-01-30';
```

**Possible causes:**
1. **Not filtering for `has_complete_shot_zones = TRUE`**
   - Fix: Add filter to query
2. **Code regression** (three_pt from box score again)
   - Fix: Check `player_game_summary_processor.py` lines ~1686, 2275
   - Verify: `three_pt_attempts = shot_zone_data.get('three_attempts_pbp')`
3. **Old data pre-fix**
   - Fix: Reprocess date with fixed code

### Issue: All Zones NULL for Recent Date

**Likely cause:** BigDataBall PBP not available yet

**Check:**
```bash
# Look for BDB extraction logs
gcloud logging read 'textPayload:"BigDataBall" AND timestamp>="DATE"' --limit=20
```

**Fix:**
- Wait 4-6 hours after games complete
- Or check if BDB scraper failed
- If >24 hours: Investigate BDB scraper

---

## Monitoring Setup

### Add to Daily Validation

In `bin/validate_pipeline.py` or daily script:
```python
# Check shot zone quality
query = """
SELECT 
  COUNTIF(has_complete_shot_zones = TRUE) * 100.0 / COUNT(*) as pct_complete,
  AVG(CASE WHEN has_complete_shot_zones = TRUE 
    THEN SAFE_DIVIDE(paint_attempts * 100.0, 
         paint_attempts + mid_range_attempts + three_attempts_pbp) END) as paint_rate
FROM player_game_summary
WHERE game_date = CURRENT_DATE() - 1 AND minutes_played > 0
"""

# Alert if paint_rate < 25 or paint_rate > 50
```

### Alert Conditions

| Metric | Threshold | Severity | Action |
|--------|-----------|----------|--------|
| Paint rate < 25% | Daily | 🔴 CRITICAL | Check for code regression |
| Three rate > 55% | Daily | 🔴 CRITICAL | Check for code regression |
| Completeness < 20% | 3 days | 🟡 WARNING | Check BDB scraper |
| Mismatched fields | Any | 🔴 CRITICAL | Code regression - revert |

---

## For ML Engineers

### Training Data Filter
```sql
-- REQUIRED: Filter for complete shot zones
WHERE has_complete_shot_zones = TRUE
```

### Historical Data Note
- **Jan 17, 2026 onwards:** Fixed data ✅
- **Pre-Jan 17, 2026:** May have corrupted rates ⚠️
- **Recommendation:** Start training data from Jan 17, 2026 or reprocess earlier dates

### Feature Impact
Features now reliable:
- `pct_paint`
- `pct_mid_range`
- `pct_three`
- Any derived shot zone features

### What Changed
- Old: `three_pt_attempts` from box score (always available)
- New: `three_pt_attempts` from PBP (matches paint/mid source)
- Impact: Some records now have NULL zones (when PBP unavailable)
- Benefit: No more corrupted rates from mixed sources

---

## Reference Documentation

### Quick Links
- **Investigation:** `docs/09-handoff/2026-01-31-SHOT-ZONE-DATA-INVESTIGATION.md`
- **Fix Details:** `docs/09-handoff/2026-01-31-SESSION-53-SHOT-ZONE-FIX-COMPLETE.md`
- **Full Handoff:** `docs/09-handoff/2026-01-31-SESSION-53-FINAL-HANDOFF.md`
- **Troubleshooting:** `docs/02-operations/troubleshooting-matrix.md` Section 2.4
- **Daily Validation:** `docs/02-operations/daily-validation-checklist.md` Step 3b

### Code Locations
```
shot_zone_analyzer.py                  Line ~302  (BigDataBall extraction)
player_game_summary_processor.py       Line ~1686 (Use PBP three_pt)
player_game_summary_processor.py       Line ~2275 (Serial path)
player_game_summary_tables.sql         Line ~72   (Schema definition)
```

### Commits
1. `13ca17fc` - Core fix (shot zone source consistency)
2. `97275456` - Downstream doc update
3. `7ee7dbf3` - Completion handoff
4. `07248218` - Project doc updates
5. `589c0631` - Final handoff

---

## Quick Decision Tree

```
Is shot zone data behaving oddly?
│
├─ Are rates outside 30-45% paint, 20-50% three?
│  └─ YES → Check if filtering for has_complete_shot_zones = TRUE
│     ├─ Not filtering → Add filter
│     └─ Already filtering → CODE REGRESSION - check processor code
│
├─ Is completeness very low (<20%)?
│  └─ YES → Check BigDataBall PBP availability
│     ├─ BDB missing → Normal, wait or investigate scraper
│     └─ BDB exists → Processor issue, check logs
│
└─ Are three_pt_attempts and three_attempts_pbp mismatched?
   └─ YES → CODE REGRESSION - revert recent changes
```

---

## Rollback Plan (If Needed)

If the fix causes issues:

1. **Revert code:**
   ```bash
   git revert 13ca17fc
   git push origin main
   ```

2. **Redeploy processor:**
   ```bash
   # This will deploy the reverted code
   python -m data_processors.analytics.player_game_summary.player_game_summary_processor \
     --start-date PROBLEM_DATE --end-date PROBLEM_DATE
   ```

3. **Verify:**
   ```sql
   SELECT COUNT(*) FROM player_game_summary WHERE game_date = 'PROBLEM_DATE';
   ```

4. **Alert:** Notify in Slack/email that shot zone fix was reverted

---

## Contact Information

**For questions:**
- Check: `docs/02-operations/troubleshooting-matrix.md` Section 2.4
- Review: Full handoff in `docs/09-handoff/2026-01-31-SESSION-53-FINAL-HANDOFF.md`

**Escalation:**
- Data corruption: Revert code and investigate
- Low completeness: Check BDB scraper health
- Code regression: Review recent commits to processor

---

## Success Metrics

**Fix is working if:**
- ✅ Shot zone completeness: 50-90% (varies by BDB coverage)
- ✅ Paint rate: 30-45%
- ✅ Three rate: 20-50%
- ✅ Rates sum to ~100%
- ✅ zero_pt_attempts = three_attempts_pbp (100% match)

**Fix needs attention if:**
- ❌ Paint rate < 25% or three rate > 55%
- ❌ Completeness < 20% for 3+ consecutive days
- ❌ Mismatches between three_pt_attempts and three_attempts_pbp

---

**Last Updated:** 2026-01-31  
**Owner:** Data Engineering  
**Status:** ✅ Active in Production
