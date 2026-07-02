# Session Handoff — 2026-06-29 (Session 3)

**Branch:** main
**State:** Off-season (halt active, no live picks until ~Oct 2026)
**Commits:** merge `narrative-national-tv-under-shadow` + `whole_line_precision` shadow signal

---

## What was accomplished

### 1. March 2026 production collapse — FULLY DIAGNOSED

Production BB hit 46.7% in March while the clean walk-forward model held up. Three overlapping causes:

**Cause 1: TIGHT market (March 8, vegas_mae_7d = 4.40)**
- 15 OVER picks went 1/15 (6.7%) on March 8 alone
- The edge-based auto-halt (Session 515) didn't exist yet in March

**Cause 2: Bad signals active/rescue-enabled by March**
- `projection_consensus_over`: 9.5% HR (21 picks) — **REMOVED** Session 514
- `volatile_scoring_over`: 6.7% HR (15 picks) — **REMOVED** Session 514
- `downtrend_under`: 11.1% HR (18 picks) — **SHADOW** — DO NOT PROMOTE without regime gate
- `mean_reversion_under`: 0.0% HR (8 picks) — **SHADOW** — same warning
- `day_of_week_under`: 18.2% HR (11 picks) — SHADOW

**Cause 3: Algorithm churn**
- 10+ algorithm versions deployed in March vs 1 stable version all of January
- Each panic-fix promoted new untested signals

**Status of fixes:** All major fixes in place. One open item: add "regime-conditional promotion" rule for `downtrend_under`/`mean_reversion_under` — these should only be promoted if cross-season validation holds AND `market_regime = 'LOOSE'`.

### 2. Season-open playbook — COMPLETE

All shadow signals staged and wired before October:

| Signal | Status | Promotion gate |
|--------|--------|---------------|
| `national_tv_under` | SHADOW, on main (merged today) | N≥30, HR≥55% live 2026-27 |
| `b2b_fatigue_under` | SHADOW, on main | N≥30, HR≥58% live 2026-27 |
| `whole_line_precision` | SHADOW, on main (wired today) | UNDER: N≥30 HR≥62%; OVER: N≥50 HR≥70% |
| `fast_pace_over`, `cold_3pt_over`, `line_rising_over`, `book_disagree_over`, `b2b_boost_over` | SHADOW (demoted OVER layer) | Must earn back via `over_decay_watch.py` (N≥30, HR≥58% live) |

`over_decay_watch.py` smoke-test passes cleanly. Run from Dec 2026 onward.

### 3. New signal discovered: `whole_line_precision`

**Finding:** Books that set prop lines at whole numbers (23.0 not 22.5) yield +10-20pp higher HR for our model predictions — consistent across ALL 5 seasons and ALL line buckets.

| Season | Half-line HR | Whole-line HR | Gap |
|--------|-------------|---------------|-----|
| 2022-23 | 66.6% | 81.5% | +14.9pp |
| 2023-24 | 64.9% | 84.0% | +19.1pp |
| 2024-25 | 64.2% | 75.2% | +11.0pp |
| 2025-26 (normal) | 63.3% | 76.6% | +13.3pp |

BB-level UNDER (2026): 70.6% vs 58.3% (+12pp, N=34).

**Mechanism:** Whole-number line = lower book conviction or early-market line. Push mechanics (3.5-3.9% push rate) explain <2pp. The gap is genuine model accuracy difference.

**Implementation:** `ml/signals/whole_line_precision.py`, SHADOW in `aggregator.py`, registered in `registry.py` and `signals.yaml`. Pre-registration at `docs/08-projects/current/whole-line-precision/00-PREREGISTRATION.md`.

**Key question for 2026-27:** Do whole-number lines appear at major US-regulated books (DraftKings, FanDuel)? Observe in October — if yes, this is a major practical edge.

---

## Staged items (NOT yet wired — season-open build list)

1. **`line_converging_under` (CLV live gate)** — validated in Phase 2 CLV research. UNDER picks where model edge dir AND line drift agree → 62.4% HR (p=5e-26). Needs live T-3h implementation using intraday `odds_api_player_points_props` snapshots. Build before Oct 2026.

2. **`low_variance_under_block`** — UNDER edge[3,5] with σ<4.5 → 45.7% HR (blocks losers 4/5 seasons). **2025-26 INVERTED to 61.9%** → stage shadow, promote only if live CF HR ≤48% N≥30. Do NOT activate without live confirmation.

3. **Same-game co-directional Kelly haircut** — when multiple picks from same game in same direction, reduce bet size ~⅓. Pre-register for live watch, don't implement sizing until N≥30.

---

## Remaining open direction: Narrative/news frontier

Not scaffolded this session (Phase 0/1 already done). Next step: start forward collection when season opens in October. Cheapest entry: `nbainjuries` Python package for injury-report snapshots + ESPN hidden-API probe for news blurbs. Payoff deferred to 2027+; start collecting in October.

---

## Data source issues found

- `covers_referee_stats`: all key columns NULL (over_record, under_record, over_percentage), data only from March-April 2026. **Dead end** for referee analysis — scraper isn't capturing data.
- `nba_tracking_stats`: `touches`, `drives`, `catch_shoot_fga` all zero across the board. **Dead end** — scraper captures minutes/usage but not play-by-play tracking columns.
- `vsin_betting_splits`: no data (failed queries). **Dead end** until scraper is fixed.

These three data sources look active in the pipeline but are yielding empty/zero data for the analytics columns. Worth a scraper audit before the season starts.

---

## Commits this session

```
c005ff03  feat: whole_line_precision shadow signal — +10-20pp HR on integer prop lines
db0b03a9  feat: merge national_tv_under shadow signal + narrative-proxies Phase 0/1
```

Both on main, pushed to origin.
