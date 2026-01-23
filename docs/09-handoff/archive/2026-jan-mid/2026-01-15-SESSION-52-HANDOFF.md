# Session 52 Handoff: Feature Engineering Strategy & Analysis

**Date**: 2026-01-15
**Focus**: Deep analysis of potential features, classification model success, market efficiency findings
**Status**: Strategy defined, ready for Phase 1 feature implementation

---

## Executive Summary

This session made critical discoveries about market efficiency and validated a new classification approach. We also received comprehensive feature recommendations from external research and synthesized them into an actionable plan.

### Key Achievements

| Task | Result | Impact |
|------|--------|--------|
| Classification model | 55.5% overall, 59.2% high conf | Better than regression (53%) |
| Walk-forward validation | 10-month test, 4,672 samples | Realistic performance estimate |
| BP perf_last_5 analysis | Data is STALE/BROKEN | Must calculate our own |
| Market efficiency proof | Lines adjust for trends | Simple signals don't work |
| Feature strategy | 40+ features analyzed | Prioritized to top 10 |

### Critical Finding: Market is Efficient

When we calculate rolling over/under performance correctly (not BP's broken data):
- **All confidence tiers hit ~50%** - the signal disappears
- Vegas adjusts lines: pitchers trending OVER get lines set 1.2K BELOW recent average
- **Simple trend-following doesn't work** - need leading indicators

---

## Current Model Performance (Walk-Forward Validated)

| Metric | Value | Confidence Interval |
|--------|-------|---------------------|
| Overall Hit Rate | 55.5% | ±4.9% monthly variance |
| High Confidence (>60% or <40%) | **59.2%** | 2,018 bets |
| Very High Over (>65%) | 60.7% | 786 bets |
| Breakeven | 52.4% | At -110 odds |
| Expected ROI | ~13% | On high confidence bets |

**Monthly Performance Range:**
- Best: September 2025 (66.5%)
- Worst: September 2024 (49.1%)
- Average: 55.3%

---

## Feature Analysis: What's Worth Adding

### Evaluated 40+ Features, Prioritized to Top 10

After deep analysis of the web chat recommendations against our market efficiency findings:

#### ✅ HIGH PRIORITY (Phase 1)

| Feature | Expected Lift | Why It Works | Effort |
|---------|---------------|--------------|--------|
| **SwStr% / CSW%** | +2-3% | Leading indicator - identifies "unlucky" pitchers with elite stuff but bad recent results | Medium |
| **Velocity Trends** | +1.5-2% | Early injury/fatigue detection - market adjusts after results, not during decline | Medium |
| **Red Flag Filters** | Avoid -5% losses | Skip bad spots (IL returns, velocity >2.5mph drop, bullpen games) | Low |

**Why these first:** They're LEADING indicators. Market prices in trailing indicators (recent Ks), but may underweight process metrics (SwStr%, velocity).

#### ⚡ MEDIUM PRIORITY (Phase 2)

| Feature | Expected Lift | Why It Works | Effort |
|---------|---------------|--------------|--------|
| **Weather × Breaking Ball** | +1-2% | Physics-based (cold reduces spin). Only for April/October | Low |
| **Umpire Interactions** | +0.5-1% | Table stakes, but interactions (ump × weather × style) add value | Low |
| **Opponent 7-Day Trends** | +1% | Teams go through slumps in contact quality | Medium |

**Why second tier:** These are real effects but either limited applicability (weather) or partially priced in (umpires).

#### 📋 LOWER PRIORITY (Phase 3)

| Feature | Expected Lift | Why It Works | Effort |
|---------|---------------|--------------|--------|
| **Actual Lineup K-Rates** | +2-3% | Timing advantage (lineups 2-3hr before game) | **HIGH** |
| **Catcher Framing** | +0.5% | Elite framers steal strikes | Low |
| **Feature Interactions** | +1-2% | Compound effects (cold + breaking ball + tight ump) | High |

**Why third tier:** Lineup is highest impact but hardest to implement. Save for when infrastructure is solid.

#### ❌ SKIP FOR NOW

| Feature | Why Skip |
|---------|----------|
| Our own rolling O/U | Signal disappears when calculated correctly - market is efficient |
| Times Through Order | Marginal value, partially captured by IP features |
| Bullpen Workload | Indirect effect on Ks |
| Historical pitcher vs team | Small samples, roster turnover makes it noise |

---

## Why SwStr% is Priority #1

### The Process vs Results Edge

```
Current model uses: k_avg_last_3, k_avg_last_5, k_avg_last_10
These are RESULTS - what happened

SwStr% measures: Swinging strike rate (whiffs / total pitches)
This is PROCESS - how good is the stuff

The Gap:
- Pitcher A: Elite SwStr% (14%), but bad luck, K avg below line
  → Market sees bad results, sets line based on results
  → We see great stuff, expect positive regression → BET OVER

- Pitcher B: Declining SwStr% (8%), but recent Ks above line
  → Market sees good results, line stays high
  → We see weakening stuff, expect negative regression → BET UNDER
```

### Concrete Example

| Metric | Pitcher A | Pitcher B |
|--------|-----------|-----------|
| K avg last 5 | 4.2 | 7.8 |
| Betting line | 5.5 | 6.5 |
| SwStr% season | 14.2% | 8.1% |
| SwStr% last 3 | 15.1% | 7.2% |
| **Our Signal** | **VALUE OVER** | **FADE OVER** |

Market sees results, we see process. That's the edge.

---

## Why Velocity Trends Matter

### Red Flag Detection

```
Velocity drop patterns:

Normal variance: ±0.5 mph game-to-game
Early concern:  -1.0 to -1.5 mph (monitor)
Red flag:       -1.5 to -2.5 mph (bias UNDER)
Critical:       >-2.5 mph (DO NOT BET OVER)

Why this matters:
- Velocity loss precedes K-rate decline by 1-2 starts
- Market adjusts after ERA/K-rate drops, not during velocity decline
- Identifies injury risk before it's obvious
```

### This is More Filter Than Feature

Velocity trends are most valuable for AVOIDING bad bets, not finding good ones:
- Skip OVER bets when velocity declining significantly
- Protects against injury traps
- Reduces variance

---

## Red Flag System (Must Implement)

### Hard Rules - Skip Bet Entirely

| Condition | Action | Reasoning |
|-----------|--------|-----------|
| First start off IL | SKIP | Pitch count limits, rust |
| Velocity drop >2.5 mph | SKIP OVER | Injury risk |
| Bullpen game/Opener | SKIP | Model designed for starters |
| MLB debut (first 2 starts) | SKIP | No baseline |
| Doubleheader | SKIP | Lineup chaos |
| Line moved >1.5 K | SKIP | Sharps strongly disagree |

### Soft Rules - Reduce Confidence

| Condition | Action | Reduction |
|-----------|--------|-----------|
| Line moved 1+ K against model | Reduce confidence | 50% |
| Velocity drop 1.5-2.5 mph | Bias UNDER | 70% for OVER |
| Public >85% one side | Reduce confidence | 30% |
| First 3 starts of season | Reduce confidence | 30% |

---

## Implementation Roadmap

### Phase 1: Quick Wins (1-2 Weeks)

```
Week 1:
□ Build Baseball Savant scraper for SwStr%, CSW%
□ Add velocity trend detection
□ Implement red flag filter system
□ Re-run walk-forward validation with new features

Week 2:
□ Validate feature lift on holdout data
□ Deploy to production predictor
□ Start tracking actual performance
```

### Phase 2: Context Features (Weeks 3-4)

```
□ Weather × breaking ball interaction
□ Umpire K-rate lookup table
□ Opponent team 7-day K-rate trends
□ Calibrate confidence thresholds
```

### Phase 3: Advanced (Weeks 5-8)

```
□ Lineup scraper (2-3 hr pre-game)
□ Feature interaction scoring
□ Catcher framing data
□ Full system optimization
```

---

## Data Sources Needed

| Data | Source | Update Frequency | Effort |
|------|--------|------------------|--------|
| SwStr%, CSW% | Baseball Savant | Daily | Build scraper |
| Velocity | Baseball Savant | Per-game | Same scraper |
| Weather | OpenWeather API | Real-time | API call |
| Umpires | UmpScorecards | Daily | Scrape or manual |
| Lineups | MLB.com | 2-3hr pre-game | Scraper needed |

### Baseball Savant Scraping Notes

```
Rate limit: 1 request per 2-3 seconds
Data available: Statcast pitch-level data
Key metrics: SwStr%, CSW%, avg_velocity, spin_rate
Format: CSV downloads available (faster than scraping)
```

---

## Files Created This Session

| File | Purpose |
|------|---------|
| `scripts/mlb/training/train_pitcher_strikeouts_classifier.py` | Classification model (direct O/U) |
| `scripts/mlb/training/walk_forward_validation.py` | 10-month rolling validation |
| `docs/08-projects/current/mlb-pitcher-strikeouts/FEATURE-BRAINSTORM-PROMPT.md` | Prompt for web chat research |

---

## Realistic Expectations

### Current State → Target State

| Metric | Current | After Phase 1 | After Phase 2 | Best Case |
|--------|---------|---------------|---------------|-----------|
| Overall | 55.5% | 57-59% | 58-61% | 60-62% |
| High Conf | 59.2% | 61-64% | 63-66% | 65-68% |
| Monthly Variance | ±5% | ±4% | ±3.5% | ±3% |

**Important:** The web chat suggested 67-70% is achievable. I'm more conservative because:
1. Our walk-forward showed market is very efficient
2. BP's "strong signals" were based on broken data
3. Sharp bettors likely already use SwStr%/velocity

### ROI Projections

At 59.2% high confidence:
- Per $100 bet: +$13.07 expected
- Monthly (200 bets): +$2,614
- Variance: Some months -10%, others +25%

At 64% high confidence:
- Per $100 bet: +$21.00 expected
- Monthly (200 bets): +$4,200

---

## Questions for Next Session

1. **SwStr% data availability:** Can we get historical SwStr% for all pitchers in our training set?

2. **Velocity baseline:** How do we establish "normal" velocity for each pitcher?

3. **Interaction validation:** With ~5-15 occurrences per season for rare interactions, how do we validate without overfitting?

4. **Lineup timing:** Is 2-3 hour pre-game window enough time to re-run model and place bets?

---

## Commands Reference

```bash
# Train classifier
PYTHONPATH=. python scripts/mlb/training/train_pitcher_strikeouts_classifier.py

# Run walk-forward validation
PYTHONPATH=. python scripts/mlb/training/walk_forward_validation.py

# Check backfill progress
python scripts/mlb/historical_bettingpros_backfill/check_progress.py
```

---

## Backfill Status

**As of session end:** 64.6% complete (5,258/8,140)
- Pitcher props: DONE
- Batter props: 57% complete, ~3 hours remaining

---

## Key Takeaways

1. **Classification > Regression** for O/U prediction (55.5% vs 53%)
2. **Market is efficient** - simple trends don't work when calculated correctly
3. **BP's perf_last_5 is broken** - don't rely on it
4. **SwStr% is the #1 priority** - leading indicator market may underweight
5. **Red flags are essential** - skip bad spots even when model is confident
6. **59.2% high confidence is real** - validated across 10 months, 2,018 bets
7. **Expect 60-65% with new features** - not 70%+, market is too efficient

---

## Handoff Checklist

- [x] Classification model trained and validated
- [x] Walk-forward validation complete (55.5% / 59.2%)
- [x] Market efficiency analysis done
- [x] Feature priority matrix created
- [x] Implementation roadmap defined
- [ ] SwStr% scraper built (next session)
- [ ] Velocity trend detection (next session)
- [ ] Red flag filters (next session)

---

*Session 52 Complete*
