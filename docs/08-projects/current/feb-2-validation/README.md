# February 2, 2026 - Validation Investigation

**Status:** 🔴 **CRITICAL ISSUES - Awaiting Opus Investigation**
**Date:** 2026-02-03 01:00 ET
**Validator:** Sonnet (Claude Code)
**Game Date:** 2026-02-02 (4 games scheduled)

---

## Quick Summary

Daily validation for Feb 2, 2026 revealed **5 critical issues** (P0/P1) blocking production use:

| Issue | Priority | Status | Impact |
|-------|----------|--------|--------|
| **Missing Game Data** (PHI-LAC) | P0 | ❌ BLOCKING | 0/25 players processed |
| **Orchestrator Completion Missing** | P0 | ❌ BLOCKING | No audit trail |
| **Usage Rate 0% Coverage** | P1 | ❌ CRITICAL | All games affected |
| **6 Active Players Missing Cache** | P1 | ❌ CRITICAL | Key rotation players |
| **Deployment Drift** (3 services) | P1 | ⚠️ FIXABLE | 15 min to resolve |

**Data Quality:** Insufficient for model retraining or production use
**Recommended Action:** Fix P0 issues before any analysis or predictions

---

## Documents in this Directory

### 1. [FEB-1-VS-FEB-2-COMPARISON.md](./FEB-1-VS-FEB-2-COMPARISON.md) ⭐ **START HERE**
**Comparison Analysis** - Proves Feb 2 issues are NEW regressions

**Contents:**
- Side-by-side metrics comparison (Feb 1 healthy, Feb 2 broken)
- Timeline reconstruction of when issues started
- Root cause analysis pointing to 19:26 deployment
- Regression timeline for each issue
- Critical questions for investigation

**Key Finding:** 🔴 **All major issues started between Feb 1 and Feb 2**
- Feb 1: 100% minutes, 95.9% usage_rate, orchestrator working
- Feb 2: 47% minutes, 0% usage_rate, orchestrator failed

**Use this to:** Understand WHEN issues started and narrow investigation scope

---

### 2. [FEB-2-VALIDATION-ISSUES-2026-02-03.md](./FEB-2-VALIDATION-ISSUES-2026-02-03.md)
**Main Issues Report** - Comprehensive documentation of all 5 critical issues

**Contents:**
- Executive summary with severity assessment
- Detailed analysis of each issue (evidence, root causes, investigation steps)
- Cross-issue analysis and common root cause hypothesis
- Priority matrix and recommended fix order
- Questions for Opus investigation
- All validation queries used

**Key Issues Documented:**
1. Missing Game Data - PHI vs LAC (0 BDL records)
2. Usage Rate Complete Failure (0% coverage despite team data existing)
3. Low Minutes Coverage (47% - though largely explained by DNPs)
4. No Phase 3 Completion Record (orchestrator tracking missing)
5. Deployment Drift (3 services running stale code)

**Use this for:** Understanding what broke and why

---

### 2. [FEB-2-DATA-LINEAGE-REPORT-2026-02-03.md](./FEB-2-DATA-LINEAGE-REPORT-2026-02-03.md)
**Data Lineage Validation** - Following validate-lineage skill methodology

**Contents:**
- Tier 1-4 lineage validation results
- Pipeline coverage analysis (RAW → ANALYTICS → CACHE → FEATURES → PREDICTIONS)
- Missing player identification (6 active players missing from cache)
- Team data lineage verification (proves usage_rate is code bug, not missing data)
- Contamination risk assessment
- All validation queries used

**Key Findings:**
- ✅ RAW → ANALYTICS: 99.0% (1 duplicate correctly handled)
- ⚠️ ANALYTICS → CACHE: 90.5% (6 players missing - **Trey Murphy 37 min, Jabari Smith 30 min**)
- ✅ CACHE → FEATURES: 100.0% (perfect)
- 🟡 FEATURES → PREDICTIONS: 45.9% (expected due to edge filter)
- ✅ Team data lineage: 100% (usage_rate bug is NOT missing data)

**Use this for:** Understanding data flow breaks and missing records

---

## Executive Summary for Opus

### What Happened

The daily validation on Feb 3 for Feb 2 games uncovered multiple critical pipeline failures:

1. **BDL scraper completely missed 1 of 4 games** (PHI-LAC)
2. **Usage rate calculation failed for ALL players** despite team data being present
3. **6 active rotation players missing from cache** including 37-minute and 30-minute starters
4. **No orchestrator completion record**, breaking monitoring/audit trail
5. **3 critical services running stale code** from 10-45 minutes before latest commits

### Impact

- **Data quality: INSUFFICIENT** for production use
- **Model retraining: BLOCKED** until issues resolved
- **Prediction quality: DEGRADED** for missing cache players
- **Monitoring: BROKEN** due to orchestrator failure

### Root Causes (Hypotheses)

**Issue 1 (Missing Game):** BDL API didn't return game OR scraper filtering excluded it
**Issue 2 (Usage Rate 0%):** JOIN logic bug in processor (NOT missing team data - we verified)
**Issue 3 (Missing Cache):** Cache processor filtering/logic excluding valid players
**Issue 4 (No Completion):** Orchestrator crashed OR failed to write Firestore document
**Issue 5 (Deployment Drift):** Manual deployment process, services not auto-updated

### Critical Path to Resolution

**FASTEST FIX ORDER:**

1. **Deploy stale services** (15 min) - Eliminates code version as variable
2. **Investigate orchestrator** (1-2h) - May reveal why other issues occurred
3. **Debug missing PHI-LAC game** (2-4h) - Most impactful to data quality
4. **Fix usage_rate calculation** (2-6h) - Code bug in JOIN logic
5. **Fix cache missing players** (2-4h) - May be related to orchestrator failure

**Total estimated time:** 7-17 hours of investigation/fixes

---

## For Opus: Investigation Checklist

### Before Starting

- [ ] Read both documents completely
- [ ] Note related issues (Issue 2 + Issue 4 may share root cause)
- [ ] Check if Feb 1 data had similar issues (establish baseline)

### Priority 1 (Deploy First)

- [ ] Deploy `nba-phase3-analytics-processors`
- [ ] Deploy `nba-phase4-precompute-processors`
- [ ] Deploy `prediction-coordinator`
- [ ] Verify deployments with `./bin/check-deployment-drift.sh`

### Priority 2 (Investigate Orchestrator - May Explain Everything)

- [ ] Check Phase 3 orchestrator logs (`gcloud functions logs read phase2-to-phase3`)
- [ ] Check Firestore completion collection (any documents for Feb 2-3?)
- [ ] Check Pub/Sub subscription metrics
- [ ] Determine if orchestrator ran at all

**If orchestrator didn't run:** This explains Issues 1, 2, 3, and 4
**If orchestrator ran but failed:** Check where it crashed

### Priority 3 (Missing Game - PHI-LAC)

- [ ] Check BDL scraper logs for Feb 2
- [ ] Query BDL API directly for game 0022500715
- [ ] Check if game was in schedule when scraper ran
- [ ] Determine if manual trigger can backfill

### Priority 4 (Usage Rate Bug)

- [ ] Review `player_game_summary_processor.py` JOIN logic (lines with `team_offense`)
- [ ] Check if JOIN happens before or after usage_rate calculation
- [ ] Look for timing/race conditions
- [ ] Compare to Feb 1 data (did it work yesterday?)

### Priority 5 (Missing Cache Players)

- [ ] Check cache processor logs for these 6 players
- [ ] Review filtering logic in `player_daily_cache_processor.py`
- [ ] Check if these players have historical cache entries
- [ ] Determine if conditional filtering excluded them

---

## Data Context

### Games Validated
```
Game ID      | Teams       | Status | BDL Scraped | Analytics | Cache | Predictions
-------------|-------------|--------|-------------|-----------|-------|------------
0022500712   | NOP @ CHA   | Final  | ✅ 72 rec   | ✅ 20     | ⚠️    | ✅
0022500713   | HOU @ IND   | Final  | ✅ 34 rec   | ✅ 22     | ⚠️    | ✅
0022500714   | MIN @ MEM   | Final  | ✅ 70 rec   | ✅ 21     | ⚠️    | ✅
0022500715   | PHI @ LAC   | Final  | ❌ 0 rec    | ❌ 0      | ❌    | ⚠️ (bad data)
```

### Service Versions (Before Fix)
```
Service                          | Status     | Deployed    | Code Changed
---------------------------------|------------|-------------|-------------
nba-phase3-analytics-processors  | STALE ❌   | 19:26 PT    | 19:36 PT
nba-phase4-precompute-processors | STALE ❌   | 19:28 PT    | 19:36 PT
prediction-coordinator           | STALE ❌   | 18:51 PT    | 19:36 PT
prediction-worker                | UP TO DATE | 20:36 PT    | 19:36 PT
nba-phase1-scrapers              | UP TO DATE | 14:37 PT    | -
```

---

## Key Files for Investigation

**Scrapers:**
- `scrapers/bdl_player_boxscores_scraper.py` - BDL scraper logic
- `scrapers/registry.py` - Scraper registration

**Processors:**
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py` - Usage rate calculation
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py` - Cache filtering

**Orchestration:**
- `orchestration/phase2_to_phase3_orchestrator.py` - Phase 3 trigger
- Firestore collection: `phase3_completion`

**Deployment:**
- `bin/deploy-service.sh` - Deployment script
- `bin/check-deployment-drift.sh` - Drift detection

---

## Success Criteria

### Issues Resolved When:

1. ✅ PHI-LAC game has ~25 player records in analytics
2. ✅ Usage rate populated for >80% of active players
3. ✅ All 6 missing cache players have entries (treymurphy, jabarismith, etc.)
4. ✅ Firestore `phase3_completion/2026-02-03` document exists
5. ✅ All services show "Up to date" in drift check

### Validation Passed When:

Run these commands and get PASS:
```bash
# Minutes coverage >80%
python scripts/spot_check_data_accuracy.py --start-date 2026-02-02 --end-date 2026-02-02

# Lineage >95%
# Run queries from FEB-2-DATA-LINEAGE-REPORT-2026-02-03.md

# Orchestrator completion exists
# Check Firestore phase3_completion/2026-02-03

# Deployment drift = 0
./bin/check-deployment-drift.sh
```

---

## Related Documentation

- **Daily Validation Skill:** `.claude/skills/validate-daily/SKILL.md`
- **Lineage Validation Skill:** `.claude/skills/validate-lineage.md`
- **Troubleshooting Matrix:** `docs/02-operations/troubleshooting-matrix.md`
- **Session Learnings:** `docs/02-operations/session-learnings.md`

---

## Timeline

| Time | Event |
|------|-------|
| Feb 2, 14:37 PT | nba-phase1-scrapers deployed |
| Feb 2, 18:51 PT | prediction-coordinator deployed |
| Feb 2, 19:26 PT | nba-phase3-analytics-processors deployed |
| Feb 2, 19:28 PT | nba-phase4-precompute-processors deployed |
| Feb 2, 19:36 PT | Code commits (execution logger fix + Phase 6 exporters) |
| Feb 2, 20:36 PT | prediction-worker deployed (includes latest commits) |
| Feb 2, ~23:00 PT | Feb 2 games finish |
| Feb 3, ~00:00-05:00 PT | Overnight processing (Phase 2→3→4→5) |
| Feb 3, 00:41 PT | Validation run - issues discovered |
| Feb 3, 01:00 PT | This report created |

---

## Questions for Opus

### Scoping Questions
1. Should we check if Feb 1 data has similar issues? (Establish if this is new or ongoing)
2. Are there other dates we haven't checked that may have silent failures?
3. Should predictions for Feb 2 be invalidated until data is fixed?

### Technical Questions
4. Why would orchestrator not write completion record? (Firestore permissions? Exception handling?)
5. Can we manually trigger BDL scraper for game 0022500715?
6. What's the proper backfill procedure after fixing issues?

### Process Questions
7. Should deployment be automated to prevent drift?
8. Should we add pre-validation that fails if services are stale?
9. What's the SLA for fixing data quality issues?

---

**Next Action:** Opus to review and begin investigation with Priority 1 (Deploy stale services)

**Estimated Resolution:** 1-2 days for full investigation and fixes
