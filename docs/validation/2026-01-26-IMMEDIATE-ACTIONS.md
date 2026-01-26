# Immediate Actions Required - 2026-01-26

**Time:** 10:25 AM ET
**Urgency:** 🔴 CRITICAL - 8 hours until games start
**Status:** Pipeline completely stalled

---

## TL;DR

**The betting data scrapers (odds_api) failed to collect prop lines and game lines overnight. Without this data, Phase 3 cannot create game context, blocking the entire prediction pipeline.**

**Fix Priority:** P0 - Must fix within next 2 hours

---

## Critical Blockers (Fix Immediately)

### 1. Missing Prop Lines (P0 - 30 min)

**Problem:** `odds_api_player_points_props` has 0 records for today

**Expected:** 200-300 player prop lines for 7 games
**Actual:** 0 records

**Actions:**
```bash
# Check scraper logs
gcloud logging read \
  'resource.type=cloud_run_revision
   AND resource.labels.service_name=odds-api-player-props-scraper
   AND timestamp>="2026-01-26T00:00:00Z"' \
  --limit 100 --format json | jq '.[] | {timestamp, textPayload, severity}'

# Manual trigger
python orchestration/manual_trigger.py \
  --scraper odds_api_player_points_props \
  --date 2026-01-26 \
  --force
```

---

### 2. Missing Game Lines (P0 - 30 min)

**Problem:** `odds_api_game_lines` has 0 records for today

**Expected:** ~70 game line records (7 games × 10 sportsbooks)
**Actual:** 0 records

**Actions:**
```bash
# Check scraper logs
gcloud logging read \
  'resource.type=cloud_run_revision
   AND resource.labels.service_name=odds-api-game-lines-scraper
   AND timestamp>="2026-01-26T00:00:00Z"' \
  --limit 100 --format json | jq '.[] | {timestamp, textPayload, severity}'

# Manual trigger
python orchestration/manual_trigger.py \
  --scraper odds_api_game_lines \
  --date 2026-01-26 \
  --force
```

---

### 3. Phase 3 Not Running (P0 - 15 min after data fixes)

**Problem:** Zero records in upcoming_player_game_context and upcoming_team_game_context

**Expected:**
- 14 team context records (2 per game)
- 200-300 player context records (all rostered players with games tonight)

**Actual:** 0 records in both tables

**Diagnosis Steps:**
```bash
# 1. Check Phase 2 → Phase 3 Pub/Sub trigger
gcloud pubsub topics list --filter="name:nba-phase2"

# 2. Check subscription backlog
gcloud pubsub subscriptions describe nba-phase3-analytics-sub

# 3. Check for stuck messages (don't ack)
gcloud pubsub subscriptions pull nba-phase3-analytics-sub \
  --limit=10 \
  --auto-ack=false

# 4. Check Phase 3 processor logs
gcloud logging read \
  'resource.type=cloud_run_revision
   AND resource.labels.service_name=upcoming-player-game-context-processor
   AND timestamp>="2026-01-26T00:00:00Z"' \
  --limit 50
```

**Manual Trigger (if Pub/Sub broken):**
```bash
# Option A: Trigger all Phase 3 processors
python orchestration/manual_trigger_phase3.py --date 2026-01-26

# Option B: Trigger individual processors
python data_processors/analytics/upcoming_player_game_context/trigger.py \
  --date 2026-01-26 \
  --mode daily

python data_processors/analytics/upcoming_team_game_context/trigger.py \
  --date 2026-01-26 \
  --mode daily
```

---

## Validation After Fixes

**After completing each fix, run:**
```bash
# Quick validation
python scripts/validate_tonight_data.py --date 2026-01-26

# Full pipeline check
python bin/validate_pipeline.py 2026-01-26
```

**Expected Results:**
```
✅ odds_api_player_points_props: 200-300 records
✅ odds_api_game_lines: ~70 records
✅ upcoming_player_game_context: 200-300 records (has_prop_line flag set correctly)
✅ upcoming_team_game_context: 14 records
✅ API exports: 2026-01-26 date
```

---

## Secondary Actions (Can Wait Until After Games)

### 4. Fix Proxy Infrastructure (P1 - 20 min)

**Problem:** cdn.nba.com and statsdmz.nba.com degraded/blocked

**Impact:** Limits post-game data collection tonight

**Actions:**
```bash
# Rotate proxy pool
python orchestration/proxy_manager.py --rotate-pool --target cdn.nba.com
python orchestration/proxy_manager.py --rotate-pool --target statsdmz.nba.com

# Verify success rates
python scripts/check_proxy_health.py --last 24h
```

---

### 5. Monitor GSW Game Specifically (P1)

**Problem:** GSW/SAC game context was missing yesterday (2026-01-25)

**Tonight's Game:** GSW @ MIN

**Actions:**
```bash
# After Phase 3 runs, verify GSW players present
bq query --use_legacy_sql=false --location=us-west2 "
SELECT
  COUNT(*) as gsw_player_count,
  COUNT(DISTINCT player_lookup) as unique_players
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = '2026-01-26'
  AND (team_abbr = 'GSW' OR opponent_team_abbr = 'GSW')
"

# Expected: ~30 players (15 GSW + 15 MIN)
# If 0: GSW issue has recurred
```

---

## Timeline

### NOW (10:25 AM)
- [ ] Fix odds_api_player_points_props scraper
- [ ] Fix odds_api_game_lines scraper

### 11:00 AM
- [ ] Verify betting data collected
- [ ] Trigger Phase 3 processors manually if needed

### 11:30 AM
- [ ] Validate Phase 3 completion
- [ ] Verify 200-300 player context records created

### 12:00 PM (Noon)
- [ ] Final validation before games start
- [ ] Monitor API export timestamp update

### 7:00 PM (Games Start)
- [ ] Phase 2 post-game scrapers ready
- [ ] Monitor boxscore collection

### 11:00 PM (Games End)
- [ ] Phase 3 post-game processors run
- [ ] Phase 4 precompute starts

### Midnight
- [ ] Phase 5 predictions run
- [ ] Phase 6 exports update

### Tomorrow 6:00 AM
- [ ] Validate predictions available
- [ ] Users receive updated prop predictions

---

## Escalation

**Contact:** Platform team
**Reason:** Repeat failure pattern from 2026-01-25
**Evidence:** Identical symptoms (missing betting data, zero game context)
**Implication:** Yesterday's remediation did not fix root cause

**Questions for Platform Team:**
1. Did odds_api scraper config change overnight?
2. Is there API rate limiting or quota issue with Odds API?
3. Is the Phase 2 → Phase 3 Pub/Sub trigger chain healthy?
4. Should we add alerting when Phase 2 scrapers return 0 records?

---

## Success Criteria

**Pipeline Ready for Tonight's Games:**
- ✅ Pre-game betting data collected (props + lines)
- ✅ Pre-game game context created (team + player)
- ✅ API exports updated with 2026-01-26 data
- ✅ Post-game scraping ready (proxy infrastructure healthy)

**Tomorrow Morning:**
- ✅ Predictions generated for all players with prop lines
- ✅ No cascade failures in Phase 4 or Phase 5
- ✅ API exports serving fresh predictions

---

**Last Updated:** 2026-01-26 10:25 AM ET
**Next Check:** After betting data scrapers fixed (11:00 AM target)
