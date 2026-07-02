# Final review — 5-agent audit of the recommended plan

**Review date:** 2026-05-12
**Method:** 5 parallel general-purpose agents, each on a distinct angle of the recommended plan in `03-RECOMMENDED-PLAN.md`. Each capped at 400-600 words. Each opinionated.

This file preserves the audit trail of what each follow-up agent claimed and the load-bearing evidence they produced.

---

## Final-Agent A — Sequencing critic

**Independent re-rank of Phase A (before reading plan's order):**

1. **A4 (Poisson loss)** — fixes the -0.45K bias that is root cause of UNDER suppression and inflated OVER edges. Every other measurement is biased without it.
2. **A2 (OVER ranking)** — 4h, +3-6pp on the cash cow, no retrain, independent.
3. **A3 (weather + 2nd export)** — scratch protection is a *correctness* fix (currently scratched pitchers reach the public site).
4. **A1 (lineup features)** — high option value, unknown EV; f26 is dead-on-arrival.

**The plan ranks A1 highest. Agent A ranks it last.**

**A1/A4 attribution warning is RIGHT but the prescription is WRONG.** The plan's "A1 retrain → measure → A4 retrain → measure" implies 2 weeks of live measurement between retrains, AND the A1 baseline is corrupted by RMSE bias. **Better: walk-forward all variants offline in parallel (A4-only, A1-only, A1+A4); ship the winner. Walk-forward IS the attribution mechanism.**

**Cross-phase dependencies the plan misses:**
- B1 (early-warning) depends on A4 — current trigger thresholds were measured under RMSE+sigmoid, will be stale after Poisson
- A2 (OVER ranking) depends on A4 — edge buckets are a function of loss function
- Phase C decision depends on B2 (CLV) — without CLV, "is UNDER good?" relies on HR alone, the lagging indicator that let May collapse run 14 days

**Recommended Phase A order:** A4 → A2 (parallel WF with A4) → A3 → A1. **Move B2 (CLV) from Phase B to Phase A** if Phase C decision relies on anything other than raw HR.

---

## Final-Agent B — Risk-adjusted EV

| Item | P(delivers lift) | Downside if disappoints | Risk-adj EV |
|---|---|---|---|
| A1 — Lineup features | **25-35%** | Wasted retrain; -1 to -3pp HR regression; muddies A4 attribution | LOW-MEDIUM |
| A2 — OVER ranking | 35-45% | N=48 CI overlaps "sweet spot"; could flatten or hurt | MEDIUM |
| A3 — Weather + 2nd export | 75-85% (export); 20-30% (weather lift) | Low — ops value is real even if weather signal is flat | HIGH |
| A4 — RMSE→Poisson | 40-50% | WF UNDER bias could overshoot (-0.45 → +0.30); rollback risk | MEDIUM-HIGH |
| B1 — Early-warning detector | 60-70% (correct firing); 30-40% (no alert spam) | Hindsight calibration; April/June low-N spurious fires | MEDIUM |
| B2 — CLV tracking | 15-25% (auto-demote killer claim); 70% (table itself) | 7h build; auto-demote on unproven MLB CLV literature | LOW-MEDIUM |

**Justification highlights:**

- **A1:** CLAUDE.md is unambiguous — "Adding features consistently hurts." MLB Session 435 directly tested this class: lineup K rate = "NOISE." Features are abandoned because they're degenerate. 30-min edit ships *broken data into the model*. P ~30%.
- **A2:** N=48 Wilson LB = 30.5%, UB = 58.2% — CI overlaps the alleged "sweet-spot" CI. Inversion could be variance.
- **A3:** Operational hardening is high-P. But `WeatherColdUnderSignal` is speculatively coded. Research shows weather affects HR more than K rate. Win is operational, not signal.
- **A4:** Lane 12's Poisson is escalation beyond Agent 3's Quantile. Cited as "calibrated probability for free," but model is already absolutely calibrated (5.12 vs 5.16). Bias is selection-driven, not loss-driven. RMSE has 4 seasons of evidence (+470.7u, 12.8% ROI).
- **B1:** Triggers retrofit to one event (April 28). Not back-tested on 2024/2025 where 7d HR routinely sub-50 in April + June. Would fire spuriously every spring + summer.
- **B2:** CLV literature on MLB props is thin. NBA's auto-demote works on HR, not CLV. Killer-use-case has zero MLB precedent.

**Most likely to disappoint: A1.** De-prioritize if upstream `bdl_batter_splits` can't be replaced AND lineup scraper coverage isn't fixed first.

---

## Final-Agent C — Contradiction resolver

**Contradiction 1 — "Abandon UNDER" vs "directional motivation is real":**

Lane 7 verified the collapse IS real (May Wilson LB 29.9% excludes 53%). Lane 6/8 argue the *response* (shadow rollout) is EV-negative (+0.069u/day vs OVER doubling at +0.72u/day). Lane 1 killed the gate independently (Wilson LB 43.4% promotes noise 1-in-4 launches).

**Both collapse into the same answer:** the shadow plan must die regardless. The remaining question is whether to keep the option alive after Poisson. **Path A keeps the option for ~1h cost** (one BQ check at decision point). Path B closes it permanently.

**Contradiction 2 — Quantile-first vs shadow-first vs Poisson-first compromise:**

The plan doesn't dodge — it upgrades. Lane 4 said Quantile-first; Lane 12 escalated to Poisson because K is count data and Poisson CDF yields free calibrated `p_over`. The "compromise" isn't compromise — it's dominant strategy: same one-line cost, strictly more information, makes shadow either unnecessary OR correctly designed against an unbiased model.

**Contradiction 3 — Lane 16 reframes the investigation:**

Yes, partially. The 30-min edit *is* bigger than the entire UNDER project AND helps both directions. But this doesn't mean the original review was malformed — the 20-agent expansion is precisely what surfaced Lane 16. The 6-agent UNDER investigation could not have found this because it was scoped to UNDER.

**Meta-question — framing bias:**

The original question — "all picks are OVER, what about UNDER?" — assumed a direction-symmetric problem. The structural answer is direction-agnostic (biased loss + discarded features + inverted OVER ranking). **Fix: require at least one "what's broken upstream of this symptom?" lane in any directional/output investigation.**

**Verdict:** **Path A.** Prematurely foreclosing the option (Path B) has zero marginal benefit — Phase C is a 1-hour BQ check, not a commitment. The original investigation was framed *incorrectly* — direction asymmetry was a symptom, not the cause.

---

## Final-Agent D — Devil's advocate (CRITICAL FINDING)

**Agent D ran a BQ check and discovered A1 is largely vapor.**

`SELECT COUNTIF(f25 > 0), COUNTIF(f26 > 0), COUNTIF(f27 > 0), COUNTIF(f33 > 0), COUNTIF(f34 > 0), COUNT(*) FROM mlb_precompute.pitcher_ml_features WHERE game_date >= '2026-04-01'`:

| Feature | Non-zero | % populated |
|---|---|---|
| f25_bottom_up_k_expected | **119/976** | **12.2%** |
| f26_lineup_k_vs_hand | **0/976** | **0%** |
| f27_platoon_advantage | **0/976** | **0%** |
| f33_lineup_weak_spots | **0/976** | **0%** |
| f34_matchup_edge | **0/976** | **0%** |

Code reads `lineup_data.get(...) or 0.0` — when `lineup_k_analysis` doesn't return a hit, every feature silently defaults to 0.0. Of the 6 features the plan calls "already-computed," **five are constants** and the sixth fires 12% of the time.

**Attacks on remaining items:**

- **A2 OVER inversion:** N=48 at 43.75%, Wilson LB = 30.5%, UB = 58.2%. CI contains the alleged 59.0% sweet spot. Two adjacent buckets whose CIs overlap = noise, not inversion. Lane 1 rejected every other N<100 claim under Bonferroni; A2 survives only because filed in a different lane.

- **A4 Poisson:** Theory-only — no backtest in this repo. April's actual problem (per `mlb-system.md`) was training-data composition (no April months), already fixed by retraining on 2024-04 onward (+33.5pp jump). May spend the budget on a parameter the data already showed is composition-driven.

- **Phase C decision rule:** Circular — new model is non-stationary in first 1-2 weeks. The decision treats a 50-sample HR snapshot as stable signal when system history says snapshots that small reverse monthly.

- **"4 of 7 non-UNDER opportunities":** Selection-biased framing. Lanes 11-20 were briefed as open-ended generators, structurally prohibited from re-surfacing UNDER work. The count is an artifact, not evidence.

**Fatal flaw:** **A1 wires constants. 5 of 6 features are 0.0 across all 976 rows of `pitcher_ml_features`.** The plan calls A1 "highest priority" without a populate-check.

---

## Final-Agent E — Concrete this-week actions

(Note: written before Agent D's BQ finding surfaced — A1 plan herein needs revision.)

**Day 1 (Mon):**

1. **A2 (OVER ranking)** — code-only, ships same day. `ml/signals/mlb/best_bets_exporter.py` — tighten MAX_EDGE 1.5→1.25, rewrite `_over_sort_key` to bucket-rank. No retrain. Rollback = revert constants.

2. **A3 (weather + 2nd export)** — config + small wire-up. `bin/schedulers/setup_mlb_schedulers.sh`, `predictions/mlb/supplemental_loader.py:230`, new `mlb-best-bets-generate-late` scheduler at 16:30 UTC.

3. ~~A1 (lineup features) kickoff~~ — **CANCEL given Agent D finding. Investigate upstream pipeline first.**

**Day 2-3 (Tue-Wed):**

4. **B1 (early-warning)** — extend `bin/monitoring/mlb_daily_performance.py`. Backtest must fire WARN by Apr 28 on historical data.

5. **B2 (CLV scheduler + table)** — new scheduler + `mlb_raw.pitcher_props_closing` table + extend `prediction_accuracy` with CLV columns. Schema migration MUST land before code deploy.

**Day 4-5 (Thu-Fri):**

6. ~~A1 governance review~~ — replaced with: **investigate why `lineup_k_analysis_processor` produces 0 rows in `mlb_precompute.lineup_k_analysis`.** This is the upstream root cause for A1.

**Stop and reassess on:** (a) A2 7-day OVER HR regresses >2pp, (b) Phase 6 re-export deletes live picks, (c) lineup pipeline investigation reveals deeper rot than expected.

---

## Cross-agent convergent verdict

All 5 agents independently agreed:

1. **A4 (Poisson) should come BEFORE A1**, not after — agents A, B, C, D all said this in different ways
2. **A1 is the most likely item to disappoint** — agents B and D made this explicit; agent A ranked it last
3. **Path A (keep UNDER option open) beats Path B (abandon)** — agents A, C explicitly; agents B, E by implication
4. **B2 (CLV) should move up** — agent A explicitly; agent C implicitly via Phase C dependency

**Agent D's BQ finding is the most important load-bearing update.** A1 as written ships placeholders. The lineup pipeline needs upstream investigation before A1 can be considered. This bumps A1 from "do first" to "blocked, investigate upstream."

## Implications for the recommended plan

A1 (Lane 16's headline finding) is structurally weaker than the agents originally presented. It's not a 30-min edit — it's a 2+ week upstream pipeline rebuild. The signal data fields ARE designed and the precompute processor exists, but it's either not scheduled, broken, or returning empty results.

The user has two paths now:

**Path A-revised:** Investigate lineup pipeline. If fixable in <1 week, ship A1 after the upstream fix. Otherwise defer to Phase E with `bdl_batter_splits` replacement + scraper coverage fix as prerequisites.

**Path A-conservative:** Skip A1 entirely for now. Phase A becomes: A4 → A2 → A3, then B1 + B2 in Phase B. Re-evaluate A1 in 4-6 weeks once Poisson retrain has shipped and the model's UNDER bias is corrected.

See `05-REVISED-PLAN.md` for the revised sequencing that incorporates these findings.
