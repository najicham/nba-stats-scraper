# Session 331 Handoff — VOID/DNP Fix, Daily Steering, Weekend Pipeline Check

**Date:** 2026-02-22
**Previous Session:** 330 — Coordinator Bug Fixes + Batch Line Optimization

## What Was Done

### 1. P1 RESOLVED: Investigated 6 ungraded picks

Frontend showed "100 of 106 picks graded". Root cause: all 6 are **DNP (Did Not Play)** — players who were predicted pre-game but didn't play.

| Date | Player | Team | Void Reason |
|------|--------|------|-------------|
| Feb 12 | Lauri Markkanen | UTA | dnp_unknown |
| Feb 11 | Joel Embiid | PHI | dnp_unknown |
| Feb 11 | OG Anunoby | NYK | dnp_unknown |
| Feb 10 | OG Anunoby | NYK | dnp_late_scratch |
| Jan 30 | Austin Reaves | LAL | dnp_injury_confirmed |
| Jan 26 | Deni Avdija | POR | dnp_injury_confirmed |

Grading pipeline correctly marks these `is_voided = true` in `prediction_accuracy`, but the exporter wasn't surfacing this to the frontend.

### 2. Fixed best_bets_all_exporter.py to surface VOID/DNP picks

**Commit:** `272f63a1` — `feat: add VOID/DNP status to best bets export for frontend`

Changes to `data_processors/publishing/best_bets_all_exporter.py`:
- Added `pa.is_voided` and `pa.void_reason` to the BQ query
- Pick-level: `result: "VOID"` with `void_reason: "DNP"` for voided picks
- Day-level: `record.voided` count, `status: "void"` for all-voided days, voided no longer inflates `pending`
- Top-level: `total_picks` now excludes voided (100 not 106), new `voided: 6` field

Re-exported to GCS — live at `v1/best-bets/all.json`. Verified in production.

### 3. Frontend prompt for VOID/DNP display

Written at `docs/08-projects/current/frontend-data-design/09-VOID-DNP-FRONTEND-PROMPT.md`. Includes:
- Full before/after JSON examples for all levels (pick, day, top-level)
- TypeScript type updates (`PickResult = 'WIN' | 'LOSS' | 'VOID' | null`, `DayStatus` includes `'void'`)
- Visual treatment recommendations (gray "DNP" badge, dimmed card)
- Day status handling for new `"void"` value

### 4. Daily Steering Report

**Model Health (as of Feb 21):**
- V9 champion: HEALTHY (80% 7d, N=5 — misleading small sample). 14d HR is 41.7%
- V9_low_vegas: HEALTHY (60-66.7% 7d, N=15)
- V12: WATCH/BLOCKED (48-56% 7d)
- Most shadow models: BLOCKED (below 52.4% threshold)
- Quantile 0131 models: INSUFFICIENT_DATA (0 picks in 7d)

**Market Regime — Triple RED:**
- Compression: 0.551 (RED, < 0.65)
- 7d avg max edge: 4.6 (RED, < 5.0)
- Edge 5+ supply: 0.8 picks/day (RED, 30d norm: 4.1)
- Direction split: balanced (OVER 50% / UNDER 50%)
- Residual bias: +0.11 (negligible)

**Best Bets:** 3-3 last 7d, 6-6 last 14d, 30-16 (65.2%) last 30d

**Recommendation: WATCH.** All-Star break compressed the market. Not a model failure. Reassess Wed Feb 25 after 2 full-slate days.

### 5. Weekend pipeline timing verified

Saturday Feb 22:
- `overnight-predictions` scheduler fired at 8:00 AM ET
- 32 V9 predictions completed at 8:29 AM ET
- CLE @ OKC (first game): 1:00 PM ET — **predictions ready 4.5 hours early**
- Session 329 backfill at 6:57 PM ET superseded with 52 predictions (added V12+vegas)

Pipeline ran properly. No timing issues.

## Follow-Up (Next Session)

### P1: Wednesday reassessment (Feb 25)

Run `/daily-steering` after Mon Feb 24 (11 games) + Tue Feb 25 (6 games). Key thresholds:
- V9 7d HR with 15+ picks — if below 55%, initiate retrain
- Market compression recovery above 0.85
- Edge 5+ supply returning to 3+ picks/day

### P2: V12+Vegas monitoring

V12+vegas generating predictions (52 on Feb 22). Track via `model_performance_daily`:
- Historical advantage: 62.7% edge 3+ HR vs V9 48.3%
- If sustained, discuss promotion

### P3: Model staleness watch

- V9 champion: 16 days (OK)
- Shadow models at 27 days — approaching 30-day retrain trigger
- Quantile 0131 models starved (INSUFFICIENT_DATA)

### P4: Uncommitted model_direction_affinity code

Unstaged changes from a previous session implement model-direction affinity filter (observation mode):
- `ml/signals/model_direction_affinity.py` (new)
- `signal_best_bets_exporter.py`, `aggregator.py`, `test_aggregator.py` (modified)
- `tests/unit/signals/test_model_direction_affinity.py` (new)

Review and commit or discard next session.

### Optional

- Frontend VOID/DNP implementation — prompt delivered, awaiting frontend pickup
- Ultra OVER gate: 17-2 (89.5%, N=19). Need 50 for public. ~10 weeks.
- Admin dashboard `ultra_gate` field still missing

## Key Files Changed

| File | Change |
|------|--------|
| `data_processors/publishing/best_bets_all_exporter.py` | VOID/DNP support: query, picks, days, top-level counts |
| `docs/08-projects/current/frontend-data-design/09-VOID-DNP-FRONTEND-PROMPT.md` | Frontend guidance for VOID/DNP display |
| `docs/09-handoff/2026-02-22-SESSION-331-HANDOFF.md` | This file |
