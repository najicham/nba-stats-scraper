# Daily Validation Report - January 20, 2026

**Validation Date:** January 20, 2026, 12:16 AM EST
**Validation Type:** Evening Pipeline + Pre-Morning Analysis
**Validated By:** Explore Agent (Automated Analysis)
**Overall Status:** ✅ EVENING PIPELINE SUCCESSFUL | ⏳ MORNING PIPELINE PENDING

---

## EXECUTIVE SUMMARY

The **evening prediction pipeline** for January 20, 2026 ran successfully on **January 19 at 2:31 PM PST**, generating **885 predictions** across **6 of 7 scheduled games** (85.7% coverage).

**Key Findings:**
- ✅ Evening schedulers ran on time (2:00-3:00 PM PST)
- ✅ Pipeline duration: 31 minutes (excellent performance)
- ⚠️ 1 missing gamebook from Jan 19 (8/9 complete, 88.9%)
- ⚠️ 1 game without predictions (TOR @ GSW) - may resolve in morning pipeline
- ⏳ Morning pipeline scheduled for 10:30-11:30 AM ET (not yet run)

---

## 1. PREDICTIONS GENERATED ✅

### Evening Predictions (Generated Jan 19 for Jan 20 games)

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Total predictions | 885 | 500-2000 | ✅ GOOD |
| Unique players | 26 | N/A | ✅ |
| Games covered | 6/7 | ≥80% | ✅ (85.7%) |
| First prediction | 2:31:26 PM PST | 2:00-3:00 PM | ✅ ON TIME |
| Last prediction | 2:31:37 PM PST | 2:00-3:00 PM | ✅ ON TIME |
| Batch duration | 11 seconds | <60 sec | ✅ EXCELLENT |

### Breakdown by Game

| Game ID | Teams | Game Time (EST) | Predictions | Players | Status |
|---------|-------|-----------------|-------------|---------|--------|
| 20260120_PHX_PHI | PHX @ PHI | 7:00 PM | 210 | 6 | ✅ |
| 20260120_LAC_CHI | LAC @ CHI | 8:00 PM | 280 | 8 | ✅ |
| 20260120_SAS_HOU | SAS @ HOU | 8:00 PM | 105 | 3 | ✅ |
| 20260120_MIN_UTA | MIN @ UTA | 9:00 PM | 90 | 3 | ✅ |
| 20260120_LAL_DEN | LAL @ DEN | 10:00 PM | 140 | 4 | ✅ |
| 20260120_MIA_SAC | MIA @ SAC | 10:00 PM | 60 | 2 | ✅ |
| TOR @ GSW | TOR @ GSW | 3:00 AM | 0 | 0 | ❌ MISSING |

### Coverage Gap Analysis

**Missing Game:** TOR @ GSW (Game time: 3:00 AM EST / 12:00 AM PST)

**Possible Reasons:**
1. Late game time (after midnight PT) - props may arrive later
2. Insufficient player data availability (quality score < 70%)
3. BettingPros may lack props for this matchup
4. Players filtered out due to production_ready status

**Recommendation:** Check morning pipeline (11:30 AM ET) to verify if TOR @ GSW receives predictions. If still missing, investigate player quality scores and prop line availability.

---

## 2. BETTINGPROS PROPS DATA ✅

### Props Timing for Jan 20 Games

| Metric | Value | Expected | Status |
|--------|-------|----------|--------|
| Total props (game_date=2026-01-19) | 79,278 | 70-90K | ✅ CURRENT |
| Unique players | 151 | N/A | ✅ |
| First scraped | 6:14 AM PST (Jan 19) | 1-2 AM | ⚠️ EARLY |
| Last scraped | 5:15 PM PST (Jan 19) | N/A | ✅ |
| Most recent scrape | 4:12-4:15 PM PST | N/A | ✅ |
| Data freshness | <7 hours | <48 hours | ✅ EXCELLENT |

**Note:** BettingPros props are stored with `game_date = 2026-01-19` (scrape date), not `game_date = 2026-01-20` (game date). This is expected behavior.

### Props-to-Predictions Timing

**Critical Finding:** Predictions generated **BEFORE** final evening props scrape.

```
Props last scraped:  5:15 PM PST (Jan 19)
Predictions created: 2:31 PM PST (Jan 19)
Gap: -2 hours 44 minutes (predictions BEFORE props)
```

**Analysis:**
- Evening pipeline does NOT wait for BettingPros props
- Predictions rely on Phase 3 (upcoming context) and Phase 4 (ML features)
- Props are used for **coverage** (which players to predict), not **timing**
- This is **expected behavior** for the evening "tomorrow" pipeline
- Morning pipeline will incorporate fresh overnight props

---

## 3. PIPELINE DURATION ✅

### Evening Pipeline Timeline

| Stage | Time (PST) | Duration | Status |
|-------|------------|----------|--------|
| Phase 3: Upcoming Context | 2:00-2:02 PM | 2 min | ✅ |
| Phase 4: ML Features | 2:30 PM | <1 min | ✅ |
| Phase 5: Predictions | 2:31 PM | 11 sec | ✅ EXCELLENT |
| **Total Duration** | **2:00-2:31 PM** | **31 min** | **✅ EXCELLENT** |

**Expected:** <60 minutes for full pipeline
**Actual:** 31 minutes (48% faster than target)

---

## 4. SCHEDULER STATUS ✅

### Evening Schedulers (Completed)

| Job Name | Schedule (PT) | Last Run (PST) | Status |
|----------|---------------|----------------|--------|
| same-day-phase3-tomorrow | 5:00 PM daily | Jan 19, 2:00 PM | ✅ SUCCESS |
| same-day-phase4-tomorrow | 5:30 PM daily | Jan 19, 2:30 PM | ✅ SUCCESS |
| same-day-predictions-tomorrow | 6:00 PM daily | Jan 19, 3:00 PM | ✅ SUCCESS |

**Assessment:** ✅ All evening schedulers ran on time with no errors.

### Morning Schedulers (Pending)

| Job Name | Schedule (ET) | Next Run | Status |
|----------|---------------|----------|--------|
| same-day-phase3 | 10:30 AM daily | Jan 20, 10:30 AM | ⏳ ENABLED (awaiting) |
| same-day-phase4 | 11:00 AM daily | Jan 20, 11:00 AM | ⏳ ENABLED (awaiting) |
| same-day-predictions | 11:30 AM daily | Jan 20, 11:30 AM | ⏳ ENABLED (awaiting) |

**Assessment:** ⏳ Morning schedulers not yet run (currently 12:16 AM ET). Expected at 10:30-11:30 AM ET.

### Supporting Schedulers

| Job Name | Schedule | Status |
|----------|----------|--------|
| overnight-phase4 | 6:00 AM PT daily | ✅ ENABLED |
| phase4-timeout-check-job | Every 30 minutes | ✅ ENABLED |

---

## 5. DATA COMPLETENESS

### Yesterday's Gamebooks (Jan 19) ⚠️

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Scheduled games | 9 | N/A | - |
| Gamebooks received | 8 | 9 | ⚠️ INCOMPLETE |
| Completeness | 88.9% | 100% | ⚠️ |
| Missing gamebooks | 1 | 0 | ⚠️ |

**Severity:** HIGH

**Impact:**
- Reduces data quality for Phase 4 ML feature generation
- May cause quality scores < 70% for affected players
- Contributes to prediction gaps and lower confidence levels

**From Agent Findings:**
- Auto-backfill infrastructure is **80% complete**
- Morning validation job **not yet deployed**
- **Recommendation:** Deploy morning gamebook validation job (6-8 hour effort)

**Action Items:**
1. Identify which game is missing gamebook
2. Check if gamebook available in GCS: `gs://nba-scraped-data/gamebooks/`
3. Trigger manual backfill if available
4. Implement auto-backfill job (6-8 hours) - see Agent Findings Summary

### Phase 3 Data (Upcoming Context) ✅

| Metric | Value | Status |
|--------|-------|--------|
| Records for Jan 20 | 132 | ✅ |
| Unique players | 132 | ✅ |
| Games covered | 7/7 | ✅ 100% |
| Created at | 2:00-2:02 PM PST | ✅ ON TIME |

**Assessment:** ✅ Phase 3 data complete for all scheduled games.

### Phase 4 Data (ML Features) ⚠️

**Status:** RUNNING IN DEGRADED MODE

**Evidence:**
- No records found in `player_daily_cache` for Jan 20
- Logs show: "SAME-DAY/FUTURE MODE: Skipping completeness check"
- Logs show: "SKIP DEPENDENCY CHECK: Same-day prediction mode"

**Analysis:**
- Phase 4 runs in **same-day mode** for evening pipeline
- Uses **Phase 3 fallback weights** (75% quality vs 100% from Phase 4)
- This is expected behavior for evening "tomorrow" predictions
- Morning overnight Phase 4 (6:00 AM PT) generates full ML features

**From Agent Findings:**
- Recommendation: Increase Phase 3 fallback weight from 75 → 87
- Impact: +10-12% prediction quality when Phase 4 delayed
- Effort: 5-minute code change (see Agent Findings Summary, Quick Win #1)

---

## 6. QUALITY & ERRORS

### Prediction Quality ✅

**Status:** No quality warnings detected in logs

**Evidence:**
- All 885 predictions met quality threshold (≥50%)
- No "quality_too_low" skip reasons logged
- No "features_not_production_ready" errors

**Quality Threshold Verification:**
- Minimum threshold: 50%
- High confidence: ≥70%
- Low confidence: 50-70%
- Self-healing override: ≥35% for production_ready players

### Service Errors ✅

**Status:** No critical errors detected

**Logs Checked:**
- prediction-coordinator: No errors
- Phase 3 processors: No errors
- Phase 4 processors: No errors
- prediction-worker: No errors in evening batch

**From Previous Report (Jan 19, 8:38 PM):**
- 3x HTTP 500 errors from prediction-worker
- Impact: None (predictions already complete)
- Action: Monitor for pattern today ✅ (no recurrence detected)

---

## 7. CRITICAL ISSUES & OBSERVATIONS

### Issue 1: Timing Anomaly - Predictions Before Props ⚠️

**Severity:** MEDIUM (Expected behavior, documentation gap)

**Finding:** Predictions generated at 2:31 PM PST, but props scraped until 5:15 PM PST

**Root Cause:**
- Evening pipeline is **prop-independent** for timing
- Props determine **coverage** (which players), not **schedule**
- Pipeline uses Phase 3/4 data, not live prop lines

**Impact:** None (expected behavior)

**Recommendation:** Document that evening pipeline does not wait for props

### Issue 2: Missing Jan 19 Gamebook ⚠️

**Severity:** HIGH

**Finding:** 8 of 9 gamebooks received (88.9% completeness)

**Root Cause:** Unknown (need to investigate)

**Impact:**
- Reduces Phase 4 ML feature quality
- May cause quality scores < 70% for affected players
- Contributes to prediction gaps

**Recommendation:**
1. Investigate missing gamebook (which game?)
2. Check GCS for late-arriving gamebook
3. Trigger backfill if available
4. Deploy auto-backfill job (6-8 hour effort from Agent Findings)

### Issue 3: Coverage Gap - TOR @ GSW ⚠️

**Severity:** LOW

**Finding:** 1 of 7 games missing predictions

**Possible Causes:**
1. Insufficient player data (quality < 70%)
2. BettingPros lacks props for this matchup
3. Late game time (3:00 AM EST) - props arrive later
4. Players filtered out (production_ready = FALSE)

**Impact:** Single game missing predictions (85.7% coverage, above 80% target)

**Recommendation:**
- Check morning pipeline (11:30 AM ET) for TOR @ GSW predictions
- If still missing, investigate player quality scores
- Query `upcoming_player_game_context` for TOR/GSW players

### Issue 4: Phase 4 Same-Day Mode Limitations ⚠️

**Severity:** MEDIUM

**Finding:** Phase 4 runs in degraded mode for evening pipeline

**Evidence:**
- Logs: "SKIP DEPENDENCY CHECK: Same-day prediction mode"
- No `player_daily_cache` records for Jan 20
- Quality relies on Phase 3 fallback weights (75%)

**Impact:**
- Lower quality scores vs full Phase 4 mode (100%)
- May reduce prediction accuracy

**From Agent Findings:**
- **Quick Win #1:** Increase Phase 3 weight from 75 → 87
- **Impact:** +10-12% quality improvement
- **Effort:** 5 minutes (1-line code change)
- **File:** `data_processors/precompute/ml_feature_store/quality_scorer.py:24`

**Recommendation:** Implement Quick Win #1 immediately (included in tonight's plan)

---

## 8. VALIDATION CHECKLIST (from daily-monitoring.md)

| Check | Status | Notes |
|-------|--------|-------|
| Are today's predictions generated? | ✅ / ⏳ | Evening: YES (885), Morning: PENDING |
| Are yesterday's gamebooks complete? | ⚠️ | 8/9 complete (88.9%) |
| Did prediction workers have quality issues? | ✅ | No quality warnings |
| Did the morning schedulers run? | ⏳ | Awaiting 10:30-11:30 AM ET |
| Are BettingPros props current? | ✅ | <7 hours old, 79K props |
| Are services healthy? | ✅ | All Phase 3/4/5 operational |

---

## 9. METRICS SUMMARY

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Evening predictions (Jan 20) | 885 | 500-2000 | ✅ GOOD |
| Morning predictions (Jan 20) | TBD | 500-2000 | ⏳ PENDING |
| Games with predictions (evening) | 6/7 (85.7%) | ≥80% | ✅ GOOD |
| Yesterday's gamebooks | 8/9 (88.9%) | 100% | ⚠️ INCOMPLETE |
| Scheduler success rate (evening) | 3/3 (100%) | 100% | ✅ PERFECT |
| BettingPros data freshness | <7 hours | <48 hours | ✅ CURRENT |
| Critical errors | 0 | 0 | ✅ NONE |
| Evening pipeline duration | 31 min | <60 min | ✅ EXCELLENT |
| Phase 3 data completeness | 7/7 games | 100% | ✅ PERFECT |
| Phase 4 data completeness | Degraded mode | Full mode | ⚠️ EXPECTED |

---

## 10. ACTION ITEMS

### IMMEDIATE (Next 10 Hours - Before Morning Pipeline)

**Priority 1: Monitor Morning Pipeline** (10:30-11:30 AM ET)
- [ ] Verify Phase 3, 4, 5 all run successfully
- [ ] Check if TOR @ GSW receives predictions
- [ ] Expected: 500-1500 predictions for Jan 20 games
- [ ] Validate total coverage reaches 7/7 games (100%)

**Priority 2: Investigate Missing Gamebook**
- [ ] Query which game is missing from Jan 19
- [ ] Check GCS: `gs://nba-scraped-data/gamebooks/2026-01-19/`
- [ ] Trigger backfill if gamebook available
- [ ] Document root cause

**Priority 3: Verify Overnight Props Scrape** (1-2 AM)
- [ ] Check for props with `game_date = 2026-01-21`
- [ ] Expected: ~70-90K props for tomorrow's games
- [ ] Verify scraper ran on schedule

### SHORT-TERM (This Week)

**From Agent Findings Summary - High Priority Quick Wins:**

1. ⭐ **Increase Phase 3 fallback weight: 75 → 87** (5 min)
   - File: `quality_scorer.py:24`
   - Impact: +10-12% quality when Phase 4 missing

2. **Reduce Phase 4 timeout check: 30min → 15min** (5 min)
   - Impact: 2x faster failure detection

3. **Add pre-flight quality filter in coordinator** (30 min)
   - Filter players with quality <70% before Pub/Sub
   - Impact: 15-25% faster batch processing

4. ⭐⭐ **Deploy morning gamebook validation job** (6-8 hours)
   - Schedule: 5:00 AM ET daily
   - Auto-trigger backfill for missing gamebooks
   - Zero-touch recovery

5. **Add missing predictions SLA alert** (20 min)
   - Schedule: 11:45 AM ET daily
   - Alert if 0 predictions for today

### MEDIUM-TERM (Next 2 Weeks)

1. Wire auto-backfill pipeline (1 hour)
2. Add downstream re-processing after backfill (4-6 hours)
3. Add Phase 3 dependency check (30 min)
4. Standardize 70% quality threshold across pipeline (1 hour)

---

## 11. RECOMMENDATIONS FOR FOLLOW-UP VALIDATION

### Morning Validation (12:00 PM ET)

**After morning pipeline completes:**

```sql
-- Check morning predictions
SELECT
  COUNT(*) as predictions,
  COUNT(DISTINCT game_id) as games,
  COUNT(DISTINCT player_lookup) as players,
  MIN(created_at) as first_pred,
  MAX(created_at) as last_pred
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-20'
  AND DATE(created_at) = '2026-01-20'
  AND is_active = TRUE;

-- Verify all 7 games covered
SELECT
  game_id,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-20' AND is_active = TRUE
GROUP BY game_id
ORDER BY predictions DESC;

-- Check for TOR @ GSW specifically
SELECT game_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-20'
  AND (game_id LIKE '%TOR%' OR game_id LIKE '%GSW%')
  AND is_active = TRUE
GROUP BY game_id;
```

### Evening Validation (6:00 PM PT)

**Verify tomorrow (Jan 21) predictions:**

1. Check evening pipeline ran (2:00-3:00 PM PST)
2. Verify predictions for Jan 21 games
3. Monitor gamebook completeness for Jan 20 games
4. Check Phase 4 timeout job for any alerts

---

## 12. TECHNICAL VERIFICATION

### Code Behavior Matches Observations ✅

**Verified by Technical Agent:**

| Aspect | Expected | Code Implements | Validated |
|--------|----------|-----------------|-----------|
| Trigger mechanism | Automatic Phase 4→5 | ✅ Pub/Sub + HTTP | ✅ |
| Quality threshold | 50-70% | ✅ 50% min, 70% high | ✅ |
| Pre-flight checks | Yes | ✅ 5 validation steps | ✅ |
| Phase 4→5 timeout | 4 hours | ✅ 14,400 seconds | ✅ |
| Incomplete Phase 4 | Fail-forward | ✅ Triggers anyway | ✅ |
| SOURCE_WEIGHTS | Phase4=100, Phase3=75 | ✅ Exact match | ✅ |
| Coverage gaps | Expected | ✅ Quality filters | ✅ |

**Code Locations:**
- Coordinator: `predictions/coordinator/coordinator.py`
- Worker: `predictions/worker/worker.py`
- Orchestrator: `orchestration/cloud_functions/phase4_to_phase5/main.py`
- Quality Scorer: `data_processors/precompute/ml_feature_store/quality_scorer.py`

**Quality Threshold Logic:**
- ≥70%: High confidence predictions
- 50-70%: Low confidence (proceed with warning)
- <50%: Skip (quality too low)
- Self-healing override: ≥35% for `production_ready=TRUE` players

---

## 13. CONCLUSION

**Overall Assessment:** ✅ **EVENING PIPELINE SUCCESSFUL** | ⏳ **MORNING PIPELINE PENDING**

### What's Working ✅

- Evening prediction pipeline ran on time (2:31 PM PST)
- 885 predictions generated for 6 of 7 games (85.7% coverage)
- All schedulers enabled and operational
- BettingPros props current (<7 hours old)
- No critical errors or quality warnings
- Excellent pipeline performance (31 minutes)

### What Needs Attention ⚠️

- **Missing gamebook** from Jan 19 (8/9 complete, 88.9%)
- **Coverage gap** for TOR @ GSW (may resolve in morning pipeline)
- **Phase 4 degraded mode** for evening pipeline (using Phase 3 fallback)
- **Implement quick wins** from Agent Findings (especially Phase 3 weight increase)

### What's Pending ⏳

- Morning pipeline execution (10:30-11:30 AM ET)
- Overnight BettingPros props scrape (1-2 AM)
- TOR @ GSW prediction coverage check
- Jan 21 evening predictions (2:00-3:00 PM PST)

### Confidence Level

**HIGH** for evening pipeline performance
**MONITORING** for morning pipeline and coverage gaps

### Next Validation

**January 20, 2026, 12:00 PM ET** (after morning pipeline completes)

---

## FILES REFERENCED

**Documentation:**
- `docs/02-operations/daily-monitoring.md`
- `docs/02-operations/validation-reports/2026-01-19-daily-validation.md`
- `docs/09-handoff/2026-01-19-AGENT-FINDINGS-SUMMARY.md`
- `docs/09-handoff/2026-01-20-MORNING-SESSION-HANDOFF.md`

**Code:**
- `predictions/coordinator/coordinator.py`
- `predictions/worker/worker.py`
- `orchestration/cloud_functions/phase4_to_phase5/main.py`
- `data_processors/precompute/ml_feature_store/quality_scorer.py`

**BigQuery Tables:**
- `nba_raw.bettingpros_player_points_props`
- `nba_predictions.player_prop_predictions`
- `nba_raw.nbac_schedule`
- `nba_raw.nbac_gamebook_player_stats`
- `nba_analytics.upcoming_player_game_context`
- `nba_precompute.player_daily_cache`

**GCS Buckets:**
- `gs://nba-scraped-data/bettingpros/player-props/points/2026-01-19/`
- `gs://nba-scraped-data/gamebooks/`

---

**Report Created:** January 20, 2026, 12:16 AM EST
**Validated By:** Explore Agent (Automated)
**Agent ID:** a13491a
**Report Version:** 1.0
**Next Update:** After morning pipeline (12:00 PM ET)
