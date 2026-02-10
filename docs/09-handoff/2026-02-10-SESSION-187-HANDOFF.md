# Session 187 Handoff — Phase 2→3 Trigger Root Cause Fix, Data Gap Backfills, Grading Deploy

**Date:** 2026-02-10
**Previous:** Session 185 (deploy bug fixes, validation, postponed games cleanup)
**Focus:** Fix Phase 2→3 trigger (never firing), backfill data gaps, deploy stale grading service, model assessment

## What Was Done

### 1. Phase 2→3 Trigger Root Cause Fix (P0 CRITICAL)

Session 185 deployed a fix for the `NbacGambookProcessor` typo, but the trigger STILL never fired (`_triggered: False` on Feb 8 and Feb 9). Session 187 found the deeper root cause:

**Two problems:**

1. **EXPECTED_PROCESSORS had 6 entries but only 5 processors report daily.** `p2_bdl_box_scores` (BDL boxscores) and `p2_br_season_roster` (Basketball Reference rosters) never publish completion events for specific game dates. The trigger condition (`completed_count >= EXPECTED_PROCESSOR_COUNT`) was 5 >= 6, which never fires.

2. **3 processor class names missing from CLASS_TO_CONFIG_MAP.** `NbacPlayerBoxscoreProcessor`, `OddsApiGameLinesBatchProcessor`, and `OddsApiPropsBatchProcessor` were not in the explicit mapping. They fell through to raw class names, breaking monitoring/tracking.

**Fix (commit `b2e9e54b`):**
- Updated EXPECTED_PROCESSORS (both `orchestration_config.py` and Cloud Function fallback) to the 5 processors that actually report daily:
  - `p2_bigdataball_pbp` (BigDataBallPbpProcessor)
  - `p2_odds_game_lines` (OddsApiGameLinesBatchProcessor)
  - `p2_odds_player_props` (OddsApiPropsBatchProcessor)
  - `p2_nbacom_gamebook_pdf` (NbacGamebookProcessor)
  - `p2_nbacom_boxscores` (NbacPlayerBoxscoreProcessor)
- Added missing CLASS_TO_CONFIG_MAP entries for batch processors
- Removed non-ASCII `NbacGamébookProcessor` legacy entry
- Pre-commit validator passes clean (0 errors, 0 warnings)

**Deployment:** Cloud Build trigger `deploy-phase2-to-phase3-orchestrator` fired on push. All 8 Cloud Build triggers activated due to `shared/` change.

**Verification needed next session:** Check Firestore `phase2_completion` for Feb 10 — `_triggered` should now be `True`.

### 2. Grading Service Deployed (Was 4 Commits Behind)

`nba-grading-service` Cloud Run service was stale since Feb 8 (commit `9622c706`), missing:
- `1a903d38` fix: Disable multi-line predictions (dedup bug causes +2.0 UNDER bias, Session 170)
- `afa71700` fix: Recommendation direction validation, correlated subquery fix (Session 175)
- Two other Session 170 commits (avg_pvl signal, model_version filter)

Deployed manually to `b2e9e54b`. All smoke tests passed (deep health check, BigQuery writes, env vars).

**Note:** `phase5b-grading` Cloud Function was already up-to-date (auto-deployed via Cloud Build trigger).

### 3. Team Offense Game Summary Gaps Backfilled

Session 185's Phase 3 audit found 12 missing team records. All fixed:

| Date | Missing Teams | Status |
|------|--------------|--------|
| Jan 21 | SAC, TOR | Fixed (14 teams reprocessed) |
| Jan 24 | CLE, NYK, ORL, PHI | Fixed (12 teams reprocessed) |
| Jan 26 | ATL, CHA, CLE, IND, ORL, PHI | Fixed (14 teams reprocessed) |

### 4. November Usage Rate Gaps Fixed

Nov 13 and Nov 20 had 0% usage_rate coverage because team_offense records were missing. After backfilling team records (step 3), reprocessed PlayerGameSummaryProcessor:

| Date | Before | After |
|------|--------|-------|
| Nov 13 | 0% | 97.8% (87/89 active players) |
| Nov 20 | 0% | 98.9% (87/88 active players) |

### 5. Phase 3 Season Audit — 100% Coverage

Re-ran `phase3_season_audit.py` after all fixes:
- **Player game summary:** 100% complete (all dates Nov 2025 - Feb 2026)
- **Team offense game summary:** 100% complete (all gaps resolved)
- **Usage rate:** 2 critical dates fixed. 34 minor yellow warnings remain (88-99% coverage)
- **No new gaps** introduced

### 6. Daily Validation Results (Feb 10)

| Check | Status | Details |
|-------|--------|---------|
| Deployment drift | 2 stale → fixed | nba-grading-service deployed, scrapers still stale |
| Feature quality | 74.7% ready | 59/79 quality ready, matchup 100% |
| Predictions | 4 actionable | 4 games today (IND@NYK, LAC@HOU, DAL@PHX, SAS@LAL) |
| Signal | YELLOW | 33.3% pct_over, heavy UNDER skew |
| Grading (7-day) | 38.6% champion | Below other models at 47.3% |
| Heartbeats | Clean | 31 docs, 0 bad format |

### 7. Model Assessment — Champion Catastrophically Decaying

| Model | HR All (14d) | HR Edge 3+ (N) | Edge Picks/Wk | Vegas Bias |
|-------|-------------|----------------|---------------|------------|
| Champion (catboost_v9) | 27.9% | 49.0% (149) | ~40 | -0.27 |
| Jan 8 shadow (_0108) | 50.3% | 70.8% (24) | ~12 | -0.06 |
| Jan 31 tuned (_0131_tuned) | 53.4% | 33.3% (6) | ~3 | +0.06 |
| Jan 31 defaults (_0131) | 53.6% | 33.3% (6) | ~3 | +0.04 |
| **QUANT_43** | **No data** | **—** | **—** | **—** |
| **QUANT_45** | **No data** | **—** | **—** | **—** |

**Champion at 27% HR on Feb 8-9** — effectively losing money on every bet. 39 days stale.

**QUANT models timing issue:** Configs were committed and pushed after today's prediction run already completed. The latest prediction-worker deploy (18:39 UTC, revision `00196-9p6`) has the correct config. First QUANT predictions expected from tomorrow's 2:30 AM ET run.

### 8. Prevention Validator Passes Clean

`.pre-commit-hooks/validate_pipeline_patterns.py` now passes with 0 errors, 0 warnings after the Phase 2→3 fix. Previously had a non-ASCII character warning.

## Quick Start for Next Session

```bash
# 1. Verify Phase 2→3 trigger fired overnight (CRITICAL — first test of fix)
python3 -c "
from google.cloud import firestore
db = firestore.Client(project='nba-props-platform')
import datetime
yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
doc = db.collection('phase2_completion').document(yesterday).get()
if doc.exists:
    data = doc.to_dict()
    print(f'Phase 2 for {yesterday}:')
    print(f'  _triggered: {data.get(\"_triggered\", False)}')
    processors = [k for k in data.keys() if not k.startswith('_')]
    print(f'  Processors ({len(processors)}): {processors}')
"

# 2. Verify QUANT models generated predictions
bq query --use_legacy_sql=false "
SELECT system_id, game_date, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE system_id LIKE 'catboost_v9_q%'
  AND game_date >= '2026-02-10'
GROUP BY 1, 2 ORDER BY 1, 2 DESC"

# 3. Check QUANT grading (once games are played)
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q43_train1102_0131 --days 7

# 4. Run daily validation
/validate-daily

# 5. Run prevention validator
python .pre-commit-hooks/validate_pipeline_patterns.py
```

## Pending Follow-Ups

### High Priority
1. **Verify Phase 2→3 trigger fires tonight** — `_triggered` should be `True` for Feb 10 game date
2. **Verify QUANT_43/45 generate predictions** — first predictions expected tomorrow AM
3. **Model promotion decision** — champion at 27% HR is catastrophic. Once QUANT models have 3-5 days of data (~Feb 14-15), evaluate for promotion
4. **Grading backfill** — champion has 38.6% 7-day grading coverage. Consider running grading backfill

### Medium Priority
5. **Deploy nba-phase1-scrapers** — stale, missing expanded OddsAPI bookmakers (6 sportsbooks)
6. **Commit Session 186 uncommitted work** — `bin/compare-model-performance.py` (--all/--segments), `catboost_monthly.py` (strengths metadata), compare-models SKILL.md updates, model monitoring strategy doc

### Lower Priority
7. **Fix breakout classifier feature mismatch** — shadow mode, fires errors hourly (Session 184 Bug 5)
8. **Delay overnight Phase 3/4 schedulers** — from 6 AM to 8 AM ET to reduce noisy failures
9. **Extended eval for C1_CHAOS and NO_VEG** — when 2+ weeks of eval data available

## Key Commit

| SHA | Message |
|-----|---------|
| `b2e9e54b` | fix: Phase 2→3 trigger never fires — wrong expected processors and missing mappings |

## Architecture Decision: Phase 2 Expected Processors

The Phase 2→3 orchestrator trigger tracks completion via Firestore. The trigger fires when `completed_count >= EXPECTED_PROCESSOR_COUNT`.

**Previous (broken):** Expected 6 processors including `p2_bdl_box_scores` and `p2_br_season_roster` which never publish completion for individual game dates. Only 5 processors ever reported, so 5 < 6 = never triggers.

**New (Session 187):** Expected 5 processors that reliably publish daily completion:

| Config Name | Class Name | What It Does |
|-------------|------------|-------------|
| `p2_bigdataball_pbp` | BigDataBallPbpProcessor | Play-by-play data |
| `p2_odds_game_lines` | OddsApiGameLinesBatchProcessor | Game-level betting lines |
| `p2_odds_player_props` | OddsApiPropsBatchProcessor | Player point props |
| `p2_nbacom_gamebook_pdf` | NbacGamebookProcessor | Post-game player stats |
| `p2_nbacom_boxscores` | NbacPlayerBoxscoreProcessor | NBA.com player boxscores |

**Processors NOT in expected list (don't report daily):**
- `p2_bdl_box_scores` — BDL boxscores (separate from NBA.com)
- `p2_br_season_roster` — Basketball Reference rosters (weekly, not per game date)
- `p2_nbacom_schedule` — Schedule updates (not tied to specific game dates)

**Lesson:** Always validate expected processor lists against actual Pub/Sub messages in Firestore. The pre-commit validator (`validate_pipeline_patterns.py`) now checks that every expected config has a CLASS_TO_CONFIG_MAP entry, but it cannot detect processors that never report — that requires Firestore observation.
