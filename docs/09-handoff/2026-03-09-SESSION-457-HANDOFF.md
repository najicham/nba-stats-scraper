# Session 457 Handoff — BB Pipeline Gap Analysis + Retraining Strategy

**Date:** 2026-03-09
**Session:** 457 (NBA)
**Status:** Analysis COMPLETE. Retraining docs and code UPDATED.

---

## What Was Done

### 1. BB Pipeline Gap Analysis (Priority 1 from Session 454)

Investigated why walk-forward model gets 85% HR at edge 3+ but production BB only gets ~60%.

**Root cause: Model staleness + seasonal phase, NOT the BB pipeline.**

| Factor | Impact | Evidence |
|--------|--------|----------|
| Seasonal warm-up | -15 to -25pp | Walk-forward 2024-25: Jan=56%, Feb=70%, Mar=87% |
| Model staleness | -5 to -10pp | Production models 10-60d stale. 7d retrain = +2pp |
| BB pipeline | **+7pp** | Pipeline ADDS value — selects better picks |
| Rescue drag | -3pp | 12% of picks at lower HR |

Key findings:
- Pure edge ranking from walk-forward: 86% HR. Even random selection from edge 3+ pool gets 83%.
- Walk-forward 85% is dominated by peak months (Mar-Jun). Same-period: walk-forward 56-87% vs production 54%.
- Stale models are **confidently wrong**: production edge 5+ = 32.8% HR. Walk-forward edge 5+ = 90%+.
- 2024-25 early season dramatically worse than 2023-24 (Dec HR: 54% vs 84%). Model hugs the line (pred-line r=0.97). Not fixable with features.

### 2. Feature Analysis — NO new features recommended

- Seasonal phase: 1.75% of variance after controlling for edge. Model can't learn it from 56d window.
- Larger training windows (90d) DON'T help early season. 56d validated as optimal.
- 80+ features tested across Sessions 407-410, ALL dead ends. V12_NOVEG remains best.
- Only intervention that works: more frequent retraining.

### 3. Walk-Forward Integrity Audit — 85% HR CONFIRMED LEGITIMATE

Comprehensive audit for data leakage and inflated results:

| Test | Result | Details |
|------|--------|---------|
| Temporal leakage in features | CLEAN | All features use `game_date < current_date`. Code-verified. |
| Features 50-53 (flagged suspects) | CLEAN | Use historical prop lines, not current game. Combined importance only 5.0%. |
| Naive baseline | CLEAN | Always OVER=48.6%, random at edge 3+=49.9%. HR is 35pp above chance. |
| Seed stability | CLEAN | 5 seeds (42,7,123,456,999): 84.6%-85.5% HR. <1pp variance. |
| Feature importance | CLEAN | Top 5 (62% of importance) are all historical averages. No suspicious features. |
| DNP survivorship bias | PRODUCTION-CONSISTENT | DNP rate ~10-13%, but DNPs don't have prop lines in production either. |

Minor caveats (not disqualifying):
- Retrospective feature store regeneration gives slightly cleaner features than real-time (<1-2pp)
- 2022-23 seed season uses backfilled closing lines (only affects seed grading)
- Quality gate filters to established players (same gate in production)

### 4. Code Updates

- `bin/retrain.sh`: ROLLING_WINDOW_DAYS 42→56 (walk-forward validated)
- `ml/experiments/quick_retrain.py`: default train-days 60→56

### 4. Documentation Updates

- `docs/08-projects/current/model-management/MONTHLY-RETRAINING.md`: Complete rewrite as "Weekly Model Retraining Guide"
- `CLAUDE.md`: Added "Retraining (Session 455)" section with 7-day cadence

### 5. Analysis Script

- `scripts/nba/training/bb_pipeline_gap_analysis.py`: 8 selection strategies on walk-forward predictions

---

## Production vs Walk-Forward (March 2026)

| | Walk-Forward | Production |
|--|--|--|
| Latest retrain window | Jan 9 - Mar 5 (56d) | Jan 3 - Feb 27 (55d) |
| Data freshness | Retrained Mar 6 | 10+ days stale |
| Retrain cadence | Every 7 days | Manual, irregular |
| Feature set | V12_NOVEG only | Mixed (V9, V12, V16, LGBM, XGB) |
| Edge 3+ HR | ~87% (March) | ~54% |

Production is NOT handling this month like the walk-forward. Walk-forward retrains every 7d with 56d window. Production's newest model ends Feb 27 — missing 10 days of March data.

---

## What to Do Next

### Immediate: Retrain All Models
```bash
./bin/retrain.sh --all --enable
```

### Build Weekly Auto-Retrain CF
Current state: `retrain-reminder` alerts but doesn't retrain. Need new `weekly-retrain` CF:
- Cloud Scheduler: Monday 6 AM ET
- Logic: retrain all enabled families, 56d window, governance gates
- Slack notification on success/failure

### Prior-Season Warm-Start (Future Experiment)
CatBoost `fit(init_model=...)` supports continuing training from existing model.
Could help Nov-Dec warm-up (+10pp potential). Test in walk-forward first.

### 2025-26 Walk-Forward (Future)
Validate current-season expectations against walk-forward.

---

## Files Created/Modified

| File | Change |
|------|--------|
| `scripts/nba/training/bb_pipeline_gap_analysis.py` | NEW |
| `results/nba_walkforward/bb_gap_analysis.json` | NEW |
| `bin/retrain.sh` | Window 42→56 days |
| `ml/experiments/quick_retrain.py` | Default train-days 60→56 |
| `docs/08-projects/current/model-management/MONTHLY-RETRAINING.md` | Complete rewrite |
| `CLAUDE.md` | Added retraining section |
