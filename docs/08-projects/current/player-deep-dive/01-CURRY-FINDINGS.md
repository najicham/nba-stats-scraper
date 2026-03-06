# Stephen Curry -- Deep Dive Findings

*Session 417, March 5 2026*
*Data: 188 games, Oct 2023 - Jan 2026 (3 seasons)*
*157 games with prop lines, 285 graded predictions*

## Executive Summary

Curry is a clear **UNDER player** against his prop line (54.8% under rate). The market consistently overvalues him, particularly at higher lines. His scoring variance is extreme (std 9.9) driven primarily by 3PT volume and efficiency. Key actionable patterns: high-line fade, bounce-back after bad games, and Saturday/Thursday scoring spikes.

---

## 1. Prop Line Performance (Most Actionable)

### Overall: 45.2% over / 54.8% under

| Line Range | Games | Over % | Avg Margin | Signal |
|------------|-------|--------|------------|--------|
| <20 | 6 | 33.3% | -4.3 | STRONG UNDER |
| 20-22.5 | 6 | 33.3% | -4.3 | STRONG UNDER |
| 23-25.5 | 56 | **57.1%** | +0.9 | **OVER SWEET SPOT** |
| 26-28.5 | 77 | 42.9% | -1.5 | UNDER lean |
| 29+ | 18 | **22.2%** | -4.8 | **STRONG UNDER** |

**Key insight:** The only line range where Curry goes OVER consistently is 23-25.5. At 29+, he goes under nearly 4 out of 5 times. Market systematically overprices Curry at high lines.

### Streaks
- Longest OVER streak: 5 games
- Longest UNDER streak: 7 games
- Avg UNDER streak (1.8) longer than avg OVER streak (1.5) -- UNDER momentum stronger

### Margin Distribution
- 19.7% of games: misses by 10+ pts (catastrophic UNDER)
- Only 10.2% of games: beats by 10+ pts
- Distribution skews left (toward UNDER blowouts)

---

## 2. Rest & Fatigue

| Days Rest | Games | Avg Pts | Over Line % | Avg Margin |
|-----------|-------|---------|-------------|------------|
| 1 (short) | 28 | 27.0 | 48.0% | +0.2 |
| 2 (normal) | 105 | 25.4 | 44.3% | -1.3 |
| 3+ (rested) | 35 | 25.5 | 51.6% | -1.3 |

**Surprise:** Rest doesn't meaningfully affect Curry's scoring. Fatigue score correlation is only -0.072 (essentially zero). Only 3 B2B games in the dataset (too small).

**Implication:** Don't weight rest heavily in Curry predictions. The market may over-adjust for rest.

---

## 3. Home vs Away (Counter-Intuitive)

| Location | Games | Avg Pts | FG% | Over Line % | Avg Margin |
|----------|-------|---------|-----|-------------|------------|
| Home | 53 | 24.4 | 45.1% | 47.5% | -1.4 |
| **Away** | 50 | **26.8** | **46.2%** | **51.3%** | **+0.8** |

**Curry scores MORE on the road** (+2.4 pts) and goes over his line more often away. This contradicts the typical home-court advantage expectation.

### Home + Rest Combinations
| Combo | Games | Avg Pts |
|-------|-------|---------|
| Away + 1d rest | 38 | **28.2** |
| Home + 3+ rest | 11 | 26.1 |
| Home + 1d rest | 42 | 24.0 |
| Away + 3+ rest | 11 | 22.5 |

**Best spot:** Away on short rest (28.2 avg). **Worst:** Away on long rest (22.5 avg).

---

## 4. Matchup Analysis

### Best Opponents (avg pts)
| Opponent | Games | Avg | Median | Best |
|----------|-------|-----|--------|------|
| ATL | 4 | 34.8 | 28 | 60 |
| BKN | 5 | 32.2 | 29 | 40 |
| ORL | 6 | 32.2 | 30 | 56 |
| SAS | 7 | 31.4 | 33 | 49 |
| LAL | 9 | 31.1 | 32 | 46 |

### Worst Opponents (avg pts)
| Opponent | Games | Avg | Median | Best |
|----------|-------|-----|--------|------|
| MIA | 4 | 20.0 | 18 | 31 |
| CHA | 5 | 20.0 | 21 | 26 |
| CLE | 4 | 20.2 | 20 | 30 |
| BOS | 4 | 20.5 | 22.5 | 33 |
| TOR | 6 | 22.0 | 21 | 39 |

**14.8 pt spread** between best and worst matchups. Curry's scoring is highly opponent-dependent.

### Defensive Rating Impact
| Opp Defense | Games | Avg Pts |
|-------------|-------|---------|
| Elite (<105 DRtg) | 4 | 18.5 |
| Good (105-110) | 12 | 23.5 |
| Average (110-115) | 49 | 25.3 |
| Poor (>115) | 28 | 27.6 |

Correlation: 0.170 (positive but modest). +9.1 pt spread between elite and poor defense.

### Pace Impact
| Opp Pace | Games | Avg Pts |
|----------|-------|---------|
| Below avg (97-100) | 35 | 25.8 |
| Above avg (100-103) | 38 | 23.5 |
| Fast (>103) | 19 | **29.3** |

Curry only benefits from extreme pace (>103). Moderate pace doesn't help.

---

## 5. Shooting Patterns

### What Drives Above-Average Games

| Metric | Above Avg Games | Below Avg Games | Delta |
|--------|----------------|-----------------|-------|
| FG% | 51.6% | 38.5% | **+13.1** |
| 3PT% | 46.0% | 33.5% | **+12.5** |
| FGA/game | 21.8 | 15.5 | +6.3 |
| 3PA/game | 13.2 | 9.7 | +3.5 |
| FTA/game | 5.5 | 3.2 | +2.3 |

**Both volume AND efficiency drive big games.** Shot zone distribution is identical -- Curry doesn't change where he shoots, just how well and how often.

### Three-Point Volume is the Key Driver

| 3PA Range | Games | Avg Pts | 3PT% |
|-----------|-------|---------|------|
| 1-5 | 7 | 12.7 | 36.7% |
| 6-8 | 31 | 17.5 | 39.3% |
| 9-11 | 54 | 23.5 | 37.8% |
| **12+** | 89 | **31.0** | **41.2%** |

Curry needs 12+ 3PA to hit big numbers. He maintains his best efficiency at highest volume (41.2% on 12+ attempts).

---

## 6. Game Context

### Minutes are Destiny
| Minutes | Games | Avg Pts | % of Games |
|---------|-------|---------|------------|
| <25 | 17 | 14.0 | 9.0% |
| 25-29 | 31 | 22.0 | 16.5% |
| **30-34** | **107** | **26.7** | **56.9%** |
| 35+ | 33 | 32.6 | 17.6% |

Curry plays 30-34 minutes 57% of the time. When he gets 35+, he averages 32.6 pts.

### Usage Rate Correlation: 0.667 (strong)
| Usage Rate | Games | Avg Pts |
|------------|-------|---------|
| Low (<25%) | 33 | 16.2 |
| Medium (25-30%) | 44 | 21.5 |
| High (30-35%) | 67 | 28.2 |
| Very High (>35%) | 38 | **34.9** |

### Game Spread Impact
| Spread | Games | Avg Pts | Avg Min |
|--------|-------|---------|---------|
| Close (<3) | 6 | 27.8 | 32.2 |
| Moderate (3-6) | 8 | **34.9** | 34.1 |
| Clear (6-10) | 6 | 26.2 | 31.1 |
| Blowout (>10) | 4 | 18.5 | 28.5 |

**Curry plays best in moderate spreads (3-6).** Gets pulled in blowouts (-16.4 pts vs moderate).

---

## 7. Temporal Patterns

### Day of Week
| Day | Avg Pts | Over Line % | Signal |
|-----|---------|-------------|--------|
| **Saturday** | **29.3** | **59.1%** | **OVER lean** |
| Thursday | 26.7 | 50.0% | Neutral |
| Friday | 26.4 | 32.0% | **UNDER lean** |
| **Wednesday** | **23.9** | **33.3%** | **UNDER lean** |

Saturday is Curry's best day (+3.5 pts vs avg, 59.1% over). Wednesday and Friday are worst for OVER.

### Season Phase
| Phase | Avg Pts | Avg Min |
|-------|---------|---------|
| Early (Oct-Dec) | 25.9 | 32.3 |
| Mid (Jan-Feb) | 26.6 | 32.4 |
| Late (Mar-Apr) | 24.7 | 32.6 |

Curry fades late in the season (-1.9 pts) despite same minutes.

### Bounce-Back Effect
- **After bad games (<16 pts):** next game avg 30.8 pts (+5.0 bounce)
- **After big games (>36 pts):** next game avg 26.1 pts (slight regression)

Strong mean-reversion pattern. The 30.8 avg after bad games is well above his overall 25.8 avg.

---

## 8. Model Performance on Curry

### Our models predict Curry UNDER well
| Direction | Predictions | Hit Rate |
|-----------|-------------|----------|
| OVER | 94 | 68.1% |
| **UNDER** | 191 | **71.2%** |

### By Edge Band
| Edge | Predictions | Hit Rate |
|------|-------------|----------|
| 5-8 | 55 | **83.6%** |
| 8+ | 46 | **80.4%** |
| 3-5 | 75 | 64.0% |
| 0-2 | 51 | 66.7% |

catboost_v8 is our best Curry model: 79.0% HR (N=143).

---

## Actionable Signals for Best Bets

### Strong Conviction Spots

1. **UNDER when line 29+** — 77.8% under (N=18). High-confidence UNDER.
2. **OVER when line 23-25.5** — 57.1% over (N=56). Moderate OVER.
3. **Saturday games** — 59.1% over (N=22). OVER lean.
4. **After bad game (<16 pts)** — 30.8 avg next game. OVER lean.
5. **Away on short rest** — 28.2 avg (N=38). Counter-intuitive OVER.
6. **vs ATL/BKN/ORL/SAS/LAL** — 30+ avg pts. OVER lean if line isn't inflated.

### Avoid / UNDER Spots

1. **Wednesday/Friday games** — 33.3% / 32.0% over.
2. **vs BOS/CLE/CHA/MIA** — avg 20 pts.
3. **Blowout games (spread >10)** — 18.5 avg, minutes cut.
4. **Late season (Mar-Apr)** — scoring fades.
5. **Line 29+** — systematic overpricing.

### What Doesn't Matter (Surprise)

- **Days rest** — virtually no impact on scoring
- **Fatigue score** — near-zero correlation
- **Home court** — Curry is actually BETTER away
