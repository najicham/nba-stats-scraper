# ⚡ QUICK REFERENCE - Next Session

**Last Updated**: January 6, 2026, 8:05 AM PST

---

## 🎯 30-SECOND STATUS

- **PCF is RUNNING**: PID 571554, ETA 3:45 PM
- **Phase 3**: ✅ 100% complete
- **Phase 4 Group 1**: ✅ Complete (TDZA + PSZA)
- **Phase 4 Group 2**: ⏳ Running (PCF 2/918 dates)
- **MERGE Bug Fix**: ✅ Validated in production!

---

## 📋 TODAY'S TODO (In Order)

### 1. Monitor PCF (Ongoing)
```bash
tail -f /tmp/phase4_pcf_sequential_20260106_080010.log
ps -p 571554  # Check if running
```

### 2. Deduplication (10:00 AM)
```bash
bash /tmp/dedup_reminder.sh
./scripts/maintenance/deduplicate_player_game_summary.sh
```

### 3. Launch Group 3 (3:45 PM - After PCF completes)
```bash
cd /home/naji/code/nba-stats-scraper && export PYTHONPATH=.
nohup python3 backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2026-01-03 --skip-preflight \
  > /tmp/phase4_pdc_$(date +%Y%m%d_%H%M%S).log 2>&1 &
echo "PDC PID: $!"
```

### 4. Launch Group 4 (7:00 PM - After Group 3 completes)
```bash
cd /home/naji/code/nba-stats-scraper && export PYTHONPATH=.
nohup python3 backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2026-01-03 --skip-preflight \
  > /tmp/phase4_mlfs_$(date +%Y%m%d_%H%M%S).log 2>&1 &
echo "MLFS PID: $!"
```

---

## 🚨 IF SOMETHING WENT WRONG

### PCF Died?
```bash
# Check log for errors
tail -100 /tmp/phase4_pcf_sequential_*.log

# Check checkpoint
cat /tmp/backfill_checkpoints/player_composite_factors_*.json | grep processed

# Restart (it will resume from checkpoint)
cd /home/naji/code/nba-stats-scraper && export PYTHONPATH=.
nohup python3 backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2021-10-19 --end-date 2026-01-03 --skip-preflight \
  > /tmp/phase4_pcf_restart_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

### Deduplication Failed?
```bash
# Check streaming buffer status
bq query --use_legacy_sql=false "DELETE FROM \`nba-props-platform.nba_analytics.player_game_summary\` WHERE game_date = '2021-10-20' AND 1=0"
# If error mentions "streaming buffer", wait 30-60 minutes
```

---

## 📊 VALIDATION QUERIES

### Check PCF Progress
```sql
SELECT COUNT(DISTINCT game_date) as dates
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2021-10-19'
-- Expected when complete: 848
```

### Check for Duplicates
```sql
SELECT COUNT(*) as dup_groups
FROM (
  SELECT game_id, player_lookup, COUNT(*) as cnt
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2021-10-19'
  GROUP BY game_id, player_lookup
  HAVING COUNT(*) > 1
)
-- Expected before dedup: 354
-- Expected after dedup: 0
```

### Verify MERGE Working
```bash
# Check logs for MERGE messages
grep "Using proper SQL MERGE" /tmp/phase4_pcf_sequential_*.log | head -5
# Should see: "Using proper SQL MERGE with temp table"
```

---

## 📞 KEY FILES

- **Full Handoff**: `/home/naji/code/nba-stats-scraper/HANDOFF-2026-01-06-MORNING.md`
- **PCF Log**: `/tmp/phase4_pcf_sequential_20260106_080010.log`
- **PCF PID**: 571554
- **PCF Checkpoint**: `/tmp/backfill_checkpoints/player_composite_factors_2021-10-19_2026-01-03.json`

---

## 🎯 SUCCESS = PHASE 4 COMPLETE BY TONIGHT

**Timeline**:
- 3:45 PM: PCF done
- 7:00 PM: Group 3 done
- 11:00 PM: Group 4 done
- **PHASE 4 COMPLETE!** 🎉

Then tomorrow: Phase 5 & 6 → **100% COMPLETE!**

---

**Read full details**: `cat /home/naji/code/nba-stats-scraper/HANDOFF-2026-01-06-MORNING.md`
