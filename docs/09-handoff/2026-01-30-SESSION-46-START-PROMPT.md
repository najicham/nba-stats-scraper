# Session 46 Start Prompt

Copy and paste the text below to start a new Claude Code session:

---

## Context

Session 44-45 discovered and fixed a **critical fatigue_score bug** that was corrupting data since Jan 25. The bug existed in TWO files:

1. `player_composite_factors_processor.py` - fixed in commit `cec08a99`
2. `worker.py` (multiprocessing module) - fixed in commit `c475cb9e`

**The fixes are committed but NOT YET DEPLOYED.**

Pre-write validation was also added to catch future bugs immediately.

Read the full handoff:
```
cat docs/09-handoff/2026-01-30-SESSION-45-FEATURE-QUALITY-HANDOFF.md
```

---

## Priority 1: Deploy and Backfill (REQUIRED)

### 1. Deploy Phase 4 Processor

```bash
./bin/deploy-service.sh nba-phase4-precompute-processors
```

### 2. Run Backfill for Jan 25-30

After deployment succeeds:

```bash
PYTHONPATH=/home/naji/code/nba-stats-scraper python backfill_jobs/precompute/player_composite_factors/backfill.py --start-date 2026-01-25 --end-date 2026-01-30
```

### 3. Verify Fix Worked

```sql
SELECT
  game_date,
  ROUND(AVG(fatigue_score), 2) as avg_fatigue,
  COUNTIF(fatigue_score = 0) as zeros,
  COUNTIF(fatigue_score < 0) as negatives
FROM nba_precompute.player_composite_factors
WHERE game_date >= '2026-01-25'
GROUP BY 1 ORDER BY 1;
```

**Expected:** avg_fatigue ~90-100, zeros ~0, negatives = 0

---

## Priority 2: Investigate Other Broken Features

Session 45 found 6+ features with issues:

| Feature | Issue | Impact |
|---------|-------|--------|
| fatigue_score | 65% zeros since Jan 25 | CRITICAL - fixed |
| team_win_pct | Always 0.5, no variance | MEDIUM |
| back_to_back | Always 0 | MEDIUM |
| usage_spike_score | Always 0 | LOW |
| vegas_points_line | 67-100% zeros Jan 30-31 | HIGH |
| pace_score | 100% zeros some days | MEDIUM |

Check each with:
```sql
-- team_win_pct
SELECT DISTINCT team_win_pct FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE() - 1;

-- back_to_back
SELECT COUNTIF(back_to_back = 1) as b2b_count
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 7;
```

---

## Priority 3: Implement Feature Health Monitoring

Create daily monitoring table:

```sql
CREATE TABLE nba_monitoring.feature_health_daily (
  report_date DATE NOT NULL,
  feature_name STRING NOT NULL,
  mean FLOAT64,
  zero_count INT64,
  negative_count INT64,
  total_count INT64,
  health_status STRING  -- 'healthy', 'warning', 'critical'
);
```

Add to `/validate-daily` skill:
- Feature zero counts
- Mean vs expected baseline
- Out-of-range violations

---

## Key Files

| File | Description |
|------|-------------|
| `docs/09-handoff/2026-01-30-SESSION-45-FEATURE-QUALITY-HANDOFF.md` | Full handoff |
| `docs/08-projects/current/2026-01-30-session-44-maintenance/FEATURE-QUALITY-COMPREHENSIVE-ANALYSIS.md` | Investigation details |
| `data_processors/precompute/player_composite_factors/worker.py` | Fixed worker with validation |

---

## What Was Fixed

**The Bug:**
```python
# BEFORE (broken): Stored adjustment -5 to 0
'fatigue_score': int(factor_scores['fatigue_score'])

# AFTER (fixed): Stores raw score 0-100
'fatigue_score': factor_contexts['fatigue_context_json']['final_score']
```

**Prevention Added:**
```python
FEATURE_RANGES = {
    'fatigue_score': (0, 100),
    'shot_zone_mismatch_score': (-15, 15),
    ...
}

def _validate_feature_ranges(record):
    # Logs CRITICAL errors for out-of-range values
    # Would have caught fatigue bug immediately
```

---

## Quick Validation

```bash
# Check deployment status
gcloud run services describe nba-phase4-precompute-processors --region=us-west2 --format="value(status.latestReadyRevisionName)"

# Check for errors
gcloud logging read 'resource.labels.service_name="nba-phase4-precompute-processors" AND severity>=ERROR' --limit=10

# Run daily validation
/validate-daily
```

---

## Success Criteria

1. ✅ Phase 4 deployed with commits cec08a99 + c475cb9e
2. ✅ fatigue_score values are 0-100 after backfill
3. ✅ Other broken features investigated
4. ✅ Feature health monitoring started

---

## Latest Commits

```
d9c85961 docs: Add comprehensive feature quality analysis and Session 45 handoff
c475cb9e fix: Fix fatigue_score bug in worker.py and add pre-write validation
cec08a99 fix: Restore fatigue_score to use raw 0-100 value instead of adjustment
```

**Focus: Deploy the fix, run backfill, verify data is correct.**
