# Session 275 Handoff — Signal Cleanup & Combo Registry Update

**Date:** 2026-02-16
**Focus:** Signal system optimization — remove underperformers, add UNDER combos, validate
**Result:** Aggregator HR improved from 60.3% to **73.9%**

---

## What Was Done

### 1. Removed 10 Underperforming Signals from Registry

**File:** `ml/signals/registry.py`

**Below breakeven (4):** These signals gave undeserved 2-signal qualification
- `hot_streak_2` — 45.8% AVG HR, N=416 (fired on 19% of picks!)
- `hot_streak_3` — 47.5% AVG HR, N=182
- `cold_continuation_2` — 45.8% AVG HR, N=130
- `fg_cold_continuation` — 49.6% AVG HR, catastrophic W4 decay

**Never fire (6):** Dead code
- `pace_mismatch`, `points_surge_3`, `home_dog`, `minutes_surge_5`, `three_pt_volume_surge`, `scoring_acceleration`

**Impact:** Registry now 18 signals (was 28). Import comments preserved for traceability.

### 2. Updated Combo Registry (Python + BigQuery)

**File:** `ml/signals/combo_registry.py`

Added 3 new SYNERGISTIC entries:
- `bench_under` — 76.9% HR, score_weight=1.5, PRODUCTION
- `high_ft_under` — 64.1% HR, score_weight=0.5, CONDITIONAL
- `b2b_fatigue_under` — 85.7% HR, score_weight=1.0, CONDITIONAL

Updated existing entries with fresh backtest stats:
- `blowout_recovery` — HR 58.0→56.9, N 50→112
- `3pt_bounce` — HR 69.0→74.9, N 29→28

**BigQuery:** 3 new rows inserted into `signal_combo_registry` (verified).
**Total:** 10 combo entries (8 SYNERGISTIC, 2 ANTI_PATTERN).

### 3. Backtest Validation

Post-cleanup backtest (`signal_backtest.py --save`):

| Window | Picks | HR | ROI |
|--------|-------|----|-----|
| W2 (Jan 5-18) | 50 | **80.0%** | +52.7% |
| W3 (Jan 19-31) | 65 | **78.5%** | +49.8% |
| W4 (Feb 1-13) | 57 | **63.2%** | +20.6% |
| **AVG** | — | **73.9%** | — |

Key overlap combos:
- `bench_under+model_health`: N=129, **76.7% HR** — dominant signal
- 7-way combo (combo_3way+...+rest_advantage_2d): N=20, **95.0% HR**

### 4. Documentation Updates

| Doc | Change |
|-----|--------|
| `CLAUDE.md` | Added full signal inventory section (18 active, 10 removed), updated combo count |
| `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md` | Complete rewrite with actual backtest HRs |
| `docs/02-operations/system-features.md` | Signal section updated (18 signals, combos, health) |
| `docs/09-handoff/START-NEXT-SESSION-HERE.md` | Current state refresh |
| `docs/08-projects/summaries/2026-02.md` | Added Sessions 253-275 work |

---

## Files Changed

| File | Lines Changed | What |
|------|--------------|------|
| `ml/signals/registry.py` | -20, +15 | Removed 10 signals (kept comments) |
| `ml/signals/combo_registry.py` | +20 | 3 new SYNERGISTIC entries, updated stats |
| `CLAUDE.md` | +30 | Signal inventory section, combo count |
| Signal inventory doc | Full rewrite | 18 active, 10 removed, combos, backtest |
| System features doc | +40 | Signal section expanded |
| Start-here doc | Full rewrite | Current state, priorities |
| Feb summary doc | Full rewrite | Sessions 253-275 coverage |

---

## What's Next

### Priority 1: Feb 19 Readiness
- Run `/validate-daily` morning of Feb 19
- Verify signal tags no longer include removed signals
- Check `bench_under` appears in live picks

### Priority 2: Post-Break Monitoring
- Track aggregator performance on live out-of-sample data
- Validate `bench_under` standalone HR holds above 70%
- Re-evaluate WATCH signals after 2+ weeks

### Priority 3: Retrain (URGENT)
- V9: 39+ days stale — `./bin/retrain.sh --promote`
- V12: 16+ days stale
- Fresh models + clean signals = strongest system yet

### Priority 4: Multi-Model Aggregation
- Route UNDER signals to Q43/Q45 for model-aware scoring
- Per-family signal profiles (option C from Session 273 analysis)

---

## Key Design Decisions

1. **Keep ESO in registry** despite 67.2% standalone — needed for anti-pattern detection
2. **Keep cold_snap** despite N=0 in recent windows — seasonal/conditional, high HR when active
3. **Score weights:** bench_under=1.5 (top standalone), b2b_fatigue=1.0 (small N caution), high_ft=0.5 (conditional)
4. **Direction filter on all UNDER combos** — prevents boosting OVER picks with UNDER signals

---

## Verification Commands

```bash
# Verify 18 signals in registry
PYTHONPATH=. python -c "from ml.signals.registry import build_default_registry; r = build_default_registry(); print(f'Signals: {len(r.all())}')"

# Verify BQ combo entries
bq query --use_legacy_sql=false 'SELECT combo_id, classification, status, hit_rate FROM nba_predictions.signal_combo_registry ORDER BY score_weight DESC'

# Run backtest
PYTHONPATH=. python ml/experiments/signal_backtest.py --save

# Check live signal tags (post-Feb-19)
bq query --use_legacy_sql=false 'SELECT signal_tag, COUNT(*) FROM nba_predictions.pick_signal_tags, UNNEST(signal_tags) AS signal_tag WHERE game_date = CURRENT_DATE() GROUP BY 1 ORDER BY 2 DESC'
```
