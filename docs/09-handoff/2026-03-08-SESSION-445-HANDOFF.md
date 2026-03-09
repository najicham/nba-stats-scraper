# Session 445 Handoff — Per-Model Best Bets Pipelines

**Date:** 2026-03-08
**Session:** 445 (NBA, continuation of 442)
**Status:** CODE COMPLETE, NOT YET DEPLOYED. Replay validation pending.

---

## What Was Done

### Per-Model Pipeline Architecture (Major)

Replaced the single winner-take-all BB pipeline with per-model pipelines feeding a pool-and-rank merge layer. The old system used `ROW_NUMBER() OVER (PARTITION BY player ORDER BY |edge| * HR_weight DESC)` to pick ONE model per player — this caused the best model (catboost_v9_train1102_0108, 87.5% OVER 3-4) to be **disabled entirely** because it dominated selection then got blocked by LEGACY_MODEL_BLOCKLIST.

**New architecture:**
```
Worker predictions → Batch query ALL models (no dedup)
  → Per-model pipeline (signals + aggregator in mode='per_model')
  → Pool all candidates, sort by composite_score
  → First-occurrence player dedup + team cap + volume cap + rescue cap
  → Final best bets picks
```

### Files Created
| File | Lines | Purpose |
|------|-------|---------|
| `ml/signals/per_model_pipeline.py` | 1,621 | SharedContext, batch query, per-model runner |
| `ml/signals/pipeline_merger.py` | 366 | Pool-and-rank merge with provenance tracking |
| `bin/replay_per_model_pipeline.py` | 659 | Season replay comparison script |
| `schemas/model_bb_candidates.json` | 272 | BQ schema (45 columns) |
| `docs/08-projects/current/per-model-pipelines/` | — | Architecture + implementation plan |

### Files Modified
| File | Change |
|------|--------|
| `data_processors/publishing/signal_best_bets_exporter.py` | Wired to per-model pipelines + merger |
| `ml/signals/aggregator.py` | Added `mode='per_model'` (skips team/rescue cap) |
| `ml/signals/supplemental_data.py` | Fixed `source_model_family` bug in single-model path |
| `ml/analysis/model_performance.py` | Extended with pipeline-level HR metrics |
| `tests/unit/signals/test_aggregator.py` | +4 tests (per_model mode) |
| `tests/unit/publishing/test_signal_best_bets_exporter.py` | Updated for per-model integration |

### Key Design Decisions
1. **Signals evaluated per-model** — nearly every signal gates on `recommendation` (OVER/UNDER) which is model-specific. Cannot share.
2. **Batch query optimization** — ONE BQ scan for all models' predictions (no ROW_NUMBER dedup), partition in Python. 10x reduction in BQ queries.
3. **Pool-and-rank merge** — no custom merge scoring formula. Pool all candidates, sort by `composite_score` (already validated by aggregator), first-occurrence dedup. Simpler and reuses existing ranking logic.
4. **No agreement bonus** — raw multi-model agreement is anti-correlated with winning. Tracked as `pipeline_agreement_count` for future study.
5. **Full provenance** — `model_bb_candidates` table stores ALL candidates from ALL models with 45-column provenance schema for historical study.

### BQ Table Created
- `nba_predictions.model_bb_candidates` — partitioned by game_date, clustered by system_id + player_lookup

### Bug Fixes
- **`source_model_family` not set in single-model path** — V9 UNDER 7+ filter silently failed in single-model mode. Fixed unconditionally.
- **`source_pipeline` tagged after merge in replay** — pipeline agreement was always 1. Fixed: tag before merge.

---

## System State

| Item | Status |
|------|--------|
| Algorithm Version | `v443_per_model_pipelines` |
| Tests | **127 pass** (111 aggregator + 16 exporter) |
| Commits | 4 this session |
| Deployed | **NO — not pushed to main yet** |
| Season Replay | **NOT YET RUN** |
| BB HR (old system) | 64.1% (91-51, Jan 9 - Mar 7) |

---

## What to Do Next

### Priority 1: Run Season Replay (CRITICAL — do this first)
```bash
PYTHONPATH=. python bin/replay_per_model_pipeline.py --start 2026-01-09 --end 2026-03-07 --verbose
```
Compares per-model pipeline vs old system across full season (~50 game dates). Takes ~30 min.
Add `--write-candidates` to populate `model_bb_candidates` BQ table with historical data.

**Decision gate:** Deploy only if new system HR >= old system HR (64.1%).

The replay script produces:
- Head-to-head HR comparison (new vs old)
- Edge tier breakdown (3-4, 4-6, 6+)
- Line tier × direction breakdown
- Per-model pipeline contribution (which models source winning picks)
- Overlap analysis (shared picks, new-only picks, old-only picks + HR for each)
- Pipeline agreement analysis (does post-filter agreement correlate with winning?)
- Rescued OVER/UNDER split
- Day-level comparison (which days did new system win?)

### Priority 2: Re-enable catboost_v9_train1102_0108
Best model in fleet — 87.5% OVER 3-4, 74.2% UNDER 3-4, 82.6% top-1 daily.
Currently disabled (shadow in registry). Registry entry:
```
model_id: catboost_v9_33f_train20251102-20260108_20260208_170526
system_id: catboost_v9_train1102_0108
```
```sql
UPDATE nba_predictions.model_registry
SET enabled = true, status = 'active',
    notes = CONCAT(notes, ' | Re-enabled Session 445: best model per autopsy')
WHERE model_id = 'catboost_v9_33f_train20251102-20260108_20260208_170526';
```
After registry update, force worker cache refresh:
```bash
gcloud run services update prediction-worker --region=us-west2 \
  --update-env-vars="MODEL_CACHE_REFRESH=$(date +%Y%m%d_%H%M)"
```
**Risk:** Training data is 2 months stale (Nov 2 - Jan 8). Decay detection will auto-disable if it degrades.

### Priority 3: Push and Deploy
```bash
git push origin main  # Auto-deploys all services
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
./bin/check-deployment-drift.sh --verbose
```

### Priority 4: Monitor First Game Day
- Verify per-model pipelines produce candidates
- Verify `model_bb_candidates` table gets populated
- Compare pick count/quality to expectations
- Check logs for errors in `per_model_pipeline.py` or `pipeline_merger.py`

### Priority 5: Update Memory
Add Session 445 findings to MEMORY.md after replay results are known.

---

## NOT Doing Yet
- Pipeline-HR-weighted dedup (using pool-and-rank instead until pipeline data accumulates)
- Post-filter agreement bonus (anti-correlated at raw level, needs backfill validation)
- Direction conflict penalty (need data first)
- Model-specific filter thresholds (needs architectural design)
- Backfill `model_bb_candidates` for historical dates (do after replay validates)

---

## Key Context from Session 442

- **Losing day DNA:** low-edge OVER on bench players via rescue, 0 rescued on winning days, 1.8 on losing
- **OVER collapsed:** 80% Jan → 53% Feb → 47% Mar. UNDER stable: 63% → 63% → 71%
- **Solo picks = 52.2% HR** vs multi-pick = 75.3% (23pp gap)
- **Rescue net-negative:** 44.4% rescued OVER vs 67.1% organic. Only HSE works (80%).
- **Model profiles wildly different:** v9_train1102 = 87.5% OVER 3-4; catboost_v8 = 47% same
- **UNDER bottleneck = signal coverage:** 907 candidates/day → 25 BB picks (2.8%)
- **catboost_v12_train0104_0222 (82.4% HR, 0 BB):** vegas features compress 95%+ to HOLD

## Architecture Reference

- Full architecture: `docs/08-projects/current/per-model-pipelines/00-ARCHITECTURE.md`
- Implementation plan: `docs/08-projects/current/per-model-pipelines/01-IMPLEMENTATION-PLAN.md`

## Commits
```
3b241030 feat: Session 442 — autopsy-driven observations + rest_advantage_2d weight
43164d7a feat: Session 442 — solo game pick observation (O5)
bfac51f2 feat: Session 443 — per-model best bets pipelines
35a113ff feat: Session 443 — per-model pipeline season replay script
```
