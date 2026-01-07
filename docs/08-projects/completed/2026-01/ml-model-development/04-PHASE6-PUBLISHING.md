# Phase 6: Publishing & Exports

**Updated**: 2026-01-02
**Status**: ⚪ NOT RUN YET
**Priority**: LOW (doesn't block ML work)
**Purpose**: Export graded predictions to JSON/GCS for website consumption

---

## 🎯 What is Phase 6?

**Phase 6 = Publishing** = Making prediction data available to the frontend/website

**What it does**:
1. Reads graded predictions from `nba_predictions.prediction_accuracy`
2. Formats as JSON
3. Exports to GCS bucket
4. Makes available for website to display

**What it does NOT do**:
- ❌ Generate new predictions
- ❌ Grade predictions (that's Phase 5B)
- ❌ Create ML models
- ❌ Affect data in BigQuery

---

## 📊 Current State

### What Exists ✅

- **Input data**: `nba_predictions.prediction_accuracy` (328k records)
- **Export code**: `backfill_jobs/publishing/daily_export.py`
- **Live pipeline**: `data_processors/publishing/` (for current season)

### What Doesn't Exist ⚪

- **Historical exports**: JSON files for 2021-2024 seasons
- **GCS bucket**: No "exports/" or "predictions/" folder found
- **Published data**: Website likely not showing historical predictions

---

## 🔧 What Needs to Run

### Backfill Script

**Located**: `backfill_jobs/publishing/daily_export.py`

**What it does**:
1. Query `prediction_accuracy` for date range
2. Format as JSON (one file per day)
3. Upload to GCS
4. Optionally: Export player profiles

**Example Usage** (from EXECUTION-PLAN.md):
```bash
# Export all historical data
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py --backfill-all

# Or by season:
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --start-date 2021-11-01 --end-date 2022-04-10

PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --start-date 2022-10-19 --end-date 2023-04-09

PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --start-date 2023-10-25 --end-date 2024-04-14

# Export player profiles
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py --players --min-games 5
```

**Estimated Time**: 30 minutes - 1 hour

---

## 📁 Expected Output

### GCS Structure

**Likely destination**: `gs://nba-scraped-data/exports/` or similar

**Format**:
```
exports/
├── predictions/
│   ├── 2021-11-06.json
│   ├── 2021-11-07.json
│   ├── ...
│   ├── 2024-04-14.json
│   └── 2026-01-01.json
├── player-profiles/
│   ├── lebron-james.json
│   ├── stephen-curry.json
│   └── ...
└── system-performance/
    ├── 2021-22-summary.json
    ├── 2022-23-summary.json
    └── 2023-24-summary.json
```

### JSON Format

**Daily predictions file**:
```json
{
  "date": "2022-01-15",
  "games": [
    {
      "game_id": "20220115_LALBOS",
      "predictions": [
        {
          "player": "lebron-james",
          "predicted_points": 28.5,
          "actual_points": 31.0,
          "error": 2.5,
          "recommendation": "OVER",
          "line": 26.5,
          "was_correct": true,
          "system": "system_a",
          "confidence": 0.72
        },
        // ...
      ]
    }
  ]
}
```

---

## ❓ Do We Need to Run This?

### For ML Work: ❌ NO

**Why not?**
- ML code queries BigQuery directly
- Don't need JSON exports
- BigQuery has more flexibility for analysis

**Bottom line**: Phase 6 doesn't help ML at all

### For Website: ✅ YES

**Why yes?**
- Frontend can't query BigQuery directly (usually)
- Needs pre-formatted JSON files
- GCS hosting for static files
- Faster page loads

**Bottom line**: Only run Phase 6 if you're building a website that displays historical predictions

---

## 🎯 Decision Framework

### Run Phase 6 If:

✅ You have a website/frontend that displays predictions
✅ You want users to browse historical predictions
✅ You need public-facing prediction data
✅ You want to show system performance over time

### Skip Phase 6 If:

❌ Only doing ML/data science work
❌ Only using internal tools/dashboards
❌ No public website planned
❌ Can query BigQuery directly

---

## 🚀 When to Run Phase 6

### Option 1: Run Now (Low Priority)

**Pros**:
- Gets it done
- Historical data available for website
- Only 30-60 minutes

**Cons**:
- Doesn't help ML work
- May not be needed yet
- Can run anytime

### Option 2: Defer Until Website Ready (Recommended)

**Pros**:
- Focus on ML first
- Only run when actually needed
- Website requirements may change

**Cons**:
- Will need to remember to run it
- Small delay when website is ready

**Recommendation**: **DEFER** - Focus on ML work first

---

## 📋 If You Decide to Run It

### Pre-Flight Checklist

- [ ] Determine GCS bucket/path for exports
- [ ] Verify export script runs without errors
- [ ] Test with small date range first
- [ ] Confirm JSON format matches frontend needs
- [ ] Check file sizes (may be large)

### Execution Steps

1. **Test Run** (1 day):
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --start-date 2022-01-15 --end-date 2022-01-15 \
  --dry-run
```

2. **Small Batch** (1 week):
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --start-date 2022-01-15 --end-date 2022-01-21
```

3. **Full Season** (after validation):
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
  --start-date 2021-11-01 --end-date 2022-04-15
```

4. **Repeat for all seasons**

### Validation

```bash
# Check files created
gsutil ls gs://nba-scraped-data/exports/predictions/ | wc -l
# Should see ~403 files (one per date)

# Check file size
gsutil du -sh gs://nba-scraped-data/exports/predictions/

# Sample a file
gsutil cat gs://nba-scraped-data/exports/predictions/2022-01-15.json | head -50
```

---

## 📊 Terminology Clarification

### Is Phase 6 a "Backfill"?

**Technically**: It's **historical processing** (running a new export process on old data)

**Commonly called**: "Backfill" (close enough)

**More accurate**: "Historical export" or "batch export"

**Does it matter?** No - it's clear what needs to be done regardless of terminology.

---

## 🎯 Summary

**What**: Export graded predictions to JSON/GCS for website
**Status**: Not run yet
**Blocks ML?**: NO
**Blocks website?**: YES
**Effort**: 30-60 minutes
**Priority**: LOW (defer until needed)

**Recommendation**:
- Focus on ML work first (Phase 5B data already exists!)
- Run Phase 6 only when website/frontend is ready
- Can be done anytime - not urgent

---

## 🔗 Related Documents

- `00-OVERVIEW.md` - Project overview
- `01-DATA-INVENTORY.md` - What data exists
- `02-EVALUATION-PLAN.md` - How to use grading data for ML
- `../four-season-backfill/EXECUTION-PLAN.md` - Original Phase 6 plan

---

**Next Steps**:
1. Skip Phase 6 for now
2. Focus on ML evaluation and training
3. Come back to Phase 6 when website needs it
