# Session 490 Handoff — Multi-Sport Frontend + Schema Review

**Date:** 2026-03-26
**Status:** Implementation complete + schema review done. Ready for Opening Day (Mar 27).

---

## What Was Done This Session

### 1. Full multi-sport implementation shipped

**Backend** (`nba-stats-scraper`, commits `eb571e04` + `203b1185`):

- **`mlb_best_bets_exporter.py`** — Added `export_all()` + 4 helpers that generate
  `v1/mlb/best-bets/all.json` in the `BestBetsAllResponse` shape (today picks, record
  windows, streak, 8-week history). Mapped from `pitcher_strikeouts` BQ → frontend schema.
- **`phase6_export/main.py`** — `sport:"mlb"` Pub/Sub message routes to MLB exporter,
  bypasses NBA analytics/prediction validation checks entirely.
- **Cloud Scheduler** `mlb-daily-best-bets-publish` created in `us-central1`:
  `0 14 * 3-10 *` America/New_York (2 PM ET, March–October).

**Frontend** (`props-web`, commit `9cd4a94`):

- `Sport = "nba" | "mlb"` type + `sport?` field on `BestBetsPick`
- `fetchBestBetsAll(sport)` routes to `mlb/best-bets/all.json` for MLB
- `K → "k"` stat label in BetCard + TodayPicksTable (renders as `O 6.5 k`)
- `🏀 NBA | ⚾ MLB` pill tabs on `/best-bets` — switches sport, resets + refetches
- No-op `onPlayerClick` for MLB (no pitcher profiles)
- Proxy TTLs: `mlb/best-bets` → 5 min, `mlb/results` → 24h

### 2. Schema review — everything verified

Reviewed `mlb_predictions.pitcher_strikeouts` actual BQ schema. Key findings:

| Field | Status | Note |
|-------|--------|------|
| `pitcher_lookup` | ✅ EXISTS | player_lookup in frontend |
| `pitcher_name` | ✅ EXISTS | player in frontend |
| `team_abbr` | ✅ EXISTS | |
| `opponent_team_abbr` | ✅ EXISTS | |
| `is_home` | ✅ EXISTS | BOOLEAN |
| `strikeouts_line` | ✅ EXISTS | FLOAT |
| `recommendation` | ✅ EXISTS | 'OVER'/'UNDER'/'PASS'/'NO_LINE' |
| `edge` | ✅ EXISTS | predicted_strikeouts - strikeouts_line |
| `confidence` | ✅ EXISTS FLOAT, **0-100 scale** | base=75, typical=75-95 |
| `is_correct` | ✅ EXISTS | BOOLEAN, null until graded |
| `actual_strikeouts` | ✅ EXISTS | INTEGER, null until graded |
| `game_time` | ❌ NOT IN TABLE | Schema mapping doc was wrong. Fixed: set to None. |
| `system_id` | ✅ EXISTS | model identifier, not used in export yet |

**`MIN_CONFIDENCE = 70` is correct** — confidence is 0-100 (base 75 + data quality adjustments).
The `03-SCHEMA-MAPPING.md` that showed `0.72` was wrong.

**`game_time` bug fixed** — removed from SELECT, hardcoded `None` in frontend pick.
Frontend handles `game_time: null` gracefully (hides time display).

### 3. Infrastructure review

| Component | Status |
|-----------|--------|
| Phase 6 CF (`phase6-export`) | ✅ DEPLOYED (build `12a5547e`) |
| MLB prediction worker Cloud Run | ✅ RUNNING |
| MLB schedulers (30 total, us-west2) | ✅ ALL ENABLED |
| `mlb-predictions-generate` | `0 13 * * *` UTC = 9 AM ET |
| `mlb-daily-best-bets-publish` (new) | `0 14 * 3-10 *` ET = 2 PM ET |
| `mlb-opening-day-check` | Fires 2 PM UTC March 27 (10 AM ET) |

**Timing is correct:** predictions at 9 AM ET → best-bets export at 2 PM ET (5h gap).

**Note:** New `mlb-daily-best-bets-publish` is in `us-central1`, all other MLB schedulers
are in `us-west2`. No functional impact, just an inconsistency.

---

## State Right Now

- **MLB predictions in BQ:** NONE (expected — Opening Day is March 27)
- **`v1/mlb/best-bets/all.json` in GCS:** Does NOT exist yet
- **Frontend `/best-bets`:** Shows `🏀 NBA | ⚾ MLB` tabs. MLB tab will fail or show empty
  until Opening Day predictions are published.

---

## Opening Day Checklist (March 27, 2026)

### Morning
```bash
# 1. Verify predictions generated (should happen ~9 AM ET automatically)
bq query --project_id=nba-props-platform --use_legacy_sql=false \
"SELECT COUNT(*) as picks, COUNTIF(recommendation='OVER') as overs,
        COUNTIF(recommendation='UNDER') as unders
 FROM mlb_predictions.pitcher_strikeouts
 WHERE game_date = '2026-03-27'"

# 2. Check data quality
bq query --project_id=nba-props-platform --use_legacy_sql=false \
"SELECT recommendation, COUNT(*) as n, AVG(confidence) as avg_conf,
        AVG(ABS(edge)) as avg_edge
 FROM mlb_predictions.pitcher_strikeouts
 WHERE game_date = '2026-03-27' AND recommendation IN ('OVER','UNDER')
   AND confidence >= 70 AND ABS(edge) >= 1.0
 GROUP BY 1"
```

### Afternoon (2 PM ET — scheduler fires automatically)
```bash
# If scheduler doesn't fire, trigger manually:
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"sport":"mlb","export_types":["best-bets"],"target_date":"2026-03-27"}'

# Verify GCS output
gcloud storage cat gs://nba-props-platform-api/v1/mlb/best-bets/all.json \
  --project=nba-props-platform | python3 -m json.tool | head -60
```

### Frontend verification
```
[ ] /best-bets shows 🏀 NBA | ⚾ MLB tabs
[ ] MLB tab shows picks in "O 6.5 k" format
[ ] Clicking pitcher name does NOT open player modal
[ ] Record shows 0-0 (no graded picks yet on Opening Day)
[ ] 🏀 NBA tab still works exactly as before
```

---

## Known Issues / Future Work

### Immediate
- **`game_time` is `null` for all MLB picks** — the `pitcher_strikeouts` table has no
  game_time column. Impact: no game time shown on pick cards. Enhancement: join with
  MLB schedule table to populate. Not blocking for launch.

- **MLB tab shows error until Opening Day** — `v1/mlb/best-bets/all.json` doesn't exist
  until first export runs. Proxy returns 404 → frontend shows error state. Acceptable for
  pre-season, but consider a static stub file if the error state is jarring.

### Future sessions
- MLB results export (next-morning grading refresh): needs `mlb-daily-results-publish`
  scheduler + `export_types: ["results","best-bets"]` for yesterday
- `game_time` from schedule join
- `SEASON_START = '2026-03-27'` is hardcoded — dynamic from min(game_date) in future
- MLB Tonight page (pitcher matchups, lineups)
- Sport switcher in global nav/header
- Additional MLB stats beyond strikeouts

---

## Quick Reference

```bash
# Check MLB predictions
bq query --project_id=nba-props-platform --use_legacy_sql=false \
"SELECT CAST(game_date AS STRING), COUNT(*) FROM mlb_predictions.pitcher_strikeouts
 WHERE game_date >= '2026-03-27' GROUP BY 1 ORDER BY 1 DESC LIMIT 5"

# Trigger MLB export
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"sport":"mlb","export_types":["best-bets"],"target_date":"today"}'

# Verify all.json
gcloud storage cat gs://nba-props-platform-api/v1/mlb/best-bets/all.json \
  --project=nba-props-platform | python3 -m json.tool | head -40

# Full schema
bq show --schema --format=prettyjson nba-props-platform:mlb_predictions.pitcher_strikeouts
```
