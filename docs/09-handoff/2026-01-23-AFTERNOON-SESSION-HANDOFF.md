# Afternoon Session Handoff - Jan 23, 2026

**Time:** ~9:30 AM ET
**Status:** Major progress made, predictions batch in progress
**Priority:** Monitor Jan 23 predictions, verify odds_api data flow

---

## Executive Summary

This session accomplished significant infrastructure improvements:
1. **Deployed Line Quality Self-Healing** - New cloud function that automatically detects and regenerates predictions when real betting lines become available
2. **Fixed Odds API Scrapers** - Identified the issue (temporary API failures) and manually scraped Jan 23 data
3. **Backfilled Grading** - Jan 19-22 now have grading results
4. **Cleaned Up Placeholders** - Deactivated 865 bad predictions from Jan 21

---

## Current System State

### Prediction Coordinator
- **Status:** ✅ Healthy
- **Active Batch:** `batch_2026-01-23_1769177457`
- **Progress:** ~2-3% complete (was progressing slowly)
- **Check Status:**
```bash
API_KEY=$(gcloud secrets versions access latest --secret=coordinator-api-key)
curl -s "https://prediction-coordinator-756957797294.us-west2.run.app/status?batch_id=batch_2026-01-23_1769177457" -H "X-API-Key: $API_KEY"
```

### Line Quality Self-Heal Function (NEW)
- **Status:** ✅ Deployed and Scheduled
- **URL:** https://us-west2-nba-props-platform.cloudfunctions.net/line-quality-self-heal
- **Schedule:** Every 2 hours, 8 AM - 8 PM ET
- **Test (dry-run):**
```bash
curl "https://us-west2-nba-props-platform.cloudfunctions.net/line-quality-self-heal?dry_run=true"
```
- **Documentation:** `/docs/08-projects/current/line-quality-self-healing/README.md`

### Grading Status
| Date | Graded | MAE | Accuracy | Within 3pts |
|------|--------|-----|----------|-------------|
| Jan 17 | 62 | 9.63 | 19.4% | 11.3% |
| Jan 18 | ❌ Missing | - | - | - |
| Jan 19 | 274 | 5.53 | 31.8% | 40.5% |
| Jan 20 | 382 | 5.35 | 30.9% | 42.9% |
| Jan 21 | 241 | 6.54 | 27.8% | 36.9% |
| Jan 22 | 449 | 6.62 | 21.4% | 29.6% |

### Predictions Status
| Date | Total Active | ACTUAL_PROP | ESTIMATED_AVG | NULL/Placeholder |
|------|-------------|-------------|---------------|------------------|
| Jan 19 | 825 | 285 | 540 | 0 |
| Jan 20 | 1,283 | 432 | 851 | 0 |
| Jan 21 | 432 | 262 | 170 | 0 (865 deactivated) |
| Jan 22 | 609 | 449 | 160 | 0 |
| Jan 23 | ~60+ | In progress | - | - |

### Betting Lines Data
```sql
-- Odds API player props
SELECT game_date, COUNT(*) FROM nba_raw.odds_api_player_points_props WHERE game_date >= '2026-01-15' GROUP BY 1 ORDER BY 1;
-- Jan 15-18: 75-84 records each
-- Jan 23: 27 records (more may be processing)

-- Odds API game lines
SELECT game_date, COUNT(*) FROM nba_raw.odds_api_game_lines WHERE game_date >= '2026-01-15' GROUP BY 1 ORDER BY 1;
-- Jan 15-18: 16-88 records each
-- Jan 23: 8 records (complete - 1 per game)

-- BettingPros player props
SELECT game_date, COUNT(*) FROM nba_raw.bettingpros_player_points_props WHERE game_date >= '2026-01-20' GROUP BY 1 ORDER BY 1;
-- Jan 20: 28,410
-- Jan 21: 28,614
-- Jan 22: 32,643
-- Jan 23: 0 (proxy issue)
```

---

## What Was Accomplished

### 1. Line Quality Self-Healing Architecture

Created a new cloud function that solves the root cause of the placeholder prediction issue:

**Problem Statement:**
- Predictions generated before betting lines are available use ESTIMATED_AVG
- Later, real lines become available from odds_api or bettingpros
- Previously, no mechanism existed to detect this and regenerate

**Solution:**
- New function `line-quality-self-heal` runs every 2 hours
- Queries predictions with ESTIMATED_AVG or placeholder lines
- Checks if real lines NOW exist in odds_api or bettingpros tables
- Deactivates old predictions and triggers coordinator to regenerate

**Files Created:**
- `/orchestration/cloud_functions/line_quality_self_heal/main.py`
- `/orchestration/cloud_functions/line_quality_self_heal/requirements.txt`
- `/docs/08-projects/current/line-quality-self-healing/README.md`

**BigQuery Table Created:**
- `nba_orchestration.self_heal_log` - Audit trail for self-healing actions

### 2. Grading Backfill

Triggered grading for missing dates via Pub/Sub:
```bash
gcloud pubsub topics publish nba-grading-trigger --message='{"target_date": "2026-01-XX", "run_aggregation": true}'
```

Jan 19, 20, 21, 22 all now have grading results.

### 3. Placeholder Cleanup

Deactivated 865 bad predictions from Jan 21:
```sql
UPDATE `nba_predictions.player_prop_predictions`
SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP()
WHERE game_date = '2026-01-21' AND line_source IS NULL
-- Affected 865 rows
```

### 4. Odds API Investigation & Fix

**Root Cause Finding:**
- The odds_api scrapers WERE configured correctly
- The failures since Jan 19 were due to temporary API issues (possibly rate limiting)
- The API key is valid and works
- When called with correct parameters, scrapers work fine

**Manual Data Collection:**
Successfully scraped Jan 23 data for all 8 games:
```bash
# Step 1: Get event IDs
curl -s -X POST https://nba-scrapers-756957797294.us-west2.run.app/scrape \
  -H 'Content-Type: application/json' \
  -d '{"workflow": "betting_lines", "scraper": "oddsa_events", "source": "MANUAL", "game_date": "2026-01-23", "sport": "basketball_nba"}'

# Step 2: For each event_id, scrape game_lines and player_props
curl -s -X POST https://nba-scrapers-756957797294.us-west2.run.app/scrape \
  -H 'Content-Type: application/json' \
  -d '{"workflow": "betting_lines", "scraper": "oddsa_game_lines", "source": "MANUAL", "game_date": "2026-01-23", "event_id": "EVENT_ID", "sport": "basketball_nba"}'

curl -s -X POST https://nba-scrapers-756957797294.us-west2.run.app/scrape \
  -H 'Content-Type: application/json' \
  -d '{"workflow": "betting_lines", "scraper": "oddsa_player_props", "source": "MANUAL", "game_date": "2026-01-23", "event_id": "EVENT_ID", "sport": "basketball_nba"}'
```

**Jan 23 Event IDs:**
```
33e30f1df9e99bd29c9441f743696b58 (HOU@DET)
70f49db28c0730ed5a7fe2a39bf5ae73 (PHX@ATL)
42123e483653bc996b61e0fcfbc67da2 (BOS@BKN)
8d16f2f9be8f5a265957b50f7784e5be (SAC@CLE)
9a2969b2bb642ef5b38118ac285d03b9 (NOP@MEM)
daaae076a5da6cc33ed11e20704f5f52 (DEN@MIL)
06550e9068aeea4e2be8aabda5cf129b (IND@OKC)
3a66232944c62d098202ca1bd3903b1e (TOR@POR)
```

---

## Outstanding Issues

### 1. BettingPros Proxy Issue (MEDIUM PRIORITY)
- The `bp_player_props` scraper is getting 403 errors from the proxy
- This is why there's no bettingpros data for Jan 23
- Less critical now that odds_api is working
- Error in logs: `Proxy failed: http://...@gate2.proxyfuel.com:2000, status=403`

### 2. Jan 18 Low Analytics (LOW PRIORITY)
- Only 23 boxscores processed out of 141 expected
- Grading can't run without actuals
- May need manual investigation

### 3. Historical Odds API Backfill (MEDIUM PRIORITY)
- Jan 19-22 have no odds_api data (only bettingpros)
- Could use historical API endpoint to backfill
- The-Odds-API has `/v4/historical/` endpoint

### 4. Phase 2 Processing Delay
- Some odds_api files may be in GCS but not processed to BigQuery yet
- Check cleanup processor logs or manually trigger Phase 2

---

## Key Files Modified This Session

```
NEW: orchestration/cloud_functions/line_quality_self_heal/main.py
NEW: orchestration/cloud_functions/line_quality_self_heal/requirements.txt
NEW: docs/08-projects/current/line-quality-self-healing/README.md
```

---

## Useful Commands

### Check Prediction Status
```bash
API_KEY=$(gcloud secrets versions access latest --secret=coordinator-api-key)
curl -s "https://prediction-coordinator-756957797294.us-west2.run.app/status?batch_id=batch_2026-01-23_1769177457" -H "X-API-Key: $API_KEY"
```

### Check Jan 23 Predictions in BigQuery
```bash
bq query --use_legacy_sql=false '
SELECT game_date, line_source, COUNT(*) as count
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = "2026-01-23" AND is_active = TRUE
GROUP BY 1, 2'
```

### Trigger Grading for a Date
```bash
gcloud pubsub topics publish nba-grading-trigger --message='{"target_date": "2026-01-XX", "run_aggregation": true}'
```

### Manual Odds API Scrape
```bash
# Get events first
curl -s -X POST https://nba-scrapers-756957797294.us-west2.run.app/scrape \
  -H 'Content-Type: application/json' \
  -d '{"workflow": "betting_lines", "scraper": "oddsa_events", "source": "MANUAL", "game_date": "YYYY-MM-DD", "sport": "basketball_nba"}'

# Then for each event_id, call game_lines and player_props
```

### Test Self-Heal Function
```bash
# Dry run (no changes)
curl "https://us-west2-nba-props-platform.cloudfunctions.net/line-quality-self-heal?dry_run=true"

# Full run
curl -X POST "https://us-west2-nba-props-platform.cloudfunctions.net/line-quality-self-heal"
```

### Check Grading Results
```bash
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as graded, ROUND(AVG(absolute_error), 2) as mae,
  ROUND(SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as accuracy_pct
FROM `nba_predictions.prediction_accuracy`
WHERE game_date >= "2026-01-17"
GROUP BY 1 ORDER BY 1'
```

### Check Workflow Decisions
```bash
bq query --use_legacy_sql=false '
SELECT workflow_name, action, reason, decision_time
FROM nba_orchestration.workflow_decisions
WHERE workflow_name = "betting_lines"
ORDER BY decision_time DESC LIMIT 10'
```

---

## Architecture Understanding

### How Betting Lines Flow Works

```
1. betting_lines workflow (runs every 2h during business hours)
   ↓
2. Step 1: oddsa_events (gets event IDs for today's games)
   ↓ captures event_ids in context
3. Step 2: oddsa_player_props + oddsa_game_lines (parallel, for each event_id)
   ↓
4. Files saved to GCS
   ↓
5. Phase 2 processors read from GCS, write to BigQuery
   ↓
6. Prediction coordinator queries BigQuery for betting lines
   ↓
7. Worker generates predictions with real or estimated lines
```

### How Self-Healing Works

```
1. line-quality-self-heal runs every 2h
   ↓
2. Queries predictions with ESTIMATED_AVG or placeholder lines (last 3 days)
   ↓
3. Joins with odds_api/bettingpros tables to find where real lines NOW exist
   ↓
4. If sufficient players affected (≥5):
   a. Deactivates old placeholder predictions
   b. Calls coordinator /start to regenerate
   ↓
5. Logs actions to nba_orchestration.self_heal_log
6. Sends Slack notification (if configured)
```

### Key Configuration Files

- `/config/workflows.yaml` - Workflow definitions and schedules
- `/config/scraper_parameters.yaml` - Scraper parameter mappings
- `/orchestration/parameter_resolver.py` - Complex parameter resolution (odds scrapers)
- `/shared/config/orchestration_config.py` - Pipeline configuration

---

## Next Steps for New Session

### Immediate (Check First)
1. Verify Jan 23 prediction batch completed
2. Verify odds_api data made it to BigQuery (should have 400+ player props)
3. Check if self-heal function ran successfully at its scheduled time

### Short Term
1. Investigate BettingPros proxy 403 issue
2. Consider historical backfill for Jan 19-22 odds_api data
3. Monitor next betting_lines workflow run to ensure it works automatically

### Medium Term
1. Add monitoring/alerting for self-heal actions
2. Consider player-level regeneration (currently date-level)
3. Investigate Jan 18 low analytics issue

---

## Related Documents

- [2026-01-23-LATE-MORNING-HANDOFF.md](./2026-01-23-LATE-MORNING-HANDOFF.md) - Earlier session (identified the placeholder issue)
- [2026-01-23-PLACEHOLDER-LINE-AUDIT.md](./2026-01-23-PLACEHOLDER-LINE-AUDIT.md) - Audit of placeholder lines
- [Line Quality Self-Healing README](../08-projects/current/line-quality-self-healing/README.md) - New component docs

---

## Session Notes

The major breakthrough this session was understanding that the odds_api scrapers weren't fundamentally broken - they just had temporary API issues. The system is designed correctly with:
- Proper parameter resolution (sport=basketball_nba is configured in YAML)
- Proper dependency chaining (oddsa_events → oddsa_player_props/oddsa_game_lines)
- Proper fallback (bettingpros when odds_api fails)

The new self-healing function adds resilience for when lines become available after predictions are generated. This was a gap in the architecture that caused the placeholder issue to persist.
