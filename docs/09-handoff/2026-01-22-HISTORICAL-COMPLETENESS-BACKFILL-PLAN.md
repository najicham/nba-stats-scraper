# Historical Completeness Backfill Plan

**Date:** January 22, 2026
**Status:** Ready to Execute
**Purpose:** Populate `historical_completeness` for all historical feature records

---

## Current State

| Metric | Value |
|--------|-------|
| Data range | Nov 6, 2024 → Jan 22, 2026 |
| Total game days | 276 |
| Total records | 43,790 |
| Records WITH `historical_completeness` | 156 (0.4%) |
| Records NEEDING backfill | 43,634 (99.6%) |

---

## What the Backfill Does

Re-running the `ml_feature_store_processor` will:
1. **Populate `historical_completeness`** for all records
2. **Update feature values** if source data has changed
3. **NOT break anything** - uses idempotent MERGE operations

The backfill is **safe** because:
- All processors use Smart Idempotency (detects unchanged data)
- MERGE operations handle upserts cleanly
- `backfill_mode=True` skips unnecessary checks

---

## Pre-Backfill Validation

**Completed:**
- [x] Spot check tool validates calculations are correct (180 checks, 0 failures)
- [x] Schema migration deployed
- [x] Monitoring views created
- [x] CLI tool (check_cascade.py) working

---

## Backfill Options

### Option 1: Full Season Backfill (Recommended)

**Scope:** Oct 22, 2024 → Jan 22, 2026 (~93 days of games)
**Time Estimate:** 2-4 hours
**Benefit:** Complete visibility into data quality for entire season

```bash
# Run Phase 4 backfill for entire 2024-25 season
./bin/backfill/run_year_phase4.sh --start-date=2024-10-22 --end-date=2026-01-22
```

### Option 2: Recent Data Only

**Scope:** Jan 1, 2026 → Jan 22, 2026 (22 days)
**Time Estimate:** 15-30 minutes
**Benefit:** Quick validation of new feature

```bash
# Run just for January 2026
./bin/backfill/run_year_phase4.sh --start-date=2026-01-01 --end-date=2026-01-22
```

### Option 3: No Backfill (Forward Only)

**Scope:** None
**Benefit:** Zero effort
**Downside:** Historical data has no completeness tracking

---

## Recommended Approach

**Step 1: Run Recent Backfill First (Validation)**
```bash
# Backfill just January to validate the process
./bin/backfill/run_year_phase4.sh --start-date=2026-01-01 --end-date=2026-01-22
```

**Step 2: Verify Results**
```bash
# Check completeness summary
python bin/check_cascade.py --summary --days 30

# Spot check random players
python bin/spot_check_features.py --count 20

# Check for any incomplete records
python bin/check_cascade.py --incomplete --start 2026-01-01 --end 2026-01-22
```

**Step 3: Run Full Season Backfill**
```bash
# Backfill from season start
./bin/backfill/run_year_phase4.sh --start-date=2024-10-22 --end-date=2025-12-31
```

**Step 4: Final Verification**
```bash
# Verify all data has completeness
python bin/check_cascade.py --summary --days 100

# Check for any data gaps
python bin/check_cascade.py --incomplete --start 2024-10-22 --end 2026-01-22
```

---

## Backfill Mode Behavior

When `backfill_mode=True`:
- **Completeness checks SKIPPED** - Won't block on missing upstream
- **Defensive checks SKIPPED** - No upstream processor validation
- **Alerts suppressed** - Only critical alerts sent
- **Historical dates allowed** - Can process >90 days old

This is **correct** for backfills - we want to process everything and check completeness afterward.

---

## Monitoring During Backfill

**Track progress:**
```bash
# Check how many records have been updated
bq query --use_legacy_sql=false "
SELECT
    DATE(game_date) as game_date,
    COUNT(*) as total,
    COUNTIF(historical_completeness IS NOT NULL) as with_completeness
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2024-10-22'
GROUP BY 1
ORDER BY 1 DESC
LIMIT 20
"
```

**Watch for errors:**
```bash
# Check processor logs
kubectl logs -l app=ml-feature-store-processor --tail=100
```

---

## Post-Backfill Validation

After backfill completes:

1. **Check all records have completeness:**
```bash
python bin/check_cascade.py --summary --days 100
```

2. **Spot check random players:**
```bash
python bin/spot_check_features.py --count 50
```

3. **Look for any data gaps:**
```bash
python bin/check_cascade.py --incomplete --start 2024-10-22 --end 2026-01-22
```

4. **Verify monitoring views:**
```sql
SELECT * FROM nba_predictions.v_historical_completeness_daily
ORDER BY game_date DESC
LIMIT 30;
```

---

## Rollback (If Needed)

The backfill only ADDS the `historical_completeness` field. If something goes wrong:

1. The field can be set to NULL without affecting predictions
2. All other feature data remains unchanged
3. Re-run the backfill to fix any issues

---

## Next Steps After Backfill

1. **Daily monitoring:** Use `v_historical_completeness_daily` view
2. **Cascade detection:** Use `check_cascade.py` after any backfills
3. **Spot checks:** Periodically run spot checks on new data

---

**Document Created:** January 22, 2026
**Estimated Backfill Time:** 2-4 hours for full season
