# Session Handoff — 2026-06-29 (Session 4)

**Branch:** main
**State:** Off-season (halt active, no live picks until ~Oct 2026)
**Commits this session:** 5 (bc9a44ec → f849ed02)

---

## What was accomplished

Worked through the prioritized off-season build list in order. 5 of 6 tasks complete.

### 1. `line_converging_under` CLV live gate (Task 1) ✅

**Commit:** `bc9a44ec`

Two-wire implementation of the T-3h CLV gate validated in Session 3 (62.4% agree vs 46.6% disagree, p=5e-26, N=1,155):

- **Positive signal** (`line_converging_under`): UNDER + DK line rose ≥ 0.5 intraday → SHADOW. File: `ml/signals/line_converging_under.py`.
- **Active block filter** (`clv_diverge_under_block`): UNDER + DK line dropped ≥ 0.5 intraday → ACTIVE inline block in `aggregator.py`. Records to `best_bets_filtered_picks` for CF HR tracking.

Uses `dk_line_move_direction` which is already on every prediction dict (computed in `supplemental_data.py` from DK bookmaker closing - opening). No new scraper needed.

**T-3h precision gap:** The Phase 6 export currently runs at 1 PM ET (~T-6h). For full T-3h precision, a Cloud Scheduler job at ~4:30 PM ET should re-trigger the Phase 6 best-bets export — then `dk_line_move_direction` would use the T-3h snapshot as "latest." This is the one remaining infrastructure item for this gate.

**Predecessor warning:** `positive_clv_under` (in `closing_line_value.py`, registered but dormant) was removed Session 514 for 41.4% BB HR. The difference is that the new gate is specifically T-3h validated with a direction-agreement filter, not just "did the line move today."

**Promotion gate:** UNDER signal: N≥30 at HR≥60% live 2026-27. Block filter: monitor CF HR — if CF HR climbs above 55% (meaning we're blocking winners), add `clv_diverge_under_block` to `_runtime_demoted`.

### 2. Scraper audit (Task 2) ✅

**Commit:** `679241db`

All three dead scrapers diagnosed and addressed:

| Scraper | Root cause | Fix |
|---------|-----------|-----|
| `covers_referee_stats` | Wrong URL: `/referees/statistics/{season}` → correct is `/referee-stats` | Updated `set_url()` |
| `nba_tracking_stats` | Wrong endpoint: `leaguedashplayerstats?MeasureType=Usage` doesn't return TOUCHES/DRIVES/CATCH_SHOOT. Need `leaguedashptstats?PtMeasureType=...` | Refactored to fetch 4 PtMeasureType endpoints + Usage, join on PLAYER_ID in `transform_data()` |
| `vsin_betting_splits` | Code is correct (Session 406 fix in place); data stopped 2026-03-28 — scheduler gap or VSiN HTML class change | Added diagnostic checklist comment; needs manual test at 2026-27 season open |

For `nba_tracking_stats`: both `_fetch_all_via_nba_api` and `_fetch_all_via_http` paths updated. Now fetches `Possessions`, `Drives`, `CatchShoot`, `PaintTouch` and joins on PLAYER_ID. Requires `LeagueDashPtStats` from `nba_api` (already in container requirements).

### 3. Regime-conditional promotion gate (Task 3) ✅

**Commit:** `46458a49`

`downtrend_under` (11.1% HR, 2/18 in March 2026) and `mean_reversion_under` (0.0% HR, 0/8) are both in SHADOW but nothing prevented premature promotion. Added explicit gates:
- `signals.yaml`: `promotion_gate` field on both — LOOSE market required (`vegas_mae_7d >= 4.5`) before adding to `UNDER_SIGNAL_WEIGHTS`
- `aggregator.py`: `⚠️ REGIME-GATED` comment block adjacent to each SHADOW_SIGNALS entry

### 4. `high_line_under` overlap check and wiring (Task 4) ✅

**Commit:** `7db333c9`

**Key finding:** `star_line_under` is NOT a "star player" signal — it's purely `line >= 25 + edge 3-7`. No usage/minutes/player-tier criterion despite the name. So `high_line_under` (line >= 25, no edge gate) is a **strict superset** of `star_line_under`.

`high_line_under` passed the formal discovery gate (59.9% HR, 5/5 seasons, p=0.0007). Wired as SHADOW. Key notes:
- **2025-26 decay warning:** `star_line_under` is 35.3% HR this season (N=17). The `line >= 25 UNDER` thesis is stressed in 2025-26. Watch `high_line_under` live HR carefully.
- **Intended replacement:** if `high_line_under` graduates, retire `star_line_under` (artificial edge band is the only difference).
- **Do NOT co-promote** both — they measure the same phenomenon.
- Promotion gate: N≥30 at HR≥58%, stratify by edge band before graduating.

Updated `star_line_under.py` with decay warning and overlap documentation.

### 5. `over_decay_watch.py` confirmed (Task 5) ✅

**Commit:** `f849ed02`

Script confirmed ready — syntax clean, smoke-tested in Session 3. Added to CLAUDE.md monitoring section with the `~Dec 2026` run date. It's a manual read-only tool (prints report, writes nothing). No Cloud Scheduler needed.

Run command: `PYTHONPATH=. python bin/monitoring/over_decay_watch.py`

---

## Open task (not started this session)

### Task 6: Narrative forward-collection scraper

Phase 0/1 showed a news scraper isn't justified yet, but forward collection is free. Should start collecting before October:
- `nbainjuries` Python package for injury-report snapshots
- Probe ESPN hidden API for game-day news blurbs

Not started this session. Low urgency — NBA doesn't open until October.

---

## Open infrastructure item

**T-3h Phase 6 re-export Cloud Scheduler job** — needed for `line_converging_under` to use a T-3h line snapshot instead of the ~noon snapshot. Add a Cloud Scheduler job at ~4:30 PM ET that fires: `{"export_types": ["signal-best-bets"], "target_date": "today"}` to the Phase 6 Pub/Sub topic. Without this, the CLV gate still works (uses morning drift direction) but is less precise.

---

## Commits this session

```
f849ed02  docs: add over_decay_watch.py to monitoring section + season-open checklist
7db333c9  feat: high_line_under shadow signal — edge-ungated replacement for star_line_under
46458a49  docs: regime-conditional promotion gate for downtrend_under / mean_reversion_under
679241db  fix: scraper audit — covers URL, tracking stats endpoint, vsin diagnostic
bc9a44ec  feat: line_converging_under CLV live gate — shadow signal + active block filter
```

All on main, pushed to origin.

---

## Shadow signal inventory (current state)

All signals with zero pick impact, accumulating live data:

| Signal | Promotion gate | Key risk |
|--------|---------------|---------|
| `national_tv_under` | N≥30, HR≥55% | Post-hoc discovery, overlap with star_line_under |
| `b2b_fatigue_under` | N≥30, HR≥58% | `is_b2b` unpopulated pre-2025-26 |
| `whole_line_precision` | N≥30, HR≥62% UNDER | Post-hoc |
| `line_converging_under` | N≥30, HR≥60% | Single-season validation |
| `high_line_under` | N≥30, HR≥58% + edge stratification | `star_line_under` showing decay |
| `fast_pace_over`, `cold_3pt_over`, `line_rising_over`, `book_disagree_over`, `b2b_boost_over` | N≥30, HR≥58% (via over_decay_watch.py) | 2025-26-only artifacts |
