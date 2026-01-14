# Next Session: Backfill Historical Data

**Purpose:** Load historical NBA data (2020-2024 seasons) to enable production predictions
**Estimated Time:** 3-5 days of automated processing
**Prerequisites:** v1.0 deployed and operational ✅

---

## 🎯 **Session Goal**

Load 4+ years of historical NBA data so that:
- Phase 3 analytics have sufficient historical averages
- Phase 4 precompute completeness checks pass
- Phase 5 predictions can generate with confidence
- Production pipeline works end-to-end with real data

---

## ✅ **What's Already Done**

### **Infrastructure (v1.0 Deployed)**
- ✅ All 8 Pub/Sub topics created
- ✅ Phase 2→3 orchestrator deployed (ACTIVE, Firestore proven working)
- ✅ Phase 3→4 orchestrator deployed (ACTIVE)
- ✅ Phase 5 prediction coordinator deployed (HEALTHY)
- ✅ Firestore initialized (Native mode, us-west2)
- ✅ IAM permissions configured

### **Current Data State**
- **Phase 1-2 (Raw Data):** Exists for current season (2024-25)
- **Phase 3 (Analytics):** Exists for recent dates, but limited history
- **Phase 4 (Precompute):** Exists but completeness checks fail
- **Phase 5 (Predictions):** Can't generate without complete historical data

### **What's Missing**
- Historical raw data (2020-2024 seasons)
- Historical analytics (rolling averages, trends)
- Historical precompute features
- Sufficient data for completeness checks to pass

---

## 📊 **Why Backfill is Needed**

### **Completeness Checks in Phase 3/4**
Analytics processors check for:
- **Minimum games:** ~30 games of history per player
- **Rolling averages:** Last 10 games, last 30 games, season average
- **Trend data:** Performance over time
- **Opponent analysis:** Historical matchups

**Without backfill:**
- Completeness checks fail
- Phase 4 won't process data
- Phase 5 won't generate predictions

**With backfill:**
- Full historical context
- Completeness checks pass
- Production-quality predictions

---

## 🗂️ **Backfill Scope**

### **Recommended Data to Load**

**Seasons:**
- 2024-25: ✅ Already exists (current season)
- 2023-24: ⏳ Need to backfill (82 games + playoffs)
- 2022-23: ⏳ Need to backfill (82 games + playoffs)
- 2021-22: ⏳ Need to backfill (82 games + playoffs)
- 2020-21: ⏳ Optional (COVID-shortened, 72 games)

**Data Types:**
1. **Phase 1-2 (Raw Data):**
   - Game schedules
   - Box scores (team & player)
   - Play-by-play data
   - Injuries, lineups
   - Betting lines (if available historically)

2. **Phase 3 (Analytics):**
   - Will be generated from Phase 2 raw data
   - Orchestrator will trigger automatically

3. **Phase 4 (Precompute):**
   - Will be generated from Phase 3 analytics
   - Orchestrator will trigger automatically

---

## 📋 **Backfill Strategy**

### **Approach: Sequential Season-by-Season**

**Why not all at once?**
- Avoid overwhelming APIs with requests
- Monitor progress and catch errors early
- Reduce alert spam (use digest mode)
- Allow for pauses/adjustments

**Recommended Order:**
1. **2023-24 season** (most recent complete season)
   - Validates backfill scripts work
   - Most relevant for current predictions

2. **2022-23 season**
   - Adds more historical depth

3. **2021-22 season**
   - Provides 3 seasons of data (good baseline)

4. **Earlier seasons** (optional)
   - If you want more historical training data

---

## 🛠️ **Backfill Scripts (Already Exist)**

### **Location**
Check: `bin/scrapers/deploy/` and related backfill scripts

### **What to Look For**
- Date range backfill scripts
- Batch processing for multiple dates
- Progress tracking
- Error handling and retry logic

### **Features Needed for Backfill**

**Alert Digest Mode:**
- Batch alerts instead of individual emails
- Daily summary instead of per-processor alerts
- Reduces inbox spam during backfill

**Skip Downstream Trigger (Optional):**
- `skip_downstream: true` in UnifiedPubSubPublisher
- Prevents orchestrators from firing during backfill
- Load all raw data first, then trigger analytics

**Progress Tracking:**
- Log which dates completed
- Track failures for retry
- Monitor completion percentage

---

## 🎯 **Recommended Backfill Plan**

### **Phase 1: Prepare**

1. **Review Existing Backfill Scripts**
   ```bash
   # Find backfill-related scripts
   find bin -name "*backfill*"
   ls -la bin/scrapers/deploy/*backfill*
   ```

2. **Test with Small Date Range**
   - Pick 5-7 days from 2023-24 season
   - Run backfill for just those dates
   - Verify data loads correctly
   - Check orchestrators trigger properly

3. **Configure Alert Digest**
   - Create alert digest system (if not exists)
   - Set to daily summary mode
   - Test with small backfill

### **Phase 2: Execute Season Backfills**

**2023-24 Season (Most Recent):**
```bash
# Example command structure
./bin/scrapers/backfill_season.sh \
  --season "2023-24" \
  --start-date "2023-10-01" \
  --end-date "2024-06-30" \
  --alert-mode digest \
  --skip-downstream false  # Let orchestrators run
```

**Monitor Progress:**
- Check BigQuery for row counts daily
- Monitor orchestrator Firestore documents
- Review error logs
- Track API rate limits

**Expected Duration:**
- ~1-2 days per season (depends on API limits)
- Can run in background
- Hands-off after starting

### **Phase 3: Verify & Test**

After backfill completes:
1. **Check Data Completeness**
   ```sql
   SELECT
     season,
     COUNT(DISTINCT game_date) as days_with_data,
     COUNT(*) as total_games
   FROM `nba-props-platform.nba_raw.games`
   GROUP BY season
   ORDER BY season DESC
   ```

2. **Test Phase 3 Analytics**
   - Pick a recent date
   - Trigger Phase 3 manually
   - Verify completeness checks pass

3. **Test Phase 4 Precompute**
   - Should trigger automatically after Phase 3
   - Check for completeness

4. **Test Phase 5 Predictions**
   - Trigger for a game date with historical data
   - Verify predictions generate successfully

---

## ⚠️ **Potential Issues & Solutions**

### **Issue: API Rate Limits**
- **Solution:** Add delays between requests, spread over multiple days
- **Config:** Adjust batch size in backfill scripts

### **Issue: Alert Spam**
- **Solution:** Use alert digest mode
- **Fallback:** Temporarily disable alerts during backfill

### **Issue: Orchestrator Overload**
- **Solution:** Use `skip_downstream: true` during Phase 2 load
- **Then:** Trigger Phase 3 manually after all raw data loaded

### **Issue: Incomplete Data**
- **Solution:** Some historical dates may not have data (no games)
- **Expected:** ~250-300 dates per season with games
- **Verify:** Check NBA schedule for actual game dates

### **Issue: Disk Space**
- **Check:** BigQuery storage quotas
- **Monitor:** Storage usage in GCP Console
- **Note:** BigQuery has generous free tier

---

## 📊 **Success Criteria**

### **Data Loaded**
- [ ] 2023-24 season: 82 games + playoffs
- [ ] 2022-23 season: 82 games + playoffs
- [ ] 2021-22 season: 82 games + playoffs
- [ ] Analytics generated for all dates
- [ ] Precompute generated for all dates

### **Completeness**
- [ ] Phase 3 completeness checks pass
- [ ] Phase 4 completeness checks pass
- [ ] Sufficient history for rolling averages (30+ games)

### **End-to-End Test**
- [ ] Trigger pipeline for a recent date
- [ ] Phase 2→3 orchestrator triggers Phase 3
- [ ] Phase 3→4 orchestrator triggers Phase 4
- [ ] Phase 5 generates predictions
- [ ] Correlation ID flows through all phases

---

## 🔗 **Useful Queries**

### **Check Backfill Progress**
```sql
-- Count of games by season
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(DISTINCT game_date) as game_days,
  COUNT(*) as total_games
FROM `nba-props-platform.nba_raw.games`
GROUP BY year
ORDER BY year DESC
```

### **Check Analytics Coverage**
```sql
-- Verify analytics generated for dates
SELECT
  COUNT(DISTINCT game_date) as analytics_days,
  MIN(game_date) as earliest,
  MAX(game_date) as latest
FROM `nba-props-platform.nba_analytics.player_game_summary`
```

### **Check Precompute Coverage**
```sql
-- Verify precompute features exist
SELECT
  COUNT(DISTINCT analysis_date) as precompute_days,
  COUNT(DISTINCT player_lookup) as unique_players
FROM `nba-props-platform.nba_precompute.ml_feature_store`
```

---

## 📚 **Key Files & Documentation**

### **Backfill Scripts**
- `bin/scrapers/deploy/*backfill*.sh` - Backfill execution scripts
- `scripts/backfill/` - Any backfill utilities

### **Alert Configuration**
- `shared/utils/notification_system.py` - Alert system
- Check for digest mode configuration

### **Phase Configuration**
- `shared/publishers/unified_pubsub_publisher.py` - Has `skip_downstream` flag
- `shared/config/pubsub_topics.py` - Topic definitions

### **Documentation**
- `docs/09-handoff/2025-11-29-backfill-alert-suppression-complete.md` - Alert digest info
- `docs/04-deployment/v1.0-deployment-guide.md` - Deployment reference

---

## 🚀 **Quick Start for Next Session**

1. **Review backfill scripts:**
   ```bash
   find bin -name "*backfill*" -type f
   ```

2. **Test with small date range:**
   - Pick 3-5 days from November 2023
   - Run backfill
   - Verify data appears in BigQuery

3. **Configure alerts:**
   - Enable digest mode
   - Test with small backfill

4. **Execute season backfills:**
   - Start with 2023-24
   - Monitor progress
   - Verify completeness

5. **Test end-to-end:**
   - Trigger for a date with full history
   - Verify predictions generate

---

## 💡 **Pro Tips**

1. **Start Small:** Test with 1 week before doing full season
2. **Monitor Daily:** Check progress each day during backfill
3. **Document Issues:** Keep notes on any problems encountered
4. **Pause if Needed:** Backfill can be paused and resumed
5. **Verify Each Season:** Test completeness after each season loads

---

## ✅ **What Success Looks Like**

After successful backfill:
- 3+ seasons of historical data loaded
- Analytics completeness checks pass
- Precompute features generated
- Predictions generate successfully
- End-to-end pipeline works with real data
- Ready for daily production processing

---

**Good luck with the backfill!** It's the final piece to make v1.0 production-ready. 🚀

**Estimated Total Time:** 3-5 days (mostly automated)
**Hands-on Time:** 3-4 hours (setup, monitoring, verification)
**Difficulty:** Medium (scripts exist, just need execution)

---

**Document Created:** 2025-11-29
**For Session:** Backfill Historical Data
**Prerequisites:** v1.0 deployed ✅
**Next Doc:** After backfill → Full production launch!
