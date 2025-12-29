# Handoff: Same-Day Pipeline Reliability Fix

**Date:** December 29, 2025
**Priority:** P0 - Critical
**Estimated Time:** 4-6 hours
**Goal:** Implement all fixes to prevent today's prediction pipeline failure from recurring

---

## Context

Today (Dec 29) the prediction pipeline failed to generate predictions for 11 NBA games. The failure was not detected until manual investigation at 1:45 PM ET. Root causes:

1. **Self-heal only checks TOMORROW** - It ran at 2:15 PM and didn't notice today's missing predictions
2. **Phase 4 service was misconfigured** - Running wrong code, returned 404
3. **Phase 3→4 orchestrator stuck** - Waiting for 5 processors when only 1 ran

After manual intervention, predictions were generated (~1,700 for 11 games).

---

## Your Mission

Implement all the improvements in the project document to prevent this from happening again.

**Project Doc:** `docs/08-projects/current/same-day-pipeline-fix/README.md`

---

## Tasks (In Order)

### Task 1: Update Self-Heal Function (P0 - 2h)

**File:** `orchestration/cloud_functions/self_heal/main.py`

**Current behavior:** Only checks if TOMORROW has predictions (line 197: `get_tomorrow_date()`)

**Required changes:**
1. Add `get_today_date()` function
2. Update `self_heal_check()` to check BOTH today AND tomorrow
3. Refactor healing logic into `heal_for_date(target_date, result)` function

**Key code changes (see project doc for full implementation):**

```python
def get_today_date():
    """Get today's date in ET timezone."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    today = datetime.now(et)
    return today.strftime("%Y-%m-%d")

@functions_framework.http
def self_heal_check(request):
    today = get_today_date()
    tomorrow = get_tomorrow_date()

    # Check TODAY first (most important)
    today_games = check_games_scheduled(bq_client, today)
    if today_games > 0:
        today_predictions, _ = check_predictions_exist(bq_client, today)
        if today_predictions == 0:
            heal_for_date(today, result)

    # Then check TOMORROW (existing behavior)
    # ... existing code ...
```

**Test after changes:**
```bash
cd orchestration/cloud_functions/self_heal
python3 main.py  # Should output checks for both dates
```

### Task 2: Deploy Self-Heal Function (P0 - 30m)

```bash
cd orchestration/cloud_functions/self_heal
gcloud functions deploy self-heal-predictions \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=. \
  --entry-point=self_heal_check \
  --trigger-http \
  --allow-unauthenticated=false \
  --service-account=756957797294-compute@developer.gserviceaccount.com \
  --timeout=540 \
  --memory=512MB
```

**Verify deployment:**
```bash
gcloud scheduler jobs run self-heal-predictions --location=us-west2
gcloud logging read 'resource.labels.function_name="self-heal-predictions"' --limit=10 --freshness=5m
```

### Task 3: Create Morning Health Check Script (P1 - 2h)

**File to create:** `bin/monitoring/daily_health_check.sh`

See project doc for full script. Key checks:
- Today's games scheduled
- Today's predictions count
- Phase 3 completion state (Firestore)
- ML Feature Store count
- Recent errors
- Service health

**After creating:**
```bash
chmod +x bin/monitoring/daily_health_check.sh
./bin/monitoring/daily_health_check.sh
```

### Task 4: Create Firestore State Query Tool (P1 - 1h)

**File to create:** `bin/monitoring/check_orchestration_state.py`

See project doc for full script. Shows:
- Phase 3 completion (X/5 processors)
- Phase 4 completion
- Stuck run_history entries

**After creating:**
```bash
chmod +x bin/monitoring/check_orchestration_state.py
PYTHONPATH=. python3 bin/monitoring/check_orchestration_state.py 2025-12-29
```

### Task 5: Create Daily Phase Status View (P1 - 30m)

Run this in BigQuery console or via CLI:

```bash
bq query --use_legacy_sql=false "
CREATE OR REPLACE VIEW \`nba-props-platform.nba_orchestration.daily_phase_status\` AS
WITH schedule AS (
  SELECT game_date, COUNT(DISTINCT game_id) as games_scheduled
  FROM \`nba_raw.nbac_schedule\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date
),
phase3_context AS (
  SELECT game_date, COUNT(*) as phase3_context_records
  FROM \`nba_analytics.upcoming_player_game_context\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date
),
phase4 AS (
  SELECT game_date, COUNT(*) as phase4_records
  FROM \`nba_predictions.ml_feature_store_v2\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date
),
phase5 AS (
  SELECT game_date, COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
  FROM \`nba_predictions.player_prop_predictions\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND is_active = TRUE
  GROUP BY game_date
)
SELECT
  s.game_date,
  s.games_scheduled,
  COALESCE(p3.phase3_context_records, 0) as phase3_context,
  COALESCE(p4.phase4_records, 0) as phase4_features,
  COALESCE(p5.predictions, 0) as predictions,
  COALESCE(p5.players, 0) as players_with_predictions,
  CASE
    WHEN COALESCE(p5.predictions, 0) > 0 THEN 'COMPLETE'
    WHEN COALESCE(p4.phase4_records, 0) > 0 THEN 'PHASE_5_PENDING'
    WHEN COALESCE(p3.phase3_context_records, 0) > 0 THEN 'PHASE_4_PENDING'
    WHEN s.games_scheduled > 0 THEN 'PHASE_3_PENDING'
    ELSE 'NO_GAMES'
  END as pipeline_status
FROM schedule s
LEFT JOIN phase3_context p3 ON s.game_date = p3.game_date
LEFT JOIN phase4 p4 ON s.game_date = p4.game_date
LEFT JOIN phase5 p5 ON s.game_date = p5.game_date
ORDER BY s.game_date DESC
"
```

**Verify:**
```bash
bq query --use_legacy_sql=false "SELECT * FROM nba_orchestration.daily_phase_status"
```

### Task 6 (Optional): Add Phase 3 Stuck Alerting (P2 - 2h)

If time permits, create a Cloud Function that:
- Runs at 1:00 PM ET
- Checks if Phase 3 completion is partial (>0 but <5)
- Sends email alert if stuck

---

## Files to Reference

| File | Purpose |
|------|---------|
| `docs/08-projects/current/same-day-pipeline-fix/README.md` | Full project doc with code |
| `docs/08-projects/current/2025-12-29-DAILY-ORCHESTRATION-POSTMORTEM.md` | Post-mortem |
| `orchestration/cloud_functions/self_heal/main.py` | Self-heal function |
| `docs/02-operations/daily-validation-checklist.md` | Validation checklist |

---

## Validation Checklist

After implementing, verify:

- [ ] Self-heal function logs show checks for BOTH today and tomorrow
- [ ] `./bin/monitoring/daily_health_check.sh` runs successfully
- [ ] `python3 bin/monitoring/check_orchestration_state.py` shows state
- [ ] `SELECT * FROM nba_orchestration.daily_phase_status` returns data
- [ ] All changes committed with descriptive messages

---

## Current State

| Item | Status |
|------|--------|
| Predictions for Dec 29 | ✅ Generated (1,700+) |
| Phase 4 service | ✅ Redeployed correctly |
| ESPN roster fix | ✅ Deployed |
| Self-heal update | ⏳ TODO |
| Health check script | ⏳ TODO |
| Firestore state tool | ⏳ TODO |
| Daily status view | ⏳ TODO |

---

## Commits from Today's Session

```
727b93c docs: Add daily orchestration post-mortem and pipeline analysis
bd7fe6e fix: Add missing storage import for ESPN roster folder handling
```

---

## Quick Commands Reference

```bash
# Check today's predictions
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date = CURRENT_DATE('America/New_York') AND is_active = TRUE"

# Check Firestore state
PYTHONPATH=. python3 -c "
from google.cloud import firestore
db = firestore.Client()
doc = db.collection('phase3_completion').document('$(date +%Y-%m-%d)').get()
print(doc.to_dict() if doc.exists else 'No doc')
"

# Trigger self-heal manually
gcloud scheduler jobs run self-heal-predictions --location=us-west2

# Check self-heal logs
gcloud logging read 'resource.labels.function_name="self-heal-predictions"' --limit=10 --freshness=10m

# Check Phase 4 health
curl -s "https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/health" | jq .
```

---

*Handoff created: December 29, 2025, 2:45 PM ET*
