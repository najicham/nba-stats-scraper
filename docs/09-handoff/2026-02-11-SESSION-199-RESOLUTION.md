# Session 199 Resolution - Multi-Window Completeness Check

**Date:** February 11, 2026
**Issue:** Phase 3 missing 10 players with betting lines
**Root Cause:** Multi-window completeness check filtering players as INCOMPLETE_DATA_SKIPPED
**Discovered By:** Opus
**Status:** ✅ **ROOT CAUSE IDENTIFIED** - Decision needed on fix approach

---

## The Answer (From Opus)

**The completeness check is your filter.**

### The Filtering Chain

```
17 ORL players from SQL query
  ↓
extract_players_daily_mode() → self.players_to_process (17 players)
  ↓
_process_single_player() for EACH player:
  ↓
  Check ALL 5 completeness windows (L5, L10, L7d, L14d, L30d)
  ↓
  If ANY window has is_production_ready=False → SKIP
  ↓
  12 players rejected as INCOMPLETE_DATA_SKIPPED
  ↓
  5 players pass → saved to database
```

### The Critical Code

**File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py`

**Lines 1083-1117:**
```python
# Check if ALL windows are production-ready
all_windows_ready = (
    completeness_l5['is_production_ready'] and
    completeness_l10['is_production_ready'] and
    completeness_l7d['is_production_ready'] and
    completeness_l14d['is_production_ready'] and
    completeness_l30d['is_production_ready']
)

if not all_windows_ready and not is_bootstrap and not is_season_boundary and not skip_completeness:
    return (False, {
        'reason': f"Multi-window completeness {avg_completeness:.1f}%",
        'category': 'INCOMPLETE_DATA_SKIPPED'
    })
```

**Completeness Threshold:** 70% (from `shared/utils/completeness_checker.py` line 94)

**Logic:** Each window calculates `completeness_pct = actual_games / expected_games * 100`
- If completeness_pct >= 70% → `is_production_ready = True`
- If ANY of the 5 windows < 70% → player is SKIPPED

---

## Evidence: Systemic Impact

**ALL teams affected**, not just ORL:

| Team | Roster | Phase 3 | Missing | Coverage |
|------|--------|---------|---------|----------|
| GSW | 16 | 4 | 12 | **25.0%** |
| ATL | 18 | 5 | 13 | **27.8%** |
| ORL | 17 | 5 | 12 | **29.4%** |
| BKN | 20 | 6 | 14 | **30.0%** |
| POR | 18 | 6 | 12 | **33.3%** |
| MIA | 17 | 6 | 11 | **35.3%** |
| PHI | 17 | 6 | 11 | **35.3%** |
| CLE | 17 | 6 | 11 | **35.3%** |
| OKC | 19 | 7 | 12 | **36.8%** |
| MEM | 17 | 7 | 10 | **41.2%** |

**Average coverage: ~35%** (only 1/3 of players passing completeness check)

**Conclusion:** This is NOT a bug. This is intentional design to avoid predictions on players with incomplete historical data. The question is whether the 70% threshold is too strict for daily (pre-game) mode.

---

## Paolo Banchero Example

**Game Counts:**
- L5 (last 5 days): 2 games
- L7d (last 7 days): 3 games
- L10 (last 10 days): 6 games
- L14d (last 14 days): 8 games
- L30d (last 30 days): 13 games

**Expected (ORL team games in last 30 days):** 12 games

**Why He Fails:**
- If ORL only had 3 games in last 5 days, and Paolo played in 2 → 67% completeness for L5 → FAIL
- If ORL only had 4 games in last 7 days, and Paolo played in 3 → 75% completeness for L7d → PASS
- Need to check each window's expected vs actual to understand which window fails

**Result:** Because at least ONE window is below 70%, Paolo is SKIPPED despite:
- ✅ Being in the roster
- ✅ Having betting lines
- ✅ Passing the injury filter
- ✅ Being in the SQL query results

---

## Why We Didn't Find This Earlier

1. **SQL query works** - Returns all 17 players ✅
2. **DataFrame works** - Contains all 17 players ✅
3. **Filtering happens later** - In `_process_single_player()` during transform
4. **We focused on query layer** - Didn't check post-query processing carefully enough

---

## Opus's Questions Answered

### 1. Diagnostic Strategy

**Opus's Answer:** "Option A (check logs) would work — the processor logs rejection reasons in failed_entities."

**But now we know the exact code path**, so we can go straight to checking completeness data.

### 2. MERGE_UPDATE Suspicion

**Opus's Answer:** "No. MERGE is not the problem. Records are filtered before they ever reach the write layer."

**Confirmed:** The 12 players never reach `save_analytics()`, so MERGE never sees them.

### 3. Broader Pattern

**Opus's Answer:** "Almost certainly affects all teams, not just ORL."

**Confirmed:** ALL teams have ~25-41% coverage. This is systemic.

### 4. Quick Fix vs Root Cause

**Opus's Answer:** "Root cause is identified. The question is now whether the completeness check is too aggressive for daily mode."

**Two paths:**
- **If this is new behavior:** Something changed in completeness thresholds or underlying data
- **If this has always been this way:** System designed to only predict on players with strong historical coverage

---

## The Bypass Exists

**File:** Line 1093 in `upcoming_player_game_context_processor.py`

```python
# RECOVERY MODE: Skip completeness checks via environment variable
skip_completeness = os.environ.get('SKIP_COMPLETENESS_CHECK', 'false').lower() == 'true'
```

**Warning:** Using `SKIP_COMPLETENESS_CHECK=true` would predict on players with incomplete features, which **conflicts with Session 141's zero-tolerance-for-defaults policy**.

---

## Recommended Next Steps (From Opus)

**Check the Phase 3 logs for:**
1. INCOMPLETE_DATA_SKIPPED counts
2. Specific completeness percentages for Paolo/Jalen

**This tells you:**
- "Slightly below threshold" (e.g., 65-69%) → fixable by tuning threshold
- "Zero historical data" (e.g., 0-30%) → deeper pipeline issue (data gaps)

**Query to run:**
```bash
gcloud logging read \
  "resource.labels.service_name=nba-phase3-analytics-processors
   AND timestamp>='2026-02-11T15:20:00Z'
   AND timestamp<='2026-02-11T16:00:00Z'" \
  --limit=500 --project=nba-props-platform \
  | grep -i "incomplete\|failed_entities\|completeness"
```

---

## Potential Fixes (Requires User Decision)

### Option 1: Lower Completeness Threshold

**Change:** Reduce from 70% to 50% or 60%

**Pros:** More players get predictions (better coverage)

**Cons:** Predicting on players with less historical data (lower quality)

**File to modify:** `shared/utils/completeness_checker.py` line 94

### Option 2: Relax Multi-Window Requirement

**Change:** Instead of requiring ALL 5 windows to pass, require 3 out of 5 or 4 out of 5

**Pros:** Players with recent data gaps (injury, rest) still get predictions

**Cons:** More complex logic, might allow predictions on players with spotty data

**File to modify:** `upcoming_player_game_context_processor.py` lines 1084-1090

### Option 3: Use SKIP_COMPLETENESS_CHECK for Daily Mode

**Change:** Set `SKIP_COMPLETENESS_CHECK=true` for daily (pre-game) predictions only

**Pros:** All players with betting lines get predictions

**Cons:** **Conflicts with zero-tolerance policy** - will predict with incomplete/default features

**Risk:** Session 141 established zero tolerance for defaults. This would bypass that.

### Option 4: Investigate Why L5/L7d Windows Fail

**Change:** Check if recent games are missing from `player_game_summary`

**Pros:** Fix data pipeline issue rather than relaxing quality gates

**Cons:** Might be expected (players rest, rotate) rather than a data issue

**Investigation needed:**
```sql
-- Check if Paolo's last 5 days have game data
SELECT game_date, game_id, points, minutes
FROM nba_analytics.player_game_summary
WHERE player_lookup = 'paolobanchero'
  AND game_date >= DATE_SUB('2026-02-11', INTERVAL 5 DAY)
  AND game_date < '2026-02-11'
ORDER BY game_date DESC
```

### Option 5: Keep As-Is (Intentional Design)

**Change:** None

**Rationale:** System designed to only predict on players with complete historical data

**Accept:** ~35% coverage is intentional to maintain high prediction quality

**Document:** This is working as designed per Session 141 zero-tolerance policy

---

## Historical Context: Session 141

**Session 141 established:** Zero tolerance for default/missing features

**Quote:** "Predictions blocked for ANY player with `default_feature_count > 0`"

**Philosophy:** "Accuracy > coverage" - Better to skip players than predict with incomplete data

**Current behavior aligns with this philosophy:**
- Completeness check ensures players have sufficient historical data
- Players with data gaps are skipped to avoid low-quality predictions
- ~35% coverage is the cost of maintaining quality

---

## Questions for User

### 1. Is This New Behavior?

**Check:** Did this work a week ago?

```sql
-- Compare Phase 3 coverage over time
SELECT game_date,
       COUNT(DISTINCT player_lookup) as phase3_players,
       COUNT(DISTINCT CASE WHEN team_abbr = 'ORL' THEN player_lookup END) as orl_players
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= '2026-02-04'
  AND game_date <= '2026-02-11'
GROUP BY game_date
ORDER BY game_date
```

**If coverage was higher last week:** Something changed (threshold? data quality? schedule?)

**If coverage has always been ~35%:** This is expected behavior

### 2. What's the Acceptable Coverage Threshold?

**Current:** ~35% of roster gets predictions (5 out of 17 players)

**Options:**
- **Maintain 70% threshold:** Keep quality high, accept low coverage
- **Lower to 60%:** Increase coverage moderately, slight quality hit
- **Lower to 50%:** Maximize coverage, accept lower quality
- **Relax to 3/5 windows:** Smart middle ground

**Business question:** Is it better to predict on 5 players with high confidence or 15 players with medium confidence?

### 3. Are The Missing Players Actually Incomplete?

**Need to check:** Are Paolo, Jalen, Desmond actually missing games from `player_game_summary`?

**Or:** Did they play all available games, but the windows are too strict?

**Investigation:** Check actual vs expected for each window for missing players

---

## Files Modified This Session

**None yet** - This is a DISCOVERY session, not a fix session.

Waiting for user decision on:
1. Is this new or expected behavior?
2. What's the acceptable quality vs coverage trade-off?
3. Should we tune threshold, relax windows, or keep as-is?

---

## Documents Created

1. **Session 199 Complete Handoff:** `docs/09-handoff/2026-02-11-SESSION-199-COMPLETE-HANDOFF.md`
   - Full session context and investigation timeline

2. **Root Cause Investigation:** `docs/09-handoff/2026-02-11-SESSION-199-PHASE3-ROOT-CAUSE.md`
   - Detailed findings before Opus's answer

3. **This Resolution Doc:** `docs/09-handoff/2026-02-11-SESSION-199-RESOLUTION.md`
   - Opus's answer and next steps

4. **Opus Review Prompt:** `docs/09-handoff/2026-02-11-OPUS-REVIEW-PROMPT.md`
   - What we sent to Opus

5. **Obsolete (Wrong Hypothesis):** `docs/09-handoff/2026-02-11-GAME-ID-MISMATCH-INVESTIGATION.md`
   - Game ID investigation (incorrect)

---

## Key Takeaways

### What We Learned

1. **Completeness checks happen in transform layer, not query layer**
2. **Multi-window requirements are strict: ALL 5 windows must pass**
3. **70% threshold is high - most players fail at least one window**
4. **This affects ALL teams, not just ORL (systemic)**
5. **The bypass exists but conflicts with zero-tolerance policy**

### What We Proved

1. ✅ SQL query works perfectly (returns all 17 ORL players)
2. ✅ Roster data is complete and correct
3. ✅ Injury filter works correctly
4. ✅ Betting lines exist for missing players
5. ✅ Players are filtered in `_process_single_player()` during transform

### What We Don't Know Yet

1. ❓ Is 35% coverage new or has it always been this way?
2. ❓ Are missing players actually incomplete or just below threshold?
3. ❓ What's the acceptable quality vs coverage trade-off?
4. ❓ Should we tune threshold, relax windows, or keep as-is?

---

## Next Session Should:

1. **Check historical coverage** - Was Phase 3 coverage higher last week?
2. **Audit Paolo's completeness** - Why exactly does he fail? Which window?
3. **User decision** - Quality vs coverage trade-off
4. **Implement fix** - Based on user's chosen approach

---

**Status:** ✅ Root cause identified by Opus
**Decision Needed:** User choice on fix approach
**Session 199 Complete**
