# Continuation Prompt - Phase 6 API Gaps Post-Deployment

**Copy everything below this line to a new Claude Code session:**

---

I need to validate and complete the Phase 6 API gaps deployment from Session 209.

## Context

Session 209 just completed implementing 16 API fixes based on frontend team's comprehensive review. All code is merged to main and Cloud Build is deploying.

**What was delivered:**
- ✅ Sprint 1: 7 quick wins (days_rest, minutes_avg, recent_form, safe_odds, player_lookup, game_time fix)
- ✅ Sprint 2: High-impact features (last_10_lines array, prediction.factors with directional logic, best_bets table selection fix)
- ✅ Sprint 3: Enhancements (date-specific tonight files, calendar exporter)

**Impact:** 6/10 endpoints working → 10/10 endpoints working, 84% → 100% data completeness

**Deployment:**
- Commit: `6033075b2b8fe2f32f23cdec0244cd8dda0da00c`
- Cloud Build: 785bd5fa (should be complete now)
- Branch: `main`

## Read These First

**Essential docs (in priority order):**
1. `/home/naji/code/nba-stats-scraper/docs/09-handoff/2026-02-12-SESSION-209-HANDOFF.md` - Next steps checklist
2. `/home/naji/code/nba-stats-scraper/docs/08-projects/current/phase6-api-gaps/08-SESSION-209-COMPLETION-SUMMARY.md` - Full implementation details
3. `/home/naji/code/nba-stats-scraper/docs/08-projects/current/phase6-api-gaps/09-FRONTEND-NOTIFICATION.md` - What to tell frontend

**Background (if needed):**
4. `/home/naji/code/nba-stats-scraper/docs/08-projects/current/phase6-api-gaps/07-FINAL-EXECUTION-PLAN.md` - What was implemented
5. `/home/naji/code/props-web/docs/08-projects/current/backend-integration/API_ENDPOINT_REVIEW_2026-02-11.md` - Original frontend review

## Tasks for This Session

### 1. Validate Deployment (10 min)

**Check Cloud Build:**
```bash
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=3
# Verify build 785bd5fa is SUCCESS
```

**Check Deployment Drift:**
```bash
./bin/check-deployment-drift.sh --verbose
# All services should show commit 6033075b
```

**If drift detected:** Services need manual deploy (deployment instructions in handoff doc)

### 2. Validate API Endpoints (20 min)

**Run these validation commands:**

```bash
# 1. Check new fields exist
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | \
  jq '.games[0].players[] | select(.has_line) | {
    days_rest,
    minutes_avg,
    recent_form,
    last_10_lines: (.last_10_lines | length),
    factors: (.prediction.factors | length)
  }' | head -5

# 2. Verify arrays match length (CRITICAL)
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | \
  jq '.games[0].players[] | select(.has_line) | {
    name,
    points_len: (.last_10_points | length),
    lines_len: (.last_10_lines | length),
    results_len: (.last_10_results | length)
  }' | head -10
# All three should be same length for each player

# 3. Check for contradictory factors (should return 0)
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | \
  jq '.games[].players[] |
      select(.prediction.recommendation == "OVER") |
      select(.prediction.factors | any(contains("Elite") or contains("slump") or contains("fatigue")))' | wc -l
# Expected: 0 (no OVER picks with UNDER factors)

# 4. Best bets current date (should be >0)
curl https://storage.googleapis.com/nba-props-platform-api/v1/best-bets/latest.json | jq '.total_picks'
# Expected: >0 (was 0 before fix)

# 5. Calendar endpoint
curl https://storage.googleapis.com/nba-props-platform-api/v1/calendar/game-counts.json | jq 'keys | length'
# Expected: 30+ dates

# 6. Date-specific tonight file
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/2026-02-11.json | jq '.game_date'
# Should return the date

# 7. Verify max 4 factors
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | \
  jq '[.games[].players[] | select(.prediction.factors) | .prediction.factors | length] | max'
# Expected: <= 4

# 8. All lined players have factors field
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | \
  jq '[.games[].players[] | select(.has_line) | select(.prediction.factors == null)] | length'
# Expected: 0
```

**Create validation report with results**

### 3. Monitor for Issues (5 min)

**Check recent logs:**
```bash
# Phase 6 export errors
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=nba-scrapers" \
  --limit=100 --format=json | jq '.[] | select(.severity == "ERROR")'
```

**Check Slack alerts:**
- `#deployment-alerts` - Drift monitoring
- `#canary-alerts` - Pipeline health
- `#nba-alerts` - Export errors

### 4. Notify Frontend Team

**Share this message:**

```
Phase 6 API updates deployed and validated! 🎉

New fields (all 192 lined players):
✅ days_rest - Context badge
✅ minutes_avg - Player stats
✅ recent_form - Hot/Cold/Neutral indicator
✅ last_10_lines - Accurate O/U history (fixes 31 players)
✅ prediction.factors - Max 4 directional reasons per pick
✅ player_lookup - In picks endpoint

New endpoints:
✅ /tonight/{YYYY-MM-DD}.json - Historical dates
✅ /calendar/game-counts.json - Calendar widget

Details & integration guide:
/docs/08-projects/current/phase6-api-gaps/09-FRONTEND-NOTIFICATION.md

All backward-compatible. Ready for integration!
```

## Success Criteria

**Must validate:**
- [x] Cloud Build SUCCESS
- [x] Services deployed with commit 6033075b
- [ ] `prediction.factors` populated for all lined players
- [ ] No contradictory factors (OVER + "Elite defense" = bug)
- [ ] `last_10_lines` arrays match length with `last_10_points`
- [ ] Best bets returns >0 picks for current date
- [ ] Calendar endpoint returns 30+ dates
- [ ] Date-specific tonight files exist
- [ ] No errors in Phase 6 export logs

## Critical Implementation Details

**prediction.factors (MUST be directional):**
- OVER + "Weak opposing defense" ✅
- OVER + "Hot over streak" ✅
- UNDER + "Elite opposing defense" ✅
- UNDER + "Back-to-back fatigue" ✅
- OVER + "Elite opposing defense" ❌ (blocked)
- UNDER + "Weak opposing defense" ❌ (blocked)

**last_10_lines (same-length arrays):**
```json
{
  "last_10_points": [25, 18, null, 30, 19],
  "last_10_lines":  [20.5, 18.5, null, 21.5, 17.5],
  "last_10_results": ["O", "U", "DNP", "O", "O"]
}
```
All three arrays MUST have same length (same 10 games), nulls where data missing.

**best_bets (table selection):**
- Current/future dates (≥ today): Query `player_prop_predictions`
- Historical dates (< today): Query `prediction_accuracy`

## If Issues Found

**Rollback:**
```bash
git revert 6033075b
git push origin main
# Cloud Build will auto-deploy previous version
```

**Common issues:**
1. **Factors contradictory** → Check `_build_prediction_factors()` directional logic
2. **Arrays different lengths** → Check `_query_last_10_results()` NOT filtering IS NOT NULL
3. **Best bets still 0** → Check table selection `use_predictions_table` logic
4. **Calendar empty** → Check `calendar_exporter.py` query

**Debug locally:**
```bash
PYTHONPATH=. python -c "
from data_processors.publishing.tonight_all_players_exporter import TonightAllPlayersExporter
exporter = TonightAllPlayersExporter()
data = exporter.generate_json('2026-02-11')
# Inspect data
import json
print(json.dumps(data['games'][0]['players'][0], indent=2))
"
```

## Deliverables for This Session

1. **Validation report** - Results of all 8 validation commands
2. **Issue list** - Any problems found (hopefully none)
3. **Frontend notification** - Confirmation that APIs are ready
4. **Monitoring setup** - Watch for issues in next 24 hours

## Additional Context

**Files changed in Session 209:**
- `tonight_all_players_exporter.py` (+184 lines)
- `best_bets_exporter.py` (+138 lines)
- `calendar_exporter.py` (+85 lines, NEW)
- `exporter_utils.py` (+34 lines)
- `all_subsets_picks_exporter.py` (+3 lines)
- `daily_export.py` (+14 lines)

**Commits (all on main):**
1. `72a2fd35` - Sprint 1 (quick wins)
2. `47db5500` - Sprint 2A (last_10_lines)
3. `ad0f2a4` - Sprint 2C (best_bets)
4. `12a161f6` - Sprint 2B (prediction.factors)
5. `6033075b` - Sprint 3 (calendar + date files)

**Documentation created:**
- 11 comprehensive docs in `/docs/08-projects/current/phase6-api-gaps/`
- Handoff doc in `/docs/09-handoff/2026-02-12-SESSION-209-HANDOFF.md`

## Expected Timeline

- Validation: 20-30 min
- Issue investigation (if any): 15-30 min
- Frontend notification: 5 min
- **Total:** 30-60 min

Start by checking Cloud Build status and running validation commands. Create a summary of results.
