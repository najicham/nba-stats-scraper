# Session Handoff — 2026-06-29 (Session 5)

**Branch:** main
**State:** Off-season — halt active, no live picks until ~Oct 2026
**Session commit:** `3fa2287b` (29 files, 3772 insertions)
**Picking up from:** `docs/09-handoff/2026-06-29-4-session-handoff.md`

---

## Context for the next session

This was the most productive build session of the off-season. We launched 10+ agents in parallel and executed two categories of work:
1. Finished the remaining open items from Session 4 (narrative scraper + T-3h scheduler)
2. Launched a broad multi-agent search for new edges — research + build in parallel

Everything is in `SHADOW` (zero pick impact) or `forward-collection only`. Nothing deploys to live picks until October.

**Do not re-litigate.** The research is done. All 10 original research agents completed. Two hypotheses were backtested and killed (H4 flat-line UNDER +1.6pp too weak; milestone proximity UNDER refuted). The rest are wired as shadow signals.

---

## What was built this session

### Infrastructure

**T-3h Phase 6 re-export scheduler**
- Added `phase6-clv-reexport` job to `bin/deploy/deploy_phase6_scheduler.sh`
- Schedule: `30 16 * * *` (4:30 PM ET, America/New_York timezone)
- Message: `{"export_types": ["signal-best-bets"], "target_date": "today"}`
- Run to deploy: `./bin/deploy/deploy_phase6_scheduler.sh`
- Purpose: gives `line_converging_under` and `clv_diverge_under_block` T-3h intraday precision instead of ~T-6h (noon)

---

### New forward-collection scrapers

Six new scrapers for narrative/sentiment data. All are **forward-collection only** — start Oct 2026, first backtest signals Jan–Feb 2027.

**1. `scrapers/external/espn_nba_news.py`** — ESPN bulk news API
- URL: `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news?limit=100&dates=YYYYMMDD`
- Extracts: headline, description, published_at, athlete_ids (REPEATED), topic_tags (REPEATED)
- BQ table: `nba_raw.espn_nba_news`
- Schedule: daily ~8 AM ET on game days

**2. `scrapers/external/espn_injuries.py`** — ESPN injury status, hourly game-day poller
- URL: `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries`
- Extracts per player: status (Day-To-Day/Out), fantasy_status (GTD/OUT), injury_type/detail/side, short_comment, long_comment, reported_at
- Timestamped GCS path so every hourly run APPENDS — enables GTD→Out change detection
- BQ table: `nba_raw.espn_injuries`
- Key query pattern for change detection: join on espn_injury_id + game_date, compare status between successive scraped_at timestamps
- Schedule: hourly on game days (~10 AM–8 PM ET)

**3. `scrapers/external/nba_injury_snapshots.py`** — Official NBA PDF via `nbainjuries` package
- PDF URL: `https://ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HH_MMPM.pdf`
- Uses `nbainjuries` package (handles 15-min cadence format change since Dec 2025)
- **Added `default-jre-headless` to Dockerfile** (tabula-py requires Java)
- BQ table: `nba_raw.nba_injury_snapshots`
- Complementary to existing `nbac_injury_report` scraper (same PDF, different parser)

**4. `scrapers/external/rotowire_nba_news.py`** — RotoWire RSS feed
- URL: `https://www.rotowire.com/rss/news.php?sport=NBA`
- RSS only returns ~5 most-recent items — needs to run every 5–10 min on game days to not miss articles
- Player name reliably extractable from `<title>` via `"Player Name: Action"` colon format
- BQ table: `nba_raw.rotowire_nba_news`

**5. `scrapers/external/stokastic_dfs_ownership.py`** — DFS ownership % + projections
- API: Stokastic's public Azure backend `https://app-api-dfs-prod-main.azurewebsites.net` (no auth!)
- Phase 1: get slate list → Phase 2: get projections for DK Main slate
- Captures: projected_ownership_pct (0-100), projected_salary, projected_points, projection_std_dev, dk_value, injury_status, confirmed_lineup
- BQ table: `nba_raw.stokastic_dfs_ownership`
- Schedule: 2 PM ET + 5 PM ET re-scrape on game days (Oct–Apr)
- **Off-season behavior:** returns 0 NBA slates (expected, gracefully handled)
- **Backtest query (2027):** `JOIN stokastic_dfs_ownership ON player_name + game_date WHERE projected_ownership_pct >= 30 AND recommendation='UNDER'` — test if high DFS ownership inflates prop lines → UNDER value

**6. `scrapers/external/bluesky_nba_news.py`** — Beat writer Jetstream WebSocket listener
- Subscribes to 30 NBA beat writer DIDs via Bluesky Jetstream (`wss://jetstream1.us-east.bsky.network`)
- No auth required. Uses `websockets` library directly (Jetstream is plain WebSocket, not atproto firehose)
- Keyword filters: `questionable`, `limited`, `scratch`, `GTD`, `game-time`, `won't play`, `out tonight`, `ruled out`, `reduced minutes`, `bounce back`, `won't start`
- Flushes to GCS + BQ every 5 minutes; exponential backoff reconnection (5s→120s)
- **This is a long-lived listener**, not a one-shot scraper. Designed to run as a Cloud Run Job from noon ET on game days
- BQ table: `nba_raw.bluesky_nba_news`
- **Key strategic signal:** Cascade repricing of TEAMMATE props takes 30–90 minutes after a star is ruled out. Beat writers post on Bluesky ~1–2 hours before tip. This monitor captures those posts to flag teammate OVER opportunities.
- Beat writer handles in the scraper: chrisbhaynes, thesteinline, zachlowenba, samamick, jakelfischer, anthonyvslater, danwoikesports, fredkatz, jonkrawczynski, bytimreynolds

---

### New shadow signals (zero pick impact)

**1. `dense_schedule_grind_under`** (`ml/signals/dense_schedule_grind.py`)
- Fires: `recommendation=='UNDER'` AND `games_in_last_7_days >= 4`
- Confidence: 0.60 base, 0.75 at 5+ games
- Data field: `games_in_last_7_days` — exposed via `per_model_pipeline.py` as `feature_4_value AS games_in_last_7_days` in the `book_stats` CTE
- Literature: schedule density is real (4-in-7 stretch causes cumulative fatigue, underpriced by books)
- Promotion gate: N≥30 HR≥58% live 2026-27; check overlap with b2b_fatigue_under first

**2. `long_road_trip_under`** (`ml/signals/long_road_trip_under.py`)
- Fires: `recommendation=='UNDER'` AND `is_home==False` AND `consecutive_road_games >= 3`
- Confidence: 0.62 base, +0.05 per extra game, capped 0.72
- Data field: `consecutive_road_games` — computed in `supplemental_data.py` via new `road_trip_query` CTE. Ranks prior games newest-first, finds first home game boundary: `boundary - 1 = consecutive away games`. 30-day lookback.
- Literature: 5th consecutive away game → win rate collapses; cumulative hotel/travel fatigue compounds
- Distinct from `b2b_fatigue_under`: fires even with rest days between games as long as team has been on road 3+ games
- Promotion gate: N≥30 HR≥58% live 2026-27

**3. `ref_crew_under_tendency`** (`ml/signals/ref_crew_under_tendency.py`)
- Fires: `recommendation=='UNDER'` AND `crew_under_data_available==True` AND `crew_avg_over_pct < 0.48`
- Data fields: `crew_avg_over_pct`, `crew_under_data_available` — added to `supplemental_data.py` via new `referee_crew_query` CTE. Joins `nba_raw.nbac_referee_game_pivot` on `game_date + away/home team abbr`, then joins each official to `covers_referee_stats`. Requires ≥2 of 3 crew members having Covers data.
- **Will return no-qualify for almost all games until covers_referee_stats accumulates through 2026-27** (scraper was broken until Session 4)
- Promotion gate: N≥30 HR≥58% AND Covers has 2+ full seasons of data

---

## Backtested and killed

- **H4 (flat line UNDER):** `|prop_line_delta| < 0.5` + UNDER = +1.6pp pooled, 3/4 seasons correct. Too weak to pre-register standalone. Maybe additive modifier someday.
- **Milestone proximity UNDER:** Player within 50pts of round-number season milestone + line≥20 + UNDER. −0.3pp, 2/4 seasons. Refuted. "Public piles on OVER for milestone stories" mechanism doesn't appear in data.

---

## Registry updates

- `clv_diverge_under_block` added to `shared/registry/filters.yaml` (was referenced in CLAUDE.md but not registered)
- `dense_schedule_grind_under`, `long_road_trip_under`, `ref_crew_under_tendency` added to `shared/registry/signals.yaml` with promotion gates

---

## Key strategic insight from this session

**The cascade repricing window (30–90 min) is the real edge, not primary injury news.** Sharp books reprice player props within 10–30 seconds of major injury news. But TEAMMATE props lag 30–90 minutes. The Bluesky beat-writer monitor + ESPN injuries hourly poller + RotoWire RSS are all designed to capture the "star just ruled out" signal before books fully reprice teammates.

**The right query once we have 1 season of data:**
```sql
-- Find teammate prop performance when star was ruled out within 2h of tip
SELECT
  pa.player_name, pa.recommendation, pa.prediction_correct,
  b.post_text AS trigger_post,
  TIMESTAMP_DIFF(pa.game_start, b.created_at, MINUTE) AS mins_after_post
FROM nba_raw.bluesky_nba_news b
JOIN nba_predictions.prediction_accuracy pa
  ON pa.game_date = b.game_date
  AND REGEXP_CONTAINS(b.post_text, r'(?i)(out tonight|won.t play|ruled out)')
WHERE b.keywords_matched LIKE '%out%'
```

---

## Open items for next session / season open

### Immediate (before October)
1. **Deploy the T-3h scheduler:** `./bin/deploy/deploy_phase6_scheduler.sh` (already in script, just needs running)
2. **Wire Bluesky scraper as a Cloud Run Job** with noon-ET daily trigger for game days
3. **Set up hourly ESPN injuries scheduler** for game days (similar to existing scraper schedulers)
4. **Fix RotoWire scraper to hit `/projected-minutes.php`** for actual per-player minute projections — the current `rotowire_lineups.py` hits the lineup page which has no minute projections, making `minutes_surge_over` structurally dead
5. **Consider `rotowire_bench_under`** — wire `rotowire_lineups.is_starter` (pre-game, already in BQ) as a fallback for `bench_under` instead of the post-game `starter_flag` (look-ahead bias)

### At season open (October 2026)
6. Verify `stokastic_dfs_ownership` scraper fires and returns data (off-season returns 0 slates)
7. Check Bluesky handle DIDs are still valid (handles can change)
8. Watch `dense_schedule_grind_under` and `long_road_trip_under` fire rates — confirm overlap with b2b_fatigue_under
9. First week `ref_crew_under_tendency` check — `crew_under_data_available` should stay FALSE until Covers accumulates data

### From December 2026 / January 2027
10. Run `over_decay_watch.py` once OVER signals have N≥30 live picks
11. Backtest `stokastic_dfs_ownership` ownership % vs UNDER hit rate (high ownership → inflated lines → UNDER value)
12. Evaluate `bluesky_nba_news` cascade repricing query (teammate props after star ruled out)
13. Evaluate `dense_schedule_grind_under` and `long_road_trip_under` against live N — promote to `UNDER_SIGNAL_WEIGHTS` at HR≥58% N≥30

---

## Additional signals researched but NOT YET BUILT (from research findings)

These were researched this session but deferred:

| Signal | Why Deferred | Priority |
|--------|-------------|---------|
| `westward_road_trip_under` | Needs `travel_direction` from `nba_enriched.travel_distances` to flow to player context | Medium |
| `b2b_long_haul_under` | Needs `travel_miles` from team context → player context pipeline | Medium |
| `multi_book_convergence_under` | Needs new supplemental CTE counting per-book intraday moves | Medium |
| `tight_consensus_under` | Expose `book_count` from existing query (1 line change) | Low |
| TV broadcast granularity | Extend ESPN scoreboard to capture network + game_time_et | Low |
| Action Network prop splits | No historical data, collect Oct 2026, Playwright needed | Oct 2026 |
| `low_variance_under_block` | Pre-registered after Wave 1 research; needs live CF HR monitor | Season open |

---

## Commits this session

```
3fa2287b  feat: narrative forward-collection scrapers + T-3h scheduler (29 files, 3772 insertions)
```

Pushed to origin/main. Auto-deploy will run for nba-scrapers service (Dockerfile changed + new scrapers).

---

## What NOT to re-litigate

- **Milestone proximity UNDER:** Refuted with real data. Done.
- **H4 flat-line UNDER:** +1.6pp, not signal-strength. Do not pre-register.
- **OVER layer:** 5 OVER signals in SHADOW. Use `over_decay_watch.py` from Dec 2026.
- **Features are done:** R²≈0 from error decomposition. Edge is in selection/signals. No new model features.
- **Google Trends:** 48h lag kills pre-game use. Skip.
- **Reddit:** ToS risk, no historical data, Pushshift dead. Skip.
