# RESULT: "edge5+ is the money zone" is OVER-FALSE — high-edge OVER has no cross-season edge

**Date:** 2026-06-23 · **Status:** Closed — CORE FRAMING CORRECTION. **Method:** 5-season walk-forward
CatBoost V12_NOVEG predictions, `DiscoveryDataset(min_edge=0.0)` (N=47,585 all edges; 1,803 at edge≥3). HR by
edge bucket × direction × season; Wilson 95% CIs; 2025-26-vs-prior Fisher exact. **Breakeven ≈ 53.5%.**

## The headline
The system-wide belief "edge5+ is the money zone" (CLAUDE.md, memory) is **direction-blind and OVER-wrong.**
It is TRUE for UNDER (cross-season durable) and FALSE for OVER (a 2025-26 artifact).

### OVER — no cross-season-profitable edge band, at any level
| Band | pooled prior 4 seasons | 2025-26 | per-season prior (21-22…24-25) | Fisher |
|---|---|---|---|---|
| edge ≥ 5 | **42.1%** (N=38) | 88.5% (N=52) | 60 / 38 / 43 / 17 | **p<0.001** |
| edge ≥ 6 (floor-allowed) | **38.9%** (N=18) | 92.6% (N=27) | 50 / 33 / 40 / 33 | **p<0.001** |
| edge 3-4 | 51.5% pooled (below breakeven) | | | |

**The OVER picks the system actually publishes (edge ≥ 6, above the floor) hit 38.9% in normal seasons —
below breakeven in ALL 4 prior years.** The 2025-26 performance (92.6%) is an anomaly, not a repeatable edge.
The OVER floor of 6.0 does not make OVER profitable; it only throttles volume on a directionally-losing bet.

### UNDER — durable money zone, strengthens with edge
| Band | pooled prior | 2025-26 | per-season (21-22…25-26) | Fisher |
|---|---|---|---|---|
| edge ≥ 5 | 58.6% (N=116) | 67.4% (N=43) | 54 / 45 / 57 / 78 / 67 | p=0.363 (n.s.) |
| edge ≥ 6 | 61.0% (N=41) | 71.4% (N=21) | 44 / 60 / 61 / 78 / 71 | p=0.576 (n.s.) |
| edge 3-4 | 56.2% pooled (profitable) | | | |

UNDER is profitable across the whole edge≥3 range, cross-season, and 2025-26 is NOT significantly different
from prior — i.e. UNDER's edge is real and repeatable.

## Why (mechanism)
2025-26 had a documented scoring-environment shift (avg_actual ≈ +1K/player vs prior; see
`memory/2025-26-anomaly-rootcause.md`). The league scored above what lines/models expected, so OVER bets
systematically won — and high-edge OVER (where the model most disagreed upward) won biggest (92.6%). When the
environment normalized / market tightened (Feb-Mar 2026), OVER reverted toward its true cross-season ~39% and
the BB record collapsed Jan 73.8% → Mar 46.7%. **The collapse was not bad luck or stale models — it was a
directionally-fragile OVER book reverting to its real expectation.** UNDER held throughout.

## CAVEATS
Prior-season high-edge OVER N is small (edge≥6: 3-6/season, 18 total). The strength of the claim is the
**consistency across 4 independent prior seasons** (all below breakeven) + the p<0.001 contrast, not any single
cell. Single-model walk-forward (fleet is mostly CatBoost clones, so representative). A bet that loses in 4/4
prior seasons and wins only in the one anomalous season is not a "money zone."

## Implications & corrections
1. **Correct the core framing** (CLAUDE.md "Edge 5+ is the money zone"; memory): make it direction-specific —
   "UNDER edge≥3 is the durable money zone (strengthens with edge, cross-season). OVER has NO cross-season-
   robust edge band; its 2025-26 high-edge performance (88-93%) is a scoring-anomaly artifact (≈39% in the
   prior 4 seasons)."
2. **2026-27 posture — UNDER-dominant.** If 2026-27's scoring environment is normal (not 2025-26-like), every
   edge≥6 OVER pick is expected to LOSE (~39%). The system should treat OVER as **unproven until 2026-27 data
   confirms the scoring environment** — consider suppressing OVER harder (shadow / higher floor / require the
   scoring-environment check) rather than just gating volume at floor 6.0.
3. **This subsumes the signal trust-map:** OVER fragility isn't just the signals — it's the entire edge→OVER
   relationship. No OVER signal can be durable when high-edge OVER itself isn't.
4. **Lean the system's weight onto UNDER + edge.** UNDER edge≥6 (61% cross-season) is the most reliable lane;
   UNDER edge≥3 (56%+) is the durable base. This is where 2026-27 EV should be concentrated.
5. **Auto-halt is well-justified but for a refined reason:** in a normal season OVER won't generate the edge≥5
   volume 2025-26 did, so OVER picks will be naturally sparse — correct. The halt protects against the
   low-edge collapse; this analysis adds that high-edge OVER is *also* not to be trusted in a normal season.

## Action (NO off-season deploy change)
- Add to season-resume runbook: direction-specific edge posture + an explicit early-season OVER scoring-
  environment gate (don't trust OVER until 2026-27 shows the league is scoring above expectations).
- Correct the "edge5+ money zone" framing in memory now; flag the CLAUDE.md line for the user to update.
