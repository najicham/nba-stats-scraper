# DNP and Voided Bet Treatment

**Date:** 2026-01-10
**Status:** Implemented
**Impact:** Coverage analysis, prediction grading, accuracy metrics

---

## Background

Investigation of Jan 9 prediction gaps revealed 4 players (jamalmurray, kristapsporzingis, zaccharierisacher, tristandasilva) who had betting lines but no predictions. These players were DNP (Did Not Play) with 0 minutes in the box score.

**Key Question:** Should these count as prediction gaps?

---

## Sportsbook Rules for DNP Players

Research of major sportsbooks (DraftKings, FanDuel, BetMGM, Fanatics) shows consistent treatment:

| Scenario | Sportsbook Action |
|----------|-------------------|
| Player ruled OUT before game | **Bet voided**, stake refunded |
| Player DNP (0 minutes) | **Bet voided**, stake refunded |
| Player plays 1+ minute then exits | **Bet stands** |
| Player plays full game | **Bet stands** |

**The threshold is participation, not production.** If a player steps on the court for even 1 minute, the bet is live. If they play 0 minutes, the bet is voided regardless of reason (injury, coach's decision, inactive).

### Sources

- [What Happens To A Prop Bet When A Player Doesn't Play? - Rithmm](https://www.rithmm.com/post/what-happens-to-a-prop-bet-when-a-player-doesnt-play)
- [FanDuel - Inactive or Injured Players](https://support.fanduel.com/s/article/What-happens-to-my-prop-bet-if-a-player-is-inactive-or-injured)
- [DraftKings Early Exit Feature - CBS Sports](https://www.cbssports.com/betting/news/draftkings-launches-new-refund-feature-for-player-injuries-called-early-exit-ahead-of-2025-nfl-season/)
- [Is Your Bet Void If a Player Gets Hurt? - OddsAssist](https://oddsassist.com/sports-betting/resources/is-bet-void-if-player-gets-hurt/)

---

## DNP Categories in NBA Data

Our data sources distinguish between:

| Status | Source | Meaning |
|--------|--------|---------|
| `dnp` | nbac_gamebook_player_stats | Dressed, on bench, 0 minutes (coach's decision) |
| `inactive` | nbac_gamebook_player_stats | Not in 12-man game roster |
| `out` | nbac_injury_report | Ruled out pre-game (injury) |
| `doubtful` | nbac_injury_report | Unlikely to play |
| `questionable` | nbac_injury_report | Uncertain, game-time decision |
| `probable` | nbac_injury_report | Likely to play |

**For bet voiding purposes, all 0-minute scenarios are treated the same** - the bet is voided regardless of whether the player was injured, a healthy scratch, or inactive.

---

## Treatment Rules

### 1. Predictions

| Player Status | Pre-Game Prediction | Backfill Prediction |
|---------------|--------------------|--------------------|
| `probable` | **Generate** | Generate if played |
| `questionable` | **Generate with flag** | Generate if played |
| `doubtful` | Skip (likely voided) | Generate if played |
| `out` | **Skip** | Skip |
| No injury status | **Generate** | Generate if played |
| DNP (0 min) | N/A (post-game) | **Skip** (bet voided) |

**Rationale for backfill:** Generating predictions for DNP players in backfill is meaningless because:
- The bet would have been voided anyway
- There's no outcome to grade against
- It inflates coverage numbers artificially

### 2. Coverage Analysis

| Category | Count as Gap? | Reasoning |
|----------|---------------|-----------|
| Player played (min > 0), no prediction | **Yes - REAL GAP** | We should have predicted |
| Player DNP (0 min), no prediction | **No - VOIDED** | Bet voided, prediction moot |
| Player OUT pre-game, no prediction | **No - EXPECTED** | Correctly skipped |
| Player has prediction, didn't play | **N/A** | Prediction exists but voided |

**Coverage formula:**
```
Real Coverage = Players with predictions who played / Players who played with betting lines
```

Not:
```
Wrong: Players with predictions / Players with betting lines (includes DNP)
```

### 3. Grading / Accuracy Metrics

| Scenario | Include in Grading? | Notes |
|----------|---------------------|-------|
| Player plays 30 min, scores 25 pts | **Yes** | Normal grading |
| Player plays 1 min, scores 0 pts | **Yes** | Bet stood, count the result |
| Player DNP (0 min) | **No** | Bet voided, no outcome |
| Player OUT pre-game | **No** | Bet voided, no outcome |

**Edge case - 1 minute player:**
- If player plays 1 minute and scores 0 points, we predicted 25
- Sportsbook: Bet STANDS, under wins
- Our grading: This is a "miss" (predicted 25, actual 0)
- This is an outlier but should be counted - the bet was live

---

## Implementation

### Coverage Check Changes

The `check_prediction_coverage.py` tool now:

1. **Excludes DNP players from gap counts**
   - Players with 0 minutes in `player_game_summary` are not counted as gaps
   - New gap reason: `BET_VOIDED` for transparency

2. **Shows separate metrics**
   - Real gaps (players who played but no prediction)
   - Voided (DNP/inactive players)
   - Total betting lines

3. **Uses correct denominator**
   - Coverage % = predictions / players who actually played
   - Not: predictions / all betting lines

### SQL Logic

```sql
-- Players who actually played (minutes > 0)
played_game AS (
    SELECT DISTINCT player_lookup
    FROM player_game_summary
    WHERE game_date = @game_date
    AND minutes_played > 0  -- Key filter
)

-- Gap categorization
CASE
    WHEN pg.player_lookup IS NULL THEN 'BET_VOIDED'  -- DNP, bet would be voided
    WHEN f.player_lookup IS NULL THEN 'NO_FEATURES'
    ...
END as gap_reason
```

---

## Example: Jan 9, 2026

### Before (incorrect)
```
Total betting lines: 146
Predictions: 136
Gap: 10 (6.8%)
Coverage: 93.2%
```

### After (correct)
```
Total betting lines: 146
Players who played: 142
Predictions for players who played: 136
Real gaps: 6
Voided (DNP): 4
Coverage: 95.8% (136/142)
```

The 4 DNP players (Murray, Porzingis, Risacher, da Silva) are no longer counted as gaps.

---

## Files Changed

| File | Change |
|------|--------|
| `tools/monitoring/check_prediction_coverage.py` | Exclude 0-minute players from gaps, add BET_VOIDED category |
| `docs/.../2026-01-10-DNP-VOIDED-BET-TREATMENT.md` | This documentation |

---

## Future Considerations

1. **Pre-game injury integration**: Implement `_extract_injuries()` TODO to populate injury status in player context

2. **Questionable player flagging**: Add confidence adjustment for questionable players

3. **Grading system**: When implementing pick grading, exclude 0-minute players from accuracy calculations

4. **Real-time alerts**: Consider alerting when a player with predictions is ruled OUT close to game time

---

**Author:** Claude Code (Opus 4.5)
**Session:** 7
