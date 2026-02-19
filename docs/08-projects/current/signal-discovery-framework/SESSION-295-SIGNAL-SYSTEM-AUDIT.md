# Session 295: Signal System Comprehensive Audit

**Date:** 2026-02-18
**Algorithm Version:** `v295_direction_alignment`

## Audit Tool

`ml/experiments/signal_system_audit.py` -- 5-audit tool covering full season (Nov 2 - Feb 16):
1. Signal value-add vs pure edge
2. Direction bias per signal
3. Combo registry validation
4. Consensus bonus impact
5. Pre-filter impact assessment

## Key Findings

### Signal System Value-Add: +9.2pp HR over pure edge
- Signal-curated: **67.8% HR** vs pure edge-only: **58.6%**
- P&L delta: **+$3,270**
- Validates that the signal layer is net-positive

### combo_3way UNDER Was an Anti-Pattern (FIXED)
- OVER: **95.5% HR** (N=22)
- UNDER: **20.0% HR** (N=5)
- Fix: OVER-only direction filter added in `ml/signals/combo_3way.py`
- BQ `combo_registry`: direction changed from `BOTH` to `OVER_ONLY`, HR updated to 95.5%

### 3 New Combo Registry Entries (10 -> 13 total)

| Combo | HR | N | Weight | Direction |
|-------|-----|-----|--------|-----------|
| `volatile_under` | 73.1% | 26 | +1.0 | UNDER |
| `high_usage_under` | 68.1% | 47 | +0.5 | UNDER |
| `prop_line_drop_over` | 79.1% | 67 | +1.0 | OVER |

### V9 Champion Has OVER Bias
- OVER: **63.1% HR** vs UNDER: **54.9% HR**
- UNDER signals compensate well (see below)

### UNDER Signal Performance
| Signal | HR | Notes |
|--------|-----|-------|
| `bench_under` | 85.7% | Top standalone |
| `volatile_under` | 73.1% | New combo |
| `high_usage_under` | 68.1% | New combo |
| `self_creator_under` | 66.7% | |
| `high_ft_under` | 66.7% | |

### Consensus Bonus: Marginal
- Impact: **+0.5pp HR**, changes only **3 picks**
- Decision: Keep (not harmful), but do not invest more

### Quantile Models' Unique UNDER Picks
- HR: **80.0%** but N=10 (too small)
- Action: Monitor post-All-Star break

### Session 294 Pre-Filters: Marginal
- Impact: **+0.4pp HR**, **+$110 P&L**
- Decision: Keep (not harmful)

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/combo_3way.py` | OVER-only direction filter |
| `ml/signals/combo_registry.py` | 3 new entries, combo_3way direction fix |
| `ml/signals/aggregator.py` | Algorithm version bump to `v295_direction_alignment` |
| `ml/experiments/signal_system_audit.py` | NEW -- 5-audit comprehensive tool |
| `CLAUDE.md` | Updated combo count (10 -> 13), combo_3way notes |
