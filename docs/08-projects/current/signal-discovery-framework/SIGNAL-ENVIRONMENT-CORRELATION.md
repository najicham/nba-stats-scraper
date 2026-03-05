# Signal-Environment Correlation Analysis

**Date:** 2026-03-05 (Session 411)
**Period analyzed:** Dec 1, 2025 — Mar 4, 2026 (84 game days with 5+ edge-3 picks)

---

## Summary

Investigated whether league-level scoring environment predicts signal and best bets performance. Found that **performance is autocorrelated (r=0.43)** but league scoring does not predict next-day performance. Specific signals have strong same-day correlations with league environment, suggesting directional signal weighting could improve daily picks.

---

## 1. Best Bets HR Autocorrelation (Strongest Finding)

BB HR today strongly predicts BB HR tomorrow:

| Lag | Correlation |
|-----|-------------|
| 1 day | **r=0.429** |
| 2 days | r=0.275 |
| 3 days | **r=0.412** |

**Regime persistence:** After a bad day (<50% HR), the next day averages only **53.9%**. After a great day (75%+ HR), the next day averages **72.2%**. Performance clusters in multi-day regimes, not random noise.

| Yesterday's BB HR | N days | Next-day avg BB HR |
|-------------------|--------|--------------------|
| < 50% (bad) | 20 | 53.9% |
| 50-74% (normal) | 52 | 60.7% |
| 75%+ (great) | 11 | 72.2% |

**2-day bad streaks** (7 occurrences): Day 3 averages 55.8%. Most cluster in the toxic window (Feb 1-5, Feb 10-12, Feb 24-26). Recovery happens but slowly.

**Implication:** A bad day is a signal to be cautious tomorrow. This is a *regime* effect, not mean reversion.

---

## 2. League Scoring vs BB HR (Same-Day)

| Scoring Quartile | Avg pts/player | N days | BB HR | OVER HR | UNDER HR |
|------------------|----------------|--------|-------|---------|----------|
| Q1 (lowest) | 9.7 | 19 | **63.4%** | 56.6% | **67.4%** |
| Q2 | 10.4 | 20 | 60.5% | 57.5% | 60.6% |
| Q3 | 10.7 | 21 | 61.6% | **66.9%** | 59.4% |
| Q4 (highest) | 11.6 | 24 | 57.8% | 61.8% | 57.8% |

**Key pattern:** Low-scoring days favor UNDER (67.4% HR). High-scoring days slightly favor OVER. Overall BB HR is actually *higher* on low-scoring days (63.4% vs 57.8%) — counterintuitive.

**Overall correlations:**
- `league_avg_pts` vs `bb_hr`: r=-0.122 (weak negative — low scoring = slightly better BB)
- `league_std_pts` vs `bb_hr`: r=+0.148 (weak positive — more variance = slightly better)
- `num_games` vs `bb_hr`: r=+0.064 (negligible)

---

## 3. League Scoring vs NEXT-Day Performance (No Signal)

| Condition | Next-day OVER HR | Next-day UNDER HR |
|-----------|-----------------|-------------------|
| After LOW scoring day | 59.9% | 61.3% |
| After HIGH scoring day | 61.7% | 60.6% |

**Essentially identical.** Yesterday's league scoring environment does NOT predict today's signal performance. The autocorrelation (Section 1) captures the regime effect; league scoring adds nothing on top of it.

---

## 4. Per-Signal Environment Sensitivity (Actionable)

Signals with statistically meaningful correlation between same-day league avg pts and signal HR:

| Signal | r(pts, HR) | Low-scoring HR | High-scoring HR | Delta | Interpretation |
|--------|-----------|----------------|-----------------|-------|----------------|
| `bench_under` | **-0.456** | 80.0% | 50.1% | -29.9pp | Blowouts bench players → low scoring days = more blowouts = bench_under thrives |
| `combo_he_ms` | **+0.387** | 67.3% | 77.8% | +10.5pp | High edge + minutes surge = OVER-oriented, needs scoring volume |
| `minutes_surge` | **+0.386** | 48.8% | 57.5% | +8.6pp | More scoring = more minutes for contributors |
| `3pt_bounce` | +0.199 | 40.9% | 54.4% | +13.4pp | 3PT shooting bounce-back more likely in high-scoring environments |
| `blowout_recovery` | +0.137 | 49.4% | 58.8% | +9.5pp | Weak but directionally consistent |
| `prop_line_drop_over` | **-0.439** | 56.4% | 43.8% | -12.6pp | (Disabled signal — confirms it was bad) |

**Slate size** has no meaningful effect:
- Small (<=5 games): 61.3% BB HR
- Medium (6-10): 60.0%
- Large (11+): 63.0%

**Scoring variance** has a slight positive effect:
- Low variance days: 59.4% BB HR
- High variance days: 62.1%

---

## 5. Day of Week

| Day | N | BB HR | Avg games |
|-----|---|-------|-----------|
| Mon | 12 | **65.0%** | 6.7 |
| Thu | 12 | **65.0%** | 7.2 |
| Sat | 12 | **64.5%** | 6.5 |
| Wed | 12 | 59.5% | 7.5 |
| Sun | 12 | 59.5% | 7.8 |
| Fri | 12 | 56.8% | 8.0 |
| Tue | 12 | **54.3%** | 7.1 |

Already captured by `day_of_week_over` signal (Mon/Thu/Sat boost). Friday OVER block filter also aligned.

---

## 6. Implications and Next Steps

### What works now (no changes needed)
- **Day of week** already captured by `day_of_week_over` signal + Friday filter
- **Toxic window autocorrelation** captured by signal decay monitor (Session 411)
- **UNDER bias on low-scoring days** naturally handled by signal mix

### Potential enhancements (future sessions)

**A. Daily regime indicator in aggregator**
Add a "regime_confidence" modifier to the aggregator based on yesterday's BB HR:
- After bad day (<50%): reduce pick count or tighten edge floor
- After great day (75%+): loosen slightly, more picks
- r=0.43 is strong enough to act on, but N=84 days is thin for sub-segmentation

**B. Environment-aware signal weighting**
On low-scoring days, upweight `bench_under` and downweight OVER combos. On high-scoring days, upweight `combo_he_ms`. This requires real-time league scoring data (available from schedule/game status).

**C. Blowout detection as leading indicator**
`bench_under`'s strong negative correlation with league scoring (r=-0.456) suggests that tracking early-game blowout development could identify when bench_under is most likely to hit. This is a live-game signal, not a pre-game one.

### What doesn't work
- **League scoring → next day prediction:** No signal (r=0.06). Don't build this.
- **Slate size:** No meaningful effect. Don't filter by number of games.
- **Scoring variance:** Weak effect (+2.7pp), not actionable.

---

## Raw Data Notes

- League avg pts per player: min=8.7, median=10.6, max=13.2
- 84 game days with 5+ edge-3 picks in the analysis period
- Signal-level analysis limited by N (8-40 signal-day observations per signal)
- All correlations are Pearson r on daily aggregates
