# Phase 4 Precompute Backfill Runbook

**Created:** 2025-12-07
**Last Updated:** 2025-12-07
**Purpose:** Step-by-step guide for running Phase 4 (precompute) backfills with expected failure analysis
**Audience:** Engineers running backfills

---

## Quick Reference

```bash
# Run Phase 4 backfill for a date range
./bin/backfill/run_phase4_backfill.sh --start 2021-11-01 --end 2021-11-30

# Validate a single date
python bin/validate_pipeline.py 2021-11-22 --phase 4 --verbose

# Check failure rates
bq query 'SELECT processor_name, failure_category, COUNT(*) FROM nba_processing.precompute_failures WHERE analysis_date BETWEEN "2021-11-01" AND "2021-11-30" GROUP BY 1,2'
```

---

## Phase 4 Processor Chain

Phase 4 processors have strict ordering requirements:

```
┌─────────────────────────────────────────────────────────────┐
│                    PARALLEL PHASE                           │
├─────────────────────────────────────────────────────────────┤
│  #1 TDZA (Team Defense Zone Analysis)                       │
│  #2 PSZA (Player Shot Zone Analysis)     ← Run together     │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   SEQUENTIAL PHASE                          │
├─────────────────────────────────────────────────────────────┤
│  #3 PCF (Player Composite Factors)  ← Depends on #1, #2     │
│                    │                                        │
│                    ▼                                        │
│  #4 PDC (Player Daily Cache)        ← Depends on #1,#2,#3   │
│                    │                                        │
│                    ▼                                        │
│  #5 ML (ML Feature Store)           ← Depends on ALL        │
└─────────────────────────────────────────────────────────────┘
```

### Output Tables

| Processor | Table | Dataset |
|-----------|-------|---------|
| TDZA | `team_defense_zone_analysis` | `nba_precompute` |
| PSZA | `player_shot_zone_analysis` | `nba_precompute` |
| PCF | `player_composite_factors` | `nba_precompute` |
| PDC | `player_daily_cache` | `nba_precompute` |
| ML | `ml_feature_store_v2` | `nba_predictions` |

---

## Expected Failure Rates by Season Week

**IMPORTANT:** Failures are EXPECTED in early season due to minimum game requirements.

### PSZA (Player Shot Zone Analysis)
- **Requirement:** 10 games minimum
- **Failure reason:** `INSUFFICIENT_DATA`

| Season Week | Days Since Start | Expected Failure Rate | Example |
|-------------|------------------|----------------------|---------|
| 1-2 | 0-14 | **90-100%** | Nov 1-4 (2021-22 started Oct 19) |
| 3 | 15-21 | **60-75%** | Nov 5-11 |
| 4 | 22-28 | **40-50%** | Nov 12-18 |
| 5 | 29-35 | **30-40%** | Nov 19-25 |
| 6+ | 36+ | **25-30%** | Nov 26+ (baseline) |
| Mid-season | 60+ | **15-20%** | Dec/Jan+ |

### PDC (Player Daily Cache)
- **Requirement:** 5 games minimum + PSZA data
- **Failure reasons:**
  - `INSUFFICIENT_DATA` - Player has < 5 games
  - `MISSING_DEPENDENCY` - No PSZA data available (cascades from PSZA)

---

## Backfill Mode Optimizations

### What's Skipped in Backfill Mode

| Check | Normal Mode | Backfill Mode | Reason |
|-------|------------|---------------|--------|
| Defensive checks | ✅ Run | ⏭️ Skipped | No need to verify upstream processor status for historical data |
| Dependency freshness | ✅ Run (103s) | ⏭️ Skipped (~0s) | Historical data won't change |
| Completeness check | ✅ Run | ⏭️ Skipped | Trust the data exists |
| Downstream trigger | ✅ Publish | ⏭️ Skipped | Avoid triggering Phase 5 during backfill |

### How to Enable Backfill Mode

The backfill scripts automatically enable backfill mode:

```python
# In processor options
opts = {
    'analysis_date': date(2021, 11, 22),
    'backfill_mode': True,           # Key flag
    'skip_downstream_trigger': True,  # Don't trigger Phase 5
}
```

---

## Step-by-Step Backfill Process

### 1. Pre-Flight Check

```bash
# Verify Phase 3 data exists for target dates
python bin/backfill/preflight_check.py 2021-11-01 --end-date 2021-11-30

# Check what Phase 4 data already exists
bq query --use_legacy_sql=false '
SELECT
  DATE(analysis_date) as dt,
  COUNT(*) as records
FROM nba_precompute.player_shot_zone_analysis
WHERE DATE(analysis_date) BETWEEN "2021-11-01" AND "2021-11-30"
GROUP BY 1
ORDER BY 1'
```

### 2. Run Phase 4 Backfill

```bash
# Run all Phase 4 processors in correct order
./bin/backfill/run_phase4_backfill.sh \
  --start 2021-11-01 \
  --end 2021-11-30 \
  --skip-preflight  # Optional: skip if you already ran preflight
```

### 3. Monitor Progress

```bash
# Watch the backfill progress
tail -f /tmp/backfill_checkpoints/*.json

# Or run individual processor backfills with verbose output
.venv/bin/python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --start-date 2021-11-01 \
  --end-date 2021-11-30 \
  --skip-preflight
```

### 4. Validate Completion

```bash
# Validate all Phase 4 tables for a date
python bin/validate_pipeline.py 2021-11-22 --phase 4 --verbose

# Check record counts per date
bq query --use_legacy_sql=false '
SELECT
  DATE(analysis_date) as dt,
  "PSZA" as processor,
  COUNT(*) as records
FROM nba_precompute.player_shot_zone_analysis
WHERE DATE(analysis_date) BETWEEN "2021-11-01" AND "2021-11-30"
GROUP BY 1, 2
UNION ALL
SELECT
  DATE(analysis_date) as dt,
  "PCF" as processor,
  COUNT(*) as records
FROM nba_precompute.player_composite_factors
WHERE DATE(analysis_date) BETWEEN "2021-11-01" AND "2021-11-30"
GROUP BY 1, 2
ORDER BY 1, 2'
```

### 5. Analyze Failures

```bash
# Check failure breakdown
bq query --use_legacy_sql=false '
SELECT
  processor_name,
  failure_category,
  COUNT(*) as count,
  COUNTIF(can_retry) as retryable
FROM nba_processing.precompute_failures
WHERE analysis_date BETWEEN "2021-11-01" AND "2021-11-30"
GROUP BY 1, 2
ORDER BY 1, 2'
```

---

## Failure Triage

### When to Investigate vs Ignore

| Failure Category | Expected? | Action |
|------------------|-----------|--------|
| `INSUFFICIENT_DATA` (early season) | ✅ Yes | **Ignore** - Business logic requirement |
| `INSUFFICIENT_DATA` (mid-season) | ⚠️ Maybe | **Investigate** if rate > 20% |
| `MISSING_DEPENDENCY` | ✅ Yes (cascade) | **Check upstream** - Did PSZA/PCF fail? |
| `PROCESSING_ERROR` | ❌ No | **Investigate immediately** - Code bug |
| `UNKNOWN` | ❌ No | **Investigate** - Unexpected failure |

### Failure Rate Validation

Compare actual failure rates to expected:

```sql
-- Calculate failure rate by date
WITH failures AS (
  SELECT
    DATE(analysis_date) as dt,
    COUNT(DISTINCT entity_id) as failed_players
  FROM nba_processing.precompute_failures
  WHERE processor_name = 'PlayerShotZoneAnalysisProcessor'
    AND analysis_date BETWEEN '2021-11-01' AND '2021-11-30'
  GROUP BY 1
),
successes AS (
  SELECT
    DATE(analysis_date) as dt,
    COUNT(*) as successful_records
  FROM nba_precompute.player_shot_zone_analysis
  WHERE DATE(analysis_date) BETWEEN '2021-11-01' AND '2021-11-30'
  GROUP BY 1
)
SELECT
  f.dt,
  f.failed_players,
  s.successful_records,
  ROUND(f.failed_players * 100.0 / (f.failed_players + s.successful_records), 1) as failure_pct
FROM failures f
JOIN successes s ON f.dt = s.dt
ORDER BY f.dt;
```

**Red Flags to Investigate:**
- Failure rate > 30% after week 6 of season
- `PROCESSING_ERROR` failures (any count)
- Sudden increase in failure rate vs previous dates

---

## Common Issues & Solutions

### Issue: "Bootstrap period - skipping"

**Symptom:** First few dates are skipped entirely
**Cause:** First 14 days of season have special handling
**Solution:** This is expected behavior. Season needs 2 weeks of games before Phase 4 can produce meaningful output.

### Issue: High failure rate on specific date

**Symptom:** One date has 80%+ failure rate while others are normal
**Cause:** Likely missing Phase 3 data for that date
**Solution:**
```bash
# Check Phase 3 exists for the date
python bin/validate_pipeline.py 2021-11-XX --phase 3 --verbose

# If missing, run Phase 3 backfill first
```

### Issue: "MISSING_DEPENDENCY" cascade

**Symptom:** PDC and ML have high MISSING_DEPENDENCY failures
**Cause:** Upstream PSZA failed for those players
**Solution:** Check PSZA first. If PSZA succeeded, the dependency cascade is expected.

### Issue: Backfill running slowly

**Symptom:** Each date takes >5 minutes
**Cause:** Dependency check not skipped (backfill_mode not set)
**Solution:** Ensure `--skip-preflight` is used and scripts pass `backfill_mode=True`

---

## Validation Queries

### Quick Status Check

```sql
-- All Phase 4 tables status for a month
SELECT
  'TDZA' as proc, MIN(DATE(analysis_date)) as min_dt, MAX(DATE(analysis_date)) as max_dt, COUNT(DISTINCT DATE(analysis_date)) as dates
FROM nba_precompute.team_defense_zone_analysis WHERE DATE(analysis_date) BETWEEN '2021-11-01' AND '2021-11-30'
UNION ALL
SELECT 'PSZA', MIN(DATE(analysis_date)), MAX(DATE(analysis_date)), COUNT(DISTINCT DATE(analysis_date))
FROM nba_precompute.player_shot_zone_analysis WHERE DATE(analysis_date) BETWEEN '2021-11-01' AND '2021-11-30'
UNION ALL
SELECT 'PCF', MIN(DATE(analysis_date)), MAX(DATE(analysis_date)), COUNT(DISTINCT DATE(analysis_date))
FROM nba_precompute.player_composite_factors WHERE DATE(analysis_date) BETWEEN '2021-11-01' AND '2021-11-30'
UNION ALL
SELECT 'PDC', MIN(DATE(cache_date)), MAX(DATE(cache_date)), COUNT(DISTINCT DATE(cache_date))
FROM nba_precompute.player_daily_cache WHERE DATE(cache_date) BETWEEN '2021-11-01' AND '2021-11-30'
UNION ALL
SELECT 'ML', MIN(DATE(game_date)), MAX(DATE(game_date)), COUNT(DISTINCT DATE(game_date))
FROM nba_predictions.ml_feature_store_v2 WHERE DATE(game_date) BETWEEN '2021-11-01' AND '2021-11-30';
```

### Retryable Failures

```sql
-- Find retryable failures
SELECT
  processor_name,
  failure_category,
  COUNT(*) as count
FROM nba_processing.precompute_failures
WHERE analysis_date BETWEEN '2021-11-01' AND '2021-11-30'
  AND can_retry = true
  AND failure_category NOT IN ('INSUFFICIENT_DATA')  -- Skip expected failures
GROUP BY 1, 2;
```

---

## Useful Commands Reference

```bash
# Run single processor for single date
.venv/bin/python -c "
from datetime import date
from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import PlayerShotZoneAnalysisProcessor
p = PlayerShotZoneAnalysisProcessor()
p.run({'analysis_date': date(2021, 11, 22), 'backfill_mode': True, 'skip_downstream_trigger': True})
"

# Run backfill with specific date range
.venv/bin/python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --start-date 2021-11-01 \
  --end-date 2021-11-30 \
  --skip-preflight

# Check run history for a processor
bq query 'SELECT processor_name, status, records_created, duration_seconds FROM nba_reference.processor_run_history WHERE data_date = "2021-11-22" AND phase = "phase_4_precompute" ORDER BY started_at DESC LIMIT 10'
```

---

## Related Documentation

- **General Backfill Guide:** `../../../backfill-guide.md`
- **Cross-Date Dependencies:** `../../../01-architecture/cross-date-dependencies.md`
- **Completeness Validation:** `../../../monitoring/05-data-completeness-validation.md`
- **Phase 4 Processor READMEs:** `data_processors/precompute/*/README.md`

---

**Document Status:** Current and maintained
**Next Review:** After next full-season backfill
