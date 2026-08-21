# Session Handoff — 2026-08-21 — the auto-halt rebuild, and why the premise changed

**Branch:** `main`. Previous: `2026-08-20-SESSION-3-HANDOFF.md`.
Review that scoped this work: `2026-08-20-TEN-AGENT-REVIEW.md` §2.

---

## TL;DR

Owner decision 1 was "rebuild the edge-collapse auto-halt." Chasing defect (a) far
enough turned up something bigger: **the metric measures fleet composition end to end,
and on any invariant basis the 2026 collapse does not exist.** The February halt is a
composition artifact, the March halt is largely one too, the market never compressed,
and the actual damage was a two-day over-publishing event the metric was
anti-correlated with.

So the halt was **demoted rather than recalibrated**: it is now a degeneracy guard with
thresholds far below anything ever observed, real collapse detection moves to drawdown
(decision 4), and all five mechanical defects are fixed. `halt_state` now actually gates
NBA picks — it never did.

---

## 1. Defect (d), confirmed first as asked

Traced every `return` in `signal_best_bets_exporter.generate_json`. The only gate that
zeroed NBA picks was `regime_ctx['bb_auto_halt_active']`. `halt_envelope()` was called
three times and **every one was a stamp, never a condition.**

- `manual`, `fleet_blocked`, `off_season`, `between_rounds`, `predictions_inactive` and
  `tight_market` rows did **not** suppress NBA picks.
- `edge_collapse` only worked because `regime_context` independently recomputed it.
- MLB has gated on the envelope since 2026-05 (`mlb_best_bets_exporter.py:98`). NBA was
  the outlier; the intended design existed and NBA was never wired to it.

Two follow-on hazards, both now fixed:

- The payload got `halt_active: true` **with `picks` fully populated**, and
  `validate_content` whitelisted exactly those reasons → the content guard was skipped
  on the one payload that was internally contradictory.
- `manual` was deliberately **excluded** from that whitelist, so decision 4's drawdown
  halt would have published a `status="degraded"` sentinel on day one.

No empirical confirmation was possible: `halt_state` was created 2026-05-09, after the
season. All 100 NBA rows have 0 predictions and 0 picks. The code trace is the proof.

---

## 2. Why the market-breaker framing was retired

**2.1 On a fixed model set, February 2026 never collapsed.** Avg daily median edge for
models present in both January and February:

| model | Jan | Feb |
|---|---|---|
| ensemble_v1 | 2.036 | **2.695** |
| similarity_balanced_v1 | 2.189 | **2.719** |
| moving_average | 1.944 | **2.750** |
| catboost_v8 | 2.290 | 2.053 |
| catboost_v9 | 1.222 | 1.190 |
| zone_matchup_v1 | 3.021 | 2.592 |

Three up, two mildly down, one flat. The fleet-wide reading fell 1.9 → 1.3 because
~20 new line-hugging `system_id`s appeared, most alive 1-5 days — one-off experiment
runs writing into `player_prop_predictions`. **They moved the circuit breaker.**

**2.2 On a fixed procedure, no season collapses.** `walkforward_sim_predictions`
(`wf_sim_v12noveg`, leak-free, five seasons), monthly median edge:

```
2021-22  0.745-0.874     2024-25  0.783-0.923
2022-23  0.728-0.919     2025-26  0.799-0.880   Feb .799  Mar .839  Apr .880
2023-24  0.823-0.999
```

Mar-2026 reads **above** 2022-03 (0.738), 2023-01 (0.728) and 2025-01 (0.783). The
quantity does not move. That basis would also sit at ~0.85 forever — permanently below
the old 1.4 bar.

**2.3 The market did not compress.** Vegas MAE (closing line vs actual, model-free, so
leak-immune) by month: 4.64-5.38 across five seasons. Feb-2026 **5.054**, Mar **5.044**,
Apr **5.391**. The tightest recent month was Jan-2026 (4.719) — the best month (73.1%).

**2.4 March was over-publishing, not a drought.** Picks/day ran ~3 in Jan and ~2 in Feb,
then **Mar 4-8 = 9, 13, 1, 10, 16** — the season's highest volume. 03-08 went **2-11**.
The unit curve at -110 peaked 35.90 on 03-05 and fell to 22.63 on 03-08: **13.3 units in
two days**, against a season-long prior max drawdown of 3.64. Throughout, the old metric
read "median 0.97, halt". **Metric and danger were anti-correlated in the only episode
it was calibrated on.**

---

## 3. What was built

`shared/config/edge_halt.py` rewritten; three callers updated; the exporter wired to
`halt_state`.

**Basis (defect a).** Per (day, model) median edge and pct_e3 → median **across models**
→ 7d trailing mean. A model joins only after `MIN_MODEL_HISTORY_DAYS = 7` distinct
prediction-days and on days with ≥ 20 rows. Measured effect on 2025-26: February moves
from 1.40 / 17.0% (halt) to **1.63 / 22.5% (healthy)**, and the first halt day moves
from 2026-02-22 to **2026-03-04** — three days *before* the loss.

**Thresholds — LOOSENED, never tightened.** `0.35` and `0.30%`, placed below every value
observed on either basis:

| basis | days | min edge_med_7d | min pct_e3_7d |
|---|---|---|---|
| production, warm-up applied | 1,663 | 0.871 | 6.72% |
| fixed procedure (`wf_sim_v12noveg`) | 563 | 0.656 | 0.65% |

47% and 54% margin on the binding floor. Zero breaches on either basis in five seasons.
The AND conjunction is retained — `pct_e3_7d` dips below 1.0% on the fixed basis in four
of five seasons, which is exactly why the old 10% bar could not survive a fleet change.

**Release (defect b).** Symmetric: the halt needs BOTH conditions, so release needs only
ONE past a 10% band, for 2 consecutive evaluable days. Plus `MAX_HALT_DAYS = 14`: an
auto-halt self-releases and says so loudly. A **`lifetime_spent` latch** stops it
re-firing the next day on the same stretch — without it the cap accomplishes nothing
(caught by a test). Permanence now requires an operator `halt_overrides` row, and
overrides can only *add* a halt.

**Fail-closed (defect c).** `query_halt_state` returns `{'error': True,
'halt_active': None}` — never a bare `None` that reads as "not halted". New
`resolve_halt_state` is what callers use: fresh computation → most recent `halt_state`
row within 3 days → fail closed as `edge_state_unknown`. All three callers converted.

**halt_state gates NBA picks (defect d).** New Step 0 in `generate_json`, before the
per-model pipelines, so a halted date also skips the expensive prediction scan.
`validate_content` now treats **any** active halt as a legitimate zero rather than a
three-reason whitelist. Shared `_halt_payload` keeps the schema identical whichever gate
fired.

**days_sampled (defect e).** Reports the target-date row, not the last *evaluated* row,
so `halt_state_writer`'s `MIN_DAYS_SAMPLED` guard can finally reject a thin target day.

**Lookback (defect f).** `series_start_for()` = later of (target − 240d) and the season's
Oct 1. Replay is season-scoped on purpose: an April halt must not silently govern
October six months and one fleet later. Carrying a halt across an off-season is now an
operator decision.

**Verified:** 38 tests in `tests/unit/signals/test_edge_halt.py`; 313 signals + 508
publishing + 433 orchestration/shared pass; all 28 pre-commit hooks pass on the changed
files. The new query was run against live BigQuery and reproduces the offline analysis
exactly (2026-03-08: 0.9714 / 8.37%, models_7d 1.71).

---

## 4. Season-open behavior

The warm-up basis is empty for roughly the first 7 game-days, so the guard is dormant
until ~Oct 28 and `halt_state_writer` returns no edge reason. Verified live: target
2026-10-25 → `days_sampled=0`. That is intended — do not run a circuit breaker you
cannot calibrate.

The three enabled models (all trained to 2026-04-02/03, all v12_noveg family) read
median 1.2 / 1.4 / 1.7 and pct_e3 10.1% / 23.6% / 29.1% on their April days. Under the
**old** thresholds the median-of-three would have been exactly 1.4 — sitting on the halt
line with only `pct_e3` holding the season open.

---

## 5. What this hands to decision 4

Drawdown is now the actual circuit breaker, and the dependency the owner flagged is
cleared: `halt_state` gates picks, and `validate_content` no longer punishes a
`manual`-class zero. Two things to decide when implementing it:

1. **Threshold.** The 2025-26 curve gives the scale: max drawdown was 3.64 units for
   five months, then 14.27 in two days. Anything between 5 and 8 units separates the two
   regimes; below 5 will fire on ordinary variance.
2. **A volume-anomaly guard is the cheaper half.** Mar 4-8 ran 3-5× the trailing median
   pick count and would have fired on 2026-03-04 — same day as the rebuilt edge guard,
   but for a defensible reason. ~20 lines against `signal_best_bets_picks`.

## 6. Deploy note

`halt-state-writer` has **no build trigger** — `./bin/deploy-function.sh halt-state-writer`.
Verify by `BUILD_COMMIT == SHORT_SHA`, never by `latestReady == latestCreated`. Nothing
was deployed in this session; the batch is committed and awaiting the owner's go.

---

## 7. Seven-agent review — what it changed

Seven independent reviewers (fresh context) covered statistical validity, threshold
red-team, state-machine logic, SQL, the halt-gate blast radius, caller integration, and
operational readiness. **One BLOCKER and nine MAJORs were found and fixed.** The
headline claims in §2 survived re-derivation; three of their supporting numbers did not
and are corrected in the module docstring.

### Fixed

| Sev | Finding | Fix |
|---|---|---|
| BLOCKER | Reason string crashed on `f"{None:.3f}"` when a halt ran into a 7+ day dataless stretch — and `evaluate_halt_state` ran OUTSIDE `query_halt_state`'s try, so the crash escaped the fail-closed chain | None-safe formatting; evaluation moved inside the try |
| MAJOR | Warm-up keyed on train-stamped `system_id`, which the weekly retrainer rotates faster than the quarantine clears. **80 of 102 ids never reached warm; the currently-enabled fleet had `warm_days = 0`; the guard averaged 1.7 warm models in March and 0.3 in April** | Keyed on model FAMILY. March 1.7 → **7.4** warm models, April 0.3 → 2.9; February still 1.17 / 12.4%, nowhere near firing |
| MAJOR | Docstring claimed coverage of stale line feeds and constant-serving models. **Both produce LARGE edges — this guard reads them as healthier.** | Docstring corrected; the large-edge gap is now stated explicitly as OPEN and delegated to decision 4's volume guard |
| MAJOR | `_nba_edge_degeneracy`'s `days_sampled` gate swallowed carried-forward halts (fallbacks inherit `days_sampled=0`), so the writer would persist `halt_active=False` — overwriting a real halt with "healthy" in the row everything else reads | Fallback verdict handled before the thin-day gate |
| MAJOR | Fixing the above alone creates a permanent latch: the writer re-writes `halt_state` from its own fallback output, so rows are never "stale" and `MAX_HALT_DAYS` never applies (it lives in `evaluate_halt_state`, which the fallback never reaches) | Fallback now carries `halt_since` and enforces the lifetime itself; the fallback query excludes fallback-derived rows so the writer cannot launder stale into fresh |
| MAJOR | `weekly_retrain` loosened **model governance gates** whenever `halt_active` was true — including on fail-closed. "BigQuery was down" is exactly when gates should tighten | Gated on `halt_source == 'computed'` |
| MAJOR | `halt_envelope` had no carry-forward: one missed write = zero picks. `halt_state` has a real 4-day gap (2026-08-16..19), never backfilled | 3-day carry-forward before fail-closed, matching `resolve_halt_state` |
| MAJOR | `unknown_state` zero-publishes were silent — the blanket `validate_content` loosening lost the CRITICAL log and `degraded` sentinel, and the Step-0 return bypasses the started-games re-export guard, so a gap-date re-export would overwrite a good file with zeros | `unknown_state` excluded from the halt excusal; metric emitted on every halt suppression |
| MAJOR | A mid-day halt left GCS zeroed and BQ rows active; `post_grading_export` then **re-added every active pick into the halted JSON next morning**, silently undoing the suppression in the public record | Re-add skipped when the payload says `halt_active` |
| MAJOR | `halt-state-stale` **could not fire**: a GT-36h threshold on a metric that only exists when a write succeeds. A dead writer emits nothing, so there is no series to evaluate — and a dead writer now means zero picks | Rewritten absence-based, Critical, 30h, with backfill instructions |
| MAJOR | **Opening night would have been zeroed.** The writer runs 5 AM ET, the workflow starts ~6 AM, so on 2026-10-20 `_predictions_inactive` sees zero predictions and writes a halt that stands all day. Same trap after any 3+ day league gap | Requires at least one PAST day that actually had games |
| MAJOR (pre-existing) | `all.json`'s guard returns early on `off_season`, so **Floor 2 — the history-collapse check its own docstring exists for — has been off every day since May** | A halt now excuses Floor 1 only; Floor 2 runs unconditionally |

Plus minors: lifetime now ages through thin days; `lifetime_expired` clears on recovery;
re-arm requires the same streak a normal release does; `RELEASE_BAND < 1.0` clamped;
`history` CTE moved to `ROW_NUMBER` (verified 0 mismatches); `APPROX_QUANTILES` even-n
lower-middle bias and the ~20% duplicate-row basis documented rather than silently
"fixed"; dormancy recorded in `halt_metrics`; `halt_active` metric emitted.

### Corrections to §2's supporting numbers

- `catboost_v8` does not reproduce as "down" under any recipe tried — flat to slightly up.
- `ensemble_v1_1` spans both months and fell **35%**; it was missing from the table.
  Corrected tally ≈ 6 up, 3 down, 1 flat. Conclusion unchanged.
- Feb-only `system_id`s: **42**, not "~20" (30 alive ≤5 days).
- "The market did not compress" → **"never left its historical range."** 7d trailing MAE
  did touch five-season lows (~4.48 on 02-20, 4.68-4.79 around Mar 7-8). Not a regime
  break, and the tightest stretch preceded rather than caused the loss.
- The `wf_sim` basis starts 56 days into each season, so it is a Dec-Apr claim only.

### Still open — owner decisions, not defects

1. **Large-edge degeneracy is unguarded.** A frozen line feed or a constant-serving model
   is caught by nothing that halts: `EDGE_ABS_MAX = 20` only rejects absurd rows, the
   >95% same-direction block misses a constant near the line median, the coordinator's
   skew check only alerts, and both canaries are paused. No threshold on *this* metric is
   defensible for it. Recommend it ride with decision 4's volume-anomaly guard.
2. **`SLACK_WEBHOOK_URL_ALERTS` is unset on the deployed `halt-state-writer`**, so
   `maybe_alert_on_change` — the only notification that a halt fired or released — is a
   no-op. Set it at deploy time with `--update-env-vars` (never `--set-env-vars`).
3. **The Step-0 halt payload omits `regime_context`**, which every previous halt file
   carried. Run the `halt-mode-frontend-impact.md` checklist against props-web.

## 8. Deploy order (nothing is deployed)

1. `git push origin main` → auto-deploys **`phase6-export`** (the Step-0 gate),
   **`post-grading-export`**, **`weekly-retrain`**, plus ~26 `shared/**` triggers.
2. **Manual, required:** `./bin/deploy-function.sh halt-state-writer` — no build trigger.
   It is currently serving `2b190789`, i.e. the pre-rebuild fail-open logic.
3. Set `SLACK_WEBHOOK_URL_ALERTS` on the writer in the same deploy.
4. Verify all four by `BUILD_COMMIT == SHORT_SHA`, never by revision equality.
5. Apply the rewritten `halt-state-stale` policy.

Old-writer + new-exporter coexistence is safe today (the row says `off_season` either
way), but do steps 1 and 2 in the same session.

*Session 2026-08-21.*
