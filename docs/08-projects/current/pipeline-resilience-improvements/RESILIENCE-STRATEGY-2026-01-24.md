# Pipeline Resilience Strategy

**Created:** 2026-01-24
**Status:** Implementation in progress
**Problem:** Data gaps went undetected for weeks, causing cascade failures and degraded predictions

---

## Root Cause Analysis

### What Happened
1. **Analytics pipeline gaps** - Only 1 game/day processed for many dates (Oct-Jan)
2. **Feature quality degraded** - avg_quality dropped from 85-93 to 71-78
3. **Prediction hit rate collapsed** - From 72-84% to 54.6% in January
4. **No one noticed** - Gaps accumulated for weeks before discovery

### Why It Wasn't Detected
1. **No daily completeness alerts** - No automated check for data gaps
2. **Game ID format mismatch** - Tables use different ID formats, making joins fail
3. **Pipeline continued silently** - Predictions made with incomplete data
4. **Grading looked "complete"** - 100% of graded predictions graded, but only a subset were graded

### The Cascade Effect
```
BDL Box Scores (Phase 2)
    ↓ gaps
Analytics (Phase 3) - player_game_summary
    ↓ gaps
Feature Store (Phase 4) - ml_feature_store_v2 (lower quality scores)
    ↓ degraded features
Predictions (Phase 5) - lower accuracy
    ↓
Grading (Phase 5B) - incomplete grading
```

---

## Resilience Strategy: Three Layers

### Layer 1: VISIBILITY (Detect gaps within 24 hours)

**Implementation:** `bin/validation/daily_data_completeness.py` ✅ DONE

```bash
# Run daily at 6 AM ET via Cloud Scheduler
python bin/validation/daily_data_completeness.py --days 7 --alert
```

**Checks:**
- BDL box score coverage (games with data vs scheduled)
- Analytics coverage (player_game_summary completeness)
- Feature quality scores (ml_feature_store_v2 avg quality)
- Grading coverage (predictions graded vs made)

**Alerts if:**
- Any phase < 90% coverage for yesterday
- Feature quality < 80 avg
- Grading backlog > 2 days

**Implementation needed:**
- [ ] Add Cloud Scheduler job for daily run
- [ ] Add feature quality check to script
- [ ] Add grading backlog check

### Layer 2: PREVENTION (Stop bad predictions)

**Implementation:** Prediction gating in `predictions/coordinator/coordinator.py` ✅ DONE

```python
# Returns 503 if analytics coverage < 80% for lookback period
if not completeness_result['is_complete']:
    return jsonify({
        'status': 'error',
        'error': 'DATA_INCOMPLETE',
        'message': f"Cannot make predictions - historical data is incomplete."
    }), 503
```

**Blocks predictions when:**
- Analytics coverage < 80% for last 7 days
- Can override with `skip_completeness_check=true` for emergencies

### Layer 3: SELF-HEALING (Auto-fix transient errors)

**Implementation:**
- Auto-retry queue in `scrapers/scraper_base.py` ✅ DONE
- `auto_retry_processor` Cloud Function ✅ DEPLOYED
- BDL catchup workflow in `master_controller.py` ✅ DONE

**Flow:**
```
Scraper fails → log_processor_error() → failed_processor_queue
    ↓
auto_retry_processor (every 15 min) → republish to Pub/Sub
    ↓
Scraper retries (up to 3 times with exponential backoff)
    ↓
If still fails → Slack alert for manual intervention
```

---

## Implementation Checklist

### Completed Tonight
- [x] Sync Cloud Function utilities
- [x] Implement BDL catchup workflow
- [x] Integrate pipeline_logger into ScraperBase
- [x] Create daily_data_completeness.py script
- [x] Add prediction gating
- [x] Backfill analytics (player_game_summary)
- [x] Start feature store backfill

### Still Needed
- [ ] Cloud Scheduler job for daily completeness check
- [ ] Grading backfill for January
- [ ] Feature quality monitoring in completeness script
- [ ] Deploy updated ScraperBase
- [ ] Unified monitoring dashboard

---

## Monitoring Queries

### Daily Health Check (run at 6 AM ET)
```sql
-- Quick health summary
SELECT
  'BDL' as phase,
  ROUND(SUM(CASE WHEN bdl_ok THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as pct_ok
FROM (
  SELECT
    s.game_date,
    COUNT(DISTINCT s.game_id) <= COUNT(DISTINCT b.game_date) as bdl_ok
  FROM nba_raw.v_nbac_schedule_latest s
  LEFT JOIN (SELECT DISTINCT game_date FROM nba_raw.bdl_player_boxscores WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)) b
    ON s.game_date = b.game_date
  WHERE s.game_status = 3
    AND s.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND s.game_date < CURRENT_DATE()
  GROUP BY s.game_date
)
```

### Feature Quality Trend
```sql
SELECT
  game_date,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  COUNT(*) as features
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY game_date
ORDER BY game_date DESC
```

### Grading Backlog
```sql
SELECT
  p.game_date,
  COUNT(*) as predictions,
  COUNTIF(pa.game_date IS NOT NULL) as graded,
  COUNT(*) - COUNTIF(pa.game_date IS NOT NULL) as backlog
FROM nba_predictions.player_prop_predictions p
LEFT JOIN nba_predictions.prediction_accuracy pa
  ON p.prediction_id = pa.prediction_id
WHERE p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND p.system_id = 'catboost_v8'
GROUP BY p.game_date
ORDER BY p.game_date DESC
```

---

## Key Insight: Game ID Format Mismatch

**Critical finding:** Tables use different game_id formats making joins unreliable:
- `v_nbac_schedule_latest`: `0022500228` (NBA official)
- `bdl_player_boxscores`: `20251115_OKC_CHA` (date_team)
- `player_game_summary`: Mix of formats

**Solution:** Use game_date-based counts for completeness checks, not game_id joins.

---

## Success Metrics

After implementing this strategy:
1. **Detection time:** Data gaps detected within 24 hours (vs weeks before)
2. **Prediction quality:** Predictions blocked when data < 80% complete
3. **Auto-recovery:** Transient scraper failures retried automatically
4. **Manual intervention:** Permanent failures alerted for human review

---

## Next Steps

1. **Tonight:**
   - Complete feature store backfill (running)
   - Run grading backfill
   - Verify hit rates improve with complete data

2. **Tomorrow:**
   - Deploy updated ScraperBase
   - Set up Cloud Scheduler for daily completeness check
   - Add completeness check to daily health summary Slack

3. **This Week:**
   - Build unified monitoring dashboard
   - Add circuit breaker for feature quality < 70
