# Session Handoff — 2026-08-19 (entry point for the next session)

**Branch:** `main`, pushed and clean. **System:** off-season, halted. **Opener: Tue 20 Oct 2026**
(62 days out at time of writing).

**Read this, then `docs/08-projects/current/2026-27-season-prep/00-GAMEPLAN.md`.** The game plan
is the substance; this doc is state, corrections, and what to do first.

---

## TL;DR

A pre-season audit (17 subagents + direct verification) found two defects that would each have
broken the season on their own, fixed five others, and narrowed four research questions. Nothing
is blocked on analysis any more — **it is blocked on five owner decisions**, listed in §5.

**The single most important finding: the edge-based auto-halt would have published zero picks all
of last season.** It is a bug, not a tuning preference, and it must be resolved before 20 Oct.

---

## 1. What shipped (pushed to main)

| Commit | What |
|---|---|
| `564ff4a0` | **real_sc integrity** — 16 retired signals removed from `real_sc` (32 → 16 contributors, drift now 0); 3 inverted negative filters folded into `NEGATIVE_SEMANTIC_SIGNALS`; UNDER ranking now excludes SHADOW (mirroring OVER); `book_count` populated from BettingPros; `validate_signal_registry_consistency()` + 15 regression tests |
| `d84f5eb4` | **`shared/config/breakeven.py`** — break-even as a function of execution (53.5 / 52.4 / 51.5). Value unchanged at 52.4; pure refactor |
| `f5f5d0b1` | **CF dedup** — the counterfactual evaluator counted rows, not distinct picks (1.43× inflation, up to 2.4× per filter, moving CF HR by ±12pp) |
| `2682e41a` | **Season date Oct 21 → Oct 20** (the "6 vendored copies" are symlinks — one edit) and the **CDN schedule scraper** repaired |
| `ae015751` | `docs/02-operations/runbooks/drawdown-protocol.md` |
| `27e7b7df` | `docs/02-operations/runbooks/morning-canary-set.md` |

**Infrastructure changes (verified in place):**
- **29 MLB schedulers paused**, 2 kept (`mlb-schedule-daily`, `mlb-box-scores-daily`) for BQ data
  continuity. Note: `/mlb` *site pages* will go stale — the exporters are paused. That was the
  accepted trade.
- **4 NBA REB/AST data-clock jobs resumed** (they were PAUSED, contradicting the runbook's claim
  that they were intentionally enabled).
- **2025-26 season snapshotted** → `gs://nba-props-platform-api/v1/seasons/2025-26/` (7 objects,
  3.07 MiB, record verified 105-70). This was time-critical: on **1 Nov** five publishing sites
  flip a `month >= 11` boundary and overwrite the season aggregates irreversibly.
- **2026-27 schedule loaded** — 1,207 games, 2026-10-20 → 2027-04-11, 160 game days.

**props-web: PR #4 open** (`preseason/2026-27-readiness`, 4 commits). That repo has branch
protection with 2 required checks. The e2e suite failed on the first push and was fixed — see §4.

---

## 2. The two season-breaking defects

### 2.1 Auto-halt zeroes the season — NOT YET FIXED (owner decision)

Replay of `regime_context.py`'s exact halt query over 2025-26: **fires 136/148 days (91.9%)**.
Peak 7d avg edge all season 4.41 (threshold <5.0); peak edge-5+ rate 19.5% (threshold <50%).
Neither bar cleared once. Cause: no `system_id` filter, so it averages over every model's every
prediction (typical edge ~2.5) while the constants were set from best-bets-level edges.

**Second bug: un-halt is unreachable** (needs 5.0 / 50%; maxima are 4.41 / 19.5%) — once fired it
never releases.

Proposed replacements, replayed over 676 healthy days across 5 seasons vs the 48-day collapse:
`avg_edge < 2.0 AND pct_e5 < 6%` (0/676 false positives, 48/48 coverage, first fire 2026-02-21),
or the preferred median-per-player-game variant `edge_med < 1.4 AND pct_e3 < 10%`, plus hysteresis
(`edge_med >= 1.6` × 3 days) for release. Full detail in the game plan §2.1.

### 2.2 Health multipliers have never applied in production — NOT YET FIXED

The exporter queries `signal_health_daily WHERE game_date = @target_date` at pick time, but the row
for day D is computed **D+1** (measured: +41h off-season; January 2026 rows weren't written until
22 February). The lookup returns empty and `_health_multiplier` fails open to `1.0`. So HOT ×1.2,
COLD ×0.5 and model-dependent COLD ×0.0 have **never fired**, despite being documented as active in
CLAUDE.md and memory. Do not assume they work when reasoning about signal weighting.

---

## 3. Corrections — several first reports were wrong

**This matters more than the findings themselves.** Roughly three of four headline claims shrank or
inverted under verification. Treat any subagent conclusion as provisional until its load-bearing
number is independently reproduced.

| First reported | Verified reality |
|---|---|
| CF row-counting inflates N ~10× | **1.43×** overall (up to 2.4× per filter) |
| Worker UNDER filters lay dormant then "awakened" in Feb | They were **added 3-11 Feb 2026** during the panic week. They never existed before — repo history only starts 2025-05-31 |
| Those filters blocked 60-74% pools | Blocked pools ran **47-52%**. The 60-74% figures were the *archetype* over Nov-Jan, before the filters existed |
| OVER against-movers are poison (35.7%) | **Does not replicate** — 50-53% at N=26-64 |
| Drop rule works at T-30, useless at T-3h | **No cliff.** Shallow monotone curve; most value earned by T-120-T-60 |
| Bet UNDER early, wait on OVER | **Refuted.** UNDER is not hurt by waiting |
| Fleet-diversity collapse killed `combo_3way`/`book_disagreement` | **Falsified in-repo.** `combo_3way` is single-model; `book_disagreement` is cross-*book* |
| Health multipliers were calibrated on leakage | No leak — the mechanism **never runs** |
| `mlb-snapshot-daily` runs year-round | It is month-gated `3-10` like the rest |

---

## 4. props-web PR #4 — one real bug caught by CI

The season-date change seeds the Tonight page to opening night. That is a *future* date with no
`tonight/{date}.json`, so the fetch 404s and the page rendered `InlineErrorState` — a red "Failed
to load data" — for the entire pre-season. The e2e `sport-render` spec caught it.

Fixed in `38edbc7` with an explicit pre-season branch ("Season starts October 20", derived from
`SPORT_META` so it cannot drift). **Verify CI is green before merging.**

Known follow-ups the frontend agent flagged and did not do: the `ultra_record` pill in `RecordHero`
still recomputes Ultra client-side, bypassing the backend N≥50/HR≥80% gate; `checkMlbLeaderboard`
is now dead code in the cron path; `BottomNav` says "Record" not "Track Record" for width reasons.

---

## 5. Owner decisions — everything below is blocked on these

1. **Auto-halt variant + thresholds** (§2.1). Without it the season publishes nothing.
2. **Where you actually bet.** Sets break-even at 53.5% (one book) / 52.4% (four majors) / 51.5%
   (ten). `DEFAULT_BREAKEVEN_HR` is 52.4 pending this. It gates model governance, signal promotion,
   filter demotion, and decay alerts — and **production has been using 52.4 while the discovery
   scripts use 53.5**, so things in that band were scored profitable by one and unprofitable by the
   other.
3. **REB/AST backfill go/no-go.** Validated and ready; ~37,000 calls, ~14h both markets.
4. **Drawdown tolerance** — the number that triggers the drawdown protocol.
5. **Backend deploy gate** — test gate only, or full branch protection?

---

## 6. Recommended first moves

1. **Read the game plan**, then decide §5 items 1 and 2. Everything else sequences behind them.
2. **Build `scripts/nba_offseason_restore_jobs.sh`** — it is the critical path and does not exist.
   58 jobs; `weekly-retrain-trigger`, `execute-workflows` and `decay-detection-daily` are all
   verified absent right now. Spec is at the bottom of the restore manifest. Do not hand-restore.
3. **Apply the auto-halt fix** once the variant is chosen (bug-fix, so freeze-exempt).
4. **Remove the three panic-era worker filters**; move `star_under_bias_suspect` into the pipeline.
5. **Merge props-web PR #4** once CI is green.

---

## 7. Environment notes

- `gcloud scheduler jobs list` and `gcloud builds triggers list` **worked** on this host (they have
  hung on others). Probe before assuming. Always `--project=nba-props-platform`.
- The `bq` CLI hangs — use `.venv/bin/python3` + `google.cloud.bigquery`.
- `signal_best_bets_picks` **requires a partition filter** on `game_date`.
- `signal_health_daily` uses `computed_at`, not `created_at`.
- Two Cloud Build jobs report `TIMEOUT` on a 600s limit while the CF deploy completes server-side
  seconds later (`transition-monitor`, `nba-grading-alerts`). Not a real failure; raise the timeout
  so builds aren't permanently red.
- A push touching `shared/config/**` fans out to ~20 builds, including two MLB services.
- **Billing:** the project was moved to a **new** billing account (`01E7DE-AB13E8-281CB2`) after a
  4-day delinquency outage. It has **no budget alert configured** — worth adding. After the fix,
  Cloud Run 429'd project-wide for ~30 min while quota propagated; that resolved on its own.

---

## 8. Query traps that produced wrong answers this session

- `prediction_accuracy` carries many `system_id`s — **de-duplicate to one row per player-game
  before any aggregate.** Skipping this produced a completely spurious no-vig result.
- Pooling odds snapshots across a day is **time travel** — it fabricated a +1.28-point line-shopping
  gain that does not exist at any real decision moment. Use one simultaneous snapshot per decision.
- Unbounded American odds let alt-line quotes (up to +9900) drive `MAX()` and produce fake ROI.
  Bound to roughly [-250, +250].
- `best_bets_filtered_picks` rows are duplicated per model — dedupe on
  `(game_date, player_lookup, game_id, filter_reason, recommendation, line_value)`.
- Prior-season `prediction_accuracy` rows are **leak-era backfills and inflated** (they show OVER
  edge-8+ at ~86%, contradicting the clean walk-forward's ~39%). Prefer `player_prop_predictions`
  or the walk-forward cache for cross-season claims.
- The **element-median of half-point book lines quantizes to whole points** — use the mean for
  line-movement work or a 0.5 threshold silently breaks.

---

*Session 2026-08-19. Game plan: `docs/08-projects/current/2026-27-season-prep/00-GAMEPLAN.md`.
Runbooks: `drawdown-protocol.md`, `morning-canary-set.md`.*
