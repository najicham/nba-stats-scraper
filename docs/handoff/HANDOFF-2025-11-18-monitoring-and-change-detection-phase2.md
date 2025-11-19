# Session Handoff: Monitoring & Change Detection Documentation (Phase 2)

**Date:** 2025-11-18
**Session:** Monitoring infrastructure improvements
**Context Used:** 82% at handoff decision point
**Status:** Phase 1 complete, Phase 2 ready to execute

---

## ✅ **What Was Completed This Session**

### 1. Created 3 Monitoring Documents
- ✅ `docs/monitoring/04-observability-gaps-and-improvement-plan.md`
  - What visibility exists vs what's missing
  - Gap analysis for Phase 1 (excellent) vs Phase 2-5 (gaps)
  - Prioritized implementation plan

- ✅ `docs/monitoring/OBSERVABILITY_QUICK_REFERENCE.md`
  - One-page quick reference card
  - What you can vs can't see today
  - Quick decision guide

- ✅ `docs/monitoring/05-data-completeness-validation.md`
  - Daily completeness validation
  - Backfill completeness validation
  - Row count reconciliation
  - Missing entity detection
  - Recovery procedures

### 2. Created Change Detection Investigation Framework
- ✅ `docs/architecture/07-change-detection-current-state-investigation.md`
  - Investigation queries to check current behavior
  - Test scenarios for player AND team entity-level changes
  - Decision matrix based on findings
  - Covers cross-entity dependencies (team changes → player reprocessing)

### 3. Updated Navigation
- ✅ Updated `docs/monitoring/README.md`
- ✅ Updated `docs/architecture/README.md`
- ✅ Updated `docs/README.md` main navigation

---

## 📋 **What's Next (To Be Done in Next Session)**

### High Priority (6-11 hours)

#### 1. Cross-Date Dependency Management Doc (5-6 hours)
**File:** `docs/architecture/08-cross-date-dependency-management.md`

**Purpose:** Document how processors depend on historical data, not just same-date data

**Key Content Sections:**
1. Cross-Date Dependency Matrix
2. Lookback Window Requirements
3. Early Season Handling
4. Backfill Orchestration Order
5. Dependency Check Queries for Historical Data

---

#### 2. Backfill Operations Guide (4-5 hours)
**File:** `docs/operations/backfill-operations-guide.md`

**Purpose:** How to actually run backfills safely

**Key Content Sections:**
1. When to Backfill vs When to Skip
2. Backfill Order and Sequencing
3. Date Range Calculation (including lookback windows)
4. Validation Before/After Each Phase
5. Partial Backfill Recovery
6. Early Season Special Handling
7. Example Scenarios with Commands

---

### Medium Priority (5-7 hours)

#### 3. Alerting Strategy & Escalation (3-4 hours)
**File:** `docs/monitoring/06-alerting-strategy-and-escalation.md`

**Purpose:** When to alert, who to alert, severity levels

**Key Content Sections:**
1. Alert Severity Matrix
2. Escalation Paths
3. Backfill Progress Alerts
4. Cross-Date Dependency Missing Alerts
5. Stalled Backfill Detection
6. On-Call Runbooks
7. Alert Fatigue Prevention

---

#### 4. Single Entity Debugging (2-3 hours)
**File:** `docs/monitoring/DEBUGGING_SINGLE_ENTITY.md`

**Purpose:** Trace a single player/team through all phases

**Key Content Sections:**
1. Player Trace Query
2. Team Trace Query
3. Game Trace Query
4. "Why didn't this entity process?" Checklist
5. Check Historical Data Availability

---

## 🔑 **Critical Information From User**

### Cross-Date Dependencies

**User's Example:**
> "When checking how a player did on a specific amount of days rest and calculating their fatigue score, that requires having data from the beginning of the season or the past year. This isn't implemented as a dependency check yet in the code but it will be."

**Key Implication:**
- Some processors need historical context, not just today's data
- Phase 4/5 may need "last 10 games" or "last 15 games" or "season-to-date"
- Backfill order matters: Must fill historical dates BEFORE running processors that need lookback

**Examples to Document:**
```
Processor: player_shot_zone_analysis
  Depends on: Last 10 games from player_game_summary
  Lookback: 10 game dates (not 10 calendar days!)
  Min required: 5 games (degraded mode)

Processor: fatigue_score_calculator (future)
  Depends on: Days of rest calculation
  Lookback: Beginning of season or past year
  Min required: Season start date
```

---

### Historical Data Available

**User's Context:**
- ✅ **4 past seasons scraped** (2020-21 through 2023-24)
- ✅ Can backfill any date in those 4 seasons
- ✅ Daily scrapers run, but may fail occasionally
- ✅ May need manual re-scraping if data was wrong

**Backfill Scenarios to Document:**

1. **Historical Backfill**
   - Backfill entire 2023-24 season (Oct 2023 - Apr 2024)
   - ~180 game dates × 5 phases = 900 phase-date combinations
   - Validation critical: Need to verify all 900 completed

2. **Gap Filling**
   - Daily scraper failed Nov 8-14
   - Backfill those 7 dates
   - Validate each phase before next

3. **Re-Processing**
   - Scraped data had error, manually fixed in GCS
   - Need to re-run Phase 2→5 for that date
   - Not technically a "backfill" but same process

4. **Manual Correction**
   - Data was wrong, manually changed in BigQuery
   - Need to re-run downstream processors only
   - Need to track which phases need re-running

---

### Existing Backfill Infrastructure

**Location:** `/home/naji/code/nba-stats-scraper/backfill_jobs`

**User's Context:**
> "I have some backfill jobs in /home/naji/code/nba-stats-scraper/backfill_jobs that handle the scraper backfill and the other phases have their own cloud run job config that can be deployed with a script from the bin directory. I don't have backfill jobs for everything yet and lately I have been running them locally."

**Implications:**
- Some automation exists but incomplete
- Currently manual/local execution
- Document process, don't require full automation
- Link to existing scripts where they exist
- Provide commands even if no script exists

---

## 📐 **Doc 2 Outline: Cross-Date Dependency Management**

### Recommended Structure

```markdown
# Cross-Date Dependency Management

## Overview
- Same-date dependencies (Phase 2→3 for Nov 18)
- Cross-date dependencies (Phase 4 needs last 10 games)
- Why this matters for backfills

## Cross-Date Dependency Matrix

| Processor | Depends On | Lookback Window | Min Games | Fallback Strategy |
|-----------|-----------|-----------------|-----------|-------------------|
| player_shot_zone_analysis | Phase 3: player_game_summary | Last 10 games | 5 | Use available, set quality score |
| player_composite_factors | Phase 3: player_game_summary | Season-to-date | 3 | Early season flag |
| fatigue_score (future) | Phase 3: player_game_summary | Season start or 1 year | 30 | N/A - skip if insufficient |
| ml_feature_store_v2 | Phase 4: player_shot_zone | Last 15 games | 10 | Use available, lower confidence |

## Lookback Window Requirements

### Game-Based Lookback (Not Calendar Days!)
**Important:** "Last 10 games" means last 10 game dates the PLAYER played, not last 10 calendar days

**Example:**
```
Player: LeBron James
Current date: Nov 18
Last game: Nov 17 (played)
Game before: Nov 15 (played)
Nov 14: DNP - Rest
Nov 13: (played)
Nov 12: (played)
...

To get "last 10 games":
- Query for last 10 dates WHERE player_id = lebron AND minutes_played > 0
- NOT: game_date BETWEEN Nov 8 AND Nov 17
```

### Calendar-Based Lookback
**Used for:** Team-level stats, league-wide aggregations

**Example:**
```
Team: Lakers
Current date: Nov 18
Last 10 games = last 10 games Lakers played (not 10 calendar days)
```

## Early Season Handling

### Problem: Insufficient Historical Data

**Scenario:**
- Season starts Oct 22
- Player has only played 3 games by Oct 28
- Processor needs "last 10 games"
- Only 3 available

**Solutions:**

1. **Degraded Mode:**
```sql
-- Use available games, flag as degraded
IF historical_games >= required_games THEN
  quality_score = 100
ELSE
  quality_score = (historical_games / required_games) * 100
  early_season_flag = TRUE
END IF
```

2. **Skip Processing:**
```sql
-- Skip if below minimum threshold
IF historical_games < minimum_required THEN
  SKIP PROCESSING
  LOG "Insufficient data for player_id={id}, games={count}, required={min}"
END IF
```

3. **Use Defaults:**
```sql
-- Use league average or position average
IF historical_games < required_games THEN
  use_league_average = TRUE
  confidence_score = LOW
END IF
```

## Dependency Check Queries

### Check Historical Data Availability

```sql
-- Check if Phase 4 can run for Nov 18 (needs last 10 games)
WITH player_history AS (
  SELECT
    player_id,
    COUNT(DISTINCT game_date) as historical_games,
    MIN(game_date) as first_game,
    MAX(game_date) as last_game
  FROM nba_analytics.player_game_summary
  WHERE game_date BETWEEN DATE_SUB('2025-11-18', INTERVAL 30 DAY) AND '2025-11-17'
    -- 30 day window should capture 10 games
  GROUP BY player_id
)
SELECT
  player_id,
  historical_games,
  first_game,
  last_game,
  CASE
    WHEN historical_games >= 10 THEN '✅ Can process normally'
    WHEN historical_games >= 5 THEN '⚠️ Degraded mode (5-9 games)'
    WHEN historical_games >= 3 THEN '⚠️ Early season mode (3-4 games)'
    ELSE '❌ Skip (< 3 games)'
  END as processing_status
FROM player_history
ORDER BY historical_games ASC;
```

### Check Cross-Phase Dependencies

```sql
-- Verify all required historical data exists before running Phase 4
DECLARE target_date DATE DEFAULT '2025-11-18';
DECLARE lookback_days INT64 DEFAULT 30;  -- Should capture 10 games

WITH required_dates AS (
  SELECT DISTINCT game_date
  FROM nba_raw.nbac_schedule
  WHERE game_date BETWEEN DATE_SUB(target_date, INTERVAL lookback_days DAY) AND target_date - 1
),
available_dates AS (
  SELECT DISTINCT game_date
  FROM nba_analytics.player_game_summary
)

SELECT
  r.game_date,
  CASE WHEN a.game_date IS NOT NULL THEN '✅' ELSE '❌' END as phase3_available
FROM required_dates r
LEFT JOIN available_dates a ON r.game_date = a.game_date
ORDER BY r.game_date;

-- If any ❌, cannot run Phase 4 for target_date yet
```

## Backfill Orchestration Order

### Correct Order for Cross-Date Dependencies

**Problem:** Can't run Phase 4 for Nov 18 without Phase 3 for Nov 8-17

**Solution:** Sequential backfill by phase, not by date

**WRONG Approach:**
```bash
# Don't do this!
for date in Nov-08 Nov-09 ... Nov-18; do
  run_phase2 $date
  run_phase3 $date
  run_phase4 $date  # FAILS for Nov-08: needs Oct 29-Nov 07 data
  run_phase5 $date
done
```

**CORRECT Approach:**
```bash
# Fill all Phase 2 first, then Phase 3, then Phase 4
# Phase 1: Scrapers (can be parallel)
for date in Oct-29 ... Nov-18; do
  run_phase1_scrapers $date
done

# Phase 2: Raw processing (can be parallel after Phase 1 complete)
for date in Oct-29 ... Nov-18; do
  run_phase2 $date
done

# Validate Phase 2 complete for ALL dates
validate_phase2 Oct-29 Nov-18

# Phase 3: Analytics (can be parallel after Phase 2 complete)
for date in Oct-29 ... Nov-18; do
  run_phase3 $date
done

# Validate Phase 3 complete for ALL dates
validate_phase3 Oct-29 Nov-18

# Phase 4: Now safe to run (has 10-game historical context)
for date in Nov-08 ... Nov-18; do
  run_phase4 $date  # ✅ Has Oct 29-Nov 07 available
done
```

## Date Range Calculation

### Include Lookback Windows in Range

**User wants to backfill:** Nov 8-14

**Calculate required range:**
```
Target dates: Nov 8-14
Phase 4 lookback: 10 games ≈ 30 calendar days
Required range: Oct 9 - Nov 14

Check what exists:
- Phase 3 exists: Oct 1 - Nov 7 ✅
- Phase 3 missing: Oct 9 - Oct 30 ❌

Actual backfill needed:
- Phase 2+3: Oct 9 - Oct 30 (fill the gap)
- Phase 4: Nov 8 - Nov 14 (original target)
```

**Formula:**
```python
def calculate_backfill_range(target_start, target_end, lookback_days=30):
    """
    Calculate full range needed for backfill including lookback.

    Args:
        target_start: First date user wants to backfill
        target_end: Last date user wants to backfill
        lookback_days: How many days of history needed (default 30 for 10 games)

    Returns:
        (phase2_start, phase2_end, phase4_start, phase4_end)
    """
    # Phase 2-3 must cover lookback window
    phase2_start = target_start - timedelta(days=lookback_days)
    phase2_end = target_end

    # Phase 4-5 only for target range
    phase4_start = target_start
    phase4_end = target_end

    return (phase2_start, phase2_end, phase4_start, phase4_end)

# Example
target = (Nov 8, Nov 14)
ranges = calculate_backfill_range(Nov 8, Nov 14, lookback_days=30)
# Returns:
# Phase 2-3: Oct 9 - Nov 14
# Phase 4-5: Nov 8 - Nov 14
```

## Related Documentation
- `docs/monitoring/05-data-completeness-validation.md` - How to validate backfills
- `docs/operations/backfill-operations-guide.md` - How to run backfills (NEXT DOC)
- `docs/architecture/07-change-detection-current-state-investigation.md` - Entity-level investigation
```

---

## 📐 **Doc 3 Outline: Backfill Operations Guide**

### Recommended Structure

```markdown
# Backfill Operations Guide

## When to Backfill

### Scenario 1: Historical Data (Full Season)
**Use case:** Fill 2023-24 season before predictions go live
**Range:** Oct 24, 2023 - Apr 14, 2024 (~180 game dates)
**Phases:** All (1-5)

### Scenario 2: Gap Filling (Missing Days)
**Use case:** Daily scrapers failed Nov 8-14
**Range:** Nov 8-14 (7 dates)
**Phases:** All (1-5)

### Scenario 3: Re-Processing (Data Fix)
**Use case:** Scraped data had error, manually fixed
**Range:** Nov 15 (1 date)
**Phases:** Phase 2-5 only (Phase 1 scraped data already corrected)

### Scenario 4: Downstream Re-Processing
**Use case:** Manual change in BigQuery Phase 3 table
**Range:** Nov 10-15 (6 dates)
**Phases:** Phase 4-5 only (Phase 3 already has correct data)

## Backfill Order and Sequencing

### Rule 1: Always Phase-by-Phase, Not Date-by-Date
Due to cross-date dependencies, backfill ALL dates for Phase N before starting Phase N+1

### Rule 2: Validate Between Phases
Check completeness after each phase before starting next

### Rule 3: Include Lookback Windows
Calculate required range including historical context needed

## Date Range Calculation

### Tool: Calculate Backfill Range
```bash
#!/bin/bash
# bin/backfill/calculate_range.sh

TARGET_START=$1  # e.g., 2024-11-08
TARGET_END=$2    # e.g., 2024-11-14
LOOKBACK_DAYS=${3:-30}  # Default 30 days for ~10 games

# Calculate Phase 2-3 range (includes lookback)
PHASE2_START=$(date -d "$TARGET_START - $LOOKBACK_DAYS days" +%Y-%m-%d)
PHASE2_END=$TARGET_END

# Phase 4-5 range (target only)
PHASE4_START=$TARGET_START
PHASE4_END=$TARGET_END

echo "Target range: $TARGET_START to $TARGET_END"
echo "Phase 2-3 range: $PHASE2_START to $PHASE2_END"
echo "Phase 4-5 range: $PHASE4_START to $PHASE4_END"
echo ""
echo "Dates to backfill for Phase 2-3:"
seq -f "2024-11-%02g" $(date -d $PHASE2_START +%d) $(date -d $PHASE2_END +%d)
```

## Validation Before/After Each Phase

### Before Phase N
- [ ] Verify Phase N-1 complete for ALL dates in range
- [ ] Check row counts match expectations
- [ ] No gaps in date range

### After Phase N
- [ ] Run completeness validation (see Query 2 in 05-data-completeness-validation.md)
- [ ] Check row counts
- [ ] Verify no missing dates
- [ ] Sample check: Pick 3 random dates, verify data quality

## Example Scenarios with Commands

### Scenario 1: Backfill Nov 8-14

```bash
# Step 1: Calculate range
START_DATE="2024-11-08"
END_DATE="2024-11-14"
LOOKBACK=30

# Phase 2-3 needs Oct 9 - Nov 14
# Phase 4-5 needs Nov 8 - Nov 14

# Step 2: Check what exists
./bin/backfill/check_existing.sh --start=2024-10-09 --end=2024-11-14

# Output shows:
# Oct 9-31: Phase 2 ❌, Phase 3 ❌
# Nov 1-7: Phase 2 ✅, Phase 3 ✅
# Nov 8-14: Phase 2 ❌, Phase 3 ❌, Phase 4 ❌, Phase 5 ❌

# Step 3: Backfill Phase 1 (scrapers) for Oct 9-31 and Nov 8-14
cd backfill_jobs
./run_scraper_backfill.sh --start=2024-10-09 --end=2024-10-31
./run_scraper_backfill.sh --start=2024-11-08 --end=2024-11-14

# Step 4: Validate Phase 1 complete
./bin/backfill/validate_phase1.sh --start=2024-10-09 --end=2024-11-14

# Step 5: Backfill Phase 2 (raw processors)
for phase in nbac-gamebook nbac-team-boxscore odds-api-spreads; do
  gcloud run jobs execute phase2-$phase \
    --region us-central1 \
    --set-env-vars "START_DATE=2024-10-09,END_DATE=2024-11-14"
done

# Step 6: Validate Phase 2 complete
./bin/backfill/validate_phase2.sh --start=2024-10-09 --end=2024-11-14

# Step 7: Backfill Phase 3 (analytics)
gcloud run jobs execute phase3-player-game-summary \
  --region us-central1 \
  --set-env-vars "START_DATE=2024-10-09,END_DATE=2024-11-14"

gcloud run jobs execute phase3-team-offense-game-summary \
  --region us-central1 \
  --set-env-vars "START_DATE=2024-10-09,END_DATE=2024-11-14"

# ... (other Phase 3 processors)

# Step 8: Validate Phase 3 complete
./bin/backfill/validate_phase3.sh --start=2024-10-09 --end=2024-11-14

# Step 9: Backfill Phase 4 (now has historical context!)
gcloud run jobs execute phase4-player-shot-zone-analysis \
  --region us-central1 \
  --set-env-vars "START_DATE=2024-11-08,END_DATE=2024-11-14"

# ... (other Phase 4 processors)

# Step 10: Validate Phase 4 complete
./bin/backfill/validate_phase4.sh --start=2024-11-08 --end=2024-11-14

# Step 11: Backfill Phase 5 (predictions)
gcloud run jobs execute phase5-prediction-coordinator \
  --region us-central1 \
  --set-env-vars "START_DATE=2024-11-08,END_DATE=2024-11-14"

# Step 12: Final validation
./bin/backfill/validate_all_phases.sh --start=2024-11-08 --end=2024-11-14
```

## Early Season Special Handling

### Problem: Season Start Has No Historical Data

**Scenario:** Season starts Oct 22, backfilling Oct 22 - Nov 5

**Challenge:**
- First 10 games don't have 10-game lookback
- Phase 4 processors expect historical context

**Solution: Progressive Quality Scores**

```bash
# Phase 1-3: Normal backfill (no lookback needed)
./run_phases_1_3.sh --start=2024-10-22 --end=2024-11-05

# Phase 4-5: Accept degraded quality for early dates
gcloud run jobs execute phase4-player-shot-zone-analysis \
  --region us-central1 \
  --set-env-vars "START_DATE=2024-10-22,END_DATE=2024-11-05,EARLY_SEASON_MODE=true"

# Early season mode:
# - Oct 22: 0 historical games → quality_score = 0, skip or use defaults
# - Oct 24: 1 historical game → quality_score = 10
# - Oct 27: 3 historical games → quality_score = 30
# - Nov 5: 10 historical games → quality_score = 100 ✅
```

## Partial Backfill Recovery

### Problem: Phase 3 Failed Midway Through Range

**Diagnosis:**
```bash
# Check which dates completed Phase 3
./bin/backfill/check_existing.sh --start=2024-11-08 --end=2024-11-14 --phase=3

# Output:
# Nov 8: ✅
# Nov 9: ✅
# Nov 10: ✅
# Nov 11: ❌  <-- Failed here
# Nov 12: ❌
# Nov 13: ❌
# Nov 14: ❌
```

**Recovery:**
```bash
# Re-run only failed dates
gcloud run jobs execute phase3-player-game-summary \
  --region us-central1 \
  --set-env-vars "START_DATE=2024-11-11,END_DATE=2024-11-14"

# Validate
./bin/backfill/validate_phase3.sh --start=2024-11-08 --end=2024-11-14
```

## Related Documentation
- `docs/monitoring/05-data-completeness-validation.md` - Validation queries
- `docs/architecture/08-cross-date-dependency-management.md` - Understanding dependencies
```

---

## 🎯 **Next Session Action Plan**

1. **Start with Doc 2:** Cross-Date Dependency Management
   - Use outline above
   - Flesh out each section
   - Add user's fatigue score example
   - Add dependency check queries

2. **Then create Doc 3:** Backfill Operations Guide
   - Use outline above
   - Link to existing scripts in `/home/naji/code/nba-stats-scraper/backfill_jobs`
   - Provide commands even where scripts don't exist yet
   - Document current process (manual/local)

3. **Update navigation** in README files

4. **Validate completeness:**
   - All user questions answered?
   - Cross-date dependencies well explained?
   - Backfill process clear?
   - Early season handling documented?

---

## 📊 **Estimated Effort Remaining**

| Task | Effort | Priority |
|------|--------|----------|
| Doc 2: Cross-Date Dependencies | 5-6 hours | Critical |
| Doc 3: Backfill Operations | 4-5 hours | Critical |
| Doc 4: Alerting Strategy | 3-4 hours | High |
| Doc 5: Single Entity Debugging | 2-3 hours | Medium |

**Total:** 14-18 hours remaining work

**Critical path (Docs 2-3):** 9-11 hours

---

## 🔗 **Files Created This Session**

1. `docs/monitoring/04-observability-gaps-and-improvement-plan.md`
2. `docs/monitoring/OBSERVABILITY_QUICK_REFERENCE.md`
3. `docs/monitoring/05-data-completeness-validation.md`
4. `docs/architecture/07-change-detection-current-state-investigation.md`
5. `docs/monitoring/README.md` (updated)
6. `docs/architecture/README.md` (updated)
7. `docs/README.md` (updated)

---

## ✅ **Session Complete**

**Status:** Phase 1 documentation complete, Phase 2 ready to execute
**Next:** Create Docs 2-3 using outlines above
**Context at handoff:** 82% (safe to start new session)

---

**Handoff created:** 2025-11-18
**Ready for next session:** ✅
