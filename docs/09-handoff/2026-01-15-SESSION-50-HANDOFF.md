# Session 50 Handoff - Orchestration Optimization & Event-Driven Grading

**Date**: 2026-01-15 (~10:30 AM ET)
**Focus**: Deployed line timing tracking, optimized orchestration schedule, implemented event-driven grading

---

## Executive Summary

Major improvements to pipeline timing:
1. **Line timing tracking** deployed (v3.6) - captures `line_minutes_before_game`
2. **Grading optimized** from 13hr delay → potentially 0-15 min (event-driven)
3. **Predictions optimized** - added 10 AM job when odds are fresh
4. **Documentation** created for orchestration optimization project

---

## Deployments Completed

### 1. Prediction Services (v3.6 - Line Timing)

| Service | Revision | What's New |
|---------|----------|------------|
| prediction-coordinator | 00039-q54 | `line_minutes_before_game` tracking |
| prediction-worker | 00035-4xk | `line_minutes_before_game` storage |

**Line Timing Flow:**
```
odds_api_player_points_props (minutes_before_tipoff)
    → PlayerLoader query
    → Pub/Sub message to worker
    → BigQuery prediction record (line_minutes_before_game)
```

### 2. New Cloud Scheduler Jobs

| Job | Schedule (ET) | Type | Purpose |
|-----|---------------|------|---------|
| `grading-latenight` | 2:30 AM | Pub/Sub | Grade ASAP after games |
| `grading-morning` | 6:30 AM | Pub/Sub | Catch late games |
| `morning-predictions` | 10:00 AM | HTTP | First with real odds |

### 3. Grading Readiness Monitor ✅

**Status**: Deployed and scheduled

**Components**:
- Cloud Function: `grading-readiness-monitor` (deployed)
- Scheduler Job: `grading-readiness-check` (*/15 22-23,0-2 * * * ET)
- URL: `https://grading-readiness-monitor-f7p3g7f6ya-wl.a.run.app`

**What it does**: Polls every 15 min (10 PM - 3 AM ET) to check if all games are complete, triggers grading immediately when ready.

### 4. Staging Table Cleanup ✅

**Status**: Complete (2,929 → 0 tables)

---

## Current Pipeline Schedule

### Grading (3 runs + event-driven)

| Time (ET) | Job | Source |
|-----------|-----|--------|
| ~10-11 PM | readiness-monitor | Event-driven ✨ |
| 2:30 AM | grading-latenight | Scheduled |
| 6:30 AM | grading-morning | Scheduled |
| 11:00 AM | grading-daily | Scheduled (safety net) |

### Predictions (4 runs)

| Time (ET) | Job | Expected Line Source |
|-----------|-----|---------------------|
| 7:00 AM | overnight-predictions | ESTIMATED |
| 10:00 AM | morning-predictions | ODDS_API ✨ |
| 11:30 AM | same-day-predictions | ODDS_API |
| 6:00 PM | same-day-predictions-tomorrow | ODDS_API |

---

## Timing Improvements

### Before (Jan 14)

```
10:05 PM - Games finish, boxscores processed
   ↓
   ... 13 hour wait ...
   ↓
11:00 AM - Grading runs
```

### After (Jan 15+)

```
10:05 PM - Games finish, boxscores processed
10:15 PM - Readiness monitor: "All complete!"
10:20 PM - Grading triggered (event-driven)
   ↓
   ~15 minute delay instead of 13 hours!
```

---

## Verification Needed

### 1. Line Timing Capture (After 11:30 AM ET today)

```sql
-- Check if line_minutes_before_game is captured
SELECT
  line_source_api,
  COUNT(*) as predictions,
  COUNTIF(line_minutes_before_game IS NOT NULL) as with_timing,
  ROUND(AVG(line_minutes_before_game), 0) as avg_timing
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-15'
  AND created_at > '2026-01-15 16:00:00'  -- After 11 AM ET
GROUP BY 1
```

**Expected**: ODDS_API predictions should have `with_timing > 0`

### 2. Grading Readiness Monitor ✅ DEPLOYED

```bash
# Test the readiness monitor
curl -s -X POST https://grading-readiness-monitor-f7p3g7f6ya-wl.a.run.app \
  -H "Content-Type: application/json" \
  -d '{"target_date": "2026-01-14"}' | jq .

# Check scheduler job
gcloud scheduler jobs describe grading-readiness-check --location=us-west2
```

### 3. Tonight's Grading (Jan 14 games)

```sql
-- After 2:30 AM ET tomorrow, check if grading ran
SELECT
  game_date,
  COUNT(*) as graded,
  MIN(graded_at) as first_graded
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-01-14'
GROUP BY 1
```

---

## Files Created/Modified

| File | Action | Purpose |
|------|--------|---------|
| `orchestration/cloud_functions/grading_readiness_monitor/main.py` | Created | Event-driven grading trigger |
| `orchestration/cloud_functions/grading_readiness_monitor/requirements.txt` | Created | Dependencies |
| `docs/08-projects/current/orchestration-optimization/README.md` | Created | Project documentation |
| `scripts/nba/backfill_line_timing.sql` | Created | Line timing backfill query |

---

## Staging Table Cleanup

**Status**: Partially complete (background job ran but may need continuation)

```bash
# Check remaining count
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_predictions.INFORMATION_SCHEMA.TABLES WHERE table_name LIKE '%staging%'"

# Continue cleanup if needed
bq query --use_legacy_sql=false --format=csv --max_rows=500 \
  "SELECT table_name FROM nba_predictions.INFORMATION_SCHEMA.TABLES WHERE table_name LIKE '%staging%' LIMIT 500" \
  | tail -n +2 | xargs -P20 -I{} bq rm -f "nba_predictions.{}"
```

---

## Research Recommendations

### 1. Odds Availability Trigger

**Question**: Can we trigger predictions when odds first appear for today's games?

**Approach**:
- Monitor `odds_api_player_points_props` for today's game_date
- When player count exceeds threshold (e.g., 30), trigger predictions
- Would enable predictions as soon as odds markets open (~8 AM)

**Implementation**: Similar polling pattern to grading readiness monitor

### 2. Line Movement Analysis

**Question**: Do closing lines (captured near game time) perform better than early lines?

**Data available after ~1 week**:
```sql
SELECT
  CASE
    WHEN line_minutes_before_game < 60 THEN 'closing (< 1hr)'
    WHEN line_minutes_before_game < 180 THEN 'afternoon (1-3hr)'
    ELSE 'early (> 3hr)'
  END as timing,
  COUNT(*) as predictions,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as hit_rate
FROM predictions_with_results
WHERE line_minutes_before_game IS NOT NULL
GROUP BY 1
```

### 3. Best Bets Strategy Implementation

**From Session 43-44 findings**, optimal filters:
- System: catboost_v8 only
- Edge: >= 4-5 points
- Direction: UNDER preferred (95% vs 53%)
- Exclude star players (>25 predicted points)

**Action**: Consider creating a "recommended bets" view with these filters

### 4. Phase 4 Precompute Investigation

**Issue**: Only 7% success rate (from Session 48 audit)

**Action**: Investigate failure patterns, may need deployment

---

## Tomorrow's Monitoring Checklist

- [ ] **7:00 AM**: overnight-predictions runs (check logs)
- [ ] **10:00 AM**: morning-predictions runs (new! verify ODDS_API lines)
- [ ] **11:00 AM**: grading-daily runs (should grade Jan 14)
- [ ] **11:30 AM**: same-day-predictions runs (verify line_minutes_before_game captured)

### Commands for Monitoring

```bash
# Check prediction coordinator logs
gcloud logging read 'resource.labels.service_name="prediction-coordinator" AND timestamp>="2026-01-15T12:00:00Z"' --limit=20

# Check grading logs
gcloud logging read 'resource.labels.service_name="phase5b-grading" AND timestamp>="2026-01-15T07:00:00Z"' --limit=20

# Check scheduler job history
gcloud scheduler jobs list --location=us-west2 | grep -E "grading|prediction"
```

---

## Quick Reference

### Verify New Scheduler Jobs

```bash
gcloud scheduler jobs list --location=us-west2 | grep -E "grading-latenight|grading-morning|morning-predictions"
```

### Verify Deployments

```bash
gcloud run revisions list --service=prediction-coordinator --region=us-west2 --limit=2
gcloud run revisions list --service=prediction-worker --region=us-west2 --limit=2
```

### Trigger Manual Grading (if needed)

```bash
gcloud pubsub topics publish nba-grading-trigger \
  --message='{"target_date": "2026-01-14", "trigger_source": "manual", "run_aggregation": true}'
```

---

## Session Stats

| Metric | Value |
|--------|-------|
| Duration | ~3.5 hours |
| Deployments | 3 (coordinator, worker, readiness-monitor) |
| New Scheduler Jobs | 4 (grading-latenight, grading-morning, morning-predictions, grading-readiness-check) |
| Staging Tables Cleaned | 2,929 → 0 |
| Files Created | 5 |
| Documentation | Project readme, handoff |

---

## Summary of Changes

1. **Line Timing** - New field `line_minutes_before_game` enables closing line analysis
2. **Earlier Grading** - 2:30 AM + 6:30 AM jobs reduce delay from 13hr to 1.5-4.5hr
3. **Event-Driven Grading** - Readiness monitor reduces delay to 0-15 minutes
4. **Morning Predictions** - 10 AM job gets fresh odds (vs 11:30 AM before)
5. **Documentation** - New orchestration optimization project docs

---

**Next Session Priority**:
1. ✅ ~~Complete grading readiness monitor deployment~~ (Done)
2. ✅ ~~Create scheduler job for readiness monitor~~ (Done)
3. **Verify line timing capture** - after 11:30 AM predictions, check `line_minutes_before_game` populated
4. **Monitor tonight's grading** - readiness monitor (10 PM - 3 AM), latenight (2:30 AM), morning (6:30 AM)
5. **Check Jan 14 grading** - should complete tonight via new schedule
