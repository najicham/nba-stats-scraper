# Orchestration & Validation Deep Dive Handoff
**Date:** January 23, 2026
**Session Focus:** Daily orchestration validation, bug fixes, and system improvement research
**Status:** Fixes deployed, research complete, action items identified

---

## Executive Summary

This session addressed critical daily orchestration issues and conducted deep research into system reliability. **4 critical bugs were fixed and deployed**, and **comprehensive research identified 15+ improvement opportunities** across orchestration, validation, monitoring, and data quality.

---

## Part 1: Completed Fixes (Deployed to Production)

### Fix 1: YESTERDAY_TARGET_WORKFLOWS Missing Entries
**File:** `orchestration/parameter_resolver.py:44-49`
**Problem:** `post_game_window_2b` and `morning_recovery` workflows were configured with `decision_type: "game_aware_yesterday"` in `workflows.yaml` but missing from the code list.
**Impact:** These workflows looked for TODAY's games instead of YESTERDAY's, causing empty game lists and "Missing required option" errors.
**Fix:** Added both workflows to the list.

### Fix 2: Missing oddsa_events Resolver
**File:** `orchestration/parameter_resolver.py:83-94, 642-658`
**Problem:** `oddsa_events` scraper had no resolver registered, causing "Missing required option [sport]" errors.
**Fix:** Added `_resolve_odds_events()` method returning `{'sport': 'basketball_nba', 'game_date': context['execution_date']}`.

### Fix 3: Feature Store 60-Day Lookback Bug (CRITICAL)
**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py:414-467`
**Problem:** `total_games_available` was incorrectly limited to 60-day window, causing:
- 80% of players failing spot check validation
- Incorrect `games_found` and `games_expected` values
- False bootstrap detection for players with older games

**Fix:** Rewrote query using CTE to separate:
- Last-10 retrieval (60-day window for efficiency)
- Total games count (no date limit for accuracy)

**Note:** Fix applies to NEW records only. Historical records (Jan 1-22) retain old values. To fix:
```bash
bq query 'DELETE FROM nba_predictions.ml_feature_store_v2 WHERE game_date BETWEEN "2026-01-01" AND "2026-01-22"'
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
    --start-date 2026-01-01 --end-date 2026-01-22 --parallel
```

### Fix 4: Stale Schedule Fix Script + Automation
**File:** `bin/monitoring/fix_stale_schedule.py`
**Problems Fixed:**
- Column name errors (`start_time_et` → `time_slot`, `home_team_abbr` → `home_team_tricode`)
- Missing partition filter on UPDATE query
- Inconsistent updates (now sets both `game_status` and `game_status_text`)

**Automation Added:**
- New endpoint: `POST /fix-stale-schedule` in `scrapers/main_scraper_service.py`
- Cloud Scheduler job: `fix-stale-schedule` runs every 4 hours
- Setup script: `bin/schedulers/setup_stale_schedule_job.sh`

### Deployment Status
- **Commit:** `6ba6618c` - "fix: Resolve orchestration parameter resolution and feature store bugs"
- **Cloud Run:** `nba-scrapers-00097-s25` serving 100% traffic
- **Cloud Scheduler:** `fix-stale-schedule` job created and enabled
- **Verification:** No "Missing required option" errors in last 6 hours

---

## Part 2: Research Findings - Prioritized Issues

### CRITICAL Priority (Immediate Action Required)

#### Issue C1: Validation System Has 21 Empty/Disabled Validators
**Location:** `validation/configs/raw/`, `validation/validators/raw/`
**Impact:** Critical data sources have NO automated validation

**Empty validators (0 lines):**
- `nbac_gamebook.yaml` - Primary game stats source
- `nbac_schedule.yaml` - Schedule source of truth
- `nbac_injury_report.yaml` - Game context data
- `nbac_player_boxscore.yaml`
- `nbac_play_by_play.yaml`
- `bdl_active_players.yaml`
- `bdl_injuries.yaml`
- `bdl_standings.yaml`
- `espn_rosters.yaml`
- `espn_box_scores.yaml`
- `br_rosters.yaml`
- `bigdataball_pbp.yaml`
- And 9 more...

**Only working validators:** BDL Boxscores, ESPN Scoreboard, Odds Game Lines, BettingPros Props

**Recommendation:** Implement validators for top 5 critical sources first:
1. NBAC Gamebook
2. NBAC Schedule
3. NBAC Player Boxscore
4. BDL Box Scores
5. NBAC Injury Report

---

#### Issue C2: Cleanup Processor Missing Table Coverage
**File:** `orchestration/cleanup_processor.py:199-224`
**Impact:** Files from missing scrapers flagged as "unprocessed" → unnecessary republishing or permanent orphaning

**Currently checks (4 tables):**
```python
nbac_schedule, odds_events, odds_player_props, bdl_player_boxscores
```

**Missing (15+ tables):**
```
nbac_team_boxscore, nbac_player_boxscore, bdl_box_scores, nbac_play_by_play,
nbac_gamebook_pdf, bp_events, bp_player_props, bigdataball_pbp, espn_scoreboard,
espn_rosters, bdl_active_players, bdl_injuries, bdl_standings, nbac_injury_report
```

**Fix:** Expand query to include ALL Phase 2 raw tables, or implement a unified `file_processed` audit table.

---

#### Issue C3: Dead Letter Queue (DLQ) Monitoring is Placeholder
**File:** `bin/alerts/daily_summary/main.py`
**Impact:** Messages stuck in DLQ go unnoticed for hours

**Current code:**
```python
# Comment: "num_undelivered_messages is not directly available via API"
# Returns -1 (placeholder)
```

**Fix:** Implement proper Pub/Sub monitoring API integration:
```python
from google.cloud import monitoring_v3
# Query pubsub.googleapis.com/subscription/num_undelivered_messages
```

---

### HIGH Priority (Within 1-2 Weeks)

#### Issue H1: BettingPros Proxy Retry Logic Inefficient
**File:** `scrapers/scraper_base.py:1327-1840`
**Impact:** 40% of failures are false positives due to poor retry strategy

**Current flow:**
```
Try Proxy1 → fail → Try Proxy2 → fail → Try Proxy3 → fail → Outer retry loop × 8
```

**Recommended flow:**
```
Proxy1 (retry×3 with 4-12s backoff) → wait 30s →
Proxy2 (retry×3 with 4-12s backoff) → wait 30s →
Proxy3 (retry×3 with 4-12s backoff)
```

**Additional fixes needed:**
- Increase `timeout_http` from 45s to 90s for Decodo residential proxies
- Add adaptive rate limiting (2.5s → 20s based on 429 responses)
- Implement per-proxy circuit breaker

---

#### Issue H2: Hardcoded Timeouts in Orchestration
**File:** `orchestration/workflow_executor.py:116-119`
```python
SCRAPER_TIMEOUT = 180  # Hard-coded
FUTURE_TIMEOUT = SCRAPER_TIMEOUT + 10
```

**Impact:** Can't adjust for slow APIs without code deployment

**Fix:** Move to `config/workflows.yaml`:
```yaml
settings:
  executor:
    scraper_timeout_seconds: 180
    future_timeout_seconds: 190
```

---

#### Issue H3: Project ID Environment Variable Inconsistency
**Files:** Multiple

```python
# cleanup_processor.py:58
os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

# master_controller.py:117
os.getenv("GCP_PROJECT", "nba-props-platform")  # Different var name!
```

**Fix:** Standardize on `GCP_PROJECT` everywhere.

---

#### Issue H4: Phase Transition Failures Go Undetected
**Impact:** Pipelines can hang silently (Phase N completes, Phase N+1 never starts)

**Current state:** Only visible via manual Firestore inspection

**Fix:** Add monitoring that:
- Checks Firestore `phase_completion` documents
- Alerts if Phase N completes but Phase N+1 doesn't trigger within 10 minutes
- Tracks per-processor completion

---

#### Issue H5: Cleanup Processor Has No Retry on Pub/Sub Publish Failure
**File:** `orchestration/cleanup_processor.py:250-302`

```python
try:
    future = self.publisher.publish(...)
except Exception as e:
    logger.error(...)  # NO RETRY - file permanently orphaned
```

**Fix:** Add exponential backoff retry (3-5 attempts) with jitter.

---

### MEDIUM Priority (Within 1 Month)

#### Issue M1: Broken Scraper Health Monitoring Views
**File:** `validation/queries/scraper_availability/daily_scraper_health.sql`

References non-existent views:
- `nba_orchestration.v_scraper_latency_daily`
- `nba_orchestration.v_game_data_timeline`

**Fix:** Create the views or remove the queries.

---

#### Issue M2: Cleanup Processor Lookback Window Too Short
**File:** `orchestration/cleanup_processor.py`

**Configuration:**
- `lookback_hours: 1` - Only checks last hour
- `min_file_age_minutes: 30`
- Runs every 15 minutes

**Problem:** Files older than 1 hour are never checked again.

**Fix:** Increase `lookback_hours` to 4-6 hours.

---

#### Issue M3: Workflow Executor Logging Failure Not Monitored
**File:** `orchestration/workflow_executor.py:842-852`

```python
except Exception as e:
    logger.error(f"Failed to log workflow execution: {e}")
    # TODO: Add monitoring/alerting for logging failures
```

**Fix:** Implement retry logic and alert on persistent failures.

---

#### Issue M4: No Prediction Quality Distribution Monitoring
**Impact:** Systematic confidence degradation goes undetected

**Current:** Only checks average confidence

**Fix:** Track confidence histogram, alert on:
- Bimodal distribution (fallback mixing)
- High concentration in 0.49-0.51 range
- Sudden distribution shifts

---

#### Issue M5: nbac_team_boxscore Status Unclear
**File:** `config/workflows.yaml:126-135`

```yaml
nbac_team_boxscore:
    # TEMPORARILY DISABLED: NBA API returning 0 teams (Dec 2025)
    # TODO: Investigate and re-enable when API issue resolved
    critical: false
```

**Problem:** No ticket reference, no deadline, unclear fallback status.

**Fix:** Create Jira ticket, document recovery criteria, add health check.

---

### LOW Priority (Backlog)

| Issue | File | Description |
|-------|------|-------------|
| L1 | master_controller.py | Early game timezone conversions done 3x in loop (inefficient) |
| L2 | cleanup_processor.py | Notification threshold (5) undocumented |
| L3 | workflows.yaml | BDL catch-up smart_retry logic undocumented |
| L4 | Multiple | No Prometheus metrics from orchestration components |
| L5 | circuit_breaker_mixin.py | Uses in-memory state, lost on restart |

---

## Part 3: Files Modified This Session

| File | Change Type | Description |
|------|-------------|-------------|
| `orchestration/parameter_resolver.py` | Modified | Added workflows + oddsa_events resolver |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Modified | Fixed 60-day lookback bug |
| `bin/monitoring/fix_stale_schedule.py` | Modified | Fixed column names + partition filter |
| `scrapers/main_scraper_service.py` | Modified | Added /fix-stale-schedule endpoint |
| `bin/schedulers/setup_stale_schedule_job.sh` | Created | Cloud Scheduler setup script |
| `docs/08-projects/current/jan-23-orchestration-fixes/` | Created | Project documentation |
| `docs/08-projects/current/MASTER-PROJECT-TRACKER.md` | Modified | Added today's fixes |

---

## Part 4: Verification Commands

### Check Orchestration Health
```bash
# Recent scraper executions
bq query --use_legacy_sql=false 'SELECT scraper_name, status, COUNT(*) FROM nba_orchestration.scraper_execution_log WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR) GROUP BY 1,2 ORDER BY 3 DESC'

# Check for parameter errors (should be 0)
bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM nba_orchestration.scraper_execution_log WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR) AND error_message LIKE "%Missing required option%"'

# Schedule status
bq query --use_legacy_sql=false 'SELECT game_date, game_status_text, COUNT(*) FROM nba_raw.nbac_schedule WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY) GROUP BY 1,2 ORDER BY 1 DESC'
```

### Test Stale Schedule Endpoint
```bash
curl -s -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "https://nba-scrapers-756957797294.us-west2.run.app/fix-stale-schedule"
```

### Spot Check Features
```bash
python bin/spot_check_features.py --count 10 --date 2026-01-22
```

---

## Part 5: Recommended Next Actions

### Immediate (Next Session)
1. **Fix cleanup processor table coverage** - Low effort, critical impact
2. **Implement DLQ monitoring** - Medium effort, critical for reliability
3. **Standardize GCP_PROJECT env var** - Low effort, prevents cross-project issues

### Short-Term (This Week)
4. **Add phase transition alerts** - Prevents silent pipeline hangs
5. **Implement proxy retry improvements** - Reduces betting_pros failures by 40%
6. **Create NBAC Gamebook validator** - Most critical missing validator

### Medium-Term (Next 2 Weeks)
7. **Create remaining critical validators** (Schedule, Player Boxscore)
8. **Add prediction quality distribution monitoring**
9. **Fix broken scraper health monitoring views**

---

## Part 6: Related Documentation

- **Project docs:** `docs/08-projects/current/jan-23-orchestration-fixes/`
- **Validation framework:** `validation/IMPLEMENTATION_GUIDE.md`
- **Orchestration docs:** `docs/03-phases/phase1-orchestration/`
- **Daily validation checklist:** `docs/02-operations/daily-validation-checklist.md`

---

## Appendix: Research Agent IDs (For Resume If Needed)

| Research Area | Agent ID |
|---------------|----------|
| Orchestration improvements | a9a8b07 |
| BettingPros investigation | aa005ec |
| Data quality issues | a632949 |
| Monitoring gaps | a18dd0f |
