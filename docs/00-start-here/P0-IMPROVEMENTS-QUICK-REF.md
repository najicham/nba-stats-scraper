# P0 Backfill Improvements - Quick Reference
**Last Updated:** 2026-01-13
**Status:** ✅ Production Ready

---

## 🎯 What Changed?

4 critical safeguards added to prevent partial backfills like the Jan 6, 2026 incident:

1. **Coverage Validation** - Blocks checkpoint if < 90% players processed
2. **Defensive Logging** - Shows UPCG vs PGS comparison in logs
3. **Fallback Logic Fix** - Triggers on partial data (not just empty)
4. **Data Cleanup** - Automated daily cleanup of stale UPCG records

---

## 🚀 Quick Start

### Running a Backfill (Normal)
```bash
# No changes needed - just works!
PYTHONPATH=. python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2023-02-23 --end-date 2023-02-24 --parallel
```

### What You'll See (New Logs)
```
📊 Data source check for 2023-02-23:
   - upcoming_player_game_context (UPCG): 187 players
   - player_game_summary (PGS): 187 players
   - Coverage: 100.0%

✅ Using upcoming_player_game_context: 187 players

✅ Coverage validation passed: 187/187 players (100.0%)
```

### If There's a Problem
```
📊 Data source check for 2023-02-23:
   - upcoming_player_game_context (UPCG): 1 players
   - player_game_summary (PGS): 187 players
   - Coverage: 0.5%

❌ INCOMPLETE DATA DETECTED for 2023-02-23:
   - upcoming_player_game_context has only 1/187 players (0.5%)
   - Missing 186 players
   → RECOMMENDATION: Clear stale UPCG data before running backfill

🔄 TRIGGERING FALLBACK for 2023-02-23:
   - Reason: UPCG has incomplete data (1/187 = 0.5%)
   - Action: Generating synthetic context from player_game_summary

✅ Coverage validation passed: 187/187 players (100.0%)
```

---

## ⚠️ Edge Cases

### Validation Fails But You Know It's Legitimate

**Scenario:** Roster trade mid-game, legitimate coverage is 85%

**Solution:**
```bash
# Use --force flag to bypass validation
python ...backfill.py --start-date DATE --end-date DATE --force
```

**⚠️ CAUTION:** Only use `--force` when you understand WHY coverage is low!

### Bootstrap Period (First 14 Days of Season)

**Scenario:** No games in bootstrap period
**Behavior:** Validation passes automatically (expected = 0)
**Action:** None needed

### Off-Days (No NBA Games)

**Scenario:** All-Star break, no games scheduled
**Behavior:** Validation passes automatically (expected = 0)
**Action:** None needed

---

## 🗑️ Data Cleanup

### One-Time Cleanup (If Needed)
```bash
# Preview what will be deleted
python scripts/cleanup_stale_upcoming_tables.py --dry-run

# Execute cleanup (creates backup automatically)
python scripts/cleanup_stale_upcoming_tables.py
```

### Automated Cleanup (Daily at 4 AM ET)

**Already deployed:** Cloud Function runs automatically
**Monitor:** Check BigQuery for cleanup logs
```sql
SELECT * FROM nba_orchestration.cleanup_operations
WHERE cleanup_type = 'upcoming_tables_ttl'
ORDER BY cleanup_time DESC
LIMIT 10;
```

---

## 📊 Monitoring

### Check Coverage for Recent Runs
```sql
-- Query checkpoint for recent runs
SELECT
  date,
  status,
  error
FROM checkpoint_table
WHERE processor_name = 'PlayerCompositeFactorsProcessor'
  AND status = 'failed'
  AND error LIKE '%Coverage validation%'
ORDER BY date DESC
LIMIT 10;
```

### Check for Stale UPCG Data
```sql
-- Find records older than 7 days (shouldn't exist)
SELECT
  game_date,
  COUNT(*) as stale_records
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date < CURRENT_DATE() - INTERVAL 7 DAY
GROUP BY game_date
ORDER BY game_date DESC;
```

---

## 🐛 Troubleshooting

### Problem: "Coverage validation failed (X players)"

**Possible Causes:**
1. Stale data in `upcoming_player_game_context`
2. Incomplete `player_game_summary` (upstream issue)
3. Legitimate roster change (trade, injury)

**Solutions:**
1. Check defensive logs for UPCG vs PGS counts
2. Query both tables to verify expected count:
   ```sql
   -- Expected count
   SELECT COUNT(DISTINCT player_lookup) FROM nba_analytics.player_game_summary WHERE game_date = 'YYYY-MM-DD';

   -- Actual count
   SELECT COUNT(DISTINCT player_lookup) FROM nba_precompute.player_composite_factors WHERE analysis_date = 'YYYY-MM-DD';
   ```
3. If legitimate, use `--force` flag
4. If stale UPCG, run cleanup script

### Problem: Fallback not triggering when UPCG is partial

**Check:**
1. Is `backfill_mode: True` in opts?
2. Are you running the latest code?
3. Check logs for "Data source check" message

**Debug:**
```bash
# Verify code has the fix
grep -A5 "upcg_count < expected_count \* 0.9" data_processors/precompute/player_composite_factors/player_composite_factors_processor.py
```

### Problem: Too many cleanup notifications

**If getting alerts every day:**
- Check if backfill is running on historical dates
- Verify TTL_DAYS is set correctly (default: 7)
- Review if pipeline is creating UPCG records for past dates

---

## 📞 Quick Help

### I need to...

**...run a backfill and it's failing validation:**
1. Check logs for coverage percentage
2. If < 90%, determine if legitimate
3. If stale data, run cleanup script
4. If legitimate edge case, use `--force`

**...understand why validation failed:**
1. Look for "📊 Data source check" in logs
2. Compare UPCG count vs PGS count
3. Check coverage percentage

**...bypass validation for a one-time run:**
```bash
python ...backfill.py --start-date DATE --end-date DATE --force
```

**...check if cleanup is running:**
```sql
SELECT * FROM nba_orchestration.cleanup_operations
WHERE cleanup_type = 'upcoming_tables_ttl'
ORDER BY cleanup_time DESC LIMIT 1;
```

**...test the improvements:**
```bash
pytest tests/test_p0_improvements.py -v
```

---

## 📚 Full Documentation

- **Implementation Details:** `docs/08-projects/current/historical-backfill-audit/2026-01-13-P0-IMPLEMENTATION-SUMMARY.md`
- **Test Results:** `docs/08-projects/current/historical-backfill-audit/2026-01-13-P0-VALIDATION-REPORT.md`
- **Session Handoff:** `docs/09-handoff/2026-01-13-SESSION-30-HANDOFF.md`
- **Cloud Function Setup:** `orchestration/cloud_functions/upcoming_tables_cleanup/README.md`
- **Root Cause Analysis:** `docs/08-projects/current/historical-backfill-audit/ROOT-CAUSE-ANALYSIS-2026-01-12.md`

---

## ✅ Validation Checklist

Before running backfill:
- [ ] Check for stale UPCG data (should be none > 7 days old)
- [ ] Verify `player_game_summary` has data for target dates
- [ ] Review recent checkpoint failures (if any)

After running backfill:
- [ ] Check logs for coverage validation results
- [ ] Verify 100% coverage achieved
- [ ] Confirm no "Coverage validation failed" errors

---

## 🎯 Success Metrics

**Target:** 0 partial backfill incidents per month

**Monitor:**
- Coverage validation failures (should be 0 or < 1 per month)
- Fallback triggers (log count)
- Cleanup records deleted daily (should be < 1000)

**Alert on:**
- Any coverage validation failure
- Cleanup deleting > 10,000 records (unusual)
- Fallback triggering > 2 times per week (investigate why)

---

**For urgent issues:** Check logs first, then reference full documentation

**Last validated:** 2026-01-13 (21/21 tests passing)
