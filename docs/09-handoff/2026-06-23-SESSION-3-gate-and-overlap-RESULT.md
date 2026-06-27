# Session 3 (2026-06-23) — two gated confirmatory tests from the action list

Follows `2026-06-23-SESSION-2-research-HANDOFF.md`. Closes two open action items WITHOUT
reopening broad mining. Both reuse the formal discovery infra (`DiscoveryDataset` 5-season
walk-forward + `combo_tester.define_signal_conditions`). Scripts:
- `scripts/nba/training/discovery/high_line_under_overlap.py`
- `scripts/nba/training/discovery/over_scoring_env_gate.py`

---

## 1. `high_line_under` overlap analysis → MODESTLY ADDITIVE (add at low weight)

**Action item was:** "Consider `high_line_under` (line≥25); passes the gate strongly (59.9%,
5/5, p=0.0007) — check overlap with existing UNDER signals before adding."

**Standalone (edge3+, UNDER, line≥25):** 59.9% HR, N=506, **5/5 seasons above breakeven**,
p=9e-05, boot CI [55.6, 63.9]. Confirms the gate result.

**Overlap with existing real UNDER signals** (column proxies from `combo_tester`): **68.6%
(347/506) of high_line_under picks already fire ≥1 existing UNDER signal** — dominated by
`home_under` (48% co-fire), then line-movement signals (`bp_dropped_under` 18%,
`sharp_line_drop` proxy 9%, `line_drop_under` 8%) and `hot_3pt_under` (15%).
`volatile_starter_under` does NOT overlap (its proxy is line-capped 18–25).

**The decision split — orthogonal subset (fires NO existing UNDER signal):**
- N=159 (**31% of the signal; 16% of all edge3+ UNDER picks**), HR **57.9%**, above breakeven
  in **4/5 seasons** (56/62/61/60/**51**). Single-test p=0.063, but per-methodology the
  cross-season 4/5 is the reliable evidence, not the single cell.
- Weakest season is 2025-26 (51%, N=41) — the SAME not-a-recency-artifact pattern as
  `b2b_fatigue_under`, the opposite of the fragile OVER signals. Reinforces validity.

**Verdict:** genuinely additive but bounded. About a third of its picks are new coverage at
~58% HR; the other two-thirds duplicate `home_under` (it's partly "home_under for away
stars"). **Recommendation (season-open, sign-off): add `high_line_under` to
`UNDER_SIGNAL_WEIGHTS` at a MODEST weight (~1.5), gated line≥25.** Don't over-weight — much
of its volume is already captured. Main value is lifting orthogonal star-UNDER picks to
real_sc≥1 so they can pair into real_sc≥2 (the `under_low_rsc` gate). Not a blockbuster;
a clean, durable, low-risk add.

---

## 2. OVER scoring-environment gate → **DO NOT BUILD (negative result; escape hatch refuted)**

**Action item was:** "Treat OVER as unproven; add an early-season scoring-environment gate
(only lean into OVER if the league is scoring above expectation like 2025-26)."

**Designed + backtested two pre-game-safe regime metrics**, each a trailing-10-game-day,
lagged (no-leakage) league aggregate:
- **scoring env** = mean(`actual_points − line`) — are players beating their lines lately?
- **edge-availability** = mean(`|edge|`) — the research's "2025-26 = bigger edges that paid".

**Neither separates the one season OVER paid from the four it didn't.** Season-level realized
scoring env is FLAT and does not track OVER HR:

| season | mean(act−line) | OVER e3+ HR | trailing edge-env |
|---|---|---|---|
| 2021-22 | +0.18 | 48.9% | 1.08 |
| 2022-23 | +0.18 | 46.5% | 1.03 |
| 2023-24 | +0.10 | 47.7% | 1.14 |
| 2024-25 | **+0.36** | 50.7% | 1.07 |
| 2025-26 | +0.16 | **71.5%** | 1.08 |

2025-26 (OVER 71.5%) had a LOWER scoring env than 2024-25 (OVER 50.7%) and an average
edge-env. **Gated pooled OVER HR (env≥0) = 55.0%, but per-season it's 49/50/48/51/71** —
sub-breakeven in all four normal seasons, ~71% only in 2025-26. The "55% pooled" is entirely
the 2025-26 cell; the metric is not doing the separating, the calendar is. The edge-env gate
is identical (HOT 53.3% vs COLD 55.1%, no spread). A stricter env≥+0.5 threshold makes OVER
*worse* (48%).

**Conclusion:** there is no simple, forward-deployable scoring-environment regime metric that
turns OVER back on profitably. 2025-26 OVER outperformance is a within-season,
not-pre-detectable phenomenon (per-pick edge magnitude — already captured by the static edge
floor — not a league-wide regime). **This REFUTES the proposed escape hatch and SIMPLIFIES
the season-open posture:** keep OVER behind the static 6.0 edge floor as a pure volume
throttle, treat 2025-26 OVER as non-repeatable, and do NOT spend effort building a regime
gate. Removes an action item rather than adding one.

---

## Net effect on the 2026-27 action list
- **`high_line_under`:** **add at weight 1.0 as a PAIRING signal (NOT 1.5, NOT solo-rescue)**
  — see the post-review correction below.
- **OVER scoring-env gate:** **struck from the list** — backtested and refuted. OVER stays
  unproven behind the edge floor; no gate to build.
- Reinforces the core thesis: UNDER + edge is the durable engine; OVER has no
  forward-detectable profitable regime.

---

## POST-REVIEW CORRECTION (34-agent review + 2 RUN_NOW audits, same day)

A 34-agent adversarial review audited every 2026-06 result. It flagged the "add at 1.5"
recommendation above as OVERSTATED (live `star_line_under` is 35.3% HR, N=17 this season,
already flagged "do NOT graduate"). Two cheap offline RUN_NOW audits followed
(`scripts/nba/training/discovery/runnow_under_audits.py`):

**Audit 1 — `under_low_rsc>=2` gate: KEEP, do not relax.** Reconstructed real_sc on the
5-season cache. Pooled `rsc=1` (60.2% HR, ROI +15%, boot CI excludes 0) is a TWO-SEASON
mirage — only **2/5 seasons above breakeven** (52/42/64/51/75). `rsc>=2` is the robust
bucket: **5/5 seasons** (58.8% HR, ROI +12.2%). `rsc=1` at edge3-5 (the band the gate
blocks) is only 3/5. The much-thrashed gate is correctly calibrated; relaxing it imports
single-season losers. **Resolved: keep `under_low_rsc` at >=2.**

**Audit 2 — `high_line_under` marginal P/L → add at 1.0 as a PAIRING signal.** The orthogonal
subset's marginal ROI is +10.5% but **bootstrap CI [-4.0%, +24.4%] includes zero**, weakest
in 2025-26 (51%, N=41). The orthogonal edge3-5 picks (N=126) do NOT become best bets alone —
they're blocked by the (now-confirmed) `rsc>=2` gate. So high_line_under's real value is as
the SECOND signal that lifts an existing `rsc=1` star-UNDER into the robust `rsc=2` bucket —
which justifies a modest **weight 1.0, kept OUT of RESCUE_SIGNAL_PRIORITY** (its solo edge5+
lane is thin/inconsistent: N=33, 45% in 2025-26). Not 1.5, not a rescue tier.

## POST-REVIEW WORTH_TRYING tests (formal gate) — one new validated signal

Ran the review's cross-season-validatable WORTH_TRYING candidates through the mandatory gate
(`scripts/nba/training/discovery/runnow_worth_trying.py`):

- **`slow_pace_under` (opponent_pace<=99 raw, UNDER, edge3+) → PASSES THE GATE.** N=218,
  **58.7% HR (+7.2pp)**, p=0.019, bootstrap CI [0.523,0.654] excludes baseline, cross-season
  **4/4 above baseline, CV=0.037** (58/61/56/62), **BH-FDR adj_p=0.039 significant**. Strict
  <=98 variant FAILS (N=116, 55.2%, CI includes baseline) — the edge sits at the <=99 line.
  **Recommendation: promote shadow→active at 2026-27 open (sign-off), weight ~1.5–2.0,** pending
  live N>=30. A genuine new durable UNDER signal. (Aside: combo_tester's `fast_pace_over` proxy
  uses `opponent_pace>=0.75` but pace is RAW 91–111 here, so that OVER proxy never fires — a
  latent combo-tester bug, not in this UNDER test.)
- **`b2b x high_line x home` 3-way → INSUFFICIENT (N=46 < 100).** As predicted: individuals all
  strong (b2b 63.2%, high_line 59.9%, home 58.5%) but rarely co-occur. No validatable synergy;
  individuals already capture the edge separately. No combo to add.
- **`stars_out>=2 UNDER` → DROPPED.** `star_teammates_out` is 0% populated 2021-25, 100% only
  2025-26 — the SAME single-season coverage artifact as `is_b2b`. Cannot be cross-season
  validated (the review's "data_confirmed" was wrong; confirmed here).

**Headline-number caveats the review surfaced (carry forward):** UNDER-only "+9.4% ROI" is
+4.9% ex-2025-26; OVER edge>=6 "38.9%" is direction-robust but magnitude-fragile (N=18) — say
"unproven, not proven-bad"; the "58% UNDER / 73% OVER March WF" figure (broad-research doc +
memory) could NOT be verified in any source — drop it; 14d cadence edge5+ mixed OVER+UNDER and
needs a direction-split before adoption. Features: **add none** (no new data source is in the
cache; diversity levers dead). Full review output retained in the session transcript.
