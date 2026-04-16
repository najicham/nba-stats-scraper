# Session 539 Handoff — MLB validation, BB-scheduler cold-start hypothesis

**Date:** 2026-04-16 (continuation of S537 + S538)
**Focus:** Full pipeline validation for today. Discovered that `mlb-best-bets-generate` also fails at scheduled time despite having OIDC — pointing at a cold-start + Cloud Run LB pattern, not auth. No code changes this session; diagnostic + manual recovery only.

> **Context docs:** read [Session 537](./2026-04-16-SESSION-537-HANDOFF.md) (the big one — MLB pipeline recovery, URL routing refactor, banner redesign) and [Session 538](./2026-04-16-SESSION-538-HANDOFF.md) (typographic cleanup on PitcherCard) for full context. This handoff only captures the new validation + scheduler diagnosis.

---

## TL;DR

Ran a full stage-by-stage validation of the MLB pipeline for 2026-04-16. **Everything is healthy now** (after manual recovery), and the "0 best bets today" is correct behavior (edge compression), not a pipeline failure.

**One new finding with implications for tomorrow:** `mlb-best-bets-generate` also failed at its 16:55 UTC fire, despite already having OIDC configured (I had only flagged `mlb-predictions-generate` in S537 for the OIDC fix). Same error signature — `URL_UNREACHABLE-UNREACHABLE_5xx. Original HTTP response code number = 500`, worker logs empty for the window. Manual curl to the same endpoint succeeds in 26 seconds. **This points at a cold-start + Cloud Run LB pattern, not auth.** Tomorrow morning is the test.

---

## Pipeline state at session end (2026-04-16 19:02 UTC)

| Stage | State | Detail |
|---|---|---|
| Predictions | ✅ 17 rows | `mlb_predictions.pitcher_strikeouts` for 2026-04-16; 14 with lines, 3 BLOCKED (NULL line) |
| Filter audit | ✅ 47 rows | 7 direction_filter (UNDER disabled), 5 whole_line_over, 3 away_edge_floor, 2 edge_floor, plus standard skip filters |
| Best bets | ✅ 0 picks (correct) | No pitcher cleared home 0.75 / away 1.25 floors |
| Leaderboard JSON | ✅ 13 tonight starters | `gs://.../mlb/pitchers/leaderboard.json`, generated 18:12 UTC |
| Best-bets JSON | ✅ 0 picks | `gs://.../mlb/best-bets/2026-04-16.json`, refreshed 19:02 UTC |
| Yesterday grading | ✅ 10-5 (66.7% HR) | Model is performing well; drought is gating, not quality |

**Closest miss today:** Luis Castillo OVER edge +1.15 (away), just 0.10 short of the 1.25 away floor.

---

## What I did this session (no code changes)

1. Ran a full cross-stage BQ audit (`pitcher_strikeouts`, `signal_best_bets_picks`, `best_bets_filter_audit`, `signal_health_daily`, `prediction_accuracy`).
2. Found: BB pipeline hadn't run today — `signal_best_bets_picks` + `best_bets_filter_audit` were empty.
3. Diagnosed: `mlb-best-bets-generate` scheduler failed at 16:55 UTC with `status.code: 13` / `URL_UNREACHABLE-UNREACHABLE_5xx`. Confirmed via `gcloud logging read` that zero logs reached `mlb-prediction-worker` during the 16:55 window — the 5xx came from Cloud Run's layer, not the app.
4. Verified scheduler HAS OIDC token configured correctly (`audience: https://mlb-prediction-worker-...`, `serviceAccountEmail: 756957797294-compute@...`). So auth isn't the issue.
5. Manual recovery: `curl -X POST https://mlb-prediction-worker-.../best-bets -d '{"game_date": "TODAY"}'` → HTTP 200, 17 predictions evaluated, 0 picks (correct), filter_audit populated with 47 rows. Took 25 seconds.
6. Re-triggered best-bets export via pubsub → `gs://.../mlb/best-bets/2026-04-16.json` refreshed at 19:02 UTC.

**No commits, no pushes, no code changes this session.**

---

## Scheduler failure pattern — the key open question

Both MLB schedulers hitting `mlb-prediction-worker` failed at their scheduled fires today:

| Scheduler | Scheduled fire | Status | OIDC | Manual curl same endpoint |
|---|---|---|---|---|
| `mlb-best-bets-generate` | 16:55 UTC | ❌ 5xx in <1s | ✅ configured | ✅ 200 in 26s |
| `mlb-predictions-generate` | 17:00 UTC | ❌ 5xx in <1s | ❌ missing (**fixed by me in S537**) | ✅ 200 in 19s |

Fact pattern:
- Both fail with the same error signature (`URL_UNREACHABLE-UNREACHABLE_5xx`)
- Both return 5xx in under a second
- Worker logs are completely empty for both failure windows (no cold-start, no request received)
- Manual curl always works, takes 19–26 seconds (cold start + ML inference)
- BB scheduler fires first (16:55) → worker is scaled to zero; predictions scheduler fires 5 min later (17:00) → worker still scaled to zero because BB scheduler's request never actually woke it

**Hypothesis:** Cloud Run's load balancer is returning 5xx on the first request to a scaled-to-zero instance, before cold start completes. The OIDC token may or may not be rejected during this race. Requests with identical config from curl succeed because the instance happens to be warm (from my earlier `/health` call seconds before) OR because the connection stays open long enough to ride the cold-start.

The OIDC I added to `mlb-predictions-generate` might help (authenticated requests get different Cloud Run handling), but the BB scheduler already has OIDC and still fails. So OIDC is necessary but probably not sufficient.

### Three potential fixes for tomorrow

Ranked by confidence:

1. **`gcloud run services update mlb-prediction-worker --min-instances=1`** (cleanest, ~$5–10/month). Worker never scales to zero → no cold start → no 5xx. Single-line fix. Reversible.
2. **Pre-warmer scheduler** firing `/health` at 16:54 UTC (60s before BB scheduler). Requires a new scheduler job; slightly less clean. Uses Cloud Scheduler cost but no Cloud Run cost.
3. **Tighter scheduler retry config** so the inevitable retry after 500 hits a warm instance. Currently `minBackoffDuration: 5s`, `maxDoublings: 5`. If first fire fails but retry succeeds, data still lands on time. But doesn't fix the root cause.

My recommendation: **option 1**. The mlb-prediction-worker serves ~2 real scheduled invocations per day plus grading reads; keeping 1 instance warm is almost nothing compared to the infrastructure reliability win.

---

## Incidental findings, lower priority

- **`mlb_umpire_assignments` scraper broken.** 3 errors today at 15:30 UTC: `AttributeError: 'function' object has no attribute 'get'` in `scrapers/mlb/mlbstatsapi/mlb_umpire_assignments.py:101`. Looks like `self.download_data` is a function, not a dict — likely a regression from a recent refactor. Umpire data feeds the `umpire_k_friendly` signal; signal still fires because the umpire table has historical data, but today's umpires won't be in it. Non-critical for today. Easy fix.
- **Walker Buehler SKIP with confidence 0.0** today. Model abstained. Likely feature missingness for him (first start of season?). Worth spot-checking his feature row if it persists.
- **Null pitcher name** on one COL prediction (Tomoyuki Sugano per the leaderboard JSON). Cosmetic — doesn't affect gating or predictions, just display. Likely a mismatch between prediction's `pitcher_lookup` and `player_full_name` in upstream.

---

## What the next session should do, in order

### Priority 1 — verify tomorrow's 16:55 + 17:00 UTC scheduler fires

```bash
# After 17:05 UTC tomorrow (2026-04-17):
gcloud scheduler jobs describe mlb-best-bets-generate --location=us-west2 --project=nba-props-platform --format="yaml(lastAttemptTime,status)"
gcloud scheduler jobs describe mlb-predictions-generate --location=us-west2 --project=nba-props-platform --format="yaml(lastAttemptTime,status)"

bq query --use_legacy_sql=false --format=pretty '
SELECT "preds" AS s, COUNT(*) n FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts` WHERE game_date = CURRENT_DATE()
UNION ALL SELECT "bb", COUNT(*) FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks` WHERE game_date = CURRENT_DATE()
UNION ALL SELECT "filter_audit", COUNT(*) FROM `nba-props-platform.mlb_predictions.best_bets_filter_audit` WHERE game_date = CURRENT_DATE()
'
```

Expected outcomes:
- **If both schedulers succeed (status codes 0):** The S537 OIDC fix alone solved it, and the cold-start theory was wrong. Close this line of investigation.
- **If `mlb-predictions-generate` succeeds but `mlb-best-bets-generate` still fails:** Confirms cold-start hypothesis (BB fires first against cold worker). Apply min-instances=1 fix.
- **If both still fail:** Deeper issue. Check worker revision health; check if any deploy from today's `deploy-phase6-export` build affected the worker revision.

### Priority 2 — apply `min-instances=1` if either scheduler still fails

```bash
gcloud run services update mlb-prediction-worker \
  --region=us-west2 --project=nba-props-platform \
  --min-instances=1
```

Monitor cost for a day. If it's trivial (should be, since the worker is already pretty lightweight), leave it. If surprisingly high, back off to a pre-warmer scheduler instead.

### Priority 3 — fix the `mlb_umpire_assignments` scraper

`scrapers/mlb/mlbstatsapi/mlb_umpire_assignments.py:101` — `self.download_data.get("dates", [])` fails because `download_data` is a function. Easy fix: either call it (`self.download_data()`) or fix the attribute name.

### Priority 4 — carried forward from S537

- Audit remaining 21 MLB schedulers for OIDC (defensive)
- Evaluate MLB UNDER enablement (needs 2024-2025 season replay first)
- Session 536 frontend TODOs (analytics, drilldown, XAxis)

---

## Useful one-liners

Full pipeline health (run anytime):
```bash
bq query --use_legacy_sql=false --format=pretty '
SELECT "preds" AS s, COUNT(*) n FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts` WHERE game_date = CURRENT_DATE()
UNION ALL SELECT "bb", COUNT(*) FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks` WHERE game_date = CURRENT_DATE()
UNION ALL SELECT "filter_audit", COUNT(*) FROM `nba-props-platform.mlb_predictions.best_bets_filter_audit` WHERE game_date = CURRENT_DATE()
UNION ALL SELECT "graded_yday", COUNT(*) FROM `nba-props-platform.mlb_predictions.prediction_accuracy` WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
'
```

Manual pipeline kick (both predictions + BB + filter audit):
```bash
curl -X POST https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app/best-bets \
  -H "Content-Type: application/json" -d '{"game_date": "TODAY"}'
```

Re-export GCS JSON artifacts:
```bash
gcloud pubsub topics publish nba-phase6-export-trigger --project=nba-props-platform \
  --message='{"sport":"mlb","export_types":["pitchers","best-bets"],"target_date":"today"}'
```

---

## Commit state at session end

- `nba-stats-scraper` main: `8202bb62` (S538 handoff). Nothing new.
- `props-web` main: `698af01` (PitcherCard type unification from S538). Nothing new.
- No code pushed this session.

---

## Key lesson

**"Scheduler failure with URL_UNREACHABLE-UNREACHABLE_5xx and zero worker logs = cold start, not auth."** Adding OIDC to a scheduler doesn't help if the Cloud Run load balancer is returning 5xx before the instance wakes. The tell: manual curl to the same endpoint with the same payload succeeds in 20+ seconds (cold-start + processing). If OIDC alone solved it, curl would fail too. Conversely, if curl succeeds, the endpoint + auth + payload are all fine, and the only remaining variable is **when** the request arrives (warm vs cold).

Test tomorrow settles it. If `mlb-predictions-generate` succeeds tomorrow with the S537 OIDC fix, auth mattered. If it still fails but curl works, it's cold-start.
