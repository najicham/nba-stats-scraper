# Session Handoff — 2026-07-03

**Branch:** main (clean, pushed → `258c9d75`)
**State:** Off-season — halt active, no live picks until ~Oct 2026
**Prior handoff:** `2026-07-02-2-session-handoff.md`
**Deploys:** `deploy-data-source-health-canary` ✅ SUCCESS, `deploy-prediction-worker` ✅ SUCCESS

---

## Goal this session

Two asks: (1) get the DraftKings Network scraper "all ready" for season-open, and
(2) determine whether we actually have a system that catches scrapers silently dying
(VSiN was dark from 2026-03-28 and nobody noticed for months).

---

## 1. DraftKings Network scraper — now ready for season-open

The scraper/processor/BQ table were built last session (commit `17173267`). This
session closed the two remaining wiring gaps.

| Item | State |
|------|-------|
| **Signal wiring** | DONE — `ml/signals/supplemental_data.py` sharp-money query now `UNION`s `dknetwork_betting_splits` + `vsin_betting_splits`, preferring dknetwork per game (`QUALIFY ROW_NUMBER()`), VSiN kept as fallback if it ever revives. Pred keys stay `vsin_*` so `sharp_money.py` needs no change. **Zero pick impact** — `sharp_money_over` removed, `sharp_money_under`/`public_fade_filter` are shadow. |
| **Scheduler** | WRITTEN, NOT DEPLOYED — `bin/deploy/deploy_dknetwork_scheduler.sh`, daily 2 PM ET, dry-run verified. Deploy needs season-open sign-off. |
| **Canary monitoring** | DONE — added to `data_source_health_canary` SOURCES. |

### Remaining (season-open, needs live NBA games — cannot be done now)
1. Run `./bin/deploy/deploy_dknetwork_scheduler.sh` once NBA games exist.
2. **First-game-day smoke test** — NBA tricode/matchup format is *assumed*
   (`"LAL Lakers @ BOS Celtics"`); only MLB format was validated. Fix
   `resolve_team()` in the scraper if tricodes parse wrong.
3. If Cloud Run returns 0 games / HTTP errors → GCP egress IP blocked → set
   `proxy_enabled=True` in the scraper and redeploy nba-scrapers.
4. Promote `sharp_money_under` / `public_fade_filter` out of shadow only after
   live validation.

The scraper URL hardcodes `tb_edate=today`, so the scheduled job MUST fire on the
actual game day (a same-day 2 PM ET run is correct). All of the above is documented
in the scheduler script header.

---

## 2. Scraper monitoring — the answer, and three bugs fixed

**Answer: yes, we now have a working silent-death monitor.** We already had
`data_source_health_canary` (CF `data-source-health-canary`, scheduled
`data-source-health-canary-daily` 7 AM ET — confirmed live in GCP). But it had
**three defects** that are exactly why VSiN slipped. All fixed this session
(commit `10fda5d5`).

1. **Baseline-decay blind spot (the root cause).** DEAD required a nonzero 7-day
   baseline. Once a source was dead >7 days, its baseline decayed to 0 and it
   flipped back to **HEALTHY** — the canary literally forgot the death after a
   week. Fixed: DEAD now also uses a **60-day last-seen window** and reports
   **"N days dark, last seen `<date>`"**.

2. **No escalation.** DEAD only reached `#nba-alerts` for CRITICAL sources;
   external scrapers (all WARNING) produced one ignorable `#canary-alerts` line.
   Fixed: any DEAD source (any severity) now fires a dedicated
   **`💀 SCRAPER DEAD`** alert to `#nba-alerts` with source + days-dark +
   last-seen. Gated on `games_today` so the off-season never false-alarms
   (verified: off-season no-game-day run is silent).

3. **Four source configs were erroring every run.** `teamrankings_team_stats`,
   `hashtagbasketball_dvp`, `covers_referee_stats`, `nba_tracking_stats` used
   `date_column: scrape_date` (nonexistent column) → ERROR every run →
   effectively unmonitored. Fixed to `game_date`. **This revealed
   `covers_referee_stats` was also silently dead since 2026-03-30**, hidden
   behind the error.

### Validation
- In-season dry-run (`--date 2026-04-05`): VSiN flags DEAD ("8 days dark, last
  seen 2026-03-28") and covers DEAD ("6 days dark") — escalation message renders
  correctly.
- Off-season dry-run (`--skip-game-check`, no games today): all HEALTHY, no
  alert. No summer spam.
- `dknetwork` correctly reads HEALTHY (never-had-data ≠ dead).

### Deliberately NOT done
Full `expected_outputs` / `gap_detector` wiring for external scrapers was
considered and declined — for zero-pick-impact shadow sources the DEAD
escalation gives the detection value without dragging them into the
auto-backfill/FAILED-row machinery. Revisit only if an external source becomes
pick-load-bearing.

---

## Files changed

| File | Change |
|------|--------|
| `bin/monitoring/data_source_health_canary.py` | DEAD escalation + 60-day last-seen fix + games_today gate + fixed 4 `scrape_date`→`game_date` configs + added dknetwork |
| `ml/signals/supplemental_data.py` | sharp-money query UNIONs dknetwork + vsin |
| `bin/deploy/deploy_dknetwork_scheduler.sh` | NEW — ready-to-run scheduler (not deployed) |

**Commits:** `10fda5d5` (fix: canary), `258c9d75` (feat: DK wiring)

---

## System state
- Off-season, halt active, no live picks until ~Oct 2026.
- Branch main clean and pushed; both affected services deployed SUCCESS.
- Scraper silent-death monitoring is materially better than at start of session.
