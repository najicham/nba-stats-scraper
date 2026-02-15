# Session 258 — Signal Implementation + Advanced Testing

**Goal:** Implement production combo signals AND run any remaining advanced tests
**Prerequisites:** Read the files listed below first

---

## Context: What Sessions 256-257 Accomplished

### Read these files first:
1. `docs/09-handoff/2026-02-14-SESSION-257-HANDOFF.md` — Session 257 results summary
2. `docs/08-projects/current/signal-discovery-framework/COMPREHENSIVE-TESTING-RESULTS.md` — Full test results (9 dimensions)
3. `docs/08-projects/current/signal-discovery-framework/SIGNAL-DECISION-MATRIX.md` — Decision matrix with conditional filters
4. `docs/08-projects/current/signal-discovery-framework/COMPREHENSIVE-SIGNAL-ANALYSIS.md` — Session 256 signal decisions

### Quick Summary

**Session 256:** Ran 4 parallel agents analyzing all 23 signals. Discovered production combo (`high_edge + minutes_surge`, 79.4% HR), anti-patterns, and combo-only signals.

**Session 257:** Ran 9 exhaustive validation tests across every meaningful dimension. Upgraded confidence to HIGH for key combos. **INVALIDATED `high_edge+prop_value`** as production signal (0% HR when model stale).

### Final Signal Rankings (HIGH Confidence)

| Rank | Signal/Combo | HR | Picks | Key Conditions | Status |
|------|---|---|---|---|---|
| 1 | `3way_combo` (HE+MS+ESO) | 88.9% | 18 | None needed (robust everywhere) | **DEPLOY** |
| 2 | `high_edge + minutes_surge` | 68.8-85.7% | 16-31 | None needed (rest-insensitive) | **DEPLOY** |
| 3 | `cold_snap` | 93.3% | 15 | **HOME-ONLY** (31.3% away) | **DEPLOY with filter** |
| 4 | `3pt_bounce` | 69-78% | 13-17 | Guards + Home preferred | **DEPLOY with filter** |
| 5 | `blowout_recovery` | ~58% | 113 | No Centers + No B2B | **DEPLOY with filter** |
| - | `high_edge + prop_value` | 0-95.8% | 31 | DANGEROUS without full gate stack | **CONDITIONAL ONLY** |
| - | `HE + edge_spread 2-way` | 31.3% | 179 | ANTI-PATTERN | **NEVER USE** |

### Key Numbers to Remember
- **Breakeven HR:** 52.4% (at -110 odds)
- **Model training cutoff:** 2026-01-08 (champion is 37+ days stale)
- **OVER bias:** Strong combos are exclusively OVER picks
- **Minutes_surge:** The "universal amplifier" — independent of model freshness

---

## Track 1: Implement Production Combo Signals (Priority)

### 1A. Create `HighEdgeMinutesSurgeComboSignal` (P0)

Look at existing signals in `ml/signals/` for the pattern. This signal should:
- Fire when both `high_edge` AND `minutes_surge` are present in a pick's signal tags
- Confidence: 0.85 (HIGH)
- OVER-only recommended (all validated picks were OVER)
- Cross-conference bonus (88.9% vs 66.7% same-conference) — optional confidence boost

### 1B. Create `ThreeWayComboSignal` (P0)

- Fire when `high_edge` + `minutes_surge` + `edge_spread_optimal` ALL present
- Confidence: 0.95 (PREMIUM)
- No filters needed — robust across all 9 tested dimensions

### 1C. Update `cold_snap` with HOME-ONLY filter (P1)

- Add `is_home` check: only fire for home players
- Impact: HR jumps from 61.1% → 93.3% (at cost of ~50% volume)
- Check `ml/signals/cold_snap.py` for current implementation

### 1D. Update `blowout_recovery` with exclusions (P1)

- Exclude Centers: `position NOT IN ('C')` → removes 20% HR subsegment
- Exclude B2B: `rest_days >= 2` → removes 46.2% HR subsegment
- Check `ml/signals/blowout_recovery.py` for current implementation

### 1E. Update combo-aware Best Bets aggregator (P2)

Add scoring bonuses/penalties:
```python
# Synergistic combos (bonus)
if 'high_edge' in tags and 'minutes_surge' in tags:
    score += 2.0  # 68.8-85.7% HR
if all(x in tags for x in ['high_edge', 'minutes_surge', 'edge_spread_optimal']):
    score += 2.5  # 88.9% HR (replaces 2.0 above)

# Anti-patterns (penalty)
if 'high_edge' in tags and 'edge_spread_optimal' in tags and 'minutes_surge' not in tags:
    score -= 2.0  # 31.3% HR, -37.4% ROI
```

---

## Track 2: Advanced Testing (If Time)

### What's Been Tested (9 dimensions, 100% coverage)

| Dimension | Status | Key Finding |
|---|---|---|
| Temporal windows (W1-W4) | DONE | `HE+PV` collapses when model stale |
| Home vs Away | DONE | `cold_snap` 62-pt gap, `3pt_bounce` 44-pt gap |
| Model staleness (5 buckets) | DONE | Only HE+MS and 3way survive decay |
| Position (G/F/C) | DONE | Centers terrible on blowout_recovery |
| 3-way combos (all 35) | DONE | ESO+HE+MS confirmed #1 |
| Rest/B2B (4 categories) | DONE | HE+MS rest-insensitive; BR tanks on B2B |
| Team strength (3 tiers) | DONE | cold_snap top teams only; BR bottom teams |
| OVER/UNDER direction | DONE | HE+PV UNDER 3.8% HR; strong combos OVER-only |
| Conference/matchup type | DONE | HE+MS cross-conf boost; HE+PV same-conf |

### Untested Angles (see TESTING-COVERAGE-MAP.md for full list)

Priority angles that could yield new insights:
1. **Line size analysis** — Do combos work differently on high lines (25+) vs low lines (<15)?
2. **Day-of-week effect** — Weekday vs weekend performance differences?
3. **Vegas movement** — How does line movement before game time affect combo HR?
4. **Player tier/usage** — Stars vs role players within each combo
5. **Game total (O/U)** — High-scoring game environments vs low-scoring
6. **Opponent defensive rating** — Against top/bottom defenses
7. **Season phase granularity** — Monthly breakdown (Oct, Nov, Dec, Jan, Feb)
8. **4-way combos** — Do any 4-signal combinations exist with enough data?
9. **Streak analysis** — Do combos perform differently on W/L streaks?
10. **Time since last combo fire** — Does recency of last combo signal matter?

See `docs/08-projects/current/signal-discovery-framework/TESTING-COVERAGE-MAP.md` for the full coverage matrix with query templates.

---

## Success Criteria

- [ ] At least 2 production combo signals implemented (HE+MS, 3way)
- [ ] cold_snap and blowout_recovery updated with conditional filters
- [ ] Best Bets aggregator updated with combo bonuses/penalties
- [ ] (Stretch) 2-3 advanced tests completed from untested angles
- [ ] All changes deployed and verified
