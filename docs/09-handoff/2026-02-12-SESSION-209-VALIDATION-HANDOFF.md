# Session 209 Validation - Immediate Handoff

**Status:** ⚠️ Code merged, but manual deployment needed
**Time:** 2026-02-12 00:42 UTC
**Commit:** 6033075b (merged to main ✅)

---

## Current Situation

**What's done:**
- ✅ All 3 sprints implemented (16 fixes)
- ✅ Code merged to main (commit 6033075b)
- ✅ Cloud Build SUCCESS (785bd5fa)
- ✅ 12 comprehensive docs created

**What's NOT done:**
- ❌ nba-scrapers service NOT deployed with new code
- Current: `69bed26`
- Needed: `6033075b`

**Why auto-deploy didn't work:**
- `deploy-nba-scrapers` trigger only watches `scrapers/**` and `shared/**`
- Our changes are in `data_processors/publishing/**`
- Trigger configuration gap (needs fixing)

---

## IMMEDIATE ACTION NEEDED

### Deploy nba-scrapers Service

```bash
cd /home/naji/code/nba-stats-scraper

# Option 1: Quick deploy (recommended)
./bin/hot-deploy.sh nba-scrapers

# Option 2: Full validation deploy
./bin/deploy-service.sh nba-scrapers

# Option 3: Manual gcloud
gcloud run deploy nba-scrapers \
  --source . \
  --region us-west2 \
  --project nba-props-platform
```

**Wait ~5-10 min for deployment to complete**

---

## After Deployment: Validation

### 1. Verify Deployment
```bash
# Check deployed commit
gcloud run services describe nba-scrapers --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"
# Should show: 6033075b
```

### 2. Trigger Phase 6 Export

Phase 6 exports run on the nba-scrapers service. After deploying, you need to trigger an export to generate the new JSON files.

**Option A: Wait for scheduled run**
- Exports run automatically via Cloud Scheduler
- Check schedule in Cloud Console

**Option B: Manual trigger**
- Find the Phase 6 export endpoint
- Call it manually for today's date

### 3. Validate Endpoints (8 commands)

**After export completes,** run these:

```bash
# 1. Check new fields
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | \
  jq '.games[0].players[0] | {days_rest, minutes_avg, recent_form, factors: .prediction.factors}'

# 2. Array lengths (CRITICAL - must match)
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | \
  jq '.games[0].players[] | select(.has_line) | {
    points_len: (.last_10_points | length),
    lines_len: (.last_10_lines | length)
  }' | head -5

# 3. No contradictions (should return 0)
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | \
  jq '.games[].players[] |
      select(.prediction.recommendation == "OVER") |
      select(.prediction.factors | any(contains("Elite")))' | wc -l

# 4. Best bets >0 picks
curl https://storage.googleapis.com/nba-props-platform-api/v1/best-bets/latest.json | jq '.total_picks'

# 5. Calendar endpoint
curl https://storage.googleapis.com/nba-props-platform-api/v1/calendar/game-counts.json | jq 'keys | length'

# 6. Date-specific tonight
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/2026-02-11.json | jq '.game_date'

# 7. Max 4 factors
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | \
  jq '[.games[].players[] | select(.prediction.factors) | .prediction.factors | length] | max'

# 8. All have factors field
curl https://storage.googleapis.com/nba-props-platform-api/v1/tonight/all-players.json | \
  jq '[.games[].players[] | select(.has_line) | select(.prediction.factors == null)] | length'
```

---

## Success Criteria

- [ ] nba-scrapers deployed with 6033075b
- [ ] Phase 6 export completes without errors
- [ ] All 8 validation commands pass
- [ ] No contradictory factors
- [ ] Arrays same length
- [ ] Best bets >0 picks
- [ ] Calendar returns 30+ dates

---

## Follow-Up Task: Fix Auto-Deploy

**Problem:** nba-scrapers trigger doesn't watch `data_processors/publishing/**`

**Solution:** Update Cloud Build trigger to include:
```yaml
includedFiles:
  - scrapers/**
  - data_processors/publishing/**  # ADD THIS
  - backfill_jobs/publishing/**     # ADD THIS
  - shared/**
```

**How:**
1. Cloud Console → Cloud Build → Triggers
2. Find `deploy-nba-scrapers`
3. Edit → Add included files
4. Save

---

## If Issues Found

**Rollback:**
```bash
git revert 6033075b
git push origin main
./bin/hot-deploy.sh nba-scrapers
```

**Debug:**
```bash
# Check export logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=nba-scrapers" --limit=50

# Test locally
PYTHONPATH=. python -c "
from data_processors.publishing.tonight_all_players_exporter import TonightAllPlayersExporter
exporter = TonightAllPlayersExporter()
data = exporter.generate_json('2026-02-11')
print(data['games'][0]['players'][0])
"
```

---

## Documents Reference

**All docs:** `/docs/08-projects/current/phase6-api-gaps/`

**Key docs:**
1. `08-SESSION-209-COMPLETION-SUMMARY.md` - Full implementation details
2. `09-FRONTEND-NOTIFICATION.md` - What to tell frontend
3. `11-CONTINUATION-PROMPT.md` - Full validation guide

---

## Timeline

**Estimated:**
- Deploy nba-scrapers: 5-10 min
- Trigger Phase 6 export: 5-10 min (or wait for scheduled)
- Run validations: 10 min
- **Total: 20-30 min**

**Start:** Deploy nba-scrapers now with `./bin/hot-deploy.sh nba-scrapers`

---

**Status:** Ready for deployment
**Next:** Deploy nba-scrapers, trigger export, validate
