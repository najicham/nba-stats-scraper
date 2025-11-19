# Phase 3 Deployment - Important Details & Gotchas

**Created:** 2025-11-15
**Purpose:** Key technical details for Phase 3 deployment (things easy to miss)
**Status:** Deployment in progress

---

## ⚠️ Critical Details - Don't Miss These

### 1. Phase 3 Processor Dependencies

**Execution Order Matters:**
```
Phase 3 Part 1 (10:00-10:30 PM):
├─ Player Game Summary (reads 6 Phase 2 sources)
├─ Team Offense Summary (reads team boxscore + play-by-play)
└─ Team Defense Summary (reads team boxscore + player stats)

Phase 3 Part 2 (10:30-11:00 PM):
├─ Upcoming Player Context (needs Player Game Summary complete)
└─ Upcoming Team Context (needs Team summaries complete)
```

**Key Point:** Upcoming contexts depend on game summaries being done first!

---

### 2. BigQuery Table Names & Datasets

**Dataset:** `nba_analytics` (not `nba_raw`)

**Tables to verify exist:**
```sql
-- Phase 3 outputs
nba_analytics.player_game_summary
nba_analytics.team_offense_game_summary
nba_analytics.team_defense_game_summary
nba_analytics.upcoming_player_game_context
nba_analytics.upcoming_team_game_context
```

**Common mistake:** Writing to wrong dataset or table name typo

---

### 3. Pub/Sub Topic/Subscription Names

**Phase 2 publishes to:**
- Topic: `raw-data-processed` (or similar - verify actual name)

**Phase 3 subscribes from:**
- Subscription: `phase3-analytics-sub` (or similar - verify)

**Phase 3 publishes to:**
- Topic: `analytics-data-processed` (for future Phase 4 connection)

**Action Item:** Verify these exist or need to be created:
```bash
gcloud pubsub topics list
gcloud pubsub subscriptions list
```

---

### 4. Partition Filters - CRITICAL!

**All Phase 3 processors MUST filter partitions:**

```sql
-- ✅ CORRECT (filters partition)
WHERE game_date = @game_date

-- ❌ WRONG (scans entire table, expensive!)
WHERE player_name = 'LeBron James'
```

**Why this matters:**
- Without partition filter = full table scan = $$$ and slow
- With partition filter = scans only today = fast and cheap

**Check:** All Phase 3 SQL queries should have partition filters

---

### 5. Season Logic (IMPORTANT!)

**Season calculation for dates:**
```python
# Oct-Dec dates → current year is season start
# Example: 2024-12-15 = 2024-25 season

# Jan-Sep dates → previous year is season start
# Example: 2025-01-15 = 2024-25 season

def get_season(date):
    if date.month >= 10:  # Oct, Nov, Dec
        return f"{date.year}-{str(date.year + 1)[2:]}"
    else:  # Jan-Sep
        return f"{date.year - 1}-{str(date.year)[2:]}"
```

**Common mistake:** Using current year as season for Jan-Sep dates

---

### 6. Player/Team Lookup Keys

**Player Identifier:**
- Use `player_lookup` (standardized, e.g., "lebron-james")
- NOT `player_id` (varies by source)
- NOT `player_name` (spelling variations)

**Team Identifier:**
- Use `team_abbr` (e.g., "LAL", "BOS")
- NOT `team_id` (varies by source)
- NOT `team_name` (can change, e.g., "LA Lakers" vs "Los Angeles Lakers")

**Check:** All joins should use lookup keys, not raw IDs

---

### 7. Data Source Tracking (v4.0 Pattern)

**Each Phase 3 processor should track:**
```python
# For each source table
source_<name>_last_updated
source_<name>_row_count
source_<name>_completeness_pct
```

**Example from Player Game Summary:**
```python
source_gamebook_last_updated
source_gamebook_row_count
source_boxscore_last_updated
source_boxscore_row_count
# ... for all 6 sources
```

**Why:** Enables troubleshooting data quality issues later

---

### 8. Null Handling & Defaults

**Stats that can be null:**
- Playing time (player DNP = null minutes)
- Shot attempts (player didn't shoot = null FGA)
- Assists, rebounds, etc. (can be 0 or null)

**Pattern:**
```python
points = stats.get('PTS', 0)  # Default to 0 if missing
minutes = stats.get('MIN')     # Can be null (DNP)

# Derived stats
points_per_minute = points / minutes if minutes else None
```

**Common mistake:** Dividing by null/zero without checking

---

### 9. Cloud Run Configuration

**Memory Requirements:**
```
Player Game Summary: 2 GB (processes ~300 players/game)
Team Offense/Defense: 512 MB (only 2 teams/game)
Upcoming Player Context: 2 GB (queries 450 players)
Upcoming Team Context: 512 MB (30 teams)
```

**Timeout:**
- Set to 15 minutes minimum (some processors are slow)
- Player Game Summary can take 2-5 minutes

**Concurrency:**
- Start with concurrency=1 (one request at a time)
- Can increase after verifying stability

**Environment Variables Needed:**
```bash
GCP_PROJECT=nba-props-platform
BQ_DATASET=nba_analytics
PUBSUB_TOPIC=analytics-data-processed
```

---

### 10. Testing Edge Cases

**Test these scenarios:**

**1. No games today (off day):**
- Upcoming contexts should return empty (0 rows)
- Game summaries shouldn't run at all

**2. Missing raw data:**
- Processor should log warning, not crash
- Use graceful degradation (partial data OK)

**3. Late data arrival:**
- Game finishes at 11 PM, data arrives at 11:30 PM
- Phase 3 should still process (even if late)

**4. Duplicate triggers:**
- Same game processed twice (idempotency)
- Should overwrite, not duplicate rows

---

## 🔍 Quick Verification Queries

### After deploying, run these to verify:

**1. Check Phase 3 tables exist:**
```sql
SELECT table_name
FROM `nba_analytics.INFORMATION_SCHEMA.TABLES`
WHERE table_name LIKE '%summary%'
   OR table_name LIKE '%context%';
```

**2. Check for today's data:**
```sql
-- Game summaries (if games today)
SELECT COUNT(*) FROM `nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE();

-- Upcoming contexts (for tomorrow's games)
SELECT COUNT(*) FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE() + 1;
```

**3. Check partition usage:**
```sql
-- This should scan ONLY today's partition (cheap)
-- Not the entire table (expensive)
SELECT COUNT(*)
FROM `nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE();

-- Verify in query plan: "Partitions scanned: 1"
```

---

## 🚨 Common Deployment Mistakes

**1. Missing IAM Permissions:**
- Cloud Run service account needs BigQuery write access
- Cloud Run service account needs Pub/Sub publish access
- Verify: `gcloud iam service-accounts list`

**2. Wrong Pub/Sub Message Format:**
- Phase 2 publishes JSON with `{processor, table, timestamp}`
- Phase 3 expects this format - verify message structure

**3. Timezone Issues:**
- All times should be ET (America/New_York)
- Use `DATE(timestamp, 'America/New_York')` for date calculations

**4. Forgetting to Deploy All 5 Processors:**
- Easy to deploy 3/5 and forget the others
- Checklist: Player Summary, Team Offense, Team Defense, Upcoming Player, Upcoming Team

**5. Not Setting Up Dead Letter Queue (DLQ):**
- Failed messages need somewhere to go
- Create DLQ subscription for debugging

---

## 📋 Pre-Flight Checklist

Before marking deployment complete, verify:

- [ ] All 5 Phase 3 processors deployed to Cloud Run
- [ ] Pub/Sub topics/subscriptions exist and connected
- [ ] BigQuery tables exist in `nba_analytics` dataset
- [ ] IAM permissions configured correctly
- [ ] Environment variables set on Cloud Run services
- [ ] At least one successful end-to-end test (Phase 2→3)
- [ ] Health check queries return expected data
- [ ] DLQ configured for failed messages
- [ ] Monitoring/logging accessible (Cloud Console)

---

## 🔗 Quick Reference Links

**Processor Details:**
- `docs/processor-cards/phase3-player-game-summary.md`
- `docs/processor-cards/phase3-team-offense-game-summary.md`
- `docs/processor-cards/phase3-team-defense-game-summary.md`
- `docs/processor-cards/phase3-upcoming-player-game-context.md`
- `docs/processor-cards/phase3-upcoming-team-game-context.md`

**Operations:**
- `docs/processors/02-phase3-operations-guide.md`
- `docs/processors/03-phase3-scheduling-strategy.md`
- `docs/processors/04-phase3-troubleshooting.md`

**Troubleshooting:**
- `docs/operations/cross-phase-troubleshooting-matrix.md` (Section 2.2)

---

## 💡 Pro Tips

**1. Deploy in order:**
- Game summaries first (Part 1)
- Context processors second (Part 2)
- Verify Part 1 works before deploying Part 2

**2. Use manual triggers initially:**
- Test each processor manually first
- Then enable Pub/Sub auto-triggering
- Easier to debug one at a time

**3. Check logs frequently:**
```bash
# View recent logs
gcloud run services logs read phase3-player-summary \
  --region=us-central1 \
  --limit=50
```

**4. Monitor BigQuery costs:**
- First few runs might be expensive (full table scans if partition filters missing)
- Check query costs in BigQuery console
- Should be <$0.01 per query with partition filters

---

**Document Status:** Active deployment reference
**Last Updated:** 2025-11-15
**Use:** Keep this open while deploying Phase 3

---

*Good luck with the deployment! Check these details as you go.*
