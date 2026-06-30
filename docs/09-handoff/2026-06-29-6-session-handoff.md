# Session Handoff — 2026-06-29 (Session 6)

**Branch:** main
**State:** Off-season — halt active, no live picks until ~Oct 2026
**Session commit:** `1f92011a` (9 files, 408 insertions)
**Picking up from:** `docs/09-handoff/2026-06-29-5-session-handoff.md`

---

## What was completed this session

This session finished all 5 immediate open items from Session 5, plus two bonus additions (scraper registry gaps).

### Deployed to GCP
- **`phase6-clv-reexport` scheduler** — live at 4:30 PM ET daily. Triggers re-export of `signal-best-bets` with T-3h intraday line snapshots for `line_converging_under` / `clv_diverge_under_block` precision.

### Code committed (`1f92011a`)

**Scrapers:**
- `scrapers/registry.py` — added `stokastic_dfs_ownership` + `nba_injury_snapshots` to `NBA_SCRAPER_REGISTRY` and `"external"` group (both scrapers existed but weren't reachable via the service endpoint)
- `scrapers/external/bluesky_nba_news.py` — `--date` is now optional (defaults to today), enabling Cloud Run Job use without dynamic arg injection
- `scrapers/external/rotowire_lineups.py` — secondary fetch to `/projected-minutes.php` after parsing lineups; merges minutes by `player_lookup`; fixes `minutes_surge_over` data gap where the lineup page has no minute projections

**Signals:**
- `ml/signals/rotowire_bench_under.py` (new) — shadow signal using pre-game `rotowire_lineups.is_starter` as a look-ahead-free proxy for `bench_under` (which reads post-game `starter_flag`)
- `ml/signals/aggregator.py` — `rotowire_bench_under` added to `SHADOW_SIGNALS`
- `shared/registry/signals.yaml` — `rotowire_bench_under` registered
- `ml/signals/per_model_pipeline.py` — rotowire BQ query extended to also fetch `is_starter`; `rotowire_lineup` dict wired into `supplemental_map` keyed by `player_lookup`

**Deploy scripts (written, not yet run):**
- `bin/deploy/deploy_espn_injuries_scheduler.sh` — creates `espn-injuries-hourly` Cloud Scheduler job: hourly 10 AM–8 PM ET, calls nba-scrapers service at `espn_injuries` endpoint
- `bin/deploy/deploy_bluesky_listener.sh` — creates `bluesky-nba-listener` Cloud Run Job (8h, uses nba-scrapers image, overrides CMD to run bluesky_nba_news.py) + `nba-bluesky-listener-daily` Cloud Scheduler at noon ET

---

## First things to do in the next session

### 1. Run the two deploy scripts (quick, ~2 min each)

```bash
./bin/deploy/deploy_bluesky_listener.sh
./bin/deploy/deploy_espn_injuries_scheduler.sh
```

Both support `--dry-run` to preview first. These create live GCP resources (Cloud Run Job + 2 Cloud Scheduler jobs) — confirm before running.

### 2. RotoWire news scraper needs a scheduler

The `rotowire_nba_news.py` scraper RSS feed only returns ~5 most-recent items. The current `rotowire_lineups` scheduler fires once daily — that's not enough for news (items rotate off). Needs a scheduler that fires every 10 min on game days (or minimum every 30 min). No script exists yet.

Pattern to follow: `bin/schedulers/setup_nba_player_props_schedulers.sh`. The body format is:
```json
{"scraper": "rotowire_nba_news", "date": "TODAY"}
```

---

## Open items by priority

### Medium (build when ready)

| Signal | What's needed | Notes |
|--------|-------------|-------|
| `tight_consensus_under` | Expose `book_count` from existing supplemental CTE — 1 line change | Low lift, confirm threshold scale (raw vs normalized) |
| `westward_road_trip_under` | `travel_direction` from `nba_enriched.travel_distances` → player context | Needs travel data pipeline check |
| `b2b_long_haul_under` | `travel_miles` from team context → player context | Same pipeline as above |
| `multi_book_convergence_under` | New supplemental CTE counting per-book intraday moves | More involved — needs multiple snapshots |

### Season open (October 2026)

- Verify `stokastic_dfs_ownership` scraper returns data (was returning 0 slates off-season, now in registry)
- Check Bluesky handle DIDs still valid (handles can change)
- Watch `dense_schedule_grind_under` / `long_road_trip_under` fire rates — confirm additive beyond `b2b_fatigue_under`
- First week: `ref_crew_under_tendency.crew_under_data_available` should stay FALSE until Covers accumulates 2026-27 data
- Tune RotoWire `/projected-minutes.php` parser if HTML structure differs from what the off-season implementation assumed

### December 2026 / January 2027

- Run `over_decay_watch.py` once OVER signals have N≥30 live picks
- Backtest `stokastic_dfs_ownership` ownership % vs UNDER HR (high ownership → inflated lines → UNDER value)
- Bluesky cascade repricing query (teammate props when star ruled out within 2h of tip)
- Evaluate `dense_schedule_grind_under` + `long_road_trip_under` for promotion at N≥30 HR≥58%
- `low_variance_under_block` — pre-registered after Wave 1 research; needs live CF HR monitor before promotion

---

## Key wiring detail: rotowire_bench_under

The signal reads from `supplemental['rotowire_lineup']['is_starter']` (bool or None). This is populated in `per_model_pipeline.py` from `nba_raw.rotowire_lineups.is_starter`. The query now fetches `is_starter` alongside `projected_minutes`. Off-season: `rotowire_lineups` has no rows → signal returns `_no_qualify()` gracefully.

Promotion gate: N≥30 live picks at HR≥65%. Confirm it's additive beyond the existing `bench_under` signal (which fires on post-game `starter_flag`).

---

## State of the shadow signal fleet (as of 2026-06-29)

| Signal | Added | Status | Promote when |
|--------|-------|--------|-------------|
| `b2b_fatigue_under` | 2026-06-23 | Shadow | N≥30 HR≥58% live 2026-27 |
| `national_tv_under` | 2026-06-28 | Shadow | N≥30 HR≥55% |
| `whole_line_precision` | 2026-06-29 | Shadow | UNDER: N≥30 HR≥62%; OVER: N≥50 HR≥70% |
| `line_converging_under` | 2026-06-29 | Shadow | N≥30 HR≥60% cross-season |
| `high_line_under` | 2026-06-29 | Shadow | N≥30 HR≥58% |
| `ref_crew_under_tendency` | 2026-06-29 | Shadow | N≥30 HR≥58% + 2 Covers seasons |
| `dense_schedule_grind_under` | 2026-06-29 | Shadow | N≥30 HR≥58% |
| `long_road_trip_under` | 2026-06-29 | Shadow | N≥30 HR≥58% |
| `rotowire_bench_under` | 2026-06-29 | Shadow | N≥30 HR≥65% |
| 5 demoted OVER signals | 2026-06-26 | Shadow | Each: N≥30 HR≥58% via `over_decay_watch.py` |

---

## What NOT to re-litigate

- **OVER layer is fragile** — 5 signals in shadow, use `over_decay_watch.py` from Dec 2026, do not promote early
- **Features are done** — R²≈0 from error decomposition, edge is selection/signals
- **Research is converged** — CLV, low_variance, same-game sizing are pre-registered; no new backtesting needed off-season
- **RotoWire minutes parser** — intentionally best-effort for off-season; tune at season open when you can see the actual page
