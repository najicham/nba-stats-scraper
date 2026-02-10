Read docs/09-handoff/2026-02-10-SESSION-181-HANDOFF.md and work through priorities:

- P0: **Commit and push Session 181 changes** (segmented HR breakdowns in quick_retrain.py). Then **check Feb 10 predictions** — re-trigger if prop lines now exist, grade once games complete, backfill challengers, run comparison.

- P1: **Re-run C1_CHAOS and C4_MATCHUP_ONLY with extended eval** (Feb 1-15+) once 2 weeks of data available. The eval now includes **segmented hit rates** — look at "SEGMENTED HIT RATES" section for segments with HR >= 58% and N >= 20+. Key question: are C4's 60% HR and C1's 58.3% HR concentrated in specific segments (UNDER-only, role players, specific line ranges)? Commands in handoff P1.

- P2: **Investigate systematic OVER weakness.** All 34 experiments had OVER HR below breakeven. Use segmented breakdowns + query prediction_accuracy OVER vs UNDER split to determine if model-specific or systemic.

- P3: **Monitor promotion decision** (~Feb 17-20). Jan 31 tuned leads at 55.1% HR with +24pp disagreement signal vs champion. Champion decaying at 49.5%.

Session 181 context:
- Added `compute_segmented_hit_rates()` to quick_retrain.py — breaks down HR by tier, direction, tier x direction, edge bucket, line range
- Session 180 ran 34 experiments (docs/09-handoff/2026-02-09-SESSION-180-HANDOFF.md) — NONE passed all gates
- Session 180 ops (docs/09-handoff/2026-02-10-SESSION-180-HANDOFF.md) — graded Feb 9, 4-way comparison: tuned 55.1%, defaults 54.2%, champion 49.5%
- Segmented results stored in results_json.segmented_hit_rates — queryable in BigQuery

Use agents in parallel where possible.
