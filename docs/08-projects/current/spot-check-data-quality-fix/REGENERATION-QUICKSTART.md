# Data Regeneration Quick Start

**Last Updated**: 2026-01-26
**Purpose**: Quick reference for regenerating data after spot check bug fix

---

## ⚡ Quick Commands

### 1️⃣ Regenerate Recent Data (URGENT - Run First)

```bash
# Last 30 days - most critical for active predictions
cd /home/naji/code/nba-stats-scraper

python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2024-12-27 \
  --end-date 2025-01-26 \
  --backfill-mode
```

**Duration**: 3-5 hours
**Records**: ~13,500

---

### 2️⃣ Validate Recent Data

```bash
# Test specific known failures
python scripts/spot_check_data_accuracy.py --player-lookup mobamba --date 2025-01-20
python scripts/spot_check_data_accuracy.py --player-lookup joshgiddey --date 2025-01-20
python scripts/spot_check_data_accuracy.py --player-lookup justinchampagnie --date 2025-01-08

# Broad validation (should show >95% accuracy now)
python scripts/spot_check_data_accuracy.py \
  --samples 100 \
  --start-date 2025-01-01 \
  --end-date 2025-01-26
```

**Duration**: 10-15 minutes

---

### 3️⃣ Regenerate Full Season (Run After Validation)

```bash
# Entire 2024-25 season
python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2024-10-01 \
  --end-date 2025-01-26 \
  --backfill-mode
```

**Duration**: 12-15 hours
**Records**: ~53,100

---

### 4️⃣ Update ML Feature Store

```bash
# Regenerate ML features (depends on cache)
python backfill_jobs/predictions/ml_feature_store_v2_backfill.py \
  --start-date 2024-10-01 \
  --end-date 2025-01-26 \
  --backfill-mode
```

**Duration**: 8-10 hours

---

### 5️⃣ Final Validation

```bash
# Comprehensive spot check across full range
python scripts/spot_check_data_accuracy.py \
  --samples 200 \
  --start-date 2024-10-01 \
  --end-date 2025-01-26
```

**Duration**: 20-30 minutes

---

## 🔍 Monitoring

### Check Backfill Progress

```bash
# View logs
tail -f logs/player_daily_cache_backfill.log

# Check BigQuery for recent updates
bq query --use_legacy_sql=false "
SELECT
  cache_date,
  COUNT(*) as records,
  MAX(processed_at) as last_processed
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date >= '2024-12-27'
GROUP BY cache_date
ORDER BY cache_date DESC
LIMIT 30
"
```

### Verify Fix Applied

```bash
# Check specific player to see if rolling averages are correct
bq query --use_legacy_sql=false "
SELECT
  cache_date,
  points_avg_last_5,
  points_avg_last_10
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE player_lookup = 'mobamba'
  AND cache_date BETWEEN '2025-01-18' AND '2025-01-21'
ORDER BY cache_date DESC
"

# After fix, should see:
# cache_date = 2025-01-19: points_avg_last_5 = 6.4 (was 4.6 before fix)
```

---

## 📊 Expected Results

### Before Fix
- Mo Bamba (2025-01-19): points_avg_last_5 = 4.6 ❌ (28% error)
- Spot check accuracy: 30%
- Sample pass rate: 66%

### After Fix
- Mo Bamba (2025-01-19): points_avg_last_5 = 6.4 ✅ (0% error)
- Spot check accuracy: >95%
- Sample pass rate: >95%

---

## 🚨 If Issues Occur

### Backfill Fails

```bash
# Check logs
tail -100 logs/player_daily_cache_backfill.log

# Check for dependency issues
python scripts/validate_tonight_data.py --date 2025-01-26
```

### Spot Check Still Fails

```bash
# Verify fix was applied to code
grep -n "game_date <" data_processors/precompute/player_daily_cache/player_daily_cache_processor.py

# Should show:
# 425:            WHERE game_date < '{analysis_date.isoformat()}'
# 454:            WHERE game_date < '{analysis_date.isoformat()}'
```

### Performance Issues

```bash
# Run with smaller batch size
python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2025-01-20 \
  --end-date 2025-01-26 \
  --backfill-mode \
  --batch-size 5  # Process 5 dates at a time instead of all
```

---

## 📝 Notes

- Run Phase 1 (recent data) first - most critical for active predictions
- Validate Phase 1 before starting full season regeneration
- Can run overnight if needed (24-32 hour total runtime)
- Use `--backfill-mode` to skip dependency checks and suppress alerts

---

## ✅ Completion Checklist

- [ ] Phase 1: Regenerate recent data (30 days)
- [ ] Phase 2: Validate recent data (spot checks pass)
- [ ] Phase 3: Regenerate full season (118 days)
- [ ] Phase 4: Update ML feature store
- [ ] Phase 5: Final validation (>95% accuracy)
- [ ] Update project status to COMPLETE
- [ ] Document lessons learned

---

**Contact**: Data Engineering Team
