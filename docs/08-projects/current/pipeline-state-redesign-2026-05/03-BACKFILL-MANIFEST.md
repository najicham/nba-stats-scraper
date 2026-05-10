# Backfill Manifest — Oct 2025 – Feb 2026 NBA Data Recovery

**Scope:** 109 days (2025-10-21 → 2026-02-06) where Phase 1 GCS + Phase 2 BQ raw tables are absent for NBA. User decision: try everything, accept what we can recover.

**Status:** pending — backfill begins in Phase F (after gap_detector is live).

---

## Per-source recoverability

| Source | Bucket / Table | Recoverable? | Notes |
|---|---|---|---|
| `nbac_schedule` | `gs://nba-scraped-data/nba-com/schedule/2025-26/` + `nba_raw.nbac_schedule` | YES | NBA.com publishes full season schedule; re-scrape is idempotent. Already partially populated through 2026-06-19. |
| `nbac_gamebook_player_stats` | `gs://nba-scraped-data/nba-com/gamebooks-data/` + `nba_raw.nbac_gamebook_player_stats` | LIKELY YES | NBA.com publishes historical gamebooks indefinitely. PDF fetcher in `scrapers/nbacom/`. |
| `nbac_injury_report` | `gs://nba-scraped-data/nba-com/injury-report-data/` + `nba_raw.nbac_injury_report` | PARTIAL | NBA.com keeps current injury reports only; historical recovery via Wayback Machine or third-party archive may be partial. |
| `nbac_play_by_play` | `nba_raw.nbac_play_by_play` (entire 2025-26 season missing) | YES | NBA.com keeps PBP in JSON form indefinitely. Big effort: ~1000 games. |
| `odds_api_*` | `gs://nba-scraped-data/odds-api/...` + `nba_raw.odds_api_*` | NO (free tier) / MAYBE (paid) | Odds API historical endpoints require paid tier. Decision pending. |
| `bettingpros_player_props` | `gs://nba-scraped-data/bettingpros/...` + `nba_raw.bettingpros_player_points_props` | NO | BettingPros snapshots are point-in-time; no historical re-fetch path. |
| `numberfire_projections` (FanDuel) | `gs://nba-scraped-data/projections/numberfire/` | NO | Projections are pre-game point-in-time. |
| `fantasypros_projections`, `dailyfantasyfuel_projections`, `dimers_projections` | various | NO | Same — pre-game snapshots, no archive. |
| `teamrankings_pace`, `hashtagbasketball_dvp`, `rotowire_lineups`, `covers_referee_stats`, `nba_tracking_stats`, `vsin_betting_splits` | various | PARTIAL | TeamRankings + Hashtag may have historical pages; NBA Tracking via stats.nba.com works historically; VSiN/Covers/RotoWire are point-in-time. |

---

## Per-date status (placeholder — will be auto-populated by gap_detector once live)

| game_date | nbac_schedule | gamebook | injury | pbp | odds_api | bettingpros | projections | analytics_p3 | feature_store_p4 | predictions_p5 | published_p6 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025-10-21 | ? | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING |
| 2025-10-22 | ? | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING |
| ... | | | | | | | | | | | |
| 2026-02-06 | ? | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING | MISSING |

(Auto-generated table will replace this once `expected_outputs` is seeded in Phase C.)

---

## Recovery strategy

1. **Phase C** seeds `expected_outputs` with one row per (date, phase, output) for the entire 2025-26 season. All currently-missing dates get `status='EXPECTED'` with `expected_by` in the past.
2. **Phase E** activates `gap_detector` which auto-publishes Pub/Sub messages for every overdue row.
3. `scraper-gap-backfiller` consumes the messages and runs the appropriate scraper. `nbac_*` should mostly succeed; paid sources will fail, will be marked `FAILED + halt_reason='source_unavailable'`.
4. After Phase 2 raw data is recovered, re-run Phase 3 analytics + Phase 4 feature store + Phase 5 predictions for each backfilled date (idempotent reprocessing tooling — see `bin/reprocess.sh` to be added in Phase E).
5. Phase 6 publishing is NOT retried for historical dates — frontend doesn't browse historical date detail; we only need the data for training/grading.

---

## Auditing recovery

After Phase F runs, this manifest will be regenerated from `expected_outputs`:

```sql
SELECT
  game_date, output_type, status, last_error
FROM `nba-props-platform.nba_orchestration.expected_outputs`
WHERE game_date BETWEEN '2025-10-21' AND '2026-02-06'
  AND sport = 'nba'
ORDER BY game_date, phase, output_type;
```

A summary row in `00-PROJECT-PLAN.md` will record:
- Total expected: N
- COMPLETE: M (M/N %)
- EMPTY_OK: O (legitimately empty days)
- FAILED + paid-source-unavailable: P
- FAILED + recoverable: Q (these should be 0 by end of Phase F)
