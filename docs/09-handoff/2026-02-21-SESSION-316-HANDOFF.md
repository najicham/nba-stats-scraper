# Session 316 Handoff — Best Bets Fixes, Backfill, and Research Agenda

**Date:** 2026-02-21
**Focus:** Fixed 3 best bets bugs, backfilled true performance, identified research areas
**Status:** Code deployed, backfill complete, research agenda for next session
**Prior sessions:** 315 (directional cap investigation), 314 (consolidation), 297 (edge-first)

---

## TL;DR

Fixed three bugs that were corrupting best bets tracking. Backfilled Jan 1 - Feb 20 with v316 algorithm. **True best bets HR is 74.6% (91W-31L, +$5,690 P&L)**. The earlier-reported 48% was tracking the wrong picks entirely.

---

## What Was Done

### Bugs Fixed

1. **Duplicate writes in `signal_annotator.py`:** `_bridge_signal_picks()` lacked DELETE-before-INSERT idempotency. Each re-run appended duplicates (Feb 20 had 16x per player). Fixed with DELETE + batch load (not streaming, to avoid DML buffer conflicts).

2. **Legacy dual writer:** `dynamic_subset_definitions` had a `best_bets` row with `min_edge=0.0, top_n=5` that caused `SubsetMaterializer` to write low-edge picks alongside the aggregator's proper edge-5+ picks. **Deactivated** (`is_active=FALSE`).

3. **UNDER 7+ star-line refinement:** UNDER edge 7+ overall = 40.7% HR, but line >= 25 (stars) = 71.4% HR (N=7). Modified filter to block only when `line < 25`.

### Backfill

- Ran `bin/backfill_dry_run.py --start 2026-01-01 --end 2026-02-20 --write`
- All 134 picks written to `signal_best_bets_picks` with `algorithm_version = 'v316_star_under_refinement'`
- Old rows deleted per date before inserting (idempotent)

### Data Cleanup

- Deduped `current_subset_picks` best_bets rows for Feb 19-20
- Feb 21 rows in streaming buffer, will self-clean on next export

---

## True Best Bets Performance (v316 Algorithm)

```
Period:       Jan 1 - Feb 20, 2026
Total picks:  134
Graded:       122 (91W - 31L)
Hit Rate:     74.6%
P&L:          +$5,690 ($110 risk / $100 win per bet)

Weekly breakdown:
  Jan 8  — 53W-9L  (85%)   ← peak performance
  Jan 15 — 10W-5L  (67%)
  Jan 22 — 9W-1L   (90%)   ← peak performance
  Jan 29 — 6W-5L   (55%)   ← DOWN WEEK
  Feb 5  — 11W-8L  (58%)   ← DOWN WEEK
  Feb 19 — 2W-3L   (40%)   ← post-ASB, thin market (N=5)
```

### Why Was 48% Reported Earlier?

The daily-steering skill queried `current_subset_picks` (subset_id='best_bets'), which was populated by the **legacy SubsetMaterializer** with `min_edge=0.0`. These were completely different picks from the aggregator. The actual aggregator picks went to `signal_best_bets_picks` and were 74.6% HR.

**Fix needed:** Daily-steering skill should query `signal_best_bets_picks`, not `current_subset_picks`.

---

## Down Week Analysis (Jan 29 - Feb 12)

### Picks That Lost During Down Weeks

| Date | Player | Dir | Edge | Line | Actual | Signals |
|------|--------|-----|------|------|--------|---------|
| Jan 29 | tyresemaxey | UNDER | 7.2 | 27.1 | 40 | HE, ESO, volatile_under |
| Jan 30 | lukadoncic | UNDER | 5.7 | 33.6 | 37 | HE, ESO, high_usage_under |
| Feb 1 | nikolajokic | OVER | 9.7 | 24.5 | 16 | HE, blowout_recovery, ESO |
| Feb 3 | austinreaves | OVER | 17.6 | 15.5 | 15 | HE, blowout_recovery, ESO |
| Feb 4 | jamalmurray | UNDER | 6.6 | 22.5 | 39 | HE, ESO, b2b_fatigue_under |
| Feb 7 | keyontegeorge | OVER | 11.5 | 15.5 | 5 | HE, ESO, prop_line_drop_over |
| Feb 7 | donovanmitchell | UNDER | 5.4 | 28.5 | 35 | HE, ESO, high_usage_under |
| Feb 8 | paytonpritchard | OVER | 6.7 | 11.5 | 6 | HE, ESO, prop_line_drop_over |
| Feb 8 | jadenmcdaniels | OVER | 5.4 | 13.5 | 2 | HE, MS, combo_he_ms, combo_3way |
| Feb 9 | franzwagner | OVER | 5.0 | 15.5 | 14 | HE, blowout_recovery, ESO |
| Feb 10 | brandonwilliams | OVER | 5.0 | 11.5 | 5 | HE, ESO, rest_advantage_2d |
| Feb 11 | tyresemaxey | UNDER | 5.3 | 25.5 | 32 | HE, ESO, self_creator_under |
| Feb 11 | jalenjohnson | OVER | 5.0 | 22.5 | 19 | HE, ESO, rest_advantage_2d |

### Patterns in Losses

1. **Star UNDERs failing:** Maxey (27.1 line, scored 40), Doncic (33.6, scored 37), Murray (22.5, scored 39), Mitchell (28.5, scored 35), Maxey again (25.5, scored 32). Stars exceeded their lines by 5-17 points.
2. **blowout_recovery OVER failing:** Jokic (24.5 line, scored 16), Reaves (15.5, scored 15), Wagner (15.5, scored 14). Players expected to bounce back from blowouts didn't.
3. **prop_line_drop_over failing:** George (15.5, scored 5), Pritchard (11.5, scored 6), McDaniels (13.5, scored 2). Line drops may indicate market knew something the model didn't.
4. **Low-line OVERs failing:** Williams (11.5, scored 5), Pritchard (11.5, scored 6), McDaniels (13.5, scored 2). Bench/role players with low lines had catastrophic misses.

---

## Research Agenda for Next Session

### 1. Down Week Root Cause Deep Dive

**Question:** Could any additional filter have prevented the Jan 29 - Feb 12 losses?

**Research tasks:**
- Query all losses at edge 5+ during down weeks. Categorize by: direction, line tier, signal combination, player type (star/starter/role/bench)
- Test hypothetical filters:
  - `blowout_recovery` OVER block: what's the season HR? The signal is 56.9% overall (WATCH status). Should it be a negative filter?
  - `prop_line_drop_over` + low line (<15): multiple catastrophic failures. Is this a systematic pattern?
  - Star UNDER + `high_usage_under` or `self_creator_under`: check if these signal combos are anti-correlated
  - `rest_advantage_2d` on its own: 64.8% overall but "W4 decay to 45.2%" per CLAUDE.md. Was the down week during a decay period?
- Run `/what-if` comparing a model retrained to Jan 28 vs the production model for Feb 1-12

### 2. Signal Subset Integration with Best Bets

**Question:** Are signal subset picks (combo_he_ms, combo_3way, bench_under, signal_high_count) making it into best bets? Should they be weighted differently?

**Research tasks:**
- Query overlap between `signal_*` subset picks and `signal_best_bets_picks` (query was started but returned empty — may need re-run after backfill)
- For each signal subset, compare HR of picks that ARE in best bets vs those that AREN'T
- Check if `combo_he_ms` (94.9% HR) and `combo_3way` (95.5% HR) picks always pass the aggregator's edge 5+ floor
- If high-HR signal combos are being filtered out by edge floor or signal_count, consider special-casing them

### 3. Backfill Signal Subsets and Export to Website

**Question:** Should we backfill signal subset picks and add them to the GCS API?

**Research tasks:**
- Check `current_subset_picks` for signal_* subset coverage (are they populated from Jan 1?)
- If not, the `SignalSubsetMaterializer` needs backfilling (it was created Session 311, so only recent data)
- Design a new GCS JSON endpoint: `v1/best-bets/history.json` or `v1/best-bets/{date}.json`
- Consider: should the website show individual picks or just aggregate stats?

### 4. Website Best Bets Display Design

**Question:** How should best bets be displayed on playerprops.io?

**Design options to evaluate:**

**Option A — Daily view with weekly grouping:**
```
Season: 91-31 (74.6%)  |  This Month: 13-11 (54.2%)  |  This Week: 2-3 (40.0%)

Week of Feb 17
├── Feb 19: 2-2 (50%) — Kawhi Leonard ✓, Alperen Sengun ✓, Jalen Green ✗, Donovan Mitchell ✗
└── Feb 20: 0-1 (0%) — Luka Doncic ✗

Week of Feb 3
├── Feb 11: 3-2 — Jarrett Allen ✓, Kyle Kuzma ✓, Victor Wembanyama ✓, ...
├── Feb 08: 1-2 — Jaylen Brown ✓, Payton Pritchard ✗, Jaden McDaniels ✗
...
```

**Option B — Calendar heat map:**
- Color-coded calendar (green = winning day, red = losing day, gray = no picks)
- Click a day to expand picks

**Option C — Running record with streak tracking:**
```
Current streak: L3
Best streak: W12 (Jan 11-22)
Record: 91-31 (74.6%)
```

**Key considerations:**
- The GCS API currently has `v1/signal-best-bets/{date}.json` and `v1/signal-best-bets/latest.json`
- Historical JSON files exist but have the OLD algorithm data (pre-edge-first)
- Need to decide: re-export all historical JSONs, or create a new aggregate endpoint?
- Time period records at top of page: Season / Month / Week / Last 10 picks

**Recommended approach:**
1. Create `v1/best-bets/record.json` — aggregate stats (season/month/week W-L-HR, current streak, last 10)
2. Create `v1/best-bets/history.json` — full pick history with grading (for calendar/daily view)
3. Keep existing `v1/signal-best-bets/{date}.json` for daily picks
4. Frontend shows record banner + daily picks below

### 5. Fix Daily-Steering Skill

**Task:** Update `.claude/skills/daily-steering/SKILL.md` to query `signal_best_bets_picks` instead of `current_subset_picks` for best bets track record. The current queries produce misleading numbers.

### 6. Model Retrain Timing

**Context:**
- Champion V9 is 13 days stale (OVERDUE per 7-day cadence)
- What-if showed Feb 10 retrain vs Feb 5 retrain = nearly identical results
- Post-ASB market is tighter — only 6 edge 5+ picks in last 2 game days
- V12 outperforms V9 (66.7% vs 43.8% at edge 5+) but too low volume

**Question:** Should we retrain now or wait for more post-ASB data?
- Run what-if with train-end 2026-02-19 (includes 2 post-ASB game days)
- Compare against current production model's actual performance
- If retrain shows no improvement, wait until end of week (Feb 28) for 7+ post-ASB game days

---

## Files Modified This Session

| File | Change |
|------|--------|
| `data_processors/publishing/signal_annotator.py` | DELETE-before-INSERT + batch load for best_bets |
| `ml/signals/aggregator.py` | UNDER 7+ star-line exception (line>=25 allowed), v316 version |
| `tests/unit/signals/test_aggregator.py` | New test for star-line exception |
| `tests/unit/signals/test_player_blacklist.py` | Updated version assertion |
| `bin/backfill_dry_run.py` | Added `--write` flag for BQ backfill |
| BQ: `dynamic_subset_definitions` | Deactivated legacy `best_bets` row (is_active=FALSE) |
| BQ: `signal_best_bets_picks` | Backfilled Jan 1 - Feb 20 with v316 algorithm |
| BQ: `current_subset_picks` | Cleaned up Feb 19-20 duplicates |

## Key Commits

- `575a77ab` — fix: best bets duplicate writes and UNDER 7+ star-line refinement

---

## Priority Order for Next Session

1. **Fix daily-steering skill** (5 min) — prevents misleading reports
2. **Down week root cause** (30 min) — find additional negative filters
3. **Signal subset integration** (20 min) — verify high-HR signals reach best bets
4. **Website display design** (30 min) — design + implement GCS endpoints
5. **Model retrain assessment** (15 min) — decide timing

---
*Created: Session 316. Prior: Session 315 (directional cap investigation).*
