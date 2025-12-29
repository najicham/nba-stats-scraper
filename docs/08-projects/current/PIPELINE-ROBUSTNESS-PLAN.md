# Pipeline Robustness Improvement Plan

**Created:** 2025-12-28
**Session:** 183
**Status:** IN PROGRESS (P0/P1 complete, P2/P3 pending)
**Priority:** HIGH
**Last Updated:** 2025-12-29

---

## Executive Summary

Session 182 revealed critical gaps in the data pipeline that caused 5 teams to have 0 players in predictions. This plan addresses root causes and adds multiple layers of protection to prevent future issues.

**Session 183 Progress:** Fixed critical issues (processor registry, completeness check, circuit breaker lockout). Remaining work documented below.

---

## Root Cause Analysis (Session 182)

```
BDL player-box-scores scraper → GCS (player-box-scores/)
                                      ↓
                              NO PROCESSOR REGISTERED ← FIXED ✅
                                      ↓
                              Data never loaded to BigQuery
                                      ↓
                              Completeness checks fail (<70%)
                                      ↓
                              Circuit breakers trip (5 failures)
                                      ↓
                              Players locked out 7 DAYS ← FIXED ✅ (now 24h)
                                      ↓
                              5 teams with 0 players in predictions
```

### Key Problems Identified

| Problem | Impact | Status | Fix Applied |
|---------|--------|--------|-------------|
| Missing processor registry | Data lost | ✅ FIXED | BdlPlayerBoxScoresProcessor added |
| Circuit breaker 7-day lockout | Extended outages | ✅ FIXED | Reduced to 24h via config |
| No automated gap detection | Late discovery | ✅ FIXED | Scheduler at 6 AM ET |
| No automatic backfill | Manual intervention | 🔲 PENDING | Cloud Function needed |
| Prediction duplicates | 5x data bloat | 🔲 PENDING | Need MERGE instead of APPEND |

---

## Improvement Plan

### Phase 1: Critical Fixes (Today)

#### 1.1 Add Processor Registry Entry

**File:** `data_processors/raw/main_processor_service.py`

```python
# Add to PROCESSOR_REGISTRY
'ball-dont-lie/player-box-scores': BdlPlayerBoxscoresProcessor,
```

**Issue:** The `bdl_player_box_scores` scraper exports to `ball-dont-lie/player-box-scores/` but no processor is registered for this path. Data goes to GCS but never reaches BigQuery.

**Note:** May need a new processor if data format differs from `ball-dont-lie/boxscores`.

---

#### 1.2 Schedule Boxscore Completeness Check

The endpoint already exists at `/monitoring/boxscore-completeness`. Just needs a scheduler.

```bash
# Create scheduler (6 AM ET daily)
gcloud scheduler jobs create http boxscore-completeness-check \
    --location=us-west2 \
    --schedule="0 6 * * *" \
    --time-zone="America/New_York" \
    --uri="https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/monitoring/boxscore-completeness" \
    --http-method=POST \
    --message-body='{"check_days": 1, "alert_on_gaps": true}' \
    --oidc-service-account-email=scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com
```

**When called:** Compares scheduled games vs boxscore data, sends alerts if teams below 70%.

---

#### 1.3 Reduce Circuit Breaker Lockout

**File:** `shared/processors/patterns/circuit_breaker_mixin.py`

```python
# Current
CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)  # This is for processor circuit breakers

# The 7-day lockout is in reprocess_attempts table
# File: data_processors/analytics/analytics_base.py or similar
circuit_breaker_until = now + timedelta(days=7)  # CHANGE TO:
circuit_breaker_until = now + timedelta(hours=24)
```

**Rationale:** 7 days is too long. If data is backfilled the next day, players should be eligible for reprocessing.

---

### Phase 2: Data Reliability (This Week)

#### 2.1 Fix Prediction Worker Duplicates

**File:** `predictions/worker/worker.py` (lines 996-1041)

**Current:** Uses `WRITE_APPEND` which creates duplicates when Pub/Sub retries.

**Fix:** Use MERGE statement instead:

```python
# Replace load_table_from_json with MERGE statement
merge_query = f"""
MERGE `{table_id}` T
USING UNNEST(@predictions) S
ON T.player_lookup = S.player_lookup
   AND T.game_date = S.game_date
   AND T.prop_type = S.prop_type
WHEN MATCHED THEN
  UPDATE SET
    predicted_value = S.predicted_value,
    is_active = S.is_active,
    updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (...)
  VALUES (...)
"""
```

**Alternative:** Add deduplication in tonight exporter (already done as workaround).

---

#### 2.2 Add Automatic Backfill Trigger

When boxscore completeness check finds gaps, automatically trigger backfill.

**New Cloud Function:** `boxscore-backfill-trigger`

```python
def trigger_backfill(missing_dates, missing_teams):
    """Trigger BDL player boxscores scraper for missing dates."""
    for date in missing_dates:
        # Call scraper service with date parameter
        requests.post(
            f"{SCRAPER_URL}/scrape",
            json={
                "scraper_name": "bdl_player_box_scores",
                "params": {"startDate": date, "endDate": date}
            }
        )
```

**Flow:**
1. `boxscore-completeness-check` runs at 6 AM ET
2. If gaps found, publishes to `boxscore-gaps-detected` topic
3. `boxscore-backfill-trigger` receives message and triggers scraper
4. Scraper runs and fills gaps
5. Phase 2 processes new data automatically

---

#### 2.3 Extend Self-Heal to Check Phase 2

**File:** `orchestration/cloud_functions/self_heal/main.py`

Currently only checks if predictions exist. Should also check:
- Boxscore data for yesterday
- Game context for today
- Prop lines for today

```python
def check_phase2_health(bq_client, target_date):
    """Check if Phase 2 raw data is complete."""
    yesterday = target_date - timedelta(days=1)

    # Check boxscore completeness
    query = f"""
    WITH schedule AS (
      SELECT DISTINCT game_date FROM nba_raw.nbac_schedule
      WHERE game_date = '{yesterday}' AND game_status = 3
    ),
    boxscores AS (
      SELECT DISTINCT game_date FROM nba_raw.bdl_player_boxscores
      WHERE game_date = '{yesterday}'
    )
    SELECT
      s.game_date,
      b.game_date IS NOT NULL as has_boxscores
    FROM schedule s
    LEFT JOIN boxscores b ON s.game_date = b.game_date
    """
    # If missing, trigger backfill
```

---

### Phase 3: Monitoring & Alerting (Near Term)

#### 3.1 Morning Data Quality Report

**Schedule:** 7 AM ET daily (after overnight collection)

**Content:**
- Games collected overnight: X/Y
- Boxscore completeness: 98%
- Gamebook completeness: 95%
- Any missing teams/dates
- Circuit breakers active: 5 players

**Implementation:** Cloud Function that queries BigQuery and sends email via SES.

---

#### 3.2 Pre-Game Prediction Validation

**Schedule:** 4 hours before first game

**Checks:**
- All teams have players in game context
- Predictions exist for all games
- Quality scores above threshold
- Prop lines loaded

**If issues:** Trigger self-heal and send alert.

---

#### 3.3 Circuit Breaker Dashboard

Add endpoint to show current circuit breaker state:

```bash
GET /monitoring/circuit-breaker-status

Response:
{
  "active_breakers": 5,
  "players_affected": ["player1", "player2", ...],
  "earliest_reset": "2025-12-29T10:00:00Z",
  "tripped_reasons": {
    "completeness_below_70": 3,
    "dependency_failure": 2
  }
}
```

---

### Phase 4: Resilience (Long Term)

#### 4.1 Multi-Source Fallback

When BDL API fails, fall back to NBA.com:

```python
def get_player_boxscores(game_date):
    try:
        return bdl_scraper.scrape(game_date)
    except Exception as e:
        logger.warning(f"BDL failed: {e}, trying NBA.com")
        return nbacom_scraper.scrape(game_date)
```

**Priority Sources:**
1. Ball Don't Lie (primary - fast, structured)
2. NBA.com (secondary - official but rate-limited)
3. ESPN (tertiary - backup)

---

#### 4.2 Auto-Retry with Exponential Backoff

For scrapers that fail:
- Retry 1: 5 minutes
- Retry 2: 15 minutes
- Retry 3: 1 hour
- After 3 failures: Send alert, add to dead-letter queue

**Implementation:** Modify scraper_base.py to track retries.

---

#### 4.3 Dead Letter Queue

Messages that fail processing 5 times go to dead-letter topic:
- Manual review required
- Daily summary of DLQ items
- Easy replay mechanism

---

## Implementation Priority

| Priority | Task | Effort | Status |
|----------|------|--------|--------|
| P0 | Add processor registry entry | 1 hour | ✅ DONE (Session 183) |
| P0 | Schedule boxscore completeness check | 30 min | ✅ DONE (Session 183) |
| P1 | Reduce circuit breaker lockout | 30 min | ✅ DONE (Session 183) |
| P1 | Fix prediction duplicates | 2 hours | 🔲 PENDING |
| P1 | Update remaining circuit breaker hardcodes | 1 hour | 🔲 PENDING |
| P2 | Automatic backfill trigger | 4 hours | 🔲 PENDING |
| P2 | Extend self-heal to Phase 2 | 2 hours | 🔲 PENDING |
| P2 | Circuit breaker auto-reset | 2 hours | 🔲 PENDING |
| P3 | Morning data quality report | 3 hours | 🔲 PENDING |
| P3 | Pre-game validation | 2 hours | 🔲 PENDING |
| P4 | Multi-source fallback | 8 hours | 🔲 PENDING |
| P4 | Dead letter queue | 4 hours | 🔲 PENDING |

---

## Files Modified (Session 183)

| File | Change | Status |
|------|--------|--------|
| `data_processors/raw/balldontlie/bdl_player_box_scores_processor.py` | NEW - handles player-box-scores path | ✅ |
| `data_processors/raw/main_processor_service.py` | Registry entry + notification fix | ✅ |
| `shared/config/orchestration_config.py` | CircuitBreakerConfig dataclass | ✅ |
| `data_processors/analytics/upcoming_player_game_context_processor.py` | Uses config for lockout | ✅ |
| `data_processors/precompute/ml_feature_store_processor.py` | Uses config for lockout | ✅ |

## Files Still Needing Changes

| File | Change Needed |
|------|---------------|
| `predictions/worker/worker.py:996-1041` | Use MERGE instead of WRITE_APPEND |
| `orchestration/cloud_functions/self_heal/main.py` | Add Phase 2 checks |
| `data_processors/precompute/player_composite_factors_processor.py:1066` | Use config for lockout |
| `data_processors/precompute/player_shot_zone_analysis_processor.py:810` | Use config for lockout |
| `data_processors/precompute/player_daily_cache_processor.py:1172,1237` | Use config for lockout |
| `data_processors/precompute/team_defense_zone_analysis_processor.py:607` | Use config for lockout |
| `data_processors/analytics/upcoming_team_game_context_processor.py:1036` | Use config for lockout |

---

## New Files to Create

| File | Purpose |
|------|---------|
| `orchestration/cloud_functions/boxscore_backfill/main.py` | Auto-backfill trigger |
| `orchestration/cloud_functions/morning_report/main.py` | Daily health email |
| `bin/monitoring/setup_boxscore_scheduler.sh` | Create scheduler job |
| `data_processors/raw/balldontlie/bdl_player_boxscores_processor.py` | If new processor needed |

---

## Success Metrics

After implementation, expect:
- **Zero** data loss from missing processor registry
- **24 hour** max lockout instead of 7 days
- **Automatic** gap detection within 12 hours
- **Self-healing** for boxscore gaps (no manual intervention)
- **No duplicate** predictions (clean data)

---

## Monitoring After Implementation

Daily checks:
```bash
# 1. Boxscore completeness
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT team_abbr) as teams
FROM nba_raw.bdl_player_boxscores
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date ORDER BY game_date"

# 2. Circuit breakers
bq query --use_legacy_sql=false "
SELECT COUNT(*) as active_breakers
FROM nba_orchestration.reprocess_attempts
WHERE circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()"

# 3. Prediction duplicates
bq query --use_legacy_sql=false "
SELECT player_lookup, game_date, prop_type, COUNT(*) as copies
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE
GROUP BY player_lookup, game_date, prop_type
HAVING COUNT(*) > 1"
```

---

## Related Documents

- `docs/08-projects/current/BOXSCORE-DATA-GAPS-ANALYSIS.md` - Session 182 investigation
- `docs/08-projects/current/self-healing-pipeline/README.md` - Current self-heal system
- `docs/09-handoff/2025-12-28-SESSION182-COMPLETE-HANDOFF.md` - Handoff from Session 182
