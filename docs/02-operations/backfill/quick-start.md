# Backfill Quick Start

**Purpose:** Run your first backfill in 10 minutes
**Audience:** Engineers new to the backfill process

---

## The Approach: Test Small, Validate, Iterate

1. **Start with 1 date** - Not a range, just one
2. **Run preflight checks** - Make sure upstream data exists
3. **Execute the backfill** - Run the processor
4. **Validate the output** - Check it worked correctly
5. **Check for errors** - Look at error tables
6. **Then scale up** - Only after small test passes

---

## Step 1: Pick a Date

Choose a date with data (mid-season is safest):

```bash
# Check what dates have Phase 3 data ready
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as records
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN "2021-12-01" AND "2021-12-15"
GROUP BY 1 ORDER BY 1'
```

Pick a date that has records (e.g., `2021-12-10`).

---

## Step 2: Run Pre-Flight Check

```bash
cd /home/naji/code/nba-stats-scraper

# Check upstream data exists for your date
.venv/bin/python bin/backfill/preflight_check.py \
    --start-date 2021-12-10 --end-date 2021-12-10 --verbose
```

**Expected:** All green checkmarks. If red X's, fix upstream data first.

---

## Step 3: Run the Backfill (Single Date)

Example: Run Player Composite Factors (PCF) for one date:

```bash
.venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-12-10 --end-date 2021-12-10
```

**Expected time:** ~50-60 seconds for one date.

---

## Step 4: Validate It Worked

```bash
# Check records were created
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as records,
       COUNTIF(is_production_ready) as prod_ready
FROM nba_precompute.player_composite_factors
WHERE game_date = "2021-12-10"
GROUP BY 1'

# Check for cascade contamination (critical fields have valid values)
.venv/bin/python scripts/validate_cascade_contamination.py \
    --start-date 2021-12-10 --end-date 2021-12-10
```

**Expected:**
- Records > 0 (typically 200-400 per date)
- `prod_ready` > 0
- No cascade contamination warnings

---

## Step 5: Check Error Tables

```bash
# Check processor run history
bq query --use_legacy_sql=false '
SELECT processor_name, data_date, status,
       SUBSTR(error_message, 1, 100) as error
FROM nba_reference.processor_run_history
WHERE data_date = "2021-12-10"
  AND processor_name LIKE "%composite%"
ORDER BY started_at DESC'

# Check name registry errors (if relevant)
bq query --use_legacy_sql=false '
SELECT * FROM nba_reference.registry_errors
WHERE created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
LIMIT 10'
```

**Expected:** `status = "success"`, no recent registry errors.

---

## Step 6: Scale Up (If Step 4-5 Pass)

Only after validating single date:

```bash
# Try a small range (3 dates)
.venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
    --start-date 2021-12-10 --end-date 2021-12-12

# Validate the range
.venv/bin/python scripts/validate_backfill_coverage.py \
    --start-date 2021-12-10 --end-date 2021-12-12 --details
```

---

## Common Issues

| Issue | Symptom | Solution |
|-------|---------|----------|
| No upstream data | Preflight shows red X | Run Phase 3 first |
| Early season | High failure rate | Expected - bootstrap period |
| Cascade contamination | `opponent_strength_score = 0` | Fix TDZA, reprocess |
| Slow performance | >2 min per date | Check `backfill_mode=True` |

---

## Phase 4 Processor Order

If running multiple Phase 4 processors, run in this order:

```
1. TDZA + PSZA (can run parallel)
2. PCF (needs TDZA)
3. PDC (needs PSZA, PCF)
4. MLFS (needs all above)
```

---

## Next Steps

- [README.md](./README.md) - Full documentation hub
- [backfill-guide.md](./backfill-guide.md) - Comprehensive procedures
- [data-integrity-guide.md](./data-integrity-guide.md) - Gap prevention

---

**Created:** 2025-12-08
