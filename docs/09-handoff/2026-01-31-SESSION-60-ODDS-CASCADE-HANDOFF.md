# Session 60 Handoff - Odds Data Cascade Investigation

**Date:** 2026-01-31
**Session:** Session 60 (Odds Cascade track - parallel with Firestore Heartbeats)
**Status:** ⏳ Historical scraper running, all other work COMPLETE
**Duration:** ~2 hours

---

## Executive Summary

Investigated why ML feature store had missing Vegas line data. Discovered V8 was trained on BettingPros Consensus (not DraftKings). Implemented DraftKings-priority cascade and filled historical gaps.

**Key Finding:** V8 trained on BettingPros Consensus, not DraftKings - this is a calibration mismatch with user betting experience.

---

## Tasks Completed

### ✅ Task 1: V8 Training Data Investigation

**Finding:** V8 trained on `BettingPros Consensus` (76,863 samples, Nov 2021 - Jun 2024)

**Evidence:**
```python
# ml/train_final_ensemble_v8.py lines 59-65
WHERE bookmaker = 'BettingPros Consensus' AND bet_side = 'over'
```

**Implication:** Model calibrated to Consensus lines, not DraftKings where users bet.

**Documentation:** Full analysis at `docs/05-ml/V8-TRAINING-DATA-ANALYSIS.md`

---

### ✅ Task 2: DraftKings-Priority Cascade Implementation

**Files Modified:**
- `data_processors/analytics/upcoming_player_game_context/betting_data.py`
- `data_processors/analytics/upcoming_player_game_context/async_upcoming_player_game_context_processor.py`
- `data_processors/analytics/upcoming_player_game_context/loaders/game_data_loaders.py`

**New Cascade Order:**
1. Odds API DraftKings (primary, most real-time)
2. BettingPros DraftKings (fills 15% coverage gap)
3. Odds API FanDuel
4. BettingPros FanDuel
5. BettingPros Consensus (last resort)

**Key Methods Added:**
- `extract_prop_lines_with_cascade()` - New cascade method in `BettingDataExtractor`
- Updated SQL queries to prioritize DraftKings in ORDER BY clauses

---

### ✅ Task 3: Bookmaker Tracking in prediction_accuracy

**Schema Changes:**
```sql
ALTER TABLE nba_predictions.prediction_accuracy
ADD COLUMN line_bookmaker STRING;  -- e.g., 'DRAFTKINGS', 'FANDUEL'

ALTER TABLE nba_predictions.prediction_accuracy
ADD COLUMN line_source_api STRING;  -- e.g., 'ODDS_API', 'BETTINGPROS'
```

**Code Changes:**
- `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` - Populates new fields
- `schemas/bigquery/nba_predictions/prediction_accuracy.sql` - Updated to v5

---

### ✅ Task 4: Vegas Lines Backfill (Nov 2025)

**Script:** `scripts/backfill_feature_store_vegas.py`

**Results:** 1,817 records fixed in ml_feature_store_v2 for Nov 2025

---

### ✅ Task 5: /validate-scraped-data Skill Created

**File:** `.claude/skills/validate-scraped-data.md`

**Purpose:** Audit betting/odds data coverage against game schedule. Distinguishes between:
- Data in GCS but not in BigQuery → Just run processor
- Data not scraped → Need historical API scrape

---

### ✅ Task 6: Scraped Data Coverage Check Added to /validate-daily

**File:** `.claude/skills/validate-daily/SKILL.md`

**Added Priority 2E:** Quick 7-day coverage check for game lines and player props.

---

### ✅ Task 7: Nov 14-30 Game Lines Processed from GCS to BigQuery

**Command:**
```bash
python scripts/backfill_odds_game_lines.py --start-date 2025-11-14 --end-date 2025-11-30
```

**Result:** 434 files processed, 0 errors

---

### ⏳ Task 8: Historical Scrape Oct 22 - Nov 13 (IN PROGRESS)

**Command Running:**
```bash
PYTHONPATH=. python backfill_jobs/scrapers/odds_api_lines/odds_api_lines_scraper_backfill.py \
  --service-url="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app" \
  --dates-file="/tmp/nba-backfill/missing_game_lines_dates.txt"
```

**Progress:** 11/23 dates completed (~48%)
**ETA:** ~15-20 minutes from handoff time

**Dates Being Scraped:**
- Oct 22-31, 2025 (10 dates) ✅ Completed
- Nov 1, 2025 ✅ Completed
- Nov 2-13, 2025 (12 dates) ⏳ In progress

---

## Data Gap Summary

| Period | Game Lines Status | Player Props Status |
|--------|-------------------|---------------------|
| Oct 22-31, 2025 | ⏳ Scraping in progress | ✅ OK (Odds API) |
| Nov 1-13, 2025 | ⏳ Scraping in progress | ✅ OK (Odds API) |
| Nov 14-30, 2025 | ✅ Processed (434 files) | ✅ OK (Odds API) |
| Dec 2025 | ✅ OK (99.5%) | ✅ OK |
| Jan 2026 | ✅ OK (70.6%+) | ✅ OK |

---

## Commits Made This Session

| Commit | Description |
|--------|-------------|
| `741d8b09` | feat: Implement DraftKings-priority betting cascade and bookmaker tracking |
| `719e3b1b` | feat: Add /validate-scraped-data skill for odds data coverage audit |
| `d32dda7a` | feat: Add scraped data coverage checks to validation skills |

---

## Files Changed

### Code Changes
```
data_processors/analytics/upcoming_player_game_context/betting_data.py       CASCADE + PRIORITY
data_processors/analytics/upcoming_player_game_context/async_*.py            CASCADE ASYNC
data_processors/analytics/upcoming_player_game_context/loaders/*.py          USE NEW CASCADE
data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py BOOKMAKER TRACKING
schemas/bigquery/nba_predictions/prediction_accuracy.sql                     SCHEMA v5
scripts/backfill_feature_store_vegas.py                                      BUG FIX
```

### New Files
```
docs/05-ml/V8-TRAINING-DATA-ANALYSIS.md
.claude/skills/validate-scraped-data.md
```

### Updated Files
```
.claude/skills/validate-daily/SKILL.md   Added Priority 2E scraped data check
```

---

## Next Session Priorities

### High Priority

1. **Verify Historical Scrape Completed**
   ```bash
   grep "✓ Completed" /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b310ce7.output | wc -l
   # Should show 23 when complete
   ```

2. **Process Scraped Data to BigQuery** (after scrape completes)
   ```bash
   python scripts/backfill_odds_game_lines.py --start-date 2025-10-22 --end-date 2025-11-13
   ```

3. **Verify Final Coverage**
   ```sql
   -- Should show 80+ games for Oct, 200+ for Nov
   SELECT
     FORMAT_DATE('%Y-%m', game_date) as month,
     COUNT(DISTINCT game_id) as games_with_lines
   FROM nba_raw.odds_api_game_lines
   WHERE game_date >= '2025-10-22'
   GROUP BY 1
   ORDER BY 1
   ```

---

### Medium Priority

4. **Deploy Cascade Changes** to Phase 3/4 processors
   ```bash
   ./bin/deploy-service.sh nba-phase3-analytics-processors
   ```

5. **Run Per-Bookmaker Hit Rate Analysis** (new fields now capturing)
   ```sql
   SELECT line_bookmaker,
          COUNT(*) as bets,
          ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
   FROM nba_predictions.prediction_accuracy
   WHERE line_bookmaker IS NOT NULL
   GROUP BY 1
   ORDER BY 2 DESC
   ```

---

### Low Priority

6. **Consider V9 Training Strategy** based on V8 analysis
   - Train on DraftKings-only for user experience alignment?
   - Or continue with Consensus for larger dataset?
   - See `V8-TRAINING-DATA-ANALYSIS.md` for recommendations

7. **Add BettingPros Historical Backfill** (if API supports)
   - BettingPros collection only started Dec 20, 2025
   - Earlier data may not be recoverable

---

## Background Process Status

**Task ID:** b310ce7
**Output File:** `/tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b310ce7.output`

**To Check Progress:**
```bash
tail -30 /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b310ce7.output
grep -c "✓ Completed" /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/b310ce7.output
```

**Expected Completion:** 23 dates total, ~2 minutes per date

---

## Key Learnings

### 1. V8 Training Calibration Mismatch
V8 was trained on Consensus lines, but users bet on DraftKings. This means model edge calculations may not align with actual betting experience.

### 2. GCS vs BigQuery Gaps Need Different Fixes
- Data in GCS but not in BQ → Just run processor
- Data not scraped → Need historical API call
Use `/validate-scraped-data` to distinguish.

### 3. BettingPros Has More DraftKings History
- Odds API DraftKings: May 2023 - present (~30K records)
- BettingPros DraftKings: May 2022 - present (~104K records)
Consider BettingPros for training data.

---

## Related Documents

- **V8 Training Analysis:** `docs/05-ml/V8-TRAINING-DATA-ANALYSIS.md`
- **Cascade Investigation:** `docs/08-projects/current/odds-data-cascade-investigation/README.md`
- **Session 59 Handoff:** `docs/09-handoff/2026-01-31-SESSION-59-HANDOFF-FOR-CONTINUATION.md`

---

*Created: 2026-01-31 19:20 UTC*
*Session: Session 60 (Odds Cascade)*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
