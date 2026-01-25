# Next Steps After Grading Backfill

**Status:** ✅ Grading backfill COMPLETE (98.1% coverage)
**Date:** 2026-01-25

---

## ✅ What's Done

- [x] Grading backfill: 18,983 predictions graded
- [x] System daily performance: 325 records updated
- [x] Coverage improved: 45.9% → 98.1%
- [x] Validation: All predictions passed duplicate checks

---

## 🔴 CRITICAL - Do These Next (Required for Accuracy)

### 1. Phase 6 Exports (~30-60 min)

**Why:** Website showing old metrics based on 45.9% coverage

```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

PYTHONPATH=. python backfill_jobs/publishing/daily_export.py \
  --backfill-all \
  --only results,performance,best-bets
```

**Regenerates:**
- `gs://nba-props-platform-api/v1/results/*.json` - Daily results
- `gs://nba-props-platform-api/v1/systems/*.json` - System rankings
- `gs://nba-props-platform-api/v1/best-bets/*.json` - Top picks

### 2. ML Feedback Adjustments (~15-30 min)

**Why:** Future predictions using biased adjustments (±0.089 MAE regression)

```bash
# TODO: Determine exact command for scoring_tier_processor backfill
# Location: data_processors/ml_feedback/scoring_tier_processor.py
```

**Updates:**
- `scoring_tier_adjustments` table
- Bias corrections by player tier (STAR_30PLUS, STARTER, etc.)

---

## 🟡 OPTIONAL - Do If Time Permits

### 3. BDL Boxscore Gaps (~30 min total)

**Current:** 96.2% coverage
**Target:** >98%

```bash
# 4 high-priority dates (9 missing games)
python bin/backfill/bdl_boxscores.py --date 2026-01-15  # 3 missing
python bin/backfill/bdl_boxscores.py --date 2026-01-14  # 2 missing
python bin/backfill/bdl_boxscores.py --date 2026-01-13  # 2 missing
python bin/backfill/bdl_boxscores.py --date 2026-01-12  # 2 missing
```

### 4. Admin Dashboard Cache (~5 min)

Check if cached, clear if needed:
- `/grading/extended`
- `/grading/weekly`
- `/grading/comparison`

---

## 📊 Quick Verification

```bash
# Check grading coverage
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) as graded FROM nba_predictions.prediction_accuracy
   WHERE game_date >= '2025-11-01'"

# Check exports exist
gsutil ls gs://nba-props-platform-api/v1/results/*.json | wc -l
```

---

## ⚠️ Important Notes

### Nov 4-18 Ungradable Predictions (3,189 total)

**Why ungradable:** All have `current_points_line IS NULL`
**Impact:** None - already filtered from all metrics
**Action:** Accept as-is (incomplete predictions by design)

### Jan 8-18 Gaps

Some dates still show partial grading. Investigate if critical:

```sql
SELECT game_date, COUNT(*) as predictions,
       COUNTIF(current_points_line IS NULL) as missing_lines
FROM nba_predictions.player_prop_predictions
WHERE game_date BETWEEN '2026-01-08' AND '2026-01-18'
GROUP BY game_date
```

---

## 📁 Full Details

See: `/docs/08-projects/current/season-validation-plan/GRADING-BACKFILL-EXECUTION-REPORT.md`

- Complete execution log
- Downstream impact analysis
- Technical details
- Troubleshooting guide

---

## 🎯 Success Criteria

| Item | Status |
|------|--------|
| Grading coverage >80% | ✅ 98.1% |
| System performance updated | ✅ Complete |
| Phase 6 exports regenerated | ✅ Complete (847/847 dates) |
| ML feedback re-run | ✅ Complete (124/216 weekly snapshots) |
| BDL coverage >98% | ⏸️ Optional |

---

**Estimated time to complete critical items:** 45-90 minutes
