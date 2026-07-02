# Session Handoff — 2026-05-13 — MLB roadmap Session 1 startup

**Prior session (2026-05-12):** 26 agents reviewed the MLB UNDER shadow rollout plan. Produced a 6-doc project at `docs/08-projects/current/mlb-comprehensive-review-2026-05-12/`. No code shipped. User picked the multi-session roadmap path.

**This handoff:** Brief the new session to execute Session 1 of `06-MULTI-SESSION-ROADMAP.md`.

## Read these in order (15 min)

1. **`docs/08-projects/current/mlb-comprehensive-review-2026-05-12/00-OVERVIEW.md`** — context + which docs to trust
2. **`docs/08-projects/current/mlb-comprehensive-review-2026-05-12/06-MULTI-SESSION-ROADMAP.md`** — the canonical multi-session plan. Session 1 is the entry point.
3. Skim **`04-FINAL-REVIEW.md`** Agent D section — explains the load-bearing A1 vapor finding

## Load-bearing context the docs assume you know

- **The original shadow rollout plan is DEAD.** Don't ship the 45-day shadow with N=60/HR≥56% gate. Wilson LB on that gate is 43.4% (Lane 1).
- **A1 (lineup features wire-up) is VAPOR.** Agent D's BQ check showed 5 of 6 features are 0.0 constants in production. DO NOT just add them to the V2 feature contract — they'll ship placeholders.
- **MLB OVER ships 60.3% HR live.** Don't disturb the cash cow. A2 changes are reversible and well-evidenced.
- **NBA is dormant.** Playoffs + auto-halt active since ~Mar 28. Don't touch NBA models.
- **MLB UNDER stays disabled.** `MLB_UNDER_ENABLED=false`. Phase C in week ~4 decides what happens next.

## Session 1 — Concrete task list (3-4h)

In order:

### Task 1 — X2 verification (15 min) — DO FIRST

Verify Agent D's finding that A1 lineup features are vapor. If contradicted, the plan needs revisiting. Query:

```sql
SELECT
  COUNT(*) AS total_rows,
  COUNTIF(f25_bottom_up_k_expected != 0) AS f25_nonzero,
  COUNTIF(f26_lineup_k_vs_hand != 0) AS f26_nonzero,
  COUNTIF(f27_platoon_advantage != 0) AS f27_nonzero,
  COUNTIF(f33_lineup_weak_spots != 0) AS f33_nonzero,
  COUNTIF(f34_matchup_edge != 0) AS f34_nonzero
FROM `nba-props-platform.mlb_precompute.pitcher_ml_features`
WHERE game_date >= '2026-04-01';
```

Expected if Agent D was correct: total ~976, f25 ~119, f26/f27/f33/f34 = 0. If different, STOP and surface to user before continuing.

### Task 2 — X1 preliminary lineup pipeline diagnosis (45 min)

Don't fix yet — just scope. Check:
- Does `lineup_k_analysis_processor` have a Cloud Scheduler entry? (`gcloud scheduler jobs list --project=nba-props-platform | grep -i lineup`)
- Last successful run?
- Row counts: `SELECT COUNT(*) FROM mlb_precompute.lineup_k_analysis` (Lane 16 reported 0)
- Lineup coverage: `SELECT game_date, COUNT(*) AS rows, COUNT(DISTINCT team_abbr) AS teams FROM mlb_raw.mlb_lineup_batters WHERE game_date >= CURRENT_DATE() - 14 GROUP BY 1 ORDER BY 1 DESC`

Report findings as a brief note. Don't attempt to fix.

### Task 3 — A3 weather scheduler + 2nd pre-game export (2-3h) — SHIP THIS

The one real bug fix this session. Two components:

**Component A — Schedule weather scraper:**
- File: `bin/schedulers/setup_mlb_schedulers.sh`
- Add: `mlb-weather-pregame` job. Reasonable time: ~11:30 UTC (after morning props scrape, before midday).
- Scraper already exists at `scrapers/mlb/external/mlb_weather.py`
- Verify the scheduler job actually fires: deploy + manual `gcloud scheduler jobs run` test
- Confirm rows land: `SELECT COUNT(*) FROM mlb_raw.mlb_weather WHERE game_date = CURRENT_DATE()` should be >0 after one run

**Component B — Wire weather to predictions:**
- File: `predictions/mlb/supplemental_loader.py:230` (search for `_load_weather`)
- Currently returns `{}` because `mlb_raw.mlb_weather` is empty. Once Component A is shipping rows, the existing code should populate `temperature`, `is_dome`, `k_weather_factor` on the supplemental dict.
- Verify: `WeatherColdUnderSignal` and `ColdWeatherKOverSignal` start firing on appropriate games.

**Component C — 2nd pre-game export (~16:30 UTC):**
- File: `bin/schedulers/setup_mlb_schedulers.sh`
- Add: `mlb-best-bets-generate-late` job at `30 16 * 3-10 *` (16:30 UTC, March-October)
- This second export catches late scratches (currently scratched pitchers reach the public site until next-morning grading)
- Verify: a published pick gets dropped if pitcher is scratched between 12:55 and 16:30 UTC

**Test plan:**
- Manually fire each scheduler once
- Verify `mlb_raw.mlb_weather` has next-day rows
- Verify `signal_best_bets_picks` has no rows for scratched pitchers as of next-day check
- Roll back via `gcloud scheduler jobs pause` if anything misbehaves

### Task 4 — Session 1 handoff (15 min)

Write `docs/09-handoff/2026-05-13-mlb-roadmap-session-2.md` capturing:
- X2 result (A1 vapor confirmed / contradicted)
- X1 diagnosis findings (one paragraph)
- What A3 components shipped
- Any deferred items
- Session 2 entry conditions

## What this session does NOT do

- A2 (OVER ranking) — Session 2
- A5 (CLV foundation) — Session 3
- B1 (early-warning) — Session 4
- A4 (Poisson WF) — Session 3
- Anything UNDER-related — Phase C decision in Session 6
- Any model retrain or deploy — first model touchpoint is Session 5
- Lineup pipeline FIX — Session 1 only diagnoses, doesn't fix

## Stop conditions for this session

ABORT and surface to user if:
- X2 contradicts Agent D's finding → A1 may not be vapor → re-evaluate plan
- X1 reveals `lineup_k_analysis` IS scheduled and producing rows somewhere we missed → A1 may be salvageable cheaply
- A3 component A scheduler can't deploy (auth, permissions) → fix root cause, don't bypass
- Any A3 deploy causes `signal_best_bets_picks` writes to fail → pause schedulers immediately

## Useful pointers

- Auto-deploy is live on push to main. Code MUST be deployable when committed.
- Schema migrations should land BEFORE code that depends on them (Lane 3 finding).
- For Cloud Scheduler changes: verify they take effect with `gcloud scheduler jobs describe NAME --location=us-west2`.
- Reminders: `bin/schedulers/setup_mlb_reminders.sh` exists separately — Session 1 only touches `setup_mlb_schedulers.sh`.

## Calendar context

Today is 2026-05-13 (mid-week). MLB regular season in stride. NBA in playoffs (dormant). OVER pipeline is profitable; protect it.

## Suggested session opening

```
/clear
Read docs/09-handoff/2026-05-13-mlb-roadmap-session-1.md.
Execute Session 1 as described. Start with Task 1 (X2 verification).
```

The handoff and the roadmap together should be enough context to run Session 1 self-contained.
