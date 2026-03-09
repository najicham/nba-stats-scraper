# MLB 2026 — Season Goals & Monitoring

## Season Targets

### Best Bets (1u flat)

| Metric | Floor | Target | Stretch | Backtest |
|--------|-------|--------|---------|----------|
| Season HR | 58% | 62% | 66% | 64.6% |
| Monthly HR (median) | 56% | 62% | 68% | 63.6% |
| Losing months | ≤ 3 | ≤ 2 | 0 | 1/13 |
| Picks/day | 1.5 | 2.5 | 3.0 | 2.4 |
| Season profit | +30u | +100u | +175u | +174u |
| ROI | 8% | 18% | 25% | 23.3% |

### Ultra (2u)

| Metric | Floor | Target | Stretch | Backtest |
|--------|-------|--------|---------|----------|
| Season HR | 63% | 70% | 75% | 72.9% |
| Monthly HR (median) | 58% | 70% | 78% | 72.7% |
| Losing months | ≤ 2 | ≤ 1 | 0 | 1/13 |
| Picks/day | 0.8 | 1.4 | 2.0 | 1.4 |
| Season profit | +40u | +120u | +175u | +173u |
| ROI | 15% | 30% | 40% | 39.1% |

### Combined Portfolio

| Metric | Floor | Target | Stretch | Backtest |
|--------|-------|--------|---------|----------|
| Total profit | +60u | +200u | +300u | +270u |
| ROI | 10% | 23% | 30% | 27.3% |
| Max drawdown | < 25% | < 15% | < 10% | 13.2% |

## Monthly Checkpoints

### April (weeks 1-4): Calibration Phase
- **Expected:** BB 57-62%, Ultra 65-75% (higher variance, lower N)
- **Risk:** Model calibrating with limited in-season data. April 2025 was 63.6% BB.
- **Action if BB < 55%:** Reduce to top-2/day. Do NOT panic — April is historically weak.
- **Action if BB > 65%:** System is working. Maintain course.

### May-June: Steady State
- **Expected:** BB 62-68%, Ultra 70-80%
- **Risk:** June is historically weakest (52.4% both years, not significant but watch it).
- **Action if June BB < 52%:** Tighten edge floor to 1.0 for 2 weeks.
- **UNDER decision:** Enable if OVER HR >= 58% through May.

### July-August: Peak Performance
- **Expected:** BB 63-70%, Ultra 65-78%
- **Risk:** ASB break. No significant effect found but monitor.
- **Blacklist review:** Any pitcher with 10+ picks and HR > 55% should be removed.

### September: Late Season
- **Expected:** BB 65-72%, Ultra 70-82% (historically strongest month)
- **Risk:** September callups — no negative effect found in walk-forward.
- **Action:** Consider increasing to top-4/day if pool is deep enough.

## Monitoring Triggers

### Green (system healthy)
- BB rolling 30d HR >= 58%
- Ultra rolling 30d HR >= 65%
- Picks generating daily (>= 2 BB, >= 0.5 Ultra)
- Filter audit showing expected blocks

### Yellow (investigate)
- BB rolling 30d HR 52-58%
- Ultra rolling 30d HR 55-65%
- Picks < 1.5/day for 5+ consecutive days
- Single-day loss of 3+ picks (all wrong)

### Red (intervene)
- BB rolling 30d HR < 52% (below breakeven)
- Ultra rolling 30d HR < 55%
- 5+ consecutive losing days
- Filter blocking > 80% of candidates (over-filtering)
- Model producing 0 predictions for a game day

### Intervention Playbook

| Trigger | Action |
|---------|--------|
| BB HR < 52% for 30d | Tighten edge floor to 1.0, reduce to top-2 |
| Ultra HR < 55% for 30d | Disable ultra staking (drop to 1u) |
| 5+ consecutive losses | Review: are we hitting blacklisted pitchers? Check filter audit. |
| April HR < 50% at day 15 | Reduce to top-1 until retrain at day 21 |
| Model 0 predictions | Check Cloud Run logs, verify scheduler running |
| Filter blocking > 80% | Check blacklist — are too many pitchers on it? |

## Bankroll Management

| Bankroll | Unit Size | Max Daily Risk | Season Target |
|----------|-----------|---------------|---------------|
| 50u | 1u (2%) | 7u (14%) | +60-200u |
| 100u | 1u (1%) | 7u (7%) | +60-200u |
| 200u | 2u (1%) | 14u (7%) | +120-400u |

**Rule:** Never risk more than 15% of current bankroll in a single day.

**Drawdown limits:**
- At -15u from peak: review system, check for errors
- At -25u from peak: reduce to top-2, 1u ultra
- At -40u from peak: pause system, full diagnostic

## Weekly Review Template

```
Week N (Mon-Sun):
  BB: X-Y (Z% HR), +/-Wu
  Ultra: X-Y (Z% HR), +/-Wu
  Total: +/-Wu (cumulative: +/-Wu)

  Filters fired: whole_line=N, blacklist=N, overconfidence=N
  Ultra qualification rate: N/M (Z%)
  Notable: [any unusual patterns]
```
