# Same-Day Pipeline Issues - Comprehensive Fix Plan

**Created:** 2026-01-09
**Status:** In Progress (Recovery Complete, Prevention Pending)
**Priority:** Critical
**Issues Discovered:**
1. UPGC timing race condition (0% prop coverage) - **FIXED for today**
2. V8 model not loading (env var missing) - **NEEDS FIX**
3. V8 confidence normalization bug - **NEEDS FIX**
4. 241/349 player completeness failures - **NEEDS INVESTIGATION**

---

## Executive Summary

On January 9, 2026, all 108 V8 predictions were generated with `recommendation='NO_LINE'`, making them unusable for betting decisions. Root cause: UPGC (UpcomingPlayerGameContextProcessor) ran at 12:45 PM ET, but BettingPros props weren't available until 12:59 PM ET.

**Impact:**
- 0 actionable picks for today's 10 games
- 108 predictions exist but all have `has_prop_line=false`
- Revenue impact: Users cannot see any OVER/UNDER recommendations

---

## Root Cause Analysis

### Timeline of Events (January 9, 2026)

| Time (ET) | Event | Status |
|-----------|-------|--------|
| 10:30 AM | `same-day-phase3` scheduled | Unknown if it ran |
| 12:45 PM | UPGC actually ran | Props NOT yet available |
| 12:59 PM | BettingPros props first loaded | Too late - UPGC done |
| ~1:00 PM | Feature store generated | Inherited `has_prop_line=false` |
| ~1:30 PM | V8 predictions generated | All `recommendation='NO_LINE'` |

### Race Condition Diagram

```
EXPECTED:
─────────
Props Scrape (8-10 AM) → UPGC (10:30 AM) → Features → Predictions
                ↓              ↓
          props available   joins with props
                          has_prop_line = TRUE

ACTUAL TODAY:
─────────────
UPGC (12:45 PM) ────────→ Props Scrape (12:59 PM)
       ↓                          ↓
joins with EMPTY table      too late!
has_prop_line = FALSE
```

### Data Evidence

```sql
-- Props timing vs UPGC timing
SELECT 'UPGC' as source, MIN(created_at), MAX(created_at)
FROM nba_analytics.upcoming_player_game_context WHERE game_date = '2026-01-09'
UNION ALL
SELECT 'Props', MIN(created_at), MAX(created_at)
FROM nba_raw.bettingpros_player_points_props WHERE game_date = '2026-01-09';

-- Results:
-- UPGC:  17:45:42 UTC - 17:45:55 UTC (12:45 PM ET)
-- Props: 17:59:59 UTC - 18:45:13 UTC (12:59 PM ET)
```

---

## Three Issues Identified

| # | Problem | Impact | Severity |
|---|---------|--------|----------|
| 1 | **Props scraped AFTER UPGC ran** | ALL predictions unusable | Critical |
| 2 | **241/349 players failed completeness** | Only 4/10 games have predictions | High |
| 3 | **No automatic recovery mechanism** | Bad state persists until manual fix | High |

---

## Solution Architecture

### Layer 1: Prevention - Props Pre-flight Check

**Add a dependency check that prevents UPGC from running until props are available.**

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

```python
def _check_props_readiness(self, target_date: date) -> dict:
    """
    Pre-flight check: Are props available for today's games?
    For same-day processing, props MUST be available before we run.
    """
    if target_date < date.today():
        # Backfill mode - don't require props
        return {'ready': True, 'reason': 'backfill_mode'}

    query = """
    SELECT
        COUNT(DISTINCT player_lookup) as player_count,
        COUNT(*) as line_count,
        MAX(created_at) as latest_scrape
    FROM `{project}.nba_raw.bettingpros_player_points_props`
    WHERE game_date = @target_date AND is_active = TRUE
    """.format(project=self.project_id)

    result = list(self.bq_client.query(query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("target_date", "DATE", target_date)]
        )).result())[0]

    # Need at least 20 players with props for a game day
    min_players = 20

    return {
        'ready': result.player_count >= min_players,
        'player_count': result.player_count,
        'line_count': result.line_count,
        'latest_scrape': result.latest_scrape,
        'min_required': min_players
    }

def process_date(self, target_date: date, **kwargs) -> Dict:
    """Process with props pre-flight check."""

    # NEW: Same-day props readiness check
    if target_date >= date.today() and not kwargs.get('skip_props_check', False):
        props_status = self._check_props_readiness(target_date)

        if not props_status['ready']:
            raise DependencyNotReady(
                f"BettingPros props not yet available for {target_date}. "
                f"Found {props_status['player_count']} players (need {props_status['min_required']}). "
                f"Latest scrape: {props_status['latest_scrape']}. "
                "Waiting for props scraper to complete first."
            )

        logger.info(f"Props pre-flight check passed: {props_status['player_count']} players available")

    # Continue with normal processing...
```

**Benefit:** UPGC will fail fast if props aren't ready, rather than running with bad data.

---

### Layer 2: Prevention - Scheduler Reordering

**Current Schedule:**
- `execute-workflows` (props scraper): hourly at :05
- `same-day-phase3`: 10:30 AM ET

**Problem:** Props may not be scraped until after 10:30 AM.

**Solution: Force props scrape before Phase 3**

```bash
# Create new scheduler that ensures props are ready BEFORE Phase 3
gcloud scheduler jobs create http same-day-props-ensure --location=us-west2 \
  --schedule="0 10 * * *" \
  --time-zone="America/New_York" \
  --uri="https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/execute" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"workflow": "betting_lines", "force": true}' \
  --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com" \
  --oidc-token-audience="https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/execute"

# Then delay Phase 3 to 11:00 AM (was 10:30 AM)
gcloud scheduler jobs update http same-day-phase3 --location=us-west2 \
  --schedule="0 11 * * *"

# Cascade downstream schedulers
gcloud scheduler jobs update http same-day-phase4 --location=us-west2 \
  --schedule="30 11 * * *"

gcloud scheduler jobs update http same-day-predictions --location=us-west2 \
  --schedule="0 12 * * *"
```

---

### Layer 3: Detection - 0% Prop Coverage Alert

**Add alerting when UPGC completes with 0% prop matching.**

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

```python
def _emit_prop_coverage_alert(self):
    """Alert if prop coverage is unexpectedly low."""
    total = len(self.transformed_data)
    with_props = sum(1 for p in self.transformed_data if p.get('has_prop_line'))

    prop_pct = 100.0 * with_props / max(total, 1)

    # CRITICAL: 0% prop coverage on a game day means timing issue
    if total > 50 and prop_pct == 0:
        from shared.utils.email_alerting import send_alert
        send_alert(
            level='CRITICAL',
            subject="UPGC: 0% Prop Coverage - Timing Issue Detected",
            body=f"""
CRITICAL: UpcomingPlayerGameContextProcessor completed with 0% prop line coverage.

Players processed: {total}
Players with prop lines: {with_props} (0%)

This likely means props weren't scraped before UPGC ran.
Action needed: Re-run UPGC after props are available.

Run this to check props:
bq query "SELECT COUNT(*) FROM nba_raw.bettingpros_player_points_props WHERE game_date = '{self.target_date}'"

To re-run UPGC:
gcloud scheduler jobs run same-day-phase3 --location=us-west2
            """
        )
    elif total > 50 and prop_pct < 30:
        # Warning for unusually low coverage
        send_alert(
            level='WARNING',
            subject=f"UPGC: Low Prop Coverage ({prop_pct:.0f}%)",
            body=f"Only {with_props}/{total} players have prop lines. Expected ~45-50%."
        )
```

---

### Layer 4: Recovery - Self-Healing Scheduler

**Create a self-healing job that catches and fixes timing issues automatically.**

```bash
# Create self-healing job that runs at 1 PM ET
gcloud scheduler jobs create http same-day-selfheal --location=us-west2 \
  --schedule="0 13 * * *" \
  --time-zone="America/New_York" \
  --uri="https://us-west2-nba-props-platform.cloudfunctions.net/same-day-selfheal" \
  --http-method=POST \
  --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com"
```

**Cloud Function: same-day-selfheal**

```python
def same_day_selfheal(request):
    """
    Self-healing check at 1 PM ET.
    Detects and fixes same-day pipeline issues.
    """
    from datetime import date
    from google.cloud import bigquery

    today = date.today()
    client = bigquery.Client()

    # Check 1: Do we have props?
    props_query = """
    SELECT COUNT(DISTINCT player_lookup) as cnt
    FROM nba_raw.bettingpros_player_points_props
    WHERE game_date = @today AND is_active = TRUE
    """
    props_count = run_query(client, props_query, today)

    if props_count < 20:
        send_alert("Props still not available at 1 PM - cannot self-heal")
        return {'status': 'blocked', 'reason': 'no_props'}

    # Check 2: Does UPGC have 0% prop coverage?
    upgc_query = """
    SELECT
        COUNT(*) as total,
        COUNTIF(has_prop_line) as with_props
    FROM nba_analytics.upcoming_player_game_context
    WHERE game_date = @today
    """
    upgc_stats = run_query(client, upgc_query, today)

    if upgc_stats['total'] > 0 and upgc_stats['with_props'] == 0:
        # DETECTED: UPGC ran before props were available
        logger.warning(f"Self-heal triggered: UPGC has 0% prop coverage")

        # Re-run the pipeline
        trigger_phase3_rerun(today)
        time.sleep(120)  # Wait 2 minutes

        trigger_phase4_rerun(today)
        time.sleep(120)

        trigger_predictions_rerun(today)

        send_alert(f"Self-heal completed: Re-ran same-day pipeline for {today}")
        return {'status': 'healed', 'actions': ['upgc', 'phase4', 'predictions']}

    # Check 3: Do we have actionable predictions?
    pred_query = """
    SELECT
        COUNT(*) as total,
        COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable
    FROM nba_predictions.player_prop_predictions
    WHERE game_date = @today AND is_active = TRUE
    """
    pred_stats = run_query(client, pred_query, today)

    if pred_stats['total'] > 0 and pred_stats['actionable'] == 0:
        # All predictions are NO_LINE - trigger re-run
        trigger_full_rerun(today)
        return {'status': 'healed', 'reason': 'all_no_line'}

    return {'status': 'healthy'}
```

---

### Layer 5: Visibility - Same-Day Health Dashboard

**Add to daily validation or create new monitoring query:**

```sql
-- Same-Day Health Check: Run after 11 AM ET
-- Add to bin/validate_pipeline.py or monitoring dashboard

WITH pipeline_status AS (
  SELECT
    'Props Available' as check_name,
    COUNT(DISTINCT player_lookup) as value,
    CASE WHEN COUNT(*) > 20 THEN 'OK' ELSE 'MISSING' END as status
  FROM nba_raw.bettingpros_player_points_props
  WHERE game_date = CURRENT_DATE()

  UNION ALL

  SELECT
    'UPGC Prop Coverage %',
    ROUND(100.0 * COUNTIF(has_prop_line) / NULLIF(COUNT(*), 0)),
    CASE
      WHEN COUNTIF(has_prop_line) = 0 THEN 'CRITICAL - TIMING ISSUE'
      WHEN 100.0 * COUNTIF(has_prop_line) / COUNT(*) < 30 THEN 'WARNING'
      ELSE 'OK'
    END
  FROM nba_analytics.upcoming_player_game_context
  WHERE game_date = CURRENT_DATE()

  UNION ALL

  SELECT
    'Actionable Predictions',
    COUNT(*),
    CASE
      WHEN COUNT(*) = 0 THEN 'CRITICAL - NO PICKS'
      WHEN COUNT(*) < 50 THEN 'WARNING - LOW'
      ELSE 'OK'
    END
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = CURRENT_DATE()
    AND is_active = TRUE
    AND recommendation IN ('OVER', 'UNDER')
)
SELECT * FROM pipeline_status;
```

---

## Implementation Priority

| # | Solution | Effort | Impact | Priority |
|---|----------|--------|--------|----------|
| 1 | **Props pre-flight check** | 2 hours | Prevents issue | P0 |
| 2 | **0% coverage alert** | 1 hour | Detects issue | P0 |
| 3 | **Scheduler reordering** | 30 min | Better timing | P1 |
| 4 | **Self-healing scheduler** | 4 hours | Auto-recovery | P1 |
| 5 | **Dashboard query** | 1 hour | Visibility | P2 |

---

## Immediate Recovery Steps (For Today)

```bash
# Step 1: Verify props are now available
bq query --use_legacy_sql=false "SELECT COUNT(DISTINCT player_lookup) FROM nba_raw.bettingpros_player_points_props WHERE game_date = '2026-01-09'"
# Expected: 157+

# Step 2: Force re-run UPGC
curl -X POST "https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2026-01-09",
    "end_date": "2026-01-09",
    "processors": ["UpcomingPlayerGameContextProcessor"],
    "backfill_mode": true
  }'

# Step 3: Wait 2 minutes, then re-run Phase 4
curl -X POST "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "analysis_date": "2026-01-09",
    "processors": ["MLFeatureStoreProcessor"],
    "strict_mode": false,
    "skip_dependency_check": true
  }'

# Step 4: Wait 2 minutes, then re-run predictions
gcloud scheduler jobs run same-day-predictions --location=us-west2

# Step 5: Verify fix
bq query --use_legacy_sql=false "
SELECT
  COUNTIF(has_prop_line) as with_props,
  COUNT(*) as total
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = '2026-01-09'"
```

---

## Related Documentation

- `docs/07-monitoring/observability-gaps.md` - Broader monitoring gaps
- `docs/02-operations/daily-validation-checklist.md` - Daily validation procedures
- `docs/09-handoff/2026-01-09-DAILY-OPS-AND-FIXES.md` - Today's handoff doc

---

---

## Issue 2: V8 Model Not Loading (CRITICAL)

### Problem

CatBoost V8 model exists in GCS but prediction-worker service doesn't have the env var set.

**Evidence:**
```
# Worker logs show fallback being used:
"Unknown system_id catboost_v8, assuming 0-1 scale"

# All V8 predictions have:
confidence_score = 50.0 (fallback default)
recommendation = 'PASS' (fallback always returns PASS)
```

**Root Cause:**
- Model uploaded to: `gs://nba-props-platform-ml-models/catboost_v8_33features_20260108_211817.cbm`
- Environment variable `CATBOOST_V8_MODEL_PATH` NOT set on prediction-worker
- Worker falls back to simple average prediction

### Fix

```bash
# Set the missing environment variable
gcloud run services update prediction-worker --region=us-west2 \
  --update-env-vars="CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-ml-models/catboost_v8_33features_20260108_211817.cbm"
```

### Verification

After fix, check logs for:
```
INFO - Loading CatBoost v8 model from gs://...
INFO - Loaded CatBoost v8 model successfully
```

---

## Issue 3: V8 Confidence Normalization Bug

### Problem

`normalize_confidence()` in `data_loaders.py` doesn't recognize `catboost_v8` system_id.

**File:** `predictions/worker/data_loaders.py` lines 908-932

**Current Code:**
```python
if system_id in ['moving_average', 'zone_matchup_v1', 'ensemble_v1']:
    return confidence  # 0-1 scale
elif system_id in ['similarity_balanced_v1', 'xgboost_v1']:
    return confidence / 100.0  # Convert 0-100 to 0-1
else:
    logger.warning(f"Unknown system_id {system_id}, assuming 0-1 scale")
    return confidence  # Bug: V8 returns 0-100, not 0-1
```

### Fix

Add `catboost_v8` to the 0-100 scale list:

```python
elif system_id in ['similarity_balanced_v1', 'xgboost_v1', 'catboost_v8']:
    return confidence / 100.0
```

---

## Issue 4: 241/349 Player Failures

### Problem

Only 108/349 rostered players processed in UPGC. 241 failed completeness checks.

**Impact:** Only 4 of 10 games have predictions

**Games WITH predictions:**
- ORL vs PHI
- WAS vs NOP
- DEN vs ATL
- PHX vs NYK

**Games WITHOUT predictions:**
- BOS vs TOR
- BKN vs LAC
- MEM vs OKC
- GSW vs SAC
- POR vs HOU
- LAL vs MIL

### Investigation Needed

1. Check completeness checker logs for specific failure reasons
2. Check if BDL API has data gaps for affected teams
3. Consider lowering completeness threshold for same-day mode (70% → 50%)
4. Check if early season boundary detection is working

---

## Comprehensive Todo List

### P0 - Critical (Do Today)

- [ ] **Fix V8 model loading** - Set CATBOOST_V8_MODEL_PATH env var on prediction-worker
- [ ] **Re-run predictions after V8 fix** - Get actual V8 predictions with proper confidence
- [ ] **Verify V8 fix** - Check predictions have confidence > 50 and OVER/UNDER recommendations

### P1 - High (This Week)

- [ ] **Fix V8 confidence normalization** - Add `catboost_v8` to normalize_confidence()
- [ ] **Add props pre-flight check** - UPGC fails fast if props not available
- [ ] **Add 0% prop coverage alert** - Email alert when UPGC completes with 0% props
- [ ] **Reorder schedulers** - Ensure props scrape before Phase 3 (add 10 AM props job)
- [ ] **Deploy UPGC changes** - Deploy props check and alert

### P2 - Medium (This Week)

- [ ] **Create self-healing scheduler** - 1 PM job to detect and fix timing issues
- [ ] **Deploy self-healing Cloud Function** - Auto-recovery when bad state detected
- [ ] **Add same-day health dashboard** - BigQuery query for pipeline health

### P3 - Lower (Next Week)

- [ ] **Investigate 241 player failures** - Why did 6 games fail completeness?
- [ ] **Consider same-day completeness threshold** - Lower from 70% for same-day mode
- [ ] **Add processor execution logging** - BigQuery table for processor runs (broader improvement)

---

## Acceptance Criteria

- [ ] V8 model loading from GCS (not fallback)
- [ ] V8 predictions have varied confidence scores (not all 50.0)
- [ ] V8 recommendations include OVER/UNDER (not all PASS)
- [ ] Props pre-flight check implemented in UPGC
- [ ] 0% prop coverage alert functional
- [ ] Self-healing scheduler deployed
- [ ] Documentation updated

---

## Related Documentation

- `docs/08-projects/current/ml-model-v8-deployment/PRODUCTION-DEPLOYMENT.md` - V8 deployment guide
- `docs/07-monitoring/observability-gaps.md` - Broader monitoring improvements
- `docs/02-operations/daily-validation-checklist.md` - Daily validation procedures

---

## Change Log

| Date | Change |
|------|--------|
| 2026-01-09 AM | Initial document - timing issue discovered |
| 2026-01-09 PM | Recovery executed - 44% prop coverage restored |
| 2026-01-09 PM | V8 model issue discovered - env var missing |
| 2026-01-09 PM | Comprehensive fix plan created |
