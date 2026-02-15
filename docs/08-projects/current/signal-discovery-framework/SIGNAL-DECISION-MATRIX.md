# Signal Decision Matrix — Post-Comprehensive Testing

**Date:** 2026-02-14
**Sessions:** 256 + 257
**Tests Completed:** Tier 1 (4/4), Tier 2 (3/3), Tier 3 (3/3) — ALL COMPLETE

---

## Decision Matrix

| Signal/Combo | Standalone HR | Best Combo HR | Temporal Stable? | Home/Away Delta | Position Effect | Team Tier | OVER/UNDER | Final Decision | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| **3way_combo** (HE+MS+ESO) | N/A | **88.2% (17)** | 92.3%→80% | No split | All strong | All strong | OVER only | **PRODUCTION** | **HIGH** |
| **high_edge+minutes_surge** | N/A | **68.8% (16)** | 66.7%→75% | Away +21% | Guards slight | Middle best | OVER only | **PRODUCTION** | **HIGH** |
| high_edge+prop_value | N/A | 74.2% (31) | 95.8%→**0.0%** | Home +73% | Guards 71% / Fwd 32% | Mid/Top | OVER 82% / UNDER **4%** | **CONDITIONAL** | HIGH (gated) |
| 3pt_bounce | 64.7% (17) | — | Stable | Home +45% | Guards 69% | All tiers | OVER only | **KEEP** | HIGH |
| cold_snap | 61.1% (18) | — | Non-monotonic | **Home +62%** | Fwd 78% | Top 83% | Slight UNDER | **KEEP (HOME)** | HIGH |
| blowout_recovery | 53.1% (113) | — | Stable | Away +18% | **Centers 20%** | Bottom 59% | Marginal | **KEEP (no C)** | MODERATE |
| high_edge only | 43.8% (89) | — | 86.4%→30.9% | — | — | — | — | **NEVER STANDALONE** | HIGH |
| minutes_surge only | 48.6% (303) | — | Stable | — | — | — | — | **COMBO ONLY** | HIGH |
| HE+edge_spread 2-way | N/A | **31.3% (179)** | 75.9%→24.8% | Bad everywhere | — | — | UNDER 27% | **ANTI-PATTERN** | **HIGH** |

---

## Conditional Filter Requirements

### high_edge + prop_value — FULL GATE STACK

```
REQUIRED (ALL must be true):
  1. days_since_training <= 14    (0.0% HR when stale)
  2. is_home = TRUE               (100% Home vs 26.8% Away)
  3. position IN ('PG', 'SG')     (71.4% Guards vs 31.6% Forwards)
  4. recommendation = 'OVER'       (81.5% OVER vs 3.8% UNDER)

OPTIONAL (boosts confidence):
  5. team_tier IN (1, 2)          (80-92% vs 57% bottom)
  6. matchup_type = 'same_conf'   (91.7% vs 63.2% cross-conf)
```

**Expected with all gates:** Very few picks but ~90%+ HR.
**Without gates:** Aggregate 74.2% but hides catastrophic subsegments.

### cold_snap — HOME-ONLY

```
REQUIRED:
  1. is_home = TRUE               (93.3% Home vs 31.3% Away)

OPTIONAL:
  2. team_tier = 1                (83.3% top teams)
  3. position IN ('SF', 'PF')    (77.8% forwards)
```

### blowout_recovery — EXCLUDE CENTERS + NO B2B

```
REQUIRED:
  1. position NOT IN ('C')        (20.0% Centers vs ~58% others)
  2. rest_days >= 2               (46.2% B2B vs 53-62% with rest)

OPTIONAL:
  3. is_home = FALSE              (63.5% away vs 45.5% home)
  4. team_tier = 3                (58.8% bottom teams)
  5. matchup_type = 'cross_conf'  (61.0% vs 44.4% same-conf)
  6. rest_days >= 3               (62.5% with extra rest)
```

### 3pt_bounce — GUARDS + HOME

```
RECOMMENDED:
  1. position IN ('PG', 'SG')    (69.2% guards vs 50% forwards)
  2. is_home = TRUE               (77.8% home vs 33.3% away)
```

---

## Anti-Pattern Registry

| Anti-Pattern | HR | ROI | N | Why It Fails | Confidence |
|---|---|---|---|---|---|
| `high_edge + edge_spread 2-way` | 31.3% | -37.4% | 179 | Both measure confidence → redundancy | **HIGH** |
| `high_edge_only` (no 2nd signal) | 43.8% | -12.4% | 89 | No validation signal | HIGH |
| `high_edge+prop_value` UNDER | 3.8% | -92.3% | 26 | Model can't identify downside | **HIGH** |
| `high_edge+prop_value` stale model | 0.0% | -100% | 29 | Model edge inverts when stale | **HIGH** |
| `blowout_recovery` Centers | 20.0% | -60% | 15 | Center production too matchup-dependent | MODERATE |
| `blowout_recovery` B2B | 46.2% | -7.6% | 13 | Fatigue compounds blowout effect | MODERATE |
| `cold_snap` Away | 31.3% | -37.5% | 16 | Unknown mechanism | HIGH |
| `ESO+HE+PVG` (3-way) | 37.8% | -24.4% | 45 | Near-zero avg edge (0.02), inflated signals | HIGH |

---

## Signal Families (Updated)

### Family 1: Universal Amplifiers
- `minutes_surge` — Boosts ANY edge signal. Independent of model freshness.
- **Role:** Validation layer ("opportunity is real")

### Family 2: Value Signals (Model-Dependent)
- `high_edge`, `prop_value_gap_extreme`, `edge_spread_optimal`
- **Risk:** Collapse when model is stale
- **Rule:** ALWAYS combine with Family 1 amplifier

### Family 3: Bounce-Back Signals (Decay-Resistant)
- `cold_snap` (home-only), `blowout_recovery` (no centers), `3pt_bounce` (guards+home)
- **Key:** Player behavior signals, less coupled to model accuracy
- **Rule:** Apply conditional filters per testing results

### Family 4: Redundancy Traps
- `high_edge + edge_spread` (2-way) — Both measure the same thing
- **Rule:** NEVER combine signals from the same measurement dimension

---

## Deployment Priority

| Priority | Signal | Expected HR | Expected Volume | Action |
|---|---|---|---|---|
| P0 | 3way_combo | 88.2% | 1-2/week | Deploy immediately |
| P0 | high_edge+minutes_surge | 68.8% | 3-4/week | Deploy immediately |
| P1 | cold_snap (home-only) | 93.3% | 3-4/month | Deploy with filter |
| P1 | 3pt_bounce (guards+home) | 69-78% | 3-4/month | Deploy with filter |
| P2 | blowout_recovery (no centers) | ~58% | 8-10/week | Deploy with filter |
| P3 | high_edge+prop_value (full gates) | 90%+ | <1/week | Deploy when model fresh |
