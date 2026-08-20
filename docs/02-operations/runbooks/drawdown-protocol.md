# Runbook: Drawdown Protocol

**Purpose:** decide, while calm, what you are allowed to do when the system is losing.

**Why this exists:** the 2025-26 season did not fail because of the model. It failed because
Jan 73.8% → Mar 46.7% triggered **ten algorithm versions in a short window**, and the churn
compounded a market problem into a collapse. Supporting evidence from the same period:
`home_under` was demoted on a bad stretch and caused a **12-day pick drought**;
`high_spread_over_would_block` was flipped **three times in 19 days** on N≈14; Session 488 read
counterfactual hit rate backwards and reverted the same session.

Every one of those was a smart, well-intentioned reaction to a losing week. That is the point.
This document exists because judgment under drawdown is systematically worse than judgment
before it, and the only defense is a decision made in advance.

**Read this before touching selection logic during a losing stretch. If you are reading it
*because* you are losing, start at §3.**

---

## 1. The asymmetric change rule (the core of this document)

Drawdown pressure only ever pushes one direction: toward more picks and looser gates. So the
rules are deliberately asymmetric.

| Direction | Examples | Requirement |
|---|---|---|
| **Tightening** | raising an edge floor, adding a filter in observation mode, narrowing a rescue lane, lowering a volume cap | May ship same-day. No wait. |
| **Loosening** | lowering the auto-halt thresholds, lowering the OVER edge floor, promoting a signal out of SHADOW, un-demoting a filter, raising a volume cap, relaxing `real_sc` gates, relaxing zero-tolerance defaults | **N ≥ 30 live graded evidence + 7-day wait between proposal and merge + explicit owner sign-off in the PR body.** |

The 7-day wait is the active ingredient. It is not a review period — it is a cooling-off period.
Most bad changes in this system's history would have been abandoned voluntarily if they had been
required to sit for a week.

**No exceptions during a drawdown.** If a loosening change is genuinely urgent, that is evidence
of a bug, and bugs are handled under §3, not here.

---

## 2. Trigger

The protocol is ACTIVE when any of the following is true:

- 7-day best-bets hit rate **< 48%** at N ≥ 15, or
- **3 consecutive** losing days, or
- a **10-day pick drought** *after* the fleet has unblocked (a drought while models are still
  governance-blocked is expected, not a trigger — see §6).

It deactivates when 7-day HR ≥ 52.4% at N ≥ 15 for 3 consecutive days.

---

## 3. The first 72 hours: integrity work only

**No selection-logic changes for 72 hours.** Not the floors, not the filters, not the weights,
not the halt. The auto-halt is already the panic move, and it executes better than a human at
1 a.m.

Instead, establish whether the losses are real. In order:

1. **Is the machine alive?** Run the canary set. Verify schedulers exist (a *deleted* scheduler
   is invisible to health checks that iterate over existing jobs — this is how weekly retraining
   died silently and cost the 2025-26 season).
2. **Did recent fixes take effect?** Check the effect assertions. Three separate silent no-ops
   were found in a single night in Aug 2026 (`book_count` never set, health multipliers never
   applied, the counterfactual evaluator counting rows). A fix that merged is not a fix that ran.
3. **Is grading closed?** If grading is behind, every downstream number — retraining N, decay
   states, counterfactual HR, signal health — is stale, and you are reacting to a measurement
   artifact.
4. **Is the fleet fresh?** Newest enabled model ≤ 10 days old. Stale models do not fail visibly;
   they become *confidently wrong* — high edge, low hit rate — which reads as good news right up
   until it doesn't.
5. **Is upstream data intact?** Check `failed_processor_queue` for core sources
   (`nbac_injury_report`, `nbac_schedule`, `nbac_gamebook_player_stats`, odds feeds).

If all five are green, the losses are market variance or a genuine edge decay. Variance is not
actionable. Edge decay is handled by retraining and by the auto-halt — both automatic.

---

## 4. Pre-registration (required for any selection change, drawdown or not)

Any commit touching selection logic carries this in the commit body:

```
PREREG:
  Hypothesis:  <what you believe is wrong and why>
  Change:      <the specific edit>
  Expected:    <direction and rough size of the effect>
  Evaluate at: N = <number> graded picks, or <date>, whichever is later
  Rollback if: <the specific observation that would falsify this>
```

**Evaluation happens on the stated date.** Not the next bad morning, not the next good one.
Writing the rollback condition before you can see the outcome is most of the value.

---

## 5. Landmines — verified, and each has burned this system before

- **Counterfactual HR is the hit rate of the picks a filter BLOCKED.** LOW (37-46%) means the
  filter is correctly blocking losers — *keep it*. HIGH (≥55%) means it is blocking winners —
  demote it. This is inverted from intuition and has been misread in production.
- **Do not demote `home_under` on a bad stretch.** It carries most UNDER picks to `real_sc` ≥ 1;
  removing it caused a 12-day drought. The COLD health multiplier was designed to handle this —
  though note that as of Aug 2026 the health multipliers were found never to apply in production,
  so verify before relying on them.
- **Do not flip a filter on N < 30.** `high_spread_over_would_block` was flipped three times in
  19 days on N≈14.
- **Do not "fix" a model's edge compression by decalibrating it.** A well-calibrated model hugs
  consensus and produces fewer high-edge picks. That is correct behavior, not a defect.
- **Do not relax `cap_to_pre_late_season`.** Re-confirmed by review; the counter-finding is
  single-season and non-significant.
- **Do not relax zero-tolerance on default features.** Coverage dropping from ~180 to ~75 players
  is intentional.
- **Never use `--set-env-vars`** — it wipes all environment variables including model paths and
  halt config. Always `--update-env-vars`.

---

## 6. October–November is not a drawdown

Season open is an accumulation period **by design**: roughly 1–3 picks/day, UNDER-dominant, and
possibly **zero picks for weeks** while the edge-based auto-halt holds output until retrained
models are genuinely confident. Governance gates (HR ≥ 53% at edge 3+, N ≥ 15 graded) will block
models until enough new-season data exists — typically 2–3 weeks in.

This is the system working. Impatience with thin output is the documented cause of the last
collapse, so the drought trigger in §2 deliberately does **not** apply until the fleet has
unblocked.

The one thing that must be verified during designed silence: that the silence is *explained*.
Zero picks plus a populated halt state plus healthy upstream predictions is green. Zero picks
plus empty upstream is an incident. Silence you cannot decompose is the dangerous kind.

---

## 7. Escalation

If something genuinely warrants a same-day loosening change — a bug, not a bad week — it is an
incident, not a tuning decision. Write what broke, what the fix is, and what you expect it to do,
then make the change as a single isolated commit with `PREREG:` in the body and no other edits
riding along. One logical change per push; auto-deploy ships every service from HEAD, so an
unrelated edit in the same push goes to production with it.

---

*Created 2026-08-19 from the pre-season audit. Companion: the morning canary set. The evidence
behind each rule is in the Aug 2026 session findings and `docs/09-handoff/`.*
