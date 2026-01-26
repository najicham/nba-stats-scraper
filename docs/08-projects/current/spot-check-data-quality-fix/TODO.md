# Spot Check Fix - TODO Checklist

**Status**: Phase 1 complete, Phase 2-4 pending
**Estimated Time**: 30-35 minutes total

---

## ✅ Completed

- [x] Investigate data quality issues (Session 113 spot check failures)
- [x] Identify root cause (date filter bug: `<=` should be `<`)
- [x] Fix code in player_daily_cache_processor.py (lines 425, 454)
- [x] Create standalone regeneration script (scripts/regenerate_player_daily_cache.py)
- [x] Regenerate recent data (last 31 days: 2024-12-27 to 2025-01-26)
- [x] Validate fix (Mo Bamba 28%→0%, Josh Giddey 27%→0%)
- [x] Document everything (6 docs created)

---

## ⏳ Remaining Tasks

### [ ] Task 1: Full Season Regeneration
**Priority**: HIGH
**Time**: 5-10 minutes
**Command**:
```bash
cd /home/naji/code/nba-stats-scraper

nohup python scripts/regenerate_player_daily_cache.py \
  --start-date 2024-10-01 \
  --end-date 2025-01-26 \
  > logs/cache_regeneration_full_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# Monitor
tail -f logs/cache_regeneration_full_*.log

# Verify completion
grep "REGENERATION COMPLETE" logs/cache_regeneration_full_*.log
```

**Expected**:
- ~118 days processed
- ~15,000-18,000 records updated
- All rolling averages fixed

---

### [ ] Task 2: ML Feature Store Update
**Priority**: HIGH
**Time**: 10-15 minutes
**Depends on**: Task 1 complete

**Command**:
```bash
# Try existing processor first
python data_processors/predictions/ml_feature_store_v2_processor.py \
  --start-date 2024-10-01 \
  --end-date 2025-01-26 \
  --skip-downstream-trigger

# If that fails, may need to create standalone script
# (similar to scripts/regenerate_player_daily_cache.py)
```

**Expected**:
- ML feature store updated with corrected cache values
- Check D failures drop from 70% to <5%

---

### [ ] Task 3: Final Validation
**Priority**: MEDIUM
**Time**: 5 minutes
**Depends on**: Tasks 1 & 2 complete

**Command**:
```bash
# Test specific known failures
python scripts/spot_check_data_accuracy.py --player-lookup mobamba --date 2025-01-20
python scripts/spot_check_data_accuracy.py --player-lookup joshgiddey --date 2025-01-20
python scripts/spot_check_data_accuracy.py --player-lookup justinchampagnie --date 2025-01-08

# Comprehensive validation
python scripts/spot_check_data_accuracy.py \
  --samples 100 \
  --start-date 2024-10-01 \
  --end-date 2025-01-26 \
  > logs/final_validation_$(date +%Y%m%d_%H%M%S).log 2>&1

# Check results
grep "accuracy" logs/final_validation_*.log
```

**Expected**:
- Overall accuracy: >95% (was 30%)
- Sample pass rate: >95% (was 66%)
- Known failures all pass

---

### [ ] Task 4: Project Cleanup
**Priority**: LOW
**Time**: 2 minutes
**Depends on**: Task 3 complete

**Actions**:
1. Move project to completed:
```bash
mv docs/08-projects/current/spot-check-data-quality-fix \
   docs/08-projects/completed/spot-check-data-quality-fix-2026-01-26
```

2. Create completion summary in moved folder

3. Update any references in master project tracker

---

## Quick Reference

**All docs**: `docs/08-projects/current/spot-check-data-quality-fix/`
**Handoff**: `HANDOFF.md` (most detailed)
**Quick start**: `REGENERATION-QUICKSTART.md`
**This file**: `TODO.md`

**Script**: `scripts/regenerate_player_daily_cache.py`
**Logs**: `logs/cache_regeneration_*.log`

---

## Success Criteria

Project complete when:
- ✅ Full season cache regenerated (2024-10-01 to 2025-01-26)
- ✅ ML feature store updated
- ✅ Spot check validation >95% accuracy
- ✅ All known failures pass
- ✅ Project moved to completed folder

---

**Last Updated**: 2026-01-26
**Next Action**: Run Task 1 (full season regeneration)
