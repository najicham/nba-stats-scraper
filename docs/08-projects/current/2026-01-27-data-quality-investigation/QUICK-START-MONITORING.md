# Quick Start: Monitoring Reprocessing

**Last Updated**: 2026-01-27 16:20 PST
**Status**: AWAITING REPROCESSING

---

## 🚀 Quick Start (Choose One)

### Option 1: Automated Monitoring (Recommended)
```bash
bash docs/08-projects/current/2026-01-27-data-quality-investigation/monitor-reprocessing.sh
```
This will check every 60 seconds and alert you when targets are reached.

### Option 2: Manual Single Check
```bash
# Check usage_rate for Jan 26
bq query --use_legacy_sql=false "
SELECT ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL AND usage_rate <= 50) / COUNT(*), 1) as usage_pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2026-01-26'"

# Check predictions for Jan 27
bq query --use_legacy_sql=false "
SELECT COUNT(*) as prediction_count
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2026-01-27' AND is_active = TRUE"
```

### Option 3: Manual Trigger (If Automatic Doesn't Start)
```bash
# Reprocess Jan 26
python scripts/backfill_player_game_summary.py \
  --start-date 2026-01-26 \
  --end-date 2026-01-26 \
  --force

# Regenerate cache for Jan 27
python scripts/regenerate_player_daily_cache.py \
  --start-date 2026-01-26 \
  --end-date 2026-01-27
```

---

## 🎯 Success Targets

| Metric | Current (Baseline) | Target | Status |
|--------|-------------------|--------|--------|
| Jan 26 usage_rate | 57.8% | 90%+ | ⏳ |
| Jan 27 predictions | 0 | 80+ | ⏳ |
| Jan 27 betting lines | 37 | 80+ | ⏳ |

---

## ✅ When Reprocessing Completes

Run full validation:
```bash
# Historical validation
/validate-historical 2026-01-26 2026-01-27

# Spot checks
python scripts/spot_check_data_accuracy.py \
  --start-date 2026-01-26 \
  --end-date 2026-01-27 \
  --samples 10 \
  --checks rolling_avg,usage_rate
```

Update VALIDATION-REPORT.md with final results.

---

## 📚 Full Documentation

- **VALIDATION-REPORT.md**: Comprehensive validation report with all metrics
- **VALIDATION-SESSION-SUMMARY.md**: Detailed session summary and next steps
- **monitor-reprocessing.sh**: Automated monitoring script

---

## ⚠️ If Something Goes Wrong

1. Check Cloud Functions logs for errors
2. Verify code deployment status
3. Check team stats availability for Jan 26
4. Review data_quality_flag values
5. Consider re-running fixes manually
