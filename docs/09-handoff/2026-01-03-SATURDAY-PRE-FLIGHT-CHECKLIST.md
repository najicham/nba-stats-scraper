# ✈️ Saturday Test Day - Pre-Flight Checklist
**Date:** Saturday, January 3, 2026
**Critical Test Time:** 5:30 PM PST (8:30 PM EST)
**Purpose:** Verify betting lines flow through entire pipeline

---

## 🌅 MORNING PREP (Optional - If You Wake Up Early)

### Quick Health Check (5 min)
```bash
# Check Phase 3 is still healthy
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 --format="value(status.latestReadyRevisionName)"
# Should show: nba-phase3-analytics-processors-00051-njs or higher

# Check for critical errors overnight
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors"
  AND severity=ERROR
  AND timestamp>="2026-01-03T00:00:00Z"' --limit=5
# Look for: AttributeError about target_date/source_tracking/prop_lines
# If found: May need to redeploy
```

### Check NBA Schedule (2 min)
```bash
# How many games today?
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT game_id) as games_today
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_date = '2026-01-03'"

# Expected: 8-15 games (Saturday is busy!)
```

---

## 🕐 AFTERNOON PREP (1:00-5:00 PM PST)

### Monitor Betting Lines Collection (Starting ~11:00 AM PST)

Betting lines workflow runs throughout the day. Check it's working:

```bash
# Check raw betting lines are being collected
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_lines,
  COUNT(DISTINCT game_id) as games_covered,
  MAX(scraped_at) as latest_scrape
FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
WHERE game_date = '2026-01-03'"

# Expected throughout day:
# - total_lines increasing from 1,000 → 14,000+
# - games_covered: 8-15
# - latest_scrape: Recent timestamp
```

---

## 🎯 THE CRITICAL TEST (5:30 PM PST)

### Before You Start
- [ ] Games have started (most start 4:00-7:00 PM PST)
- [ ] Betting lines collected (check query above shows 12,000+)
- [ ] You have 30-45 min uninterrupted time
- [ ] Coffee/water ready ☕

### Step 1: Run Full Pipeline (5:30 PM PST)
```bash
cd /home/naji/code/nba-stats-scraper

# THE MONEY COMMAND
./bin/pipeline/force_predictions.sh 2026-01-03

# This kicks off:
# Phase 1→2: Process raw data
# Phase 3: Merge betting lines ← THE FIX WE'RE TESTING
# Phase 4: Precompute
# Phase 5: Generate predictions
# Phase 6: Publish to API

# Watch for completion (usually 5-10 min)
```

### Step 2: Verify Betting Lines in ALL Layers (5:40 PM PST)
```bash
# ONE QUERY TO CHECK EVERYTHING
bq query --use_legacy_sql=false --format=pretty "
SELECT
  'Raw' as layer,
  COUNT(*) as count,
  'betting_lines' as metric
FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\`
WHERE game_date = '2026-01-03'

UNION ALL

SELECT
  'Analytics' as layer,
  COUNTIF(has_prop_line) as count,
  'players_with_lines' as metric
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = '2026-01-03'

UNION ALL

SELECT
  'Predictions' as layer,
  COUNTIF(current_points_line IS NOT NULL) as count,
  'predictions_with_lines' as metric
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date = '2026-01-03'
  AND system_id = 'ensemble_v1'

UNION ALL

SELECT
  'Frontend' as layer,
  COUNT(*) as count,
  'total_records' as metric
FROM \`nba-props-platform.nba_frontend.tonight_all_players\`
WHERE game_date = '2026-01-03'
"

# EXPECTED RESULTS:
# Layer      | Count   | Metric
# -----------+---------+----------------------
# Raw        | 12,000+ | betting_lines
# Analytics  | 100-150 | players_with_lines    ← KEY WIN
# Predictions| 100-150 | predictions_with_lines ← KEY WIN
# Frontend   | 200-300 | total_records
```

### Step 3: Check Frontend API (5:45 PM PST)
```bash
# Fetch public API
curl -s "https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
total = len(data.get('players', []))
with_lines = len([p for p in data.get('players', []) if p.get('betting_line')])
print(f'Game Date: {data.get(\"game_date\")}')
print(f'Total Players: {total}')
print(f'With Betting Lines: {with_lines}')
print(f'Coverage: {with_lines/total*100:.1f}%' if total > 0 else 'N/A')
"

# EXPECTED OUTPUT:
# Game Date: 2026-01-03
# Total Players: 200-300
# With Betting Lines: 100-150  ← THE CRITICAL NUMBER!
# Coverage: 40-60%
```

---

## ✅ SUCCESS CRITERIA

### PASS = All of these are TRUE:
- [ ] Raw table: 12,000+ betting lines ✅
- [ ] Analytics: 100+ players with `has_prop_line = TRUE` ✅
- [ ] Predictions: 100+ players with `current_points_line != NULL` ✅
- [ ] Frontend API: `with_lines > 100` ✅

**If all pass:** 🎉 BETTING LINES PIPELINE IS COMPLETE!

### PARTIAL PASS = Some layers missing:
- [ ] Raw has lines BUT Analytics doesn't → Phase 3 issue
- [ ] Analytics has lines BUT Predictions doesn't → Phase 5 issue
- [ ] Predictions has lines BUT Frontend doesn't → Phase 6 issue

**Action:** Debug the failing phase (see debugging section below)

### FAIL = No betting lines anywhere:
- [ ] Raw table has < 1,000 lines → Scraper issue
- [ ] All layers empty → Pipeline didn't run

**Action:** Check workflow logs, verify schedule

---

## 🚨 DEBUGGING GUIDE

### Issue: Analytics Layer Has 0 Players with Lines

**Most Likely:** Phase 3 AttributeError returned

```bash
# Check Phase 3 logs for errors
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors"
  AND severity=ERROR
  AND timestamp>="2026-01-03T17:00:00Z"' \
  --limit=10

# Look for: AttributeError about target_date, source_tracking, prop_lines
# If found: Our fix didn't work, need to investigate
```

**Quick Check:**
```bash
# Did Phase 3 even run?
bq query --use_legacy_sql=false "
SELECT processor_name, status, triggered_at, error_message
FROM \`nba-props-platform.nba_orchestration.processor_execution_log\`
WHERE processor_name = 'UpcomingPlayerGameContextProcessor'
  AND DATE(triggered_at) = '2026-01-03'
ORDER BY triggered_at DESC
LIMIT 5"
```

---

### Issue: Predictions Layer Has 0 Lines

**Most Likely:** Analytics succeeded but Phase 5 didn't pick up the data

```bash
# Check prediction coordinator logs
gcloud logging read 'resource.labels.service_name="prediction-coordinator"
  AND timestamp>="2026-01-03T17:00:00Z"' \
  --limit=20

# Check if batch completed
gcloud logging read 'resource.labels.service_name="prediction-coordinator"
  AND textPayload=~"Batch.*complete"
  AND timestamp>="2026-01-03T17:00:00Z"' \
  --limit=5
```

---

### Issue: Frontend API Has 0 Lines

**Most Likely:** Phase 6 publishing issue

```bash
# Check Phase 6 logs
bq query --use_legacy_sql=false "
SELECT processor_name, status, triggered_at, records_published
FROM \`nba-props-platform.nba_orchestration.processor_execution_log\`
WHERE processor_name = 'TonightPublisher'
  AND DATE(triggered_at) = '2026-01-03'
ORDER BY triggered_at DESC
LIMIT 5"

# Check GCS bucket
gsutil ls gs://nba-props-platform-api/v1/tonight/
# Should show: all-players.json with recent timestamp
```

---

## 📝 DOCUMENTATION CHECKLIST

### After Test Completes (Win or Lose)

**If SUCCESS:**
```bash
# Create success doc
cat > docs/09-handoff/2026-01-03-BETTING-LINES-TEST-SUCCESS.md << 'EOF'
# 🎉 Betting Lines Pipeline - SUCCESS!

**Date:** Saturday, Jan 3, 2026 - 5:30 PM PST
**Test Duration:** XX minutes
**Result:** PASS ✅

## Results

Raw Layer: X,XXX betting lines
Analytics Layer: XXX players with lines
Predictions Layer: XXX predictions with lines
Frontend API: XXX players with betting lines

## Next Steps

- [x] Betting lines pipeline COMPLETE
- [ ] Monitor for 24-48 hours
- [ ] Tomorrow: Tune hand-coded ML rules (1-2 hours)
- [ ] Next week: Hybrid ML approach

**Pipeline is PRODUCTION READY!** 🚀
EOF
```

**If FAILURE:**
```bash
# Create debugging doc
cat > docs/09-handoff/2026-01-03-BETTING-LINES-TEST-FAILED.md << 'EOF'
# ⚠️ Betting Lines Pipeline - Issues Found

**Date:** Saturday, Jan 3, 2026 - 5:30 PM PST
**Result:** FAIL ❌

## What Failed

- [ ] Raw layer: X lines (expected 12,000+)
- [ ] Analytics layer: X players (expected 100+)
- [ ] Predictions layer: X predictions (expected 100+)
- [ ] Frontend API: X players (expected 100+)

## Error Details

[Paste error logs here]

## Root Cause

[Analysis of what went wrong]

## Fix Applied

[What was done to fix it]

## Retest Results

[Results after fix]
EOF
```

---

## 🎯 AFTER THE TEST

### If PASS (Pipeline Works!)

**Immediate:**
- [ ] Document success (template above)
- [ ] Celebrate! 🎉
- [ ] Monitor for anomalies over next 24h

**Tomorrow (Sunday):**
- [ ] Rest day OR
- [ ] Optional: Start ML rule tuning (1-2 hours)

**Next Week:**
- [ ] ML rule tuning to beat 4.27 MAE
- [ ] Hybrid ML approach planning
- [ ] Data quality investigation

---

### If FAIL (Pipeline Has Issues)

**Immediate:**
- [ ] Document failure (template above)
- [ ] Analyze root cause
- [ ] Apply fix if obvious
- [ ] Retest

**Tomorrow:**
- [ ] Deep dive on root cause
- [ ] Fix implementation
- [ ] Comprehensive retest

---

## ⏰ TIME ESTIMATES

- Morning prep: 5-10 min (optional)
- Afternoon monitoring: 5 min checks every hour
- Critical test: 30-45 min total
  - Run pipeline: 5-10 min
  - Verify results: 10-15 min
  - Check API: 5 min
  - Document: 10-15 min

**Total active time:** ~1 hour

---

## 🔑 KEY FILES

**Test Commands:**
- All commands in this file (copy-paste ready)

**Background Context:**
- `docs/09-handoff/START-HERE-JAN-3.md`
- `docs/09-handoff/2026-01-03-CRITICAL-FIXES-SESSION-HANDOFF.md`

**If Issues:**
- `docs/09-handoff/2026-01-03-BETTING-LINES-PIPELINE-FIX.md` (root cause analysis)

---

## 💡 PRO TIPS

1. **Don't test too early** - Wait until games start (4-7 PM PST)
2. **Don't test too late** - Betting lines close ~7:30 PM PST
3. **5:30 PM PST is the sweet spot** - Mid-game, lines are stable
4. **Copy-paste commands** - Don't type them out, avoid typos
5. **Take screenshots** - Especially of the success verification query
6. **Stay calm** - If something fails, we have debugging guides

---

**Good luck tomorrow! 🍀**

You've got this. The fix is deployed, everything is ready. Just follow this checklist step-by-step and you'll know definitively if the betting lines pipeline works.

**Remember:** 5:30 PM PST = Critical test time

**END OF PRE-FLIGHT CHECKLIST**
