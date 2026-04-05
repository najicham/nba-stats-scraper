# Deep Dive Plan — Session 512 (2026-04-04)

Based on 5-agent parallel investigation of both NBA and MLB systems.

---

## Investigation Findings Summary

### NBA: Edge 3-5 Leakage (43.2% HR, N=44)

**The real leak is UNDER at edge 3-5 with `real_sc=2`: 4-7 (36.4%, N=11).**

- OVER rescue at edge 3-5: mostly historical (pre-Session 466). Current code only allows HSE rescue, which is 3-0 (100%). No code change needed for OVER.
- UNDER has no edge floor beyond `MIN_EDGE=3.0`. Picks with `real_sc >= 2` pass through at edge 3-5 and lose money.
- `real_sc=3` at edge 3-5 = 75% HR (N=4). `real_sc=2` = 36.4% (N=11). Clear separation.

**Recommended fix:** Raise `under_low_rsc` threshold from `real_sc < 2` to `real_sc < 3` for edge < 5.0. Blocks the 36.4% tier, preserves the 75% tier. ~15 min implementation in `aggregator.py`.

### NBA: Fleet Status — Concerning

- Feb-anchored models started generating predictions today (Apr 4) — first day.
- **Feb models have LOWER avg edge (1.37-1.38) than Mar models (1.62-1.74).** Pick drought may continue.
- AUTO_DISABLE_ENABLED=true → BLOCKED Mar models will auto-disable at 11 AM ET.
- Market is NORMAL/LOOSE (vegas MAE 5.35) — favorable, but edges still compressed.
- **Monday auto-retrain risk:** Rolling 56-day window ending ~Apr 6 will include heavy March data. TIGHT cap only activates if vegas_mae < 4.5, which hasn't been the case recently (5.35-5.88). New models may have same compressed-edge problem.

### MLB: System is Effectively Dead — 5 Interconnected Blockers

**All four links in the pipeline chain are broken simultaneously.**

#### Blocker 1: No Proxy Credentials on MLB Service (CRITICAL)
- `mlb-phase1-scrapers` has ZERO proxy secrets configured
- NBA service has `DECODO_PROXY_CREDENTIALS` + `PROXYFUEL_CREDENTIALS`
- MLB deploy script (`bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh`) has no `--set-secrets`
- **Fix:** Add `--set-secrets` line, redeploy. ~15 min.

#### Blocker 2: TODAY Literal in GCS Path
- Schedulers pass `"game_date": "TODAY"` but config_mixin only resolves `date`, not `game_date`
- MLB events scraper resolves `game_date` AFTER `super()` already derived `date` from unresolved value
- Files land at `mlb-odds-api/events/TODAY/` instead of `mlb-odds-api/events/2026-04-04/`
- **Fix:** Resolve `game_date` before calling `super().set_additional_opts()`. ~5 min.

#### Blocker 3: Phase 2 Events Processor Format Mismatch
- Scraper uses `ExportMode.RAW` (writes raw API response as JSON array)
- Processor expects dict with `"events"` key → validation fails, 0 rows written
- **Fix:** Change `ExportMode.RAW` to `ExportMode.DATA` in scraper. ~1 line.

#### Blocker 4: Missing Schedulers
- `mlb_box_scores_mlbapi` has no scheduler → `mlbapi_pitcher_stats` stopped after Mar 27
- Statcast scheduler at 3 AM UTC (7 PM PT) runs before west coast games finish
- Schedule scraper only runs for TODAY, never re-scrapes past dates for `is_final`
- **Fix:** Add 3 scheduler jobs. ~30 min.

#### Blocker 5: Grading Has 3 Trivial Bugs
- `game_pk` vs `game_id` column mismatch in grading SQL (line 285)
- `"YESTERDAY"` literal passed to `_backfill_shadow_picks` unresolved
- `game_status` column doesn't exist in `mlb_schedule` (actual: `status_detailed`)
- **Fix:** 3 one-line changes. ~10 min.

---

## Prioritized Action Plan

### Priority 1: MLB Pipeline Fixes (Batch — All Small, All Interconnected)

These must all be done together because fixing any one alone doesn't produce end-to-end flow.

| # | Fix | File(s) | Complexity | Time |
|---|-----|---------|-----------|------|
| 1a | Add proxy secrets to MLB deploy script | `bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh` | 1 line + redeploy | 15 min |
| 1b | Fix TODAY literal in events scraper | `scrapers/mlb/oddsapi/mlb_events.py` | 3-5 lines | 5 min |
| 1c | Fix ExportMode.RAW → DATA | `scrapers/mlb/oddsapi/mlb_events.py` | 1 line | 2 min |
| 1d | Add NoneType guard to bp_events.py | `scrapers/bettingpros/bp_events.py` | 3 lines | 5 min |
| 1e | Fix grading: game_pk → game_id | `data_processors/grading/mlb/mlb_prediction_grading_processor.py` | 1 line | 2 min |
| 1f | Fix grading: YESTERDAY literal | `data_processors/grading/mlb/main_mlb_grading_service.py` | 3 lines | 5 min |
| 1g | Fix grading: game_status column | `data_processors/grading/mlb/mlb_prediction_grading_processor.py` | 1 line | 2 min |

**Total: ~35 min coding, then deploy + create schedulers.**

### Priority 2: MLB Scheduler Creation

| Scheduler | Target | Schedule | Body |
|-----------|--------|----------|------|
| `mlb-box-scores-daily` | `mlb-phase1-scrapers` | `0 13 * * * (6 AM PT)` | `{"scraper": "mlb_box_scores_mlbapi", "date": "YESTERDAY"}` |
| `mlb-schedule-update` | `mlb-phase1-scrapers` | `0 13 * * * (6 AM PT)` | `{"scraper": "mlb_schedule", "date": "YESTERDAY"}` |
| Update `mlb-statcast-daily` | same | `0 13 * * *` (was 3 AM UTC) | same body |

### Priority 3: NBA Edge 3-5 Leakage Fix

Raise `under_low_rsc` gate from `real_sc < 2` to `real_sc < 3` for UNDER picks at edge < 5.0.
- File: `ml/signals/aggregator.py` lines ~1292-1299
- Expected impact: blocks ~11 of 22 UNDER edge 3-5 picks (the 36.4% HR tier)
- Preserves: `real_sc >= 3` tier at 75% HR (N=4)

### Priority 4: NBA Fleet Monitoring (No Action, Observe)

- Feb-anchored models just started today. Monitor edge distribution over next 2-3 days.
- AUTO_DISABLE will handle BLOCKED Mar models.
- **Decision point Monday Apr 6:** If auto-retrain includes March data and produces compressed models, consider manually setting `--train-end 2026-02-28` for next retrain.

### Priority 5: End-of-Season Posture (Deferred)

- 8 game days left. Consider tighter filters if load management spikes.
- No action needed today.

---

## What to Focus on FIRST

**Priority 1: MLB Pipeline Fixes.**

Rationale:
- MLB has a 63.4% backtest HR system that is 100% broken due to ~10 small bugs
- All fixes are trivial (1-5 lines each) but interconnected — must batch them
- Every day without fixes = another day of 0 actionable predictions + 0 grading
- NBA edge 3-5 fix saves ~1-2 picks/week; MLB fix enables 5-10 picks/day
- NBA fleet issue needs observation time anyway (Feb models just started today)

**Start with the code fixes (1a-1g), deploy, create schedulers, verify end-to-end.**
