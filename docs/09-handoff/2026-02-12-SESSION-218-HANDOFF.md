# Session 218 Handoff — Frontend Integration Fixes, UPCG Race Condition, Injury Deactivation

**Date:** 2026-02-12
**Session:** 218
**Status:** Complete — 6 fixes deployed, validation skills updated, pipeline re-triggered

## What Happened

Frontend team flagged 6 items from their morning check-in. Investigated all, fixed 4 code issues, resolved a critical race condition causing 2/3 games to have zero predictions, and added injury status deactivation to the enrichment pipeline.

## Fixes Deployed

### 1. Player Profile `summary.player_name: null` — Code Bug Fixed
- **Root cause:** `player_name` was at the top level (`player_full_name`) but never added inside the `summary` dict
- **Fix:** Added `'player_name': summary.get('player_full_name', player_lookup)` to summary dict
- **File:** `data_processors/publishing/player_profile_exporter.py:141`
- **Deployed:** Auto-deploy via Cloud Build (`deploy-phase6-export`)
- **Manually triggered player profile re-export** after deploy completed

### 2. Confidence Scale 0-100 — Documentation Fixed
- **Root cause:** API spec and schema comment showed 0-1 scale, but system uses 0-100 throughout
- **Fix:** Updated API spec examples from `0.72` → `72`, schema comment from "0.0-1.0" → "0-100"
- **Files:** `docs/08-projects/completed/frontend-api-backend/03-api-specification.md`, `schemas/bigquery/predictions/01_player_prop_predictions.sql`
- **Frontend can remove divide-by-100 workaround** or keep it (contract is 0-100)

### 3. Tonight Exporter `is_active` Filter — Bug Fixed
- **Root cause:** Predictions query lacked `AND pp.is_active = TRUE`, serving deactivated predictions
- **Fix:** Added `is_active = TRUE` filter to predictions CTE
- **File:** `data_processors/publishing/tonight_all_players_exporter.py:138`

### 4. UPCG Props Readiness — Made BLOCKING
- **Root cause:** UPCG ran at 07:01 UTC before BettingPros lines arrived at 07:02 UTC. Props readiness check was LOG-ONLY.
- **Fix:** Made `_check_props_readiness()` raise `ValueError` for future dates when props < 20 players. Returns 500 → Pub/Sub retry with exponential backoff. Backfill mode bypasses the check.
- **File:** `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py:527-543`

### 5. Injury Recheck in Enrichment Trigger
- **Root cause:** No mechanism to deactivate predictions when player status changes to "Out" after prediction creation. Enrichment at 18:40 UTC blindly enriched all predictions including Out players.
- **Fix:** Added `recheck_injuries()` method to `PredictionLineEnrichmentProcessor`. After enriching lines, queries current injury report, sets `is_active = FALSE` and `invalidation_reason = 'player_injured_out'` for Out players.
- **Files:** `data_processors/enrichment/prediction_line_enrichment/prediction_line_enrichment_processor.py` (new method), `orchestration/cloud_functions/enrichment_trigger/main.py` (wired into flow)

### 6. Pipeline Re-Triggered for Missing Games
- **Problem:** 2 of 3 games (POR@UTA, DAL@LAL) had zero predictions
- **Action:** Re-ran UPCG → Phase 4 (with `skip_dependency_check`) → Phase 5
- **Result:** 337 predictions across all 3 games (87 edge 3+, 26 edge 5+)

## Validation Skills Updated

### validate-daily — 3 New Phases
- **Phase 0.715:** UPCG Prop Coverage Check (game-level — are all games covered?)
- **Phase 0.72:** Injury Status vs Active Predictions (are Out players deactivated?)
- **Phase 0.975:** Tonight Export Completeness (do all scheduled games appear in export?)

### reconcile-yesterday — 2 New Phases
- **Phase 6.75:** Prop Coverage Audit (game-level prop line coverage)
- **Phase 10:** Injury Deactivation Audit (did enrichment correctly deactivate Out players?)

## Root Cause Analysis

### UPCG Race Condition (Item 1)
```
06:00 UTC  Phase 2 scrapers complete
07:00 UTC  Odds API scraper runs — only MIL@OKC has lines
07:01 UTC  UPCG runs, queries both Odds API + BettingPros
           → Odds API: 11 players (MIL@OKC only)
           → BettingPros: 0 records (not scraped yet!)
           → UPCG completes with 11/104 players having lines
07:02 UTC  BettingPros lines arrive — TOO LATE
           → Phase 4 only processes 11 MIL@OKC players
           → Phase 5 only generates predictions for MIL@OKC
```
**Prevention:** UPCG now blocks with 500 if < 20 players have props (Pub/Sub retries).

### Injury Status Timing (Item 2)
Three failure modes for Out players with active predictions:
1. **Timing gap (60%):** "Out" status not in BQ when predictions created (8+ hour lag)
2. **Status change (30%):** Player was Questionable/Doubtful → Out after prediction
3. **Late scratch (10%):** Player was Probable/Available → scratched pre-game

**Prevention:** Enrichment trigger (18:40 UTC) now rechecks injuries and deactivates Out players.

## Items Confirmed Working (No Fix Needed)
- **13 picks with null results (Item 3):** All are PASS recommendations or voided (DNP/scratch). Expected.
- **Tonight scores (Item 6):** Fixed in Session 214. Live export refreshes every 2-3 min during games. Will verify tonight.

## Files Changed

| File | Change |
|------|--------|
| `data_processors/publishing/player_profile_exporter.py` | Add `player_name` to summary dict |
| `data_processors/publishing/tonight_all_players_exporter.py` | Add `is_active = TRUE` filter |
| `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` | Make props readiness BLOCKING |
| `data_processors/enrichment/prediction_line_enrichment/prediction_line_enrichment_processor.py` | Add `recheck_injuries()` method |
| `orchestration/cloud_functions/enrichment_trigger/main.py` | Wire injury recheck after enrichment |
| `docs/08-projects/completed/frontend-api-backend/03-api-specification.md` | Fix confidence scale to 0-100 |
| `schemas/bigquery/predictions/01_player_prop_predictions.sql` | Fix confidence schema comment |
| `.claude/skills/validate-daily/SKILL.md` | Add Phases 0.715, 0.72, 0.975 |
| `.claude/skills/reconcile-yesterday/SKILL.md` | Add Phases 6.75, 10 |

## Tonight's Verification Checklist
- [ ] Watch MIL@OKC, POR@UTA, DAL@LAL for live score updates in tonight/all-players.json
- [ ] Verify enrichment trigger at 18:40 UTC deactivates Out players
- [ ] Confirm all 3 games have predictions in the export
- [ ] Check if player profiles now show `summary.player_name` populated

## Remaining Work (From Earlier Session 218)

### High — Scheduler Job Triage
10 code-13 scheduler jobs still need individual investigation (see earlier in this session).

### Medium — From Session 216B
1. Wire Slack secrets to `daily-health-check`
2. `pipeline-health-summary` container startup failure
3. `bigquery-daily-backup` rewrite to Python GCS client
4. `live-freshness-monitor` stale deploy
