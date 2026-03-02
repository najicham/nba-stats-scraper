# Session 385 Handoff — Per-Model Profile Filtering Investigation

**Date:** 2026-03-02
**Branch:** main (pushed)
**Focus:** Investigate whether profile blocking, group-specific signal exclusions, or model selection changes would improve best bets

## What Was Done

### 1. Ran 5 Diagnostic Queries Against Live Data

All queries against `signal_best_bets_picks` + `prediction_accuracy` + `model_profile_daily` (Dec 1+).

**All 5 decision gates returned NO-GO:**

| Gate | Threshold | Actual | Verdict |
|------|-----------|--------|---------|
| Q1: Signal gap >10pp, N>=15 both sides | N>=15 | Max N=7 (book_disagreement v12_noveg) | NO-GO |
| Q2: Profile blocked picks HR <45% | <45% | AWAY blocks = 66.7% HR (profitable!) | NO-GO |
| Q3: Group x direction x tier combo <45%, N>=10 | <45% | 45.5% (v9 OVER starter, 0.5pp above) | NO-GO |
| Q4: Net swap benefit >5 | >5 | ±1 | NO-GO |
| Q5: Star UNDER <45% all months | <45% | 55.6-63.6% | NO-GO |

### 2. Key Finding: AWAY Profile Block Would HURT Performance

The most important discovery — AWAY-blocked picks in best bets have 66.7% HR (N=12). Activating profile blocking wholesale would remove profitable picks. The filter stack already compensates for raw-level AWAY weakness.

### 3. Best Bets Volume by Affinity Group

| Group | N | HR | Share |
|-------|---|-----|-------|
| v9 | 66 | 63.6% | 56% |
| v12_vegas | 35 | 74.3% | 30% |
| v12_noveg | 12 | 58.3% | 10% |
| v9_low_vegas | 4 | 75.0% | 3% |

Feb decline is universal: v9 -9.8pp, v12_vegas -31.5pp. v12_noveg has ALL picks in Feb.

### 4. Wrote Project Documentation

- `docs/08-projects/current/session-385-profile-filtering-investigation/00-FINDINGS.md` — investigation results
- `docs/08-projects/current/session-385-profile-filtering-investigation/01-FORWARD-LOOKING-ROADMAP.md` — comprehensive forward-looking strategy

### 5. Forward-Looking Roadmap (from 3 agent reviews)

The roadmap doc covers:
- **Profile Phase 2 design**: Activate direction dimension only (NOT home_away). Graduated response (green/yellow/red zones). Integration into ROW_NUMBER SQL via `model_profile_daily` join.
- **Model selection**: Direction-conditional HR weighting is the top candidate (wait for N>=15 per direction per model, ~3-4 weeks).
- **Signal evolution**: Model-aware signal gating (exclude book_disagreement for v12_noveg when N>=15), confidence-weighted signal counting, market-derived signal focus.
- **Ultra bets expansion**: Group-aware criteria, signal-conditioned ultra, backtest window refresh.
- **Monitoring improvements**: 5 leading indicators, 5 new daily checks, automated model lifecycle triggers.
- **Retraining**: 14-day cadence (not 7-day), vegas-weight dampening during regime shifts.

## What Was NOT Done

- No code changes — all gates NO-GO, no interventions warranted
- Did not run daily validation (user interrupted to request handoff)
- Did not retrain any models

## Items to Monitor

| Item | Current | Threshold to Act | Timeline |
|------|---------|-------------------|----------|
| book_disagreement for v12_noveg | 14.3% (N=7) | N>=15 and HR <40% | ~3 weeks |
| v12_noveg group overall | 58.3% (N=12) | N>=30 and HR <50% | ~4 weeks |
| v9 OVER starter | 45.5% (N=11) | N>=20 and HR <45% | ~2 weeks |
| Profile blocking direction/tier | Mixed (N=14) | N>=30 aggregate | ~4 weeks |

## Immediate Next Steps for New Session

1. **Run daily validation** — was not completed this session
2. **Fresh retrain** with 56d window + vw015 — highest leverage improvement per roadmap
3. **Check deployment drift** — `./bin/check-deployment-drift.sh --verbose`
4. Profile blocking stays in observation mode — no changes needed

## Files Changed

| File | Change |
|------|--------|
| `docs/08-projects/current/session-385-profile-filtering-investigation/00-FINDINGS.md` | NEW — investigation results |
| `docs/08-projects/current/session-385-profile-filtering-investigation/01-FORWARD-LOOKING-ROADMAP.md` | NEW — forward-looking strategy |
| Memory MEMORY.md | Updated Session 384 entry with 385 findings |

## Git Status

- All changes committed and pushed to main
- No deployment needed (docs only)
