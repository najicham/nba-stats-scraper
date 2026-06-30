# Session Handoff — 2026-06-30 (Session 1)

**Branch:** main
**State:** Off-season — halt active, no live picks until ~Oct 2026
**Session commits:** `37d7f7f9`, `4c09ce23`
**Picking up from:** `docs/09-handoff/2026-06-29-6-session-handoff.md`

---

## What was completed this session

All 3 open items from Session 6 are done. Everything is live in GCP.

### Deployed to GCP

| Resource | Type | Schedule |
|----------|------|----------|
| `espn-injuries-hourly` | Cloud Scheduler | Hourly 10 AM–8 PM ET, year-round |
| `rotowire-nba-news-frequent` | Cloud Scheduler | Every 10 min, 10 AM–10 PM ET, year-round |
| `rotowire-nba-news-daily` | Cloud Scheduler | Daily noon ET, May–Sep off-season only |
| `bluesky-nba-listener` | Cloud Run Job | 8h task (noon–8 PM ET) |
| `nba-bluesky-listener-daily` | Cloud Scheduler | Triggers the job daily at noon ET |

### Code committed

- `bin/deploy/deploy_rotowire_news_scheduler.sh` — new script, creates both RotoWire news scheduler jobs (frequent + off-season daily)
- `bin/deploy/deploy_bluesky_listener.sh` — fixed: `gcloud run jobs create` does not support `--description` flag (was causing silent failure)

---

## There are no immediate open items

The off-season deployment backlog from Sessions 5–6 is fully cleared. The system is in a clean waiting state until October 2026.

---

## Open items by priority

### Medium (build when ready, off-season)

| Signal | What's needed | Notes |
|--------|--------------|-------|
| `tight_consensus_under` | Expose `book_count` from existing supplemental CTE — 1 line change | Low lift, confirm threshold scale (raw vs normalized) |
| `westward_road_trip_under` | `travel_direction` from `nba_enriched.travel_distances` → player context | Check travel data pipeline first |
| `b2b_long_haul_under` | `travel_miles` from team context → player context | Same pipeline as above |
| `multi_book_convergence_under` | New supplemental CTE counting per-book intraday moves | More involved — needs multiple snapshots |

### Season open (October 2026)

- Verify `stokastic_dfs_ownership` scraper returns data (returns 0 slates off-season, now in registry)
- Check Bluesky handle DIDs still valid (handles can change between seasons)
- Watch `dense_schedule_grind_under` / `long_road_trip_under` fire rates — confirm additive beyond `b2b_fatigue_under`
- First week: `ref_crew_under_tendency.crew_under_data_available` should stay FALSE until Covers accumulates 2026-27 data
- Tune RotoWire `/projected-minutes.php` parser if HTML structure differs (off-season implementation was best-effort)
- Verify RotoWire news scheduler cadence is adequate (10 min during games, daily off-season)
- Confirm Bluesky listener job runs cleanly on first game day (check logs: `gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=bluesky-nba-listener' --limit=50`)

### December 2026 / January 2027

- Run `over_decay_watch.py` once OVER signals have N≥30 live picks
- Backtest `stokastic_dfs_ownership` ownership % vs UNDER HR (high ownership → inflated lines → UNDER value)
- Bluesky cascade repricing query (teammate props when star ruled out within 2h of tip)
- Evaluate `dense_schedule_grind_under` + `long_road_trip_under` for promotion at N≥30 HR≥58%
- `low_variance_under_block` — pre-registered after Wave 1 research; needs live CF HR monitor before promotion

---

## State of the shadow signal fleet (as of 2026-06-30, unchanged from Session 6)

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
| 5 demoted OVER signals | 2026-06-26 | Shadow | Each: N≥30 HR≥58% via `over_decay_watch.py` |

---

## What NOT to re-litigate

- **OVER layer is fragile** — 5 signals in shadow, use `over_decay_watch.py` from Dec 2026, do not promote early
- **Features are done** — R²≈0 from error decomposition, edge is selection/signals
- **Research is converged** — CLV, low_variance, same-game sizing are pre-registered; no new backtesting needed off-season
- **RotoWire minutes parser** — intentionally best-effort for off-season; tune at season open when you can see the actual page
