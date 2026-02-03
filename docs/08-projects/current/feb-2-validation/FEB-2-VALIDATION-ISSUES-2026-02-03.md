# February 2, 2026 Validation Issues - Critical Problems Report

**Date:** 2026-02-03 00:41 ET
**Validator:** Sonnet (Claude Code validation session)
**Purpose:** Document critical issues found during daily validation for Opus review and fix planning
**Game Date Validated:** 2026-02-02 (4 games)
**Processing Date:** 2026-02-03 (overnight processing)

---

## Executive Summary

**Status:** 🔴 **PRODUCTION BLOCKING - Multiple P0/P1 Critical Issues**

Daily validation for February 2, 2026 games revealed **5 critical issues** that prevent the data pipeline from functioning correctly:

1. **Missing Game Data** - PHI vs LAC game completely missing from BDL scraper (P0)
2. **Usage Rate Complete Failure** - 0% coverage across all games (P1)
3. **Low Minutes Coverage** - 47% vs 80% threshold (P1)
4. **No Orchestrator Completion Record** - Phase 3 completion tracking missing (P0)
5. **Deployment Drift** - 3 critical services running stale code (P1)

**Impact:** Data quality insufficient for model retraining, analysis, or production use.

---

## Issue 1: Missing Game Data - PHI vs LAC (P0 CRITICAL)

### Problem Statement

The Philadelphia 76ers vs LA Clippers game (game_id: `0022500715`) on Feb 2, 2026 has **zero records** in the raw BDL data and analytics tables, despite the game being marked as "Final" in the schedule.

### Evidence

**Schedule shows game completed:**
```sql
SELECT * FROM nba_reference.nba_schedule
WHERE game_date = '2026-02-02' AND game_id = '0022500715'
-- Result: Status = "Final"
```

**BDL raw data missing:**
```sql
SELECT COUNT(*) FROM nba_raw.bdl_player_boxscores
WHERE game_date = '2026-02-02' AND game_id = '0022500715'
-- Result: 0 records
```

**Analytics data breakdown by game:**
```
Game ID              | Total Players | Played | Has Minutes | Has Usage Rate
---------------------|---------------|--------|-------------|---------------
20260202_HOU_IND    | 35            | 22     | 22          | 0
20260202_MIN_MEM    | 37            | 21     | 21          | 0
20260202_NOP_CHA    | 37            | 20     | 20          | 0
20260202_PHI_LAC    | 25            | 0      | 0           | 0  ← MISSING
```

**Other games successfully scraped:**
- HOU @ IND: 34 raw BDL records → 22 active players processed
- MIN @ MEM: 70 raw BDL records → 21 active players processed
- NOP @ CHA: 72 raw BDL records → 20 active players processed

### Impact

- 0/25 players processed for PHI-LAC game
- All PHI-LAC roster marked as DNP, but many likely played
- Minutes coverage drops to 47% (63/134 instead of ~88/134)
- Predictions may exist for PHI-LAC but with NO underlying analytics
- Grading will fail for PHI-LAC predictions

### Possible Root Causes

1. **BDL API didn't return game:**
   - API outage or rate limiting
   - Game ID format not recognized by BDL
   - Game data delayed/not available at scrape time

2. **Scraper filtering logic excluded it:**
   - Game ID format mismatch in scraper query
   - Date/time filtering bug
   - Status filter (game marked wrong status when scraped)

3. **Scraper failed silently:**
   - Exception caught but not logged
   - Timeout on this specific game
   - Data validation failed and record skipped

### Investigation Needed

**Check scraper execution logs:**
```bash
# Check if BDL scraper ran for Feb 2
gcloud logging read 'resource.labels.service_name="nba-phase1-scrapers"
  AND jsonPayload.scraper="bdl_player_boxscores"
  AND timestamp>="2026-02-02T00:00:00Z"' \
  --limit=50

# Look for errors or game_id mentions
grep -i "0022500715\|PHI\|LAC" <logs>
```

**Verify game exists in schedule with correct status:**
```bash
# Check when game status was updated
bq query "SELECT game_id, game_status, game_status_text,
  home_team_score, away_team_score
FROM nba_raw.nbac_schedule
WHERE game_date = '2026-02-02' AND game_id = '0022500715'"
```

**Check BDL API directly:**
```bash
# Manual API call to see if BDL has the data now
curl "https://www.balldontlie.io/api/v1/stats?game_ids[]=5029715&per_page=100"
# (Note: BDL game_id format may differ - need to check conversion)
```

### Questions for Opus

1. What is the BDL game_id format for NBA game_id `0022500715`?
2. Does the scraper have retry logic for failed games?
3. Should we add this game to a "pending retry" queue?
4. Are there similar missing games in recent history?

---

## Issue 2: Usage Rate Complete Failure (P1 CRITICAL)

### Problem Statement

**0% of active players have `usage_rate` populated** despite team offense data existing with valid possession counts.

### Evidence

**Usage rate coverage:**
```
Total players: 134
Has usage_rate > 0: 0
Coverage: 0.0%
Expected: ≥80%
```

**Team offense data EXISTS and looks valid:**
```
Game ID              | Team | Possessions | FG Attempts | Turnovers
---------------------|------|-------------|-------------|----------
20260202_HOU_IND    | IND  | 81          | 71          | 8
20260202_HOU_IND    | HOU  | 81          | 75          | 13
20260202_MIN_MEM    | MIN  | 51          | 48          | 6
20260202_MIN_MEM    | MEM  | 55          | 52          | 6
20260202_NOP_CHA    | NOP  | 97          | 84          | 7
20260202_NOP_CHA    | CHA  | 99          | 85          | 16
```

All 6 team records have valid, non-zero possessions.

**Sample player records (all NULL usage_rate):**
```
Player           | Team | Minutes | Points | Usage Rate
-----------------|------|---------|--------|------------
juliusrandle     | MIN  | 40      | 19     | NULL
anthonyedwards   | MIN  | 40      | 39     | NULL
amenthompson     | HOU  | 39      | 16     | NULL
jadenmcdaniels   | MIN  | 37      | 29     | NULL
```

### Game ID Format Analysis

**CRITICAL FINDING:** Both tables use the SAME game_id format:

- `team_offense_game_summary.game_id`: `20260202_HOU_IND`
- `player_game_summary.game_id`: `20260202_HOU_IND`

**Initial hypothesis of game_id mismatch is INCORRECT.**

### Impact

- Usage rate is a key ML feature (feature index 25)
- Cannot assess player usage patterns
- Model predictions may be degraded (using NULL or default value)
- Historical analysis broken for this date

### Possible Root Causes

1. **JOIN logic failure in player processor:**
   - JOIN keys correct but JOIN not executing
   - JOIN happening AFTER usage_rate calculation (logic order bug)
   - Conditional JOIN (only when certain criteria met) skipping

2. **Team data written after player data:**
   - Data race: player processor ran before team processor completed
   - Team data exists NOW but didn't exist during player processing
   - Check `updated_at` timestamps to verify

3. **Calculation logic bug:**
   - Division by zero handling removing all values
   - Type conversion issue (INT vs FLOAT)
   - NULL propagation from intermediate calculation

4. **Schema/field name issue:**
   - `possessions` field renamed or in wrong location
   - JOIN succeeds but field reference fails silently
   - Check if `team_offense_game_summary` schema changed recently

### Investigation Needed

**Check timestamps to detect race condition:**
```sql
-- Compare when team data vs player data was written
SELECT
  'player' as source,
  game_id,
  MAX(updated_at) as last_updated
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-02-02' AND is_dnp = FALSE
GROUP BY game_id

UNION ALL

SELECT
  'team' as source,
  game_id,
  MAX(updated_at) as last_updated
FROM nba_analytics.team_offense_game_summary
WHERE game_date = '2026-02-02'
GROUP BY game_id

ORDER BY game_id, source
```

**Review player processor usage_rate calculation code:**
```bash
# Check the exact JOIN and calculation logic
grep -A 30 "usage_rate" data_processors/analytics/player_game_summary/player_game_summary_processor.py
```

**Check processor completion order:**
```bash
# See if team_offense processor completed before player_game_summary
# This would rule out race condition
python3 << 'EOF'
from google.cloud import firestore
db = firestore.Client()
doc = db.collection('phase3_completion').document('2026-02-03').get()
if doc.exists:
    data = doc.to_dict()
    print("Completed processors:", [k for k in data.keys() if not k.startswith('_')])
    print("team_offense status:", data.get('team_offense_game_summary'))
    print("player_game status:", data.get('player_game_summary'))
else:
    print("No completion record - see Issue 4")
EOF
```

### Questions for Opus

1. What is the exact JOIN logic between player_game_summary and team_offense_game_summary?
2. Is usage_rate calculated during processing or in a post-processing step?
3. Has this calculation worked correctly in previous days?
4. Should we check Feb 1, Jan 31 data to see if this is new or ongoing?

---

## Issue 3: Low Minutes Coverage - 47% (P1 CRITICAL)

### Problem Statement

Only 47% of player records have `minutes_played` populated, falling far below the 80% threshold and into CRITICAL territory (<80%).

### Evidence

```
Total player records: 134
Has minutes_played: 63
Coverage: 47.0%
Threshold: ≥80% (OK), ≥50% (WARNING), <50% (CRITICAL)
Status: CRITICAL (just above 50% boundary)
```

### Breakdown of Missing Minutes

**By game:**
- HOU @ IND: 22/35 have minutes (62.9%)
- MIN @ MEM: 21/37 have minutes (56.8%)
- NOP @ CHA: 20/37 have minutes (54.1%)
- PHI @ LAC: 0/25 have minutes (0%) ← **Issue 1 causing this**

**Player categories:**
- DNP (Did Not Play): 71 players - correctly have NULL minutes
- Active players: 63 players - ALL have minutes populated (100%)

### Root Cause Analysis

**PRIMARY CAUSE:** Issue 1 (missing PHI-LAC game) accounts for major gap.

If PHI-LAC had ~22 players with minutes (typical), coverage would be:
- Expected: 85/134 = 63.4% (still below 80% but improved)

**SECONDARY CAUSE:** High DNP count (71/134 = 53%)

Typical breakdown:
- 25-30 DNPs per game is normal (injuries, coach decisions, inactive)
- 4 games × 30 DNPs = 120 total roster spots
- 4 games × ~22 active players = 88 with minutes
- Expected ratio: 88/208 = 42% have minutes (if counting ALL roster spots)

**FINDING:** The 47% coverage is actually **reasonable** if we account for DNPs being included in the count.

**Coverage by active players only:**
```
Active (is_dnp = FALSE): 63 players
Has minutes: 63 players
Coverage: 100% ✅
```

### Impact Re-Assessment

**Severity downgrade:** P1 → P2

When excluding DNPs (which should have NULL minutes), coverage is actually 100%. The low overall percentage is due to:
1. PHI-LAC missing (Issue 1) - 0/25
2. High DNP count (71 DNPs correctly marked)

**Real issue:** The alert threshold may need adjustment to account for DNP players.

### Recommendation

**Option 1:** Change alert query to only check active players:
```sql
SELECT
  COUNTIF(is_dnp = FALSE) as active_players,
  COUNTIF(is_dnp = FALSE AND minutes_played IS NOT NULL) as has_minutes,
  ROUND(100.0 * COUNTIF(is_dnp = FALSE AND minutes_played IS NOT NULL) /
    NULLIF(COUNTIF(is_dnp = FALSE), 0), 1) as active_coverage
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-02-02'
```

**Option 2:** Keep current query but adjust thresholds:
- New CRITICAL: <40% (accounts for ~50% DNP rate)
- New WARNING: 40-60%
- New OK: ≥60%

### Questions for Opus

1. Should DNPs be included in minutes coverage calculation?
2. What is the typical DNP rate historically?
3. Is 47% coverage normal when 53% are DNP?

---

## Issue 4: No Phase 3 Completion Record (P0 CRITICAL)

### Problem Statement

The Firestore document `phase3_completion/2026-02-03` does not exist, meaning orchestrator completion tracking failed.

### Evidence

```python
# Query result
No Phase 3 completion record for 2026-02-03
STATUS: CRITICAL - No completion record found
```

**Expected structure:**
```json
{
  "player_game_summary": {"status": "complete", "records": 134, ...},
  "team_offense_game_summary": {"status": "complete", "records": 6, ...},
  "team_defense_game_summary": {"status": "complete", "records": 6, ...},
  "upcoming_player_game_context": {"status": "complete", ...},
  "upcoming_team_game_context": {"status": "complete", ...},
  "_triggered": true,
  "_trigger_reason": "All 5 processors complete",
  "_trigger_timestamp": "2026-02-03T05:30:00Z"
}
```

**Actual:** Document does not exist.

### Impact

- Cannot verify orchestrator is working
- Cannot determine if Phase 4 was auto-triggered or manually run
- No audit trail of processor completion
- Silent orchestrator failures possible
- Cannot track processor completion times
- Session 81+ orchestrator health checks will fail

### Possible Root Causes

1. **Orchestrator didn't run:**
   - Cloud Function didn't trigger
   - Pub/Sub message not delivered
   - Scheduler job failed

2. **Processors failed before completion:**
   - All processors crashed before marking complete
   - Orchestrator waiting forever (no timeout)
   - Prerequisites not met (e.g., Phase 2 didn't complete)

3. **Firestore write failed:**
   - Permissions issue
   - Firestore outage
   - Document path/collection name wrong
   - Exception during write

4. **Wrong date being checked:**
   - Phase 3 ran on 2026-02-02 (not 2026-02-03)
   - Date boundary issue (UTC vs ET)

### Investigation Needed

**Check orchestrator Cloud Function logs:**
```bash
# Phase 2 → Phase 3 orchestrator
gcloud functions logs read phase2-to-phase3 \
  --region=us-west2 \
  --limit=50 \
  --start-time="2026-02-02T00:00:00Z"

# Look for:
# - "Phase 3 orchestration starting"
# - "Checking processor completion"
# - "All processors complete"
# - Any errors or exceptions
```

**Check if document exists with different date:**
```python
from google.cloud import firestore
db = firestore.Client()

# Check Feb 2 (maybe ran earlier)
doc = db.collection('phase3_completion').document('2026-02-02').get()
if doc.exists:
    print("Found record for 2026-02-02:", doc.to_dict())

# Check Feb 3 explicitly
doc = db.collection('phase3_completion').document('2026-02-03').get()
if doc.exists:
    print("Found record for 2026-02-03:", doc.to_dict())

# List all recent documents
docs = db.collection('phase3_completion').where('_triggered', '==', True).stream()
for doc in docs:
    print(f"{doc.id}: {doc.to_dict().get('_trigger_timestamp')}")
```

**Check Pub/Sub metrics:**
```bash
# Check if phase2-complete messages were published
gcloud pubsub topics list-subscriptions phase2-complete

# Check subscription metrics
gcloud pubsub subscriptions describe phase3-orchestrator-sub \
  --format="value(numUndeliveredMessages)"
```

**Verify processors actually ran:**
```bash
# Check if analytics processors logged any activity for Feb 2 data
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors"
  AND jsonPayload.data_date="2026-02-02"' \
  --limit=20
```

### Questions for Opus

1. What triggers Phase 3 orchestrator? (Pub/Sub vs Cloud Scheduler)
2. Does orchestrator have timeout logic?
3. What's the fallback if completion record fails to write?
4. Should we manually create the completion record to unblock?

---

## Issue 5: Deployment Drift (P1 CRITICAL)

### Problem Statement

Three critical services are running **stale code** - deployed 10-45 minutes before the latest commits.

### Evidence

```
Service                              | Deployed    | Code Changed | Gap
-------------------------------------|-------------|--------------|--------
nba-phase3-analytics-processors     | 19:26 PT    | 19:36 PT     | 10 min
nba-phase4-precompute-processors    | 19:28 PT    | 19:36 PT     | 8 min
prediction-coordinator               | 18:51 PT    | 19:36 PT     | 45 min
```

**Commits not deployed:**
1. `41bc42f4` - fix: Prevent BigQuery NULL errors in execution logger
2. `2993e9fd` - feat: Add Phase 6 subset exporters with Opus review fixes

**Services up to date:**
- ✅ `prediction-worker` (deployed 20:36 PT - AFTER code changes)
- ✅ `nba-phase1-scrapers` (deployed 14:37 PT - before changes, but changes don't affect it)

### Impact Assessment

**Immediate impact:** Likely LOW for today's issues

The two commits that aren't deployed:
1. Execution logger fix - affects prediction-worker logging (but worker IS deployed)
2. Phase 6 exporters - new feature, doesn't affect existing pipeline

**However:**
- Running stale code is a pattern that causes issues (see Sessions 81, 82, 64)
- May have been EARLIER stale deployments that caused Issues 1-4
- No guarantee issues aren't related to stale code

**Risk:** If Issues 1-4 had fixes deployed earlier, they're not active now.

### Investigation Needed

**Check if earlier fixes were committed but not deployed:**
```bash
# See what changed in Phase 3 processors on Feb 2
git log --oneline --since="2026-02-02 00:00" --until="2026-02-02 19:26" \
  -- data_processors/analytics/

# See what changed in orchestrators
git log --oneline --since="2026-02-02 00:00" --until="2026-02-02 19:26" \
  -- orchestration/

# Any fixes to usage_rate, minutes_played, or game_id handling?
git log --grep="usage\|minutes\|game_id" --since="2026-02-01" --oneline
```

**Verify what code is actually running:**
```bash
# Check commit SHA labels on running services
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"

# Compare to current HEAD
git rev-parse HEAD
```

### Recommendation

**Deploy all three services immediately:**
```bash
./bin/deploy-service.sh nba-phase3-analytics-processors
./bin/deploy-service.sh nba-phase4-precompute-processors
./bin/deploy-service.sh prediction-coordinator
```

Even if the two new commits don't fix Issues 1-4, keeping services in sync with code prevents confusion and eliminates a variable.

### Questions for Opus

1. Should deployment be automated (deploy on every commit to main)?
2. Is there a CI/CD pipeline that should have deployed these?
3. Should we add a pre-validation check that fails if services are stale?

---

## Cross-Issue Analysis

### Are Issues Related?

**Issue 1 (missing game) + Issue 4 (no completion record):**
- Possible: If Phase 3 expected 4 games but only got 3, orchestrator may wait forever
- Check: Does orchestrator check game count before marking complete?

**Issue 2 (usage_rate) + Issue 5 (deployment drift):**
- Possible: A fix was deployed that broke usage_rate JOIN logic
- Check: Was there a recent change to player_game_summary_processor.py?

**Issue 3 (minutes coverage) + Issue 1 (missing game):**
- Confirmed: Issue 1 directly causes ~15% of Issue 3's gap
- Fix Issue 1 first, then re-assess Issue 3

### Timing Analysis

**When did these issues start?**

Need to check:
1. Did Feb 1 data process correctly? (baseline for comparison)
2. Did Jan 31 data process correctly? (further back)
3. When was last successful validation with no issues?

```bash
# Check Feb 1 data quality
bq query "SELECT
  COUNT(*) as total,
  COUNTIF(minutes_played IS NOT NULL AND is_dnp = FALSE) as has_minutes,
  COUNTIF(usage_rate IS NOT NULL AND is_dnp = FALSE) as has_usage_rate
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-02-01' AND is_dnp = FALSE"

# Check Jan 31
# ... same query with '2026-01-31'
```

If Feb 1 has 100% usage_rate coverage → Issue 2 is NEW (started Feb 2)
If Feb 1 also has 0% usage_rate → Issue 2 is ONGOING

### Common Root Cause Hypothesis

**Hypothesis:** Phase 3 orchestrator failure (Issue 4) may have caused partial processing:
- Processors started but didn't all complete
- Some wrote data (team_offense), others partially wrote (player_game)
- Orchestrator crashed before finalizing
- This explains:
  - No completion record (Issue 4)
  - Incomplete usage_rate JOINs (Issue 2)
  - Possibly missing BDL scrape if triggered by orchestrator (Issue 1)

**Test:** Check if Phase 2 → Phase 3 orchestrator has logs indicating partial failure.

---

## Priority Matrix

| Issue | Priority | Blocking | Est. Time | Must Fix Before |
|-------|----------|----------|-----------|-----------------|
| **Issue 1: Missing Game** | P0 | YES | 2-4h | Analysis, predictions |
| **Issue 4: No Completion Record** | P0 | YES | 1-2h | Validation, monitoring |
| **Issue 2: Usage Rate 0%** | P1 | NO | 2-6h | Feature generation |
| **Issue 5: Deployment Drift** | P1 | NO | 15m | Everything (eliminates variable) |
| **Issue 3: Minutes Coverage** | P2 | NO | N/A | May auto-fix with Issue 1 |

**Recommended Fix Order:**

1. **Issue 5 (Deploy stale services)** - 15 minutes, eliminates code version as variable
2. **Issue 4 (Orchestrator investigation)** - 1-2 hours, critical for understanding what happened
3. **Issue 1 (Missing game)** - 2-4 hours, most impactful to data quality
4. **Issue 2 (Usage rate)** - 2-6 hours, may reveal itself during Issue 4 investigation
5. **Issue 3 (Minutes coverage)** - Re-assess after Issue 1 fixed

---

## Data for Opus Context

### Environment
- **Date:** 2026-02-03 00:41 ET
- **Validation Type:** Yesterday's results (Feb 2 games)
- **GCP Project:** nba-props-platform
- **Region:** us-west2

### Games Validated
```
Game ID     | Teams       | Status | BDL Raw | Analytics | Predictions
------------|-------------|--------|---------|-----------|------------
0022500712  | NOP @ CHA   | Final  | 72 rec  | 20 active | Yes
0022500713  | HOU @ IND   | Final  | 34 rec  | 22 active | Yes
0022500714  | MIN @ MEM   | Final  | 70 rec  | 21 active | Yes
0022500715  | PHI @ LAC   | Final  | 0 rec ❌| 0 active ❌| Yes (bad data)
```

### Service Versions
```
Service                          | Status      | Commit   | Deployed
---------------------------------|-------------|----------|------------------
nba-phase1-scrapers              | Up to date  | (recent) | 2026-02-02 14:37
nba-phase3-analytics-processors  | STALE ❌    | 41bc42f4 | 2026-02-02 19:26
nba-phase4-precompute-processors | STALE ❌    | 41bc42f4 | 2026-02-02 19:28
prediction-coordinator           | STALE ❌    | 41bc42f4 | 2026-02-02 18:51
prediction-worker                | Up to date  | 41bc42f4 | 2026-02-02 20:36
```

### Key Files to Review

**For Issue 1 (Missing Game):**
- `scrapers/bdl_player_boxscores_scraper.py` - BDL scraper logic
- `scrapers/scheduler/` - Scraper scheduler configuration
- `scrapers/registry.py` - Scraper registration

**For Issue 2 (Usage Rate):**
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py` - JOIN logic
- `data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py` - Team data generation

**For Issue 4 (Orchestrator):**
- `orchestration/phase2_to_phase3_orchestrator.py` - Phase 3 trigger logic
- `shared/orchestration/` - Orchestrator utilities
- Firestore completion tracking code

**For Issue 5 (Deployment):**
- `bin/deploy-service.sh` - Deployment script
- `.github/workflows/` - CI/CD configuration (if exists)

---

## Questions for Opus Investigation

### Issue 1 - Missing Game
1. How does BDL scraper discover which games to scrape? (Schedule-based vs API discovery)
2. Is there a manual trigger endpoint to re-scrape game 0022500715?
3. Does the scraper have a "pending games" queue or retry mechanism?
4. Can we backfill this game or is it lost forever?

### Issue 2 - Usage Rate Failure
1. Walk through the exact JOIN logic between player and team tables
2. When (processing step) is usage_rate calculated?
3. Is there error handling that could silently skip usage_rate calculation?
4. Has this calculation been tested with the current game_id format?
5. Are there unit tests for usage_rate calculation?

### Issue 4 - Orchestrator Failure
1. What are the prerequisites for Phase 3 orchestrator to trigger?
2. Does it verify game count or just processor completion?
3. What's the timeout for waiting for processors?
4. Is there a fallback if Firestore write fails?
5. Should we manually create the completion record?

### Issue 5 - Deployment Drift
1. Why weren't these services auto-deployed?
2. Is there a deployment schedule or is it manual?
3. Can we add a gate that prevents processing with stale code?
4. Should deployment be part of the commit workflow?

### Cross-Cutting
1. Can we run a historical check to see when these issues started?
2. Are there other dates with similar issues we haven't discovered?
3. Should we invalidate predictions for Feb 2 until data is fixed?
4. What's the SLA for fixing data quality issues?

---

## Appendix: Validation Queries Used

### Minutes Coverage Check
```sql
SELECT
  COUNT(*) as total_players,
  COUNTIF(minutes_played IS NOT NULL AND minutes_played > 0) as has_minutes,
  ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL AND minutes_played > 0) /
    NULLIF(COUNT(*), 0), 1) as minutes_coverage_pct
FROM nba_analytics.player_game_summary
WHERE game_date = DATE('2026-02-02')
```

### Usage Rate Coverage Check
```sql
SELECT
  COUNT(*) as total_players,
  COUNTIF(usage_rate IS NOT NULL AND usage_rate > 0) as has_usage_rate,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL AND usage_rate > 0) /
    NULLIF(COUNT(*), 0), 1) as usage_rate_coverage_pct
FROM nba_analytics.player_game_summary
WHERE game_date = DATE('2026-02-02')
```

### Game-by-Game Breakdown
```sql
SELECT
  game_id,
  COUNT(*) as total_players,
  COUNTIF(is_dnp = FALSE) as players_who_played,
  COUNTIF(is_dnp = FALSE AND minutes_played IS NOT NULL) as has_minutes,
  COUNTIF(is_dnp = FALSE AND usage_rate IS NOT NULL) as has_usage_rate
FROM nba_analytics.player_game_summary
WHERE game_date = DATE('2026-02-02')
GROUP BY game_id
ORDER BY game_id
```

### BDL Raw Data Check
```sql
SELECT
  game_id,
  COUNT(*) as players
FROM nba_raw.bdl_player_boxscores
WHERE game_date = DATE('2026-02-02')
GROUP BY game_id
ORDER BY game_id
```

### Team Offense Data Check
```sql
SELECT
  game_id,
  team_abbr,
  possessions,
  fg_attempts,
  turnovers
FROM nba_analytics.team_offense_game_summary
WHERE game_date = DATE('2026-02-02')
ORDER BY game_id
```

---

## Next Steps for Opus

1. **Review this document thoroughly**
2. **Choose investigation priority** (recommend: Issue 4 → Issue 5 → Issue 1 → Issue 2)
3. **Run suggested investigation queries**
4. **Develop fix plan** with:
   - Immediate fixes (deploy, manual triggers)
   - Short-term fixes (code changes)
   - Long-term fixes (monitoring, tests, automation)
5. **Document findings** in session handoff
6. **Create prevention mechanisms** to avoid recurrence

---

**Document Status:** Ready for Opus Review
**Created:** 2026-02-03 00:45 ET by Sonnet (Claude Code)
**Next Action:** Opus to investigate and develop fix plan
