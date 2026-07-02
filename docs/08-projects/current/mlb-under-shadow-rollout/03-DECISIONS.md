# Decisions log — MLB UNDER shadow rollout

**Decision date:** 2026-05-12
**Approver:** user (nchammas@gmail.com)
**Context:** `00-OVERVIEW.md`, `02-AGENT-FINDINGS.md`

This file records the decisions made on this project so future sessions can pick up without re-litigating settled questions.

---

## D1 — Path: (a) Shadow rollout with pre-work

**Options considered:**
- (a) Ship UNDER in shadow mode for 45 days, with sequenced pre-work fixing dead signal pipeline first
- (a-lite) Ship shadow today with no pre-work
- (b) Keep UNDER disabled indefinitely, document rationale
- (c) Ship UNDER live with specific filters/thresholds

**Decision:** **(a) — shadow rollout with pre-work.**

**Rationale:**
- (c) ruled out by Agent 1 — no filtered UNDER subset with N >= 100 clears 56% HR. Live UNDER is currently 40.9% HR in May and trending down. Shipping live would lose money immediately.
- (a-lite) ruled out by Agent 4 — `UNDER_MIN_SIGNALS=3` is structurally unreachable today. Shadow without pre-work produces zero useful data.
- (b) too defeatist. Agent 3 showed the OVER bias is structurally fixable (RMSE → Quantile loss). Agent 4 showed half the UNDER signal pipeline is dead code, never tested. We don't know what a working UNDER pipeline would do until we ship one.

**Cost:** ~3-4 working days of pre-work, then 45 days passive shadow.

---

## D2 — Volume: shared 5/day quota

**Options considered:**
- Shared 5/day quota (UNDER competes with OVER for slots)
- Separate UNDER quota (e.g. cap UNDER at 2/day even when live)
- Decide at live-flip, not at shadow

**Decision:** **Shared 5/day quota.**

**Rationale:**
- Matches current code (`MAX_PICKS_PER_DAY=5` is a single shared bucket — `best_bets_exporter.py:82`, applied to `over_picks + under_picks` combined at line 589)
- Frontend density stays the same (~5 picks/day total)
- Simpler — less code to write, less to reason about during graduation
- Shadow picks don't publish anyway, so quota decisions only bite at live-flip time

**Note on shadow:** Per Phase 1 Step 5, shadow UNDER picks bypass `MAX_PICKS_PER_DAY` truncation to log every qualified pick. This is for ranking discovery — does not affect production quota.

---

## D3 — UNDER ranking: redesign from scratch using shadow data

**Options considered:**
- Match NBA's `UNDER_SIGNAL_WEIGHTS` pattern (current code)
- Redesign from scratch

**Decision:** **Redesign from scratch using shadow data.**

**Rationale:**
- Current `UNDER_SIGNAL_WEIGHTS` in `best_bets_exporter.py:122-129` is untested in MLB live (UNDER has been disabled since launch)
- Agent 4 found 2 of 5 weighted entries are dead (`pitch_count_limit_under`, `weather_cold_under`)
- Even after Phase 0 fixes, the empirical weights for MLB UNDER are unknown — borrowed from NBA without validation
- 45 days of shadow data gives us the basis for an evidence-driven ranker

**Approach (Phase 1 Step 5):**
- Shadow mode does NOT rank — writes all qualified UNDER picks (skips `MAX_PICKS_PER_DAY` truncation, sets `rank=NULL`)
- Captures structured fields (archetype tags, signal confidences, edge buckets) for post-hoc analysis
- Day 30 deliverable: `scripts/mlb/discovery/under_ranking_scanner.py` — modeled after NBA's `feature_scanner.py`. Runs on shadow data, finds the empirical ranking that maximizes HR within each daily slate.
- Production ranker built from scanner output, NOT borrowed from NBA blindly.

**Placeholder:** `05-RANKING-REDESIGN.md` (to be populated after 30d shadow data).

---

## D4 — Quantile-loss retrain: deferred

**Options considered:**
- Retrain with Quantile loss BEFORE shadow (Agent 3's recommendation)
- Retrain AFTER 30 days of shadow data
- Don't retrain

**Decision:** **Defer until 30 days of shadow data exists.**

**Rationale (implicit — not explicitly asked but implied by the user's (a) choice):**
- Model swap has its own governance gates (training pipeline, walk-forward, validation, deployment)
- Doing it AFTER shadow lets us A/B: RMSE-shadow-UNDER vs Quantile-shadow-UNDER
- Phase 3 owns this work. Not in Phase 0 or Phase 1 scope.

---

## D5 — Shadow table: reuse blacklist_shadow_picks (Agent 6)

**Options considered:**
- New `mlb_predictions.shadow_under_picks` table (Agent 2 recommendation)
- Reuse `mlb_predictions.blacklist_shadow_picks` with `shadow_reason` discriminator (Agent 6 recommendation)

**Decision (in synthesis, not user-asked):** **Reuse `blacklist_shadow_picks`.**

**Rationale:**
- Schema already fits (recommendation, edge, signal_tags, real_signal_count, would_be_selected, prediction_correct, is_voided)
- DELETE-by-date dedup pattern already implemented
- Less BQ surface area, simpler grading
- `shadow_reason` discriminator (`'blacklist'` vs `'under_shadow'` vs `'under_shadow_backfill'`) keeps queries clean
- Caveat: scoped DELETE in `_write_shadow_under_picks` MUST include `shadow_reason='under_shadow'` predicate so it doesn't trample blacklist rows

**Open to revisit at graduation** — if shadow UNDER picks structurally diverge from blacklist shadow analysis patterns, can split tables then.

---

## D6 — Walk-forward auditability requirement

**Surfaced by Agent 1 — not explicitly approved but de facto adopted in plan:**

> Future decisions about MLB UNDER (or any pick direction) require walk-forward output to be written to BigQuery. JSON-only outputs in `results/` are not auditable.

**Implementation:** Add to Phase 3 work scope — modify `scripts/mlb/training/walk_forward_simulation.py` to write results to a new `mlb_predictions.walk_forward_results` BQ table. Detailed design: `06-WALK-FORWARD-AUDITABILITY.md`.

---

## Questions deferred to graduation (Day 47)

| Question | When to revisit |
|---|---|
| Should `UNDER_MIN_SIGNALS` be tightened to 4 once 5 signals fire reliably? | Graduation analysis |
| Does NBA's `feature_scanner.py` work as-is on MLB shadow data or need adaptation? | Day 30 ranker discovery |
| Should Quantile-loss retrain happen before live-flip or after first month live? | Day 47 if graduation gate passes |
| Add `pitcher_blacklist_under` symmetric to OVER blacklist? | After 60+ days of live UNDER |
