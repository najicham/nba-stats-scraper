# Session 261 Handoff — Deployment, Historical Replay, Decision Framework

**Date:** 2026-02-15
**Status:** Sessions 259+260+261 fully deployed. V12 driving best bets. Framework documented.

---

## What Was Done

### 1. Deployed Sessions 259+260 (Fully Live)

| Step | Status |
|------|--------|
| BQ DDLs (2 tables, 7 ALTER columns, 1 view) | Done |
| Git push + Cloud Build (8 builds) | All SUCCESS |
| post-grading-export Cloud Function | ACTIVE (Gen2, revision 00003) |
| Signal backfill (Jan 9 - Feb 14) | 2,130 tag rows, 117 best bets |
| Signal health backfill | 298 rows (7-9 signals/day) |
| Combo performance view | Working, all SYNERGISTIC combos above breakeven |

### 2. Switched Best Bets to catboost_v12

```
BEST_BETS_MODEL_ID=catboost_v12
```
Set on both `phase6-export` and `post-grading-export` services.

**Why V12:** 56.0% edge 3+ HR on 50 picks (+6.9% ROI) — best model with sufficient sample size. Clears 52.4% breakeven by 3.6 points.

**Rollback:** Remove env var → falls back to catboost_v9 (champion default).

### 3. Historical Replay Analysis

Replayed entire prediction history (7 queries across all models). Key findings:
- Champion decayed from 77.4% to 42.3% over 20 days
- Automated alert at 55% HR would have given 4-5 days lead time
- Signals are amplifiers, not independent alpha generators
- V8 remains all-time champion ($1.59M simulated P&L, 4 seasons)
- Feb retrain (v9_2026_02) was catastrophic (30% HR, -42.7% ROI)

### 4. Decision Framework Documented

Full framework at `docs/08-projects/current/signal-discovery-framework/SESSION-261-HISTORICAL-REPLAY-AND-DECISION-FRAMEWORK.md`

**Automated:** Decay detection, signal health, model comparison, auto-blocking
**Human decision:** Model switching, retraining, promotions, threshold adjustments

### 5. Replay Tool Designed (Not Yet Built)

Python scripts (`ml/analysis/replay_*.py`) + Claude skill (`/replay`). Design documented in project doc. Builds in Phase 2-3.

---

## Current System State

### Active Models
| Model | Role | Edge 3+ HR (14d) | Status |
|-------|------|------------------|--------|
| catboost_v12 | **Best bets driver** | 56.0% (N=50) | ACTIVE via env var |
| catboost_v9 | Champion (baseline) | 40.6% (N=187) | DECAYED, still producing predictions |
| catboost_v9_q45 | Shadow | 60.0% (N=25) | Monitoring |
| catboost_v9_q43 | Shadow | 54.1% (N=37) | Monitoring |
| catboost_v8 | Legacy | 47.0% recent | 4-year track record |

### Signal Health (as of Feb 12 backfill)
- 9 signals tracked daily
- 4 COLD, 2 HOT, 0 DEGRADING
- Health weighting LIVE in aggregator (HOT 1.2x, COLD 0.5x)

### Known Issues
- **Combo registry has duplicate rows** (14 instead of 7). INSERT ran twice. Non-blocking but should clean up:
  ```sql
  -- Deduplicate (keep one copy of each combo_id)
  CREATE OR REPLACE TABLE nba_predictions.signal_combo_registry AS
  SELECT * FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY combo_id ORDER BY created_at DESC) as rn
    FROM nba_predictions.signal_combo_registry
  ) WHERE rn = 1
  ```
- **latest.json not yet created** — will be generated on first game day (Feb 19)
- **V12 prediction coverage unknown** — need to verify V12 shadow model is running and will produce predictions for Feb 19 games

---

## What Needs to Be Done Next

### URGENT: V12 Confidence Tier Filter

Subset analysis revealed V12 has a **41.7% HR at 85-90% confidence** (same gap V8 had). The 90+ tier is 60.5%. We may need to add a confidence floor to best bets scoring before Feb 19 games. This is the same type of "hidden subset that loses money" that V8 taught us about.

Options:
1. Add `confidence_score >= 0.90` filter to aggregator/exporter (code change)
2. Add it as a signal weighting factor (confidence < 0.90 gets 0.5x weight)
3. Monitor first few game days and decide after seeing V12 in production

### Priority 1: Pre-Game-Day Verification (Before Feb 19)
- [ ] Verify catboost_v12 predictions pipeline is active (check Feb 19 will produce predictions)
- [ ] Clean up combo registry duplicates
- [ ] Run `validate-daily` to check overall pipeline health
- [ ] Verify latest.json gets created after first game day export

### Priority 2: Build Automated Monitoring (Phase 2)
- [ ] Create `model_performance_daily` BQ table (7d/14d/30d rolling HR per model)
- [ ] Build decay detection Cloud Function (WATCH at 58%, ALERT at 55%, BLOCK at 52.4%)
- [ ] Wire Slack alerts for model state changes
- [ ] Add `validate-daily` Phase 0.58 check
- [ ] Build challenger-beats-champion alerts

### Priority 3: Replay Tool (Phase 2-3)
- [ ] Build `ml/analysis/replay_engine.py` — core simulation
- [ ] Build `ml/analysis/replay_strategies.py` — pluggable strategies (threshold, best-of-N, conservative)
- [ ] Build `ml/analysis/replay_cli.py` — CLI entry point
- [ ] Build `/replay` Claude skill
- [ ] Run V8 multi-season replay to calibrate optimal thresholds
- [ ] Run replay against V9 era with multiple strategy parameters

### Priority 4: Deeper Analysis
- [ ] Subset analysis: edge buckets x confidence x prop type across all models (query results pending from Session 261 agent)
- [ ] Investigate Feb 2 week collapse (see parallel chat prompt)
- [ ] Determine if confidence tier filtering adds value for V12 (like V8's 88-90% gap)
- [ ] Test whether excluding model-dependent signals during COLD periods improves results

---

## Parallel Chat: Feb 2 Investigation

A dedicated chat prompt has been created at:
`docs/09-handoff/session-prompts/SESSION-261-FEB2-INVESTIGATION.md`

This chat should investigate:
1. Root cause of the Feb 2 crash (market shift? data quality? lineup changes?)
2. Whether better filtering could have avoided the worst losses
3. Early warning indicators that could predict crashes 1-3 days earlier
4. Whether V8 and V9 crashed for the same reason (suggesting external cause)

---

## Files Changed/Created

### Session 261 New Files
| File | Purpose |
|------|---------|
| `docs/08-projects/current/signal-discovery-framework/SESSION-261-HISTORICAL-REPLAY-AND-DECISION-FRAMEWORK.md` | Main analysis + framework |
| `docs/09-handoff/session-prompts/SESSION-261-FEB2-INVESTIGATION.md` | Parallel chat prompt for Feb 2 investigation |
| `docs/09-handoff/2026-02-15-SESSION-261-HANDOFF.md` | This file |

### Session 260 Files (committed this session)
| File | Action |
|------|--------|
| `shared/config/model_selection.py` | NEW — configurable model ID |
| `ml/signals/aggregator.py` | MODIFIED — health weighting |
| `ml/signals/supplemental_data.py` | MODIFIED — configurable system_id |
| `data_processors/publishing/signal_best_bets_exporter.py` | MODIFIED — configurable model |
| `data_processors/publishing/signal_annotator.py` | MODIFIED — configurable model |

### Infrastructure Changes
| Change | Details |
|--------|---------|
| `BEST_BETS_MODEL_ID=catboost_v12` | Set on phase6-export and post-grading-export |
| `signal_combo_registry` table | Created + seeded with 7 combos |
| `signal_health_daily` table | Created + backfilled 298 rows |
| `v_signal_combo_performance` view | Created |
| Combo columns on pick_signal_tags | 3 columns added |
| Combo columns on signal_best_bets_picks | 4 columns added |
| post-grading-export CF | Deployed revision 00003 |

---

## Key Commits

| SHA | Message |
|-----|---------|
| `e433b22c` | feat: combo registry, signal health monitoring, scoring fix, signal count floor |
| `48b5707c` | docs: Session 259 handoff and updated START-NEXT-SESSION-HERE |
| `fc7b6e91` | feat: configurable model selection, signal health weighting, Session 260 docs |
