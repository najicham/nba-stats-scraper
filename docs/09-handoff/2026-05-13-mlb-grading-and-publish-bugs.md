# Session Handoff — 2026-05-13 — MLB grading + publish bugs

**Reported by user end of Session 5:** "Yesterday's picks have one not graded and it is not showing today's picks."

This handoff documents two independent production bugs surfaced by the user's spot-check. Both diagnosed end-to-end with high confidence; neither fixed in this session (each touches the auto-deployed grading/publishing flow and warrants review before ship).

## TL;DR

1. **`all.json.today` shows YESTERDAY's picks** (5/12 instead of 5/13). Frontend renders yesterday's row as today's section. Caused by the grading service reading the wrong key from the Pub/Sub envelope (`target_date` vs `game_date`), defaulting to `'yesterday'`, then re-exporting `all.json` with that date. The 1:00 PM ET `phase6_export` scheduler corrects it; the 4:30 PM ET late re-fire stomps it back with no follow-up to fix.
2. **Matt Waldron pick (2026-05-12, OVER 3.5, edge 1.3) never graded.** ~~He was scratched.~~ He pitched as the bulk pitcher behind opener Bradgley Rodriguez (3 K in 2.2-3 IP — actual LOSS vs OVER 3.5). `pitcher_game_summary` only ingests the "official starter" (the opener Rodriguez), so Waldron has no actuals row and grading silently drops him. Frontend displays `result=null` permanently. Bonus issue: `mlb_raw.mlb_pitcher_stats` has 0 rows for ALL of 2026-05-12 — the aggregated-stats scraper failed yesterday.

Plus a third smaller integrity finding: `signal_best_bets_picks` has the wrong opponent (`CHC`) for Waldron — `pitcher_strikeouts.opponent_team_abbr=MIL` was correct. Likely a stale read between the two writes. Diagnose before fixing Issue 2 — same window of staleness may explain both.

## Issue 1 — `all.json.today` shows yesterday

### Symptom

- `gs://nba-props-platform-api/v1/mlb/best-bets/all.json` (generated 2026-05-13 20:31:18 UTC) has:
  - `"date": "2026-05-12"`
  - `"today": [5 picks all from 2026-05-12]` — Waldron, Springs, Rogers, Fedde, Gore
- Today's 3 actual picks (Dylan Cease, Noah Schultz, Kumar Rocker for 2026-05-13) are present in BQ `signal_best_bets_picks` (created 2026-05-13 20:30:26 UTC) and in the per-date file `v1/mlb/best-bets/2026-05-13.json` (generated 2026-05-13 18:00:49 UTC by the 1:00 PM ET `mlb-pitcher-export-pregame` Pub/Sub fire) — but not in `all.json.today`.

### Root cause

**Two collaborating defects:**

**A — Grading service reads the wrong field from the Pub/Sub envelope.** The MLB prediction worker's `/best-bets` endpoint publishes a `mlb-phase5-predictions-complete` Pub/Sub event with payload:

```python
# predictions/mlb/worker.py:967
message = {
    'game_date': game_date,                      # today's date
    'predictions_count': prediction_count,
    'timestamp': datetime.utcnow().isoformat(),
    'service': 'mlb-prediction-worker'
}
```

The `mlb-phase6-grading` Cloud Run service is subscribed to this topic (`mlb-phase6-grading-sub`). Its `/process` handler reads:

```python
# data_processors/grading/mlb/main_mlb_grading_service.py:89
target_date = message.get('target_date', 'yesterday')
game_date = _resolve_date(target_date)
```

The published payload has no `target_date` key, so it defaults to `'yesterday'`. The grading runs against `game_date=2026-05-12` (yesterday — actually correct for grading the previous day's games), and then `_re_export_all_json(game_date)` is invoked with that yesterday date.

**B — `_re_export_all_json` conflates "the date being graded" with "the date `all.json` should center on".** Implementation:

```python
# data_processors/grading/mlb/main_mlb_grading_service.py:299
def _re_export_all_json(game_date: str) -> dict:
    exporter = MlbBestBetsExporter()
    path = exporter.export_all(today=game_date)
```

`export_all(today=...)` then builds the JSON with `'date': today` and filters today's picks as `r['game_date'] == today`. With `today='2026-05-12'`, the resulting `all.json` shows 2026-05-12 as the live day.

### Timeline of today (2026-05-13, all UTC)

| Time | Event | `all.json.date` after |
|---|---|---|
| 14:45 ET / ~18:45 | `mlb-pitcher-export-morning` Pub/Sub → `phase6_export` CF → `export_all(today=today)` | **2026-05-13** ✓ (presumed; not verified) |
| 12:55 ET / 16:55 | `mlb-best-bets-generate` HTTP → worker `/best-bets` → publishes to `mlb-phase5-predictions-complete` → `mlb-phase6-grading` `/process` → grades 5/12 → `_re_export_all_json('2026-05-12')` | **2026-05-12** ✗ |
| 13:00 ET / 17:00 | `mlb-pitcher-export-pregame` Pub/Sub → `phase6_export` CF → `export_all(today=today)` | **2026-05-13** ✓ (generated_at: `2026-05-13T18:00:49Z` matches this) |
| 16:30 ET / 20:30 | `mlb-best-bets-generate-late` HTTP → worker `/best-bets` → publishes → grading `/process` → `_re_export_all_json('2026-05-12')` | **2026-05-12** ✗ (generated_at: `2026-05-13T20:31:18Z` matches this — currently in prod) |
| (no further trigger) | | Stays at 2026-05-12 until tomorrow morning |

So the per-date file `2026-05-13.json` is correct (last write 18:00:49 UTC by the 1 PM Pub/Sub trigger; the 4:30 PM late fire writes BQ but does NOT publish per-date JSON). The `all.json.today` field is wrong from 20:31 UTC onward until tomorrow.

### Fix options (pick one or combine)

**Option 1 (smallest patch, recommended): Make `_re_export_all_json` always pass today's actual date.**

```python
# data_processors/grading/mlb/main_mlb_grading_service.py:299
def _re_export_all_json(game_date: str) -> dict:
    """game_date is the date being GRADED (yesterday). all.json's 'today'
    field should still be today's actual calendar date — what the frontend
    displays as the live day."""
    try:
        from data_processors.publishing.mlb.mlb_best_bets_exporter import MlbBestBetsExporter
        from datetime import datetime, timezone
        exporter = MlbBestBetsExporter()
        today_str = datetime.now(timezone.utc).date().isoformat()
        path = exporter.export_all(today=today_str)
        logger.info(f"Post-grading: re-exported all.json (graded={game_date}, today={today_str}) to {path}")
        return {'status': 'ok', 'path': path}
    ...
```

Risk: low. `export_all` already queries the whole season; only the `'date'` field and `today_rows` filter change. Verified by reading `data_processors/publishing/mlb/mlb_best_bets_exporter.py:438-471`.

**Option 2: Unsubscribe `mlb-phase6-grading-sub` from `mlb-phase5-predictions-complete`.** Let grading run only on its daily 10 AM ET cron (`mlb-grading-daily`). Eliminates the every-fire grading invocation entirely. Risk: medium — need to check whether anything else depends on the post-predictions grading trigger. Suspect not (grading runs against yesterday; doesn't need today's predictions to complete).

**Option 3: Add a follow-up `mlb-phase6-export` Pub/Sub trigger after the 4:30 PM ET late re-fire.** Create `mlb-pitcher-export-late` scheduler at 16:35 ET that publishes to `nba-phase6-export-trigger` with `{"sport":"mlb","export_types":["pitchers","best-bets"],"target_date":"today"}`. Symptomatic patch — doesn't fix the underlying conflation, but does ensure the per-date JSON is refreshed after late changes (which we DO need for scratches; see also Issue 2).

**Recommendation: ship Option 1 (1-line fix) AND Option 3 (1 new scheduler).** Option 1 stops the stomping; Option 3 ensures the per-date JSON reflects late lineup changes.

### Verification commands

```bash
# Confirm bug in current state
gsutil cat gs://nba-props-platform-api/v1/mlb/best-bets/all.json | python3 -c "
import json, sys; d=json.load(sys.stdin)
print('date:', d['date'])
print('today picks:', [p['player'] for p in d['today']])"
# Expected today (after fix): 2026-05-13, [Dylan Cease, Noah Schultz, Kumar Rocker]
# Current state:               2026-05-12, [Matt Waldron, Jeffrey Springs, Trevor Rogers, Erick Fedde, MacKenzie Gore]

# Manual fix tonight (no code change) — re-publish all.json via Pub/Sub
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"sport":"mlb","export_types":["pitchers","best-bets"],"target_date":"today"}'
```

## Issue 2 — Matt Waldron ungraded (opener+bulk pattern; NOT scratched)

### Symptom

- `signal_best_bets_picks` has Waldron pick: 2026-05-12, OVER 3.5, edge 1.3, system `mlb_v8_s456_v3final_away_5picks`, opponent `CHC` (wrong — see Issue 3 below).
- `pitcher_strikeouts` has prediction: 4.81 K predicted, line 3.5, opponent MIL (correct), game_pk 823790.
- `prediction_accuracy` has NO row for Waldron 2026-05-12 (neither graded nor voided).
- `pitcher_game_summary` (analytics) for game 823790 lists only **Bradgley Rodriguez (SD)** and **Brandon Sproat (MIL)** — no Waldron row.
- Schedule's `away_probable_pitcher_name = 'Bradgley Rodriguez'` for game 823790.

### Actual reality (user-confirmed)

**Waldron DID pitch — user reports 2.2 IP. Confirmed by raw per-pitch data:**

```sql
SELECT pitcher_name, COUNT(*) as n_pitches, COUNT(DISTINCT inning) as innings
FROM `nba-props-platform.mlb_raw.mlb_game_feed_pitches`
WHERE game_date = '2026-05-12' AND game_pk = 823790
GROUP BY 1 ORDER BY n_pitches DESC;
```

Returns 9 pitchers including Waldron at 59 pitches across innings 2-4. **Bradgley Rodriguez threw 11 pitches in 1 inning — he was the opener, not the starter.** Waldron came in as the bulk pitcher. Strikeouts (from `at_bat_event='Strikeout'`): **3 K in 17 batters faced**. Pick was OVER 3.5 → actual 3 → **LOSS** (not VOID).

### Root cause

This is the **opener + bulk pitcher** pattern. SD's strategy was: Rodriguez opens for 1 inning, Waldron pitches behind him for the bulk. Vegas correctly lined Waldron's K total at 3.5 because oddsmakers track which pitcher will handle the workload. But our analytics/grading pipeline tags Rodriguez as the starter (matches `mlb_schedule.away_probable_pitcher_name`), and `pitcher_game_summary` excludes the bulk pitcher.

The grading flow:

1. **Prediction step:** `pitcher_strikeouts` row written with Waldron (correct — best-bets generator knows Waldron is the lined pitcher).
2. **Game step:** Rodriguez pitches 1 IP (opener), Waldron pitches ~2.2-3 IP, then relievers finish.
3. **Analytics step:** `pitcher_game_summary` ingests only the "official starter" (Rodriguez). Waldron is excluded — most likely by an `is_starter=TRUE` filter in `mlb_pitcher_game_summary_processor` (need to read source to confirm). The schema's `is_starter` column hints at this.
4. **Grading step:** `MlbPredictionGradingProcessor` joins on `pitcher_game_summary`. Waldron has no row → skipped → no `prediction_accuracy` insert.
5. **Frontend:** `_map_to_frontend_pick` handles `is_voided=TRUE` but NOT "no row at all" — Waldron displays as `result=None` permanently.

### Bonus issue (related, surfaced during investigation)

**`mlb_raw.mlb_pitcher_stats` has ZERO rows for 2026-05-12** — all pitchers, all teams. The aggregated-stats scraper failed yesterday. The per-pitch table `mlb_game_feed_pitches` IS populated (271 pitches for game 823790), so per-pitch ingestion ran fine; the aggregated-stats path is broken. This is a separate data integrity issue but compounds the grading problem: even a fix that sources from `mlb_pitcher_stats` instead of `pitcher_game_summary` would still miss yesterday because the table is empty. Investigate `mlb_pitcher_stats` scraper logs for 2026-05-12.

### Fix options

**Option 1 (recommended, durable): Source grading actuals from `mlb_game_feed_pitches`.** Aggregate per-pitch data into `actual_strikeouts` for any pitcher who threw in the game, regardless of `is_starter`. Query pattern:

```sql
SELECT pitcher_lookup, game_date, game_pk,
       COUNTIF(is_at_bat_end AND LOWER(at_bat_event) LIKE '%strikeout%') AS actual_strikeouts,
       -- IP computed from outs in innings pitched; need per-inning out tracking
       ...
FROM `nba-props-platform.mlb_raw.mlb_game_feed_pitches`
WHERE game_date = '2026-05-12'
GROUP BY 1,2,3
```

Replaces the current `pitcher_game_summary` join. Captures bulk pitchers, openers, and relievers correctly. Risk: medium — `mlb_game_feed_pitches` may be late-arriving for some games (live ingestion); add a "game is final" check.

**Option 2: Include all pitchers (not just starters) in `pitcher_game_summary`.** Modify the analytics processor to ingest every pitcher who threw, even if `is_starter=FALSE`. Downstream features that depend on per-pitcher rolling K averages will need to disambiguate by `is_starter` flag. Risk: medium — changes feature surface area for the ML model. Might also fix other unrelated lined-bulk-pitcher bugs.

**Option 3 (smallest patch, today): Insert a Waldron grading row tonight.** Mark his pick as a LOSS (3 K < 3.5 line):

```sql
INSERT INTO `nba-props-platform.mlb_predictions.prediction_accuracy` (
  pitcher_lookup, game_pk, game_date, system_id, team_abbr, opponent_team_abbr,
  predicted_strikeouts, recommendation, line_value, edge,
  actual_strikeouts, prediction_correct, is_voided, graded_at
)
VALUES (
  'matt_waldron', 823790, '2026-05-12', 'mlb_v8_s456_v3final_away_5picks',
  'SD', 'MIL', 4.81, 'OVER', 3.5, 1.3,
  3, FALSE, FALSE, CURRENT_TIMESTAMP()
);
```

Verify schema NOT NULL columns before running. Does not prevent recurrence.

**Option 4: Detect bulk-pitcher pattern at /best-bets time and refuse to publish.** Heuristic: if `pitcher_lookup` does NOT match `mlb_schedule.{away,home}_probable_pitcher_name` (with name normalization), flag the pick as `requires_lineup_confirmation`. Defer publishing until confirmed. Avoids the grading problem by avoiding the unconfirmed pick. Risk: low blast radius but might suppress legitimate picks during the morning gap before lineup release.

**Recommendation:**
- **Tonight:** Option 3 (one-row manual insert, unblocks user's pending-state complaint).
- **This week:** Option 1 (durable grading fix using `mlb_game_feed_pitches`).
- **Investigate separately:** Why `mlb_pitcher_stats` had 0 rows for 2026-05-12.

## Issue 3 — opponent mismatch between `pitcher_strikeouts` and `signal_best_bets_picks`

For Matt Waldron 2026-05-12:
- `pitcher_strikeouts.opponent_team_abbr = 'MIL'` ✓ (matches schedule for game_pk 823790)
- `signal_best_bets_picks.opponent_team_abbr = 'CHC'` ✗

This is its own data integrity issue. Both rows are written by the worker `/best-bets` flow (predictions, then best-bets exporter). The opponent gets recomputed somewhere in `ml/signals/mlb/best_bets_exporter.py` — likely a stale schedule cache or a wrong join. Worth a quick code read before fixing Issue 2 because it may indicate a broader stale-read pattern.

Quick grep starting point:
```bash
grep -nI "opponent_team_abbr" ml/signals/mlb/best_bets_exporter.py
grep -nI "opponent_team_abbr" predictions/mlb/pitcher_loader.py
```

## Suggested next-session plan

1. **(15 min) Manual fix tonight:** publish to `nba-phase6-export-trigger` with `{"sport":"mlb","export_types":["pitchers","best-bets"],"target_date":"today"}` to fix `all.json.today` for tonight's site. (Optional: also insert Waldron void row.)
2. **(45 min) Issue 1 fix:** patch `_re_export_all_json` per Option 1. Add `mlb-pitcher-export-late` 16:35 ET scheduler per Option 3.
3. **(60 min) Issue 2 fix:** read `MlbPredictionGradingProcessor`, add scratch detection per Option 1. Add unit test for the no-actuals-game-final case.
4. **(30 min) Issue 3 investigation:** root-cause the opponent mismatch in best_bets_exporter. Fix or file separately.

Total estimated effort: 2.5h. Defer Session 6 (UNDER decision + E2 NBA-port) until these ship — Issue 1 in particular is user-visible site breakage.

## Calendar context

Today is 2026-05-13. NBA in playoffs (halted). MLB regular season mid-stride.

## Suggested session opening

```
/clear
Read docs/09-handoff/2026-05-13-mlb-grading-and-publish-bugs.md.
Start with the 15-minute manual fix to unstick all.json, then patch
_re_export_all_json (Issue 1 Option 1). Defer Issue 2 + 3 until after that
verifies clean.
```
