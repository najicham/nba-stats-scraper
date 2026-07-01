# Session Handoff — 2026-07-01 (Session 1)

**Branch:** main
**State:** Off-season — halt active, no live picks until ~Oct 2026
**Session commits:** `0937b461`, `0d892287`
**Picking up from:** `docs/09-handoff/2026-06-30-1-session-handoff.md`

---

## What was completed this session

### Commit `0937b461` — 4 new shadow signals

All 4 are in `SHADOW_SIGNALS` (zero pick impact). Registered in `signals.yaml`, `aggregator.py`, `registry.py`. New supplemental queries in `supplemental_data.py` feed the pred dict fields they read.

| Signal | Tag | Fires when | Pred dict field | Promote at |
|--------|-----|-----------|-----------------|------------|
| Tight consensus UNDER | `tight_consensus_under` | 6+ distinct bookmakers posting lines today | `book_count_current` | N≥30 HR≥58% |
| Westward road trip UNDER | `westward_road_trip_under` | Away team traveled west tonight (body clock ahead) | `away_travel_direction` | N≥30 HR≥58% |
| B2B + long haul UNDER | `b2b_long_haul_under` | Back-to-back (rest_days==1) AND 1000+ miles traveled | `away_travel_miles` | N≥30 HR≥62% |
| Multi-book convergence UNDER | `multi_book_convergence_under` | 3+ bookmakers all lowered line intraday | `books_converging_down` | N≥30 HR≥58% |

**New supplemental queries (supplemental_data.py, before `predictions = []`):**
- `book_count_query` — `COUNT(DISTINCT bookmaker)` from `odds_api_player_points_props` for today
- `travel_context_query` — last game location → tonight join on `nba_static.travel_distances` → `distance_miles`, `travel_direction`, `time_zones_crossed` keyed by away_team_tricode
- `book_convergence_query` — `rn_asc`/`rn_desc` window functions to get first/last line per bookmaker → count of books moving down or up

**New pred dict fields:** `book_count_current`, `away_travel_direction`, `away_travel_miles`, `away_travel_tz_crossed`, `books_converging_down`, `books_converging_up`, `convergence_total_books`

---

### Commit `0d892287` — observation filter, Kelly haircut, cascade script

#### `low_variance_under_block` (observation filter)
- **Where:** `aggregator.py` inline filter block (before `blowout_risk_under_block`)
- **Condition:** UNDER + `points_std_last_10 < 4.5` + `3.0 <= pred_edge <= 5.0` + std > 0 (not missing)
- **Mode:** OBSERVATION — calls `_record_filtered()` but NO `continue`. Flows to `best_bets_filter_audit` for CF grading; picks are NOT blocked.
- **Registry:** `filters.yaml` with `status: observation`
- **Promote to active block when:** live CF HR ≤ 48% at N≥30 graded BB picks
- **Background:** Wave 1 pre-registered. 4/5 backtest seasons blocked losers (+11pp). 2025-26 inverted to 61.9% winners blocked (may be scoring-anomaly regime artifact — cannot tell until live data).

#### Same-team co-directional Kelly haircut
- **Where:** `pipeline_merger.py` after `selected` is finalized; `signal_best_bets_exporter.py` in `pick_dict` and `rows_to_insert`
- **Logic:** Groups `selected` picks by `(game_id, team_abbr, recommendation)`. Second+ pick in any co-directional same-team group gets `bet_size_units = 0.67` (⅓ haircut). All others get `1.0`.
- **Why:** Wave 1 walk-forward: same-team same-direction picks have ρ=+0.272 (p=0.014, N=38 real BB pairs) — correlated exposure.
- **Note:** `bet_size_units FLOAT64` column already existed in `signal_best_bets_picks` schema but was NULL until now. No schema migration needed.

#### Cascade repricing script
- **File:** `bin/analysis/cascade_repricing.py`
- **Usage:** `PYTHONPATH=. .venv/bin/python3 bin/analysis/cascade_repricing.py [--date YYYY-MM-DD]`
- **What it does:** Queries `nbac_injury_report` for stars (≥15 PPG avg last 90 days) who are Out/Doubtful, finds their teammates via `espn_team_rosters`, surfaces those teammates' predictions from `player_prop_predictions`, appends Bluesky posts about the ruled-out star from `bluesky_nba_news`. Read-only. Degrades gracefully when Bluesky listener isn't running (off-season).

---

## There are no immediate open items

The entire off-season backlog is cleared. All medium-priority signals from the handoff are built. All pre-registered research items (low_variance, Kelly haircut, cascade repricing) are wired.

---

## State of the shadow signal fleet (as of 2026-07-01)

| Signal | Added | Status | Promote when |
|--------|-------|--------|--------------|
| `b2b_fatigue_under` | 2026-06-23 | Shadow | N≥30 HR≥58% live 2026-27 |
| `national_tv_under` | 2026-06-28 | Shadow | N≥30 HR≥55% |
| `whole_line_precision` | 2026-06-29 | Shadow | UNDER: N≥30 HR≥62%; OVER: N≥50 HR≥70% |
| `line_converging_under` | 2026-06-29 | Shadow | N≥30 HR≥60% cross-season |
| `high_line_under` | 2026-06-29 | Shadow | N≥30 HR≥58% |
| `ref_crew_under_tendency` | 2026-06-29 | Shadow | N≥30 HR≥58% + 2 Covers seasons |
| `dense_schedule_grind_under` | 2026-06-29 | Shadow | N≥30 HR≥58% |
| `long_road_trip_under` | 2026-06-29 | Shadow | N≥30 HR≥58% |
| `rotowire_bench_under` | 2026-06-29 | Shadow | N≥30 HR≥65% |
| `tight_consensus_under` | 2026-06-30 | Shadow | N≥30 HR≥58% |
| `westward_road_trip_under` | 2026-06-30 | Shadow | N≥30 HR≥58% |
| `b2b_long_haul_under` | 2026-06-30 | Shadow | N≥30 HR≥62% |
| `multi_book_convergence_under` | 2026-06-30 | Shadow | N≥30 HR≥58% |
| 5 demoted OVER signals | 2026-06-26 | Shadow | Each: N≥30 HR≥58% via `over_decay_watch.py` |

**Observation filter fleet (new):**

| Filter | Added | Mode | Activate when |
|--------|-------|------|---------------|
| `low_variance_under_block` | 2026-07-01 | Observation (no block) | Live CF HR ≤48% at N≥30 |

---

## Season open (October 2026)

- Verify `stokastic_dfs_ownership` scraper returns data (returns 0 slates off-season)
- Check Bluesky handle DIDs still valid (handles can change between seasons)
- Watch `dense_schedule_grind_under` / `long_road_trip_under` / `westward_road_trip_under` / `b2b_long_haul_under` fire rates — all new, confirm additive beyond `b2b_fatigue_under`
- `ref_crew_under_tendency.crew_under_data_available` should stay FALSE until Covers accumulates 2026-27 data
- Tune RotoWire `/projected-minutes.php` parser if HTML structure differs
- Verify `travel_direction` values from `nba_static.travel_distances` populate correctly — spot-check a known westward trip in first week
- Check `tight_consensus_under` fire rate — expect ~10-15% of picks to have book_count≥6; if 0, odds_api scraper cadence may be too sparse
- Check `multi_book_convergence_under` fire rate — needs multiple intraday snapshots; if 0, scraper runs too infrequently to see movement
- First game with ≥2 same-team UNDER picks: verify `bet_size_units` shows 1.0/0.67 split in BQ

## December 2026 / January 2027

- Run `over_decay_watch.py` once OVER signals have N≥30 live picks
- Backtest `stokastic_dfs_ownership` ownership % vs UNDER HR
- Evaluate `low_variance_under_block` CF HR — promote to active block if CF HR ≤48% at N≥30
- Promote shadow signals hitting their thresholds (see fleet table above)
- Evaluate `dense_schedule_grind_under` + `long_road_trip_under` for promotion at N≥30 HR≥58%

---

## What NOT to re-litigate

- **OVER layer is fragile** — 5 signals in shadow, use `over_decay_watch.py` from Dec 2026, do not promote early
- **Features are done** — R²≈0 from error decomposition, edge is selection/signals
- **Research is converged** — CLV, low_variance, same-game sizing are all wired; no new backtesting needed off-season
- **Kelly haircut is ⅓ of the 2nd pick only** — do not apply to all picks or to opposite-direction pairs; ρ was for co-directional same-team only
- **`low_variance_under_block` must NOT be activated** without live CF HR confirmation — the 2025-26 inversion (61.9% winners blocked) is a real caution signal
