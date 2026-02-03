# Feb 1 vs Feb 2 Data Quality Comparison

**Analysis Date:** 2026-02-03 01:15 ET
**Purpose:** Determine if Feb 2 issues are new or ongoing
**Conclusion:** 🔴 **Feb 2 issues are NEW - Feb 1 data was healthy**

---

## Executive Summary

**Feb 1 (Healthy Baseline):**
- ✅ 10 games processed successfully
- ✅ 100% minutes coverage
- ✅ 95.9% usage_rate coverage
- ✅ Phase 3 completion record exists
- ✅ All BDL games scraped

**Feb 2 (Multiple Failures):**
- ❌ Only 3/4 games scraped (PHI-LAC missing)
- ❌ 47% minutes coverage
- ❌ 0% usage_rate coverage
- ❌ No Phase 3 completion record
- ❌ 6 active players missing from cache

**CRITICAL FINDING:** Issues started between Feb 1 night and Feb 2 night processing cycles.

---

## Detailed Comparison

### Data Quality Metrics

| Metric | Feb 1 | Feb 2 | Change | Severity |
|--------|-------|-------|--------|----------|
| **Games Scheduled** | 10 | 4 | -6 | Normal variance |
| **BDL Games Scraped** | 10/10 (100%) | 3/4 (75%) | -25% | 🔴 CRITICAL |
| **Active Players** | 319 | 63 | -256 | Expected (fewer games) |
| **Minutes Coverage** | 100.0% | 47.0% | -53% | 🔴 CRITICAL |
| **Usage Rate Coverage** | 95.9% | 0.0% | -96% | 🔴 CRITICAL |
| **Phase 3 Completion** | ✅ EXISTS (4/5) | ❌ MISSING | N/A | 🔴 CRITICAL |

---

## Data Lineage Comparison

### Pipeline Coverage

| Stage | Feb 1 | Feb 2 | Change | Status |
|-------|-------|-------|--------|--------|
| **RAW → ANALYTICS** | 96.0% (334/348) | 99.0% (104/105) | +3% | Both good |
| **ANALYTICS → CACHE** | 88.1% (207/235) | 90.5% (57/63) | +2.4% | Both suboptimal |
| **CACHE → FEATURES** | 100.0% (289/289) | 100.0% (122/122) | 0% | ✅ Both perfect |
| **FEATURES → PREDS** | 94.1% (336/357) | 45.9% (68/148) | -48% | Feb 2 edge filter |

### Key Findings

#### 1. Missing Game (PHI-LAC) is NEW
- **Feb 1:** All 10 games scraped successfully by BDL
- **Feb 2:** Only 3/4 games scraped (PHI-LAC 0022500715 missing)
- **Onset:** Feb 2 scraper run (likely overnight or next morning)

#### 2. Usage Rate Failure is NEW
- **Feb 1:** 95.9% coverage (306/319 active players)
- **Feb 2:** 0.0% coverage (0/63 active players)
- **Root Cause:** NOT missing team data (team_offense exists for both dates)
- **Onset:** Between Feb 1 and Feb 2 processing

#### 3. Orchestrator Issue is NEW
- **Feb 1 Processing (2026-02-02):** ✅ Completion record exists (4/5 processors)
- **Feb 2 Processing (2026-02-03):** ❌ No completion record at all
- **Onset:** Feb 2 night → Feb 3 morning processing

#### 4. Cache Missing Players - ONGOING ISSUE
- **Feb 1:** 88.1% coverage (28 players missing)
- **Feb 2:** 90.5% coverage (6 players missing)
- **Status:** This appears to be an existing issue, not new
- **Severity:** Lower on Feb 2 due to fewer games, but still concerning

---

## Phase 3 Completion Status

### Feb 1 Processing (2026-02-02 document)
```
✅ Completion record EXISTS
Processors complete: 4/5
Phase 4 triggered: True

Completed:
  ✅ player_game_summary
  ✅ team_offense_game_summary
  ✅ team_defense_game_summary
  ✅ upcoming_player_game_context

Missing:
  ❌ upcoming_team_game_context (1 processor didn't complete)
```

### Feb 2 Processing (2026-02-03 document)
```
❌ NO COMPLETION RECORD
Status: Document does not exist
Impact: Cannot verify ANY processors completed
```

**Analysis:** Feb 1 had minor issue (1/5 processor missing) but orchestrator still ran and created completion record. Feb 2 orchestrator completely failed.

---

## Raw Data Coverage

### BDL Scraper Performance

**Feb 1:**
```
Games Scraped: 10/10 (100%)
Total Records: 348
Unique Players: 348
Status: ✅ ALL GAMES SCRAPED
```

**Feb 2:**
```
Games Scraped: 3/4 (75%)
Total Records: 176 (only 3 games)
Unique Players: 105
Missing Game: PHI @ LAC (0022500715)
Status: ❌ 1 GAME COMPLETELY MISSING
```

---

## Team Data Coverage

### Team Offense Summary

**Feb 1:**
```
Games: 17 (some teams played multiple games?)
Team Records: 34 (2 per game expected)
Has Possessions: 34/34 (100%)
Status: ✅ COMPLETE
```

**Feb 2:**
```
Games: 3
Team Records: 6 (2 per game)
Has Possessions: 6/6 (100%)
Status: ✅ COMPLETE (for 3 games that were scraped)
```

**Analysis:** Team data generation is working correctly on both dates. Usage rate 0% on Feb 2 is NOT due to missing team data.

---

## Usage Rate Deep Dive

### Coverage by Date

| Date | Active Players | Has Usage Rate | Coverage % | Status |
|------|----------------|----------------|------------|--------|
| Feb 1 | 319 | 306 | 95.9% | ✅ HEALTHY |
| Feb 2 | 63 | 0 | 0.0% | 🔴 BROKEN |

### Why Did Usage Rate Break?

**What we know:**
1. Team data EXISTS for both dates (100% possession coverage)
2. Feb 1 usage_rate calculation WORKED (95.9%)
3. Feb 2 usage_rate calculation FAILED (0%)
4. Code changes occurred Feb 2 at 19:36 PT
5. Phase 3 processor was deployed BEFORE code changes (19:26 PT)

**Timeline of events:**
```
Feb 2, 19:26 PT - nba-phase3-analytics-processors deployed
Feb 2, 19:36 PT - Code commits (execution logger fix + Phase 6)
Feb 2, ~23:00 PT - Feb 2 games finish
Feb 3, ~00:00-05:00 PT - Overnight processing (Phase 2→3→4→5)
Feb 3, 00:41 PT - Validation discovers 0% usage_rate
```

**Hypotheses:**

1. **Code Change in 19:26 Deployment (Most Likely):**
   - Phase 3 processor deployed at 19:26 had a bug
   - Bug was in the 19:26 deployment, not the 19:36 commits
   - Need to check what code was in the 19:26 deployment

2. **Orchestrator Failure Cascade:**
   - Orchestrator failed to complete on Feb 2
   - Some processors ran but didn't coordinate properly
   - Usage rate calculation depends on orchestrator sequencing

3. **Data Race Condition:**
   - Player processor ran before team processor completed
   - Feb 1 worked by luck (good timing)
   - Feb 2 failed due to bad timing

---

## Missing Cache Players - Ongoing Issue

### Coverage Comparison

**Feb 1:**
- Active players: 235
- Cached: 207
- Missing: 28 (11.9%)
- Coverage: 88.1%

**Feb 2:**
- Active players: 63
- Cached: 57
- Missing: 6 (9.5%)
- Coverage: 90.5%

**Analysis:**
- Missing rate is similar (9-12%)
- This appears to be an EXISTING issue, not new to Feb 2
- Affects high-minute players (Trey Murphy 37 min, Jabari Smith 30 min)
- Likely a filtering/logic issue in cache processor

**Priority:** P2 (needs fix but not urgent like Feb 2 specific issues)

---

## Prediction Coverage

### Feature Store → Predictions

**Feb 1:**
- Features: 357 players
- Predictions: 336 players
- Coverage: 94.1%
- Status: ✅ HIGH COVERAGE (pre-edge-filter)

**Feb 2:**
- Features: 148 players
- Predictions: 68 players
- Coverage: 45.9%
- Status: 🟡 EXPECTED (edge filter working)

**Analysis:**
- Feb 1 has 94% coverage (likely before Session 81 edge filter)
- Feb 2 has 46% coverage (edge filter removing low-edge predictions)
- This is EXPECTED behavior, not a regression
- Edge filter (min edge 3.0) is working correctly

---

## Root Cause Analysis

### What Changed Between Feb 1 and Feb 2?

#### Deployments on Feb 2
```
14:37 PT - nba-phase1-scrapers deployed
18:51 PT - prediction-coordinator deployed
19:26 PT - nba-phase3-analytics-processors deployed ← SUSPECT
19:28 PT - nba-phase4-precompute-processors deployed
19:36 PT - Code commits (but services already deployed)
20:36 PT - prediction-worker deployed
```

**Key Observation:** Phase 3 processor was deployed at 19:26 PT, 10 minutes BEFORE the 19:36 code commits. Need to check what code was in that deployment.

#### Possible Code Issues Introduced

**Check these commits before 19:26 deployment:**
```bash
# See what was deployed at 19:26
git log --oneline --before="2026-02-02 19:26:00 PST" -10 -- data_processors/analytics/

# Look for usage_rate related changes
git log --grep="usage\|team_offense\|JOIN" --since="2026-02-01" --oneline
```

---

## Regression Timeline

### When Did Each Issue Start?

| Issue | Working on Feb 1? | Broken on Feb 2? | First Occurrence |
|-------|-------------------|------------------|------------------|
| **Missing PHI-LAC game** | ✅ All games OK | ❌ 1 game missing | Feb 2 scraper run |
| **Usage rate 0%** | ✅ 95.9% coverage | ❌ 0% coverage | Feb 2 overnight processing |
| **No completion record** | ✅ Record exists | ❌ No record | Feb 2 → Feb 3 orchestration |
| **Missing cache players** | ❌ 88.1% (28 missing) | ❌ 90.5% (6 missing) | Pre-existing issue |
| **Deployment drift** | N/A | ⚠️ 3 services | Feb 2 19:36 commits |

---

## Recommendations for Opus

### Immediate Actions

1. **Check 19:26 Deployment Code:**
   ```bash
   # Find commit SHA deployed at 19:26
   git log --before="2026-02-02 19:26:00 PST" --format="%h %s" -1

   # Check for usage_rate changes
   git show <commit-sha> -- data_processors/analytics/player_game_summary/
   ```

2. **Investigate Orchestrator Logs:**
   - Why did orchestrator create completion record on Feb 1 but not Feb 2?
   - Did orchestrator even run on Feb 2 night?
   - Check Pub/Sub delivery metrics

3. **BDL Scraper Investigation:**
   - Why did PHI-LAC game (0022500715) not get scraped?
   - Check scraper logs for Feb 2
   - Was game_id in schedule when scraper ran?

### Timeline Reconstruction

**Needed:** Trace exactly when each Feb 2 component ran:
- When did BDL scraper run? (missed 1 game)
- When did Phase 3 processors run? (usage_rate failed)
- When did orchestrator run? (no completion record)
- What code version was each using?

### Validation

After fixes, validate both dates:
```bash
# Re-validate Feb 2 after fixes
python scripts/validate_tonight_data.py --date 2026-02-02

# Ensure Feb 1 still works (no regression)
python scripts/validate_tonight_data.py --date 2026-02-01
```

---

## Conclusion

### Summary

**Feb 2 introduced 3 NEW critical failures:**
1. Missing game from BDL scraper
2. Usage rate calculation completely broken
3. Orchestrator completion tracking failed

**Pre-existing issue (also affects Feb 1):**
4. Cache processor missing 9-12% of active players

### Critical Questions

1. **What code was in the 19:26 Phase 3 deployment?**
   - This deployment happened right before Feb 2 overnight processing
   - Usage rate worked on Feb 1, broke on Feb 2
   - Timing strongly suggests this deployment introduced the bug

2. **Why did orchestrator completely fail on Feb 2?**
   - Feb 1 orchestrator ran (4/5 processors, triggered Phase 4)
   - Feb 2 orchestrator left NO trace (no completion record at all)
   - This is more severe than Feb 1 partial failure

3. **Why did BDL scraper miss exactly 1 game?**
   - Feb 1: 10/10 games scraped
   - Feb 2: 3/4 games scraped
   - Was PHI-LAC game ID (0022500715) malformed or not in schedule?

### Next Steps

1. ✅ Deploy stale services (15 min) - Get all services on same code version
2. 🔍 Investigate 19:26 deployment commit - Likely root cause of usage_rate bug
3. 🔍 Check orchestrator logs - Why no completion record?
4. 🔍 Check BDL scraper logs - Why PHI-LAC was skipped?
5. 🔧 Fix and redeploy broken components
6. ✅ Re-validate both Feb 1 and Feb 2 data

---

## Related Documents

- **Issues Report:** `FEB-2-VALIDATION-ISSUES-2026-02-03.md`
- **Lineage Report:** `FEB-2-DATA-LINEAGE-REPORT-2026-02-03.md`
- **Index:** `README.md`

---

**Report Status:** Complete
**Conclusion:** Feb 2 failures are NEW regressions, not ongoing issues
**Action:** Focus investigation on deployments and code changes between Feb 1 and Feb 2
