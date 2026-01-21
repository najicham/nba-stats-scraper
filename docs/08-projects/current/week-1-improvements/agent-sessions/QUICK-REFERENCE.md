# Missing Tables Investigation - Quick Reference
**Date:** 2026-01-21
**Status:** ✅ Resolved - No tables missing, config fix only

---

## One-Line Summary
All Phase 2 tables exist; orchestrator config expects `br_roster` but table is named `br_rosters_current`.

---

## Phase 2 Expected Tables Status

```
✅ bdl_player_boxscores       → EXISTS (1,195 rows in last 7 days)
✅ bigdataball_play_by_play   → EXISTS (0 rows - no games today yet)
✅ odds_api_game_lines        → EXISTS (312 rows - Jan 18)
✅ nbac_schedule              → EXISTS (643 rows - through June)
✅ nbac_gamebook_player_stats → EXISTS (1,402 rows - Jan 19)
❌ br_roster                  → WRONG NAME
   ✅ br_rosters_current       → CORRECT NAME (655 rows - season 2024)
```

---

## Impact

**Tonight's Pipeline:** ✅ SAFE - No impact
**Monitoring:** ⚠️ Name mismatch affects tracking only

---

## Fix

Update 2 files, change line 32/87:
```python
# Before:
'br_roster',

# After:
'br_rosters_current',
```

**Files:**
- `/shared/config/orchestration_config.py` (line 32)
- `/orchestration/cloud_functions/phase2_to_phase3/main.py` (line 87)

**Priority:** Low - can wait for next deployment

---

## Verification Command

```bash
bq query --use_legacy_sql=false '
SELECT
  "br_rosters_current" as table,
  COUNT(*) as players,
  COUNT(DISTINCT team_abbrev) as teams,
  MAX(last_scraped_date) as updated
FROM `nba-props-platform.nba_raw.br_rosters_current`
WHERE season_year = 2024'
```

Expected: ~450 players, 30 teams, recent update date

---

## Why It Doesn't Break

1. Phase 2→3 orchestrator is **monitoring-only**
2. Phase 3 triggered via **Pub/Sub subscription**
3. Phase 3 reads via **fallback_config.yaml** (has correct name)
4. BR roster processor writes to **br_rosters_current** successfully

---

## Full Reports

- **INVESTIGATION-SUMMARY.md** - Executive summary
- **MISSING-TABLES-INVESTIGATION.md** - Full investigation report
- **PHASE2-ORCHESTRATOR-CONFIG-FIX.md** - Deployment instructions
