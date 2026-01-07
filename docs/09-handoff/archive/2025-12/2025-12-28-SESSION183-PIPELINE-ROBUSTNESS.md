# Session 183 - Pipeline Robustness Improvements

**Date:** 2025-12-28 (late night) / 2025-12-29 (early morning)
**Duration:** ~2 hours
**Focus:** Fixing root causes from Session 182 data gaps

---

## Summary

Fixed critical pipeline issues that caused 5 teams to have 0 players in predictions:

| Task | Status | Impact |
|------|--------|--------|
| Add processor for `player-box-scores` | ✅ Done | Data now flows to BigQuery |
| Schedule boxscore completeness check | ✅ Done | 6 AM ET daily alerts |
| Reduce circuit breaker lockout (7d → 24h) | ✅ Done | Faster recovery |
| Fix notification parameter bug | ✅ Done | Completeness check works |

---

## Changes Made

### 1. New Processor: BdlPlayerBoxScoresProcessor

**Files:**
- `data_processors/raw/balldontlie/bdl_player_box_scores_processor.py` (new)
- `data_processors/raw/main_processor_service.py` (updated registry)

**What it does:**
- Handles `/stats` endpoint output from `bdl_player_box_scores` scraper
- Transforms flat stats array to `nba_raw.bdl_player_boxscores` table
- Uses MERGE_UPDATE strategy with smart idempotency

**Root Cause Fixed:**
- Scraper wrote to `ball-dont-lie/player-box-scores/` path
- NO processor was registered for this path
- Data went to GCS but never loaded to BigQuery

### 2. Boxscore Completeness Scheduler

**Scheduler:** `boxscore-completeness-check`
- Schedule: 6 AM ET daily
- Endpoint: `/monitoring/boxscore-completeness`
- Alerts when teams below 70% coverage

**IAM Fix:**
- Added `roles/run.invoker` to `scheduler-orchestration` SA for Phase 2

### 3. Circuit Breaker Configuration

**File:** `shared/config/orchestration_config.py`

New `CircuitBreakerConfig` dataclass:
```python
entity_lockout_hours: int = 24      # Was 7 days!
entity_failure_threshold: int = 5
auto_reset_on_data: bool = True
processor_timeout_minutes: int = 30
```

Configurable via environment:
- `CIRCUIT_BREAKER_ENTITY_LOCKOUT_HOURS`
- `CIRCUIT_BREAKER_AUTO_RESET`

**Updated Processors:**
- `UpcomingPlayerGameContextProcessor` (Phase 3)
- `MLFeatureStoreProcessor` (Phase 4)

**Other processors still hardcoded** - need follow-up to update:
- `player_composite_factors_processor.py`
- `player_shot_zone_analysis_processor.py`
- `player_daily_cache_processor.py`
- `team_defense_zone_analysis_processor.py`
- `upcoming_team_game_context_processor.py`

---

## Deployments

| Service | Revision | Time |
|---------|----------|------|
| Phase 2 (raw) | `nba-phase2-raw-processors-00045-pmr` | 04:07 UTC |
| Phase 3 (analytics) | `nba-phase3-analytics-processors-...` | 04:20 UTC |
| Phase 4 (precompute) | `nba-phase4-precompute-processors-00026-lrn` | 04:31 UTC |

---

## Commits

```
ffed66b feat: Add processor for ball-dont-lie/player-box-scores path
c163982 fix: Use correct parameters for notify_error/notify_warning
cd5f22c feat: Reduce circuit breaker lockout from 7 days to 24 hours
```

---

## Remaining Work (Priority Order)

### P1 - Should Do Soon
1. **Fix prediction worker duplicates** - Use MERGE instead of WRITE_APPEND
   - File: `predictions/worker/worker.py:996-1041`
   - Causes 5x duplicate rows due to Pub/Sub retries

2. **Update remaining circuit breaker hardcodes** - Apply config to all processors
   - Run: `grep -rn "timedelta(days=7)" data_processors/`

### P2 - Nice to Have
3. **Add automatic backfill trigger** - When completeness check finds gaps
4. **Extend self-heal to Phase 2** - Check raw data gaps, not just predictions
5. **Circuit breaker auto-reset** - Clear when data becomes available
6. **Morning completeness report** - Email summary after overnight collection

---

## Testing Commands

### Verify processor works:
```bash
# Publish test message
gcloud pubsub topics publish nba-phase1-scrapers-complete \
    --message='{"scraper_name": "bdl_player_box_scores", "gcs_path": "gs://nba-scraped-data/ball-dont-lie/player-box-scores/2025-12-28/20251229_000854.json", "status": "success"}'

# Check logs
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors" AND textPayload=~"BdlPlayerBoxScores"' --limit=10 --freshness=5m
```

### Verify completeness check:
```bash
gcloud scheduler jobs run boxscore-completeness-check --location=us-west2

# Check logs
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors" AND textPayload=~"completeness"' --limit=5 --freshness=5m
```

### Check circuit breaker config:
```python
from shared.config.orchestration_config import get_orchestration_config
config = get_orchestration_config()
print(f"Entity lockout: {config.circuit_breaker.entity_lockout_hours} hours")
```

---

## Related Documents

- `docs/08-projects/current/PIPELINE-ROBUSTNESS-PLAN.md` - Full improvement plan
- `docs/08-projects/current/BOXSCORE-DATA-GAPS-ANALYSIS.md` - Session 182 investigation
- `docs/09-handoff/2025-12-28-SESSION182-COMPLETE-HANDOFF.md` - Previous handoff
