# Session 438 Handoff — Season Autopsy Deep Dives + Injury Analysis Direction

**Date:** 2026-03-08
**Session:** 438 (NBA focus)
**Status:** v438 DEPLOYED. Deep dives complete. Injury analysis framework requested.

---

## What Was Done

### 1. Daily Autopsy (Mar 7)

**Record: 1-5 (16.7%), -4.09 units.** All 5 losses OVER. 1 win (SGA UNDER).

- 3 of 5 losses were rescued picks (combo_he_ms x2, volatile_scoring_over x1) — all would be blocked by v437
- Keyonte George OVER missed by 0.5 pts (bad shooting 4/17 FG, but 12/13 FT saved him)
- UTA had 6 teammates OUT — OVER on depleted rosters underperformed
- Algorithm was still v429 (pre-Phase 2-3). First v437 picks are Mar 9.

### 2. Full Season Autopsy (Jan 9 - Mar 7)

**Record: 91-51 (64.1%), +31.81 units.**

Monthly trajectory: Jan 73.1% (+26.59u) → Feb 57.1% (+4.48u) → Mar 53.8% (+0.74u)

Key findings:
- OVER HR collapsed: 80% → 53% → 47%. UNDER stable at 63-71%.
- Edge compression: avg 7.2 → 6.2 → 4.2 (rescue admitting low-edge picks)
- OVER edge 3-4 = 30.8% BB HR (N=13) despite 59.7% model HR — anti-selection by rescue layer
- Edge 6+ is the money zone: 75% OVER HR, 70% UNDER HR
- Friday 42.9% HR (later DENIED as noise)
- Filter data only 5 days old (since Mar 3)

### 3. Five Deep Dive Investigations (Agents)

| Finding | Verdict | Detail |
|---------|---------|--------|
| `line_jumped_under` filter destroying value | CONFIRMED | 67.7% HR at model level (N=65). Already in obs mode since Session 417. No action needed. |
| Friday performance (42.9%) | **DENIED** | N=14, p=15%. Post-ASB toxic window + random bad day. Cross-season Friday = 63.4%. |
| OVER edge 3-4 paradox (30.8% vs 59.7%) | CONFIRMED | 3 causes: v429 edge floor 3.0, combo_he_ms rescue losers, bench player concentration. v437 blocks 12 of 13. |
| Wembanyama/Edwards cover kings | MIXED | **Wemby: 75% model HR (N=20), 81.8% direction accuracy. REAL. Monitor at N=30+.** Edwards: 42.9% deduped HR, model wrong. Do NOT whitelist. |
| Rescue system + edge compression | CONFIRMED | Edge compression from rescue, not model drift. OVER bias growing +0.8→+1.6. Edge 5+ = +33.89u vs actual +31.81u. |
| Anti-signals (low_line_over etc.) | CONFIRMED | `low_line_over` 20% BB HR, NOT in BASE_SIGNALS — was inflating real_sc. **FIXED.** |

### 4. Code Changes (v438)

- **`low_line_over` → BASE_SIGNALS** (20% BB HR, confirmed anti-signal at both model and BB level)
- **`prop_line_drop_over` → BASE_SIGNALS** (57.9% BB HR, below 60% graduation threshold)
- **P9: Edge z-score observation** (`edge / points_std_last_10`). Normalizes edge by player variance. On pick dict, not in BQ yet.
- **P10: Prediction sanity observation** (flags `predicted > 2x season_avg` on bench/role players with line < 18)
- **Algorithm version:** `v438_base_signals_zscore`
- **88 tests pass** (80 existing + 8 new)

### 5. Deployment Verified

- v437 builds all SUCCESS at 17:36 UTC Mar 8 (BUILD_COMMIT=982aed0)
- v438 pushed to main, auto-deploying
- First v437 picks: Mar 9. First v438 picks: after v438 build completes.

---

## What to Do Next

### Priority 1: Injury Impact Deep Dive (USER REQUESTED)

The user wants to study how injuries affect predictions more deeply. Key questions to investigate:

**A. Teammate injury volume boost — does it actually work?**
```sql
-- For each player who went OVER by 5+ pts, check how many teammates were OUT
-- Compare: big covers with 3+ teammates out vs big covers with 0-1 teammates out
-- Key: does the model account for teammate injuries in its predictions?

-- Check: is teammate injury data available at prediction time?
-- Check: does the feature store include teammate availability features?
-- Feature 22 = teammate_usage_available (already used in med_usage_under filter)
```

**B. Players with biggest deviation from season avg on Mar 7:**
```sql
-- Find players whose actual points deviated most from their season_avg
-- Cross-reference with injury report (own team + opponent)
-- Hypothesis: biggest deviations correlate with unusual injury situations
SELECT
  pgs.player_lookup, pgs.points, pgs.points_line,
  pgs.points - (SELECT AVG(p2.points) FROM player_game_summary p2
    WHERE p2.player_lookup = pgs.player_lookup AND p2.game_date < '2026-03-07') as deviation_from_avg,
  -- join with injury report to count teammates out
FROM nba_analytics.player_game_summary pgs
WHERE pgs.game_date = '2026-03-07'
ORDER BY ABS(deviation_from_avg) DESC
```

**C. Can we detect "volume boost" opportunities proactively?**
- When a team's top scorer(s) are OUT, remaining starters get more shots
- Check: do players on depleted rosters consistently go OVER?
- Check: does the effect depend on the player's role (starter absorbs more than bench)?
- Check: is the market already pricing this in (line adjustments)?

**D. Opponent injury impact on UNDER predictions:**
- When opponent stars are OUT → game is less competitive → less need to score
- Does this help or hurt UNDER predictions?
- Mar 7 example: SGA UNDER won with 7 OKC teammates OUT (less need to force)

**E. Specific analysis framework for each day's autopsy:**
```
For every BB pick that lost:
  1. How many teammates were OUT? Who specifically?
  2. What was the player's scoring in the last 3 games with similar injury context?
  3. Did the line adjust for the injury? (compare line_value vs usual line)
  4. What was the opponent's injury situation?
  5. Was this a "usage boost expected but didn't materialize" situation?
```

**F. Historical injury-context performance:**
```sql
-- For each player, compute their points performance when:
-- 1. Team has 0-1 starters out vs 2+ starters out
-- 2. Opponent has 0-1 starters out vs 2+ starters out
-- This requires joining injury_report with player_game_summary over the season
```

### Priority 2: Monitor v437/v438 Impact (Mar 9+)

Run `/daily-autopsy` on Mar 9 to see first v437 picks. Key metrics:
- `algorithm_version` should be `v438_base_signals_zscore`
- Rescued pick count should decrease
- OVER real_sc should be lower (low_line_over/prop_line_drop excluded)
- Check `prediction_sanity_obs` and `edge_zscore` in logs

### Priority 3: Continue Season Autopsy Pattern

Run `/season-autopsy` weekly (every 7-10 days) to track:
- Is the OVER decline reversing post-v437?
- Are filter CF HRs stabilizing with more data?
- Wembanyama UNDER at N=30+ → whitelist candidate?
- OVER bias trajectory (+1.6 in Mar → still growing?)

### Priority 4: Phase 4 Remaining Items

- **P9 promotion:** After 2 weeks of edge_zscore data, analyze if z-score-ranked picks outperform edge-ranked
- **P10 promotion:** After 2 weeks of prediction_sanity_obs data, check CF HR. If < 45%, promote to active filter.

### NOT Doing Yet

- Edge 5+ floor (marginal +2.08u gain, v437 may already fix the OVER 3-4 issue)
- Retrain (OVER bias +1.6 not actionable yet)
- Wembanyama whitelist (need N=30+, currently N=20)
- "Engineer for profit" items (single champion, learned rejection, bet sizing)
- Friday filter (DENIED — noise)
- Anthony Edwards whitelist (DENIED — model wrong on him)

---

## System State

| Item | Status |
|------|--------|
| Algorithm Version | `v438_base_signals_zscore` |
| v437 deployed | YES (Mar 8 17:36 UTC) |
| v438 deployed | DEPLOYING (pushed to main) |
| Tests | **88 pass** (80 + 8 new) |
| BB HR (season) | 64.1% (91-51), +31.81 units |
| BB HR (7d) | ~50% (check after Mar 9 for v437 impact) |
| First v437 picks | Mar 9 |

---

## Key Learnings

1. **OVER edge 3-4 anti-selection is the root cause of OVER decline.** v437 blocks it. Confirmed by 3 independent analyses.
2. **`low_line_over` was inflating real_sc** as a confirmed anti-signal (20% BB HR, 50% model HR). Fixed.
3. **Edge compression is from rescue admitting low-edge picks**, not model degradation. Model is producing MORE high-edge predictions in March.
4. **Wembanyama is a structural opportunity** — 75% model HR, 81.8% direction accuracy, but avg edge 2.0 below our floor.
5. **Anthony Edwards is a structural TRAP** — model has stale UNDER bias, Vegas has him perfectly priced.
6. **Friday effect is noise** — N=14, driven by post-ASB toxic window. Cross-season Friday = normal.
7. **Injury context was a major factor on Mar 7** — 4 of 5 losses were on teams with 5-6 players OUT. The model may not be accounting for depleted roster effects adequately.
8. **`rest_advantage_2d` is a real signal** — 18.1pp edge-controlled lift in edge 5-7 bucket.
9. **Best signal pair: combo + rest_advantage_2d = 86.7% HR (N=15).**

---

## Files Changed

```
# Aggregator (core)
ml/signals/aggregator.py — BASE_SIGNALS: +low_line_over, +prop_line_drop_over
                           P10: prediction_sanity_obs filter (observation)
                           P9: edge_zscore computation (observation)
                           filter_counts: +prediction_sanity_obs
                           Algorithm: v438_base_signals_zscore

# Tests
tests/unit/signals/test_aggregator.py — 8 new tests (88 total):
  TestBaseSignalsAntiSignals (3): low_line_over, prop_line_drop_over in BASE, real_sc exclusion
  TestPredictionSanityObservation (2): obs doesn't block, not triggered for stars
  TestEdgeZscore (3): computation, std floor at 1.0, high variance low zscore
```

## Commits

```
742604aa feat: Session 438 — BASE_SIGNALS fix + P9 z-score + P10 sanity check observations
```
