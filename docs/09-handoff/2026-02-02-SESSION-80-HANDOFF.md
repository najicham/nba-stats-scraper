# Session 80 Handoff - February 2, 2026

## Session Summary

Verified system status on Super Bowl Sunday. Fixed missing team context scheduler bug. Deleted redundant Pub/Sub subscription causing 400 error spam. Deployed scrapers with Kalshi fixes. Analyzed V9 model variants.

---

## Fixes Applied

### 1. Team Context Scheduler Bug Fixed ✅
**Problem:** `UpcomingTeamGameContextProcessor` was missing from same-day schedulers, causing team context to not be generated for today/tomorrow's games.

**Fix:** Updated both schedulers to include team context:
```bash
gcloud scheduler jobs update http same-day-phase3 --location=us-west2 \
  --message-body='{"start_date": "TODAY", "end_date": "TODAY", "processors": ["UpcomingPlayerGameContextProcessor", "UpcomingTeamGameContextProcessor"], "backfill_mode": true}'

gcloud scheduler jobs update http same-day-phase3-tomorrow --location=us-west2 \
  --message-body='{"start_date": "TOMORROW", "end_date": "TOMORROW", "processors": ["UpcomingPlayerGameContextProcessor", "UpcomingTeamGameContextProcessor"], "backfill_mode": true}'
```

**Result:** Team context now generated for Feb 2 (8 records) and Feb 3 (20 records).

### 2. Phase 4 400 Error Spam Fixed ✅
**Problem:** Redundant Pub/Sub subscription `nba-phase3-analytics-complete-sub` was pushing to `/process` endpoint with wrong payload format, causing continuous 400 errors.

**Root Cause:** Two subscriptions existed for the same topic:
- `eventarc-...-phase3-to-phase4-orchestrator-...-sub-494` → Working correctly
- `nba-phase3-analytics-complete-sub` → Failing with 400s (redundant)

**Fix:** Deleted the redundant subscription:
```bash
gcloud pubsub subscriptions delete nba-phase3-analytics-complete-sub
```

### 3. Scrapers Deployed ✅
`nba-scrapers` revision `00122-pgz` (commit `328eace0`) deployed with:
- Kalshi scraper GCS export fix
- Kalshi player props registration
- ESPN roster syntax fix
- Player list scraper season fix

---

## Key Findings

### V9 Model Clarification
There are **two V9 models** running in parallel:

| Model | system_id | Training Window | Status |
|-------|-----------|-----------------|--------|
| V9 Original | `catboost_v9` | Nov 2 - Jan 8, 2026 | Production champion |
| V9 Feb Monthly | `catboost_v9_2026_02` | Nov 2 - Jan 24, 2026 | New challenger (started Feb 2) |

**Note:** Another session deployed a newer model version during this session.

### Feb 2 All-UNDER Signal
- **50 UNDER predictions**, 10 PASS, 0 OVER (avg edge -4.0 points)
- Two consecutive RED signal days (Feb 1: 15.5% OVER, Feb 2: 0% OVER)
- Games not yet completed - validate after games finish

### System Health After Fixes
| Component | Status | Notes |
|-----------|--------|-------|
| Feature Store | ✅ | 148 players (today) |
| Feb 2 Predictions | ✅ | 544 active |
| Team Context | ✅ Fixed | Feb 2: 8, Feb 3: 20 records |
| Shot Zones | ✅ | 88-94% complete |
| Phase 4 Errors | ✅ Fixed | Subscription deleted |
| Deployments | ✅ | All up to date |

---

## Current System State

### Model Performance (V9 Original)
| Metric | Value |
|--------|-------|
| 7-day overall hit rate | 52.9% (478 bets) |
| 7-day high-edge hit rate | 63.0% |
| 14-day high-edge hit rate | 73.6% (53 bets) |

### Feb 3 Schedule
10 games: DEN@DET, UTA@IND, NYK@WAS, LAL@BKN, ATL@MIA, BOS@DAL, CHI@MIL, ORL@OKC, PHI@GSW, PHX@POR

---

## Priority Tasks for Next Session

### P1: Check Feb 2 Results (After Games Complete)
```sql
SELECT recommendation, COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date = DATE('2026-02-02') AND system_id = 'catboost_v9'
GROUP BY 1;
```

### P2: Verify Feb 3 prediction_run_mode Tracking
After 2:30 AM ET:
```sql
SELECT prediction_run_mode, FORMAT_TIMESTAMP('%H:%M', created_at, 'America/New_York') as time_ET, COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE game_date = DATE('2026-02-03') AND system_id = 'catboost_v9'
GROUP BY 1, 2 ORDER BY time_ET;
```

### P3: Compare V9 Model Performance
Once Feb 2 games complete, compare `catboost_v9` vs `catboost_v9_2026_02`:
```sql
SELECT system_id, COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date = DATE('2026-02-02')
  AND system_id IN ('catboost_v9', 'catboost_v9_2026_02')
GROUP BY 1;
```

---

## Quick Start for Next Session

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-02-02-SESSION-80-HANDOFF.md

# 2. Run daily validation
/validate-daily

# 3. Check Feb 2 results (after games finish ~midnight ET)
bq query --use_legacy_sql=false "
SELECT recommendation, COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE game_date = DATE('2026-02-02') AND system_id = 'catboost_v9'
GROUP BY 1"
```

---

## Key Learnings

1. **Check scheduler payloads, not just existence** - The team context scheduler existed but was missing the processor from its payload

2. **Duplicate Pub/Sub subscriptions cause retry storms** - When migrating to Eventarc, old manual subscriptions should be deleted

3. **Multiple model versions run in parallel** - V9 Original and V9 Feb Monthly both generate predictions; track system_id carefully

4. **Super Bowl Sunday = fewer games** - Only 4 games vs normal 10+, games start later

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
