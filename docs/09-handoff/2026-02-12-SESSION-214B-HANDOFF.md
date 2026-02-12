# Session 214B Handoff - Remaining GCS Live Update Issues

**Date:** 2026-02-12
**Session:** 214 (continued)
**Status:** Partially complete — 2 of 5 endpoints fixed, 3 awaiting upstream pipeline

## Current State

| Endpoint | Status | Issue |
|----------|--------|-------|
| Live Grading | ✅ FIXED | 89 correct, 98 incorrect. Was 141 "graded" before. |
| Tonight game_status | ✅ FIXED | All 14 games show "final" |
| Tonight scores | ❌ Upstream | `nbac_schedule` has NULL score columns for Feb 11. Feb 10 has scores. Scraper hasn't refreshed. |
| Picks actuals | ❌ Upstream | `player_game_summary` has 0 records for Feb 11. Phase 3 hasn't run. |
| Best Bets | ⚠️ JUST FIXED | Was 0 picks (regression). Fixed date comparison to use PT timezone. Re-export triggered. |

## What Happened

### Best-Bets Regression (fixed just now)
The post-game re-export fired for `target_date=2026-02-11` after midnight UTC (Feb 12). The best-bets exporter used `datetime.now().date()` (UTC) to decide which table to query:
- `target (Feb 11) >= today (Feb 12 UTC)` → FALSE → historical branch
- Historical branch queries `prediction_accuracy` → 0 records (grading hasn't run)
- Overwrote file with 0 picks

**Fix committed:** `best_bets_exporter.py` now uses PT with 1 AM cutover for the date comparison, matching the live-export game-day boundary. Re-export published to `nba-phase6-export-trigger`.

### Upstream Pipeline Not Yet Run
The morning pipeline (~6 AM ET) processes raw game data through Phase 2→3→4. Until it runs:
- `player_game_summary` has no Feb 11 data → picks/best-bets can't show actuals
- `nbac_schedule` scores still NULL → tonight can't show scores
- `prediction_accuracy` has no Feb 11 data → grading incomplete

## Morning Session Tasks

### 1. Verify pipeline populated Feb 11 data
```bash
# Check player_game_summary
bq query --nouse_legacy_sql "SELECT COUNT(*) FROM nba_analytics.player_game_summary WHERE game_date = '2026-02-11'"

# Check nbac_schedule scores
bq query --nouse_legacy_sql "SELECT home_team_score, away_team_score, home_team_tricode FROM nba_raw.nbac_schedule WHERE game_date = '2026-02-11' LIMIT 3"

# Check grading
bq query --nouse_legacy_sql "SELECT COUNT(*) FROM nba_predictions.prediction_accuracy WHERE game_date = '2026-02-11' AND system_id = 'catboost_v9'"
```

### 2. Trigger re-export for Feb 11 (after pipeline completes)
```bash
PYTHONPATH=. python -c "
from google.cloud import pubsub_v1; import json
publisher = pubsub_v1.PublisherClient()
topic = publisher.topic_path('nba-props-platform', 'nba-phase6-export-trigger')
msg = {'export_types': ['best-bets', 'subset-picks', 'season-subsets', 'tonight'], 'target_date': '2026-02-11', 'trigger_source': 'manual-post-pipeline', 'update_latest': True}
publisher.publish(topic, json.dumps(msg).encode('utf-8'))
print('Published')
"
```

### 3. Verify JSON files have actuals
```bash
gsutil cat gs://nba-props-platform-api/v1/picks/2026-02-11.json | python3 -c "
import json, sys; data = json.load(sys.stdin)
total = sum(1 for mg in data['model_groups'] for s in mg['subsets'] for p in s['picks'])
actual = sum(1 for mg in data['model_groups'] for s in mg['subsets'] for p in s['picks'] if p.get('actual') is not None)
print(f'Picks: {actual}/{total} have actuals')
"

gsutil cat gs://nba-props-platform-api/v1/best-bets/latest.json | python3 -c "
import json, sys; data = json.load(sys.stdin)
print(f'Total picks: {data.get(\"total_picks\")}, game_date: {data.get(\"game_date\")}')
for p in data.get('picks', [])[:3]:
    print(f'  {p.get(\"player_full_name\")}: result={p.get(\"result\")} actual={p.get(\"actual\")}')
"
```

### 4. CRITICAL: Add live-export to Cloud Build auto-deploy
The `live-export` Cloud Function has NO Cloud Build trigger. It's the only function without one. This caused the entire session's deployment issues.

**Current state:** gen1, HTTP-triggered, `--allow-unauthenticated`, `processor-sa` service account
**Other functions:** gen2, Pub/Sub-triggered, `--no-allow-unauthenticated`, default compute SA

**Options:**
1. Convert to gen2 + add trigger (cleanest, update scheduler auth to OIDC)
2. Create custom cloudbuild yaml preserving gen1 settings
3. Add to existing `cloudbuild-functions.yaml` with `_TRIGGER_TYPE: http`

**Deploy script (for manual deploys until auto-deploy is set up):**
```bash
./bin/deploy/deploy_live_export.sh --function-only
```

### 5. Investigate nbac_schedule score population
The `nbac_schedule` table has `game_status=3` for Feb 11 games but `home_team_score=NULL`. Feb 10 has scores. Either:
- The schedule scraper ran and updated status but not scores (bug in scraper)
- The scraper hasn't re-run since games ended (timing issue)

Check when the scraper last ran and whether it populates scores on the same pass as game_status.

## Commits This Session (4 total)
```
1391cdb0 feat: Fix GCS JSON files to update with game results post-game (Session 214)
c7df6eb1 fix: Add shared/clients and firestore dep to live-export deploy (Session 214)
0a8912ab feat: Switch live-export to Pacific time with 1 AM cutover + frontend API doc (Session 214)
4ba56250 fix: Best-bets table selection uses PT game-day boundary, not UTC (Session 214)
```

## Frontend API Doc
Complete reference at: `docs/08-projects/current/session-214-gcs-live-updates/FRONTEND-API-CHANGES.md`

---

**Session paused:** 2026-02-12 ~10:30 PM PT
