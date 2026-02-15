# Rest of Season Model Plan — Session 253

Based on 52 experiments across 8 eval windows, 2 seasons, 5 configs, tier/population/staleness analysis.

## Schedule

- **Feb 14**: Today (session)
- **Feb 15-18**: All-Star Break (no games)
- **Feb 19**: Games resume (10 games)
- **Feb 6 was trade deadline**: 34 players changed teams
- **~400 games remain** through April regular season + playoffs

---

## Phase 1: ASB Retrain (Feb 18, day before games resume)

### Action
Retrain **two models** as shadow challengers:

1. **Config E (V9 MAE 33f)** — the "sniper"
   - `--train-start 2025-11-02 --train-end 2026-02-13`
   - Includes vegas features, generates few but high-conviction picks
   - Historical avg: 78.3% HR 3+ across 4 windows this season
   - Acts as quality filter — when it finds edge 3+, it's usually right

2. **Config C (V12 MAE RSM50 no-vegas)** — the "workhorse"
   - `--feature-set v12 --no-vegas --rsm 0.5 --grow-policy Depthwise`
   - Same dates
   - More picks at edge 3+ (2-4x more than E), good accuracy
   - Historical avg: 72.9% HR 3+ across 4 windows

### Why two?
- E's selectivity is a feature (6 picks in W4 = knew the market was hard)
- C provides volume for daily content and more betting opportunities
- When BOTH agree on a pick, that's highest confidence
- If one decays, the other may hold up

### Governance gates must pass before promoting either.

---

## Phase 2: Retraining Cadence

### Schedule

| Date | Action | Train Window |
|------|--------|-------------|
| Feb 18 | ASB Retrain | Nov 2 → Feb 13 |
| Mar 8 | Monthly retrain #1 | Nov 2 → Mar 1 |
| Mar 29 | Monthly retrain #2 | Nov 2 → Mar 22 |
| Apr 12 | Playoff prep retrain | Nov 2 → Apr 5 |

### Rules
- **Standard cadence: every 3 weeks** (staleness curve showed 28-day gap still at 66.7%)
- **Emergency retrain trigger**: if validate-daily shows HR 3+ < 52.4% for 5+ consecutive days
- **Never skip the ASB retrain** — trade deadline makes pre-ASB model stale
- **Each retrain trains BOTH configs** (E and C) and runs governance gates

---

## Phase 3: Model Selection Strategy

### Dual-model deployment

| Scenario | Action |
|----------|--------|
| Both E and C recommend same pick | **HIGH CONFIDENCE** — both models agree |
| Only C recommends (E has no edge) | **STANDARD** — normal pick |
| Only E recommends (C has no edge) | **STANDARD** — E found something C missed |
| E and C disagree on direction | **SKIP** — conflicting signals |

### Promotion criteria
- Model must pass all 6 governance gates
- Shadow for 2+ days (Feb 19-20 = first shadow window)
- If both pass gates: deploy both. If only one passes: deploy that one.
- Champion (stale V9) should be retired immediately after a challenger passes gates — it's at 32% HR edge 5+.

---

## Phase 4: Subset Strategy

Based on segmented analysis across all experiments:

### High-confidence subsets (consistently profitable)

| Subset | Evidence | Action |
|--------|----------|--------|
| **Edge 5+** | 82%/74% when fresh, collapses when stale | Always bet, key retrain signal |
| **Starters (15-24 PPG)** | 60-80% HR across most windows | Core picks |
| **Mid-range lines UNDER (12.5-20.5)** | 63-84% in non-disrupted windows | Bet when model fresh |
| **Both models agree** | New — untested but highest theoretical confidence | Flag as premium |

### Avoid subsets

| Subset | Evidence | Action |
|--------|----------|--------|
| **Stars UNDER** | Inconsistent (25-75% swing across windows) | Reduce position or skip |
| **Edge < 3** | 48-51% across all windows, below breakeven | Never bet (existing rule, validated) |
| **High-line OVER (20.5+)** | 36-60% — too volatile | Reduce weight |

### Monitor subsets (need more data)

| Subset | Evidence | Action |
|--------|----------|--------|
| **Low-line OVER (<12.5)** | 53-61% — sometimes good, sometimes flat | Track post-ASB |
| **Role players** | 57-75% — promising but small N | Track separately |

---

## Phase 5: Monitoring & Triggers

### Daily (automated via validate-daily)
- HR 3+ by model (E vs C vs champion)
- Pick volume per model
- Direction balance (OVER/UNDER split)

### Weekly (manual review)
- Subset HR breakdown (tier, direction, line range)
- Agreement rate between E and C
- Edge distribution shift

### Emergency triggers

| Trigger | Condition | Action |
|---------|-----------|--------|
| **Stale model** | HR 3+ < 52.4% for 5 consecutive game days | Emergency retrain |
| **Volume collapse** | < 5 edge 3+ picks for 3 consecutive game days | Check feature store, check line coverage |
| **Direction collapse** | OVER or UNDER < 40% for 7 days | Investigate bias, consider retrain |
| **Trade/injury shock** | Star player traded or season-ending injury wave | Retrain within 48 hours |

---

## Phase 6: Playoff Adjustments (April+)

### Known risks
- Playoff games have different dynamics (slower pace, tighter defense, star usage spikes)
- Training data is mostly regular season
- Sample sizes shrink (fewer games per day)

### Plan
- Retrain Apr 5 with full regular season data
- Consider `playoff_game` feature (already in V9 at index 16)
- Tighten edge threshold to 5+ for playoff picks (higher-conviction only)
- If HR drops in playoffs: pause and observe before continuing

---

## Decision Tree Summary

```
Games resume Feb 19
  |
  +--> Feb 18: Retrain E + C on Nov 2 → Feb 13
  |      |
  |      +--> Both pass gates? Deploy both as shadow
  |      +--> One passes? Deploy that one
  |      +--> Neither passes? Keep champion, investigate
  |
  +--> Feb 19-20: Shadow period (2 days)
  |
  +--> Feb 21: Promote best challenger(s), retire champion
  |
  +--> Every 3 weeks: Retrain both models
  |
  +--> Daily: Monitor HR, volume, direction
  |
  +--> Emergency: Retrain if HR < 52.4% for 5 days
```

---

## Key Learnings Baked Into This Plan

1. **Freshness > config choice** — A fresh mediocre model beats a stale great model
2. **Trade deadline is a regime change** — Always retrain after it
3. **Selectivity is valuable** — Config E's low volume is a feature (knows when to pass)
4. **Universal training > tier-specific** — Don't filter training data
5. **Monthly retraining is sufficient** — But never go past 4 weeks
6. **Edge 5+ is the premium signal** — When model is fresh, it's 74-82% accurate
7. **Both seasons confirm the architecture works** — The model itself isn't broken, staleness is the enemy
