# QUICK REFERENCE CARD - NBA Backfill + ML Work

**Date**: 2026-01-03 17:21 UTC

---

## STATUS AT-A-GLANCE

**Backfill**: ⏳ 85% complete (finishing in 20 min)
**ML Data**: ✅ READY NOW (315K predictions)
**Next Action**: START ML EVALUATION (don't wait)
**Check Back**: 17:45 UTC (25 minutes)

---

## RUN THIS NOW (5 minutes)

```bash
# Query 1: Which prediction system is best?
bq query --use_legacy_sql=false --format=pretty "
SELECT
  system_id,
  COUNT(*) as total_predictions,
  AVG(absolute_error) as mae,
  AVG(CASE WHEN was_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE game_date >= '2021-11-01' AND game_date < '2024-05-01'
GROUP BY system_id
ORDER BY mae ASC
" > /tmp/ml_eval_q1.txt && cat /tmp/ml_eval_q1.txt
```

**What you'll see**: System IDs ranked by MAE (lowest = best)

---

## AT 17:45 - CHECK THIS

```bash
# Are processes done?
ps aux | grep "player_composite_factors" | grep -v grep

# Did they succeed?
tail -20 /tmp/backfill_execution.log
tail -20 /tmp/processor3_2022_23.log
tail -20 /tmp/processor3_2023_24.log

# How many rows now?
bq query --use_legacy_sql=false "
SELECT COUNT(*) FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
WHERE game_date >= '2021-04-16' AND game_date <= '2024-06-18'
"
```

**Expected**:
- No processes running
- Logs show "success" or "complete"
- Row count: 105,000-110,000 (was 102,533)

---

## CHECKPOINT TIMES

**17:41** - Processes complete (validate row counts)
**18:30** - ML evaluation queries 1-5 done
**19:30** - Full evaluation complete (all 10 queries)
**21:00** - Session complete (documentation done)

---

## DATA AVAILABLE RIGHT NOW

| Dataset | Rows | Coverage | Status |
|---------|------|----------|--------|
| Graded predictions | 315,442 | 2021-2024 | ✅ READY |
| Player features | 102,533 | 2021-2024 | ✅ READY |
| Playoff predictions | 755 | 2022-2024 | ✅ READY |

**YOU CAN START ML EVALUATION NOW!**

---

## KEY DECISIONS

**Q1: Start evaluation now or wait?**
A: START NOW (don't wait for backfill)

**Q2: Full evaluation or skip to training?**
A: FULL EVALUATION (find quick wins first)

**Q3: Which ML model first?**
A: XGBOOST (fast, accurate, proven)

---

## PROCESS STATUS

```
2021-22: 16/45 dates (35%) → 15.5 min remaining
2022-23:  8/45 dates (18%) → 19.7 min remaining
2023-24:  8/47 dates (17%) → 20.8 min remaining

Estimated completion: 17:41 UTC
```

---

## IF SOMETHING GOES WRONG

**Process hangs?**
```bash
pkill -f "player_composite_factors"
# Re-run from last successful date
```

**Query fails?**
- Wait 1 hour (BigQuery quota)
- Add `--max_rows=1000` for testing
- Space out queries more

**Data looks wrong?**
- Check Phase 3 analytics first
- Verify no gaps in playoff dates
- Re-run specific date ranges

---

## SUCCESS CRITERIA

**Phase 4**: 105K+ rows, all playoff dates covered
**Evaluation**: Best system ID + MAE baseline identified
**Training**: New model beats baseline by 3%+ MAE

---

## FULL DOCUMENTATION

**Master TODO**: `/home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-03-MASTER-TODO-NBA-BACKFILL-AND-ML.md`
- 800+ lines, comprehensive roadmap
- All queries, commands, timelines
- Decision trees, risk assessment

**Executive Summary**: `/home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-03-EXECUTIVE-SUMMARY-START-HERE.md`
- Quick start guide
- Next 30 minutes of actions
- Current state snapshot

**This Card**: Quick reference only - read full docs for details!

---

**GO RUN QUERY 1 NOW!** ⚡
