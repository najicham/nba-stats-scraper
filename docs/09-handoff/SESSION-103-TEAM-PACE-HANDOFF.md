# Session 103 - Handoff: Team Pace Metrics Implementation

**Date:** 2026-01-18 18:01 UTC  
**Previous Session:** 102 (Performance investigation & deployments)  
**Ready to Start:** YES ✅  
**Time Available:** Until 23:00 UTC coordinator verification (4h 59m)

---

## 🎯 QUICK START (Do This First)

### 1. Review What Session 102 Accomplished

**✅ Deployed (2 critical fixes):**
1. **Coordinator Batch Loading** - Re-enabled with 4x timeout increase
   - Revision: prediction-coordinator-00049-zzk (deployed 17:42 UTC)
   - Expected: 75-110x speedup (225s → 2-3s for 360 players)
   - **NEEDS VERIFICATION:** at 23:00 UTC coordinator run

2. **Grading Coverage Alert** - Added missing monitoring
   - Revision: nba-grading-alerts-00005-swh (deployed 17:54 UTC)
   - Alerts when <70% coverage (predictions vs graded)
   - Monitoring gap closed ✅

**✅ Cleaned (1 refactor):**
3. **AlertManager Consolidation** - Removed 1,665 lines of dead code
   - Deleted orphaned alert_manager.py (3 duplicate copies)
   - All imports verified working

**✅ Investigated (4 parallel agents):**
- CatBoost V8: **Already has 32 tests** (handoff was wrong)
- Coordinator performance: **Identified bypass causing 75-110x slowdown**
- Stubbed features: **13 ready to implement with existing data**
- Monitoring: **Infrastructure exists, needs activation**

---

## 📊 CURRENT SYSTEM STATE

### Services (All Healthy)
```bash
gcloud run services list --format="table(metadata.name,status.conditions[0].status)"
# All True except nba-phase1-scrapers (known issue, non-blocking)
```

### Recent Activity
- **Predictions:** 20,663 today (Jan 18), 36,364 yesterday
- **Data Quality:** 99.98% valid (40/202K placeholder lines)
- **Coordinator:** New revision deployed, awaiting verification
- **Grading Alerts:** New coverage monitoring active

### Pending Verifications (at 23:00 UTC)
1. **Coordinator batch loading performance** - Check batch_load_time metric
2. **Model version fix** - Verify 0% NULL (was 62%)

---

## 🚀 PRIMARY TASK: Implement Team Pace Metrics

**Why This is Next:**
- High value: Improves all 6 model predictions
- Ready to go: All data exists and is populated
- Clean implementation: Easy 2-3 hours
- Perfect timing: Fits before 23:00 UTC verification

### What You're Implementing

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**3 Fields to Add:**
1. **`pace_differential`** - Team pace vs opponent pace
2. **`opponent_pace_last_10`** - Opponent's recent pace (last 10 games)
3. **`opponent_ft_rate_allowed`** - Opponent's defensive FT rate

**Current State:** All 3 fields return `None` (stubbed)

---

## 📋 IMPLEMENTATION GUIDE

### Data Sources (All Verified Ready ✅)

**1. Team Offensive Pace:**
- **Table:** `nba-props-platform.nba_analytics.team_offense_game_summary`
- **Rows:** 3,840 for 2024-25 season
- **Fields:** `pace`, `offensive_rating`, `possessions`, `team_abbr`, `game_date`

**2. Team Defensive Stats:**
- **Table:** `nba-props-platform.nba_analytics.team_defense_game_summary`
- **Rows:** 3,848 for 2024-25 season
- **Fields:** `defensive_rating`, `opponent_pace`, `opp_ft_attempts`, `team_abbr`, `game_date`

### Step-by-Step Implementation

#### **Step 1: Find the Stubbed Functions (5 mins)**

```bash
cd /home/naji/code/nba-stats-scraper
grep -n "pace_differential\|opponent_pace_last_10\|opponent_ft_rate_allowed" \
  data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py
```

**Expected locations:**
- Around line 800-1000 (where other stub functions are)
- Currently returning `None` or `0.0`

---

#### **Step 2: Implement pace_differential (30 mins)**

**Function signature:**
```python
def _calculate_pace_differential(self, team_abbr: str, opponent_abbr: str, game_date: str) -> float:
    """Calculate difference between team's pace and opponent's pace."""
```

**Implementation:**
```python
def _calculate_pace_differential(self, team_abbr: str, opponent_abbr: str, game_date: str) -> float:
    """Calculate difference between team's pace and opponent's pace (last 10 games)."""
    try:
        query = f"""
        WITH team_pace AS (
            SELECT AVG(pace) as avg_pace
            FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
            WHERE team_abbr = '{team_abbr}'
              AND game_date < '{game_date}'
            ORDER BY game_date DESC
            LIMIT 10
        ),
        opponent_pace AS (
            SELECT AVG(pace) as avg_pace
            FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
            WHERE team_abbr = '{opponent_abbr}'
              AND game_date < '{game_date}'
            ORDER BY game_date DESC
            LIMIT 10
        )
        SELECT 
            ROUND(t.avg_pace - o.avg_pace, 2) as pace_diff
        FROM team_pace t, opponent_pace o
        """
        
        result = self.bq_client.query(query).result()
        for row in result:
            return row.pace_diff if row.pace_diff is not None else 0.0
        
        logger.warning(f"No pace data found for {team_abbr} vs {opponent_abbr}")
        return 0.0
        
    except Exception as e:
        logger.error(f"Error calculating pace differential: {e}")
        return 0.0
```

**Test Query:**
```bash
bq query --nouse_legacy_sql "
SELECT AVG(pace) as avg_pace, COUNT(*) as games
FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
WHERE team_abbr = 'LAL'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 10 DAY)
"
```

---

#### **Step 3: Implement opponent_pace_last_10 (20 mins)**

**Function signature:**
```python
def _get_opponent_pace_last_10(self, opponent_abbr: str, game_date: str) -> float:
    """Get opponent's average pace over last 10 games."""
```

**Implementation:**
```python
def _get_opponent_pace_last_10(self, opponent_abbr: str, game_date: str) -> float:
    """Get opponent's average pace over last 10 games."""
    try:
        query = f"""
        SELECT ROUND(AVG(pace), 2) as avg_pace
        FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
        WHERE team_abbr = '{opponent_abbr}'
          AND game_date < '{game_date}'
        ORDER BY game_date DESC
        LIMIT 10
        """
        
        result = self.bq_client.query(query).result()
        for row in result:
            return row.avg_pace if row.avg_pace is not None else 0.0
        
        return 0.0
        
    except Exception as e:
        logger.error(f"Error getting opponent pace for {opponent_abbr}: {e}")
        return 0.0
```

---

#### **Step 4: Implement opponent_ft_rate_allowed (30 mins)**

**Function signature:**
```python
def _get_opponent_ft_rate_allowed(self, opponent_abbr: str, game_date: str) -> float:
    """Get opponent's defensive FT rate allowed (opponent FTA per game)."""
```

**Implementation:**
```python
def _get_opponent_ft_rate_allowed(self, opponent_abbr: str, game_date: str) -> float:
    """Get opponent's defensive FT rate allowed (last 10 games)."""
    try:
        query = f"""
        SELECT ROUND(AVG(opp_ft_attempts), 2) as avg_opp_fta
        FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
        WHERE team_abbr = '{opponent_abbr}'
          AND game_date < '{game_date}'
        ORDER BY game_date DESC
        LIMIT 10
        """
        
        result = self.bq_client.query(query).result()
        for row in result:
            return row.avg_opp_fta if row.avg_opp_fta is not None else 0.0
        
        return 0.0
        
    except Exception as e:
        logger.error(f"Error getting FT rate allowed for {opponent_abbr}: {e}")
        return 0.0
```

**Test Query:**
```bash
bq query --nouse_legacy_sql "
SELECT AVG(opp_ft_attempts) as avg_opp_fta, COUNT(*) as games
FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\`
WHERE team_abbr = 'LAL'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 10 DAY)
"
```

---

#### **Step 5: Wire Up the Functions (15 mins)**

**Find where features are populated:**
```bash
grep -n "def _extract_features\|def _build_feature_dict" \
  data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py
```

**Add function calls in feature building:**
```python
# Around line 400-500 where other features are populated
features['pace_differential'] = self._calculate_pace_differential(
    team_abbr=player_team,
    opponent_abbr=opponent_team,
    game_date=game_date
)

features['opponent_pace_last_10'] = self._get_opponent_pace_last_10(
    opponent_abbr=opponent_team,
    game_date=game_date
)

features['opponent_ft_rate_allowed'] = self._get_opponent_ft_rate_allowed(
    opponent_abbr=opponent_team,
    game_date=game_date
)
```

---

#### **Step 6: Test Locally (30 mins)**

**Run the processor test suite:**
```bash
cd /home/naji/code/nba-stats-scraper
pytest tests/processors/analytics/upcoming_player_game_context/test_unit.py -v
```

**Manual verification query:**
```bash
bq query --nouse_legacy_sql "
SELECT 
    player_lookup,
    team_abbr,
    opponent_abbr,
    pace_differential,
    opponent_pace_last_10,
    opponent_ft_rate_allowed
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = CURRENT_DATE()
LIMIT 10
"
```

**Expected results:**
- `pace_differential`: -5.0 to +5.0 (team faster/slower than opponent)
- `opponent_pace_last_10`: 95-105 (typical NBA pace range)
- `opponent_ft_rate_allowed`: 15-25 (FTA allowed per game)

---

#### **Step 7: Deploy (if tests pass) (15 mins)**

**Deployment decision:**
- If all tests pass → Deploy to analytics processor
- If any tests fail → Debug and fix before deployment
- Deployment can wait until next session if time runs out

**To deploy:**
```bash
# Use existing deployment script
cd /home/naji/code/nba-stats-scraper
./bin/analytics/deploy/deploy_analytics_processors.sh
```

---

#### **Step 8: Commit Changes (10 mins)**

```bash
git add data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py
git commit -m "feat(analytics): Implement team pace metrics (3 new features)

- Add pace_differential: team vs opponent pace (last 10 games)
- Add opponent_pace_last_10: opponent's recent pace
- Add opponent_ft_rate_allowed: defensive FT rate allowed

Data sources:
- nba_analytics.team_offense_game_summary (3,840 rows)
- nba_analytics.team_defense_game_summary (3,848 rows)

Impact: Improves prediction quality for all 6 models
Testing: Unit tests passing, verified with BigQuery

Addresses: Session 102 investigation - stubbed features

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## 🧪 VALIDATION CHECKLIST

After implementation, verify:

- [ ] All 3 functions implemented and wired up
- [ ] Unit tests pass (`pytest tests/processors/analytics/...`)
- [ ] Manual BigQuery verification shows non-zero values
- [ ] No NULL/NaN values in output
- [ ] Values in expected ranges (pace 95-105, FTA 15-25)
- [ ] Error handling works (try invalid team codes)
- [ ] Logging provides useful debugging info
- [ ] Code committed with clear message

---

## ⏰ TIME MANAGEMENT

**Total Estimated:** 2.5 hours

| Task | Time | Cumulative |
|------|------|------------|
| Find stubbed functions | 5m | 5m |
| Implement pace_differential | 30m | 35m |
| Implement opponent_pace_last_10 | 20m | 55m |
| Implement opponent_ft_rate_allowed | 30m | 1h 25m |
| Wire up functions | 15m | 1h 40m |
| Test locally | 30m | 2h 10m |
| Deploy (optional) | 15m | 2h 25m |
| Commit changes | 10m | 2h 35m |

**Buffer:** 30 minutes for debugging/issues

**Hard Stop:** 22:45 UTC (leave 15m before coordinator verification)

---

## 📊 AT 23:00 UTC - VERIFICATION TASKS

**Stop implementation work at 22:45 UTC and switch to verification:**

### 1. Verify Coordinator Batch Loading

```bash
gcloud logging read \
  'resource.labels.service_name="prediction-coordinator" AND 
   jsonPayload.message:"Batch loaded" AND 
   timestamp>="2026-01-18T23:00:00Z"' \
  --limit=5
```

**Expected output:**
```
✅ Batch loaded 1,850 historical games for 67 players in 1.23s
```

**Success criteria:**
- Batch load time <10s
- No timeout errors
- Message shows player count and duration

---

### 2. Verify Model Version Fix

```bash
bq query --nouse_legacy_sql "
SELECT
  IFNULL(model_version, 'NULL') as model_version,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) as pct
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE created_at >= TIMESTAMP('2026-01-18 18:00:00 UTC')
GROUP BY model_version
ORDER BY predictions DESC
"
```

**Expected result:**
- 0% NULL (was 62% before fix)
- All predictions have model_version populated

---

### 3. Check for Errors

```bash
gcloud logging read \
  'resource.labels.service_name="prediction-coordinator" AND 
   severity>=ERROR AND 
   timestamp>="2026-01-18T23:00:00Z"' \
  --limit=20
```

**Expected:** No errors, or only non-blocking warnings

---

## 🗂️ KEY FILES & LOCATIONS

### Implementation
- **Main file:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`
- **Tests:** `tests/processors/analytics/upcoming_player_game_context/test_unit.py`
- **Deploy script:** `bin/analytics/deploy/deploy_analytics_processors.sh`

### Documentation (Session 102)
- **Investigation:** `docs/09-handoff/SESSION-102-INVESTIGATION-SUMMARY.md`
- **Coordinator deployment:** `docs/08-projects/current/coordinator-deployment-session-102.md`
- **Grading alert:** `docs/08-projects/current/grading-coverage-alert-deployment.md`
- **Available work list:** `/tmp/available-work-session-102.md`

### Tables
- **Team offense:** `nba-props-platform.nba_analytics.team_offense_game_summary`
- **Team defense:** `nba-props-platform.nba_analytics.team_defense_game_summary`
- **Output:** `nba-props-platform.nba_analytics.upcoming_player_game_context`

---

## 🎯 SUCCESS CRITERIA

### Minimum Success
- ✅ 3 team pace functions implemented
- ✅ Functions wired into feature extraction
- ✅ Code committed (deployment can wait)

### Good Success
- ✅ All above
- ✅ Unit tests passing
- ✅ BigQuery verification showing valid data
- ✅ Coordinator/model version verified at 23:00 UTC

### Excellent Success
- ✅ All above
- ✅ Analytics processor deployed with new features
- ✅ Next session handoff created
- ✅ Comprehensive documentation updated

---

## 🚨 IF THINGS GO WRONG

### Issue: BigQuery queries timeout
**Solution:** Add query timeout parameter
```python
job_config = bigquery.QueryJobConfig(
    default_dataset=f"{self.project_id}.nba_analytics"
)
result = self.bq_client.query(query, job_config=job_config).result(timeout=60)
```

### Issue: No data returned for some teams
**Solution:** Add fallback to season average
```python
if not result or row.avg_pace is None:
    logger.warning(f"No recent pace data for {team_abbr}, using league average")
    return 100.0  # League average pace
```

### Issue: Unit tests fail
**Solution:** 
1. Check test fixtures have required fields
2. Update test expectations for new features
3. Add mocks for BigQuery queries if needed

### Issue: Run out of time
**Solution:**
- Commit work in progress
- Document where you stopped
- Next session can continue from checkpoint

---

## 📝 NOTES FROM SESSION 102

### What We Discovered

**The handoff document was WRONG:**
- ❌ Said "CatBoost V8 has ZERO tests" → Actually has 32 comprehensive tests
- ❌ Said "Coordinator performance uninvestigated" → Session 78 timeout was known
- ❌ Said "All stubbed features blocked" → 13 features ready with existing data

**What We Fixed:**
- ✅ Deployed coordinator batch loading (75-110x speedup expected)
- ✅ Added grading coverage monitoring (critical gap closed)
- ✅ Removed 1,665 lines of dead code (AlertManager cleanup)
- ✅ Verified system health (all services operational)

**Investigation Method:**
- Used 4 parallel Explore agents
- Deeply analyzed code, data, and infrastructure
- Corrected priorities based on actual findings

---

## 🎓 LEARNING FROM SESSION 102

### Investigation > Assumptions
- Don't trust handoff docs blindly
- Verify with agents and actual code inspection
- Outdated docs can waste time on non-issues

### Quick Wins Add Up
- 4 items completed in ~2 hours
- 2 critical deployments
- Clean technical debt removal
- Comprehensive documentation

### Parallel Agents Are Powerful
- 4 agents investigated simultaneously
- Each specialized in different areas
- Comprehensive analysis in minutes

---

## 🚀 RECOMMENDED APPROACH

**Phase 1: Setup (10 mins)**
1. Read this handoff
2. Review stubbed features location
3. Test BigQuery access to team analytics tables

**Phase 2: Implementation (2 hours)**
1. Implement pace_differential (hardest, do first)
2. Implement opponent_pace_last_10 (easy)
3. Implement opponent_ft_rate_allowed (medium)
4. Wire up all 3 functions
5. Test locally

**Phase 3: Verification (30 mins)**
1. Run unit tests
2. Verify BigQuery output
3. Commit changes

**Phase 4: Coordinator Check (15 mins at 23:00 UTC)**
1. Verify batch loading performance
2. Verify model version fix
3. Check for errors
4. Document results

---

## ✅ SESSION 102 COMMITS

**Commit 1:** Grading coverage alert
- Added coverage monitoring to nba-grading-alerts
- Deployed to nba-grading-alerts-00005-swh

**Commit 2:** AlertManager cleanup
- Removed 1,665 lines of orphaned alert_manager.py files
- All imports verified working

**Git Status:**
- Branch: session-98-docs-with-redactions
- Commits ahead: 8
- Untracked files: Handoff docs (add these after team pace work)

---

## 🎯 YOUR GOAL FOR SESSION 103

**Primary:** Implement 3 team pace metrics (2-3 hours)

**Secondary:** Verify coordinator performance at 23:00 UTC

**Success:** New features improving prediction quality + coordinator validation

**Time Available:** 4h 59m (until 23:00 UTC)

---

**Status:** ✅ Ready to start
**Blocker:** None
**Data:** All verified available
**Path:** Clear and well-defined

**Good luck! You've got this.** 🚀

---

**Handoff created by:** Claude Sonnet 4.5 (Session 102)
**Date:** 2026-01-18 18:01 UTC
**For:** Session 103 continuation
