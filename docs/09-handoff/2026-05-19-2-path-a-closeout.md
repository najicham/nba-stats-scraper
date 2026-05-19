# Session Handoff — 2026-05-19-2 — Path A close-out

**Predecessor:** [`2026-05-19-cf-eligibility-and-halt-check.md`](2026-05-19-cf-eligibility-and-halt-check.md)

Short session. Path A from the strategic plan turned out to be already done —
the audit doc was written 5/18 21:21 but never committed, so yesterday's
handoff still listed it as "not started". Re-verified the two load-bearing
claims with fresh queries and committed the doc with a verification footer.

## TL;DR

- **Path A closed.** Audit committed in `11a5bb56`. NBA grading is book-aligned
  — no analog to the MLB MIN_IP issue. Reported 63.85% BB HR (415/650 graded
  picks, 2025-26) is what bettors actually faced.
- **MLB CF eligibility verified working.** Today's 11:30 AM ET fire produced
  2 per-day rows (`edge_floor` 36.4%, `away_over_blocked_policy` 33.3%) — both
  correctly blocking losers, no actionable trending-bad signals. The lowered
  bar is reachable.
- **No open work created.** Path B (binary side-model for the MLB regressor)
  is now the only strategic thread on the queue.

## What changed

### `docs/08-projects/current/nba-grading-audit/AUDIT-2026-05-18.md`

Committed. Added a verification footer with today's re-runs:

- **Whole-season void inventory** (lined OVER/UNDER, voided rows only): 1,835
  total voids across 3 categories. `played_n = 0` and `min_n = 0` across every
  category. The 304 "soft" `dnp_unknown` voids (actual_points=0 but
  minutes_played NULL) all have no recorded minutes — DNP semantics intact.
- **BB-level join**: 415 hits, 235 misses, 44 voids, **0 voided-but-played**,
  0 pushes. 415/650 = 63.85% exactly matches the cited number.

No false voids. No inflation. Every recent model/filter decision against the
63.8% number remains valid.

## Files NOT changed but worth knowing

- `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`
  `detect_dnp_voiding` (376-489) is the audited code. Three trigger conditions:
  `is_dnp=TRUE`, `actual_points=0 AND minutes IN (0, NULL)`, `actual_points
  IS NULL`. All three correspond to "did not play" in book terms.
- `ml/analysis/league_macro.py` BB HR formula (253-262) correctly excludes
  NULL `prediction_correct` from the denominator. Pushes (58 in 2025-26) are
  excluded — matches book refund behavior.

## Open threads (carried forward)

| Thread | Where it lives | When to revisit |
|---|---|---|
| 5/23 halt_state verification | Remote routine `mlb-regressor-halt-check-2026-05-23` (`trig_01QiPjbGA3ztkgK56uq8dLD1`), fires 12:00 UTC 5/23 | 5/23 morning |
| Props-web Tonight-page stale-tab bug | Separate session in `~/code/props-web`, prompt at `2026-05-19-props-web-stale-tab-prompt.md` | When that session reports back |
| Path B: binary side-model for MLB regressor | Spec in `2026-05-18-3` handoff. Trained on 729 graded picks; shadow-only until N≥100 BB-level CF HR confirms signal. Multi-session. | Session 3+ priority — now the only strategic thread |
| Push line resolution (deferred) | Audit "What is NOT in scope". 58 pushes in 2025-26 — could indicate half-point line discrepancies vs book lines. Not actionable until push count grows or a CLV audit is wanted | When push count grows or a CLV-style audit is on the docket |

## Verification queries (rerun in any session)

```bash
# Whole-season void inventory — should show played_n=0, min_n=0 for all
bq query --use_legacy_sql=false 'SELECT is_voided, void_reason, COUNT(*) AS n, COUNTIF(actual_points > 0) AS played_n, COUNTIF(minutes_played > 0) AS min_n FROM `nba-props-platform.nba_predictions.prediction_accuracy` WHERE game_date >= "2025-10-01" AND game_date <= "2026-04-15" AND has_prop_line = TRUE AND recommendation IN ("OVER","UNDER") AND is_voided = TRUE GROUP BY 1, 2 ORDER BY n DESC'

# BB-level: should show 0 voided-but-played
bq query --use_legacy_sql=false 'SELECT b.recommendation, COUNTIF(pa.prediction_correct = TRUE) AS hits, COUNTIF(pa.prediction_correct = FALSE) AS misses, COUNTIF(pa.is_voided) AS voided, COUNTIF(pa.is_voided AND pa.minutes_played > 0) AS voided_but_played FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` b LEFT JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa ON pa.player_lookup = b.player_lookup AND pa.game_id = b.game_id AND pa.recommendation = b.recommendation AND pa.line_value = b.line_value WHERE b.game_date >= "2025-10-01" AND b.game_date <= "2026-04-15" GROUP BY 1'
```

## First message for the next session

```
Read docs/09-handoff/2026-05-19-2-path-a-closeout.md.

State of open threads:
- 5/23 halt_state check fires as remote routine on 5/23 morning. No action until then.
- Props-web Tonight-page stale-tab bug is being investigated in a separate ~/code/props-web session. Integrate findings if they reported back; otherwise leave alone.
- Path A (NBA grading audit) is closed — committed in 11a5bb56. NBA grading is book-aligned, no re-baselining needed.

The only open strategic thread is Path B from the 5/18-3 handoff: a binary side-model on top of the MLB regressor. Spec:
- Inputs: predicted_K, edge, line_level, opponent_k_rate, batter_k_rate, weather, park_factor (whatever pitcher_loader.py serves)
- Target: prediction_correct (binary)
- Model: small XGBoost or logistic regression
- Train on 729 graded MLB picks (2026 season)
- Shadow-only until N≥100 BB-level CF HR confirms signal

Reuse data-prep from scripts/mlb/isotonic_calibration_analysis.py. Multi-session.

Defers and revisit triggers in the 5/18-3 handoff.
```

## Session totals

1 commit. The audit itself was done by the predecessor session; this session
just verified and committed it.
