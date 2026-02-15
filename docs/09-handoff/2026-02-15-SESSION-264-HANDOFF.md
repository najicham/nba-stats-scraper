# Session 264 Handoff — COLD Model-Dependent Signal Fix

**Date:** 2026-02-15
**Scope:** Small, focused code change — 2 files, 24 lines added
**Status:** Committed and pushed (`03c715a5`). Auto-deploys with next Cloud Run build touching `shared/` or `predictions/`.

---

## What Changed

### Problem

Signal health weighting (Session 260) applied 0.5x multiplier to ALL COLD signals. But model-dependent signals (`high_edge`, `edge_spread_optimal`, `edge_spread_confident`) are **downstream of model predictions** — when the model is decaying, these signals are broken by definition.

Feb 2 data proved this: model-dependent signals hit 5.9-8.0% during model decay, while behavioral signals (`minutes_surge`) went 3/3 (100%). Treating both at 0.5x was too generous for model-dependent signals.

### Fix

**`ml/signals/aggregator.py`** — `_get_health_multiplier()` (line ~195):
- COLD + model-dependent signal → **0.0x** weight (was 0.5x)
- COLD + behavioral signal → **0.5x** weight (unchanged)
- HOT → 1.2x (unchanged)
- NORMAL → 1.0x (unchanged)

The method checks `is_model_dependent` from the signal health dict first, with a fallback to the static `MODEL_DEPENDENT_SIGNALS` frozenset if the BQ field is missing.

**`ml/signals/signal_health.py`** — `get_signal_health_summary()` (line ~267):
- Now includes `is_model_dependent` in the query and output dict so the aggregator can distinguish signal types without hardcoding.

### What Did NOT Change

- HOT (1.2x) and NORMAL (1.0x) multipliers — untouched
- Combo registry classifications — untouched
- `MODEL_DEPENDENT_SIGNALS` set in `signal_health.py` — already existed
- `is_model_dependent` field in `signal_health_daily` BQ table — already existed
- Fail-safe behavior: missing signal health still defaults to 1.0x

---

## Effect on Picks

When the model is in COLD regime:

| Signal Type | Example | Old Weight | New Weight |
|-------------|---------|-----------|-----------|
| Model-dependent | `high_edge` | 0.5x | **0.0x** |
| Model-dependent | `edge_spread_optimal` | 0.5x | **0.0x** |
| Behavioral | `minutes_surge` | 0.5x | 0.5x |
| Behavioral | `cold_snap` | 1.0x (NORMAL) | 1.0x (NORMAL) |

**Key consequence:** A pick with only `high_edge` + `edge_spread_optimal` during model decay gets weighted signal count of **0.0**, falling well below `MIN_SIGNAL_COUNT=2` — it gets excluded entirely. A pick with `high_edge` + `minutes_surge` gets 0.0 + 0.5 = 0.5, also excluded. Only picks with sufficient behavioral signal support survive.

---

## Verification

Inline test confirmed all cases:
```
high_edge (COLD, model-dep):           0.0x  ✓
edge_spread_optimal (COLD, model-dep): 0.0x  ✓
minutes_surge (COLD, behavioral):      0.5x  ✓
cold_snap (NORMAL, behavioral):        1.0x  ✓
high_edge + minutes_surge weighted:    0.5   ✓ (below MIN_SIGNAL_COUNT)
minutes_surge + cold_snap weighted:    1.5   ✓ (passes MIN_SIGNAL_COUNT)
Fallback (no is_model_dependent):      0.0x  ✓ (uses static set)
```

No existing unit tests for these modules. The change is straightforward and verified manually.

---

## Review Checklist

- [ ] Confirm `MODEL_DEPENDENT_SIGNALS` set in `signal_health.py:40-43` covers all model-dependent signals (currently: `high_edge`, `edge_spread_optimal`, `combo_he_ms`, `combo_3way`, `dual_agree`, `model_consensus_v9_v12`)
- [ ] Confirm `edge_spread_confident` (mentioned in session prompt) should be added to `MODEL_DEPENDENT_SIGNALS` if it exists as a signal tag
- [ ] Verify the aggregator import of `MODEL_DEPENDENT_SIGNALS` doesn't create a circular import issue (tested locally — imports clean)
- [ ] Consider whether `combo_he_ms` and `combo_3way` (combo signals containing model-dependent components) should also be zeroed — current code zeroes them since they're in `MODEL_DEPENDENT_SIGNALS`

---

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | COLD model-dep → 0.0x, import `MODEL_DEPENDENT_SIGNALS`, docstring update |
| `ml/signals/signal_health.py` | `get_signal_health_summary()` returns `is_model_dependent` |

---

## START-NEXT-SESSION-HERE Updates Needed

- Known issue "COLD model-dependent signals at 0.5x may be too generous" → **RESOLVED Session 264**
- Priority 2 item "COLD model-dependent signals at 0.0x" → **DONE Session 264**
- Signal health weighting line → update to "COLD behavioral=0.5x, COLD model-dependent=0.0x"
