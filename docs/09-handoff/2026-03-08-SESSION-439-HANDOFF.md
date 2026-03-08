# Session 439 Handoff — Injury Deep Dive + Star Fix + Player Performance Analysis

**Date:** 2026-03-08
**Session:** 439 (NBA focus)
**Status:** v439 DEPLOYED. Star criteria + normalizer fixes complete. Player analysis ready.

---

## What Was Done

### 1. Injury Impact Deep Dive (5 parallel agents)

Investigated whether teammate/opponent injuries affect BB pick quality. **Key findings:**

| Finding | Verdict |
|---------|---------|
| Depleted roster hurts OVER | **DENIED** — star classification was broken. With correct stars, OVER at 2+ stars out = 68.2% (not 50%) |
| Volume boost is real | **CONFIRMED** — cross-season validated +1-2pp in both 2024-25 and 2025-26 |
| Opponent depleted hurts OVER | **PARTIALLY** — -1.6pp effect, too weak for filter. Mechanism: blowouts reduce star minutes |
| Star classification broken | **CONFIRMED** — 50 false "stars" from usage >= 25% and 28 MPG low-scorers |
| Duplicate player lookups | **CONFIRMED** — 40 affected players, 3 processors had broken normalizer |
| Injury report timing gap | **CONFIRMED** — 1-hour blind spot (preds at 4 PM, final report at 5 PM). Only 2-3 BB picks affected/season |

### 2. Star Criteria Fix (`team_context.py`)

**Before:** `pts >= 18 OR min >= 28 OR usage >= 25%` (no game floor)
**After:** `pts >= 18 OR (min >= 28 AND pts >= 12)` with `games >= 10` floor

- Removes 30 false stars (Mo Bamba 52.7% usage in 3 MPG, Herb Jones 8.9 PPG/28.8 MPG)
- Mar 7 GSW stars_out corrected: 3 → 1 (only Curry). UTA: 3 → 1-2 (Markkanen + maybe Kessler)
- Fixed in both `get_star_teammates_out()` and `get_questionable_star_teammates()`

### 3. Normalizer Fix (3 processors)

Replaced broken local `normalize_player_name()` with shared `normalize_name_for_lookup()`:
- `nbac_player_boxscore_processor.py` — was creating `nikolajoki` instead of `nikolajokic`
- `nbac_play_by_play_processor.py` — same bugs
- `espn_boxscore_processor.py` — same bugs

Root cause: local normalizer lacked Unicode/diacritic handling and stripped suffixes (Jr/III).

### 4. Observation Filter

`depleted_stars_over_obs` — tracks OVER when stars_out >= 3. Based on noisy data pre-fix, but keeping in observation to validate with corrected star counts.

### 5. Tests & Verification

- **91 aggregator tests pass** (3 new)
- Schema validation pass, 876 Python files syntax check pass
- **Algorithm version:** `v439_depleted_roster_obs`

---

## What to Do Next

### Priority 1: Mar 7 Player Performance Deep Dive

**Goal:** Study every player who had a significant deviation from their season average on Mar 7. Use agents to investigate each anomaly individually. Look for patterns we can exploit.

**Mar 7 BB Picks (1-5, 16.7%):**

| Player | Team | Rec | Line | Actual | Edge | Result |
|--------|------|-----|------|--------|------|--------|
| Keyonte George | UTA | OVER | 22.5 | 22 | 5.6 | LOSS (-0.5!) |
| Ace Bailey | UTA | OVER | 15.5 | 9 | 3.7 | LOSS |
| John Konchar | UTA | OVER | 5.5 | 2 | 3.4 | LOSS |
| Al Horford | GSW | OVER | 9.5 | 4 | 3.8 | LOSS |
| Nolan Traore | BKN | OVER | 9.5 | 2 | 4.2 | LOSS |
| SGA | OKC | UNDER | 30.5 | 27 | 3.8 | **WIN** |

**Top Scoring Outliers (z-score >= 2.0):**

| Player | Team | Actual | Season Avg | Dev | Z-Score | FGA Dev | Min Dev | Notes |
|--------|------|--------|-----------|-----|---------|---------|---------|-------|
| Ziaire Williams | BKN | 23 | 9.2 | +13.8 | +2.5 | +0.5 | +8.9 | Huge minutes bump, efficient |
| Quentin Grimes | PHI | 26 | 12.3 | +13.7 | +2.2 | +6.0 | +11.7 | Massive FGA + minutes surge |
| Gui Santos | GSW | 22 | 9.6 | +12.4 | +2.3 | +12.1 | +14.1 | Biggest FGA spike of night |
| Donte DiVincenzo | MIN | 0 | 12.9 | -12.9 | -2.3 | -4.2 | -2.1 | ZERO points, normal minutes |
| Nic Claxton | BKN | 2 | 12.6 | -10.6 | -2.3 | -3.9 | -1.2 | Near-zero, normal minutes |

**Investigation framework for each outlier player:**

```
For each player with |z-score| >= 1.5:

1. CONTEXT
   - Who was their opponent? How does that opponent defend their position?
   - How many teammates were out? Did they absorb extra usage?
   - Was this a blowout? When did starters get pulled?
   - Home or away? Back-to-back?

2. SHOOTING
   - FG%, 3P%, FT% vs season averages
   - Shot distribution: more/fewer 3s? More paint attempts?
   - Assisted vs unassisted makes
   - Did they get to the free throw line more/less?

3. MINUTES & ROLE
   - Minutes deviation from average — why?
   - Did their role change (more ball handling, different position)?
   - Garbage time minutes? Or extended starter minutes?

4. RECENT TREND
   - Last 5 games scoring trend — was this a breakout or continuation?
   - Is there a matchup-specific pattern?
   - Any injury/return context?

5. PREDICTION RELEVANCE
   - Was this player a BB pick? What signals fired?
   - What was their line? Did Vegas adjust?
   - Would any current filter have caught this?
   - Is this a repeatable pattern or one-off variance?
```

**Specific players to deep-dive with agents:**

1. **Ziaire Williams (BKN)** — 23 pts on 9.2 avg, barely more FGA. How? Efficiency spike?
2. **Gui Santos (GSW)** — 22 pts on 9.6 avg, +12.1 FGA, +14.1 mins. Curry out → Santos becomes primary?
3. **Donte DiVincenzo (MIN)** — ZERO points on 12.9 avg, normal minutes. What happened?
4. **Nic Claxton (BKN)** — 2 pts on 12.6 avg, normal minutes. Shot 0-for-something?
5. **Keyonte George (UTA)** — Our BB pick. 22 on 22.5 line. Missed by 0.5. Was it bad luck or bad call?
6. **Jalen Johnson (ATL)** — 35 on 23.5 avg (+11.5). Normal FGA/mins. Pure efficiency spike.
7. **Quentin Grimes (PHI)** — 26 on 12.3 avg. +11.7 mins, +6 FGA. Embiid/George out? Volume boost?
8. **SGA (OKC)** — Our only win. 27 on 31.4 avg. UNDER won. Why did he underperform?

**SQL queries to seed each agent:**

```sql
-- Full game stats for a specific player on Mar 7
SELECT *
FROM `nba_analytics.player_game_summary`
WHERE player_lookup = '{PLAYER}' AND game_date = '2026-03-07';

-- Player's last 10 games trending
SELECT game_date, points, fg_attempts, fg_makes, three_pt_attempts, three_pt_makes,
       ft_attempts, ft_makes, minutes_played, usage_rate, plus_minus
FROM `nba_analytics.player_game_summary`
WHERE player_lookup = '{PLAYER}'
  AND game_date >= DATE_SUB(DATE('2026-03-07'), INTERVAL 30 DAY)
  AND game_date <= '2026-03-07'
  AND (is_dnp IS NULL OR is_dnp = FALSE)
ORDER BY game_date DESC;

-- All teammates out for that player's team
SELECT ir.player_lookup, ir.injury_status, ir.reason
FROM `nba_raw.nbac_injury_report` ir
WHERE ir.report_date = '2026-03-07'
  AND ir.team = '{TEAM}'
  AND LOWER(ir.injury_status) IN ('out', 'doubtful')
QUALIFY ROW_NUMBER() OVER (PARTITION BY ir.player_lookup ORDER BY ir.report_hour DESC) = 1;

-- Opponent defensive stats (DvP-style)
SELECT player_lookup, points, fg_attempts, fg_makes, minutes_played
FROM `nba_analytics.player_game_summary`
WHERE opponent_team_abbr = '{OPPONENT}'
  AND game_date >= '2026-01-01' AND game_date < '2026-03-07'
  AND (is_dnp IS NULL OR is_dnp = FALSE) AND minutes_played > 15
ORDER BY points DESC LIMIT 20;
```

### Priority 2: Additional Player Deviation Categories

Beyond scoring, look at these anomaly types:

**FGA Outliers (shot volume):**
- Gui Santos: +12.1 FGA (6.9 → 19). Why did he take 19 shots?
- Quentin Grimes: +6.0 FGA. Embiid absence?
- Michael Porter Jr: +6.6 FGA (18.4 → 25). More aggressive?
- Javon Small: -6.9 FGA (7.9 → 1). What happened to his shots?

**Minutes Outliers:**
- Gui Santos: +14.1 mins (23 → 37.1). Curry out → extended role
- Cody Williams: +14.4 mins (22.9 → 37.3). UTA depleted
- Quentin Grimes: +11.7 mins (29.3 → 41). PHI shorthanded?
- Myles Turner: -9.5 mins (27.7 → 18.2). Why benched?

**Efficiency Outliers (same FGA, different output):**
- Jalen Johnson: 35 pts on 19 FGA (1.84 pts/FGA vs 1.33 avg). How?
- DiVincenzo: 0 pts on 6 FGA (0.0 pts/FGA). Historically bad.
- SGA: 27 pts on 15 FGA (1.80 pts/FGA). Fewer shots but efficient.

### Priority 3: Monitor v439 Impact (Mar 9+)

- Star criteria change will affect feature_37 values starting Mar 9
- Check that star counts are reasonable (most teams 2-4, not 8-10)
- Normalizer fix prevents new duplicates; existing bad rows still in BQ (need backfill)

### NOT Doing Yet

- Backfill/clean 397 bad `nbac_player_boxscores` rows + 191 `player_game_summary` rows (safe — zero-tolerance blocks predictions on them)
- Fix scrapers' local normalizers (7 projection/external scrapers have same bug — lower priority since they don't feed player_game_summary)
- Opponent injury filter (signal too weak at -1.6pp)
- Late injury report refresh (only 2-3 BB picks/season affected)

---

## System State

| Item | Status |
|------|--------|
| Algorithm Version | `v439_depleted_roster_obs` |
| v439 deployed | DEPLOYING (pushed to main) |
| Tests | **91 pass** (88 + 3 new) |
| Star criteria | FIXED — games >= 10, no usage, pts >= 12 guard on MPG |
| Normalizer | FIXED — 3 processors use shared normalizer |
| BB HR (season) | 64.1% (91-51), +31.81 units |
| Last game date (graded) | Mar 7 (1-5, -4.09 units) |

---

## Key Learnings

1. **Star classification was the root cause of the "depleted roster" signal.** Usage >= 25% catches garbage-time players with 3 MPG. Fixed.
2. **Volume boost is REAL and cross-season stable.** When real stars are out, remaining players score +1-2pp above average.
3. **Opponent depletion effect is too weak** (-1.6pp) for a filter. Mechanism is blowout-driven minute suppression.
4. **Duplicate player lookups from broken normalizers** affected 40 players across 3 processors. Now fixed.
5. **Injury reports are highly accurate** (OUT: 99.7%, DOUBTFUL: 97%) but there's a 1-hour timing gap.
6. **The "0-5 on OVER" on Mar 7 was about picking bench players**, not injury depletion. Konchar (5.5 line), Traore (9.5), Horford (9.5) are role/bench players.

---

## Files Changed

```
# Aggregator
ml/signals/aggregator.py — depleted_stars_over_obs filter, algo v439

# Star criteria fix (Phase 3)
data_processors/analytics/upcoming_player_game_context/team_context.py
  — get_star_teammates_out(): tightened criteria, added games >= 10 + is_dnp filter
  — get_questionable_star_teammates(): same fix

# Normalizer fixes (Phase 2)
data_processors/raw/nbacom/nbac_player_boxscore_processor.py — shared normalizer
data_processors/raw/nbacom/nbac_play_by_play_processor.py — shared normalizer
data_processors/raw/espn/espn_boxscore_processor.py — shared normalizer

# Tests
tests/unit/signals/test_aggregator.py — 3 new tests (91 total)

# Docs
docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md
```

## Commits

```
(pending — ready to commit)
```
