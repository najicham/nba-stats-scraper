# Session 200 Start Prompt - Phase 3 Completeness Decision

**Copy-paste this into a new chat:**

---

```
I'm starting Session 200 to continue Session 199's Phase 3 investigation.

## Quick Context

Session 199 found the root cause of why only 7/12 players with betting lines got predictions on Feb 11.

**Root Cause:** Multi-window completeness check filtering players as INCOMPLETE_DATA_SKIPPED.
- Players need ≥70% completeness across ALL 5 windows (L5, L10, L7d, L14d, L30d)
- Paolo Banchero, Jalen Suggs, Desmond Bane fail at least one window → skipped
- This affects ALL teams: only ~35% coverage (5/17 ORL players, 4/16 GSW players, etc.)
- Code: `upcoming_player_game_context_processor.py` lines 1083-1117

## Read These First

1. **START HERE:** `docs/09-handoff/2026-02-11-SESSION-199-RESOLUTION.md`
   - Opus's answer (completeness check is the filter)
   - Systemic impact (all teams ~35% coverage)
   - 5 potential fix options

2. **Full Context:** `docs/09-handoff/2026-02-11-SESSION-199-COMPLETE-HANDOFF.md`
   - Complete session timeline
   - What NOT to do (game_id was wrong hypothesis)

3. **Optional:** `docs/09-handoff/2026-02-11-SESSION-199-PHASE3-ROOT-CAUSE.md`
   - Investigation details before Opus's answer

## Current Status

✅ **Root cause identified** by Opus
⏸️ **Awaiting decision** on fix approach
❓ **Unknown:** Is this new behavior or has coverage always been ~35%?

## Your Mission

### Step 1: Determine if This is New

Check if Phase 3 coverage has always been ~35% or if it recently dropped:

```sql
-- Compare Phase 3 coverage over last week
SELECT game_date,
       COUNT(DISTINCT player_lookup) as total_players,
       COUNT(DISTINCT CASE WHEN team_abbr = 'ORL' THEN player_lookup END) as orl_players,
       COUNT(DISTINCT CASE WHEN team_abbr = 'GSW' THEN player_lookup END) as gsw_players
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= '2026-02-04'
  AND game_date <= '2026-02-11'
GROUP BY game_date
ORDER BY game_date
```

**If coverage was higher last week (e.g., 60-70%):** Something changed (investigate what)
**If coverage has always been ~35%:** This is expected behavior per Session 141 zero-tolerance

### Step 2: Audit Paolo's Completeness

Understand WHY Paolo fails (which window is below 70%):

```sql
-- Check Paolo's game counts per window
WITH paolo_games AS (
  SELECT game_date
  FROM nba_analytics.player_game_summary
  WHERE player_lookup = 'paolobanchero'
    AND game_date >= '2026-01-12'
    AND game_date < '2026-02-11'
),
orl_games AS (
  SELECT game_date
  FROM nba_raw.nbac_schedule
  WHERE game_date >= '2026-01-12'
    AND game_date < '2026-02-11'
    AND (home_team_tricode = 'ORL' OR away_team_tricode = 'ORL')
)
SELECT
  -- L5 window
  (SELECT COUNT(*) FROM paolo_games WHERE game_date >= DATE_SUB('2026-02-11', INTERVAL 5 DAY)) as paolo_L5,
  (SELECT COUNT(*) FROM orl_games WHERE game_date >= DATE_SUB('2026-02-11', INTERVAL 5 DAY)) as orl_L5,
  ROUND((SELECT COUNT(*) FROM paolo_games WHERE game_date >= DATE_SUB('2026-02-11', INTERVAL 5 DAY)) * 100.0 /
        NULLIF((SELECT COUNT(*) FROM orl_games WHERE game_date >= DATE_SUB('2026-02-11', INTERVAL 5 DAY)), 0), 1) as L5_pct,

  -- L7d window
  (SELECT COUNT(*) FROM paolo_games WHERE game_date >= DATE_SUB('2026-02-11', INTERVAL 7 DAY)) as paolo_L7d,
  (SELECT COUNT(*) FROM orl_games WHERE game_date >= DATE_SUB('2026-02-11', INTERVAL 7 DAY)) as orl_L7d,
  ROUND((SELECT COUNT(*) FROM paolo_games WHERE game_date >= DATE_SUB('2026-02-11', INTERVAL 7 DAY)) * 100.0 /
        NULLIF((SELECT COUNT(*) FROM orl_games WHERE game_date >= DATE_SUB('2026-02-11', INTERVAL 7 DAY)), 0), 1) as L7d_pct,

  -- L10 window
  (SELECT COUNT(*) FROM paolo_games WHERE game_date >= DATE_SUB('2026-02-11', INTERVAL 10 DAY)) as paolo_L10,
  (SELECT COUNT(*) FROM orl_games WHERE game_date >= DATE_SUB('2026-02-11', INTERVAL 10 DAY)) as orl_L10,
  ROUND((SELECT COUNT(*) FROM paolo_games WHERE game_date >= DATE_SUB('2026-02-11', INTERVAL 10 DAY)) * 100.0 /
        NULLIF((SELECT COUNT(*) FROM orl_games WHERE game_date >= DATE_SUB('2026-02-11', INTERVAL 10 DAY)), 0), 1) as L10_pct
```

**Expected result:** Shows which window(s) are below 70%

### Step 3: Present Options to User

Based on your findings, present these 5 options:

**Option 1: Lower Completeness Threshold**
- Change 70% → 60% or 50% in `completeness_checker.py` line 94
- Pros: More coverage
- Cons: Lower quality (predicting with less historical data)

**Option 2: Relax Multi-Window Requirement**
- Require 3/5 or 4/5 windows instead of 5/5
- Pros: Players with recent gaps (injury/rest) still get predictions
- Cons: More complex logic

**Option 3: Skip Completeness for Daily Mode**
- Set `SKIP_COMPLETENESS_CHECK=true` for daily predictions
- Pros: All players with lines get predictions
- Cons: **CONFLICTS with Session 141 zero-tolerance policy**

**Option 4: Investigate Data Gaps**
- Check if games missing from `player_game_summary`
- Pros: Fix pipeline issue rather than relaxing quality
- Cons: Might be expected (players rest/rotate)

**Option 5: Keep As-Is**
- Accept ~35% coverage as intentional design
- Pros: Maintains Session 141 quality standards
- Cons: 65% of players with betting lines don't get predictions

### Step 4: Implement User's Choice

After user decides, implement the fix and document:
- What changed
- Why this approach was chosen
- What the trade-offs are
- How to measure success

## Important Context

### Session 141 Zero-Tolerance Policy

**Philosophy:** "Accuracy > coverage" - Better to skip players than predict with incomplete data

**Established:** Predictions blocked for ANY player with `default_feature_count > 0`

**Current behavior aligns:** Completeness check ensures sufficient historical data before predicting

**Question:** Is 35% coverage the intended result of this policy?

### What We Already Proved (Don't Re-investigate)

✅ SQL query works (returns all 17 ORL players)
✅ Roster data is complete
✅ Injury filter works correctly
✅ Betting lines exist for missing players
✅ Game_id format mismatch is NOT the issue (Opus confirmed it's handled)
✅ MERGE_UPDATE is NOT the issue (filtering happens before write)

### What NOT to Do

❌ Don't investigate game_id format mismatch (already ruled out by Opus)
❌ Don't investigate MERGE_UPDATE strategy (filtering happens before write layer)
❌ Don't add debug logging to query execution (query works perfectly)
❌ Don't re-run Phase 3 hoping it fixes itself (this is systemic, not a fluke)

## Key Files

**Code:**
- `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` (lines 1083-1117)
- `shared/utils/completeness_checker.py` (line 94: threshold = 70%)

**Data:**
- `nba_analytics.player_game_summary` - Historical game data for completeness check
- `nba_analytics.upcoming_player_game_context` - Only has ~35% of roster

**Docs:**
- `docs/09-handoff/2026-02-11-SESSION-199-RESOLUTION.md` - READ THIS FIRST

## Expected Outcome

By end of session:
1. ✅ Determined if 35% coverage is new or expected
2. ✅ Identified which window(s) Paolo/Jalen fail
3. ✅ User decided on fix approach (1-5 above)
4. ✅ Implemented fix OR documented decision to keep as-is
5. ✅ Created handoff doc for Session 201

## Questions?

If anything is unclear, ask the user:
- "Should I prioritize quality (keep 70%) or coverage (lower threshold)?"
- "Is 35% coverage acceptable for daily predictions?"
- "Do you want me to investigate if this is new behavior first?"

Let's figure out the right quality vs coverage trade-off!
```

---

**This prompt is ready to copy-paste into a new chat session.**
