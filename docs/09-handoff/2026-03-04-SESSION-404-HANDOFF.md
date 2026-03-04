# Session 404 Handoff — Shadow Signal Expansion + VSiN Sharp Money + Doc Updates

**Date:** 2026-03-04 (late evening, continuation of 403)
**Algorithm:** `v404_sharp_money_shadow`
**Status:** Code complete, all files compile. Deploy needed.

---

## Changes Made

### Phase 1: Documentation Trim (early Session 404)

1. **CLAUDE.md trimmed** 455 → 385 lines (31KB → 21KB)
   - Dead ends → `docs/06-reference/model-dead-ends.md`
   - Signal details → `SIGNAL-INVENTORY.md`
2. **Signal Inventory** — complete rewrite (26 active + 8 shadow + 17 filters)
3. **Model Dead Ends** — new doc with 80+ categorized dead ends

### Phase 2: Shadow Signal Monitoring (Session 404 late)

Added 9 shadow signals to `ACTIVE_SIGNALS` in `signal_health.py`:
- Session 401 signals: `projection_consensus_over/under`, `predicted_pace_over`, `dvp_favorable_over`, `positive_clv_over/under`
- Session 404 signals: `sharp_money_over/under`, `minutes_surge_over`

These now get tracked in `signal_health_daily` and the firing canary.

### Phase 3: VSiN Sharp Money Signals (NEW)

**File:** `ml/signals/sharp_money.py` — 3 signal classes:
- `sharp_money_over` — Handle >= 65% OVER + tickets <= 45% OVER
- `sharp_money_under` — Handle >= 65% UNDER + tickets <= 45% UNDER
- `public_fade_filter` — 80%+ tickets on OVER (negative filter, registered but not active)

**Data pipeline:** VSiN query added to `supplemental_data.py`, joins via away_team/home_team from game_id. Team abbreviation format confirmed matching (3-letter tricodes).

### Phase 4: RotoWire Minutes Projection Signal (NEW)

**File:** `ml/signals/minutes_projection.py` — 1 signal class:
- `minutes_surge_over` — RotoWire projected minutes >= season avg + 3

**Data pipeline:** RotoWire query added to `supplemental_data.py`, joins via player_lookup.

**Note:** RotoWire `projected_minutes` is currently null for all rows. The signal will gracefully no-op until data appears.

### Phase 5: Pick Angle Templates

Added angle templates for all 9 new shadow signals in `pick_angle_builder.py`.

---

## Verification Results (Phase 1)

| Check | Result |
|-------|--------|
| 7 working scrapers | All have Mar 4 data |
| NumberFire (fixed) | Deploy succeeded, **zero BQ rows** — not triggered yet |
| VSiN (fixed) | Deploy succeeded, **zero BQ rows** — not triggered yet |
| NBA Tracking (fixed) | Deploy succeeded, **zero BQ rows** — not triggered yet |
| `predicted_pace_over` | **First shadow signal fire:** 2x on Mar 4 |
| `projection_consensus` | Not firing — NumberFire has no data yet |
| Mar 4 best bets | 2 picks (both OVER rescued) |
| RotoWire `projected_minutes` | Null for all rows — scraper gets lineups but not minutes |

---

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/sharp_money.py` | **NEW** — 3 signal classes (137 lines) |
| `ml/signals/minutes_projection.py` | **NEW** — 1 signal class (58 lines) |
| `ml/signals/supplemental_data.py` | +70 lines: VSiN + RotoWire BQ queries + pred dict wiring |
| `ml/signals/registry.py` | +17 lines: registered 4 new signals |
| `ml/signals/signal_health.py` | +12 lines: 9 shadow signals in ACTIVE_SIGNALS |
| `ml/signals/pick_angle_builder.py` | +11 lines: 9 pick angle templates |
| `ml/signals/aggregator.py` | Algorithm version → `v404_sharp_money_shadow` |
| `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md` | Updated with Session 404 signals |
| `docs/09-handoff/START-NEXT-SESSION-HERE.md` | Updated fleet + priorities |

---

## What to Check Next Session

### Immediate (before anything else)
1. **Trigger 3 fixed scrapers** — `nba-numberfire-projections`, `nba-vsin-betting-splits`, `nba-tracking-stats` Cloud Scheduler jobs
2. **Verify scraper data flows to BQ** — all 3 should produce rows
3. **Confirm projection_consensus fires** — with NumberFire data, MIN_SOURCES=2 should be achievable
4. **Check VSiN data format** — verify team abbreviations match game_id format

### After predictions run (~6 AM ET)
5. **Shadow signal validation query** (from SIGNAL-INVENTORY.md) — check fires for all 12 shadow signals
6. **Algorithm version** — verify `v404_sharp_money_shadow` in `best_bets_filter_audit`
7. **Pick volume** — compare vs Mar 4 baseline (2 picks)

### ~Mar 12-14 (first promotion window)
8. **Projection consensus** N=30 check — first promotion decision
9. **Signal rescue 14d check** — any rescue tag < 52.4% on 15+ picks → remove

---

## Key Decisions

- **All new signals start in shadow mode** — no aggregator integration until N >= 30 graded
- **VSiN sharp money is highest-priority new signal** — handle-ticket divergence is the most validated edge in sports betting
- **RotoWire minutes projection deferred** until `projected_minutes` field is populated
- **Algorithm version bumped** even though shadow signals don't affect picks — tracks the code change
